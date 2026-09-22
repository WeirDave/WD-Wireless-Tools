"""The two halves of the dev gate, joined, against a real server.

`tests/test_the_dev_actions_that_write_need_the_server.py` holds the server
half and `tests/test_dev_toolbar_browser.py` holds the browser half with
`WD.api` stubbed. Neither covers the seam: **does the password box actually
unlock the server**, and does a writing action that comes back locked offer
the password rather than just failing?

That seam is where this kind of change goes wrong. A gate whose client half
works and whose server half works, with nothing joining them, is a toolbar
that asks for a password and then refuses everything - which is the
"control that exists is a control that works" rule, in its worst form,
because the control looks fine right up until it is needed.

`?dev=1` is the case worth the most here. It is his own way in, it is
deliberately not password-protected, and it tells the server nothing - so it
is the route where the first writing action is the first time anybody
notices. What should happen is one prompt, at that moment, with a sentence
saying why.

**This starts a real `server.py`, which CLAUDE.md warns against**, and it
follows the prescription in that warning rather than ignoring it: the tree is
copied to a scratch directory, `_open_browser` is neutralised there so no
Firefox window lands on his desktop, `WD_USER_DIR` points at a throwaway
folder, the port is unusual and found free at run time, and every cleanup -
the directory, the server process, the driver - is registered at the moment
the thing is created rather than left to a teardown that a raised SkipTest
would skip.

Nothing here knows the dev password. The gate is pointed at the digest of a
string this file invented, in the copied tree, the same seam
`WD.Dev._expectedHash` gives the browser tests. That the shipped constant is
the one WaxFrame uses is checked separately by comparing the two files.
"""
from __future__ import annotations

from tests import browsers as _browsers

import contextlib
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

BROWSERS = [
    ("firefox", _browsers.find("firefox")),
    ("chrome", _browsers.find("chrome")),
    ("edge", _browsers.find("edge")),
]

#: Invented here, and the copied tree's gate is pointed at its digest.
PASSPHRASE = "a-string-this-test-invented"
DIGEST = hashlib.sha256(PASSPHRASE.encode("utf-8")).hexdigest()

#: Deliberately not 8675, which is his own running instance, and not a
#: number another test file reaches for.
PORT_HINT = 8811


def _free_port(start):
    for port in range(start, start + 40):
        with contextlib.closing(socket.socket()) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise unittest.SkipTest("no free port near %d" % start)


def _driver(kind, binary):
    try:
        if kind == "firefox":
            opts = webdriver.FirefoxOptions()
            opts.binary_location = binary
            opts.add_argument("-headless")
            return webdriver.Firefox(options=opts)
        if kind == "chrome":
            opts = webdriver.ChromeOptions()
            opts.binary_location = binary
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            return webdriver.Chrome(options=opts)
        opts = webdriver.EdgeOptions()
        opts.binary_location = binary
        opts.add_argument("--headless=new")
        return webdriver.Edge(options=opts)
    except (WebDriverException, OSError):
        return None


