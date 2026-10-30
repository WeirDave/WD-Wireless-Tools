"""A report is never cut off at the right, in the browser it is saved from.

Reported as: AP Placement Map reports coming out landscape with the whole
right-hand side cut off, saving to PDF from Firefox.

Firefox 158 turned on a new PDF writer (``print.experimental.skpdf``). It puts
every sheet on the paper the print dialog names and ignores ``@page`` size,
named pages included. A page laid out landscape - the width a named landscape
page asks for - then lands on a portrait sheet and loses everything past
7.7in. Firefox 157 honoured the sizes, Chrome and Edge still do, and every
check made here until then was measured through one of those.

The check that should have caught it did see it: from 158 every report printed
on portrait sheets through WebDriver. That was recorded as a WebDriver quirk
(v2.235.3) and Firefox was dropped from the measurement, so the suite stayed
green while the real Save to PDF produced the fault. **It is not WebDriver.**
Firefox's own print path, driven from its chrome context with the page size
rule honoured, gives the same sheets - and gives the right ones with the PDF
writer switched back.

So where the sheet cannot follow the page, the page follows the sheet: one
orientation for the whole document and no named ``@page`` rules (report.js,
``sheetsFollowTheDialog``). This prints the real Placement Map and requires:

* every browser: sheets on the print options' paper, though the pages were turned landscape -
  proof the named pages are off, because with them on Chrome and Edge print
  landscape sheets;
* Firefox, through its own print path: the sheet is the orientation the
  dialog was given, and the page heading's rule ends inside the right margin
  rather than running to the sheet edge. Measured from the PDF, not from the
  class the page carries - the class was right throughout.

The browser path needs ``MOZ_REMOTE_ALLOW_SYSTEM_ACCESS`` to reach Firefox's
chrome context; it is set here, for a Firefox this test starts on a scratch
profile, and nowhere else.
"""
from __future__ import annotations

from tests import browsers as _browsers

import base64
import os
import shutil
import tempfile
import threading
import time
import unittest
from functools import partial
from pathlib import Path

from tests.pdf_sheets import sheet_sizes
from tests.test_report_filename_browser import DROP_JS, _StubApi

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

try:  # pragma: no cover - availability varies by machine
    import pymupdf
    HAVE_PYMUPDF = True
except ImportError:  # pragma: no cover
    HAVE_PYMUPDF = False

try:  # pragma: no cover
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.print_page_options import PrintOptions
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

#: Pages carrying a key, in order - what has to have been turned.
KEYED_JS = """
return Array.from(document.querySelectorAll('#reportCanvas [data-page-key]'))
  .map(function (e) { return e.classList.contains('is-landscape') ? 'L' : 'P'; })
  .join('');
"""

#: The print settings Firefox's own Save to PDF builds, from its chrome context:
#: a file destination, the PDF writer, the page rule honoured, and the
#: dialog's Orientation as given (0 portrait, 1 landscape).
CHROME_PRINT_JS = """
const done = arguments[arguments.length - 1];
try {
  const ps = Cc["@mozilla.org/gfx/printsettings-service;1"]
    .getService(Ci.nsIPrintSettingsService).createNewPrintSettings();
  ps.outputDestination = Ci.nsIPrintSettings.kOutputDestinationFile;
  ps.toFileName = arguments[0];
  ps.outputFormat = Ci.nsIPrintSettings.kOutputFormatPDF;
  ps.usePageRuleSizeAsPaperSize = true;
  ps.orientation = arguments[1];
  gBrowser.selectedBrowser.browsingContext.print(ps)
    .then(() => done('ok'), e => done('error ' + e));
} catch (e) { done('error ' + e); }
"""

#: The right margin is 0.4in. A rule that stops inside it is on the sheet; one
#: that reaches the edge has been cut off.
MARGIN_PT = 0.3 * 72


