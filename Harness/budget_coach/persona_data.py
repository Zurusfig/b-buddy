"""Budget tools over the 10 synthetic personas in persona/csv. Pure functions, no LLM.

    pd = PersonaData(1)
    pd.sum_by_category("2026-09", "food")

Same counting rules as persona/personas.md (the ground truth follows them):
  - spending = `expense` rows; a refund is an `income` row in an expense category and is
    subtracted from that category
  - income   = `income` rows in income categories (allowance, salary, part_time, freelance, gift)
  - `transfer` rows (ATM, e-wallet top-ups, card payments, goal deposits and withdrawals) are never
    spending or income
  - soft-deleted rows (`deletedAt` set) are ignored everywhere
Every query is scoped to one userId fixed when the object is built, so a model can never ask for
another user's rows: user_id is not an argument of any tool.

The original single-student tools stay in tools.py; this module does not touch them.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

PERSONA_DIR = Path(__file__).resolve().parents[2] / "persona" / "csv"
MAX_ROWS = 500
EXPENSE_CATEGORIES = ("food", "transport", "shopping", "entertainment", "bills", "education",
                      "health", "other")


@lru_cache(maxsize=None)
def _table(name: str, root: str) -> tuple[dict, ...]:
    with open(Path(root) / f"{name}.csv", encoding="utf-8", newline="") as f:
        return tuple(csv.DictReader(f))


def available(root: Path = PERSONA_DIR) -> bool:
    return (Path(root) / "Transaction.csv").exists()


def list_users(root: Path = PERSONA_DIR) -> list[dict]:
    """[{user_id, key, email}] for every persona. The key is read from the account email."""
    out = []
    for u in _table("User", str(root)):
        email = u["email"]
        key = email.split("@")[0].split(".", 1)[-1]  # persona01.mint@... -> mint
        out.append({"user_id": int(u["id"]), "key": key, "email": email})
    return out


def resolve_user(who: str | int, root: Path = PERSONA_DIR) -> int:
    """Accept a numeric id ("3") or a key ("bank") and return the user id."""
    users = list_users(root)
    for u in users:
        if str(who) == str(u["user_id"]) or str(who).lower() == u["key"]:
            return u["user_id"]
    raise ValueError(f"unknown persona {who!r}; choose from "
                     + ", ".join(f"{u['user_id']}={u['key']}" for u in users))


class PersonaData:
    def __init__(self, user_id: int, root: Path = PERSONA_DIR):
        self.user_id = int(user_id)
        root = str(root)
        cats = {c["id"]: c for c in _table("Category", root) if int(c["userId"]) == self.user_id}
        if not cats:
            raise ValueError(f"no persona with user id {user_id}")
        self.categories = {c["id"]: c["name"] for c in cats.values()}
        self.category_type = {c["name"]: c["type"] for c in cats.values()}
        self.budgets = {c["name"]: float(c["budget"]) for c in cats.values()
                        if c["type"] == "expense" and c["budget"] not in ("", None)}
        self.rows = []
        for t in _table("Transaction", root):
            if int(t["userId"]) != self.user_id or t["deletedAt"]:
                continue
            self.rows.append({"date": t["date"], "amount": float(t["amount"]), "type": t["type"],
                              "description": t["description"],
                              "category": self.categories.get(t["categoryId"])})
        self.expense_categories = tuple(c for c in EXPENSE_CATEGORIES
                                        if self.category_type.get(c) == "expense")

    # ------------------------------------------------------------------ helpers
    def months(self) -> list[str]:
        return sorted({r["date"][:7] for r in self.rows})

    def reference_month(self) -> str:
        """The latest month with data; "this month" for the agent."""
        return self.months()[-1]

    def _check(self, month: str | None = None, category: str | None = None) -> None:
        if category is not None and category not in self.expense_categories:
            raise ValueError(f"unknown category {category!r}; expected one of {self.expense_categories}")
        if month is not None and month not in self.months():
            raise ValueError(f"no data for month {month!r}; available: {self.months()}")

    def _month_rows(self, month: str):
        return [r for r in self.rows if r["date"].startswith(month)]

    # -------------------------------------------------------------------- tools
    def sum_by_category(self, month: str, category: str) -> float:
        """Net spend in one category for one month: expenses minus refunds."""
        self._check(month, category)
        total = 0.0
        for r in self._month_rows(month):
            if r["category"] != category:
                continue
            if r["type"] == "expense":
                total += r["amount"]
            elif r["type"] == "income":  # refund into an expense category
                total -= r["amount"]
        return round(total, 2)

    def compare_months(self, m1: str, m2: str, category: str) -> dict:
        """Spend in `category` for m1 vs m2. diff = m2 - m1; pct_change relative to m1."""
        a, b = self.sum_by_category(m1, category), self.sum_by_category(m2, category)
        return {"category": category, "m1": m1, "m2": m2, "m1_total": a, "m2_total": b,
                "diff": round(b - a, 2), "pct_change": round((b - a) / a * 100, 1) if a else None}

    def get_budget(self, category: str) -> float:
        """Monthly limit for one category; an error if this user never set one."""
        self._check(category=category)
        if category not in self.budgets:
            raise ValueError(f"no budget is set for {category!r}")
        return self.budgets[category]

    def over_budget(self, month: str) -> list[dict]:
        """Categories whose spend exceeded their limit in `month` (empty list if none)."""
        self._check(month)
        if not self.budgets:
            raise ValueError("this user has not set any budgets")
        out = []
        for cat, limit in self.budgets.items():
            spent = self.sum_by_category(month, cat)
            if spent > limit:
                out.append({"category": cat, "spent": spent, "limit": limit,
                            "over_by": round(spent - limit, 2)})
        return out

    def month_summary(self, month: str) -> dict:
        """Income, spending (refunds netted), net cash flow and refunds for one month."""
        self._check(month)
        income = spending = refunds = 0.0
        for r in self._month_rows(month):
            cat_type = self.category_type.get(r["category"])
            if r["type"] == "expense":
                spending += r["amount"]
            elif r["type"] == "income" and cat_type == "expense":
                spending -= r["amount"]
                refunds += r["amount"]
            elif r["type"] == "income":
                income += r["amount"]
        return {"month": month, "income_total": round(income, 2), "spending_total": round(spending, 2),
                "net_cashflow": round(income - spending, 2), "refunds_total": round(refunds, 2)}

    def get_transactions(self, month: str, category: str | None = None) -> list[dict]:
        """Individual purchases in one month (at most MAX_ROWS), optionally one category."""
        self._check(month, category)
        rows = [{"date": r["date"][:10], "amount": r["amount"], "category": r["category"],
                 "description": r["description"]}
                for r in self._month_rows(month)
                if r["type"] == "expense" and (category is None or r["category"] == category)]
        return rows[:MAX_ROWS]
