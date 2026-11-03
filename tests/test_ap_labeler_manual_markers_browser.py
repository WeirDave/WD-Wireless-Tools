"""AP Labeler, Manual order, in a real browser: an AP still to be numbered can be
seen, and an AP left as "Simulated ..." is reported.

* Numbering by hand means finding every AP on the plan. An unnumbered AP was a
  26px disc with a 2px dashed ring in its own colour - on a busy plan, or in a
  pale colour on white paper, it could not be told from the drawing, and one
  was missed. It is now a larger hollow disc with a thick ring, edged dark and
  then white, while a numbered AP stays a filled disc.
* An AP that still carries Ekahau's placeholder name is listed under the
  preview, floor by floor, and downloading asks first.

Served by ``http.server`` over ``web/``, never ``server.py``. Every name and
id is invented.
"""
from __future__ import annotations

from tests import browsers as _browsers

import base64
import io
import json
import time
import unittest
import zipfile

from tests.test_ap_labeler_second_project_browser import (
    FLOORS, PLAN_SVG, HAVE_SELENIUM, _InABrowser)

try:  # pragma: no cover - availability varies by machine
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
except ImportError:  # pragma: no cover
    pass

#: Pale yellow is the case the old ring lost on white paper.
COLOURS = ["#FFE600", "#0068FF", "#FF0000"]


def _esx() -> bytes:
    aps = []
    for fi, (fid, _) in enumerate(FLOORS):
        for k in range(3):
            aps.append({"id": f"{fid}-{k + 1}", "name": f"Simulated AP-{47 + fi * 3 + k}",
                        "color": COLOURS[k],
                        "location": {"floorPlanId": fid,
                                     "coord": {"x": 150 + 200 * k, "y": 300}}})
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
        z.writestr("project.json", json.dumps({"project": {"name": "Invented"}}))
    return buf.getvalue()


OPEN_JS = r"""
var done = arguments[arguments.length - 1];
var b64 = arguments[0], fname = arguments[1];
var started = Date.now();
(function waitReady() {
  if (!(document.readyState === 'complete' && typeof window.arDownload === 'function' && window.__aprename)) {
    if (Date.now() - started > 20000) { done({ error: 'page never ready' }); return; }
    setTimeout(waitReady, 100); return;
  }
  var bytes = Uint8Array.from(atob(b64), function (c) { return c.charCodeAt(0); });
  var dt = new DataTransfer();
  dt.items.add(new File([bytes], fname, { type: 'application/octet-stream' }));
  var input = document.getElementById('fileInput');
  input.files = dt.files;
  input.dispatchEvent(new Event('change', { bubbles: true }));
  (function waitLoaded() {
    var tabs = document.querySelectorAll('#arFloorTabs .ar-floor-tab').length;
    if (tabs === 2 && !document.getElementById('arPlanBox').hidden
        && document.querySelectorAll('.ar-marker').length) { setTimeout(function () { done({ ok: 1 }); }, 300); return; }
    if (Date.now() - started > 30000) { done({ error: 'not loaded' }); return; }
    setTimeout(waitLoaded, 100);
  })();
})();
"""

