"""Columns and rows are each floor's own.

A mezzanine over part of a building is not cut the way the slab under it is, and
one size for the whole project could not say so. The grid dialog now keeps a
size per floor (`segGrids`, by floor id); a project-wide size from an earlier
version is still honoured and is turned into per-floor sizes the first time the
dialog is opened.

Every test drives the real `report.js` against the stub DOM of
`test_report_prints_what_the_design_holds`, through the dialog's own functions
(open, the +/- buttons, switching floor, Done), and prints the report to see
what each floor was cut into.
"""
from __future__ import annotations

import unittest

from tests.test_report_prints_what_the_design_holds import ReportCase

# Two floors of the invented project, "fA" and "fB". `labels` are the section
# letters the placement map printed, floor by floor; the dialog's state is
# read through the real functions rather than set.
KIT = r"""
const MERGE_4x3 = { cols: 4, rows: 3, groups: [{ c0: 0, r0: 0, c1: 1, r1: 0 }] };
function start(opts) {
  open();
  E('(function (o) { currentReportId = "placement"; currentOpts = o; })')(opts || {});
}
function labels(opts) {
  open();
  const html = render('placement', Object.assign({ segmented: true, nameKey: 'never', inclOmni: true }, opts));
  return (html.match(/class="rep-grid-label[^"]*"[^>]*>[^<]*</g) || []).map(x => x.replace(/.*>/, '').replace('<', ''));
}
function sizeShown() { return [E('_gridCols'), E('_gridRows')]; }
"""


class EachFloorIsCutOnItsOwn(ReportCase):

    def test_two_floors_print_with_different_columns_and_rows(self):
        self.run_block(KIT + r"""
          eq('a 3 x 1 ground floor and a 1 x 2 upper floor',
             labels({ segGrids: { fA: { cols: 3, rows: 1 }, fB: { cols: 1, rows: 2 } } }),
             ['A1', 'B1', 'C1', 'A1', 'A2']);
        """)

    def test_a_floor_with_no_size_of_its_own_takes_the_project_wide_one(self):
        """Older saves, and a project started from the last size set elsewhere."""
        self.run_block(KIT + r"""
          eq('fA has its own, fB takes the project-wide 2 x 1',
             labels({ segCols: 2, segRows: 1, segGrids: { fA: { cols: 3, rows: 1 } } }),
             ['A1', 'B1', 'C1', 'A1', 'B1']);
          eq('without a floor entry, both take it',
             labels({ segCols: 2, segRows: 1 }), ['A1', 'B1', 'A1', 'B1']);
        """)

    def test_a_floor_with_a_size_of_its_own_ignores_the_project_wide_one(self):
        self.run_block(KIT + r"""
          const grid = E('computeAntennaGrid');
          const aps = [];
          const o = { segCols: 5, segRows: 5, segGrids: { fB: { cols: 2, rows: 3 } } };
          eq('fB', grid(1000, 800, aps, o, 0.05, 'fB'), { cols: 2, rows: 3 });
          eq('fA', grid(1000, 800, aps, o, 0.05, 'fA'), { cols: 5, rows: 5 });
          eq('no floor named', grid(1000, 800, aps, o, 0.05), { cols: 5, rows: 5 });
          eq('a nonsense entry is not a size',
             grid(1000, 800, aps, { segCols: 4, segRows: 4, segGrids: { fA: { cols: 0, rows: 7 } } }, 0.05, 'fA'),
             { cols: 4, rows: 4 });
        """)


