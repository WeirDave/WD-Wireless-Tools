"""The Change / Audit report's comparison, run against projects built for it.

``compareProjects`` is sliced out of report.js and executed. Every assertion is
about what it returned, not about what the source says - a report that merely
*mentions* "added" would pass a substring check while pairing nothing.

The case worth reading first is the re-cropped floor plan. Coordinates in an
.esx are measured from the corner of the floor plan image, so running PlanTrim
between the two saves moves every coordinate on that floor by the crop offset.
Reported naively that is every access point on the floor "moved", which buries
the one that really did. ``TheReCroppedFloorTests`` is that case, from both
sides: the shift is taken out when the image changed size, and it is emphatically
not taken out when the image did not - a compensation that fired on an ordinary
floor would hide every real move on it, which is the more dangerous failure of
the two.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"

NODE_TIMEOUT_S = 120

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
globalThis.window = globalThis;

// The comparison, exactly as shipped. It touches no DOM and no module state,
// which is the property that makes this possible.
eval(slice('  var DEFAULT_MOVE_THRESHOLD_M =', '\n  window.WDCompare'));

/* ── builders ─────────────────────────────────────────────────────────────
   0.05 metres per pixel throughout, so 10 px is half a metre - exactly the
   default threshold, which makes the boundary cases arithmetic rather than
   guesswork. */
function floor(id, name, w, h, mpu) {
  return { id: id, name: name, width: w == null ? 800 : w,
           height: h == null ? 600 : h, metersPerUnit: mpu == null ? 0.05 : mpu };
}
function ap(id, name, floorId, x, y, extra) {
  return Object.assign({
    id: id, name: name, vendor: 'Vendor', model: 'Model-X',
    location: floorId === null ? {} : { floorPlanId: floorId, coord: { x: x, y: y } },
  }, extra || {});
}
function radio(apId, extra) {
  return Object.assign({ accessPointId: apId, radioTechnology: 'IEEE802_11',
                         antennaDirection: 90, antennaTilt: -10,
                         antennaHeight: 3.0, antennaMounting: 'CEILING',
                         antennaTypeId: 'ant-1' }, extra || {});
}
function project(floors, aps, radios, extra) {
  return Object.assign({
    projectName: 'Fixture', projectId: 'p1',
    floorPlans: floors, accessPoints: aps, radios: radios || [],
    antennas: { 'ant-1': { id: 'ant-1', name: 'Panel 30' },
                'ant-2': { id: 'ant-2', name: 'Omni 3dBi' } },
    buildings: {}, buildingFloors: {}, images: {}, imageUrls: {}, notes: {},
  }, extra || {});
}
globalThis.floor = floor; globalThis.ap = ap;
globalThis.radio = radio; globalThis.project = project;

function kindsOf(rec) { return rec.changes.map(c => c.kind).sort(); }
function byName(list, n) {
  return list.find(r => ((r.after || r).name) === n) || null;
}
globalThis.kindsOf = kindsOf; globalThis.byName = byName;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function eq(what, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) failures.push(what + '\n     got:  ' + g + '\n     want: ' + w);
}
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = NODE_PRELUDE + "eval(" + json.dumps(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(REPORT_JS)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"node did not finish within {NODE_TIMEOUT_S}s") from exc


class NodeCase(unittest.TestCase):
    def run_checks(self, checks: str):
        proc = run_node(checks)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class MatchingTests(NodeCase):
    def test_an_ap_is_paired_by_ekahau_id_even_after_a_rename(self):
        """The ordinary case: the after-file is a descendant of the before."""
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const before = project(F, [ap('a1', 'OLD-NAME', 'f1', 100, 100)]);
          const after  = project(F, [ap('a1', 'NEW-NAME', 'f1', 100, 100)]);
          const r = compareProjects(before, after);
          eq('one pair', r.matched, 1);
          eq('nothing added', r.added.length, 0);
          eq('nothing removed', r.removed.length, 0);
          eq('the rename is the change', kindsOf(r.changed[0]), ['renamed']);
          eq('paired by id', r.changed[0].by, 'id');
          done();
        """)

    def test_a_deleted_and_re_added_ap_is_paired_by_name(self):
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const before = project(F, [ap('a1', 'AP-101', 'f1', 100, 100)]);
          const after  = project(F, [ap('zzz', 'AP-101', 'f1', 100, 100)]);
          const r = compareProjects(before, after);
          eq('one pair', r.matched, 1);
          eq('and it says how it was found', r.matchedByName, 1);
          eq('nothing added or removed', [r.added.length, r.removed.length], [0, 0]);
          done();
        """)

    def test_an_ambiguous_name_is_not_paired_at_all(self):
        """Two APs called the same thing must not pair off arbitrarily.

        Inventing a relationship is worse than reporting one added and one
        removed, which is at least true.
        """
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const before = project(F, [ap('b1', 'AP', 'f1', 10, 10),
                                     ap('b2', 'AP', 'f1', 700, 500)]);
          const after  = project(F, [ap('x1', 'AP', 'f1', 10, 10),
                                     ap('x2', 'AP', 'f1', 700, 500)]);
          const r = compareProjects(before, after);
          eq('nothing was paired', r.matched, 0);
          eq('two removed', r.removed.length, 2);
          eq('two added', r.added.length, 2);
          done();
        """)

    def test_one_before_and_two_after_with_the_same_name_is_still_ambiguous(self):
        """The other half of ambiguity, and it needs its own guard.

        The case above is caught by counting the *before* side. This one has a
        single "AP" before and two after, so that count is 1 and only the check
        on the after side can refuse it. Removing that check leaves this test
        as the one that fails, which is why both cases are here.
        """
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const before = project(F, [ap('b1', 'AP', 'f1', 10, 10)]);
          const after  = project(F, [ap('x1', 'AP', 'f1', 10, 10),
                                     ap('x2', 'AP', 'f1', 700, 500)]);
          const r = compareProjects(before, after);
          eq('nothing was paired', r.matched, 0);
          eq('the one before is removed', r.removed.map(a => a.id), ['b1']);
          eq('both after are added', r.added.length, 2);
          done();
        """)

    def test_position_is_never_a_matching_key(self):
        """Two APs that swapped places are two moves, not a match.

        Matching on position would report this as nothing having happened,
        which is exactly what the report exists to catch.
        """
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const before = project(F, [ap('a1', 'AP-1', 'f1', 100, 100),
                                     ap('a2', 'AP-2', 'f1', 600, 400)]);
          const after  = project(F, [ap('a1', 'AP-1', 'f1', 600, 400),
                                     ap('a2', 'AP-2', 'f1', 100, 100)]);
          const r = compareProjects(before, after);
          eq('both paired by id', r.matched, 2);
          eq('and both moved', r.changed.length, 2);
          r.changed.forEach(rec => check('a move was recorded for ' + rec.after.name,
                                         kindsOf(rec).indexOf('moved') !== -1));
          done();
        """)

    def test_added_and_removed_are_what_is_left_over(self):
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const before = project(F, [ap('a1', 'AP-1', 'f1', 100, 100),
                                     ap('gone', 'AP-OLD', 'f1', 200, 200)]);
          const after  = project(F, [ap('a1', 'AP-1', 'f1', 100, 100),
                                     ap('new', 'AP-NEW', 'f1', 300, 300)]);
          const r = compareProjects(before, after);
          eq('one removed, by name', r.removed.map(a => a.name), ['AP-OLD']);
          eq('one added, by name', r.added.map(a => a.name), ['AP-NEW']);
          eq('the untouched one is unchanged', r.unchanged.length, 1);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class MovementThresholdTests(NodeCase):
    """0.05 m per pixel, so 10 px is exactly the 0.5 m default."""

    def test_a_nudge_under_the_threshold_is_not_a_move(self):
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const before = project(F, [ap('a1', 'AP-1', 'f1', 100, 100)]);
          const after  = project(F, [ap('a1', 'AP-1', 'f1', 109, 100)]);  // 0.45 m
          const r = compareProjects(before, after);
          eq('nothing to report', r.changed.length, 0);
          eq('it is unchanged', r.unchanged.length, 1);
          done();
        """)

    def test_a_move_at_the_threshold_counts(self):
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const before = project(F, [ap('a1', 'AP-1', 'f1', 100, 100)]);
          const after  = project(F, [ap('a1', 'AP-1', 'f1', 110, 100)]);  // 0.50 m
          const r = compareProjects(before, after);
          eq('one change', r.changed.length, 1);
          eq('and it is a move', kindsOf(r.changed[0]), ['moved']);
          const m = r.changed[0].changes[0];
          check('the distance is in metres, got ' + m.metres,
                Math.abs(m.metres - 0.5) < 1e-9);
          done();
        """)

    def test_the_threshold_is_the_callers_to_set(self):
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const before = project(F, [ap('a1', 'AP-1', 'f1', 100, 100)]);
          const after  = project(F, [ap('a1', 'AP-1', 'f1', 109, 100)]);
          eq('every distance counts at zero',
             compareProjects(before, after, { threshold: 0 }).changed.length, 1);
          eq('nothing counts at three metres',
             compareProjects(before, after, { threshold: 3 }).changed.length, 0);
          done();
        """)

    def test_the_distance_uses_the_floors_own_scale(self):
        """metersPerUnit differs per floor, and a move is a real-world distance."""
        self.run_checks(r"""
          const coarse = [floor('f1', 'Level 1', 800, 600, 0.5)];  // 10x the scale
          const before = project(coarse, [ap('a1', 'AP-1', 'f1', 100, 100)]);
          const after  = project(coarse, [ap('a1', 'AP-1', 'f1', 102, 100)]);
          const r = compareProjects(before, after);
          eq('2 px at 0.5 m/px is a metre, so it counts', r.changed.length, 1);
          check('reported as 1 m',
                Math.abs(r.changed[0].changes[0].metres - 1) < 1e-9);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TheReCroppedFloorTests(NodeCase):
    """PlanTrim between the two saves must not read as every AP moving."""

    SHIFTED = r"""
      const bFloor = [floor('f1', 'Level 1', 1000, 800)];
      const aFloor = [floor('f1', 'Level 1', 700, 500)];   // trimmed
      const SHIFT = 150;
      const beforeAps = [ap('a1', 'AP-1', 'f1', 300, 300),
                         ap('a2', 'AP-2', 'f1', 500, 400),
                         ap('a3', 'AP-3', 'f1', 700, 600),
                         ap('a4', 'AP-4', 'f1', 400, 500)];
      const afterAps = beforeAps.map(a => ap(a.id, a.name, 'f1',
                                             a.location.coord.x - SHIFT,
                                             a.location.coord.y - SHIFT));
    """

    def test_a_uniform_shift_from_a_crop_is_not_reported_as_movement(self):
        self.run_checks(self.SHIFTED + r"""
          const r = compareProjects(project(bFloor, beforeAps),
                                    project(aFloor, afterAps));
          eq('all four paired', r.matched, 4);
          eq('and none of them moved', r.changed.length, 0);
          eq('all four are unchanged', r.unchanged.length, 4);
          done();
        """)

    def test_the_crop_is_named_on_the_result_so_the_page_can_say_so(self):
        """Silently correcting would be its own problem: the reader has to know
        the comparison did something to the numbers."""
        self.run_checks(self.SHIFTED + r"""
          const r = compareProjects(project(bFloor, beforeAps),
                                    project(aFloor, afterAps));
          eq('one floor was noted', r.floorNotes.length, 1);
          const n = r.floorNotes[0];
          eq('named', n.name, 'Level 1');
          eq('with both sizes', [n.beforeSize, n.afterSize], [[1000, 800], [700, 500]]);
          eq('and the shift taken out', [n.dx, n.dy], [-150, -150]);
          done();
        """)

    def test_a_real_move_on_a_re_cropped_floor_still_shows(self):
        """The whole point. The crop must not become an amnesty."""
        self.run_checks(self.SHIFTED + r"""
          // AP-3 moved 60 px (3 m) on top of the crop shift.
          afterAps[2] = ap('a3', 'AP-3', 'f1', 700 - SHIFT + 60, 600 - SHIFT);
          const r = compareProjects(project(bFloor, beforeAps),
                                    project(aFloor, afterAps));
          eq('exactly one change', r.changed.length, 1);
          eq('and it is the one that moved', r.changed[0].after.name, 'AP-3');
          const m = r.changed[0].changes.find(c => c.kind === 'moved');
          check('reported as 3 m, got ' + (m && m.metres),
                m && Math.abs(m.metres - 3) < 1e-9);
          done();
        """)

    def test_a_same_size_floor_is_never_compensated(self):
        """The dangerous direction. If every AP on an uncropped floor shifted
        by the same amount, that is a real relocation of the whole design and
        must be reported as such - not explained away."""
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1', 800, 600)];
          const beforeAps = [ap('a1', 'AP-1', 'f1', 100, 100),
                             ap('a2', 'AP-2', 'f1', 200, 200),
                             ap('a3', 'AP-3', 'f1', 300, 300),
                             ap('a4', 'AP-4', 'f1', 400, 400)];
          const afterAps = beforeAps.map(a => ap(a.id, a.name, 'f1',
                                                 a.location.coord.x + 40,
                                                 a.location.coord.y));
          const r = compareProjects(project(F, beforeAps), project(F, afterAps));
          eq('no crop was claimed', r.floorNotes.length, 0);
          eq('all four moved', r.changed.length, 4);
          done();
        """)

    def test_two_points_are_not_enough_to_call_something_a_crop(self):
        """Two APs that both moved look exactly like a shift. Refuse to guess."""
        self.run_checks(r"""
          const bFloor = [floor('f1', 'Level 1', 1000, 800)];
          const aFloor = [floor('f1', 'Level 1', 700, 500)];
          const beforeAps = [ap('a1', 'AP-1', 'f1', 300, 300),
                             ap('a2', 'AP-2', 'f1', 500, 400)];
          const afterAps = beforeAps.map(a => ap(a.id, a.name, 'f1',
                                                 a.location.coord.x - 150,
                                                 a.location.coord.y - 150));
          const r = compareProjects(project(bFloor, beforeAps), project(aFloor, afterAps));
          eq('nothing was compensated', r.floorNotes.length, 0);
          eq('so both read as moves', r.changed.length, 2);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class WhatCountsAsAChangeTests(NodeCase):
    def test_aim_mount_height_and_hardware_are_each_reported(self):
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const A = [ap('a1', 'AP-1', 'f1', 100, 100)];
          const before = project(F, A, [radio('a1')]);
          const after  = project(F, A, [radio('a1', {
            antennaDirection: 180, antennaTilt: -25, antennaHeight: 4.5,
            antennaMounting: 'WALL', antennaTypeId: 'ant-2' })]);
          const r = compareProjects(before, after);
          eq('one AP changed', r.changed.length, 1);
          eq('five things about it',
             kindsOf(r.changed[0]),
             ['antenna', 'azimuth', 'height', 'mount', 'tilt']);
          done();
        """)

    def test_the_antenna_is_named_rather_than_given_as_an_id(self):
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const A = [ap('a1', 'AP-1', 'f1', 100, 100)];
          const r = compareProjects(project(F, A, [radio('a1')]),
                                    project(F, A, [radio('a1', { antennaTypeId: 'ant-2' })]));
          const c = r.changed[0].changes.find(c => c.kind === 'antenna');
          eq('from a name', c.from, 'Panel 30');
          eq('to a name', c.to, 'Omni 3dBi');
          done();
        """)

    def test_an_azimuth_nudged_across_north_is_two_degrees_not_three_fifty_eight(self):
        self.run_checks(r"""
          eq('359 to 1', angleDelta(1, 359), 2);
          eq('and the other way', angleDelta(359, 1), 2);
          eq('a real half turn is still 180', angleDelta(0, 180), 180);
          eq('0 to 0', angleDelta(0, 0), 0);
          done();
        """)

    def test_moving_an_ap_to_another_floor_is_a_floor_change_not_a_move(self):
        """Comparing pixel coordinates across two different plans would produce
        a distance that means nothing."""
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1'), floor('f2', 'Level 2')];
          const before = project(F, [ap('a1', 'AP-1', 'f1', 100, 100)]);
          const after  = project(F, [ap('a1', 'AP-1', 'f2', 700, 500)]);
          const r = compareProjects(before, after);
          eq('the floor is the change', kindsOf(r.changed[0]), ['floor']);
          const c = r.changed[0].changes[0];
          eq('named from', c.from, 'Level 1');
          eq('named to', c.to, 'Level 2');
          done();
        """)

    def test_taking_an_ap_off_the_plan_is_reported(self):
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const before = project(F, [ap('a1', 'AP-1', 'f1', 100, 100)]);
          const after  = project(F, [ap('a1', 'AP-1', null)]);
          const r = compareProjects(before, after);
          check('it is reported', kindsOf(r.changed[0]).indexOf('unplaced') !== -1);
          done();
        """)

    def test_an_identical_project_reports_nothing_at_all(self):
        """The result that has to be trustworthy: a clean comparison means no
        differences, not a comparison that failed to look."""
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1'), floor('f2', 'Level 2')];
          const A = [ap('a1', 'AP-1', 'f1', 100, 100),
                     ap('a2', 'AP-2', 'f2', 300, 200),
                     ap('a3', 'AP-3', 'f1', 640, 480)];
          const R = A.map(a => radio(a.id));
          const r = compareProjects(project(F, A, R), project(F, A, R));
          eq('nothing changed', r.changed.length, 0);
          eq('nothing added', r.added.length, 0);
          eq('nothing removed', r.removed.length, 0);
          eq('and all three were looked at', r.unchanged.length, 3);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class FloorsAppearAndDisappearTests(NodeCase):
    def test_a_floor_is_paired_by_name_when_its_id_changed(self):
        self.run_checks(r"""
          const before = project([floor('old', 'Level 1')],
                                 [ap('a1', 'AP-1', 'old', 100, 100)]);
          const after  = project([floor('new', 'Level 1')],
                                 [ap('a1', 'AP-1', 'new', 100, 100)]);
          const r = compareProjects(before, after);
          eq('the floor was paired', r.floorPairs.length, 1);
          eq('so the AP did not change floor', r.changed.length, 0);
          done();
        """)

    def test_an_added_floor_is_named_as_added(self):
        self.run_checks(r"""
          const before = project([floor('f1', 'Level 1')], []);
          const after  = project([floor('f1', 'Level 1'), floor('f2', 'Level 2')], []);
          const r = compareProjects(before, after);
          eq('one added floor', r.addedFloors.map(f => f.name), ['Level 2']);
          eq('none removed', r.removedFloors.length, 0);
          done();
        """)

    def test_a_removed_floor_is_named_as_removed(self):
        self.run_checks(r"""
          const before = project([floor('f1', 'Level 1'), floor('f2', 'Level 2')], []);
          const after  = project([floor('f1', 'Level 1')], []);
          const r = compareProjects(before, after);
          eq('one removed floor', r.removedFloors.map(f => f.name), ['Level 2']);
          done();
        """)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
