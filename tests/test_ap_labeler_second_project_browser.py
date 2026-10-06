"""AP Labeler, driven in a real browser: a second project, the start box, the
archive it writes.

* Opening a second project kept the first one's adopted scheme. A project
  named Ekahau's way (AP-1, AP-2) has nothing to adopt, so it was offered the
  previous building's site text while the note said his own pattern had been
  left as it was.
* Adopting a project whose floor column reads F1 / F2 rewrote it to 01 / 02 on
  every AP.
* The counter's start box was rebuilt on every keystroke, so "101" could not
  be typed, and 0 turned into 1.
* The download was written uncompressed, about eleven times the size.

Every assertion reads the archive the Download button builds, or the page as
it stands after real key presses. Served by ``http.server`` over ``web/``,
never ``server.py``; the settings endpoint is stubbed to hand back a saved
default pattern. Every name is invented.
"""
from __future__ import annotations

from tests import browsers as _browsers

import base64
import io
import json
import threading
import time
import unittest
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

from tests.test_ap_labeler_floor_pick_browser import _ExclusiveServer

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

BROWSERS = _browsers.triple()

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import Select
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False


PLAN_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">'
            b'<rect x="50" y="50" width="700" height="500" fill="none" stroke="#000"/></svg>')

#: His saved default pattern, as the settings endpoint returns it.
DEFAULTS = {
    "mode": "structured", "scope": "all", "order": "proximity", "sepS": "-",
    "segments": [{"type": "text", "value": "HQZ"}, {"type": "floor"},
                 {"type": "counter", "tag": "AP", "start": 1, "digits": 3}],
}

#: A template he saved, offered in the Load template list. Invented.
TEMPLATE = {
    "name": "Invented template", "mode": "structured", "scope": "all",
    "order": "proximity", "sepS": "-",
    "segments": [{"type": "text", "value": "TPL"}, {"type": "floor"},
                 {"type": "counter", "tag": "AP", "start": 1, "digits": 3}],
}

#: Long enough that every test opens its project before the defaults land.
SETTINGS_DELAY = 1.5

#: Longer than the Labeler waits for the defaults (5 s) before it opens a
#: project anyway, so the defaults land on a project already on screen.
SETTINGS_LATE = 6.5

FLOORS = [("fa", "Level 1"), ("fb", "Level 2")]


def _esx(names_by_floor) -> bytes:
    """One row of APs per floor, left to right in name order, so the
    Labeler's own walk numbers them in the order they are already named."""
    aps = []
    for (fid, _), names in zip(FLOORS, names_by_floor):
        for k, name in enumerate(names):
            aps.append({"id": f"{fid}-{k + 1}", "name": name,
                        "location": {"floorPlanId": fid,
                                     "coord": {"x": 100 + 150 * k, "y": 300}}})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": f, "name": nm, "width": 800, "height": 600, "imageId": "i" + f}
            for f, nm in FLOORS]}))
        z.writestr("images.json", json.dumps({"images": [
            {"id": "i" + f, "imageFormat": "SVG"} for f, _ in FLOORS]}))
        for f, _ in FLOORS:
            z.writestr("image-i" + f, PLAN_SVG)
        z.writestr("accessPoints.json", json.dumps({"accessPoints": aps}))
        z.writestr("notes.json", json.dumps({"notes": [
            {"id": f"n{i}", "text": "invented note text " * 8} for i in range(200)]}))
        z.writestr("project.json", json.dumps({"project": {"name": "Invented"}}))
    return buf.getvalue()


#: A building already named to its own scheme, floor column F1 / F2.
SCHEMED = [[f"QRX-BX-F{fl}-AP0{k}" for k in range(1, 4)] for fl in (1, 2)]
#: A fresh survey: Ekahau's placeholders, nothing to adopt.
PLACEHOLDER = [["AP-1", "AP-2"], ["AP-3", "AP-4"]]


class _StubApi(SimpleHTTPRequestHandler):
    delay = SETTINGS_DELAY

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
            # His saved pattern arrives late on purpose. On a slow machine the
            # project was read before it landed, and the late defaults then
            # wrote over the scheme adopted from the project - seen once in
            # CI's Firefox on Windows. The delay makes that race certain.
            time.sleep(self.delay)
            self._json({"ok": True, "settings": {"aprename": {
                "defaults": DEFAULTS, "templates": [TEMPLATE]}}})
        else:
            self._json({"ok": True})

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._json({"ok": True})
            return
        super().do_GET()


