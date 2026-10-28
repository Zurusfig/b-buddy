"""Budget tools: pure functions over transactions.csv / budget.csv. No LLM.

Months are "YYYY-MM". Amounts are THB; refunds are negative and net into totals.
"""
from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATEGORIES = ("food", "transport", "shopping", "subscriptions", "education", "entertainment",
              "other")


def _transactions() -> list[dict]:
    with open(HERE / "transactions.csv", encoding="utf-8") as f:
        return [{**r, "amount": float(r["amount"])} for r in csv.DictReader(f)]


def _budgets() -> dict[str, float]:
    with open(HERE / "budget.csv", encoding="utf-8") as f:
        return {r["category"]: float(r["monthly_limit"]) for r in csv.DictReader(f)}


def _months() -> list[str]:
    return sorted({r["date"][:7] for r in _transactions()})


def _check(month: str | None = None, category: str | None = None) -> None:
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; expected one of {CATEGORIES}")
    if month is not None and month not in _months():
        raise ValueError(f"no data for month {month!r}; available: {_months()}")


MAX_ROWS = 500


def get_transactions(month: str, category: str | None = None) -> list[dict]:
    """Individual transactions for one month (at most MAX_ROWS), optionally one category."""
    _check(month, category)
    rows = [{"date": r["date"], "amount": r["amount"], "category": r["category"],
             "merchant": r["merchant"]}
            for r in _transactions()
            if r["date"].startswith(month) and (category is None or r["category"] == category)]
    return rows[:MAX_ROWS]


def sum_by_category(month: str, category: str) -> float:
    """Net spend in one category for one month."""
    _check(month, category)
    return round(sum(r["amount"] for r in _transactions()
                     if r["date"].startswith(month) and r["category"] == category), 2)


def compare_months(m1: str, m2: str, category: str) -> dict:
    """Spend in `category` for m1 vs m2. diff = m2 - m1; pct_change relative to m1."""
    a, b = sum_by_category(m1, category), sum_by_category(m2, category)
    return {"category": category, "m1": m1, "m2": m2, "m1_total": a, "m2_total": b,
            "diff": round(b - a, 2), "pct_change": round((b - a) / a * 100, 1) if a else None}


def get_budget(category: str) -> float:
    """Monthly limit for one category."""
    _check(category=category)
    return _budgets()[category]


def over_budget(month: str) -> list[dict]:
    """Categories whose spend exceeded their limit in `month` (empty list if none)."""
    _check(month)
    out = []
    for cat, limit in _budgets().items():
        spent = sum_by_category(month, cat)
        if spent > limit:
            out.append({"category": cat, "spent": spent, "limit": limit,
                        "over_by": round(spent - limit, 2)})
    return out
