"""Offline tests for the budget coach: validator, router, tools, agent loop and routing.

    python -m unittest discover -s tests -v

Model and network calls are replaced with scripted fakes; no Ollama or gateway key is needed.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

COACH = Path(__file__).resolve().parent.parent / "budget_coach"
sys.path.insert(0, str(COACH))

import agent  # noqa: E402
import router  # noqa: E402
import tools  # noqa: E402
import validator  # noqa: E402
from harness.logger import JsonlLogger  # noqa: E402

FOOD = tools.sum_by_category("2026-07", "food")


def tool_reply(name, args, call_id="call_0"):
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}}]}, "finish_reason": "tool_calls"}],
        "usage": {"completion_tokens": 5}}


def text_reply(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 5}}


class ScriptedChat:
    """Stands in for agent._chat; replays replies in order and records each request."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, key, model, messages, think, tool_defs):
        self.requests.append({"model": model, "think": think, "messages": list(messages),
                              "tools": [t["function"]["name"] for t in tool_defs]})
        return self.replies.pop(0)


class AgentTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.log_path = Path(tmp) / "coach.jsonl"
        patch = mock.patch.object(agent, "LOG", JsonlLogger(self.log_path))
        patch.start()
        self.addCleanup(patch.stop)


class ValidatorTests(unittest.TestCase):
    CALLS = [{"name": "sum_by_category", "args": {}, "result": 3199.5},
             {"name": "over_budget", "args": {}, "result": [{"category": "food", "spent": 4800.0,
                                                              "limit": 4500.0, "over_by": 300.0}]}]

    def test_verbatim_numbers_pass(self):
        self.assertEqual(validator.unsupported_numbers("Food was 3,199.5 THB, over by 300.", self.CALLS), [])

    def test_rounding_to_the_baht_passes(self):
        self.assertEqual(validator.unsupported_numbers("About 3,200 baht on food.", self.CALLS), [])

    def test_invented_and_derived_numbers_are_rejected(self):
        bad = validator.unsupported_numbers("Food 3,199.5 and a total of 7,000.", self.CALLS)
        self.assertEqual(bad, [7000.0])

    def test_thai_digits_and_commas_are_normalised(self):
        self.assertEqual(validator.unsupported_numbers("ค่าอาหาร ๔,๘๐๐ บาท", self.CALLS), [])

    def test_dates_list_markers_and_guideline_ids_are_ignored(self):
        text = "1. In 2026-07 follow tip [G03].\n2) Then review."
        self.assertEqual(validator.unsupported_numbers(text, [], extra=(2026,)), [])

    def test_numbers_from_the_question_and_persona_are_allowed(self):
        self.assertEqual(validator.unsupported_numbers("You said 4,000; income is 12,000.", [],
                                                       "I spent 4,000 on food", extra=(12000,)), [])

    def test_list_length_counts_as_a_number(self):
        self.assertEqual(validator.unsupported_numbers("You are over in 1 category.", self.CALLS), [])

    def test_fallback_lists_raw_results_and_skips_errors(self):
        calls = self.CALLS + [{"name": "get_budget", "args": {}, "result": {"error": "bad"}}]
        out = validator.fallback_answer(calls)
        self.assertIn("sum_by_category", out)
        self.assertNotIn("get_budget", out)
        self.assertIn("(no data", validator.fallback_answer([]))


class ToolTests(unittest.TestCase):
    def test_get_transactions_filters_by_month_and_category(self):
        rows = tools.get_transactions("2026-07", "food")
        self.assertTrue(rows)
        self.assertTrue(all(r["date"].startswith("2026-07") and r["category"] == "food" for r in rows))
        self.assertAlmostEqual(sum(r["amount"] for r in rows), FOOD, places=2)

    def test_get_transactions_rejects_bad_month(self):
        with self.assertRaises(ValueError):
            tools.get_transactions("2020-01")

    def test_guidelines_have_source_and_url_keys(self):
        for g in agent.GUIDELINES.values():
            self.assertIn("source", g)
            self.assertIn("url", g)


