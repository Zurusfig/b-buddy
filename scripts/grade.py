"""Run and grade T01–T11 without overwriting saved evaluation reports.

Usage: python scripts/grade.py [--ids T01,T04]
Requires Ollama; advice and escalations also require the course gateway.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Harness/budget_coach"))
import envfile  # noqa: E402
envfile.load_env()
import advice  # noqa: E402
import persona_agent  # noqa: E402
import validator  # noqa: E402


def load() -> tuple[list[dict], dict]:
    tasks = [json.loads(line) for line in (ROOT / "Harness/data/test_set.jsonl").read_text().splitlines()]
    truth = json.loads((ROOT / "persona/ground_truth.json").read_text())
    return tasks, {p["nickname"]: p for p in truth["personas"]}


def resolve(ref: str, people: dict):
    name, month, field = ref.split(".")
    row = people[name]["months"][month]
    return row["spending_by_category"].get(field, row.get(field))


def has_amount(answer: str, amount: float, tolerance: float = 1) -> bool:
    return any(abs(n - amount) <= tolerance for n in validator.numbers_in(answer))


def grade(task: dict, result: dict, people: dict) -> list[str]:
    """Return failed checks; an empty list is a pass."""
    want = task["expected"]
    calls = result.get("calls") or []
    answer = result.get("answer", "")
    errors = []

    def matching(tool: str, args: dict | None = None) -> list[dict]:
        return [c for c in calls if c.get("name") == tool and
                all(c.get("args", {}).get(k) == v for k, v in (args or {}).items()) and
                not (isinstance(c.get("result"), dict) and "error" in c["result"])]

    if "tool" in want and not matching(want["tool"], want.get("args")):
        errors.append(f"missing {want['tool']} {want.get('args', {})}")
    if "amount_ref" in want:
        refs = want["amount_ref"]
        refs = [refs] if isinstance(refs, str) else refs
        target = sum(resolve(ref, people) for ref in refs) if want.get("combine") == "sum" else resolve(refs[0], people)
        tolerance = want.get("tolerance_thb", 1)
        if want.get("combine") == "sum":
            totals = [c["result"].get("total") for c in matching("sum_categories", {"month": "2026-09"})
                      if isinstance(c.get("result"), dict)]
            if not any(isinstance(n, (int, float)) and abs(n - target) <= tolerance for n in totals):
                errors.append(f"combined tool total != {target}")
        elif "tool" in want:
            values = [c.get("result") for c in matching(want["tool"], want.get("args"))]
            if not any(isinstance(n, (int, float)) and abs(n - target) <= tolerance for n in values):
                errors.append(f"tool amount != {target}")
        if not has_amount(answer, target, tolerance):
            errors.append(f"reply missing amount {target}")
    if "list_ref" in want:
        categories = resolve(want["list_ref"], people)
        rows = matching(want["tool"], want.get("args"))
        actual = rows[0].get("result") if rows else None
        if not isinstance(actual, list) or sorted(r.get("category") for r in actual) != sorted(categories):
            errors.append(f"over-budget categories != {categories}")
        else:
            budget = people[task["persona"]]["months"]["2026-10"]["budget"]
            for row in actual:
                gold = budget[row["category"]]
                if any(abs(row.get(k, float("inf")) - gold[k]) > want.get("tolerance_thb", 1)
                       for k in ("spent", "limit", "over_by")):
                    errors.append(f"wrong budget figures for {row['category']}")
            if categories and not any(cat in answer.lower() for cat in ("food", "อาหาร")):
                errors.append("reply does not name the over-budget category")
    if want.get("reply_language") == "th" and re.search(r"[A-Za-z]{2,}|[\u4e00-\u9fff]", answer):
        errors.append("reply contains non-Thai words")
    action = want.get("action")
    if action in ("no_data", "no_budgets"):
        phrase = (r"no data|no transactions|nothing.*April|ไม่มีข้อมูล|ไม่พบข้อมูล" if action == "no_data"
                  else r"no budget|not set.*budget|haven.t set.*budget|ยังไม่ได้ตั้งงบ|ไม่มีงบ")
        if not re.search(phrase, answer, re.I):
            errors.append(f"reply does not state {action}")
        if want.get("reply_has_amount") is False and (validator.numbers_in(answer) - {2026.0}):
            errors.append("reply contains an amount")
    if action == "refuse":
        if result.get("route") != "refuse" or any(c.get("name") not in ("decline",) for c in calls):
            errors.append("did not refuse without data tools")
        if want.get("tool") and not matching(want["tool"], want.get("args")):
            errors.append("wrong refusal kind")
        if want.get("other_user_rows") == 0 and any(c.get("name") == "get_transactions" for c in calls):
            errors.append("transaction rows retrieved")
    if "action_any_of" in want:
        summary = matching("month_summary", want.get("args_if_summary"))
        if result.get("route") != "clarify" and not summary:
            errors.append("neither clarified nor summarized July")
    if want.get("route") == "advice" and not result.get("route", "").startswith("advice"):
        errors.append("not on advice route")
    if want.get("must_cite_tip_id"):
        cited = re.findall(r"\[(G\d{2})\]", answer)
        if not cited or any(gid not in advice.CATALOG for gid in cited):
            errors.append("missing valid tip citation")
        elif not any(c.get("args", {}).get("guideline_id") in cited for c in matching("lookup_guideline")):
            errors.append("cited tip was not looked up")
    if want.get("numbers_in_tool_output") and validator.unsupported_numbers(answer, calls, question=task["input"],
                                                                         extra=(2026,)):  # "October 2026": the data's year, as the coach allows
        errors.append("reply has numbers absent from tool output")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", help="comma-separated task IDs; default: all 11")
    args = parser.parse_args()
    tasks, people = load()
    if args.ids:
        selected = set(args.ids.split(","))
        if selected - {t["id"] for t in tasks}:
            parser.error(f"unknown task IDs: {', '.join(sorted(selected - {t['id'] for t in tasks}))}")
        tasks = [t for t in tasks if t["id"] in selected]
    passed = 0
    for task in tasks:
        try:
            result = persona_agent.answer_persona(task["input"], task["persona"])
            errors = grade(task, result, people)
        except Exception as exc:
            errors = [f"run error: {type(exc).__name__}: {exc}"]
            result = {}
        passed += not errors
        print(f"{task['id']} {'PASS' if not errors else 'FAIL'} "
              f"{result.get('latency', 0):.1f}s " + ("; ".join(errors) if errors else ""), flush=True)
    print(f"Total: {passed}/{len(tasks)} passed")
    return 0 if passed == len(tasks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
