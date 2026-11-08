"""Known gaps in the student's data (UAT-07 no data for April, UAT-08 no budgets set, a category that cannot be looked up).

    raise DataGap("no_data", "no data for month '2026-04'", month="2026-04", available=["2026-05", "2026-10"])
    resolve([{"error": "...", "gap": {"kind": "no_data", ...}}], "en")["answer"]
        -> "I have no data for April 2026. Your data runs from May 2026 to October 2026."

A tool that says "no data" or "no budget" is a correct answer, not a failure. Tools raise DataGap, which carries its
kind and facts as fields, so nothing here reads error text: rewording a message cannot break the reply. Code writes
the reply in the question's language, so no model is asked and nothing is escalated to the large model (the UAT
spent 37 to 51 s on exactly these cases, mostly on that escalation).
"""
from __future__ import annotations

KINDS = ("no_data", "no_budget", "unknown_category")


class DataGap(ValueError):
    """The data has nothing to report. Still a ValueError, so code that catches ValueError keeps working."""

    def __init__(self, kind: str, message: str, **facts):
        assert kind in KINDS, kind
        super().__init__(message)
        self.kind, self.facts = kind, facts

    def info(self) -> dict:
        return {"kind": self.kind, **self.facts}


MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
    "th": ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน",
           "ตุลาคม", "พฤศจิกายน", "ธันวาคม"],
}
TEXT = {
    "no_data": {"en": "I have no data for {month}. Your data runs from {first} to {last}.",
                "th": "ไม่มีข้อมูลของ{month} ข้อมูลของคุณมีตั้งแต่{first} ถึง{last}"},
    "no_budget": {"en": "You haven't set a budget for this yet, so there is no limit to compare with. "
                        "Set a limit in the app, then ask again.",
                  "th": "คุณยังไม่ได้ตั้งงบประมาณในส่วนนี้ จึงยังไม่มีวงเงินให้เทียบ ตั้งวงเงินในแอปแล้วถามใหม่ได้เลย"},
    "unknown_category": {"en": "I can't look up “{category}” by name yet. I can show everything you spent, category by category.",
                         "th": "ยังดูยอดของหมวด “{category}” แยกเดี่ยวไม่ได้ แต่แสดงรายจ่ายทุกหมวดให้ได้"},
}
BREAKDOWN_BUTTON = {"en": {"label": "Show all categories", "question": "What did I spend on this month?"},
                    "th": {"label": "ดูทุกหมวด", "question": "เดือนนี้ใช้เงินไปกับอะไรบ้าง"}}


def _label(ym: str, lang: str) -> str:
    year, month = ym.split("-")
    names = MONTHS.get(lang, MONTHS["en"])
    name = names[int(month) - 1]
    return f"{'เดือน' if lang == 'th' else ''}{name} {year}"


def _plain(text) -> str:
    """A name from the model's tool arguments, made safe to show: one short line."""
    return " ".join(str(text).split())[:40]


def kind_of(result) -> str | None:
    gap = result.get("gap") if isinstance(result, dict) else None
    return gap.get("kind") if isinstance(gap, dict) and gap.get("kind") in KINDS else None


def is_gap(result) -> bool:
    return kind_of(result) is not None


def resolve(results: list, lang: str) -> dict | None:
    """{"answer", "options"} when every tool result of a round is a known gap, else None (let the model answer)."""
    if not results or not all(is_gap(r) for r in results):
        return None
    lang = lang if lang in TEXT["no_data"] else "en"
    gaps = [r["gap"] for r in results]
    for kind in KINDS:  # the first kind in this order decides the reply
        found = next((g for g in gaps if g["kind"] == kind), None)
        if not found:
            continue
        if kind == "no_data":
            months = found.get("available") or []
            if not found.get("month") or not months:
                return None
            text = TEXT[kind][lang].format(month=_label(found["month"], lang), first=_label(months[0], lang),
                                           last=_label(months[-1], lang))
            return {"answer": text, "options": []}
        if kind == "unknown_category":
            text = TEXT[kind][lang].format(category=_plain(found.get("category", "")))
            return {"answer": text, "options": [dict(BREAKDOWN_BUTTON[lang])]}
        return {"answer": TEXT[kind][lang], "options": []}
    return None


def reply(results: list, lang: str) -> str | None:
    """Just the text of resolve()."""
    found = resolve(results, lang)
    return found["answer"] if found else None
