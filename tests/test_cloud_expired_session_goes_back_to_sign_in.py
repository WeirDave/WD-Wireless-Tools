"""An expired Ekahau Cloud session is a sign-in problem, not a wrong address.

What he was shown, over an empty list:

    401 Client Error: Unauthorized for url:
    https://www.ekahau.cloud/site-management-api/v1/sites

which reads as though the tool is calling the wrong URL. It is not. A 401 is
Ekahau's server answering and refusing the saved AccessToken cookie - the
session had expired. Three things were wrong around that:

* `_handle_api_error` recognised a dead session only as a redirect loop, so a
  401 went out as `raise_for_status()`'s own text;
* `self.api` was kept, so every retry - and Live retries every 30 seconds -
  replayed the same dead cookie until the app was restarted;
* the page drew an empty list under the toast, with nothing on it that would
  reconnect.

Both halves are driven here: the real `EkahauAPI.get` against a stubbed 401,
and the real `onData` / `onDuplicates` against a stubbed page.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import requests

from tools import cloud_manager as cm

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120


def _response(status):
    r = requests.Response()
    r.status_code = status
    r.reason = {401: "Unauthorized", 500: "Internal Server Error"}[status]
    r.url = cm.EKAHAU_URL + "/site-management-api/v1/sites"
    r._content = b""
    return r


def _manager_whose_api_answers(status):
    m = cm.CloudManager.__new__(cm.CloudManager)
    m.config = {"output_dir": ""}
    m.api = cm.EkahauAPI([], "csrf")
    m.api.http.get = mock.Mock(return_value=_response(status))
    return m


class ADeadSessionIsSaidAsOne(unittest.TestCase):

    def test_a_401_on_the_listing_is_reported_as_an_expired_sign_in(self):
        m = _manager_whose_api_answers(401)
        out = m.get_data("sites")
        self.assertTrue(out.get("sessionExpired"), out)
        self.assertEqual(out["error"], cm.CloudManager.SESSION_EXPIRED)
        self.assertNotIn("Client Error", out["error"])
        self.assertNotIn("url:", out["error"])

    def test_the_dead_session_is_dropped_so_the_next_call_revalidates(self):
        m = _manager_whose_api_answers(401)
        m.get_data("sites")
        self.assertIsNone(m.api)
        with mock.patch.object(cm, "try_saved_cookies", return_value=None) as saved, \
             mock.patch.object(cm, "try_browser_cookies", return_value=None):
            again = m.get_data("sites")
        saved.assert_called_once()
        self.assertTrue(again.get("sessionExpired"), again)

    def test_the_duplicates_listing_says_the_same_once_it_is_dropped(self):
        """`build_duplicates_data` treats each read as best-effort and does
        not raise, so it meets the dead session here: after the main listing
        has dropped it and nothing can revalidate."""
        m = _manager_whose_api_answers(401)
        m.get_data("sites")
        with mock.patch.object(cm, "try_saved_cookies", return_value=None), \
             mock.patch.object(cm, "try_browser_cookies", return_value=None):
            out = m.get_duplicates()
        self.assertTrue(out.get("sessionExpired"), out)

    def test_a_redirect_loop_is_still_an_expired_session(self):
        m = _manager_whose_api_answers(401)
        m.api.http.get = mock.Mock(
            side_effect=requests.exceptions.TooManyRedirects("Exceeded 30 redirects."))
        out = m.get_data("sites")
        self.assertTrue(out.get("sessionExpired"), out)

    def test_a_server_fault_is_not_mistaken_for_one(self):
        """A 500 says nothing about the cookie. Throwing him back to sign-in
        for it would be the guard firing on a case that is not his."""
        m = _manager_whose_api_answers(500)
        out = m.get_data("sites")
        self.assertNotIn("sessionExpired", out)
        self.assertIn("500", out["error"])
        self.assertIsNotNone(m.api)


HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function fn(head) {
  const a = src.indexOf(head);
  if (a < 0) throw new Error('moved: ' + head);
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
const el = {};
function node(id) { return el[id] || (el[id] = { id, style: {}, hidden: false, innerHTML: '' }); }
globalThis.document = { getElementById: node, querySelector: () => null,
                        querySelectorAll: () => [] };
const said = [], auth = [];
let stopped = 0;
function toast(m, kind) { said.push([String(m), kind]); }
function stopLive() { stopped++; }
function stopLoginPoll() {}
function setAuthState(s) { auth.push(s); }
function e(s) { return String(s); }
let data = { matched: [1] }, dupData = { x: 1 }, currentTab = 'sites';
let _drawnData = { matched: [1] }, _drawnFingerprint = 'fp', _lastPollError = '';
node('appScreen').style.display = 'flex';
node('loginScreen').style.display = 'none';
eval(fn('function backToSignIn(msg) {'));
eval(fn('function onData(kind, jsonStr, opts) {'));
eval(fn('function onDuplicates(kind, jsonStr) {'));
"""


