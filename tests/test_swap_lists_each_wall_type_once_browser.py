"""Visual Wall Swap lists a wall type once, however many copies the project has.

A project can carry several wall types with the same name - Ekahau lets a type
be copied, and a template applied over a project can add one beside the type
already there. The swap dropdowns listed every copy, so "Elevator Shaft" and
"Door, Steel Fire/Exit" each appeared twice and a swap to the "wrong" copy left
walls behind. The tool swaps walls for walls; one name is one choice.

Asserted by running it: a project with deliberate same-name copies is opened in
the real page, the real dropdowns and legend are read back, and the real Swap
handlers are run. The names here are invented.
"""
from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
import zipfile
from collections import Counter
from pathlib import Path

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

# (id, name, colour). `door-2` is deliberately the most-used copy, `win-2`
# differs only in case and spacing, and the "(Copy)" type must stay its own
# entry because its name is different.
TYPES = [
    ("wall-1", "Wall, Invented A", "#C9A27A"),
    ("door-1", "Door, Invented B", "#8B5A2B"),
    ("door-2", "Door, Invented B", "#E85D04"),
    ("win-1", "Window, Invented C", "#0093EA"),
    ("win-2", "window,  invented c", "#ADE1FF"),
    ("win-copy", "Window, Invented C(Copy)", "#999999"),
]
# What each segment is drawn with, in order.
DRAWN = (["wall-1"] * 3 + ["door-1"] * 2 + ["door-2"] * 5
         + ["win-1"] * 2 + ["win-2"] * 1 + ["win-copy"] * 4)

SELECTS = ["swapTargetType", "swapFromType", "swapToType"]


def _esx(path):
    from PIL import Image
    w, h = 1200, 800
    im = Image.new("RGB", (w, h), "white")
    b = io.BytesIO()
    im.save(b, "PNG")
    pts, segs = [], []
    for n, type_id in enumerate(DRAWN):
        a, z = "p%d" % len(pts), "p%d" % (len(pts) + 1)
        y = 60 + n * 40
        pts.append({"id": a, "location": {"floorPlanId": "f1",
                                          "coord": {"x": 100, "y": y}}})
        pts.append({"id": z, "location": {"floorPlanId": "f1",
                                          "coord": {"x": 300, "y": y}}})
        segs.append({"id": "s%d" % n, "wallPoints": [a, z],
                     "wallTypeId": type_id})
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("project.json", json.dumps(
            {"project": {"id": "proj-invented-dupes", "name": "Invented"}}))
        zf.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": "f1", "name": "01", "imageId": "img-f1", "width": w,
             "height": h, "metersPerUnit": 0.03}]}))
        zf.writestr("images.json", json.dumps({"images": [
            {"id": "img-f1", "imageFormat": "PNG", "resolutionWidth": w,
             "resolutionHeight": h}]}))
        zf.writestr("wallTypes.json", json.dumps({"wallTypes": [
            {"id": i, "name": nm, "color": c, "thickness": 0.1,
             "attenuations": []} for i, nm, c in TYPES]}))
        zf.writestr("wallPoints.json", json.dumps({"wallPoints": pts}))
        zf.writestr("wallSegments.json", json.dumps({"wallSegments": segs}))
        zf.writestr("image-img-f1", b.getvalue())
    return path


OPTIONS = """
return Array.prototype.map.call(
  document.getElementById(arguments[0]).options,
  function (o) { return {value: o.value, text: o.textContent}; });
"""