#: Opens a project through the file input - the path "open another" takes -
#: and waits until it is loaded: badge named, floors drawn, plan on screen.
OPEN_JS = r"""
var done = arguments[arguments.length - 1];
var b64 = arguments[0], fname = arguments[1];
var started = Date.now();
function ready() {
  return document.readyState === 'complete' && typeof window.arDownload === 'function'
    && window.__aprename;
}
(function waitReady() {
  if (!ready()) {
    if (Date.now() - started > 20000) { done({ error: 'page never ready' }); return; }
    setTimeout(waitReady, 100);
    return;
  }
  var bytes = Uint8Array.from(atob(b64), function (c) { return c.charCodeAt(0); });
  var dt = new DataTransfer();
  dt.items.add(new File([bytes], fname, { type: 'application/octet-stream' }));
  var input = document.getElementById('fileInput');
  input.files = dt.files;
  input.dispatchEvent(new Event('change', { bubbles: true }));
  (function waitLoaded() {
    var badge = document.getElementById('fileBadge').textContent;
    var tabs = document.querySelectorAll('#arFloorTabs .ar-floor-tab').length;
    var shown = !document.getElementById('arPlanBox').hidden;
    if (badge === fname && tabs === 2 && shown) { setTimeout(function () { done({ ok: 1 }); }, 300); return; }
    if (Date.now() - started > 30000) {
      done({ error: 'not loaded: ' + document.getElementById('arNoPlan').textContent });
      return;
    }
    setTimeout(waitLoaded, 100);
  })();
})();
"""

#: Presses Download and hands back the archive's bytes. The anchor click is
#: swallowed so nothing lands on anybody's disk.
DOWNLOAD_JS = r"""
var done = arguments[arguments.length - 1];
var blob = null;
URL.createObjectURL = function (b) { blob = b; return 'blob:captured'; };
HTMLAnchorElement.prototype.click = function () {};
document.getElementById('arDownloadBtn').click();
var tries = 0;
(function wait() {
  if (!blob) {
    if (++tries > 150) { done({ error: 'no download was built' }); return; }
    setTimeout(wait, 100);
    return;
  }
  var r = new FileReader();
  r.onload = function () { done({ b64: String(r.result).split(',')[1] }); };
  r.onerror = function () { done({ error: 'could not read the download' }); };
  r.readAsDataURL(blob);
})();
"""


