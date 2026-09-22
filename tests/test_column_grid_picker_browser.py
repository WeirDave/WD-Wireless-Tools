"""The column grid picker, driven by clicking it in a real browser.

Everything else about this feature is checked by calling functions. That
settles the arithmetic and the markup and nothing at all about whether two
clicks on a floor plan become a saved calibration - which is the entire
feature, and the shape this repository keeps shipping broken: a control that
renders perfectly and does nothing.

So this opens the picker, clicks the plan twice at known pixel positions,
types the two labels, and asserts on what reaches the server. The click-to-plan
coordinate conversion is the part with no other coverage: it runs through
`getSvgScale`, the zoom and the pan, and an error there puts every AP in the
wrong bay while every other test stays green.

`WD.api` is stubbed, which is the seam the handlers use, so a test can never
reach his disk. The page is served by `http.server` over `web/`, never
`server.py`, which opens a browser window nobody closes.

Chrome, Edge and Firefox, per the standing rule.
"""
from __future__ import annotations

from tests import browsers as _browsers

import base64
import contextlib
import json
import shutil
import socket
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: An unusual port, and not 8675, which is his own running instance.
PORT_HINT = 8869

BROWSERS = [
    ("firefox", _browsers.find("firefox")),
    ("chrome", _browsers.find("chrome")),
    ("edge", _browsers.find("edge")),
]

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False


def _free_port(start):
    for port in range(start, start + 40):
        with contextlib.closing(socket.socket()) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port near %d" % start)


class _StubApi(SimpleHTTPRequestHandler):
    """web/ as files, /api/* as JSON. settings/get is what turns
    settingsAvailable on, and without it the page takes itself for the hosted
    build and the picker refuses to open at all."""

    def log_message(self, *a):
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if self.path == "/api/settings/get":
            self._json({"ok": True, "settings": {"report": {}, "aprename": {}}})
        elif self.path.startswith("/api/report/grid/"):
            self._json({"ok": True, "floors": {}})
        else:
            self._json({"ok": True})

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._json({"ok": True, "exists": False})
            return
        super().do_GET()


#: Drops the project, opens the picker, and records what the handlers send.
#: The real page code runs throughout; only WD.api is replaced.
SETUP_JS = r"""
var done = arguments[arguments.length - 1];
var bytes = Uint8Array.from(atob(arguments[0]), function (c) { return c.charCodeAt(0); });
var file = new File([bytes], 'grid-fixture.esx', { type: 'application/octet-stream' });
var dt = new DataTransfer();
dt.items.add(file);
document.getElementById('dropzone').dispatchEvent(
  new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
setTimeout(function () {
  window.__sent = [];
  var real = window.WD.api;
  window.WD.api = function (action, body) {
    window.__sent.push({ action: action, body: body });
    if (action === 'report/grid/save') {
      var floors = {};
      floors[body.floorId] = body.grid;
      return Promise.resolve({ ok: true, floors: floors });
    }
    if (action === 'report/grid/clear') return Promise.resolve({ ok: true, floors: {} });
    return real(action, body);
  };
  window.openGridRef();
  var modal = document.getElementById('gridRefModal');
  done({ opened: !!modal && !modal.hidden,
         floors: document.getElementById('gridRefFloorSelect').options.length });
}, 2500);
"""

#: One click at a fraction of the **plan**, dispatched as a real MouseEvent at
#: real client coordinates so the handler's own conversion runs.
#:
#: The fraction is of the drawn plan, not of the element box, and the two are
#: not the same: the SVG fills its container while the plan keeps its aspect
#: inside it, so a 4:3 plan in a 2.6:1 box is letterboxed with wide empty
#: margins left and right. Clicking at 20% of the *box* lands outside the plan
#: entirely - measured at -48% of the plan in Firefox and -137% in Chrome,
#: which is what the first version of this test was asserting against.
#:
#: The placement below is `preserveAspectRatio="xMidYMid meet"` written out
#: longhand, deliberately independent of the implementation - which uses
#: `getScreenCTM` - so the two cannot agree by sharing a mistake.
CLICK_JS = r"""
var which = arguments[0], fx = arguments[1], fy = arguments[2];
window.gridRefPick(which);
var svg = document.getElementById('gridRefSvg');
var box = svg.getBoundingClientRect();
var dw = parseFloat(svg.getAttribute('data-dw'));
var dh = parseFloat(svg.getAttribute('data-dh'));
var imgAspect = dw / dh, boxAspect = box.width / box.height;
var rw, rh;
if (imgAspect > boxAspect) { rw = box.width; rh = box.width / imgAspect; }
else { rh = box.height; rw = box.height * imgAspect; }
var originX = box.left + (box.width - rw) / 2;
var originY = box.top + (box.height - rh) / 2;
var x = originX + rw * fx, y = originY + rh * fy;
document.getElementById('gridRefPreviewContainer').dispatchEvent(
  new MouseEvent('click', { clientX: x, clientY: y, bubbles: true,
                            cancelable: true, button: 0 }));
return { x: x, y: y, renderedW: rw, renderedH: rh };
"""

