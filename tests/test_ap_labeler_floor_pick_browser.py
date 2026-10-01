"""AP Labeler renames only the floors it was asked to, driven in a real browser.

Adding one floor to a labelled project and labelling it renamed every floor.
The only control near the question was Scope, whose "Per Floor" read as
"rename per floor" and only ever meant "restart the counter on each floor". So
there are two controls now: **Floors to rename** (whole project, this floor
only, or chosen floors) and **Numbering** (continuous or restart each floor).
The project's own names also decide the numbering when they show it: a new
floor on a project numbered per floor starts at 001, not where the floor below
left off.

Every assertion reads the names back out of the ``.esx`` the Download button
builds. That archive is what he opens in Ekahau, and a preview that looks right
over a download that renames every floor anyway is the failure this replaces.

Served by ``http.server`` over ``web/``, never ``server.py``. Chrome, Edge and
Firefox, per the standing rule.
"""
from __future__ import annotations

from tests import browsers as _browsers

import base64
import contextlib
import io
import json
import socket
import threading
import time
import unittest
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: Not 8675, which is his own running instance.
PORT_HINT = 8931

BROWSERS = _browsers.triple()

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False


FLOORS = [("fa", "01 - Level One"), ("fb", "02 - Level Two"), ("fc", "03 - Level Three")]
PLAN_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">'
            b'<rect x="50" y="50" width="700" height="500" fill="none" stroke="#000"/></svg>')


def _fixture() -> bytes:
    """Two floors already labelled per floor, and a third just added with
    Ekahau's placeholder names. Every name is invented.

    The finished floors are numbered right to left, against the walk the
    Labeler would take. Numbered its way, renaming them again would reproduce
    the same names, and a test that only a changed name can fail would pass
    with the floor choice ignored entirely.
    """
    aps, n = [], 0
    for fi, (fid, _) in enumerate(FLOORS):
        for k in range(4):
            n += 1
            name = (f"SITE1-{fi + 1:02d}-AP{4 - k:03d}" if fid != "fc"
                    else f"Simulated AP-{n}")
            aps.append({"id": f"ap{n}", "name": name,
                        "location": {"floorPlanId": fid,
                                     "coord": {"x": 100 + 150 * k, "y": 150 + 80 * k}}})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": f, "name": nm, "width": 800, "height": 600, "imageId": "i" + f}
            for f, nm in FLOORS]}))
        z.writestr("images.json", json.dumps({"images": [
            {"id": "i" + f, "imageFormat": "SVG"} for f, _ in FLOORS]}))
        for f, _ in FLOORS:
            z.writestr("image-i" + f, PLAN_SVG)
        z.writestr("accessPoints.json", json.dumps({"accessPoints": aps}))
        z.writestr("project.json", json.dumps({"project": {"name": "Invented"}}))
    return buf.getvalue()


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
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if self.path == "/api/settings/get":
            self._json({"ok": True, "settings": {"aprename": {}}})
        else:
            self._json({"ok": True})

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._json({"ok": True})
            return
        super().do_GET()


#: Waits for the page to be wired before dropping, then for the floors to
#: appear, rather than for fixed times. Fixed sleeps (1.2 s, then 2.5 s) lost
#: the drop on a cold Edge start in CI with four workers sharing the runner:
#: the drop fired before ap-rename.js had bound its handler, and the floors
#: never came. Each wait is still bounded.
DROP_JS = r"""
var done = arguments[arguments.length - 1];
var b64 = arguments[0];
var started = Date.now();
function count() { return document.querySelectorAll('#arFloorTabs .ar-floor-tab').length; }
function ready() {
  return document.readyState === 'complete' && typeof window.arDownload === 'function';
}
(function waitReady() {
  if (!ready()) {
    if (Date.now() - started > 20000) { done(-1); return; }
    setTimeout(waitReady, 100);
    return;
  }
  var bytes = Uint8Array.from(atob(b64), function (c) { return c.charCodeAt(0); });
  var file = new File([bytes], 'floors-fixture.esx', { type: 'application/octet-stream' });
  var dt = new DataTransfer();
  dt.items.add(file);
  document.getElementById('dropzone').dispatchEvent(
    new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
  (function waitFloors() {
    var n = count();
    if (n >= 3 || Date.now() - started > 30000) { done(n); return; }
    setTimeout(waitFloors, 100);
  })();
})();
"""

#: Presses Download and hands back the names in the archive it built.
#: The anchor click is swallowed so nothing lands on anybody's disk.
DOWNLOAD_JS = r"""
var done = arguments[arguments.length - 1];
var blob = null;
URL.createObjectURL = function (b) { blob = b; return 'blob:captured'; };
HTMLAnchorElement.prototype.click = function () {};
document.getElementById('arDownloadBtn').click();
var tries = 0;
(function wait() {
  if (!blob) {
    if (++tries > 100) { done({ error: 'no download was built' }); return; }
    setTimeout(wait, 100);
    return;
  }
  JSZip.loadAsync(blob).then(function (z) {
    return z.file('accessPoints.json').async('string');
  }).then(function (s) {
    var out = {};
    JSON.parse(s).accessPoints.forEach(function (a) { out[a.id] = a.name; });
    done({ names: out });
  }, function (e) { done({ error: String(e) }); });
})();
"""


