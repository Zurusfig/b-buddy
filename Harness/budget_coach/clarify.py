"""Ask back instead of guessing (P5, UAT T11). Code decides; the question and its buttons are fixed text.

    needs("Grab เดือนนี้เท่าไหร่")  -> {"reason": "ambiguous:grab", "options": [...]}   a ride or food?
    needs("ช่วยหน่อย")               -> {"reason": "vague", "options": [...]}            nothing to look up
    needs("ค่าวิน")                  -> None                                            the glossary knows it

Each option is a button with a label and a complete question. Tapping one sends that question, so the server
keeps no conversation state and never has to parse "yes" or "ใช่". The text is a per-language table (like the
refusals in P1), so no model runs and nothing can be mistranslated.

Only two things trigger it, both cheap to explain:
  - an ambiguous word listed in data/glossary.json (_ambiguous), such as Grab, unless the question already says which
  - a short question with nothing to look up: no category word, no time word and no money word
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import categories
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
    return None
