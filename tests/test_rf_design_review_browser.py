"""The RF Design Review and the AP schedule, driven in a real browser.

`test_rf_design_review` runs the rules and the renderer in Node. This drives
the page the way it is used: a synthetic .esx dropped on the real drop zone,
the report chosen through the real gallery, the CSV saved through the real
button in the review bar, and the document printed through the browser's own
print pipeline.

The print check is the one that only a browser can make. Every section of a
report starts a new sheet unless it says otherwise, and a finding can be one
row, so a review of a design with six findings printed six nearly empty
sheets. The findings run on now; the channel map still gets its own sheet.

Chrome, Edge and Firefox, per the standing rule.
"""
from __future__ import annotations

from tests import browsers as _browsers

import base64
import json
import shutil
import tempfile
import threading
import time
import unittest
import zipfile
from functools import partial
from pathlib import Path

from tests.pdf_sheets import sheet_sizes
# The module, not the class: a test class imported by name is collected and
# run a second time as part of this file.
from tests import test_change_audit_browser as _audit
from tests.test_change_audit_browser import BROWSERS, HAVE_SELENIUM, PNG_1X1, _StubApi

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

if HAVE_SELENIUM:  # pragma: no cover - availability varies by machine
    from selenium.webdriver.common.print_page_options import PrintOptions


def _ap(ap_id, name, x, y):
    return {"id": ap_id, "name": name, "vendor": "Vendo", "model": "V-100",
            "location": {"floorPlanId": "fl", "coord": {"x": x, "y": y}}}


def _radio(ap_id, freqs, tx=17.0, **extra):
    r = {"id": "r-%s-%d" % (ap_id, freqs[0]), "accessPointId": ap_id,
         "radioTechnology": "IEEE802_11", "antennaTypeId": "omni",
         "antennaMounting": "CEILING", "antennaHeight": 3.0, "transmitPower": tx,
         "channelByCenterFrequencyDefinedNarrowChannels": freqs}
    r.update(extra)
    return r


#: 800 x 600 at 0.05 m per unit. Six findings, each with a reason to fire:
#: two APs on 36 eight metres apart, a duplicate name, Ekahau's default name,
#: 2.4 GHz on channel 3, an unaimed panel, and a DFS channel.
APS = [
    _ap("a1", "Sample-AP01", 100, 100),
    _ap("a2", "Sample-AP02", 260, 100),
    _ap("a3", "Sample-AP02", 600, 450),
    _ap("a4", "Simulated AP-4", 400, 300),
    _ap("a5", "Sample-AP05", 700, 100),
]
RADIOS = [
    _radio("a1", [5180], 17.0), _radio("a1", [2412], 11.0),
    _radio("a2", [5180], 17.0), _radio("a2", [2422], 11.0),
    _radio("a3", [5745], 17.0),
    _radio("a4", [5260], 17.0),
    _radio("a5", [5785], 17.0, antennaTypeId="panel", antennaDirection=None),
]