def _click(driver, selector):
    driver.execute_script(
        "document.querySelector(arguments[0]).click();", selector)
    time.sleep(0.4)


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class OnlyTheChosenFloorsAreRenamedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b64 = base64.b64encode(_fixture()).decode("ascii")
        cls.port = _free_port(PORT_HINT)
        cls.httpd = ThreadingHTTPServer(
            ("127.0.0.1", cls.port), partial(_StubApi, directory=str(WEB)))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/ap-rename.html" % cls.port

    @classmethod
    def tearDownClass(cls):
        _browsers.stop_server(cls.httpd)

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
                driver.set_window_size(1600, 1000)
                driver.set_script_timeout(60)
                driver.get(self.url)
                tabs = driver.execute_async_script(DROP_JS, self.b64)
                self.assertEqual(tabs, 3, f"{kind}: the project did not load")
                yield kind, driver
            finally:
                _browsers.shut_down(driver)
        if not started:
            self.skipTest(_browsers.why_missing())

    def _download(self, driver):
        got = driver.execute_async_script(DOWNLOAD_JS)
        self.assertNotIn("error", got, got.get("error"))
        return got["names"]

    def _floor(self, names, fid):
        idx = [i for i, (f, _) in enumerate(FLOORS) if f == fid][0]
        return [names["ap%d" % (idx * 4 + k + 1)] for k in range(4)]

    def test_this_floor_only_leaves_every_other_floor_exactly_as_it_was(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                _click(driver, '.ar-floor-tab[data-fp="fc"]')
                _click(driver, '#arFloorPickTabs [data-arg="current"]')
                names = self._download(driver)
                self.assertEqual(self._floor(names, "fa"),
                                 ["SITE1-01-AP004", "SITE1-01-AP003",
                                  "SITE1-01-AP002", "SITE1-01-AP001"])
                self.assertEqual(self._floor(names, "fb"),
                                 ["SITE1-02-AP004", "SITE1-02-AP003",
                                  "SITE1-02-AP002", "SITE1-02-AP001"])
                new = self._floor(names, "fc")
                self.assertTrue(all(n.startswith("SITE1-03-AP") for n in new), new)
                # The project restarts per floor, so the new floor does too.
                self.assertEqual(sorted(new),
                                 ["SITE1-03-AP001", "SITE1-03-AP002",
                                  "SITE1-03-AP003", "SITE1-03-AP004"])

    def test_looking_at_another_floor_does_not_move_this_floor_only(self):
        """Checking a finished floor after choosing must not quietly retarget
        the download at the floor on screen."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                _click(driver, '.ar-floor-tab[data-fp="fc"]')
                _click(driver, '#arFloorPickTabs [data-arg="current"]')
                _click(driver, '.ar-floor-tab[data-fp="fa"]')
                head = driver.execute_script(
                    "return document.getElementById('arPreviewHead').textContent;")
                self.assertIn("not being renamed", head)
                names = self._download(driver)
                self.assertEqual(self._floor(names, "fa")[0], "SITE1-01-AP004")
                self.assertTrue(self._floor(names, "fc")[0].startswith("SITE1-03-AP"))

    def test_chosen_floors_are_the_ticked_ones(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                # Start from the new floor, then tick none and tick back
                # through the real checkboxes.
                _click(driver, '.ar-floor-tab[data-fp="fc"]')
                _click(driver, '#arFloorPickTabs [data-arg="chosen"]')
                _click(driver, '.ar-fp-bulk [data-arg-json="false"]')
                empty = self._download_or_none(driver)
                self.assertIsNone(empty, "a download was built with no floors ticked")
                _click(driver, '#arFloorPickList input[data-arg="fc"]')
                names = self._download(driver)
                self.assertEqual(self._floor(names, "fa")[0], "SITE1-01-AP004")
                self.assertEqual(self._floor(names, "fb")[0], "SITE1-02-AP004")
                self.assertTrue(self._floor(names, "fc")[0].startswith("SITE1-03-AP"))

    def _download_or_none(self, driver):
        disabled = driver.execute_script(
            "return document.getElementById('arDownloadBtn').disabled;")
        if disabled:
            return None
        return self._download(driver)

    def test_numbering_follows_the_project(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                active = driver.execute_script(
                    "var t = document.querySelector('#arScopeTabs .ar-scope-tab.active');"
                    "return t && t.getAttribute('data-scope');")
                self.assertEqual(active, "perFloor")


if __name__ == "__main__":
    unittest.main()
