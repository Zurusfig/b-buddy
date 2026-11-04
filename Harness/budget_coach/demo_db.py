"""Demo accounts for the finance app, built from persona/csv, and a clean way to remove them again.

    python dev.py demo-seed              # dry run: shows what would be inserted, writes nothing
    python dev.py demo-seed --yes        # inserts the 10 demo users and their data
    python dev.py demo-remove            # dry run: shows what would be deleted
    python dev.py demo-remove --yes      # deletes ONLY the demo users' rows and demo-credentials.txt
    python dev.py demo-reader-sql        # writes coach_reader.generated.sql (read-only coach role)
    python dev.py demo-reset-passwords   # preview password reset for Henry, Diana, Grace
    python dev.py demo-reset-passwords --yes  # rotate those three only; preserve all data
    python dev.py demo-shared-password --yes  # prompt privately for one password for all 10 personas

Every demo user has an email ending in @demo.budgetbuddy.test, and that is the only thing removal
looks at: no real account can match it, and no row is touched unless it belongs to such a user.
Ids are never copied from the CSVs; the database assigns them, so nothing collides with real rows.

Connection: DEMO_ADMIN_DATABASE_URL in Harness/.env (the database owner, since this writes and deletes).
Each seeding run draws new random passwords, prints them once, and saves them to demo-credentials.txt
(git-ignored). `transfer` rows are not inserted: the app has no transfer type and the coach never counts them.
"""
from __future__ import annotations

import csv
import getpass
import os
import re
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PERSONA_CSV = ROOT / "persona" / "csv"
CREDENTIALS = ROOT / "demo-credentials.txt"
READER_TEMPLATE = HERE / "coach_reader.sql"
READER_OUT = HERE / "coach_reader.generated.sql"
DEMO_DOMAIN = "demo.budgetbuddy.test"
UAT_EMAILS = tuple(f"{name}@{DEMO_DOMAIN}" for name in ("henry", "diana", "grace"))
DEMO_EMAILS = tuple(f"{name}@{DEMO_DOMAIN}" for name in
                    ("alice", "bob", "charlie", "diana", "eve", "frank", "grace", "henry", "ivy", "jack"))
THAI_OFFSET = "+07:00"

ACCOUNT_TYPE = {"cash": "wallet", "ewallet": "wallet", "bank": "bank", "credit": "credit_card"}
GOAL_RULE = {"fixed_monthly": "fixed"}
ICON = {"utensils": "🍜", "bus": "🚌", "shopping-bag": "🛍️", "music": "🎬", "receipt": "💡",
        "book": "📚", "heart": "💊", "dots": "🏷️", "gift": "🎁", "briefcase": "💼", "clock": "⏱️",
        "pen": "✏️", "heart-handshake": "🎁", "plane": "✈️", "shield": "🛟", "laptop": "💻", "home": "🏠"}

# Delete order matters: children before parents. Every statement is limited to demo users.
DEMO_USERS = f"SELECT id FROM \"User\" WHERE email LIKE '%@{DEMO_DOMAIN}'"
REMOVE_STEPS = [
    ("GoalEntry", f'DELETE FROM "GoalEntry" WHERE "userId" IN ({DEMO_USERS})'),
    ("Goal", f'DELETE FROM "Goal" WHERE "userId" IN ({DEMO_USERS})'),
    ("AssetLot", f'DELETE FROM "AssetLot" WHERE "userId" IN ({DEMO_USERS})'),
    ("Bond", f'DELETE FROM "Bond" WHERE "userId" IN ({DEMO_USERS})'),
    ("RecurringTransaction", f'DELETE FROM "RecurringTransaction" WHERE "userId" IN ({DEMO_USERS})'),
    ("Transaction", f'DELETE FROM "Transaction" WHERE "userId" IN ({DEMO_USERS})'),
    ("Account", f'DELETE FROM "Account" WHERE "userId" IN ({DEMO_USERS})'),
    ("Category", f'DELETE FROM "Category" WHERE "userId" IN ({DEMO_USERS})'),
    ("User", f"DELETE FROM \"User\" WHERE email LIKE '%@{DEMO_DOMAIN}'"),
]
COUNT_STEPS = [(t, sql.replace("DELETE FROM", "SELECT count(*) FROM", 1)) for t, sql in REMOVE_STEPS]


