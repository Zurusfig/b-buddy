"""Say what the coach understood, and ask back when the answer does not match the question.

A 4B model can read a new phrasing wrongly, and no word list can cover every phrasing. So instead of trying to
understand everything, the coach makes a wrong reading visible and cheap to correct (UAT-02 answered a different
question than the one asked):

    line(calls, "en")       -> "Looked up: Food, September 2026"        printed under every looked-up answer
    doubt(q, calls, ctx)    -> "month" | "category" | "list" | None      the answer does not match what was asked
    reading(q, ctx, lang)   -> {"ask", "options"}                       buttons built from what code can read

Code decides all of it from the question's own words and the tool calls, so no model is asked.
"""
from __future__ import annotations

import re

import breakdown
import categories
import gaps

EN_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
TH_STEMS = ("มกรา", "กุมภา", "มีนา", "เมษา", "พฤษภา", "มิถุนา", "กรกฎา", "สิงหา", "กันยา", "ตุลา", "พฤศจิกา", "ธันวา")
LAST = re.compile(r"last month|previous month|เดือนที่แล้ว|เดือนก่อน|เดือนที่ผ่านมา|เดือนที่ล่วงมา", re.I)
THIS = re.compile(r"this month|เดือนนี้", re.I)
# Asking for a list ("what did I spend on", "แยกหมวด") expects the all-categories tool, not a single total.
LIST_CUE = re.compile(r"what did i spen[dt] (?:on|my)|where (?:did|does) my money|break ?down|each category|by category|"
                      r"per category|อะไรบ้าง|ไรบ้าง|หายไปไหน|ไปไหนหมด|แยกหมวด|แต่ละหมวด", re.I)
LABELLED = {"sum_by_category", "sum_categories", "compare_months", "over_budget", "month_summary", "get_budget"}
PREFIX = {"en": "Looked up: ", "th": "ดูข้อมูล: "}


def _month_text(ym: str, lang: str) -> str:
    return gaps._label(ym, lang)


def _cat(cat: str, lang: str) -> str:
    return breakdown.LABEL[lang].get(cat, cat)


def named_months(question: str, months: tuple, reference: str) -> set[str]:
    """The months the question names ("last month", "this month", "July", "สิงหา"), as YYYY-MM. Empty when none."""
    q = (question or "").lower()
    out: set[str] = set()
    if reference and months:
        earlier = [m for m in months if m < reference]
        if LAST.search(q) and earlier:
            out.add(earlier[-1])
        if THIS.search(q):
            out.add(reference)
    for i, short in enumerate(EN_MONTHS, 1):
        if re.search(rf"\b{short}[a-z]*\b", q) and not (short == "mar" and "march" not in q and not re.search(r"\bmar\b", q)):
            out.add(_latest(i, months, reference))
    for i, stem in enumerate(TH_STEMS, 1):
        if stem in q:
            out.add(_latest(i, months, reference))
    return {m for m in out if m}


def _latest(number: int, months: tuple, reference: str) -> str:
    """The newest data month with this month number; the reference year when the data has none (the tool then says so)."""
    same = [m for m in months if int(m[5:7]) == number]
    if same:
        return same[-1]
    return f"{reference[:4]}-{number:02d}" if reference else ""


def _ok(call: dict) -> bool:
    return "result" in call and not (isinstance(call["result"], dict) and "error" in call["result"])


def doubt(question: str, calls: list, months: tuple = (), reference: str = "", valid=None) -> str | None:
    """Why the answer may not be the one asked for, or None. Only successful lookups are judged."""
    done = [c for c in calls if c["name"] in LABELLED | {"spending_by_category"} and _ok(c)]
    if not done:
        return None
    if categories.mismatch(question, calls, valid):
        return "category"
    named = named_months(question, months, reference)
    if len(named) == 1:
        looked = {a.get(k) for c in done for a in [c.get("args") or {}] for k in ("month", "m1", "m2") if a.get(k)}
        if looked and named.isdisjoint(looked):
            return "month"
    if (LIST_CUE.search((question or "").lower()) and not categories.implied_categories(question)
            and not categories.asks_budget(question) and not any(c["name"] == "spending_by_category" for c in done)):
        return "list"
    return None


