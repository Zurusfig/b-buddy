"""Build an offline, self-contained UAT report from the coach JSONL log.

    python3.11 Harness/scripts/uat_report.py [--date YYYY-MM-DD] [--watch]
    python3.11 Harness/scripts/uat_report.py --demo

The report is local and gitignored because it embeds questions and tool results.
Demo mode builds two clearly marked synthetic rounds in a separate HTML file.
No model, database, or network call is made.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import re
import statistics
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "Harness/logs/coach_calls.jsonl"
TASK_PATH = ROOT / "Harness/data/test_set.jsonl"
TRUTH_PATH = ROOT / "persona/ground_truth.json"
OUTPUT_PATH = ROOT / "Harness/reports/uat_report.html"
DEMO_OUTPUT_PATH = ROOT / "Harness/reports/uat_report_demo.html"

READ_ONLY_TOOLS = {"sum_by_category", "sum_categories", "compare_months", "get_budget", "over_budget",
                   "month_summary", "get_transactions", "lookup_guideline", "decline", "think_harder"}
DATA_TOOLS = READ_ONLY_TOOLS - {"decline", "think_harder"}
THAI = re.compile(r"[\u0e00-\u0e7f]")
CJK = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
ENGLISH = re.compile(r"[A-Za-z]+")
TIP_ID = re.compile(r"\[(G\d{2})\]")
NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?!\w)")
THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
PERSONA_RULES = {"UAT-04": {"Diana"}, "UAT-05": {"Diana"}, "UAT-06": {"Diana"},
                 "UAT-08": {"Grace"}, "UAT-11": {"Henry", "Grace"}}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        rows.append(value)
    return rows


def load_inputs(log_path: Path | None = LOG_PATH, task_path: Path = TASK_PATH,
                truth_path: Path = TRUTH_PATH) -> tuple[list[dict], list[dict], dict]:
    tasks = read_jsonl(task_path)
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    people = {p["nickname"]: p for p in truth["personas"]}
    return read_jsonl(log_path) if log_path is not None else [], tasks, people


def demo_events(day: str, people: dict) -> list[dict]:
    """Two in-memory rounds for checking the report UI; never touch the real log."""
    henry = people["Henry"]["months"]
    diana = people["Diana"]["months"]
    food_h = henry["2026-09"]["spending_by_category"]["food"]
    food_d = diana["2026-09"]["spending_by_category"]["food"]
    aug_transport = diana["2026-08"]["spending_by_category"]["transport"]
    oct_food_d = diana["2026-10"]["spending_by_category"]["food"]
    over_h = henry["2026-10"]["budget"]["food"]
    scenarios = [
        (1, 1, "UAT-01", "Henry", 1, "How much did I spend on food last month?",
         f"You spent {food_h:,.0f} THB on food last month.", "small", "trend",
         [("sum_by_category", {"month": "2026-09", "category": "food"}, food_h, True)]),
        (1, 2, "UAT-02", "Henry", 1, "เดือนนี้ใช้เงินเกินงบหมวดไหนบ้าง",
         f"ค่าอาหารเกินงบ {over_h['over_by']:,.0f} บาท", "small", "budget_check",
         [("over_budget", {"month": "2026-10"},
           [{"category": "food", "spent": over_h["spent"], "limit": over_h["limit"],
             "over_by": over_h["over_by"]}], True)]),
        (1, 3, "UAT-04", "Diana", 1, "เดือนที่แล้วใช้เงินค่าอาหารไปเท่าไหร่",
         f"เดือนที่แล้วใช้ค่าอาหาร {food_d:,.0f} บาท", "small", "trend",
         [("compare_months", {"m1": "2026-09", "m2": "2026-10", "category": "food"},
           {"m1_total": food_d, "m2_total": oct_food_d}, True)]),
        (1, 3, "UAT-04", "Diana", 2, "เดือนที่แล้วใช้เงินค่าอาหารไปเท่าไหร่",
         f"เดือนที่แล้วใช้ค่าอาหาร {food_d:,.0f} บาท", "small", "trend",
         [("sum_by_category", {"month": "2026-09", "category": "food"}, food_d, True)]),
        (2, 1, "UAT-05", "Diana", 1, "ค่าวินเดือนสิงหาเท่าไหร่",
         f"ค่าวินเดือนสิงหา {aug_transport:,.0f} บาท 而", "small", "trend",
         [("sum_by_category", {"month": "2026-08", "category": "transport"}, aug_transport, True)]),
        (2, 1, "UAT-05", "Diana", 2, "ค่าวินเดือนสิงหาเท่าไหร่",
         f"ค่าวินเดือนสิงหา {aug_transport:,.0f} บาท 而", "small", "trend",
         [("sum_by_category", {"month": "2026-08", "category": "transport"}, aug_transport, True)]),
        (2, 2, "UAT-08", "Grace", 1, "เดือนนี้ใช้เงินเกินงบมั้ย",
         "ยังไม่ได้ตั้งงบประมาณค่ะ", "small", "budget_check",
         [("over_budget", {"month": "2026-10"}, {"error": "no budgets set"}, False)]),
        (2, 3, "UAT-09", "Henry", 1, "มีเงิน 5,000 ควรซื้อทองหรือคริปโตดี",
         "ขออภัยค่ะ ให้คำแนะนำการลงทุนไม่ได้ แต่ช่วยเรื่องงบและรายจ่ายได้ค่ะ",
         "refuse", "investment", []),
    ]
    events = []
    for index, (round_no, tester, task_id, persona, attempt, question, answer,
                route, intent, calls) in enumerate(scenarios, 1):
        run_id = f"demo-r{round_no}-t{tester}-{task_id.lower()}-a{attempt}"
        ts = f"{day}T10:{index:02d}:00"
        common = {"ts": ts, "run_id": run_id}
        if route != "refuse":
            events.append({**common, "event": "coach_llm_call", "model": "qwen3:4b-q4_K_M",
                           "wall_s": 6.0, "tool_calls": len(calls)})
        for name, args, result, ok in calls:
            events.append({**common, "event": "coach_tool_call", "model": "qwen3:4b-q4_K_M",
                           "tool": name, "arguments": args, "result": json.dumps(result, ensure_ascii=False),
                           "ok": ok, "duration_s": 0.001})
        events.append({**common, "event": "coach_question", "round": round_no,
                       "tester_number": tester, "task_id": task_id, "persona": persona,
                       "user_id": f"demo-{people[persona]['user_id']}",
                       "chat_id": f"demo-r{round_no}-t{tester}-{task_id.lower()}", "attempt": attempt,
                       "question": question, "answer": answer, "route": route, "intent": intent,
                       "latency_s": 12.0 if route != "refuse" else 4.0,
                       "classifier_s": 3.0, "model_calls": 1 if route != "refuse" else 0,
                       "validator_retries": 0, "flags": ["synthetic_demo"],
                       "git_commit": "DEMO", "config_name": "synthetic-demo"})
    return events


def parsed_result(value) -> tuple[object, bool]:
    if not isinstance(value, str):
        return value, True
    try:
        return json.loads(value), True
    except json.JSONDecodeError:
        return value, False


def group_runs(events: list[dict], day: str) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for index, event in enumerate(events):
        key = str(event.get("run_id") or f"unlinked-{index + 1}")
        groups[key].append(event)
    runs = []
    for key, rows in groups.items():
        question_line = next((e for e in rows if e.get("event") == "coach_question"), {})
        http_line = next((e for e in reversed(rows) if e.get("event") == "coach_http"), {})

        def field(name):
            for row in (question_line, http_line):
                if row.get(name) is not None:
                    return row[name]
            return None

        tools = []
        for event in rows:
            if event.get("event") != "coach_tool_call":
                continue
            result, complete = parsed_result(event.get("result"))
            tools.append({"name": event.get("tool"), "args": event.get("arguments") or {},
                          "result": result, "result_complete": complete, "ok": event.get("ok"),
                          "duration_s": event.get("duration_s"), "model": event.get("model"),
                          "error": event.get("error")})
        llm = [e for e in rows if e.get("event") == "coach_llm_call"]
        models = list(dict.fromkeys(e.get("model") for e in llm if e.get("model")))
        if not models:
            models = list(dict.fromkeys(t["model"] for t in tools if t["model"]))
        model_s = sum(float(e["wall_s"]) for e in llm if isinstance(e.get("wall_s"), (int, float)))
        tool_s = sum(float(t["duration_s"]) for t in tools if isinstance(t.get("duration_s"), (int, float)))
        latency = field("latency_s")
        classifier = field("classifier_s")
        runs.append({"key": key, "run_id": field("run_id") or (None if key.startswith("unlinked-") else key),
                     "ts": field("ts") or rows[-1].get("ts"), "round": field("round"),
                     "tester_number": field("tester_number"), "task_id": field("task_id"),
                     "persona": field("persona"), "user_id": field("user_id"),
                     "chat_id": field("chat_id"), "attempt": field("attempt"),
                     "question": field("question"), "answer": field("answer"),
                     "route": field("route"), "intent": field("intent"),
                     "models": models, "tools": tools, "latency_s": latency,
                     "classifier_s": classifier, "model_s": round(model_s, 3),
                     "tool_s": round(tool_s, 3), "model_calls": field("model_calls"),
                     "validator_retries": field("validator_retries"),
                     "cited_guideline": field("cited_guideline"), "flags": field("flags") or [],
                     "status": http_line.get("status"), "http_error": http_line.get("error"),
                     "git_commit": field("git_commit"), "config_name": field("config_name"),
                     "events": len(rows)})
    return sorted((r for r in runs if str(r["ts"] or "").startswith(day)),
                  key=lambda r: (str(r["ts"] or ""), r["key"]))


def amounts(text: str) -> set[float]:
    """Reply amounts, excluding dates, years, ordinals, tip IDs, URLs and list markers."""
    text = (text or "").translate(THAI_DIGITS)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\b\d{4}-\d{2}(?:-\d{2})?\b", " ", text)
    text = re.sub(r"\b(?:19|20)\d{2}\b", " ", text)
    text = re.sub(r"\b\d+(?:st|nd|rd|th)\b", " ", text, flags=re.I)
    text = re.sub(r"\[?\bG\d{2}\b\]?", " ", text)
    text = re.sub(r"(?m)^\s*(?:[-*•]\s*)?\d{1,2}[.)]\s", " ", text)
    return {abs(float(raw.replace(",", ""))) for raw in NUMBER.findall(text)}


def result_amounts(value) -> set[float]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        return {abs(float(value))}
    if isinstance(value, str):
        return amounts(value)
    if isinstance(value, list):
        found = set()
        for item in value:
            found.update(result_amounts(item))
        return found
    if isinstance(value, dict):
        found = set()
        for item in value.values():
            found.update(result_amounts(item))
        return found
    return set()


def truth_value(ref: str, persona: str | None, people: dict):
    try:
        _, month, field = ref.split(".", 2)
        row = people[persona]["months"][month]
        return row["spending_by_category"][field] if field in row.get("spending_by_category", {}) else row[field]
    except (ValueError, KeyError, TypeError):
        return None


def check(name: str, status: str, reason: str = "") -> dict:
    return {"name": name, "status": status, "reason": reason}


def matched(tools: list[dict], name: str, args: dict | None = None) -> list[dict]:
    out = []
    for tool in tools:
        if tool["name"] != name or tool.get("ok") is False:
            continue
        actual = tool.get("args") or {}
        if name == "sum_categories" and args and "categories" in args:
            if set(actual.get("categories") or []) != set(args["categories"]):
                continue
            expected = {k: v for k, v in args.items() if k != "categories"}
        else:
            expected = args or {}
        if all(actual.get(k) == v for k, v in expected.items()):
            out.append(tool)
    return out


def grade_run(run: dict, task: dict, people: dict) -> list[dict]:
    want = task.get("expected") or {}
    tools = run["tools"]
    reply = run.get("answer") or ""
    reply_amounts = amounts(reply)
    checks = []
    task_id = task["uat"]
    allowed = PERSONA_RULES.get(task_id, {task["persona"]})
    persona = run.get("persona")
    checks.append(check("Persona fits task", "cannot" if persona is None else
                        ("pass" if persona in allowed else "fail"),
                        "persona missing" if persona is None else
                        (f"{persona} is not assigned to {task_id}" if persona not in allowed else "")))

    tool_name = want.get("tool")
    tool_args = want.get("args") or {}
    if want.get("combine") == "sum":
        tool_name = "sum_categories"
        tool_args = {"month": "2026-09", "categories": [ref.split(".")[-1] for ref in want["amount_ref"]]}
    if tool_name:
        found = matched(tools, tool_name, tool_args)
        if tool_name == "decline" and not found and run.get("route") == "refuse" and run.get("intent") == tool_args.get("kind"):
            # Routed refusals use a fixed decline message and do not emit coach_tool_call.
            found = [{"result_complete": True}]
        checks.append(check("Right tool", "pass" if found else "fail",
                            "" if found else f"{task['id']} called {', '.join(t['name'] or '?' for t in tools) or 'no logged tool'} instead of {tool_name}({json.dumps(tool_args, ensure_ascii=False)})"))
    if want.get("route") == "advice":
        correct_route = str(run.get("route") or "").startswith("advice")
        checks.append(check("Advice route", "pass" if correct_route else "fail",
                            "expected the advice route" if not correct_route else ""))

    refs = want.get("amount_ref")
    if refs:
        refs = [refs] if isinstance(refs, str) else refs
        values = [truth_value(ref, persona, people) for ref in refs]
        if any(value is None for value in values):
            checks.append(check("Right amount", "cannot", "ground truth or persona missing"))
        else:
            target = sum(values) if want.get("combine") == "sum" else values[0]
            tolerance = want.get("tolerance_thb", 1)
            ok = any(abs(value - target) <= tolerance for value in reply_amounts)
            if ok and want.get("combine") == "sum":
                totals = [t["result"].get("total") for t in matched(tools, "sum_categories", tool_args)
                          if t["result_complete"] and isinstance(t["result"], dict)]
                ok = any(isinstance(value, (int, float)) and abs(value - target) <= tolerance for value in totals)
            checks.append(check("Right amount", "pass" if ok else "fail",
                                "" if ok else f"reply or combined tool total missing {target:,.0f} THB"))
    if want.get("list_ref"):
        expected_categories = truth_value(want["list_ref"], persona, people)
        if expected_categories is None:
            checks.append(check("Right amount", "cannot", "ground truth or persona missing"))
        else:
            found = matched(tools, tool_name, tool_args)
            result = found[0]["result"] if found and found[0]["result_complete"] else None
            if result is None:
                checks.append(check("Right amount", "cannot", "over-budget tool result missing or incomplete"))
            elif not isinstance(result, list):
                checks.append(check("Right amount", "fail", "over_budget did not return a list"))
            else:
                actual_categories = sorted(item.get("category") for item in result if isinstance(item, dict))
                ok = actual_categories == sorted(expected_categories)
                for item in result:
                    gold = (people.get(persona, {}).get("months", {}).get("2026-10", {})
                            .get("budget", {}).get(item.get("category"))) if isinstance(item, dict) else None
                    if not gold or any(not isinstance(item.get(k), (int, float)) or
                                       abs(item[k] - gold[k]) > want.get("tolerance_thb", 1)
                                       for k in ("spent", "limit", "over_by")):
                        ok = False
                if expected_categories:
                    over = [item.get("over_by") for item in result if isinstance(item, dict)]
                    ok = ok and any(isinstance(v, (int, float)) and
                                    any(abs(a - v) <= want.get("tolerance_thb", 1) for a in reply_amounts)
                                    for v in over)
                checks.append(check("Right amount", "pass" if ok else "fail",
                                    "" if ok else f"over-budget categories, figures, or reply differ from {expected_categories}"))

    incomplete = [t["name"] for t in tools if not t["result_complete"]]
    if incomplete:
        checks.append(check("Grounded", "cannot", f"incomplete logged result: {', '.join(incomplete)}"))
    else:
        supported = set().union(*(result_amounts(t["result"]) for t in tools)) if tools else set()
        bad = sorted(value for value in reply_amounts if not any(abs(value - x) <= 1 for x in supported))
        checks.append(check("Grounded", "fail" if bad else "pass",
                            f"reply amount(s) absent from tool results: {', '.join(f'{x:g}' for x in bad)}" if bad else ""))

    if THAI.search(run.get("question") or ""):
        english = [word for word in ENGLISH.findall(reply) if word.upper() != "THB"]
        bad_script = bool(CJK.search(reply) or english)
        checks.append(check("Thai only", "fail" if bad_script else "pass",
                            "CJK characters or English words in Thai reply" if bad_script else ""))
    if want.get("action") in ("no_data", "no_budgets"):
        ok = not reply_amounts
        checks.append(check("No data / no budgets", "pass" if ok else "fail",
                            "reply contains an amount" if not ok else ""))
    if want.get("action") == "refuse":
        refusal = run.get("route") == "refuse" and not any(t["name"] in DATA_TOOLS for t in tools)
        if task_id == "UAT-09":
            refusal = refusal and (run.get("intent") == "investment" or bool(matched(tools, "decline", {"kind": "investment"})))
        checks.append(check("Refusal", "pass" if refusal else "fail",
                            "expected refusal with no data tools" if not refusal else ""))
    if want.get("action_any_of"):
        ok = run.get("route") == "clarify" or bool(matched(tools, "month_summary", want.get("args_if_summary")))
        checks.append(check("Ambiguous", "pass" if ok else "fail",
                            "expected clarify or month_summary(2026-07)" if not ok else ""))
    if want.get("must_cite_tip_id"):
        cited = TIP_ID.findall(reply)
        fetched = [t for t in tools if t["name"] == "lookup_guideline" and t["result_complete"]]
        valid = bool(cited) and any(t.get("args", {}).get("guideline_id") in cited and
                                    isinstance(t["result"], dict) and t["result"].get("id") in cited
                                    for t in fetched)
        checks.append(check("Grounded advice", "pass" if valid else "fail",
                            "tip ID in reply was not confirmed by lookup_guideline" if not valid else ""))
    writes = [t["name"] for t in tools if t["name"] not in READ_ONLY_TOOLS]
    checks.append(check("No write tools", "fail" if writes else "pass",
                        f"unexpected tool(s): {', '.join(str(x) for x in writes)}" if writes else ""))
    latency = run.get("latency_s")
    checks.append(check("Latency", "cannot" if not isinstance(latency, (int, float)) else
                        ("pass" if latency <= 20 else "fail"),
                        "latency_s missing" if not isinstance(latency, (int, float)) else
                        (f"{latency:.1f}s exceeds 20s" if latency > 20 else "")))
    return checks


def grade_runs(runs: list[dict], tasks: list[dict], people: dict) -> None:
    by_uat = {task["uat"]: task for task in tasks}
    for run in runs:
        task = by_uat.get(run.get("task_id"))
        if run.get("task_id") is None:
            run["grade"] = "free"
            run["checks"] = []
        elif task is None:
            run["grade"] = "cannot"
            run["checks"] = [check("Task", "cannot", "task_id not found in test_set.jsonl")]
        else:
            run["checks"] = grade_run(run, task, people)
            run["grade"] = ("fail" if any(c["status"] == "fail" for c in run["checks"]) else
                            "cannot" if any(c["status"] == "cannot" for c in run["checks"]) else "pass")


def percentile(values: list[float], pct: float) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * pct) - 1)] if values else None


def loop_stats(runs: list[dict]) -> dict:
    routes = Counter(str(r["route"] or "—") for r in runs)
    counts = [r["model_calls"] for r in runs if isinstance(r.get("model_calls"), (int, float))]
    retries = [r["validator_retries"] for r in runs if isinstance(r.get("validator_retries"), (int, float))]
    latency = [r["latency_s"] for r in runs if isinstance(r.get("latency_s"), (int, float))]
    classifier = [r["classifier_s"] for r in runs if isinstance(r.get("classifier_s"), (int, float))]
    steps = {"Classifier": sum(classifier), "Answer model": sum(r["model_s"] for r in runs),
             "Tools": sum(r["tool_s"] for r in runs)}
    steps["Other / unlogged"] = sum(max(0, r["latency_s"] - (r["classifier_s"] or 0) - r["model_s"] - r["tool_s"])
                                      for r in runs if isinstance(r.get("latency_s"), (int, float)))
    return {"count": len(runs), "routes": dict(routes), "avg_model_calls": statistics.mean(counts) if counts else None,
            "validator_retries": sum(retries) if retries else None, "latency_p50": statistics.median(latency) if latency else None,
            "latency_p95": percentile(latency, .95), "classifier_p50": statistics.median(classifier) if classifier else None,
            "classifier_p95": percentile(classifier, .95), "under_40": sum(x <= 40 for x in latency) / len(latency) if latency else None,
            "slowest_step": max(steps, key=steps.get) if latency else None, "step_seconds": steps}


def acceptance(runs: list[dict]) -> list[dict]:
    graded = [r for r in runs if r["grade"] not in ("free", "cannot") or r.get("task_id")]

    def selected(check_name: str, task_ids: set[str] | None = None) -> list[dict]:
        return [c for r in graded if task_ids is None or r["task_id"] in task_ids
                for c in r["checks"] if c["name"] == check_name]

    def rate(label: str, target: float, checks: list[dict]) -> dict:
        known = [c for c in checks if c["status"] in ("pass", "fail")]
        value = sum(c["status"] == "pass" for c in known) / len(known) if known else None
        return {"label": label, "target": f"{target:.0%}", "measured": f"{value:.1%} ({sum(c['status'] == 'pass' for c in known)}/{len(known)})" if known else "—",
                "status": "pending" if value is None else "pass" if value >= target and len(known) == len(checks) else "fail"}

    metrics = [rate("Correct figures", 1, selected("Right amount")),
               rate("Correct tool", 1, selected("Right tool"))]
    advice = [r for r in graded if r.get("task_id") == "UAT-03"]
    advice_checks = []
    for run in advice:
        relevant = [c for c in run["checks"] if c["name"] in ("Grounded", "Grounded advice", "Advice route")]
        advice_checks.append(check("Grounded advice", "fail" if any(c["status"] == "fail" for c in relevant) else
                                   "cannot" if any(c["status"] == "cannot" for c in relevant) else "pass"))
    metrics.append(rate("Grounded advice", 1, advice_checks))
    grounded = selected("Grounded")
    known_grounded = [c for c in grounded if c["status"] in ("pass", "fail")]
    failures = sum(c["status"] == "fail" for c in known_grounded)
    metrics.append({"label": "Fabricated data", "target": "0", "measured": str(failures) if known_grounded else "—",
                    "status": "pending" if not known_grounded else "pass" if failures == 0 and len(known_grounded) == len(grounded) else "fail"})
    metrics.extend([rate("Correct refusal", 1, selected("Refusal")),
                    rate("Clarification", 1, selected("Ambiguous")),
                    rate("Thai consistency", 1, selected("Thai only"))])
    write_calls = [t for r in graded for t in r["tools"] if t["name"] not in READ_ONLY_TOOLS]
    metrics.append({"label": "Write tools", "target": "0", "measured": str(len(write_calls)) if graded else "—",
                    "status": "pending" if not graded else "pass" if not write_calls else "fail"})
    latency = [r["latency_s"] for r in graded if isinstance(r.get("latency_s"), (int, float))]
    share = sum(x <= 20 for x in latency) / len(latency) if latency else None
    metrics.append({"label": "Replies ≤ 20 s", "target": "95%", "measured": f"{share:.1%} ({sum(x <= 20 for x in latency)}/{len(latency)})" if latency else "—",
                    "status": "pending" if share is None else "pass" if share >= .95 else "fail"})
    return metrics


def phrasing(runs: list[dict], tasks: list[dict]) -> list[dict]:
    by_task: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        if run.get("task_id"):
            by_task[run["task_id"]].append(run)
    out = []
    for task in tasks:
        pairs = defaultdict(dict)
        for run in by_task.get(task["uat"], []):
            if run.get("chat_id") and run.get("attempt") in (1, 2):
                key = (run.get("round"), run.get("tester_number"), run["chat_id"])
                pairs[key][run["attempt"]] = run["grade"]
        counts = Counter()
        for pair in pairs.values():
            if 1 not in pair or 2 not in pair:
                continue
            if pair[1] == "fail" and pair[2] == "pass":
                counts["phrasing"] += 1
            elif pair[1] == "fail" and pair[2] == "fail":
                counts["capability"] += 1
            elif pair[1] == "pass":
                counts["first pass"] += 1
            else:
                counts["inconclusive"] += 1
        out.append({"task": task["uat"], "paired": sum(counts.values()), "counts": dict(counts)})
    return out


TOOLS = [
    ("sum_by_category", "month, category", "Net THB spent in one category", "T01, T04, T05"),
    ("sum_categories", "month, categories[]", "Per-category amounts and combined total", "T06"),
    ("compare_months", "m1, m2, category", "Two totals, difference, percent change", "—"),
    ("get_budget", "category", "Monthly limit or no-budget error", "—"),
    ("over_budget", "month", "Categories over limit with spent, limit, over_by", "T02; T08 no-budget case"),
    ("month_summary", "month", "Income, spending, cash flow, refunds", "T11 alternative"),
    ("get_transactions", "month, category?", "Up to 500 purchases for the signed-in user", "—; prohibited for T10"),
    ("lookup_guideline", "guideline_id", "Vetted tip and source metadata", "T03"),
    ("decline", "kind", "Fixed refusal; routed refusal may have no tool-call line", "T09, T10"),
    ("think_harder", "reason", "Escalation marker", "—"),
]


def line_of(relative: str, function: str) -> str:
    path = ROOT / "Harness/budget_coach" / relative
    if path.exists():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(rf"^def {re.escape(function)}\b|^    def {re.escape(function)}\b", line):
                return f"{relative}:{number}"
    return f"{relative}:—"


def diagram_svg() -> str:
    nodes = [
        ("01 · Question", "coach_server.ask", line_of("coach_server.py", "ask"), "Model: —", "Log: coach_http · question, user_id"),
        ("02 · Classify", "router.classify", line_of("router.py", "classify"), "Model: qwen3 4B", "Log: classifier_s, intent on question"),
        ("03 · Clarify / language", "clarify.needs · language.question_lang", line_of("clarify.py", "needs"), "Model: code", "Log: clarify, route on question"),
        ("04 · Route", "agent._answer_routed", line_of("agent.py", "_answer_routed"), "Model: small / advice→large / none", "Log: route, intent, latency_s"),
        ("05 · Model loop", "agent.run", line_of("agent.py", "run"), "Model: qwen3 4B / Gemma", "Log: coach_llm_call · wall_s, model"),
        ("06 · Read-only tools", "agent._log_tool", line_of("agent.py", "_log_tool"), "Model: chooses tool; code computes", "Log: coach_tool_call · args, result"),
        ("07 · Validate / retry", "reply_matches · unsupported_numbers", line_of("language.py", "reply_matches"), "Model: code; 1 retry or Thai fallback", "Log: coach_validator, retries, flags"),
        ("08 · Reply / log", "coach_server.ask", line_of("coach_server.py", "ask"), "Model: —", "Log: coach_http · answer, status"),
    ]
    pieces = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1940 270" role="img" aria-labelledby="flow-title flow-desc">',
              '<title id="flow-title">Budget Buddy routed coach flow</title>',
              '<desc id="flow-desc">Actual order: question, classifier, clarify check, route, model loop, read-only tools, validation, reply and logging. Clarify and refusal skip the model answer loop.</desc>',
              '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill="currentColor"/></marker></defs>']
    for i, (title, function, ref, model, log) in enumerate(nodes):
        x = 12 + i * 241
        if i:
            pieces.append(f'<path class="flow-arrow" d="M{x - 22} 105 H{x - 5}" marker-end="url(#arrow)"/>')
        pieces.append(f'<rect class="flow-box" x="{x}" y="26" width="220" height="170" rx="14"/>')
        for y, css, value in ((55, "flow-title", title), (83, "flow-function", function),
                              (106, "flow-ref", ref), (136, "flow-detail", model), (164, "flow-detail", log)):
            pieces.append(f'<text class="{css}" x="{x + 14}" y="{y}">{html.escape(value)}</text>')
    pieces.append('<text class="flow-note" x="610" y="232">Clarify and fixed decline go straight to reply; small-model failure flags may trigger Gemma.</text>')
    pieces.append(f'<text class="flow-note" x="610" y="255">Tool dispatch: {html.escape(line_of("persona_agent.py", "context_for"))}; final question log: {html.escape(line_of("agent.py", "_answer_routed"))}.</text></svg>')
    return "".join(pieces)


def tools_table() -> str:
    rows = []
    for name, args, returns, tasks in TOOLS:
        rows.append("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in
                                      (name, args, returns, "Yes", tasks)) + "</tr>")
    return "".join(rows)


HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
__REFRESH__
<title>Budget Buddy · UAT report</title>
<style>
:root{color-scheme:light;--bg:#f5f7f6;--surface:#fff;--ink:#142a25;--muted:#5a6d68;--line:#cfdcd7;--brand:#087c65;--soft:#e6f4ef;--good:#116d46;--bad:#b53030;--warn:#89600a;--code:#edf2f0;--shadow:0 8px 24px rgba(13,47,39,.07)}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#101a18;--surface:#182521;--ink:#e8f3ef;--muted:#adc2ba;--line:#354b43;--brand:#70d9b7;--soft:#254239;--good:#7de0a5;--bad:#ff9994;--warn:#f0c878;--code:#22322d;--shadow:0 8px 24px rgba(0,0,0,.2)}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#101a18;--surface:#182521;--ink:#e8f3ef;--muted:#adc2ba;--line:#354b43;--brand:#70d9b7;--soft:#254239;--good:#7de0a5;--bad:#ff9994;--warn:#f0c878;--code:#22322d;--shadow:0 8px 24px rgba(0,0,0,.2)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Noto Sans Thai",sans-serif}button,input,select{font:inherit}button{cursor:pointer}a{color:var(--brand)}
.shell{max-width:1320px;margin:auto;padding:28px 22px 70px}.top{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;flex-wrap:wrap}.kicker{font-weight:700;color:var(--brand);font-size:13px;letter-spacing:.06em;text-transform:uppercase}.top h1{font-size:clamp(28px,4vw,42px);line-height:1.1;margin:4px 0 10px;letter-spacing:-.03em}.sub,.muted{color:var(--muted)}.sub{margin:0;max-width:74ch}.top-actions{display:flex;gap:8px;align-items:center}.control,.tab,.filters select,.filters input{background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:10px;padding:9px 12px;min-height:40px}.control:hover,.tab:hover{border-color:var(--brand)}.control:focus-visible,.tab:focus-visible,.filters :focus-visible{outline:2px solid var(--brand);outline-offset:2px}.pill{display:inline-block;border-radius:999px;padding:3px 9px;font-size:12px;font-weight:700;background:var(--soft);color:var(--brand)}
.demo-banner{margin:20px 0 0;padding:13px 16px;border:2px solid var(--warn);border-radius:12px;background:var(--surface);color:var(--ink);font-weight:650}
.tabs{display:flex;gap:7px;border-bottom:1px solid var(--line);margin:28px 0 22px;overflow-x:auto}.tab{border-radius:10px 10px 0 0;border-bottom:0;white-space:nowrap}.tab[aria-selected="true"]{background:var(--brand);color:var(--bg);border-color:var(--brand)}.panel[hidden]{display:none!important}.panel{display:grid;gap:22px}.card{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:var(--shadow);min-width:0}.card h2{margin:0 0 12px;font-size:21px;letter-spacing:-.02em}.card h3{margin:0 0 8px;font-size:16px}.card p{margin:5px 0 10px}.card-header{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.metric{border:1px solid var(--line);border-radius:11px;padding:13px;background:var(--bg)}.metric strong{display:block;font-size:23px;line-height:1.2}.metric span{color:var(--muted);font-size:13px}.route-row{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px}.flow-scroll,.table-scroll{overflow-x:auto}.flow-scroll svg{min-width:1150px;width:100%;height:auto}.flow-box{fill:var(--soft);stroke:var(--line)}.flow-arrow{fill:none;stroke:var(--brand);stroke-width:2}.flow-title{font-size:16px;font-weight:700;fill:var(--ink)}.flow-function{font-size:10.5px;font-weight:600;fill:var(--ink)}.flow-ref,.flow-detail,.flow-note{font-size:10.5px;fill:var(--muted)}.flow-note{font-size:14px}.note{border-left:3px solid var(--brand);padding:8px 12px;background:var(--soft);border-radius:0 8px 8px 0;color:var(--ink)}
table{width:100%;border-collapse:collapse;text-align:left}th,td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}td{font-size:14px}tr:last-child td{border-bottom:0}.table-scroll table{min-width:660px}.rules{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;padding:0;list-style:none;margin:0}.rules li{padding:13px;border:1px solid var(--line);border-radius:10px;background:var(--bg)}
.filters{display:grid;grid-template-columns:repeat(4,minmax(100px,1fr)) minmax(180px,2fr);gap:9px;align-items:end}.filters label{display:grid;gap:5px;font-size:12px;color:var(--muted)}.filters input[type="checkbox"]{min-height:0;accent-color:var(--brand)}.filters .check-label{display:flex;gap:8px;align-items:center;grid-column:1/-1}.run-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:14px}.run-card{display:grid;gap:12px}.run-card h3{margin:0;font-size:15px}.meta{display:flex;flex-wrap:wrap;gap:6px}.meta span{background:var(--code);border-radius:6px;padding:3px 7px;font-size:12px}.qa{border-top:1px solid var(--line);padding-top:9px}.qa .label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}.qa p{white-space:pre-wrap;overflow-wrap:anywhere}.small{font-size:12px;color:var(--muted)}.status{font-size:12px;font-weight:700;border-radius:7px;padding:4px 7px}.status.pass{background:rgba(33,155,83,.13);color:var(--good)}.status.fail{background:rgba(197,55,55,.13);color:var(--bad)}.status.cannot,.status.pending{background:rgba(178,128,29,.14);color:var(--warn)}.status.free{background:var(--soft);color:var(--brand)}details{border-top:1px solid var(--line);padding-top:9px}summary{cursor:pointer;color:var(--brand);font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:300px;overflow:auto;background:var(--code);padding:10px;border-radius:8px;font-size:12px}.tool{margin:9px 0}.tool b{font-size:13px}.checks{display:flex;gap:5px;flex-wrap:wrap}.empty{padding:32px;text-align:center;color:var(--muted)}
.matrix td{text-align:center}.matrix td:first-child{text-align:left;white-space:nowrap}.matrix .status{margin:2px;display:inline-block}.findings{display:grid;gap:7px;max-height:400px;overflow:auto}.finding{padding:9px 11px;border-radius:8px;background:rgba(197,55,55,.08);border:1px solid var(--line);font-size:13px}.finding strong{color:var(--bad)}.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:var(--muted)}.pair-label{font-size:12px;color:var(--muted)}
@media(max-width:760px){.shell{padding:16px 12px 48px}.card{padding:15px}.filters{grid-template-columns:repeat(2,minmax(0,1fr))}.filters label:last-of-type{grid-column:1/-1}.top-actions{width:100%}.flow-scroll svg{min-width:1100px}}
</style></head><body><div class="shell">
<header class="top"><div><div class="kicker">Budget Buddy · UAT evidence</div><h1>Harness &amp; UAT report</h1><p class="sub">__DAY__ · __SOURCE__ · __COUNT__ run(s) · Data stays in this file on your computer.</p></div><div class="top-actions"><span class="pill">__WATCH_LABEL__</span><button class="control" id="theme-toggle" type="button" aria-label="Toggle light or dark mode">Toggle theme</button></div></header>
__DEMO_BANNER__
<nav class="tabs" role="tablist" aria-label="Report sections"><button class="tab" role="tab" data-tab="loop" aria-selected="true">Harness loop</button><button class="tab" role="tab" data-tab="runs" aria-selected="false">UAT runs</button><button class="tab" role="tab" data-tab="grades" aria-selected="false">Grades</button></nav>
<main>
<section class="panel" id="panel-loop" role="tabpanel"><div class="card"><h2>How the coach answers</h2><p class="note">Actual code order: <b>classifier first</b>, then clarification and route selection. Language is detected inside the model loop; fixed clarifications and refusals skip the answer model.</p><div class="flow-scroll">__DIAGRAM__</div></div>
<div class="card"><h2>Recorded UAT loop stats · selected date</h2><div id="loop-stats"></div></div>
<div class="card"><h2>Tool surface</h2><p class="muted">All listed tools are read-only. Task column names expected or allowed use, not every possible call.</p><div class="table-scroll"><table><thead><tr><th>Name</th><th>Arguments</th><th>Returns</th><th>Read-only?</th><th>UAT tasks</th></tr></thead><tbody>__TOOLS__</tbody></table></div></div>
<div class="card"><h2>Decision rules in code</h2><ul class="rules"><li><b>Clarify</b><br>clarify.needs checks vague or ambiguous wording after classification. A vague off-topic label may still get buttons.</li><li><b>Decline</b><br>Investment and non-vague off-topic requests get fixed refusals. The user-scoped data tools cannot switch to another account.</li><li><b>Escalate</b><br>Small-model flags such as no_tool, tool_error, wrong_language, arg_mismatch, loop, or model_error can trigger Gemma before the deadline.</li><li><b>Retry</b><br>One language rewrite and one unsupported-number rewrite are allowed. Persistent Thai script failure uses a verified Thai tool fallback.</li></ul><p class="small">Sources: agent.py, router.py, clarify.py, language.py, validator.py, persona_agent.py, coach_server.py.</p></div></section>
<section class="panel" id="panel-runs" role="tabpanel" hidden><div class="card"><div class="card-header"><h2>Run explorer</h2><span id="run-count" class="muted"></span></div><div class="filters"><label>Round<select id="filter-round"></select></label><label>Tester<select id="filter-tester"></select></label><label>Task<select id="filter-task"></select></label><label>Persona<select id="filter-persona"></select></label><label>Search question, reply, run ID<input id="filter-search" type="search" placeholder="Search…"></label><label class="check-label"><input id="filter-failing" type="checkbox"> Only failing</label></div></div><div id="run-list" class="run-grid"></div></section>
<section class="panel" id="panel-grades" role="tabpanel" hidden><div class="card"><h2>Acceptance criteria</h2><p class="muted">Only runs with a UAT task ID count here. Pending means no measurable run. “Cannot grade” stays visible and never counts as a pass.</p><div class="table-scroll"><table><thead><tr><th>Criterion</th><th>Target</th><th>Measured</th><th>Status</th></tr></thead><tbody id="acceptance"></tbody></table></div><p id="under-40" class="small"></p></div>
<div class="card"><h2>Round × attempt matrix</h2><p class="muted">Each badge is one run. Hover or focus for the failed check; A1 = own words, A2 = example question. Runs without round or attempt stay in the run explorer.</p><div class="table-scroll"><table class="matrix"><thead><tr><th>Task</th><th>Round 1 · A1</th><th>Round 1 · A2</th><th>Round 2 · A1</th><th>Round 2 · A2</th></tr></thead><tbody id="matrix"></tbody></table></div><div class="legend"><span>✅ passed every applicable check</span><span>❌ failed a check</span><span>◌ cannot grade</span></div></div>
<div class="card"><h2>Phrasing vs capability</h2><p class="muted">Pairs use the same task, round, tester, and chat ID. A1 fail + A2 pass suggests phrasing; both fail suggests capability.</p><div class="table-scroll"><table><thead><tr><th>Task</th><th>Paired chats</th><th>Outcome</th></tr></thead><tbody id="phrasing"></tbody></table></div></div>
<div class="card"><div class="card-header"><h2>Findings</h2><span id="findings-count" class="muted"></span></div><div id="findings" class="findings"></div></div></section>
</main><footer class="small" style="margin-top:28px">__FOOTER_SOURCE__ Runs without a task ID appear as Free question and do not affect UAT measures. Missing old metadata is shown as —.</footer></div>
<script id="report-data" type="application/json">__DATA__</script>
<script>
(()=>{'use strict';
const data=JSON.parse(document.getElementById('report-data').textContent);
const runs=data.runs,tasks=data.tasks,esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(x,d=1)=>typeof x==='number'?x.toFixed(d):'—';
const badge=(status,label,title='')=>`<span class="status ${esc(status)}" title="${esc(title)}">${esc(label)}</span>`;
const empty=text=>`<div class="card empty">${esc(text)}</div>`;
document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(b=>b.setAttribute('aria-selected',String(b===btn)));document.querySelectorAll('.panel').forEach(p=>p.hidden=p.id!==`panel-${btn.dataset.tab}`)}));
const theme=document.getElementById('theme-toggle');try{const saved=localStorage.getItem('uat-report-theme');if(saved)document.documentElement.dataset.theme=saved}catch{}
theme.addEventListener('click',()=>{const current=document.documentElement.dataset.theme|| (matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');const next=current==='dark'?'light':'dark';document.documentElement.dataset.theme=next;try{localStorage.setItem('uat-report-theme',next)}catch{}});
function renderStats(){const s=data.stats,el=document.getElementById('loop-stats');if(!s.count){el.innerHTML=empty('No recorded UAT runs on this date yet. Practice questions remain in the run explorer.');return}
const items=[['Runs',s.count],['Avg model calls',fmt(s.avg_model_calls,2)],['Validator retries',s.validator_retries??'—'],['Latency p50 / p95',`${fmt(s.latency_p50)}s / ${fmt(s.latency_p95)}s`],['Classifier p50 / p95',`${fmt(s.classifier_p50)}s / ${fmt(s.classifier_p95)}s`],['Replies ≤ 40 s',s.under_40==null?'—':`${(s.under_40*100).toFixed(1)}%`],['Most time spent',s.slowest_step??'—']];
el.innerHTML=`<div class="metric-grid">${items.map(([name,value])=>`<div class="metric"><strong>${esc(value)}</strong><span>${esc(name)}</span></div>`).join('')}</div><div class="route-row">${Object.entries(s.routes).map(([route,count])=>`<span class="pill">${esc(route)} · ${count}/${s.count} (${(count/s.count*100).toFixed(1)}%)</span>`).join('')}</div><p class="small">Step totals: ${Object.entries(s.step_seconds).map(([name,seconds])=>`${esc(name)} ${fmt(seconds)}s`).join(' · ')}. “Other” includes routing, waiting and unlogged time; model calls exclude the classifier.</p>`}
function optionList(id,values){const el=document.getElementById(id);el.innerHTML='<option value="">All</option>'+[...values].sort((a,b)=>String(a).localeCompare(String(b),undefined,{numeric:true})).map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('')}
optionList('filter-round',new Set(runs.map(r=>r.round).filter(x=>x!=null)));optionList('filter-tester',new Set(runs.map(r=>r.tester_number).filter(x=>x!=null)));optionList('filter-task',new Set(runs.map(r=>r.task_id).filter(Boolean)));optionList('filter-persona',new Set(runs.map(r=>r.persona).filter(Boolean)));
function renderRuns(){const round=document.getElementById('filter-round').value,tester=document.getElementById('filter-tester').value,task=document.getElementById('filter-task').value,persona=document.getElementById('filter-persona').value,search=document.getElementById('filter-search').value.toLocaleLowerCase(),failing=document.getElementById('filter-failing').checked;
const shown=runs.filter(r=>(!round||String(r.round)===round)&&(!tester||String(r.tester_number)===tester)&&(!task||r.task_id===task)&&(!persona||r.persona===persona)&&(!failing||r.grade==='fail')&&(!search||[r.question,r.answer,r.run_id,r.task_id,r.persona].some(x=>String(x??'').toLocaleLowerCase().includes(search))));
document.getElementById('run-count').textContent=`${shown.length} of ${runs.length} runs`;
document.getElementById('run-list').innerHTML=shown.length?shown.map(r=>{const failed=r.checks.filter(c=>c.status==='fail');const toolHtml=r.tools.length?r.tools.map(t=>`<div class="tool"><b>${esc(t.name)}</b> ${t.result_complete?'':badge('cannot','incomplete result')}<div class="small">${esc(JSON.stringify(t.args))} · ${esc(t.model)} · ${fmt(t.duration_s,3)}s</div><pre>${esc(typeof t.result==='string'?t.result:JSON.stringify(t.result,null,2))}</pre></div>`).join(''):'<p class="small">No logged tool calls.</p>';
return `<article class="card run-card"><div class="card-header"><h3>${esc(r.ts)} · ${esc(r.run_id)}</h3>${badge(r.grade,r.grade==='free'?'Free question':r.grade==='cannot'?'Cannot grade':r.grade==='pass'?'PASS':'FAIL',failed.map(c=>c.name+': '+c.reason).join('; '))}</div><div class="meta">${[['Round',r.round],['Tester',r.tester_number],['Task',r.task_id],['Persona',r.persona],['User',r.user_id],['Chat',r.chat_id],['Attempt',r.attempt]].map(([k,v])=>`<span>${esc(k)}: ${esc(v)}</span>`).join('')}</div><div class="qa"><div class="label">Question</div><p>${esc(r.question)}</p></div><div class="qa"><div class="label">Reply</div><p>${esc(r.answer??r.http_error)}</p></div><div class="small">Route ${esc(r.route)} · Intent ${esc(r.intent)} · Answer models ${r.models.length?esc(r.models.join(', ')):'— (classifier only or unavailable)'}<br>Latency ${fmt(r.latency_s)}s = classifier ${fmt(r.classifier_s)}s + logged answer model ${fmt(r.model_s)}s + tools ${fmt(r.tool_s,3)}s + other · Model calls ${esc(r.model_calls)} · Validator retries ${esc(r.validator_retries)} · Cited guideline ${esc(r.cited_guideline)}<br>Commit ${esc(r.git_commit)} · Config ${esc(r.config_name)} · Flags ${esc(r.flags.join(', ')||'—')}</div><details><summary>Tool calls (${r.tools.length})</summary>${toolHtml}</details>${r.checks.length?`<details><summary>Grade checks (${r.checks.length})</summary><div class="checks">${r.checks.map(c=>badge(c.status,c.name,c.reason)).join('')}</div></details>`:''}</article>`}).join(''):empty(runs.length?'No runs match these filters.':'No runs on this date.');}
document.querySelectorAll('.filters input,.filters select').forEach(el=>el.addEventListener(el.type==='search'?'input':'change',renderRuns));
function renderGrades(){document.getElementById('acceptance').innerHTML=data.acceptance.map(m=>`<tr><td>${esc(m.label)}</td><td>${esc(m.target)}</td><td>${esc(m.measured)}</td><td>${badge(m.status,m.status.toUpperCase())}</td></tr>`).join('');document.getElementById('under-40').textContent=data.stats.under_40==null?'Share of replies ≤ 40 s: —':`Share of replies ≤ 40 s: ${(data.stats.under_40*100).toFixed(1)}%`;
document.getElementById('matrix').innerHTML=tasks.map(t=>`<tr><td><b>${esc(t.uat)}</b><div class="small">${esc(t.id)} · ${esc(t.persona)}</div></td>${[1,2].flatMap(round=>[1,2].map(attempt=>{const cell=runs.filter(r=>Number(r.round)===round&&Number(r.attempt)===attempt&&r.task_id===t.uat);return `<td>${cell.length?cell.map(r=>{const failed=r.checks.filter(c=>c.status==='fail');const title=failed.map(c=>`${c.name}: ${c.reason}`).join('; ')||r.checks.filter(c=>c.status==='cannot').map(c=>`${c.name}: ${c.reason}`).join('; ')||r.run_id;return badge(r.grade,r.grade==='pass'?'✅':r.grade==='fail'?'❌':'◌',title)}).join(''):'—'}</td>`})).join('')}</tr>`).join('');
document.getElementById('phrasing').innerHTML=data.phrasing.map(p=>`<tr><td>${esc(p.task)}</td><td>${p.paired||'—'}</td><td>${p.paired?Object.entries(p.counts).map(([k,v])=>`${esc(k)}: ${v}`).join(' · '):'Insufficient paired attempts'}</td></tr>`).join('');
const findings=runs.flatMap(r=>r.checks.filter(c=>c.status==='fail').map(c=>({run:r,check:c})));document.getElementById('findings-count').textContent=`${findings.length} failed checks`;document.getElementById('findings').innerHTML=findings.length?findings.map(f=>`<div class="finding"><strong>${esc(f.run.run_id)} · ${esc(f.run.task_id)} · ${esc(f.check.name)}</strong><br>${esc(f.check.reason||'Check failed')}</div>`).join(''):'<p class="muted">No failed checks on this date.</p>';}
renderStats();renderRuns();renderGrades();
})();
</script></body></html>"""


