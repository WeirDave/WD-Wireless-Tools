"""The RF Design Review finds what is wrong with a design, and only that.

A paying user's first question of a design somebody hands over - their own
included - is "what will hurt on site": two radios on one channel within
earshot, a 2.4 GHz radio on channel 3, a 2.4 GHz cell louder than the 5 GHz
one, a directional antenna nobody aimed, two APs with one name. The review
reads those out of the .esx the way every other report does.

Every test here runs the **real** `designReview` and the real renderer from
`report.js` against an invented project built so each rule has exactly one
reason to fire, and one reason it must *not* - a disabled radio sitting on
top of another on the same channel, a Bluetooth radio, a 6 GHz radio on a
preferred scanning channel, a band balance exactly on the 3 dB line.

The AP schedule export is tested the same way: the real button in
`report.html`, the real handler it names, and the bytes that would be saved.
"""
from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from tests.test_report_prints_what_the_design_holds import ReportCase
from tests.delegated import DELEGATED_JS

ROOT = Path(__file__).resolve().parent.parent
REPORT_HTML = ROOT / "web" / "report.html"

PROJECT = r"""
/* 1000 x 800 at 0.05 m per unit: a 50 m x 40 m floor, so 200 units is 10 m. */
function reviewProject() {
  const floorPlans = [
    { id: 'fA', name: 'Ground Sample', width: 1000, height: 800, metersPerUnit: 0.05, imageId: 'imA' },
    { id: 'fB', name: 'Unscaled Sample', width: 1000, height: 800, imageId: 'imB' },
  ];
  const antennas = {
    omni: { id: 'omni', name: 'Integrated Omni Sample', directional: false },
    panel: { id: 'panel', name: 'Sample Panel 60', directional: true, beamWidthHorizontal: 60 },
  };
  const accessPoints = [], radios = [];
  let n = 0;
  function ap(name, floor, x, y, extra) {
    const id = 'ap' + (++n);
    accessPoints.push(Object.assign({ id, name, vendor: 'Vendo', model: 'V-100', noteIds: [],
      location: floor ? { floorPlanId: floor, coord: { x, y } } : undefined }, extra || {}));
    return id;
  }
  function radio(apId, freqs, tx, extra) {
    radios.push(Object.assign({ id: 'r' + radios.length, accessPointId: apId,
      radioTechnology: 'IEEE802_11', antennaTypeId: 'omni', antennaMounting: 'CEILING',
      antennaHeight: 3, transmitPower: tx,
      channelByCenterFrequencyDefinedNarrowChannels: freqs }, extra || {}));
  }
  // Two radios on 36 ten metres apart: one 20 MHz, one 80 MHz covering it.
  const a1 = ap('Sample-AP01', 'fA', 100, 100);
  radio(a1, [5180], 17); radio(a1, [2412], 14);           // 14 is exactly 3 below 17: fine
  radio(a1, [5975], 12);                                  // 6 GHz ch 1? no - 5975 is ch 5, a PSC
  const a2 = ap('Sample-AP02', 'fA', 300, 100);
  radio(a2, [5180, 5200, 5220, 5240], 17); radio(a2, [2422], 17);   // ch 3, and as loud as 5 GHz
  // Far corner, DFS, too loud, and a 6 GHz channel with no PSC in it.
  const a3 = ap('Sample-AP03', 'fA', 900, 700);
  radio(a3, [5260], 23); radio(a3, [5995], 12);
  // Same name as AP02.
  const a4 = ap('Sample-AP02', 'fA', 600, 400);
  radio(a4, [5745], 17);
  // Ekahau's default name, no model, no height, 40 MHz in 2.4.
  const a5 = ap('Simulated AP-5', 'fA', 600, 100, { model: '' });
  radio(a5, [2412, 2432], 12, { antennaHeight: null }); radio(a5, [5500], 17, { antennaHeight: null });
  // Directional, never aimed.
  const a6 = ap('Sample-AP06', 'fA', 800, 300);
  radio(a6, [5765], 17, { antennaTypeId: 'panel', antennaDirection: null });
  // A disabled radio and a Bluetooth radio on top of AP01, both on 36:
  // neither may count as a co-channel neighbour.
  const a7 = ap('Sample-AP07', 'fA', 110, 100);
  radio(a7, [5180], 17, { enabled: false });
  radio(a7, [5180], 17, { radioTechnology: 'BLUETOOTH' });
  radio(a7, [5785], 17);
  // On no floor plan at all.
  const a8 = ap('Sample-AP08', null);
  radio(a8, [5805], 17);
  // Two on 149 on a floor with no scale: cannot be measured, said so.
  const a9 = ap('Sample-AP09', 'fB', 100, 100); radio(a9, [5745], 17);
  const a10 = ap('Sample-AP10', 'fB', 120, 100); radio(a10, [5745], 17);
  return { accessPoints, radios, antennas, floorPlans, images: {},
    imageUrls: { imA: 'blob:a', imB: 'blob:b' }, buildings: {}, buildingFloors: {},
    notes: {}, measurements: [], measuredRadios: [], surveys: [], projectName: 'Invented' };
}
function openReview() {
  E('(function (p) { proj = p; fileName = "Invented Sample.esx"; })')(reviewProject());
}
function review(o) {
  return E('(function (o) { return designReview(proj, proj.accessPoints, o || {}); })')(o);
}
function byId(res, id) { return res.findings.find(f => f.id === id) || null; }
function names(f) { return f ? f.rows.map(r => r.ap ? r.ap.name : r.floor) : []; }
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheReviewFindsWhatIsWrong(ReportCase):

    def check(self, js: str):
        self.run_block(PROJECT + js)

    def test_co_channel_neighbours_closer_than_the_distance(self):
        self.check(r"""
          openReview();
          const res = review({ cciMeters: 20 });
          const f = byId(res, 'cci-FIVE');
          check('the 5 GHz co-channel finding exists', !!f);
          // AP01 on 36/20 and AP02 on 36/80 share 5180: ten metres apart.
          eq('who is listed', names(f), ['Sample-AP01', 'Sample-AP02']);
          check('the detail names the neighbour and the distance: ' + f.rows[0].detail,
                /Sample-AP02 \(ch 36\/80\) at 32\.8 ft/.test(f.rows[0].detail));
          eq('one pair on the map', res.pairs.length, 1);
          eq('severity', f.severity, 'check');
          // Tighten it below ten metres and they are no longer listed.
          check('nothing under 10 m', !byId(review({ cciMeters: 9 }), 'cci-FIVE'));
        """)

    def test_disabled_and_non_wifi_radios_are_never_neighbours(self):
        self.check(r"""
          openReview();
          const f = byId(review({ cciMeters: 20 }), 'cci-FIVE');
          check('AP07 is half a metre from AP01 on 36, but on a disabled and a Bluetooth radio',
                names(f).indexOf('Sample-AP07') === -1);
        """)

    def test_the_two_four_plan(self):
        self.check(r"""
          openReview();
          eq('channel 3 is off 1/6/11', names(byId(review({}), 'off24')), ['Sample-AP02']);
          eq('and on 1/5/9/13 too', names(byId(review({ plan24: '1-5-9-13' }), 'off24')), ['Sample-AP02']);
          eq('40 MHz in 2.4 GHz', names(byId(review({}), 'wide24')), ['Simulated AP-5']);
        """)

    def test_band_balance_flags_only_what_is_inside_three_db(self):
        self.check(r"""
          openReview();
          const f = byId(review({}), 'bandBalance');
          // AP01 is 14 against 17 - exactly three below, which passes.
          eq('only AP02, at 17 and 17', names(f), ['Sample-AP02']);
          check('the detail gives both powers', /2\.4 GHz 17 dBm, 5 GHz 17 dBm/.test(f.rows[0].detail));
          check('and it can be turned off', !byId(review({ bandBalance: false }), 'bandBalance'));
        """)

    def test_power_ceiling(self):
        self.check(r"""
          openReview();
          eq('23 dBm over 20', names(byId(review({ txCeiling: '20' }), 'txCeiling')), ['Sample-AP03']);
          check('off means no check', !byId(review({ txCeiling: 'off' }), 'txCeiling'));
          const many = names(byId(review({ txCeiling: '14' }), 'txCeiling'));
          check('at 14 the 17 dBm radios are listed too: ' + many, many.length > 5);
        """)

    def test_naming_mounting_and_placement(self):
        self.check(r"""
          openReview();
          const res = review({});
          eq('duplicate names', names(byId(res, 'dupName')), ['Sample-AP02', 'Sample-AP02']);
          eq('severity of a duplicate', byId(res, 'dupName').severity, 'fix');
          // Two rows reading the same would leave nobody able to find which is which.
          const dup = byId(res, 'dupName').rows.map(r => r.detail);
          check('the duplicates can be told apart: ' + dup, dup[0] !== dup[1]
                && /5 GHz ch 36\/80/.test(dup.join()) && /5 GHz ch 149/.test(dup.join()));
          eq('default name', names(byId(res, 'genericName')), ['Simulated AP-5']);
          eq('no model', names(byId(res, 'noModel')), ['Simulated AP-5']);
          eq('no height', names(byId(res, 'noHeight')), ['Simulated AP-5']);
          eq('unaimed panel', names(byId(res, 'noAzimuth')), ['Sample-AP06']);
          eq('no floor', names(byId(res, 'noFloor')), ['Sample-AP08']);
        """)

    def test_notes_dfs_psc_and_unscaled_floors(self):
        self.check(r"""
          openReview();
          const res = review({});
          eq('DFS', names(byId(res, 'dfs')).sort(), ['Sample-AP03', 'Simulated AP-5']);
          eq('6 GHz off the PSCs: AP03 on ch 9, not AP01 on ch 5',
             names(byId(res, 'psc')), ['Sample-AP03']);
          eq('the unscaled floor is named', names(byId(res, 'noScale')), ['Unscaled Sample']);
          check('and the two radios on it are not guessed at',
                !res.pairs.some(p => p.floorId === 'fB'));
        """)

    def test_a_clean_design_says_so(self):
        self.check(r"""
          const p = reviewProject();
          p.accessPoints = p.accessPoints.filter(a => a.id === 'ap1');
          p.radios = p.radios.filter(r => r.accessPointId === 'ap1');
          E('(function (q) { proj = q; })')(p);
          eq('no findings', review({}).findings.map(f => f.id), []);
          const html = render('design', { inclOmni: true, inclDirectional: true });
          check('the verdict says nothing to fix', html.includes('Nothing to fix and nothing to check'));
        """)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheReviewPrints(ReportCase):

    def check(self, js: str):
        self.run_block(PROJECT + js)

    def test_the_rendered_report(self):
        self.check(r"""
          openReview();
          const html = render('design', { inclOmni: true, inclDirectional: true, cciDistance: '20',
                                          plan24: '1-6-11', txCeiling: '20', units: 'meters' });
          check('fix count leads', /rep-hotspot-stat--severity"><b>(\d+)</.test(html));
          const fixes = +html.match(/rep-hotspot-stat--severity"><b>(\d+)</)[1];
          // dupName x2, off24, wide24, noAzimuth.
          eq('items to fix', fixes, 5);
          check('the verdict says it is not ready', html.includes('5 items to fix before this design is handed over.'));
          check('distances in the chosen unit', html.includes('Sample-AP02 (ch 36/80) at 10.00 m'));
          check('the channel plan table', html.includes('<h2 class="rep-floor-title">Channel plan</h2>'));
          check('36 is used twice on the ground floor', /36 <span class="rep-alt">×1<\/span>/.test(html)
                && html.includes('36/80 <span class="rep-alt">×1</span>'));
          // The channel map: one dashed line for the one pair, one marker per 5 GHz radio.
          const map = html.slice(html.indexOf('Ground Sample — 5 GHz channels'));
          check('a 5 GHz map for the ground floor', map.length > 0 && html.indexOf('Ground Sample — 5 GHz channels') >= 0);
          const groundMap = map.slice(0, map.indexOf('</section>'));
          eq('one co-channel line', (groundMap.match(/class="rep-dr-cci"/g) || []).length, 1);
          // AP01, AP02, AP03, AP04, AP05, AP06 and AP07's one live 5 GHz radio.
          eq('one marker per live 5 GHz radio', (groundMap.match(/class="rep-dr-mark"/g) || []).length, 7);
          // 36 and 36/80 share air, so they share a colour; 149 does not.
          const fill = lbl => (groundMap.match(new RegExp('fill="(#[0-9a-f]{6})"[^>]*/><text[^>]*>' + lbl.replace('/', '\\/') + '<')) || [])[1];
          check('36 and 36/80 drawn alike', fill('36') && fill('36') === fill('36/80'));
          check('149 drawn differently', fill('149') && fill('149') !== fill('36'));
          check('the methodology is printed', html.includes('What was checked'));
          check('the footer names the report', html.includes('RF Design Review'));
          // Notes off: no DFS section.
          const short = render('design', { inclOmni: true, inclDirectional: true, showNotes: false });
          check('notes can be left out', short.indexOf('DFS channels') === -1 && html.indexOf('DFS channels') >= 0);
          // The 2.4 GHz map draws the 2.4 radios instead.
          const two = render('design', { inclOmni: true, inclDirectional: true, mapBand: 'TWO' });
          check('a 2.4 GHz map', two.includes('Ground Sample — 2.4 GHz channels'));
        """)

    def test_the_card_is_in_the_gallery(self):
        self.check(r"""
          const cats = E('REPORT_CATEGORIES');
          check('the design review is offered in a category',
                cats.some(c => c.ids.indexOf('design') !== -1));
          eq('and renders with its own function', E('REPORTS.design.render.name'), 'renderDesignReviewReport');
        """)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheApScheduleExports(ReportCase):

    def test_the_button_reaches_a_handler_that_saves_the_schedule(self):
        self.run_block(DELEGATED_JS + PROJECT + r"""
          // Read by Node, not inlined: the page would push the command line
          // past Windows' 32K limit (WinError 206).
          const page = fs.readFileSync(""" + json.dumps(str(REPORT_HTML)) + r""", 'utf8');
          const hit = delegated(page, 'exportApSchedule');
          check('the review bar has the export button', !!hit);
          openReview();
          // A note with a comma and a quote, and a name that starts like a formula.
          E('proj.notes = { n1: { id: "n1", text: "Lift needed, \\"tall\\" one", imageIds: [] } };');
          E('proj.accessPoints[0].noteIds = ["n1"];');
          E('proj.accessPoints[1].name = "=HYPERLINK(1)";');
          E('apDisabled = new Set(["ap9"]);');   // unticked in the AP filter
          const saved = [];
          globalThis.Blob = function (parts, o) { this.text = parts.join(''); this.type = o.type; };
          globalThis.URL = { createObjectURL(b) { saved.push(b); return 'blob:x'; }, revokeObjectURL(){} };
          const anchors = [];
          document.createElement = t => { const el = mkEl(t); anchors.push(el); return el; };
          window[hit.fn].apply(null, hit.args);
          eq('one file', saved.length, 1);
          const a = anchors.find(x => x.download);
          check('named for the project: ' + (a && a.download), a && /AP Schedule.*\.csv$/.test(a.download));
          const text = saved[0].text;
          check('starts with a byte-order mark for Excel', text.charCodeAt(0) === 0xfeff);
          const lines = text.slice(1).split('\r\n').filter(Boolean);
          eq('header plus every AP but the unticked one', lines.length, 1 + 9);
          const head = lines[0].split(',');
          eq('first columns', head.slice(0, 5), ['AP name', 'Floor', 'Building', 'Vendor', 'Model']);
          check('per-band columns', head.indexOf('5 GHz channel') > 0 && head.indexOf('2.4 GHz TX (dBm)') > 0
                && head.indexOf('6 GHz width (MHz)') > 0);
          const ap1 = lines.find(l => l.indexOf('Sample-AP01,') === 0);
          check('AP01 row: ' + ap1, !!ap1);
          const cells = ap1.split(',');
          const at = k => cells[head.indexOf(k)];
          eq('5 GHz channel', at('5 GHz channel'), '36');
          eq('5 GHz TX', at('5 GHz TX (dBm)'), '17');
          eq('2.4 GHz channel', at('2.4 GHz channel'), '1');
          eq('6 GHz channel', at('6 GHz channel'), '5');
          eq('height in feet by default', at('Height (ft)'), '9.8');
          eq('X in feet', at('X (ft)'), '16.4');
          check('a note with a comma and quotes is quoted whole', text.includes('"Lift needed, ""tall"" one"'));
          check('a formula-shaped name is defused', text.includes("'=HYPERLINK(1)"));
          const ap2 = lines.find(l => l.indexOf("'=HYPERLINK") === 0);
          eq('80 MHz width', ap2.split(',')[head.indexOf('5 GHz width (MHz)')], '80');
          check('the unticked AP is not exported', !lines.some(l => l.indexOf('Sample-AP09,') === 0));
          check('a toast says what was saved', toasts.some(t => /Saved .*9 access points/.test(t.msg)));
        """)

    def test_metres_when_the_unit_is_metres(self):
        self.run_block(PROJECT + r"""
          openReview();
          const rows = E('(function () { return apScheduleRows(proj.accessPoints, { units: "meters" }); })')();
          const head = rows[0];
          const ap1 = rows.find(r => r[0] === 'Sample-AP01');
          eq('height', ap1[head.indexOf('Height (m)')], '3.00');
          eq('X', ap1[head.indexOf('X (m)')], '5.00');
          const ap8 = rows.find(r => r[0] === 'Sample-AP08');
          eq('no position for an AP on no floor', ap8[head.indexOf('X (m)')], '');
          const ap9 = rows.find(r => r[0] === 'Sample-AP09');
          eq('no position on a floor with no scale', ap9[head.indexOf('X (m)')], '');
        """)

    def test_nothing_to_export_says_so(self):
        self.run_block(PROJECT + r"""
          openReview();
          E('apDisabled = new Set(proj.accessPoints.map(a => a.id));');
          let made = 0;
          globalThis.Blob = function () { made++; };
          window.exportApSchedule();
          eq('no file', made, 0);
          check('and the reason', toasts.some(t => /no access points to export/.test(t.msg)));
        """)


if __name__ == "__main__":
    unittest.main()
