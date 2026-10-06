"""The Change / Audit report says what changed, and only what is true.

A review of the report, driven through the real page with deliberately
awkward pairs of files, found the same family over and over: the page
printed a confident sentence that the comparison behind it did not earn.

* **"Any distance at all" reported every AP as moved**, by 0.0 ft: the
  threshold is 0 and 0 >= 0.
* **Channel, width, transmit power and the radio set were never compared**,
  yet a pair in which every radio had changed channel printed "Nothing
  changed ... same hardware".
* **A move on a floor with no scale vanished**, because a missing scale meant
  no move was ever reported.
* **A plan re-imported at twice the resolution** (coordinates doubled,
  metres-per-pixel halved) reported most of the APs as moved by up to 76 ft
  and a 810 px "crop" over a building nobody had touched.
* **A plan shifted as a whole, at the same size**, reported every AP as moved
  with no hint that it was one shift rather than thirty decisions.
* **Azimuth, tilt and height going from unset to set** (or back) were skipped,
  because the comparison needed a number on both sides.
* **Floors added, removed or renamed** were computed and never printed.
* **Every small table printed on its own sheet**, so 34 APs made eight pages.

Every test runs the real ``report.js`` against a stub DOM, and each fails
against the code it replaced.
"""
from __future__ import annotations

import unittest

from tests.test_report_prints_what_the_design_holds import ReportCase

BUILD = r"""
function fl(id, name, w, h, mpu) {
  return { id, name, width: w == null ? 1000 : w, height: h == null ? 800 : h,
           metersPerUnit: mpu === undefined ? 0.05 : mpu, imageId: 'im-' + id };
}
function apx(id, name, floor, x, y, extra) {
  return Object.assign({ id, name, vendor: 'Vendo', model: 'V-100', noteIds: [],
    location: floor === null ? {} : { floorPlanId: floor, coord: { x, y } } }, extra || {});
}
function rad(apId, extra) {
  return Object.assign({ id: 'r-' + apId, accessPointId: apId, radioTechnology: 'IEEE802_11',
    antennaTypeId: 'omni1', antennaMounting: 'CEILING', antennaHeight: 3,
    antennaDirection: null, transmitPower: 15,
    channelByCenterFrequencyDefinedNarrowChannels: [5180] }, extra || {});
}
function mk(floors, aps, radios) {
  const imageUrls = {};
  floors.forEach(f => { imageUrls[f.imageId] = 'blob:' + f.id; });
  return { accessPoints: aps, radios: radios, floorPlans: floors, images: {}, imageUrls,
    antennas: { omni1: { id: 'omni1', name: 'Omni Sample', directional: false } },
    buildings: {}, buildingFloors: {}, notes: {}, measurements: [], measuredRadios: [],
    surveys: [], projectName: 'Invented' };
}
// Eight APs on one floor, in a grid, each with one radio.
function grid(floorId, n, dx, dy) {
  const aps = [], rs = [];
  for (let i = 0; i < n; i++) {
    const id = 'a' + i;
    aps.push(apx(id, 'AP-' + (101 + i), floorId, 100 + (i % 4) * 200 + (dx || 0), 150 + Math.floor(i / 4) * 300 + (dy || 0)));
    rs.push(rad(id));
  }
  return { aps, rs };
}
function cmp(b, a, thr) { return E('WDCompare').compare(b, a, { threshold: thr }); }
function kinds(rec) { return rec.changes.map(c => c.kind).sort(); }
function auditHtml(before, after, opts) {
  E('(function (b, a) { baseline = b; baselineName = "before.esx"; baselineError = "";'
    + ' proj = a; fileName = "after.esx"; })')(before, after);
  return render('audit', Object.assign({ overlay: false }, opts || {}));
}
function text(html) {
  return html.replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"')
             .replace(/\s+/g, ' ').trim();
}
"""