class TheDialogChangesOneFloor(ReportCase):

    def test_changing_one_floor_leaves_the_others_alone(self):
        self.run_block(KIT + r"""
          start();
          window.openGridConfig();
          const a0 = sizeShown();
          window.adjustGridCols(1);
          eq('the floor being edited moved', sizeShown(), [a0[0] + 1, a0[1]]);
          window.gridFloorPick(1);
          const b0 = E('autoGridFor')(E('proj.floorPlans[1]'));
          eq('the other floor still shows its own automatic grid', sizeShown(), [b0.cols, b0.rows]);
          window.gridFloorPick(0);
          eq('and the first floor kept the change', sizeShown(), [a0[0] + 1, a0[1]]);
          window.doneGridConfig();
          eq('only that floor is stored', E('currentOpts.segGrids'),
             { fA: { cols: a0[0] + 1, rows: a0[1] } });
          eq('no project-wide size', [E('currentOpts.segCols'), E('currentOpts.segRows')], [undefined, undefined]);
        """)

    def test_a_size_changed_on_the_second_floor_is_stored_for_the_second_floor(self):
        self.run_block(KIT + r"""
          start();
          window.openGridConfig();
          window.gridFloorPick(1);
          window.adjustGridRows(-1);
          window.adjustGridRows(1);
          window.adjustGridRows(1);
          const b = sizeShown();
          window.doneGridConfig();
          eq('fB only', E('currentOpts.segGrids'), { fB: { cols: b[0], rows: b[1] } });
        """)

    def test_putting_a_number_back_to_what_automatic_gives_stores_nothing(self):
        self.run_block(KIT + r"""
          start();
          window.openGridConfig();
          window.adjustGridCols(1);
          window.adjustGridCols(-1);
          window.doneGridConfig();
          eq('the floor is still automatic', E('currentOpts.segGrids'), null);
        """)

    def test_reset_to_auto_is_for_the_floor_being_shown(self):
        self.run_block(KIT + r"""
          start({ segGrids: { fA: { cols: 4, rows: 3 }, fB: { cols: 2, rows: 2 } } });
          window.openGridConfig();
          window.resetGridToAuto();
          const auto = E('autoGridFor')(E('proj.floorPlans[0]'));
          eq('fA is back to its automatic count', sizeShown(), [auto.cols, auto.rows]);
          window.doneGridConfig();
          eq('fB kept its own', E('currentOpts.segGrids'), { fB: { cols: 2, rows: 2 } });
        """)

    def test_a_project_wide_size_becomes_each_floors_own_on_opening(self):
        self.run_block(KIT + r"""
          start({ segCols: 4, segRows: 3 });
          window.openGridConfig();
          eq('the first floor shows it', sizeShown(), [4, 3]);
          window.gridFloorPick(1);
          eq('so does the second', sizeShown(), [4, 3]);
          window.adjustGridCols(-1);
          window.doneGridConfig();
          eq('the floor that was changed is its own, the other keeps the old size',
             E('currentOpts.segGrids'), { fA: { cols: 4, rows: 3 }, fB: { cols: 3, rows: 3 } });
          eq('and the project-wide size is gone, so nothing answers twice',
             [E('currentOpts.segCols'), E('currentOpts.segRows')], [undefined, undefined]);
        """)

    def test_cancelling_changes_nothing(self):
        self.run_block(KIT + r"""
          start({ segGrids: { fA: { cols: 4, rows: 3 } } });
          window.openGridConfig();
          window.adjustGridCols(1);
          window.closeGridConfig();
          eq('what was set is still what was set', E('currentOpts.segGrids'), { fA: { cols: 4, rows: 3 } });
        """)


class CombinedSectionsFollowTheirOwnFloor(ReportCase):

    def test_changing_one_floors_grid_keeps_the_other_floors_combined_sections(self):
        self.run_block(KIT + r"""
          start({ segGrids: { fA: { cols: 4, rows: 3 }, fB: { cols: 4, rows: 3 } },
                  segMerges: { fA: MERGE_4x3, fB: MERGE_4x3 } });
          window.openGridConfig();
          window.adjustGridCols(1);
          window.doneGridConfig();
          eq('fA lost its combined sections, which no longer fit its grid',
             Object.keys(E('currentOpts.segMerges') || {}), ['fB']);
        """)

    def test_a_floor_with_combined_sections_is_held_at_that_size(self):
        """Combined with the real buttons on a floor nobody gave a size: the
        sections are cut from today's automatic count, which moves when APs
        do, so the floor is held at it."""
        self.run_block(KIT + r"""
          start();
          E('(function () { proj.floorPlans[0].metersPerUnit = 1; })')();   // big enough to need sections
          window.openGridConfig();
          const auto = sizeShown();
          check('the floor is cut into more than one cell: ' + auto, auto[0] > 1);
          window.toggleGridMergeMode();
          window.gridMergePick('0,0');
          window.gridMergePick('1,0');
          window.combineGridCells();
          window.doneGridConfig();
          eq('the size the sections were cut from is stored', E('currentOpts.segGrids'),
             { fA: { cols: auto[0], rows: auto[1] } });
          eq('with the combined sections', Object.keys(E('currentOpts.segMerges')), ['fA']);
        """)

    def test_apply_to_all_floors_carries_the_size_with_the_combined_sections(self):
        self.run_block(KIT + r"""
          start({ segGrids: { fA: { cols: 4, rows: 3 }, fB: { cols: 2, rows: 2 } },
                  segMerges: { fA: MERGE_4x3 } });
          window.openGridConfig();
          window.applyGridFloor(true);
          window.doneGridConfig();
          eq('both floors are 4 x 3', E('currentOpts.segGrids'),
             { fA: { cols: 4, rows: 3 }, fB: { cols: 4, rows: 3 } });
          eq('both have the combined sections', Object.keys(E('currentOpts.segMerges')).sort(), ['fA', 'fB']);
        """)


class TheOptionsPanelSaysWhatTheFloorsAre(ReportCase):

    def test_auto_one_size_and_per_floor(self):
        self.run_block(KIT + r"""
          const html = () => E('renderOptHtml')({ type: 'grid-button', label: 'Section grid' });
          start();
          check('nothing set reads Auto', />Auto</.test(html()));
          E('(function () { currentOpts.segGrids = { fA: { cols: 3, rows: 2 }, fB: { cols: 3, rows: 2 } }; })')();
          check('the same on every floor reads that size', />3 × 2</.test(html()));
          E('(function () { currentOpts.segGrids.fB = { cols: 1, rows: 2 }; })')();
          check('different sizes read Per floor', />Per floor</.test(html()));
          E('(function () { delete currentOpts.segGrids.fB; })')();
          check('one floor set and the other automatic reads Per floor', />Per floor</.test(html()));
          E('(function () { delete currentOpts.segGrids; currentOpts.segCols = 4; currentOpts.segRows = 4; })')();
          check('a project-wide size still reads as it did', />4 × 4</.test(html()));
        """)


if __name__ == "__main__":
    unittest.main()