TYPE_JS = r"""
var which = arguments[0], text = arguments[1];
var input = document.getElementById('gridRefLabel' + which.toUpperCase());
input.value = text;
window.gridRefLabelChanged(which, input);
return document.getElementById('gridRefStatus').textContent;
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class ThePickerSavesWhatWasClicked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.esx_factory import make_esx
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-gridpick-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        esx = make_esx(cls.tmp / "grid-fixture.esx")
        cls.b64 = base64.b64encode(esx.read_bytes()).decode("ascii")
        cls.port = _free_port(PORT_HINT)
        cls.httpd = ThreadingHTTPServer(
            ("127.0.0.1", cls.port), partial(_StubApi, directory=str(WEB)))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/report.html" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

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

    def _each_browser(self):
        started = 0
        for kind, binary in BROWSERS:
            driver = self._driver(kind, binary)
            if driver is None:
                continue
            started += 1
            try:
                driver.set_window_size(1600, 1200)
                driver.set_script_timeout(60)
                driver.get(self.url)
                time.sleep(1.2)
                opened = driver.execute_async_script(SETUP_JS, self.b64)
                self.assertTrue(opened["opened"],
                                f"{kind}: the picker did not open")
                self.assertGreaterEqual(opened["floors"], 1,
                                        f"{kind}: no floors offered")
                yield kind, driver
            finally:
                _browsers.shut_down(driver)
        if not started:
            self.skipTest("none of Firefox, Chrome or Edge would start")

    def _calibrate(self, driver):
        """Two clicks and two labels, the way a person does it."""
        driver.execute_script(CLICK_JS, "a", 0.2, 0.2)
        driver.execute_script(TYPE_JS, "a", "A-1")
        driver.execute_script(CLICK_JS, "b", 0.8, 0.8)
        return driver.execute_script(TYPE_JS, "b", "E-5")

    def test_two_clicks_and_two_labels_reach_the_server(self):
        """The whole feature. The button is enabled only when the grid solves,
        and what it sends is what was clicked."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._calibrate(driver)
                save = driver.find_element("id", "gridRefSaveBtn")
                self.assertFalse(save.get_attribute("disabled"),
                                 "Save stayed disabled on a grid that solves")
                driver.execute_script("window.saveGridRefFloor();")
                time.sleep(0.6)
                sent = driver.execute_script(
                    "return window.__sent.filter(c => c.action === 'report/grid/save');")
                self.assertTrue(sent, "nothing was sent to the server")
                grid = sent[0]["body"]["grid"]
                self.assertEqual(grid["a"]["col"], 0)
                self.assertEqual(grid["a"]["row"], 1)
                self.assertEqual(grid["b"]["col"], 4)
                self.assertEqual(grid["b"]["row"], 5)
                self.assertEqual(grid["lettersAxis"], "x")
                self.assertTrue(sent[0]["body"]["floorId"],
                                "the floor was not identified")

    def test_the_clicked_point_lands_where_it_was_clicked(self):
        """The conversion from a click to a plan coordinate has no other
        coverage, and an error in it puts every AP in the wrong bay while
        every other test stays green. Clicking at 20% and 80% of the rendered
        plan must come back as roughly 20% and 80% of its width and height."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._calibrate(driver)
                driver.execute_script("window.saveGridRefFloor();")
                time.sleep(0.6)
                sent = driver.execute_script(
                    "return window.__sent.filter(c => c.action === 'report/grid/save');")
                grid = sent[0]["body"]["grid"]
                # The fixture's own dimensions. `proj` lives inside the
                # page's IIFE and is deliberately not on window, so this is
                # asserted against what the fixture was built with rather than
                # against what the page happens to report.
                width, height = 1600, 1200
                for point, want in ((grid["a"], 0.2), (grid["b"], 0.8)):
                    self.assertAlmostEqual(point["x"] / width, want, delta=0.04)
                    self.assertAlmostEqual(point["y"] / height, want, delta=0.04)

    def test_an_unsolvable_pair_cannot_be_saved_and_says_why(self):
        """Two points on one lettered line. The button stays dead and the
        reason is on screen - a reference that is quietly wrong is the failure
        this whole feature is written around."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                driver.execute_script(CLICK_JS, "a", 0.2, 0.2)
                driver.execute_script(TYPE_JS, "a", "C-1")
                driver.execute_script(CLICK_JS, "b", 0.8, 0.8)
                status = driver.execute_script(TYPE_JS, "b", "C-5")
                save = driver.find_element("id", "gridRefSaveBtn")
                self.assertTrue(save.get_attribute("disabled"),
                                "an unsolvable pair could be saved")
                self.assertIn("same lettered line", status)

    def test_switching_the_letters_axis_changes_the_saved_grid(self):
        """Two points cannot say which way the letters run, so the switch is
        the answer. If it did not reach the payload it would be decoration."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._calibrate(driver)
                driver.execute_script(
                    "var s = document.getElementById('gridRefAxis');"
                    "s.value = 'y'; window.gridRefAxisChanged(s);")
                driver.execute_script("window.saveGridRefFloor();")
                time.sleep(0.6)
                sent = driver.execute_script(
                    "return window.__sent.filter(c => c.action === 'report/grid/save');")
                self.assertEqual(sent[0]["body"]["grid"]["lettersAxis"], "y")

    def test_the_grid_is_drawn_over_the_plan_once_it_solves(self):
        """The drawn grid is the only check on a rotated or interrupted grid,
        so it has to actually appear. Nothing is drawn before it solves."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                before = driver.execute_script(
                    "return document.querySelectorAll('#gridRefSvg .grid-ref-lines line').length;")
                self.assertEqual(before, 0, "a grid was drawn before it solved")
                self._calibrate(driver)
                after = driver.execute_script(
                    "return document.querySelectorAll('#gridRefSvg .grid-ref-lines line').length;")
                self.assertGreater(after, 4, "no grid was drawn")
                labels = driver.execute_script(
                    "return Array.from(document.querySelectorAll("
                    "'#gridRefSvg .grid-ref-labels text')).map(e => e.textContent);")
                self.assertIn("A", labels)
                self.assertIn("1", labels)
