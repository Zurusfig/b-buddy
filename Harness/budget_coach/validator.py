"""Strict number validator: every number in a reply must come from a tool result.

    bad = unsupported_numbers(answer, calls, question)   # [] means the reply passes

Allowed numbers: anything in a tool result (amounts, limits, counts, guideline text), the
student's income, numbers the user typed in the question, and the years of the data months.
Rounding to the nearest baht is accepted. Dates (2026-07), list markers (1.) and guideline
ids ([G03]) are not treated as numbers. Derived arithmetic is NOT accepted: if a reply needs
a figure, a tool has to return it.
"""
from __future__ import annotations

import json
import re

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
DATE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
LIST_MARKER = re.compile(r"(?m)^\s*(?:[-*•]\s*)?\d{1,2}[.)]\s")
GUIDELINE_ID = re.compile(r"\[?\bG\d{2}\b\]?")


def numbers_in(text: str) -> set[float]:
    """Absolute values of the numbers written in `text` (Thai digits and thousands commas handled)."""
    text = text.translate(THAI_DIGITS)
    for pattern in (DATE, LIST_MARKER, GUIDELINE_ID):
        text = pattern.sub(" ", text)
    found = set()
    for raw in NUMBER.findall(text):
        try:
            found.add(abs(float(raw.replace(",", ""))))
        except ValueError:
            pass
    return found


def _walk(value, out: set[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(abs(float(value)))
    elif isinstance(value, str):
        out |= numbers_in(value)
    elif isinstance(value, dict):
        for v in value.values():
            _walk(v, out)
    elif isinstance(value, (list, tuple)):
        out.add(float(len(value)))  # "3 categories" is a count the tool already shows
        for v in value:
            _walk(v, out)


def allowed_numbers(calls: list[dict], question: str = "", extra: tuple = ()) -> set[float]:
    ok: set[float] = set(float(x) for x in extra) | numbers_in(question)
    for c in calls:
        _walk(c.get("result"), ok)
    return ok


def _close(n: float, a: float) -> bool:
    return abs(n - a) <= (0.51 if max(n, a) >= 100 else 0.051)


def unsupported_numbers(answer: str, calls: list[dict], question: str = "",
                        extra: tuple = ()) -> list[float]:
    """Numbers in `answer` that no tool result, the question or `extra` supports (sorted)."""
    ok = allowed_numbers(calls, question, extra)
    return sorted(n for n in numbers_in(answer) if not any(_close(n, a) for a in ok))


# Investment language (design doc, validator check 3). A reply to an in-scope question must not drift into
# products to buy or invest in. Thai has no word boundaries, so Thai terms are matched as plain substrings.
INVESTMENT = re.compile(
    r"\b(?:stocks?|shares? (?:of|in)|equit(?:y|ies)|crypto(?:currenc(?:y|ies))?|bitcoin|btc|ethereum|"
    r"mutual funds?|index funds?|money[- ]market funds?|etfs?|bonds?|gold|invest(?:s|ed|ing|ment|ments|or)?|"
    r"portfolio|dividends?|forex|savings insurance|lotter(?:y|ies)|rmf|ssf|thaiesg)\b"
    r"|หุ้น|คริปโต|บิตคอยน์|บิทคอยน์|กองทุน|ทองคำ|ลงทุน|พันธบัตร|หุ้นกู้|ปันผล|ประกันออมทรัพย์|ประกันชีวิตแบบออม|"
    r"ลอตเตอรี่|ล็อตเตอรี่|หวย|สลากกินแบ่ง",
    re.I)
# Saving phrases that contain an investment word but are budgeting, not investing.
INVESTMENT_OK = re.compile(r"\b(?:emergency|rainy[- ]day|sinking)\s+funds?\b", re.I)


def _strings(value, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            out.append(str(k))
            _strings(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _strings(v, out)


def investment_terms(answer: str, calls: list[dict] = ()) -> list[str]:
    """Investment words in `answer` (lower-cased, sorted). [] means the reply passes.

    A word that also appears in a tool result is the user's own data (a category or a purchase named
    "insurance" or "gold"), not advice, so it is allowed. Budgeting phrases such as "emergency fund" are allowed.
    """
    text = INVESTMENT_OK.sub(" ", answer or "")
    data: list[str] = []
    for c in calls:
        _strings(c.get("result"), data)
    blob = INVESTMENT_OK.sub(" ", " ".join(data)).lower()
    return sorted({m.group(0).lower() for m in INVESTMENT.finditer(text) if m.group(0).lower() not in blob})


FALLBACK_HEADER = {
    "en": "I could not verify a written answer, so here are the raw results.",
    "th": "ตรวจสอบคำตอบไม่ผ่าน จึงแสดงผลดิบจากเครื่องมือแทนค่ะ",
}
FALLBACK_EMPTY = {"en": "- (no data was retrieved)", "th": "- (ไม่ได้ดึงข้อมูลมา)"}


def fallback_answer(calls: list[dict], lang: str = "en") -> str:
    """Raw totals from the tool results, used when the model cannot give a verified answer, in the question's language."""
    lines = [FALLBACK_HEADER.get(lang, FALLBACK_HEADER["en"])]
    shown = 0
    for c in calls:
        res = c.get("result")
        if res is None or c["name"] in ("decline", "think_harder"):
            continue
        if isinstance(res, dict) and "error" in res:
            continue
        lines.append(f"- {c['name']}({json.dumps(c['args'], ensure_ascii=False)}): "
                     f"{json.dumps(res, ensure_ascii=False)}")
        shown += 1
    if not shown:
        lines.append(FALLBACK_EMPTY.get(lang, FALLBACK_EMPTY["en"]))
    return "\n".join(lines)