#: What a marker looks like to someone looking at it.
LOOK_JS = r"""
var out = {};
document.querySelectorAll('.ar-marker').forEach(function (m) {
  var cs = getComputedStyle(m), r = m.getBoundingClientRect();
  out[m.getAttribute('data-ap-id')] = {
    unnumbered: m.classList.contains('is-unnumbered'),
    width: r.width, height: r.height,
    ring: parseFloat(cs.borderTopWidth), ringColour: cs.borderTopColor,
    fill: cs.backgroundColor, shadow: cs.boxShadow, text: m.firstChild ? m.firstChild.textContent.trim() : ''
  };
});
return out;
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class AnApStillToNumberCanBeSeenTests(_InABrowser, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = base64.b64encode(_esx()).decode("ascii")

    def _manual(self, driver):
        got = driver.execute_async_script(OPEN_JS, self.project, "invented-site.esx")
        self.assertNotIn("error", got, got.get("error"))
        order = Select(driver.find_element(By.ID, "arOrder"))
        order.select_by_value("manual")
        time.sleep(0.4)

    def _click_ap(self, driver, ap_id):
        driver.execute_script(
            "document.querySelector('.ar-marker[data-ap-id=\"' + arguments[0] + '\"]').click();", ap_id)
        time.sleep(0.2)

    def test_an_unnumbered_ap_is_larger_and_ringed_a_numbered_one_is_filled(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._manual(driver)
                self._click_ap(driver, "fa-2")
                look = driver.execute_script(LOOK_JS)
                numbered, bare = look["fa-2"], look["fa-1"]
                self.assertFalse(numbered["unnumbered"], look)
                self.assertTrue(bare["unnumbered"], look)
                self.assertGreaterEqual(bare["width"], 33, look)
                self.assertGreater(bare["width"], numbered["width"] + 4, look)
                self.assertGreaterEqual(bare["ring"], 4, "the ring is too thin to see: %r" % bare)
                # Hollow and white inside; the filled disc is the AP's colour.
                self.assertEqual(bare["fill"], "rgb(255, 255, 255)", bare)
                self.assertNotEqual(numbered["fill"], "rgb(255, 255, 255)", numbered)
                self.assertEqual(numbered["text"], "1", numbered)

    def test_a_pale_ring_is_edged_dark_so_it_shows_on_white_paper(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._manual(driver)
                yellow = driver.execute_script(LOOK_JS)["fa-1"]
                self.assertEqual(yellow["ringColour"], "rgb(255, 230, 0)", yellow)
                # Dark on the inside edge and again outside the ring, then white.
                self.assertIn("inset", yellow["shadow"], yellow)
                self.assertGreaterEqual(yellow["shadow"].count("rgb(0, 0, 0)"), 2, yellow)
                self.assertIn("rgb(255, 255, 255) 0px 0px 0px 4px", yellow["shadow"], yellow)

    def test_every_ap_still_to_number_is_drawn_until_it_is_clicked(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._manual(driver)
                look = driver.execute_script(LOOK_JS)
                self.assertEqual(sorted(k for k, v in look.items() if v["unnumbered"]),
                                 ["fa-1", "fa-2", "fa-3"])
                for ap in ("fa-1", "fa-2", "fa-3"):
                    self._click_ap(driver, ap)
                look = driver.execute_script(LOOK_JS)
                self.assertFalse(any(v["unnumbered"] for v in look.values()), look)


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class AnApThatStillSaysSimulatedIsReportedInABrowserTests(_InABrowser, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = base64.b64encode(_esx()).decode("ascii")

    def _manual(self, driver):
        got = driver.execute_async_script(OPEN_JS, self.project, "invented-site.esx")
        self.assertNotIn("error", got, got.get("error"))
        Select(driver.find_element(By.ID, "arOrder")).select_by_value("manual")
        time.sleep(0.4)

    def _warn(self, driver):
        return driver.execute_script(
            "var w = document.getElementById('arSimWarn');"
            "return { hidden: w.hidden || w.offsetParent === null, text: w.innerText };")

    def test_the_warning_lists_the_aps_and_shrinks_as_they_are_numbered(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._manual(driver)
                w = self._warn(driver)
                self.assertFalse(w["hidden"], w)
                self.assertIn("6 access points are still named", w["text"])
                for n in range(47, 53):
                    self.assertIn("Simulated AP-%d" % n, w["text"])
                for ap in ("fa-1", "fa-2", "fa-3"):
                    driver.execute_script(
                        "document.querySelector('.ar-marker[data-ap-id=\"%s\"]').click();" % ap)
                time.sleep(0.3)
                w = self._warn(driver)
                self.assertIn("3 access points are still named", w["text"], w)
                self.assertNotIn("Simulated AP-47", w["text"])
                self.assertIn("Simulated AP-50", w["text"])

    def test_a_floor_button_in_the_warning_shows_that_floor(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._manual(driver)
                for b in driver.find_elements(By.CSS_SELECTOR, "#arSimWarn .ar-sim-jump"):
                    if b.text.startswith("Level 2"):
                        driver.execute_script("arguments[0].click();", b)
                        break
                else:
                    self.fail("no button for Level 2")
                time.sleep(0.4)
                shown = driver.execute_script(
                    "return window.__aprename.getState().currentFloor;")
                self.assertEqual(shown, "fb")

    def test_downloading_with_one_left_asks_and_cancelling_builds_nothing(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._manual(driver)
                self._number_all_but_one(driver)
                got = driver.execute_script(r"""
var asked = [], built = 0;
window.confirm = function (t) { asked.push(t); return false; };
var orig = URL.createObjectURL;
URL.createObjectURL = function (b) { built++; return orig.call(URL, b); };
HTMLAnchorElement.prototype.click = function () {};
document.getElementById('arDownloadBtn').click();
return new Promise(function (res) { setTimeout(function () { res({ asked: asked, built: built }); }, 1200); });
""")
                self.assertEqual(len(got["asked"]), 1, got)
                self.assertIn("Simulated AP-52", got["asked"][0])
                self.assertEqual(got["built"], 0, "the file was built after Cancel")

    def test_downloading_with_one_left_builds_the_file_when_it_is_confirmed(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._manual(driver)
                self._number_all_but_one(driver)
                got = driver.execute_script(r"""
var built = 0;
window.confirm = function () { return true; };
var orig = URL.createObjectURL;
URL.createObjectURL = function (b) { built++; return orig.call(URL, b); };
HTMLAnchorElement.prototype.click = function () {};
document.getElementById('arDownloadBtn').click();
return new Promise(function (res) { setTimeout(function () { res({ built: built }); }, 2500); });
""")
                self.assertEqual(got["built"], 1)

    def _number_all_but_one(self, driver):
        """Floor 1's three and floor 2's first two: Simulated AP-52 is the one
        missed."""
        driver.execute_script("window.arShowFloor('fa');")
        time.sleep(0.4)
        for ap in ("fa-1", "fa-2", "fa-3"):
            driver.execute_script(
                "document.querySelector('.ar-marker[data-ap-id=\"%s\"]').click();" % ap)
        driver.execute_script("window.arShowFloor('fb');")
        time.sleep(0.5)
        for ap in ("fb-1", "fb-2"):
            driver.execute_script(
                "document.querySelector('.ar-marker[data-ap-id=\"%s\"]').click();" % ap)
        time.sleep(0.3)


if __name__ == "__main__":
    unittest.main()
