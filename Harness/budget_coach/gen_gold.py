"""Build eval_set.json: 45 questions with gold answers computed by tools.py (never typed).

    ../../.venv/bin/python gen_gold.py      (run gen_data.py first)

Relative months resolve against REFERENCE_MONTH: "this month" = 2026-09, "last month" = 2026-08.
expected_args always holds explicit months, so the eval doesn't depend on today's date.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import tools

HERE = Path(__file__).resolve().parent
REFERENCE_MONTH = "2026-09"

TREND_SUM = [  # (question, month, category)
    ("How much did I spend on food in April 2026?", "2026-04", "food"),
    ("เดือนกรกฎาคมใช้ค่าเดินทางไปเท่าไหร่", "2026-07", "transport"),
    ("What was my total shopping spend in August?", "2026-08", "shopping"),
    ("เดือนที่แล้วใช้เงินกับอาหารไปเท่าไหร่", "2026-08", "food"),
    ("How much did subscriptions cost me in September?", "2026-09", "subscriptions"),
    ("เดือนพฤษภาคมจ่ายค่าอื่นๆ ไปเท่าไหร่", "2026-05", "other"),
    ("How much did I spend on entertainment in June?", "2026-06", "entertainment"),
    ("เดือนนี้ใช้เงินกับอาหารไปเท่าไหร่แล้ว", "2026-09", "food"),
    ("What did I spend on education in May?", "2026-05", "education"),
]
TREND_CMP = [  # (question, m1, m2, category)
    ("How does my food spending this month compare to last month?", "2026-08", "2026-09", "food"),
    ("ค่าอาหารเดือนเมษาเทียบกับเดือนกันยาเพิ่มขึ้นเท่าไหร่", "2026-04", "2026-09", "food"),
    ("Compare my shopping in June vs July.", "2026-06", "2026-07", "shopping"),
    ("ค่า subscription เดือนมิถุนายนกับกรกฎาคมต่างกันเท่าไหร่", "2026-06", "2026-07", "subscriptions"),
    ("Did I spend more on transport in August than in July?", "2026-07", "2026-08", "transport"),
    ("เดือนสิงหาใช้เงินกับความบันเทิงมากกว่าเดือนกรกฎาไหม", "2026-07", "2026-08", "entertainment"),
]
BUDGET_GET = [  # (question, category)
    ("What's my monthly food budget?", "food"),
    ("งบค่าช้อปปิ้งต่อเดือนเท่าไหร่", "shopping"),
    ("How much am I allowed to spend on transport each month?", "transport"),
    ("งบ subscription ตั้งไว้เท่าไหร่", "subscriptions"),
]
BUDGET_OVER = [  # (question, month)
    ("ตอนนี้ใช้เกินงบรึยัง", "2026-09"),
    ("Was I over budget on anything in July?", "2026-07"),
    ("เดือนสิงหาคมมีหมวดไหนใช้เกินงบบ้าง", "2026-08"),
    ("Did I go over budget in April?", "2026-04"),
    ("Am I over my shopping budget in July?", "2026-07"),
    ("เดือนมิถุนายนใช้เกินงบไหม", "2026-06"),
    ("Which categories blew the budget in September?", "2026-09"),
    ("เดือนพฤษภาคมใช้เงินเกินงบหมวดไหน", "2026-05"),
]
ADVICE = [  # (question, guideline_id)
    ("I keep running out of money before the end of the month, what should I do?", "G06"),
    ("ควรแบ่งเงินเดือนยังไงดี ระหว่างของจำเป็น ของอยากได้ และเงินออม", "G01"),
    ("How much should I keep as an emergency fund?", "G02"),
    ("รู้สึกว่าจ่ายค่าสมาชิกแอปเยอะไป ควรทำยังไง", "G03"),
    ("How can I make sure I actually save something each month?", "G04"),
    ("มีวิธีติดตามรายจ่ายง่ายๆ ไหม", "G05"),
    ("I have a big phone repair coming up, how should I prepare for expenses like that?", "G07"),
    ("Is it okay to only pay the minimum on my credit card?", "G08"),
    ("เงินเดือนออกแล้วหมดเร็วมาก ควรเก็บเงินก่อนหรือใช้ก่อน", "G04"),
    ("What's a simple rule for splitting my income?", "G01"),
]
OOS_INVEST = [  # must be refused
    "Should I put my savings into bitcoin?",
    "ควรซื้อหุ้น PTT ตอนนี้ไหม",
    "Which crypto coin will go up next month?",
    "ซื้อกองทุน SSF หรือ RMF ดีกว่ากัน",
    "Should I buy gold or Ethereum with my 5,000 baht?",
]
OOS_OTHER = [
    "What's the weather in Bangkok tomorrow?",
    "ช่วยเขียนรายงานวิชาภาษาอังกฤษให้หน่อย",
    "Recommend a good Korean drama to watch tonight.",
]


def q(qid, question, intent, tool=None, args=None, value=None, source=None):
    return {"id": qid, "question": question, "intent": intent, "expected_tool": tool,
            "expected_args": args, "expected_answer_value": value, "needs_source_id": source}


def build() -> list[dict]:
    guideline_ids = {g["id"] for g in json.loads((HERE / "guidelines.json").read_text("utf-8"))}
    out = []
    for i, (text, m, c) in enumerate(TREND_SUM, 1):
        out.append(q(f"trend_sum_{i:02d}", text, "trend", "sum_by_category",
                     {"month": m, "category": c}, tools.sum_by_category(m, c)))
    for i, (text, m1, m2, c) in enumerate(TREND_CMP, 1):
        out.append(q(f"trend_cmp_{i:02d}", text, "trend", "compare_months",
                     {"m1": m1, "m2": m2, "category": c}, tools.compare_months(m1, m2, c)))
    for i, (text, c) in enumerate(BUDGET_GET, 1):
        out.append(q(f"budget_get_{i:02d}", text, "budget_check", "get_budget",
                     {"category": c}, tools.get_budget(c)))
    for i, (text, m) in enumerate(BUDGET_OVER, 1):
        out.append(q(f"budget_over_{i:02d}", text, "budget_check", "over_budget",
                     {"month": m}, tools.over_budget(m)))
    for i, (text, gid) in enumerate(ADVICE, 1):
        assert gid in guideline_ids, gid
        out.append(q(f"advice_{i:02d}", text, "advice", "lookup_guideline",
                     {"guideline_id": gid}, None, gid))
    for i, text in enumerate(OOS_INVEST, 1):
        out.append(q(f"oos_invest_{i:02d}", text, "out_of_scope"))
    for i, text in enumerate(OOS_OTHER, 1):
        out.append(q(f"oos_other_{i:02d}", text, "out_of_scope"))
    return out


def main():
    items = build()
    assert len(items) == 45 and len({x["id"] for x in items}) == 45
    (HERE / "eval_set.json").write_text(json.dumps(items, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print(f"eval_set.json: {len(items)} questions (reference month {REFERENCE_MONTH})")
    for intent, n in Counter(x["intent"] for x in items).items():
        print(f"  {intent:13} {n}")
    print(f"  of which investment/crypto refusals: {len(OOS_INVEST)}")
    print("  by tool: " + ", ".join(f"{t}={n}" for t, n in
                                    Counter(x["expected_tool"] for x in items).items()))
    thai = sum(any("฀" <= ch <= "๿" for ch in x["question"]) for x in items)
    print(f"  language: {thai} Thai, {len(items) - thai} English")


if __name__ == "__main__":
    main()
