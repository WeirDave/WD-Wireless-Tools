"""Every page of a report prints on the paper it asked for, the first included,
and nothing prints after the last one.

Reported from Firefox: with the cover set to Landscape the cover's text moved
but the first sheet stayed portrait, every later page came out landscape, and
a blank sheet followed the last page. "Match all pages" did not change it.

The cause was not the orientation code, which had set the right class on
every page throughout. Firefox gives a whitespace-only text node its own box
in print when it sits beside a display:none sibling, and #stageReview has two
of those in front of the canvas - the review bar and the print hint - with
the modals and scripts after it. Those boxes belong to no named page, so the
sheet before the cover took the default paper and a sheet after the last page
was laid out to hold nothing. Chromium draws neither box, which is why a
Chromium check never saw it. The landscape cover also asked for 90vh, which
in print is taller than a landscape sheet's printable area, so once page one
turned the cover spilled onto a blank second sheet.

So this prints the real page, reads the paper size of every sheet back out of
the PDF, and requires exactly one sheet per page, in the orientation that
page's class asks for. Against the code before the fix, Firefox produced
``PLLLLLP`` for an all-landscape report and ``PPPPPPP`` for an all-portrait
one; each is seven sheets for six pages.

The server is ``http.server`` over ``web/``, never ``server.py``, which opens a
browser window nobody closes.
"""
from __future__ import annotations

from tests import browsers as _browsers

import base64
import shutil
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from tests.pdf_sheets import orientations
from tests.test_report_filename_browser import DROP_JS, _StubApi

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.print_page_options import PrintOptions
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

#: The orientation each page's class asks for, one letter per page in
#: document order - what the sheets have to match.
ASKED_JS = """
return Array.from(document.querySelectorAll('#reportCanvas [data-page-key]'))
  .map(function (e) { return e.classList.contains('is-landscape') ? 'L' : 'P'; })
  .join('');
"""

SCENARIOS = [
    # What was reported: cover to Landscape, then Match all pages.
    ("all landscape",
     "setPageOrient('cover', 'landscape'); matchAllPageOrient('cover');"),
    # The first report of it: the cover turned and nothing else.
    ("cover landscape, the rest portrait",
     "setPageOrient('placement:floor-0', 'portrait');"
     " matchAllPageOrient('placement:floor-0');"
     " setPageOrient('cover', 'landscape');"),
    # The trailing blank sheet showed on an all-portrait report as well.
    ("all portrait",
     "setPageOrient('cover', 'portrait'); matchAllPageOrient('cover');"),
]


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class EverySheetIsThePaperItsPageAskedFor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.esx_factory import make_esx
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-first-sheet-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        # Two floors so there are two map pages and two label pages; placed APs
        # so the maps have something on them.
        esx = make_esx(cls.tmp / "Sample.esx", floors=2, aps=6, placed=True)
        cls.b64 = base64.b64encode(esx.read_bytes()).decode("ascii")
        cls.httpd = _browsers.ExclusiveServer(
            ("127.0.0.1", 0), partial(_StubApi, directory=str(WEB)))
        cls.port = cls.httpd.server_address[1]
        cls.addClassCleanup(_browsers.stop_server, cls.httpd)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d/report.html" % cls.port

    @staticmethod
    def _driver(kind, binary):
        if not Path(binary).exists():
            return None
        try:
            if kind == "firefox":
                o = webdriver.FirefoxOptions()
                o.binary_location = binary
                o.add_argument("-headless")
                return webdriver.Firefox(options=o)
            if kind == "chrome":
                o = webdriver.ChromeOptions()
                o.binary_location = binary
                o.add_argument("--headless=new")
                o.add_argument("--no-sandbox")
                return webdriver.Chrome(options=o)
            o = webdriver.EdgeOptions()
            o.binary_location = binary
            o.add_argument("--headless=new")
            return webdriver.Edge(options=o)
        except (WebDriverException, OSError):
            return None

    def _print(self, driver, setup):
        driver.get(self.url)
        time.sleep(1.2)
        driver.set_script_timeout(60)
        driver.execute_async_script(DROP_JS, self.b64, "Sample.esx")
        driver.execute_script(
            "selectReport('placement'); goStage('review');" + setup)
        time.sleep(0.8)
        asked = driver.execute_script(ASKED_JS)
        pdf = base64.b64decode(driver.print_page(PrintOptions()))
        return asked, orientations(pdf)

    def test_one_sheet_per_page_on_the_paper_it_asked_for(self):
        started = 0
        for kind, binary in _browsers.triple():
            driver = self._driver(kind, binary)
            if driver is None:
                continue
            started += 1
            try:
                for name, setup in SCENARIOS:
                    with self.subTest(browser=kind, scenario=name):
                        asked, sheets = self._print(driver, setup)
                        # The fixture's own shape, so a report that rendered
                        # nothing cannot pass by printing nothing.
                        self.assertEqual(len(asked), 6, asked)
                        self.assertEqual(
                            sheets, asked,
                            "%s printed %s for pages asking for %s"
                            % (kind, sheets, asked))
            finally:
                _browsers.shut_down(driver)
        if not started:
            self.skipTest("none of Firefox, Chrome or Edge would start")


if __name__ == "__main__":
    unittest.main()
