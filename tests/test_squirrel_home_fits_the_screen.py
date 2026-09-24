"""Squirrel's five cards sit in one row, and the page fits a laptop screen.

`.pick-cards` was capped at 774px, which holds three 246px cards, so Rename
and Acorn Notes always wrapped to a second row. On a laptop that put them
below the fold behind a 180px icon, with empty space either side of the
cards - the page had to be scrolled to reach two of its five tools.

Measured in a real browser because every claim here is about layout: which
row each card landed on, where the last one ends, and whether anything spills
sideways. Driven through the real Flask app on an unusual port, the same way
`test_strict_pages_work_in_a_browser.py` does it, and in each browser this
machine has.
"""
from __future__ import annotations

import contextlib
import json
import threading
import unittest
from unittest import mock

from tests import browsers as _browsers
from tests.test_strict_pages_work_in_a_browser import (
    BROWSERS, HAVE_SELENIUM, _driver, _free_port)

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

PORT_HINT = 47391

#: Which rows the cards are on, where the last one ends, and whether anything
#: is wider than its box. The last-folder hint is shown with a long path,
#: because that is the tallest the first card gets and the state a returning
#: user sees.
MEASURE = """
var hint = document.getElementById('lastFolderHint');
hint.hidden = false;
document.getElementById('lastFolderPath').textContent =
  'C:\\\\Users\\\\example\\\\Documents\\\\Ekahau AI Pro\\\\Projects';
var cards = Array.prototype.slice.call(
  document.querySelectorAll('#pickScreen .pick-card'));
var rects = cards.map(function (c) { return c.getBoundingClientRect(); });
var tops = {};
rects.forEach(function (r) { tops[Math.round(r.top)] = true; });
var content = document.getElementById('content');
return {
  cards: cards.length,
  rows: Object.keys(tops).length,
  lastBottom: Math.max.apply(null, rects.map(function (r) { return r.bottom; })),
  innerWidth: window.innerWidth,
  innerHeight: window.innerHeight,
  sideways: document.documentElement.scrollWidth > window.innerWidth
            || content.scrollWidth > content.clientWidth,
  cardSpills: cards.some(function (c) { return c.scrollWidth > c.clientWidth + 1; })
};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class SquirrelHomeFitsTheScreenTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server
        import server
        from tools import settings as settings_mod

        # A scratch user directory looks like a first run and redirects every
        # page to /setup; a settings file is what a configured install has.
        if not settings_mod.SETTINGS_FILE.exists():
            settings_mod.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            done = json.loads(json.dumps(settings_mod.DEFAULTS))
            done["setup_complete"] = True
            settings_mod.SETTINGS_FILE.write_text(json.dumps(done),
                                                  encoding="utf-8")
        cls._patches = [
            mock.patch.object(server.updater, "detect_install",
                              return_value={"method": "manual",
                                            "isGitInstall": False,
                                            "isDevCheckout": True,
                                            "currentVersion": "0.0.0"}),
            mock.patch.object(server.updater, "fetch_latest_release",
                              return_value=None),
        ]
        for patcher in cls._patches:
            patcher.start()
        cls.port = _free_port(PORT_HINT)
        cls.httpd = make_server("127.0.0.1", cls.port, server.app,
                                threaded=True)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.drivers = {}
        for kind, binary in BROWSERS:
            drv = _driver(kind, binary)
            if drv is not None:
                drv.set_page_load_timeout(30)
                cls.drivers[kind] = drv

    @classmethod
    def tearDownClass(cls):
        for patcher in getattr(cls, "_patches", []):
            with contextlib.suppress(Exception):
                patcher.stop()
        for drv in getattr(cls, "drivers", {}).values():
            _browsers.shut_down(drv)
        httpd = getattr(cls, "httpd", None)
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        thread = getattr(cls, "thread", None)
        if thread is not None:
            thread.join(timeout=10)

    def measure(self, drv, width, height):
        drv.set_window_size(width, height)
        drv.get(self.base + "/squirrel")
        WebDriverWait(drv, 15).until(
            EC.visibility_of_element_located((By.ID, "pickScreen")))
        return drv.execute_script(MEASURE)

    def each_browser(self):
        if not self.drivers:
            self.skipTest("no browser could be started on this machine")
        return self.drivers.items()

    def test_all_five_cards_share_one_row_on_a_wide_window(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m = self.measure(drv, 1440, 900)
                if m["innerWidth"] < 1080:
                    self.skipTest("%s gave a %dpx viewport" % (kind, m["innerWidth"]))
                self.assertEqual(m["cards"], 5)
                self.assertEqual(m["rows"], 1, m)
                self.assertFalse(m["sideways"], m)
                self.assertFalse(m["cardSpills"], m)

    def test_a_laptop_screen_shows_every_card_without_scrolling(self):
        """The screen the report came from: every card, top to bottom,
        without scrolling."""
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m = self.measure(drv, 1366, 860)
                if m["innerWidth"] < 1200 or m["innerHeight"] < 700:
                    self.skipTest("%s gave a %dx%d viewport"
                                  % (kind, m["innerWidth"], m["innerHeight"]))
                self.assertLessEqual(m["lastBottom"], m["innerHeight"], m)

    def test_a_narrow_window_wraps_rather_than_spilling_sideways(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m = self.measure(drv, 900, 900)
                self.assertGreater(m["rows"], 1, m)
                self.assertFalse(m["sideways"], m)
                self.assertFalse(m["cardSpills"], m)


if __name__ == "__main__":
    unittest.main()