LEGEND = """
return Array.prototype.map.call(
  document.querySelectorAll('#swapLegend .swap-legend-row'),
  function (r) { return {
    name: r.querySelector('.swap-legend-name').textContent,
    count: parseInt(r.querySelector('.swap-legend-count').textContent, 10)}; });
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheSwapListsEachWallTypeOnce(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = _esx(Path(cls._tmp.name) / "invented-dupes.esx")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def open_swap(self, drv):
        drv.set_window_size(1600, 1000)
        drv.get(self.base + "/walls")
        WebDriverWait(drv, 15).until(
            lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 20).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, ".wall-card"))
        drv.execute_script("openSwapModal();")
        WebDriverWait(drv, 20).until(lambda d: d.execute_script(
            "return !!(window.__wallsSwap && window.__wallsSwap.getSegmentCount());"))
        time.sleep(0.4)

    def types(self, drv):
        return Counter((t["type"]) for t in drv.execute_script(
            "return window.__wallsSwap.getSegTypes();"))

    def pick(self, drv, select_id, text):
        """Choose an entry by what it reads, as a person would."""
        found = [o for o in drv.execute_script(OPTIONS, select_id)
                 if o["text"] == text]
        self.assertEqual(len(found), 1, "%s: %r" % (select_id, text))
        drv.execute_script(
            "document.getElementById(arguments[0]).value = arguments[1];",
            select_id, found[0]["value"])

    def test_every_dropdown_lists_each_name_once(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                for sel in SELECTS:
                    texts = [o["text"] for o in drv.execute_script(OPTIONS, sel)
                             if o["value"]]
                    self.assertEqual(
                        sorted(texts),
                        sorted(["Wall, Invented A", "Door, Invented B",
                                "Window, Invented C",
                                "Window, Invented C(Copy)"]),
                        "%s lists a name more than once, or lost one" % sel)

    def test_the_legend_counts_a_name_as_one_row(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                rows = {r["name"]: r["count"]
                        for r in drv.execute_script(LEGEND)}
                self.assertEqual(rows, {
                    "Wall, Invented A": 3,
                    "Door, Invented B": 7,         # 2 + 5, both copies
                    "Window, Invented C": 3,       # 2 + 1, both copies
                    "Window, Invented C(Copy)": 4,
                })

    def test_a_selection_groups_by_name(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                drv.execute_script("window.__wallsSwap.selectAll();")
                groups = drv.execute_script(
                    "return window.__wallsSwap.getGroups();")
                names = [g["name"] for g in groups]
                self.assertEqual(len(names), len(set(names)), names)
                self.assertEqual(
                    {g["name"]: g["total"] for g in groups}["Door, Invented B"],
                    7)

    def test_swapping_from_a_name_takes_every_copy_of_it(self):
        """From = "Door, Invented B" moves the walls drawn with either copy."""
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                self.pick(drv, "swapFromType", "Door, Invented B")
                self.pick(drv, "swapToType", "Wall, Invented A")
                drv.execute_script(
                    "document.getElementById('swapScope').value = 'project';"
                    "applyQuickSwap();")
                got = self.types(drv)
                self.assertEqual(got["wall-1"], 3 + 7)
                self.assertEqual(got["door-1"] + got["door-2"], 0,
                                 "walls drawn with a copy were left behind")

    def test_undo_puts_each_wall_back_on_the_copy_it_was_drawn_with(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                before = self.types(drv)
                self.pick(drv, "swapFromType", "Door, Invented B")
                self.pick(drv, "swapToType", "Wall, Invented A")
                drv.execute_script(
                    "document.getElementById('swapScope').value = 'project';"
                    "applyQuickSwap();")
                drv.execute_script("swapUndo();")
                time.sleep(0.4)
                self.assertEqual(self.types(drv), before)

    def test_swapping_to_a_name_lands_on_one_type(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                self.pick(drv, "swapFromType", "Wall, Invented A")
                self.pick(drv, "swapToType", "Window, Invented C")
                drv.execute_script(
                    "document.getElementById('swapScope').value = 'project';"
                    "applyQuickSwap();")
                got = self.types(drv)
                self.assertEqual(got["wall-1"], 0)
                landed = {k: v for k, v in got.items()
                          if k in ("win-1", "win-2") and v}
                self.assertEqual(sum(landed.values()), 3 + 3,
                                 "the three walls must arrive, and the "
                                 "existing window walls stay where they were")

    def test_a_copy_of_the_name_is_not_a_swap(self):
        """Swapping a name to itself changes nothing, whichever copy was meant."""
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                before = self.types(drv)
                self.pick(drv, "swapFromType", "Door, Invented B")
                self.pick(drv, "swapToType", "Door, Invented B")
                drv.execute_script(
                    "document.getElementById('swapScope').value = 'project';"
                    "applyQuickSwap();")
                self.assertEqual(self.types(drv), before)

    def test_a_different_name_stays_its_own_entry(self):
        """"(Copy)" is a name of its own and is not folded into the original."""
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                self.pick(drv, "swapFromType", "Window, Invented C(Copy)")
                self.pick(drv, "swapToType", "Wall, Invented A")
                drv.execute_script(
                    "document.getElementById('swapScope').value = 'project';"
                    "applyQuickSwap();")
                got = self.types(drv)
                self.assertEqual(got["win-copy"], 0)
                self.assertEqual(got["win-1"], 2)
                self.assertEqual(got["win-2"], 1)


if __name__ == "__main__":
    unittest.main()
