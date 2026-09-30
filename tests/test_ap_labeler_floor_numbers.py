"""Two APs must never leave the AP Labeler carrying one name.

Found by loading a three-floor project into the real page in Firefox, choosing
Per Floor scope, and reading the names off all three floors: **27 access points
came back with 9 names, each used three times.**

The cause was one line. `getFloorNumber()` read `floor.order`, and `order` is
only ever assigned from `buildingFloors.json`; every floor is initialised to 0
and stays there when a project's floors are not attached to a building. So the
Floor segment of the name auto-detected as "00" on every floor at once, and Per
Floor scope restarts the counter on each floor, so floor 2's first AP got the
same name as floor 1's.

Nothing reported it. The preview showed the duplicates plainly if you compared
two floor tabs by hand, and the download wrote them into the .esx.

Both halves are fixed and both are held here: a floor number that actually
distinguishes floors, and a check on the finished names that catches every
other route to the same outcome - a template with no Floor segment, a colour
sequence numbered per floor, or anything else nobody has thought of yet.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.css_source import css_for

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "assets" / "js" / "ap-rename.js"
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"
PAGE = ROOT / "web" / "ap-rename.html"

NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const shared = fs.readFileSync(process.argv[2], 'utf8');
function cut(from, to, src) {
  src = src || source;
  const a = src.indexOf(from);
  const b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
globalThis.WD = {};
eval(cut('  WD.storeyNumber = function', '  /* ── Legibility', shared));
eval(cut('function getFloorNumber(floor) {', 'function buildStructuredName'));
eval(cut('function duplicateNames(items) {', 'function updateDownloadBtn'));

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function eq(what, got, want) {
  if (got !== want) failures.push(what + ': got ' + JSON.stringify(got)
    + ', wanted ' + JSON.stringify(want));
}
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}

"""


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = PRELUDE + "eval(" + json.dumps(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(JS), str(SHARED_JS)],
                              capture_output=True, text=True,
                              timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s - that is a Node "
            f"startup timeout, not a failure of the code under test.") from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class EveryFloorGetsItsOwnNumber(unittest.TestCase):

    def run_block(self, checks: str):
        r = run_node(checks)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).strip())

    def test_the_reported_case_three_floors_no_building(self):
        """The project that produced 9 names for 27 APs. Its floors carry
        their number in their names and nothing else."""
        self.run_block("""
          const floors = numberFloors([
            { id: 'f1', name: '01 - Ground' },
            { id: 'f2', name: '02 - Level 2' },
            { id: 'f3', name: '03 - Level 3' },
          ], []);
          eq('ground', getFloorNumber(floors[0]), '01');
          eq('second', getFloorNumber(floors[1]), '02');
          eq('third',  getFloorNumber(floors[2]), '03');
          check('all three differ', new Set(floors.map(getFloorNumber)).size === 3);
          done();
        """)

    def test_ekahaus_stacking_position_is_not_the_storey(self):
        """The reported case. Current Ekahau versions store a building's first
        floor as 0, so a plan named "Floor 1" carries 0 and "Floor 3" carries
        2. Read as stored, the first floor's APs were named "00" and the
        third floor's "02"."""
        self.run_block("""
          const floors = numberFloors([
            { id: 'f1', name: 'Floor 1' },
            { id: 'f2', name: 'Floor 2' },
            { id: 'f3', name: 'Floor 3' },
          ], [{ floorPlanId: 'f1', floorNumber: 0 },
              { floorPlanId: 'f2', floorNumber: 1 },
              { floorPlanId: 'f3', floorNumber: 2 }]);
          eq('first',  getFloorNumber(floors[0]), '01');
          eq('second', getFloorNumber(floors[1]), '02');
          eq('third',  getFloorNumber(floors[2]), '03');
          done();
        """)

    def test_a_building_with_unnumbered_names_counts_from_one(self):
        """With nothing in the name, Ekahau's number is all there is. A
        building with a floor at 0 is a current project, so it is shifted."""
        self.run_block("""
          const floors = numberFloors([
            { id: 'f1', name: 'Ground' },
            { id: 'f2', name: 'Mezzanine' },
          ], [{ floorPlanId: 'f1', floorNumber: 0 },
              { floorPlanId: 'f2', floorNumber: 1 }]);
          eq('ground',    getFloorNumber(floors[0]), '01');
          eq('mezzanine', getFloorNumber(floors[1]), '02');
          done();
        """)

    def test_the_name_wins_over_the_stacking_position(self):
        """A building whose plans were stacked out of order, or that starts
        above the ground: the name is what the designer typed."""
        self.run_block("""
          const floors = numberFloors([
            { id: 'f1', name: 'Level 4' },
            { id: 'f2', name: '3rd Floor' },
            { id: 'f3', name: 'FL-7 East' },
          ], [{ floorPlanId: 'f1', floorNumber: 0 },
              { floorPlanId: 'f2', floorNumber: 5 },
              { floorPlanId: 'f3', floorNumber: 1 }]);
          eq('level', getFloorNumber(floors[0]), '04');
          eq('ordinal', getFloorNumber(floors[1]), '03');
          eq('fl-', getFloorNumber(floors[2]), '07');
          done();
        """)

    def test_an_older_project_that_counts_from_one_is_read_as_stored(self):
        """Older Ekahau versions stored the first floor as 1. No floor at 0 in
        the building means that convention, and nothing is shifted."""
        self.run_block("""
          const floors = numberFloors([
            { id: 'f1', name: 'Dock' },
            { id: 'f2', name: 'Offices' },
          ], [{ floorPlanId: 'f1', buildingId: 'b', floorNumber: 1 },
              { floorPlanId: 'f2', buildingId: 'b', floorNumber: 2 }]);
          eq('first',  getFloorNumber(floors[0]), '01');
          eq('second', getFloorNumber(floors[1]), '02');
          done();
        """)

    def test_a_floor_word_beats_a_building_number_in_the_same_name(self):
        self.run_block("""
          const floors = numberFloors([{ id: 'f1', name: 'Bldg 5 Level 2' }], []);
          eq('floor word', getFloorNumber(floors[0]), '02');
          done();
        """)

    def test_a_floor_with_no_number_anywhere_still_differs_from_its_neighbour(self):
        """Position is the last resort and is always distinct, which is the
        property that matters - "00" for everything was not."""
        self.run_block("""
          const floors = numberFloors([
            { id: 'f1', name: 'Ground' },
            { id: 'f2', name: 'Mezzanine' },
            { id: 'f3', name: 'Roof' },
          ], []);
          eq('first',  getFloorNumber(floors[0]), '01');
          eq('second', getFloorNumber(floors[1]), '02');
          eq('third',  getFloorNumber(floors[2]), '03');
          done();
        """)

    def test_a_mixed_project_does_not_collapse_the_floors_it_does_know(self):
        self.run_block("""
          const floors = numberFloors([
            { id: 'f1', name: 'Ground' },
            { id: 'f2', name: 'Level 7' },
          ], [{ floorPlanId: 'f1', floorNumber: 0 }]);
          eq('from building', getFloorNumber(floors[0]), '01');
          eq('from the name', getFloorNumber(floors[1]), '07');
          done();
        """)

    def test_a_missing_floor_is_still_answered(self):
        self.run_block("eq('no floor', getFloorNumber(null), '01'); done();")

    def test_order_is_left_alone_because_it_sorts_the_tabs(self):
        """`num` was added rather than `order` repurposed. Changing `order`
        would reorder the floor tabs as a side effect of a naming fix."""
        src = JS.read_text(encoding="utf-8")
        self.assertIn("S.floors.sort(function (a, b) { return a.order - b.order; });",
                      src)
        self.assertIn("f.num = m ? parseInt(m[0], 10) : (i + 1);", src)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class NoTwoAPsLeaveWithOneName(unittest.TestCase):
    """The floor token was one way in. This is the check that does not depend
    on knowing which way."""

    def run_block(self, checks: str):
        r = run_node(checks)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).strip())

    def test_it_finds_a_collision(self):
        self.run_block("""
          const d = duplicateNames([
            { newName: 'SITE-AP001' }, { newName: 'SITE-AP002' },
            { newName: 'SITE-AP001' },
          ]);
          eq('one name reported', d.length, 1);
          eq('and it is the right one', d[0], 'SITE-AP001');
          done();
        """)

    def test_a_name_used_three_times_is_reported_once(self):
        """Three floors colliding is the reported case. Listing it three times
        would make nine collisions read as twenty-seven."""
        self.run_block("""
          const d = duplicateNames([
            { newName: 'A' }, { newName: 'A' }, { newName: 'A' },
          ]);
          eq('reported once', d.length, 1);
          done();
        """)

    def test_a_clean_run_reports_nothing(self):
        self.run_block("""
          eq('no dupes', duplicateNames([
            { newName: 'A' }, { newName: 'B' }, { newName: 'C' }]).length, 0);
          done();
        """)

    def test_an_ap_with_no_new_name_is_not_a_collision(self):
        """In manual mode every AP nobody has clicked yet has no number, and
        those must not all read as duplicates of each other."""
        self.run_block("""
          eq('blanks ignored', duplicateNames([
            { newName: '' }, { newName: '' }, { newName: null }, {}]).length, 0);
          done();
        """)