def _write_esx(path: Path) -> Path:
    members = {
        "project.json": {"project": {"id": "rv-1", "name": "Review Sample"}},
        "floorPlans.json": {"floorPlans": [{
            "id": "fl", "name": "Level 1", "width": 800.0, "height": 600.0,
            "metersPerUnit": 0.05, "imageId": "im"}]},
        "images.json": {"images": [{"id": "im", "imageFormat": "PNG",
                                    "resolutionWidth": 800.0, "resolutionHeight": 600.0}]},
        "accessPoints.json": {"accessPoints": APS},
        "simulatedRadios.json": {"simulatedRadios": RADIOS},
        "antennaTypes.json": {"antennaTypes": [
            {"id": "omni", "name": "Integrated Omni", "directional": False},
            {"id": "panel", "name": "Sample Panel", "directional": True}]},
        "buildings.json": {"buildings": []},
        "buildingFloors.json": {"buildingFloors": []},
        "notes.json": {"notes": []},
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for member, doc in members.items():
            z.writestr(member, json.dumps(doc))
        z.writestr("image-im", PNG_1X1)
    return path


OPEN_JS = """
var done = arguments[arguments.length - 1];
var bytes = Uint8Array.from(atob(arguments[0]), function (c) { return c.charCodeAt(0); });
var file = new File([bytes], 'Review Sample.esx', { type: 'application/octet-stream' });
var dt = new DataTransfer();
dt.items.add(file);
document.getElementById('dropzone').dispatchEvent(
  new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
setTimeout(function () {
  window.selectReport('design');
  window.goStage('review');
  setTimeout(function () {
    done(JSON.stringify({
      text: document.getElementById('reportCanvas').innerText,
      marks: document.querySelectorAll('#reportCanvas .rep-dr-mark').length,
      lines: document.querySelectorAll('#reportCanvas .rep-dr-cci').length,
    }));
  }, 1200);
}, 2500);
"""

#: Click the real button. The blob is read on its way to the download, and the
#: anchor's click is kept from starting one, which a headless browser may not
#: allow and nobody needs left in a downloads folder.
CSV_JS = """
var done = arguments[arguments.length - 1];
var make = URL.createObjectURL;
var name = '';
HTMLAnchorElement.prototype.click = function () { name = this.download; };
URL.createObjectURL = function (b) {
  b.text().then(function (t) { setTimeout(function () { done(JSON.stringify({ name: name, text: t })); }, 0); });
  return make.call(URL, b);
};
var btn = document.querySelector('#stageReview [data-fn="exportApSchedule"]');
if (!btn) { done(JSON.stringify({ name: '', text: '', missing: true })); return; }
btn.click();
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheReviewWorksInABrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-review-browser-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.esx_b64 = base64.b64encode(
            _write_esx(cls.tmp / "Review Sample.esx").read_bytes()).decode("ascii")
        cls.httpd = _browsers.ExclusiveServer(
            ("127.0.0.1", 0), partial(_StubApi, directory=str(WEB)))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d/report.html" % cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _each_browser(self):
        started = 0
        for kind, binary in BROWSERS:
            driver = _audit.TheReportCanBeReachedAndUsedTests._driver(kind, binary)
            if driver is None:
                continue
            started += 1
            try:
                yield kind, driver
            finally:
                _browsers.shut_down(driver)
        if not started:
            self.skipTest("none of Chrome, Edge or Firefox could be started")

    def test_the_review_the_schedule_and_the_printout(self):
        """One journey per browser: each costs a launch and a parse."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                driver.get(self.url)
                time.sleep(1.2)
                driver.set_script_timeout(90)
                page = json.loads(driver.execute_async_script(OPEN_JS, self.esx_b64))
                text = page["text"]

                self.assertIn("RF DESIGN REVIEW", text.upper(), f"{kind}: not the review")
                self.assertIn("4 items to fix before this design is handed over.", text,
                              f"{kind}: the verdict is wrong")
                for finding in ("Access points sharing a name",
                                "2.4 GHz channels off the 1/6/11 plan",
                                "Directional antennas with no azimuth",
                                "5 GHz co-channel neighbours closer than",
                                "Access points without a real name",
                                "5 GHz radios on DFS channels"):
                    self.assertIn(finding, text, f"{kind}: {finding!r} is missing")
                # 160 units at 0.05 m is eight metres, printed in feet.
                self.assertIn("Sample-AP02 (ch 36) at 26.2 ft", text, f"{kind}: distance")
                self.assertEqual(page["marks"], 5, f"{kind}: one marker per 5 GHz radio")
                self.assertEqual(page["lines"], 1, f"{kind}: one too-close pair")

                csv = json.loads(driver.execute_async_script(CSV_JS))
                self.assertFalse(csv.get("missing"), f"{kind}: no CSV button")
                self.assertEqual(csv["name"], "Report - AP Schedule - Review Sample.csv",
                                 f"{kind}: file name")
                lines = [l for l in csv["text"].lstrip("﻿").split("\r\n") if l]
                self.assertEqual(len(lines), 1 + len(APS), f"{kind}: one row per AP")
                self.assertTrue(lines[0].startswith("AP name,Floor,"), f"{kind}: header")

                pdf = base64.b64decode(driver.print_page(PrintOptions()))
                sheets = len(sheet_sizes(pdf))
                # Cover, the findings running on, the channel map, and what was
                # checked. One sheet per finding came to twelve.
                self.assertLessEqual(sheets, 7, f"{kind}: {sheets} sheets")


if __name__ == "__main__":
    unittest.main()
