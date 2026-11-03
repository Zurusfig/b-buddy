"""Validate the UAT tasks against generated persona ground truth."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class UatSetTests(unittest.TestCase):
    def test_all_tasks_and_ground_truth_references(self):
        tasks = [json.loads(line) for line in (ROOT / "Harness/data/test_set.jsonl").read_text().splitlines()]
        truth = json.loads((ROOT / "persona/ground_truth.json").read_text())
        people = {p["nickname"]: p for p in truth["personas"]}
        self.assertEqual([t["id"] for t in tasks], [f"T{i:02d}" for i in range(1, 12)])
        for i, task in enumerate(tasks, 1):
            with self.subTest(task=task["id"]):
                self.assertEqual(task["uat"], f"UAT-{i:02d}")
                self.assertIn(task["persona"], people)
                self.assertTrue(task["input"])
                expected = task["expected"]
                refs = expected.get("amount_ref", [])
                refs = [refs] if isinstance(refs, str) else list(refs)
                refs += [expected["list_ref"]] if "list_ref" in expected else []
                for ref in refs:
                    name, month, field = ref.split(".")
                    self.assertEqual(name, task["persona"])
                    row = people[name]["months"][month]
                    value = row["spending_by_category"].get(field, row.get(field))
                    self.assertIsNotNone(value, ref)
                    if ref == expected.get("list_ref"):
                        self.assertIsInstance(value, list)
                    else:
                        self.assertIsInstance(value, (int, float))


if __name__ == "__main__":
    unittest.main()