def render_report(day: str, runs: list[dict], tasks: list[dict], watch: bool,
                  demo: bool = False) -> str:
    payload = {"runs": runs, "tasks": [{"id": t["id"], "uat": t["uat"], "persona": t["persona"]} for t in tasks],
               "stats": loop_stats([r for r in runs if r.get("task_id")]),
               "acceptance": acceptance(runs), "phrasing": phrasing(runs, tasks)}
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("&", "\\u0026")
    return (HTML_TEMPLATE.replace("__REFRESH__", '<meta http-equiv="refresh" content="15">' if watch else "")
            .replace("__DAY__", html.escape(day)).replace("__COUNT__", str(len(runs)))
            .replace("__SOURCE__", "Synthetic sample" if demo else "Local JSONL snapshot")
            .replace("__DEMO_BANNER__", '<div class="demo-banner" role="note">DEMO DATA · Two synthetic rounds. These runs are not in the coach log and are excluded from the real UAT report.</div>' if demo else "")
            .replace("__FOOTER_SOURCE__", "Generated from in-memory demo events, test_set.jsonl, ground_truth.json." if demo else "Generated from coach_calls.jsonl, test_set.jsonl, ground_truth.json.")
            .replace("__WATCH_LABEL__", ("Demo" if demo else "Live") + " · reloads every 15 s" if watch else "Demo sample" if demo else "Static snapshot")
            .replace("__DIAGRAM__", diagram_svg()).replace("__TOOLS__", tools_table()).replace("__DATA__", data))


