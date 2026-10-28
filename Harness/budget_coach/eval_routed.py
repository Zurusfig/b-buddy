"""Evaluate the routed agent (agent.answer_routed) on eval_set.json (45) + the hard set (19).

    cd Harness/budget_coach && python eval_routed.py            # everything
    python eval_routed.py --limit 8                              # first 8 questions, for a quick check

Needs Ollama running with the small model pulled, and GATEWAY_KEY for advice / escalated questions.
Reports the pitch metrics: numeric accuracy, advice cites a source id, refusals, false refusals,
classifier accuracy, accuracy by class and language (Thai vs English), latency p50 / p95 by route,
validator retries and fallbacks. Overwrites eval_routed_results.md and eval_routed_rows.json.
Correctness reuses eval_agent.score: right tool call AND the gold number in the reply.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import agent
import eval_agent
import router

HERE = Path(__file__).resolve().parent
OUT_FILE = HERE / "eval_routed_results.md"
ROWS_FILE = HERE / "eval_routed_rows.json"
THAI = re.compile(r"[฀-๿]")
GUIDELINE_ID = re.compile(r"\bG\d{2}\b")
NUMERIC_CHECKS = ("value", "cmp", "over")


def labels() -> dict[str, dict]:
    """Gold intent and required source id per eval_set question; hard questions have neither."""
    return {x["id"]: x for x in json.loads((HERE / "eval_set.json").read_text("utf-8"))}


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "n/a"


def percentile(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, round(p / 100 * (len(s) - 1)))] if s else float("nan")


def main():
    qs = eval_agent.items()
    if "--limit" in sys.argv:
        qs = qs[: int(sys.argv[sys.argv.index("--limit") + 1])]
    gold = labels()
    rows = []
    for i, q in enumerate(qs, 1):
        r = eval_agent.score(q, agent.answer_routed(q["question"]))
        lab = gold.get(q["id"], {})
        row = {"id": q["id"], "set": q["set"], "question": q["question"],
               "lang": "TH" if THAI.search(q["question"]) else "EN",
               "gold_intent": lab.get("intent"), "needs_source_id": lab.get("needs_source_id"),
               "check": q["check"], "refusal_expected": q["accept"] == "decline",
               **{k: r[k] for k in ("answer", "calls", "flags", "latency", "intent", "route",
                                    "escalated_by", "validator_retries", "tool_ok", "correct",
                                    "false_decline", "classifier_error")}}
        row["cited"] = bool(GUIDELINE_ID.search(r["answer"]))
        rows.append(row)
        print(f"[{i}/{len(qs)}] {q['id']:<15} intent={row['intent']} route={row['route']:<14} "
              f"correct={row['correct']} {row['latency']:.1f}s flags={row['flags']}", flush=True)
    ROWS_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), "utf-8")
    report(rows)


def report(rows: list[dict]) -> None:
    n = len(rows)
    numeric = [r for r in rows if r["check"] in NUMERIC_CHECKS]
    advice = [r for r in rows if r["gold_intent"] == "advice" or
              (r["set"] == "hard" and r["check"] is None and not r["refusal_expected"])]
    refusals = [r for r in rows if r["refusal_expected"]]
    labelled = [r for r in rows if r["gold_intent"]]
    lat = [r["latency"] for r in rows]
    L = ["# Budget coach: routed agent evaluation", "",
         f"- `agent.answer_routed` on {n} questions (eval_set + hard set). Small model `{agent.SMALL_MODEL}` on "
         f"Ollama, large model `{agent.BIG_MODEL}` on the gateway. Gold values come from `tools.py`.",
         "- correct = an acceptable tool call was made AND the reply contains the gold number "
         "(refusals: `decline` called).",
         "- Latency is wall time per question including the classifier, on this machine.", "",
         "## Pitch targets", "",
         "| metric | target | result |", "|---|---|---|",
         f"| Numeric accuracy | ≥ 85% | {pct(sum(r['correct'] for r in numeric), len(numeric))} |",
         f"| Advice cites a source id | 100% | {pct(sum(r['cited'] for r in advice), len(advice))} |",
         f"| Investment / off-topic refused | 100% | {pct(sum(r['correct'] for r in refusals), len(refusals))} |",
         f"| False refusals (in-scope question declined) | 0 | {sum(r['false_decline'] for r in rows)} of "
         f"{n - len(refusals)} |",
         f"| Classifier accuracy (eval_set intent labels) | report | "
         f"{pct(sum(router.coarse(r['intent']) == r['gold_intent'] for r in labelled), len(labelled))} |",
         f"| Overall correct | report | {pct(sum(r['correct'] for r in rows), n)} |",
         f"| Latency p50 / p95 (s) | report | {percentile(lat, 50):.1f} / {percentile(lat, 95):.1f} |",
         f"| Validator retries / fallbacks | report | {sum(r['validator_retries'] for r in rows)} / "
         f"{sum('validator_fallback' in r['flags'] for r in rows)} |", "",
         "## By class and language", "", "| group | n | correct |", "|---|---|---|"]
    groups = defaultdict(list)
    for r in rows:
        cls = r["gold_intent"] or ("refusal" if r["refusal_expected"] else "hard")
        groups[f"class: {cls}"].append(r)
        groups[f"language: {r['lang']}"].append(r)
    for g in sorted(groups):
        L.append(f"| {g} | {len(groups[g])} | {pct(sum(r['correct'] for r in groups[g]), len(groups[g]))} |")

    L += ["", "## By route", "", "| route | n | correct | latency p50 (s) | latency p95 (s) |", "|---|---|---|---|---|"]
    by_route = defaultdict(list)
    for r in rows:
        by_route[r["route"]].append(r)
    for route, rs in sorted(by_route.items()):
        t = [r["latency"] for r in rs]
        L.append(f"| {route} | {len(rs)} | {pct(sum(r['correct'] for r in rs), len(rs))} | "
                 f"{percentile(t, 50):.1f} | {percentile(t, 95):.1f} |")
    esc = Counter(t for r in rows for t in r["escalated_by"])
    L += ["", f"Escalations small -> large: {sum(bool(r['escalated_by']) for r in rows)} "
              f"({', '.join(f'{k} {v}' for k, v in esc.items()) or 'none'}).", ""]

    confusion = Counter((r["gold_intent"], router.coarse(r["intent"])) for r in labelled
                        if router.coarse(r["intent"]) != r["gold_intent"])
    L += ["## Classifier misses (gold -> predicted)", ""]
    L += [f"- {g} -> {p}: {c}" for (g, p), c in confusion.items()] or ["- none"]
    L += ["", "## Failures", ""]
    for r in rows:
        if not r["correct"]:
            calls = ", ".join(f"{c['name']}({json.dumps(c['args'], ensure_ascii=False)})" for c in r["calls"])
            L.append(f"- {r['id']} [{r['route']}] {r['question']} -> calls: {calls or 'none'} | flags {r['flags']} "
                     f"| reply: {' '.join(r['answer'].split())[:160]}")
    L.append("")
    OUT_FILE.write_text("\n".join(L), "utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
