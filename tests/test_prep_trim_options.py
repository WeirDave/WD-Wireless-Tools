"""Prep's trim options: they change the crop, and by default they change nothing.

Two questions, and the second is the one that protects him.

* Does setting a margin actually produce a different crop? A control that looks
  like it does something and does not is worse than no control.
* Does an untouched form produce exactly what it produced before the controls
  existed? This is an addition, not a change to what the button does, and the
  only way to know is to run the pass both ways and compare the members.

Everything here is built synthetically. Nothing comes from a real project.
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from server import API_REQUEST_HEADER, app
from tools import esx_trimmer, prep_pipeline

ROOT = Path(__file__).resolve().parent.parent
PREP_HTML = ROOT / "web" / "prep.html"
PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"

# Big enough, at the scale below, that every preset's margin still fits
# inside the sheet - otherwise the widest ones clamp to the full canvas and
# the trimmer rightly reports there is nothing to reclaim.
W, H = 1200, 900
FLOOR = "flr-0001"
IMAGE = "img-0001"


def _png(width, height, ink):
    rows = []
    x0, y0, x1, y1 = ink
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            dark = x0 <= x < x1 and y0 <= y < y1
            row += bytes((0, 0, 0) if dark else (255, 255, 255))
        rows.append(bytes(row))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows)))
            + chunk(b"IEND", b""))


def make_esx(path, mpu=0.05):
    """One floor with ink in the middle, so there is margin to reclaim."""
    members = {
        "project.json": {"project": {"id": "prj-0001", "name": "Example Site"}},
        "floorPlans.json": {"floorPlans": [{
            "id": FLOOR, "name": "Level 1", "imageId": IMAGE,
            "width": float(W), "height": float(H), "metersPerUnit": mpu,
            "cropMinX": 0.0, "cropMinY": 0.0,
            "cropMaxX": float(W), "cropMaxY": float(H)}]},
        "images.json": {"images": [{"id": IMAGE, "imageFormat": "PNG",
                                    "resolutionWidth": W, "resolutionHeight": H}]},
        "accessPoints.json": {"accessPoints": []},
        "wallTypes.json": {"wallTypes": []},
        "wallSegments.json": {"wallSegments": []},
        "areas.json": {"areas": []},
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, json.dumps(body))
        z.writestr("image-" + IMAGE, _png(W, H, (500, 400, 700, 500)))
    return path


def plan_of(path):
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("floorPlans.json"))["floorPlans"][0]


class MarginChangesTheCrop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-prep-margin-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = make_esx(self.tmp / "in.esx")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _trim(self, margin):
        out = self.tmp / f"out-{margin}.esx"
        prep_pipeline.run(str(self.src), dest=str(out), steps=["trim"],
                          margin=margin)
        return plan_of(out)

    def test_a_wider_margin_keeps_more_of_the_sheet(self):
        """The whole point of the control."""
        tight = self._trim("tight")
        normal = self._trim("normal")
        wide = self._trim("wide")
        self.assertLess(tight["width"], normal["width"],
                        "normal should keep more than tight")
        self.assertLess(normal["width"], wide["width"],
                        "wide should keep more than normal")

    def test_every_preset_is_offered_and_understood(self):
        """A name in the page that the trimmer does not know is a silent
        fallback to the default - the control would look like it worked."""
        html = PREP_HTML.read_text(encoding="utf-8")
        for preset in esx_trimmer.MARGIN_PRESETS:
            with self.subTest(preset=preset):
                self.assertIn(f'value="{preset}"', html)

    def test_the_margin_is_measured_on_the_plans_own_scale(self):
        """Two plans of the same pixel size but different scales must keep
        different amounts, or the setting is not a real distance."""
        coarse = make_esx(self.tmp / "coarse.esx", mpu=0.05)
        fine = make_esx(self.tmp / "fine.esx", mpu=0.02)
        outs = []
        for i, src in enumerate((coarse, fine)):
            dest = self.tmp / f"scaled-{i}.esx"
            prep_pipeline.run(str(src), dest=str(dest), steps=["trim"],
                              margin="normal")
            outs.append(plan_of(dest)["width"])
        self.assertNotEqual(outs[0], outs[1])

    def test_the_scale_survives_whatever_the_margin(self):
        before = plan_of(self.src)["metersPerUnit"]
        for margin in ("tight", "normal", "wide", "extra-wide"):
            with self.subTest(margin=margin):
                self.assertEqual(repr(self._trim(margin)["metersPerUnit"]),
                                 repr(before))


class UntouchedFormChangesNothing(unittest.TestCase):
    """The protection: adding controls must not move the default behaviour.

    Prep's default margin is the `normal` preset and was before these controls
    existed. A form nobody has touched must therefore produce the same archive,
    member for member, as calling the pipeline with no margin argument at all.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-prep-default-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = make_esx(self.tmp / "in.esx")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _members(path):
        with zipfile.ZipFile(path) as z:
            return {n: z.read(n) for n in sorted(z.namelist())}

    def test_the_page_default_is_the_pipeline_default(self):
        """What the selector ships selected has to be what the code already did."""
        html = PREP_HTML.read_text(encoding="utf-8")
        marker = f'value="{esx_trimmer.DEFAULT_MARGIN_PRESET}" selected'
        self.assertIn(marker, html,
                      "the selected option must be the pipeline's own default")

    def test_the_default_produces_byte_identical_output(self):
        """Through the route, because that is the path the page takes.

        The old page sent no margin at all; the new one sends the selector's
        value. An untouched selector has to make those two the same file.
        """
        client = app.test_client()

        def run(query):
            r = client.post("/api/prep/run?name=x.esx&steps=trim" + query,
                            data=self.src.read_bytes(),
                            headers={API_REQUEST_HEADER: "1"})
            try:
                self.assertEqual(r.status_code, 200, r.get_data()[:200])
                return r.get_data()
            finally:
                r.close()

        before = run("")                     # the page as it was
        after = run("&margin=normal")        # the page with nothing touched
        self.assertEqual(self._archive(after), self._archive(before))

    @staticmethod
    def _archive(blob):
        import io
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            return {n: z.read(n) for n in sorted(z.namelist())}


