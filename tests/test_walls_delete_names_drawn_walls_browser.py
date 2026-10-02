"""Deleting a wall type says how many drawn walls it leaves without one.

The confirmation used to read only 'Remove "Wall, Dry"?' - even for a type
with hundreds of segments drawn on the plan, which would be left pointing at
a type that no longer exists. It now names the count and where to move them
first, and it counts afresh, because Visual Swap rewrites the segments after
the file was opened.

Driven through the real page with an invented project; `window.confirm` is
replaced by a recorder that answers "no", so nothing is deleted.
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait


def _band(name):
    return {"band": name, "attenuationFactor": 10.0,
            "reflectionCoefficient": 0.1, "diffractionCoefficient": 5.0}


def _esx(path):
    types = [{"id": "wt-drawn", "name": "Invented Drawn Wall", "color": "#AA5500",
              "thickness": 0.1, "key": "WallInventedDrawn",
              "propagationProperties": [_band("TWO"), _band("FIVE"), _band("SIX")]},
             {"id": "wt-unused", "name": "Invented Unused Wall", "color": "#0055AA",
              "thickness": 0.1, "key": "WallInventedUnused",
              "propagationProperties": [_band("TWO"), _band("FIVE"), _band("SIX")]}]
    points = [{"id": "p%d" % i, "location": {"floorPlanId": "f1",
                                             "coord": {"x": 10.0 * i, "y": 5.0}}}
              for i in range(4)]
    segs = [{"id": "s%d" % i, "wallTypeId": "wt-drawn",
             "wallPoints": ["p%d" % i, "p%d" % (i + 1)]} for i in range(3)]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps({"project": {"id": "p", "name": "Invented"}}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": "f1", "name": "Level 1", "width": 100, "height": 100,
             "metersPerUnit": 0.05}]}))
        z.writestr("wallTypes.json", json.dumps({"wallTypes": types}))
        z.writestr("wallPoints.json", json.dumps({"wallPoints": points}))
        z.writestr("wallSegments.json", json.dumps({"wallSegments": segs}))
    return path


#: Press the real Delete button on the named card and return what confirm()
#: was asked. The answer is "no", so the type stays.
PRESS_DELETE = """
var done = arguments[arguments.length - 1];
var name = arguments[0];
var asked = [];
window.confirm = function (m) { asked.push(m); return false; };
var card = Array.prototype.find.call(document.querySelectorAll('.wall-card'),
  function (c) { return c.querySelector('.wall-name').textContent === name; });
if (!card) { done({error: 'no card named ' + name}); return; }
card.querySelector('.btn-danger').click();
setTimeout(function () {
  done({asked: asked, cards: document.querySelectorAll('.wall-card').length});
}, 600);
"""

#: What Visual Swap does to the project: rewrite wallSegments.json in place.
MOVE_ALL_TO_UNUSED = """
var done = arguments[arguments.length - 1];
var f = window.esxZip.file('wallSegments.json');
f.async('string').then(function (t) {
  var doc = JSON.parse(t);
  doc.wallSegments.forEach(function (s) { s.wallTypeId = 'wt-unused'; });
  window.esxZip.file('wallSegments.json', JSON.stringify(doc));
  done(true);
});
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class DeletingADrawnWallType(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = _esx(Path(cls._tmp.name) / "invented-drawn.esx")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def open(self, drv):
        drv.set_window_size(1366, 1000)
        drv.get(self.base + "/walls")
        WebDriverWait(drv, 15).until(lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 20).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, ".wall-card")) >= 2)
        time.sleep(0.5)
        drv.set_script_timeout(10)

    def test_the_confirmation_names_the_drawn_walls(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv)
                before = len(drv.find_elements(By.CSS_SELECTOR, ".wall-card"))
                r = drv.execute_async_script(PRESS_DELETE, "Invented Drawn Wall")
                self.assertEqual(len(r["asked"]), 1, r)
                msg = r["asked"][0]
                self.assertIn("3 drawn wall segments", msg)
                self.assertIn("no wall type", msg)
                self.assertIn("Quick swap by type", msg)
                self.assertEqual(r["cards"], before, "answering no deleted it")

                r = drv.execute_async_script(PRESS_DELETE, "Invented Unused Wall")
                self.assertIn("No drawn walls use it", r["asked"][0])

    def test_it_counts_after_the_walls_were_moved(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv)
                drv.execute_async_script(MOVE_ALL_TO_UNUSED)
                r = drv.execute_async_script(PRESS_DELETE, "Invented Drawn Wall")
                self.assertIn("No drawn walls use it", r["asked"][0])
                r = drv.execute_async_script(PRESS_DELETE, "Invented Unused Wall")
                self.assertIn("3 drawn wall segments", r["asked"][0])


if __name__ == "__main__":
    unittest.main()
