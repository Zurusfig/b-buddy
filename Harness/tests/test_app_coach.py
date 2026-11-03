"""Offline tests for the finance-app link: demo seeding/removal, the database reader, the local server.

    python -m unittest discover -s tests -v

No database, model or network is used: the database is a fake that records statements or serves rows
built from persona/csv, and the server is exercised on an ephemeral local port.
"""
import csv
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

COACH = Path(__file__).resolve().parent.parent / "budget_coach"
sys.path.insert(0, str(COACH))

import coach_server  # noqa: E402
import db_data  # noqa: E402
import demo_db  # noqa: E402
import persona_data  # noqa: E402
from persona_data import PersonaData  # noqa: E402

HAVE_DATA = persona_data.available()


class FakeCursor:
    def __init__(self, log, existing_demo=0):
        self.log, self.existing, self._next, self.rowcount = log, existing_demo, 0, 3

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        if "RETURNING id" in sql:
            self._next += 1
            self._row = (self._next,)
        elif sql.startswith("SELECT count(*)"):
            self._row = (self.existing,)

    def fetchone(self):
        return self._row


class FakeConn:
    def __init__(self, existing_demo=0):
        self.log = []
        self._cur = FakeCursor(self.log, existing_demo)

    def cursor(self):
        return self._cur


