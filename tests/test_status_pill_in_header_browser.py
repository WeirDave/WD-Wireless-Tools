"""The status pill: one small pill in every page's header that says whether the
install is current and whether the Ekahau Cloud sign-in is good.

It began as an "update is waiting" pill that existed only while there was bad
news. It is now always there, so it can say "all clear" as well, and it carries
the Ekahau Cloud sign-in, which goes stale without any page noticing - clicking
it opens About, where the Ekahau Cloud card logs back in.

The probe loads real pages from the real server and clicks the real controls
with a real mouse. The update check is answered by a stubbed updater that
reports invented versions, and the Cloud side by a stand-in manager whose state
the test chooses - no test here can reach Ekahau or read a browser's cookies.
Nothing asserts that the source contains something: the pill has to be
visible, beside the toggle, taking no room from the page, saying the right
thing for each state, and the buttons have to do what they say.

The promise that matters most is last in the list and first in importance:
loading a page must not contact Ekahau.
"""
from __future__ import annotations

import time
import unittest
from unittest import mock

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

# Cloud Manager keeps its header on a screen that only exists once someone is
# signed in to Ekahau Cloud, which a test cannot be; it is shown here the way
# the page itself shows it (goToDashboard), and the pill must already be in it.
HEADER_PAGES = ("/", "/cloud", "/walls", "/report", "/scale", "/plantrim", "/aprename",
                "/capacity", "/prep", "/squirrel", "/rename", "/settings")
# No theme toggle to sit beside: a floating pill pinned to the top right.
FLOATING_PAGES = ("/manual",)
SHOW_CLOUD_HEADER = """
document.getElementById('loginScreen').style.display = 'none';
document.getElementById('appScreen').style.display = 'flex';
"""
CACHE_KEY = "wd-update-check"

INSTALL = {"method": "git", "isGitInstall": False, "isDevCheckout": False,
           "currentVersion": "9.0.0", "reason": "Invented install."}
NEWER = {"tag": "v9.0.9", "version": "9.0.9", "url": "https://example.invalid/r",
         "notes": "- An invented line."}
CURRENT = {"tag": "v9.0.0", "version": "9.0.0", "url": "https://example.invalid/r",
           "notes": ""}
INVENTED_EMAIL = "someone@example.com"

# Visible pills only: a page with a drop screen and a workspace keeps two
# headers, and the hidden one carries a hidden pill.
MEASURE = """
var r = function (e) { var b = e.getBoundingClientRect();
  return { l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height }; };
var shown = Array.prototype.filter.call(document.querySelectorAll('.wd-status-pill'),
  function (p) { return p.getClientRects().length > 0; });
var pill = shown[0] || null;
var toggle = pill ? pill.nextElementSibling : null;
var header = document.querySelector('.topbar, .dz-topbar');
var cloud = pill ? pill.querySelector('.wd-status-cloud') : null;
return {
  count: shown.length,
  pill: pill ? r(pill) : null,
  toggle: toggle && toggle.classList.contains('theme-toggle') ? r(toggle) : null,
  header: header ? r(header) : null,
  floating: pill ? pill.classList.contains('is-floating') : null,
  oldBar: document.querySelectorAll('.wd-update-banner, #wdUpdateBanner, #wdUpdateBadge, .wd-update-pill').length,
  text: pill ? pill.querySelector('.wd-status-label').textContent : null,
  tone: pill ? (pill.className.match(/is-(ok|attn|idle)/) || [])[1] : null,
  cloud: cloud ? (cloud.className.match(/is-(connected|saved|expired|none)/) || [])[1] : null,
  title: pill ? pill.title : null,
  scrollW: document.documentElement.scrollWidth, viewport: [innerWidth, innerHeight]
};
"""

SETTLED = ("return Array.prototype.some.call(document.querySelectorAll('.wd-status-pill'),"
           " function (p) { return p.getClientRects().length > 0 &&"
           " p.querySelector('.wd-status-label').textContent !== 'Checking…'; });")