class _Rig(unittest.TestCase):
    """The real report over a stub API, with a project dropped on it."""

    @classmethod
    def setUpClass(cls):
        from tests.esx_factory import make_esx
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-sheets-follow-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        esx = make_esx(cls.tmp / "Sample.esx", floors=2, aps=6, placed=True)
        cls.b64 = base64.b64encode(esx.read_bytes()).decode("ascii")
        cls.httpd = _browsers.ExclusiveServer(
            ("127.0.0.1", 0), partial(_StubApi, directory=str(WEB)))
        cls.port = cls.httpd.server_address[1]
        cls.addClassCleanup(_browsers.stop_server, cls.httpd)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/report.html" % cls.port

    def _open(self, driver, setup):
        """The Placement Map open, the policy forced on, then ``setup``."""
        driver.get(self.url)
        # Ready when the page can do the work, not after a fixed pause: a
        # loaded runner is slow to get here and the pause was a guess.
        deadline = time.time() + 60
        while time.time() < deadline:
            if driver.execute_script(
                    "return typeof selectReport === 'function'"
                    " && typeof matchAllPageOrient === 'function';"):
                break
            time.sleep(0.25)
        else:
            self.fail("the Report page never finished loading")
        driver.set_script_timeout(60)
        driver.execute_script("window.repSheetsFollowDialog = true;")
        driver.execute_async_script(DROP_JS, self.b64, "Sample.esx")
        driver.execute_script(
            "selectReport('placement'); goStage('review');")
        deadline = time.time() + 30
        while time.time() < deadline:
            if len(driver.execute_script(KEYED_JS)) >= 5:
                break
            time.sleep(0.25)
        driver.execute_script("markSheetPolicy();" + setup)
        time.sleep(1.2)
        return driver.execute_script(KEYED_JS)


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class EveryBrowserPrintsOneSheetSize(_Rig):
    def test_turned_pages_do_not_ask_for_a_sheet_of_their_own(self):
        started = 0
        for kind, binary in _browsers.triple():
            driver = _browsers.make_driver(kind, binary)
            if driver is None:
                continue
            started += 1
            try:
                with self.subTest(browser=kind):
                    asked = self._open(
                        driver, "setPageOrient('placement:floor-0','landscape');")
                    # Every page was turned: a choice on one is a choice on all.
                    self.assertEqual(asked, "L" * len(asked), asked)
                    self.assertGreaterEqual(len(asked), 5)
                    pdf = base64.b64decode(driver.print_page(PrintOptions()))
                    sizes = sheet_sizes(pdf)
                    # Every page was turned landscape. With named pages on,
                    # Chrome and Edge print LLLLL; with them off the sheet is
                    # the one the print options name, which is portrait.
                    self.assertEqual(
                        {(round(w), round(h)) for w, h in sizes},
                        {(612, 792)},
                        "%s printed sheets %s for pages that ask for none of "
                        "their own" % (kind, sizes))
            finally:
                _browsers.shut_down(driver)
        if not started:
            self.skipTest("no browser could be started")

    def test_auto_never_turns_a_page_where_pages_cannot_turn(self):
        for kind, binary in _browsers.triple():
            driver = _browsers.make_driver(kind, binary)
            if driver is None:
                continue
            try:
                with self.subTest(browser=kind):
                    asked = self._open(driver, "")
                    self.assertEqual(asked, "P" * len(asked), asked)
            finally:
                _browsers.shut_down(driver)

    def test_the_print_step_says_what_the_dialog_decides(self):
        for kind, binary in _browsers.triple():
            driver = _browsers.make_driver(kind, binary)
            if driver is None:
                continue
            try:
                with self.subTest(browser=kind):
                    self._open(driver, "")
                    on = driver.execute_script(
                        "renderPrintHint();"
                        "return document.getElementById('repPrintHint').textContent;")
                    self.assertIn("Orientation", on)
                    driver.execute_script(
                        "window.repSheetsFollowDialog = false; renderPrintHint();")
                    off = driver.execute_script(
                        "return document.getElementById('repPrintHint').textContent;")
                    self.assertNotIn("Orientation", off,
                                     "the note belongs only where sheets "
                                     "cannot turn one at a time")
            finally:
                _browsers.shut_down(driver)


