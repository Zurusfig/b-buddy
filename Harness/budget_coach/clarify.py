"""Ask back instead of guessing (P5, UAT T11). Code decides; the question and its buttons are fixed text.

    needs("Grab เดือนนี้เท่าไหร่")  -> {"reason": "ambiguous:grab", "options": [...]}   a ride or food?
    needs("ช่วยหน่อย")               -> {"reason": "vague", "options": [...]}            nothing to look up
    needs("ค่าวิน")                  -> None                                            the glossary knows it

Each option is a button with a label and a complete question. Tapping one sends that question, so the server
keeps no conversation state and never has to parse "yes" or "ใช่". The text is a per-language table (like the
refusals in P1), so no model runs and nothing can be mistranslated.

Only three things trigger it, all cheap to explain:
  - an ambiguous word listed in data/glossary.json (_ambiguous), such as Grab, unless the question already says which
  - a short question with nothing to look up: no category word, no time word and no money word
  - a judgment with no yardstick ("Did July hurt?", "Did I spend too much?"): a total or a budget check? (UAT-11)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import advice
import categories
import gaps
import language

GLOSSARY = json.loads(categories.GLOSSARY_PATH.read_text("utf-8"))
AMBIGUOUS = [{**a, "_match": re.compile(a["match"]), "_resolved": re.compile(a["resolved"])}
             for a in GLOSSARY.get("_ambiguous", [])]

# Anything that gives the coach something to look up. A short question without any of these is vague.
SIGNALS = re.compile(
    r"ค่า|เงิน|จ่าย|ใช้|งบ|รายได้|เหลือ|ออม|เกิน|รวม|สรุป|เทียบ|แนะนำ|ลด|เดือน|สัปดาห์|วันนี้|ปีนี้|เท่าไหร่|เท่าไร|"
    r"หุ้น|คริปโต|ลงทุน|กองทุน|ทอง|หวย|อากาศ|"            # investment and off-topic words: the router refuses these
    r"spen[dt]|budget|income|money|save|saving|cost|pay|bill|left|total|over|compare|summary|advice|tip|reduce|cut|"
    r"month|week|today|year|invest|stock|crypto|bitcoin|fund|gold|weather|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d", re.I)
MAX_VAGUE_CHARS = 30

# A judgment ("did it hurt", "too much", "is it okay") has no yardstick until the student says which one: the
# total spent, or the limits they set. Naming a budget, a limit or a category is a yardstick, so that goes straight through.
JUDGMENT = re.compile(r"hurt|too much|\bok(?:ay)?\b|\bfine\b|\bbad\b|เยอะไป|เยอะเกิน|เยอะไหม|เยอะมั้ย|โอเคไหม|โอเคมั้ย|เจ็บ", re.I)
YARDSTICK = re.compile(r"budget|limit|overspen|\bover\b|งบ|เกิน|วงเงิน|หมวด|categor", re.I)
# Asking for an amount, a list or a comparison is a clear question, whatever the wording around it.
AMOUNT = re.compile(r"how (?:much|many)|\bamount\b|\btotal\b|what (?:did|do|have) i spen[dt]|where (?:did|does) my money|break ?down|"
                    r"summary|compare|list|เท่าไหร่|เท่าไร|กี่บาท|อะไรบ้าง|ไรบ้าง|หายไปไหน|ไปไหนหมด|ไปกับอะไร|ยอด|สรุป|แยก|เทียบ|รวม", re.I)
MONTH_WORDS = [("january", 1), ("february", 2), ("march", 3), ("april", 4), ("may", 5), ("june", 6), ("july", 7),
               ("august", 8), ("september", 9), ("october", 10), ("november", 11), ("december", 12)]

ASK = {"vague": {"en": "What would you like to know? Pick one, or type your own question.",
                 "th": "อยากให้ช่วยเรื่องไหน เลือกข้อด้านล่าง หรือพิมพ์คำถามของคุณเองได้เลย"}}
VAGUE_OPTIONS = [
    {"label": {"en": "This month's summary", "th": "สรุปเดือนนี้"},
     "question": {"en": "Give me a summary of this month", "th": "สรุปเดือนนี้ให้หน่อย"}},
    {"label": {"en": "Am I over budget?", "th": "เช็กงบ"},
     "question": {"en": "Which categories am I over budget on this month?", "th": "เดือนนี้ใช้เกินงบหมวดไหนบ้าง"}},
    {"label": {"en": "A tip to save", "th": "ขอคำแนะนำ"},
     "question": {"en": "Give me a tip to save money", "th": "ช่วยแนะนำวิธีประหยัดเงินหน่อย"}},
]


def _month_in(q: str, lang: str) -> str:
    """The month the student named, written for the question's language; "this month" when none."""
    low = q.lower()
    for name, n in MONTH_WORDS:
        short = "sept?" if name == "september" else name[:3]
        if re.search(rf"\b(?:{name}|{short})\b", low) or gaps.MONTHS["th"][n - 1] in q:
            return ("เดือน" + gaps.MONTHS["th"][n - 1]) if lang == "th" else name.capitalize()
    return "เดือนนี้" if lang == "th" else "this month"


