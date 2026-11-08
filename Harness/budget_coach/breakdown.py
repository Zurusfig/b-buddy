"""A category breakdown written by code (UAT-02: "what did I spend on?").

    render({"month": "2026-10", "by_category": {"food": 4093.0, ...}, "total": 6430.0}, "th")
        -> "รายจ่ายเดือนตุลาคม 2026\n- อาหาร: 4,093 บาท\n...\nรวม 6,430 บาท"

The reply is only a list of amounts, so a model has nothing to add and two things to get wrong: it invented Thai
category names (entertainment came back as "เที่ยวบิน/กิจกรรม", bills as "ค่าใช้จ่าย") and it varied the number
format. Code writes it from a fixed label table, in the question's language, and no second model call is made.
"""
from __future__ import annotations

import gaps

LABEL = {
    "en": {"food": "Food", "transport": "Transport", "shopping": "Shopping", "entertainment": "Entertainment",
           "bills": "Bills and utilities", "education": "Education", "health": "Health", "other": "Other"},
    "th": {"food": "อาหาร", "transport": "เดินทาง", "shopping": "ช้อปปิ้ง", "entertainment": "บันเทิง",
           "bills": "บิลและค่าสาธารณูปโภค", "education": "การศึกษา", "health": "สุขภาพ", "other": "อื่นๆ"},
}
TEXT = {"en": {"head": "Spending in {month}", "unit": "baht", "total": "Total", "none": "No spending recorded."},
        "th": {"head": "รายจ่าย{month}", "unit": "บาท", "total": "รวม", "none": "ไม่มีรายจ่ายที่บันทึกไว้"}}


def money(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}"


def is_breakdown(result) -> bool:
    return isinstance(result, dict) and isinstance(result.get("by_category"), dict) and "total" in result


def render(result: dict, lang: str) -> str:
    lang = lang if lang in TEXT else "en"
    t = TEXT[lang]
    lines = [t["head"].format(month=gaps._label(result["month"], lang))]
    rows = sorted(((c, v) for c, v in result["by_category"].items() if v), key=lambda cv: -abs(cv[1]))
    for cat, value in rows:
        lines.append(f"- {LABEL[lang].get(cat, cat)}: {money(value)} {t['unit']}")  # a custom name is shown as stored
    lines.append(f"{t['total']} {money(result['total'])} {t['unit']}" if rows else t["none"])
    return "\n".join(lines)
