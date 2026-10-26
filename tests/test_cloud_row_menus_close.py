"""A row's action menu closes when something else is clicked, or Escape is pressed.

The outside-click and Escape handlers were written for the main menu
(`.wd-menu`) and looked for nothing else. Every row's action menu is a
`<details class="row-menu">`, so once opened it stayed open - over the row it
had just acted on - until its own summary was clicked again.

The handlers are cut out of cloud.js with their selectors and run against a
small stand-in for the document that answers `closest` and `querySelectorAll`
the way a browser does for the selectors they use. Nothing here is a path or a
name from a real project.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"

PROGRAM = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
// From the menu handlers' first line, whichever way they name their selectors.
const m = src.match(/(?:const OPEN_MENUS = [^\r\n]*\r?\n)?document\.addEventListener\('click', \(ev\) => \{\s+const inside/);
const a = m ? m.index : -1;
const b = src.indexOf('function clearSelection()');
if (a < 0 || b < 0) throw new Error('the menu handlers moved');
const block = src.slice(a, b);

// Elements know their classes and their parent; `closest` and
// `querySelectorAll` understand the selector shapes the handlers use.
const all = [];
function el(classes, parent, extra) {
  const n = Object.assign({ classes, parent, open: false }, extra || {});
  n.closest = sel => {
    const wanted = sel.split(',').map(s => s.trim().replace(/^details/, '').replace(/^\./, ''));
    for (let x = n; x; x = x.parent) if (wanted.some(w => x.classes.includes(w))) return x;
    return null;
  };
  all.push(n);
  return n;
}
const listeners = {};
const document = {
  addEventListener: (type, fn) => { listeners[type] = fn; },
  querySelectorAll: sel => {
    const wanted = sel.split(',').map(s => s.trim().replace(/\[open\]$/, '')
      .replace(/^details/, '').replace(/^\./, ''));
    return all.filter(n => n.open && wanted.some(w => n.classes.includes(w)));
  },
};
const timers = [];
const setTimeout = fn => { timers.push(fn); return 0; };
eval(block);

const mainMenu = el(['wd-menu']);
const menuA = el(['row-menu']), summaryA = el(['row-menu-btn'], menuA);
const itemA = el(['row-menu-item'], menuA);
const menuB = el(['row-menu']), summaryB = el(['row-menu-btn'], menuB);
const elsewhere = el(['somewhere-else']);
const open = (...ms) => ms.forEach(m => { m.open = true; });
const state = () => ({ a: menuA.open, b: menuB.open, main: mainMenu.open });
const click = target => { listeners.click({ target }); timers.splice(0).forEach(f => f()); };
const out = {};

open(menuA); click(elsewhere);              out.outsideClick = state();
open(menuA); click(summaryA);               out.ownSummaryLeavesItAlone = state();
open(menuA); click(itemA);                  out.itemClosesItsMenu = state();
open(menuA); click(summaryB);               // opening B (the browser does that) closes A
                                            out.anotherSummaryClosesTheFirst = state();
open(menuA, menuB, mainMenu); listeners.keydown({ key: 'Escape' });
                                            out.escape = state();
open(menuA); listeners.keydown({ key: 'Enter' });
                                            out.otherKeysDoNothing = state();
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class RowMenusCloseTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", PROGRAM, str(CLOUD_JS)],
                           capture_output=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_click_elsewhere_closes_an_open_row_menu(self):
        self.assertFalse(self.out["outsideClick"]["a"], self.out)

    def test_clicking_its_own_summary_is_left_to_the_browser(self):
        self.assertTrue(self.out["ownSummaryLeavesItAlone"]["a"], self.out)

    def test_choosing_an_item_closes_the_menu(self):
        self.assertFalse(self.out["itemClosesItsMenu"]["a"], self.out)

    def test_opening_another_row_menu_closes_the_first(self):
        self.assertFalse(self.out["anotherSummaryClosesTheFirst"]["a"], self.out)

    def test_escape_closes_every_menu_and_other_keys_do_not(self):
        self.assertEqual({"a": False, "b": False, "main": False}, self.out["escape"])
        self.assertTrue(self.out["otherKeysDoNothing"]["a"], self.out)


if __name__ == "__main__":
    unittest.main()
