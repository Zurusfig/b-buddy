"""Budget tools over one user's rows in the app's database (Postgres), read-only.

    data = DbData(user_id=7)                 # reads COACH_DATABASE_URL
    data.sum_by_category("2026-09", "food")

Same tools and counting rules as persona_data.PersonaData (it is the parent class), so the numbers
the coach states follow the rules the evaluations were scored with:
  - spending = `expense` rows; a refund is an `income` row in an expense category and is subtracted
  - income   = `income` rows in income categories
  - any other row type (e.g. `transfer`) is never spending or income
  - soft-deleted rows and investment cash legs are removed by the view, not here

Access is limited by the database, not by this code: the coach connects as `coach_reader`, which can
only SELECT from two views (v_transactions, v_categories; see coach_reader.sql). The user is fixed when
the object is built, and no tool takes a user id.

"this month" is fixed to 2026-10 for the app's UAT data, even if the environment omits the setting.
"""
from __future__ import annotations

import os
from typing import Callable

from persona_data import EXPENSE_CATEGORIES, PersonaData

TRANSACTIONS_SQL = (
    "SELECT to_char(local_date, 'YYYY-MM-DD HH24:MI:SS') AS date, amount, type, description, "
    "category, category_type FROM v_transactions WHERE \"userId\" = %s ORDER BY local_date, id")
CATEGORIES_SQL = 'SELECT category, category_type, monthly_limit FROM v_categories WHERE "userId" = %s'
STATEMENT_TIMEOUT_MS = 5000
CONNECT_TIMEOUT_S = 5
UAT_REFERENCE_MONTH = "2026-10"

Fetch = Callable[[str, tuple], list[dict]]


def connect_fetch(dsn: str) -> Fetch:
    """A fetch(sql, params) -> list[dict] that opens a read-only connection for each call."""
    if not dsn:
        raise RuntimeError("COACH_DATABASE_URL is not set")
    import psycopg
    from psycopg.rows import dict_row

    def fetch(sql: str, params: tuple) -> list[dict]:
        # prepare_threshold=None: safe behind a transaction-mode pooler. The pooler also ignores startup
        # options, so read-only and the timeout are set on the connection and on the transaction.
        with psycopg.connect(dsn, connect_timeout=CONNECT_TIMEOUT_S, row_factory=dict_row,
                             prepare_threshold=None) as conn:
            conn.read_only = True
            conn.execute(f"SET LOCAL statement_timeout = {int(STATEMENT_TIMEOUT_MS)}")
            return list(conn.execute(sql, params).fetchall())

    return fetch


class DbData(PersonaData):
    def __init__(self, user_id: int, fetch: Fetch | None = None, reference_month: str | None = None):
        fetch = fetch or connect_fetch(os.environ.get("COACH_DATABASE_URL", ""))
        self.user_id = int(user_id)
        self.category_type: dict[str, str] = {}
        self.rows = []
        for r in fetch(TRANSACTIONS_SQL, (self.user_id,)):
            cat = r["category"]
            if cat is not None and r["category_type"]:
                self.category_type[cat] = r["category_type"]
            self.rows.append({"date": r["date"], "amount": float(r["amount"]), "type": r["type"],
                              "description": r["description"], "category": cat})
        self.budgets: dict[str, float] = {}
        categories = fetch(CATEGORIES_SQL, (self.user_id,))
        for r in categories:
            self.category_type[r["category"]] = r["category_type"]
            if r["category_type"] == "expense" and r["monthly_limit"] is not None:
                self.budgets[r["category"]] = float(r["monthly_limit"])
        if not categories:
            raise ValueError(f"no data for user {user_id}")
        names = [c for c, t in self.category_type.items() if t == "expense"]
        known = [c for c in EXPENSE_CATEGORIES if c in names]
        self.expense_categories = tuple(known + sorted(n for n in names if n not in known))
        self._reference = reference_month or UAT_REFERENCE_MONTH

    def reference_month(self) -> str:
        return self._reference