class ABoxIsTheDecisionOnTheCanvas(unittest.TestCase):
    """The Trim stage is PlanTrim's box editor, and a box on the plan is what
    the trim crops to. The boxes are PlanTrim's own, saved under the project's
    id, so one drawn in either tool is used by both - and it is on the plan and
    in the floor strip as "Your box", so it is never used unseen. With no box
    anywhere the pass is exactly the automatic one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-prep-boxes-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = make_esx(self.tmp / "in.esx")
        self.client = app.test_client()
        from tools import plantrim_store
        self.store = plantrim_store
        self.addCleanup(plantrim_store.forget, "prj-0001")

    def plan(self, query):
        r = self.client.post("/api/prep/plan?name=x.esx&steps=trim&margin=tight" + query,
                             data=self.src.read_bytes(),
                             headers={API_REQUEST_HEADER: "1"})
        body = r.get_json()
        self.assertTrue(body.get("ok"), body)
        return body

    def floor(self, body):
        return body["step"]["trim"]["floors"][0]

    def test_a_saved_box_crops_to_itself_rather_than_to_the_ink(self):
        auto = self.tmp / "auto.esx"
        boxed = self.tmp / "boxed.esx"
        prep_pipeline.run(str(self.src), dest=str(auto), steps=["trim"],
                          margin="tight")
        prep_pipeline.run(str(self.src), dest=str(boxed), steps=["trim"],
                          margin="tight",
                          boxes={FLOOR: [100, 80, 900, 700]})
        self.assertEqual((plan_of(boxed)["width"], plan_of(boxed)["height"]),
                         (800.0, 620.0))
        self.assertNotEqual(plan_of(auto)["width"], plan_of(boxed)["width"])

    def test_the_box_the_page_sends_is_the_crop(self):
        box = [100, 80, 900, 700]
        f = self.floor(self.plan("&boxes=" + json.dumps({FLOOR: box})))
        self.assertEqual(f["source"], "manual")
        self.assertEqual(f["offset"], [100, 80])
        self.assertEqual(f["newSize"], [800, 620])

    def test_the_saved_box_is_used_until_the_page_has_its_own(self):
        self.store.save("prj-0001", {FLOOR: [100, 80, 900, 700]})
        first = self.plan("&useBoxes=1")
        self.assertEqual(self.floor(first)["source"], "manual")
        # The facts that let the page show it and save changes to it.
        self.assertEqual(first["project"]["projectId"], "prj-0001")
        self.assertEqual(first["project"]["boxes"], {FLOOR: [100.0, 80.0, 900.0, 700.0]})
        self.assertEqual(first["project"]["floors"],
                         [{"id": FLOOR, "name": "Level 1", "w": W, "h": H}])

    def test_back_to_automatic_is_an_empty_set_and_beats_the_saved_one(self):
        self.store.save("prj-0001", {FLOOR: [100, 80, 900, 700]})
        f = self.floor(self.plan("&useBoxes=1&boxes=%7B%7D"))
        self.assertNotEqual(f.get("source"), "manual")

    def test_nothing_asked_for_is_automatic_whatever_is_saved(self):
        self.store.save("prj-0001", {FLOOR: [100, 80, 900, 700]})
        f = self.floor(self.plan(""))
        self.assertNotEqual(f.get("source"), "manual")

    def test_nonsense_boxes_are_automatic_rather_than_an_error(self):
        f = self.floor(self.plan("&boxes=not-json"))
        self.assertNotEqual(f.get("source"), "manual")

    def test_suggest_answers_for_a_dropped_project(self):
        r = self.client.post("/api/prep/suggest?name=x.esx", data=self.src.read_bytes(),
                             headers={API_REQUEST_HEADER: "1"})
        body = r.get_json()
        self.assertTrue(body["ok"], body)
        self.assertIsInstance(body["suggestions"], list)


BOX_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const els = {};
function el(id) {
  if (!els[id]) els[id] = {
    id, innerHTML: '', textContent: '', value: '', checked: false, hidden: false,
    disabled: false, style: {}, files: [], title: '', options: [], children: [],
    classList: { add() {}, remove() {}, toggle() {} },
    listeners: {}, addEventListener(t, f) { this.listeners[t] = f; }, click() {},
  };
  return els[id];
}
el('prepStep-trim').checked = true;
el('prepMargin').value = 'normal';
const docListeners = {};
global.document = { getElementById: el, addEventListener(t, f) { docListeners[t] = f; },
                    querySelector: () => null, visibilityState: 'visible' };
global.window = global;
const saves = [];
global.WD = {
  esc: s => String(s), escAttr: s => String(s).replace(/"/g, '&quot;'),
  toast() {}, applyVersions() {}, savedWallTemplateName: () => Promise.resolve(''),
  wallTemplateOrder: l => l, chooseWallTemplate: () => null, wallTemplateLabel: t => t.name,
  api: (action, body) => { if (action === 'plantrim/boxes_save') saves.push(body);
                           return Promise.resolve({ ok: true, settings: {} }); },
};
const calls = [];
const FLOORS = [{ id: 'f1', name: 'Ground', w: 800, h: 600 },
                { id: 'f2', name: 'Level 2', w: 800, h: 600 },
                { id: 'f3', name: 'Roof', w: 400, h: 300 }];
global.fetch = (url) => {
  calls.push(url);
  const body = url.indexOf('/prep/plan') >= 0
    ? { ok: true, steps: ['trim'], project: { projectId: 'prj-9', floors: FLOORS,
          boxes: { f1: [10, 20, 700, 500] }, wallCount: 0 },
        step: { trim: { trimmedCount: 1, floorCount: 3, floors: [
          { id: 'f1', name: 'Ground', action: 'trimmed', source: 'manual', areaSavedPct: 30,
            oldSize: [800, 600], newSize: [690, 480], offset: [10, 20] },
          { id: 'f2', name: 'Level 2', action: 'trimmed', areaSavedPct: 20,
            oldSize: [800, 600], newSize: [600, 500], offset: [100, 50] },
          { id: 'f3', name: 'Roof', action: 'skipped', reason: 'tight' }] } } }
    : url.indexOf('/prep/templates') >= 0 ? { ok: true, wall: [], capacity: [] }
    : { ok: true };
  return Promise.resolve({ json: () => Promise.resolve(body), ok: true,
                           headers: { get: () => null } });
};
const flush = () => new Promise(r => setTimeout(r, 0));
const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function param(url, name) {
  const m = new RegExp('[?&]' + name + '=([^&]*)').exec(url || '');
  return m ? decodeURIComponent(m[1]) : null;
}
function last() { return calls.filter(u => u.indexOf('/prep/plan') >= 0).pop(); }
(async () => {
  eval(src);
  docListeners.DOMContentLoaded();
  for (let i = 0; i < 5; i++) await flush();
  el('fileInput').listeners.change({ target: { files: [{ name: 'Invented.esx',
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) }], value: '' } });
  for (let i = 0; i < 8; i++) await flush();

  check('the first preview asks for the saved boxes', param(last(), 'useBoxes') === '1');
  check('it opens on the floor being cropped', /Your box/.test(el('prepMapStrip').innerHTML));
  check('the rail counts his box: ' + el('prepStatus-trim').textContent,
        /1 your box/.test(el('prepStatus-trim').textContent));

  window.prepSyncStepUi();
  for (let i = 0; i < 5; i++) await flush();
  check('after that the page sends its own set',
        JSON.stringify(JSON.parse(param(last(), 'boxes'))) === JSON.stringify({ f1: [10, 20, 700, 500] }));

  window.prepMapSelect('f1');
  window.prepTrimApplyAll();
  for (let i = 0; i < 5; i++) await flush();
  const all = JSON.parse(param(last(), 'boxes'));
  check('apply to all copies to the same-size floor only: ' + JSON.stringify(all),
        all.f2 && all.f2.join() === '10,20,700,500' && !all.f3);
  check('and saves them where PlanTrim reads them',
        saves.length && saves[saves.length - 1].projectId === 'prj-9'
        && saves[saves.length - 1].boxes.f2);

  window.prepTrimAuto();
  for (let i = 0; i < 5; i++) await flush();
  const after = JSON.parse(param(last(), 'boxes'));
  check('back to automatic takes this floor out: ' + JSON.stringify(after),
        !after.f1 && after.f2);

  window.prepMapSelect('f2');
  window.prepTrimAuto();
  window.prepTrimDraw();
  for (let i = 0; i < 5; i++) await flush();
  const drawn = JSON.parse(param(last(), 'boxes'));
  check('draw my own starts from what automatic keeps: ' + JSON.stringify(drawn.f2),
        drawn.f2 && drawn.f2.join() === '100,50,700,550');

  window.prepRun();
  for (let i = 0; i < 5; i++) await flush();
  const run = calls.filter(u => u.indexOf('/prep/run') >= 0).pop();
  check('prepare crops to the same boxes the preview showed',
        param(run, 'boxes') === param(last(), 'boxes'));

  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheTrimStageDrivesTheBoxes(unittest.TestCase):
    """The page's handlers, run against a stubbed server: what each one sends
    is what the trim will crop to."""

    def test_the_trim_controls_reach_the_server(self):
        r = subprocess.run(["node", "-e", BOX_HARNESS, str(PREP_JS)],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())


class TheOptionsBelongToTheStep(unittest.TestCase):
    """The margin lives in the Trim stage's panel, once."""

    def test_the_margin_is_in_the_trim_panel(self):
        html = PREP_HTML.read_text(encoding="utf-8")
        panel = html.index('id="prepPanel-trim"')
        margin = html.index('id="prepMargin"')
        areas = html.index('id="prepPanel-areas"')
        self.assertLess(panel, margin)
        self.assertLess(margin, areas)

    def test_there_is_no_second_place_to_set_this(self):
        """Not a tab, not a gear, not a modal - one place, in the stage."""
        html = PREP_HTML.read_text(encoding="utf-8")
        self.assertEqual(html.count('id="prepMargin"'), 1)