JUDGMENT_ASK = {"en": "Do you want the total you spent in {m}, or which categories went over their limit?",
                "th": "อยากดูยอดใช้จ่ายรวมของ{m} หรืออยากรู้ว่าหมวดไหนใช้เกินงบ"}
JUDGMENT_OPTIONS = [
    {"label": {"en": "Total spent", "th": "ยอดใช้จ่ายรวม"},
     "question": {"en": "Give me a summary of {m}", "th": "สรุป{m}ให้หน่อย"}},
    {"label": {"en": "Over budget?", "th": "เช็กงบ"},
     "question": {"en": "Which categories am I over budget on in {m}?", "th": "{m}ใช้เกินงบหมวดไหนบ้าง"}},
]


def _options(raw: list[dict], lang: str) -> list[dict]:
    return [{"label": o["label"][lang], "question": o["question"][lang]} for o in raw]


def needs(question: str) -> dict | None:
    """None when the question can be answered as written, else the reason and the buttons (in its language)."""
    q = (question or "").strip()
    lang = language.question_lang(q)
    low = q.lower()
    for a in AMBIGUOUS:
        if a["_match"].search(low) and not a["_resolved"].search(low):
            return {"reason": f"ambiguous:{a['id']}", "ask": a["ask"][lang], "options": _options(a["options"], lang)}
    if len(q) <= MAX_VAGUE_CHARS and not SIGNALS.search(low) and not categories.implied_categories(q):
        return {"reason": "vague", "ask": ASK["vague"][lang], "options": _options(VAGUE_OPTIONS, lang)}
    if JUDGMENT.search(low):
        return judgment(q)
    return None


def unsure(question: str) -> dict | None:
    """For a spending question the router labelled trend or budget_check: buttons when it asks for no amount and
    names no yardstick ("Was August a disaster?"), else None. The router often calls a judgment "trend", so this
    looks at what the question is missing, not at how the model labelled it."""
    return None if AMOUNT.search(question or "") else judgment(question)


def judgment(question: str) -> dict | None:
    """Buttons for a judgment with no yardstick, or None when the question names one (a budget, a limit, a category,
    a tip topic). Used by the word list above and by the router's budget_check label, so both share the guards."""
    q = (question or "").strip()
    low = q.lower()
    lang = language.question_lang(q)
    if YARDSTICK.search(low) or categories.implied_categories(q) or advice.pick_match(q)[1]:
        return None  # a tip topic ("is it okay to pay only the minimum?") is advice, not a judgment
    m = _month_in(q, lang)
    return {"reason": "judgment", "ask": JUDGMENT_ASK[lang].format(m=m),
            "options": [{"label": o["label"][lang], "question": o["question"][lang].format(m=m)}
                        for o in JUDGMENT_OPTIONS]}
