"""The saved report file name, read off a real browser after a real drop.

Everything in ``test_report_filename`` runs the name builders directly, which
settles what they return and nothing about whether anything reaches them. The
drop zone is the front page of the Report tool and the folder lookup hangs off
it, so that gap is the whole feature: written and driven only in Node, the
lookup was never called at all and the file name came out exactly as it had
before - which is what this file was written after finding.

So a synthetic .esx is dropped on the real drop zone with a real DragEvent, the
page's own handlers run, and ``document.title`` is read back. That title is the
string the browser offers in the Save-as-PDF dialog, so it is the file name in
all but name.

The server is ``http.server`` over ``web/`` and answers ``/api/*`` itself,
never ``server.py``, which opens a browser window nobody closes. Answering
``settings/get`` matters rather than being scaffolding: it is what turns
``settingsAvailable`` on, and with it refused the page treats itself as the
hosted build and skips the lookup - which is how the first run of this file
passed a broken page in all three browsers.

Chrome, Edge and Firefox, per the standing rule.
"""
from __future__ import annotations

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

#: An unusual port, and not one anybody reaches for. 8675 is his own running
#: instance and must never be bound.
PORT_HINT = 8834

BROWSERS = [
    ("firefox", r"C:\Program Files\Mozilla Firefox\firefox.exe"),
    ("chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ("edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]

SITE = "Northwind Traders - Building 4 - 1200 Fake Rd"
ESX_NAME = "B04 - PD.esx"

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
    """web/ as files, /api/* as JSON. Every call is recorded.

    ``answer`` is what ``report/find_folder`` replies with; the test sets it
    per case, so the page's own request/response path runs rather than a
    stubbed function inside it.
    """

    answer = {"ok": False, "reason": "not_found"}
    calls = []

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
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except ValueError:
            body = {}
        action = self.path[len("/api/"):]
        type(self).calls.append((action, body))
        if action == "settings/get":
            self._json({"ok": True, "settings": {"report": {}, "aprename": {}}})
        elif action == "report/find_folder":
            self._json(type(self).answer)
        else:
            self._json({"ok": True})

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._json({"ok": True, "exists": False})
            return
        super().do_GET()


#: Builds a File from bytes and drops it on the real drop zone, then reads the
#: title after the page has had time to parse and look the folder up.
DROP_JS = """
var done = arguments[arguments.length - 1];
var bytes = Uint8Array.from(atob(arguments[0]), function (c) { return c.charCodeAt(0); });
var file = new File([bytes], arguments[1], { type: 'application/octet-stream' });
var dt = new DataTransfer();
dt.items.add(file);
var dz = document.getElementById('dropzone');
dz.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
setTimeout(function () { done(document.title); }, 2500);
"""

PREVIEW_JS = """
window.renderFilenamePreview();
var host = document.getElementById('setNamePreview');
return host ? host.innerText : '';
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class DroppedFileNamesTheReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.esx_factory import make_esx
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-fname-browser-"))
        # Registered here rather than in tearDownClass so the cleanup cannot be
        # separated from the thing it cleans up - the suite leaked 116 temp
        # directories a run before that rule existed.
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        esx = make_esx(cls.tmp / ESX_NAME)
        cls.b64 = base64.b64encode(esx.read_bytes()).decode("ascii")
        cls.size = esx.stat().st_size
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
        browser cannot fail the run on a machine that has the other two, and CI
        (which has none of the three at these paths) skips rather than fails."""
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

    def _drop(self, driver, answer):
        _StubApi.answer = answer
        _StubApi.calls = []
        driver.get(self.url)
        time.sleep(1.2)
        driver.set_script_timeout(60)
        title = driver.execute_async_script(DROP_JS, self.b64, ESX_NAME)
        asked = [b for (a, b) in _StubApi.calls if a == "report/find_folder"]
        return title, asked

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
                driver.quit()
        if not started:
            self.skipTest("none of Firefox, Chrome or Edge would start")

    def test_the_site_reaches_the_title_after_a_plain_drop(self):
        """The whole point. A drop carries no path, so the page has to ask -
        and until it did, every report opened from the front page was named
        after the .esx and not after the job."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                title, asked = self._drop(driver, {"ok": True, "folder": SITE})
                self.assertEqual(title, "AP Installation - " + SITE)
                self.assertTrue(asked, "the drop never looked the folder up")

    def test_it_asks_with_the_name_and_the_byte_size(self):
        """The size is what makes the answer safe to act on: two buildings
        surveyed from one template share a file name."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                _, asked = self._drop(driver, {"ok": True, "folder": SITE})
                self.assertTrue(asked, "the drop never looked the folder up")
                self.assertEqual(asked[0].get("name"), ESX_NAME)
                self.assertEqual(asked[0].get("size"), self.size)

    def test_a_refused_lookup_leaves_the_old_name_and_says_why(self):
        """Every way the lookup can come back empty has to cost nothing and be
        explainable. "The site is missing and I cannot tell why" is the state
        the whole preview exists to prevent."""
        cases = [
            ({"ok": False, "reason": "no_root"}, "Local project folder"),
            ({"ok": False, "reason": "ambiguous", "count": 2}, "more than one project"),
            ({"ok": False, "reason": "not_found"}, "was not found"),
        ]
        for kind, driver in self._each_browser():
            for answer, phrase in cases:
                with self.subTest(browser=kind, reason=answer["reason"]):
                    title, asked = self._drop(driver, answer)
                    self.assertEqual(title, "AP Installation - B04 - PD")
                    self.assertTrue(asked, "the drop never looked the folder up")
                    preview = driver.execute_script(PREVIEW_JS)
                    self.assertIn(phrase, preview)
