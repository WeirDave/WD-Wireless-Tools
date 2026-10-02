"""Capacity: what the page says is what the file gets.

Three faults from the second functional review:

* **Rounding.** The server rounded each row with Python's ``round()`` - half
  to even - and the page with ``Math.round`` - half up - so 22.5 laptops were
  23 on the page and 22 in the file. The page also rounded the total on its
  own rather than adding up its rows. Both now round each row half up and
  total the rows; checked against the shipped example template.
* **A stale plan.** The headcount box plans on every keystroke with no
  ordering, so a late reply for an older headcount could be the card on
  screen while Apply wrote the newer one. Plans are numbered, only the
  newest is drawn, and Apply waits while it is out.
* **Template file names.** Every non-Latin name stripped to ``capacity``, so
  only one such template could exist. Letters and digits of any script are
  kept, on the server and in the page's mirror of it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from tools import capacity_profiles as cap  # noqa: E402

HDR = {"X-WD-Wireless-Tools": "1"}
CAPACITY_JS = ROOT / "web" / "assets" / "js" / "capacity.js"
EXAMPLE = ROOT / "templates" / "Office_Wi-Fi_6E_example_capacitytemplate.json"
HEADCOUNTS = (5, 15, 25, 201)

SLICE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(sig) {
  const a = src.indexOf(sig);
  if (a < 0) throw new Error(sig + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
"""

# The template card the page draws before Apply, at a headcount.
VIEW = SLICE + r"""
const tpl = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const people = JSON.parse(process.argv[3]);
const els = {};
global.$ = id => els[id] || (els[id] = { id, innerHTML: '', textContent: '', disabled: false, value: '' });
global.esc = s => String(s);
global.templates = [tpl]; global.chosen = 'x'; global.defaultTemplate = '';
global.templateByFile = () => tpl; global.resetDelete = () => {};
global.shortDevice = s => s; global.fmtPer = n => String(n);
eval(slice('function devicesFor(') + ';global.devicesFor=devicesFor;');
eval(slice('function renderTemplateView() {') + ';global.renderTemplateView=renderTemplateView;');
const out = {};
for (const n of people) {
  $('capHeadcount').value = String(n);
  renderTemplateView();
  const cells = [...$('capTplView').innerHTML.matchAll(/<td class="cap-n( cap-total)?">([^<]*)<\/td><\/tr>/g)].map(m => Number(m[2]));
  out[n] = { rows: cells.slice(0, -1), total: cells[cells.length - 1] };
}
console.log(JSON.stringify(out));
"""

PLAN = SLICE + r"""
(async () => {
  const els = {};
  global.$ = id => els[id] || (els[id] = { id, innerHTML: '', textContent: '', disabled: false, value: '' });
  global.window = global;
  global.esc = s => String(s);
  global.renderTemplateView = () => {};
  global.fileBytes = new ArrayBuffer(1); global.chosen = 'x';
  global.applyQuery = () => '?occupants=' + $('capHeadcount').value;
  global.shortDevice = s => s; global.basisWords = s => s; global.fmtPeople = String;
  global.floorPeopleHtml = () => ''; global.existingPickHtml = () => '';
  const pending = [];
  global.api = (a, body, q) => new Promise(r => pending.push({ q, r }));
  eval(slice('function setApply(') + ';global.setApply=setApply;');
  eval('var planSeq = 0;' + slice('window.capPlan = function () {'));
  const reply = n => ({ ok: true, willWrite: 1, willSkip: 0, occupants: n, rows: [],
    floors: [], totalDevices: n, occupantsWritten: n, devicesWritten: n });
  const seen = [];
  $('capHeadcount').value = '20'; capPlan();
  $('capHeadcount').value = '200'; capPlan();
  seen.push({ inFlight: $('capApplyBtn').disabled });
  pending[1].r(reply(200)); await new Promise(r => setTimeout(r, 0));
  pending[0].r(reply(20)); await new Promise(r => setTimeout(r, 0));
  seen.push({ disabled: $('capApplyBtn').disabled, card: $('capPlan').innerHTML });
  console.log(JSON.stringify({ queries: pending.map(p => p.q), seen }));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""

FILES = SLICE + r"""
eval(slice('function templateFileFor(name) {') + ';global.templateFileFor=templateFileFor;');
console.log(JSON.stringify(JSON.parse(process.argv[2]).map(templateFileFor)));
"""


def _node(probe: str, *args: str):
    r = subprocess.run(["node", "-e", probe, str(CAPACITY_JS), *args],
                       capture_output=True, encoding="utf-8", timeout=30)
    if r.returncode:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout)


class TheServerRoundsHalfUpTests(unittest.TestCase):
    def test_a_half_is_rounded_up(self):
        tpl = {"items": [{"device": "Invented Laptop", "usage": "Invented", "perOccupant": 0.9}]}
        r = cap.apply_headcount(tpl, 25)
        self.assertEqual(r["rows"][0]["deviceCount"], 23)
        self.assertEqual(r["totalDevices"], 23)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePageShowsWhatIsWrittenTests(unittest.TestCase):
    def test_the_template_card_agrees_with_the_writer_on_the_shipped_example(self):
        tpl = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        page = _node(VIEW, str(EXAMPLE), json.dumps(list(HEADCOUNTS)))
        for n in HEADCOUNTS:
            written = cap.apply_headcount(tpl, n)
            with self.subTest(people=n):
                self.assertEqual(page[str(n)]["rows"], [r["deviceCount"] for r in written["rows"]])
                self.assertEqual(page[str(n)]["total"], written["totalDevices"])

    def test_a_stale_plan_reply_is_dropped_and_apply_waits_for_the_current_one(self):
        out = _node(PLAN)
        self.assertEqual(out["queries"], ["?occupants=20", "?occupants=200"])
        self.assertTrue(out["seen"][0]["inFlight"])
        self.assertFalse(out["seen"][1]["disabled"])
        card = out["seen"][1]["card"].replace("<b>", "").replace("</b>", "")
        self.assertIn(" 200 people, 200 devices", card)
        self.assertNotIn(" 20 people, 20 devices", card)


class NonLatinNamesHaveTheirOwnFileTests(unittest.TestCase):
    NAMES = ["Офис", "Склад", "倉庫", "Büro", "Lab #1", "Lab 1", "  ", "Invented office"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        orig = cap.USER_DIR
        cap.USER_DIR = Path(self.tmp.name) / "capacity"
        self.addCleanup(setattr, cap, "USER_DIR", orig)
        self.client = server.app.test_client()

    def build(self, name):
        spec = {"name": name, "items": [
            {"device": "Invented Laptop", "usage": "Invented Usage", "perOccupant": 1}]}
        return self.client.post("/api/capacity/build", json={"spec": spec},
                                headers=HDR).get_json()

    def test_two_cyrillic_templates_both_save(self):
        a, b = self.build("Офис"), self.build("Склад")
        self.assertTrue(a["ok"], a)
        self.assertTrue(b["ok"], b)
        self.assertNotEqual(a["file"], b["file"])
        names = sorted(t["name"] for t in cap.list_templates()["templates"] if not t["_builtin"])
        self.assertEqual(names, ["Офис", "Склад"])

    def test_the_conflict_refusal_still_works(self):
        self.assertTrue(self.build("Lab #1")["ok"])
        r = self.build("Lab 1")
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("exists"))

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_the_page_names_the_same_file_as_the_server(self):
        page = _node(FILES, json.dumps(self.NAMES))
        self.assertEqual(page, [cap._safe_filename(n) for n in self.NAMES])


if __name__ == "__main__":
    unittest.main()
