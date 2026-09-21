"""The column grid reference printed under the marker, on the plan itself.

This was the half of the column-grid item the tables left open: a reference in
a table tells somebody which AP is at C-4, and a reference on the drawing tells
them where C-4 is while they are standing in the building holding it.

``buildAntennaMarkers`` is sliced out of report.js and run for real, and every
assertion reads the text back out of the SVG it returns. Asserting that
``report.js`` contains ``labelGrid`` would pass with the option wired to
nothing - which is exactly how the `Local -> Cloud` button shipped inert. The
grid arithmetic is not stubbed; it is half of what is under test.
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
  resolveApColor: c => c || '',
  safeColor: c => c || '#000',
  needsDarkText: () => false,
  outlineOn: () => '',
};
globalThis.WD = WD;

/* The same floor the table test uses: 800 x 600, A..E every 150 across,
   1..5 every 120 down, so the expected references are arithmetic rather than
   whatever the code happens to produce. */
const FLOOR = { id: 'floor-1', name: 'Level 1', width: 800, height: 600,
                metersPerUnit: 0.05 };
globalThis.settingsAvailable = true;
globalThis.proj = {
  projectId: 'p1', floorPlans: [FLOOR],
  antennas: {}, buildings: {}, buildingFloors: {}, images: {}, imageUrls: {},
  notes: [],
};
globalThis.CALIBRATION = {
  a: { x: 0,   y: 0,   col: 0, row: 1 },
  b: { x: 600, y: 480, col: 4, row: 5 },
  lettersAxis: 'x',
};
globalThis.FLOOR = FLOOR;

function mkAp(id, name, coord) {
  return { id: id, name: name, vendor: 'Vendor', model: 'Model-X',
           color: '#FF0000',
           location: coord ? { floorPlanId: FLOOR.id, coord: coord }
                           : { floorPlanId: FLOOR.id } };
}
/* Spread out: the placement search drops the second line on a crowded marker,
   which is correct behaviour and would otherwise be read here as the option
   failing. */
globalThis.APS = [
  mkAp('ap-1', 'SITE1-B1-01-AP001', { x: 0,   y: 0 }),     // exactly A-1
  mkAp('ap-2', 'SITE1-B1-01-AP002', { x: 600, y: 480 }),   // exactly E-5
  mkAp('ap-3', 'SITE1-B1-01-AP003', { x: 310, y: 250 }),   // mid-bay -> C-3
];
globalThis.OFF_PLAN = mkAp('ap-4', 'SITE1-B1-01-AP004', null);

/* ── stubs for what the marker builder reaches outside itself ───────────── */
function apLabel(ap, mode) {
  const n = (ap && ap.name) || '';
  return mode === 'short' ? n.slice(-3) : n;
}
function radioIsDirectional() { return false; }
function apIsOmniOnly() { return true; }
function safeColor(c) { return c || '#000'; }
function needsDarkText() { return false; }
function outlineOn() { return ''; }
function floorPlanImageUrl() { return ''; }
function freqToChannel(f) { return f; }
function fmt(v, d) { return String(v == null ? '' : Number(v).toFixed(d)); }
function fmtLength(v) { return v == null ? '' : v + ' m'; }

const ctx = {
  proj: proj,
  primaryRadio: () => ({ antennaHeight: 3.2, transmitPower: 15,
                         channelByCenterFrequencyDefinedNarrowChannels: [36] }),
};
globalThis.ctx = ctx;

// The grid arithmetic and its runtime, exactly as shipped - not stubbed.
eval(slice('function gridColumnIndex(label)', '\n  window.WDGrid'));
// The marker label and the marker builder, exactly as shipped.
eval(slice('  function apMarkerLabel(ap, opts, ctx) {',
           '\n  function antennaLabelHint('));

function opts(extra) {
  return Object.assign({ shortLabels: false, showCones: false }, extra || {});
}

/* Render the markers for a set of APs and hand back the SVG. */
function markersFor(o, aps, calibrated) {
  resetFloorGrids(calibrated === false ? {} : { [FLOOR.id]: CALIBRATION });
  return buildAntennaMarkers(aps || APS, 800, 600, opts(o), ctx, null, {});
}
globalThis.markersFor = markersFor;

/* Every piece of text painted into the SVG, in document order. */
function textsIn(svg) {
  return (svg.match(/<text[^>]*>[\s\S]*?<\/text>/g) || [])
    .map(t => t.replace(/<[^>]*>/g, '').replace(/&amp;/g, '&')
               .replace(/&#183;|&middot;/g, '·').trim())
    .filter(Boolean);
}
globalThis.textsIn = textsIn;

/* The sub-label lines only: whatever is not one of the AP main labels. */
function subsIn(svg) {
  const mains = APS.map(a => a.name).concat(APS.map(a => a.name.slice(-3)));
  return textsIn(svg).filter(t => mains.indexOf(t) === -1);
}
globalThis.subsIn = subsIn;

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
        # encoding is explicit: the labels carry a middle dot, and decoding the
        # child with the locale codec reads it as mojibake on Windows and
        # intact in CI - the inversion that wastes the most time.
        return subprocess.run(["node", "-e", program, str(REPORT_JS)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"node did not finish within {NODE_TIMEOUT_S}s") from exc


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class GridReferenceIsPaintedOnThePlanTests(unittest.TestCase):
    def run_checks(self, checks: str):
        proc = run_node(checks)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    def test_the_reference_appears_under_the_marker_when_the_option_is_on(self):
        self.run_checks(r"""
          const svg = markersFor({ labelGrid: true });
          const subs = subsIn(svg);
          eq('one sub-label per AP', subs.length, 3);
          check('A-1 is on the plan', subs.indexOf('A-1') !== -1);
          check('E-5 is on the plan', subs.indexOf('E-5') !== -1);
          check('C-3 is on the plan', subs.indexOf('C-3') !== -1);
          done();
        """)

    def test_nothing_is_painted_when_the_option_is_off(self):
        """The default. A reference nobody asked for is clutter on a drawing."""
        self.run_checks(r"""
          const svg = markersFor({ labelGrid: false });
          eq('no sub-labels at all', subsIn(svg).length, 0);
          check('no grid reference anywhere', !/>A-1</.test(svg));
          done();
        """)

    def test_an_uncalibrated_floor_paints_no_reference_rather_than_a_dash(self):
        """A dash on a drawing reads as a reference somebody failed to fill in."""
        self.run_checks(r"""
          const svg = markersFor({ labelGrid: true }, null, false);
          eq('no sub-labels', subsIn(svg).length, 0);
          check('no dash placeholder', !/>\s*[-—–]\s*</.test(svg));
          done();
        """)

    def test_the_reference_leads_the_other_extras(self):
        """It answers "where do I stand", which the model and height do not."""
        self.run_checks(r"""
          const svg = markersFor({ labelGrid: true, labelModel: true,
                                   labelHeight: true });
          const subs = subsIn(svg);
          check('something was painted', subs.length === 3);
          subs.forEach(function (s) {
            check('sub starts with the grid reference, got: ' + s,
                  /^[A-Z]+-\d+ · /.test(s));
            check('the model is still there, got: ' + s,
                  s.indexOf('Model-X') !== -1);
          });
          done();
        """)

    def test_an_ap_that_was_never_placed_contributes_nothing(self):
        self.run_checks(r"""
          const svg = markersFor({ labelGrid: true }, [OFF_PLAN]);
          eq('an unplaced AP paints no marker at all', textsIn(svg).length, 0);
          done();
        """)

    def test_the_reference_matches_what_the_tables_would_print(self):
        """One grid, one answer. Two renderers disagreeing about where C-4 is
        would be worse than neither having it - see the AP colour case in
        CLAUDE.md, where the Report printed a hex and the Labeler a name."""
        self.run_checks(r"""
          resetFloorGrids({ [FLOOR.id]: CALIBRATION });
          const svg = markersFor({ labelGrid: true });
          const subs = JSON.stringify(subsIn(svg).slice().sort());
          const viaTable = JSON.stringify(APS.map(gridRefForAp).slice().sort());
          eq('the plan and the table agree', subs, viaTable);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TheOptionIsOfferedWhereItWorksTests(unittest.TestCase):
    """The control has to exist, be reachable, and have a way to be set up.

    A checkbox whose feature needs calibration, on a panel with no way to
    calibrate, is the Sync dialog naming a greyed-out button again.
    """

    def test_the_placement_panel_offers_the_option_and_the_setup_button(self):
        proc = run_node(r"""
          const block = slice("      id: 'placement',", "      id: 'summary',");
          check('the label option is offered', block.indexOf("id: 'labelGrid'") !== -1);
          check('and a way to set the grid up is beside it',
                block.indexOf("type: 'gridref-button'") !== -1);
          const iOpt = block.indexOf("id: 'labelGrid'");
          const iBtn = block.indexOf("type: 'gridref-button'");
          check('the setup button follows the option it serves', iBtn > iOpt);
          check('it is off by default',
                /id: 'labelGrid'[\s\S]{0,200}?default: false/.test(block));
          done();
        """)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    def test_the_two_grids_are_told_apart_in_words(self):
        """The placement panel now carries two things called a grid: the
        section grid that splits a big floor across pages, and the building's
        own column grid. Naming both "grid" and leaving it there is how a
        control gets used for the wrong job."""
        proc = run_node(r"""
          const block = slice("      id: 'placement',", "      id: 'summary',");
          const m = block.match(/type: 'gridref-button'[\s\S]*?description: '([^']*)'/);
          check('the column grid button has a description', !!m);
          const desc = m ? m[1] : '';
          check('it says it is not the section grid, got: ' + desc,
                /section grid/.test(desc));
          done();
        """)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
