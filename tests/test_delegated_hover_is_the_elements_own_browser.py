"""A delegated mouseenter/mouseleave fires for the element, not for its children.

`WD.actions` catches every event on the document. mouseenter and mouseleave do
not bubble, so they are caught in the capture phase - where a child's enter
and leave also arrive, and `closest()` walked from the child up to the row
and ran the row's handler. Moving the pointer from a Visual Swap row onto the
row's own button fired the row's mouseleave, and the highlight on the plan
dropped while the pointer was still on the row.

Driven in each browser with the real `wd-shared.js`, served from a scratch
folder beside a page that records what reaches the handler.
"""
from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

from tests import browsers as _browsers
from tests.test_strict_pages_work_in_a_browser import (
    BROWSERS, HAVE_SELENIUM, _driver)

if HAVE_SELENIUM:
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parent.parent

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script src="wd-shared.js"></script></head><body style="margin:0">
<div id="row" style="box-sizing:border-box;width:460px;height:90px;padding:30px;background:#eee"
     data-action-mouseenter="call" data-action-mouseleave="call"
     data-fn="recordHover" data-arg-event="1" data-arg="seg-1">
  <button id="btn" type="button" style="width:120px;height:30px">Segment 1</button>
</div>
<div id="away" style="height:200px"></div>
<script src="record.js"></script></body></html>
"""

# The same rule as swapHoverSeg in walls-swap.js: leaving clears the highlight.
RECORD = """window.events = []; window.hovered = null;
window.recordHover = function (id, e) {
  events.push(e.type + '@' + (e.target && e.target.id));
  hovered = e.type === 'mouseleave' ? null : id;
};
"""


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheRowKeepsItsHoverOverItsOwnButtonTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        site = Path(cls._tmp.name)
        shutil.copy(ROOT / "web/assets/js/wd-shared.js", site / "wd-shared.js")
        (site / "hover.html").write_text(PAGE, encoding="utf-8")
        (site / "record.js").write_text(RECORD, encoding="utf-8")
        cls.server = _browsers.ExclusiveServer(
            ("127.0.0.1", 0), partial(_Quiet, directory=str(site)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d/hover.html" % cls.server.server_address[1]
        cls.drivers = {}
        for kind, binary in BROWSERS:
            drv = _driver(kind, binary)
            if drv is not None:
                drv.set_page_load_timeout(30)
                cls.drivers[kind] = drv

    @classmethod
    def tearDownClass(cls):
        for drv in cls.drivers.values():
            _browsers.shut_down(drv)
        _browsers.stop_server(cls.server)
        cls.thread.join(timeout=10)
        cls._tmp.cleanup()

    def test_moving_onto_the_rows_button_does_not_leave_the_row(self):
        if not self.drivers:
            self.skipTest("no browser could be started on this machine")
        for kind, drv in self.drivers.items():
            with self.subTest(browser=kind):
                drv.set_window_size(900, 700)
                drv.get(self.url)
                WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                    "return !!(window.WD && window.recordHover);"))
                row = drv.find_element(By.ID, "row")
                btn = drv.find_element(By.ID, "btn")
                away = drv.find_element(By.ID, "away")

                # Onto the row to the right of the button, then onto the
                # button, then back onto the row.
                ActionChains(drv).move_to_element_with_offset(row, 150, 0).perform()
                ActionChains(drv).move_to_element(btn).perform()
                time.sleep(0.1)
                on_button = drv.execute_script("return hovered;")
                ActionChains(drv).move_to_element_with_offset(row, 150, 0).perform()
                time.sleep(0.1)
                back_on_row = drv.execute_script("return hovered;")
                ActionChains(drv).move_to_element(away).perform()
                time.sleep(0.1)
                events = drv.execute_script("return events;")

                self.assertEqual(on_button, "seg-1", events)
                self.assertEqual(back_on_row, "seg-1", events)
                self.assertEqual(events, ["mouseenter@row", "mouseleave@row"])


if __name__ == "__main__":
    unittest.main()
