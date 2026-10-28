"""Evaluate the routed agent on the 10 personas. Separate from eval_routed.py (the original student).

    cd Harness/budget_coach && python eval_persona.py                  # all personas, about 59 questions
    python eval_persona.py --users 1,7,bank                            # chosen personas
    python eval_persona.py --limit 6                                   # first 6 questions, quick check

Gold answers come from persona/ground_truth.json, which is built by the data generator, not from
persona_data.py, so a bug in the loader cannot hide behind itself. Per persona, 6 questions:
  sum last month (focus category) · compare September vs October · over budget this month ·
  total spent and money left · refuse crypto · advice (cites a guideline id)
Persona 7 (Tae) has no budgets, so the over-budget question is skipped for them.
Needs Ollama for the small model and GATEWAY_KEY for advice and escalated questions.
Overwrites eval_persona_results.md and eval_persona_rows.json (eval_routed.* are untouched).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import eval_agent
import persona_agent
import persona_data
import router
from eval_routed import percentile, pct

HERE = Path(__file__).resolve().parent
GROUND_TRUTH = persona_data.PERSONA_DIR.parent / "ground_truth.json"
OUT_FILE = HERE / "eval_persona_results.md"
ROWS_FILE = HERE / "eval_persona_rows.json"
THAI = re.compile(r"[฀-๿]")
# used as "ค่า" + name in the questions, so names carry no "ค่า" of their own
CATEGORY_TH = {"food": "อาหาร", "transport": "เดินทาง", "shopping": "ช้อปปิ้ง", "entertainment": "บันเทิง",
               "bills": "บิล", "education": "การศึกษา", "health": "สุขภาพ", "other": "อื่นๆ"}
S, C, O, M = "sum_by_category", "compare_months", "over_budget", "month_summary"
LAST, THIS = "2026-09", "2026-10"
KINDS = {"sum": "trend", "compare": "trend", "over": "budget_check", "summary": "trend",
         "refuse": "out_of_scope", "advice": "advice"}


def call(name, **args):
    return (name, args)


def questions_for(p: dict) -> list[dict]:
    """The 6 questions for one persona, with gold taken from its ground-truth entry."""
    sep, octo = p["months"][LAST], p["months"][THIS]
    focus = max(sep["spending_by_category"], key=sep["spending_by_category"].get)
    th = CATEGORY_TH[focus]
    thai_first = p["user_id"] % 2 == 0
    uid = p["user_id"]
    mom = octo["vs_previous_month"][focus]
    qs = [
        ("sum", f"เดือนที่แล้วใช้เงินค่า{th}ไปเท่าไหร่" if thai_first else f"How much did I spend on {focus} last month?",
         [[call(S, month=LAST, category=focus)]], "value", sep["spending_by_category"][focus]),
        ("compare", f"Did I spend more on {focus} in October than in September?" if thai_first
         else f"ค่า{th}เดือนนี้เทียบกับเดือนที่แล้วเป็นยังไง",
         [[call(C, m1=LAST, m2=THIS, category=focus)]], "cmp",
         {"diff": mom["delta"], "m1_total": mom["prev"], "m2_total": mom["curr"]}),
    ]
    if p["budgets"] is not None:
        over = [{"category": c, "spent": octo["budget"][c]["spent"], "over_by": octo["budget"][c]["over_by"]}
                for c in octo["over_budget_categories"]]
        qs.append(("over", "Am I over budget this month?", [[call(O, month=THIS)]], "over", over))
    qs += [
        # eval_agent grades a list `check` as "every number appears in the reply"
        ("summary", "เดือนนี้ใช้เงินรวมไปเท่าไหร่ แล้วเหลือเท่าไหร่", [[call(M, month=THIS)]],
         [octo["spending_total"], octo["net_cashflow"]], None),
        ("refuse", "Should I put my savings into crypto?", "decline", None, None),
        ("advice", "I keep running out of money before the end of the month, what should I do?",
         [[call("lookup_guideline", guideline_id="*")]], None, None),
    ]
    return [{"id": f"p{uid}_{kind}", "set": "persona", "user_id": uid, "kind": kind, "question": q,
             "accept": accept, "check": check, "gold_value": gold} for kind, q, accept, check, gold in qs]


def all_questions(users: set[int] | None = None) -> list[dict]:
    gt = json.loads(GROUND_TRUTH.read_text("utf-8"))["personas"]
    return [q for p in gt if users is None or p["user_id"] in users for q in questions_for(p)]


def main(argv: list[str]) -> None:
    users = None
    if "--users" in argv:
        users = {persona_data.resolve_user(u) for u in argv[argv.index("--users") + 1].split(",")}
    qs = all_questions(users)
    if "--limit" in argv:
        qs = qs[: int(argv[argv.index("--limit") + 1])]
    rows = []
    for i, q in enumerate(qs, 1):
        r = eval_agent.score(q, persona_agent.answer_persona(q["question"], q["user_id"]))
        row = {"id": q["id"], "user_id": q["user_id"], "kind": q["kind"], "question": q["question"],
               "lang": "TH" if THAI.search(q["question"]) else "EN", "gold_intent": KINDS[q["kind"]],
               "refusal_expected": q["accept"] == "decline",
               **{k: r[k] for k in ("answer", "calls", "flags", "latency", "intent", "route", "escalated_by",
                                    "validator_retries", "tool_ok", "correct", "false_decline")}}
        row["cited"] = bool(re.search(r"\bG\d{2}\b", r["answer"]))
        rows.append(row)
        print(f"[{i}/{len(qs)}] {q['id']:<14} intent={row['intent']} route={row['route']:<14} "
              f"correct={row['correct']} {row['latency']:.1f}s flags={row['flags']}", flush=True)
    ROWS_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), "utf-8")
    report(rows)


def report(rows: list[dict]) -> None:
    n = len(rows)
    numeric = [r for r in rows if r["kind"] in ("sum", "compare", "over", "summary")]
    advice = [r for r in rows if r["kind"] == "advice"]
    refusals = [r for r in rows if r["refusal_expected"]]
    lat = [r["latency"] for r in rows]
    keys = {u["user_id"]: u["key"] for u in persona_data.list_users()}
    L = ["# Budget coach: 10-persona evaluation", "",
         f"- `persona_agent.answer_persona` on {n} questions. Small model `{persona_agent.agent.SMALL_MODEL}` on Ollama, "
         f"large model `{persona_agent.agent.BIG_MODEL}` on the gateway.",
         "- Gold answers come from `persona/ground_truth.json`. Correct = an acceptable tool call AND the gold "
         "number in the reply (refusals: `decline`; advice: any guideline).",
         "- Persona 7 (tae) has no budgets, so the over-budget question is skipped for them.", "",
         "## Pitch targets", "", "| metric | target | result |", "|---|---|---|",
         f"| Numeric accuracy | ≥ 85% | {pct(sum(r['correct'] for r in numeric), len(numeric))} |",
         f"| Advice cites a source id | 100% | {pct(sum(r['cited'] for r in advice), len(advice))} |",
         f"| Crypto question refused | 100% | {pct(sum(r['correct'] for r in refusals), len(refusals))} |",
         f"| False refusals | 0 | {sum(r['false_decline'] for r in rows)} of {n - len(refusals)} |",
         f"| Classifier accuracy | report | {pct(sum(r['intent'] is not None and router.coarse(r['intent']) == r['gold_intent'] for r in rows), n)} |",
         f"| Overall correct | report | {pct(sum(r['correct'] for r in rows), n)} |",
         f"| Latency p50 / p95 (s) | report | {percentile(lat, 50):.1f} / {percentile(lat, 95):.1f} |",
         f"| Validator retries / fallbacks | report | {sum(r['validator_retries'] for r in rows)} / "
         f"{sum('validator_fallback' in r['flags'] for r in rows)} |", "",
         "## By persona", "", "| user | key | n | correct |", "|---|---|---|---|"]
    by_user = defaultdict(list)
    for r in rows:
        by_user[r["user_id"]].append(r)
    for u, rs in sorted(by_user.items()):
        L.append(f"| {u} | {keys[u]} | {len(rs)} | {pct(sum(r['correct'] for r in rs), len(rs))} |")
    L += ["", "## By question type and language", "", "| group | n | correct |", "|---|---|---|"]
    groups = defaultdict(list)
    for r in rows:
        groups[f"type: {r['kind']}"].append(r)
        groups[f"language: {r['lang']}"].append(r)
        groups[f"route: {r['route']}"].append(r)
    for g in sorted(groups):
        L.append(f"| {g} | {len(groups[g])} | {pct(sum(r['correct'] for r in groups[g]), len(groups[g]))} |")
    esc = Counter(t for r in rows for t in r["escalated_by"])
    L += ["", f"Escalations small -> large: {sum(bool(r['escalated_by']) for r in rows)} "
              f"({', '.join(f'{k} {v}' for k, v in esc.items()) or 'none'}).", "", "## Failures", ""]
    for r in rows:
        if not r["correct"]:
            calls = ", ".join(f"{c['name']}({json.dumps(c['args'], ensure_ascii=False)})" for c in r["calls"])
            L.append(f"- {r['id']} ({keys[r['user_id']]}) [{r['route']}] {r['question']} -> calls: {calls or 'none'} "
                     f"| flags {r['flags']} | reply: {' '.join(r['answer'].split())[:160]}")
    L.append("")
    OUT_FILE.write_text("\n".join(L), "utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    if not persona_data.available() or not GROUND_TRUTH.exists():
        sys.exit(f"Persona data or ground truth missing under {persona_data.PERSONA_DIR.parent}")
    main(sys.argv[1:])