class AnyDistanceDoesNotMeanEveryAp(ReportCase):

    def test_a_file_against_itself_has_no_moves_at_threshold_zero(self):
        self.run_block(BUILD + r"""
          const F = [fl('f1', 'Level 1')];
          const g = grid('f1', 8);
          const p = mk(F, g.aps, g.rs);
          const r = cmp(p, p, 0);
          eq('nothing changed', r.changed.length, 0);
          eq('all unchanged', r.unchanged.length, 8);
          const html = auditHtml(p, p, { moveThreshold: '0' });
          check('and the page says nothing changed', /Nothing changed/.test(text(html)));
          check('no zero-length move is printed: ' + text(html).slice(0, 300), !/Moved 0\.0/.test(text(html)));
        """)

    def test_a_real_sub_threshold_move_still_counts_at_zero(self):
        self.run_block(BUILD + r"""
          const F = [fl('f1', 'Level 1')];
          const g = grid('f1', 4);
          const after = grid('f1', 4);
          after.aps[1].location.coord.x += 2;                  // 0.1 m at 0.05 m/px
          const r = cmp(mk(F, g.aps, g.rs), mk(F, after.aps, after.rs), 0);
          eq('exactly the one that moved', r.changed.map(c => c.after.name), ['AP-102']);
        """)


class RadioSettingsAreCompared(ReportCase):

    def pair(self):
        return BUILD + r"""
          const F = [fl('f1', 'Level 1')];
          const b = grid('f1', 6), a = grid('f1', 6);
          const before = mk(F, b.aps, b.rs), after = mk(F, a.aps, a.rs);
        """

    def test_channel_width_and_power_are_changes(self):
        self.run_block(self.pair() + r"""
          a.rs[0].channelByCenterFrequencyDefinedNarrowChannels = [5745];     // 36 -> 149
          a.rs[1].channelByCenterFrequencyDefinedNarrowChannels = [5180, 5200, 5220, 5240]; // 36 -> 36/80
          a.rs[2].transmitPower = 5;
          a.rs[3].channelByCenterFrequencyDefinedNarrowChannels = [5745, 5765];
          const r = cmp(before, after, 0.5);
          eq('channel', kinds(r.changed.find(c => c.after.name === 'AP-101')), ['channel']);
          eq('width only: the lowest channel is the same',
             kinds(r.changed.find(c => c.after.name === 'AP-102')), ['width']);
          eq('power', kinds(r.changed.find(c => c.after.name === 'AP-103')), ['power']);
          eq('channel and width together',
             kinds(r.changed.find(c => c.after.name === 'AP-104')), ['channel', 'width']);
          eq('the other two are untouched', r.unchanged.length, 2);
          const t = text(auditHtml(before, after));
          check('the row names the channels: ' + t, /Channel 5 GHz: 36 → 149/.test(t));
          check('and the bonded width', /Width 5 GHz: 20 → 80 MHz/.test(t));
          check('and the power', /TX power 5 GHz: 15 dBm → 5 dBm/.test(t));
          check('so it can no longer claim nothing changed', !/Nothing changed/.test(t));
        """)

    def test_a_radio_added_removed_or_switched_off_is_a_change(self):
        self.run_block(self.pair() + r"""
          a.rs.push(rad('a0', { id: 'r-a0-24', channelByCenterFrequencyDefinedNarrowChannels: [2437] }));   // added
          b.rs.push(rad('a1', { id: 'r-a1-24', channelByCenterFrequencyDefinedNarrowChannels: [2412] }));   // removed
          a.rs[2].enabled = false;                                                                           // switched off
          const r = cmp(before, after, 0.5);
          const radio = n => r.changed.find(c => c.after.name === n).changes.filter(c => c.kind === 'radio');
          eq('added', radio('AP-101').map(c => [c.action, c.band]), [['added', '2.4 GHz']]);
          eq('removed', radio('AP-102').map(c => [c.action, c.band]), [['removed', '2.4 GHz']]);
          eq('disabled', radio('AP-103').map(c => c.action), ['disabled']);
          const t = text(auditHtml(before, after));
          check('printed as words: ' + t, /Radio 2\.4 GHz added/.test(t) && /Radio 2\.4 GHz removed/.test(t)
                && /Radio 5 GHz disabled/.test(t));
        """)

    def test_a_radio_turned_off_is_not_also_reported_as_a_channel_change(self):
        self.run_block(self.pair() + r"""
          a.rs[0].enabled = false;
          a.rs[0].channelByCenterFrequencyDefinedNarrowChannels = [5745];
          const rec = cmp(before, after, 0.5).changed.find(c => c.after.name === 'AP-101');
          eq('only the switch is said', kinds(rec).filter(k => k === 'channel' || k === 'radio'), ['radio']);
        """)


