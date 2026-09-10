"""Quick Walls' vertical extent editor, driven through the real functions.

Height lives on the wall *type*, in metres, as ``lowerEdge``/``upperEdge`` in
``wallTypes.json``. ``wallSegments.json`` carries no geometry at all, so there
is no such thing as making one segment shorter than another of the same type -
which is exactly what the editor has to make unmistakable before it saves.

Two things here are guarded because getting either wrong is silent:

* **Auto is the absence of ``upperEdge``, not a zero.** A zero would tell
  Ekahau the type has no vertical extent rather than a full one. Auto is also a
  legitimate answer rather than an unset state, so a type that was given a
  height has to be able to go back to Auto and stay there through a save.
* **Heights are feet, thickness is inches.** The same modal holds both, and a
  12 ft rack entered as 12 in is a wall a quarter of a metre tall that still
  looks plausible in the list.

The functions are sliced out of walls.js and run in Node, so what is asserted
is the object the page would actually write, not a restatement of the rule.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALLS_JS = ROOT / "web" / "assets" / "js" / "walls.js"
WALLS_HTML = ROOT / "web" / "walls.html"

NODE_TIMEOUT_S = 120

# walls.js touches the DOM at import time, so the height block is sliced out and
# given only what it reaches for.
NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0) throw new Error('could not find ' + from);
  if (b < 0) throw new Error('could not find ' + to);
  return source.slice(a, b);
}

let UNITS = 'imperial';
globalThis.wallUnits = () => UNITS;
globalThis.setUnits = (u) => { UNITS = u; };
globalThis.esc = (s) => String(s);

const block =
    slice('const M_TO_FT', '\n// Segment counts per wall type id')
  + slice('function applyVertExtent', '\nfunction populateVertFields');
eval(block);
"""


