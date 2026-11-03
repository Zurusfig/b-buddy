"""Acceptance tests for P3 (wrong tool) and P4 (combined totals). Cases: data/acceptance_tools.jsonl.

    python -m unittest tests.test_tools -v

Rules under test:
  - a question that names a category must be answered with a tool call about that category, or `arg_mismatch` is
    raised and the question reruns on the large model
  - "food plus transport" is answered by one sum_categories call, so the total comes from code, not the model
No model or network: the model is a scripted fake.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS / "budget_coach"))

import agent  # noqa: E402
import categories  # noqa: E402
import persona_agent  # noqa: E402
import persona_data  # noqa: E402

CASES = [json.loads(x) for x in (HARNESS / "data" / "acceptance_tools.jsonl").read_text("utf-8").splitlines() if x.strip()]
HAVE_DATA = persona_data.available()


def tool_reply(name, args):
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c0", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
        "finish_reason": "tool_calls"}], "usage": {"completion_tokens": 5}}


def text_reply(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 5}}


class Scripted:
    def __init__(self, *replies):
        self.replies = list(replies)

    def __call__(self, key, model, messages, think, tool_defs):
        return self.replies.pop(0)


PERSONA_CATEGORIES = ("food", "transport", "shopping", "entertainment", "bills", "education", "health", "other")


def valid_for(case):
    return PERSONA_CATEGORIES if case.get("valid") == "persona" else None


class CheckTests(unittest.TestCase):
    def test_implied_categories_match_the_cases(self):
        for c in CASES:
            self.assertEqual(set(categories.implied_categories(c["question"], valid_for(c))), set(c["implied"]), c["id"])

    def test_mismatch_matches_the_cases(self):
        for c in CASES:
            calls = [{"result": 0, **call} for call in c["calls"]]
            self.assertEqual(categories.mismatch(c["question"], calls, valid_for(c)), c["mismatch"], c["id"])

    def test_gemma_text_calls_keep_lists_whole(self):
        raw = 'categories:[<|"|>food<|"|>,<|"|>transport<|"|>],month:<|"|>2026-09<|"|>'
        self.assertEqual(agent._text_args(raw), {"categories": ["food", "transport"], "month": "2026-09"})
        self.assertEqual(agent._text_args('category:<|"|>food<|"|>,month:<|"|>2026-09<|"|>'),
                         {"category": "food", "month": "2026-09"})
        self.assertEqual(agent._text_args(""), {})
        self.assertEqual(agent._text_args('month:<|"|>a, b: c<|"|>'), {"month": "a, b: c"})

    def test_a_failed_tool_call_is_left_to_tool_error(self):
        calls = [{"name": "sum_by_category", "args": {"category": "food"}, "result": {"error": "bad"}}]
        self.assertFalse(categories.mismatch("ค่าวิน", calls))


@unittest.skipUnless(HAVE_DATA, "persona/csv not present")
class SumCategoriesTests(unittest.TestCase):
    def setUp(self):
        self.data = persona_data.PersonaData(persona_data.resolve_user("alice"))

    def test_total_is_the_sum_of_the_categories(self):
        r = self.data.sum_categories("2026-10", ["food", "transport"])
        self.assertAlmostEqual(r["total"], r["by_category"]["food"] + r["by_category"]["transport"], places=2)
        self.assertAlmostEqual(r["by_category"]["food"], self.data.sum_by_category("2026-10", "food"), places=2)
        self.assertAlmostEqual(r["by_category"]["food"], 5624, places=0)  # ground truth for Alice, October

    def test_repeats_are_counted_once(self):
        r = self.data.sum_categories("2026-10", ["food", "food"])
        self.assertEqual(r["categories"], ["food"])
        self.assertAlmostEqual(r["total"], self.data.sum_by_category("2026-10", "food"), places=2)

    def test_bad_input_raises(self):
        for bad in ([], "food", ["nonsense"]):
            with self.assertRaises(ValueError):
                self.data.sum_categories("2026-10", bad)

    def test_the_tool_is_offered_and_runs_through_the_agent_context(self):
        ctx, _ = persona_agent.build_context("alice")
        self.assertIn("sum_categories", [t["function"]["name"] for t in ctx.tools])
        self.assertIn("sum_categories", ctx.data_tools)
        out = ctx.run_tool("sum_categories", {"month": "2026-10", "categories": ["food", "transport"]}, True)
        self.assertEqual(set(out["by_category"]), {"food", "transport"})


@unittest.skipUnless(HAVE_DATA, "persona/csv not present")
class RunTests(unittest.TestCase):
    def setUp(self):
        self.ctx, self.data = persona_agent.build_context("alice")

    def run_q(self, question, *replies):
        with mock.patch.object(agent, "_chat", Scripted(*replies)), mock.patch.object(agent, "LOG"):
            return agent.run(question, "m", False, ctx=self.ctx)

    def test_win_answered_with_a_whole_month_summary_is_flagged_and_escalates(self):
        r = self.run_q("ค่าวิน", tool_reply("month_summary", {"month": "2026-10"}), text_reply("เดือนนี้ใช้จ่ายรวมเยอะมาก"))
        self.assertIn("arg_mismatch", r["flags"])
        self.assertIn("arg_mismatch", agent.escalate(r))

    def test_win_answered_with_transport_is_not_flagged(self):
        spent = self.data.sum_by_category("2026-09", "transport")
        r = self.run_q("ค่าวินเดือนที่แล้ว", tool_reply("sum_by_category", {"month": "2026-09", "category": "transport"}),
                       text_reply(f"ค่าเดินทางเดือนที่แล้ว {spent:g} บาท"))
        self.assertNotIn("arg_mismatch", r["flags"])

    def test_combined_total_uses_one_code_computed_number(self):
        total = self.data.sum_categories("2026-09", ["food", "transport"])["total"]
        r = self.run_q("ค่าอาหารกับค่าเดินทางเดือนที่แล้วรวมเท่าไหร่",
                       tool_reply("sum_categories", {"month": "2026-09", "categories": ["food", "transport"]}),
                       text_reply(f"รวม {total:g} บาท"))
        self.assertNotIn("arg_mismatch", r["flags"])
        self.assertNotIn("validator_fallback", r["flags"])
        self.assertEqual(r["validator_retries"], 0)

    def test_a_total_the_model_added_itself_is_rejected_by_the_validator(self):
        a, b = (self.data.sum_by_category("2026-09", c) for c in ("food", "transport"))
        r = self.run_q("ค่าอาหารกับค่าเดินทางเดือนที่แล้วรวมเท่าไหร่",
                       tool_reply("sum_categories", {"month": "2026-09", "categories": ["food", "transport"]}),
                       text_reply(f"รวม {a + b + 1:g} บาท"), text_reply(f"รวม {a + b + 1:g} บาท"))
        self.assertIn("validator_fallback", r["flags"])


@unittest.skipUnless(HAVE_DATA, "persona/csv not present")
class AnswerCleanTests(unittest.TestCase):
    def test_a_stray_cjk_full_stop_becomes_a_normal_one(self):
        ctx, _ = persona_agent.build_context("alice")
        chat = Scripted(tool_reply("get_budget", {"category": "food"}), text_reply("งบอาหารมีอยู่。"))
        with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            r = agent.run("งบอาหาร", "m", False, ctx=ctx)
        self.assertNotIn("。", r["answer"])


SLANG = [json.loads(x) for x in (HARNESS / "data" / "acceptance_slang.jsonl").read_text("utf-8").splitlines() if x.strip()]


class SlangTests(unittest.TestCase):
    """20 bare Thai phrases. The 4B model got 11 right in a live run; the large model got all 20."""

    def test_every_phrase_names_its_category(self):
        for c in SLANG:
            self.assertEqual(categories.implied_categories(c["question"], PERSONA_CATEGORIES), [c["category"]], c["id"])

    def test_every_wrong_tool_the_small_model_chose_is_caught(self):
        wrong = [c for c in SLANG if c["small_model_did"]]
        self.assertEqual(len(wrong), 9)
        for c in wrong:
            args = {"month": "2026-10"} if c["small_model_did"] in ("month_summary", "lookup_guideline") else {"category": c["category"]}
            calls = [{"name": c["small_model_did"], "args": args, "result": 1}]
            self.assertTrue(categories.mismatch(c["question"], calls, PERSONA_CATEGORIES), c["id"])

    def test_the_right_tool_is_never_flagged(self):
        for c in SLANG:
            calls = [{"name": "sum_by_category", "args": {"month": "2026-10", "category": c["category"]}, "result": 1}]
            self.assertFalse(categories.mismatch(c["question"], calls, PERSONA_CATEGORIES), c["id"])

    def test_the_glossary_file_is_valid(self):
        for cat, pattern in categories.KEYWORDS.items():
            self.assertTrue(pattern.pattern, cat)
        self.assertEqual(set(categories.KEYWORDS), set(PERSONA_CATEGORIES) - {"other"} | {"subscriptions"})


class FlagTests(unittest.TestCase):
    def test_arg_mismatch_is_an_escalation_trigger(self):
        self.assertIn("arg_mismatch", agent.AUTO_TRIGGERS)


if __name__ == "__main__":
    unittest.main()
