"""Every margin preset is a real-world distance, and the measurement proves it.

He spotted the defect himself, prefaced with "but what do I know":

    "You've got tight which is 10 pixels, and then normal which is 10 ft, and
    then wide at 20 ft, and then extra wide at 33 ft, which is a little weird,
    it's not scaling upward correctly."

He was right twice over.

1. `tight` was `0`, which fell through to DEFAULT_MARGIN - **ten pixels**. A
   pixel margin is a different real-world size on every drawing, so it was the
   one preset that meant something different every time it was used, while the
   others meant the same thing everywhere.
2. The others were 3, 6 and 10 **metres**, displayed in feet, which is why they
   read as 10, 20 and 33 - a clean metric progression that looks arbitrary once
   rendered in the unit the person is actually working in.

Both are fixed by the same rule, which is what this file holds: **a preset is a
number of feet, stored as the metres that number really is, converted to pixels
through the plan's own metersPerUnit.** So the assertion is not "wide keeps more
than normal" - it is "the margin measured off the saved file is the distance on
the label, to the foot".

The fixture is deliberately coarse (0.5 m per pixel) so that even a 200 ft
margin fits on the sheet and every preset can be measured without clamping.
Nothing here comes from a real project.
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from server import API_REQUEST_HEADER, app
from tools import esx_trimmer, prep_pipeline

import subprocess
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_prep_trim_options import make_esx, plan_of, W, H  # noqa: E402

#: The fixture's ink block, in pixels. make_esx draws (500,400)-(700,500).
INK_W, INK_H = 200, 100
#: Coarse on purpose: 200 ft is 122 px here, so nothing clamps.
COARSE = 0.5


class EveryPresetIsTheDistanceOnItsLabel(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-margin-real-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = make_esx(self.tmp / "in.esx", mpu=COARSE)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _kept_feet(self, margin):
        """The margin actually left on the saved plan, in feet, per side."""
        out = self.tmp / f"m-{margin}.esx"
        prep_pipeline.run(str(self.src), dest=str(out), steps=["trim"],
                          margin=margin)
        plan = plan_of(out)
        px = (plan["width"] - INK_W) / 2.0
        return px * COARSE * esx_trimmer.FEET_PER_METRE

    def test_each_preset_measures_the_feet_it_claims(self):
        """The assertion the old table could not have passed."""
        for name, feet in esx_trimmer.MARGIN_PRESET_FEET.items():
            with self.subTest(preset=name, feet=feet):
                got = self._kept_feet(name)
                self.assertAlmostEqual(
                    got, feet, delta=1.0,
                    msg=f"{name} says {feet} ft and kept {got:.1f} ft")

    def test_tight_is_a_distance_rather_than_a_pixel_count(self):
        """The defect he found. A pixel margin is not a distance at all.

        Two plans of the same pixel size at different scales: a real distance
        keeps a different number of pixels on each. Ten pixels keeps ten on
        both, which is what it used to do.
        """
        coarse = make_esx(self.tmp / "c.esx", mpu=0.5)
        fine = make_esx(self.tmp / "f.esx", mpu=0.05)
        widths = []
        for i, src in enumerate((coarse, fine)):
            dest = self.tmp / f"t-{i}.esx"
            prep_pipeline.run(str(src), dest=str(dest), steps=["trim"],
                              margin="tight")
            widths.append(plan_of(dest)["width"])
        self.assertNotEqual(widths[0], widths[1],
                            "tight kept the same pixels on two different "
                            "scales, so it is still a pixel count")

    def test_the_progression_rises_and_is_round_in_feet(self):
        """What he actually complained about: 10, 20, 33 is not a progression
        anybody chose, it is 3, 6, 10 metres seen through a conversion."""
        feet = list(esx_trimmer.MARGIN_PRESET_FEET.values())
        self.assertEqual(feet, sorted(feet), "the presets do not rise in order")
        for f in feet:
            with self.subTest(feet=f):
                self.assertEqual(f, round(f),
                                 f"{f} ft is not a round number of feet")

    def test_the_metres_stored_are_the_feet_converted_exactly(self):
        for name, feet in esx_trimmer.MARGIN_PRESET_FEET.items():
            with self.subTest(preset=name):
                self.assertAlmostEqual(esx_trimmer.MARGIN_PRESETS[name],
                                       feet * 0.3048, places=3)

    def test_there_is_a_parking_lot_and_it_is_the_largest(self):
        """His ask: 'we need a fifth one called parking lot where we go out
        I'm going to say like 200 ft'."""
        self.assertIn("parking-lot", esx_trimmer.MARGIN_PRESETS)
        biggest = max(esx_trimmer.MARGIN_PRESET_FEET,
                      key=esx_trimmer.MARGIN_PRESET_FEET.get)
        self.assertEqual(biggest, "parking-lot")

    def test_the_scale_is_byte_identical_whatever_the_margin(self):
        before = plan_of(self.src)["metersPerUnit"]
        for name in esx_trimmer.MARGIN_PRESET_FEET:
            with self.subTest(preset=name):
                out = self.tmp / f"s-{name}.esx"
                prep_pipeline.run(str(self.src), dest=str(out), steps=["trim"],
                                  margin=name)
                self.assertEqual(repr(plan_of(out)["metersPerUnit"]),
                                 repr(before))


class AMarginNeverInventsPaper(unittest.TestCase):
    """Clamped to the sheet, in every direction.

    Asking for 200 ft on a plan that only carries 80 ft of site keeps the 80
    and stops. It must never extend past the image edge, and it must never
    error - "there was nothing more to keep" is an answer.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-margin-clamp-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_margin_larger_than_the_sheet_keeps_the_sheet_and_no_more(self):
        src = make_esx(self.tmp / "in.esx", mpu=0.05)   # 200 ft = 1219 px
        rep = esx_trimmer.analyze(src, margin="parking-lot")
        f = rep.floors[0]
        if f.action == "trimmed":
            self.assertLessEqual(f.new_size[0], W)
            self.assertLessEqual(f.new_size[1], H)
            self.assertGreaterEqual(f.offset[0], 0)
            self.assertGreaterEqual(f.offset[1], 0)
        else:
            # The honest outcome when the margin covers the whole sheet.
            self.assertEqual(f.action, "skipped")
            self.assertIn("fills", f.reason)

    def test_it_does_not_raise(self):
        src = make_esx(self.tmp / "in2.esx", mpu=0.05)
        esx_trimmer.analyze(src, margin=1000.0)          # a kilometre


