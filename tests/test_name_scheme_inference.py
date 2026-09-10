"""Reading the naming scheme a project already uses.

Adding one AP to a building whose APs are already named meant retyping the
whole pattern by hand, when the answer was sitting in the file. The names are
read on load and the segment list is filled in from them.

Inference is over *segments*, not a fixed CLLI / Building / Suite / Floor
shape. The Labeler stopped having named fields when the segment builder landed
- a name is whatever ordered run of text / floor / counter parts you drag
together - so inferring by position keeps working for schemes that look
nothing like anyone else's, and sidesteps having to decide whether the third
segment is a suite or a floor when the tool no longer cares.

The rule everywhere below: fill in what the names actually show, and leave
anything ambiguous as plain text. Plain text reproduces the existing names
exactly, so being cautious costs nothing, while a wrong guess that goes
unnoticed renames a building.

Driven through the real inferSegments in Node.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AP_JS = ROOT / "web" / "assets" / "js" / "ap-rename.js"
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"

NODE_TIMEOUT_S = 120

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const a = source.indexOf('  var SEPARATOR_CANDIDATES');
const b = source.indexOf('  /* ── segment builder UI');
if (a < 0 || b < 0) throw new Error('the inference block moved');
eval(source.slice(a, b));

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
// Compact rendering of an inferred segment list: t=text, F=floor, c=counter.
function shape(r) {
  if (!r) return 'none';
  return r.segments.map(s => s.type === 'text' ? 't'
                           : s.type === 'floor' ? 'F' : 'c').join('');
}
function texts(r) {
  return r.segments.filter(s => s.type === 'text')
                   .map(s => s.value).join(',');
}
function counter(r) {
  return r.segments.find(s => s.type === 'counter');
}
// One floor of APs named to a pattern.
function floorOf(id, tpl, from, to) {
  const out = [];
  for (let i = from; i <= to; i++) {
    out.push({ name: tpl.replace('#', String(i).padStart(2, '0')), floorId: id });
  }
  return out;
}
"""


