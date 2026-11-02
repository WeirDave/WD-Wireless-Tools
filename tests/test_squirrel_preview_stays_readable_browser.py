"""Squirrel's preview is usable when there are a lot of site folders.

Two things were wrong with a large folder. The card said three files would
move, but the list showed every site folder, so finding those three meant
scrolling; and rows scrolled up through the strip above the Change Folder /
New Folder / Rescan / Settings bar, so data showed above it.

Driven through the real server's own scan of a scratch folder with forty
invented sites, three files that move and the rest staying.
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

SITES = 40

SCAN = """
var done = arguments[arguments.length - 1];
localStorage.setItem('wd-project-directory', arguments[0]);
localStorage.setItem('wd-organizer-details', '1');
localStorage.removeItem('wd-organizer-filter');
localStorage.removeItem('wd-organizer-advanced');
_restoreCurrentRootSilently().then(function () { return doScan(); })
  .then(function () { setTimeout(function () { done(true); }, 600); })
  .catch(function (e) { done(String(e)); });
"""

#: What is on screen, as a person would count it.
VISIBLE = """
function shown(e) { return e.getClientRects().length > 0; }
var groups = Array.prototype.filter.call(document.querySelectorAll('#siteList .site-group'), shown);
return {
  sites: groups.length,
  movingRows: Array.prototype.filter.call(
    document.querySelectorAll('#siteList input[data-file]'), shown).length,
  stayingRows: Array.prototype.filter.call(
    document.querySelectorAll('#siteList .staying-row'), shown).length,
  scanSites: document.querySelectorAll('#siteList .site-group').length,
  scanMoving: document.querySelectorAll('#siteList input[data-file]').length,
  scanMovingSites: document.querySelectorAll('#siteList .site-group:not([data-moves="0"])').length
};
"""

#: The note beside the filter, as a person sees it (empty when it is hidden).
NOTE = """
var n = document.getElementById('orgFilterNote');
return n && n.getClientRects().length ? n.textContent : '';
"""

#: Click the real button the way the page wires it.
PRESS = """
var b = document.querySelector('#orgFilterBar [data-filter="' + arguments[0] + '"]');
if (!b) return 'no such button';
b.click();
return true;
"""

#: Scroll the list well down, then ask what is at the top edge of the scroll
#: area: it has to be the bar, at every pixel of what used to be the gap.
TOP_EDGE = """
var c = document.getElementById('content');
c.scrollTop = 700;
var top = c.getBoundingClientRect().top;
var bar = document.querySelector('.sticky-header').getBoundingClientRect();
var x = bar.left + bar.width / 2;
var out = [];
for (var dy = 0; dy <= 24; dy += 4) {
  var el = document.elementFromPoint(x, top + dy);
  out.push({dy: dy, inBar: !!(el && el.closest('.sticky-header')),
            what: el ? el.tagName + '.' + el.className : null});
}
return {scrolled: c.scrollTop, out: out};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class SquirrelPreviewStaysReadable(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name) / "invented-root"
        for n in range(SITES):
            d = root / ("Invented Site %02d" % n)
            d.mkdir(parents=True)
            (d / ("Invented Site %02d.esx" % n)).write_text("x", encoding="utf-8")
            (d / "notes.xyz").write_text("x", encoding="utf-8")
        # Three files that will move, in two of the sites.
        for site, names in (("Invented Site 03", ("floor 1.png", "photo 001.jpg")),
                            ("Invented Site 17", ("floor 2.png",))):
            for name in names:
                (root / site / name).write_text("x", encoding="utf-8")
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def open_preview(self, drv):
        drv.set_window_size(1366, 900)
        drv.get(self.base + "/organizer")
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(
            "return typeof doScan === 'function';"))
        drv.set_script_timeout(30)
        self.assertIs(drv.execute_async_script(SCAN, str(self.root)), True)
        for _ in range(40):
            if drv.execute_script(
                    "return document.querySelectorAll('#siteList .site-group').length;"):
                break
            time.sleep(0.25)

    def test_the_list_opens_on_what_will_move(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_preview(drv)
                v = drv.execute_script(VISIBLE)
                self.assertEqual((v["scanSites"], v["scanMoving"], v["scanMovingSites"]),
                                 (SITES, 3, 2), v)
                self.assertEqual(v["sites"], 2, v)
                self.assertEqual(v["movingRows"], 3, v)
                self.assertEqual(v["stayingRows"], 0, v)
                self.assertEqual(drv.execute_script(NOTE), "38 site folders with nothing to move hidden")
                drv.execute_script(PRESS, "all")
                self.assertEqual(drv.execute_script(NOTE), "")

    def test_everything_shows_every_folder_and_back_again_keeps_the_choices(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_preview(drv)
                drv.execute_script(
                    "document.querySelector('#siteList input[data-file]').checked = false;")
                self.assertIs(drv.execute_script(PRESS, "all"), True)
                v = drv.execute_script(VISIBLE)
                self.assertEqual(v["sites"], SITES, v)
                self.assertGreater(v["stayingRows"], 0, v)
                self.assertIs(drv.execute_script(PRESS, "moving"), True)
                v = drv.execute_script(VISIBLE)
                self.assertEqual(v["sites"], 2, v)
                self.assertFalse(drv.execute_script(
                    "return document.querySelector('#siteList input[data-file]').checked;"),
                    "switching the filter must not redraw and re-tick a box")

    def test_the_choice_is_remembered(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_preview(drv)
                drv.execute_script(PRESS, "all")
                # A rescan redraws the list from scratch; the choice survives it.
                drv.execute_async_script(
                    "var done = arguments[arguments.length - 1];"
                    "doScan().then(function () { setTimeout(done, 400); });")
                v = drv.execute_script(VISIBLE)
                self.assertEqual(v["sites"], SITES, v)
                self.assertEqual(drv.execute_script(
                    "return document.querySelector('#orgFilterBar [data-filter=all]')"
                    ".getAttribute('aria-pressed');"), "true")

    def test_nothing_shows_above_the_bar_when_the_list_is_scrolled(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_preview(drv)
                drv.execute_script(PRESS, "all")
                r = drv.execute_script(TOP_EDGE)
                self.assertGreater(r["scrolled"], 300, r)
                for hit in r["out"]:
                    self.assertTrue(hit["inBar"], r)


if __name__ == "__main__":
    unittest.main()