@unittest.skipUnless(HAVE_DATA, "persona/csv not present")
class DemoSeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = demo_db.build_plan()

    def test_ten_users_all_on_the_demo_domain(self):
        self.assertEqual(len(self.plan), 10)
        for u in self.plan:
            self.assertTrue(u["email"].endswith("@" + demo_db.DEMO_DOMAIN), u["email"])
        self.assertEqual(self.plan[0]["email"], "alice@demo.budgetbuddy.test")

    def test_transfers_skipped_and_no_other_type_changes(self):
        types = {t["type"] for u in self.plan for t in u["transactions"]}
        self.assertEqual(types, {"income", "expense"})
        self.assertEqual(sum(u["skipped_transfers"] for u in self.plan), 672)

    def test_values_use_the_apps_vocabulary(self):
        accts = {a["type"] for u in self.plan for a in u["accounts"]}
        self.assertTrue(accts <= {"wallet", "bank", "credit_card"}, accts)
        icons = {c["icon"] for u in self.plan for c in u["categories"]}
        self.assertFalse(any(i and i.isascii() and "-" in i or i in ("utensils", "bus") for i in icons), icons)
        rules = {g["ruleType"] for u in self.plan for g in u["goals"]}
        self.assertTrue(rules <= {None, "fixed", "percent"}, rules)

    def test_timestamps_carry_the_thai_offset(self):
        t = self.plan[0]["transactions"][0]["date"]
        self.assertRegex(t, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+07:00$")

    def test_seed_inserts_without_csv_ids_and_hashes_passwords(self):
        conn = FakeConn()
        pw = demo_db.make_passwords(self.plan)
        self.assertEqual(len(set(pw.values())), 10)
        totals = demo_db.seed(conn, self.plan, pw, hasher=lambda p: "hash:" + p)
        self.assertEqual(totals["User"], 10)
        self.assertEqual(totals["Transaction"], 5500)
        inserts = [s for s, _ in conn.log if s.startswith("INSERT")]
        self.assertFalse(any('"id"' in s.split("VALUES")[0] for s in inserts), "ids must be database-assigned")
        users = [p for s, p in conn.log if s.startswith('INSERT INTO "User"')]
        self.assertTrue(all(p[1].startswith("hash:") and p[1] != "hash:" for p in users))

    def test_seed_refuses_when_demo_users_exist(self):
        with self.assertRaises(RuntimeError):
            demo_db.seed(FakeConn(existing_demo=1), self.plan, demo_db.make_passwords(self.plan), hasher=str)

    def test_credentials_file_lists_every_login(self):
        import tempfile
        path = Path(tempfile.mkdtemp()) / "creds.txt"
        pw = demo_db.make_passwords(self.plan)
        demo_db.write_credentials(pw, path)
        text = path.read_text("utf-8")
        for email, p in pw.items():
            self.assertIn(f"{email}    {p}", text)


class DemoRemoveTests(unittest.TestCase):
    def test_every_delete_is_limited_to_demo_users(self):
        for table, sql in demo_db.REMOVE_STEPS:
            self.assertTrue(sql.startswith("DELETE FROM"), sql)
            self.assertIn("@" + demo_db.DEMO_DOMAIN, sql, f"{table} delete is not scoped to demo users")
            self.assertIn("WHERE", sql)

    def test_children_deleted_before_parents(self):
        order = [t for t, _ in demo_db.REMOVE_STEPS]
        self.assertEqual(order[-1], "User")
        for child, parent in [("Transaction", "Account"), ("Transaction", "Category"), ("GoalEntry", "Goal"),
                              ("GoalEntry", "Account"), ("Account", "User")]:
            self.assertLess(order.index(child), order.index(parent), f"{child} before {parent}")

    def test_remove_runs_each_step_and_counts_rows(self):
        conn = FakeConn()
        counts = demo_db.remove(conn)
        self.assertEqual(list(counts), [t for t, _ in demo_db.REMOVE_STEPS])
        self.assertEqual(len(conn.log), len(demo_db.REMOVE_STEPS))

    def test_status_counts_use_select_not_delete(self):
        for _, sql in demo_db.COUNT_STEPS:
            self.assertTrue(sql.startswith("SELECT count(*)"), sql)
            self.assertNotIn("DELETE", sql)

    def test_reader_sql_fills_the_password_and_grants_only_views(self):
        sql = demo_db.reader_sql("pw-for-test")
        self.assertNotIn("__PASSWORD__", sql)
        self.assertIn("pw-for-test", sql)
        grants = [ln for ln in sql.splitlines() if ln.startswith("GRANT")]
        self.assertEqual(grants, ["GRANT USAGE ON SCHEMA public TO coach_reader;",
                                  "GRANT SELECT ON v_transactions, v_categories TO coach_reader;"])
        self.assertIn("default_transaction_read_only = on", sql)


def csv_fetch(user_id):
    """A fake database serving the view rows for one persona, built from the CSVs the way the views would."""
    with open(persona_data.PERSONA_DIR / "Category.csv", encoding="utf-8") as f:
        cats = {c["id"]: c for c in csv.DictReader(f) if int(c["userId"]) == user_id}
    with open(persona_data.PERSONA_DIR / "Transaction.csv", encoding="utf-8") as f:
        txns = list(csv.DictReader(f))

    def fetch(sql, params):
        assert params == (user_id,), "the user id must be a bound parameter"
        if "v_transactions" in sql:
            out = []
            for t in txns:
                if int(t["userId"]) != user_id or t["deletedAt"]:
                    continue
                c = cats.get(t["categoryId"])
                out.append({"date": t["date"], "amount": t["amount"], "type": t["type"],
                            "description": t["description"], "category": c["name"] if c else None,
                            "category_type": c["type"] if c else None})
            return out
        return [{"category": c["name"], "category_type": c["type"],
                 "monthly_limit": c["budget"] or None} for c in cats.values()]
    return fetch


@unittest.skipUnless(HAVE_DATA, "persona/csv not present")
class DbDataTests(unittest.TestCase):
    def test_matches_the_csv_reader_for_every_persona_and_month(self):
        for u in persona_data.list_users():
            uid = u["user_id"]
            ref, db = PersonaData(uid), db_data.DbData(uid, fetch=csv_fetch(uid))
            self.assertEqual(db.months(), ref.months(), u["key"])
            for m in ref.months():
                self.assertEqual(db.month_summary(m), ref.month_summary(m), (u["key"], m))
                for cat in ref.expense_categories:
                    self.assertEqual(db.sum_by_category(m, cat), ref.sum_by_category(m, cat), (u["key"], m, cat))
            self.assertEqual(db.budgets, ref.budgets, u["key"])

    def test_user_without_budgets_reports_a_clear_error(self):
        db = db_data.DbData(7, fetch=csv_fetch(7))
        with self.assertRaises(ValueError):
            db.over_budget(db.reference_month())

    def test_reference_month_override_and_default(self):
        self.assertEqual(db_data.DbData(1, fetch=csv_fetch(1), reference_month="2026-09").reference_month(), "2026-09")
        with mock.patch.dict("os.environ", {"COACH_REFERENCE_MONTH": "2026-09"}):
            self.assertEqual(db_data.DbData(1, fetch=csv_fetch(1)).reference_month(), "2026-10")
        with mock.patch.dict("os.environ", {"COACH_REFERENCE_MONTH": ""}):
            self.assertEqual(db_data.DbData(1, fetch=csv_fetch(1)).reference_month(), "2026-10")

    def test_unknown_user_is_an_error_not_empty_data(self):
        with self.assertRaises(ValueError):
            db_data.DbData(99, fetch=lambda sql, params: [])

    def test_missing_connection_string_fails_clearly(self):
        with mock.patch.dict("os.environ", {"COACH_DATABASE_URL": ""}):
            with self.assertRaises(RuntimeError):
                db_data.DbData(1)


class UatMetadataTests(unittest.TestCase):
    def test_app_run_passes_metadata_to_question_and_http_logs(self):
        seen = {}
        def answer(question, data, log_extra=None):
            seen.update(log_extra)
            return {"answer": "ok", "route": "small", "model": "qwen3:4b", "flags": [],
                    "latency": 0.1, "calls": [], "run_id": "test-run"}
        uat = {"round": 2, "tester_number": 3, "task_id": "UAT-04"}
        with mock.patch.object(coach_server, "ollama_ready", return_value=(True, "")), \
             mock.patch.object(coach_server.agent.LOG, "write") as log:
            status, _ = coach_server.ask(4, "ค่าอาหาร", data_factory=lambda uid: mock.Mock(user_id=uid),
                                         answerer=answer, uat=uat, persona="Diana")
        self.assertEqual(status, 200)
        self.assertEqual({k: seen[k] for k in ("round", "tester_number", "task_id", "persona")},
                         {**uat, "persona": "Diana"})
        self.assertEqual(log.call_args.kwargs["task_id"], "UAT-04")
        self.assertEqual(log.call_args.kwargs["run_id"], "test-run")

    def test_normal_run_logs_null_metadata(self):
        with mock.patch.object(coach_server, "ollama_ready", return_value=(False, "ollama_offline")), \
             mock.patch.object(coach_server.agent.LOG, "write") as log:
            coach_server.ask(1, "food?")
        self.assertIsNone(log.call_args.kwargs["round"])
        self.assertIsNone(log.call_args.kwargs["task_id"])


class ServerTests(unittest.TestCase):
    SECRET = "test-secret"

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), coach_server.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def call(self, path, body=None, secret=SECRET, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                     headers={"Content-Type": "application/json", "X-Coach-Secret": secret or ""})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def setUp(self):
        p = mock.patch.dict("os.environ", {"COACH_SHARED_SECRET": self.SECRET})
        p.start()
        self.addCleanup(p.stop)

    def test_health_needs_no_secret_and_reports_offline_ollama(self):
        with mock.patch.object(coach_server, "ollama_ready", return_value=(False, "ollama_offline")):
            status, body = self.call("/health", secret=None)
        self.assertEqual((status, body["ready"], body["reason"]), (200, False, "ollama_offline"))

    def test_ask_rejects_missing_or_wrong_secret(self):
        for s in (None, "", "wrong"):
            status, body = self.call("/ask", {"userId": 1, "question": "hi"}, secret=s)
            self.assertEqual((status, body["error"]), (401, "unauthorized"))

    def test_ask_rejects_bad_bodies(self):
        bad = [{"userId": "1", "question": "x"}, {"userId": True, "question": "x"}, {"userId": 0, "question": "x"},
               {"userId": 1, "question": ""}, {"userId": 1, "question": "x" * 501}, {"userId": 1},
               {"question": "x"}]
        for b in bad:
            self.assertEqual(self.call("/ask", b)[0], 400, b)
        self.assertEqual(self.call("/ask", raw=b"not json")[0], 400)

    def test_unknown_path_is_404(self):
        self.assertEqual(self.call("/nope", {"a": 1})[0], 404)

    def test_ask_refuses_up_front_when_ollama_is_down(self):
        with mock.patch.object(coach_server, "ollama_ready", return_value=(False, "ollama_offline")), \
             mock.patch.object(coach_server.persona_agent, "answer_for") as answer:
            status, body = self.call("/ask", {"userId": 1, "question": "hi"})
        self.assertEqual((status, body), (503, {"error": "ollama_offline"}))
        answer.assert_not_called()

    def test_ask_passes_the_token_user_to_the_data_layer_and_shapes_the_reply(self):
        seen = {}

        def factory(uid):
            seen["uid"] = uid
            return mock.Mock(user_id=uid)

        fake = {"answer": "ใช้ไป 100 บาท", "route": "small", "intent": "spend_lookup", "model": "qwen3:4b",
                "flags": [], "escalated_by": [], "latency": 1.234,
                "calls": [{"name": "sum_by_category", "args": {"month": "2026-10", "category": "food"},
                           "result": 100.0},
                          {"name": "decline", "args": {}, "result": "x"}]}
        with mock.patch.object(coach_server, "ollama_ready", return_value=(True, "")), \
             mock.patch.object(coach_server.agent.LOG, "write"):
            status, body = coach_server.ask(7, "food?", data_factory=factory, answerer=lambda q, d, log_extra=None: fake)
        self.assertEqual(status, 200)
        self.assertEqual(seen["uid"], 7)
        self.assertEqual(body["answeredBy"], "local")
        self.assertEqual([c["tool"] for c in body["receipt"]], ["sum_by_category"])
        self.assertEqual(body["latencyS"], 1.23)

    def test_error_text_from_the_gateway_is_never_returned(self):
        fake = {"answer": "[error] HTTP 401 {'key': 'abc-secret-hash'}", "route": "advice", "model": None,
                "flags": [], "latency": 0.1, "calls": []}
        with mock.patch.object(coach_server, "ollama_ready", return_value=(True, "")):
            status, body = coach_server.ask(1, "q", data_factory=lambda u: mock.Mock(user_id=u),
                                            answerer=lambda q, d, log_extra=None: fake)
        self.assertEqual((status, body), (502, {"error": "model_error"}))

    def test_database_failure_is_reported_without_details(self):
        def boom(uid):
            raise ConnectionError("password authentication failed for user coach_reader")
        with mock.patch.object(coach_server, "ollama_ready", return_value=(True, "")):
            status, body = coach_server.ask(1, "q", data_factory=boom)
        self.assertEqual((status, body), (503, {"error": "database_unavailable"}))

    def test_unknown_user_is_404(self):
        def none(uid):
            raise ValueError("no data")
        with mock.patch.object(coach_server, "ollama_ready", return_value=(True, "")):
            self.assertEqual(coach_server.ask(1, "q", data_factory=none)[0], 404)

    def test_oversized_receipt_results_are_trimmed(self):
        big = [{"d": "x" * 50} for _ in range(100)]
        out = coach_server._trim(big)
        self.assertEqual(out["total"], 100)
        self.assertEqual(len(out["shown"]), 10)


if __name__ == "__main__":
    unittest.main()


class ReaderUrlTests(unittest.TestCase):
    def test_pooler_username_keeps_the_project_ref(self):
        url = demo_db.reader_url("postgresql://postgres.abcref:ownerpw@aws-1-x.pooler.supabase.com:6543/postgres?pgbouncer=true", "pw-1_x")
        self.assertEqual(url, "postgresql://coach_reader.abcref:pw-1_x@aws-1-x.pooler.supabase.com:6543/postgres")

    def test_direct_connection_user_has_no_ref(self):
        url = demo_db.reader_url("postgresql://postgres:ownerpw@db.example.com:5432/postgres", "pw")
        self.assertTrue(url.startswith("postgresql://coach_reader:pw@db.example.com:5432/"))

    def test_owner_password_is_never_copied(self):
        self.assertNotIn("ownerpw", demo_db.reader_url("postgresql://postgres.r:ownerpw@h:6543/postgres", "pw"))

    def test_bad_url_is_rejected(self):
        with self.assertRaises(ValueError):
            demo_db.reader_url("not a url", "pw")