class _InABrowser:
    stub = _StubApi

    @classmethod
    def setUpClass(cls):
        cls.schemed = base64.b64encode(_esx(SCHEMED)).decode("ascii")
        cls.placeholder = base64.b64encode(_esx(PLACEHOLDER)).decode("ascii")
        cls.httpd = _ExclusiveServer(
            ("127.0.0.1", 0), partial(cls.stub, directory=str(WEB)))
        cls.port = cls.httpd.server_address[1]
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
            if kind == "safari":
                return _browsers.safari_driver()
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
                yield kind, driver
            finally:
                _browsers.shut_down(driver)
        if not started:
            self.skipTest(_browsers.why_missing())

    def _open(self, driver, b64, fname):
        got = driver.execute_async_script(OPEN_JS, b64, fname)
        self.assertNotIn("error", got, got.get("error"))

    def _archive(self, driver) -> zipfile.ZipFile:
        got = driver.execute_async_script(DOWNLOAD_JS)
        self.assertNotIn("error", got, got.get("error"))
        return zipfile.ZipFile(io.BytesIO(base64.b64decode(got["b64"])))

    def _names(self, driver) -> dict:
        z = self._archive(driver)
        aps = json.loads(z.read("accessPoints.json"))["accessPoints"]
        return {a["id"]: a["name"] for a in aps}

    def _preview(self, driver) -> dict:
        return driver.execute_script(
            "var o = {}; window.__aprename.getState().preview.forEach("
            "function (it) { o[it.ap.id] = it.newName; }); return o;")


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheLabelerInABrowserTests(_InABrowser, unittest.TestCase):
    def test_an_adopted_scheme_writes_the_names_back_unchanged(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._open(driver, self.schemed, "schemed-site.esx")
                # Nothing would change, so there is nothing to download: the
                # names are read off the preview that decides the download.
                state = driver.execute_script(
                    "var S = window.__aprename.getState(), o = {};"
                    "S.preview.forEach(function (it) { o[it.ap.id] = it.newName; });"
                    "return {names: o,"
                    " disabled: document.getElementById('arDownloadBtn').disabled};")
                want = {f"{fid}-{k + 1}": n
                        for (fid, _), row in zip(FLOORS, SCHEMED)
                        for k, n in enumerate(row)}
                self.assertEqual(state["names"], want)
                self.assertTrue(state["disabled"], "Download offered with nothing to rename")

    def test_a_second_project_starts_from_his_own_pattern(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._open(driver, self.schemed, "schemed-site.esx")
                self._open(driver, self.placeholder, "fresh-survey.esx")
                names = self._names(driver)
                self.assertEqual(
                    sorted(names.values()),
                    ["HQZ-01-AP001", "HQZ-01-AP002", "HQZ-02-AP003", "HQZ-02-AP004"],
                    names)

    def test_a_template_picked_over_an_adopted_scheme_carries_to_the_next_project(self):
        """Loading a template is choosing a pattern. Over an adopted scheme it
        used to be thrown away when the next project opened, and his saved
        defaults came back in its place."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._open(driver, self.schemed, "schemed-site.esx")
                summary = driver.find_element(By.CSS_SELECTOR, ".ar-templates-detail > summary")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", summary)
                summary.click()
                Select(driver.find_element(By.ID, "arTemplateSelect")).select_by_value("0")
                time.sleep(0.3)
                self._open(driver, self.placeholder, "fresh-survey.esx")
                self.assertEqual(
                    sorted(self._preview(driver).values()),
                    ["TPL-01-AP001", "TPL-01-AP002", "TPL-02-AP003", "TPL-02-AP004"])

    def test_a_segment_typed_over_an_adopted_scheme_carries_to_the_next_project(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._open(driver, self.schemed, "schemed-site.esx")
                box = driver.find_element(
                    By.CSS_SELECTOR, '#arSegments .ar-seg-row input.ar-seg-input')
                self.assertEqual(box.get_attribute("value"), "QRX")
                box.send_keys(Keys.CONTROL, "a")
                box.send_keys("ZZQ")
                time.sleep(0.3)
                self._open(driver, self.placeholder, "fresh-survey.esx")
                names = self._preview(driver)
                self.assertEqual(len(names), 4, names)
                for name in names.values():
                    self.assertTrue(name.startswith("ZZQ-"), names)

    def _start_box(self, driver):
        boxes = driver.find_elements(By.CSS_SELECTOR, '#arSegments input[type="number"]')
        self.assertEqual(len(boxes), 1, "expected one counter start box")
        return boxes[0]

    def test_the_start_box_takes_a_whole_number_and_keeps_focus(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._open(driver, self.placeholder, "fresh-survey.esx")
                box = self._start_box(driver)
                box.click()
                box.send_keys(Keys.CONTROL, "a")
                box.send_keys(Keys.BACKSPACE)
                box.send_keys("101")
                time.sleep(0.3)
                state = driver.execute_script(
                    "var b = document.querySelector('#arSegments input[type=\"number\"]');"
                    "return {value: b.value, focused: document.activeElement === b};")
                self.assertEqual(state, {"value": "101", "focused": True})
                names = self._names(driver)
                self.assertEqual(sorted(names.values())[0], "HQZ-01-AP101", names)

    def test_a_start_of_zero_numbers_from_zero(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._open(driver, self.placeholder, "fresh-survey.esx")
                box = self._start_box(driver)
                box.click()
                box.send_keys(Keys.CONTROL, "a")
                box.send_keys("0")
                time.sleep(0.3)
                names = self._names(driver)
                self.assertEqual(sorted(names.values())[0], "HQZ-01-AP000", names)

    def test_the_download_is_compressed(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._open(driver, self.placeholder, "fresh-survey.esx")
                z = self._archive(driver)
                stored = [i.filename for i in z.infolist()
                          if i.compress_type != zipfile.ZIP_DEFLATED]
                self.assertEqual(stored, [], "written without compression")



class _LateStubApi(_StubApi):
    delay = SETTINGS_LATE


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class DefaultsThatLandAfterTheWaitTests(_InABrowser, unittest.TestCase):
    """The Labeler waits a bounded time for the saved pattern, then opens the
    project anyway. Defaults that landed after that were applied over the
    scheme already adopted from the project on screen."""
    stub = _LateStubApi

    def test_late_defaults_leave_the_adopted_scheme_and_serve_the_next_project(self):
        want = {f"{fid}-{k + 1}": n
                for (fid, _), row in zip(FLOORS, SCHEMED)
                for k, n in enumerate(row)}
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._open(driver, self.schemed, "schemed-site.esx")
                self.assertEqual(self._preview(driver), want, "not adopted at all")
                # Until the defaults have landed, then a moment more.
                landed = time.monotonic() + SETTINGS_LATE + 3
                while time.monotonic() < landed and not driver.execute_script(
                        "return document.getElementById('arTemplateSelect')"
                        ".options.length > 1;"):
                    time.sleep(0.2)
                time.sleep(0.5)
                self.assertTrue(driver.execute_script(
                    "return document.getElementById('arTemplateSelect').options.length > 1;"),
                    "the settings never arrived")
                self.assertEqual(self._preview(driver), want)
                self._open(driver, self.placeholder, "fresh-survey.esx")
                self.assertEqual(
                    sorted(self._preview(driver).values()),
                    ["HQZ-01-AP001", "HQZ-01-AP002", "HQZ-02-AP003", "HQZ-02-AP004"])


if __name__ == "__main__":
    unittest.main()
