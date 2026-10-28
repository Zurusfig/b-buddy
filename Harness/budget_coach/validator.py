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


def fallback_answer(calls: list[dict]) -> str:
    """Raw totals from the tool results, used when the model cannot give a verified answer."""
    lines = ["I could not verify a written answer, so here are the raw results. / "
             "ตรวจสอบคำตอบไม่ผ่าน จึงแสดงผลดิบจากเครื่องมือแทนค่ะ"]
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
        lines.append("- (no data was retrieved)")
    return "\n".join(lines)
