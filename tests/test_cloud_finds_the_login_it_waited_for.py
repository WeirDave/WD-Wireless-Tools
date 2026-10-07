"""Logging in through the browser has to be *found*, and when it is not, say why.

Reported: after an update, with the machine left idle, Cloud Manager showed the
sign-in screen; he chose "Log in to Ekahau Cloud", logged in, and the tool still
did not see it. It took three or four rounds before it did.

Three separate faults sat behind that, and each is held here:

* **Firefox's newest cookies were invisible.** `browser_cookie3` copies
  `cookies.sqlite` alone, and Firefox keeps that database in WAL mode, so the
  AccessToken written by the login just completed lives in `cookies.sqlite-wal`
  until a checkpoint. What the copy held was the old, expired token, which Ekahau
  refuses. `_firefox_cookies_including_wal` copies the log beside it.
* **The wait was an unguarded `setInterval`.** Overlapping checks (each reads
  four browsers' cookie files and tries each session against Ekahau), a second
  interval for every extra click, nothing to stop them, and every failure
  swallowed - "logged in, not found" looked exactly like "not logged in".
* **Nothing said why.** `status()` now carries a one-line reason per browser
  while signed out, and the waiting screen shows it.

The Firefox half is driven against a real SQLite database in WAL mode with the
real `browser_cookie3`; the page half runs the real functions from `cloud.js`
under Node against stubbed timers.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import requests

from tools import cloud_manager as cm

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CLOUD_HTML = ROOT / "web" / "cloud.html"
NODE_TIMEOUT_S = 120

try:
    import browser_cookie3 as real_bc3
except Exception:                                    # pragma: no cover
    real_bc3 = None


def _firefox_profile_with_a_login_in_the_log(directory):
    """A cookies.sqlite whose *main file* holds the expired AccessToken and
    whose `-wal` holds the fresh one. The returned connection is the "browser":
    it stays open, so SQLite cannot checkpoint the log away behind our back."""
    path = Path(directory) / "cookies.sqlite"
    con = sqlite3.connect(str(path))
    con.execute("pragma journal_mode=wal")
    con.execute("pragma wal_autocheckpoint=0")
    con.execute("create table moz_cookies (id integer primary key, host text, "
                "path text, isSecure integer, expiry integer, name text, "
                "value text, isHttpOnly integer)")
    far = 4102444800
    rows = [(".ekahau.cloud", "/", 1, far, "AccessToken", "expired-token", 1),
            (".ekahau.cloud", "/", 1, far, "CSRF-Token", "csrf-value", 0)]
    con.executemany("insert into moz_cookies (host, path, isSecure, expiry, "
                    "name, value, isHttpOnly) values (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.execute("pragma wal_checkpoint(full)")          # the old login is in the file
    con.execute("update moz_cookies set value='fresh-token' where name='AccessToken'")
    con.commit()                                        # the new one is only in the log
    return path, con


class _AcceptsOnlyTheFreshToken:
    """Stands in for Ekahau: a session is good if its AccessToken is the one
    written by the login he just completed."""
    def __init__(self, jar, csrf):
        self.token = next((c.value for c in jar if c.name == "AccessToken"), "")
        self.failure = ""

    def test_connection(self):
        if self.token == "fresh-token":
            return True
        self.failure = "Ekahau did not accept the sign-in it was given"
        return False


@unittest.skipIf(real_bc3 is None, "browser_cookie3 is not installed")
class FirefoxsFreshLoginIsReadFromItsLog(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wd-test-ff-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path, self.browser = _firefox_profile_with_a_login_in_the_log(self.dir)
        self.addCleanup(self.browser.close)
        path = self.path

        def broken(**_):
            raise RuntimeError("deliberate failure for the test")

        self.reader = types.SimpleNamespace(
            chrome=broken, edge=broken, opera=broken,
            firefox=lambda domain_name="": real_bc3.Firefox(
                cookie_file=str(path), domain_name=domain_name).load(),
            Firefox=lambda domain_name="": types.SimpleNamespace(cookie_file=str(path)),
            create_cookie=real_bc3.create_cookie)
        patches = [mock.patch.object(cm, "browser_cookie3", self.reader),
                   mock.patch.object(cm, "EkahauAPI", _AcceptsOnlyTheFreshToken),
                   mock.patch.object(cm, "save_cookies_to_disk")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_the_login_he_just_completed_is_the_session_that_is_found(self):
        api = cm.try_browser_cookies()
        self.assertIsNotNone(api, cm.session_search_summary())
        self.assertEqual(api.token, "fresh-token")

    def test_the_session_that_is_saved_is_the_fresh_one(self):
        cm.try_browser_cookies()
        cookies, csrf = cm.save_cookies_to_disk.call_args[0]
        tokens = [c["value"] for c in cookies if c["name"] == "AccessToken"]
        self.assertEqual(tokens, ["fresh-token"])
        self.assertEqual(csrf, "csrf-value")

    def test_a_log_that_cannot_be_read_still_leaves_the_ordinary_answer(self):
        self.reader.Firefox = mock.Mock(side_effect=OSError("deliberate"))
        self.assertIsNone(cm.try_browser_cookies())      # only the expired token
        self.assertIn("Firefox: Ekahau did not accept", cm.session_search_summary())


class WhenItIsNotFoundTheScreenCanSayWhy(unittest.TestCase):

    def setUp(self):
        cm._saved_session_note = ""

    def _manager(self):
        m = cm.CloudManager.__new__(cm.CloudManager)
        m.config = {"output_dir": ""}
        m.api = None
        return m

    @staticmethod
    def _jar(*names):
        jar = []
        for n in names:
            c = mock.Mock()
            c.name, c.value, c.domain, c.path = n, "v", ".ekahau.cloud", "/"
            jar.append(c)
        return jar

    def _reader(self, **by_browser):
        reader = mock.Mock()
        for browser in ("chrome", "firefox", "edge", "opera"):
            r = by_browser.get(browser, FileNotFoundError("x"))
            fn = getattr(reader, browser)
            if isinstance(r, Exception):
                fn.side_effect = r
            else:
                fn.return_value = r
        reader.Firefox.side_effect = OSError("no log in this test")
        return reader

    def test_each_browser_gets_its_own_reason_and_no_path_or_value(self):
        reader = self._reader(chrome=PermissionError("C:\\Users\\x\\Cookies"),
                              firefox=self._jar("Other"),
                              edge=self._jar("AccessToken"))
        with mock.patch.object(cm, "browser_cookie3", reader), \
             mock.patch.object(cm, "try_saved_cookies", return_value=None):
            m = self._manager()
            status = m.status()
        self.assertFalse(status["connected"])
        detail = status["detail"]
        self.assertIn("Chrome: its cookie file is locked", detail)
        self.assertIn("Firefox: no Ekahau sign-in found", detail)
        self.assertIn("Edge: sign-in found but no CSRF token", detail)
        self.assertNotIn("Users", detail)
        self.assertNotIn("Cookies", detail)

    def test_a_connected_status_carries_no_detail(self):
        m = self._manager()
        m.api = cm.EkahauAPI([], "csrf")
        self.assertEqual(m.status()["detail"], "")

    def test_a_network_that_is_not_up_is_not_called_a_bad_login(self):
        api = cm.EkahauAPI([], "csrf")
        api.http.get = mock.Mock(side_effect=requests.exceptions.ConnectionError("down"))
        self.assertFalse(api.test_connection())
        self.assertIn("network", api.failure)
        self.assertNotIn("did not accept", api.failure)

    def test_a_refused_cookie_is_called_that(self):
        api = cm.EkahauAPI([], "csrf")
        r = requests.Response()
        r.status_code = 302
        api.http.get = mock.Mock(return_value=r)
        self.assertFalse(api.test_connection())
        self.assertIn("did not accept", api.failure)

    def test_the_saved_login_is_named_when_it_is_the_one_that_failed(self):
        cm._saved_session_note = ""
        with mock.patch.object(cm, "load_cookies_from_disk",
                               return_value=([{"name": "AccessToken", "value": "v"}], "c")), \
             mock.patch.object(cm.EkahauAPI, "test_connection",
                               side_effect=lambda self: setattr(
                                   self, "failure", "could not reach Ekahau Cloud") or False,
                               autospec=True):
            self.assertIsNone(cm.try_saved_cookies())
        with mock.patch.object(cm, "browser_cookie3", self._reader()):
            self.assertIsNone(cm.try_browser_cookies())
        self.assertTrue(cm.session_search_summary().startswith(
            "Saved sign-in: could not reach Ekahau Cloud"))


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
function line(head) {
  const a = src.indexOf(head);
  if (a < 0) throw new Error('moved: ' + head);
  return src.slice(a, src.indexOf('\n', a)).replace(/^(const|let) /, 'var ');
}

/* Virtual time: nothing here waits, and a timer that is never set can never fire. */
let now = 1000000, nextId = 0, timers = [];
Date.now = () => now;
globalThis.setTimeout = (f, ms) => { const t = { f, at: now + ms, id: ++nextId }; timers.push(t); return t.id; };
globalThis.clearTimeout = (id) => { timers = timers.filter(t => t.id !== id); };
const tick = () => new Promise(r => setImmediate(r));
async function advance(ms) {
  const target = now + ms;
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    const t = timers[0];
    if (!t || t.at > target) break;
    timers.shift(); now = t.at; t.f();
    await tick();
  }
  now = target;
  await tick();
}

const el = {};
function node(id) { return el[id] || (el[id] = { id, style: {}, hidden: false, textContent: '' }); }
globalThis.document = { getElementById: node };
const said = [], auth = [], shown = [], calls = [];
let stopped = 0, statusReply = { connected: false, detail: '' }, statusPending = null, statusCalls = 0;
function toast(m, kind) { said.push([String(m), kind]); }
function stopLive() { stopped++; }
function setAuthState(s) { auth.push(s); }
function showApp(email) { shown.push(email); }
async function pyApi(method) {
  calls.push(method);
  if (method === 'get_status') {
    statusCalls++;
    if (statusPending) return statusPending;
    return statusReply;
  }
  return { ok: true };
}
let data = null, dupData = null, _drawnData = null, _drawnFingerprint = '';
eval(line('const LOGIN_POLL_MS'));
eval(line('const LOGIN_SAY_AFTER_MS'));
eval(line('const LOGIN_GIVE_UP_MS'));
eval(line('let _loginPoll'));
eval(fn('function stopLoginPoll() {'));
eval(fn('function _setLoginWaitDetail(text) {'));
eval(fn('async function _loginTick(poll) {'));
eval(fn('function checkLoginNow() {'));
eval(fn('function cancelLogin() {'));
eval(fn('async function openEkahauLogin() {'));
eval(fn('function backToSignIn(msg) {'));
node('appScreen'); node('loginScreen'); node('setupScreen');
"""


