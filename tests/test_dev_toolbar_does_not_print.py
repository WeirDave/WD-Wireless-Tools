"""The dev toolbar is on screen and not on the paper.

He sent a photograph of the Report print view with the pink DEV strip sitting
on the white sheet, above the report content, on the morning he needed to print
a deliverable. It would have printed onto a document handed to installers.

**The cause is the ordinary one for this class.** Every preview surface in
Report sits inside `.noprint`; the toolbar was added afterwards and never got
the same treatment. Nothing in the suite checks that a new overlay is excluded
from print, so it shipped green.

**Why this prints rather than reads the stylesheet.** A rule in `@media print`
proves a rule exists. It does not prove the element is gone from the sheet -
the toolbar is `position: fixed`, and fixed elements are exactly the ones that
survive naive print rules. The only thing that settles it is the PDF, through
Firefox's own pagination, which is what he prints from.

The two halves matter equally and one test would miss either:

* the strip is **absent from the printed output**, and
* it is **still on screen** - a fix that hid it everywhere would pass an
  absence check and take his toolbar away.

Measured through geckodriver's WebDriver Print Page command - the same
pagination the print dialog uses - with the fix reverted and reapplied:

    the strip, on Report      before: printed    after: absent
    the strip, every page     before: printed on 14 of them    after: none
    dev off vs dev on         before: different documents      after: identical
    the toolbar on screen     before: present    after: present

The fault was not confined to Report. Fourteen pages carried the strip onto
the sheet; Report is simply the one he prints, so it is the one he saw.

Skipped where selenium or Firefox is missing, so CI stays green; the harness
drives a real browser, which is not something to ask of CI - the same split
`test_print_trailing_page.py` describes.
"""
from __future__ import annotations

from tests import browsers as _browsers

import contextlib
import socket
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: Its own port range, clear of the other browser suites and of his 8675.
PORT_HINT = 8903

#: Text that only the dev toolbar puts on a page. Read off the strip's own
#: labels, so a rename breaks this loudly rather than silently passing.
STRIP_MARKERS = ("Realign renamed cloud projects",
                 "Clean up leftover files",
                 "About dev mode")

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.print_page_options import PrintOptions
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

try:  # pragma: no cover
    import pymupdf
    HAVE_PYMUPDF = True
except ImportError:  # pragma: no cover
    HAVE_PYMUPDF = False

FIREFOX = _browsers.find("firefox")


def _free_port(start):
    for port in range(start, start + 40):
        with contextlib.closing(socket.socket()) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port near %d" % start)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def pages_that_load_the_toolbar():
    """Read off disk rather than listed, so a new page cannot be skipped."""
    return [p.name for p in sorted(WEB.glob("*.html"))
            if "js/wd-dev.js" in p.read_text(encoding="utf-8", errors="ignore")]


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
@unittest.skipUnless(HAVE_PYMUPDF, "PyMuPDF is not installed")
@unittest.skipUnless(Path(FIREFOX).exists(), "Firefox is not installed here")
class TheToolbarIsNotOnThePaper(unittest.TestCase):
    """Firefox, because it is what he prints from and it is the engine that
    has twice carried a print fault Chromium does not have."""

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port(PORT_HINT)
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", cls.port), partial(QuietHandler, directory=str(WEB)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

        opts = webdriver.FirefoxOptions()
        opts.binary_location = FIREFOX
        opts.add_argument("-headless")
        try:
            cls.driver = webdriver.Firefox(options=opts)
        except (WebDriverException, OSError) as exc:
            cls.server.shutdown()
            cls.server.server_close()
            raise unittest.SkipTest("Firefox would not start: %s" % exc)
        cls.driver.set_page_load_timeout(60)

    @classmethod
    def tearDownClass(cls):
        # Always, on the failure path too.
        _browsers.shut_down(cls.driver)
        _browsers.stop_server(cls.server)

    def open(self, page, query=""):
        self.driver.get("http://127.0.0.1:%d/%s%s" % (self.port, page, query))
        for _ in range(40):
            if self.driver.execute_script(
                    "return !!(window.WD && window.WD.Dev);"):
                break
            time.sleep(0.05)
        time.sleep(0.2)

    def printed_text(self):
        """Every character on the sheets, through Firefox's own pagination -
        the same path `window.print()` takes. `PrintOptions` is left with its
        page size unset deliberately: pinning it overrides what the CSS asked
        for, which is its own trap."""
        import base64
        pdf = base64.b64decode(self.driver.print_page(PrintOptions()))
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)

    # ── the fault he photographed ────────────────────────────────
    def test_the_strip_does_not_print_on_the_report(self):
        """The one that matters: Report is what he prints."""
        self.open("report.html", "?dev=1")
        self.assertTrue(self.driver.find_element(By.ID, "devToolbar").is_displayed(),
                        "the toolbar is not on screen, so this proves nothing")
        printed = self.printed_text()
        for marker in STRIP_MARKERS:
            self.assertNotIn(marker, printed,
                             "the dev toolbar printed onto the sheet")

    def test_it_is_still_on_screen_while_absent_from_print(self):
        """The other half. Hiding it everywhere would pass the check above and
        take his toolbar away."""
        self.open("report.html", "?dev=1")
        strip = self.driver.find_element(By.ID, "devToolbar")
        self.assertTrue(strip.is_displayed())
        self.assertIn("Realign renamed cloud projects",
                      strip.get_attribute("textContent"))

    def test_an_open_panel_does_not_print_either(self):
        """A modal left open is a full-page overlay - the version of this fault
        that covers the whole sheet rather than the top of it.

        **This one passed before the fix as well.** The dev panels are built on
        `.modal-overlay`, which the print block already excludes, so they were
        never exposed; only the strip was. It is kept as a guard, not as
        evidence - it catches a panel being restyled off `.modal-overlay`, or
        that selector being tidied out of the print list - and it is labelled
        so that nobody later reads it as part of what proved the fix."""
        self.open("report.html", "?dev=1")
        self.driver.execute_script(
            "document.getElementById('wdRealignOpenBtn').click();")
        time.sleep(0.3)
        self.assertTrue(
            self.driver.find_element(By.ID, "devResultModal").is_displayed())
        printed = self.printed_text()
        for marker in ("Renaming a project in Ekahau Cloud",
                       "What it will not do"):
            self.assertNotIn(marker, printed,
                             "the open dev panel printed onto the sheet")

    def test_no_page_that_carries_the_toolbar_prints_it(self):
        """The toolbar injects into every page, so Report is not the only
        printable surface - Ctrl+P works anywhere. Checked across all of them
        rather than the one that was reported."""
        offenders = []
        for page in pages_that_load_the_toolbar():
            self.open(page, "?dev=1")
            if not self.driver.find_elements(By.ID, "devToolbar"):
                continue
            printed = self.printed_text()
            if any(m in printed for m in STRIP_MARKERS):
                offenders.append(page)
        self.assertEqual(offenders, [],
                         "the dev toolbar prints on these pages")

    def test_dev_mode_off_prints_the_same_document(self):
        """The workaround he was given was to exit dev mode. The printed
        output has to be identical either way, or the fix has changed the
        deliverable rather than only hiding the strip."""
        self.open("report.html", "?dev=0")
        without = self.printed_text()
        self.open("report.html", "?dev=1")
        with_dev = self.printed_text()
        self.assertEqual(without.split(), with_dev.split(),
                         "dev mode changes what prints")


if __name__ == "__main__":
    unittest.main()
