"""Offline tests for the 10-persona coach: loader vs ground truth, user isolation, tools, routing.

    python -m unittest discover -s tests -v

Skipped when persona/csv is absent (persona/ must be committed for CI to run them). No model or
network is used: the loop runs against a scripted fake.
"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

COACH = Path(__file__).resolve().parent.parent / "budget_coach"
sys.path.insert(0, str(COACH))

import agent  # noqa: E402
import persona_agent  # noqa: E402
import persona_data  # noqa: E402
import router  # noqa: E402
from harness.logger import JsonlLogger  # noqa: E402

HAVE_DATA = persona_data.available() and (persona_data.PERSONA_DIR.parent / "ground_truth.json").exists()
GROUND_TRUTH = (json.loads((persona_data.PERSONA_DIR.parent / "ground_truth.json").read_text("utf-8"))["personas"]
                if HAVE_DATA else [])


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
        self.requests.append({"messages": list(messages), "tools": [t["function"]["name"] for t in tool_defs]})
        return self.replies.pop(0)


@unittest.skipUnless(HAVE_DATA, "persona/csv not present")
class LoaderMatchesGroundTruth(unittest.TestCase):
    def test_every_persona_month_and_category_matches(self):
        mismatches, checked = [], 0
        for p in GROUND_TRUTH:
            d = persona_data.PersonaData(p["user_id"])
            for month, gt in p["months"].items():
                for cat, want in gt["spending_by_category"].items():
                    checked += 1
                    if abs(d.sum_by_category(month, cat) - want) > 0.011:
                        mismatches.append((p["key"], month, cat))
                s = d.month_summary(month)
                for k in ("income_total", "spending_total", "net_cashflow", "refunds_total"):
                    checked += 1
                    if abs(s[k] - gt[k]) > 0.011:
                        mismatches.append((p["key"], month, k))
        self.assertEqual(checked, 10 * 6 * (8 + 4))  # personas x months x (categories + summary fields)
        self.assertEqual(mismatches, [])

    def test_over_budget_and_limits_match(self):
        for p in GROUND_TRUTH:
            if p["budgets"] is None:
                continue
            d = persona_data.PersonaData(p["user_id"])
            for cat, limit in p["budgets"].items():
                self.assertAlmostEqual(d.get_budget(cat), limit, places=2, msg=f"{p['key']} {cat}")
            for month, gt in p["months"].items():
                got = {o["category"]: o["over_by"] for o in d.over_budget(month)}
                want = {c: gt["budget"][c]["over_by"] for c in gt["over_budget_categories"]}
                self.assertEqual(got.keys(), want.keys(), f"{p['key']} {month}")
                for c in got:
                    self.assertAlmostEqual(got[c], want[c], places=2)

    def test_compare_months_matches_previous_month_block(self):
        gt = GROUND_TRUTH[0]
        d = persona_data.PersonaData(gt["user_id"])
        want = gt["months"]["2026-10"]["vs_previous_month"]["food"]
        got = d.compare_months("2026-09", "2026-10", "food")
        self.assertEqual((got["m1_total"], got["m2_total"]), (want["prev"], want["curr"]))
        self.assertAlmostEqual(got["diff"], want["delta"], places=2)


@unittest.skipUnless(HAVE_DATA, "persona/csv not present")
class CountingRules(unittest.TestCase):
    def rows_for(self, user_id):
        with open(persona_data.PERSONA_DIR / "Transaction.csv", encoding="utf-8") as f:
            return [r for r in csv.DictReader(f) if int(r["userId"]) == user_id]

    def test_soft_deleted_rows_are_ignored(self):
        for p in GROUND_TRUTH:
            raw = self.rows_for(p["user_id"])
            live = [r for r in raw if not r["deletedAt"]]
            self.assertLess(len(live), len(raw), "fixture should contain soft-deleted rows")
            self.assertEqual(len(persona_data.PersonaData(p["user_id"]).rows), len(live))

    def test_transfers_are_never_spending_or_income(self):
        d = persona_data.PersonaData(1)
        self.assertTrue(any(r["type"] == "transfer" for r in d.rows))
        for month in d.months():
            per_category = sum(d.sum_by_category(month, c) for c in d.expense_categories)
            self.assertAlmostEqual(per_category, d.month_summary(month)["spending_total"], places=2)

    def test_refund_reduces_its_category(self):
        fern = persona_data.PersonaData(4)
        month = next(m for m in fern.months() if fern.month_summary(m)["refunds_total"] > 0)
        gross = sum(r["amount"] for r in fern._month_rows(month) if r["type"] == "expense")
        self.assertLess(fern.month_summary(month)["spending_total"], gross)

    def test_persona_without_budgets_gets_clear_errors(self):
        tae = persona_data.PersonaData(7)
        with self.assertRaisesRegex(ValueError, "not set any budgets"):
            tae.over_budget("2026-10")
        with self.assertRaisesRegex(ValueError, "no budget is set"):
            tae.get_budget("food")

    def test_unknown_month_and_category_raise(self):
        d = persona_data.PersonaData(1)
        with self.assertRaises(ValueError):
            d.sum_by_category("2020-01", "food")
        with self.assertRaises(ValueError):
            d.sum_by_category("2026-10", "crypto")

    def test_get_transactions_returns_only_live_expenses_for_this_user(self):
        d = persona_data.PersonaData(1)
        rows = d.get_transactions("2026-10", "food")
        self.assertTrue(rows)
        self.assertLessEqual(len(rows), persona_data.MAX_ROWS)
        self.assertAlmostEqual(sum(r["amount"] for r in rows),
                               sum(r["amount"] for r in d._month_rows("2026-10")
                                   if r["type"] == "expense" and r["category"] == "food"), places=2)


@unittest.skipUnless(HAVE_DATA, "persona/csv not present")
class UsersAndContext(unittest.TestCase):
    def test_resolve_user_by_id_and_key(self):
        self.assertEqual(persona_data.resolve_user("3"), 3)
        self.assertEqual(persona_data.resolve_user("bank"), 3)
        self.assertEqual(persona_data.resolve_user(7), 7)
        with self.assertRaises(ValueError):
            persona_data.resolve_user("nobody")

    def test_ten_users_listed(self):
        self.assertEqual([u["user_id"] for u in persona_data.list_users()], list(range(1, 11)))

    def test_model_cannot_pick_another_user(self):
        ctx, _ = persona_agent.build_context(1)
        with self.assertRaises(TypeError):
            ctx.run_tool("sum_by_category", {"month": "2026-10", "category": "food", "user_id": 2})

    def test_unknown_tool_and_hidden_raw_tool_are_rejected(self):
        ctx, _ = persona_agent.build_context(1)
        with self.assertRaises(ValueError):
            ctx.run_tool("drop_tables", {})
        with self.assertRaises(ValueError):
            ctx.run_tool("get_transactions", {"month": "2026-10"}, raw=False)

    def test_context_describes_this_persona(self):
        ctx, data = persona_agent.build_context("mint")
        self.assertIn('"this month" = 2026-10', ctx.system)
        self.assertIn("bills", ctx.system)
        self.assertNotIn("has not set any budgets", ctx.system)
        names = [t["function"]["name"] for t in ctx.tools]
        self.assertIn("month_summary", names)
        self.assertIn("decline", names)
        enum = next(t for t in ctx.tools if t["function"]["name"] == "sum_by_category")
        self.assertEqual(enum["function"]["parameters"]["properties"]["category"]["enum"],
                         list(data.expense_categories))

    def test_persona_without_budgets_gets_a_prompt_rule(self):
        ctx, _ = persona_agent.build_context("tae")
        self.assertIn("has not set any budgets", ctx.system)


@unittest.skipUnless(HAVE_DATA, "persona/csv not present")
class AgentLoopOnPersonas(unittest.TestCase):
    def setUp(self):
        self.log_path = Path(tempfile.mkdtemp()) / "coach.jsonl"
        patch = mock.patch.object(agent, "LOG", JsonlLogger(self.log_path))
        patch.start()
        self.addCleanup(patch.stop)

    def test_loop_uses_the_persona_tools_and_system_prompt(self):
        ctx, data = persona_agent.build_context(1)
        spent = data.month_summary("2026-10")
        chat = Scripted(tool_reply("month_summary", {"month": "2026-10"}),
                        text_reply(f"You spent {spent['spending_total']:,.0f} and net {spent['net_cashflow']:,.0f}."))
        with mock.patch.object(agent, "_chat", chat):
            r = agent.run("total this month?", "m", False, ctx=ctx)
        self.assertNotIn("validator_fallback", r["flags"])
        self.assertIn("2026-10", chat.requests[0]["messages"][0]["content"])
        self.assertIn("month_summary", chat.requests[0]["tools"])
        self.assertEqual(r["calls"][0]["name"], "month_summary")

    def test_validator_rejects_a_number_not_in_the_persona_tool_result(self):
        ctx, _ = persona_agent.build_context(1)
        chat = Scripted(tool_reply("month_summary", {"month": "2026-10"}), text_reply("You spent 1 baht."),
                        text_reply("Still 2 baht."))
        with mock.patch.object(agent, "_chat", chat):
            r = agent.run("total this month?", "m", False, ctx=ctx)
        self.assertIn("validator_fallback", r["flags"])

    def test_month_summary_counts_as_a_data_tool(self):
        ctx, _ = persona_agent.build_context(1)
        chat = Scripted(tool_reply("month_summary", {"month": "2026-10"}), text_reply("Done."))
        with mock.patch.object(agent, "_chat", chat):
            r = agent.run("total?", "m", False, ctx=ctx)
        self.assertNotIn("no_tool", r["flags"])

    def test_answer_persona_logs_dataset_and_user(self):
        cls = {"intent": "investment", "ok": True, "latency": 0.1, "error": None}
        with mock.patch.object(router, "classify", return_value=cls) as classify:
            r = persona_agent.answer_persona("buy crypto?", "ploy")
        self.assertEqual(r["route"], "refuse")
        self.assertIn("bills", classify.call_args.kwargs["hint"])
        lines = [json.loads(x) for x in self.log_path.read_text(encoding="utf-8").splitlines()]
        q = next(x for x in lines if x["event"] == "coach_question")
        self.assertEqual((q["dataset"], q["user_id"]), ("persona", 2))

    def test_original_default_context_is_unchanged(self):
        self.assertIs(agent.DEFAULT_CONTEXT.system, agent.SYSTEM)
        self.assertNotIn("month_summary", [t["function"]["name"] for t in agent.DEFAULT_CONTEXT.tools])
        self.assertEqual(agent.DEFAULT_CONTEXT.classifier_hint, "")


@unittest.skipUnless(HAVE_DATA, "persona/csv not present")
class EvalQuestions(unittest.TestCase):
    def test_questions_cover_every_persona_and_skip_budget_for_tae(self):
        import eval_persona
        qs = eval_persona.all_questions()
        self.assertEqual(len(qs), 59)
        self.assertEqual({q["user_id"] for q in qs}, set(range(1, 11)))
        self.assertFalse([q for q in qs if q["user_id"] == 7 and q["kind"] == "over"])

    def test_grader_finds_a_negative_number_in_the_reply(self):
        import eval_agent
        self.assertTrue(eval_agent.has("เหลือ -3,289 บาท", -3289.0))
        self.assertTrue(eval_agent.has("left 3,289 baht", -3289.0))
        self.assertFalse(eval_agent.has("left 3,000 baht", -3289.0))

    def test_gold_comes_from_ground_truth(self):
        import eval_persona
        q = next(x for x in eval_persona.all_questions({1}) if x["kind"] == "summary")
        self.assertEqual(q["check"], [15089.0, -3289.0])


if __name__ == "__main__":
    unittest.main()
