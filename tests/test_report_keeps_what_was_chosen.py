"""The Report keeps what was chosen, and prints what it says it prints.

A second review of the Report found defects that rendered cleanly and were
wrong on paper or in the panel:

* saved options for **AP Installation** were skipped when it was the first
  report picked, because it is also the report the page starts on - and the
  first change then autosaved the shipped values over the saved ones;
* six reports built their **cover** without their options, so Client,
  Prepared by and Project ref never printed and the cover's orientation
  picker read nothing;
* a change made **just before switching report** was saved under the next
  report's name;
* **Change / Audit** ignored "Confidentiality notice in footer", let its own
  cover option overrule "Include cover page", and promised a cover naming
  both files that named neither;
* its **Before** count of directional APs judged the earlier file's antennas
  by the later file's list;
* the **cover title** cut "Building C" off "Main Campus - Building C" and
  printed "final" for a file the document title had named by its folder;
* **Reset to shipped defaults** threw away the floor grid, the crop, a typed
  client name and the page orientations, and left Review on the old document;
* **Toggle all** unticked APs the search or the omni/directional filter was
  hiding, and the **AP count** forgot the filter after one tick;
* the Placement Map printed **feet** under a metric setting, the Coverage
  sizing table printed **metres** under a feet one, and metric heights had
  one decimal where a metre needs two;
* the Antenna Aim Sheet gave an **omni** AP an azimuth;
* the **contents** promised detail sections for a floor with no image;
* **2484 MHz** printed as channel 15.

Each test drives the real `report.js` through the harness of
`test_report_prints_what_the_design_holds.py`: the page's own handlers are
called, and what they render or send is read back.
"""
from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.test_report_prints_what_the_design_holds import run_node  # noqa: E402

