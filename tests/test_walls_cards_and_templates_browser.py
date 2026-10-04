"""Quick Walls controls, pressed in a real browser.

* **Set key** on a wall card opens the 1-9 shortcut menu. It did nothing: the
  handler measured `e.currentTarget`, which under WD.actions' delegated
  dispatch is the document, so it threw before the menu was built.
* **Add Wall Type** named "Concrete" makes a custom type. The key used to be
  derived from the name, which made it Ekahau's own `Concrete`: the new type
  listed under Standard Ekahau.
* **Save Template** and **Import** ask before replacing a template already
  saved, naming the one that would go. A name that lands on another
  template's file ("Invented A/B" and "Invented A_B") was replaced silently,
  and Import never checked at all.

Driven through the real page and server with invented projects and names;
`window.confirm` is replaced by a recorder.
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


def _esx(path, types):
    points = [{"id": "p%d" % i, "location": {"floorPlanId": "f1",
                                             "coord": {"x": 10.0 * i, "y": 5.0}}}
              for i in range(3)]
    segs = [{"id": "s0", "wallTypeId": types[0]["id"], "wallPoints": ["p0", "p1"]}]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps({"project": {"id": "p", "name": "Invented"}}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": "f1", "name": "Level 1", "width": 100, "height": 100,
             "metersPerUnit": 0.05}]}))
        z.writestr("wallTypes.json", json.dumps({"wallTypes": types}))
        z.writestr("wallPoints.json", json.dumps({"wallPoints": points}))
        z.writestr("wallSegments.json", json.dumps({"wallSegments": segs}))
    return path


def _type(tid, name, key=None):
    w = {"id": tid, "name": name, "color": "#AA5500", "thickness": 0.1,
         "propagationProperties": [_band("TWO"), _band("FIVE"), _band("SIX")]}
    if key:
        w["key"] = key
    return w


#: POST to the real template route, then refresh the page's list.
SAVE_TEMPLATE = """
var done = arguments[arguments.length - 1];
fetch('/api/templates/save', {method: 'POST',
  headers: {'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1'},
  body: JSON.stringify({name: arguments[0], wallTypes: arguments[1],
                        overwrite: true})})
  .then(function (r) { return r.json(); }).then(done)
  .catch(function (e) { done({error: String(e)}); });
"""

SCAN = """
var done = arguments[arguments.length - 1];
var prefix = arguments[0];
fetch('/api/templates/scan', {method: 'POST',
  headers: {'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1'},
  body: '{}'}).then(function (r) { return r.json(); })
  .then(function (j) { done((j.templates || []).filter(function (t) {
    return t.name.indexOf(prefix) === 0; }).map(function (t) {
    return [t.name, t.wallTypes.map(function (w) { return w.name; })]; })); });
