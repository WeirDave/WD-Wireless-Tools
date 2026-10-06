"""AP Labeler's Line Spacing box, typed into with real key presses in
Firefox, Chrome, Edge and Safari.

The first fix for "Auto draws no lines and a number will not go in" was
checked in one engine. A number box is where engines differ most, so this
drives the real page in every browser the suite has and sends real keys:

* the box takes `1`, then `12`, then `120`, and keeps focus while it does;
* Auto draws the row breaks, a half-typed number falls back to Auto rather
  than one line per pixel, and a finished number draws a line every N px;
* any whole number is valid to the browser. The box said ``step="10"``, so
  55 or 125 was a step mismatch in every engine while the code accepted it;
  older Firefox paints such a box red, which reads as the box refusing it.

Served by ``http.server`` over ``web/``, never ``server.py``; the settings
endpoint is stubbed. The project is invented: nine APs in three rows on a
plan 800 by 600.
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
    FLOORS, HAVE_SELENIUM, PLAN_SVG, _InABrowser, _StubApi,
)

try:  # pragma: no cover - availability varies by machine
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
except ImportError:  # pragma: no cover
    pass

#: Three rows (y 100, 300, 500), three columns (x 100, 400, 700) on 800 x 600.
ROWS_Y = (100, 300, 500)
COLS_X = (100, 400, 700)


def _esx() -> bytes:
    aps = []
    for (fid, _), ys in zip(FLOORS, (ROWS_Y, (300,))):
        for r, y in enumerate(ys):
            for c, x in enumerate(COLS_X):
                aps.append({"id": f"{fid}-{r}{c}", "name": f"AP-{fid}-{r}{c}",
                            "location": {"floorPlanId": fid,
                                         "coord": {"x": x, "y": y}}})
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


class _NoWait(_StubApi):
    delay = 0


#: What the page says about its guide lines right now.
STATE_JS = """
var box = document.getElementById('arPlanBox');
var g = box.querySelectorAll('.ar-guide');
var sp = document.getElementById('arSpacing');
return { n: g.length,
         at: Array.prototype.map.call(g, function (e) { return e.style.top || e.style.left; }),
         value: sp.value, valid: sp.validity.valid,
         focus: document.activeElement && document.activeElement.id,
         hint: document.getElementById('arSpacingHint').textContent };
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TypingIntoLineSpacingTests(_InABrowser, unittest.TestCase):
    stub = _NoWait

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = base64.b64encode(_esx()).decode("ascii")

    def _ready(self, driver, order):
        self._open(driver, self.project, "invented-site.esx")
        Select(driver.find_element(By.ID, "arOrder")).select_by_value(order)
        time.sleep(0.4)

    def _state(self, driver):
        return driver.execute_script(STATE_JS)

    def test_auto_draws_the_breaks_between_rows(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._ready(driver, "row-ltr")
                s = self._state(driver)
                # Halfway across each gap: y 200 and 400 of 600.
                self.assertEqual([round(float(a.rstrip("%")), 1) for a in s["at"]],
                                 [33.3, 66.7], s)
                self.assertTrue(s["hint"].startswith("Auto"), s)

    def test_real_key_presses_reach_the_box_and_draw_what_they_say(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._ready(driver, "row-ltr")
                box = driver.find_element(By.ID, "arSpacing")
                box.click()
                seen = []
                for key in "120":
                    box.send_keys(key)
                    time.sleep(0.2)
                    seen.append(self._state(driver))
                self.assertEqual([s["value"] for s in seen], ["1", "12", "120"], seen)
                self.assertEqual([s["focus"] for s in seen], ["arSpacing"] * 3, seen)
                # "1" is under the box's minimum: Auto, not a line per pixel.
                self.assertEqual(seen[0]["n"], 2, seen[0])
                self.assertIn("at least", seen[0]["hint"], seen[0])
                self.assertEqual(seen[1]["n"], 600 // 12, seen[1])
                self.assertEqual(seen[2]["n"], 600 // 120, seen[2])
                self.assertIn("120 px", seen[2]["hint"], seen[2])

    def test_the_lines_follow_the_numbering_not_the_displayed_image(self):
        """Safari reports an SVG plan's on-screen size (496 px for a 600 px
        plan here) as its natural size, and the lines were drawn from that:
        41 where the numbering used 50. A browser that does not do it is made
        to, so every browser is held to the same answer."""
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._ready(driver, "row-ltr")
                driver.execute_script(
                    "var i = document.getElementById('arPlanImg');"
                    "Object.defineProperty(i, 'naturalHeight', { get: function () { return 496; } });"
                    "Object.defineProperty(i, 'naturalWidth', { get: function () { return 661; } });")
                box = driver.find_element(By.ID, "arSpacing")
                box.click()
                box.send_keys("12")
                time.sleep(0.3)
                s = self._state(driver)
                self.assertEqual(s["n"], 600 // 12, s)

    def test_clearing_the_box_returns_to_auto(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._ready(driver, "row-ltr")
                box = driver.find_element(By.ID, "arSpacing")
                box.click()
                box.send_keys("120")
                time.sleep(0.2)
                box.clear()
                time.sleep(0.3)
                s = self._state(driver)
                self.assertEqual((s["value"], s["n"]), ("", 2), s)
                self.assertTrue(s["hint"].startswith("Auto"), s)

    def test_any_whole_number_is_valid_to_the_browser(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._ready(driver, "row-ltr")
                box = driver.find_element(By.ID, "arSpacing")
                box.click()
                for typed in ("55", "125"):
                    box.clear()
                    box.send_keys(typed)
                    time.sleep(0.2)
                    s = self._state(driver)
                    self.assertTrue(s["valid"], (typed, s))
                    self.assertEqual(s["n"], 600 // int(typed), (typed, s))

    def test_columns_draw_vertical_breaks_in_auto(self):
        for kind, driver in self._each_browser():
            with self.subTest(browser=kind):
                self._ready(driver, "col-ttb")
                s = self._state(driver)
                # x 100 / 400 / 700 of 800: breaks at 250 and 550.
                self.assertEqual([round(float(a.rstrip("%")), 1) for a in s["at"]],
                                 [31.2, 68.8], s)


if __name__ == "__main__":
    unittest.main()
