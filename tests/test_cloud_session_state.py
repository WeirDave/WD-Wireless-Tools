"""What the page header says about the Ekahau Cloud sign-in, and what it costs.

The status pill shows on every page, so the answer behind it has two jobs that
pull against each other:

* **It must be able to say the sign-in went stale** - which Cloud Manager only
  learns by trying it - so the person can log back in from wherever they are.
* **It must never contact Ekahau by itself.** The Home page promises that Cloud
  Manager talks to Ekahau only when told to, and a header that asked on every
  page load and every thirty seconds would break that for everyone who has a
  tab open.

`session` is the first, answered from memory; `session_check` is the second,
run only from a button. These tests drive both through the real server route
and through a real `CloudManager`, and assert the network is not touched by the
one that must not touch it.
"""
from __future__ import annotations

import unittest
from unittest import mock

import requests

import server
from tools import cloud_manager as cm


class _Api:
    """A stand-in for `EkahauAPI` whose answers are chosen by the test."""

    def __init__(self, ok=True, refused=False, email="someone@example.com",
                 failure=""):
        self.ok, self.refused, self.failure = ok, refused, failure
        self.user_email = email
        self.checks = 0

    def test_connection(self):
        self.checks += 1
        return self.ok


def _manager():
    m = cm.CloudManager.__new__(cm.CloudManager)
    m.config, m.api = {"output_dir": ""}, None
    return m


class _Quiet(unittest.TestCase):
    """No saved session on disk and nothing remembered from an earlier test."""

    def setUp(self):
        cm._saved_session_refused = False
        stamp = mock.patch.object(cm, "_saved_session_stamp", return_value=())
        self.stamp = stamp.start()
        self.addCleanup(stamp.stop)
        self.addCleanup(setattr, cm, "_saved_session_refused", False)


class TheFourStates(_Quiet):

    def test_no_session_and_nothing_saved_is_none(self):
        self.assertEqual(_manager().session_state()["state"], "none")

    def test_a_saved_session_that_has_not_been_tried_is_saved(self):
        self.stamp.return_value = (("a-file", 10, 1),)
        self.assertEqual(_manager().session_state()["state"], "saved")

    def test_a_session_ekahau_accepted_this_run_is_connected(self):
        m = _manager()
        m.api = _Api(email="someone@example.com")
        got = m.session_state()
        self.assertEqual((got["state"], got["email"]), ("connected", "someone@example.com"))

    def test_a_session_ekahau_refused_is_expired_and_beats_saved(self):
        """The saved files are deleted when they are refused, so `none` would
        be the honest-looking answer and the wrong one: the person was signed
        in and is not. Expired has to win until something replaces it."""
        m = _manager()
        m._expired = True
        self.stamp.return_value = (("a-file", 10, 1),)
        self.assertEqual(m.session_state()["state"], "expired")

    def test_asking_never_touches_the_network(self):
        """The whole point of the split: this runs on every page."""
        m = _manager()
        m.api = _Api()
        with mock.patch.object(requests.Session, "get",
                               side_effect=AssertionError("contacted Ekahau")), \
                mock.patch.object(requests.Session, "request",
                                  side_effect=AssertionError("contacted Ekahau")):
            for _ in range(3):
                m.session_state()
        self.assertEqual(m.api.checks, 0)


class HowASessionBecomesExpired(_Quiet):

    def test_a_listing_that_comes_back_401_marks_it_expired(self):
        """Cloud Manager is where staleness is found out; the header only
        reports what it found."""
        m = _manager()
        m.api = _Api()
        resp = requests.Response()
        resp.status_code = 401
        err = requests.exceptions.HTTPError(response=resp)
        out = m._api_error(err)
        self.assertTrue(out["sessionExpired"])
        self.assertEqual(m.session_state()["state"], "expired")

    def test_a_saved_session_ekahau_turns_away_is_expired_not_none(self):
        def refuse(self_, *a, **k):
            r = requests.Response()
            r.status_code = 302
            return r
        m = _manager()
        with mock.patch.object(cm, "load_cookies_from_disk",
                               return_value=([{"name": "AccessToken", "value": "old"}], "csrf")), \
                mock.patch.object(cm, "discard_saved_session", return_value=True), \
                mock.patch.object(requests.Session, "get", refuse), \
                mock.patch.object(cm, "try_browser_cookies", return_value=None):
            m._ensure()
        self.assertEqual(m.session_state()["state"], "expired")

    def test_a_network_that_is_down_does_not_expire_it(self):
        """No answer from Ekahau proves nothing about the cookie."""
        m = _manager()
        with mock.patch.object(cm, "load_cookies_from_disk",
                               return_value=([{"name": "AccessToken", "value": "x"}], "csrf")), \
                mock.patch.object(requests.Session, "get",
                                  side_effect=requests.exceptions.ConnectionError("down")), \
                mock.patch.object(cm, "try_browser_cookies", return_value=None):
            m._ensure()
        self.assertNotEqual(m.session_state()["state"], "expired")

    def test_signing_in_again_clears_it(self):
        m = _manager()
        m._expired = True
        with mock.patch.object(cm, "try_saved_cookies", return_value=_Api()):
            self.assertTrue(m._ensure())
        self.assertEqual(m.session_state()["state"], "connected")
        self.assertIsNotNone(m.session_state()["verifiedAt"])
        # "Connected" outranks "expired", so the state alone cannot show a flag
        # left set - and it would come back the next time the session dropped
        # for any other reason.
        self.assertFalse(m._expired)
        m.api = None
        self.assertEqual(m.session_state()["state"], "none")

    def test_forgetting_the_login_is_not_expiry(self):
        """A deliberate sign-out is not a fault, and the header must not nag."""
        m = _manager()
        m._expired = True
        with mock.patch.object(cm, "clear_saved_cookies", return_value=True):
            m.forget_login()
        self.assertEqual(m.session_state()["state"], "none")


