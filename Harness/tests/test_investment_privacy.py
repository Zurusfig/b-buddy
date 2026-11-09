"""Validator check 3 (no investment language) and the gateway privacy log/report.

    python -m unittest tests.test_investment_privacy -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(HARNESS / "budget_coach"))
sys.path.insert(0, str(HARNESS / "scripts"))

import agent  # noqa: E402
import privacy_report  # noqa: E402
import validator  # noqa: E402
from harness.logger import JsonlLogger  # noqa: E402

Q = "What is my food budget?"


def tool_reply(name="get_budget", args=None):
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": name, "arguments": json.dumps(args or {"category": "food"})}}]},
        "finish_reason": "tool_calls"}], "usage": {"completion_tokens": 3}}


def text_reply(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 3}}


class InvestmentTermsTests(unittest.TestCase):
    def test_investment_words_in_english_and_thai_are_found(self):
        for text, word in (("Put the rest into an index fund.", "index fund"), ("Consider buying gold.", "gold"),
                           ("You could invest 1,000 a month.", "invest"), ("Try Bitcoin.", "bitcoin"),
                           ("ลองซื้อหุ้นปันผลดู", "หุ้น"), ("ลองแบ่งไปลงทุนในกองทุนรวม", "กองทุน"),
                           ("ซื้อทองคำเก็บไว้", "ทองคำ"), ("ซื้อหวยทุกงวด", "หวย")):
            self.assertIn(word, validator.investment_terms(text), text)

    def test_budgeting_replies_pass(self):
        for text in ("Your food budget is 4,500.", "Build an emergency fund of 3-6 months of essentials.",
                     "Keep a rainy-day fund for repairs.", "เดือนนี้ใช้ค่าอาหารไป 4,093 บาท เกินงบ 93 บาท",
                     "Set a weekly limit for food delivery and cook at home twice a week."):
            self.assertEqual(validator.investment_terms(text), [], text)

    def test_a_word_that_is_the_users_own_data_is_allowed(self):
        calls = [{"name": "get_transactions", "args": {}, "result": [
            {"date": "2026-10-02", "amount": 900, "category": "bills", "description": "Car insurance"},
            {"date": "2026-10-03", "amount": 1500, "category": "shopping", "description": "Gold necklace"}]}]
        self.assertEqual(validator.investment_terms("You paid 1,500 for a gold necklace.", calls), [])
        self.assertEqual(validator.investment_terms("You could also buy stocks.", calls), ["stocks"])


class InvestmentRetryTests(unittest.TestCase):
    def test_investment_talk_gets_one_retry_and_a_clean_rewrite_passes(self):
        chat = mock.Mock(side_effect=[tool_reply(), text_reply("Your food budget is 4,500. Invest the rest in gold."),
                                      text_reply("Your food budget is 4,500.")])
        with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            r = agent.run(Q, agent.SMALL_MODEL, False)
        self.assertEqual(r["answer"], "Your food budget is 4,500.")
        self.assertEqual(r["validator_retries"], 1)
        retry_prompt = chat.call_args_list[2].args[2][-1]["content"]
        self.assertIn("investing", retry_prompt)
        self.assertNotIn("investment_language", r["flags"])

    def test_investment_talk_twice_falls_back_to_the_raw_tool_results(self):
        chat = mock.Mock(side_effect=[tool_reply(), text_reply("Budget 4,500. Buy stocks."),
                                      text_reply("Budget 4,500. Buy crypto.")])
        with mock.patch.object(agent, "_chat", chat), mock.patch.object(agent, "LOG"):
            r = agent.run(Q, agent.SMALL_MODEL, False)
        self.assertIn("investment_language", r["flags"])
        self.assertIn("validator_fallback", r["flags"])
        self.assertNotIn("crypto", r["answer"].lower())
        self.assertNotIn("stocks", r["answer"].lower())


class GatewayLogTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "calls.jsonl"
        self.patch = mock.patch.object(agent, "LOG", agent._RunLog(JsonlLogger(self.path)))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()

    def test_each_gateway_request_is_logged_with_its_exact_messages(self):
        http = mock.Mock(status_code=200)
        http.json.return_value = text_reply("ok")
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": Q}]
        with mock.patch.object(agent.requests, "post", return_value=http):
            agent._chat_once("k", agent.BIG_MODEL, messages, False, [tool_reply()["choices"][0]["message"]["tool_calls"][0]])
        rows = [json.loads(x) for x in self.path.read_text("utf-8").splitlines()]
        req = next(r for r in rows if r["event"] == "coach_gateway_request")
        self.assertEqual(req["messages"], messages)
        self.assertEqual(req["model"], agent.BIG_MODEL)

    def test_local_model_calls_are_not_logged_as_gateway_requests(self):
        http = mock.Mock(status_code=200)
        http.json.return_value = {"message": {"content": "ok"}, "done_reason": "stop", "eval_count": 1}
        with mock.patch.object(agent.requests, "post", return_value=http):
            agent._chat_once(None, agent.SMALL_MODEL, [{"role": "user", "content": Q}], False, [])
        events = [json.loads(x)["event"] for x in self.path.read_text("utf-8").splitlines()]
        self.assertNotIn("coach_gateway_request", events)


def gateway_request(messages, tools=("sum_by_category", "lookup_guideline"), run_id="r-1"):
    return {"ts": "2026-11-09T10:00:00", "event": "coach_gateway_request", "run_id": run_id,
            "model": "gemma-4-31b", "messages": messages, "tools": list(tools)}


class PrivacyReportTests(unittest.TestCase):
    QUESTION = "How can I stop running out of money?"

    def rows(self, request):
        return [{"event": "coach_question", "run_id": "r-1", "question": self.QUESTION}, request]

    def totals_only(self):
        return [{"role": "system", "content": "You are a budget coach. Data exists for 2026-05 to 2026-10."},
                {"role": "user", "content": self.QUESTION},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "a", "function": {"name": "over_budget"}}, {"id": "b", "function": {"name": "lookup_guideline"}}]},
                {"role": "tool", "tool_call_id": "a", "content": json.dumps([{"category": "food", "spent": 4093.0}])},
                {"role": "tool", "tool_call_id": "b", "content": json.dumps({"id": "G06", "tip": "Track it on 2026-01-01 at Starbucks"})}]

    def test_totals_and_tips_only_pass(self):
        text, bad = privacy_report.report(self.rows(gateway_request(self.totals_only())), descriptions={"Starbucks"})
        self.assertEqual(bad, 0, text)
        self.assertIn("[ok]", text)
        self.assertIn("question text: 1", text)

    def test_transaction_rows_in_a_tool_result_are_caught(self):
        messages = self.totals_only()[:2] + [{"role": "user", "content": "<tool_results>\n" + json.dumps(
            [{"tool": "spending", "result": [{"date": "2026-10-14", "amount": 120, "description": "Starbucks"}]}])
            + "\n</tool_results>\nAnswer."}]
        text, bad = privacy_report.report(self.rows(gateway_request(messages)), descriptions={"Starbucks"})
        self.assertEqual(bad, 1)
        for part in ("transaction rows", "full date 2026-10-14", "Starbucks"):
            self.assertIn(part, text)

    def test_offering_the_raw_row_tool_or_sending_a_user_id_is_caught(self):
        req = gateway_request(self.totals_only(), tools=("get_transactions",))
        req["messages"].append({"role": "user", "content": '{"userId": 24, "email": "henry@demo.budgetbuddy.test"}'})
        text, bad = privacy_report.report(self.rows(req), descriptions=set())
        self.assertEqual(bad, 1)
        for part in ("raw-row tool offered", "email address", "user id field"):
            self.assertIn(part, text)

    def test_the_question_itself_is_not_scanned(self):
        rows = [{"event": "coach_question", "run_id": "r-1", "question": "I spent 120 at Starbucks on 2026-10-14"},
                gateway_request([{"role": "user", "content": "I spent 120 at Starbucks on 2026-10-14"}])]
        self.assertEqual(privacy_report.report(rows, descriptions={"Starbucks"})[1], 0)


if __name__ == "__main__":
    unittest.main()