@unittest.skipUnless(HAVE_SELENIUM and HAVE_PYMUPDF,
                     "selenium and PyMuPDF are needed to read the sheets")
class FirefoxSaveToPdfIsNotCutOff(_Rig):
    def _firefox(self):
        binary = _browsers.find("firefox")
        if not binary or not Path(binary).exists():
            self.skipTest("Firefox is not installed")
        previous = os.environ.get("MOZ_REMOTE_ALLOW_SYSTEM_ACCESS")
        os.environ["MOZ_REMOTE_ALLOW_SYSTEM_ACCESS"] = "1"
        try:
            driver = _browsers.make_driver("firefox", binary)
        finally:
            if previous is None:
                os.environ.pop("MOZ_REMOTE_ALLOW_SYSTEM_ACCESS", None)
            else:
                os.environ["MOZ_REMOTE_ALLOW_SYSTEM_ACCESS"] = previous
        if driver is None:
            self.skipTest("Firefox would not start")
        return driver

    def _save_to_pdf(self, driver, name, orientation):
        out = str(self.tmp / name)
        try:
            driver.set_context("chrome")
        except WebDriverException:
            self.skipTest("this Firefox gives no access to its print path")
        try:
            result = driver.execute_async_script(
                CHROME_PRINT_JS, out, orientation)
        finally:
            driver.set_context("content")
        self.assertEqual(result, "ok", result)
        # The writer finishes after the call returns.
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                return pymupdf.open(out)
            except Exception:
                time.sleep(0.25)
        self.fail("Firefox wrote no readable PDF")

    @staticmethod
    def _heading_rule_right_edge(page):
        """The right end of the longest thin horizontal rule on the sheet."""
        best = 0.0
        for d in page.get_drawings():
            r = d["rect"]
            if r.height < 3 and r.width > page.rect.width * 0.4:
                best = max(best, r.x1)
        return best

    def test_the_sheet_is_what_the_dialog_chose_and_nothing_runs_off_it(self):
        driver = self._firefox()
        try:
            cases = [
                ("nothing chosen, Portrait", "", 0, "portrait"),
                ("nothing chosen, Landscape", "", 1, "landscape"),
                ("Landscape chosen, Landscape",
                 "setPageOrient('placement:floor-0','landscape');", 1, "landscape"),
                # The reader forgot the dialog. The sheet is the dialog's, and
                # the layout is the sheet's, so nothing is cut off even so.
                ("Landscape chosen, Portrait",
                 "setPageOrient('placement:floor-0','landscape');", 0, "portrait"),
            ]
            for n, (label, setup, orientation, want) in enumerate(cases):
                with self.subTest(case=label):
                    self._open(driver, setup)
                    doc = self._save_to_pdf(driver, "sheet%d.pdf" % n, orientation)
                    self.assertGreaterEqual(len(doc), 5)
                    saw_rule = False
                    for number, page in enumerate(doc, 1):
                        w, h = page.rect.width, page.rect.height
                        self.assertEqual(
                            "landscape" if w > h else "portrait", want,
                            "sheet %d is %dx%d" % (number, w, h))
                        edge = self._heading_rule_right_edge(page)
                        if edge:
                            saw_rule = True
                            self.assertLessEqual(
                                edge, w - MARGIN_PT,
                                "sheet %d: the heading rule runs to %.0fpt on a "
                                "%.0fpt-wide sheet - cut off at the right"
                                % (number, edge, w))
                    # A measurement that found no rule measured nothing.
                    self.assertTrue(saw_rule, "no heading rule found to measure")
        finally:
            _browsers.shut_down(driver)


if __name__ == "__main__":
    unittest.main()