def _js(text: str) -> str:
    return json.dumps(text)


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = NODE_PRELUDE + "eval(" + _js(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(AP_JS)],
                              capture_output=True, text=True,
                              timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s. That is a Node "
            f"startup timeout, not a failure of the code under test."
        ) from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ReadingARealScheme(unittest.TestCase):

    def run_block(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_his_scheme_across_two_floors(self):
        """FTCL3-01-01-01-AP01. The segment that changes between floors, and
        only between floors, is the floor."""
        self.run_block("""
          var aps = floorOf('f1', 'FTCL3-01-01-01-AP#', 1, 6)
            .concat(floorOf('f2', 'FTCL3-01-01-02-AP#', 1, 6));
          var r = inferSegments(aps);
          check('four fixed parts then the counter: ' + shape(r),
                shape(r) === 'tttFc');
          check('the fixed values are the ones in the file: ' + texts(r),
                texts(r) === 'FTCL3,01,01');
          check('tag AP', counter(r).tag === 'AP');
          check('two digits, from AP01', counter(r).digits === 2);
          check('hyphen separator', r.sep === '-');
          check('read from all 12', r.matched === 12 && r.total === 12);
          done();
        """)

    def test_one_floor_cannot_show_which_segment_is_the_floor(self):
        """Every fixed part looks identical on a single floor. Marking one of
        them Floor would be a guess, and text reproduces the names exactly."""
        self.run_block("""
          var r = inferSegments(floorOf('f1', 'FTCL3-01-01-01-AP#', 1, 6));
          check('no floor segment is invented: ' + shape(r),
                shape(r) === 'ttttc');
          check('and the names would rebuild as they are: ' + texts(r),
                texts(r) === 'FTCL3,01,01,01');
          done();
        """)

    def test_the_digit_count_comes_from_the_names(self):
        self.run_block("""
          var two = inferSegments(floorOf('f1', 'SITE-B-AP#', 1, 5));
          check('AP01 is two digits', counter(two).digits === 2);
          var three = inferSegments([
            {name:'SITE-B-AP001',floorId:'f1'}, {name:'SITE-B-AP002',floorId:'f1'},
            {name:'SITE-B-AP003',floorId:'f1'}]);
          check('AP001 is three digits', counter(three).digits === 3);
          done();
        """)

    def test_other_separators_are_recognised(self):
        self.run_block("""
          var u = inferSegments([{name:'SITE_B_AP001',floorId:'f'},
                                 {name:'SITE_B_AP002',floorId:'f'},
                                 {name:'SITE_B_AP003',floorId:'f'}]);
          check('underscore: ' + (u && u.sep), u && u.sep === '_');
          check('and it still reads the parts: ' + shape(u), shape(u) === 'ttc');
          done();
        """)

    def test_a_tag_that_is_not_ap_is_read_as_written(self):
        """Nothing here assumes the tag says "AP"."""
        self.run_block("""
          var r = inferSegments(floorOf('f1', 'BLDG-WAP#', 1, 4));
          check('tag WAP: ' + counter(r).tag, counter(r).tag === 'WAP');
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class WhereItRefusesToGuess(unittest.TestCase):

    def run_block(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_ekahau_placeholder_names_are_left_alone(self):
        """A fresh survey arrives as AP-1, AP-2. Those do technically describe
        a scheme, and adopting it would quietly throw away his saved default in
        favour of Ekahau's placeholder. What marks a scheme somebody chose is a
        tag on the number, or padding."""
        self.run_block("""
          check('AP-1',        inferSegments(
            [{name:'AP-1',floorId:'f'},{name:'AP-2',floorId:'f'},
             {name:'AP-3',floorId:'f'}]) === null);
          check('Ekahau AP 1', inferSegments(
            [{name:'Ekahau AP 1',floorId:'f'},{name:'Ekahau AP 2',floorId:'f'}]) === null);
          check('a padded number is deliberate, so it is read',
                inferSegments([{name:'SITE-01-001',floorId:'f'},
                               {name:'SITE-01-002',floorId:'f'}]) !== null);
          done();
        """)

    def test_names_with_no_scheme_infer_nothing(self):
        self.run_block("""
          check('free text', inferSegments(
            [{name:'kitchen ap',floorId:'f'},{name:'lobby thing',floorId:'f'}]) === null);
          check('no number anywhere', inferSegments(
            [{name:'A-B-C',floorId:'f'},{name:'A-B-D',floorId:'f'}]) === null);
          check('a single AP is not a pattern', inferSegments(
            [{name:'FTCL3-01-01-01-AP01',floorId:'f'}]) === null);
          check('nothing at all', inferSegments([]) === null);
          done();
        """)

    def test_a_segment_nobody_can_explain_stops_the_whole_thing(self):
        """Half a pattern is worse than none: the unexplained part would be
        frozen to one AP's value and rename every other AP to match."""
        self.run_block("""
          // The middle segment is neither fixed, nor per-floor, nor a number.
          var r = inferSegments([{name:'S-alpha-AP01',floorId:'f'},
                                 {name:'S-beta-AP02',floorId:'f'},
                                 {name:'S-gamma-AP03',floorId:'f'}]);
          check('nothing is inferred', r === null);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class NamesThatDoNotFitAreCountedNotForced(unittest.TestCase):

    def run_block(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_the_duplicate_suffix_case(self):
        """Ekahau appends -001 to a duplicated AP. Those names have one part
        too many; they must not distort the pattern, and the count has to say
        the scheme came from fewer APs than the project holds."""
        self.run_block("""
          var aps = floorOf('f1', 'FTCL3-01-01-01-AP#', 1, 6)
            .concat(floorOf('f2', 'FTCL3-01-01-02-AP#', 1, 6))
            .concat([{name:'FTCL3-01-01-01-AP07-001',floorId:'f1'},
                     {name:'FTCL3-01-01-01-AP08-001',floorId:'f1'}]);
          var r = inferSegments(aps);
          check('the scheme still reads correctly: ' + shape(r),
                shape(r) === 'tttFc');
          check('the tag is not polluted: ' + counter(r).tag,
                counter(r).tag === 'AP');
          check('12 of 14 were used', r.matched === 12 && r.total === 14);
          done();
        """)

    def test_a_few_odd_names_do_not_stop_the_majority(self):
        self.run_block("""
          var aps = floorOf('f1', 'FTCL3-01-01-01-AP#', 1, 8)
            .concat([{name:'spare',floorId:'f1'},
                     {name:'test rig',floorId:'f1'}]);
          var r = inferSegments(aps);
          check('the majority pattern wins: ' + shape(r), shape(r) === 'ttttc');
          check('and it says 8 of 10', r.matched === 8 && r.total === 10);
          done();
        """)

    def test_a_sample_name_is_returned_so_the_note_can_show_one(self):
        """The evidence shown on screen is a name it actually matched, not a
        reconstruction - a rebuilt sample that disagreed with the file would
        be exactly the failure this is meant to prevent."""
        self.run_block("""
          var aps = floorOf('f1', 'FTCL3-01-01-01-AP#', 1, 4);
          var r = inferSegments(aps);
          var real = aps.some(function (a) { return a.name === r.sample; });
          check('the sample is one of the real names: ' + r.sample, real);
          done();
        """)


class TheProjectSchemeIsActuallyApplied(unittest.TestCase):

    def setUp(self):
        self.source = AP_JS.read_text(encoding="utf-8")

    def test_loading_a_project_adopts_its_scheme(self):
        self.assertIn("adoptProjectScheme();", self.source)

    def test_the_note_says_how_many_aps_it_read(self):
        block = self.source[self.source.index("function renderInferredNote"):]
        block = block[:block.index("\n  }")]
        self.assertIn("read.matched", block)
        self.assertIn("read.total", block)
        self.assertIn("read.sample", block)

    def test_a_single_floor_project_says_why_no_floor_was_set(self):
        block = self.source[self.source.index("function renderInferredNote"):]
        block = block[:block.index("\n  }")]
        self.assertIn("Only one floor here", block)


class TheReportReadsTheSameShape(unittest.TestCase):
    """The Labeler's saved pattern is a segment list. The report's naming
    scheme header still expected the old fixed clli/building/suite fields, so
    it silently stopped rendering for everyone once those stopped being
    written. Two parsers for one shape is how that happened."""

    def test_the_report_no_longer_expects_the_retired_fields(self):
        source = REPORT_JS.read_text(encoding="utf-8")
        block = source[source.index("function structuredSegments(name, pat)"):]
        block = block[:block.index("\n  }")]
        self.assertNotIn("pat.clli", block)
        self.assertNotIn("pat.building", block)
        self.assertNotIn("pat.suite", block)
        self.assertNotIn("pat.apTag", block)
        self.assertIn("pat.segments", block)

    def test_the_report_does_not_assume_a_hyphen(self):
        """The Labeler offers other separators; the header drew a hyphen
        between segments whatever the name actually used."""
        source = REPORT_JS.read_text(encoding="utf-8")
        self.assertNotIn('<span class="rep-key-sep">-</span>', source)


if __name__ == "__main__":
    unittest.main()
