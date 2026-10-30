"""The Report can be run for some of a project's floors.

A building is occupied a floor at a time, so one project holds plans for floors
that are live and floors that were surveyed for another phase. The Configure
step has a **Floors to include** card; every report follows it, except the
Change / Audit report, whose two files' floors are paired by name.

These render the **real** reports from an invented three-floor project and read
the markup that would be printed, and they drive the card's controls by taking
each handler and argument out of the markup the card rendered, so a control
that renders but calls nothing fails here.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import test_report_prints_what_the_design_holds as base  # noqa: E402
from delegated import DELEGATED_JS  # noqa: E402

# Everything the checks share: an invented project with a third floor that
# holds two APs, two surveys, and one device seen on each of two floors.
HELPERS = r"""
function threeFloors() {
  const p = project();
  p.floorPlans.push({ id: 'fC', name: 'Roof Sample', width: 1000, height: 800,
    metersPerUnit: 0.05, imageId: 'imC' });
  p.imageUrls.imC = 'blob:c';
  ['13', '14'].forEach(function (n, i) {
    const id = 'ap' + n;
    p.accessPoints.push({ id, name: 'Zed-AP' + n, vendor: 'Vendo', model: 'V-100',
      location: { floorPlanId: 'fC', coord: { x: 100 + i * 200, y: 100 } }, noteIds: [] });
    p.radios.push({ id: 'r' + n, accessPointId: id, radioTechnology: 'IEEE802_11',
      antennaTypeId: 'omni1', antennaMounting: 'CEILING', antennaHeight: 3,
      antennaDirection: null, transmitPower: 20,
      channelByCenterFrequencyDefinedNarrowChannels: [5180] });
  });
  p.measurements = [
    { id: 'm1', ssid: 'Alpha iPhone', mac: 'aa:aa:aa:aa:aa:01',
      channelByCenterFrequencyDefinedNarrowChannels: [5180] },
    { id: 'm2', ssid: 'Bravo iPhone', mac: 'aa:aa:aa:aa:aa:02',
      channelByCenterFrequencyDefinedNarrowChannels: [5180] },
  ];
  p.surveys = [
    { id: 's1', floorPlanId: 'fA', routePoints: [], wifiTracks: [{ accessPointMeasurementIds: ['m1'] }] },
    { id: 's2', floorPlanId: 'fB', routePoints: [], wifiTracks: [{ accessPointMeasurementIds: ['m2'] }] },
  ];
  return p;
}
function floorsOff(list) { E('(function (l) { floorOff = new Set(l); })')(list); }
function draw() { E('renderFloorFilter()'); return els.floorFilterList.innerHTML; }
// The handler and argument a control's markup names, the way the dispatcher reads them.
function handlerOf(markup, fn, arg) {
  const tag = new RegExp('<[^>]*data-fn="' + fn + '"[^>]*data-arg="' + arg + '"[^>]*>').exec(markup);
  if (!tag) throw new Error('no ' + fn + ' control for ' + arg + ' in: ' + markup.slice(0, 400));
  return function () { return window[fn](arg); };
}
function tickBoxOf(markup, key) {
  const m = new RegExp('<input[^>]*data-floor-key="' + key + '"[^>]*data-fn="toggleFloor"[^>]*>').exec(markup);
  if (!m) throw new Error('no tick box for ' + key + ' in: ' + markup.slice(0, 400));
  return m[0];
}
const offNow = () => Array.from(E('floorOff')).sort();
"""


@unittest.skipUnless(base.shutil.which("node"), "Node.js is not installed")
class FloorSelectionCase(unittest.TestCase):
    def run_block(self, checks: str):
        r = base.run_node(HELPERS + checks)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())


class TheCardOffersTheFloors(FloorSelectionCase):

    def test_every_floor_is_listed_with_its_count_and_starts_ticked(self):
        self.run_block(r"""
          open(threeFloors());
          E('currentReportId = "location"');
          const html = draw();
          ['Ground Sample', 'Upper Sample', 'Roof Sample'].forEach(function (n) {
            check('lists ' + n, html.indexOf('>' + n + '<') >= 0);
          });
          eq('three tick boxes', (html.match(/type="checkbox"/g) || []).length, 3);
          eq('all ticked', (html.match(/ checked /g) || []).length, 3);
          check('says how many APs a floor holds', html.indexOf('6 APs') >= 0 && html.indexOf('2 APs') >= 0);
          eq('count line', els.floorCount.textContent, '3 of 3 included');
          eq('card shown', els.floorFilterCard.hidden, false);
        """)

    def test_a_one_floor_project_has_nothing_to_choose(self):
        self.run_block(r"""
          const p = project();
          p.floorPlans = p.floorPlans.slice(0, 1);
          p.accessPoints = p.accessPoints.filter(a => a.location.floorPlanId === 'fA');
          open(p);
          E('currentReportId = "location"');
          draw();
          eq('card hidden', els.floorFilterCard.hidden, true);
        """)

    def test_change_audit_does_not_offer_floors(self):
        self.run_block(r"""
          open(threeFloors());
          E('currentReportId = "audit"');
          draw();
          eq('card hidden for the audit', els.floorFilterCard.hidden, true);
          E('currentReportId = "summary"');
          draw();
          eq('card shown for the summary, which has no AP filter', els.floorFilterCard.hidden, false);
        """)

    def test_aps_with_no_floor_plan_get_a_row(self):
        self.run_block(r"""
          const p = threeFloors();
          p.accessPoints.push({ id: 'apX', name: 'Zed-APX', vendor: 'Vendo', model: 'V-100',
            location: { floorPlanId: null, coord: null }, noteIds: [] });
          open(p);
          E('currentReportId = "location"');
          const html = draw();
          check('a row for them', html.indexOf('>(No floor plan)<') >= 0);
        """)


class TheControlsDoWhatTheyAreLabelled(FloorSelectionCase):

    def test_unticking_a_box_leaves_that_floor_out(self):
        self.run_block(r"""
          open(threeFloors());
          E('currentReportId = "location"');
          const html = draw();
          tickBoxOf(html, 'fB');
          window.toggleFloor({ getAttribute: k => k === 'data-floor-key' ? 'fB' : null, checked: false });
          eq('Upper is off', offNow(), ['fB']);
          check('and drawn unticked', !/data-floor-key="fB"[^>]* checked/.test(els.floorFilterList.innerHTML));
          eq('count line', els.floorCount.textContent, '2 of 3 included');
          window.toggleFloor({ getAttribute: k => k === 'data-floor-key' ? 'fB' : null, checked: true });
          eq('ticking it again puts it back', offNow(), []);
        """)

    def test_only_this_floor_leaves_every_other_floor_out(self):
        self.run_block(r"""
          open(threeFloors());
          E('currentReportId = "location"');
          handlerOf(draw(), 'onlyFloor', 'fC')();
          eq('only the roof is in', offNow(), ['fA', 'fB']);
          eq('count line', els.floorCount.textContent, '1 of 3 included');
        """)

    def test_all_floors_and_none(self):
        self.run_block(r"""
          open(threeFloors());
          E('currentReportId = "location"');
          window.setAllFloors(false);
          eq('none', offNow(), ['fA', 'fB', 'fC']);
          window.setAllFloors(true);
          eq('all', offNow(), []);
        """)

    def test_the_all_floors_and_none_buttons_in_the_page_reach_the_handler(self):
        # The two buttons are static markup in report.html, so the page is
        # read for them and the handler each names is then run.
        page = (ROOT / "web" / "report.html").read_text(encoding="utf-8")
        card = page[page.index('id="floorFilterCard"'):page.index('id="apFilterCard"')]
        self.run_block(DELEGATED_JS + "const card = " + json.dumps(card) + ";" + r"""
          open(threeFloors());
          E('currentReportId = "location"');
          const tags = card.match(/<button[^>]*data-fn="setAllFloors"[^>]*>/g) || [];
          eq('two buttons in the card', tags.length, 2);
          const hits = tags.map(t => delegated(t, 'setAllFloors'));
          eq('All floors passes true', hits[0].args, [true]);
          eq('None passes false', hits[1].args, [false]);
          window[hits[1].fn].apply(null, hits[1].args);
          eq('None clears every floor', offNow(), ['fA', 'fB', 'fC']);
          window[hits[0].fn].apply(null, hits[0].args);
          eq('All floors puts them back', offNow(), []);
        """)

    def test_the_ap_panel_stops_listing_aps_on_a_floor_that_is_out(self):
        self.run_block(r"""
          open(threeFloors());
          E('currentReportId = "location"');
          E('currentOpts = { inclOmni: true, inclDirectional: true }');
          eq('all APs eligible', E('apFilterLists().eligible.length'), 13);
          handlerOf(draw(), 'onlyFloor', 'fC')();
          eq('only the roof APs', E('apFilterLists().eligible.length'), 2);
        """)


class EveryReportFollowsTheFloors(FloorSelectionCase):

    def test_an_ap_report_prints_only_the_floors_that_are_in(self):
        self.run_block(r"""
          open(threeFloors());
          floorsOff(['fB']);
          const html = render('location', { inclOmni: true });
          check('Ground is printed', html.indexOf('Ground Sample') >= 0);
          check('Roof is printed', html.indexOf('Roof Sample') >= 0);
          check('Upper is not', html.indexOf('Upper Sample') < 0);
          check('an Upper AP is not', html.indexOf('Zed-AP5<') < 0);
          check('a Ground AP is', html.indexOf('Zed-AP1<') >= 0);
          check('the header says which floors', html.indexOf('<b>Floors:</b> Ground Sample, Roof Sample') >= 0);
        """)

    def test_with_every_floor_in_nothing_is_cut_and_no_floors_line_is_added(self):
        self.run_block(r"""
          open(threeFloors());
          const html = render('location', { inclOmni: true });
          ['Ground Sample', 'Upper Sample', 'Roof Sample'].forEach(function (n) {
            check(n + ' printed', html.indexOf(n) >= 0);
          });
          check('no Floors line', html.indexOf('<b>Floors:</b>') < 0);
        """)

    def test_the_cover_counts_only_the_floors_that_remain(self):
        self.run_block(r"""
          open(threeFloors());
          E('document.getElementById("optCover").checked = true');
          els.optCover.checked = true;
          floorsOff(['fA', 'fB']);
          const html = render('location', { inclOmni: true });
          const stat = /<div class="rep-cover-stat"><b>(\d+)<\/b><span>Floor plan/.exec(html);
          check('the cover has a floor count', !!stat);
          eq('one floor', stat && stat[1], '1');
          check('and names it', html.indexOf('<b>Floors:</b> Roof Sample') >= 0);
        """)

    def test_the_bill_of_materials_totals_the_floors_that_are_in(self):
        self.run_block(r"""
          open(threeFloors());
          const all = render('bom', {});
          check('13 in all', />Total access points<\/td><td class="rep-az">13</.test(all));
          floorsOff(['fB', 'fC']);
          const one = render('bom', {});
          check('6 on Ground alone: ' + (/Total access points<\/td><td class="rep-az">(\d+)/.exec(one) || [])[1],
                />Total access points<\/td><td class="rep-az">6</.test(one));
        """)

    def test_the_summary_counts_and_lists_only_the_floors_that_are_in(self):
        self.run_block(r"""
          open(threeFloors());
          floorsOff(['fA']);
          const html = render('summary', { perFloor: true });
          check('Upper listed', html.indexOf('Upper Sample') >= 0);
          check('Roof listed', html.indexOf('Roof Sample') >= 0);
          check('Ground not listed', html.indexOf('Ground Sample') < 0);
          const stat = /<b>(\d+)<\/b><span>Access points?<\/span>/.exec(html);
          eq('the access point tile counts the floors in', stat && stat[1], '7');
          const fl = /<b>(\d+)<\/b><span>Floor plans?<\/span>/.exec(html);
          eq('the floor plan tile counts the floors in', fl && fl[1], '2');
        """)

    def test_interference_drops_a_device_seen_only_on_a_floor_that_is_out(self):
        self.run_block(r"""
          open(threeFloors());
          const all = render('interference', { catIphone: true, overview: false });
          check('both devices with every floor in',
                all.indexOf('Alpha iPhone') >= 0 && all.indexOf('Bravo iPhone') >= 0);
          floorsOff(['fB']);
          const some = render('interference', { catIphone: true, overview: false });
          check('Alpha was seen on Ground and stays', some.indexOf('Alpha iPhone') >= 0);
          check('Bravo was seen only on Upper and goes', some.indexOf('Bravo iPhone') < 0);
        """)

    def test_the_audit_report_ignores_the_floors(self):
        self.run_block(r"""
          open(threeFloors());
          floorsOff(['fA', 'fB']);
          eq('scope does not apply to it', E('floorScopeActive(REPORTS.audit)'), false);
          eq('but does to the placement report', E('floorScopeActive(REPORTS.location)'), true);
        """)


class ANarrowedProjectIsAlwaysPutBack(FloorSelectionCase):

    def test_the_open_project_is_whole_again_after_a_render(self):
        self.run_block(r"""
          open(threeFloors());
          floorsOff(['fB']);
          render('summary', {});
          eq('APs', E('proj.accessPoints.length'), 13);
          eq('floors', E('proj.floorPlans.length'), 3);
          eq('radios', E('proj.radios.length'), 13);
        """)

    def test_a_report_that_throws_does_not_leave_the_subset_behind(self):
        self.run_block(r"""
          open(threeFloors());
          floorsOff(['fB']);
          E('REPORTS.summary.render = function () { throw new Error("boom"); }');
          let threw = false;
          try { render('summary', {}); } catch (e) { threw = /boom/.test(String(e)); }
          check('the failure is not swallowed', threw);
          eq('APs', E('proj.accessPoints.length'), 13);
          eq('floors', E('proj.floorPlans.length'), 3);
        """)


class WhenNothingIsLeftTheReportSaysWhy(FloorSelectionCase):

    def test_every_floor_unticked_names_the_card(self):
        self.run_block(r"""
          open(threeFloors());
          floorsOff(['fA', 'fB', 'fC']);
          const html = render('location', { inclOmni: true });
          check('names the card: ' + html, html.indexOf('Floors to include') >= 0);
          const bom = render('bom', {});
          check('the summary-type reports say it too', bom.indexOf('Floors to include') >= 0);
        """)

    def test_aps_ticked_only_on_floors_that_are_out_names_the_floors_not_the_ap_panel(self):
        self.run_block(r"""
          const p = threeFloors();
          open(p);
          // Only the roof APs stay ticked in the AP panel, then the roof goes out.
          E('(function () { apDisabled = new Set(proj.accessPoints.filter(a => a.location.floorPlanId !== "fC").map(a => a.id)); })()');
          floorsOff(['fC']);
          const html = render('location', { inclOmni: true });
          check('names the floors: ' + html, html.indexOf('unticked in the Floors to include card') >= 0);
          check('and does not blame the AP panel', html.indexOf('unticked in the AP filter panel') < 0);
        """)


if __name__ == "__main__":
    unittest.main()
