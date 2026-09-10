"""Text drawn on a colour somebody picked has to be readable. Once, for all tools.

Every surface in the suite that paints a number, a label or a glyph on top of a
user-chosen colour has the same problem. It was answered three separate times,
with three different formulas and three different thresholds:

  wd-shared.js   Rec.601 brightness > 180   (Report used this)
  ap-rename.js   WCAG contrast ratio        (added when the labeler was fixed)
  walls-swap.js  Rec.601 luma > 150         (wall-type pills)

They disagreed about exactly the colours that matter. Ekahau green (#00FF00)
scores 150 and cyan (#00FFCE) 173, so both Rec.601 copies put white text on
them - a contrast ratio near 1.4, which is a number that is drawn and cannot be
read. There is one implementation now, in wd-shared.js, and these tests hold it.

Computed, not listed: Ekahau can add a swatch and a user can type a custom hex,
and a hardcoded list of "colours that need black" would be silently wrong the
first time either happens.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "web" / "assets" / "js"
SHARED_JS = JS_DIR / "wd-shared.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"

NODE_TIMEOUT_S = 120

# The ten swatches Ekahau offers in its Mark menu.
EKAHAU_PALETTE = {
    "yellow": "#FFE600", "orange": "#FF8500", "red": "#FF0000",
    "magenta": "#FF00FF", "purple": "#C297FF", "blue": "#0068FF",
    "gray": "#6B6B6B", "green": "#00FF00", "brown": "#C97700",
    "cyan": "#00FFCE",
}

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const a = source.indexOf('/* ── The Ekahau AP palette');
const b = source.indexOf('WD.toast = function', a);
if (a < 0 || b < 0) throw new Error('the shared contrast block moved');
const WD = {};
eval(source.slice(a, b));

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


def _js(text: str) -> str:
    return json.dumps(text)


def run_node(program: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["node", "-e", program, str(SHARED_JS)],
                              capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s. That is a Node "
            f"startup timeout, not a failure of the code under test."
        ) from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ReadableOnAnyColour(unittest.TestCase):

    def run_block(self, checks: str):
        result = run_node(NODE_PRELUDE + "eval(" + _js(checks) + ");")
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).strip())

    def test_every_ekahau_swatch_clears_wcag_aa(self):
        palette = json.dumps(EKAHAU_PALETTE)
        self.run_block(f"""
          var palette = {palette};
          var worst = 99, worstName = '';
          Object.keys(palette).forEach(function (name) {{
            var hex = palette[name];
            var ratio = WD.contrastRatio(hex, WD.readableOn(hex));
            if (ratio < worst) {{ worst = ratio; worstName = name; }}
          }});
          check('worst swatch was ' + worstName + ' at ' + worst.toFixed(2) +
                ':1, under the 4.5:1 AA floor', worst >= 4.5);
          done();
        """)

    def test_the_colours_that_were_unreadable_now_take_dark_ink(self):
        """Green is the one he reported; cyan and yellow failed the same way."""
        self.run_block("""
          check('green takes dark ink', WD.readableOn('#00FF00') === WD.DARK_INK);
          check('cyan takes dark ink',  WD.readableOn('#00FFCE') === WD.DARK_INK);
          check('yellow takes dark ink', WD.readableOn('#FFE600') === WD.DARK_INK);
          check('pale lavender takes dark ink', WD.readableOn('#C297FF') === WD.DARK_INK);
          check('blue keeps light ink', WD.readableOn('#0068FF') === WD.LIGHT_INK);
          check('gray keeps light ink', WD.readableOn('#6B6B6B') === WD.LIGHT_INK);
          done();
        """)

    def test_a_colour_nobody_has_seen_yet_is_still_handled(self):
        """The reason this is computed rather than a list of known swatches."""
        self.run_block("""
          check('near-white takes dark ink', WD.readableOn('#FAFAFA') === WD.DARK_INK);
          check('near-black takes light ink', WD.readableOn('#050505') === WD.LIGHT_INK);
          check('mid grey resolves either way but legibly',
                WD.contrastRatio('#808080', WD.readableOn('#808080')) >= 3.9);
          check('shorthand hex works', WD.readableOn('#ff0') === WD.DARK_INK);
          done();
        """)

    def test_a_pale_fill_gets_a_firmer_outline_than_a_dark_one(self):
        """White-on-white markers already shipped once. The ring is what stops
        a pale AP colour disappearing into a white CAD plan."""
        self.run_block("""
          function alpha(rgba) { return parseFloat(/,\\s*([\\d.]+)\\)/.exec(rgba)[1]); }
          var nearWhite = alpha(WD.outlineOn('#FAFAFA'));
          var yellow    = alpha(WD.outlineOn('#FFE600'));
          var cyan      = alpha(WD.outlineOn('#00FFCE'));
          var blue      = alpha(WD.outlineOn('#0068FF'));
          var black     = alpha(WD.outlineOn('#111111'));
          // Yellow sits at 1.19:1 against white paper and #FAFAFA at 1.04:1.
          // Both are effectively invisible without a ring, so both take the
          // firmest one - ranking them against each other would be inventing a
          // difference the eye cannot see. What must hold is that pale outranks
          // saturated, and that nothing is drawn ringless.
          check('near-white takes the firmest ring', nearWhite >= 0.7);
          check('yellow takes the firmest ring too', yellow >= 0.7);
          check('a pale fill outranks a saturated one', cyan > blue);
          check('every fill still gets some ring', blue > 0 && black > 0);
          done();
        """)

    def test_rubbish_input_does_not_throw(self):
        self.run_block("""
          check('null', WD.readableOn(null) === WD.LIGHT_INK);
          check('not a colour', WD.readableOn('banana') === WD.LIGHT_INK);
          check('luminance of junk is null', WD.relLuminance('nope') === null);
          check('outline still returns something', typeof WD.outlineOn(null) === 'string');
          done();
        """)


class OneImplementation(unittest.TestCase):
    """Three copies is how they came to disagree."""

    def test_no_file_carries_its_own_brightness_formula(self):
        # The Rec.601 coefficients, in either the x1000 or the x1 form.
        rec601 = re.compile(r"\*\s*299\b|0\.299\s*\*|\*\s*587\b|0\.587\s*\*")
        offenders = []
        for path in sorted(JS_DIR.glob("*.js")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if rec601.search(line):
                    offenders.append(f"{path.name}:{n}: {line.strip()}")
        self.assertEqual(offenders, [], (
            "a private brightness formula is back. Contrast is decided once, in "
            f"wd-shared.js, or the surfaces drift apart again: {offenders}"))

    def test_the_shared_helper_is_the_only_luminance_definition(self):
        defs = []
        for path in sorted(JS_DIR.glob("*.js")):
            source = path.read_text(encoding="utf-8")
            if "0.2126" in source and path.name != "wd-shared.js":
                defs.append(path.name)
        self.assertEqual(defs, [], f"duplicate luminance implementation in {defs}")

    def test_the_palette_is_defined_once_too(self):
        """Same failure mode one level down: the Report drew CSS keywords for
        two years because the name->hex map lived in the labeler only."""
        offenders = []
        for path in sorted(JS_DIR.glob("*.js")):
            if path.name == "wd-shared.js":
                continue
            if "#C97700" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        self.assertEqual(offenders, [], (
            "the Ekahau palette is restated in "
            f"{offenders}; it belongs to WD.EKAHAU_COLORS"))

    def test_every_consumer_goes_through_wd(self):
        """Named so a future reader can see which surfaces are covered."""
        expected = {
            "ap-rename.js": "AP markers and the preview table",
            "report.js": "AP Placement Map marker pills",
            "walls-swap.js": "wall-type pills on the swap canvas",
        }
        for name, what in expected.items():
            source = (JS_DIR / name).read_text(encoding="utf-8")
            with self.subTest(surface=what):
                self.assertTrue(
                    "WD.needsDarkText" in source or "WD.readableOn" in source,
                    f"{name} ({what}) no longer uses the shared helper")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class AColourNameIsNotAColour(unittest.TestCase):
    """An .esx may store "GREEN" rather than "#00FF00", and both of the bugs
    that came of that were invisible until a report was actually rendered.

    A browser accepts `fill="GREEN"` and paints CSS green, #008000 - a darker,
    duller colour than the one Ekahau shows. And the contrast helper, handed a
    word, cannot measure it and falls through to white lettering. So the report
    drew the wrong colour with unreadable text on it, which is exactly the
    complaint the shared helper was meant to answer.
    """

    def run_block(self, checks: str):
        result = run_node(NODE_PRELUDE + "eval(" + _js(checks) + ");")
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).strip())

    def test_a_palette_name_resolves_to_the_colour_ekahau_paints(self):
        self.run_block("""
          check('GREEN is Ekahau green, not CSS green',
                WD.resolveApColor('GREEN') === '#00FF00');
          check('case does not matter', WD.resolveApColor('green') === '#00FF00');
          check('brown is Ekahau brown', WD.resolveApColor('BROWN') === '#C97700');
          check('a hex passes through, normalised',
                WD.resolveApColor('#fafafa') === '#FAFAFA');
          check('an unmarked AP has no colour', WD.resolveApColor(null) === null);
          check('something unrecognised is still drawn, not dropped',
                WD.resolveApColor('chartreuse') === 'chartreuse');
          done();
        """)

    def test_resolving_first_is_what_makes_the_ink_right(self):
        self.run_block("""
          // The failure, stated: a name cannot be measured, so it reads as
          // "light ink is fine" - which is how green got white numbers.
          check('a bare name measures as nothing',
                WD.relLuminance('GREEN') === null);
          check('and would therefore take light ink',
                WD.readableOn('GREEN') === WD.LIGHT_INK);
          check('resolved first, it takes dark ink',
                WD.readableOn(WD.resolveApColor('GREEN')) === WD.DARK_INK);
          done();
        """)


class TheReportPaintsResolvedColours(unittest.TestCase):

    def test_report_resolves_before_it_paints_or_measures(self):
        source = (JS_DIR / "report.js").read_text(encoding="utf-8")
        self.assertIn("WD.resolveApColor(ap.color)", source,
                      "the report is back to using ap.color raw")
        self.assertNotIn("var apColor = ap.color", source)

    def test_the_computed_ring_can_actually_win_over_the_stylesheet(self):
        """A CSS rule beats a presentation attribute. The stroke the report
        computes is an attribute, so without :not([stroke]) the stylesheet
        quietly puts the white ring back and the fix does nothing on paper."""
        css = CSS.read_text(encoding="utf-8")
        for shape in ("rep-mark-dot", "rep-mark-pill"):
            with self.subTest(shape=shape):
                self.assertIn(f".rep-mark--omni .{shape}:not([stroke])", css)
                self.assertNotIn(f".rep-mark--omni .{shape} {{ stroke:", css)


if __name__ == "__main__":
    unittest.main()
