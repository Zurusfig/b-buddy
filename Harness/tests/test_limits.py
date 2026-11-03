"""Acceptance tests for P6 (limits), P7 (error text), P8 (logs) and P9 (one question at a time).

    python -m unittest tests.test_limits -v
"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(HARNESS / "budget_coach"))

import agent  # noqa: E402
import coach_server  # noqa: E402
from harness.logger import JsonlLogger  # noqa: E402

Q = "What is my food budget?"


def tool_reply(name="get_budget", args=None):
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": name, "arguments": json.dumps(args or {"category": "food"})}}]},
        "finish_reason": "tool_calls"}], "usage": {"completion_tokens": 3}}


def text_reply(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 3}}


def http(status, body="secret-key-hash-123"):
    r = mock.Mock()
    r.status_code, r.text = status, body
    return r


class LimitTests(unittest.TestCase):  # P6
    def test_a_model_that_keeps_calling_tools_stops_at_four_calls_and_still_answers(self):
        chat = mock.Mock(side_effect=lambda *a, **k: tool_reply())
        with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            r = agent.run(Q, agent.SMALL_MODEL, False)
        self.assertEqual((r["model_calls"], chat.call_count), (4, 4))
        self.assertIn("loop", r["flags"])
        self.assertTrue(r["answer"].strip(), "an empty reply is never shown")

    def test_a_run_past_its_deadline_stops_starting_model_calls(self):
        chat = mock.Mock(side_effect=lambda *a, **k: tool_reply())
        with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"), \
                mock.patch.object(agent, "DEADLINE_S", -1):
            r = agent.run(Q, agent.SMALL_MODEL, False)
        self.assertEqual(chat.call_count, 0)
        self.assertIn("deadline", r["flags"])
        self.assertTrue(r["answer"].strip())

    def test_a_slow_question_is_flagged_but_not_escalated_by_that_flag(self):
        cls = {"intent": "trend", "ok": True, "latency": 0.0, "error": None}
        chat = mock.Mock(side_effect=[tool_reply(), text_reply("Your food budget is 4,500.")])
        with mock.patch.object(agent.router, "classify", return_value=cls), mock.patch.object(agent, "_chat", chat), \
                mock.patch.object(agent, "LOG"), mock.patch.object(agent, "SLOW_S", -1):
            r = agent.answer_routed(Q)
        self.assertIn("slow", r["flags"])
        self.assertEqual(r["route"], "small")
        self.assertNotIn("slow", agent.AUTO_TRIGGERS)

    def test_a_small_run_that_used_up_its_time_is_not_rerun_on_the_large_model(self):
        cls = {"intent": "trend", "ok": True, "latency": 0.0, "error": None}
        small = {"answer": "x", "calls": [], "flags": ["no_tool"], "model_calls": 1, "tokens": 1, "latency": 95.0,
                 "think": False, "model": "m", "validator_retries": 0, "error": None}
        fake = mock.Mock(return_value=small)
        with mock.patch.object(agent.router, "classify", return_value=cls), mock.patch.object(agent, "run", fake), \
                mock.patch.object(agent, "LOG"):
            r = agent.answer_routed(Q)
        self.assertEqual((fake.call_count, r["route"]), (1, "small"))

    def test_the_limits_are_the_documented_ones(self):
        self.assertEqual((agent.MAX_MODEL_CALLS, agent.DEADLINE_S, agent.TIMEOUT_S, agent.SLOW_S), (4, 90, 120, 30))


class ErrorTextTests(unittest.TestCase):  # P7
    def code_for(self, **post):
        with mock.patch.object(agent.requests, "post", **post), mock.patch.object(agent, "LOG"):
            r = agent.run(Q, agent.BIG_MODEL, True, "k")
        return r

    def test_gateway_errors_become_short_codes_and_never_echo_the_response_body(self):
        for status, code in ((401, "gateway_auth"), (403, "gateway_auth"), (429, "gateway_busy"),
                             (502, "gateway_down"), (400, "gateway_error")):
            r = self.code_for(return_value=http(status))
            self.assertTrue(r["answer"].startswith(f"[error] {code}:"), (status, r["answer"]))
            self.assertNotIn("secret-key-hash-123", r["answer"])
            self.assertEqual((r["error"], "model_error" in r["flags"]), (code, True))

    def test_no_connection_and_timeouts_have_their_own_codes(self):
        r = self.code_for(side_effect=requests.ConnectionError("HTTPSConnectionPool(host='llm.nattee.net') key=abc"))
        self.assertEqual(r["error"], "gateway_down")
        self.assertNotIn("nattee", r["answer"])
        r = self.code_for(side_effect=requests.Timeout("read timed out"))
        self.assertEqual(r["error"], "timeout")

    def test_a_stopped_ollama_is_local_down(self):
        with mock.patch.object(agent.requests, "post", side_effect=requests.ConnectionError("refused")), \
                mock.patch.object(agent, "LOG"):
            r = agent.run(Q, agent.SMALL_MODEL, False)
        self.assertEqual(r["error"], "local_down")
        self.assertIn("Ollama", r["answer"])

    def test_an_unexpected_bug_gives_a_generic_line_not_the_exception_text(self):
        with mock.patch.object(agent, "_chat", side_effect=ValueError("password=hunter2")), mock.patch.object(agent, "LOG"):
            r = agent.run(Q, agent.SMALL_MODEL, False)
        self.assertEqual(r["error"], "internal")
        self.assertNotIn("hunter2", r["answer"])

    def test_a_failed_small_model_falls_back_to_the_large_model(self):
        cls = {"intent": "trend", "ok": True, "latency": 0.0, "error": None}
        seq = [LLMErr("local_down"), tool_reply(), text_reply("Your food budget is 4,500.")]
        chat = mock.Mock(side_effect=seq)
        with mock.patch.object(agent.router, "classify", return_value=cls), mock.patch.object(agent, "_chat", chat), \
                mock.patch.object(agent, "LOG"):
            r = agent.answer_routed(Q)
        self.assertEqual((r["route"], r["escalated_by"]), ("small->large", ["model_error"]))
        self.assertNotIn("[error]", r["answer"])


def LLMErr(code):
    return agent.LLMError(code)


class LogTests(unittest.TestCase):  # P8
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "calls.jsonl"
        self.patch = mock.patch.object(agent, "LOG", agent._RunLog(JsonlLogger(self.path)))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()

    def lines(self):
        return [json.loads(x) for x in self.path.read_text("utf-8").splitlines()]

    def ask(self, question, replies, intent="trend"):
        cls = {"intent": intent, "ok": True, "latency": 0.4, "error": None}
        with mock.patch.object(agent.router, "classify", return_value=cls), \
                mock.patch.object(agent, "_chat_once", mock.Mock(side_effect=replies)):
            return agent.answer_routed(question)

    def test_every_line_of_one_question_shares_its_run_id_and_two_questions_differ(self):
        a = self.ask(Q, [tool_reply(), text_reply("Your food budget is 4,500.")])
        b = self.ask(Q, [tool_reply(), text_reply("Your food budget is 4,500.")])
        rows = self.lines()
        self.assertTrue(all(r["run_id"] for r in rows))
        mine = [r for r in rows if r["run_id"] == a["run_id"]]
        self.assertEqual({r["event"] for r in mine}, {"coach_tool_call", "coach_question"})
        self.assertNotEqual(a["run_id"], b["run_id"])

    def test_the_question_line_has_the_reply_text_the_classifier_time_and_the_cost(self):
        r = self.ask(Q, [tool_reply(), text_reply("Your food budget is 4,500.")])
        q = next(x for x in self.lines() if x["event"] == "coach_question")
        self.assertEqual(q["answer"], r["answer"])
        self.assertEqual((q["classifier_s"], q["model_calls"], q["route"]), (0.4, 2, "small"))

    def test_numbers_the_validator_rejected_are_logged(self):
        self.ask(Q, [tool_reply(), text_reply("Your food budget is 9,999."), text_reply("Your food budget is 4,500.")])
        v = [x for x in self.lines() if x["event"] == "coach_validator"]
        self.assertEqual(len(v), 1)
        self.assertIn(9999.0, v[0]["rejected"])

    def test_a_model_error_is_logged_as_a_code_without_the_body(self):
        with mock.patch.object(agent.requests, "post", return_value=http(401)):
            agent.run(Q, agent.BIG_MODEL, True, "k")
        e = [x for x in self.lines() if x["event"] == "coach_error"]
        self.assertEqual(e[0]["code"], "gateway_auth")
        self.assertNotIn("secret-key-hash-123", self.path.read_text("utf-8"))

    def test_the_http_line_carries_the_same_run_id_as_the_question(self):
        r = self.ask(Q, [tool_reply(), text_reply("Your food budget is 4,500.")])
        r.setdefault("model", agent.SMALL_MODEL)
        with mock.patch.object(coach_server, "ollama_ready", return_value=(True, "")):  # CI has no Ollama
            status, _ = coach_server.ask(1, Q, data_factory=lambda uid: mock.Mock(user_id=uid),
                                         answerer=lambda q, d, log_extra=None: r)
        h = [x for x in self.lines() if x["event"] == "coach_http"]
        self.assertEqual((status, h[-1]["run_id"]), (200, r["run_id"]))


class QueueTests(unittest.TestCase):  # P9
    def setUp(self):
        self.ready = mock.patch.object(coach_server, "ollama_ready", return_value=(True, ""))
        self.ready.start()
        self.log = mock.patch.object(agent, "LOG")
        self.log.start()

    def tearDown(self):
        self.ready.stop()
        self.log.stop()

    @staticmethod
    def reply():
        return {"answer": "ok", "route": "small", "calls": [], "flags": [], "latency": 0.1, "model": "m:1"}

    def ask(self, answerer):
        return coach_server.ask(1, "q", data_factory=lambda uid: mock.Mock(user_id=uid), answerer=answerer)

    def test_questions_run_one_at_a_time_and_beyond_the_queue_the_app_is_told_busy_at_once(self):
        gate, started = threading.Event(), threading.Event()

        def slow(q, d, log_extra=None):
            started.set()
            gate.wait(5)
            return self.reply()

        out = {}
        with mock.patch.object(coach_server, "QUEUE_MAX", 1):
            t1 = threading.Thread(target=lambda: out.__setitem__("first", self.ask(slow)))
            t1.start()
            started.wait(5)
            t2 = threading.Thread(target=lambda: out.__setitem__("second", self.ask(lambda q, d, log_extra=None: self.reply())))
            t2.start()
            for _ in range(100):  # wait until the second question is queued
                if coach_server.health()["queued"] == 1:
                    break
                time.sleep(0.01)
            t0 = time.perf_counter()
            third = self.ask(lambda q, d, log_extra=None: self.reply())
            self.assertLess(time.perf_counter() - t0, 1.0, "busy is answered immediately")
            self.assertEqual(third, (429, {"error": "busy"}))
            gate.set()
            t1.join(5)
            t2.join(5)
        self.assertEqual((out["first"][0], out["second"][0]), (200, 200))
        self.assertEqual(coach_server.health()["queued"], 0)

    def test_a_question_that_waits_too_long_is_told_busy_not_left_hanging(self):
        gate, started = threading.Event(), threading.Event()

        def slow(q, d, log_extra=None):
            started.set()
            gate.wait(5)
            return self.reply()

        t1 = threading.Thread(target=lambda: self.ask(slow))
        t1.start()
        started.wait(5)
        with mock.patch.object(coach_server, "QUEUE_WAIT_S", 0.05):
            status, body = self.ask(lambda q, d, log_extra=None: self.reply())
        gate.set()
        t1.join(5)
        self.assertEqual((status, body), (429, {"error": "busy"}))
        self.assertEqual(coach_server.health()["queued"], 0)

    def test_the_lock_is_released_when_an_answer_fails(self):
        def boom(q, d, log_extra=None):
            raise ValueError("x")

        self.assertEqual(self.ask(boom)[0], 500)
        self.assertEqual(self.ask(lambda q, d, log_extra=None: self.reply())[0], 200)


if __name__ == "__main__":
    unittest.main()