# A server that accepts a settings write and echoes it back the way the real
# one does, recording each write.
RECORDING_SERVER = r"""
const writes = [];
WD.api = async (ep, body) => {
  if (ep === 'settings/update') {
    writes.push(JSON.parse(JSON.stringify(body)));
    return { ok: true, settings: { report: { report_defaults: body.patch.report.report_defaults } } };
  }
  return { ok: false };
};
function lastSaved() {
  if (!writes.length) throw new Error('nothing was saved');
  return writes[writes.length - 1].patch.report.report_defaults;
}
// A checkbox in the options panel, as `setOpt` reads it.
function tick(id, checked) {
  window.setOpt({ getAttribute(k) { return { 'data-opt-id': id, 'data-opt-type': 'bool' }[k]; },
                  checked: checked });
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ReportCase(unittest.TestCase):
    def run_block(self, checks: str):
        r = run_node(RECORDING_SERVER + checks)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())


class SavedDefaultsReachTheFirstReportPicked(ReportCase):

    def test_ap_installation_picked_first_starts_from_its_saved_options(self):
        self.run_block(r"""
          open();
          E('(function(){ settingsAvailable = true; applySettingsPayload({ report_defaults: { location: { inclOmni: true, shortLabels: false } } }); })')();
          eq('the page starts on AP Installation', E('currentReportId'), 'location');
          window.selectReport('location');
          eq('saved short-labels choice is in force', E('collectOpts()').shortLabels, false);
          eq('saved omni choice is in force', E('collectOpts()').inclOmni, true);
        """)

    def test_the_first_change_does_not_save_shipped_values_over_saved_ones(self):
        self.run_block(r"""
          open();
          E('(function(){ settingsAvailable = true; applySettingsPayload({ report_defaults: { location: { inclOmni: true, shortLabels: false } } }); })')();
          window.selectReport('location');
          tick('compass', false);
          await sleep(1700);
          const loc = lastSaved().location;
          eq('the change is saved', loc.compass, false);
          eq('the saved short-labels choice survives', loc.shortLabels, false);
        """)


class AChangeIsSavedUnderTheReportItWasMadeOn(ReportCase):

    def test_switching_report_within_the_autosave_delay_keeps_the_change(self):
        self.run_block(r"""
          open();
          E('(function(){ settingsAvailable = true; applySettingsPayload({ report_defaults: {} }); })')();
          window.selectReport('location');
          tick('compass', false);
          window.selectReport('aim');
          await sleep(1700);
          const saved = writes.map(w => w.patch.report.report_defaults);
          check('AP Installation\'s change was saved: ' + JSON.stringify(saved),
                saved.some(d => d.location && d.location.compass === false));
          check('nothing was saved for the Aim sheet, which nobody changed: ' + JSON.stringify(saved),
                saved.every(d => !d.aim));
        """)


class EveryCoverCarriesItsOptions(ReportCase):

    def test_placement_prints_client_prepared_by_and_project_ref(self):
        self.run_block(r"""
          document.getElementById('optCover').checked = true;
          open();
          const html = render('placement', { clientName: 'Invented Client Co',
            preparedBy: 'A. Sample', projectRef: 'REF-0001' });
          const cover = floorPart(html, '<section class="rep-cover', '</section>');
          check('Client on the cover', cover.includes('<b>Client:</b> Invented Client Co'));
          check('Prepared by on the cover', cover.includes('<b>Prepared by:</b> A. Sample'));
          check('Project ref on the cover', cover.includes('<b>Project ref:</b> REF-0001'));
        """)

    def test_every_cover_orientation_picker_reads_the_chosen_orientation(self):
        self.run_block(r"""
          document.getElementById('optCover').checked = true;
          open();
          E('(function(b){ baseline = b; baselineName = "Invented Before.esx"; })')(project());
          ['placement', 'summary', 'bom', 'interference', 'aim', 'audit', 'coverage', 'location']
            .forEach(id => {
              const html = render(id, { inclOmni: true, pageOrient: { cover: 'landscape' } });
              const pick = (html.match(/rep-orient noprint" data-for="cover"[\s\S]*?<\/div>/) || [''])[0];
              eq(id + ': the cover picker shows landscape',
                 (pick.match(/is-on"[^>]*data-arg2="(\w+)"/) || [])[1], 'landscape');
            });
        """)


class TheChangeReportObeysItsControls(ReportCase):

    def test_the_confidentiality_notice_prints(self):
        self.run_block(r"""
          open();
          E('(function(b){ baseline = b; baselineName = "Invented Before.esx"; })')(project());
          check('CONFIDENTIAL in the footer', render('audit', { confidential: true }).includes('CONFIDENTIAL'));
          check('and not when it is off', !render('audit', { confidential: false }).includes('CONFIDENTIAL'));
        """)

    def test_include_cover_page_decides_alone(self):
        self.run_block(r"""
          document.getElementById('optCover').checked = false;
          open();
          E('(function(b){ baseline = b; baselineName = "Invented Before.esx"; })')(project());
          // What a settings file from before this fix may still hold.
          check('no cover with "Include cover page" unticked',
                !render('audit', { cover: true }).includes('rep-cover-title'));
          document.getElementById('optCover').checked = true;
          check('a cover with it ticked', render('audit', {}).includes('rep-cover-title'));
        """)

    def test_the_cover_names_both_files(self):
        self.run_block(r"""
          document.getElementById('optCover').checked = true;
          open();
          E('(function(b){ baseline = b; baselineName = "Invented Before.esx"; })')(project());
          const cover = floorPart(render('audit', {}), '<section class="rep-cover', '</section>');
          check('the before file on the cover', cover.includes('<b>Before:</b> Invented Before.esx'));
          check('the after file on the cover', cover.includes('<b>After:</b> Invented Sample.esx'));
        """)

    def test_the_before_count_of_directional_aps_uses_the_before_antennas(self):
        self.run_block(r"""
          open();
          const before = project();
          // The earlier design used a panel the later one no longer carries.
          before.antennas.oldPanel = { id: 'oldPanel', name: 'Invented Old Panel 9dBi',
            directional: true, apCoupling: 'EXTERNAL_ANTENNA' };
          delete before.antennas.dir1;
          before.radios.forEach(r => { if (r.antennaTypeId === 'dir1') r.antennaTypeId = 'oldPanel'; });
          E('(function(b){ baseline = b; baselineName = "Invented Before.esx"; })')(before);
          const row = (render('audit', {}).match(/Directional APs<\/td>([\s\S]*?)<\/tr>/) || [])[1] || '';
          eq('before, after, change', row.replace(/<[^>]+>/g, ' ').trim().split(/\s+/), ['3', '3', '0']);
        """)


class TheTitleOnThePageIsTheNameOnTheFile(ReportCase):

    def test_cover_header_and_footer_match_the_document_title(self):
        self.run_block(r"""
          open();
          E('(function(){ fileName = "Main Campus - Building C.esx"; projectFolder = ""; })')();
          document.getElementById('optCover').checked = true;
          let html = render('summary', {});
          eq('cover title', (html.match(/rep-cover-title">([^<]*)/) || [])[1], 'Main Campus - Building C');
          eq('document title', document.title, 'Report - Site Summary - Main Campus - Building C');
          document.getElementById('optCover').checked = false;
          html = render('summary', {});
          eq('header strip title', (html.match(/rep-doc-title">([^<]*)/) || [])[1], 'Main Campus - Building C');
          html = render('location', {});
          eq('footer title', (html.match(/rep-foot-title">([^<]*)/) || [])[1], 'AP Installation — Main Campus - Building C');
        """)

    def test_a_generic_file_name_gives_way_to_the_folder_on_the_cover_too(self):
        self.run_block(r"""
          open();
          E('(function(){ fileName = "final.esx"; projectFolder = "Invented Clinic North"; })')();
          document.getElementById('optCover').checked = true;
          const html = render('summary', {});
          eq('cover title', (html.match(/rep-cover-title">([^<]*)/) || [])[1], 'Invented Clinic North');
          eq('document title', document.title, 'Report - Site Summary - Invented Clinic North');
        """)


class ResetToShippedDefaultsResetsOnlyThePanel(ReportCase):

    def test_grid_crop_and_typed_text_survive_and_review_rebuilds(self):
        self.run_block(r"""
          open();
          E('(function(){ settingsAvailable = true; applySettingsPayload({ report_defaults: { location: { inclOmni: true, compass: false } } }); })')();
          window.selectReport('location');
          E('(function(){ currentOpts.segCols = 3; currentOpts.segRows = 2; currentOpts.cropBoxes = { fA: { x: 0, y: 0, w: 0.5, h: 1 } }; currentOpts.clientName = "Invented Client B"; optOverrides.clientName = true; currentOpts.pageOrient = { cover: "landscape" }; })')();
          E('configureDirty = false');
          window.clearReportOptionDefaults();
          await sleep(50);
          const o = E('currentOpts');
          eq('the grid', [o.segCols, o.segRows], [3, 2]);
          eq('the crop', o.cropBoxes, { fA: { x: 0, y: 0, w: 0.5, h: 1 } });
          eq('the typed client name', o.clientName, 'Invented Client B');
          eq('still marked as this report\'s own', E('optOverrides.clientName'), true);
          eq('the page turned this session', o.pageOrient, { cover: 'landscape' });
          eq('compass is back to shipped', E('collectOpts()').compass, true);
          eq('the saved defaults are gone', 'location' in lastSaved(), false);
          eq('Review will rebuild', E('configureDirty'), true);
        """)


class TheApPanelActsOnWhatItShows(ReportCase):

    def test_toggle_all_leaves_aps_the_search_hides(self):
        self.run_block(r"""
          open();
          window.selectReport('location');
          window.setGroupBy('floor');
          window.setApSearch('AP1');
          window.toggleGroupAll('fA');
          eq('only the shown Ground APs are unticked', [...E('apDisabled')].sort(), ['ap1', 'ap11']);
          window.setApSearch('');
        """)

    def test_toggle_all_leaves_aps_the_omni_filter_hides(self):
        self.run_block(r"""
          open();
          window.selectReport('aim');          // directional only
          window.setGroupBy('floor');
          window.toggleGroupAll('fB');
          eq('only the directional Upper APs are unticked', [...E('apDisabled')].sort(), ['ap10', 'ap6', 'ap7']);
        """)

    def test_the_count_keeps_the_filter_after_a_tick(self):
        self.run_block(r"""
          open();
          window.selectReport('aim');
          eq('before', els.apCount.textContent, '3 of 3 checked (8 hidden by filter)');
          window.toggleAp({ getAttribute() { return 'ap6'; }, checked: false });
          eq('after unticking one', els.apCount.textContent, '2 of 3 checked (8 hidden by filter)');
        """)


class UnitsAreTheChosenOnes(ReportCase):

    def test_placement_labels_follow_the_metric_setting(self):
        self.run_block(r"""
          open();
          E('unitsPref = "meters"');
          const html = render('placement', { labelHeight: true });
          check('a height in metres on the labels', /3\.00 m\b/.test(html));
          check('no feet on the labels', !/\d ft\b/.test(html));
        """)

    def test_metric_heights_carry_two_decimals(self):
        self.run_block(r"""
          const p = project(); p.radios.forEach(r => { r.antennaHeight = 3.048; });
          open(p);
          E('unitsPref = "meters"');
          let html = render('location', { units: 'meters', inclOmni: true });
          check('AP Installation: 3.05 m', html.includes('3.05 m'));
          check('AP Installation: no 3.0 m', !html.includes('3.0 m'));
          html = render('aim', { units: 'meters' });
          check('Aim sheet: 3.05 m', html.includes('3.05 m'));
          html = render('placement', { labelHeight: true });
          check('Placement labels: 3.05 m', html.includes('3.05 m'));
        """)

    def test_the_coverage_sizing_table_follows_the_feet_setting(self):
        self.run_block(r"""
          open();
          E('unitsPref = "feet"');
          const html = render('coverage', { inclOmni: true });
          const table = floorPart(html, 'Cell sizing per AP', '</table>');
          check('radii in feet', / ft<\/td>/.test(table));
          check('no radii in metres', !/ m<\/td>/.test(table));
        """)


class SmallerFixesFromTheSecondReview(ReportCase):

    def test_the_aim_sheet_gives_an_omni_ap_no_azimuth(self):
        self.run_block(r"""
          const p = project();
          p.radios.forEach(r => { if (r.antennaDirection == null) { r.antennaDirection = 0; r.antennaTilt = 0; } });
          open(p);
          const html = render('aim', { inclOmni: true });
          const omni = (html.match(/<td class="rep-name">Zed-AP1<\/td>[\s\S]*?<\/tr>/) || [''])[0];
          check('omni Zed-AP1 reads omni: ' + omni, omni.includes('>omni<'));
          check('omni Zed-AP1 has no compass bearing: ' + omni, !omni.includes('(N)'));
          const aimed = (html.match(/<td class="rep-name">Zed-AP6<\/td>[\s\S]*?<\/tr>/) || [''])[0];
          check('directional Zed-AP6 keeps its bearing: ' + aimed, aimed.includes('90°'));
        """)

    def test_the_contents_promise_no_sections_for_a_floor_with_no_image(self):
        self.run_block(r"""
          document.getElementById('optCover').checked = true;
          const p = project(); delete p.imageUrls.imA;
          open(p);
          const html = render('location', { inclOmni: true, segmented: true, segCols: 2, segRows: 2 });
          const toc = floorPart(html, '<section class="rep-floor-section rep-toc">', '</section>');
          const ground = floorPart(toc, '<b>Ground Sample</b>', '</li>');
          check('no detail sections promised: ' + ground, ground.indexOf('detail section') < 0);
          check('no floor plan promised: ' + ground, ground.indexOf('AP placements') < 0);
          const upper = floorPart(toc, '<b>Upper Sample</b>', '</li>');
          check('a floor with its image still lists its sections: ' + upper,
                upper.indexOf('AP placement') >= 0);
        """)

    def test_2484_mhz_prints_as_channel_14(self):
        self.run_block(r"""
          const p = project();
          p.radios[0].channelByCenterFrequencyDefinedNarrowChannels = [2484];
          open(p);
          const row = floorPart(render('location', { inclOmni: true }), 'Zed-AP1<', '</tr>');
          check('channel 14: ' + row, row.includes('>14 <span'));
          check('not 15: ' + row, !row.includes('>15 <span'));
        """)


if __name__ == "__main__":
    unittest.main()
