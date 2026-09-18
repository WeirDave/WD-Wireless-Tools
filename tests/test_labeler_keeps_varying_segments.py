"""A segment that differs between APs is not a fixed part of the scheme.

Found by auditing the Labeler with a synthetic project whose APs were named
`…-STE100-AP001`, `…-STE101-AP002`, `…-STE102-AP003`. Every proposed new name
came back as `…-STE100-…`: the tool offered to move two thirds of a building
into a suite they are not in.

One branch did it. `inferSegments` allows exactly one counter, and demoted any
earlier counter-shaped segment with

    segments[j] = { type: 'text', value: _modal(col).value };

- the most common value in that column, standing in for every AP. That is
correct only when the column is constant, and a column that reaches this branch
is a column that varied: it got there by looking like TAG+digits across
*differing* values. So the one value that happened to be most common was
written over everybody else's.

The suite number says where an installer has to stand. It is on the drawings
and in the report, and the .esx is the only copy. A bulk rename that flattens it
is work he redoes by hand, done by a tool that appeared to be helping.

What must hold now:

  * a column that varies keeps each AP's own value
  * a column that really is constant is still plain text, exactly as before
  * typing a literal into a varying segment still overrides every AP, because
    moving a building into one suite is a thing somebody might mean
  * and the two classifications work side by side in one project

Every name here is invented for this file.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "assets" / "js" / "ap-rename.js"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function cut(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}

// The page the builder expects, stubbed before anything is evaluated:
// buildStructuredName reads the separator off a <select>, and there is no
// document here.
var _sep = '-';
globalThis.$ = function () { return { value: _sep }; };
globalThis.getFloorNumber = function (floor) {
  return (floor && floor.num != null) ? String(floor.num) : '00';
};
globalThis.padNum = function (n, digits) {
  var s = String(n);
  while (s.length < digits) s = '0' + s;
  return s;
};

// The real inference and the real name builder, sliced out of the real file.
eval(cut('var SEPARATOR_CANDIDATES', '/* entries: [{ name, floorId }]'));
eval(cut('function inferSegments(entries)', "/* Read the project's own scheme"));
eval(cut('function keptPart(seg, ap)', '/* ── reading the scheme'));

// The save and load halves, taken out of the real functions rather than
// retyped: getSettings writes a segment out, applySettings maps it back.
eval(cut('function getSettings()', 'function applySettings(s)'));
var _reloadBody = cut('_segments = s.segments.map(function (o) {',
                      '      padSegments();');
eval('function reload(o) { ' + _reloadBody
       .replace('_segments = s.segments.map(function (o) {', 'return (function () {')
       .replace(/\}\);\s*$/, '})(); }'));

function nameEach(segments, entries) {
  _segments = segments;
  return entries.map(function (e, i) {
    return buildStructuredName({ num: 1 }, i + 1, { name: e.name });
  });
}
"""


def run_node(script):
    proc = subprocess.run(["node", "-e", PRELUDE + script, str(JS)],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=NODE_TIMEOUT_S)
    if proc.returncode != 0:
        raise AssertionError("node failed:\n" + proc.stderr)
    return json.loads(proc.stdout)


def entries(names, floor="f1"):
    return [{"name": n, "floorId": floor} for n in names]


VARYING = ["EXMPL-B1-STE100-AP001",
           "EXMPL-B1-STE101-AP002",
           "EXMPL-B1-STE102-AP003",
           "EXMPL-B1-STE103-AP004"]