class TheWarningIsOnScreenAndSaysWhatToDo(unittest.TestCase):
    """A count with no names leaves him to find them, and a toast fades before
    he has read it. This one sits above the preview, where the names are."""

    def setUp(self):
        self.src = JS.read_text(encoding="utf-8")
        self.page = PAGE.read_text(encoding="utf-8")
        b = self.src[self.src.index("function updateDownloadBtn"):]
        self.body = b[:b.index("window._arShowAll")]

    def test_the_element_exists_on_the_page(self):
        self.assertIn('id="arDupeWarn"', self.page)
        self.assertIn(".ar-dupe-warn", css_for("ap-rename.html"))

    def test_the_check_runs_on_every_update(self):
        self.assertIn("duplicateNames(S.preview)", self.body)
        update_all = self.src[self.src.index("function updateAll() {"):]
        update_all = update_all[:update_all.index("\n  }")]
        self.assertIn("updateDownloadBtn()", update_all)

    def test_it_names_the_colliding_names(self):
        """Every one of them, not the first four.

        This used to assert the literal `dupes.slice(0, 4)`, which is the shape
        that has shipped five defects this week: the string was present and the
        behaviour it stood for was the defect. A collision you cannot see is
        one you cannot fix, so the claim is now that nothing is left out.
        """
        self.assertIn("dupes.map(esc).join", self.body)
        self.assertNotIn("dupes.slice(", self.body,
                         "the warning still stops short of naming them all")
        self.assertNotIn("more'", self.body.split("Ekahau will take them")[0],
                         "it still trails off with 'and N more'")

    def test_it_says_both_ways_out(self):
        self.assertIn("Add a Floor segment", self.body)
        self.assertIn("Continuous", self.body)

    def test_it_clears_itself_when_the_collision_is_resolved(self):
        """A warning that stays up after the cause is gone is worse than none;
        he would stop reading it."""
        self.assertIn("warn.hidden = true;", self.body)

    def test_the_download_is_warned_about_rather_than_blocked(self):
        """A name he chose deliberately is his call. The rule this file
        enforces is that he is told, not that he is stopped."""
        self.assertIn("$('arDownloadBtn').disabled = !hasChanges;", self.body)
        self.assertNotIn("disabled = !!dupes.length", self.body)


if __name__ == "__main__":
    unittest.main()
