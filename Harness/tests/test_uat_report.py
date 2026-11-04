"""Offline report grading for a correct run and two UAT regressions."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/uat_report.py"
spec = importlib.util.spec_from_file_location("uat_report", SCRIPT)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class UatReportTests(unittest.TestCase):
    def test_three_fake_runs_and_offline_html(self):
        events = []
        cases = [
            ("pass", "sum_by_category", "เดือนที่แล้วใช้เงินค่าอาหารไป 6,064 บาท"),
            ("wrong-tool", "compare_months", "เดือนที่แล้วใช้เงินค่าอาหารไป 6,064 บาท"),
            ("cjk", "sum_by_category", "เดือนที่แล้วใช้เงินค่าอาหารไป 6,064 บาท 而"),
        ]
        for run_id, tool_name, answer in cases:
            arguments = ({"month": "2026-09", "category": "food"} if tool_name == "sum_by_category"
                         else {"m1": "2026-09", "m2": "2026-10", "category": "food"})
            events.extend([
                {"ts": "2026-11-03T23:59:59", "event": "coach_llm_call", "run_id": run_id,
                 "model": "qwen3:4b-q4_K_M", "wall_s": 3.0},
                {"ts": "2026-11-04T00:00:02", "event": "coach_tool_call", "run_id": run_id,
                 "tool": tool_name, "arguments": arguments, "ok": True,
                 "result": json.dumps({"total": 6064.0, "amount": 6064.0})},
                {"ts": "2026-11-04T00:00:05", "event": "coach_question", "run_id": run_id,
                 "task_id": "UAT-04", "persona": "Diana", "round": 1,
                 "tester_number": 1, "chat_id": f"chat-{run_id}", "attempt": 1,
                 "question": "เดือนที่แล้วใช้เงินค่าอาหารไปเท่าไหร่", "answer": answer,
                 "route": "small", "intent": "lookup", "latency_s": 12.0,
                 "classifier_s": 2.0, "model_calls": 1, "validator_retries": 0},
            ])

        with tempfile.TemporaryDirectory() as folder:
            log_path = Path(folder) / "coach_calls.jsonl"
            output_path = Path(folder) / "uat_report.html"
            log_path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
            result = report.generate("2026-11-04", True, log_path=log_path, output_path=output_path)
            by_id = {r["run_id"]: r for r in result["runs"]}
            self.assertEqual(len(by_id), 3)
            self.assertEqual(by_id["pass"]["events"], 3)  # includes the prior-day event
            self.assertEqual(by_id["pass"]["grade"], "pass")
            self.assertEqual(by_id["wrong-tool"]["grade"], "fail")
            self.assertIn("Right tool", [c["name"] for c in by_id["wrong-tool"]["checks"]
                          if c["status"] == "fail"])
            self.assertEqual(by_id["cjk"]["grade"], "fail")
            self.assertIn("Thai only", [c["name"] for c in by_id["cjk"]["checks"]
                          if c["status"] == "fail"])
            page = output_path.read_text(encoding="utf-8")
            self.assertIn('http-equiv="refresh" content="15"', page)
            self.assertIn('<svg xmlns="http://www.w3.org/2000/svg"', page)
            self.assertIn('id="report-data" type="application/json"', page)
            self.assertNotIn("<script src=", page)
            self.assertIn("Right tool", page)


if __name__ == "__main__":
    unittest.main()
