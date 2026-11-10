"""A one-figure answer written by code (UAT-05: "how much did I spend on the motorbike taxi in August?").

    render({"name": "sum_by_category", "args": {"month": "2026-08", "category": "transport"}, "result": 292.0}, "th")
        -> "เดือนสิงหาคม 2026 ค่าเดินทาง 292 บาท"

A model that is only asked to repeat one number can still write another: in the live UAT run the 4B model wrote 2,566
where the tool said 292, twice, and the question was rerun on the large model (22 s, six model calls). The figure,
category and month are all in the tool call, so code writes the sentence from them and no model sees the number.
Only a single successful lookup is handled; comparisons and advice stay with the model. The over-budget list and the
month summary are written by code too: the 4B model wrote "93.0 บาท compared to 4000.0 บาท" in a Thai reply (a language
retry, then the large model: about 14 s instead of 3 s) and "$2,070" for baht in an English one.
"""
from __future__ import annotations

import breakdown
import categories
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


OVER = {
    "en": {"none": "You are not over budget in any category in {month}.",
           "head": "In {month} you are over budget in {n} {word}:",
           "row": "- {category}: spent {spent} of {limit} baht ({over} baht over)",
           "fine": "{category} is not over budget."},
    "th": {"none": "{month} ไม่มีหมวดไหนใช้เกินงบ",
           "head": "{month} ใช้เกินงบ {n} หมวด",
           "row": "- {category}: ใช้ไป {spent} บาท จากงบ {limit} บาท (เกิน {over} บาท)",
           "fine": "หมวด{category}ไม่เกินงบ"},
}
SUMMARY = {
    "en": {"head": "{month}: income {income} baht, spending {spending} baht.",
           "left": "You have {net} baht left over.", "short": "You spent {net} baht more than you earned.",
           "refunds": "Refunds of {refunds} baht are already taken off your spending."},
    "th": {"head": "{month} รายรับ {income} บาท รายจ่าย {spending} บาท",
           "left": "เหลือ {net} บาท", "short": "ใช้เกินรายรับ {net} บาท",
           "refunds": "หักเงินคืน {refunds} บาท ออกจากรายจ่ายแล้ว"},
}


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def applies(calls: list) -> bool:
    """True for exactly one successful sum_by_category, sum_categories, over_budget or month_summary call."""
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
    if c["name"] == "over_budget":
        return isinstance(res, list) and all(
            isinstance(r, dict) and r.get("category") and all(_number(r.get(k)) for k in ("spent", "limit", "over_by"))
            for r in res)
    if c["name"] == "month_summary":
        return isinstance(res, dict) and all(_number(res.get(k)) for k in ("income_total", "spending_total", "net_cashflow"))
    return False


def _over(res: list, month: str, lang: str, question: str) -> str:
    t = OVER[lang]
    lines = [t["head"].format(month=month, n=len(res), word="category" if len(res) == 1 else "categories")] if res else [
        t["none"].format(month=month)]
    for r in res:
        lines.append(t["row"].format(category=_name(r["category"], lang), spent=breakdown.money(r["spent"]),
                                     limit=breakdown.money(r["limit"]), over=breakdown.money(r["over_by"])))
    if res:  # a category the question asked about that is not in the list is within its budget: say so
        over = {r["category"] for r in res}
        lines += [t["fine"].format(category=_name(c, lang)) for c in categories.implied_categories(question)
                  if c not in over]
    return "\n".join(lines)


def _summary(res: dict, month: str, lang: str) -> str:
    t, net = SUMMARY[lang], res["net_cashflow"]
    parts = [t["head"].format(month=month, income=breakdown.money(res["income_total"]),
                              spending=breakdown.money(res["spending_total"])),
             (t["left"] if net >= 0 else t["short"]).format(net=breakdown.money(abs(net)))]
    if _number(res.get("refunds_total")) and res["refunds_total"] > 0:
        parts.append(t["refunds"].format(refunds=breakdown.money(res["refunds_total"])))
    return (" " if lang == "en" else "\n").join(parts)


def render(call: dict, lang: str, question: str = "") -> str:
    lang = lang if lang in TEXT else "en"
    month = gaps._label(call["args"]["month"], lang)
    res = call["result"]
    if call["name"] == "over_budget":
        return _over(res, month, lang, question)
    if call["name"] == "month_summary":
        return _summary(res, month, lang)
    if call["name"] == "sum_by_category":
        return TEXT[lang]["one"].format(amount=breakdown.money(res), category=_name(call["args"]["category"], lang),
                                        month=month)
    names = list(res["by_category"])
    parts = ", ".join(f"{_name(c, lang)} {breakdown.money(v)}" for c, v in res["by_category"].items())
    return TEXT[lang]["many"].format(amount=breakdown.money(res["total"]), month=month, parts=parts,
                                     category=AND[lang].join(_name(c, lang) for c in names))
