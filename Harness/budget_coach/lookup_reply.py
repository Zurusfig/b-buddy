"""A one-figure answer written by code (UAT-05: "how much did I spend on the motorbike taxi in August?").

    render({"name": "sum_by_category", "args": {"month": "2026-08", "category": "transport"}, "result": 292.0}, "th")
        -> "เดือนสิงหาคม 2026 ค่าเดินทาง 292 บาท"

A model that is only asked to repeat one number can still write another: in the live UAT run the 4B model wrote 2,566
where the tool said 292, twice, and the question was rerun on the large model (22 s, six model calls). The figure,
category and month are all in the tool call, so code writes the sentence from them and no model sees the number.
Only a single successful lookup is handled; comparisons, budgets and advice stay with the model.
"""
from __future__ import annotations

import breakdown
import gaps

TEXT = {
    "en": {"one": "You spent {amount} baht on {category} in {month}.",
           "many": "{category} in {month}: {amount} baht in total ({parts})."},
    "th": {"one": "{month} ค่า{category} {amount} บาท",
           "many": "{month} {category} รวม {amount} บาท ({parts})"},
}
AND = {"en": " + ", "th": " + "}


def _name(cat: str, lang: str) -> str:
    return breakdown.LABEL[lang].get(cat, cat)  # a category the student made is shown as stored


def applies(calls: list) -> bool:
    """True for exactly one successful sum_by_category or sum_categories call."""
    if len(calls) != 1:
        return False
    c = calls[0]
    res, args = c.get("result"), c.get("args") or {}
    if not args.get("month"):
        return False
    if c["name"] == "sum_by_category":
        return isinstance(res, (int, float)) and not isinstance(res, bool) and bool(args.get("category"))
    if c["name"] == "sum_categories":
        return (isinstance(res, dict) and isinstance(res.get("by_category"), dict) and res["by_category"]
                and isinstance(res.get("total"), (int, float)))
    return False


def render(call: dict, lang: str) -> str:
    lang = lang if lang in TEXT else "en"
    month = gaps._label(call["args"]["month"], lang)
    res = call["result"]
    if call["name"] == "sum_by_category":
        return TEXT[lang]["one"].format(amount=breakdown.money(res), category=_name(call["args"]["category"], lang),
                                        month=month)
    names = list(res["by_category"])
    parts = ", ".join(f"{_name(c, lang)} {breakdown.money(v)}" for c, v in res["by_category"].items())
    return TEXT[lang]["many"].format(amount=breakdown.money(res["total"]), month=month, parts=parts,
                                     category=AND[lang].join(_name(c, lang) for c in names))