def _read(name: str, root: Path) -> list[dict]:
    with open(root / f"{name}.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _ts(value: str | None) -> str | None:
    return f"{value.replace(' ', 'T')}{THAI_OFFSET}" if value else None


def demo_email(csv_email: str) -> str:
    """persona01.alice@budgetbuddy.test -> alice@demo.budgetbuddy.test"""
    key = csv_email.split("@")[0].split(".", 1)[-1]
    return f"{key}@{DEMO_DOMAIN}"


def build_plan(root: Path = PERSONA_CSV) -> list[dict]:
    """One dict per persona with its rows in app terms, keyed by the CSV's own ids (only used to link rows)."""
    by_user: dict[str, dict] = {}
    for u in _read("User", root):
        by_user[u["id"]] = {"csv_id": u["id"], "email": demo_email(u["email"]), "accounts": [],
                            "categories": [], "transactions": [], "goals": [], "entries": [],
                            "recurring": [], "skipped_transfers": 0}
    for a in _read("Account", root):
        by_user[a["userId"]]["accounts"].append({
            "csv_id": a["id"], "name": a["name"], "type": ACCOUNT_TYPE.get(a["type"], "bank"),
            "currency": a["currency"] or "THB", "bankName": a["bankName"] or None, "deletedAt": _ts(a["deletedAt"])})
    for c in _read("Category", root):
        by_user[c["userId"]]["categories"].append({
            "csv_id": c["id"], "name": c["name"], "color": c["color"] or None,
            "icon": ICON.get(c["icon"], c["icon"] or None), "type": c["type"],
            "budget": float(c["budget"]) if c["budget"] else None, "deletedAt": _ts(c["deletedAt"])})
    for t in _read("Transaction", root):
        u = by_user[t["userId"]]
        if t["type"] == "transfer":
            u["skipped_transfers"] += 1
            continue
        u["transactions"].append({
            "amount": float(t["amount"]), "type": t["type"], "description": t["description"] or None,
            "date": _ts(t["date"]), "account": t["accountId"], "category": t["categoryId"] or None,
            "createdAt": _ts(t["createdAt"]), "deletedAt": _ts(t["deletedAt"])})
    for g in _read("Goal", root):
        by_user[g["userId"]]["goals"].append({
            "csv_id": g["id"], "name": g["name"], "icon": ICON.get(g["icon"], g["icon"] or None),
            "target": float(g["target"]), "deadline": _ts(g["deadline"]),
            "ruleType": GOAL_RULE.get(g["ruleType"]), "ruleValue": float(g["ruleValue"]) if g["ruleValue"] else None,
            "createdAt": _ts(g["createdAt"]), "deletedAt": _ts(g["deletedAt"])})
    for e in _read("GoalEntry", root):
        by_user[e["userId"]]["entries"].append({
            "goal": e["goalId"], "account": e["accountId"], "amount": float(e["amount"]),
            "kind": e["kind"], "date": _ts(e["date"]), "deletedAt": _ts(e["deletedAt"])})
    for r in _read("RecurringTransaction", root):
        by_user[r["userId"]]["recurring"].append({
            "amount": float(r["amount"]), "type": r["type"], "description": r["description"] or None,
            "account": r["accountId"], "category": r["categoryId"] or None, "frequency": r["frequency"],
            "nextDate": _ts(r["nextDate"]), "active": r["active"] == "True", "currency": r["currency"] or None})
    return list(by_user.values())


def summarize(plan: list[dict]) -> str:
    lines = [f"{'email':<34}{'accts':>6}{'cats':>6}{'txns':>7}{'goals':>6}{'recur':>6}"]
    for u in plan:
        lines.append(f"{u['email']:<34}{len(u['accounts']):>6}{len(u['categories']):>6}"
                     f"{len(u['transactions']):>7}{len(u['goals']):>6}{len(u['recurring']):>6}")
    return "\n".join(lines)


def make_passwords(plan: list[dict]) -> dict[str, str]:
    return {u["email"]: secrets.token_urlsafe(9) for u in plan}


def write_credentials(passwords: dict[str, str], path: Path = CREDENTIALS) -> None:
    body = ["Budget Buddy demo logins (random per run). Remove with: python dev.py demo-remove --yes", ""]
    body += [f"{email}    {pw}" for email, pw in passwords.items()]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def reset_uat_passwords(conn, path: Path = CREDENTIALS, password_factory=None, hasher=None) -> None:
    """Rotate only the three UAT demo logins. Never touch their transactions or other users."""
    if path.exists():
        raise RuntimeError(f"{path.name} already exists; refusing to overwrite it")
    rows = conn.execute('SELECT id, email FROM "User" WHERE email IN (%s, %s, %s)', UAT_EMAILS).fetchall()
    if {email for _, email in rows} != set(UAT_EMAILS):
        raise RuntimeError("Henry, Diana, and Grace must all exist before resetting passwords")
    if password_factory is None:
        password_factory = lambda: secrets.token_urlsafe(12)
    if hasher is None:
        import bcrypt
        hasher = lambda password: bcrypt.hashpw(password.encode(), bcrypt.gensalt(10)).decode()
    passwords = {email: password_factory() for email in UAT_EMAILS}
    for uid, email in rows:
        result = conn.execute('UPDATE "User" SET "passwordHash" = %s WHERE id = %s AND email = %s',
                              (hasher(passwords[email]), uid, email))
        if result.rowcount != 1:
            raise RuntimeError(f"password reset did not update exactly one row for {email}")
    # O_EXCL refuses an existing file, and mode 0600 keeps passwords private from creation.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write("Budget Buddy UAT demo logins (passwords rotated for these three only)\n\n")
        for email in UAT_EMAILS:
            out.write(f"{email}    {passwords[email]}\n")


def validate_shared_password(password: str) -> None:
    if not 8 <= len(password.encode("utf-8")) <= 72 or password != password.strip():
        raise ValueError("password must be 8–72 bytes with no leading or trailing spaces")


def set_shared_demo_password(conn, password: str, hasher=None) -> None:
    """Set one entered password for exactly the ten synthetic persona accounts, in one transaction."""
    validate_shared_password(password)
    placeholders = ", ".join(["%s"] * len(DEMO_EMAILS))
    rows = conn.execute(f'SELECT id, email FROM "User" WHERE email IN ({placeholders})', DEMO_EMAILS).fetchall()
    if {email for _, email in rows} != set(DEMO_EMAILS) or len(rows) != len(DEMO_EMAILS):
        raise RuntimeError("all ten demo accounts must exist before changing passwords")
    if hasher is None:
        import bcrypt
        hasher = lambda value: bcrypt.hashpw(value.encode(), bcrypt.gensalt(10)).decode()
    for uid, email in rows:
        result = conn.execute('UPDATE "User" SET "passwordHash" = %s WHERE id = %s AND email = %s',
                              (hasher(password), uid, email))
        if result.rowcount != 1:
            raise RuntimeError(f"password change did not update exactly one row for {email}")


def seed(conn, plan: list[dict], passwords: dict[str, str], hasher) -> dict[str, int]:
    """Insert every persona. Ids come from the database; csv ids only link rows to each other."""
    cur = conn.cursor()
    cur.execute(f"SELECT count(*) FROM \"User\" WHERE email LIKE '%@{DEMO_DOMAIN}'")
    if cur.fetchone()[0]:
        raise RuntimeError("demo users already exist; run `python dev.py demo-remove --yes` first")
    totals = {"User": 0, "Account": 0, "Category": 0, "Transaction": 0, "Goal": 0, "GoalEntry": 0,
              "RecurringTransaction": 0}

    def insert(table: str, cols: list[str], vals: list) -> int:
        quoted = ", ".join(f'"{c}"' for c in cols)
        marks = ", ".join(["%s"] * len(cols))
        cur.execute(f'INSERT INTO "{table}" ({quoted}) VALUES ({marks}) RETURNING id', vals)
        totals[table] += 1
        return cur.fetchone()[0]

    for u in plan:
        uid = insert("User", ["email", "passwordHash"], [u["email"], hasher(passwords[u["email"]])])
        acc = {a["csv_id"]: insert("Account", ["userId", "name", "type", "currency", "bankName", "deletedAt"],
                                   [uid, a["name"], a["type"], a["currency"], a["bankName"], a["deletedAt"]])
               for a in u["accounts"]}
        cat = {c["csv_id"]: insert("Category", ["userId", "name", "color", "icon", "type", "budget", "deletedAt"],
                                   [uid, c["name"], c["color"], c["icon"], c["type"], c["budget"], c["deletedAt"]])
               for c in u["categories"]}
        for t in u["transactions"]:
            insert("Transaction", ["userId", "amount", "type", "description", "date", "accountId", "categoryId",
                                   "createdAt", "deletedAt"],
                   [uid, t["amount"], t["type"], t["description"], t["date"], acc[t["account"]],
                    cat.get(t["category"]), t["createdAt"], t["deletedAt"]])
        for r in u["recurring"]:
            insert("RecurringTransaction", ["userId", "amount", "type", "description", "accountId", "categoryId",
                                            "frequency", "nextDate", "active", "currency"],
                   [uid, r["amount"], r["type"], r["description"], acc[r["account"]], cat.get(r["category"]),
                    r["frequency"], r["nextDate"], r["active"], r["currency"]])
        goal = {g["csv_id"]: insert("Goal", ["userId", "name", "icon", "target", "deadline", "ruleType", "ruleValue",
                                             "createdAt", "deletedAt"],
                                    [uid, g["name"], g["icon"], g["target"], g["deadline"], g["ruleType"],
                                     g["ruleValue"], g["createdAt"], g["deletedAt"]])
                for g in u["goals"]}
        for e in u["entries"]:
            insert("GoalEntry", ["userId", "goalId", "accountId", "amount", "kind", "date", "deletedAt"],
                   [uid, goal[e["goal"]], acc[e["account"]], e["amount"], e["kind"], e["date"], e["deletedAt"]])
    return totals


def remove(conn) -> dict[str, int]:
    cur = conn.cursor()
    counts = {}
    for table, sql in REMOVE_STEPS:
        cur.execute(sql)
        counts[table] = cur.rowcount
    return counts


def count_demo(conn) -> dict[str, int]:
    cur = conn.cursor()
    out = {}
    for table, sql in COUNT_STEPS:
        cur.execute(sql)
        out[table] = cur.fetchone()[0]
    return out


def reader_sql(password: str | None = None) -> str:
    return READER_TEMPLATE.read_text(encoding="utf-8").replace("__PASSWORD__", password or secrets.token_urlsafe(24))


def _connect():
    from envfile import load_env
    load_env()
    dsn = os.environ.get("DEMO_ADMIN_DATABASE_URL", "")
    if not dsn:
        raise SystemExit("Set DEMO_ADMIN_DATABASE_URL in Harness/.env (the database owner connection).")
    import psycopg
    return psycopg.connect(dsn, connect_timeout=10, prepare_threshold=None)


def _host(dsn: str) -> str:
    m = re.search(r"@([^/:?]+)", dsn)
    return m.group(1) if m else "?"


def reader_url(admin_dsn: str, password: str) -> str:
    """The owner connection string with the user changed to coach_reader (keeping any .<project-ref>) and the new password."""
    from urllib.parse import quote, urlsplit, urlunsplit
    u = urlsplit(admin_dsn)
    if not u.username or not u.hostname:
        raise ValueError("DEMO_ADMIN_DATABASE_URL is not a postgresql:// URL with a user and host")
    _, dot, ref = u.username.partition(".")
    user = "coach_reader" + (dot + ref if dot else "")
    host = u.hostname + (f":{u.port}" if u.port else "")
    return urlunsplit((u.scheme, f"{quote(user, safe='.')}:{quote(password, safe='')}@{host}", u.path or "/postgres", "", ""))


def write_reader_url() -> int:
    """Build COACH_DATABASE_URL from the owner URL and the generated SQL's password, and save it in Harness/.env."""
    from envfile import DEFAULT_ENV, load_env
    load_env()
    admin = os.environ.get("DEMO_ADMIN_DATABASE_URL", "")
    if not admin:
        print("Set DEMO_ADMIN_DATABASE_URL in Harness/.env first.")
        return 1
    if not READER_OUT.exists():
        print("Run `python dev.py demo-reader-sql` first, then run that SQL in Supabase.")
        return 1
    m = re.search(r"PASSWORD '([^']+)'", READER_OUT.read_text(encoding="utf-8"))
    if not m:
        print("Could not find the password in the generated SQL file.")
        return 1
    url = reader_url(admin, m.group(1))
    lines = DEFAULT_ENV.read_text(encoding="utf-8").splitlines() if DEFAULT_ENV.exists() else []
    lines = [ln for ln in lines if not ln.startswith("COACH_DATABASE_URL=")] + ["COACH_DATABASE_URL=" + url]
    DEFAULT_ENV.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    shown = re.sub(r":[^:@/]+@", ":********@", url)
    print("Saved COACH_DATABASE_URL in Harness/.env as:")
    print("  " + shown)
    print("Next: run the SQL in Supabase (if you have not), then: python dev.py demo-check-reader")
    return 0


def check_reader() -> int:
    """Connect as coach_reader and prove it can read the views but nothing else. Writes nothing."""
    from envfile import load_env
    load_env()
    dsn = os.environ.get("COACH_DATABASE_URL", "")
    if not dsn:
        print("COACH_DATABASE_URL is not set in Harness/.env")
        return 1
    import psycopg
    ok = True

    def attempt(label: str, sql: str, should_work: bool) -> None:
        nonlocal ok
        try:
            with psycopg.connect(dsn, connect_timeout=10, prepare_threshold=None) as conn:
                conn.execute(sql)
            worked = True
        except psycopg.OperationalError as e:
            print(f"[xx] could not connect as coach_reader: {type(e).__name__} (check the user, password and host)")
            raise SystemExit(1)
        except psycopg.Error:
            worked = False
        good = worked == should_work
        ok &= good
        print(f"[{'ok' if good else 'xx'}] {label}: {'allowed' if worked else 'refused'}"
              f" (expected {'allowed' if should_work else 'refused'})")

    attempt("read v_transactions", "SELECT count(*) FROM v_transactions", True)
    attempt("read v_categories", "SELECT count(*) FROM v_categories", True)
    attempt('read "User" (password hashes)', 'SELECT count(*) FROM "User"', False)
    attempt('read "Transaction" directly', 'SELECT count(*) FROM "Transaction"', False)
    attempt("write: delete a transaction", 'DELETE FROM "Transaction" WHERE false', False)
    attempt("write: create a table", "CREATE TABLE coach_probe (x int)", False)
    print()
    print("The reader role is correctly limited." if ok else "Something is wrong; do not use the chat until this passes.")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("seed", "remove", "reader-sql", "status", "check-reader", "reader-url", "reset-passwords", "shared-password"):
        print(__doc__)
        return 2
    cmd, apply = argv[0], "--yes" in argv
    if cmd == "check-reader":
        return check_reader()
    if cmd == "reader-url":
        return write_reader_url()
    if cmd == "reader-sql":
        pw = secrets.token_urlsafe(24)
        READER_OUT.write_text(reader_sql(pw), encoding="utf-8")
        print(f"Wrote {READER_OUT.name} (read-only role coach_reader, random password inside the file).\n"
              "Review it, run it once in the Supabase SQL editor, then set COACH_DATABASE_URL in Harness/.env\n"
              f"to a connection string for user coach_reader with the password from that file.")
        return 0
    if cmd == "reset-passwords":
        if CREDENTIALS.exists():
            print(f"Refusing to overwrite {CREDENTIALS}.")
            return 1
        print("UAT password reset targets: " + ", ".join(UAT_EMAILS))
        if not apply:
            print("Dry run: no passwords changed. Add --yes to rotate only these three accounts.")
            return 0
        conn = _connect()
        try:
            with conn:
                reset_uat_passwords(conn)
        except Exception as e:
            print(f"Password reset failed ({type(e).__name__}); no passwords printed.")
            return 1
        finally:
            conn.close()
        print(f"Passwords saved to {CREDENTIALS} (owner-only permissions). No persona data was changed.")
        return 0
    if cmd == "shared-password":
        print("Shared password targets: " + ", ".join(DEMO_EMAILS))
        if not apply:
            print("Dry run: no passwords changed. Add --yes to enter a shared password privately.")
            return 0
        password = getpass.getpass("New shared demo password (8–72 bytes): ")
        confirm = getpass.getpass("Repeat password: ")
        if password != confirm:
            print("Passwords did not match; no accounts changed.")
            return 1
        try:
            validate_shared_password(password)
        except ValueError as e:
            print(f"{e}; no accounts changed.")
            return 1
        conn = _connect()
        try:
            with conn:
                set_shared_demo_password(conn, password)
        except Exception as e:
            print(f"Password change failed ({type(e).__name__}); no password was printed.")
            return 1
        finally:
            conn.close()
        print("All ten demo passwords changed. The existing demo-credentials.txt, if present, now has old passwords.")
        return 0
    if cmd == "seed":
        plan = build_plan()
        print(summarize(plan))
        print(f"\n{sum(len(u['transactions']) for u in plan)} transactions; "
              f"{sum(u['skipped_transfers'] for u in plan)} transfer rows skipped.")
        if not apply:
            print("\nDry run: nothing was written. Add --yes to insert.")
            return 0
        import bcrypt
        passwords = make_passwords(plan)
        conn = _connect()
        try:
            with conn:
                totals = seed(conn, plan, passwords,
                              lambda p: bcrypt.hashpw(p.encode(), bcrypt.gensalt(10)).decode())
        finally:
            conn.close()
        write_credentials(passwords)
        print("\nInserted:", ", ".join(f"{k} {v}" for k, v in totals.items()))
        print(f"Logins and passwords: {CREDENTIALS}")
        return 0
    conn = _connect()
    try:
        if cmd == "status" or not apply:
            counts = count_demo(conn)
            print("Rows belonging to demo users (@" + DEMO_DOMAIN + "): "
                  + ", ".join(f"{k} {v}" for k, v in counts.items()))
            if cmd == "remove":
                print("\nDry run: nothing was deleted. Add --yes to delete these rows.")
            return 0
        with conn:
            counts = remove(conn)
        print("Deleted:", ", ".join(f"{k} {v}" for k, v in counts.items()))
        if CREDENTIALS.exists():
            CREDENTIALS.unlink()
            print(f"Deleted {CREDENTIALS.name}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
