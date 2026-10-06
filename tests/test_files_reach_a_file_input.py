"""A file given to a file input arrives, and Select All selects all, in every
browser.

Two things every browser test leans on, held to one answer in each browser:

* **A path sent to a file input.** Firefox, Chrome and Edge deliver it. In
  Safari `send_keys(path)` is accepted and nothing arrives - the page never
  sees a change - so every test that opened a project that way waited out its
  timeout on an empty page: eleven modules on the first full Safari run.
  `tests.browsers` routes it through `upload_by_script` in a Safari run, and
  this holds that what the page reads is the same in all four.
* **Select All.** Ctrl+A moves the caret to the start of the line on a Mac,
  and Safari's WebDriver does not act on Cmd+A either. Three AP Labeler tests
  used Ctrl+A, typed `101` into a box that held `1`, read `1011` in Safari and
  looked like a fault in the page. `select_all(element)` selects by script and
  the typing that follows is still real key presses.

Served by `http.server`, never `server.py`. Everything here is invented.
"""
from __future__ import annotations

from tests import browsers as _browsers

import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path

try:  # pragma: no cover - availability varies by machine
    from selenium.webdriver.common.by import By
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

PAGE = b"""<!doctype html><meta charset="utf-8"><title>files</title>
<input type="file" id="visible" multiple>
<input type="file" id="hidden" multiple style="display:none">
<input type="text" id="text" value="abc">
<script>
window.__got = {};
['visible', 'hidden'].forEach(function (id) {
  document.getElementById(id).addEventListener('change', function (e) {
    var files = Array.prototype.slice.call(e.target.files);
    window.__got[id] = { names: files.map(function (f) { return f.name; }),
                         sizes: files.map(function (f) { return f.size; }),
                         texts: [] };
    files.forEach(function (f, i) {
      var r = new FileReader();
      r.onload = function () { window.__got[id].texts[i] = r.result; };
      r.readAsText(f);
    });
  });
});
</script>"""


class _Page(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *a, **k):
        pass


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheSameThingArrivesInEveryBrowserTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = _browsers.ExclusiveServer(("127.0.0.1", 0), _Page)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/" % cls.server.server_address[1]
        cls.tmp = tempfile.TemporaryDirectory(prefix="wd-files-")
        cls.one = Path(cls.tmp.name) / "invented-one.esx"
        cls.two = Path(cls.tmp.name) / "invented-two.txt"
        cls.one.write_text("alpha beta", encoding="utf-8")
        cls.two.write_text("gamma", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        _browsers.stop_server(cls.server)
        cls.tmp.cleanup()

    def _each_browser(self):
        started = 0
        for kind, binary in _browsers.triple():
            driver = _browsers.make_driver(kind, binary)
            if driver is None:
                continue
            started += 1
            try:
                driver.set_script_timeout(30)
                driver.get(self.url)
                yield kind, driver
            finally:
                _browsers.shut_down(driver)
        if not started:
            self.skipTest(_browsers.why_missing())

    @staticmethod
    def _got(driver, which):
        for _ in range(50):
            got = driver.execute_script("return window.__got[arguments[0]] || null;", which)
            if got and len(got["texts"]) == len(got["names"]) and None not in got["texts"]:
                return got
            time.sleep(0.1)
        return got

    def test_a_path_sent_to_a_file_input_arrives(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                driver.find_element(By.ID, "visible").send_keys(str(self.one))
                got = self._got(driver, "visible")
                self.assertEqual(got, {"names": ["invented-one.esx"], "sizes": [10],
                                       "texts": ["alpha beta"]}, got)

    def test_two_paths_arrive_in_order(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                driver.find_element(By.ID, "visible").send_keys("%s\n%s" % (self.one, self.two))
                got = self._got(driver, "visible")
                self.assertEqual(got["names"], ["invented-one.esx", "invented-two.txt"], got)
                self.assertEqual(got["texts"], ["alpha beta", "gamma"], got)

    def test_a_file_given_by_script_arrives_on_a_hidden_input_too(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                _browsers.upload_by_script(driver.find_element(By.ID, "hidden"), [self.one])
                got = self._got(driver, "hidden")
                self.assertEqual(got, {"names": ["invented-one.esx"], "sizes": [10],
                                       "texts": ["alpha beta"]}, got)

    def test_select_all_selects_all_so_typing_replaces(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                box = driver.find_element(By.ID, "text")
                box.click()
                _browsers.select_all(box)
                box.send_keys("x")
                self.assertEqual(box.get_attribute("value"), "x")


if __name__ == "__main__":
    unittest.main()
