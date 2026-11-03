"""Does the tool call match what the question named? A code check for P3 (wrong tool) and P4 (combined totals).

    implied_categories("ค่าวิน")                         -> ["transport"]
    mismatch("ค่าวิน", [month_summary call])             -> True   (asked about transport, looked at the whole month)
    mismatch("ค่าวิน", [get_budget transport call])      -> True   (asked what was spent, got the limit)
    mismatch("food plus transport", [sum_categories])    -> False

The 4B model sometimes answers a short phrase with the wrong tool and nothing notices, because the numbers it
quotes are real. This check compares the question's own words with the tool arguments, so a mismatch raises
the `arg_mismatch` flag and the question reruns on the large model.

Words are listed only where they point to one category. Ambiguous ones (Grab can be a ride or food) are left out,
so the check stays quiet rather than wrong. `valid` is the data's own category list: a student whose data has no
"subscriptions" category files Netflix under "entertainment", so the check follows the data.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "data" / "glossary.json"


def _compile(path: Path = GLOSSARY_PATH) -> dict[str, re.Pattern]:
    """One pattern per category from data/glossary.json (edit that file to teach the check a new word)."""
    out = {}
    for cat, groups in json.loads(path.read_text("utf-8")).items():
        if cat.startswith("_"):
            continue
        parts = [re.escape(t.lower()) for t in groups.get("th", [])]
        parts += [r"(?<![a-z0-9])" + re.escape(t.lower()) for t in groups.get("en", [])]
        parts += [r"(?<![a-z0-9])" + re.escape(t.lower()) + r"(?![a-z0-9])" for t in groups.get("en_exact", [])]
        out[cat] = re.compile("|".join(parts))
    return out


KEYWORDS = _compile()
ALIAS = {"subscriptions": "entertainment"}  # where such spending lives when the data has no subscriptions category
COMBINE = r"รวม|ทั้งหมด|ทั้งสอง|\btotal\b|combined|together|altogether|\bsum\b|\bplus\b|บวก|\bboth\b"
BUDGET_WORDS = r"งบ|วงเงิน|เพดาน|\bbudget|\blimit|\bover\b|เกิน"
SPEND_TOOLS = {"sum_by_category", "compare_months", "get_transactions", "sum_categories"}
BUDGET_TOOLS = {"get_budget", "over_budget"}
NUMBER_TOOLS = SPEND_TOOLS | BUDGET_TOOLS | {"month_summary"}


def implied_categories(question: str, valid=None) -> list[str]:
    q = (question or "").lower()
    out: list[str] = []
    for cat, pattern in KEYWORDS.items():
        if not pattern.search(q):
            continue
        target = cat if valid is None or cat in valid else ALIAS.get(cat)
        if target and (valid is None or target in valid) and target not in out:
            out.append(target)
    return out


def asks_combined(question: str) -> bool:
    return bool(re.search(COMBINE, (question or "").lower()))


def asks_budget(question: str) -> bool:
    return bool(re.search(BUDGET_WORDS, (question or "").lower()))


def covered(calls: list[dict], tools: set[str]) -> set[str]:
    """Categories the given tools were asked about (an over_budget result also names the categories it reports)."""
    seen: set[str] = set()
    for c in calls:
        if c["name"] not in tools:
            continue
        a, res = c.get("args") or {}, c.get("result")
        if a.get("category"):
            seen.add(a["category"])
        seen.update(a.get("categories") or [])
        if c["name"] == "over_budget" and isinstance(res, list):
            seen.update(r.get("category") for r in res if isinstance(r, dict))
    return seen


def mismatch(question: str, calls: list[dict], valid=None) -> bool:
    """True when the question names categories that the tool calls did not cover.

    A question that is not about limits ("ค่าวิน") must be answered from a spending tool; reading the budget limit
    instead would present a limit as money spent.
    """
    want = implied_categories(question, valid)
    if not want:
        return False
    if not any(c["name"] in NUMBER_TOOLS and "result" in c and not (
            isinstance(c["result"], dict) and "error" in c["result"]) for c in calls):
        # no number tool succeeded. A failed call is already flagged tool_error and no call at all is flagged
        # no_tool; what is left is an answer built from a tip (lookup_guideline) or nothing but words.
        return any(c["name"] == "lookup_guideline" for c in calls)
    seen = covered(calls, SPEND_TOOLS | BUDGET_TOOLS) if asks_budget(question) else covered(calls, SPEND_TOOLS)
    if len(want) == 1:
        return want[0] not in seen
    if asks_combined(question):  # "food plus transport": one sum_categories call has to cover all of them
        return not any(c["name"] == "sum_categories" and set(want) <= set((c.get("args") or {}).get("categories") or [])
                       for c in calls)
    return False
