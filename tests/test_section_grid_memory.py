"""The Report remembers a project's section grid.

Before this, the columns-by-rows grid, the crop on each floor and the combined
cells lasted one session: picking another report type emptied them, and so did
opening the next file, so the same site was set up again for every report.

Each test drives the real `report.js` through the harness of
`test_report_prints_what_the_design_holds.py`, and the memory itself goes
through the **real store**: what one page run saves is handed to
`report_store.save_section_grid`, and what the next page run is told is
`report_store.section_grid_for_project`'s answer. A stub on both sides would
agree with itself whatever the two ended up sending each other.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.test_report_prints_what_the_design_holds import run_node  # noqa: E402
from tools import report_store  # noqa: E402

ALPHA = "pid-alpha"
BETA = "pid-beta"

# The page, talking to a server that answers `report/sections/get` with
# whatever the real store said (REMEMBERED, keyed by project id) and records
# every save, written to a file because a process that exits straight after
# console.log can lose the line.
PAGE = r"""
const fsx = require('fs');
const ALPHA = 'pid-alpha', BETA = 'pid-beta';
const saves = [];
const REMEMBERED = JSON.parse(process.env.WD_TEST_REMEMBERED || '{}');
let serverUp = process.env.WD_TEST_SERVER !== 'down';
WD.api = async (ep, body) => {
  if (ep === 'report/sections/get') {
    if (!serverUp) throw new Error('server unreachable');
    return REMEMBERED[body.projectId] || { ok: true, project: null, last: null };
  }
  if (ep === 'report/sections/save') {
    saves.push(JSON.parse(JSON.stringify(body)));
    fsx.writeFileSync(process.env.WD_TEST_SAVES, JSON.stringify(saves));
    return serverUp ? { ok: true, project: null, last: null } : { ok: false };
  }
  return { ok: false };
};
async function esx(p, id, name) {
  const z = new globalThis.JSZip();
  z.file('accessPoints.json', JSON.stringify({ accessPoints: p.accessPoints }));
  z.file('simulatedRadios.json', JSON.stringify({ simulatedRadios: p.radios }));
  z.file('antennaTypes.json', JSON.stringify({ antennaTypes: Object.values(p.antennas) }));
  z.file('floorPlans.json', JSON.stringify({ floorPlans: p.floorPlans }));
  z.file('images.json', JSON.stringify({ images: p.floorPlans.map(f => ({ id: f.imageId, imageFormat: 'PNG' })) }));
  z.file('notes.json', JSON.stringify({ notes: Object.values(p.notes) }));
  z.file('project.json', JSON.stringify({ project: { id, name } }));
  p.floorPlans.forEach(f => z.file('image-' + f.imageId, Buffer.from([137, 80, 78, 71])));
  const buf = await z.generateAsync({ type: 'nodebuffer' });
  return { name: name + '.esx', size: buf.length,
    arrayBuffer: async () => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length) };
}
async function openProject(id, name) { await E('loadFile')(await esx(project(), id, name)); }
// What the grid dialog holds when the person presses Done: the dialog's own
// state is private to the page, so it is set the way the dialog sets it.
function inDialog(state) {
  E('(function (s) { _gridFloorIdx = 0; _gridCols = s.cols; _gridRows = s.rows;'
    + ' _gridInitCols = 0; _gridInitRows = 0; _gridAutoReset = !!s.auto;'
    + ' _cropBoxes = s.crops || {}; _segMerges = s.merges || {};'
    + ' var c = (s.crops || {})[proj.floorPlans[0].id];'
    + ' _cropBox = c ? { x: c.x, y: c.y, w: c.w, h: c.h } : { x: 0, y: 0, w: 1, h: 1 }; })')(state);
  window.doneGridConfig();
}
const CROP_ALL_APS = { x: 0.05, y: 0.05, w: 0.9, h: 0.9 };
const CROP_CUTS_APS = { x: 0, y: 0, w: 0.5, h: 0.5 };
const MERGE = { cols: 4, rows: 3, groups: [{ c0: 0, r0: 0, c1: 1, r1: 0 }] };
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class MemoryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-section-memory-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._dir = report_store.REPORT_DIR
        self._path = report_store.SECTIONS_PATH
        report_store.REPORT_DIR = self.tmp
        report_store.SECTIONS_PATH = self.tmp / "section_grids.json"
        self.addCleanup(setattr, report_store, "REPORT_DIR", self._dir)
        self.addCleanup(setattr, report_store, "SECTIONS_PATH", self._path)
        self.saves_file = self.tmp / "saves.json"

    def page(self, checks: str, server: str = "up") -> list:
        """One run of the page. Returns what it saved, for the next to hear."""
        remembered = {pid: report_store.section_grid_for_project(pid)
                      for pid in (ALPHA, BETA)}
        old = {k: os.environ.get(k) for k in
               ("WD_TEST_REMEMBERED", "WD_TEST_SAVES", "WD_TEST_SERVER")}
        os.environ["WD_TEST_REMEMBERED"] = json.dumps(remembered)
        os.environ["WD_TEST_SAVES"] = str(self.saves_file)
        os.environ["WD_TEST_SERVER"] = server
        try:
            r = run_node(PAGE + checks)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(self.saves_file.read_text(encoding="utf-8")) \
            if self.saves_file.is_file() else []

    def remember(self, saves: list):
        """What the server does with what the page sent."""
        for body in saves:
            res = report_store.save_section_grid(body["projectId"], body)
            self.assertTrue(res["ok"], res)