class RouterTests(unittest.TestCase):
    @staticmethod
    def fake_post(content):
        resp = mock.Mock(status_code=200)
        resp.raise_for_status = mock.Mock()
        resp.json.return_value = {"message": {"content": content}}
        return mock.Mock(return_value=resp)

    def test_valid_intent(self):
        with mock.patch.object(router.requests, "post", self.fake_post('{"intent": "advice"}')) as post:
            r = router.classify("how do I save?")
        self.assertEqual((r["intent"], r["ok"]), ("advice", True))
        self.assertEqual(post.call_args.kwargs["json"]["format"], router.SCHEMA)

    def test_invalid_intent_falls_back_to_none(self):
        with mock.patch.object(router.requests, "post", self.fake_post('{"intent": "poetry"}')):
            r = router.classify("hi")
        self.assertEqual((r["intent"], r["ok"]), (None, False))

    def test_connection_error_never_raises(self):
        with mock.patch.object(router.requests, "post", side_effect=router.requests.ConnectionError("down")):
            r = router.classify("hi")
        self.assertIsNone(r["intent"])
        self.assertIn("ConnectionError", r["error"])

    def test_coarse_labels(self):
        self.assertEqual(router.coarse("investment"), "out_of_scope")
        self.assertEqual(router.coarse("trend"), "trend")
        self.assertIsNone(router.coarse(None))


class RunLoopTests(AgentTestCase):
    def test_verified_answer_passes_untouched(self):
        chat = ScriptedChat(tool_reply("sum_by_category", {"month": "2026-07", "category": "food"}),
                            text_reply(f"Food in July was {FOOD:,.2f} THB."))
        with mock.patch.object(agent, "_chat", chat):
            r = agent.run("food in July?", "m", False)
        self.assertNotIn("validator_fallback", r["flags"])
        self.assertEqual(r["validator_retries"], 0)
        self.assertEqual(r["model_calls"], 2)

    def test_invented_number_gets_one_retry_then_passes(self):
        chat = ScriptedChat(tool_reply("sum_by_category", {"month": "2026-07", "category": "food"}),
                            text_reply("Food in July was 99,999 THB."),
                            text_reply(f"Food in July was {FOOD:,.2f} THB."))
        with mock.patch.object(agent, "_chat", chat):
            r = agent.run("food in July?", "m", False)
        self.assertEqual(r["validator_retries"], 1)
        self.assertNotIn("validator_fallback", r["flags"])
        self.assertIn("99999", chat.requests[2]["messages"][-1]["content"])
        self.assertIn(f"{FOOD:,.2f}", r["answer"])

    def test_persistent_invented_number_falls_back_to_raw_totals(self):
        chat = ScriptedChat(tool_reply("sum_by_category", {"month": "2026-07", "category": "food"}),
                            text_reply("It was 99,999."), text_reply("Really, 88,888."))
        with mock.patch.object(agent, "_chat", chat):
            r = agent.run("food in July?", "m", False)
        self.assertIn("validator_fallback", r["flags"])
        self.assertIn("sum_by_category", r["answer"])
        self.assertNotIn("88,888", r["answer"])

    def test_raw_false_hides_get_transactions(self):
        chat = ScriptedChat(text_reply("Hello."))
        with mock.patch.object(agent, "_chat", chat):
            agent.run("hi", "m", True, raw=False)
        self.assertNotIn("get_transactions", chat.requests[0]["tools"])
        with self.assertRaises(ValueError):
            agent.run_tool("get_transactions", {"month": "2026-07"}, raw=False)
        self.assertTrue(agent.run_tool("get_transactions", {"month": "2026-07"}, raw=True))

    def logged(self, event):
        lines = [json.loads(x) for x in self.log_path.read_text(encoding="utf-8").splitlines()]
        return [x for x in lines if x["event"] == event]

    def test_tool_calls_are_logged_with_arguments_result_and_duration(self):
        chat = ScriptedChat(tool_reply("sum_by_category", {"month": "2026-07", "category": "food"}),
                            text_reply(f"Food in July was {FOOD:,.2f} THB."))
        with mock.patch.object(agent, "_chat", chat):
            agent.run("food in July?", "m", False)
        (rec,) = self.logged("coach_tool_call")
        self.assertEqual((rec["tool"], rec["ok"], rec["error"]), ("sum_by_category", True, None))
        self.assertEqual(rec["arguments"], {"month": "2026-07", "category": "food"})
        self.assertIn(str(int(FOOD)), rec["result"])
        self.assertGreaterEqual(rec["duration_s"], 0)

    def test_failed_tool_call_is_logged_with_its_error(self):
        chat = ScriptedChat(tool_reply("sum_by_category", {"month": "1999-01", "category": "food"}),
                            text_reply("Sorry, no data."))
        with mock.patch.object(agent, "_chat", chat):
            agent.run("food in 1999?", "m", False)
        (rec,) = self.logged("coach_tool_call")
        self.assertFalse(rec["ok"])
        self.assertIn("no data for month", rec["error"])

    def test_long_results_are_truncated_in_the_log(self):
        chat = ScriptedChat(tool_reply("get_transactions", {"month": "2026-07"}), text_reply("Here."))
        with mock.patch.object(agent, "_chat", chat):
            agent.run("list July", "m", False)
        (rec,) = self.logged("coach_tool_call")
        self.assertLessEqual(len(rec["result"]), 300)

    def test_decline_is_logged_as_a_tool_call(self):
        chat = ScriptedChat(tool_reply("decline", {"kind": "investment"}))
        with mock.patch.object(agent, "_chat", chat):
            agent.run("buy bitcoin?", "m", False)
        (rec,) = self.logged("coach_tool_call")
        self.assertEqual((rec["tool"], rec["arguments"]), ("decline", {"kind": "investment"}))

    def test_decline_tool_still_works_and_skips_validation(self):
        chat = ScriptedChat(tool_reply("decline", {"kind": "investment"}))
        with mock.patch.object(agent, "_chat", chat):
            r = agent.run("buy bitcoin?", "m", False)
        self.assertIn("declined", r["flags"])
        self.assertEqual(r["answer"], agent.DECLINE_MSG["investment"])


