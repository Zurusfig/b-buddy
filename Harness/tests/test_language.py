"""Acceptance tests for P1 (Thai and English). The criteria live in data/acceptance_language.jsonl.

    python -m unittest tests.test_language -v

Rules under test:
  - the language of a question is decided by code: any Thai letter means Thai
  - a refusal and the validator's raw-results fallback are written in that one language only
  - a model reply in the wrong script is retried once, then flagged `wrong_language`, which escalates
No model or network is used: the model is a scripted fake.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS / "budget_coach"))

import agent  # noqa: E402
import language  # noqa: E402
import validator  # noqa: E402

CASES = [json.loads(line) for line in (HARNESS / "data" / "acceptance_language.jsonl").read_text("utf-8").splitlines()
         if line.strip()]


def of(check):
    return [c for c in CASES if c["check"] == check]


def tool_reply(name, args):
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "call_0", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
        "finish_reason": "tool_calls"}], "usage": {"completion_tokens": 5}}


def text_reply(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 5}}


class Scripted:
    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, key, model, messages, think, tool_defs):
        self.requests.append(list(messages))
        return self.replies.pop(0)


def only_in(lang, text):
    """True if `text` is written in one language: Thai-only has no Latin words, English-only has no Thai."""
    return (not language.LATIN.search(text)) if lang == "th" else (not language.THAI.search(text))


class DetectTests(unittest.TestCase):
    def test_every_case_is_detected_as_labelled(self):
        for c in CASES:
            self.assertEqual(language.question_lang(c["question"]), c["lang"], c["id"])

    def test_digits_and_symbols_alone_are_english(self):
        self.assertEqual(language.question_lang("7-Eleven 2026-10 ฿500".replace("฿", "")), "en")

    def test_reply_check_thresholds(self):
        self.assertFalse(language.reply_matches("th", "You spent a lot of money this month in total."))
        self.assertFalse(language.reply_matches("th", "ใช้ไป 4261 บาท ที่ Grab และ 7-Eleven"),
                         "mixed English merchant names trigger a Thai rewrite")
        self.assertTrue(language.reply_matches("th", "เดือนนี้คุณใช้ค่าอาหารไป 4261 บาท"))
        self.assertTrue(language.reply_matches("en", "You spent 4261 on ก๋วยเตี๋ยวเรือ and food this month."))
        self.assertFalse(language.reply_matches("en", "เดือนนี้คุณใช้เงินมากกว่ารายได้ของคุณอยู่พอสมควร"))
        self.assertTrue(language.reply_matches("th", "4261"), "a bare number is not judged")


class FixedMessageTests(unittest.TestCase):
    def test_refusals_use_one_language_only(self):
        for c in of("refusal"):
            msg = agent.decline_message(c["kind"], c["lang"])
            self.assertTrue(only_in(c["lang"], msg), (c["id"], msg))
            self.assertTrue(msg.strip())

    def test_routed_refusal_follows_the_question_language(self):
        for c in of("refusal"):
            cls = {"intent": c["kind"], "ok": True, "latency": 0.0, "error": None}
            with mock.patch.object(agent.router, "classify", return_value=cls), mock.patch.object(agent, "LOG"):
                r = agent.answer_routed(c["question"])
            self.assertEqual(r["answer"], agent.decline_message(c["kind"], c["lang"]), c["id"])
            self.assertTrue(only_in(c["lang"], r["answer"]), c["id"])

    def test_decline_tool_follows_the_question_language(self):
        for c in of("refusal"):
            chat = Scripted(tool_reply("decline", {"kind": c["kind"]}))
            with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
                r = agent.run(c["question"], "m", False)
            self.assertEqual(r["answer"], agent.decline_message(c["kind"], c["lang"]), c["id"])

    def test_fallback_header_follows_the_language(self):
        for c in of("fallback"):
            out = validator.fallback_answer([], c["lang"])
            self.assertTrue(only_in(c["lang"], out.replace("- (", "").replace(")", "")), (c["id"], out))

    def test_fallback_in_a_real_run_is_one_language(self):
        c = of("fallback")[0]
        invented = text_reply("คุณใช้ไป 99999 บาท")
        chat = Scripted(tool_reply("get_budget", {"category": "food"}), invented, invented)
        with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            r = agent.run(c["question"], "m", False)
        self.assertIn("validator_fallback", r["flags"])
        self.assertIn(validator.FALLBACK_HEADER["th"], r["answer"])
        self.assertNotIn(validator.FALLBACK_HEADER["en"], r["answer"])


class WrongLanguageTests(unittest.TestCase):
    def run_case(self, c, *model_replies):
        chat = Scripted(tool_reply("get_budget", {"category": "food"}), *model_replies)
        with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            return agent.run(c["question"], "m", False), chat

    def test_wrong_script_is_retried_once_and_then_passes(self):
        for c in of("model_wrong_language"):
            r, chat = self.run_case(c, text_reply(c["wrong_reply"]), text_reply(c["right_reply"]))
            self.assertEqual(r["answer"], c["right_reply"], c["id"])
            self.assertNotIn("wrong_language", r["flags"], c["id"])
            self.assertEqual(r["model_calls"], 3, c["id"])
            asked_again = chat.requests[-1][-1]["content"]
            self.assertIn("Thai" if c["lang"] == "th" else "English", asked_again, c["id"])

    def test_still_wrong_after_the_retry_is_flagged_and_escalates(self):
        for c in of("model_wrong_language"):
            r, _ = self.run_case(c, text_reply(c["wrong_reply"]), text_reply(c["wrong_reply"]))
            self.assertIn("wrong_language", r["flags"], c["id"])
            self.assertIn("wrong_language", agent.escalate(r), c["id"])
            self.assertEqual(r["model_calls"], 3, c["id"])

    def test_correct_language_is_never_retried(self):
        for c in of("model_wrong_language"):
            r, _ = self.run_case(c, text_reply(c["right_reply"]))
            self.assertEqual(r["model_calls"], 2, c["id"])
            self.assertNotIn("wrong_language", r["flags"], c["id"])

    def test_the_flag_is_an_escalation_trigger(self):
        self.assertIn("wrong_language", agent.AUTO_TRIGGERS)


class ThaiAdviceGlossTests(unittest.TestCase):
    """Real Gemma replies to "ช่วยแนะนำวิธีลดค่าอาหารหน่อย" that were rejected, and cost about 45 s of retries."""
    TIP = [{"name": "lookup_guideline", "args": {"guideline_id": "G06"}, "result": {
        "id": "G06", "title": "Weekly spending allowance (envelope method)",
        "source": "Dave Ramsey, The Total Money Makeover (envelope system)"}},
        {"name": "sum_by_category", "args": {"month": "2026-10", "category": "food"}, "result": 4093.0}]

    def allowed(self):
        return language.tool_text(self.TIP)

    def test_an_english_gloss_in_brackets_is_fine_in_a_thai_reply(self):
        reply = ("แนะนำให้ลองใช้วิธีแบ่งงบรายสัปดาห์ (envelope method) โดยนำค่าอาหารของเดือนนี้ที่ใช้ไป 4,093.0 บาท "
                 "มาแบ่งเป็นงบรายสัปดาห์ และเมื่อเงินในสัปดาห์นั้นหมดให้หยุดใช้ครับ [G06]")
        self.assertTrue(language.reply_matches("th", reply))

    def test_a_cited_source_in_nested_brackets_is_fine(self):
        reply = ("เดือนนี้คุณใช้ค่าอาหารไป 4093.0 บาท แนะนำให้ลองแบ่งงบค่าอาหารเป็นรายสัปดาห์ครับ "
                 "(Dave Ramsey, The Total Money Makeover (envelope system) [G06])")
        self.assertTrue(language.reply_matches("th", reply))

    def test_names_from_the_tool_results_may_be_quoted_outside_brackets(self):
        reply = "ลองใช้ envelope method ตามแนวทางของ Dave Ramsey โดยแบ่งค่า food เป็นรายสัปดาห์ครับ"
        self.assertFalse(language.reply_matches("th", reply), "without the tool results these are loose English")
        self.assertTrue(language.reply_matches("th", reply, self.allowed()))

    def test_field_names_are_not_allowed_words(self):
        self.assertNotIn("over_by", language.tool_text([{"name": "over_budget", "args": {}, "result": [
            {"category": "food", "spent": 1.0, "over_by": 1.0}]}]))

    def test_english_drift_and_chinese_are_still_rejected(self):
        self.assertFalse(language.reply_matches("th", "คุณใช้ค่าอาหารไป 4,093 บาท compared to last month",
                                                self.allowed()))
        self.assertFalse(language.reply_matches("th", "คุณใช้ค่าอาหารไป 4,093 บาท 而在本月 (envelope method)",
                                                self.allowed()))

    def test_the_run_loop_accepts_the_bracketed_reply_without_a_retry(self):
        reply = "แนะนำให้แบ่งงบค่าอาหาร 4,093.0 บาท เป็นรายสัปดาห์ (envelope method) ครับ [G06]"
        chat = mock.Mock(side_effect=[
            {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c", "type": "function", "function": {"name": "sum_by_category",
                                                             "arguments": '{"month": "2026-07", "category": "food"}'}}]},
                "finish_reason": "tool_calls"}], "usage": {"completion_tokens": 1}},
            {"choices": [{"message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
             "usage": {"completion_tokens": 1}}])
        with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"), \
                mock.patch.object(agent.validator, "unsupported_numbers", return_value=[]):
            r = agent.run("ช่วยแนะนำวิธีลดค่าอาหารหน่อย", agent.BIG_MODEL, False, "k")
        self.assertEqual(chat.call_count, 2)
        self.assertNotIn("wrong_language", r["flags"])
        self.assertEqual(r["answer"], reply)


if __name__ == "__main__":
    unittest.main()
