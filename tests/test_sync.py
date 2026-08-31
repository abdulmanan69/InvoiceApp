"""Phase B: prove customer sync works two-way against a fake Supabase backend.

Uses an in-memory stand-in for the REST calls the engine makes (upsert/select), so no network
is needed. Covers: local create -> push, remote pull on a second 'PC', edit propagation
(last-write-wins), and soft-delete propagation.
"""
import os
import tempfile
import types
import unittest

import db as dbmod
import models
import sync


class FakeSupabase:
    """Minimal in-memory model of the two PostgREST calls the sync engine uses."""

    def __init__(self):
        self.tables = {t: {} for t in dbmod.SYNC_ACTIVE}
        self._clock = 0

    def _ts(self):
        self._clock += 1
        return f"2026-08-31T00:00:{self._clock:02d}.000000+00:00"

    def upsert(self, table, token, rows, on_conflict="id"):
        for r in rows:
            r = dict(r)
            r["updated_at"] = self._ts()          # server stamps updated_at (like the SQL trigger)
            self.tables[table][r["id"]] = r
        return rows

    def select(self, table, token, params=None):
        params = params or {}
        cursor = params.get("updated_at", "gt.").split("gt.", 1)[-1]
        out = [r for r in self.tables[table].values() if r["updated_at"] > cursor]
        out.sort(key=lambda r: r["updated_at"])
        return out


class SyncPhaseBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.server = FakeSupabase()
        self._orig_client = models.cloud_client
        models.cloud_client = lambda db: self.server   # every 'PC' talks to the same fake server

    def tearDown(self):
        models.cloud_client = self._orig_client

    def _make_pc(self, name):
        app = types.SimpleNamespace()
        app.db = dbmod.Database(os.path.join(self.tmp, f"{name}.db"))
        for k, v in {"cloud_enabled": "1", "cloud_url": "http://x", "cloud_anon_key": "k",
                     "cloud_shop_id": "SHOP1", "cloud_auto_sync": "1"}.items():
            app.db.set_setting(k, v)
        app.db.set_secret("session", {"access_token": "tok", "refresh_token": "r", "user": {"id": "u1"}})
        return app, sync.SyncEngine(app)

    def test_two_way_customer_sync(self):
        a_app, a = self._make_pc("a")
        b_app, b = self._make_pc("b")

        # PC-A creates a customer and pushes it
        models.save_customer(a_app.db, {"name": "Alpha Traders", "phone": "0300"})
        res = a.sync_now()
        self.assertEqual(res["last_error"], "")
        self.assertEqual(res["pushed"], 1)

        # PC-B pulls and sees it
        b.sync_now()
        names = {c["name"]: c["phone"] for c in models.list_customers(b_app.db)}
        self.assertEqual(names.get("Alpha Traders"), "0300")

        # PC-B edits, PC-A pulls the edit (last-write-wins)
        bid = [c["id"] for c in models.list_customers(b_app.db) if c["name"] == "Alpha Traders"][0]
        models.save_customer(b_app.db, {"id": bid, "name": "Alpha Traders Ltd", "phone": "0311"})
        b.sync_now()
        a.sync_now()
        names = {c["name"]: c["phone"] for c in models.list_customers(a_app.db)}
        self.assertEqual(names.get("Alpha Traders Ltd"), "0311")

        # PC-A soft-deletes, PC-B pulls -> gone locally
        aid = [c["id"] for c in models.list_customers(a_app.db) if c["name"] == "Alpha Traders Ltd"][0]
        models.delete_customer(a_app.db, aid)
        a.sync_now()
        b.sync_now()
        self.assertNotIn("Alpha Traders Ltd", [c["name"] for c in models.list_customers(b_app.db)])

    def test_dirty_local_edit_survives_pull(self):
        # a local unpushed (dirty) edit must not be clobbered when a pull runs before it is pushed
        a_app, a = self._make_pc("a")
        b_app, b = self._make_pc("b")
        models.save_customer(a_app.db, {"name": "Beta", "phone": "1"})
        a.sync_now()
        b.sync_now()
        # B edits locally but has NOT pushed yet
        bid = [c["id"] for c in models.list_customers(b_app.db)][0]
        models.save_customer(b_app.db, {"id": bid, "name": "Beta", "phone": "999"})
        # a pull happens before B pushes; B's dirty row must survive
        b.sb = self.server
        b.shop = "SHOP1"
        b._pull()
        self.assertEqual([c["phone"] for c in models.list_customers(b_app.db)][0], "999")


class InviteTests(unittest.TestCase):
    def _code(self):
        import base64
        import json
        payload = {"u": "https://x.supabase.co", "k": "anonkey", "s": "S1", "c": "C1", "n": "My Shop"}
        return "SHOP-" + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")

    def test_invite_roundtrip_and_bad(self):
        d = models.cloud_parse_invite("  " + self._code() + "\n")
        self.assertEqual((d["u"], d["s"], d["c"], d["n"]),
                         ("https://x.supabase.co", "S1", "C1", "My Shop"))
        with self.assertRaises(Exception):
            models.cloud_parse_invite("SHOP-notbase64!!!")

    def test_parse_pasted_blob(self):
        import base64
        import cloud as cloudmod
        anon = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                + base64.urlsafe_b64encode(b'{"role":"anon"}').decode().rstrip("=") + ".sig123456")
        blob = f"Project URL\nhttps://abcd1234.supabase.co\nsome text {anon} more"
        u, k = cloudmod.parse_pasted(blob)
        self.assertEqual(u, "https://abcd1234.supabase.co")
        self.assertEqual(k, anon)
        self.assertEqual(cloudmod.parse_pasted("nothing here"), ("", ""))

    def test_join_invite_creates_local_employee(self):
        db = dbmod.Database(os.path.join(tempfile.mkdtemp(), "e.db"))

        class FakeAuth:
            def sign_in(self, e, p):
                raise Exception("400: Invalid login credentials")

            def sign_up(self, e, p, m=None):
                return {"access_token": "t", "refresh_token": "r", "user": {"id": "u9", "email": e}}

            def rpc(self, fn, tok, params=None):
                assert fn == "join_shop" and params == {"p_shop": "S1", "p_code": "C1"}
                return "employee"

        orig = models.cloud_client
        models.cloud_client = lambda _db: FakeAuth()
        try:
            u = models.cloud_join_invite(db, self._code(), "emp@x.com", "secret7", "Emp One")
        finally:
            models.cloud_client = orig
        self.assertEqual(u["role"], "employee")
        self.assertTrue(models.authenticate(db, "emp@x.com", "secret7"))
        self.assertEqual(db.get_setting("cloud_shop_id", ""), "S1")


if __name__ == "__main__":
    unittest.main()
