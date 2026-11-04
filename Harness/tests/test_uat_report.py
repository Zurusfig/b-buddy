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
    def test_practice_run_is_visible_but_does_not_change_uat_measures(self):
        events = [
            {"ts": "2026-11-04T09:00:00", "event": "coach_tool_call", "run_id": "official-1",
             "tool": "sum_by_category", "arguments": {"month": "2026-09", "category": "food"},
             "result": "4728.0", "ok": True},
            {"ts": "2026-11-04T09:00:01", "event": "coach_question", "run_id": "official-1",
             "persona": "Henry", "task_id": "UAT-01", "question": "Food last month?",
             "answer": "You spent 4,728 THB on food.", "route": "small", "intent": "trend",
             "latency_s": 12.0, "classifier_s": 3.0},
            {"ts": "2026-11-04T10:00:00", "event": "coach_tool_call", "run_id": "practice-1",
             "tool": "unexpected_tool", "arguments": {}, "result": "{}", "ok": True},
            {"ts": "2026-11-04T10:00:01", "event": "coach_question", "run_id": "practice-1",
             "persona": "Henry", "user_id": 23, "task_id": None, "question": "Can I try this?",
             "answer": "Yes", "route": "small", "latency_s": 100.0, "classifier_s": 10.0},
        ]
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            log_path = folder / "coach_calls.jsonl"
            output_path = folder / "uat_report.html"
            log_path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            result = report.generate("2026-11-04", False, log_path=log_path,
                                     output_path=output_path)
            grades = {r["run_id"]: r["grade"] for r in result["runs"]}
            self.assertEqual(grades, {"official-1": "pass", "practice-1": "free"})
            self.assertEqual(result["stats"]["count"], 1)
            self.assertEqual(result["stats"]["latency_p50"], 12.0)
            measures = {m["label"]: m for m in result["acceptance"]}
            self.assertEqual(measures["Write tools"]["status"], "pass")
            self.assertEqual(measures["Replies ≤ 20 s"]["measured"], "100.0% (1/1)")
            self.assertIn('"grade":"free"', output_path.read_text(encoding="utf-8"))

    def test_demo_rounds_are_isolated_from_real_log_and_report(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            real_log = folder / "coach_calls.jsonl"
            real_html = folder / "uat_report.html"
            demo_html = folder / "uat_report_demo.html"
            real_log.write_text('{"event":"coach_question","run_id":"real-run"}\n', encoding="utf-8")
            real_html.write_text("real report stays here", encoding="utf-8")
            log_before = real_log.read_bytes()
            html_before = real_html.read_bytes()

            result = report.generate("2026-11-04", False, log_path=real_log,
                                     output_path=demo_html, demo=True)

            self.assertEqual(real_log.read_bytes(), log_before)
            self.assertEqual(real_html.read_bytes(), html_before)
            with self.assertRaisesRegex(ValueError, "cannot overwrite"):
                report.generate("2026-11-04", False, log_path=real_log,
                                output_path=report.OUTPUT_PATH, demo=True)
            self.assertEqual(len(result["runs"]), 8)
            self.assertEqual({r["round"] for r in result["runs"]}, {1, 2})
            grades = {(r["task_id"], r["attempt"]): r["grade"] for r in result["runs"]}
            self.assertEqual(grades["UAT-04", 1], "fail")
            self.assertEqual(grades["UAT-04", 2], "pass")
            self.assertEqual(grades["UAT-05", 1], "fail")
            self.assertEqual(grades["UAT-05", 2], "fail")
            self.assertEqual(grades["UAT-08", 1], "pass")
            page = demo_html.read_text(encoding="utf-8")
            self.assertIn("DEMO DATA · Two synthetic rounds", page)
            self.assertIn("Synthetic sample", page)
            self.assertNotIn('http-equiv="refresh"', page)

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
            self.assertIn("window.addEventListener('pagehide',saveView)", page)
            self.assertIn("requestAnimationFrame(()=>scrollTo", page)
            self.assertIn('<svg xmlns="http://www.w3.org/2000/svg"', page)
            self.assertIn('id="report-data" type="application/json"', page)
            self.assertNotIn("<script src=", page)
            self.assertIn("Right tool", page)


if __name__ == "__main__":
    unittest.main()
