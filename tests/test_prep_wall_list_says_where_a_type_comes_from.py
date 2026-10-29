"""The wall-type list in Prep says which types are Ekahau's own.

Reported as: the list is just names, and there is no telling which of them are
Ekahau's defaults. It was a run of grey chips - "Adding", "Setting to the
template's version" - where the 21 stock types and the template's own additions
looked identical, and an update did not say what it would change.

The preview now carries, per type, whether it is one of Ekahau's stock types,
its colour, and for an update the things that differ. The page groups the types
by that and shows one row each. Driven here with the two files that ship, so a
change to either is read the way the page will read it.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import template_store, wall_inject  # noqa: E402

WD = json.loads((ROOT / "templates" / "WD Template_walltemplate.json").read_text("utf-8"))["wallTypes"]
STOCK = json.loads((ROOT / "templates" / "ekahau_defaults.json").read_text("utf-8"))["wallTypes"]


def project(types=None):
    types = copy.deepcopy(STOCK if types is None else types)
    for i, w in enumerate(types):
        w["id"] = "proj-%02d" % i
    return {wall_inject.MEMBER: json.dumps({"wallTypes": types})}


def by_name(entries):
    return {e["name"]: e for e in entries}


class ThePlanSaysWhereEachTypeComesFrom(unittest.TestCase):

    def setUp(self):
        self.plan = wall_inject.plan_into_members(project(), WD)
        self.every = by_name(self.plan["add"] + self.plan["update"] + self.plan["same"])

    def test_every_type_in_the_template_is_listed_once(self):
        self.assertEqual(sorted(self.every), sorted(w["name"] for w in WD))
        self.assertEqual(len(self.plan["add"]) + len(self.plan["update"]) + len(self.plan["same"]),
                         len(WD))
        self.assertEqual(len(self.plan["same"]), self.plan["unchanged"])

    def test_ekahaus_own_types_are_marked_and_the_templates_additions_are_not(self):
        stock_keys = {w["key"] for w in STOCK}
        for want in WD:
            with self.subTest(type=want["name"]):
                self.assertIs(self.every[want["name"]]["stock"], want["key"] in stock_keys)
        stock = [n for n, e in self.every.items() if e["stock"]]
        own = [n for n, e in self.every.items() if not e["stock"]]
        self.assertTrue(stock and own, "the shipped template should carry both kinds")

    def test_the_additions_are_exactly_the_types_ekahau_does_not_ship(self):
        self.assertEqual(sorted(a["name"] for a in self.plan["add"]),
                         sorted(n for n, e in self.every.items() if not e["stock"]))

    def test_an_update_names_what_it_changes(self):
        elevator = self.every["Elevator Shaft"]      # recoloured on purpose
        self.assertIn("colour", elevator["changes"])
        for e in self.plan["update"]:
            with self.subTest(type=e["name"]):
                self.assertTrue(e["changes"], "an update that names nothing")

    def test_each_kind_of_difference_gets_its_own_label(self):
        base = [dict(w) for w in STOCK[:1]]
        want = dict(base[0])
        cases = {
            "colour": {"color": "#123456"},
            "number key": {"keybindNumber": 7},
            "thickness": {"thickness": 9.5},
            "height": {"upperEdge": 3.0},
        }
        for label, change in cases.items():
            with self.subTest(label=label):
                plan = wall_inject.plan_into_members(project(base), [dict(want, **change)])
                self.assertEqual(plan["update"][0]["changes"], [label])
        att = copy.deepcopy(want)
        att["propagationProperties"][0]["attenuationFactor"] += 4
        plan = wall_inject.plan_into_members(project(base), [att])
        self.assertEqual(plan["update"][0]["changes"], ["attenuation"])

    def test_a_colour_that_is_not_a_hex_value_is_not_passed_on(self):
        odd = dict(STOCK[0], name="Invented Pod", key="InventedPod", color="red;background:url(x)")
        plan = wall_inject.plan_into_members(project(), [odd])
        self.assertIsNone(plan["add"][0]["color"])

    def test_without_the_stock_list_nothing_is_called_the_templates_own(self):
        with mock.patch.object(template_store, "DEFAULTS_FILE", ROOT / "templates" / "no-such-file.json"):
            plan = wall_inject.plan_into_members(project(), WD)
        for e in plan["add"] + plan["update"] + plan["same"]:
            self.assertIsNone(e["stock"])


PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(head) {
  const a = src.indexOf(head);
  if (a < 0) throw new Error(head + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
const code = slice('  function wallTypeRows(') + ' ' + slice('  function renderPreview(r) {')
  + ' ' + slice('  function captionFor(f) {');
const el = {};
function $(id) { return el[id] || (el[id] = { id, hidden: false, innerHTML: '', textContent: '', disabled: false, checked: true }); }
function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function plural(n, one) { return n === 1 ? one : one + 's'; }
function escAttr(s) { return esc(s); }
function renderMap() {}
function syncTrimControls() {}
function selectedText() { return 'His template'; }
function setStatus(step, text) { $('prepStatus-' + step).textContent = text; }
var trim = { boxes: {}, loaded: true }, lastPlan = null, fromDisk = false, stage = 'trim';
function setGo() {}
eval(code);
const mode = process.argv[2];
if (mode === 'caption') {
  const out = {};
  [['trim', {}], ['trim', { f1: [0, 0, 1, 1] }]].forEach(function (c, i) {
    stage = c[0]; trim.boxes = c[1]; captionFor({ id: 'f1' });
    out[i] = $('prepMapCaption').textContent;
  });
  console.log(JSON.stringify(out));
} else {
  renderPreview(JSON.parse(process.argv[3]));
  console.log(JSON.stringify({ html: $('prepWallList').innerHTML }));
}
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePageGroupsThem(unittest.TestCase):

    def run_probe(self, *args):
        out = subprocess.run(["node", "-e", PROBE, str(ROOT / "web/assets/js/prep.js"), *args],
                             capture_output=True, text=True, encoding="utf-8", timeout=120)
        if out.returncode != 0:
            raise AssertionError((out.stdout + out.stderr).strip())
        return json.loads(out.stdout.strip().splitlines()[-1])

    def render(self, walls):
        r = {"ok": True, "steps": ["walls"], "step": {"walls": walls}}
        return self.run_probe("preview", json.dumps(r))["html"]

    def shipped(self):
        return wall_inject.plan_into_members(project(), WD)

    def test_ekahaus_defaults_and_the_templates_own_are_in_separate_groups(self):
        html = self.render(self.shipped())
        a, b = html.index("Ekahau default types"), html.index("Only in this template")
        self.assertLess(a, b)
        for want in WD:
            with self.subTest(type=want["name"]):
                at = html.index(">" + want["name"] + "<")
                stock = want["key"] in {w["key"] for w in STOCK}
                self.assertEqual(at < b, stock, "%s is in the wrong group" % want["name"])

    def test_every_type_gets_a_row_with_its_colour(self):
        html = self.render(self.shipped())
        self.assertEqual(html.count('class="pw-row"'), len(WD))
        for want in WD:
            with self.subTest(type=want["name"]):
                self.assertIn('style="background:%s"' % want["color"], html)

    def test_an_update_says_what_it_changes_and_a_match_says_it_matches(self):
        html = self.render(self.shipped())
        self.assertIn("changes colour, number key", html)
        self.assertIn(">Matches<", html)
        self.assertIn(">Update<", html)
        self.assertIn(">Add<", html)

    def test_a_renamed_type_says_what_the_project_calls_it(self):
        html = self.render({"ok": True, "add": [], "unchanged": 0, "skip": [], "same": [],
                            "update": [{"name": "Wall, Dry", "was": "Dry Wall", "stock": True,
                                        "color": "#c3a480", "changes": ["name"]}]})
        self.assertIn("called “Dry Wall” in this project", html)

    def test_a_name_and_a_colour_cannot_inject_markup(self):
        html = self.render({"ok": True, "unchanged": 0, "skip": [], "same": [], "update": [],
                            "add": [{"name": "<img src=x onerror=alert(1)>", "stock": False,
                                     "color": "red;background:url(http://x/)"}]})
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)
        self.assertNotIn("url(", html)

    def test_a_server_that_does_not_say_still_lists_the_names(self):
        html = self.render({"ok": True, "unchanged": 3, "skip": [],
                            "add": [{"name": "Invented Pod"}],
                            "update": [{"name": "Elevator Shaft", "was": "Elevator Shaft"}]})
        self.assertIn("Invented Pod", html)
        self.assertIn("Elevator Shaft", html)
        self.assertIn("3 already match the template", html)

    def test_drawing_a_box_is_explained_with_the_key_that_moves_the_plan(self):
        captions = self.run_probe("caption")
        for text in captions.values():
            with self.subTest(text=text):
                self.assertIn("Space", text)
                self.assertIn("hand", text)


if __name__ == "__main__":
    unittest.main()