def run(body):
    r = subprocess.run(["node", "-e", HARNESS + body, str(CLOUD_JS)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


REPORT = r"""
console.log(JSON.stringify({
  app: node('appScreen').style.display, login: node('loginScreen').style.display,
  auth, said, stopped, data, dupData, drawn: _drawnData,
  rows: node('rowsContainer').innerHTML,
}));
"""

EXPIRED = json.dumps({"error": cm.CloudManager.SESSION_EXPIRED, "sessionExpired": True})


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePageGoesBackToSignIn(unittest.TestCase):

    def test_an_expired_listing_shows_the_sign_in_screen(self):
        out = run(f"onData('sites', {json.dumps(EXPIRED)});" + REPORT)
        self.assertEqual(out["app"], "none")
        self.assertEqual(out["login"], "")
        self.assertEqual(out["auth"], ["login"])
        self.assertEqual(out["stopped"], 1, "Live must stop polling a dead session")
        self.assertIsNone(out["data"])
        self.assertIsNone(out["drawn"])
        self.assertEqual(out["said"], [[cm.CloudManager.SESSION_EXPIRED, "error"]])

    def test_a_background_poll_that_finds_it_expired_does_the_same(self):
        out = run(f"onData('sites', {json.dumps(EXPIRED)}, {{ background: true }});" + REPORT)
        self.assertEqual(out["login"], "")
        self.assertEqual(out["stopped"], 1)

    def test_the_duplicates_listing_does_the_same(self):
        out = run(f"onDuplicates('sites', {json.dumps(EXPIRED)});" + REPORT)
        self.assertEqual(out["app"], "none")
        self.assertEqual(out["auth"], ["login"])

    def test_any_other_failure_leaves_him_where_he_is(self):
        other = json.dumps({"error": "Ekahau is rate-limiting"})
        out = run(f"onData('sites', {json.dumps(other)});" + REPORT)
        self.assertEqual(out["app"], "flex")
        self.assertEqual(out["auth"], [])
        self.assertEqual(out["stopped"], 0)


class EveryPlaceNamesTheAddressTheCodeUses(unittest.TestCase):
    """README, SECURITY.md and the manual told him to sign in at
    the `.com` address - `cloud.` plus the company domain. The code reads
    cookies for `.ekahau.cloud` and calls
    `www.ekahau.cloud`, so a sign-in on the documented host is one Cloud
    Manager can never pick up. Every Ekahau host named anywhere must be the
    one `EKAHAU_URL` points at."""

    def test_no_other_ekahau_host_is_named(self):
        import re
        from urllib.parse import urlparse
        host = urlparse(cm.EKAHAU_URL).hostname
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                               text=True, encoding="utf-8", check=True).stdout.split()
        pat = re.compile(r"\b(?:[a-z0-9-]+\.)*ekahau\.(?:com|cloud)\b", re.I)
        wrong = []
        for rel in files:
            if rel.startswith("docs/releases/") or not rel.endswith(
                    (".md", ".html", ".js", ".py")):
                continue
            text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
            for m in pat.finditer(text):
                h = m.group(0).lower()
                if h not in (host, "ekahau.cloud", ".ekahau.cloud") and \
                        h not in ("www.ekahau.com", "ekahau.com"):
                    wrong.append(f"{rel}: {h}")
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
