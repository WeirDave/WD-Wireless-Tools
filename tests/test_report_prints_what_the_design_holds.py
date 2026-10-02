"""The Report prints what the design holds - no less, and nothing invented.

One review of the Report found a family of defects that all rendered cleanly
and printed wrong:

* the AP Installation table dropped **Mount, Height and Antenna** from every
  floor with no directional AP on it - the common all-ceiling-omni floor -
  although an omni hangs at a height off a mount like any other AP;
* a **crop box** on a sectioned floor took the APs outside it off every
  sheet and every index dot, and nothing said so;
* the Summary, BOM and Interference reports passed their omni-filtered list
  to the AP notes pages, so **notes on omni APs** vanished from reports that
  have no AP filter to bring them back;
* opening a **second project** kept the first one's grid, crop and combined
  sections, keyed by floor id, so a revision inherited them unseen;
* the TX Power column printed **15 dBm** for a radio with no stored power;
* the contents page stated **cols x rows detail sections** where empty
  sections are skipped and combined ones are one sheet;
* "Reset to shipped defaults", when added by `refreshRememberedState`, was an
  `onclick` attribute the page's policy never runs;
* "Group by colour" made two groups for one colour, and the Antenna Aim Sheet
  sorted AP10 before AP2.

Every test here loads the **real** `wd-shared.js` and `report.js` against a
stub DOM, renders the real report from an invented project, and reads the
markup that would be printed. The only addition to report.js is one line,
appended in memory, that lets the test reach the closure's state - `proj`,
`currentOpts` - the same way the page's own handlers do.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"
JSZIP_JS = ROOT / "web" / "assets" / "lib" / "jszip.min.js"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const [REPORT, SHARED, JSZIP] = process.argv.slice(1);

function mkEl(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(), hidden: false, value: '',
    checked: false, textContent: '', innerHTML: '', style: {}, dataset: {},
    attrs: {}, children: [], childNodes: [], className: '', type: '',
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){},
    appendChild(c) { this.children.push(c); return c; }, removeChild(){},
    setAttribute(k, v) {
      this.attrs[k] = String(v);
      if (k.indexOf('data-') === 0) {
        const key = k.slice(5).replace(/-([a-z])/g, (m, c) => c.toUpperCase());
        this.dataset[key] = String(v);
      }
    },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    removeAttribute(k) { delete this.attrs[k]; }, hasAttribute(k) { return k in this.attrs; },
    toggleAttribute(){}, scrollTo(){}, remove(){}, focus(){}, click(){},
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    closest(){ return null; }, contains(){ return false; },
    getBoundingClientRect(){ return { width: 0, height: 0, top: 0, left: 0 }; },
    insertAdjacentHTML(){}, scrollIntoView(){},
  };
  return el;
}
const els = {};
const selectors = {};
const docListeners = {};
const document = {
  getElementById(id) { return els[id] || (els[id] = mkEl('div')); },
  querySelector(sel) { return selectors[sel] || null; },
  querySelectorAll() { return []; },
  createElement(t) { return mkEl(t); },
  addEventListener(type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); },
  removeEventListener(){},
  body: mkEl('body'), documentElement: mkEl('html'), head: mkEl('head'),
  title: '', readyState: 'complete', cookie: '',
};
const store = {};
const localStorage = {
  getItem(k) { return k in store ? store[k] : null; },
  setItem(k, v) { store[k] = String(v); }, removeItem(k) { delete store[k]; },
};
globalThis.window = globalThis;
Object.assign(window, {
  document, localStorage, sessionStorage: localStorage,
  scrollTo(){}, scrollY: 0, addEventListener(){}, removeEventListener(){},
  matchMedia: () => ({ matches: false, addEventListener(){}, addListener(){} }),
  location: { search: '', pathname: '/report/', href: 'http://x/report/', hash: '' },
  fetch: async () => ({ ok: false, json: async () => ({}) }),
  requestAnimationFrame: f => setTimeout(f, 0),
  getComputedStyle: () => ({ getPropertyValue(){ return ''; } }),
  HTMLElement: function(){}, Element: function(){},
  MutationObserver: function(){ this.observe = function(){}; this.disconnect = function(){}; },
  indexedDB: undefined, alert(){},
});

// Node 22 has a read-only navigator of its own; CI runs older ones too.
try { Object.defineProperty(globalThis, 'navigator', { value: { userAgent: 'node' }, configurable: true }); }
catch (e) { /* the built-in is close enough */ }

(0, eval)(fs.readFileSync(SHARED, 'utf8'));
if (!window.WD) throw new Error('wd-shared.js did not define WD');
// The real WD.esc goes through a DOM node; the stub has none, so the same
// text-content escaping is done directly.
WD.esc = s => s == null ? '' : String(s).replace(/&/g, '&amp;')
  .replace(/</g, '&lt;').replace(/>/g, '&gt;');
WD.api = async () => ({ ok: false });
const toasts = [];
WD.toast = (msg, kind) => toasts.push({ msg, kind: kind || '' });
globalThis.JSZip = require(JSZIP);

// A Windows checkout has CRLF line endings; the hook looks for LF.
let rsrc = fs.readFileSync(REPORT, 'utf8').replace(/\r\n/g, '\n');
const tail = '  renderTemplateGallery();\n})();';
const at = rsrc.lastIndexOf(tail);
if (at < 0) throw new Error('the end of report.js moved; the test hook has nowhere to go');
rsrc = rsrc.slice(0, at) + '  window.__reportEval = function (s) { return eval(s); };\n' + rsrc.slice(at);
(0, eval)(rsrc);
const E = window.__reportEval;
if (!E) throw new Error('report.js did not load');

/* An invented project, deliberately imperfect. "Ground Sample" has only
   ceiling omni APs - the floor that lost its Mount and Height columns - and
   one of them has no stored transmit power and one no mount or height.
   "Upper Sample" mixes omni and directional, with a fifty-character antenna
   part number. Names run past 9 so a plain sort puts 10 before 2. */
const LONG_ANT = 'Fictional-Sector-Panel-Dual-Band-14dBi-N-Female-XL';
function project() {
  const floorPlans = [
    { id: 'fA', name: 'Ground Sample', width: 1000, height: 800, metersPerUnit: 0.05, imageId: 'imA' },
    { id: 'fB', name: 'Upper Sample', width: 1000, height: 800, metersPerUnit: 0.05, imageId: 'imB' },
  ];
  const antennas = {
    omni1: { id: 'omni1', name: 'Integrated Omni Sample', directional: false, apCoupling: 'INTERNAL_ANTENNA' },
    dir1:  { id: 'dir1', name: LONG_ANT, directional: true, apCoupling: 'EXTERNAL_ANTENNA', beamWidthHorizontal: 60 },
  };
  const accessPoints = [], radios = [];
  function add(n, floor, x, y, dir, extra) {
    const id = 'ap' + n;
    accessPoints.push({ id, name: 'Zed-AP' + n, vendor: 'Vendo', model: dir ? 'V-200E' : 'V-100',
      location: { floorPlanId: floor, coord: { x, y } }, noteIds: [] });
    radios.push(Object.assign({ id: 'r' + n, accessPointId: id, radioTechnology: 'IEEE802_11',
      antennaTypeId: dir ? 'dir1' : 'omni1', antennaMounting: 'CEILING', antennaHeight: 3,
      antennaDirection: dir ? 90 : null, transmitPower: 20,
      channelByCenterFrequencyDefinedNarrowChannels: [5180] }, extra || {}));
  }
  // Ground: four omni APs in the left half of the plan, two top right.
  add(1, 'fA', 100, 100, false);
  add(2, 'fA', 200, 600, false, { transmitPower: null });
  add(3, 'fA', 300, 300, false, { antennaMounting: null, antennaHeight: null });
  add(4, 'fA', 150, 450, false);
  add(9, 'fA', 700, 200, false);
  add(11, 'fA', 850, 250, false);
  // Upper: two omni, three directional.
  add(5, 'fB', 100, 100, false);
  add(6, 'fB', 600, 200, true);
  add(10, 'fB', 700, 500, true);
  add(12, 'fB', 300, 600, false);
  add(7, 'fB', 800, 700, true);
  accessPoints[0].noteIds = ['n1'];                       // an omni AP's note
  const notes = { n1: { id: 'n1', text: 'Omni note: ladder needed', imageIds: [] } };
  return { accessPoints, radios, antennas, floorPlans, images: {},
    imageUrls: { imA: 'blob:a', imB: 'blob:b' }, buildings: {}, buildingFloors: {},
    notes, measurements: [], measuredRadios: [], surveys: [], projectName: 'Invented' };
}

function open(p) {
  E('(function (p) { proj = p; fileName = "Invented Sample.esx"; })')(p || project());
}
function render(id, opts) {
  E('(function (id, o) { currentReportId = id; currentOpts = o; })')(id, opts || {});
  E('window.renderReport()');
  return els.reportCanvas.innerHTML;
}
// The part of a rendered report belonging to one floor's section.
function floorPart(html, startMarker, endMarker) {
  const a = html.indexOf(startMarker);
  if (a < 0) throw new Error('not in the report: ' + startMarker);
  const b = endMarker ? html.indexOf(endMarker, a + startMarker.length) : -1;
  return html.slice(a, b < 0 ? html.length : b);
}

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function eq(what, got, want) {
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    failures.push(what + ': got ' + JSON.stringify(got) + ', wanted ' + JSON.stringify(want));
  }
}
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


def run_node(checks: str) -> subprocess.CompletedProcess:
    """Awaited, so an async check cannot exit 0 before its failures are read."""
    program = (PRELUDE + "(async function () {\n" + checks
               + "\ndone();\n})().catch(function (e) {\n"
               + "  console.error((e && e.stack) || e); process.exit(1);\n});")
    try:
        return subprocess.run(
            ["node", "-e", program, str(REPORT_JS), str(SHARED_JS), str(JSZIP_JS)],
            capture_output=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"node did not finish within {NODE_TIMEOUT_S}s") from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ReportCase(unittest.TestCase):
    def run_block(self, checks: str):
        r = run_node(checks)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())


class TheInstallationTableKeepsMountHeightAndAntenna(ReportCase):

    def test_an_all_omni_floor_prints_mount_height_and_antenna(self):
        self.run_block(r"""
          open();
          const html = render('location', { inclOmni: true });
          const ground = floorPart(html, '<h2 class="rep-floor-title">Ground Sample</h2>',
                                   '<h2 class="rep-floor-title">Upper Sample</h2>');
          const table = floorPart(ground, '<table class="rep-ap-table rep-loc-table">', '</table>');
          const heads = (table.match(/<th[^>]*>[^<]*<\/th>/g) || []).map(h => h.replace(/<[^>]+>/g, ''));
          check('Mount header on the all-omni floor: ' + heads, heads.includes('Mount'));
          check('Height header on the all-omni floor: ' + heads, heads.includes('Height'));
          check('Antenna header on the all-omni floor: ' + heads, heads.includes('Ant.'));
          check('no Azimuth on a floor with nothing to aim: ' + heads, !heads.includes('Azimuth'));
          check('no Tilt on a floor with nothing to aim', !heads.includes('Tilt'));
          const row1 = floorPart(table, 'Zed-AP1<', '</tr>');
          check('the omni AP prints its mount', row1.includes('CEILING'));
          check('the omni AP prints its height', /<td class="rep-nowrap-print">[^<]*\d/.test(row1));
          // Every row has as many cells as there are headers, and the colgroup
          // and footer agree - a column counted in one place only leaves the
          // table ragged on paper.
          const rows = table.split('<tr').slice(2).filter(r => r.indexOf('rep-subtotal') < 0);
          rows.forEach(r => eq('cells in a row', (r.match(/<td/g) || []).length, heads.length));
          eq('cols in the colgroup', (table.match(/<col /g) || []).length, heads.length);
          eq('footer span', (table.match(/colspan="(\d+)"/) || [])[1], String(heads.length));
          const widths = (table.match(/--print-col-w:([\d.]+)%/g) || [])
            .map(s => parseFloat(s.replace(/[^\d.]/g, '')));
          check('print widths add to 100%: ' + widths,
                Math.abs(widths.reduce((a, b) => a + b, 0) - 100) < 0.1);
        """)

    def test_a_floor_with_directional_aps_keeps_azimuth_and_tilt(self):
        self.run_block(r"""
          open();
          const html = render('location', { inclOmni: true });
          const upper = floorPart(html, '<h2 class="rep-floor-title">Upper Sample</h2>');
          const table = floorPart(upper, '<table class="rep-ap-table rep-loc-table">', '</table>');
          const heads = (table.match(/<th[^>]*>[^<]*<\/th>/g) || []).map(h => h.replace(/<[^>]+>/g, ''));
          ['Mount', 'Height', 'Azimuth', 'Tilt', 'Ant.'].forEach(h =>
            check(h + ' on the mixed floor: ' + heads, heads.includes(h)));
          eq('footer span', (table.match(/colspan="(\d+)"/) || [])[1], String(heads.length));
        """)

    def test_a_missing_transmit_power_prints_a_dash_not_15_dbm(self):
        self.run_block(r"""
          open();
          const html = render('location', { inclOmni: true });
          const row = floorPart(html, 'Zed-AP2<', '</tr>');
          check('no power is invented for Zed-AP2: ' + row, row.indexOf('dBm') < 0);
          const cells = row.match(/<td class="rep-nowrap">([^<]*)<\/td>/);
          eq('the TX Power cell', cells && cells[1], '—');
          const stored = floorPart(html, 'Zed-AP1<', '</tr>');
          check('a stored power still prints', stored.indexOf('20 dBm') >= 0);
        """)


class ACropNamesTheApsItLeavesOut(ReportCase):
    """Ground Sample's crop is the left 45% of the plan; Zed-AP9 and
    Zed-AP11 lie in the right half."""

    OPTS = ("{ inclOmni: true, segmented: true, segCols: 2, segRows: 2, "
            "nameKey: 'never', cropBoxes: { fA: { x: 0, y: 0, w: 0.45, h: 1 } } }")

    def test_the_placement_sheet_names_them(self):
        self.run_block(r"""
          open();
          const html = render('placement', OPTS);
          const a = html.indexOf('data-floor-id="fA"'), b = html.indexOf('data-floor-id="fB"');
          if (a < 0 || b < 0) throw new Error('floor sections not found');
          const ground = html.slice(a, b);
          check('the outside APs are named on the floor\'s sheet: ' + ground.slice(0, 600),
                ground.indexOf('2 APs lie outside the cropped area and are not on these sheets: Zed-AP9, Zed-AP11') >= 0);
          const upper = html.slice(b);
          check('an uncropped floor says nothing of the kind',
                upper.indexOf('outside the cropped area') < 0);
        """.replace("OPTS", self.OPTS))

    def test_the_installation_report_names_them_too(self):
        self.run_block(r"""
          open();
          const html = render('location', OPTS);
          const ground = floorPart(html, '<h2 class="rep-floor-title">Ground Sample</h2>',
                                   '<h2 class="rep-floor-title">Upper Sample</h2>');
          check('named on the AP Installation sheet',
                ground.indexOf('not on these sheets: Zed-AP9, Zed-AP11') >= 0);
        """.replace("OPTS", self.OPTS))

    def test_the_grid_dialog_warns_while_the_crop_is_drawn(self):
        self.run_block(r"""
          open();
          E('(function () { currentReportId = "placement"; currentOpts = { cropBoxes: { fA: { x: 0, y: 0, w: 0.45, h: 1 } } }; })')();
          window.openGridConfig();
          const warn = els.gridCropWarn;
          check('the warning is shown', warn && warn.hidden === false);
          check('it names both APs: ' + (warn && warn.textContent),
                warn && /2 APs/.test(warn.textContent)
                && warn.textContent.indexOf('Zed-AP9, Zed-AP11') >= 0);
          window.resetCropBox();
          check('the warning clears when nothing is cut', warn.hidden === true && !warn.textContent);
        """)

    def test_apply_to_all_floors_says_what_it_cut_elsewhere(self):
        self.run_block(r"""
          open();
          E('(function () { currentReportId = "placement"; currentOpts = {}; })')();
          window.openGridConfig();
          // Draw the crop on the Ground floor, as the drag would leave it.
          E('(function () { _cropBox = { x: 0, y: 0, w: 0.45, h: 1 }; })')();
          toasts.length = 0;
          window.applyGridFloor(true);
          const t = toasts[toasts.length - 1] || { msg: '' };
          check('the toast names the Upper floor\'s APs: ' + t.msg,
                t.msg.indexOf('Upper Sample: Zed-AP6, Zed-AP7, Zed-AP10') >= 0);
          check('and the Ground floor\'s: ' + t.msg,
                t.msg.indexOf('Ground Sample: Zed-AP9, Zed-AP11') >= 0);
          eq('it is a warning', t.kind, 'warn');
        """)


class TheContentsCountsTheSheetsThatPrint(ReportCase):

    def test_the_stated_count_is_the_printed_count(self):
        """2x2 on Ground Sample with the left column combined: the left
        column prints as one sheet, Zed-AP9 and Zed-AP11 share the top-right
        cell, and the bottom-right cell is empty and skipped. Two sheets,
        where cols x rows said four."""
        self.run_block(r"""
          open();
          document.getElementById('optCover').checked = true;
          const merge = { cols: 2, rows: 2, groups: [{ c0: 0, r0: 0, c1: 0, r1: 1 }] };
          const html = render('location', { inclOmni: true, segmented: true, segCols: 2,
            segRows: 2, nameKey: 'never', segMerges: { fA: merge } });
          els.optCover.checked = false;
          const toc = floorPart(html, 'rep-toc-list', '</ol>');
          const groundToc = floorPart(toc, '<b>Ground Sample</b>', '</li>');
          const stated = +((groundToc.match(/(\d+) detail section/) || [])[1]);
          const ground = floorPart(html, '<h2 class="rep-floor-title">Ground Sample</h2>',
                                   '<h2 class="rep-floor-title">Upper Sample</h2>');
          const printed = (ground.match(/class="rep-seg-cell-title"/g) || []).length;
          check('some sections printed', printed > 0);
          eq('the contents states the sections that print (printed ' + printed + ')', stated, printed);
          check('and that is not cols x rows', stated !== 4);
        """)


class OmniNotesReachEveryReport(ReportCase):

    def test_summary_bom_and_interference_carry_the_omni_note(self):
        self.run_block(r"""
          const p = project();
          // The Interference report needs a survey to reach its pages at all.
          p.measurements = [{ id: 'm1', ssid: 'Sample Office', channelByCenterFrequencyDefinedNarrowChannels: [5180] }];
          open(p);
          ['summary', 'bom', 'interference'].forEach(id => {
            const html = render(id, {});
            check(id + ' carries the note on an omni AP', html.indexOf('Omni note: ladder needed') >= 0);
          });
        """)


class ASecondProjectStartsWithItsOwnGrid(ReportCase):

    def test_grid_crop_and_merges_do_not_carry_over(self):
        self.run_block(r"""
          const JSZip = globalThis.JSZip;
          async function esx(p, name) {
            const z = new JSZip();
            z.file('accessPoints.json', JSON.stringify({ accessPoints: p.accessPoints }));
            z.file('simulatedRadios.json', JSON.stringify({ simulatedRadios: p.radios }));
            z.file('antennaTypes.json', JSON.stringify({ antennaTypes: Object.values(p.antennas) }));
            z.file('floorPlans.json', JSON.stringify({ floorPlans: p.floorPlans }));
            z.file('images.json', JSON.stringify({ images: p.floorPlans.map(f => ({ id: f.imageId, imageFormat: 'PNG' })) }));
            z.file('notes.json', JSON.stringify({ notes: Object.values(p.notes) }));
            z.file('project.json', JSON.stringify({ project: { id: 'pid-' + name, name } }));
            p.floorPlans.forEach(f => z.file('image-' + f.imageId, Buffer.from([137, 80, 78, 71])));
            const buf = await z.generateAsync({ type: 'nodebuffer' });
            return { name: name + '.esx', size: buf.length,
              arrayBuffer: async () => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length) };
          }
          const loadFile = E('loadFile');
          await loadFile(await esx(project(), 'Invented Alpha'));
          window.selectReport('placement');
          E('(function () { currentOpts.segmented = true; currentOpts.segCols = 4; currentOpts.segRows = 3; '
            + 'currentOpts.cropBoxes = { fA: { x: 0, y: 0, w: 0.5, h: 0.5 } }; '
            + 'currentOpts.segMerges = { fA: { cols: 4, rows: 3, groups: [{ c0: 0, r0: 0, c1: 1, r1: 0 }] } }; '
            + 'currentOpts.shortLabels = false; })')();
          // A revision of the same project: same floor ids.
          await loadFile(await esx(project(), 'Invented Alpha rev B'));
          window.selectReport('placement');
          const o = E('currentOpts');
          ['segCols', 'segRows', 'cropBoxes', 'segMerges'].forEach(k =>
            check(k + ' carried over to the next project: ' + JSON.stringify(o[k]), !(k in o)));
          eq('an ordinary report option is kept', o.shortLabels, false);
          eq('so is the sectioning choice', o.segmented, true);
        """)


class ResetToShippedDefaultsIsDelegated(ReportCase):

    def test_the_button_added_after_a_save_reaches_its_handler(self):
        """The button `refreshRememberedState` adds, clicked through the real
        WD.actions dispatcher. An `onclick` attribute set here is a string the
        page's policy never runs."""
        self.run_block(r"""
          open();
          E('(function () { currentReportId = "location"; savedReportDefaults = { location: { specs: true } }; })')();
          const wrap = mkEl('div');
          const state = mkEl('span');
          wrap.querySelector = sel => sel === '.rep-remembered-state' ? state : null;
          selectors['.rep-remembered-opts'] = wrap;
          window.setOpt({ getAttribute: k => ({ 'data-opt-id': 'compass', 'data-opt-type': 'checkbox' })[k],
                          checked: true });
          const btn = wrap.children[0];
          if (!btn) throw new Error('no reset button was added');
          check('no inline onclick', !('onclick' in btn.attrs));
          let called = 0;
          window.clearReportOptionDefaults = function () { called++; };
          WD.actions._handlers.call(btn, { type: 'click', preventDefault(){}, stopPropagation(){} });
          eq('the click reaches clearReportOptionDefaults', called, 1);
        """)


class SmallerFixes(ReportCase):

    def test_group_by_colour_makes_one_group_per_colour(self):
        self.run_block(r"""
          const key = E('apGroupKey'), label = E('apGroupLabel');
          const aps = [{ color: '#6D6D6D' }, { color: '#6B6B6B' }, { color: '#ff0000' },
                       { color: '#FF0000' }, {}];
          const groups = {};
          aps.forEach(a => { const k = key(a, 'color'); groups[k] = label(k, 'color'); });
          eq('one group each for Gray, Red and Clear', Object.values(groups).sort(),
             ['Clear', 'Gray', 'Red']);
        """)

    def test_the_aim_sheet_sorts_numerically(self):
        self.run_block(r"""
          open();
          const html = render('aim', { inclOmni: false });
          const order = (html.match(/Zed-AP\d+/g) || []).filter((n, i, a) => a.indexOf(n) === i);
          eq('directional APs in numeric order', order, ['Zed-AP6', 'Zed-AP7', 'Zed-AP10']);
        """)


if __name__ == "__main__":
    unittest.main()