class AMoveWithNoScaleIsNotDropped(ReportCase):

    def test_it_is_measured_in_pixels_and_the_page_says_so(self):
        self.run_block(BUILD + r"""
          const F = [fl('f1', 'Level 1'), fl('f2', 'No Scale', 1000, 800, null)];
          const bAps = [apx('a1', 'AP-1', 'f1', 100, 100), apx('s1', 'AP-S1', 'f2', 100, 100),
                        apx('s2', 'AP-S2', 'f2', 300, 300), apx('s3', 'AP-S3', 'f2', 500, 500)];
          const aAps = [apx('a1', 'AP-1', 'f1', 100, 100), apx('s1', 'AP-S1', 'f2', 600, 100),
                        apx('s2', 'AP-S2', 'f2', 304, 300), apx('s3', 'AP-S3', 'f2', 500, 500)];
          const rs = aps => aps.map(a => rad(a.id));
          const before = mk(F, bAps, rs(bAps)), after = mk(F, aAps, rs(aAps));
          const r = cmp(before, after, 0.5);
          eq('the 500 px move is reported', r.changed.map(c => c.after.name), ['AP-S1']);
          eq('it is in pixels', [r.changed[0].changes[0].metres, Math.round(r.changed[0].changes[0].px)], [null, 500]);
          eq('the 4 px nudge is below the pixel threshold', r.unchanged.length, 3);
          eq('the floor is named', r.noScaleFloors.map(n => n.name), ['No Scale']);
          const t = text(auditHtml(before, after));
          check('the row says px: ' + t, /Moved 500 px \(no scale\)/.test(t));
          check('and the page says how it measured: ' + t, /No Scale has no scale set/.test(t)
                && /10 px or more/.test(t));
        """)


class AReImportedPlanIsNotAThousandMoves(ReportCase):

    def test_doubled_coordinates_and_half_the_scale_move_nothing(self):
        self.run_block(BUILD + r"""
          const b = grid('f1', 8);
          const a = grid('f1', 8);
          a.aps.forEach(x => { x.location.coord.x *= 2; x.location.coord.y *= 2; });
          const before = mk([fl('f1', 'Level 1', 1000, 800, 0.05)], b.aps, b.rs);
          const after = mk([fl('f1', 'Level 1', 2000, 1600, 0.025)], a.aps, a.rs);
          let r = cmp(before, after, 0.5);
          eq('nothing moved', r.changed.length, 0);
          eq('the floor is said to be re-scaled', r.floorNotes.map(n => n.scale), [2]);
          check('and not as a huge crop: ' + JSON.stringify(r.floorNotes[0]),
                Math.abs(r.floorNotes[0].dx) < 1 && Math.abs(r.floorNotes[0].dy) < 1);
          // One AP really moved 3 m (120 px at 0.025 m/px) - it must survive.
          a.aps[5].location.coord.x += 120;
          r = cmp(before, mk([fl('f1', 'Level 1', 2000, 1600, 0.025)], a.aps, a.rs), 0.5);
          eq('only the real move survives', r.changed.map(c => c.after.name), ['AP-106']);
          check('measured in metres: ' + r.changed[0].changes[0].metres,
                Math.abs(r.changed[0].changes[0].metres - 3) < 0.01);
          const t = text(auditHtml(before, mk([fl('f1', 'Level 1', 2000, 1600, 0.025)], a.aps, a.rs)));
          check('the page names the re-scale: ' + t, /re-cropped or re-scaled/.test(t) && /scaled ×2/.test(t));
        """)

    def test_a_rescale_with_too_few_aps_to_measure_a_shift_still_applies_the_scale(self):
        self.run_block(BUILD + r"""
          const b = grid('f1', 2), a = grid('f1', 2);
          a.aps.forEach(x => { x.location.coord.x *= 2; x.location.coord.y *= 2; });
          const r = cmp(mk([fl('f1', 'L1', 1000, 800, 0.05)], b.aps, b.rs),
                        mk([fl('f1', 'L1', 2000, 1600, 0.025)], a.aps, a.rs), 0.5);
          eq('two APs, known scale: nothing moved', r.changed.length, 0);
        """)