class DevGateEndToEnd(unittest.TestCase):

    kind = None
    binary = None

    @classmethod
    def setUpClass(cls):
        if cls.kind is None:
            raise unittest.SkipTest("base class")
        if not HAVE_SELENIUM:
            raise unittest.SkipTest("selenium is not installed")
        if not Path(cls.binary).exists():
            raise unittest.SkipTest("%s is not installed here" % cls.kind)

        # Every cleanup registered where the thing is made. `tearDownClass`
        # does not run when `setUpClass` raises, and the lines below it can.
        cls.scratch = Path(tempfile.mkdtemp(prefix="wd-devgate-"))
        cls.addClassCleanup(shutil.rmtree, str(cls.scratch), ignore_errors=True)

        run = cls.scratch / "app"
        shutil.copytree(ROOT, run, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", "tests", "docs", "node_modules"))

        # Point the gate at a digest this file chose, so the plaintext is
        # in neither the repository nor this test.
        devjs = run / "web" / "assets" / "js" / "wd-dev.js"
        text = devjs.read_text(encoding="utf-8")
        start = text.index("DEV_PW_HASH =")
        end = text.index(";", start)
        devjs.write_text(
            text[:start] + "DEV_PW_HASH =\n    '%s'" % DIGEST + text[end:],
            encoding="utf-8")

        # `main()` spawns a browser window unconditionally and nobody closes
        # it - 307 Firefox processes holding 22.5 GB were measured after a
        # day of sessions doing exactly this.
        server_py = run / "server.py"
        source = server_py.read_text(encoding="utf-8")
        spawn = "    threading.Thread(target=_open_browser, daemon=True).start()"
        if spawn not in source:
            raise AssertionError(
                "server.main() no longer spawns _open_browser the way this "
                "test neutralises it - check before removing the guard")
        server_py.write_text(
            source.replace(spawn, "    pass  # suppressed for this test"),
            encoding="utf-8")

        cls.port = _free_port(PORT_HINT)
        env = dict(os.environ)
        env["WD_USER_DIR"] = str(cls.scratch / "userdir")
        env["PORT"] = str(cls.port)
        cls.proc = subprocess.Popen(
            [sys.executable, "server.py"], cwd=str(run), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        cls.addClassCleanup(cls._stop_server)

        cls._wait_for_server()

        # A throwaway user directory has never been set up, so every page
        # redirects to /setup the moment `WD.checkSetup()` answers - which
        # unloads the document underneath a script that is still running.
        # Marking it complete keeps the page still; it is a fresh directory
        # under `WD_USER_DIR` and nothing of his is involved.
        cls._post("settings/complete_setup", {"patch": {}}, cls.port)

        cls.driver = _driver(cls.kind, cls.binary)
        if cls.driver is None:
            raise unittest.SkipTest("%s would not start" % cls.kind)
        cls.addClassCleanup(_browsers.shut_down, cls.driver)

    @staticmethod
    def _post(action, body, port):
        request = urllib.request.Request(
            "http://127.0.0.1:%d/api/%s" % (port, action),
            data=json.dumps(body or {}).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-WD-Wireless-Tools": "1"},
            method="POST")
        with urllib.request.urlopen(request, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    @classmethod
    def _stop_server(cls):
        proc = getattr(cls, "proc", None)
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    @classmethod
    def _wait_for_server(cls, seconds=45):
        """Bounded, and loud when it does not come up.

        A stalled session looks exactly like a working one from outside,
        which makes the stall the worse outcome.
        """
        deadline = time.time() + seconds
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                raise unittest.SkipTest(
                    "server exited: " + (cls.proc.stdout.read() or "")[-400:])
            try:
                with socket.create_connection(("127.0.0.1", cls.port), 1):
                    return
            except OSError:
                time.sleep(0.4)
        raise AssertionError("the test server never came up")

    # ── talking to it ───────────────────────────────────────────

    def api(self, action, body=None):
        request = urllib.request.Request(
            "http://127.0.0.1:%d/api/%s" % (self.port, action),
            data=json.dumps(body or {}).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-WD-Wireless-Tools": "1"},
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def server_unlocked(self):
        return self.api("dev/state")[1]["unlocked"]

    def setUp(self):
        self.api("dev/lock")
        self.open_page("/settings")
        self.driver.execute_script(
            "try { localStorage.removeItem('wd_dev'); "
            "localStorage.removeItem('wd_dev_toolbar_pos'); } catch (e) {}")
        # Reloaded so the page starts from dev-mode-off, which is the state
        # every test here begins in.
        self.open_page("/settings")

    def open_page(self, path):
        self.driver.get("http://127.0.0.1:%d%s" % (self.port, path))
        # Wait for the page to settle rather than for a fixed time. The
        # toolbar mounts on DOMContentLoaded, and `WD.checkSetup()` can
        # still navigate away after that - a script that runs into a
        # navigation fails with "Document was unloaded", which reads as a
        # broken product and is a racing test.
        for _ in range(60):
            try:
                ready = self.driver.execute_script(
                    "return !!(window.WD && window.WD.Dev && window.WD.api)"
                    " && document.readyState === 'complete';")
            except Exception:
                ready = False          # mid-navigation; ask again
            if ready:
                break
            time.sleep(0.1)
        else:
            self.fail("the page never finished loading %s" % path)

        landed = self.driver.execute_script("return location.pathname;")
        self.assertNotEqual(
            "/setup", landed,
            "the page redirected to setup - the throwaway user directory was "
            "not marked complete, and every script here will race a "
            "navigation")

    def submit_password(self, value):
        self.driver.execute_script(
            "document.getElementById('devPwInput').value = arguments[0];", value)
        return self.driver.execute_async_script("""
          var done = arguments[arguments.length - 1];
          WD.Dev.submitDevPassword().then(function (r) { done(!!r); })
                                    .catch(function () { done(false); });
        """)

    def sweep(self):
        return self.driver.execute_async_script("""
          var done = arguments[arguments.length - 1];
          WD.api('dev/housekeeping_sweep', { paths: [] })
            .then(function (r) { done(r); })
            .catch(function (e) { done({ error: String(e) }); });
        """)

    # ── the seam ────────────────────────────────────────────────

    def test_the_password_box_unlocks_the_server_too(self):
        """The join. Either half alone is a gate that does not work."""
        self.assertFalse(self.server_unlocked(), "it did not start locked")
        self.assertTrue(self.submit_password(PASSPHRASE))
        self.assertTrue(self.server_unlocked(),
                        "the modal set the flag and told the server nothing")

    def test_a_wrong_password_unlocks_neither(self):
        self.assertFalse(self.submit_password("not the password"))
        self.assertFalse(self.server_unlocked())
        self.assertIsNone(self.driver.execute_script(
            "return localStorage.getItem('wd_dev');"))

    def test_the_toolbar_is_on_screen_afterwards(self):
        self.submit_password(PASSPHRASE)
        shown = self.driver.execute_script(
            "var t = document.getElementById('devToolbar');"
            "return !!t && !t.classList.contains('is-hidden');")
        self.assertTrue(shown, "dev mode is on and the strip is not there")

    def test_a_writing_action_works_after_the_modal(self):
        """His ordinary route in, end to end: nothing extra is asked for."""
        self.submit_password(PASSPHRASE)
        result = self.sweep()
        self.assertTrue(result.get("ok"), result)

    def test_leaving_dev_mode_locks_the_server_again(self):
        self.submit_password(PASSPHRASE)
        self.assertTrue(self.server_unlocked())
        self.driver.execute_script("WD.Dev.exitDevMode();")
        for _ in range(30):
            if not self.server_unlocked():
                return
            time.sleep(0.1)
        self.fail("exiting dev mode left the server unlocked")

    # ── the ?dev=1 route ────────────────────────────────────────

    def test_dev_1_leaves_the_writing_actions_locked(self):
        """It is his own way in and it tells the server nothing.

        That is correct - the point of `?dev=1` is to put the strip on
        screen without a password - and it means the first write is where
        the password gets asked for.
        """
        self.open_page("/settings?dev=1")
        self.assertFalse(self.server_unlocked())
        self.assertEqual("dev_locked", self.sweep().get("code"))

    def test_the_survey_still_runs_on_that_route(self):
        """The read is not behind the gate, on any route in."""
        self.open_page("/settings?dev=1")
        result = self.driver.execute_async_script("""
          var done = arguments[arguments.length - 1];
          WD.api('dev/housekeeping_survey', {})
            .then(function (r) { done(r); })
            .catch(function (e) { done({ error: String(e) }); });
        """)
        self.assertTrue(result.get("ok"), result)

    def test_a_locked_write_offers_the_password_rather_than_failing(self):
        """A control that refuses without saying how to proceed is a wall."""
        self.open_page("/settings?dev=1")
        state = self.driver.execute_script("""
          WD.Dev.unlockForWrites();
          var modal = document.getElementById('devModal');
          var note = document.getElementById('devPwNote');
          return { active: !!modal && modal.classList.contains('active'),
                   note: note ? note.textContent : '' };
        """)
        self.assertTrue(state["active"], "no password box was offered")
        self.assertIn("password", (state["note"] or "").lower(),
                      "the box appeared with no explanation of why")

    def test_answering_that_prompt_unlocks_without_touching_dev_mode(self):
        """It was asked for by an action, not to enter dev mode.

        The flag and the strip are already as he left them and must not
        move underneath him.
        """
        self.open_page("/settings?dev=1")
        before = self.driver.execute_script(
            "return localStorage.getItem('wd_dev');")
        unlocked = self.driver.execute_async_script("""
          var done = arguments[arguments.length - 1];
          WD.Dev.unlockForWrites().then(done);
          setTimeout(function () {
            document.getElementById('devPwInput').value = arguments[0];
            WD.Dev.submitDevPassword();
          }, 50);
        """.replace("arguments[0]", json.dumps(PASSPHRASE)))
        self.assertTrue(unlocked, "the password was accepted and not reported")
        self.assertTrue(self.server_unlocked())
        self.assertEqual(before, self.driver.execute_script(
            "return localStorage.getItem('wd_dev');"),
            "answering a write prompt changed whether dev mode is on")

    def test_cancelling_the_prompt_resolves_rather_than_hanging(self):
        """A promise nobody settles is a button that stays on 'Deleting…'."""
        self.open_page("/settings?dev=1")
        answer = self.driver.execute_async_script("""
          var done = arguments[arguments.length - 1];
          WD.Dev.unlockForWrites().then(done);
          setTimeout(function () { WD.Dev.dismissDevModal(); }, 50);
        """)
        self.assertFalse(answer)
        self.assertFalse(self.server_unlocked())

    # ── the guard in front of all of it ─────────────────────────

    def test_the_unlock_still_needs_the_local_api_header(self):
        """The gate is added to the cross-origin protection, not instead."""
        request = urllib.request.Request(
            "http://127.0.0.1:%d/api/dev/unlock" % self.port,
            data=json.dumps({"password": PASSPHRASE}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=20)
        self.assertEqual(403, caught.exception.code)
        self.assertFalse(self.server_unlocked())


def _case(kind, binary):
    return type("DevGateEndToEndIn" + kind.title(), (DevGateEndToEnd,),
                {"kind": kind, "binary": binary})


DevGateEndToEndInFirefox = _case(*BROWSERS[0])
DevGateEndToEndInChrome = _case(*BROWSERS[1])
DevGateEndToEndInEdge = _case(*BROWSERS[2])

del DevGateEndToEnd  # the base class is not a test case

if __name__ == "__main__":
    unittest.main()