def line(calls: list, lang: str) -> str:
    """One line saying what was looked up, from the tool calls only. Empty when nothing was looked up."""
    lang = lang if lang in PREFIX else "en"
    parts: list[str] = []
    for c in calls:
        if c["name"] not in LABELLED or not _ok(c):
            continue
        a = c.get("args") or {}
        month = _month_text(a["month"], lang) if a.get("month") else ""
        sep = " " if lang == "th" else ", "
        if c["name"] == "sum_by_category":
            text = f"{_cat(a.get('category', ''), lang)}{sep}{month}"
        elif c["name"] == "sum_categories":
            text = f"{' + '.join(_cat(x, lang) for x in a.get('categories') or [])}{sep}{month}"
        elif c["name"] == "compare_months":
            text = f"{_cat(a.get('category', ''), lang)}, {_month_text(a['m1'], lang)} / {_month_text(a['m2'], lang)}"
        elif c["name"] == "over_budget":
            text = ("หมวดที่เกินงบ " if lang == "th" else "Categories over budget, ") + month
        elif c["name"] == "month_summary":
            text = ("สรุป" if lang == "th" else "Summary, ") + month
        else:
            text = f"{_cat(a.get('category', ''), lang)} " + ("งบ" if lang == "th" else "budget")
        if text not in parts:
            parts.append(text)
    return PREFIX[lang] + "; ".join(parts[:3]) if parts else ""


NEXT = re.compile(r"next month|coming month|upcoming month|เดือนหน้า|เดือนถัดไป|เดือนต่อไป", re.I)
SPEND_WORDS = re.compile(r"spend|spent|cost|over|ใช้|จ่าย|เกิน|หมด", re.I)
FUTURE = {
    "en": "I can only show spending that has already happened, so I can't tell you about {month} yet. "
          "Your data runs from {first} to {last}.",
    "th": "ดูได้เฉพาะรายจ่ายที่เกิดขึ้นแล้ว จึงยังบอกยอดของ{month} ไม่ได้ ข้อมูลของคุณมีตั้งแต่{first} ถึง{last}",
}
THIS_MONTH_BUTTON = {"en": {"label": "This month so far", "question": "What did I spend on this month?"},
                     "th": {"label": "เดือนนี้ที่ผ่านมา", "question": "เดือนนี้ใช้เงินไปกับอะไรบ้าง"}}


def future(question: str, months: tuple, reference: str, lang: str) -> dict | None:
    """{"answer", "options"} for a spending question about next month, which no data can answer; else None.

    The 4B model used to hand these to the large model with thinking on (about 20 s) only to say the same thing.
    A question about the budget limit itself ("my budget next month") is not caught: limits are monthly and known.
    """
    q = question or ""
    if not (reference and months and NEXT.search(q)):
        return None
    if categories.asks_budget(q) and not SPEND_WORDS.search(q):
        return None
    year, month = int(reference[:4]), int(reference[5:7])
    nxt = f"{year + (month == 12)}-{month % 12 + 1:02d}"
    lang = lang if lang in FUTURE else "en"
    text = FUTURE[lang].format(month=_month_text(nxt, lang), first=_month_text(months[0], lang),
                               last=_month_text(months[-1], lang))
    return {"answer": text, "options": [dict(THIS_MONTH_BUTTON[lang])]}


ASK = {"en": "I'm not sure I understood. Which one do you mean?", "th": "ไม่แน่ใจว่าเข้าใจถูกไหม หมายถึงข้อไหน"}


def reading(question: str, months: tuple, reference: str, lang: str) -> dict:
    """Buttons made from what the code can read in the question: its category and month, else this month."""
    named = sorted(named_months(question, months, reference))
    month = named[0] if len(named) == 1 else reference
    mtext = (_month_text(month, lang) if month else ("เดือนนี้" if lang == "th" else "this month"))
    options = []
    for cat in categories.implied_categories(question)[:2]:
        name = _cat(cat, lang)
        options.append({"label": f"{name}, {mtext}",
                        "question": f"ค่า{name}{mtext}เท่าไหร่" if lang == "th" else f"How much did I spend on {name} in {mtext}?"})
    options.append({"label": "ทุกหมวด" if lang == "th" else "All categories",
                    "question": f"{mtext}ใช้เงินไปกับอะไรบ้าง" if lang == "th" else f"What did I spend on in {mtext}?"})
    options.append({"label": "เช็กงบ" if lang == "th" else "Over budget?",
                    "question": f"{mtext}ใช้เกินงบหมวดไหนบ้าง" if lang == "th" else f"Which categories am I over budget on in {mtext}?"})
    return {"ask": ASK[lang], "options": options[:3]}
