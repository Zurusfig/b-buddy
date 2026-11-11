"""Tests for the problems the 4 November UAT showed (speed, casual Thai, no data, unclear question, advice match).

    python -m unittest tests.test_uat_fixes -v

Every test is offline: the model calls are replaced, so these run in CI without Ollama.
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
import breakdown  # noqa: E402
import clarify  # noqa: E402
import gaps  # noqa: E402
import interpret  # noqa: E402
import lookup_reply  # noqa: E402
import persona_agent  # noqa: E402
import router  # noqa: E402

CLS = {"intent": "trend", "ok": True, "latency": 0.0, "error": None}


def tool_reply(name, args):
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
        "finish_reason": "tool_calls"}], "usage": {"completion_tokens": 3}}


class SpeedTests(unittest.TestCase):
    def test_classifier_and_answer_use_the_same_context_size(self):
        """Ollama reloads the model when num_ctx changes: 3 s a switch, two switches a question (UAT: 8.3 s classifier)."""
        sent = []

        def fake_post(url, json=None, **kw):
            sent.append(json["options"]["num_ctx"])
            r = mock.Mock()
            r.raise_for_status = lambda: None
            r.json = lambda: {"message": {"content": '{"intent": "trend"}', "role": "assistant"}}
            return r

        with mock.patch.object(router.requests, "post", fake_post):
            router.classify("how much did I spend on food last month?")
        with mock.patch.object(agent.requests, "post", fake_post):
            try:
                agent._chat_ollama(agent.SMALL_MODEL, [{"role": "user", "content": "hi"}], False, [])
            except Exception:
                pass  # the fake reply is not a full chat reply; only the options sent matter
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0], sent[1])


class KnownGapTests(unittest.TestCase):
    """Tools raise gaps.DataGap, which carries its kind and facts as fields. Nothing reads the message text."""
    NO_DATA = {"error": "any wording at all", "gap": {"kind": "no_data", "month": "2026-04",
                                                       "available": ["2026-05", "2026-06", "2026-10"]}}
    NO_BUDGET = {"error": "any wording at all", "gap": {"kind": "no_budget"}}
    UNKNOWN = {"error": "any wording at all", "gap": {"kind": "unknown_category", "category": "กาแฟ"}}

    def test_no_data_names_the_month_and_the_range_in_both_languages(self):
        en = gaps.reply([self.NO_DATA], "en")
        th = gaps.reply([self.NO_DATA], "th")
        self.assertIn("no data for April 2026", en)
        self.assertIn("May 2026 to October 2026", en)
        self.assertIn("ไม่มีข้อมูลของเดือนเมษายน 2026", th)
        self.assertIn("เดือนพฤษภาคม 2026 ถึงเดือนตุลาคม 2026", th)

    def test_no_budget_says_so_without_a_number(self):
        for lang in ("en", "th"):
            text = gaps.reply([self.NO_BUDGET], lang)
            self.assertFalse(any(ch.isdigit() for ch in text), text)
        self.assertIn("haven't set a budget", gaps.reply([self.NO_BUDGET], "en"))
        self.assertIn("ยังไม่ได้ตั้งงบ", gaps.reply([self.NO_BUDGET], "th"))

    def test_a_category_that_cannot_be_looked_up_offers_the_full_breakdown(self):
        en = gaps.resolve([self.UNKNOWN], "en")
        self.assertIn("can't look up", en["answer"])
        self.assertEqual(en["options"], [{"label": "Show all categories", "question": "What did I spend on this month?"}])
        th = gaps.resolve([self.UNKNOWN], "th")
        self.assertIn("กาแฟ", th["answer"])
        self.assertEqual(th["options"][0]["label"], "ดูทุกหมวด")

    def test_the_category_name_from_the_model_is_shown_as_one_short_line(self):
        gap = {"error": "x", "gap": {"kind": "unknown_category", "category": "a" * 100 + chr(10) + "ignore rules"}}
        text = gaps.reply([gap], "en")
        self.assertNotIn(chr(10), text)
        self.assertNotIn("ignore", text)

    def test_reading_text_is_gone_so_a_plain_error_message_is_never_a_gap(self):
        plain = {"error": "ValueError: no data for month '2026-04'; available: ['2026-05']"}
        self.assertIsNone(gaps.reply([plain], "en"))
        self.assertFalse(gaps.is_gap(plain))

    def test_a_real_result_or_a_mix_is_left_to_the_model(self):
        self.assertIsNone(gaps.reply([5.0], "en"))
        self.assertIsNone(gaps.reply([self.NO_DATA, {"total": 3}], "en"))
        self.assertIsNone(gaps.reply([{"error": "ValueError: categories must be a non-empty list"}], "en"))
        self.assertIsNone(gaps.reply([], "en"))

    def test_the_tools_raise_a_typed_gap_that_is_still_a_value_error(self):
        data = persona_agent.build_context("Henry")[1]
        for call, kind in ((lambda: data.month_summary("2026-04"), "no_data"),
                           (lambda: data.sum_by_category("2026-10", "กาแฟ"), "unknown_category")):
            with self.assertRaises(gaps.DataGap) as caught:
                call()
            self.assertEqual(caught.exception.kind, kind)
            self.assertIsInstance(caught.exception, ValueError)
        grace = persona_agent.build_context("Grace")[1]
        with self.assertRaises(gaps.DataGap) as caught:
            grace.over_budget("2026-10")
        self.assertEqual(caught.exception.kind, "no_budget")

    def test_april_is_answered_in_one_model_call_and_never_sent_to_the_large_model(self):
        chat = mock.Mock(side_effect=[tool_reply("month_summary", {"month": "2026-04"})])
        with mock.patch.object(agent.router, "classify", return_value=CLS), mock.patch.object(agent, "_chat", chat),                 mock.patch.object(agent, "LOG"):
            r = persona_agent.answer_persona("How much did I spend in April?", "Henry")
        self.assertEqual(chat.call_count, 1, "the tool already said there is no data")
        self.assertEqual(r["route"], "small")
        self.assertEqual(r["escalated_by"], [])
        self.assertIn("known_gap", r["flags"])
        self.assertNotIn("tool_error", r["flags"])
        self.assertIn("no data for April 2026", r["answer"])

    def test_a_thai_account_with_no_budgets_gets_a_thai_reply(self):
        chat = mock.Mock(side_effect=[tool_reply("over_budget", {"month": "2026-10"})])
        with mock.patch.object(agent.router, "classify", return_value=CLS), mock.patch.object(agent, "_chat", chat),                 mock.patch.object(agent, "LOG"):
            r = persona_agent.answer_persona("เดือนนี้ฉันใช้เงินเกินบัทเจ็ทไหม", "Grace")
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(r["route"], "small")
        self.assertIn("ยังไม่ได้ตั้งงบ", r["answer"])

    def test_an_unknown_category_gets_the_button_and_no_second_model_call(self):
        chat = mock.Mock(side_effect=[tool_reply("sum_by_category", {"month": "2026-10", "category": "กาแฟ"})])
        with mock.patch.object(agent.router, "classify", return_value=CLS), mock.patch.object(agent, "_chat", chat),                 mock.patch.object(agent, "LOG"):
            r = persona_agent.answer_persona("เดือนนี้ค่ากาแฟเท่าไหร่", "Henry")
        self.assertEqual((chat.call_count, r["escalated_by"]), (1, []))
        self.assertIn("known_gap", r["flags"])
        self.assertEqual(r["options"][0]["question"], "เดือนนี้ใช้เงินไปกับอะไรบ้าง")


class BreakdownTests(unittest.TestCase):
    def test_one_call_lists_every_category_and_adds_up_to_the_month_total(self):
        data = persona_agent.build_context("Henry")[1]
        out = data.spending_by_category("2026-10")
        self.assertEqual(set(out["by_category"]), set(data.expense_categories))
        self.assertAlmostEqual(out["total"], data.month_summary("2026-10")["spending_total"], places=2)
        self.assertEqual(out["by_category"]["food"], data.sum_by_category("2026-10", "food"))

    def test_the_model_is_offered_the_tool_and_told_when_to_use_it(self):
        ctx, _ = persona_agent.build_context("Henry")
        names = [t["function"]["name"] for t in ctx.tools]
        self.assertIn("spending_by_category", names)
        self.assertIn("ใช้เงินไปกับอะไรบ้าง", ctx.system)
        self.assertEqual(ctx.run_tool("spending_by_category", {"month": "2026-10"})["month"], "2026-10")


class JudgmentTests(unittest.TestCase):
    def test_unclear_judgments_ask_back_with_the_month_named(self):
        for q in ("Did July hurt?", "Hey Is did I spend too much in July?"):
            need = clarify.needs(q)
            self.assertEqual(need["reason"], "judgment", q)
            self.assertEqual([o["question"] for o in need["options"]],
                             ["Give me a summary of July", "Which categories am I over budget on in July?"])
        th = clarify.needs("เดือนมิถุนายนเยอะไปไหม")
        self.assertEqual(th["reason"], "judgment")
        self.assertEqual(th["options"][0]["question"], "สรุปเดือนมิถุนายนให้หน่อย")

    def test_a_judgment_with_a_yardstick_is_answered_directly(self):
        for q in ("Did I spend too much on food?", "Am I over budget this month?", "Did the budget hurt?",
                  "How much did I spend on food last month?", "เดือนนี้ใช้เงินเกินบัทเจ็ทไหม"):
            self.assertIsNone(clarify.needs(q), q)

    def test_no_month_named_means_this_month(self):
        self.assertEqual(clarify.needs("Is this month okay?")["options"][0]["question"],
                         "Give me a summary of this month")

    def test_asking_back_costs_no_model_call(self):
        chat = mock.Mock()
        with mock.patch.object(agent.router, "classify", return_value={**CLS, "intent": "budget_check"}), \
                mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            r = persona_agent.answer_persona("Did July hurt?", "Henry")
        self.assertEqual((r["route"], r["model_calls"], chat.call_count), ("clarify", 0, 0))


class AdviceMatchTests(unittest.TestCase):
    def test_make_the_money_last_questions_find_the_envelope_tip_as_a_topic_match(self):
        for q in ("how should i use my money so that it could last until end of month?",
                  "gimme an advice for spending money so I can still have money by the end of this month",
                  "ทำยังไงให้เงินพอใช้ถึงสิ้นเดือน"):
            self.assertEqual(advice.pick_match(q), ("G06", True), q)

    def test_other_topics_still_go_to_their_own_tip(self):
        self.assertEqual(advice.pick_match("how big should my emergency fund be?")[0], "G02")
        self.assertEqual(advice.pick_match("should I cancel Netflix?")[0], "G03")


class ModelPicksTipWhenKeywordsMissTests(unittest.TestCase):
    Q = "I want a new laptop, how do I pay for it without wrecking my month?"  # no keyword in advice.KEYWORDS

    def ask(self, picked, tmp):
        chat = mock.Mock(side_effect=[tool_reply("lookup_guideline", {"guideline_id": picked}),
                                      {"choices": [{"message": {"role": "assistant", "content": "Set aside a little each week."},
                                                    "finish_reason": "stop"}], "usage": {"completion_tokens": 3}}])
        cls = {**CLS, "intent": "advice"}
        with mock.patch.object(agent.router, "classify", return_value=cls), mock.patch.object(agent, "_chat", chat),                 mock.patch.object(agent, "LOG"), mock.patch.object(advice, "MISSES_PATH", Path(tmp) / "m.jsonl"):
            r = persona_agent.answer_persona(self.Q, "Henry")
        path = Path(tmp) / "m.jsonl"
        return r, chat, (path.read_text(encoding="utf-8") if path.exists() else "")

    def test_the_menu_lists_every_tip_so_the_model_can_choose(self):
        self.assertEqual(advice.pick_match(self.Q)[1], False)
        for gid in advice.CATALOG:
            self.assertIn(f"{gid}: ", advice.menu())

    def test_a_tip_the_model_picked_is_used_and_cited_as_a_match(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r, chat, misses = self.ask("G09", tmp)
        self.assertIn("tip_chosen_by_model", r["flags"])
        self.assertNotIn("no_topic_match", r["flags"])
        self.assertEqual(r["source"]["id"], "G09")
        self.assertIn("[G09]", r["answer"])
        self.assertIn("G01: ", chat.call_args_list[0].args[2][0]["content"], "the menu is in the prompt")
        self.assertIn("laptop", misses, "the miss is still queued so a person can add a keyword")

    def test_an_id_that_is_not_in_the_catalog_is_ignored(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r, _, _ = self.ask("G99", tmp)
        self.assertNotIn("tip_chosen_by_model", r["flags"])
        self.assertNotEqual(r["source"]["id"], "G99")
        self.assertIn("no_topic_match", r["flags"])

    def test_a_keyword_match_never_shows_the_menu(self):
        chat = mock.Mock(side_effect=[tool_reply("lookup_guideline", {"guideline_id": "G02"}),
                                      {"choices": [{"message": {"role": "assistant", "content": "Save three months."},
                                                    "finish_reason": "stop"}], "usage": {"completion_tokens": 3}}])
        with mock.patch.object(agent.router, "classify", return_value={**CLS, "intent": "advice"}),                 mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            persona_agent.answer_persona("how big should my emergency fund be?", "Henry")
        self.assertNotIn("G01: ", chat.call_args_list[0].args[2][0]["content"])


class UnsureQuestionTests(unittest.TestCase):
    """The word list is the first net; this is the second: a spending question that asks for no amount and names
    no budget, limit, category or tip topic is unclear, whatever label the small router gave it."""
    UNCLEAR = ["Did I overdo it in June?", "Was August a disaster?", "Did I go crazy in September?",
               "ถูกไหมเดือนนี้", "เดือนที่แล้วหนักไปไหม", "เดือนนี้เปย์เยอะป่าว", "Am I doing okay with money lately?"]
    CLEAR = ["How much did I spend on food last month?", "What did I spend on in October?", "Am I over budget this month?",
             "Did I spend too much on food?", "Is my transport budget okay?", "เดือนที่แล้วเสียค่าข้าวไปเท่าไหร่",
             "เดือนนี้ใช้เงินเกินบัทเจ็ทไหม", "เค้าใช้เงินไปกับไรบ้างงับเตงมุม", "แยกหมวดค่าใช้จ่ายให้หน่อย",
             "Food plus transport last month, what's the total?", "ค่าวินเดือนสิงหาเท่าไหร่",
             "Hey what amount I spend in April this year?", "How much did I spend in April?"]

    def test_unclear_judgments_get_buttons_even_when_the_router_says_trend(self):
        for q in self.UNCLEAR:
            self.assertEqual((clarify.needs(q) or clarify.unsure(q) or {}).get("reason"), "judgment", q)

    def test_clear_questions_are_never_asked_back(self):
        for q in self.CLEAR:
            self.assertIsNone(clarify.needs(q) or clarify.unsure(q), q)

    def test_a_trend_label_with_no_amount_asked_goes_to_buttons_with_no_model_call(self):
        chat = mock.Mock()
        with mock.patch.object(agent.router, "classify", return_value=CLS), mock.patch.object(agent, "_chat", chat),                 mock.patch.object(agent, "LOG"):
            r = persona_agent.answer_persona("Was August a disaster?", "Henry")
        self.assertEqual((r["route"], chat.call_count), ("clarify", 0))
        self.assertEqual(r["options"][0]["question"], "Give me a summary of August")


class RouterWordingTests(unittest.TestCase):
    def test_buying_something_to_use_is_not_an_investment(self):
        self.assertIn("laptop", router.PROMPT)
        self.assertIn("not investment", router.PROMPT)
        self.assertIn("gold", router.PROMPT)  # real investment words are still listed

    def test_income_questions_are_in_scope(self):  # 500-question eval: "What was my income in August?" was refused
        self.assertIn("income", router.PROMPT)
        self.assertIn("never off_topic", router.PROMPT)


class AdviceThinkingTests(unittest.TestCase):
    Q = "how big should my emergency fund be?"

    def text(self, t):
        return {"choices": [{"message": {"role": "assistant", "content": t}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 3}}

    def ask(self, replies):
        chat = mock.Mock(side_effect=replies)
        with mock.patch.object(agent.router, "classify", return_value={**CLS, "intent": "advice"}),                 mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            return persona_agent.answer_persona(self.Q, "Henry"), chat

    def test_advice_thinks_off_first_and_stays_off_when_the_checks_pass(self):
        r, chat = self.ask([tool_reply("lookup_guideline", {"guideline_id": "G02"}), self.text("Save three months of costs.")])
        self.assertEqual([c.args[3] for c in chat.call_args_list], [False, False])  # args: key, model, messages, think
        self.assertEqual(r["escalated_by"], [])
        self.assertEqual(r["route"], "advice->large")

    def test_a_reply_with_a_made_up_number_is_redone_with_thinking_on(self):
        bad = self.text("Aim for 987654 baht.")
        r, chat = self.ask([tool_reply("lookup_guideline", {"guideline_id": "G02"}), bad, bad,  # off: retry, then fallback
                            tool_reply("lookup_guideline", {"guideline_id": "G02"}), self.text("Save three months of costs.")])
        thinks = [c.args[3] for c in chat.call_args_list]
        self.assertEqual(thinks[0], False)
        self.assertEqual(thinks[-1], True)
        self.assertIn("validator_fallback", r["escalated_by"])
        self.assertIn("three months", r["answer"])

    def test_a_down_gateway_is_not_retried_with_thinking_on(self):
        r, chat = self.ask([agent.LLMError("gateway_down")])
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(r["error"], "gateway_down")


class CodeWrittenBreakdownTests(unittest.TestCase):
    RESULT = {"month": "2026-10", "total": 6430.0, "by_category": {
        "food": 4093.0, "transport": 218.0, "shopping": 317.0, "entertainment": 296.0, "bills": 199.0,
        "education": 874.0, "health": 0.0, "other": 433.0}}

    def test_thai_labels_come_from_the_fixed_table_and_amounts_are_in_one_format(self):
        text = breakdown.render(self.RESULT, "th")
        for label in ("อาหาร: 4,093 บาท", "บันเทิง: 296 บาท", "บิลและค่าสาธารณูปโภค: 199 บาท"):
            self.assertIn(label, text)
        self.assertNotIn("เที่ยวบิน", text)
        self.assertIn("รวม 6,430 บาท", text)
        self.assertTrue(text.startswith("รายจ่ายเดือนตุลาคม 2026"))

    def test_english_lists_biggest_first_and_leaves_out_zero_categories(self):
        lines = breakdown.render(self.RESULT, "en").splitlines()
        self.assertEqual(lines[0], "Spending in October 2026")
        self.assertEqual(lines[1], "- Food: 4,093 baht")
        self.assertFalse(any("Health" in line for line in lines))
        self.assertEqual(lines[-1], "Total 6,430 baht")

    def test_cents_are_kept_only_when_there_are_cents(self):
        self.assertEqual(breakdown.money(4093.0), "4,093")
        self.assertEqual(breakdown.money(12.5), "12.50")

    def test_a_breakdown_question_is_answered_with_one_model_call_and_no_model_wording(self):
        chat = mock.Mock(side_effect=[tool_reply("spending_by_category", {"month": "2026-10"})])
        with mock.patch.object(agent.router, "classify", return_value=CLS), mock.patch.object(agent, "_chat", chat),                 mock.patch.object(agent, "LOG"):
            r = persona_agent.answer_persona("เค้าใช้เงินไปกับไรบ้างงับเตงมุม", "Henry")
        self.assertEqual((chat.call_count, r["model_calls"]), (1, 1))
        self.assertIn("code_reply", r["flags"])
        self.assertEqual(r["escalated_by"], [])
        self.assertIn("อาหาร: 4,093 บาท", r["answer"])

    def test_a_category_the_student_made_is_listed_and_the_total_still_adds_up(self):
        data = persona_agent.build_context("Henry")[1]
        data.category_type["กาแฟ"] = "expense"
        data.rows.append({"date": "2026-10-05", "amount": 120.0, "type": "expense", "description": "latte", "category": "กาแฟ"})
        out = data.spending_by_category("2026-10")
        self.assertEqual(out["by_category"]["กาแฟ"], 120.0)
        self.assertAlmostEqual(out["total"], data.month_summary("2026-10")["spending_total"], places=2)
        self.assertIn("- กาแฟ: 120 บาท", breakdown.render(out, "th"))
        self.assertIn("- กาแฟ: 120 baht", breakdown.render(out, "en"))

    def test_where_did_my_money_go_in_thai_is_answered_not_asked_back(self):
        for q in ("เดือนที่แล้วเงินหายไปไหนหมด", "เงินไปกับอะไรบ้างเดือนนี้"):
            self.assertIsNone(clarify.needs(q) or clarify.unsure(q), q)


class UnderstoodAndDoubtTests(unittest.TestCase):
    """Wrong readings cannot all be prevented, so they are made visible (the 'Looked up' line) and cheap to correct
    (ask back with buttons) instead of being guessed at."""
    MONTHS = ("2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10")
    REF = "2026-10"

    @staticmethod
    def call(name, **args):
        return {"name": name, "args": args, "result": 1.0}

    def test_the_line_says_what_was_looked_up_in_the_questions_language(self):
        food = [self.call("sum_by_category", month="2026-09", category="food")]
        self.assertEqual(interpret.line(food, "en"), "Looked up: Food, September 2026")
        self.assertEqual(interpret.line(food, "th"), "ดูข้อมูล: อาหาร เดือนกันยายน 2026")
        both = [self.call("sum_categories", month="2026-09", categories=["food", "transport"])]
        self.assertEqual(interpret.line(both, "en"), "Looked up: Food + Transport, September 2026")
        self.assertEqual(interpret.line([self.call("month_summary", month="2026-10")], "en"), "Looked up: Summary, October 2026")
        self.assertEqual(interpret.line([], "en"), "")

    def test_a_failed_lookup_is_not_listed(self):
        failed = [{"name": "month_summary", "args": {"month": "2026-04"}, "result": {"error": "x"}}]
        self.assertEqual(interpret.line(failed, "en"), "")

    def test_the_month_the_question_names_is_read_by_code(self):
        read = lambda q: interpret.named_months(q, self.MONTHS, self.REF)
        self.assertEqual(read("food last month?"), {"2026-09"})
        self.assertEqual(read("เดือนนี้ใช้ไปเท่าไหร่"), {"2026-10"})
        self.assertEqual(read("ค่าวินเดือนสิงหา"), {"2026-08"})
        self.assertEqual(read("July total"), {"2026-07"})
        self.assertEqual(read("how much did I spend on food?"), set())

    def test_the_wrong_month_the_wrong_category_or_a_total_for_a_list_is_doubted(self):
        d = lambda q, *calls: interpret.doubt(q, list(calls), self.MONTHS, self.REF)
        self.assertEqual(d("food last month?", self.call("sum_by_category", month="2026-10", category="food")), "month")
        self.assertEqual(d("ค่าวินเดือนสิงหา", self.call("month_summary", month="2026-08")), "category")
        self.assertEqual(d("เค้าใช้เงินไปกับไรบ้างงับ", self.call("month_summary", month="2026-10")), "list")

    def test_a_matching_answer_is_not_doubted(self):
        d = lambda q, *calls: interpret.doubt(q, list(calls), self.MONTHS, self.REF)
        self.assertIsNone(d("food last month?", self.call("sum_by_category", month="2026-09", category="food")))
        self.assertIsNone(d("เค้าใช้เงินไปกับไรบ้างงับ", self.call("spending_by_category", month="2026-10")))
        self.assertIsNone(d("compare June and July food", self.call("compare_months", m1="2026-06", m2="2026-07", category="food")))
        self.assertIsNone(d("how much did I spend in April?", {"name": "month_summary", "args": {"month": "2026-04"},
                                                                 "result": {"error": "x", "gap": {"kind": "no_data"}}}))

    def test_the_buttons_are_built_from_what_code_could_read(self):
        ask = interpret.reading("ค่าวินเดือนสิงหา", self.MONTHS, self.REF, "th")
        self.assertEqual(ask["options"][0], {"label": "เดินทาง, เดือนสิงหาคม 2026", "question": "ค่าเดินทางเดือนสิงหาคม 2026เท่าไหร่"})
        self.assertEqual(len(ask["options"]), 3)
        en = interpret.reading("hmm", self.MONTHS, self.REF, "en")
        self.assertEqual([o["label"] for o in en["options"]], ["All categories", "Over budget?"])

    def ask(self, question, calls_replies):
        chat = mock.Mock(side_effect=calls_replies)
        with mock.patch.object(agent.router, "classify", return_value=CLS), mock.patch.object(agent, "_chat", chat),                 mock.patch.object(agent, "LOG"):
            return persona_agent.answer_persona(question, "Henry"), chat

    def text(self, t):
        return {"choices": [{"message": {"role": "assistant", "content": t}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 3}}

    def test_a_total_given_for_a_list_question_becomes_an_ask_back_not_an_answer_or_an_escalation(self):
        r, chat = self.ask("เค้าใช้เงินไปกับไรบ้างงับเตงมุม", [tool_reply("month_summary", {"month": "2026-10"})])
        self.assertEqual((r["route"], r["escalated_by"], chat.call_count), ("clarify", [], 1))
        self.assertIn("doubt", r["flags"])
        self.assertEqual(r["calls"], [])
        self.assertTrue(r["options"])

    def test_a_normal_answer_ends_with_the_looked_up_line(self):
        # (month_summary used to be the example; code now writes that reply, so a comparison stands in)
        r, _ = self.ask("Did I spend more on food in September than in August?",
                        [tool_reply("compare_months", {"m1": "2026-08", "m2": "2026-09", "category": "food"}),
                         self.text("You spent a little more on food in September.")])
        self.assertEqual(r["route"], "small")
        self.assertTrue(r["answer"].endswith("\n\nLooked up: Food, August 2026 / September 2026"), r["answer"])

    def test_the_line_is_not_added_to_replies_code_wrote_or_to_advice(self):
        r, _ = self.ask("How much did I spend in April?", [tool_reply("month_summary", {"month": "2026-04"})])
        self.assertNotIn("Looked up", r["answer"])
        r, _ = self.ask("เค้าใช้เงินไปกับไรบ้างงับเตงมุม", [tool_reply("spending_by_category", {"month": "2026-10"})])
        self.assertNotIn("ดูข้อมูล", r["answer"])


class CodeWrittenLookupTests(unittest.TestCase):
    """UAT-05: the 4B model wrote 2,566 where the tool said 292 (twice), so the question cost 22 s and six model calls.
    For one matching figure, code writes the sentence and no model sees the number."""
    one = staticmethod(lambda **a: {"name": "sum_by_category", "args": a, "result": 292.0})
    ask = UnderstoodAndDoubtTests.ask
    text = UnderstoodAndDoubtTests.text

    def test_one_figure_in_both_languages(self):
        c = self.one(month="2026-08", category="transport")
        self.assertEqual(lookup_reply.render(c, "en"), "You spent 292 baht on Transport in August 2026.")
        self.assertEqual(lookup_reply.render(c, "th"), "เดือนสิงหาคม 2026 ค่าเดินทาง 292 บาท")

    def test_decimals_and_a_custom_category_are_shown_as_they_are(self):
        c = {"name": "sum_by_category", "args": {"month": "2026-10", "category": "Coffee"}, "result": 1234.5}
        self.assertEqual(lookup_reply.render(c, "en"), "You spent 1,234.50 baht on Coffee in October 2026.")

    def test_combined_total_lists_its_parts(self):
        c = {"name": "sum_categories", "args": {"month": "2026-09", "categories": ["food", "transport"]},
             "result": {"month": "2026-09", "categories": ["food", "transport"],
                        "by_category": {"food": 6064.0, "transport": 458.0}, "total": 6522.0}}
        self.assertEqual(lookup_reply.render(c, "en"),
                         "Food + Transport in September 2026: 6,522 baht in total (Food 6,064, Transport 458).")
        self.assertNotRegex(lookup_reply.render(c, "th"), "[A-Za-z]{2,}")

    def test_only_a_single_successful_lookup_applies(self):
        ok = self.one(month="2026-08", category="transport")
        self.assertTrue(lookup_reply.applies([ok]))
        self.assertFalse(lookup_reply.applies([ok, ok]))
        self.assertFalse(lookup_reply.applies([{**ok, "result": {"error": "x"}}]))
        self.assertFalse(lookup_reply.applies([{"name": "month_summary", "args": {"month": "2026-08"}, "result": {}}]))

    def test_the_model_is_not_asked_to_write_the_number(self):
        r, chat = self.ask("เราจ่ายค่าวินในเดือนสิงหาไปเท่าไหร่",
                           [tool_reply("sum_by_category", {"month": "2026-08", "category": "transport"})])
        self.assertEqual((r["route"], r["escalated_by"], chat.call_count), ("small", [], 1))
        self.assertIn("code_reply", r["flags"])
        self.assertEqual(r["answer"], "เดือนสิงหาคม 2026 ค่าเดินทาง 238 บาท")  # Henry's real August figure, from the tool

    def test_a_lookup_that_does_not_match_the_question_still_asks_back(self):
        r, _ = self.ask("food last month?", [tool_reply("sum_by_category", {"month": "2026-10", "category": "food"})])
        self.assertEqual(r["route"], "clarify")
        self.assertNotIn("code_reply", r["flags"])


if __name__ == "__main__":
    unittest.main()
