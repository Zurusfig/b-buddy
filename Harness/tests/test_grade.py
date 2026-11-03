"""Focused checks for the UAT grader; no model or database calls."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import grade  # noqa: E402


class GradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tasks, cls.people = grade.load()
        cls.tasks = {task["id"]: task for task in tasks}

    def test_correct_sum_and_combined_total(self):
        one = {"answer": "You spent ฿4,728 on food.", "calls": [
            {"name": "sum_by_category", "args": {"month": "2026-09", "category": "food"}, "result": 4728.0}]}
        self.assertEqual(grade.grade(self.tasks["T01"], one, self.people), [])
        combined = {"answer": "The combined total was ฿6,522.", "calls": [
            {"name": "sum_categories", "args": {"month": "2026-09", "categories": ["food", "transport"]},
             "result": {"total": 6522.0, "by_category": {"food": 6064.0, "transport": 458.0}}}]}
        self.assertEqual(grade.grade(self.tasks["T06"], combined, self.people), [])

    def test_wrong_tool_or_missing_combined_total_fails(self):
        wrong = {"answer": "฿6,522", "calls": [
            {"name": "sum_by_category", "args": {"month": "2026-09", "category": "food"}, "result": 6064.0},
            {"name": "sum_by_category", "args": {"month": "2026-09", "category": "transport"}, "result": 458.0}]}
        self.assertIn("combined tool total != 6522.0", grade.grade(self.tasks["T06"], wrong, self.people))

    def test_over_budget_checks_category_and_figures(self):
        result = {"answer": "อาหารเกินงบ 93 บาท", "calls": [
            {"name": "over_budget", "args": {"month": "2026-10"},
             "result": [{"category": "food", "spent": 4093.0, "limit": 4000.0, "over_by": 93.0}]}]}
        self.assertEqual(grade.grade(self.tasks["T02"], result, self.people), [])

    def test_refusal_must_not_fetch_transactions(self):
        result = {"answer": "I cannot show another user's transactions.", "route": "refuse", "calls": [
            {"name": "get_transactions", "args": {"month": "2026-10"}, "result": []}]}
        self.assertTrue(grade.grade(self.tasks["T10"], result, self.people))

    def test_thai_reply_rejects_chinese_words(self):
        result = {"answer": "ค่าอาหาร 6,064 บาท 而在本月", "calls": [
            {"name": "sum_by_category", "args": {"month": "2026-09", "category": "food"}, "result": 6064.0}]}
        self.assertIn("reply contains non-Thai words", grade.grade(self.tasks["T04"], result, self.people))


if __name__ == "__main__":
    unittest.main()
