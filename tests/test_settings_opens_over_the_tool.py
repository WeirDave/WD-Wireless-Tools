"""Changing a setting must not cost him the work in front of him.

"When you go to Report and you go to run the report and then you realise you
want to change some defaults, it takes you to the Settings screen but it doesn't
allow you to go back."

Measured before this existed, on the Antenna Aim Sheet with a project open and
the Configure step filled in: clicking through to Settings and pressing Back
landed on the **drop zone**. The `.esx` was gone, because a dropped file lives
in the page's memory and navigating away unloads it, and the configure step went
with it. The cost of changing one default was opening the project again.

That was survivable while nearly every setting had a control on its own tool.
v2.149.0 - v2.152.0 moved sixteen of them onto the Settings page, which turned
every one into a reason to leave the tool - so consolidating the settings made
this worse rather than better, and the return path had to stop being the Back
button.

Settings open in a panel over the tool now. Nothing is unloaded, so there is
nothing to restore.

What is held here:

  * the tool page does not navigate - the panel is an iframe and the page
    behind it stays loaded;
  * every "Suite Settings" link in every menu goes through it, not just the
    three that Cloud Manager, Report and Quick Walls added;
  * the User Guide too, which is the same shape - consulted mid-task, not
    departed for;
  * the tool re-reads its settings when the panel closes, or the panel is
    worse than the navigation it replaced: he changes the units, comes back,
    and the report still renders in the old one;
  * `/settings` and `/manual` are the only documents the server will let be
    framed, only by this origin, and they keep every other directive of the
    strict policy.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SHARED_JS = WEB / "assets" / "js" / "wd-shared.js"
SETTINGS_JS = WEB / "assets" / "js" / "settings-page.js"
NODE_TIMEOUT_S = 120

BRACE_SLICE = """
        let b = a, depth = 0, seen = false;
        while (b < src.length && !(seen && depth === 0)) {
          if (src[b] === '{') { depth++; seen = true; }
          else if (src[b] === '}') depth--;
          b++;
        }
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheLinkOpensAPanelInsteadOfNavigating(unittest.TestCase):
    """`wireSettingsLinks` run against a stubbed document, with the click it
    installs fired at real anchors. A link that still navigates is the defect,
    and the only way to see it is to click one."""

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  WD.wireSettingsLinks = function (root) {');
        if (a < 0) throw new Error('wireSettingsLinks moved');
""" + BRACE_SLICE + r"""
        const href = process.argv[2];
        const opts = JSON.parse(process.argv[3]);

        const opened = [];
        const anchor = {
          getAttribute: (k) => (k === 'href' ? href : null),
          target: opts.target || '',
          closest: function () { return this; },
        };
        let defaultPrevented = false;
        const ev = {
          target: anchor,
          button: opts.button || 0,
          metaKey: !!opts.meta, ctrlKey: !!opts.ctrl, shiftKey: !!opts.shift,
          preventDefault: () => { defaultPrevented = true; },
        };
        let handler = null;
        const PANELLED = { '/settings': 'Suite Settings', '/manual': 'User Guide' };
        const WD = {
          openPanel: (p, s) => opened.push(p + '|' + s),
          esc: (s) => String(s), escAttr: (s) => String(s),
        };
        global.window = { top: 1, self: 1, location: { pathname: opts.on || '/report' } };
        global.document = { addEventListener: (t, fn) => { if (t === 'click') handler = fn; } };
        eval(src.slice(a, b));
        WD.wireSettingsLinks();
        if (handler) handler(ev);
        console.log(JSON.stringify({ opened: opened, prevented: defaultPrevented,
                                     wired: handler !== null }));
    """

    def click(self, href, **opts):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(SHARED_JS), href, json.dumps(opts)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_settings_link_opens_the_panel_and_does_not_navigate(self):
        got = self.click("/settings#report")
        self.assertTrue(got["prevented"],
                        "the link still navigates, so the project is unloaded")
        self.assertEqual(got["opened"], ["/settings|report"])

    def test_a_plain_settings_link_opens_the_panel_too(self):
        """Thirteen of the twenty-three are the bare `/settings` in a menu.
        Handling only the ones with a section would leave most of them."""
        got = self.click("/settings")
        self.assertTrue(got["prevented"])
        self.assertEqual(got["opened"], ["/settings|"])

    def test_the_user_guide_opens_the_panel(self):
        got = self.click("/manual#report")
        self.assertTrue(got["prevented"])
        self.assertEqual(got["opened"], ["/manual|report"])

    def test_a_link_to_another_tool_is_left_alone(self):
        """Going to Quick Walls from Report is a departure, not a detour.
        Swallowing it would trap him in a panel over the wrong tool."""
        for href in ("/walls", "/cloud", "/", "/settingsomething"):
            with self.subTest(href=href):
                got = self.click(href)
                self.assertFalse(got["prevented"], href + " was intercepted")
                self.assertEqual(got["opened"], [])

    def test_a_new_tab_click_still_opens_a_new_tab(self):
        """Ctrl-click and middle-click are how someone keeps both open, and
        preventDefault would silently take that away."""
        for opts in ({"ctrl": True}, {"meta": True}, {"shift": True},
                     {"button": 1}, {"target": "_blank"}):
            with self.subTest(**opts):
                got = self.click("/settings#report", **opts)
                self.assertFalse(got["prevented"])
                self.assertEqual(got["opened"], [])

    def test_nothing_is_wired_on_the_settings_page_itself(self):
        got = self.click("/settings", on="/settings")
        self.assertFalse(got["wired"],
                         "the Settings page would open a panel over itself")

    def test_nothing_is_wired_on_the_manual(self):
        self.assertFalse(self.click("/manual", on="/manual")["wired"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePanelIsAFrameOverThePage(unittest.TestCase):
    """The property that makes the whole thing work: the host page is never
    navigated, so its state cannot be lost."""

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  var PANELLED = {');
        const end = src.indexOf('  function _settingsEsc(e) {');
        if (a < 0 || end < 0) throw new Error('the panel moved');

        let navigated = null;
        const el = () => ({
          id: '', className: '', innerHTML: '',
          setAttribute() {}, appendChild() {},
          addEventListener() {},
          querySelector: () => ({ addEventListener() {}, focus() {} }),
          classList: { add() {}, remove() {} },
        });
        const body = el();
        const created = [];
        global.document = {
          getElementById: () => null,
          createElement: () => { const e = el(); created.push(e); return e; },
          body: body,
          addEventListener() {},
          removeEventListener() {},
        };
        global.window = {
          location: { get href() { return '/report'; },
                      set href(v) { navigated = v; },
                      pathname: '/report', origin: 'http://127.0.0.1' },
          addEventListener() {},
        };
        const WD = { esc: (s) => String(s), escAttr: (s) => String(s) };
        const SETTINGS_OVERLAY_ID = 'wdSettingsOverlay';
        let _settingsOnClose = null;
        const _settingsEsc = () => {};
        eval(src.slice(a, end));
        WD.openPanel(process.argv[2], process.argv[3]);
        console.log(JSON.stringify({
          navigated: navigated,
          html: created.length ? created[0].innerHTML : null,
        }));
    """

    def open_panel(self, path, section=""):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(SHARED_JS), path, section],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_opening_it_navigates_nowhere(self):
        got = self.open_panel("/settings", "report")
        self.assertIsNone(
            got["navigated"],
            "the page was navigated, which unloads the project - that is the "
            "defect this replaces, not the fix")

    def test_the_frame_points_at_the_section_asked_for(self):
        html = self.open_panel("/settings", "report")["html"]
        self.assertIn('src="/settings#report"', html)

    def test_the_guide_opens_at_its_chapter(self):
        html = self.open_panel("/manual", "quick-walls")["html"]
        self.assertIn('src="/manual#quick-walls"', html)

    def test_it_says_the_tool_is_still_there(self):
        """A dimmed background does not say that the work behind it survived,
        and that is the one thing he needs to know."""
        html = self.open_panel("/settings", "")["html"]
        self.assertIn("still open", html)

    def test_the_named_wrappers_open_the_panel_rather_than_navigate(self):
        """`WD.openSettings` is what Cloud Manager's gear calls and
        `WD.openManual` is there for the same reason. A wrapper that navigated
        would lose the session while every test above still passed, because
        they exercise `openPanel` directly."""
        for fn, path in (("openSettings", "/settings"), ("openManual", "/manual")):
            with self.subTest(fn=fn):
                got = self.call_wrapper(fn, "cloud")
                self.assertIsNone(got["navigated"], fn + " navigated the page")
                self.assertIn('src="' + path + '#cloud"', got["html"] or "")

    def call_wrapper(self, fn, section):
        r = subprocess.run(
            ["node", "-e", self.PROBE.replace(
                "WD.openPanel(process.argv[2], process.argv[3]);",
                "WD." + fn + "(process.argv[3]);"),
             str(SHARED_JS), "", section],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_page_that_is_not_pannellable_is_refused(self):
        """Framing is allowed for two documents; opening a panel at anything
        else would render an empty box and look like a broken tool."""
        self.assertIsNone(self.open_panel("/report", "")["html"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ClosingItRefreshesTheTool(unittest.TestCase):
    """Without this the panel is worse than the navigation: a reload at least
    picked the new value up."""

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  WD.closeSettings = function () {');
        if (a < 0) throw new Error('closeSettings moved');
""" + BRACE_SLICE + r"""
        const refreshed = [];
        const throwOnRefresh = process.argv[2] === 'throw';
        let _settingsOnClose = () => {
          refreshed.push('refresh');
          if (throwOnRefresh) throw new Error('the tool could not refresh');
        };
        const SETTINGS_OVERLAY_ID = 'wdSettingsOverlay';
        const _settingsEsc = () => {};
        let removed = false;
        const wrap = { parentNode: { removeChild: () => { removed = true; } } };
        global.document = {
          getElementById: () => wrap,
          removeEventListener() {},
          body: { classList: { remove() {} } },
        };
        const WD = {};
        eval(src.slice(a, b));
        let threw = false;
        try { WD.closeSettings(); } catch (e) { threw = true; }
        console.log(JSON.stringify({ refreshed: refreshed, removed: removed,
                                     threw: threw }));
    """

    def close(self, mode=""):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(SHARED_JS), mode],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_closing_asks_the_tool_to_re_read_its_settings(self):
        got = self.close()
        self.assertEqual(
            got["refreshed"], ["refresh"],
            "the tool keeps the values it read at load, so a setting changed "
            "in the panel does not take effect")

    def test_a_tool_that_cannot_refresh_still_gets_its_page_back(self):
        """The panel closing is the promise. A tool whose refresh throws must
        not be left with the overlay stuck over it."""
        got = self.close("throw")
        self.assertTrue(got["removed"], "the panel stayed open")
        self.assertFalse(got["threw"])


class OnlyTwoDocumentsMayBeFramed(unittest.TestCase):
    """Framing is off for everything by default and this narrows the exception
    twice: two documents, and only from this origin."""

    def _headers(self, path):
        probe = (
            "import json, sys\n"
            "sys.path.insert(0, %r)\n"
            "import server\n"
            "c = server.app.test_client()\n"
            "r = c.get(%r)\n"
            "print(json.dumps({'xfo': r.headers.get('X-Frame-Options'),\n"
            "                  'csp': r.headers.get('Content-Security-Policy')}))\n"
            % (str(ROOT), path))
        with tempfile.TemporaryDirectory(prefix="wd-frame-") as tmp:
            env = dict(os.environ)
            env["WD_USER_DIR"] = tmp
            env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            r = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                               text=True, cwd=str(ROOT), env=env, timeout=180)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_two_panelled_pages_allow_this_origin(self):
        for path in ("/settings", "/manual"):
            with self.subTest(path=path):
                h = self._headers(path)
                self.assertEqual(h["xfo"], "SAMEORIGIN")
                self.assertIn("frame-ancestors 'self'", h["csp"])

    def test_a_tool_page_is_still_refused(self):
        """Framing a tool would let one page drive another; only the two
        consulted pages need it."""
        for path in ("/report", "/cloud", "/walls", "/"):
            with self.subTest(path=path):
                h = self._headers(path)
                self.assertEqual(h["xfo"], "DENY", path + " became frameable")
                self.assertIn("frame-ancestors 'none'", h["csp"])

    def test_the_exception_keeps_every_other_strict_directive(self):
        """The first version of this replaced the whole header and dropped
        `default-src`, `script-src` and the rest - a framing change quietly
        undoing a hardening pass."""
        csp = self._headers("/settings")["csp"]
        for directive in ("default-src 'self'", "script-src 'self'",
                          "object-src 'none'", "base-uri 'none'",
                          "form-action 'none'"):
            with self.subTest(directive=directive):
                self.assertIn(directive, csp)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheFramedPageTellsTheToolItSaved(unittest.TestCase):
    """So a value takes effect without waiting for the panel to close."""

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  function announceSave() {');
        if (a < 0) throw new Error('announceSave moved');
""" + BRACE_SLICE + r"""
        const sent = [];
        const EMBEDDED = process.argv[2] === 'embedded';
        global.window = {
          parent: { postMessage: (m, o) => sent.push([m, o]) },
          location: { origin: 'http://127.0.0.1:8675' },
        };
        eval(src.slice(a, b));
        announceSave();
        console.log(JSON.stringify(sent));
    """

    def sent(self, mode):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(SETTINGS_JS), mode],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_save_inside_the_panel_is_announced_to_the_tool(self):
        sent = self.sent("embedded")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], {"wd": "settings-saved"})

    def test_it_is_addressed_to_this_origin_and_not_to_anyone(self):
        """`'*'` would post the message to whatever framed the page."""
        self.assertEqual(self.sent("embedded")[0][1], "http://127.0.0.1:8675")

    def test_the_settings_page_on_its_own_announces_nothing(self):
        self.assertEqual(self.sent("standalone"), [])


if __name__ == "__main__":
    unittest.main()
