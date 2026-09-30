"""A route that catches an exception still leaves a record of it.

Routes catch their own exceptions so the page can show a sentence, and until
_route_failed existed every one of them returned without logging - the one
failure that left nothing in the log file. Driven through a real route with
its action replaced, so the assertion is about what the request produces.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


class CaughtRouteFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT))
        import server
        cls.server = server
        server.app.config.update(TESTING=True)
        cls.client = server.app.test_client()
        cls.header = {server.API_REQUEST_HEADER: "1"}

    def post(self, fn):
        with mock.patch.dict(self.server.SETTINGS_ACTIONS, {"boom": fn}), \
                mock.patch.object(self.server.applog, "note_failure") as noted:
            r = self.client.post("/api/settings/boom", json={}, headers=self.header)
        return r, noted

    def test_a_fault_is_logged_and_the_page_gets_the_message(self):
        def fn(d):
            raise OSError("the disk said no")
        r, noted = self.post(fn)
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.get_json(), {"error": "the disk said no"})
        self.assertEqual(noted.call_count, 1)
        what, exc = noted.call_args.args
        self.assertIn("/api/settings/boom", what)
        self.assertIsInstance(exc, OSError)

    def test_a_missing_field_is_the_request_and_is_not_logged(self):
        def fn(d):
            return d["name"]
        r, noted = self.post(fn)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json(), {"error": "missing field: 'name'"})
        noted.assert_not_called()

    def test_no_traceback_reaches_the_page(self):
        def fn(d):
            raise ValueError("plain words")
        r, _ = self.post(fn)
        self.assertNotIn("Traceback", r.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