class TheGridSurvivesSwitchingReport(MemoryCase):

    def test_size_crop_and_combined_cells_are_still_there_on_the_next_report(self):
        self.page(r"""
          await openProject(ALPHA, 'Invented Alpha');
          window.selectReport('placement');
          inDialog({ cols: 4, rows: 3, crops: { fA: CROP_ALL_APS }, merges: { fA: MERGE } });
          window.selectReport('aim');
          let o = E('collectOpts()');
          eq('size on the next report', [o.segCols, o.segRows], [4, 3]);
          eq('crop on the next report', o.cropBoxes, { fA: CROP_ALL_APS });
          eq('combined cells on the next report', o.segMerges, { fA: MERGE });
          window.selectReport('placement');
          o = E('collectOpts()');
          eq('and back again', [o.segCols, o.segRows], [4, 3]);
          eq('the sidebar button reads the size', /4 × 3/.test(
            E('renderOptHtml')({ type: 'grid-button', label: 'Section grid' })), true);
        """)

    def test_it_survives_with_the_server_down_for_the_rest_of_the_session(self):
        """The write failing must not lose what the person just set."""
        self.page(r"""
          await openProject(ALPHA, 'Invented Alpha');
          window.selectReport('placement');
          inDialog({ cols: 5, rows: 2 });
          window.selectReport('aim');
          eq('size on the next report', [E('collectOpts()').segCols, E('collectOpts()').segRows], [5, 2]);
        """, server="down")


class TheGridSurvivesReopeningTheFile(MemoryCase):

    def test_the_same_project_reopens_as_it_was_left(self):
        saves = self.page(r"""
          await openProject(ALPHA, 'Invented Alpha');
          window.selectReport('placement');
          inDialog({ cols: 4, rows: 3, crops: { fA: CROP_ALL_APS }, merges: { fA: MERGE } });
        """)
        self.assertEqual(len(saves), 1)
        self.assertEqual(saves[0]["projectId"], ALPHA)
        self.remember(saves)

        self.page(r"""
          await openProject(ALPHA, 'Invented Alpha');
          window.selectReport('placement');
          const o = E('collectOpts()');
          eq('size', [o.segCols, o.segRows], [4, 3]);
          eq('crop', o.cropBoxes, { fA: CROP_ALL_APS });
          eq('combined cells', o.segMerges, { fA: MERGE });
          check('the panel says it was filled in for them',
            E('renderOptHtml')({ type: 'grid-button', label: 'Section grid' })
              .indexOf('Remembered for this project.') >= 0);
        """)

    def test_a_new_project_starts_from_the_last_size_and_nothing_else(self):
        self.remember(self.page(r"""
          await openProject(ALPHA, 'Invented Alpha');
          window.selectReport('placement');
          inDialog({ cols: 4, rows: 3, crops: { fA: CROP_ALL_APS }, merges: { fA: MERGE } });
        """))
        self.page(r"""
          await openProject(BETA, 'Invented Beta');
          window.selectReport('placement');
          const o = E('collectOpts()');
          eq('size from the last one set', [o.segCols, o.segRows], [4, 3]);
          check('no crop from another project', !('cropBoxes' in o));
          check('no combined cells from another project', !('segMerges' in o));
          check('the panel says where the size came from',
            E('renderOptHtml')({ type: 'grid-button', label: 'Section grid' })
              .indexOf('last grid size') >= 0);
        """)

    def test_a_project_never_set_up_with_nothing_remembered_is_auto(self):
        self.page(r"""
          await openProject(BETA, 'Invented Beta');
          window.selectReport('placement');
          const o = E('collectOpts()');
          check('no size', !('segCols' in o) && !('segRows' in o));
          eq('the button reads Auto', /Auto/.test(
            E('renderOptHtml')({ type: 'grid-button', label: 'Section grid' })), true);
        """)

    def test_a_server_that_cannot_answer_opens_as_auto_and_does_not_throw(self):
        self.page(r"""
          await openProject(ALPHA, 'Invented Alpha');
          window.selectReport('placement');
          check('no size', !('segCols' in E('collectOpts()')));
        """, server="down")

    def test_one_project_opened_after_another_does_not_keep_the_first_ones_crop(self):
        self.remember(self.page(r"""
          await openProject(ALPHA, 'Invented Alpha');
          window.selectReport('placement');
          inDialog({ cols: 4, rows: 3, crops: { fA: CROP_ALL_APS }, merges: { fA: MERGE } });
          await openProject(BETA, 'Invented Beta');
          window.selectReport('placement');
          const o = E('collectOpts()');
          check('no crop carried into the next project', !('cropBoxes' in o));
          check('no combined cells carried into the next project', !('segMerges' in o));
        """))