class AWholePlanShiftIsSaidNotHidden(ReportCase):

    def test_the_same_vector_on_most_aps_is_named_and_the_moves_stay_listed(self):
        self.run_block(BUILD + r"""
          const F = [fl('f1', 'Level 1')];
          const b = grid('f1', 8), a = grid('f1', 8, 146, 0);       // 146 px = 7.3 m
          const before = mk(F, b.aps, b.rs), after = mk(F, a.aps, a.rs);
          const r = cmp(before, after, 0.5);
          eq('every AP is still a move', r.changed.length, 8);
          eq('one floor is flagged', r.uniformShifts.map(u => [u.name, u.count, u.total]), [['Level 1', 8, 8]]);
          check('by the shared distance: ' + r.uniformShifts[0].metres, Math.abs(r.uniformShifts[0].metres - 7.3) < 0.01);
          const t = text(auditHtml(before, after));
          check('the page says so: ' + t, /Many access points moved together/.test(t)
                && /8 of 8 access points on Level 1 moved by the same/.test(t));
          check('and the rows are still there', (t.match(/Moved 2[34]\.\d ft/g) || []).length === 8);
        """)

    def test_independent_moves_are_not_called_a_shift(self):
        self.run_block(BUILD + r"""
          const F = [fl('f1', 'Level 1')];
          const b = grid('f1', 8), a = grid('f1', 8);
          const dirs = [[100, 0], [0, 120], [-90, 0], [0, -150], [160, 60], [-70, -80], [30, 200], [-200, 20]];
          a.aps.forEach((x, i) => { x.location.coord.x += dirs[i][0]; x.location.coord.y += dirs[i][1]; });
          const r = cmp(mk(F, b.aps, b.rs), mk(F, a.aps, a.rs), 0.5);
          eq('eight moves', r.changed.length, 8);
          eq('no shared vector', r.uniformShifts.length, 0);
        """)

    def test_a_genuine_crop_is_still_compensated_and_not_flagged_twice(self):
        self.run_block(BUILD + r"""
          const b = grid('f1', 8), a = grid('f1', 8, -150, -150);
          const r = cmp(mk([fl('f1', 'L1', 1000, 800)], b.aps, b.rs),
                        mk([fl('f1', 'L1', 700, 500)], a.aps, a.rs), 0.5);
          eq('the crop is taken out', r.changed.length, 0);
          eq('and reported as a crop', r.floorNotes.length, 1);
          eq('not as an unexplained shift', r.uniformShifts.length, 0);
        """)


class SetAndUnsetAreChanges(ReportCase):

    def test_azimuth_tilt_and_height_from_nothing_to_something(self):
        self.run_block(BUILD + r"""
          const F = [fl('f1', 'Level 1')];
          const b = grid('f1', 3), a = grid('f1', 3);
          a.rs[0].antennaDirection = 45;                         // unset -> set
          b.rs[1].antennaTilt = -10;  a.rs[1].antennaTilt = null; // set -> unset
          b.rs[2].antennaHeight = null; a.rs[2].antennaHeight = 3.5;
          const before = mk(F, b.aps, b.rs), after = mk(F, a.aps, a.rs);
          const r = cmp(before, after, 0.5);
          const k = n => kinds(r.changed.find(c => c.after.name === n));
          eq('azimuth', k('AP-101'), ['azimuth']);
          eq('tilt', k('AP-102'), ['tilt']);
          eq('height', k('AP-103'), ['height']);
          const t = text(auditHtml(before, after));
          check('set is said: ' + t, /Azimuth set 45°/.test(t));
          check('unset is said with what it was: ' + t, /Tilt unset \(was -10°\)/.test(t));
          check('height set: ' + t, /Height set 11\.5 ft/.test(t));
        """)

    def test_an_ap_that_gained_a_radio_is_one_change_not_three(self):
        self.run_block(BUILD + r"""
          const F = [fl('f1', 'Level 1')];
          const b = grid('f1', 2), a = grid('f1', 2);
          b.rs.splice(0, 1);                                      // AP-101 had no radio before
          a.rs[0].antennaDirection = 90;
          const r = cmp(mk(F, b.aps, b.rs), mk(F, a.aps, a.rs), 0.5);
          const rec = r.changed.find(c => c.after.name === 'AP-101');
          check('no azimuth/tilt/height noise beside the added radio: ' + kinds(rec),
                kinds(rec).every(k => k !== 'azimuth' && k !== 'tilt' && k !== 'height'));
          check('the radio is said', kinds(rec).includes('radio'));
        """)


