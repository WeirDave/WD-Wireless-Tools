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
        self.src = make_esx(self.tmp / "in.esx")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _trim(self, margin):
        out = self.tmp / f"out-{margin}.esx"
        prep_pipeline.run(str(self.src), dest=str(out), steps=["trim"],
                          margin=margin, backup=False)
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
                              margin="normal", backup=False)
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


class SavedBoxesAreOfferedNotAssumed(unittest.TestCase):
    """Drawing a rectangle cannot be a batch control; a rectangle already drawn
    is just data, and reusing it saves him drawing it twice. It is opt-in, so
    the default pass is unchanged."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-prep-boxes-"))
        self.src = make_esx(self.tmp / "in.esx")
        self.client = app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_saved_box_crops_to_itself_rather_than_to_the_ink(self):
        auto = self.tmp / "auto.esx"
        boxed = self.tmp / "boxed.esx"
        prep_pipeline.run(str(self.src), dest=str(auto), steps=["trim"],
                          margin="tight", backup=False)
        prep_pipeline.run(str(self.src), dest=str(boxed), steps=["trim"],
                          margin="tight", backup=False,
                          boxes={FLOOR: [100, 80, 900, 700]})
        self.assertEqual((plan_of(boxed)["width"], plan_of(boxed)["height"]),
                         (800.0, 620.0))
        self.assertNotEqual(plan_of(auto)["width"], plan_of(boxed)["width"])

    def test_the_page_only_offers_them_when_there_are_some(self):
        js = PREP_JS.read_text(encoding="utf-8")
        self.assertIn("savedBoxes", js)
        body = js[js.index("function syncSavedBoxes"):]
        body = body[:body.index("function renderPreview")]
        self.assertIn("row.hidden = !n", body,
                      "the offer must not appear when there is nothing to offer")

    def test_they_are_not_used_unless_asked_for(self):
        js = PREP_JS.read_text(encoding="utf-8")
        self.assertIn("useBoxes=1", js)
        html = PREP_HTML.read_text(encoding="utf-8")
        row = html[html.index('id="prepUseBoxesRow"'):]
        self.assertIn("hidden", row[:200], "the row ships hidden")
        checkbox = html[html.index('id="prepUseBoxes"'):]
        self.assertNotIn("checked", checkbox[:120], "and unticked")


class TheOptionsBelongToTheStep(unittest.TestCase):
    """His ask was about the layout: "select options right below the what to
    do". The block sits under the trim step and appears with it."""

    def test_the_block_sits_under_the_trim_step(self):
        html = PREP_HTML.read_text(encoding="utf-8")
        trim_step = html.index('id="prepStep-trim"')
        opts = html.index('id="prepTrimOpts"')
        areas_step = html.index('id="prepStep-areas"')
        self.assertLess(trim_step, opts, "the options come after their step")
        self.assertLess(opts, areas_step, "and before the next one")

    def test_it_is_styled_as_the_other_steps_options_are(self):
        html = PREP_HTML.read_text(encoding="utf-8")
        block = html[html.index('id="prepTrimOpts"') - 40:]
        self.assertIn('class="prep-opts"', block[:80])

    def test_it_is_shown_and_hidden_with_its_step(self):
        js = PREP_JS.read_text(encoding="utf-8")
        self.assertIn("$('prepTrimOpts').hidden = !$('prepStep-trim').checked;", js)

    def test_there_is_no_second_place_to_set_this(self):
        """Not a tab, not a gear, not a modal - one place, under the step."""
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


class TheRangeIsUsefulAtTheGenerousEnd(unittest.TestCase):
    """The complaint was that the crop came in too tight, so a range that only
    goes tighter than the default answers nothing. Two settings looser than the
    default, and the loosest has to be worth choosing."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-prep-generous-"))
        self.src = make_esx(self.tmp / "in.esx", mpu=0.05)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _width(self, margin):
        out = self.tmp / f"g-{margin}.esx"
        prep_pipeline.run(str(self.src), dest=str(out), steps=["trim"],
                          margin=margin, backup=False)
        return plan_of(out)["width"]

    def test_two_presets_are_looser_than_the_default(self):
        default = self._width(esx_trimmer.DEFAULT_MARGIN_PRESET)
        looser = [p for p in esx_trimmer.MARGIN_PRESETS if self._width(p) > default]
        self.assertGreaterEqual(len(looser), 2,
                                f"only {looser} keep more than the default")

    def test_the_loosest_keeps_substantially_more_than_the_default(self):
        """A generous end that is barely distinguishable is theatre."""
        building = 200.0                     # the ink in the fixture, in pixels
        default = self._width(esx_trimmer.DEFAULT_MARGIN_PRESET) - building
        loosest = self._width("extra-wide") - building
        self.assertGreaterEqual(loosest, 3 * default,
                                f"loosest {loosest}px vs default {default}px")

    def test_the_default_is_not_the_tightest_thing_on_offer(self):
        """Prep sent the bare 10-pixel DEFAULT_MARGIN until v2.103.0, which is
        `tight` by another name. That is the crop he was reacting to."""
        self.assertGreater(self._width(esx_trimmer.DEFAULT_MARGIN_PRESET),
                           self._width("tight"))