def run_node(script: str) -> dict:
    """Run a Node snippet against walls.js and return the JSON it prints."""
    body = NODE_PRELUDE + script
    try:
        proc = subprocess.run(
            ["node", "-e", body, str(WALLS_JS)],
            capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s. This is a Node "
            "startup/exec timeout, not a failure of the code under test."
        ) from exc
    if proc.returncode != 0:
        raise AssertionError(f"node failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class VerticalExtentOutputTests(unittest.TestCase):
    """What applyVertExtent actually writes onto a wall type."""

    def test_auto_removes_upper_edge_rather_than_zeroing_it(self):
        out = run_node(r"""
          const wt = { name: 'Wall, Dry', upperEdge: 1.5, lowerEdge: 0.3 };
          applyVertExtent(wt, 'auto', 0, null);
          console.log(JSON.stringify({
            hasUpper: Object.prototype.hasOwnProperty.call(wt, 'upperEdge'),
            lower: wt.lowerEdge,
          }));
        """)
        self.assertFalse(out["hasUpper"],
                         "Auto must delete upperEdge; a 0 means no extent at all")
        self.assertEqual(out["lower"], 0)

    def test_fixed_writes_both_edges_in_metres(self):
        out = run_node(r"""
          const wt = { name: 'Shelf, Warehouse' };
          applyVertExtent(wt, 'fixed', 0.5, 3.0);
          console.log(JSON.stringify(wt));
        """)
        self.assertEqual(out["upperEdge"], 3.0)
        self.assertEqual(out["lowerEdge"], 0.5)

    def test_a_type_can_go_back_to_auto_and_stay_there(self):
        """Auto is a real answer, so it has to survive the round trip."""
        out = run_node(r"""
          const wt = { name: 'Cubicle' };
          applyVertExtent(wt, 'fixed', 0, 1.5);
          const limited = Object.prototype.hasOwnProperty.call(wt, 'upperEdge');
          applyVertExtent(wt, 'auto', 0, null);
          console.log(JSON.stringify({
            limited,
            backToAuto: !Object.prototype.hasOwnProperty.call(wt, 'upperEdge'),
          }));
        """)
        self.assertTrue(out["limited"])
        self.assertTrue(out["backToAuto"])

    def test_other_fields_are_left_alone(self):
        out = run_node(r"""
          const wt = { name: 'X', thickness: 0.1, metersPerUnit: 0.07886,
                       propagationProperties: [{ band: 'FIVE' }] };
          applyVertExtent(wt, 'fixed', 0, 2.2);
          console.log(JSON.stringify(wt));
        """)
        self.assertEqual(out["thickness"], 0.1)
        self.assertEqual(out["metersPerUnit"], 0.07886)
        self.assertEqual(out["propagationProperties"], [{"band": "FIVE"}])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class VerticalExtentValidationTests(unittest.TestCase):
    def test_auto_never_complains(self):
        out = run_node(r"""
          console.log(JSON.stringify({
            empty: vertExtentError('auto', 0, null),
            junk: vertExtentError('auto', 0, NaN),
          }));
        """)
        self.assertIsNone(out["empty"])
        self.assertIsNone(out["junk"])

    def test_fixed_requires_a_usable_top(self):
        out = run_node(r"""
          console.log(JSON.stringify({
            missing: vertExtentError('fixed', 0, null),
            zero: vertExtentError('fixed', 0, 0),
            inverted: vertExtentError('fixed', 2.0, 1.0),
            equal: vertExtentError('fixed', 1.5, 1.5),
            ok: vertExtentError('fixed', 0.5, 2.5),
          }));
        """)
        self.assertIsNotNone(out["missing"])
        self.assertIsNotNone(out["zero"])
        self.assertIsNotNone(out["inverted"])
        self.assertIsNotNone(out["equal"])
        self.assertIsNone(out["ok"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class HeightUnitTests(unittest.TestCase):
    """Feet for height, inches for thickness, and no drift between them."""

    def test_imperial_height_is_feet_not_inches(self):
        out = run_node(r"""
          setUnits('imperial');
          console.log(JSON.stringify({
            twelveFtInMetres: heightToM(12),
            oneMetreInFt: mToHeight(1),
            label: heightUnitLabel(),
          }));
        """)
        # 12 ft is 3.6576 m. If height used the thickness scale it would be
        # 0.3048 m, a rack a foot tall.
        self.assertAlmostEqual(out["twelveFtInMetres"], 3.6576, places=4)
        self.assertAlmostEqual(out["oneMetreInFt"], 3.2808, places=3)
        self.assertEqual(out["label"], "ft")

    def test_metric_passes_metres_through(self):
        out = run_node(r"""
          setUnits('metric');
          console.log(JSON.stringify({
            there: heightToM(3.6576), back: mToHeight(3.6576),
            label: heightUnitLabel(),
          }));
        """)
        self.assertAlmostEqual(out["there"], 3.6576, places=4)
        self.assertAlmostEqual(out["back"], 3.6576, places=4)
        self.assertEqual(out["label"], "m")

    def test_a_height_survives_a_round_trip_through_the_field(self):
        """Display rounding must not walk 16 ft off its own value."""
        out = run_node(r"""
          setUnits('imperial');
          const results = {};
          for (const m of [1.5, 2.5, 3.6576, 4.8768, 10.0]) {
            results[String(m)] = heightToM(fmtHeight(mToHeight(m)));
          }
          console.log(JSON.stringify(results));
        """)
        for metres, back in out.items():
            with self.subTest(metres=metres):
                self.assertAlmostEqual(back, float(metres), places=2)

    def test_blank_reads_as_no_value_not_zero(self):
        out = run_node(r"""
          console.log(JSON.stringify({ blank: heightToM(''), junk: heightToM('abc') }));
        """)
        self.assertIsNone(out["blank"])
        self.assertIsNone(out["junk"])


class VerticalExtentMarkupTests(unittest.TestCase):
    """The controls the JS reaches for have to exist on the page."""

    def test_the_fields_exist(self):
        html = WALLS_HTML.read_text(encoding="utf-8")
        for ident in ("fUpperEdge", "fLowerEdge", "fVertFixed",
                      "fVertSummary", "fVertImpact", "fVertUnit"):
            with self.subTest(id=ident):
                self.assertIn(f'id="{ident}"', html)

    def test_auto_is_offered_as_its_own_choice(self):
        html = WALLS_HTML.read_text(encoding="utf-8")
        self.assertIn('data-vmode="auto"', html)
        self.assertIn('data-vmode="fixed"', html)
        self.assertIn("setHeightMode('auto')", html)

    def test_the_per_type_consequence_is_stated(self):
        """Changing a height changes every segment drawn with that type."""
        js = WALLS_JS.read_text(encoding="utf-8")
        self.assertIn("Height belongs to the wall type", js)
        self.assertIn("segmentsUsing", js)

    def test_height_styles_are_not_in_the_shared_stylesheet(self):
        """Scoped to walls.html so the shared sheet stays out of this change."""
        shared = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")
        self.assertNotIn("wt-vert-mode", shared)
        self.assertIn("wt-vert-mode", WALLS_HTML.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
