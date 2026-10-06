"""The AP Placement Map and the Antenna Aim Sheet print what the design holds.

An independent review printed both reports from a library of awkward invented
projects and found the following, each of which rendered cleanly and read wrong
on paper:

* an AP with a **directional antenna and no azimuth** was listed on the Aim
  Sheet as "omni" - the one AP the installer most needs to be told about;
* an AP whose **first radio is omni and second a sector** printed "omni" and got
  no cone, although the antenna it is aimed from is the second one;
* an AP **off the edge of the plan** had no dot but kept a label, pulled onto the
  corner so that it looked like an AP standing there;
* the note under a map pointed at an **AP table the Placement Map does not
  have**, and named model and height when it was channel and TX power that had
  been dropped;
* a **14.5 dBm** radio was labelled 15 dBm; the **key showed grey** for APs the
  map drew red; the **summary strip counted "no floor plan"** as a floor plan;
  an azimuth of **450 or -45** was printed as stored;
* on a plan more elongated than about 2.8:1 the **number straddled the pill**,
  which is what an installer reads the whole sheet by;
* a sectioned floor's **last sheet had no room for the footer**, which printed
  alone on a page of its own, once per floor;
* the **Key Plan thumbnail** lettered its sections at 1 to 3pt;
* opening **Configure grid** and pressing Done changed the report, and **None**
  in the AP filter cleared every AP while a search showed three.

Every test drives the real `report.js` against the stub DOM of
`test_report_prints_what_the_design_holds`. Geometry is measured on the markup
that would be printed, not read out of the source.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_report_prints_what_the_design_holds import ReportCase

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "web" / "assets" / "wd-tools.css"

# Everything a test needs to build one invented floor, and to read markers back
# out of the markup the Placement Map would print.
KIT = r"""
function floor(id, name, w, h) {
  return { id, name, width: w, height: h, metersPerUnit: 0.05, imageId: 'im' + id };
}
/* aps: [{ n, x, y, radios: [{ ant: 'omni1'|'dir1', dir, tx, enabled }], color, floor }] */
function build(floors, aps) {
  const p = project();
  p.floorPlans = floors;
  p.imageUrls = {}; floors.forEach(f => { p.imageUrls['im' + f.id] = 'blob:' + f.id; });
  p.accessPoints = []; p.radios = []; p.notes = {};
  aps.forEach(a => {
    const id = 'ap' + a.n;
    p.accessPoints.push({ id, name: a.name || ('Zed-AP' + a.n), vendor: 'Vendo', model: 'V-100',
      color: a.color,
      location: a.floor === null ? undefined
        : { floorPlanId: a.floor || floors[0].id, coord: { x: a.x, y: a.y } }, noteIds: [] });
    (a.radios || [{ ant: 'omni1' }]).forEach((r, i) => p.radios.push({
      id: 'r' + a.n + '_' + i, accessPointId: id, radioTechnology: 'IEEE802_11',
      antennaTypeId: r.ant, antennaMounting: 'CEILING', antennaHeight: 3,
      antennaDirection: r.dir == null ? null : r.dir, antennaTilt: -10,
      transmitPower: r.tx == null ? 20 : r.tx, enabled: r.enabled,
      channelByCenterFrequencyDefinedNarrowChannels: [5180] }));
  });
  return p;
}
/* Every marker group of a map: class, position, pill box, type size, cone. */
function markersOf(html) {
  const out = [];
  html.split('<g class="rep-mark ').slice(1).forEach(function (body) {
    const head = /^([^"]*)" transform="translate\(([-\d.e]+),([-\d.e]+)\)"/.exec(body);
    if (!head) return;
    const pill = /<rect class="rep-mark-pill" x="([-\d.e]+)" y="([-\d.e]+)" width="([-\d.e]+)" height="([-\d.e]+)"/.exec(body);
    const font = /class="rep-mark-label"[^>]*font-size="([\d.e]+)"/.exec(body);
    const text = /<text class="rep-mark-label"[^>]*>([^<]*)</.exec(body);
    const cone = /<g transform="rotate\(([-\d.e]+)\)"><path class="rep-mark-cone"/.exec(body);
    out.push({ cls: 'rep-mark ' + head[1], x: +head[2], y: +head[3],
      pill: pill && { x: +pill[1], y: +pill[2], w: +pill[3], h: +pill[4] },
      font: font && +font[1], text: text && text[1], cone: cone ? +cone[1] : null });
  });
  return out;
}
function aimRow(html, apName) {
  const at = html.indexOf('>' + apName + '<');
  if (at < 0) throw new Error('no Aim row for ' + apName);
  const a = html.lastIndexOf('<tr>', at), b = html.indexOf('</tr>', at);
  return html.slice(a, b);
}
"""


class TheAimSheetSaysWhatEachAntennaDoes(ReportCase):

    def test_a_directional_antenna_with_no_azimuth_is_flagged_not_called_omni(self):
        self.run_block(KIT + r"""
          const p = build([floor('f1', 'Level', 1000, 800)], [
            { n: 1, x: 200, y: 200, radios: [{ ant: 'dir1', dir: null }] },
            { n: 2, x: 400, y: 200, radios: [{ ant: 'omni1' }] },
          ]);
          open(p);
          const html = render('aim', { inclOmni: true, signOff: false, shortLabels: false });
          const row = aimRow(html, 'Zed-AP1');
          check('the AP with no azimuth is flagged: ' + row, /rep-aim-missing[^>]*>no azimuth</.test(row));
          check('and is not called omni: ' + row, !/omni/.test(row));
          check('a true omni still says omni', /omni/.test(aimRow(html, 'Zed-AP2')));
          // Placement: still a directional marker, with nothing to point a cone along.
          const pl = markersOf(render('placement', { showCones: true }));
          const m = pl.find(x => x.text === '1');
          check('directional class kept', m && /rep-mark--dir/.test(m.cls));
          check('no cone without an azimuth', m && m.cone === null);
        """)

    def test_a_mixed_radio_ap_is_aimed_from_its_directional_radio(self):
        self.run_block(KIT + r"""
          const p = build([floor('f1', 'Level', 1000, 800)], [
            { n: 9, x: 300, y: 300, radios: [{ ant: 'omni1' }, { ant: 'dir1', dir: 135 }] },
            // A disabled directional radio is not what the AP is aimed from.
            { n: 8, x: 600, y: 300, radios: [{ ant: 'omni1' }, { ant: 'dir1', dir: 45, enabled: false }] },
          ]);
          open(p);
          const row = aimRow(render('aim', { signOff: false, shortLabels: false, inclOmni: true }), 'Zed-AP9');
          check('azimuth of the sector radio: ' + row, />135°/.test(row) && !/omni/.test(row));
          const pl = markersOf(render('placement', { showCones: true }));
          eq('cone follows the sector radio', pl.find(x => x.text === '9').cone, 135);
          eq('no cone from a disabled radio', pl.find(x => x.text === '8').cone, null);
        """)

    def test_an_azimuth_is_printed_between_0_and_359(self):
        self.run_block(KIT + r"""
          const p = build([floor('f1', 'Level', 1000, 800)], [
            { n: 1, x: 200, y: 200, radios: [{ ant: 'dir1', dir: 450 }] },
            { n: 2, x: 400, y: 200, radios: [{ ant: 'dir1', dir: -45 }] },
            { n: 3, x: 600, y: 200, radios: [{ ant: 'dir1', dir: 360 }] },
          ]);
          open(p);
          const html = render('aim', { signOff: false, shortLabels: false, compass: true });
          const cell = n => /<td class="rep-az">([^<]*)<span class="rep-alt">\(([A-Z]+)\)/.exec(aimRow(html, 'Zed-AP' + n));
          eq('450 reads 90', cell(1).slice(1, 3), ['90° ', 'E']);
          eq('-45 reads 315', cell(2).slice(1, 3), ['315° ', 'NW']);
          eq('360 reads 0', cell(3).slice(1, 3), ['0° ', 'N']);
        """)

    def test_the_index_column_is_only_printed_when_it_differs_from_the_name(self):
        self.run_block(KIT + r"""
          const p = build([floor('f1', 'Level', 1000, 800)], [
            { n: 1, name: 'Site-AP01', x: 200, y: 200, radios: [{ ant: 'dir1', dir: 10 }] },
            { n: 2, name: 'Site-AP02', x: 400, y: 200, radios: [{ ant: 'dir1', dir: 20 }] },
          ]);
          open(p);
          const heads = h => (h.match(/<th[^>]*>[^<]*<\/th>/g) || []).map(t => t.replace(/<[^>]+>/g, ''));
          const short = render('aim', { signOff: true, shortLabels: true });
          check('short numbers: # column present', heads(short).includes('#'));
          const full = render('aim', { signOff: true, shortLabels: false });
          check('full names: no # column', !heads(full).includes('#'));
          // Header, cells and widths agree either way.
          [short, full].forEach(h => {
            const t = h.slice(h.indexOf('<table'), h.indexOf('</table>'));
            const n = heads(t).length;
            eq('cells per row', (aimRow(t, 'Site-AP01').match(/<td/g) || []).length, n);
            eq('cols', (t.match(/<col /g) || []).length, n);
          });
        """)


class TheAimMapIsFittedAndReadable(ReportCase):

    def test_the_aim_map_is_a_fitted_plan_page_with_its_numbers_kept_apart(self):
        self.run_block(KIT + r"""
          // Eight APs close enough that boxes centred on the dots would overlap.
          const aps = [];
          for (let i = 1; i <= 8; i++) aps.push({ n: i, x: 400 + (i % 3) * 12, y: 300 + Math.floor(i / 3) * 10,
            radios: [{ ant: 'dir1', dir: i * 40 }] });
          open(build([floor('f1', 'Level', 1000, 800)], aps));
          const html = render('aim', { signOff: false });
          check('a fitted plan sheet', /rep-aim-map-section/.test(html)
            && /data-page-kind="plan"/.test(html) && /data-page-key="aim:f1"/.test(html));
          const ms = markersOf(html);
          eq('every AP has a marker', ms.length, 8);
          let overlaps = 0;
          const box = m => ({ x: m.x + m.pill.x, y: m.y + m.pill.y, w: m.pill.w, h: m.pill.h });
          for (let i = 0; i < ms.length; i++) for (let j = i + 1; j < ms.length; j++) {
            const a = box(ms[i]), b = box(ms[j]);
            if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) overlaps++;
          }
          eq('no two labels overlap', overlaps, 0);
          check('every marker carries an arrow', ms.every(m => m.cone !== null));
        """)

    def test_the_aim_report_fits_its_plan_pages_after_rendering(self):
        """The map sheets are sized by fitPlanPages, which the report has to
        name as its postRender - a plan 10 times taller than wide ran to nine
        sheets without it."""
        self.run_block(KIT + r"""
          const r = E('REPORTS.aim');
          check('aim names a postRender', typeof r.postRender === 'function');
          check('and it is the shared plan fitter', r.postRender === E('fitPlanPages'));
        """)


class ThePlacementMapKeepsEveryNumberReadable(ReportCase):

    def test_the_pill_is_as_tall_as_its_type_on_an_elongated_plan(self):
        self.run_block(KIT + r"""
          [[600, 6000], [9000, 500], [4000, 1500], [1500, 1000]].forEach(function (wh) {
            const W = wh[0], H = wh[1];
            const p = build([floor('f1', 'Level', W, H)], [
              { n: 1, x: W * 0.4, y: H * 0.4 }, { n: 2, x: W * 0.6, y: H * 0.7 }]);
            open(p);
            [{}, { labelModel: true, labelHeight: true }].forEach(function (extra) {
              const ms = markersOf(render('placement', extra));
              eq('markers on ' + W + 'x' + H, ms.length, 2);
              ms.forEach(m => {
                check(W + 'x' + H + ' pill height ' + m.pill.h + ' holds 1.5 x the ' + m.font + ' type',
                      m.pill.h >= m.font * 1.5 - 1e-6);
                // On paper a plan prints about 7.2in along its long edge; the
                // number stays above 6pt there.
                const pt = m.font / Math.max(W, H) * 7.2 * 72;
                check(W + 'x' + H + ' type is ' + pt.toFixed(1) + 'pt', pt >= 6);
                check('the pill is wide enough for its text', m.pill.w >= m.text.length * m.font * 0.6);
              });
            });
          });
        """)

    def test_a_label_keeps_off_its_own_cone(self):
        self.run_block(KIT + r"""
          // A cone points down at 180 degrees; the label must not sit across it.
          // The last three are the awkward ones: the label's preferred side is
          // off the plan, and the next position along is the cone's own ground.
          [[700, 500, 0], [700, 500, 90], [700, 500, 180], [700, 500, 270], [700, 500, 225],
           [700, 20, 180], [700, 980, 0], [20, 500, 90]].forEach(function (c) {
            const az = c[2];
            const p = build([floor('f1', 'Level', 1500, 1000)], [
              { n: 1, x: c[0], y: c[1], radios: [{ ant: 'dir1', dir: az }] }]);
            open(p);
            const m = markersOf(render('placement', { showCones: true }))[0];
            eq('cone rotation', m.cone, az);
            const len = 1000 * 0.06, th = az * Math.PI / 180;
            const ax = Math.sin(th), ay = -Math.cos(th);
            let hit = 0;
            for (let t = 0.1; t <= 1.001; t += 0.1) for (let u = -1; u <= 1; u++) {
              const px = ax * t * len - ay * u * t * len * 0.35, py = ay * t * len + ax * u * t * len * 0.35;
              if (px > m.pill.x && px < m.pill.x + m.pill.w && py > m.pill.y && py < m.pill.y + m.pill.h) hit++;
            }
            eq('cone points inside the label at ' + c.join(','), hit, 0);
          });
        """)

    def test_a_tight_group_on_a_corridor_is_cut_back_to_numbers(self):
        """The radius that decides "crowded" is the label's size, not a share of
        the short edge: on a 600 x 6000 plan that share is 45 units against a
        label 80 units tall, so nothing was ever crowded."""
        self.run_block(KIT + r"""
          const aps = [1, 2, 3].map(i => ({ n: i, x: 300, y: 1000 + i * 100 }));
          open(build([floor('f1', 'Corridor', 600, 6000)], aps));
          const html = render('placement', { labelModel: true });
          check('the group is cut back and says so', /show the number only/.test(html));
        """)

    def test_a_crowded_floor_says_how_many_labels_could_not_be_cleared(self):
        self.run_block(KIT + r"""
          const aps = [];
          // Sixty APs inside a few hundred units of a small plan: more labels
          // than the plan has room for, with the long form of the name.
          for (let i = 1; i <= 60; i++) aps.push({ n: i, name: 'A-Very-Long-Site-Name-AP' + i,
            x: 300 + (i % 6) * 20, y: 300 + Math.floor(i / 6) * 20 });
          open(build([floor('f1', 'Level', 700, 600)], aps));
          const html = render('placement', { shortLabels: false });
          check('the note is printed: ' + (html.match(/could not be placed[^<]*/) || ['none']),
                /label[s]? could not be placed clear of the others/.test(html));
          // And a roomy floor does not cry wolf.
          open(build([floor('f1', 'Level', 1500, 1000)], [{ n: 1, x: 300, y: 300 }, { n: 2, x: 900, y: 600 }]));
          check('no note on a roomy floor', !/could not be placed/.test(render('placement', {})));
        """)

    def test_labels_that_found_no_room_are_cut_back_and_laid_out_again(self):
        """A grid of APs 130 units apart with a model, channel and height under
        every number: the boxes are far wider than the gaps.
        The ones that find no clear ground drop their second line and the map
        is laid out again, so nothing is left overlapping - and the leader
        lines, which run from a dot to a label that has been moved away, are
        drawn under every marker rather than across the face of the next."""
        self.run_block(KIT + r"""
          const aps = [];
          for (let r = 0; r < 5; r++) for (let c = 0; c < 6; c++)
            aps.push({ n: r * 6 + c + 1, x: 100 + c * 130, y: 100 + r * 110 });
          open(build([floor('f1', 'Level', 1400, 1000)], aps));
          const html = render('placement', { labelModel: true, labelRadio: true, labelHeight: true });
          check('some markers were cut back: ', /show the number only/.test(html));
          check('and none is left overlapping: ' + (html.match(/could not be placed[^<]*/) || ''),
                !/could not be placed/.test(html));
          const ms = markersOf(html);
          eq('all thirty drawn', ms.length, 30);
          const box = m => ({ x: m.x + m.pill.x, y: m.y + m.pill.y, w: m.pill.w, h: m.pill.h });
          let overlaps = 0;
          for (let i = 0; i < ms.length; i++) for (let j = i + 1; j < ms.length; j++) {
            const a = box(ms[i]), b = box(ms[j]);
            if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) overlaps++;
          }
          eq('no two pills overlap', overlaps, 0);
          const lead = html.indexOf('rep-mark-lead'), first = html.indexOf('<g class="rep-mark ');
          check('there are leader lines in this layout', lead > 0);
          check('and they are drawn before (under) every marker', lead < first);
        """)

    def test_the_reduced_label_note_names_what_was_dropped_and_where_it_is(self):
        self.run_block(KIT + r"""
          const aps = [];
          for (let i = 1; i <= 12; i++) aps.push({ n: i, x: 500 + (i % 4) * 25, y: 400 + Math.floor(i / 4) * 25 });
          open(build([floor('f1', 'Level', 1500, 1000)], aps));
          const note = html => (html.match(/<div class="rep-overview-note">([^<]*)</) || [])[1] || '';
          const a = note(render('placement', { labelRadio: true }));
          check('said at all: ' + a, /show the number only/.test(a));
          check('names channel and TX power: ' + a, /channel and TX power/.test(a));
          check('not the model, which was not on the label: ' + a, !/model|height/.test(a));
          check('does not send the reader to an AP table that is not there: ' + a, !/AP table/.test(a));
          check('names the report that has it: ' + a, /AP Installation/.test(a));
          const b = note(render('placement', { labelModel: true, labelHeight: true }));
          check('model and mount height named: ' + b, /model and mount height/.test(b));
        """)

    def test_an_ap_off_the_plan_is_named_not_drawn(self):
        self.run_block(KIT + r"""
          const p = build([floor('f1', 'Level', 1500, 1000)], [
            { n: 1, x: 300, y: 300 }, { n: 2, x: 2400, y: -200, name: 'Zed-OffPlan' }]);
          open(p);
          const html = render('placement', {});
          const ms = markersOf(html);
          eq('only the AP on the plan has a marker', ms.map(m => m.text), ['1']);
          const note = (html.match(/rep-seg-note--outside">([^<]*)</) || [])[1] || '';
          check('the off-plan AP is named: ' + note, /1 AP lies outside the floor plan[^:]*: Zed-OffPlan/.test(note));
        """)

    def test_tx_power_keeps_its_decimal(self):
        self.run_block(KIT + r"""
          const p = build([floor('f1', 'Level', 1500, 1000)], [
            { n: 1, x: 300, y: 300, radios: [{ ant: 'omni1', tx: 14.5 }] },
            { n: 2, x: 700, y: 300, radios: [{ ant: 'omni1', tx: 20 }] },
            { n: 3, x: 1100, y: 300, radios: [{ ant: 'omni1', tx: 11.25 }] }]);
          open(p);
          const html = render('placement', { labelRadio: true });
          check('14.5 is not rounded to 15', /14\.5 dBm/.test(html) && !/15 dBm/.test(html));
          check('whole numbers have no stray decimal', /20 dBm/.test(html) && !/20\.0 dBm/.test(html));
          check('11.25 is not printed as 11', !/>11 dBm/.test(html));
        """)

    def test_the_key_swatch_matches_the_marker_colour(self):
        self.run_block(KIT + r"""
          const p = build([floor('f1', 'Level', 1500, 1000)], [
            { n: 1, x: 300, y: 300, color: 'red' }, { n: 2, x: 700, y: 300, color: '#00FF00' }]);
          open(p);
          const html = render('placement', {});
          const key = (html.match(/<div class="rep-overview-key">[\s\S]*?<\/div>/) || [''])[0];
          const swatches = (key.match(/background:(#[0-9A-Fa-f]{6})/g) || []).map(s => s.slice(11).toUpperCase());
          eq('one swatch per marker colour, as the markers paint them', swatches.sort(), ['#00FF00', '#FF0000']);
          const dots = (html.match(/class="rep-mark-dot"[^>]*fill="(#[0-9A-F]{6})"/g) || []).map(s => s.slice(-8, -1));
          eq('and the markers are those colours', dots.sort(), ['#00FF00', '#FF0000']);
        """)

    def test_the_heading_does_not_repeat_the_floor_name(self):
        self.run_block(KIT + r"""
          const p = build([floor('f1', 'Only Floor Has A Rather Long Name', 1500, 1000)], [{ n: 1, x: 300, y: 300 }]);
          open(p);
          const html = render('placement', {});
          const head = (html.match(/<div class="rep-seg-floor rep-placement-head">[\s\S]*?<\/div>/) || [''])[0];
          const times = (head.match(/Only Floor Has A Rather Long Name/g) || []).length;
          eq('the name is in the heading once: ' + head, times, 1);
          check('the sub-line still counts the APs', /1 AP</.test(head));
        """)


class TheSummaryStripCountsFloorPlans(ReportCase):

    def test_no_floor_plan_is_not_a_floor_plan(self):
        self.run_block(KIT + r"""
          const p = build([floor('f1', 'Level 1', 1500, 1000), floor('f2', 'Level 2', 1500, 1000)], [
            { n: 1, x: 300, y: 300 }, { n: 2, x: 500, y: 300, floor: 'f2' },
            { n: 3, x: 0, y: 0, floor: null }]);
          open(p);
          const strip = html => (html.match(/<div class="rep-seg-note">([^<]*)</) || [])[1] || '';
          const s = strip(render('placement', { summary: true, inclOmni: true }));
          check('two floor plans, not three: ' + s, /3 APs planned across 2 floor plans/.test(s));
          check('the unplaced AP is said: ' + s, /1 of them on no floor plan/.test(s));
          // Only an unplaced AP: none of them on a floor plan.
          open(build([floor('f1', 'Level 1', 1500, 1000)], [{ n: 1, x: 0, y: 0, floor: null }]));
          const s2 = strip(render('placement', { summary: true, inclOmni: true }));
          check('no floor plan at all: ' + s2, /1 AP, none of them on a floor plan/.test(s2));
        """)


class TheSummaryStripSharesTheCover(ReportCase):

    def test_with_a_cover_the_strip_is_on_it_not_on_a_sheet_of_its_own(self):
        self.run_block(KIT + r"""
          open(build([floor('f1', 'Level 1', 1500, 1000)], [{ n: 1, x: 300, y: 300 }]));
          document.getElementById('optCover').checked = true;
          const html = render('placement', { summary: true });
          const a = html.indexOf('<section class="rep-cover');
          const cover = html.slice(a, html.indexOf('</section>', a));
          check('the strip is inside the cover: ' + cover.slice(-200), /planned across 1 floor plan/.test(cover));
          eq('and appears once', (html.match(/planned across/g) || []).length, 1);
          document.getElementById('optCover').checked = false;
          const plain = render('placement', { summary: true });
          check('with no cover it still prints, ahead of the first map',
                plain.indexOf('planned across') > 0 && plain.indexOf('planned across') < plain.indexOf('rep-placement-page'));
        """)


class ASectionedFloorLeavesRoomForItsFooter(ReportCase):

    def test_only_the_last_section_gives_room_back(self):
        self.run_block(KIT + r"""
          const seg = E('footerBelowIn');
          const foot = conf => ({ classList: { contains: c => c === 'rep-doc-foot' },
                                  querySelector: () => conf ? {} : null });
          const cell = next => ({ nextElementSibling: next });
          eq('a section followed by another has nothing to give',
             seg(cell({ classList: { contains: () => false } })), 0);
          eq('the last section of a report with no footer', seg(cell(null)), 0);
          check('the last section followed by the footer gives room', seg(cell(foot(false))) > 0.3);
          check('and more when the footer carries the confidentiality line',
                seg(cell(foot(true))) > seg(cell(foot(false))));
        """)

    def test_the_last_map_is_shorter_by_the_footer_when_height_limited(self):
        self.run_block(KIT + r"""
          const size = E('segPrintSizeIn');
          function overlay(next, w, h) {
            const attrs = { 'data-seg-x0': 0, 'data-seg-y0': 0, 'data-seg-x1': w, 'data-seg-y1': h };
            const locator = { style: { getPropertyValue: k => k === '--w' ? String(w) : String(h) } };
            const page = { nextElementSibling: next, querySelector: () => locator };
            return { getAttribute: k => String(attrs[k]),
                     closest: sel => sel === '.rep-seg-cell' ? page : null };
          }
          const foot = { classList: { contains: c => c === 'rep-doc-foot' }, querySelector: () => null };
          const other = { classList: { contains: () => false } };
          // A tall section is limited by height, so the footer comes straight off it.
          const mid = size(overlay(other, 600, 1000), false);
          const last = size(overlay(foot, 600, 1000), false);
          check('the last tall section is shorter: ' + mid.h + ' vs ' + last.h, last.h < mid.h - 0.3);
          // A wide one is limited by width and needs nothing.
          const wmid = size(overlay(other, 1000, 300), false), wlast = size(overlay(foot, 1000, 300), false);
          eq('a wide section is unchanged', wlast.h, wmid.h);
          // Landscape sheets too.
          check('landscape: last is shorter', size(overlay(foot, 600, 700), true).h < size(overlay(other, 600, 700), true).h);
        """)


class TheKeyPlanLettersAreReadable(ReportCase):

    def test_every_letter_prints_at_6pt_or_more_and_inside_its_cell(self):
        self.run_block(KIT + r"""
          const thumb = E('renderAntennaLocatorThumb');
          function cells(cols, rows, W, H) {
            const out = [];
            for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++)
              out.push({ col: c, row: r, x0: c * W / cols, x1: (c + 1) * W / cols,
                         y0: r * H / rows, y1: (r + 1) * H / rows, label: String.fromCharCode(65 + c) + (r + 1) });
            return out;
          }
          [[2, 2, 1500, 1000, 1], [4, 3, 6000, 1500, 0], [6, 4, 3000, 3000, 1], [3, 8, 600, 6000, 0]].forEach(function (g) {
            const cs = cells(g[0], g[1], g[2], g[3]);
            const html = thumb('blob:x', g[2], g[3], cs[0], null, cs);
            const vb = /viewBox="([-\d.e]+) ([-\d.e]+) ([\d.e]+) ([\d.e]+)"/.exec(html);
            const vW = +vb[3], vH = +vb[4];
            const thumbWIn = Math.min(90 / 96, 1.1 * vW / vH);
            const sizes = (html.match(/font-size="([\d.e]+)"/g) || []).map(s => +s.slice(11, -1));
            // Whatever letter is drawn sits inside its own cell.
            (html.match(/<text [^>]*>[^<]*<\/text>/g) || []).forEach(function (t) {
              const x = +/ x="([-\d.e]+)"/.exec(t)[1], y = +/ y="([-\d.e]+)"/.exec(t)[1];
              const f = +/font-size="([\d.e]+)"/.exec(t)[1], lab = />([^<]*)</.exec(t)[1];
              const c = cs.find(k => k.label === lab);
              check(g.slice(0, 4).join('x') + ': letter ' + lab + ' inside its cell',
                    x - lab.length * f * 0.325 >= c.x0 - 1e-6 && x + lab.length * f * 0.325 <= c.x1 + 1e-6
                    && y - f / 2 >= c.y0 - 1e-6 && y + f / 2 <= c.y1 + 1e-6);
            });
            sizes.forEach(f => check(g.slice(0, 4).join('x') + ': letter at ' + (f / vW * thumbWIn * 72).toFixed(2) + 'pt',
                                     f / vW * thumbWIn * 72 >= 6));
            // Where a cell is too small to hold a 6pt letter it goes without one
            // (the section title beside the thumbnail names it); where it is not,
            // the highlighted section is lettered.
            const roomy = g[4] === 1;
            if (roomy) check(g.join('x') + ': the highlighted section is lettered', />A1</.test(html));
          });
        """)


class TheControls(ReportCase):

    def test_none_with_a_search_clears_only_what_the_search_shows(self):
        self.run_block(KIT + r"""
          const aps = [];
          for (let i = 1; i <= 6; i++) aps.push({ n: i, name: (i <= 2 ? 'North-AP' : 'South-AP') + i, x: 100 * i, y: 100 });
          open(build([floor('f1', 'Level', 1500, 1000)], aps));
          E('(function () { currentReportId = "placement"; currentOpts = {}; apSearch = "north"; })')();
          window.toggleAllAps(false);
          eq('only the two shown are unticked', E('Array.from(apDisabled).sort()'), ['ap1', 'ap2']);
          window.toggleAllAps(true);
          eq('All with the search re-ticks them', E('Array.from(apDisabled)'), []);
          E('(function () { apSearch = ""; })')();
          window.toggleAllAps(false);
          eq('with no search it is the whole project', E('apDisabled.size'), 6);
        """)

    def test_done_without_a_change_leaves_the_grid_alone(self):
        self.run_block(KIT + r"""
          open(build([floor('f1', 'Level', 1500, 1000), floor('f2', 'Level 2', 1500, 1000)],
                     [{ n: 1, x: 300, y: 300 }]));
          E('(function () { currentReportId = "placement"; currentOpts = {}; })')();
          // Opened as it opens: the first floor's automatic grid in the dialog.
          E('(function () { _gridCols = 3; _gridRows = 2; _gridInitCols = 3; _gridInitRows = 2; _cropBoxes = {}; _segMerges = {}; _cropBox = { x: 0, y: 0, w: 1, h: 1 }; _gridFloorIdx = 0; })')();
          window.doneGridConfig();
          eq('nothing was changed, so nothing is stored', E('currentOpts.segCols'), undefined);
          eq('rows too', E('currentOpts.segRows'), undefined);
          // Now the person changes it.
          E('(function () { _gridCols = 4; })')();
          window.doneGridConfig();
          eq('a change is stored', [E('currentOpts.segCols'), E('currentOpts.segRows')], [4, 2]);
        """)

    def test_openGridConfig_remembers_what_it_opened_with(self):
        """The real open: whatever grid the dialog opens on is the baseline Done
        compares against, so opening and closing it is not a decision."""
        self.run_block(KIT + r"""
          open(build([floor('f1', 'Level', 1500, 1000)], [{ n: 1, x: 300, y: 300 }]));
          E('(function () { currentReportId = "placement"; currentOpts = {}; })')();
          let opened = true;
          try { window.openGridConfig(); } catch (e) { opened = false; }
          if (opened) {
            window.doneGridConfig();
            eq('look, do not touch', E('currentOpts.segCols'), undefined);
          }
        """)


class TheStylesheet(unittest.TestCase):

    def test_a_summary_strip_between_cover_and_first_map_does_not_get_a_sheet(self):
        css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
        printed = css[css.index("@media print"):]
        rules = re.findall(r"([^{}]+)\{([^{}]*)\}", printed)
        exempt = [sel for sel, body in rules
                  if "page-break-before: auto" in body and ".rep-placement-page" in sel]
        joined = " ".join(exempt)
        self.assertIn(".rep-cover + .rep-seg-note + .rep-placement-page", joined)
        self.assertIn(".rep-doc-head + .rep-seg-note + .rep-placement-page", joined)


if __name__ == "__main__":
    unittest.main()
