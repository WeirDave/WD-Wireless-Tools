"""Combining grid cells, driven through the real dialog in a real browser.

`test_combined_sections.py` settles what a combined section prints as. This
settles whether a person can make one: the cells are picked by click events
on the plan, which go through the container's delegated listener, and the
buttons are pressed through the page's own dispatcher. A Combine button that
renders and does nothing would pass every other test in the suite.

Chrome, Edge and Firefox, per the standing rule. The page is served over
`http.server` with `WD.api` answered by a stub, never `server.py`.
"""
from __future__ import annotations

import base64
import shutil
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from tests import browsers as _browsers
from tests import test_column_grid_picker_browser as _picker


SETUP_JS = r"""
var done = arguments[arguments.length - 1];
var bytes = Uint8Array.from(atob(arguments[0]), function (c) { return c.charCodeAt(0); });
var dt = new DataTransfer();
dt.items.add(new File([bytes], 'grid-fixture.esx', { type: 'application/octet-stream' }));
document.getElementById('dropzone').dispatchEvent(
  new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
setTimeout(function () {
  window.openGridConfig();
  // A 3x2 grid, whatever the automatic split chose.
  for (var i = 0; i < 20; i++) { window.adjustGridCols(-1); window.adjustGridRows(-1); }
  window.adjustGridCols(1); window.adjustGridCols(1); window.adjustGridRows(1);
  var modal = document.getElementById('gridConfigModal');
  done({ opened: !!modal && !modal.hidden });
}, 2500);
"""

STATE_JS = r"""
return {
  labels: Array.prototype.map.call(
    document.querySelectorAll('#gridSvg text'), function (t) { return t.textContent; }),
  count: document.getElementById('gridCellCount').textContent,
  hint: document.getElementById('gridMergeHint').textContent,
  combineDisabled: document.getElementById('gridCombineBtn').disabled,
  splitDisabled: document.getElementById('gridSplitBtn').disabled,
};
"""

#: A click on one cell of the plan, bubbling to the container as a real one does.
PICK_JS = r"""
var el = document.querySelector('[data-cell="' + arguments[0] + '"]');
if (!el) return false;
el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
return true;
"""

PRESS_JS = r"""
var b = document.getElementById(arguments[0]);
if (!b || b.disabled) return false;
b.click();
return true;
"""


@unittest.skipUnless(_picker.HAVE_SELENIUM, "selenium is not installed")
class CellsCanBeCombinedInTheDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.esx_factory import make_esx
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-combine-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        esx = make_esx(cls.tmp / "grid-fixture.esx", aps=12, placed=True)
        cls.b64 = base64.b64encode(esx.read_bytes()).decode("ascii")
        cls.httpd = _browsers.ExclusiveServer(
            ("127.0.0.1", 0), partial(_picker._StubApi, directory=str(_picker.WEB)))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/report.html" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _each_browser(self):
        started = 0
        for kind, binary in _picker.BROWSERS:
            driver = _picker.ThePickerSavesWhatWasClicked._driver(kind, binary)
            if driver is None:
                continue
            try:
                # Setting the browser itself up. A window the browser has
                # already discarded at this point (seen once on a Windows
                # runner, in Firefox) is the browser failing to start, which
                # _driver already treats as "not available" - it says nothing
                # about the page. Everything from the page load on counts.
                try:
                    driver.set_window_size(1600, 1200)
                    driver.set_script_timeout(60)
                except _picker.WebDriverException:
                    continue
                started += 1
                driver.get(self.url)
                time.sleep(1.2)
                opened = driver.execute_async_script(SETUP_JS, self.b64)
                self.assertTrue(opened["opened"], f"{kind}: the grid dialog did not open")
                yield kind, driver
            finally:
                _browsers.shut_down(driver)
        if not started:
            self.skipTest("none of Firefox, Chrome or Edge would start")

    def _combine(self, driver, *cells):
        for key in cells:
            self.assertTrue(driver.execute_script(PICK_JS, key), f"no cell {key} to click")
        self.assertTrue(driver.execute_script(PRESS_JS, "gridCombineBtn"),
                        "Combine selected was not available: "
                        + driver.execute_script(STATE_JS)["hint"])

    def test_the_l_shaped_building_can_be_set_up_by_clicking(self):
        """A1+A2 become A, B1+B2 become B, C stays divided - and it survives
        Done and reopening the dialog."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                state = driver.execute_script(STATE_JS)
                self.assertTrue(state["combineDisabled"],
                                "Combine selected was usable before Combine cells was on")
                self.assertIn("Combine cells", state["hint"])
                self.assertTrue(driver.execute_script(PRESS_JS, "gridMergeModeBtn"))
                self._combine(driver, "0,0", "0,1")
                self._combine(driver, "1,0", "1,1")
                state = driver.execute_script(STATE_JS)
                self.assertEqual(state["labels"], ["A", "B", "C1", "C2"])
                self.assertIn("4 sections", state["count"])
                driver.execute_script("window.doneGridConfig(); window.openGridConfig();")
                self.assertEqual(driver.execute_script(STATE_JS)["labels"],
                                 ["A", "B", "C1", "C2"], "the combination was lost on Done")

    def test_an_l_shaped_pick_is_refused_with_its_reason_on_screen(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                driver.execute_script(PRESS_JS, "gridMergeModeBtn")
                for key in ("0,0", "0,1", "1,1"):
                    driver.execute_script(PICK_JS, key)
                state = driver.execute_script(STATE_JS)
                self.assertTrue(state["combineDisabled"])
                self.assertIn("rectangle", state["hint"])

    def test_split_puts_the_cells_back(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                driver.execute_script(PRESS_JS, "gridMergeModeBtn")
                self._combine(driver, "0,0", "0,1")
                driver.execute_script(PICK_JS, "0,0")   # picks the whole section
                self.assertTrue(driver.execute_script(PRESS_JS, "gridSplitBtn"),
                                "Split was not available on a picked section")
                self.assertEqual(driver.execute_script(STATE_JS)["labels"],
                                 ["A1", "B1", "C1", "A2", "B2", "C2"])


if __name__ == "__main__":
    unittest.main()