class OllamaAdapterTests(unittest.TestCase):
    def test_history_is_converted_for_ollama(self):
        history = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"},
                   {"role": "assistant", "content": "", "tool_calls": [
                       {"id": "call_0", "type": "function",
                        "function": {"name": "get_budget", "arguments": '{"category": "food"}'}}]},
                   {"role": "tool", "tool_call_id": "call_0", "content": "4500"}]
        out = agent._to_ollama(history)
        self.assertEqual(out[2]["tool_calls"][0]["function"]["arguments"], {"category": "food"})
        self.assertEqual(out[3], {"role": "tool", "tool_name": "get_budget", "content": "4500"})

    def test_response_is_normalised_to_openai_shape(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"message": {"content": "", "tool_calls": [
            {"function": {"name": "get_budget", "arguments": {"category": "food"}}}]}, "eval_count": 7}
        with mock.patch.object(agent.requests, "post", return_value=resp):
            data = agent._chat_ollama("qwen3:4b-q4_K_M", [], False, [])
        call = data["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(json.loads(call["function"]["arguments"]), {"category": "food"})
        self.assertEqual(data["usage"]["completion_tokens"], 7)

    def test_model_name_decides_backend(self):
        self.assertTrue(agent.is_local("qwen3:4b-q4_K_M"))
        self.assertFalse(agent.is_local("gemma-4-31b"))


class RoutingTests(AgentTestCase):
    def route(self, intent, runs):
        cls = {"intent": intent, "ok": intent is not None, "latency": 0.5, "error": None}
        fake = mock.Mock(side_effect=runs)
        with mock.patch.object(router, "classify", return_value=cls), mock.patch.object(agent, "run", fake):
            return agent.answer_routed("q"), fake

    @staticmethod
    def result(**kw):
        return {"answer": "ok", "calls": [{"name": "get_budget", "args": {}, "result": 1}], "flags": [],
                "model_calls": 1, "tokens": 1, "latency": 1.0, "think": False, "model": "m",
                "validator_retries": 0, **kw}

    def test_investment_is_refused_without_a_model_call(self):
        r, run = self.route("investment", [])
        run.assert_not_called()
        self.assertEqual((r["route"], r["answer"]), ("refuse", agent.DECLINE_MSG["investment"]))
        self.assertIn("declined", r["flags"])

    def test_trend_uses_the_small_model(self):
        r, run = self.route("trend", [self.result()])
        self.assertEqual(run.call_args.args[1:3], (agent.SMALL_MODEL, False))
        self.assertEqual(r["route"], "small")

    def test_advice_uses_the_large_model_without_raw_tool(self):
        r, run = self.route("advice", [self.result(think=True)])
        self.assertEqual(run.call_args.args[1:3], (agent.BIG_MODEL, True))
        self.assertIs(run.call_args.kwargs["raw"], False)
        self.assertEqual(r["route"], "advice->large")

    def test_small_model_trigger_escalates_to_large_and_adds_latency(self):
        small = self.result(flags=["no_tool"], latency=1.0)
        big = self.result(think=True, latency=8.0)
        r, run = self.route("budget_check", [small, big])
        self.assertEqual(r["route"], "small->large")
        self.assertEqual(r["escalated_by"], ["no_tool"])
        self.assertAlmostEqual(r["latency"], 1.0 + 8.0 + 0.5)

    def test_unclassified_question_falls_back_to_the_small_model(self):
        r, run = self.route(None, [self.result()])
        self.assertEqual(r["route"], "small")
        self.assertIsNone(r["intent"])


if __name__ == "__main__":
    unittest.main()
