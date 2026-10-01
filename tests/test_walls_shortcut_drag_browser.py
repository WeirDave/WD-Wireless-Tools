"""Dragging a wall type onto a shortcut slot assigns it, in a real browser.

Every shortcut slot and wall card declared five drag events with one shared
`data-fn`, so the dispatcher's fallback sent dragover, dragleave, drop and
dragend all to *dragstart*. In Firefox that threw "Modifications are not
allowed for this document" on every dragover; a drop on an empty slot ran the
dragover handler and assigned nothing; and dragend re-ran dragstart, which
left the card greyed out. Each event now names its own handler with
`data-fn-<event>`.

The events are dispatched through the page's real `WD.actions` dispatcher,
against the page's real markup, after a real `.esx` has been opened. What is
asserted is the result he looks for: the slot shows the wall type, and no card
is left greyed.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from tests.esx_factory import make_esx
from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait


#: Free a slot if all nine are taken, then drag the first wall card that has
#: no shortcut onto it. The card is looked up *after* the slot is cleared,
#: because clearing redraws the list and an element from before the redraw is
#: no longer in the document - an event dispatched on it reaches nothing.
DRAG = """
var empty = document.querySelector('.hotkey-slot:not([draggable])');
if (!empty) {
  document.querySelector('.hotkey-slot .hotkey-clear').click();
  empty = document.querySelector('.hotkey-slot:not([draggable])');
}
var slot = empty.dataset.slot;
var card = Array.prototype.find.call(document.querySelectorAll('.wall-card'),
  function (c) { return !c.querySelector('.kb-badge'); })
  || document.querySelector('.wall-card');
var name = card.querySelector('.wall-name').textContent;
var dt = new DataTransfer();
var errors = [];
function onErr(e) { errors.push(String(e.message)); }
window.addEventListener('error', onErr);
function fire(el, type) {
  el.dispatchEvent(new DragEvent(type, {bubbles: true, cancelable: true,
                                        dataTransfer: dt}));
}
fire(card, 'dragstart');
fire(empty, 'dragover');
fire(empty, 'drop');
fire(card, 'dragend');
window.removeEventListener('error', onErr);
var after = document.querySelector(
  '.hotkey-slot[data-slot="' + slot + '"] .hotkey-name');
return {name: name, slot: slot, now: after ? after.textContent : null,
        grey: document.querySelectorAll('.wall-card.dragging').length,
        errors: errors};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class DraggingAWallTypeOntoAShortcutAssignsIt(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = make_esx(Path(cls._tmp.name) / "invented-walls.esx")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def open_project(self, drv):
        drv.set_window_size(1600, 1000)
        drv.get(self.base + "/walls")
        WebDriverWait(drv, 15).until(
            lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 20).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, ".wall-card"))
        time.sleep(0.3)

    def test_a_drop_on_an_empty_slot_assigns_the_dragged_type(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_project(drv)
                r = drv.execute_script(DRAG)
                self.assertEqual(r["now"], r["name"], r)
                self.assertEqual(r["grey"], 0,
                                 "a card is left greyed out after the drop")
                self.assertEqual(r["errors"], [], r)


if __name__ == "__main__":
    unittest.main()