def run(body):
    r = subprocess.run(["node", "-e", HARNESS + "(async () => {" + body + "})()"
                        ".catch(e => { console.error(e); process.exit(1); });",
                        str(CLOUD_JS)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


REPORT = r"""
console.log(JSON.stringify({
  said, auth, shown, calls, stopped, statusCalls, timers: timers.length,
  detail: node('authWaitingDetail').textContent,
  detailHidden: node('authWaitingDetail').hidden,
}));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePageKeepsLookingUntilItFindsIt(unittest.TestCase):

    def test_it_connects_the_moment_a_check_sees_the_login(self):
        out = run("""
          await openEkahauLogin();
          await advance(2100);
          statusReply = { connected: true, email: 'someone@example.com' };
          await advance(10000);
        """ + REPORT)
        self.assertEqual(out["shown"], ["someone@example.com"])
        self.assertEqual(out["timers"], 0, "it kept polling after it had connected")
        self.assertEqual(out["statusCalls"], 2)

    def test_a_check_that_is_slow_is_never_joined_by_another(self):
        out = run("""
          let release;
          statusPending = new Promise(r => { release = r; });
          await openEkahauLogin();
          await advance(60000);
          const during = statusCalls;
          statusPending = null;
          release({ connected: false, detail: '' });
          await advance(500);
          globalThis.__during = during;
        """ + REPORT.replace("statusCalls,", "statusCalls, during: __during,"))
        self.assertEqual(out["during"], 1,
                         "a second check started while the first was running")

    def test_clicking_log_in_again_does_not_add_a_second_poll(self):
        out = run("""
          await openEkahauLogin();
          await openEkahauLogin();
          await openEkahauLogin();
          await advance(2100);
        """ + REPORT)
        self.assertEqual(out["statusCalls"], 1)
        self.assertEqual(out["timers"], 1)

    def test_a_tick_that_ends_after_the_poll_was_stopped_does_not_reschedule(self):
        out = run("""
          let release;
          statusPending = new Promise(r => { release = r; });
          await openEkahauLogin();
          await advance(2100);
          cancelLogin();
          release({ connected: false, detail: '' });
          await advance(30000);
        """ + REPORT)
        self.assertEqual(out["timers"], 0)
        self.assertEqual(out["statusCalls"], 1)

    def test_a_status_that_throws_is_retried_not_dropped(self):
        out = run("""
          await openEkahauLogin();
          statusPending = Promise.reject(new Error('x'));
          statusPending.catch(() => {});
          await advance(2100);
          statusPending = null;
          statusReply = { connected: true, email: 'a@example.com' };
          await advance(2100);
        """ + REPORT)
        self.assertEqual(out["shown"], ["a@example.com"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class WhileItWaitsTheScreenSaysWhatItFound(unittest.TestCase):

    def test_nothing_is_said_in_the_first_few_seconds(self):
        out = run("""
          statusReply = { connected: false, detail: 'Firefox: no Ekahau sign-in found' };
          await openEkahauLogin();
          await advance(8000);
        """ + REPORT)
        self.assertEqual(out["detail"], "")
        self.assertTrue(out["detailHidden"])

    def test_after_a_while_it_names_what_the_last_look_found(self):
        out = run("""
          statusReply = { connected: false, detail: 'Firefox: no Ekahau sign-in found' };
          await openEkahauLogin();
          await advance(20000);
        """ + REPORT)
        self.assertIn("Firefox: no Ekahau sign-in found", out["detail"])
        self.assertIn("Still checking", out["detail"])
        self.assertFalse(out["detailHidden"])

    def test_a_server_that_does_not_answer_says_that(self):
        out = run("""
          await openEkahauLogin();
          statusPending = Promise.reject(new Error('x'));
          statusPending.catch(() => {});
          await advance(20000);
        """ + REPORT)
        self.assertIn("did not answer", out["detail"])

    def test_it_gives_up_loudly_after_ten_minutes(self):
        out = run("""
          await openEkahauLogin();
          await advance(11 * 60 * 1000);
        """ + REPORT)
        self.assertEqual(out["auth"][-1], "login")
        self.assertEqual(out["timers"], 0)
        self.assertEqual(len(out["said"]), 1)
        self.assertEqual(out["said"][0][1], "error")
        self.assertIn("10 minutes", out["said"][0][0])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheWaitingScreenHasControlsThatWork(unittest.TestCase):

    def test_check_again_now_asks_at_once(self):
        out = run("""
          await openEkahauLogin();
          const before = statusCalls;
          statusReply = { connected: true, email: 'b@example.com' };
          checkLoginNow();
          await tick();
          globalThis.__before = before;
        """ + REPORT.replace("statusCalls,", "statusCalls, before: __before,"))
        self.assertEqual(out["before"], 0)
        self.assertEqual(out["shown"], ["b@example.com"])

    def test_coming_back_to_the_tab_during_a_check_does_not_start_another(self):
        """The window `focus` handler and the button both call
        `checkLoginNow`, and one of them lands while a check is running."""
        out = run("""
          let release;
          statusPending = new Promise(r => { release = r; });
          await openEkahauLogin();
          await advance(2100);
          checkLoginNow();
          checkLoginNow();
          await tick();
          globalThis.__mid = statusCalls;
          statusPending = null;
          release({ connected: false, detail: '' });
          await advance(2100);
        """ + REPORT.replace("statusCalls,", "statusCalls, mid: __mid,"))
        self.assertEqual(out["mid"], 1)
        self.assertEqual(out["timers"], 1, "the poll must carry on after the check ends")

    def test_back_stops_looking_and_returns_to_the_login_button(self):
        out = run("""
          await openEkahauLogin();
          cancelLogin();
          await advance(30000);
        """ + REPORT)
        self.assertEqual(out["auth"][-1], "login")
        self.assertEqual(out["statusCalls"], 0)
        self.assertEqual(out["timers"], 0)

    def test_going_back_to_sign_in_from_inside_the_app_stops_the_poll_too(self):
        out = run("""
          await openEkahauLogin();
          backToSignIn();
          await advance(30000);
        """ + REPORT)
        self.assertEqual(out["statusCalls"], 0)

    def test_every_control_on_the_waiting_screen_names_a_function_that_exists(self):
        html = CLOUD_HTML.read_text(encoding="utf-8")
        block = html[html.index('id="authWaiting"'):html.index('id="setupScreen"')]
        named = re.findall(r'data-fn="([A-Za-z_.]+)"', block)
        self.assertEqual(sorted(named), ["cancelLogin", "checkLoginNow"])
        out = run("console.log(JSON.stringify({ kinds: ["
                  + ",".join(f"typeof {n}" for n in named) + "] }));")
        self.assertEqual(out["kinds"], ["function"] * len(named))
        self.assertIn("Check again now", block)


if __name__ == "__main__":
    unittest.main()