class FloorsThatCameAndWent(ReportCase):

    def test_added_removed_and_renamed_floors_are_printed(self):
        self.run_block(BUILD + r"""
          const bF = [fl('f1', 'Ground'), fl('f2', 'Mezzanine'), fl('f3', 'Roof')];
          const aF = [fl('f1', 'Ground Floor'), fl('f2', 'Mezzanine'), fl('f4', 'Annex')];
          const b = grid('f1', 4), a = grid('f1', 4);
          const bx = apx('m1', 'AP-M1', 'f3', 100, 100), ax = apx('n1', 'AP-N1', 'f4', 100, 100);
          const before = mk(bF, b.aps.concat([bx]), b.rs.concat([rad('m1')]));
          const after = mk(aF, a.aps.concat([ax]), a.rs.concat([rad('n1')]));
          const html = auditHtml(before, after);
          const t = text(html);
          check('the section is there: ' + t, /Floor plans changed \(3\)/.test(t));
          check('added with what is on it', /Added Annex 1 access point on it now/.test(t));
          check('removed with what was on it', /Removed Roof 1 access point were on it/.test(t));
          check('renamed with the old name', /Renamed Ground Floor was “Ground”/.test(t));
          check('and it is not the empty-result page', !/Nothing changed/.test(t));
        """)

    def test_a_pair_that_differs_only_in_a_floor_is_not_declared_unchanged(self):
        self.run_block(BUILD + r"""
          const b = grid('f1', 2), a = grid('f1', 2);
          const before = mk([fl('f1', 'Ground')], b.aps, b.rs);
          const after = mk([fl('f1', 'Ground'), fl('f2', 'Annex')], a.aps, a.rs);
          check('floor added: not "Nothing changed"', !/Nothing changed/.test(text(auditHtml(before, after))));
        """)


class TheTablesFlowLikeTheDesignReview(ReportCase):

    def test_every_table_section_flows_and_the_plan_sheets_do_not(self):
        self.run_block(BUILD + r"""
          const F = [fl('f1', 'Level 1')];
          const b = grid('f1', 8), a = grid('f1', 8);
          a.aps[0].location.coord.x += 100;
          a.aps.push(apx('new', 'AP-NEW', 'f1', 900, 700)); a.rs.push(rad('new'));
          b.aps.push(apx('old', 'AP-OLD', 'f1', 800, 700)); b.rs.push(rad('old'));
          const html = auditHtml(mk(F, b.aps, b.rs), mk(F, a.aps, a.rs), { overlay: true });
          const sections = html.match(/<section class="[^"]*"/g) || [];
          const titles = ['What is being compared', 'Before and after', 'Changed (', 'Added (', 'Removed ('];
          titles.forEach(ti => {
            const at = html.indexOf(ti);
            check(ti + ' is there', at >= 0);
            const open = html.lastIndexOf('<section', at);
            check(ti + ' flows: ' + html.slice(open, open + 60), /rep-dr-flow/.test(html.slice(open, open + 60)));
          });
          check('the overlay sheet exists', html.indexOf('data-page-kind="plan"') >= 0);
          const planOpen = html.slice(html.lastIndexOf('<section', html.indexOf('data-page-kind="plan"')));
          check('and does not flow, so it keeps its own sheet', !/rep-dr-flow/.test(planOpen.slice(0, 120)));
        """)
