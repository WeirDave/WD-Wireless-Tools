"""Squirrel's file list reads at arm's length.

Measured with an invented folder at 1366x1080: the file table 12px, its
headings, file extensions and badges 10-11px. Driven through the real server's
own scan of a scratch folder holding two invented sites' loose files.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.support.ui import WebDriverWait

SCAN = """
var done = arguments[arguments.length - 1];
localStorage.setItem('wd-project-directory', arguments[0]);
_restoreCurrentRootSilently().then(function () { return doScan(); })
  .then(function () {
    var b = Array.prototype.find.call(document.querySelectorAll('button'),
      function (x) { return /Show File Details/.test(x.textContent); });
    if (b) b.click();
    setTimeout(function () { done(true); }, 800);
  }).catch(function (e) { done(String(e)); });
"""

SIZES = """
const px = s => parseFloat(getComputedStyle(s).fontSize);
const all = sel => Array.prototype.filter.call(document.querySelectorAll(sel),
  e => e.getBoundingClientRect().width > 0).map(px);
return {cells: all('#siteList td'), heads: all('#siteList th'),
        ext: all('#siteList .file-ext'), badges: all('#siteList .site-badge')};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class SquirrelFileList(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name) / "invented-root"
        for site in ("Invented Site A", "Invented Site B"):
            d = root / site
            d.mkdir(parents=True)
            for name in ("floor 1.png", "photo 001.jpg", "report.pdf",
                         "notes.txt", site + ".esx"):
                (d / name).write_text("x", encoding="utf-8")
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def test_the_file_list_is_at_the_readable_sizes(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                drv.set_window_size(1366, 1000)
                drv.get(self.base + "/organizer")
                WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                    "return typeof doScan === 'function';"))
                drv.set_script_timeout(30)
                self.assertIs(drv.execute_async_script(SCAN, str(self.root)), True)
                for _ in range(40):
                    s = drv.execute_script(SIZES)
                    if s["cells"]:
                        break
                    time.sleep(0.25)
                self.assertTrue(s["cells"] and s["heads"] and s["ext"], s)
                self.assertGreaterEqual(min(s["cells"]), 14, s)
                self.assertGreaterEqual(min(s["heads"] + s["ext"] + s["badges"]), 13, s)


if __name__ == "__main__":
    unittest.main()
