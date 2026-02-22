"""
Unit tests for the OIDResolver helper class.
"""

import unittest
from pg_plan_alternatives import helper


class DummyCursor:
    def __init__(self):
        self.queries = []
        self.closed = False

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        # return two entries as if fetched from catalog
        return [("public", "foo", 100), ("bar", "baz", 200)]

    def fetchone(self):
        # return a single row stored on the instance
        return getattr(self, "_row", None)

    def close(self):
        self.closed = True


class DummyConn:
    def __init__(self):
        self.closed = False
        self.cursor_obj = DummyCursor()

    def cursor(self):
        return self.cursor_obj

    def set_session(self, **kwargs):
        pass

    def close(self):
        self.closed = True


class TestOIDResolver(unittest.TestCase):
    def setUp(self):
        # patch psycopg2.connect before creating resolver
        self._orig_connect = helper.psycopg2.connect
        helper.psycopg2.connect = lambda **kwargs: DummyConn()
        # instantiate resolver (will "connect" using DummyConn)
        self.resolver = helper.OIDResolver("postgres://u:p@h/db")

        # replace connection and cursor references with our dummy so we can
        # manipulate behaviour later
        self.resolver.connection = DummyConn()
        self.resolver.cur = self.resolver.connection.cursor()
        # clear cache to start fresh
        self.resolver.cache.clear()

    def tearDown(self):
        # restore original psycopg2.connect
        helper.psycopg2.connect = self._orig_connect

    def test_cache_hit(self):
        self.resolver.cache["123"] = "public.test"
        self.assertEqual(self.resolver.resolve_oid(123), "public.test")

    def test_fetch_all_oids_warms_cache(self):
        # call again to trigger fetch_all_oids through connect
        # but our dummy cursor returns two entries
        self.resolver.fetch_all_oids()
        self.assertIn("100", self.resolver.cache)
        self.assertEqual(self.resolver.cache["100"], "public.foo")
        self.assertIn("200", self.resolver.cache)

    def test_fetch_oid_from_db_cache(self):
        # prepare cursor to return a specific row
        self.resolver.cur._row = ("schema", "tbl")
        name = self.resolver.fetch_oid_from_db(456)
        self.assertEqual(name, "schema.tbl")
        self.assertEqual(self.resolver.cache.get("456"), "schema.tbl")

    def test_fetch_oid_not_found(self):
        self.resolver.cur._row = None
        self.assertEqual(self.resolver.fetch_oid_from_db(789), "Oid 789")

    def test_disconnect(self):
        # make sure objects are torn down
        self.resolver.disconnect()
        self.assertIsNone(self.resolver.cur)
        self.assertIsNone(self.resolver.connection)


if __name__ == "__main__":
    unittest.main()