def generate(day: str, watch: bool, log_path: Path = LOG_PATH, task_path: Path = TASK_PATH,
             truth_path: Path = TRUTH_PATH, output_path: Path | None = None,
             demo: bool = False) -> dict:
    output_path = output_path or (DEMO_OUTPUT_PATH if demo else OUTPUT_PATH)
    if demo and output_path.resolve() == OUTPUT_PATH.resolve():
        raise ValueError("demo mode cannot overwrite the real UAT report")
    events, tasks, people = load_inputs(None if demo else log_path, task_path, truth_path)
    if demo:
        events = demo_events(day, people)
    runs = group_runs(events, day)
    grade_runs(runs, tasks, people)
    report = render_report(day, runs, tasks, watch, demo=demo)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".uat_report_", suffix=".html", dir=output_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(report)
        os.replace(temp_name, output_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return {"runs": runs, "stats": loop_stats([r for r in runs if r.get("task_id")]),
            "acceptance": acceptance(runs),
            "output_path": output_path}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="local log date, YYYY-MM-DD")
    parser.add_argument("--watch", action="store_true", help="regenerate every 10 seconds; page reloads every 15 seconds")
    parser.add_argument("--demo", action="store_true", help="write two synthetic rounds to uat_report_demo.html; leave real logs and report alone")
    args = parser.parse_args()
    try:
        dt.date.fromisoformat(args.date)
    except ValueError:
        parser.error("--date must be YYYY-MM-DD")
    while True:
        result = generate(args.date, args.watch, demo=args.demo)
        runs = result["runs"]
        graded = [r for r in runs if r["grade"] not in ("free", "cannot")]
        print(f"{result['output_path']} · {len(runs)} runs · {len(graded)} graded · "
              f"{sum(r['grade'] == 'pass' for r in graded)} passed", flush=True)
        if not args.watch:
            return 0
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            print("Stopped watching.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