class TheWireCanCarryATypedDistance(unittest.TestCase):
    """"I don't know if 200 ft is the magic number, I just threw it out."

    So the number is typed rather than shipped. The only trap is that the
    trimmer's oldest form, a bare integer, means **pixels** - so a typed
    distance has to arrive in a shape that cannot be mistaken for one.
    """

    def test_a_preset_name_survives(self):
        self.assertEqual(esx_trimmer.parse_margin("wide"), "wide")

    def test_metres_are_marked_and_come_back_as_a_float(self):
        self.assertAlmostEqual(esx_trimmer.parse_margin("60.96m"), 60.96)
        self.assertIsInstance(esx_trimmer.parse_margin("60.96m"), float)

    def test_a_bare_integer_is_still_pixels(self):
        """The legacy form. 60 and 60m are both plausible and mean very
        different things; the marker is what keeps them apart."""
        self.assertEqual(esx_trimmer.parse_margin("60"), 60)
        self.assertIsInstance(esx_trimmer.parse_margin("60"), int)

    def test_nonsense_falls_back_to_the_default_rather_than_to_zero(self):
        for raw in ("", "   ", "banana", "m", "-5m", "0m"):
            with self.subTest(raw=raw):
                self.assertEqual(esx_trimmer.parse_margin(raw),
                                 esx_trimmer.DEFAULT_MARGIN_PRESET)

    def test_a_typed_distance_crops_to_that_distance_through_the_route(self):
        """End to end: the page sends metres, the file comes back that size."""
        tmp = Path(tempfile.mkdtemp(prefix="wd-margin-wire-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        try:
            src = make_esx(tmp / "in.esx", mpu=COARSE)
            client = app.test_client()
            feet = 120
            metres = feet * 0.3048
            r = client.post(
                f"/api/prep/run?name=x.esx&steps=trim&margin={metres:.4f}m",
                data=src.read_bytes(), headers={API_REQUEST_HEADER: "1"})
            try:
                self.assertEqual(r.status_code, 200, r.get_data()[:200])
                with zipfile.ZipFile(io.BytesIO(r.get_data())) as z:
                    plan = json.loads(z.read("floorPlans.json"))["floorPlans"][0]
            finally:
                r.close()
            kept_ft = ((plan["width"] - INK_W) / 2.0 * COARSE
                       * esx_trimmer.FEET_PER_METRE)
            self.assertAlmostEqual(kept_ft, feet, delta=1.0,
                                   msg=f"asked {feet} ft, kept {kept_ft:.1f} ft")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TheSheetSaysHowMuchSiteItCarries(unittest.TestCase):
    """The measurement that makes choosing a margin a decision rather than a
    guess: how much drawing is there beyond the building, each way.

    Without it, "is 200 ft the right number" can only be answered by trying one
    and comparing canvas sizes. With it, a sheet carrying 80 ft of site says so,
    and every margin above 80 is visibly the same margin.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-clearance-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_it_measures_the_real_distance_to_each_edge(self):
        # Ink at (500,400)-(700,500) on a 1200x900 sheet at 0.05 m/px.
        src = make_esx(self.tmp / "in.esx", mpu=0.05)
        c = esx_trimmer.analyze(src, margin="normal").floors[0].clearance
        self.assertIsNotNone(c, "no clearance was measured at all")
        self.assertAlmostEqual(c["left"], 500 * 0.05, delta=0.6)
        self.assertAlmostEqual(c["right"], (W - 700) * 0.05, delta=0.6)
        self.assertAlmostEqual(c["top"], 400 * 0.05, delta=0.6)
        self.assertAlmostEqual(c["bottom"], (H - 500) * 0.05, delta=0.6)

    def test_it_does_not_move_when_the_margin_does(self):
        """It describes the sheet, not the crop. If it changed with the margin
        it could not be used to choose one."""
        src = make_esx(self.tmp / "in.esx", mpu=COARSE)
        seen = [esx_trimmer.analyze(src, margin=m).floors[0].clearance
                for m in ("tight", "normal", "parking-lot")]
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(seen[1], seen[2])

    def test_a_plan_with_no_scale_quotes_no_distance(self):
        """Rather than quoting pixels as though they were feet."""
        src = make_esx(self.tmp / "noscale.esx", mpu=0)
        self.assertIsNone(esx_trimmer.analyze(src).floors[0].clearance)

    def test_it_reaches_the_page(self):
        src = make_esx(self.tmp / "in.esx", mpu=0.05)
        got = esx_trimmer.api_analyze(str(src), margin="normal")
        self.assertIn("clearance", got["floors"][0])
        self.assertIsNotNone(got["floors"][0]["clearance"])


if __name__ == "__main__":
    unittest.main()


PLANTRIM_HTML = ROOT_DIR / "web" / "plantrim.html"
PREP_HTML_F = ROOT_DIR / "web" / "prep.html"
PLANTRIM_JS = ROOT_DIR / "web" / "assets" / "js" / "plantrim.js"
PREP_JS_F = ROOT_DIR / "web" / "assets" / "js" / "prep.js"


class BothToolsOfferTheSameFiveAndACustomBox(unittest.TestCase):
    """PlanTrim and Prep share the setting, so they have to share the list.
    A preset offered in one and not the other is a saved value the other
    silently cannot honour."""

    PAGES = (("plantrim.html", PLANTRIM_HTML, "ptb"),
             ("prep.html", PREP_HTML_F, "prep"))

    def test_every_preset_the_trimmer_knows_is_offered_in_both(self):
        for label, path, _ in self.PAGES:
            html = path.read_text(encoding="utf-8")
            for preset in esx_trimmer.MARGIN_PRESETS:
                with self.subTest(page=label, preset=preset):
                    self.assertIn(f'value="{preset}"', html)

    def test_every_option_states_the_distance_it_produces(self):
        """"Normal" on its own tells you nothing about what you are getting."""
        for label, path, _ in self.PAGES:
            html = path.read_text(encoding="utf-8")
            for preset, feet in esx_trimmer.MARGIN_PRESET_FEET.items():
                with self.subTest(page=label, preset=preset):
                    opt = html[html.index(f'value="{preset}"'):]
                    opt = opt[:opt.index("</option>")]
                    self.assertIn(f"{feet} ft", opt,
                                  f"{preset} does not say how far it goes")

    def test_no_option_quotes_a_number_of_pixels(self):
        """The old `tight` label. A pixel count is not a distance."""
        for label, path, _ in self.PAGES:
            with self.subTest(page=label):
                html = path.read_text(encoding="utf-8")
                sel = html[html.index("Margin" if label.startswith("plan")
                                      else "Leave a margin of"):]
                sel = sel[:sel.index("</select>")]
                self.assertNotIn("pixel", sel.lower())

    def test_there_is_a_custom_box_and_it_starts_hidden(self):
        for label, path, prefix in self.PAGES:
            with self.subTest(page=label):
                html = path.read_text(encoding="utf-8")
                self.assertIn('value="custom"', html)
                wrap = html[html.index(f'id="{prefix}MarginCustomWrap"'):]
                self.assertIn("hidden", wrap[:200],
                              "the custom box is on screen before it is chosen")

    def test_the_custom_box_starts_at_his_number(self):
        for label, path, prefix in self.PAGES:
            with self.subTest(page=label):
                html = path.read_text(encoding="utf-8")
                box = html[html.index(f'id="{prefix}MarginFt"'):]
                box = box[:box.index(">")]
                self.assertIn(
                    f'value="{esx_trimmer.DEFAULT_CUSTOM_MARGIN_FEET}"', box)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ATypedDistanceLeavesThePageAsMetres(unittest.TestCase):
    """The page's half of the wire format, driven rather than grepped.

    Both tools build the parameter themselves, so both can get it wrong
    independently - and sending `200` instead of `60.96m` would be read as two
    hundred *pixels* and crop far tighter than asked, silently.
    """

    CASES = (
        ("plantrim.js", PLANTRIM_JS, """
         const a = src.indexOf('  function marginParam()');
         const b = src.indexOf('  function syncMarginUi()');
         if (a < 0 || b < 0) throw new Error('marginParam moved');
         var state = { margin: MARGIN };
         globalThis.$ = () => ({ value: String(FEET) });
         eval(src.slice(a, b));
         """),
        ("prep.js", PREP_JS_F, """
         const a = src.indexOf('  function marginParam()');
         const b = src.indexOf('  function loadTemplates(');
         if (a < 0 || b < 0) throw new Error('marginParam moved');
         globalThis.$ = (id) => ({ value: id === 'prepMargin' ? MARGIN
                                                              : String(FEET) });
         eval(src.slice(a, b));
         """),
    )

    def _param(self, body, path, margin, feet):
        script = (
            "const fs = require('fs');\n"
            "const src = fs.readFileSync(process.argv[1], 'utf8');\n"
            "globalThis.WD = { METRES_PER_FOOT: 0.3048,"
            " DEFAULT_CUSTOM_MARGIN_FT: 200 };\n"
            + body.replace("MARGIN", json.dumps(margin))
                  .replace("FEET", json.dumps(feet))
            + "\nconsole.log(JSON.stringify({ v: marginParam() }));"
        )
        proc = subprocess.run(["node", "-e", script, str(path)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=120)
        if proc.returncode != 0:
            raise AssertionError("node failed:\n" + proc.stderr)
        return json.loads(proc.stdout)["v"]

    def test_a_preset_goes_by_name(self):
        for label, path, body in self.CASES:
            with self.subTest(file=label):
                self.assertEqual(self._param(body, path, "parking-lot", 200),
                                 "parking-lot")

    def test_a_typed_distance_goes_as_marked_metres(self):
        for label, path, body in self.CASES:
            with self.subTest(file=label):
                v = self._param(body, path, "custom", 120)
                self.assertTrue(v.endswith("m"), f"{v} is not marked as metres")
                self.assertAlmostEqual(float(v[:-1]), 120 * 0.3048, places=3)

    def test_what_the_page_sends_is_what_the_server_reads(self):
        """The two halves of the format, checked against each other rather than
        each against its own idea of it."""
        for label, path, body in self.CASES:
            with self.subTest(file=label):
                v = self._param(body, path, "custom", 200)
                parsed = esx_trimmer.parse_margin(v)
                self.assertIsInstance(parsed, float)
                self.assertAlmostEqual(parsed, 200 * 0.3048, places=2)
