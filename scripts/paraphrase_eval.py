"""Share of rephrasings of the 11 UAT tasks that are answered right, asked back, or answered WRONG.

Usage: python scripts/paraphrase_eval.py [--ids T01,T04] [--limit 3] [--out report.md]
Each line of Harness/data/paraphrases.jsonl is {"task", "input"}: the task's persona and grading rules from
Harness/data/test_set.jsonl are applied to the new sentence, exactly as scripts/grade.py does for the original.
Requires Ollama; advice also needs the course gateway. It never writes to the saved evaluation reports.

No coach can understand every phrasing, so the aim is not "everything passes". An ask-back (route "clarify") costs
the student one tap and never shows a wrong figure, so it is counted apart from a pass. A wrong answer is the failure.
Release gate: at most 5% wrong answers overall (no task above 20%), and at most 25% ask-backs.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade  # noqa: E402

ROOT = grade.ROOT
WRONG_GATE, TASK_WRONG_GATE, ASK_GATE = 0.05, 0.20, 0.25


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", help="comma-separated task IDs; default: all 11")
    parser.add_argument("--limit", type=int, help="at most this many rephrasings per task")
    parser.add_argument("--out", help="also write the report to this markdown file")
    args = parser.parse_args()
    tasks, people = grade.load()
    by_id = {t["id"]: t for t in tasks}
    wanted = set(args.ids.split(",")) if args.ids else set(by_id)
    lines = [json.loads(x) for x in (ROOT / "Harness/data/paraphrases.jsonl").read_text("utf-8").splitlines() if x.strip()]
    per_task = defaultdict(int)
    results: dict[str, list] = defaultdict(list)
    for item in lines:
        tid = item["task"]
        if tid not in wanted or (args.limit and per_task[tid] >= args.limit):
            continue
        per_task[tid] += 1
        task = {**by_id[tid], "input": item["input"]}
        try:
            result = grade.persona_agent.answer_persona(task["input"], task["persona"])
            errors = grade.grade(task, result, people)
        except Exception as exc:  # a crash is a failure, reported with its type only
            result, errors = {}, [f"run error: {type(exc).__name__}"]
        asked = bool(errors) and result.get("route") == "clarify"
        status = "PASS" if not errors else ("ASK" if asked else "FAIL")
        results[tid].append((item["input"], errors, result.get("latency", 0.0), status))
        print(f"{tid} {status} {result.get('latency', 0):5.1f}s {item['input'][:50]}"
              + ("" if not errors else "  <- " + "; ".join(errors)), flush=True)

    total = ok_n = ask_n = wrong_n = 0
    report = ["| Task | Pass | Asked back | Wrong | Wrong answers |", "|---|---|---|---|---|"]
    worst_wrong = 0.0
    times: list[float] = []
    for tid in sorted(results):
        rows = results[tid]
        ok = sum(1 for r in rows if r[3] == "PASS")
        ask = sum(1 for r in rows if r[3] == "ASK")
        wrong = len(rows) - ok - ask
        total, ok_n, ask_n, wrong_n = total + len(rows), ok_n + ok, ask_n + ask, wrong_n + wrong
        worst_wrong = max(worst_wrong, wrong / len(rows))
        times += [r[2] for r in rows]
        fails = "; ".join(f"“{q}” ({', '.join(e)})" for q, e, _, st in rows if st == "FAIL") or "-"
        report.append(f"| {tid} | {ok}/{len(rows)} | {ask} | {wrong} | {fails} |")
    times.sort()
    median = times[len(times) // 2] if times else 0.0
    summary = (f"Total {total}: {ok_n} pass, {ask_n} asked back ({ask_n / max(total, 1):.0%}), {wrong_n} wrong "
               f"({wrong_n / max(total, 1):.0%}); worst task wrong {worst_wrong:.0%}; "
               f"median reply {median:.1f}s, slowest {times[-1] if times else 0:.1f}s")
    good = (wrong_n / max(total, 1) <= WRONG_GATE and worst_wrong <= TASK_WRONG_GATE
            and ask_n / max(total, 1) <= ASK_GATE)
    gate = "GATE PASS" if good else "GATE FAIL"
    text = "\n".join(report) + f"\n\n{summary}\n{gate} (wrong <= {WRONG_GATE:.0%}, any task wrong <= {TASK_WRONG_GATE:.0%}, " \
                               f"asked back <= {ASK_GATE:.0%})"
    print("\n" + text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
