"""A stale sign-in is removed, and only a stale one.

Two stores can hold a dead Ekahau session and each needed a different answer:

* **The tool's own saved session.** Ekahau answers a dead one with a login
  redirect or a 401. It was kept, so every start and every poll tried it first
  and was refused again until something happened to replace it. It is now
  deleted - but only on that answer. A network that is not up yet (a machine
  just woken from sleep), a timeout or a 5xx say nothing about the cookie, and
  a good session lost to a bad connection would be worse than the problem.
* **The browser's cookies.** Those belong to the browser, in a database it has
  open: rewriting it from here risks the profile for the sake of a cookie that
  logging in again replaces anyway. So nothing is deleted there. What changes
  is which cookies are *used*: expired rows are ignored, and where an old and a
  new AccessToken sit side by side the one that lasts longest is sent. A
  browser that holds only an expired token says so.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

from tools import cloud_manager as cm


class _Cookie:
    def __init__(self, name, value, expires=None, domain=".ekahau.cloud", path="/"):
        self.name, self.value, self.domain, self.path = name, value, domain, path
        self.expires = expires


class _Recorder:
    """Stands in for EkahauAPI: remembers which cookies it was built from, and
    accepts the session only if its AccessToken is the current one."""
    built = []

    def __init__(self, cookies, csrf):
        self.cookies, self.csrf = cookies, csrf
        self.failure, self.refused = "", False
        _Recorder.built.append(cookies)

    def test_connection(self):
        tokens = [c["value"] for c in self.cookies if c["name"] == "AccessToken"]
        if tokens == ["current"]:
            return True
        self.failure, self.refused = "Ekahau did not accept the sign-in it was given", True
        return False


def _reader(jar):
    reader = mock.Mock()
    for browser in ("chrome", "edge", "opera"):
        getattr(reader, browser).side_effect = FileNotFoundError("x")
    reader.firefox.return_value = jar
    reader.Firefox.side_effect = OSError("no log in this test")
    return reader


class WhichBrowserCookiesAreUsed(unittest.TestCase):

    def setUp(self):
        cm._saved_session_note = ""
        _Recorder.built = []
        far = time.time() + 86400
        self.far = far
        patches = [mock.patch.object(cm, "EkahauAPI", _Recorder),
                   mock.patch.object(cm, "save_cookies_to_disk")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _find(self, jar):
        with mock.patch.object(cm, "browser_cookie3", _reader(jar)):
            return cm.try_browser_cookies()

    def test_an_old_token_beside_the_current_one_is_not_the_one_sent(self):
        jar = [_Cookie("AccessToken", "old", self.far - 3000, domain="www.ekahau.cloud"),
               _Cookie("AccessToken", "current", self.far, domain=".ekahau.cloud"),
               _Cookie("CSRF-Token", "csrf", self.far)]
        api = self._find(jar)
        self.assertIsNotNone(api, cm.session_search_summary())
        sent = [c["value"] for c in _Recorder.built[0] if c["name"] == "AccessToken"]
        self.assertEqual(sent, ["current"])

    def test_it_does_not_matter_which_one_the_jar_lists_first(self):
        jar = [_Cookie("AccessToken", "current", self.far),
               _Cookie("AccessToken", "old", self.far - 3000, domain="www.ekahau.cloud"),
               _Cookie("CSRF-Token", "csrf", self.far)]
        self.assertIsNotNone(self._find(jar), cm.session_search_summary())

    def test_a_session_cookie_beats_a_dated_one(self):
        """No expiry means the browser holds it live right now."""
        jar = [_Cookie("AccessToken", "old", self.far),
               _Cookie("AccessToken", "current", None, domain="www.ekahau.cloud"),
               _Cookie("CSRF-Token", "csrf", None)]
        self.assertIsNotNone(self._find(jar), cm.session_search_summary())

    def test_a_stale_csrf_token_is_not_the_one_paired_with_the_session(self):
        jar = [_Cookie("AccessToken", "current", self.far),
               _Cookie("CSRF-Token", "stale", self.far - 3000, domain="www.ekahau.cloud"),
               _Cookie("CSRF-Token", "fresh", self.far)]
        self._find(jar)
        saved_csrf = cm.save_cookies_to_disk.call_args[0][1]
        self.assertEqual(saved_csrf, "fresh")

    def test_only_an_expired_token_is_called_expired_not_missing(self):
        jar = [_Cookie("AccessToken", "old", time.time() - 60),
               _Cookie("CSRF-Token", "csrf", self.far)]
        self.assertIsNone(self._find(jar))
        self.assertIn("Firefox: its Ekahau sign-in has expired", cm.session_search_summary())
        self.assertEqual(_Recorder.built, [], "an expired token was sent to Ekahau")
        self.assertNotIn("no Ekahau sign-in found", cm.session_search_summary())

    def test_no_token_at_all_is_still_called_missing(self):
        self.assertIsNone(self._find([_Cookie("Other", "x", self.far)]))
        self.assertIn("Firefox: no Ekahau sign-in found", cm.session_search_summary())

    def test_what_is_saved_for_next_time_holds_no_expired_row(self):
        jar = [_Cookie("AccessToken", "current", self.far),
               _Cookie("CSRF-Token", "csrf", self.far),
               _Cookie("Stale", "x", time.time() - 60)]
        self._find(jar)
        saved = cm.save_cookies_to_disk.call_args[0][0]
        self.assertEqual(sorted(c["name"] for c in saved), ["AccessToken", "CSRF-Token"])


class TheSavedSessionIsRemovedOnlyWhenRefused(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="wd-test-stale-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.enc = self.dir / "cookies.enc"
        self.legacy = self.dir / "cookies.json"
        self.enc.write_bytes(b"not a real credential")
        cm._saved_session_note = ""
        for p in (mock.patch.object(cm, "ENCRYPTED_COOKIE_FILE", self.enc),
                  mock.patch.object(cm, "COOKIE_FILE", self.legacy),
                  mock.patch.object(cm, "load_cookies_from_disk",
                                    return_value=([{"name": "AccessToken", "value": "v"}], "c"))):
            p.start()
            self.addCleanup(p.stop)

    def _try(self, answer):
        """`answer` is a status code, or an exception for a call that never
        got one."""
        def fake_get(self_, *a, **k):
            if isinstance(answer, Exception):
                raise answer
            r = requests.Response()
            r.status_code = answer
            return r
        with mock.patch.object(requests.Session, "get", fake_get):
            return cm.try_saved_cookies()

    def test_a_login_redirect_removes_it(self):
        self.assertIsNone(self._try(302))
        self.assertFalse(self.enc.exists())
        self.assertIn("so it was removed", cm._saved_session_note)

    def test_a_401_removes_it(self):
        self.assertIsNone(self._try(401))
        self.assertFalse(self.enc.exists())

    def test_the_legacy_file_goes_with_it(self):
        self.legacy.write_text("{}", encoding="utf-8")
        self._try(302)
        self.assertFalse(self.legacy.exists())

    def test_a_network_that_is_not_up_keeps_it(self):
        """The case the whole rule exists around: waking from sleep."""
        self.assertIsNone(self._try(requests.exceptions.ConnectionError("down")))
        self.assertTrue(self.enc.exists(), "a good session was deleted over a dead network")
        self.assertIn("network", cm._saved_session_note)
        self.assertNotIn("removed", cm._saved_session_note)

    def test_a_timeout_keeps_it(self):
        self._try(requests.exceptions.ReadTimeout("slow"))
        self.assertTrue(self.enc.exists())

    def test_a_server_error_keeps_it(self):
        self._try(503)
        self.assertTrue(self.enc.exists())

    def test_a_403_keeps_it(self):
        """Forbidden is not "signed out": it may be a permission, and the
        cookie is the same one a 200 would have accepted."""
        self._try(403)
        self.assertTrue(self.enc.exists())

    def test_a_session_that_works_is_left_and_clears_the_note(self):
        cm._saved_session_note = "Saved sign-in: something old"
        r = requests.Response()
        r.status_code = 200
        r._content = b"[]"
        with mock.patch.object(requests.Session, "get", lambda *a, **k: r):
            self.assertIsNotNone(cm.try_saved_cookies())
        self.assertTrue(self.enc.exists())
        self.assertEqual(cm._saved_session_note, "")

    def test_a_newer_session_saved_meanwhile_is_not_the_one_removed(self):
        """A poll and a second tab can both be here. If the browser sign-in
        was saved while this one was being refused, that file is the new
        session and must survive."""
        def fake_get(self_, *a, **k):
            self.enc.write_bytes(b"a newer session, written by another thread")
            r = requests.Response()
            r.status_code = 302
            return r
        with mock.patch.object(requests.Session, "get", fake_get):
            self.assertIsNone(cm.try_saved_cookies())
        self.assertTrue(self.enc.exists())
        self.assertEqual(self.enc.read_bytes(), b"a newer session, written by another thread")

    def test_the_status_says_what_happened(self):
        """Through the real chain: status -> saved session refused -> browsers
        have nothing -> the screen is told the saved one is gone."""
        def refuse(self_, *a, **k):
            r = requests.Response()
            r.status_code = 302
            return r
        m = cm.CloudManager.__new__(cm.CloudManager)
        m.config, m.api = {"output_dir": ""}, None
        with mock.patch.object(requests.Session, "get", refuse), \
                mock.patch.object(cm, "browser_cookie3", _reader([])):
            out = m.status()
        self.assertFalse(out["connected"])
        self.assertTrue(out["detail"].startswith(
            "Saved sign-in: Ekahau no longer accepts it, so it was removed"), out["detail"])
        self.assertFalse(self.enc.exists())


class DiscardSavedSessionOnItsOwn(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="wd-test-discard-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.enc, self.legacy = self.dir / "cookies.enc", self.dir / "cookies.json"
        for p in (mock.patch.object(cm, "ENCRYPTED_COOKIE_FILE", self.enc),
                  mock.patch.object(cm, "COOKIE_FILE", self.legacy)):
            p.start()
            self.addCleanup(p.stop)

    def test_it_removes_both_files_and_says_none_is_left(self):
        self.enc.write_bytes(b"x")
        self.legacy.write_text("{}", encoding="utf-8")
        self.assertTrue(cm.discard_saved_session())
        self.assertFalse(self.enc.exists() or self.legacy.exists())

    def test_nothing_to_remove_is_not_a_failure(self):
        self.assertTrue(cm.discard_saved_session())

    def test_a_changed_stamp_leaves_the_files_alone(self):
        self.enc.write_bytes(b"first")
        stamp = cm._saved_session_stamp()
        self.enc.write_bytes(b"replaced by something longer")
        self.assertFalse(cm.discard_saved_session(only_if_stamp=stamp))
        self.assertTrue(self.enc.exists())

    def test_the_same_stamp_removes_them(self):
        self.enc.write_bytes(b"first")
        self.assertTrue(cm.discard_saved_session(only_if_stamp=cm._saved_session_stamp()))
        self.assertFalse(self.enc.exists())

    def test_the_stamp_holds_sizes_and_times_never_contents(self):
        self.enc.write_bytes(b"a-secret-token-value")
        self.assertNotIn("a-secret-token-value", repr(cm._saved_session_stamp()))


if __name__ == "__main__":
    unittest.main()
