"""Slow cases found by timing 218 questions (2026-11-10).

A  over-budget and month-summary replies are written by code (a Thai reply with "compared to" took ~14 s)
B  the 50/30/20 tip comes with its amounts, so the large model does not compute them (~3 s retry)
C  "how much will I spend next month?" is answered by code (~20 s on the large model with thinking on)

    python -m unittest tests.test_speed_fixes -v
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(HARNESS / "budget_coach"))

import advice  # noqa: E402
import agent  # noqa: E402
import interpret  # noqa: E402
import lookup_reply  # noqa: E402
import validator  # noqa: E402

OVER = {"name": "over_budget", "args": {"month": "2026-10"},
        "result": [{"category": "food", "spent": 4093.0, "limit": 4000.0, "over_by": 93.0}]}
SUMMARY = {"name": "month_summary", "args": {"month": "2026-10"},
           "result": {"month": "2026-10", "income_total": 8500.0, "spending_total": 6430.0, "net_cashflow": 2070.0,
                      "refunds_total": 0.0}}
MONTHS = ("2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10")


def tool_reply(name, args):
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
        "finish_reason": "tool_calls"}], "usage": {"completion_tokens": 1}}


class OverBudgetReplyTests(unittest.TestCase):  # A
    def test_english_and_thai_lists(self):
        self.assertTrue(lookup_reply.applies([OVER]))
        self.assertEqual(lookup_reply.render(OVER, "en"),
                         "In October 2026 you are over budget in 1 category:\n- Food: spent 4,093 of 4,000 baht (93 baht over)")
        th = lookup_reply.render(OVER, "th")
        self.assertEqual(th, "เดือนตุลาคม 2026 ใช้เกินงบ 1 หมวด\n- อาหาร: ใช้ไป 4,093 บาท จากงบ 4,000 บาท (เกิน 93 บาท)")
        self.assertNotRegex(th, "[A-Za-z]{2,}", "no English words in a Thai reply")

    def test_nothing_over_and_a_named_category_within_budget(self):
        self.assertEqual(lookup_reply.render({**OVER, "result": []}, "en"),
                         "You are not over budget in any category in October 2026.")
        self.assertIn("Transport is not over budget.", lookup_reply.render(OVER, "en", "Am I over on transport?"))
        self.assertIn("หมวดเดินทางไม่เกินงบ", lookup_reply.render(OVER, "th", "ค่าเดินทางเกินงบไหม"))

    def test_every_number_in_the_reply_comes_from_the_tool(self):
        for lang in ("en", "th"):
            self.assertEqual(validator.unsupported_numbers(lookup_reply.render(OVER, lang), [OVER], extra=(2026,)), [])

    def test_a_malformed_result_is_left_to_the_model(self):
        self.assertFalse(lookup_reply.applies([{**OVER, "result": [{"category": "food"}]}]))
        self.assertFalse(lookup_reply.applies([OVER, OVER]))


class SummaryReplyTests(unittest.TestCase):  # A
    def test_baht_not_dollars(self):
        en = lookup_reply.render(SUMMARY, "en")
        self.assertEqual(en, "October 2026: income 8,500 baht, spending 6,430 baht. You have 2,070 baht left over.")
        self.assertNotIn("$", en)
        self.assertEqual(lookup_reply.render(SUMMARY, "th"), "เดือนตุลาคม 2026 รายรับ 8,500 บาท รายจ่าย 6,430 บาท\nเหลือ 2,070 บาท")

    def test_spending_more_than_income_and_refunds(self):
        res = {**SUMMARY["result"], "net_cashflow": -1200.0, "refunds_total": 120.0}
        en = lookup_reply.render({**SUMMARY, "result": res}, "en")
        self.assertIn("You spent 1,200 baht more than you earned.", en)
        self.assertIn("Refunds of 120 baht", en)


class CodeReplyLoopTests(unittest.TestCase):  # A
    def test_an_over_budget_lookup_needs_one_model_call(self):
        chat = mock.Mock(side_effect=[tool_reply("over_budget", {"month": "2026-07"})])
        with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            r = agent.run("เดือนนี้ใช้เกินหมวดอะไรบ้าง", agent.SMALL_MODEL, False, doubt_check=True)
        self.assertEqual(chat.call_count, 1)
        self.assertIn("code_reply", r["flags"])
        self.assertTrue(r["answer"].startswith("เดือนกรกฎาคม 2026"), r["answer"])


class SplitTests(unittest.TestCase):  # B
    G01 = {"id": "G01", "title": "50/30/20 rule", "tip": "Split 50/30/20."}

    def test_the_amount_in_the_question_is_split(self):
        res = advice.with_split(self.G01, "I'm a student with 8,000 baht a month. How should I plan?")
        self.assertEqual(res["amounts_for_this_student"],
                         {"income": 8000.0, "based_on": "amount in the question", "needs_50": 4000.0,
                          "wants_30": 2400.0, "savings_20": 1600.0})

    def test_otherwise_the_recorded_income_is_split(self):
        res = advice.with_split(self.G01, "What's a simple rule for splitting my income?", lambda: {"income": 10000.0})
        self.assertEqual((res["amounts_for_this_student"]["needs_50"], res["amounts_for_this_student"]["savings_20"]),
                         (5000.0, 2000.0))

    def test_other_tips_and_unknown_income_are_unchanged(self):
        g06 = {"id": "G06", "tip": "Weekly allowance."}
        self.assertIs(advice.with_split(g06, "I have 8,000 a month", lambda: {"income": 1}), g06)
        self.assertIs(advice.with_split(self.G01, "split my income?", lambda: {"income": 0}), self.G01)
        self.assertIs(advice.with_split(self.G01, "split my income?", None), self.G01)

    def test_the_validator_now_accepts_the_split_amounts(self):
        res = advice.with_split(self.G01, "split?", lambda: {"income": 10000.0})
        calls = [{"name": "lookup_guideline", "args": {"guideline_id": "G01"}, "result": res}]
        reply = "On 10,000 baht: about 5,000 for needs, 3,000 for wants and 2,000 for savings [G01]."
        self.assertEqual(validator.unsupported_numbers(reply, calls), [])
        self.assertEqual(validator.unsupported_numbers(reply, [{**calls[0], "result": self.G01}]), [2000.0, 3000.0, 5000.0, 10000.0])

    def test_the_run_loop_adds_the_split_to_the_tool_result(self):
        ctx = agent.Context("s", agent.TOOLS, agent.run_tool, (), agent.DEFAULT_CONTEXT.data_tools,
                            advice_facts=lambda: {"income": 10000.0})
        chat = mock.Mock(side_effect=[tool_reply("lookup_guideline", {"guideline_id": "G01"}),
                                      {"choices": [{"message": {"role": "assistant", "content":
                                                                "Needs 5,000, wants 3,000, savings 2,000 [G01]."},
                                                    "finish_reason": "stop"}], "usage": {"completion_tokens": 1}}])
        with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            r = agent.run("split my income?", agent.BIG_MODEL, False, "k", raw=False, ctx=ctx)
        self.assertEqual(r["validator_retries"], 0)
        self.assertEqual(r["calls"][0]["result"]["amounts_for_this_student"]["wants_30"], 3000.0)


class EmergencyFundTests(unittest.TestCase):  # B, same fix for G02 (3-6x monthly spending)
    G02 = {"id": "G02", "title": "Build an emergency fund", "tip": "3-6 times your monthly essential expenses."}

    def test_recorded_spending_gives_three_and_six_months(self):
        res = advice.with_split(self.G02, "How much should I keep as an emergency fund?",
                                lambda: {"income": 20000.0, "spending": 18842.0, "month": "2026-10"})
        self.assertEqual(res["amounts_for_this_student"],
                         {"monthly_spending": 18842.0, "based_on": "spending recorded in 2026-10",
                          "three_months": 56526.0, "six_months": 113052.0})

    def test_a_spending_figure_in_the_question_wins(self):
        res = advice.with_split(self.G02, "I spend about 9,000 baht a month, how big should my emergency fund be?")
        self.assertEqual((res["amounts_for_this_student"]["three_months"], res["amounts_for_this_student"]["six_months"]),
                         (27000.0, 54000.0))

    def test_the_validator_accepts_them(self):
        res = advice.with_split(self.G02, "emergency fund?", lambda: {"spending": 18842.0})
        reply = "Aim for about 56,526 to 113,052 baht, 3-6 months of your 18,842 baht spending [G02]."
        calls = [{"name": "lookup_guideline", "args": {"guideline_id": "G02"}, "result": res}]
        self.assertEqual(validator.unsupported_numbers(reply, calls), [])


class TipLanguageTests(unittest.TestCase):  # an English question got a Thai reply, then a language rewrite
    G01 = {"id": "G01", "title": "50/30/20 rule", "tip": "Split 50/30/20.", "tip_th": "แบ่ง 50/30/20",
           "source": "All Your Worth", "checked_by_hand": "2026-11-02"}

    def test_the_model_sees_one_language(self):
        en, th = advice.in_language(self.G01, "en"), advice.in_language(self.G01, "th")
        self.assertEqual((en["tip"], th["tip"]), ("Split 50/30/20.", "แบ่ง 50/30/20"))
        for r in (en, th):
            self.assertNotIn("tip_th", r)
            self.assertNotIn("checked_by_hand", r)
            self.assertEqual(r["source"], "All Your Worth")
        self.assertEqual(self.G01["tip_th"], "แบ่ง 50/30/20", "the catalog entry itself is not changed")

    def test_the_run_loop_passes_only_the_english_tip_for_an_english_question(self):
        chat = mock.Mock(side_effect=[tool_reply("lookup_guideline", {"guideline_id": "G01"}),
                                      {"choices": [{"message": {"role": "assistant", "content": "Try 50/30/20 [G01]."},
                                                    "finish_reason": "stop"}], "usage": {"completion_tokens": 1}}])
        with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            r = agent.run("simple rule for splitting my income", agent.BIG_MODEL, False, "k", raw=False)
        self.assertNotIn("tip_th", r["calls"][0]["result"])
        self.assertNotRegex(json.dumps(chat.call_args_list[1].args[2][-1], ensure_ascii=False), "[\u0e00-\u0e7f]")


class FutureMonthTests(unittest.TestCase):  # C
    def test_next_month_spending_is_answered_by_code(self):
        en = interpret.future("How much will I spend next month?", MONTHS, "2026-10", "en")
        self.assertEqual(en["answer"], "I can only show spending that has already happened, so I can't tell you about "
                                       "November 2026 yet. Your data runs from May 2026 to October 2026.")
        th = interpret.future("เดือนหน้าจะใช้เงินเท่าไหร่", MONTHS, "2026-10", "th")
        self.assertIn("เดือนพฤศจิกายน 2026", th["answer"])
        self.assertEqual(th["options"][0]["question"], "เดือนนี้ใช้เงินไปกับอะไรบ้าง")

    def test_december_rolls_over_to_january(self):
        self.assertIn("January 2027", interpret.future("next month spending?", ("2026-12",), "2026-12", "en")["answer"])

    def test_other_questions_are_not_caught(self):
        for q in ("How much did I spend last month?", "What is my food budget next month?"):
            self.assertIsNone(interpret.future(q, MONTHS, "2026-10", "en"), q)
        self.assertIsNone(interpret.future("next month spending?", (), "", "en"), "no data, no reference month")

    def test_answer_routed_skips_every_model(self):
        ctx = agent.Context("s", agent.TOOLS, agent.run_tool, (), agent.DEFAULT_CONTEXT.data_tools,
                            months=MONTHS, reference="2026-10")
        cls = {"intent": "trend", "ok": True, "latency": 0.3, "error": None}
        with mock.patch.object(agent.router, "classify", return_value=cls), mock.patch.object(agent, "LOG"), \
                mock.patch.object(agent, "_chat", side_effect=AssertionError("no model call")):
            r = agent.answer_routed("How much will I spend next month?", ctx=ctx)
        self.assertEqual((r["route"], r["model_calls"]), ("code", 0))
        self.assertIn("future_month", r["flags"])


if __name__ == "__main__":
    unittest.main()
