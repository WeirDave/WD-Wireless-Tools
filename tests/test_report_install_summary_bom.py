"""The AP Installation report, the Site Summary and the Bill of Materials print
what the design holds, and add up.

An independent review printed all three over a library of awkward invented
projects and found, among other things:

* **"N APs" counted radios.** The antenna table's Qty column read "64 APs"
  for 32 APs, and a 150-AP project's column added up to 182.
* **Disabled and Bluetooth radios were printed as live**: an AP with a switched
  off radio listed "15 dBm, 20 dBm", a BLE radio printed "2402 (2.4 GHz)", and
  the BOM and Summary counted their antennas.
* **The channel lost its width**: an 80 MHz block printed "36", the CSV and the
  Design Review "36/80".
* **Cover and overview disagreed on floors**, and "(No floor plan)" was one.
* **Antenna types counted ids the project does not define**; **Top AP models**
  named a vendor-only AP after its vendor, merged two vendors' same-named part,
  and silently cut the list at ten; **the BOM left radios with no antenna out**
  of its antenna table with nothing to say so.
* **Client, preparer and reference vanished with the cover off**, and the BOM
  and Summary had no fields for them at all.
* One-sheet-per-section print rules gave a one-AP Summary five sheets; a footer
  row went to a sheet of its own; the procurement notes printed pale grey on
  white from the dark theme.

Every behavioural test renders the real `report.js` in Node against an
invented project (the pattern of `test_report_prints_what_the_design_holds`).
**The pagination itself cannot be asserted from a stub DOM.** It was measured
in Chromium - printing each report to PDF from the app's default dark theme -
and what is asserted here is the part that can be: the sections carry the class
the print rule keys on, and the rule exists, scoped to that class, in the
print block. Page counts before and after are in the commit message.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_report_prints_what_the_design_holds import ReportCase

CSS = Path(__file__).resolve().parent.parent / "web" / "assets" / "wd-tools.css"

# Helpers shared by the blocks below, appended to the harness prelude.
HELPERS = r"""
function cells(row) {
  return (row.match(/<td[^>]*>.*?<\/td>/g) || []).map(c => c.replace(/<[^>]+>/g, '').trim());
}
function rowOf(html, ap) {
  const a = html.indexOf(ap + '<');
  if (a < 0) throw new Error('row not in the report: ' + ap);
  const s = html.lastIndexOf('<tr', a);
  return html.slice(s, html.indexOf('</tr>', a) + 5);
}
function section(html, title) {
  const a = html.indexOf(title);
  if (a < 0) throw new Error('section not in the report: ' + title);
  return html.slice(a, html.indexOf('</section>', a));
}
function coverOn(on) { document.getElementById('optCover').checked = on; }
function twin(p, radio, extra) {
  p.radios.push(Object.assign({}, radio, { id: radio.id + 'b' }, extra || {}));
}
"""


def block(body: str) -> str:
    return HELPERS + body


class AnAntennaIsCountedByTheApsThatUseIt(ReportCase):

    DUAL = r"""
      function dualRadio() {
        const p = project();
        p.radios.slice().forEach(r => twin(p, r, { channelByCenterFrequencyDefinedNarrowChannels: [2412] }));
        return p;
      }
    """

    def test_the_installation_legend_counts_aps_not_radios(self):
        self.run_block(block(self.DUAL + r"""
          open(dualRadio());
          const html = render('location', { inclOmni: true, specs: true });
          const legend = section(html, '<h2 class="rep-floor-title">Antennas in use</h2>');
          // 8 omni APs and 3 directional; 16 and 6 when radios were counted.
          check('the omni antenna is on 8 APs: ' + legend, />8 APs</.test(legend));
          check('the directional antenna is on 3 APs: ' + legend, />3 APs</.test(legend));
          check('no radio count is printed as an AP count', !/16 APs|6 APs/.test(legend));
        """))

    def test_the_summary_counts_aps_not_radios(self):
        self.run_block(block(self.DUAL + r"""
          open(dualRadio());
          const html = render('summary', {});
          const ant = section(html, '<h2 class="rep-floor-title">Antennas in use</h2>');
          check('8 and 3: ' + ant, />8 APs</.test(ant) && />3 APs</.test(ant));
          check('not 16', !/16 APs/.test(ant));
        """))


class ARadioThatIsNotOnTheAirIsNotPrintedAsLive(ReportCase):

    OFF = r"""
      function withDeadRadios() {
        const p = project();
        // Zed-AP1: a switched-off 2.4 GHz radio and a Bluetooth radio beside
        // its live 5 GHz one.
        p.radios.push({ id: 'rOff', accessPointId: 'ap1', radioTechnology: 'IEEE802_11',
          enabled: false, antennaTypeId: 'dir1', transmitPower: 7, antennaMounting: 'WALL_MOUNT',
          antennaHeight: 1, channelByCenterFrequencyDefinedNarrowChannels: [2412] });
        p.radios.push({ id: 'rBle', accessPointId: 'ap1', radioTechnology: 'BLUETOOTH_LE',
          antennaTypeId: 'dir1', transmitPower: 0, antennaMounting: 'FLOOR', antennaHeight: 0.2,
          channelByCenterFrequencyDefinedNarrowChannels: [2402] });
        return p;
      }
    """

    def test_the_installation_row_lists_only_the_live_radio(self):
        self.run_block(block(self.OFF + r"""
          open(withDeadRadios());
          const row = rowOf(render('location', { inclOmni: true }), 'Zed-AP1');
          const c = cells(row);
          check('TX power is the live radio alone: ' + c, c.includes('20 dBm'));
          check('no 7 dBm from the switched-off radio: ' + row, row.indexOf('7 dBm') < 0);
          check('no 0 dBm from the Bluetooth radio: ' + row, !/(^|[^\d])0 dBm/.test(row));
          check('no 2.4 GHz channel from either: ' + row, row.indexOf('2.4 GHz') < 0 && row.indexOf('2402') < 0);
          check('the switched-off radio\'s wall mount is not printed: ' + row, !/Wall/.test(row));
          const legendIds = render('location', { inclOmni: true, specs: true });
          check('its antenna is not "in use" because of them',
                section(legendIds, '<h2 class="rep-floor-title">Antennas in use</h2>').indexOf('3 APs') >= 0);
        """))

    def test_the_bom_and_summary_count_only_live_radios(self):
        self.run_block(block(self.OFF + r"""
          open(withDeadRadios());
          const bom = render('bom', {});
          const ant = section(bom, '<h2 class="rep-floor-title">Antenna quantities</h2>');
          const total = ant.match(/Total antennas \(all\)<\/td>(?:<td><\/td>){3}<td class="rep-az">(\d+)</);
          eq('BOM antenna total = the eleven live radios', total && total[1], '11');
          check('the BOM has no phantom Wall mount: ' + section(bom, '<h2 class="rep-floor-title">Mount types'),
                section(bom, '<h2 class="rep-floor-title">Mount types').indexOf('Wall') < 0);
          const sum = render('summary', {});
          check('the Summary says eleven radios: ' + section(sum, 'Project at a glance').slice(0, 400),
                /<b>11<\/b><span>Radios<\/span>/.test(sum));
          const band = section(sum, '<h2 class="rep-floor-title">Radio band breakdown</h2>');
          check('and its band table has only 5 GHz: ' + band, band.indexOf('2.4 GHz') < 0);
        """))


class TheChannelKeepsItsWidth(ReportCase):

    def test_an_80_mhz_block_prints_36_slash_80(self):
        self.run_block(block(r"""
          const p = project();
          p.radios[0].channelByCenterFrequencyDefinedNarrowChannels = [5180, 5200, 5220, 5240];
          p.radios[1].channelByCenterFrequencyDefinedNarrowChannels = [5180, 5200];
          open(p);
          const html = render('location', { inclOmni: true });
          check('36/80 for four 20 MHz channels: ' + rowOf(html, 'Zed-AP1'),
                rowOf(html, 'Zed-AP1').indexOf('36/80 <span') >= 0);
          check('36/40 for two: ' + rowOf(html, 'Zed-AP2'),
                rowOf(html, 'Zed-AP2').indexOf('36/40 <span') >= 0);
          check('a plain 20 MHz channel is still a bare number',
                rowOf(html, 'Zed-AP4').indexOf('>36 <span') >= 0);
        """))


class CoverAndOverviewAgreeOnFloors(ReportCase):

    def test_a_filter_narrows_the_cover_and_the_overview_together(self):
        """Ground has omni APs only; with omni off the report covers Upper."""
        self.run_block(block(r"""
          open(project());
          coverOn(true);
          const html = render('location', { inclOmni: false });
          coverOn(false);
          const cover = html.match(/<div class="rep-cover-stat"><b>(\d+)<\/b><span>Floor plans?<\/span>/);
          const tile = html.match(/<div class="rep-hotspot-stat"><b>(\d+)<\/b><span>Floor plans?<\/span>/);
          eq('the cover counts the floors the report covers', cover && cover[1], '1');
          eq('and so does the overview', tile && tile[1], '1');
        """))

    def test_no_floor_plan_is_not_a_floor_plan(self):
        self.run_block(block(r"""
          const p = project();
          p.accessPoints.forEach(a => { a.location = {}; });
          open(p);
          coverOn(true);
          const html = render('location', { inclOmni: true });
          coverOn(false);
          const cover = html.match(/<div class="rep-cover-stat"><b>(\d+)<\/b><span>Floor plans?<\/span>/);
          const tile = html.match(/<div class="rep-hotspot-stat"><b>(\d+)<\/b><span>Floor plans?<\/span>/);
          eq('cover: no APs sit on a floor plan', cover && cover[1], '0');
          eq('overview agrees', tile && tile[1], '0');
        """))

    def test_a_report_with_no_ap_filter_states_the_projects_floors(self):
        self.run_block(block(r"""
          open(project());
          coverOn(true);
          const html = render('bom', {});
          coverOn(false);
          check('two floor plans', /<b>2<\/b><span>Floor plans<\/span>/.test(html));
        """))


class TheSummaryAddsUp(ReportCase):

    def test_antenna_types_ignore_an_id_the_project_does_not_define(self):
        self.run_block(block(r"""
          const p = project();
          p.radios.push({ id: 'rGhost', accessPointId: 'ap1', radioTechnology: 'IEEE802_11',
            antennaTypeId: 'ant-does-not-exist', transmitPower: 10,
            channelByCenterFrequencyDefinedNarrowChannels: [2412] });
          open(p);
          const html = render('summary', {});
          check('two types, the ones in the library: ' + section(html, 'Project at a glance').slice(0, 500),
                /<b>2<\/b><span>Antenna types<\/span>/.test(html));
        """))

    def test_top_models_keep_vendor_and_model_apart_and_add_up(self):
        self.run_block(block(r"""
          const p = project();
          p.accessPoints[0].vendor = 'Vend-A'; p.accessPoints[0].model = 'X-1';
          p.accessPoints[1].vendor = 'Vend-B'; p.accessPoints[1].model = 'X-1';
          p.accessPoints[2].vendor = 'Vend-A'; p.accessPoints[2].model = '';
          open(p);
          const sec = section(render('summary', {}), '<h2 class="rep-floor-title">Top AP models</h2>');
          const rows = (sec.match(/<tr><td>[^<]*<\/td><td class="rep-name">[^<]*<\/td><td class="rep-az">\d+<\/td><\/tr>/g) || [])
            .map(cells);
          const key = r => r.join('|');
          const have = rows.map(key);
          check('the same model from two vendors is two rows: ' + have,
                have.includes('Vend-A|X-1|1') && have.includes('Vend-B|X-1|1'));
          check('a vendor-only AP is an Unknown model, not named after its vendor: ' + have,
                have.includes('Vend-A|Unknown|1') && !have.some(r => r.startsWith('Vend-A|Vend-A')));
          const total = sec.match(/Total access points<\/td><td class="rep-az">(\d+)</);
          eq('the table states the AP total', total && total[1], '11');
        """))

    def test_the_tail_past_ten_is_an_other_row_so_the_column_adds_up(self):
        self.run_block(block(r"""
          const p = project();
          p.accessPoints.forEach((a, i) => { a.model = 'Model-' + String.fromCharCode(65 + i); });
          open(p);                                      // eleven models of one each
          const sec = section(render('summary', {}), '<h2 class="rep-floor-title">Top AP models</h2>');
          check('an Other row names how many models it holds: ' + sec, /Other \(1 model\)/.test(sec));
          const qty = (sec.match(/<td class="rep-az">(\d+)<\/td>/g) || []).map(s => +s.replace(/\D/g, ''));
          const total = qty.pop();
          eq('the rows add up to the total', qty.reduce((a, b) => a + b, 0), total);
          eq('and the total is every AP', total, 11);
        """))

    def test_floors_are_in_the_order_the_other_reports_use(self):
        self.run_block(block(r"""
          const p = project();
          p.floorPlans[0].name = 'Floor 2 Mezzanine';
          p.floorPlans[1].name = 'Floor 1 Warehouse';
          open(p);
          const sec = section(render('summary', {}), '<h2 class="rep-floor-title">Per-floor breakdown</h2>');
          check('storey 1 before storey 2: ' + sec,
                sec.indexOf('Floor 1 Warehouse') >= 0 && sec.indexOf('Floor 1 Warehouse') < sec.indexOf('Floor 2 Mezzanine'));
        """))

    def test_the_size_column_is_the_real_size_in_the_chosen_unit(self):
        self.run_block(block(r"""
          const p = project();                  // 1000 x 800 px at 0.05 m per px: 50 x 40 m
          p.floorPlans[1].metersPerUnit = null;  // Upper is not calibrated
          open(p);
          const ft = section(render('summary', {}), '<h2 class="rep-floor-title">Per-floor breakdown</h2>');
          check('feet: ' + ft, ft.indexOf('164 × 131 ft') >= 0);
          check('an uncalibrated plan keeps its pixels: ' + ft, ft.indexOf('1000 × 800 px') >= 0);
          // The Summary has no units control of its own: it follows Settings.
          E('(function () { unitsPref = "meters"; })')();
          const m = section(render('summary', {}), '<h2 class="rep-floor-title">Per-floor breakdown</h2>');
          check('metres: ' + m, m.indexOf('50 × 40 m') >= 0);
        """))


class TheBomSaysWhereItIsShort(ReportCase):

    def test_a_radio_with_no_antenna_is_a_not_recorded_row(self):
        self.run_block(block(r"""
          const p = project();
          p.radios[1].antennaTypeId = null;
          p.radios[2].antennaTypeId = 'ant-does-not-exist';
          open(p);
          const ant = section(render('bom', {}), '<h2 class="rep-floor-title">Antenna quantities</h2>');
          check('the gap is a row: ' + ant, /Not recorded<\/em><\/td>(?:<td><\/td>){3}<td class="rep-az">2</.test(ant));
          const total = ant.match(/rep-bom-total"><td class="rep-name">([^<]*)<\/td>(?:<td><\/td>){3}<td class="rep-az">(\d+)</);
          eq('the total is every live radio', total && total[2], '11');
          const ext = section(render('bom', { externalOnly: true }), '<h2 class="rep-floor-title">Antenna quantities</h2>');
          check('external-only cannot say a missing antenna is external', ext.indexOf('Not recorded') < 0);
        """))

    def test_an_empty_antenna_table_says_what_is_true(self):
        self.run_block(block(r"""
          const p = project(); p.radios = [];
          open(p);
          const none = section(render('bom', {}), '<h2 class="rep-floor-title">Antenna quantities</h2>');
          check('no filter is blamed when none is on: ' + none, none.indexOf('current filter') < 0
                && /No antennas are recorded/.test(none));
          const ext = section(render('bom', { externalOnly: true }), '<h2 class="rep-floor-title">Antenna quantities</h2>');
          check('with the filter on, it names the control by its label: ' + ext,
                ext.indexOf('Show external antennas only') >= 0);
        """))

    def test_the_mount_is_spelled_the_same_in_the_bom_and_the_installation_table(self):
        self.run_block(block(r"""
          const p = project();
          p.radios[0].antennaMounting = 'WALL_MOUNT';
          open(p);
          const loc = rowOf(render('location', { inclOmni: true }), 'Zed-AP1');
          check('Installation: ' + loc, cells(loc).includes('Wall mount'));
          const bom = section(render('bom', {}), '<h2 class="rep-floor-title">Mount types');
          check('BOM: ' + bom, bom.indexOf('>Wall mount<') >= 0);
        """))


class TheClientDetailsSurviveTheCoverBeingOff(ReportCase):

    DETAILS = ("{ clientName: 'Sample Client', preparedBy: 'Sam Sample', "
               "projectRef: 'PO-0000', revision: 'Rev Q' }")

    def test_the_header_carries_them_for_every_report_that_has_the_fields(self):
        self.run_block(block(r"""
          open(project());
          coverOn(false);
          ['location', 'summary', 'bom'].forEach(id => {
            const html = render(id, DETAILS);
            const head = section(html, '<header class="rep-doc-head">');
            ['Sample Client', 'Sam Sample', 'PO-0000', 'Rev Q'].forEach(v =>
              check(id + ' header carries ' + v + ': ' + head, head.indexOf(v) >= 0));
          });
        """.replace("DETAILS", self.DETAILS)))

    def test_the_summary_and_bom_offer_the_same_four_fields_as_placement(self):
        self.run_block(block(r"""
          const defs = id => E('REPORTS.' + id + '.sidebar').filter(o => o.type === 'text')
            .map(o => o.id + '|' + o.label);
          ['summary', 'bom'].forEach(id => eq(id + ' offers placement\'s four', defs(id), defs('placement')));
        """))

    def test_and_the_cover_prints_them_for_the_bom(self):
        self.run_block(block(r"""
          open(project());
          coverOn(true);
          const html = render('bom', DETAILS);
          coverOn(false);
          const cover = section(html, '<section class="rep-cover');
          ['Sample Client', 'Sam Sample', 'PO-0000', 'Rev Q'].forEach(v =>
            check('cover carries ' + v, cover.indexOf(v) >= 0));
        """.replace("DETAILS", self.DETAILS)))


class TheInstallationTableIsHonestAboutWhatItPrints(ReportCase):

    def test_an_impossible_height_and_an_out_of_range_bearing(self):
        self.run_block(block(r"""
          const p = project();
          p.radios[2].antennaHeight = -1;          // Zed-AP3: below the floor
          p.radios.find(r => r.accessPointId === 'ap6').antennaDirection = 450;
          open(p);
          const html = render('location', { inclOmni: true });
          const low = cells(rowOf(html, 'Zed-AP3'));
          check('a negative height is a dash, not "-3.3 ft": ' + low, !/-\d[\d.]* (ft|m)/.test(low.join('|')));
          const aimed = rowOf(html, 'Zed-AP6');
          check('450 degrees prints as 90: ' + aimed, aimed.indexOf('90.0°') >= 0 || aimed.indexOf('90°') >= 0);
          check('and 450 is not printed: ' + aimed, aimed.indexOf('450') < 0);
        """))

    def test_an_unnamed_ap_has_a_visible_number_cell(self):
        self.run_block(block(r"""
          const p = project();
          p.accessPoints[3].name = '';
          open(p);
          const html = render('location', { inclOmni: true });
          check('a dash, not an empty cell',
                /<td class="rep-num">—<\/td><td class="rep-name">\(unnamed\)/.test(html));
        """))

    def test_every_live_radios_antenna_is_listed_not_only_the_primary(self):
        self.run_block(block(r"""
          const p = project();
          twin(p, p.radios[0], { antennaTypeId: 'dir1', channelByCenterFrequencyDefinedNarrowChannels: [2412] });
          open(p);
          const html = render('location', { inclOmni: true });
          const row = rowOf(html, 'Zed-AP1');
          check('two codes, as two channels are listed: ' + row,
                /<td class="rep-az" title="[^"]*">A\d, A\d<\/td>/.test(row));
        """))

    def test_the_specs_option_follows_the_antennas_in_use(self):
        self.run_block(block(r"""
          const p = project();
          p.radios.forEach(r => { r.antennaTypeId = 'omni1'; });
          p.antennas.unusedLibraryEntry = { id: 'unusedLibraryEntry', name: 'Unused', beamWidthHorizontal: 30 };
          open(p);
          eq('a beam width on an antenna nothing uses does not count', E('hasAnyBeamWidth')(p), false);
          p.antennas.omni1.beamWidthHorizontal = 360;
          eq('one on an antenna in use does', E('hasAnyBeamWidth')(p), true);
        """))

    def test_the_antenna_table_says_5_ghz_not_five(self):
        self.run_block(block(r"""
          const p = project();
          p.antennas.omni1.frequencyBand = 'FIVE';
          open(p);
          const legend = section(render('location', { inclOmni: true, specs: true }),
                                 '<h2 class="rep-floor-title">Antennas in use</h2>');
          check('humanised: ' + legend, legend.indexOf('5 GHz') >= 0 && legend.indexOf('FIVE') < 0);
        """))


class TheContentsNamesThePagesThatPrint(ReportCase):

    def test_each_entry_is_the_heading_of_a_page_that_exists(self):
        self.run_block(block(r"""
          open(project());
          coverOn(true);
          const html = render('location', { inclOmni: true, nameAudit: true, specs: true,
                                            compassRef: 'always' });
          coverOn(false);
          const toc = section(html, 'rep-toc-list');
          ['Naming audit', 'Antennas in use', 'Compass &amp; Antenna Alignment Reference', 'AP Notes', 'Approval']
            .forEach(t => {
              check('the contents lists ' + t + ': ' + toc, toc.indexOf('<b>' + t + '</b>') >= 0);
              const heading = '<h2 class="rep-floor-title">' + t + '</h2>';
              check('and a page has that heading: ' + t, html.indexOf(heading) >= 0
                    || html.indexOf('>' + t + '<') >= 0);
            });
          check('the old names are gone', toc.indexOf('Antenna reference') < 0 && toc.indexOf('AP name audit') < 0);
        """))

    def test_a_single_ap_is_not_counted_in_the_plural(self):
        self.run_block(block(r"""
          const p = project();
          p.accessPoints = p.accessPoints.slice(0, 1);
          p.radios = p.radios.slice(0, 1);
          p.floorPlans = p.floorPlans.slice(0, 1);
          open(p);
          coverOn(true);
          const loc = render('location', { inclOmni: true });
          const sum = render('summary', {});
          coverOn(false);
          check('cover', /<b>1<\/b><span>Access point<\/span>/.test(loc));
          check('overview tile', /<b>1<\/b><span>Access point<\/span>/.test(section(loc, 'Project overview')));
          check('contents', loc.indexOf('Installation table — 1 AP<') >= 0);
          ['Access point', 'Radio', 'Floor plan'].forEach(w =>
            check('summary tile ' + w, new RegExp('<b>1</b><span>' + w + '</span>').test(sum)));
          check('nothing says "1 Access points" or "1 Radios"', !/<b>1<\/b><span>(Access points|Radios|Floor plans)</.test(loc + sum));
        """))


class EveryFlowingReportCarriesTheClassThePrintRuleKeysOn(ReportCase):
    """Summary and BOM sections flow; Installation sections still take a
    sheet each. The pagination was measured in Chromium (see the module
    docstring); this holds the two halves a stub can: the class on the
    section, and the rule scoped to it."""

    @staticmethod
    def _print_css() -> str:
        css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
        return css

    def test_summary_and_bom_sections_flow_and_installation_ones_do_not(self):
        self.run_block(block(r"""
          open(project());
          ['summary', 'bom'].forEach(id => {
            const html = render(id, {});
            const secs = (html.match(/<section class="rep-floor-section[^"]*"/g) || [])
              .filter(s => s.indexOf('rep-notes-page') < 0);
            check(id + ' has sections', secs.length >= 4);
            secs.forEach(s => check(id + ' section flows: ' + s, s.indexOf('rep-flow') >= 0));
          });
          const loc = render('location', { inclOmni: true });
          check('Installation keeps a sheet per section', loc.indexOf('rep-flow') < 0);
        """))

    def test_the_print_rules_exist_and_are_scoped(self):
        css = self._print_css()
        flow = re.search(r"\.rep-floor-section\.rep-flow\s*\{([^}]*)\}", css)
        self.assertTrue(flow, "no print rule for .rep-floor-section.rep-flow")
        self.assertRegex(flow.group(1), r"break-before:\s*auto")
        self.assertRegex(flow.group(1), r"break-inside:\s*avoid")
        self.assertRegex(css, r"\.rep-loc-table tfoot\s*\{\s*display:\s*table-row-group\s*!important")
        self.assertRegex(css, r"\.rep-matrix\s*\{[^}]*break-inside:\s*avoid")
        self.assertRegex(css, r"\.rep-summary-notes,\s*\.rep-summary-notes b\s*\{\s*color:\s*black\s*!important")
        # The base rule is untouched: every other report keeps a sheet per section.
        self.assertRegex(css, r"\n\s*\.rep-floor-section \{ page-break-before: always;")

    def test_the_floor_summary_and_the_notes_are_marked_for_those_rules(self):
        self.run_block(block(r"""
          open(project());
          const loc = render('location', { inclOmni: true });
          check('the floor summary carries rep-matrix',
                /<section class="rep-floor-section rep-matrix[ "][^>]*>(<div class="rep-orient[\s\S]*?<\/div>)?<h2 class="rep-floor-title">Floor summary/.test(loc));
          check('the table footer is a real tfoot for the print rule to act on',
                loc.indexOf('<tfoot><tr><td colspan=') >= 0 && loc.indexOf('class="rep-ap-table rep-loc-table"') >= 0);
          const bom = render('bom', {});
          check('the procurement notes carry the class the rule names',
                bom.indexOf('<ul class="rep-summary-notes">') >= 0);
        """))


class PageOrientationForTheInstallationPages(ReportCase):

    def test_a_long_note_does_not_turn_the_notes_page_landscape(self):
        self.run_block(block(r"""
          // A page of the shape autoOrientationFor reads: its kind, its table,
          // and (when the table cannot be measured) the header row's width.
          function page(tableClass) {
            const table = { classList: { contains: c => c === tableClass } };
            return { getAttribute: k => (k === 'data-page-kind' ? 'table' : null),
              querySelector: sel => (sel === 'table' ? table
                : sel === 'thead tr' ? { children: new Array(13) } : null) };
          }
          const auto = E('autoOrientationFor');
          eq('the notes table wraps, so it is portrait however many columns', auto(page('rep-notes-table')), 'portrait');
          eq('a thirteen-column table that cannot be measured still turns', auto(page('rep-loc-table')), 'landscape');
        """))

    def test_the_pages_match_all_reaches_have_keys(self):
        self.run_block(block(r"""
          open(project());
          coverOn(true);
          const html = render('location', { inclOmni: true, nameAudit: true, specs: true, signOff: true });
          coverOn(false);
          ['toc', 'overview', 'matrix', 'audit', 'legend', 'signoff'].forEach(k =>
            check('page key ' + k, html.indexOf('data-page-key="' + k + '" data-page-kind="page"') >= 0
                  && html.indexOf('data-for="' + k + '"') >= 0));
        """))


if __name__ == "__main__":
    unittest.main()
