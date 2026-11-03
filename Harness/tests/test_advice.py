"""Acceptance tests for P2: advice always carries a source, chosen by code. Cases: data/acceptance_advice.jsonl.

    python -m unittest tests.test_advice -v

Rules under test:
  - the same question always gets the same guideline (deterministic picker)
  - every guideline has Thai and English text, a named source and a real https link
  - an advice reply ends with that guideline's source and link, built from the catalog (never by the model)
  - a different [Gxx] written by the model is removed; a tip the model never fetched is added by code
No model or network: the model is a scripted fake.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS / "budget_coach"))

import advice  # noqa: E402
import agent  # noqa: E402
import coach_server  # noqa: E402
import language  # noqa: E402
import tips_review  # noqa: E402

CASES = [json.loads(x) for x in (HARNESS / "data" / "acceptance_advice.jsonl").read_text("utf-8").splitlines() if x.strip()]


def tool_reply(name, args):
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c0", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
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


def routed(question, *model_replies, facts=None):
    ctx = agent.DEFAULT_CONTEXT
    if facts is not None:
        ctx = agent.Context(**{**ctx.__dict__, "advice_facts": lambda: facts})
    chat = Scripted(*model_replies)
    cls = {"intent": "advice", "ok": True, "latency": 0.0, "error": None}
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(advice, "MISSES_PATH", Path(tmp) / "misses.jsonl"), \
            mock.patch.object(agent.router, "classify", return_value=cls), mock.patch.object(agent, "_chat", chat), \
            mock.patch.object(agent, "LOG") as log:
        r = agent.answer_routed(question, ctx=ctx)
    return r, chat, log


class CatalogTests(unittest.TestCase):
    def test_every_guideline_is_complete(self):
        self.assertGreaterEqual(len(advice.CATALOG), 11)
        for gid, g in advice.CATALOG.items():
            self.assertTrue(g["tip"].strip() and g["source"].strip(), gid)
            self.assertTrue(language.THAI.search(g["tip_th"]), f"{gid} has no Thai tip")
            links = [x for x in (g.get("url"), g.get("read_more")) if x]
            self.assertTrue(links, f"{gid} has no link at all")
            for link in links:
                self.assertTrue(link.startswith("https://"), (gid, link))
            self.assertTrue(g.get("checked_by_hand"), f"{gid} has not been checked by a person")

    def test_gold_ids_used_by_the_eval_still_exist(self):
        for gid in ("G01", "G02", "G03", "G04", "G05", "G06", "G07", "G08"):
            self.assertIn(gid, advice.CATALOG)


class PickerTests(unittest.TestCase):
    def test_every_case_picks_its_guideline(self):
        for c in CASES:
            self.assertEqual(advice.pick(c["question"]), c["gid"], c["id"])

    def test_same_question_same_answer(self):
        for c in CASES:
            self.assertEqual({advice.pick(c["question"]) for _ in range(5)}, {c["gid"]})

    def test_falls_back_on_the_students_numbers(self):
        vague = "Any advice for me?"
        self.assertEqual(advice.pick(vague, {"over_budget": ["entertainment"]}), "G06")
        self.assertEqual(advice.pick(vague, {"over_budget": ["subscriptions", "food"]}), "G03")
        self.assertEqual(advice.pick(vague, {"has_budget": False}), "G05")
        self.assertEqual(advice.pick(vague, {"has_budget": True, "over_budget": [], "net": -3289}), "G01")
        self.assertEqual(advice.pick(vague, {}), advice.DEFAULT_GID)


class FooterTests(unittest.TestCase):
    def test_footer_names_the_source_and_link_in_the_right_language(self):
        en, th = advice.footer("G04", "en"), advice.footer("G04", "th")
        self.assertIn("Source:", en)
        self.assertIn("แหล่งอ้างอิง:", th)
        for out in (en, th):
            self.assertIn(advice.CATALOG["G04"]["source"], out)
            self.assertIn(advice.CATALOG["G04"]["url"], out)
            self.assertIn("[G04]", out)

    def test_book_without_a_link_shows_its_read_more_link(self):
        out = advice.footer("G06", "en")
        self.assertIn("Dave Ramsey", out)
        self.assertIn(advice.CATALOG["G06"]["read_more"], out)

    def test_two_links_when_a_guideline_has_both(self):
        out = advice.footer("G02", "en")
        self.assertIn(advice.CATALOG["G02"]["url"], out)
        self.assertIn(advice.CATALOG["G02"]["read_more"], out)


class RoutedAdviceTests(unittest.TestCase):
    Q = "How can I make sure I actually save something each month?"   # -> G04

    def test_reply_ends_with_the_source_and_logs_the_citation(self):
        r, chat, log = routed(self.Q, tool_reply("lookup_guideline", {"guideline_id": "G04"}),
                              text_reply("Move a fixed share to savings the day your money arrives."))
        self.assertTrue(r["answer"].endswith(advice.footer("G04", "en")))
        self.assertEqual(r["source"]["id"], "G04")
        self.assertNotIn("source_added", r["flags"])
        asked = chat.requests[0][0]["content"]
        self.assertIn("guideline G04", asked)
        q = [c for c in log.write.call_args_list if c.args[0] == "coach_question"][0]
        self.assertEqual(q.kwargs["cited_guideline"], "G04")

    def test_a_tip_the_model_never_fetched_is_added_by_code(self):
        r, _, _ = routed(self.Q, tool_reply("get_budget", {"category": "food"}), text_reply("Save early each month."))
        self.assertIn("source_added", r["flags"])
        self.assertIn(advice.CATALOG["G04"]["tip"], r["answer"])
        self.assertTrue(r["answer"].endswith(advice.footer("G04", "en")))

    def test_a_different_guideline_from_the_model_is_overridden(self):
        r, _, _ = routed(self.Q, tool_reply("lookup_guideline", {"guideline_id": "G01"}),
                         text_reply("Use the 50/30/20 split [G01] on your income."))
        self.assertIn("source_overridden", r["flags"])
        self.assertNotIn("[G01]", r["answer"])
        self.assertIn("[G04]", r["answer"])

    def test_thai_question_gets_a_thai_footer(self):
        q = "มีวิธีติดตามรายจ่ายง่ายๆ ไหม"   # -> G05
        r, _, _ = routed(q, tool_reply("lookup_guideline", {"guideline_id": "G05"}),
                         text_reply("จดรายรับรายจ่ายทุกวันเพื่อให้เห็นว่าเงินไปไหนบ้าง"))
        self.assertTrue(r["answer"].endswith(advice.footer("G05", "th")))
        self.assertIn("แหล่งอ้างอิง:", r["answer"])

    def test_the_students_numbers_choose_the_tip_when_the_question_is_vague(self):
        r, _, _ = routed("Any advice for me?", tool_reply("lookup_guideline", {"guideline_id": "G06"}),
                         text_reply("Spread your flexible money across the weeks."),
                         facts={"over_budget": ["entertainment"], "has_budget": True, "net": -3289})
        self.assertEqual(r["source"]["id"], "G06")

    def test_an_error_in_the_facts_does_not_break_advice(self):
        def boom():
            raise RuntimeError("db down")
        ctx = agent.Context(**{**agent.DEFAULT_CONTEXT.__dict__, "advice_facts": boom})
        chat = Scripted(tool_reply("lookup_guideline", {"guideline_id": "G04"}), text_reply("Save first."))
        cls = {"intent": "advice", "ok": True, "latency": 0.0, "error": None}
        with mock.patch.object(agent.router, "classify", return_value=cls), mock.patch.object(agent, "_chat", chat), \
                mock.patch.object(agent, "LOG"):
            r = agent.answer_routed("Any advice for me?", ctx=ctx)
        self.assertEqual(r["source"]["id"], "G04")

    def test_data_questions_get_no_source_footer(self):
        cls = {"intent": "trend", "ok": True, "latency": 0.0, "error": None}
        chat = Scripted(tool_reply("get_budget", {"category": "food"}), text_reply("Your food budget is there."))
        with mock.patch.object(agent.router, "classify", return_value=cls), mock.patch.object(agent, "_chat", chat), \
                mock.patch.object(agent, "LOG"):
            r = agent.answer_routed("What is my food budget?")
        self.assertNotIn("Source:", r["answer"])
        self.assertNotIn("source", r)


class NoTopicMatchTests(unittest.TestCase):
    VAGUE = "Any advice on spending less?"

    def ask(self, question, lang_reply):
        chat = Scripted(tool_reply("lookup_guideline", {"guideline_id": "G06"}), text_reply(lang_reply))
        cls = {"intent": "advice", "ok": True, "latency": 0.0, "error": None}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "misses.jsonl"
            with mock.patch.object(advice, "MISSES_PATH", path), mock.patch.object(agent.router, "classify", return_value=cls), \
                    mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
                r = agent.answer_routed(question, ctx=agent.Context(**{**agent.DEFAULT_CONTEXT.__dict__,
                                        "advice_facts": lambda: {"over_budget": ["food"], "has_budget": True}}))
            rows = [json.loads(x) for x in path.read_text("utf-8").splitlines()] if path.exists() else []
        return r, rows

    def test_a_general_tip_says_so_and_the_question_is_queued(self):
        r, rows = self.ask(self.VAGUE, "Spread your flexible money across the weeks.")
        self.assertIn("no_topic_match", r["flags"])
        self.assertIn(advice.NO_MATCH_NOTE["en"], r["answer"])
        self.assertTrue(r["answer"].endswith(advice.footer("G06", "en")))
        self.assertEqual([(x["question"], x["served"], x["lang"]) for x in rows], [(self.VAGUE, "G06", "en")])

    def test_thai_note_for_a_thai_question(self):
        r, rows = self.ask("ช่วยแนะนำหน่อย", "ลองแบ่งเงินเป็นงบรายสัปดาห์ เพื่อไม่ให้ใช้เงินล่วงหน้า")
        self.assertIn(advice.NO_MATCH_NOTE["th"], r["answer"])
        self.assertEqual(rows[0]["lang"], "th")

    def test_a_matched_topic_has_no_note_and_is_not_queued(self):
        r, rows = self.ask("How can I make sure I actually save something each month?", "Save early.")
        self.assertNotIn("no_topic_match", r["flags"])
        self.assertNotIn(advice.NO_MATCH_NOTE["en"], r["answer"])
        self.assertEqual(rows, [])

    def test_an_unwritable_miss_log_does_not_break_the_answer(self):
        with mock.patch.object(advice, "MISSES_PATH", Path("/nonexistent-root-xyz/a/b.jsonl")):
            advice.log_miss("q", "G04", "en")  # must not raise

    def test_an_approved_tip_with_a_match_pattern_becomes_findable(self):
        original = advice.CATALOG
        try:
            advice.CATALOG = {**original, "G99": {**original["G04"], "id": "G99", "match": r"delivery|เดลิเวอรี่"}}
            self.assertEqual(advice.pick_match("How do I stop ordering food delivery so much?"), ("G99", True))
            self.assertEqual(advice.pick_match("ค่าเดลิเวอรี่แพง"), ("G99", True))
            self.assertEqual(advice.pick_match("How can I make sure I save something?")[0], "G04")  # built-ins first
        finally:
            advice.CATALOG = original


class ReviewQueueTests(unittest.TestCase):
    GOOD = {"pending_id": "P01", "topic": "food delivery", "match": "delivery", "title": "Plan delivery orders",
            "tip": "Set a weekly cap for delivery.", "tip_th": "ตั้งเพดานค่าเดลิเวอรี่รายสัปดาห์",
            "source": "Example Org: page", "url": "https://example.org/page", "evidence": "a short quote"}

    def test_a_complete_candidate_becomes_the_next_guideline(self):
        catalog = json.loads((HARNESS / "budget_coach" / "guidelines.json").read_text("utf-8"))
        entry = tips_review.approve(self.GOOD, catalog, today="2026-11-02")
        self.assertEqual(entry["id"], "G12")
        self.assertEqual(entry["checked_by_hand"], "2026-11-02")
        self.assertEqual(entry["match"], "delivery")
        self.assertNotIn("evidence", entry)

    def test_an_incomplete_candidate_cannot_be_approved(self):
        for bad in ({**self.GOOD, "url": "http://insecure.example"}, {**self.GOOD, "tip_th": "english only"},
                    {**self.GOOD, "evidence": ""}, {**self.GOOD, "match": "(unclosed"}):
            with self.assertRaises(ValueError):
                tips_review.approve(bad, [{"id": "G11"}])


class AppReplyTests(unittest.TestCase):
    def test_shape_carries_the_chosen_source_and_links(self):
        r, _, _ = routed("How can I make sure I actually save something each month?",
                         tool_reply("lookup_guideline", {"guideline_id": "G01"}), text_reply("Split it."))
        tip = coach_server.shape(r)["tip"]
        self.assertEqual(tip["id"], "G04")  # the chosen one, not the one the model happened to fetch
        self.assertEqual(tip["url"], advice.CATALOG["G04"]["url"])


if __name__ == "__main__":
    unittest.main()