class TheOneThatAsks(_Quiet):

    def test_a_good_session_is_confirmed_and_stamped(self):
        m = _manager()
        m.api = _Api()
        out = m.session_check()
        self.assertEqual(out["state"], "connected")
        self.assertEqual(m.api.checks, 1)
        self.assertIsNotNone(out["verifiedAt"])

    def test_a_session_ekahau_refuses_is_dropped_and_reported_expired(self):
        m = _manager()
        m.api = _Api(ok=False, refused=True)
        with mock.patch.object(cm, "try_saved_cookies", return_value=None), \
                mock.patch.object(cm, "try_browser_cookies", return_value=None):
            out = m.session_check()
        self.assertEqual(out["state"], "expired")
        self.assertIsNone(m.api)

    def test_a_refused_session_is_replaced_if_the_browser_has_a_fresh_one(self):
        """The log-back-in path: the browser signs in, the next check finds it."""
        m = _manager()
        m.api = _Api(ok=False, refused=True)
        fresh = _Api(email="someone@example.com")
        with mock.patch.object(cm, "try_saved_cookies", return_value=None), \
                mock.patch.object(cm, "try_browser_cookies", return_value=fresh):
            out = m.session_check()
        self.assertEqual((out["state"], out["email"]), ("connected", "someone@example.com"))

    def test_a_network_that_is_down_keeps_the_session_and_says_so(self):
        m = _manager()
        m.api = _Api(ok=False, refused=False, failure="could not reach Ekahau Cloud")
        out = m.session_check()
        self.assertEqual(out["state"], "connected")
        self.assertTrue(out["unreachable"])
        self.assertIn("could not reach", out["detail"])
        self.assertIsNotNone(m.api)

    def test_with_no_session_it_looks_and_says_what_it_found(self):
        m = _manager()
        with mock.patch.object(cm, "try_saved_cookies", return_value=None), \
                mock.patch.object(cm, "try_browser_cookies", return_value=None), \
                mock.patch.object(cm, "session_search_summary",
                                  return_value="Firefox: no Ekahau sign-in found"):
            out = m.session_check()
        self.assertEqual(out["state"], "none")
        self.assertEqual(out["detail"], "Firefox: no Ekahau sign-in found")


class TheRoutes(_Quiet):
    """`session` and `session_check` through the real dispatcher, with the
    header every state-changing call needs."""

    def setUp(self):
        super().setUp()
        self.client = server.app.test_client()
        self.m = _manager()
        patch = mock.patch.object(server, "cm", self.m)
        patch.start()
        self.addCleanup(patch.stop)

    def post(self, action):
        return self.client.post("/api/cloud/" + action, json={},
                                headers={"X-WD-Wireless-Tools": "1"}).get_json()

    def test_session_answers_from_memory_and_never_asks_ekahau(self):
        self.m.api = _Api()
        with mock.patch.object(requests.Session, "get",
                               side_effect=AssertionError("contacted Ekahau")):
            got = self.post("session")
        self.assertEqual(got["state"], "connected")
        self.assertEqual(self.m.api.checks, 0)

    def test_session_check_asks_ekahau_exactly_once(self):
        self.m.api = _Api()
        got = self.post("session_check")
        self.assertEqual(got["state"], "connected")
        self.assertEqual(self.m.api.checks, 1)

    def test_session_names_an_expired_one(self):
        self.m._expired = True
        self.assertEqual(self.post("session")["state"], "expired")


if __name__ == "__main__":
    unittest.main()
