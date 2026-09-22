"""The Change / Audit report, driven in a real browser from two real files.

Everything in ``test_change_audit_compare`` and ``test_change_audit_renders``
slices functions out of report.js and calls them. That settles what they
return, and nothing at all about whether picking the report and choosing a
second file reaches them. The card was "Coming soon" for a long time, and the
gallery refuses to open a card in that state, so "the renderer works" and "you
can get to the renderer" are genuinely different claims.

So: two synthetic .esx files, the second dropped on the real drop zone, the
report chosen through the real gallery, and the second file handed to the real
``#baselineInput`` with a real change event. The assertions read the rendered
document out of the page.

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
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: An unusual port, and a different one from every other browser test here, so
#: two of them running at once cannot collide. 8675 is his own instance and is
#: never bound.
PORT_HINT = 8879

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

FLOOR_ID = "30000000-0000-4000-8000-00000000000a"
IMAGE_ID = "40000000-0000-4000-8000-00000000000a"

# A 1x1 PNG. The overlay needs an image to draw on; what it shows does not
# matter, only that the plan renders at all.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _ap(ap_id, name, x, y):
    return {"id": ap_id, "name": name, "vendor": "Vendor", "model": "Model-X",
            "location": {"floorPlanId": FLOOR_ID, "coord": {"x": x, "y": y}}}


def _radio(ap_id):
    return {"id": "r-" + ap_id, "accessPointId": ap_id,
            "radioTechnology": "IEEE802_11", "antennaDirection": 90.0,
            "antennaTilt": -10.0, "antennaHeight": 3.0,
            "antennaMounting": "CEILING", "antennaTypeId": "ant-1"}


def _write_esx(path: Path, name: str, aps: list) -> Path:
    members = {
        "project.json": {"project": {"id": "cmp-1", "name": name}},
        "floorPlans.json": {"floorPlans": [{
            "id": FLOOR_ID, "name": "Level 1", "width": 800.0, "height": 600.0,
            "metersPerUnit": 0.05, "imageId": IMAGE_ID,
            "cropMinX": 0.0, "cropMinY": 0.0, "cropMaxX": 800.0, "cropMaxY": 600.0,
            "gpsReferencePoints": [],
        }]},
        "images.json": {"images": [{"id": IMAGE_ID, "imageFormat": "PNG",
                                    "resolutionWidth": 800.0,
                                    "resolutionHeight": 600.0}]},
        "accessPoints.json": {"accessPoints": aps},
        "simulatedRadios.json": {"simulatedRadios": [_radio(a["id"]) for a in aps]},
        "antennaTypes.json": {"antennaTypes": [{"id": "ant-1", "name": "Panel 30"}]},
        "buildings.json": {"buildings": []},
        "buildingFloors.json": {"buildingFloors": []},
        "notes.json": {"notes": []},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for member, doc in members.items():
            z.writestr(member, json.dumps(doc, indent=1))
        z.writestr("image-" + IMAGE_ID, PNG_1X1)
    return path


#: 0.05 m per pixel, so the 100 px move below is five metres.
BEFORE_APS = [
    _ap("a1", "AP-101", 100, 100),
    _ap("a2", "AP-102", 300, 200),
    _ap("gone", "AP-199", 600, 400),
]
AFTER_APS = [
    _ap("a1", "AP-101", 100, 100),          # untouched
    _ap("a2", "AP-102", 400, 200),          # moved five metres
    _ap("new", "AP-200", 500, 500),         # added
]


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
    """web/ as files, /api/* as JSON.

    Never ``server.py``: running that opens a real browser window on his
    desktop that nobody closes, and a day of sessions doing it left 307 Firefox
    processes holding 22.5 GB.

    Answering ``settings/get`` is load-bearing rather than scaffolding. With it
    refused the page decides it is the hosted build, ``settingsAvailable`` stays
    false, and whole server-backed paths are skipped - which is how a browser
    test once reported a passing page in all three engines while the feature
    under test was never reached.
    """

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
        try:
            json.loads(self.rfile.read(length) or b"{}") if length else {}
        except ValueError:
            pass
        action = self.path[len("/api/"):]
        if action == "settings/get":
            self._json({"ok": True, "settings": {"report": {}, "aprename": {}}})
        elif action == "report/find_folder":
            self._json({"ok": False, "reason": "not_found"})
        else:
            self._json({"ok": True})

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._json({"ok": True, "exists": False})
            return
        super().do_GET()


#: Drop the "after" file on the real drop zone, then choose the report.
OPEN_JS = """
var done = arguments[arguments.length - 1];
var bytes = Uint8Array.from(atob(arguments[0]), function (c) { return c.charCodeAt(0); });
var file = new File([bytes], arguments[1], { type: 'application/octet-stream' });
var dt = new DataTransfer();
dt.items.add(file);
document.getElementById('dropzone').dispatchEvent(
  new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
setTimeout(function () {
  // The real journey: pick the report, then walk on to the step that renders
  // it. The document is built at Review, not at Configure.
  window.selectReport('audit');
  window.goStage('review');
  setTimeout(function () { done(document.getElementById('reportCanvas').innerText); }, 800);
}, 2500);
"""

#: Hand the "before" file to the real input and fire the real change event.
BASELINE_JS = """
var done = arguments[arguments.length - 1];
var bytes = Uint8Array.from(atob(arguments[0]), function (c) { return c.charCodeAt(0); });
var file = new File([bytes], arguments[1], { type: 'application/octet-stream' });
var dt = new DataTransfer();
dt.items.add(file);
var input = document.getElementById('baselineInput');
input.files = dt.files;
input.dispatchEvent(new Event('change', { bubbles: true }));
setTimeout(function () {
  done(JSON.stringify({
    canvas: document.getElementById('reportCanvas').innerText,
    html: document.getElementById('reportCanvas').innerHTML.slice(0, 200000),
    panel: (document.getElementById('reportOpts') || document.body).innerText,
  }));
}, 2500);
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheReportCanBeReachedAndUsedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-audit-browser-"))
        # Registered with the thing it cleans up rather than in tearDownClass,
        # so the two cannot be separated: the suite leaked 116 temp directories
        # a run before that rule existed.
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        before = _write_esx(cls.tmp / "Site - design.esx", "Design", BEFORE_APS)
        after = _write_esx(cls.tmp / "Site - as built.esx", "As built", AFTER_APS)
        cls.before_b64 = base64.b64encode(before.read_bytes()).decode("ascii")
        cls.after_b64 = base64.b64encode(after.read_bytes()).decode("ascii")
        cls.port = _free_port(PORT_HINT)
        cls.httpd = ThreadingHTTPServer(
            ("127.0.0.1", cls.port), partial(_StubApi, directory=str(WEB)))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d/report.html" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    @staticmethod
    def _driver(kind, binary):
        """A headless driver, or None when it will not start - so one missing
        browser cannot fail a machine that has the other two, and CI (which has
        none of the three at these paths) skips rather than fails."""
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
                yield kind, driver
            finally:
                _browsers.shut_down(driver)
        if not started:
            self.skipTest("none of Chrome, Edge or Firefox could be started")

    def _run(self, driver):
        driver.get(self.url)
        time.sleep(1.2)
        driver.set_script_timeout(90)
        empty = driver.execute_async_script(
            OPEN_JS, self.after_b64, "Site - as built.esx")
        loaded = json.loads(driver.execute_async_script(
            BASELINE_JS, self.before_b64, "Site - design.esx"))
        return empty, loaded

    def test_the_whole_path_works_in_every_browser(self):
        """One test doing the whole journey, deliberately.

        Each browser costs a page load, two file parses and two renders, so
        splitting this into six tests would mean six launches per engine for
        the same evidence.
        """
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                empty, loaded = self._run(driver)

                # 1. The card opens at all. It refused to while it was marked
                #    "Coming soon", and selectReport returns early on that.
                self.assertTrue(
                    empty.strip(),
                    f"{kind}: choosing the report rendered nothing at all")

                # 2. With no second file it says what to do, and names the
                #    control that does it.
                self.assertIn("Choose the earlier .esx", empty,
                              f"{kind}: the empty state does not name the picker")

                # 3. After choosing one, it is a document about both files.
                canvas = loaded["canvas"]
                self.assertIn("Site - as built.esx", canvas, f"{kind}: no after file")
                self.assertIn("Site - design.esx", canvas, f"{kind}: no before file")

                # 4. The three findings reach the page.
                self.assertIn("AP-102", canvas, f"{kind}: the moved AP is missing")
                self.assertIn("AP-200", canvas, f"{kind}: the added AP is missing")
                self.assertIn("AP-199", canvas, f"{kind}: the removed AP is missing")
                self.assertIn("Moved", canvas, f"{kind}: nothing says it moved")
                # 100 px at 0.05 m/px is 5 m, which is 16.4 ft.
                self.assertIn("16.4 ft", canvas,
                              f"{kind}: the distance is wrong or missing")

                # 5. The untouched one is counted, not listed as changed.
                self.assertIn("Unchanged", canvas, f"{kind}: no unchanged count")

                # 6. The overlay was drawn on the plan.
                self.assertIn("rep-aud-", loaded["html"],
                              f"{kind}: no overlay marks on the plan")

                # 7. The options panel shows which file was chosen, so the
                #    question "what am I comparing against" is answered where
                #    the control is.
                self.assertIn("Site - design.esx", loaded["panel"],
                              f"{kind}: the panel does not name the chosen file")

    def test_a_file_that_is_not_an_esx_is_refused_with_a_reason(self):
        """Refused at the picker, not accepted and then rendered as nothing."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                driver.get(self.url)
                time.sleep(1.2)
                driver.set_script_timeout(90)
                driver.execute_async_script(
                    OPEN_JS, self.after_b64, "Site - as built.esx")
                panel = driver.execute_async_script(r"""
                  var done = arguments[arguments.length - 1];
                  var dt = new DataTransfer();
                  dt.items.add(new File(['not a project'], 'notes.txt',
                                        { type: 'text/plain' }));
                  var input = document.getElementById('baselineInput');
                  input.files = dt.files;
                  input.dispatchEvent(new Event('change', { bubbles: true }));
                  setTimeout(function () {
                    done((document.getElementById('reportOpts') || document.body).innerText
                         + '\n---\n'
                         + document.getElementById('reportCanvas').innerText);
                  }, 1500);
                """)
                self.assertIn("not an .esx", panel,
                              f"{kind}: a non-project file was taken silently")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