class AutoIsAChoiceThatSticks(MemoryCase):

    def test_resetting_to_auto_is_remembered_and_is_not_the_last_size(self):
        self.remember(self.page(r"""
          await openProject(ALPHA, 'Invented Alpha');
          window.selectReport('placement');
          inDialog({ cols: 4, rows: 3 });
        """))
        saves = self.page(r"""
          await openProject(BETA, 'Invented Beta');
          window.selectReport('placement');
          eq('it started from the last size', E('collectOpts()').segCols, 4);
          // Reset to Auto in the dialog, then Done.
          inDialog({ cols: 2, rows: 2, auto: true });
          check('the size is cleared, not written down as 2 x 2',
                !('segCols' in E('collectOpts()')));
        """)
        self.assertNotIn("segCols", saves[-1])
        self.remember(saves)
        self.page(r"""
          await openProject(BETA, 'Invented Beta');
          window.selectReport('placement');
          check('Auto came back as Auto and not as the last size',
                !('segCols' in E('collectOpts()')));
        """)


class ACropIsNotAppliedBlindly(MemoryCase):

    def test_a_crop_that_would_leave_aps_off_the_sheets_is_not_applied(self):
        """The project id survives a revision in Ekahau, and a revision moves
        APs - so a crop that was right last time can cut one off on a floor
        nobody looks at."""
        self.remember([{"projectId": ALPHA, "segCols": 4, "segRows": 3,
                        "cropBoxes": {"fA": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}}}])
        self.page(r"""
          await openProject(ALPHA, 'Invented Alpha');
          window.selectReport('placement');
          const o = E('collectOpts()');
          check('the crop was not applied', !('cropBoxes' in o));
          eq('the size still was', [o.segCols, o.segRows], [4, 3]);
          check('and the person is told', toasts.some(t => /not applied/.test(t.msg)));
        """)

    def test_a_crop_on_a_floor_that_no_longer_exists_is_ignored(self):
        self.remember([{"projectId": ALPHA, "segCols": 4, "segRows": 3,
                        "cropBoxes": {"fGone": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}}}])
        self.page(r"""
          await openProject(ALPHA, 'Invented Alpha');
          window.selectReport('placement');
          check('nothing applied for a missing floor', !('cropBoxes' in E('collectOpts()')));
        """)

    def test_combined_cells_for_a_different_grid_are_not_applied(self):
        """They are cut from one grid and mean nothing on another. The page
        never sends this pair; a hand-edited or older file could hold it."""
        self.remember([{"projectId": ALPHA, "segCols": 5, "segRows": 5,
                        "segMerges": {"fA": {"cols": 4, "rows": 3,
                                             "groups": [{"c0": 0, "r0": 0, "c1": 1, "r1": 0}]}}}])
        self.page(r"""
          await openProject(ALPHA, 'Invented Alpha');
          window.selectReport('placement');
          const o = E('collectOpts()');
          eq('the size was applied', [o.segCols, o.segRows], [5, 5]);
          check('combined cells not applied to a grid they were not cut from',
                !('segMerges' in o));
        """)


if __name__ == "__main__":
    unittest.main()
