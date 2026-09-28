"""Prep applies the WD wall template the way Quick Walls does.

Reported as "I just ran prep and the quick walls portion did not load the WD
profile". It had not, and nothing said so. `wall_inject` kept any type the
project already had - and every Ekahau project already has Ekahau's stock
types. The WD template is those same types carrying his colours and his
number-key layout, plus five of his own. So Prep added the five and skipped
the twenty-one that make the template his: Elevator Shaft stayed grey, the
1-9 keys stayed Ekahau's, and Framery Pod's key 8 knocked Ekahau's Cubicle off
8, leaving a mixture of the two layouts that was neither.

Driven here with the two files that actually ship - `templates/WD
Template_walltemplate.json` onto `templates/ekahau_defaults.json` - rather than
with a fixture, because the fault was in how they meet.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import wall_inject  # noqa: E402

WD = json.loads((ROOT / "templates" / "WD Template_walltemplate.json").read_text("utf-8"))["wallTypes"]
STOCK = json.loads((ROOT / "templates" / "ekahau_defaults.json").read_text("utf-8"))["wallTypes"]


def fresh_project():
    types = copy.deepcopy(STOCK)
    for i, w in enumerate(types):
        w["id"] = "proj-%02d" % i
    return {wall_inject.MEMBER: json.dumps({"wallTypes": types})}


def applied():
    m = fresh_project()
    report = wall_inject.inject_into_members(m, WD)
    return report, json.loads(m[wall_inject.MEMBER])["wallTypes"], m


class TheTemplateLands(unittest.TestCase):

    def test_every_type_ends_up_exactly_as_the_template_has_it(self):
        _, types, _ = applied()
        by_name = {w["name"]: w for w in types}
        for want in WD:
            with self.subTest(type=want["name"]):
                have = {k: v for k, v in by_name[want["name"]].items() if k != "id"}
                self.assertEqual(have, {k: v for k, v in want.items() if k != "id"})

    def test_the_number_keys_are_his_layout_and_nothing_else(self):
        _, types, _ = applied()
        keys = sorted((w["keybindNumber"], w["name"]) for w in types if w.get("keybindNumber"))
        his = sorted((w["keybindNumber"], w["name"]) for w in WD if w.get("keybindNumber"))
        self.assertEqual(keys, his)

    def test_the_three_recolours_land(self):
        _, types, _ = applied()
        colour = {w["name"]: w["color"] for w in types}
        for name in ("Elevator Shaft", "Door, Steel Fire/Exit", "Window, Thick"):
            with self.subTest(name=name):
                self.assertEqual(colour[name], next(w["color"] for w in WD if w["name"] == name))
                self.assertNotEqual(colour[name],
                                    next(w["color"] for w in STOCK if w["name"] == name))

    def test_no_type_is_doubled_and_the_projects_ids_survive(self):
        """Wall segments point at a type by id; a new id orphans every wall."""
        _, types, _ = applied()
        names = [w["name"] for w in types]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(types), len({w["name"] for w in WD} | {w["name"] for w in STOCK}))
        stock_ids = {"proj-%02d" % i for i in range(len(STOCK))}
        self.assertTrue(stock_ids <= {w["id"] for w in types})

    def test_the_report_says_what_changed(self):
        report, _, _ = applied()
        self.assertEqual(sorted(a["name"] for a in report["add"]),
                         sorted({w["name"] for w in WD} - {w["name"] for w in STOCK}))
        self.assertTrue(report["update"], "nothing reported as updated")
        self.assertEqual(len(report["add"]) + len(report["update"]) + report["unchanged"], len(WD))

    def test_a_second_run_has_nothing_to_do(self):
        _, _, m = applied()
        again = wall_inject.plan_into_members(m, WD)
        self.assertEqual((again["add"], again["update"], again["unchanged"]), ([], [], len(WD)))


PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('  function renderPreview(r) {');
if (a < 0) throw new Error('renderPreview moved');
let b = a, depth = 0, seen = false;
while (b < src.length && !(seen && depth === 0)) {
  if (src[b] === '{') { depth++; seen = true; }
  else if (src[b] === '}') depth--;
  b++;
}
const el = {};
function $(id) { return el[id] || (el[id] = { id, hidden: false, innerHTML: '', textContent: '', disabled: false }); }
function esc(s) { return String(s); }
function plural(n, one) { return n === 1 ? one : one + 's'; }
function syncSavedBoxes() {}
function renderMap() {}
function clearanceLine() { return ''; }
function stepCard(title, badge, cls, lines) { return JSON.stringify({ title, badge, cls, lines }); }
let go = null;
function setGo(on, note) { go = { on, note }; }
eval(src.slice(a, b));
renderPreview(JSON.parse(process.argv[2]));
console.log(JSON.stringify({ go, html: $('prepPreview').innerHTML }));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePreviewOffersIt(unittest.TestCase):
    """A project that already has his five types but Ekahau's colours and keys
    has nothing to *add* - and the button must still be offered, because there
    is something to update. Counting only additions would call it prepared."""

    def render(self, walls):
        r = {"ok": True, "steps": ["walls"], "step": {"walls": walls}}
        out = subprocess.run(["node", "-e", PROBE, str(ROOT / "web/assets/js/prep.js"), json.dumps(r)],
                             capture_output=True, text=True, encoding="utf-8", timeout=120)
        if out.returncode != 0:
            raise AssertionError((out.stdout + out.stderr).strip())
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_updates_alone_are_work(self):
        out = self.render({"ok": True, "add": [], "unchanged": 14, "skip": [],
                           "update": [{"name": "Elevator Shaft", "was": "Elevator Shaft"}]})
        self.assertTrue(out["go"]["on"], out)
        self.assertIn("1 to update", out["html"])
        self.assertIn("Elevator Shaft", out["html"])

    def test_nothing_to_add_or_update_is_nothing_to_do(self):
        out = self.render({"ok": True, "add": [], "update": [], "unchanged": 26, "skip": []})
        self.assertFalse(out["go"]["on"], out)
        self.assertIn("nothing to do", out["html"])


if __name__ == "__main__":
    unittest.main()