"""

RECORD_CONFIRM = """
window.__asked = [];
var answer = arguments[0];
window.confirm = function (m) { window.__asked.push(m); return answer; };
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class QuickWallsControlsWork(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.plain = _esx(root / "invented-plain.esx",
                         [_type("wt-x", "Invented Wall", "InventedWall")])
        cls.stock = _esx(root / "invented-stock.esx",
                         [_type("wt-c", "Wall, Concrete", "Concrete")])
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def open(self, drv, esx):
        drv.set_window_size(1366, 1000)
        drv.get(self.base + "/walls")
        WebDriverWait(drv, 15).until(lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(esx))
        WebDriverWait(drv, 20).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, ".wall-card"))
        time.sleep(0.5)
        drv.set_script_timeout(15)

    def asked_confirms(self, drv, how_many=1, timeout=20):
        """The questions the page has put to `window.confirm`, once they arrive.

        The question is asked only after the page's first save request has
        come back naming a conflict, so it lands a server round-trip after the
        click. A fixed `time.sleep(1.0)` read `[]` on Firefox in CI on a
        loaded runner - the save request had not gone out yet - while Chrome
        and Edge passed the same run. This polls, bounded, and hands back
        whatever has been asked by the deadline so the caller's assertion names
        it instead of the test stalling.
        """
        deadline = time.monotonic() + timeout
        asked = []
        while time.monotonic() < deadline:
            asked = drv.execute_script("return window.__asked;")
            if len(asked) >= how_many:
                break
            time.sleep(0.1)
        # Settle briefly, so a second, unwanted question is still caught.
        time.sleep(0.25)
        return drv.execute_script("return window.__asked;") or asked

    def scan_until(self, drv, prefix, expected, timeout=20):
        """The saved templates under `prefix`, once they read `expected`.

        After a confirmed answer the page sends a second, overwriting save, so
        reading the folder the instant the question appears would race it.
        Returns the last reading on timeout, for the assertion to show.
        """
        deadline = time.monotonic() + timeout
        found = None
        while time.monotonic() < deadline:
            found = drv.execute_async_script(SCAN, prefix)
            if found == expected:
                break
            time.sleep(0.2)
        return found

    def test_set_key_opens_the_shortcut_menu(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv, self.plain)
                btn = drv.find_element(
                    By.CSS_SELECTOR, '.wall-card button[data-fn="showKeybindMenu"]')
                btn.click()
                WebDriverWait(drv, 5).until(
                    lambda d: d.find_elements(By.CSS_SELECTOR, ".keybind-menu"))
                menu = drv.find_element(By.CSS_SELECTOR, ".keybind-menu")
                self.assertIn("Invented Wall", menu.text)
                self.assertEqual(
                    len(menu.find_elements(By.CSS_SELECTOR, ".keybind-option")), 9)

    def test_a_custom_type_named_like_a_stock_one_stays_custom(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv, self.stock)
                drv.find_element(
                    By.CSS_SELECTOR, 'button[data-fn="openAddModal"]').click()
                name = drv.find_element(By.ID, "fName")
                name.clear()
                name.send_keys("Concrete")
                drv.find_element(By.ID, "modalSaveBtn").click()
                WebDriverWait(drv, 5).until(
                    lambda d: len(d.find_elements(By.CSS_SELECTOR, ".wall-card")) == 2)
                r = drv.execute_script("""
                  var group = null, where = {};
                  document.querySelectorAll('#wallList > *').forEach(function (el) {
                    if (el.classList.contains('wall-group-header')) group = el.textContent;
                    else if (el.classList.contains('wall-card'))
                      where[el.querySelector('.wall-name').textContent] = group;
                  });
                  return {where: where, keys: window.wallTypes.map(function (w) {
                    return [w.name, w.key]; })};
                """)
                self.assertEqual(r["where"].get("Concrete"), "Custom Walls", r)
                self.assertEqual(r["where"].get("Wall, Concrete"), "Standard Ekahau", r)
                keys = dict(r["keys"])
                self.assertTrue(keys["Concrete"], r)
                self.assertNotEqual(keys["Concrete"], "Concrete", r)

    def test_save_asks_before_replacing_a_template_sharing_its_file(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv, self.plain)
                drv.execute_async_script(SAVE_TEMPLATE, "Invented A/B",
                                         [{"name": "Invented Original"}])

                PREFIX = "Invented A"

                def press_save(answer):
                    drv.execute_script(RECORD_CONFIRM, answer)
                    drv.find_element(
                        By.CSS_SELECTOR, 'button[data-fn="saveAsTemplate"]').click()
                    box = drv.find_element(By.ID, "tplSaveName")
                    WebDriverWait(drv, 5).until(lambda d: box.is_displayed())
                    box.clear()
                    box.send_keys("Invented A_B")
                    drv.find_element(
                        By.CSS_SELECTOR, 'button[data-fn="confirmSaveTemplate"]').click()
                    return self.asked_confirms(drv)

                asked = press_save(False)
                self.assertEqual(len(asked), 1, asked)
                self.assertIn("Invented A/B", asked[0])
                self.assertEqual(drv.execute_async_script(SCAN, PREFIX),
                                 [["Invented A/B", ["Invented Original"]]])

                drv.execute_script(
                    "document.getElementById('saveTplModal').classList.remove('active');")
                asked = press_save(True)
                self.assertEqual(len(asked), 1, asked)
                replaced = [["Invented A_B", ["Invented Wall"]]]
                self.assertEqual(self.scan_until(drv, PREFIX, replaced), replaced)
                drv.execute_script("""
                  return fetch('/api/templates/delete', {method: 'POST',
                    headers: {'Content-Type': 'application/json',
                              'X-WD-Wireless-Tools': '1'},
                    body: JSON.stringify({filename: 'Invented A_B_walltemplate.json'})});
                """)

    def test_import_asks_before_replacing_a_saved_template(self):
        upload = self.root / "invented-import_walltemplate.json"
        upload.write_text(json.dumps({"name": "Invented Imported", "wallTypes": [
            {"name": "Invented From File"}]}), encoding="utf-8")
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv, self.plain)
                drv.execute_async_script(SAVE_TEMPLATE, "Invented Imported",
                                         [{"name": "Invented Already Here"}])

                PREFIX = "Invented Imported"

                def import_it(answer):
                    drv.execute_script(RECORD_CONFIRM, answer)
                    drv.execute_script("""
                      var i = document.getElementById('tplImportInput');
                      i.value = ''; i.hidden = false; i.style.display = 'block';
                    """)
                    drv.find_element(By.ID, "tplImportInput").send_keys(str(upload))
                    return self.asked_confirms(drv)

                asked = import_it(False)
                self.assertEqual(len(asked), 1, asked)
                self.assertIn("Invented Imported", asked[0])
                self.assertEqual(drv.execute_async_script(SCAN, PREFIX),
                                 [["Invented Imported", ["Invented Already Here"]]])

                asked = import_it(True)
                self.assertEqual(len(asked), 1, asked)
                imported = [["Invented Imported", ["Invented From File"]]]
                self.assertEqual(self.scan_until(drv, PREFIX, imported), imported)


if __name__ == "__main__":
    unittest.main()