if __name__ == "__main__":
    unittest.main()


class TheMarginIsOneSettingNotTwo(unittest.TestCase):
    """His ask: "I wanted to have the trim settings reflective of what's in
    trim ... because we were cutting the plans too close to the rail for my
    taste."

    Offering the same four words in a second dropdown is not that. PlanTrim
    saves the chosen preset; Prep opened on its own hardcoded `normal` and
    ignored it, so a margin he had already widened in PlanTrim was thrown away
    on every new site - and Prep is the tool he runs on every new site. Nothing
    on screen said the two disagreed, and he reads these from a phone at work
    where going and looking is not an option.

    Driven through the real functions in Node rather than matched in the
    source, because "the string is present" has passed here for code that was
    never called.
    """

    PRELUDE = r"""
    const fs = require('fs');
    const src = fs.readFileSync(process.argv[1], 'utf8');
    const i = src.indexOf('  function loadMargin(');
    const j = src.indexOf('  function loadTemplates(', i);
    if (i < 0 || j < 0) throw new Error('loadMargin is no longer where it was');
    const saved = [];
    let value = 'normal';
    globalThis.window = globalThis;
    globalThis.document = { getElementById: () => ({
      get value() { return value; }, set value(v) { value = v; } }) };
    globalThis.$ = document.getElementById;
    globalThis.syncStepUi = () => {};
    globalThis.WD = {
      api: (path, body) => {
        if (path === 'settings/update') { saved.push(body); return Promise.resolve({}); }
        return Promise.resolve(globalThis.__SETTINGS__);
      },
    };
    eval(src.slice(i, j));
    """

    def _node(self, settings, script):
        prelude = ("globalThis.__SETTINGS__ = " + json.dumps(settings) + ";\n"
                   + self.PRELUDE)
        proc = subprocess.run(["node", "-e", prelude + script, str(PREP_JS)],
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=120)
        if proc.returncode != 0:
            raise AssertionError("node failed:\n" + proc.stderr)
        return json.loads(proc.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_prep_opens_on_the_margin_he_chose_in_plantrim(self):
        out = self._node(
            {"settings": {"plantrim": {"margin_preset": "extra-wide"}}},
            "loadMargin().then(() => console.log(JSON.stringify("
            "{ value: $().value })));")
        self.assertEqual(out["value"], "extra-wide",
                         "Prep ignored the margin he set in PlanTrim")

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_a_margin_picked_in_prep_is_remembered(self):
        """Otherwise he re-picks it on every site, from a phone, and the one
        time he forgets he gets a crop he did not want and no way to tell."""
        out = self._node(
            {"settings": {}},
            "prepSetMargin('wide');"
            "console.log(JSON.stringify({ saved: saved }));")
        self.assertEqual(len(out["saved"]), 1,
                         "picking a margin in Prep saved nothing")

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_it_writes_the_same_key_plantrim_reads(self):
        """A second key would look identical on screen and drift forever - the
        exact shape of the merge-rule bug the settings registry exists for."""
        out = self._node(
            {"settings": {}},
            "prepSetMargin('wide');"
            "console.log(JSON.stringify({ saved: saved }));")
        self.assertEqual(out["saved"][0],
                         {"patch": {"plantrim": {"margin_preset": "wide"}}})

    def test_neither_tool_invented_a_second_key(self):
        js = PREP_JS.read_text(encoding="utf-8")
        plantrim = (ROOT / "web" / "assets" / "js" / "plantrim.js").read_text(encoding="utf-8")
        for src, who in ((js, "prep.js"), (plantrim, "plantrim.js")):
            with self.subTest(file=who):
                self.assertIn("margin_preset", src)
                self.assertNotIn("prep_margin", src,
                                 f"{who} saves the margin somewhere of its own")

    def test_the_selector_saves_rather_than_only_redrawing(self):
        html = PREP_HTML.read_text(encoding="utf-8")
        sel = html[html.index('id="prepMargin"'):]
        self.assertIn("prepSetMargin", sel[:300],
                      "the margin dropdown does not save what he picks")

    def test_the_hint_does_not_claim_the_two_tools_always_agree(self):
        """It used to say Normal "is what PlanTrim uses", which stopped being
        true the moment he changed it there."""
        html = PREP_HTML.read_text(encoding="utf-8")
        self.assertNotIn("is the default and is what PlanTrim uses", html)
        self.assertIn("same setting as PlanTrim", html)