class _Api:
    """Stands in for `EkahauAPI`, counting how often Ekahau would be asked."""

    def __init__(self, email=INVENTED_EMAIL):
        self.user_email, self.checks, self.refused, self.failure = email, 0, False, ""

    def test_connection(self):
        self.checks += 1
        return True


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheStatusPillSitsInTheHeader(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import server
        from tools import cloud_manager as cm_mod
        server.updater.detect_install.return_value = dict(INSTALL)
        server.updater.fetch_latest_release.return_value = dict(NEWER)
        cls._since = mock.patch.object(
            server.updater, "releases_since",
            return_value={"changes": [{"version": "9.0.9", "title": "Invented release",
                                       "notes": "## What changed\n- An invented line.",
                                       "url": ""}], "more": False})
        cls._since.start()
        # Nothing in this file may read a browser's cookies or reach Ekahau,
        # whatever page it loads: Cloud Manager's own start-up looks for both.
        cls._safety = [
            mock.patch.object(cm_mod, "try_saved_cookies", return_value=None),
            mock.patch.object(cm_mod, "try_browser_cookies", return_value=None),
            mock.patch.object(cm_mod, "_saved_session_stamp", return_value=()),
        ]
        for p in cls._safety:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._safety:
            p.stop()
        cls._since.stop()
        super().tearDownClass()

    # ── fixtures ───────────────────────────────────────────────────────────

    def manager(self, state="none"):
        """A Cloud Manager standing in the server's place, in `state`."""
        import server
        from tools import cloud_manager as cm_mod
        m = cm_mod.CloudManager.__new__(cm_mod.CloudManager)
        m.config, m.api = {"output_dir": ""}, None
        m.status = mock.Mock(return_value={"connected": False, "email": "",
                                           "outputDir": "", "detail": ""})
        if state == "connected":
            m.api = _Api()
        elif state == "expired":
            m._expired = True
        # Always set, never left to an earlier call: a test that walks through
        # several states must not carry "a sign-in is saved" into the next.
        patch = mock.patch.object(cm_mod, "_saved_session_stamp",
                                  return_value=(("a-file", 1, 1),) if state == "saved" else ())
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(server, "cm", m)
        patch.start()
        self.addCleanup(patch.stop)
        return m

    def release(self, which):
        import server
        server.updater.fetch_latest_release.return_value = dict(which)
        self.addCleanup(setattr, server.updater.fetch_latest_release,
                        "return_value", dict(NEWER))

    def load(self, drv, path):
        """The page, with no remembered answer, so its own check has to ask."""
        drv.get(self.base + "/")
        drv.execute_script("localStorage.removeItem(arguments[0]);", CACHE_KEY)
        drv.get(self.base + path)

    def pill_drawn(self, drv, path=None):
        if path == "/cloud":
            WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                "return document.querySelectorAll('.wd-status-pill').length > 0;"))
            drv.execute_script(SHOW_CLOUD_HEADER)
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(SETTLED))
        return drv.execute_script(MEASURE)

    def wait_for(self, drv, script, timeout=15):
        WebDriverWait(drv, timeout).until(lambda d: d.execute_script(script))

    def click_pill(self, drv):
        [p for p in drv.find_elements(By.CSS_SELECTOR, ".wd-status-pill")
         if p.is_displayed()][0].click()
        self.wait_for(drv, "return !!document.querySelector('#wdAboutModal.active');")

    def card(self, drv):
        return drv.execute_script(
            "var c = document.getElementById('wdAboutCloud');"
            "var q = function (s) { return c.querySelector(s); };"
            "var shown = function (e) { return !e.hidden && e.getClientRects().length > 0; };"
            "return {cls: c.className, state: q('.wd-about-cloudState').textContent,"
            " note: q('.wd-about-cloudNote').textContent,"
            " login: shown(q('.wd-about-cloudLogin')) ? q('.wd-about-cloudLogin').textContent : null,"
            " check: shown(q('.wd-about-cloudCheck')) ? q('.wd-about-cloudCheck').textContent : null,"
            " cancel: shown(q('.wd-about-cloudCancel'))};")

    # ── on every page ──────────────────────────────────────────────────────

    def test_a_pill_sits_against_the_theme_toggle_on_every_page(self):
        self.manager("none")
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            for path in HEADER_PAGES:
                with self.subTest(browser=kind, page=path):
                    self.load(drv, path)
                    m = self.pill_drawn(drv, path)
                    self.assertEqual(m["count"], 1, m)
                    self.assertIsNotNone(m["toggle"], "the pill must sit directly before the toggle: " + str(m))
                    # Against the toggle, on its row, and not wider than a pill.
                    self.assertLessEqual(m["pill"]["r"], m["toggle"]["l"] + 0.5, m)
                    self.assertLessEqual(m["toggle"]["l"] - m["pill"]["r"], 24, m)
                    mid = lambda b: (b["t"] + b["b"]) / 2
                    self.assertLess(abs(mid(m["pill"]) - mid(m["toggle"])), 6, m)
                    self.assertLessEqual(m["pill"]["w"], 190, m)
                    self.assertLessEqual(m["scrollW"], m["viewport"][0], m)

    def test_a_page_with_no_toggle_gets_one_pill_pinned_to_the_top_right(self):
        self.manager("none")
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            for path in FLOATING_PAGES:
                with self.subTest(browser=kind, page=path):
                    self.load(drv, path)
                    m = self.pill_drawn(drv, path)
                    self.assertEqual(m["count"], 1, m)
                    self.assertTrue(m["floating"], m)
                    self.assertGreater(m["pill"]["l"], m["viewport"][0] / 2, m)
                    self.assertLess(m["pill"]["t"], 60, m)
                    self.assertLessEqual(m["pill"]["r"], m["viewport"][0], m)

    def test_the_first_run_setup_page_is_left_alone(self):
        """A wizard that runs before there is anything to report."""
        import json
        from tools import settings as settings_mod
        self.manager("none")
        original = settings_mod.SETTINGS_FILE.read_text(encoding="utf-8")
        self.addCleanup(settings_mod.SETTINGS_FILE.write_text, original, encoding="utf-8")
        fresh = json.loads(original)
        fresh["setup_complete"] = False
        settings_mod.SETTINGS_FILE.write_text(json.dumps(fresh), encoding="utf-8")
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                drv.get(self.base + "/setup")
                time.sleep(1.5)
                self.assertEqual(drv.execute_script(
                    "return document.querySelectorAll('.wd-status-pill').length;"), 0)

    def test_nothing_is_pushed_down_and_the_old_bar_and_badge_are_gone(self):
        self.manager("none")
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            for path in HEADER_PAGES:
                with self.subTest(browser=kind, page=path):
                    self.load(drv, path)
                    m = self.pill_drawn(drv, path)
                    self.assertEqual(m["oldBar"], 0, m)
                    self.assertLess(abs(m["header"]["t"]), 1, m)

    # ── what it says ───────────────────────────────────────────────────────

    def test_current_and_signed_in_is_quiet_and_says_so(self):
        self.release(CURRENT)
        self.manager("connected")
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.load(drv, "/")
                m = self.pill_drawn(drv)
                self.assertEqual((m["text"], m["tone"], m["cloud"]), ("Up to date", "ok", "connected"), m)
                self.assertIn(INVENTED_EMAIL, m["title"], m)
                self.assertIn("up to date", m["title"], m)

    def test_each_cloud_state_has_its_own_label_tone_and_cloud(self):
        self.release(CURRENT)
        for state, want in (("none", ("Up to date", "ok", "none")),
                            ("saved", ("Up to date", "ok", "saved")),
                            ("connected", ("Up to date", "ok", "connected")),
                            ("expired", ("Sign in", "attn", "expired"))):
            self.manager(state)
            for kind, drv in self.each_browser():
                with self.subTest(browser=kind, cloud=state):
                    self.load(drv, "/")
                    self.pill_drawn(drv)
                    self.wait_for(drv, "return !!document.querySelector('.wd-status-cloud.is-%s');" % want[2])
                    m = drv.execute_script(MEASURE)
                    self.assertEqual((m["text"], m["tone"], m["cloud"]), want, m)

    def test_an_expired_sign_in_and_an_update_name_both(self):
        """Both at once name both, so neither is hidden behind the other."""
        self.manager("expired")
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.load(drv, "/")
                self.pill_drawn(drv)
                self.wait_for(drv, "return !!document.querySelector('.wd-status-cloud.is-expired');")
                m = drv.execute_script(MEASURE)
                self.assertEqual((m["text"], m["tone"]), ("Update · Sign in", "attn"), m)
                self.assertLessEqual(m["pill"]["w"], 190, m)
                self.assertIn("v9.0.9", m["title"], m)
                self.assertIn("expired", m["title"], m)

    def test_an_update_alone_is_amber_and_names_the_update(self):
        self.manager("connected")
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.load(drv, "/")
                m = self.pill_drawn(drv)
                self.assertEqual((m["text"], m["tone"], m["cloud"]), ("Update", "attn", "connected"), m)
                self.assertIn("v9.0.9", m["title"], m)

    # ── clicking it ────────────────────────────────────────────────────────

    def test_clicking_it_opens_about_with_the_update_card_marked(self):
        self.manager("connected")
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                drv.set_window_size(1366, 768)
                self.load(drv, "/report")
                self.pill_drawn(drv)
                self.click_pill(drv)
                self.wait_for(drv,
                    "var c = document.querySelector('#wdAboutModal.active .wd-about-update.is-newer');"
                    "return !!c && /9\\.0\\.9/.test(c.textContent);")
                # Opening About starts its own check, and the button reads
                # "Checking..." until that finishes; read it once it is idle.
                self.wait_for(drv,
                    "var b = document.querySelector('#wdAboutModal .wd-about-checkBtn');"
                    "return !!b && !b.disabled;")
                got = drv.execute_script(
                    "var c = document.querySelector('#wdAboutModal .wd-about-update');"
                    "return {title: c.querySelector('.wd-about-sectionTitle').textContent,"
                    " status: c.querySelector('.wd-about-updateResult').textContent,"
                    " check: c.querySelector('.wd-about-checkBtn').textContent};")
                # ascii(): the status line carries an arrow, and a failure
                # message with one cannot be printed on a cp1252 console.
                self.assertEqual(got["title"], "Updates", ascii(got))
                self.assertIn("Version 9.0.9 is available", got["status"], ascii(got))
                self.assertEqual(got["check"].strip(), "Check again", ascii(got))

    def test_the_update_button_names_the_version(self):
        self.manager("connected")
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.load(drv, "/scale")
                self.pill_drawn(drv)
                self.click_pill(drv)
                self.wait_for(drv, "return !!document.querySelector('#wdAboutModal .wd-update-goBtn');")
                label = drv.execute_script(
                    "return document.querySelector('#wdAboutModal .wd-update-goBtn').textContent;")
                self.assertEqual(label.strip(), "Update to v9.0.9")

    def test_a_current_install_has_a_pill_that_says_so_and_a_plain_card(self):
        self.release(CURRENT)
        self.manager("connected")
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.load(drv, "/")
                self.assertEqual(self.pill_drawn(drv)["text"], "Up to date")
                self.click_pill(drv)
                self.wait_for(drv,
                    "return /latest release/.test(document.querySelector("
                    "'#wdAboutModal .wd-about-updateResult').textContent);")
                self.assertFalse(drv.execute_script(
                    "return document.querySelector('#wdAboutModal .wd-about-update')"
                    ".classList.contains('is-newer');"))

    # ── the Ekahau Cloud card ──────────────────────────────────────────────

    def test_the_cloud_card_says_each_state_and_offers_the_right_buttons(self):
        self.release(CURRENT)
        for state, (cls, said, login, check) in {
                "connected": ("is-ok", "Signed in as " + INVENTED_EMAIL, "Log in again", "Check now"),
                "saved": ("is-idle", "Saved sign-in", "Log in again", "Check now"),
                "expired": ("is-attn", "Sign-in expired", "Log in to Ekahau Cloud", "Check now"),
                "none": ("is-idle", "Not signed in", "Log in to Ekahau Cloud", None)}.items():
            self.manager(state)
            for kind, drv in self.each_browser():
                with self.subTest(browser=kind, cloud=state):
                    drv.set_window_size(1366, 768)
                    self.load(drv, "/")
                    self.pill_drawn(drv)
                    self.wait_for(drv, "return !!document.querySelector('.wd-status-cloud.is-%s');" % state)
                    self.click_pill(drv)
                    self.wait_for(drv,
                        "return document.querySelector('#wdAboutCloud .wd-about-cloudState')"
                        ".textContent.indexOf(%r) >= 0;" % said)
                    got = self.card(drv)
                    self.assertIn(cls, got["cls"], ascii(got))
                    self.assertEqual(got["login"], login, ascii(got))
                    self.assertEqual(got["check"], check, ascii(got))
                    self.assertFalse(got["cancel"], ascii(got))

    def test_the_cloud_card_is_inside_the_window_beside_the_update_card(self):
        self.manager("expired")
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                drv.set_window_size(1366, 768)
                self.load(drv, "/")
                self.pill_drawn(drv)
                self.click_pill(drv)
                self.wait_for(drv, "return !!document.querySelector('#wdAboutCloud.is-attn');")
                box = drv.execute_script(
                    "var r = function (s) { var b = document.querySelector(s).getBoundingClientRect();"
                    " return {l: b.left, r: b.right, t: b.top, b: b.bottom}; };"
                    "return {cloud: r('#wdAboutCloud'), upd: r('.wd-about-update'),"
                    " modal: r('.wd-about-modal'), vw: innerWidth, vh: innerHeight};")
                self.assertGreaterEqual(box["cloud"]["l"], box["modal"]["l"], box)
                self.assertLessEqual(box["cloud"]["r"], box["upd"]["l"] + 1, box)
                self.assertLessEqual(box["cloud"]["b"], box["vh"], box)

    def test_log_in_opens_the_browser_waits_and_the_pill_clears_when_it_lands(self):
        """The reason this exists: an expired sign-in, fixed from any page."""
        self.release(CURRENT)
        m = self.manager("expired")
        m.open_login = mock.Mock(return_value={"ok": True})
        seen = []

        def check():
            seen.append(1)
            if len(seen) == 1:          # the browser has not written its cookie yet
                return {"state": "expired", "email": "", "verifiedAt": None, "detail": ""}
            m.api, m._expired = _Api(), False
            m._verified_at = time.time()
            return m.session_state()
        m.session_check = mock.Mock(side_effect=check)
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m.api, m._expired = None, True
                seen.clear()
                m.open_login.reset_mock()
                self.load(drv, "/")
                self.pill_drawn(drv)
                self.wait_for(drv, "return !!document.querySelector('.wd-status-cloud.is-expired');")
                self.click_pill(drv)
                [b for b in drv.find_elements(By.CSS_SELECTOR, "#wdAboutCloud .wd-about-cloudLogin")
                 if b.is_displayed()][0].click()
                self.wait_for(drv,
                    "return /Waiting for you to log in/.test("
                    "document.querySelector('#wdAboutCloud .wd-about-cloudState').textContent);")
                waiting = self.card(drv)
                self.assertIsNone(waiting["login"], "it is already waiting: " + ascii(waiting))
                self.assertTrue(waiting["cancel"], ascii(waiting))
                self.wait_for(drv,
                    "return /Signed in/.test(document.querySelector("
                    "'#wdAboutCloud .wd-about-cloudState').textContent);", timeout=25)
                self.assertEqual(m.open_login.call_count, 1)
                self.assertGreaterEqual(len(seen), 2, "it kept looking until the cookie landed")
                got = drv.execute_script(MEASURE)
                self.assertEqual((got["text"], got["tone"], got["cloud"]),
                                 ("Up to date", "ok", "connected"), got)

    def test_cancel_stops_the_waiting_and_asks_nothing_more(self):
        self.release(CURRENT)
        m = self.manager("expired")
        m.open_login = mock.Mock(return_value={"ok": True})
        m.session_check = mock.Mock(return_value={"state": "expired", "email": "",
                                                  "verifiedAt": None, "detail": ""})
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m.session_check.reset_mock()
                self.load(drv, "/")
                self.pill_drawn(drv)
                self.wait_for(drv, "return !!document.querySelector('.wd-status-cloud.is-expired');")
                self.click_pill(drv)
                drv.find_element(By.CSS_SELECTOR, "#wdAboutCloud .wd-about-cloudLogin").click()
                self.wait_for(drv, "return !document.querySelector('#wdAboutCloud .wd-about-cloudCancel').hidden;")
                drv.find_element(By.CSS_SELECTOR, "#wdAboutCloud .wd-about-cloudCancel").click()
                self.wait_for(drv, "return /expired/.test(document.querySelector("
                                   "'#wdAboutCloud .wd-about-cloudState').textContent);")
                asked = m.session_check.call_count
                time.sleep(3)
                self.assertEqual(m.session_check.call_count, asked,
                                 "it went on asking Ekahau after Cancel")

    def test_closing_about_stops_the_waiting_too(self):
        self.release(CURRENT)
        m = self.manager("expired")
        m.open_login = mock.Mock(return_value={"ok": True})
        m.session_check = mock.Mock(return_value={"state": "expired", "email": "",
                                                  "verifiedAt": None, "detail": ""})
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m.session_check.reset_mock()
                self.load(drv, "/")
                self.pill_drawn(drv)
                self.wait_for(drv, "return !!document.querySelector('.wd-status-cloud.is-expired');")
                self.click_pill(drv)
                drv.find_element(By.CSS_SELECTOR, "#wdAboutCloud .wd-about-cloudLogin").click()
                drv.find_element(By.CSS_SELECTOR, "#wdAboutModal .wd-about-close").click()
                time.sleep(0.5)
                asked = m.session_check.call_count
                time.sleep(3)
                self.assertEqual(m.session_check.call_count, asked)

    def test_check_now_asks_once_and_the_pill_follows_the_answer(self):
        self.release(CURRENT)
        m = self.manager("saved")
        m.session_check = mock.Mock(return_value={"state": "expired", "email": "",
                                                  "verifiedAt": None, "detail": ""})
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m.session_check.reset_mock()
                m._expired = False
                self.load(drv, "/")
                self.pill_drawn(drv)
                self.wait_for(drv, "return !!document.querySelector('.wd-status-cloud.is-saved');")
                self.click_pill(drv)
                self.assertEqual(m.session_check.call_count, 0, "opening About must not ask Ekahau")
                drv.find_element(By.CSS_SELECTOR, "#wdAboutCloud .wd-about-cloudCheck").click()
                self.wait_for(drv, "return /expired/.test(document.querySelector("
                                   "'#wdAboutCloud .wd-about-cloudState').textContent);")
                self.assertEqual(m.session_check.call_count, 1)
                got = drv.execute_script(MEASURE)
                self.assertEqual((got["text"], got["tone"], got["cloud"]),
                                 ("Sign in", "attn", "expired"), got)

    def test_an_unreachable_ekahau_is_said_and_the_sign_in_is_not_called_expired(self):
        self.release(CURRENT)
        m = self.manager("connected")
        m.session_check = mock.Mock(return_value={
            "state": "connected", "email": INVENTED_EMAIL, "verifiedAt": None,
            "unreachable": True, "detail": "could not reach Ekahau Cloud (network not ready?)"})
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.load(drv, "/")
                self.pill_drawn(drv)
                self.click_pill(drv)
                drv.find_element(By.CSS_SELECTOR, "#wdAboutCloud .wd-about-cloudCheck").click()
                self.wait_for(drv, "return /could not reach Ekahau/.test(document.querySelector("
                                   "'#wdAboutCloud .wd-about-cloudNote').textContent);")
                self.assertEqual(drv.execute_script(MEASURE)["cloud"], "connected")

    # ── the promise ────────────────────────────────────────────────────────

    def test_loading_a_page_never_contacts_ekahau(self):
        """The Home page promises Cloud Manager contacts Ekahau only when told
        to. The pill is on every page and refreshes itself, so it must read
        what the server already knows and stop there - on load, on a timer,
        and on opening About."""
        m = self.manager("connected")
        m.session_check = mock.Mock(side_effect=AssertionError("asked Ekahau"))
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m.api.checks = 0
                self.load(drv, "/report")
                self.pill_drawn(drv)
                self.click_pill(drv)
                time.sleep(1.5)
                self.assertEqual(m.api.checks, 0, "a page load or About asked Ekahau")
                m.session_check.assert_not_called()
                m.status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
