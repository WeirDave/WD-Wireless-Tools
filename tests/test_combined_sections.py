"""Combining section-grid cells into one section.

A grid is regular and a building is not. On an L-shaped plan one leg can be
a single open warehouse, and a 3x2 grid cuts it into A1/A2 and B1/B2: four
sheets of empty slab joined by match lines across the middle of nothing,
with no wall or column on any of them to place an AP by. The office in the
other leg genuinely wants the division.

So cells can be combined. The case this was asked for, and the one every
test here is built around: a 3x2 grid where A1+A2 print as one section "A",
B1+B2 as "B", and C1 and C2 stay divided.

These run the real renderer - `renderAntennaSegmentedOverview` with only the
marker drawing stubbed - and read back what would be printed, because a
merge that the dialog shows and the printed report ignores is exactly the
control-that-renders-and-does-nothing shape this repository keeps shipping.
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

PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('  function segCellLabel(col, row) {');
const b = src.indexOf('  function cropAntennaSegment(overlayEl) {');
if (a < 0 || b < 0 || b < a) throw new Error('segment renderer block moved');
globalThis.WD = {
  esc: (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  escAttr: (s) => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
                           .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
};
// Only the marker drawing is stood in for; it has its own tests and needs
// the whole AP context. Everything that decides what a sheet is runs for real.
function buildAntennaMarkers(aps) { return '<!--markers:' + aps.length + '-->'; }
eval(src.slice(a, b));

// A 3x2 grid over a 3000x2000 plan: every cell 1000 square.
const W = 3000, H = 2000;
const L_SHAPE = { cols: 3, rows: 2, groups: [
  { c0: 0, r0: 0, c1: 0, r1: 1 },   // A1 + A2 -> A
  { c0: 1, r0: 0, c1: 1, r1: 1 },   // B1 + B2 -> B
] };
// One AP in the middle of every cell, so every section gets a sheet.
function apsEverywhere() {
  const out = [];
  for (let r = 0; r < 2; r++) for (let c = 0; c < 3; c++)
    out.push({ id: c + '-' + r, location: { coord: { x: c * 1000 + 500, y: r * 1000 + 500 } } });
  return out;
}
function baseCells(cols, rows) {
  const cells = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++)
    cells.push({ col: c, row: r, x0: c * 1000, y0: r * 1000,
                 x1: (c + 1) * 1000, y1: (r + 1) * 1000, aps: [{ id: c + ',' + r }] });
  return cells;
}
function render(merge, aps) {
  return renderAntennaSegmentedOverview('plan.png', W, H, aps || apsEverywhere(),
    { segMerge: merge, floorName: 'Ground' }, {}, { cols: 3, rows: 2 }, '', true);
}
const sheetTitles = (html) => (html.match(/rep-seg-cell-title">Section [^ <]+/g) || [])
  .map(s => s.replace(/.*Section /, ''));

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class CombinedSections(unittest.TestCase):
    def check(self, body: str):
        program = PRELUDE + "eval(" + json.dumps(body) + ");"
        r = subprocess.run(["node", "-e", program, str(REPORT_JS)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())

    def test_the_l_shaped_building_prints_four_sheets_named_as_asked(self):
        """The request itself: A and B are one sheet each, C stays divided."""
        self.check("""
          const html = render(L_SHAPE);
          const titles = sheetTitles(html);
          check('sheets were ' + titles, JSON.stringify(titles) === '["A","B","C1","C2"]');
          check('A1 still printed as its own sheet', !/Section A1\\b/.test(html));
          check('the note does not say what was combined',
                /2 combined sections/.test(html));
          done();
        """)

    def test_a_combined_sheet_covers_both_cells_and_carries_both_sets_of_aps(self):
        """One sheet for A means the crop is A1 and A2 together, and every AP
        from both is on it - otherwise half the leg silently has no sheet."""
        self.check("""
          const html = render(L_SHAPE);
          const sheetA = html.split('rep-seg-cell"').filter(s => /Section A\\b/.test(s))[0] || '';
          check('no sheet for A', sheetA);
          check('A does not carry both APs', /<!--markers:2-->/.test(sheetA));
          check('A is not cropped to the full column: ' + (sheetA.match(/data-seg-y1="[^"]+"/) || [''])[0],
                /data-seg-y0="0"/.test(sheetA) && /data-seg-y1="2000"/.test(sheetA));
          done();
        """)

    def test_without_a_merge_nothing_changes(self):
        """Everybody who never touches the feature gets the same six sheets."""
        self.check("""
          const titles = sheetTitles(render(null));
          check('an unmerged grid changed: ' + titles,
                JSON.stringify(titles) === '["A1","B1","C1","A2","B2","C2"]');
          done();
        """)

    def test_a_merge_drawn_on_another_grid_shape_is_ignored(self):
        """Columns A and B on a 3x2 grid are a different piece of the building
        on a 4x2 one. Applying the old merge there would be a guess."""
        self.check("""
          const stale = { cols: 4, rows: 2, groups: L_SHAPE.groups };
          const titles = sheetTitles(render(stale));
          check('a stale merge was applied: ' + titles, titles.length === 6);
          done();
        """)

    def test_the_index_and_key_plan_letter_the_combined_sections(self):
        """The index page and the key plan on every sheet are how the reader
        finds a section, so they have to use the same names as the sheets."""
        self.check("""
          const html = render(L_SHAPE);
          const index = html.split('rep-seg-index')[1].split('rep-seg-cell"')[0];
          const labels = (index.match(/rep-grid-label[^>]*>([^<]+)</g) || [])
            .map(s => s.replace(/.*>/, '').replace('<', ''));
          check('index labels were ' + labels, JSON.stringify(labels) === '["A","B","C1","C2"]');
          const keyplan = (html.match(/rep-seg-locator-label[^>]*>[^<]+</g) || [])
            .map(s => s.replace(/.*>/, '').replace('<', ''));
          check('key plan never names A', keyplan.indexOf('A') > -1);
          check('key plan still names A1', keyplan.indexOf('A1') === -1);
          done();
        """)

    def test_match_lines_follow_combined_edges(self):
        """B's right edge meets two sections, so its match line names both and
        is drawn along each half. C1's left edge meets only B, along C1's own
        height - not B's."""
        self.check("""
          const secs = segSections(baseCells(3, 2), 3, 2, L_SHAPE);
          const by = (l) => secs.filter(s => s.label === l)[0];
          const b = matchLinesFor(by('B'), secs, 1000, 2000);
          check('B right label: ' + b.labels,
                /is-right">MATCH LINE — SECTIONS C1, C2</.test(b.labels));
          check('B left label: ' + b.labels, /is-left">MATCH LINE — SECTION A</.test(b.labels));
          check('B has no top or bottom neighbour', !/is-top|is-bottom/.test(b.labels));
          check('B right was not drawn as two halves: ' + b.svg,
                /x1="2000" y1="0" x2="2000" y2="1000"/.test(b.svg)
                && /x1="2000" y1="1000" x2="2000" y2="2000"/.test(b.svg));
          const c1 = matchLinesFor(by('C1'), secs, 1000, 1000);
          check('C1 left label: ' + c1.labels, /is-left">MATCH LINE — SECTION B</.test(c1.labels));
          check('C1 left drawn past its own edge: ' + c1.svg,
                /x1="2000" y1="0" x2="2000" y2="1000"/.test(c1.svg) && !/y2="2000"/.test(c1.svg));
          check('C1 bottom', /is-bottom">MATCH LINE — SECTION C2</.test(c1.labels));
          done();
        """)

    def test_a_whole_column_is_named_by_its_letter_and_anything_else_by_its_corners(self):
        self.check("""
          check('column', segSectionLabel(0, 0, 0, 1, 2) === 'A');
          check('two columns', segSectionLabel(0, 0, 1, 1, 2) === 'A–B');
          check('part of a column', segSectionLabel(0, 0, 0, 1, 3) === 'A1–A2');
          check('a row', segSectionLabel(0, 0, 2, 0, 2) === 'A1–C1');
          check('single', segSectionLabel(2, 1, 2, 1, 2) === 'C2');
          done();
        """)

    def test_combine_accepts_a_rectangle_and_says_why_it_refuses_anything_else(self):
        """The reason is what the disabled button shows, so each refusal has
        to be one somebody can act on."""
        self.check("""
          const ok = segMergeCombine(null, 3, 2, ['0,0', '0,1']);
          check('A1+A2 refused: ' + ok.error, !ok.error && ok.label === 'A');
          check('stored against its grid', ok.merge.cols === 3 && ok.merge.rows === 2);

          const one = segMergeCombine(null, 3, 2, ['0,0']);
          check('one cell accepted', /two or more/.test(one.error || ''));

          const ell = segMergeCombine(null, 3, 2, ['0,0', '0,1', '1,1']);
          check('an L was accepted', /rectangle/.test(ell.error || ''));

          const cut = segMergeCombine(L_SHAPE, 3, 2, ['0,0', '1,0']);
          check('cutting through a combined section was accepted',
                /cuts through/.test(cut.error || ''));

          const again = segMergeCombine(L_SHAPE, 3, 2, ['0,0', '0,1']);
          check('re-combining the same cells was accepted', /already/.test(again.error || ''));

          const absorb = segMergeCombine(L_SHAPE, 3, 2, ['0,0', '0,1', '1,0', '1,1']);
          check('combining two sections into one failed: ' + absorb.error,
                !absorb.error && absorb.merge.groups.length === 1 && absorb.label === 'A–B');
          done();
        """)

    def test_split_removes_only_the_section_that_was_picked(self):
        self.check("""
          const res = segMergeSplit(L_SHAPE, 3, 2, ['0,0', '0,1']);
          check('split failed: ' + res.error, !res.error);
          check('split took both: ' + JSON.stringify(res.merge),
                res.merge && res.merge.groups.length === 1 && res.merge.groups[0].c0 === 1);
          const last = segMergeSplit(res.merge, 3, 2, ['1,0']);
          check('splitting the last section should leave no merge', last.merge === null);
          const none = segMergeSplit(L_SHAPE, 3, 2, ['2,0']);
          check('splitting a plain cell was accepted', /Select a combined section/.test(none.error || ''));
          done();
        """)


if __name__ == "__main__":
    unittest.main()
