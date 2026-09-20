"""The Grid column, rendered by the real table builders.

Asserting that report.js *contains* the string "Grid" would pass with the
column wired to nothing. These slice ``renderAimReport`` and
``renderApLocationTable`` out of report.js, run them against a project built to
a known grid, and read the cells back out of the HTML - so a column that is
present but empty, in the wrong place, or out of step with its own header
fails.

Header, cells and column widths are checked together on purpose. Those three
lists are maintained separately in both tables, and a column added to two of
them prints a row one cell short with the last value hanging outside it.

Everything the two builders lean on from the rest of the file is stubbed to
something recognisable, so a failure points at the table code rather than at a
stub. The grid arithmetic is **not** stubbed: it is the thing under test.
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
const WD = {
  esc: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                     .replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  escAttr: s => String(s == null ? '' : s).replace(/"/g, '&quot;'),
};
globalThis.WD = WD;

/* ── the project, built to a grid we know ──────────────────────────────────
   800 x 600, lines A..E every 150 across and 1..5 every 120 down. */
const FLOOR = { id: 'floor-1', name: 'Level 1', width: 800, height: 600,
                metersPerUnit: 0.05 };
globalThis.settingsAvailable = true;
globalThis.proj = {
  projectId: 'p1',
  floorPlans: [FLOOR],
  antennas: { 'ant-1': { id: 'ant-1', name: 'Test Panel 30 deg' } },
  buildings: {}, buildingFloors: {}, images: {}, imageUrls: {}, notes: [],
};

function mkAp(id, name, coord) {
  return { id: id, name: name, vendor: 'Vendor', model: 'Model-X',
           location: coord ? { floorPlanId: FLOOR.id, coord: coord }
                           : { floorPlanId: FLOOR.id } };
}
const APS = [
  mkAp('ap-1', 'SITE1-B1-01-AP001', { x: 0, y: 0 }),        // exactly A-1
  mkAp('ap-2', 'SITE1-B1-01-AP002', { x: 600, y: 480 }),    // exactly E-5
  mkAp('ap-3', 'SITE1-B1-01-AP003', { x: 310, y: 250 }),    // mid-bay -> C-3
  mkAp('ap-4', 'SITE1-B1-01-AP004', null),                  // never placed
];
globalThis.APS = APS;
globalThis.FLOOR = FLOOR;
globalThis.CALIBRATION = {
  a: { x: 0,   y: 0,   col: 0, row: 1 },
  b: { x: 600, y: 480, col: 4, row: 5 },
  lettersAxis: 'x',
};

/* ── stubs for everything the tables reach for ─────────────────────────── */
function apLabel(ap) { return (ap && ap.name) || ''; }
function apIsOmniOnly() { return false; }
function radioIsDirectional() { return true; }
function shortFloorLabel(n) { return n; }
function floorPlanForAp(ap) { return FLOOR; }
function orientPickerHtml(key) { return '<!--orient:' + key + '-->'; }
function renderAimMiniMap() { return ''; }
function wantsCompassRef() { return false; }
function renderCompassReferencePage() { return ''; }
function apNotesPages() { return ''; }
function floorPlanImageUrl() { return ''; }
function buildingNameFor() { return 'Building 1'; }
// The aim report groups by floor before it builds a row. One floor here, so
// these are the shape rather than the logic - the sort order is not what is
// under test and a real one would drag in half the file.
function groupApsByFloor(aps) { return { [FLOOR.id]: aps.slice() }; }
function sortedFloorOrder() { return [FLOOR]; }
const REPORT_FOOTER = '<footer></footer>';

const ctx = {
  report: { docName: 'Test' },
  proj: proj,
  cover: () => '', inlineHeader: () => '',
  primaryRadio: () => ({ antennaTypeId: 'ant-1', antennaDirection: 90,
                         antennaTilt: -10, antennaHeight: 3.2 }),
  compass: () => 'E', fmt: (v, d) => String(v == null ? '' : Number(v).toFixed(d)),
  fmtLength: (v) => (v == null ? '—' : v + ' m'),
  unitsOf: () => 'm', metersToFt: v => v * 3.28084,
  floorPlanForAp: floorPlanForAp,
  dateStr: '2026-01-01', dateReadable: '1 January 2026',
};
globalThis.ctx = ctx;

// The grid arithmetic and its runtime, exactly as shipped.
eval(slice('function gridColumnIndex(label)', '\n  window.WDGrid'));
// The two tables under test.
eval(slice('  function renderAimReport(aps, opts, ctx) {',
           '\n  function renderAimMiniMap('));
eval(slice('  function renderApLocationTable(aps, fp, opts, ctx, antKeys) {',
           '\n  function renderApNameAudit('));

function opts(gridOn, extra) {
  return Object.assign({ gridRef: !!gridOn, overview: false, signOff: false,
                         nameAudit: false, showChannelPower: false,
                         compass: false, shortLabels: false }, extra || {});
}
globalThis.opts = opts;

/* Render one of the two tables with the grid on or off. */
function renderTable(which, gridOn, extra) {
  resetFloorGrids(gridOn ? { [FLOOR.id]: CALIBRATION } : {});
  const o = opts(gridOn, extra);
  return which === 'aim'
    ? renderAimReport(APS, o, ctx)
    : renderApLocationTable(APS, FLOOR, o, ctx, {});
}
globalThis.renderTable = renderTable;

function cellsOf(rowHtml) {
  return (rowHtml.match(/<t[dh][^>]*>[\s\S]*?<\/t[dh]>/g) || [])
    .map(c => c.replace(/<[^>]*>/g, '').replace(/&amp;/g, '&').trim());
}
function headerOf(html) {
  return cellsOf((html.match(/<thead>[\s\S]*?<\/thead>/) || [''])[0]);
}
function bodyRowsOf(html) {
  const body = (html.match(/<tbody>[\s\S]*?<\/tbody>/) || [''])[0];
  return (body.match(/<tr[^>]*>[\s\S]*?<\/tr>/g) || []).map(cellsOf);
}
globalThis.cellsOf = cellsOf;
globalThis.headerOf = headerOf;
globalThis.bodyRowsOf = bodyRowsOf;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function eq(what, got, want) {
  if (got !== want) failures.push(what + '\n     got:  ' + JSON.stringify(got)
                                 + '\n     want: ' + JSON.stringify(want));
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


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class GridReferencesPerAp(unittest.TestCase):
    def check(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_an_ap_gets_the_reference_for_where_it_actually_is(self):
        self.check("""
          resetFloorGrids({ [FLOOR.id]: CALIBRATION });
          eq('on the A-1 intersection', gridRefForAp(APS[0]), 'A-1');
          eq('on the E-5 intersection', gridRefForAp(APS[1]), 'E-5');
          eq('mid-bay takes the nearest', gridRefForAp(APS[2]), 'C-3');
          eq('an AP that was never placed', gridRefForAp(APS[3]), '');
          eq('an AP on an uncalibrated floor',
             gridRefForAp({ location: { floorPlanId: 'other', coord: { x: 1, y: 1 } } }), '');
          done();
        """)

    def test_the_column_is_hidden_until_it_has_something_to_say(self):
        """Both conditions have to hold. A column of dashes on every row of
        every table reads as a broken feature rather than an unused one."""
        self.check("""
          resetFloorGrids({});
          check('shown with no calibration', !showsGridColumn({ gridRef: true }));
          resetFloorGrids({ [FLOOR.id]: CALIBRATION });
          check('shown with the option off', !showsGridColumn({ gridRef: false }));
          check('shown with no options at all', !showsGridColumn({}));
          check('hidden when both are true', showsGridColumn({ gridRef: true }));
          done();
        """)

    def test_a_stored_calibration_that_no_longer_solves_shows_nothing(self):
        """Both points on one lettered line, say. It has to behave as though
        the floor were never set up rather than throw or invent a bay."""
        self.check("""
          resetFloorGrids({ [FLOOR.id]: { a: { x: 0, y: 0, col: 2, row: 1 },
                                          b: { x: 600, y: 480, col: 2, row: 5 },
                                          lettersAxis: 'x' } });
          eq('a broken calibration produced a reference', gridRefForAp(APS[0]), '');
          done();
        """)

    def test_the_solver_is_built_once_per_floor(self):
        """A table asks per row, and a large floor is several hundred rows."""
        self.check("""
          resetFloorGrids({ [FLOOR.id]: CALIBRATION });
          const first = gridSolverForFloor(FLOOR.id);
          check('no solver was built', !!first);
          check('rebuilt on every call', gridSolverForFloor(FLOOR.id) === first);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheRenderedTables(unittest.TestCase):
    def check(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_the_header_the_cells_and_the_widths_all_agree(self):
        for table in ("aim", "loc"):
            with self.subTest(table=table):
                self.check("""
                  const html = renderTable(%s, true);
                  const header = headerOf(html);
                  check('no Grid header: ' + header.join(' | '),
                        header.indexOf('Grid') > -1);
                  bodyRowsOf(html).forEach(function (row, i) {
                    eq('row ' + i + ' has the wrong number of cells',
                       row.length, header.length);
                  });
                  eq('the colgroup is out of step with the header',
                     (html.match(/<col[ >]/g) || []).length, header.length);
                  done();
                """ % json.dumps(table))

    def test_the_value_lands_under_the_grid_header_and_not_beside_it(self):
        """An off-by-one here puts a bay number under Azimuth, where it reads
        as a real bearing. That is the worst failure this feature has."""
        for table in ("aim", "loc"):
            with self.subTest(table=table):
                self.check("""
                  const html = renderTable(%s, true);
                  const header = headerOf(html);
                  const body = bodyRowsOf(html);
                  const at = header.indexOf('Grid');
                  check('no Grid column', at > -1);
                  eq('first AP', body[0][at], 'A-1');
                  eq('second AP', body[1][at], 'E-5');
                  eq('mid-bay AP', body[2][at], 'C-3');
                  eq('an AP that was never placed shows a dash',
                     body[3][at], '\\u2014');
                  done();
                """ % json.dumps(table))

    def test_turning_the_option_off_removes_the_column_entirely(self):
        """Not a column of dashes - no column."""
        for table in ("aim", "loc"):
            with self.subTest(table=table):
                self.check("""
                  const html = renderTable(%s, false);
                  const header = headerOf(html);
                  eq('the Grid header survived', header.indexOf('Grid'), -1);
                  bodyRowsOf(html).forEach(function (row, i) {
                    eq('row ' + i + ' still carries the cell',
                       row.length, header.length);
                  });
                  eq('the colgroup still carries it',
                     (html.match(/<col[ >]/g) || []).length, header.length);
                  done();
                """ % json.dumps(table))

    def test_the_aim_sheet_widths_still_sum_to_a_hundred(self):
        """`table-layout: fixed` with widths that do not add up scales the
        whole sheet down, which is how an installer ends up reading 5pt text."""
        self.check("""
          [true, false].forEach(function (grid) {
            [true, false].forEach(function (signOff) {
              const html = renderTable('aim', grid, { signOff: signOff });
              const widths = (html.match(/width:([\\d.]+)%/g) || [])
                .map(function (m) { return parseFloat(/([\\d.]+)/.exec(m)[1]); });
              const total = widths.reduce(function (a, b) { return a + b; }, 0);
              check('grid=' + grid + ' signOff=' + signOff
                    + ' sums to ' + total, Math.abs(total - 100) < 0.01);
            });
          });
          done();
        """)

    def test_the_grid_width_belongs_to_the_grid_column(self):
        """Counting the <col> elements is not enough: a width inserted one slot
        out gives the Grid column Azimuth's share and squeezes Azimuth into
        7%. The count still matches and the total still sums to 100, so this is
        the only assertion that catches it - found by mutation, not by reading.
        """
        self.check("""
          const html = renderTable('aim', true);
          const header = headerOf(html);
          const at = header.indexOf('Grid');
          check('no Grid column', at > -1);
          const widths = (html.match(/width:([\d.]+)%/g) || [])
            .map(function (m) { return parseFloat(/([\d.]+)/.exec(m)[1]); });
          eq('the Grid column did not get the narrow width', widths[at], 7);
          check('Azimuth was squeezed instead: ' + widths[header.indexOf('Azimuth')],
                widths[header.indexOf('Azimuth')] > 7);
          done();
        """)

    def test_the_installation_footer_spans_the_whole_table(self):
        """The subtotal row's colspan is computed separately from the header.
        One short and the last column hangs outside the table."""
        self.check("""
          [true, false].forEach(function (grid) {
            const html = renderTable('loc', grid);
            const header = headerOf(html);
            const span = parseInt(/colspan="(\\d+)"/.exec(html)[1], 10);
            eq('grid=' + grid + ': the footer does not span the table',
               span, header.length);
          });
          done();
        """)
