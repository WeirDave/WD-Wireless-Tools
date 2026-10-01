"""Every link into Settings from a tool lands on that tool's section.

"if I'm leaving quick walls and I want to see the settings for quick walls I
don't need to open up settings and have to rifle through the damn settings
box". Two faults: the tools' own menus linked to plain `/settings`, and
Capacity's and Prep's `#sec-capacity` looked for `sec-sec-capacity` and
landed at the top of the page.

Every `/settings#...` link in the app is collected from the tracked pages and
scripts, followed in a real browser, and must open a section and bring it to
the top of the window. Each tool's own menu must carry one.
"""
from __future__ import annotations

import re
import subprocess
import time
import unittest
from pathlib import Path

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

ROOT = Path(__file__).resolve().parent.parent

#: The tool pages that have settings, and the section their link must reach.
TOOLS = {
    "walls.html": "sec-walls", "capacity.html": "sec-capacity",
    "prep.html": "sec-capacity", "plantrim.html": "sec-elsewhere",
    "ap-rename.html": "sec-elsewhere", "report.html": "sec-report",
    "cloud.html": "sec-cloud", "organizer.html": "sec-organizer",
    "rename.html": "sec-organizer",
}


def _links():
    out = subprocess.run(["git", "ls-files", "web"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    found = {}
    for p in out.split():
        if not p.endswith((".html", ".js")) or p.endswith("settings.html"):
            continue
        text = (ROOT / p).read_text(encoding="utf-8")
        for h in re.findall(r"/settings#([a-z-]+)", text):
            found.setdefault(h, set()).add(Path(p).name)
    return found


class EachToolLinksToASection(unittest.TestCase):
    def test_every_tool_with_settings_names_a_section(self):
        links = _links()
        for page in TOOLS:
            with self.subTest(page=page):
                self.assertTrue(any(page in pages for pages in links.values()),
                                "%s links to Settings without naming its section" % page)


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class EveryLinkLands(BrowserPagesHarness):

    def test_each_link_opens_its_section_at_the_top(self):
        links = _links()
        self.assertTrue(links)
        for kind, drv in self.each_browser():
            drv.set_window_size(1600, 900)
            for hash_ in sorted(links):
                with self.subTest(browser=kind, link="#" + hash_):
                    drv.get(self.base + "/settings")
                    drv.get(self.base + "/settings#" + hash_)
                    drv.refresh()
                    time.sleep(1.2)
                    r = drv.execute_script("""
                      var hit = Array.prototype.filter.call(
                        document.querySelectorAll('.s-section.is-arrived'),
                        function (s) { return s.open; })[0];
                      if (!hit) return null;
                      var b = hit.getBoundingClientRect();
                      var se = document.scrollingElement;
                      return {id: hit.id, top: b.top, win: innerHeight,
                              atEnd: se.scrollTop + se.clientHeight >= se.scrollHeight - 2};""")
                    self.assertIsNotNone(r, "#%s opened no section" % hash_)
                    # At the top of the window - or, for a section near the
                    # end of the page, as high as the page can scroll it and
                    # in the upper half of the window.
                    self.assertTrue(abs(r["top"]) < 120
                                    or (r["atEnd"] and 0 <= r["top"] < r["win"] / 2), r)
                    expected = {TOOLS[p] for p in links[hash_] if p in TOOLS}
                    if expected:
                        self.assertIn(r["id"], expected)


    def test_the_side_list_opens_one_section_and_marks_it(self):
        """The list down the side of a wide window is how a section is chosen
        on the page itself: pressing one shows that section alone and marks
        it, and every section is in the list."""
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                drv.set_window_size(1600, 900)
                drv.get(self.base + "/settings")
                time.sleep(1.2)
                count = drv.execute_script(
                    "return [document.querySelectorAll('.s-nav-item').length,"
                    " document.querySelectorAll('details.s-section').length];")
                self.assertEqual(count[0], count[1])
                drv.execute_script(
                    "document.querySelector('.s-nav-item[data-sec=\"sec-walls\"]').click();")
                time.sleep(0.8)
                r = drv.execute_script("""
                  var shown = Array.prototype.filter.call(
                    document.querySelectorAll('details.s-section'),
                    function (d) { return d.getBoundingClientRect().height > 0; })
                    .map(function (d) { return d.id; });
                  var cur = Array.prototype.map.call(
                    document.querySelectorAll('.s-nav-item.is-current'),
                    function (b) { return b.getAttribute('data-sec'); });
                  return {shown: shown, current: cur};""")
                self.assertEqual(r["shown"], ["sec-walls"])
                self.assertEqual(r["current"], ["sec-walls"])


if __name__ == "__main__":
    unittest.main()
