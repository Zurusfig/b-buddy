"""Acceptance tests for P5 (UAT T11): ask back, with buttons, only when guessing would be a gamble.
Cases: data/acceptance_clarify.jsonl.

    python -m unittest tests.test_clarify -v

Rules under test:
  - an ambiguous word (Grab) or a short question with nothing to look up gets a question and buttons
  - every question the project already uses as a clear question is answered as written, never asked about
  - the ask is fixed text in the asker's language, costs no model call, and each button is a complete question
  - a refusal still wins: an investment or off-topic question is refused, not asked about
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS / "budget_coach"))

import agent  # noqa: E402
import clarify  # noqa: E402
import coach_server  # noqa: E402
import eval_persona  # noqa: E402
import gen_gold  # noqa: E402
import language  # noqa: E402
import persona_data  # noqa: E402

CASES = [json.loads(x) for x in (HARNESS / "data" / "acceptance_clarify.jsonl").read_text("utf-8").splitlines() if x.strip()]
SLANG = [json.loads(x)["question"] for x in (HARNESS / "data" / "acceptance_slang.jsonl").read_text("utf-8").splitlines() if x.strip()]


def only_in(lang, text):
    return (not language.LATIN.search(text)) if lang == "th" else (not language.THAI.search(text))


class NeedsTests(unittest.TestCase):
    def test_every_case_asks_or_answers_as_labelled(self):
        for c in CASES:
            need = clarify.needs(c["question"])
            if c["expect"] == "ask":
                self.assertIsNotNone(need, c["id"])
                self.assertEqual(need["reason"], c["reason"], c["id"])
            else:
                self.assertIsNone(need, c["id"])

    def test_clear_questions_the_project_already_uses_are_never_asked_about(self):
        clear = list(SLANG) + [q for q, _ in gen_gold.ADVICE]
        clear += [x["question"] for x in (json.loads(l) for l in (HARNESS / "data" / "acceptance_language.jsonl")
                                         .read_text("utf-8").splitlines() if l.strip())
                  if x["id"] != "L05"]  # L05 is the Grab question: it is a language-detection case and is ambiguous on purpose
        clear += [x["question"] for x in (json.loads(l) for l in (HARNESS / "data" / "acceptance_advice.jsonl")
                                         .read_text("utf-8").splitlines() if l.strip())]
        if persona_data.available():
            clear += [q["question"] for q in eval_persona.all_questions()]
        self.assertGreater(len(clear), 90)
        asked = [q for q in clear if clarify.needs(q)]
        self.assertEqual(asked, [])

    def test_every_button_is_a_complete_question_that_is_not_asked_about_again(self):
        for q in ("ช่วยหน่อย", "help", "Grab เดือนนี้เท่าไหร่", "How much did I spend on Grab this month?"):
            need = clarify.needs(q)
            self.assertEqual(len(need["options"]), 3 if need["reason"] == "vague" else 2)
            for o in need["options"]:
                self.assertTrue(o["label"].strip() and o["question"].strip())
                self.assertIsNone(clarify.needs(o["question"]), o["question"])
                self.assertEqual(language.question_lang(o["question"]), language.question_lang(q))

    def test_the_ask_is_in_the_askers_language_only(self):
        for c in CASES:
            need = clarify.needs(c["question"])
            if need and need["reason"] == "vague":
                lang = language.question_lang(c["question"])
                self.assertTrue(only_in(lang, need["ask"]), c["id"])

    def test_a_word_that_says_which_kind_skips_the_ask(self):
        for q in ("Grab Food", "ค่าแกร็บไบค์", "grab ride last month", "แกร็บเดลิเวอรี่"):
            self.assertIsNone(clarify.needs(q), q)


def routed(question, intent):
    cls = {"intent": intent, "ok": True, "latency": 0.0, "error": None}
    chat = mock.Mock(side_effect=AssertionError("no model may run for an ask-back"))
    with mock.patch.object(agent.router, "classify", return_value=cls), mock.patch.object(agent, "_chat", chat), \
            mock.patch.object(agent, "LOG") as log:
        r = agent.answer_routed(question)
    return r, chat, log


class RoutedTests(unittest.TestCase):
    def test_an_ambiguous_question_gets_buttons_and_no_model_call(self):
        r, chat, log = routed("Grab เดือนนี้เท่าไหร่", "trend")
        chat.assert_not_called()
        self.assertEqual((r["route"], r["flags"], r["model_calls"]), ("clarify", ["clarify"], 0))
        self.assertEqual(r["answer"], "Grab หมายถึงเรียกรถหรือสั่งอาหาร")
        self.assertEqual([o["label"] for o in r["options"]], ["Grab เรียกรถ", "Grab สั่งอาหาร"])
        q = [c for c in log.write.call_args_list if c.args[0] == "coach_question"][0]
        self.assertEqual((q.kwargs["route"], q.kwargs["clarify"]), ("clarify", "ambiguous:grab"))

    def test_a_vague_english_question_gets_the_english_ask(self):
        r, _, _ = routed("help", "trend")
        self.assertEqual(r["route"], "clarify")
        self.assertIn("What would you like to know?", r["answer"])

    def test_investment_is_always_refused_even_when_the_question_is_vague(self):
        r, chat, _ = routed("ไม่รู้", "investment")
        self.assertEqual(r["route"], "refuse")
        self.assertNotIn("options", r)
        chat.assert_not_called()

    def test_off_topic_with_something_to_look_up_is_still_refused(self):
        for q in ("วันนี้อากาศเป็นยังไง", "What's the weather today?"):
            r, _, _ = routed(q, "off_topic")
            self.assertEqual(r["route"], "refuse", q)

    def test_a_greeting_the_router_calls_off_topic_gets_buttons_not_a_refusal(self):
        for q in ("ช่วยหน่อย", "help", "สวัสดี"):
            r, chat, _ = routed(q, "off_topic")
            self.assertEqual((r["route"], len(r["options"])), ("clarify", 3), q)
            chat.assert_not_called()

    def test_a_clear_question_is_not_routed_to_clarify(self):
        cls = {"intent": "trend", "ok": True, "latency": 0.0, "error": None}
        reply = {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c", "type": "function", "function": {"name": "get_budget", "arguments": json.dumps({"category": "food"})}}]},
            "finish_reason": "tool_calls"}], "usage": {"completion_tokens": 5}}
        text = {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 5}}
        chat = mock.Mock(side_effect=[reply, text])
        with mock.patch.object(agent.router, "classify", return_value=cls), mock.patch.object(agent, "_chat", chat), \
                mock.patch.object(agent, "LOG"):
            r = agent.answer_routed("What is my food budget?")
        self.assertNotEqual(r["route"], "clarify")


class AppReplyTests(unittest.TestCase):
    def test_shape_carries_the_buttons(self):
        r, _, _ = routed("Grab เดือนนี้เท่าไหร่", "trend")
        body = coach_server.shape(r)
        self.assertEqual(body["route"], "clarify")
        self.assertEqual(body["answeredBy"], "none")
        self.assertEqual(len(body["options"]), 2)
        self.assertEqual(body["receipt"], [])

    def test_other_replies_have_an_empty_options_list(self):
        r = {"answer": "x", "route": "small", "calls": [], "flags": [], "latency": 1.0, "model": "m:1"}
        self.assertEqual(coach_server.shape(r)["options"], [])



class IncomeTests(unittest.TestCase):  # 500-question eval: "What was my income in August?" got buttons, not an answer
    def test_income_questions_are_not_judgments(self):
        for q in ("What was my income in August?", "How much did I earn last month?", "รายได้เดือนสิงหาคมเท่าไหร่"):
            self.assertIsNone(clarify.unsure(q), q)


if __name__ == "__main__":
    unittest.main()
