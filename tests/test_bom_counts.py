"""The Bill of Materials has to add up, including where the data does not.

Someone was counting APs by hand off the placement maps because the numbers
they needed were not in a form they could order from. So this asserts the
thing that matters to them rather than the markup: **every access point in the
project appears in every count on the sheet.** A BOM that is quietly short is
worse than one that says where it is short.

The three ways a real project breaks a count, all of them in the fixture here:

  * an AP with no model recorded - counted as "Unknown", never dropped
  * an AP on no floor plan - counted under "(No floor plan)", never dropped
  * an AP whose radio records no mounting - counted as "Not recorded"

The renderer is run for real in Node against a synthetic project. Everything
it leans on from the rest of report.js is stubbed to something recognisable,
so a failure points at the BOM code rather than at a stub.
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

NODE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const a = source.indexOf('  function renderBomReport(aps, opts, ctx) {');
const b = source.indexOf('  function classifyHotspot(ssid) {');
if (a < 0 || b < 0) throw new Error('the BOM renderer moved');

const WD = { esc: s => String(s), escAttr: s => String(s) };
const REPORT_FOOTER = '';
function apNotesPages() { return ''; }
function renderAntennaTable() { return '<table></table>'; }
function collectUsedAntennas() { return []; }
function groupApsByFloor(aps, ctx) {
  const by = {};
  aps.forEach(ap => {
    const fp = ctx.floorPlanForAp(ap);
    const key = fp ? fp.id : '_none';
    (by[key] = by[key] || []).push(ap);
  });
  return by;
}
function sortedFloorOrder(by) {
  const order = proj.floorPlans.slice();
  if (by['_none']) order.push({ id: '_none', name: '(No floor plan)' });
  return order;
}

// A project with one of each kind of gap.
const MODELS = [
  ['Meraki', 'MR46'], ['Meraki', 'MR57'],
  ['Aruba', 'AP-575'], ['Aruba', 'AP-655'],
];
const floors = [{ id: 'f1', name: 'FLR1' }, { id: 'f2', name: 'FLR2' }];
const accessPoints = [];
const radios = [];
for (let i = 1; i <= 40; i++) {
  const [vendor, model] = MODELS[i % 4];
  const onFloor = i <= 25 ? 'f1' : 'f2';
  const ap = { id: 'ap' + i, name: 'AP' + i, vendor, model,
               location: { floorPlanId: onFloor } };
  const radio = { accessPointId: ap.id, antennaMounting: (i % 3 ? 'CEILING' : 'WALL') };
  if (i === 5) { ap.vendor = ''; ap.model = ''; }        // no model
  if (i === 9) { ap.location = {}; }                     // no floor plan
  if (i === 13) { delete radio.antennaMounting; }        // no mount
  accessPoints.push(ap); radios.push(radio);
}
const proj = { accessPoints, radios, floorPlans: floors, antennas: {} };
const ctx = {
  dateStr: '2026-01-01',
  cover: () => '', inlineHeader: () => '',
  floorPlanForAp: ap => floors.filter(f => f.id === (ap.location || {}).floorPlanId)[0] || null,
  primaryRadio: id => radios.filter(r => r.accessPointId === id)[0] || null,
};

eval(source.slice(a, b));
const html = renderBomReport(accessPoints, { cover: false }, ctx);

function sectionOf(title) {
  const i = html.indexOf(title);
  if (i < 0) return '';
  const j = html.indexOf('</section>', i);
  return html.slice(i, j < 0 ? html.length : j);
}
function qtys(section) {
  return (section.match(/class="rep-az">(\d+)</g) || [])
    .map(s => parseInt(s.replace(/\D+/g, ''), 10));
}

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }

// ── every AP is in the project-total table, including the one with no model ──
const apSec = sectionOf('Access point quantities');
const apQ = qtys(apSec);
const apTotal = apQ.pop();
check('project totals do not add up: ' + apQ.join('+') + ' vs ' + apTotal,
      apQ.reduce((x, y) => x + y, 0) === 40 && apTotal === 40);
check('an AP with no model was dropped instead of counted as Unknown',
      /Unknown/.test(apSec));

// ── and in the per-floor table, including the one on no floor plan ──
const flSec = sectionOf('Access points per floor');
check('there is no per-floor breakdown', flSec.length > 0);
const flTotals = (flSec.match(/total<\/td><td class="rep-az">(\d+)</g) || [])
  .map(s => parseInt(s.replace(/\D+/g, ''), 10));
check('per-floor totals do not reach every AP: ' + flTotals.join('+'),
      flTotals.reduce((x, y) => x + y, 0) === 40);
check('an AP on no floor plan vanished from the per-floor counts',
      /\(No floor plan\)/.test(flSec));

// ── and in the mount table, including the one with no mounting recorded ──
const mSec = sectionOf('Mount types');
check('there is no mount breakdown', mSec.length > 0);
const mQ = qtys(mSec);
const mTotal = mQ.pop();
check('mount counts do not add up: ' + mQ.join('+') + ' vs ' + mTotal,
      mQ.reduce((x, y) => x + y, 0) === 40 && mTotal === 40);
check('an AP with no mounting was dropped instead of counted',
      /Not recorded/.test(mSec));

// ── the model string is the project's own, not a prettified one ──
check('a model name was rewritten', html.indexOf('AP-575') > -1
      && html.indexOf('MR46') > -1);

if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
process.exit(0);
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class EveryAccessPointIsCounted(unittest.TestCase):
    def test_the_bom_adds_up_including_the_gaps(self):
        r = subprocess.run(["node", "-e", NODE, str(REPORT_JS)],
                           capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).strip())


class TheSheetSaysWhatItContains(unittest.TestCase):
    """The preview card on the Configure step lists what the report produces.
    If it and the renderer disagree, the card is documentation for a different
    report."""

    def test_the_declared_sections_are_the_ones_rendered(self):
        js = REPORT_JS.read_text(encoding="utf-8")
        meta = js[js.index("      id: 'bom',"):]
        meta = meta[:meta.index("sidebar:")]
        for title in ("AP quantities", "Access points per floor",
                      "Antenna quantities", "Mount types", "Procurement notes"):
            self.assertIn(title, meta, "the BOM preview card omits " + title)
        body = js[js.index("function renderBomReport"):]
        body = body[:body.index("function classifyHotspot")]
        for heading in ("Access point quantities", "Access points per floor",
                        "Antenna quantities", "Mount types",
                        "Notes for procurement"):
            self.assertIn(heading, body)


if __name__ == "__main__":
    unittest.main()
