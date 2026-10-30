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
  // The real shape: a measured radio names its design AP and a list of measurements.
  p.measuredRadios = [
    { id: 'mr1', accessPointId: 'ap1', accessPointMeasurementIds: ['m1'], status: 'OK' },
    { id: 'mr2', accessPointId: 'ap5', accessPointMeasurementIds: ['m2'], status: 'OK' },
    { id: 'mr3', accessPointId: 'ap6', accessPointMeasurementIds: ['m2'], status: 'OK' },
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

    def test_the_summary_counts_the_measured_radios_of_the_floors_that_are_in(self):
        self.run_block(r"""
          open(threeFloors());
          const tile = h => (/<b>(\d+)<\/b><span>Measured radios?<\/span>/.exec(h) || [])[1];
          eq('all three with every floor in', tile(render('summary', {})), '3');
          floorsOff(['fB']);
          eq('only the Ground one with Upper out', tile(render('summary', {})), '1');
          floorsOff(['fA', 'fB']);
          eq('none, so no tile, with only the Roof in', tile(render('summary', {})), undefined);
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


class TheStepsAfterTheScopeFollowIt(FloorSelectionCase):
    """Which floors are in is decided first, and everything below it is about
    those floors only: no plan is offered for a grid, and none is counted, on a
    floor that will not be printed."""

    SETUP = r"""
      open(threeFloors());
      E('currentReportId = "placement"');
      E('settingsAvailable = true');
      const names = id => els[id].children.map(o => o.textContent.replace(/\s+✓$/, ''));
      const values = id => els[id].children.map(o => String(o.value));
      // The stub does not clear children when innerHTML is set, so a second open starts empty by hand.
      const reopen = (open, id) => { document.getElementById(id).children = []; open(); };
    """

    def test_the_section_grid_dialog_lists_only_the_included_floors(self):
        self.run_block(self.SETUP + r"""
          E('(function () { floorOff = new Set(["fB"]); })')();
          window.openGridConfig();
          eq('names', names('gridFloorSelect'), ['Ground Sample', 'Roof Sample']);
          eq('values are real indexes into the project floors', values('gridFloorSelect'), ['0', '2']);
          eq('opens on the first included floor', E('_gridFloorIdx'), 0);
          E('(function () { floorOff = new Set(["fA"]); })')();
          reopen(window.openGridConfig, 'gridFloorSelect');
          eq('first floor out', names('gridFloorSelect'), ['Upper Sample', 'Roof Sample']);
          eq('opens on the first floor that is in', E('_gridFloorIdx'), 1);
          eq('and shows it', E('proj.floorPlans[_gridFloorIdx].name'), 'Upper Sample');
        """)

    def test_the_column_grid_dialog_lists_only_the_included_floors(self):
        self.run_block(self.SETUP + r"""
          E('(function () { floorOff = new Set(["fA", "fC"]); })')();
          window.openGridRef();
          eq('names', names('gridRefFloorSelect'), ['Upper Sample']);
          eq('index', E('_grFloorIdx'), 1);
          eq('modal opened', els.gridRefModal.hidden, false);
        """)

    def test_a_report_with_no_floors_in_opens_neither_dialog(self):
        self.run_block(self.SETUP + r"""
          const said = [];
          window.alert = m => said.push(m);
          window.setAllFloors(false);
          document.getElementById('gridConfigModal').hidden = true;
          document.getElementById('gridRefModal').hidden = true;
          window.openGridConfig();
          window.openGridRef();
          eq('section grid stays shut', els.gridConfigModal.hidden, true);
          eq('column grid stays shut', els.gridRefModal.hidden, true);
          check('and says why', said.length === 1 && said[0].indexOf('No floors are included') >= 0);
          check('both say why', toasts.some(t => t.msg.indexOf('No floors are included') >= 0));
        """)

    def test_apply_to_all_floors_leaves_a_floor_that_is_out_alone(self):
        self.run_block(self.SETUP + r"""
          E('(function () { floorOff = new Set(["fB"]); })')();
          E('(function () { currentOpts.cropBoxes = { fB: { x: 0.2, y: 0.2, w: 0.3, h: 0.3 } }; })')();
          window.openGridConfig();
          E('(function () { _cropBox = { x: 0.1, y: 0.1, w: 0.5, h: 0.5 }; })')();
          window.applyGridFloor(true);
          const got = E('_cropBoxes');
          eq('the floors that are in take the crop', [got.fA.w, got.fC.w], [0.5, 0.5]);
          eq('the floor that is out keeps what it had', got.fB, { x: 0.2, y: 0.2, w: 0.3, h: 0.3 });
          check('the message counts the floors it reached',
                toasts.some(t => t.msg.indexOf('applied to all 2 floors') >= 0));
        """)

    def test_the_button_counts_only_included_floors(self):
        self.run_block(self.SETUP + r"""
          E('(function () { _floorGrids = { fB: { a: {}, b: {} } }; })')();
          const opt = { id: '_gridRefSetup', type: 'gridref-button', label: 'Set up column grid' };
          const render = () => E('renderOptHtml')(opt);
          check('all floors in: one of three', render().indexOf('>1 of 3 floors<') >= 0);
          E('(function () { floorOff = new Set(["fB"]); })')();
          check('the calibrated floor is out: not set up', render().indexOf('>Not set up<') >= 0);
          E('(function () { floorOff = new Set(["fA"]); })')();
          check('two floors in, one calibrated', render().indexOf('>1 of 2 floors<') >= 0);
        """)

    def test_a_crop_on_a_floor_that_is_out_is_not_announced(self):
        self.run_block(self.SETUP + r"""
          E('(function () { currentOpts.cropBoxes = { fB: { x: 0, y: 0, w: 0.5, h: 0.5 } }; currentOpts.segCols = 2; currentOpts.segRows = 2; })')();
          const opt = { id: '_gridConfig', type: 'grid-button', label: 'Configure grid' };
          check('shown while the floor is in', E('renderOptHtml')(opt).indexOf('(cropped)') >= 0);
          E('(function () { floorOff = new Set(["fB"]); })')();
          check('not shown once it is out', E('renderOptHtml')(opt).indexOf('(cropped)') < 0);
        """)

    def test_the_column_grid_column_needs_a_calibrated_floor_that_is_in(self):
        self.run_block(self.SETUP + r"""
          E('(function () { _floorGrids = { fB: { a: {}, b: {} } }; })')();
          const shows = () => E('showsGridColumn')({ gridRef: true });
          eq('calibrated and in', shows(), true);
          E('(function () { floorOff = new Set(["fB"]); })')();
          eq('calibrated but out: no column of dashes', shows(), false);
        """)

    def test_the_scope_cards_come_before_the_options_that_depend_on_them(self):
        """Choosing what the report covers is the first thing on the page after
        the description of the report: floors, then APs, then the details and
        options that only make sense for what is left."""
        page = (ROOT / "web" / "report.html").read_text(encoding="utf-8")
        order = [page.index(marker) for marker in (
            'id="reportPreviewCard"', 'id="floorFilterCard"', 'id="apFilterCard"',
            'id="reportDetailsSlot"', 'id="reportOptsSlot"')]
        self.assertEqual(order, sorted(order))

    def test_ticking_a_floor_redraws_the_options_that_count_floors(self):
        self.run_block(DELEGATED_JS + self.SETUP + r"""
          E('(function () { _floorGrids = { fB: { a: {}, b: {} } }; })')();
          const html = draw();
          const untick = tickBoxOf(html, 'fB');
          const hit = delegated(untick, 'toggleFloor');
          const box = { checked: false, getAttribute: k => k === 'data-floor-key' ? 'fB' : null };
          window[hit.fn](box);
          check('the options card was rewritten without that floor',
                els.reportOptsSlot.innerHTML.indexOf('>Not set up<') >= 0);
        """)


if __name__ == "__main__":
    unittest.main()