FIXED = ["EXMPL-B1-STE100-AP001",
         "EXMPL-B1-STE100-AP002",
         "EXMPL-B1-STE100-AP003",
         "EXMPL-B1-STE100-AP004"]


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class AVaryingSegmentIsNotFixed(unittest.TestCase):

    def infer(self, names):
        return run_node(
            "var read = inferSegments(" + json.dumps(entries(names)) + ");"
            "console.log(JSON.stringify(read));")

    def names_from(self, names):
        return run_node(
            "var read = inferSegments(" + json.dumps(entries(names)) + ");"
            "console.log(JSON.stringify(nameEach(read.segments, "
            + json.dumps(entries(names)) + ")));")

    def test_the_suite_segment_is_classified_as_varying(self):
        read = self.infer(VARYING)
        self.assertIsNotNone(read, "no scheme was read at all")
        kinds = [s["type"] for s in read["segments"]]
        self.assertEqual(kinds, ["text", "text", "keep", "counter"], kinds)

    def test_every_ap_keeps_its_own_suite(self):
        """The defect, stated as the outcome rather than as a branch."""
        got = self.names_from(VARYING)
        self.assertEqual(got, ["EXMPL-B1-STE100-AP001",
                               "EXMPL-B1-STE101-AP002",
                               "EXMPL-B1-STE102-AP003",
                               "EXMPL-B1-STE103-AP004"])

    def test_nobody_is_moved_into_somebody_elses_suite(self):
        got = self.names_from(VARYING)
        suites = [n.split("-")[2] for n in got]
        self.assertEqual(len(set(suites)), 4,
                         f"four suites went in and {len(set(suites))} came out: {suites}")

    def test_a_genuinely_fixed_segment_is_still_text(self):
        read = self.infer(FIXED)
        kinds = [s["type"] for s in read["segments"]]
        self.assertEqual(kinds, ["text", "text", "text", "counter"], kinds)
        self.assertEqual(read["segments"][2]["value"], "STE100")

    def test_a_fixed_project_still_names_the_way_it_always_did(self):
        self.assertEqual(self.names_from(FIXED), FIXED)

    def test_both_kinds_side_by_side_in_one_project(self):
        """B1 is the same on every AP; the suite is not. One project, one
        inference, and each segment has to be judged on its own column."""
        read = self.infer(VARYING)
        segs = read["segments"]
        self.assertEqual(segs[1]["type"], "text")
        self.assertEqual(segs[1]["value"], "B1")
        self.assertEqual(segs[2]["type"], "keep")

    def test_a_segment_that_varies_in_only_some_aps_still_varies(self):
        """Three share a value and one does not. A majority is not a constant,
        and the odd one out is exactly who would be quietly renamed."""
        names = ["EXMPL-B1-STE100-AP001",
                 "EXMPL-B1-STE100-AP002",
                 "EXMPL-B1-STE100-AP003",
                 "EXMPL-B1-STE207-AP004"]
        read = self.infer(names)
        self.assertEqual(read["segments"][2]["type"], "keep")
        self.assertEqual(self.names_from(names), names)

    def test_the_counter_is_still_the_last_number(self):
        read = self.infer(VARYING)
        counters = [i for i, s in enumerate(read["segments"])
                    if s["type"] == "counter"]
        self.assertEqual(counters, [3], "the AP number moved")
        self.assertEqual(read["segments"][3]["tag"], "AP")
        self.assertEqual(read["segments"][3]["digits"], 3)

    def test_the_counter_still_renumbers(self):
        """Keeping a segment must not freeze the one that is meant to change."""
        got = self.names_from(VARYING)
        self.assertEqual([n.split("-")[3] for n in got],
                         ["AP001", "AP002", "AP003", "AP004"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TypingALiteralStillOverridesEveryone(unittest.TestCase):
    """He may genuinely want one suite for the whole building. That stays
    available - as something he does on purpose, never as what the tool
    assumes."""

    def test_a_typed_value_wins_for_every_ap(self):
        got = run_node(
            "var read = inferSegments(" + json.dumps(entries(VARYING)) + ");"
            "read.segments[2].value = 'STE900';"
            "console.log(JSON.stringify(nameEach(read.segments, "
            + json.dumps(entries(VARYING)) + ")));")
        self.assertEqual(got, ["EXMPL-B1-STE900-AP001",
                               "EXMPL-B1-STE900-AP002",
                               "EXMPL-B1-STE900-AP003",
                               "EXMPL-B1-STE900-AP004"])

    def test_clearing_it_goes_back_to_each_ap_s_own(self):
        got = run_node(
            "var read = inferSegments(" + json.dumps(entries(VARYING)) + ");"
            "read.segments[2].value = 'STE900';"
            "read.segments[2].value = '';"
            "console.log(JSON.stringify(nameEach(read.segments, "
            + json.dumps(entries(VARYING)) + ")));")
        self.assertEqual(got, VARYING)

    def test_an_ap_that_does_not_follow_the_shape_falls_back_to_the_sample(self):
        """It has no own value to keep. It must still produce a name rather
        than dropping a component and colliding with somebody."""
        got = run_node(
            "var read = inferSegments(" + json.dumps(entries(VARYING)) + ");"
            "_segments = read.segments;"
            "console.log(JSON.stringify(buildStructuredName({num:1}, 9, "
            "{ name: 'ODDBALL' })));")
        self.assertTrue(got.endswith("AP009"), got)
        self.assertIn("STE", got, "the kept segment vanished from the name")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheSegmentTypeSurvivesBeingSaved(unittest.TestCase):
    """A template saved with a kept segment has to come back as one.

    Dropping the type on the way through would silently restore the old
    behaviour on the next load, which is the worst version of this bug: fixed
    on screen, broken for anyone with a saved template.

    Run rather than read. `getSettings` writes the segment out and
    `applySettings` reads it back, so both halves are executed and the names
    the builder produces afterwards are compared with the names it produced
    before - which is the only thing that actually matters.
    """

    def test_a_kept_segment_survives_a_save_and_a_load(self):
        got = run_node("""
          var read = inferSegments(""" + json.dumps(entries(VARYING)) + """);
          var before = nameEach(read.segments, """ + json.dumps(entries(VARYING)) + """);

          // getSettings reads a dozen ids off the page; every one of them can
          // answer the same way here, because only `segments` is under test.
          globalThis.document = { getElementById: function () { return { value: '-' }; } };
          globalThis.$ = function () { return { value: '-' }; };
          globalThis._mode = 'structured'; globalThis._scope = 'all';
          globalThis._nesting = 'floor'; globalThis._colorOrder = [];
          _segments = read.segments;
          var saved = JSON.parse(JSON.stringify(getSettings().segments));

          // ...and the load path maps it back.
          var loaded = saved.map(reload);
          var after = nameEach(loaded, """ + json.dumps(entries(VARYING)) + """);
          console.log(JSON.stringify({ saved: saved, before: before, after: after }));
        """)
        kept = [s for s in got["saved"] if s["type"] == "keep"]
        self.assertEqual(len(kept), 1, f"saved as {got['saved']}")
        self.assertIn("index", kept[0])
        self.assertIn("sep", kept[0])
        self.assertEqual(got["after"], got["before"],
                         "the names changed after a save and a load")
        self.assertEqual(got["after"], VARYING)

    def test_a_typed_override_survives_too(self):
        """The literal he chose is a choice, and has to be saved as one."""
        got = run_node("""
          var read = inferSegments(""" + json.dumps(entries(VARYING)) + """);
          read.segments[2].value = 'STE900';
          globalThis.document = { getElementById: function () { return { value: '-' }; } };
          globalThis.$ = function () { return { value: '-' }; };
          globalThis._mode = 'structured'; globalThis._scope = 'all';
          globalThis._nesting = 'floor'; globalThis._colorOrder = [];
          _segments = read.segments;
          var saved = JSON.parse(JSON.stringify(getSettings().segments));
          var after = nameEach(saved.map(reload), """ + json.dumps(entries(VARYING)) + """);
          console.log(JSON.stringify({ after: after }));
        """)
        self.assertTrue(all("-STE900-" in n for n in got["after"]), got["after"])


if __name__ == "__main__":
    unittest.main()
