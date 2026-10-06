"""What a sweep of every report, over a library of deliberately awkward
projects, found - and the guard for each.

The sweep opened eleven invented projects in the real Report page (one with
only omni APs, one with HTML in every name, one with a survey, one 600 x 6000
plan, an empty one ...), pushed every option of every report through its real
control, and printed each result to PDF to measure it. The DOM stayed clean
throughout; what was wrong only showed on paper or in what the tool offered:

* **Interference: the device table printed with equal columns**, so the
  longest category chip was clipped to "Wide-channel W", a 17-character BSSID
  wrapped mid-address, and "Seen on" read "Fl <floor>".
* **Interference: a floor said "4 interferers detected" over one name.** Only
  Medium and High are named above the map; nothing said the rest were not.
* **The cover voted on keyed pages only.** A BOM, Summary or Coverage report
  has one keyed page - its landscape AP Notes - and five unkeyed portrait
  ones, so the cover turned landscape in front of them.
* **A sheet of one line after a landscape last page.** The closing credit
  sits outside every section on the document's own portrait page, so a
  landscape notes page before it forced a new sheet for the footer alone.
* **The gallery offered Interference on a project with no survey** - an
  "Available" card that opened a page saying there is nothing to report.

Every test drives the real `report.js`. The cover and footer rules need a DOM,
which the stub does not have, so those two run against a tiny tree that
implements exactly the calls the real functions make.
"""
from __future__ import annotations

import unittest

from tests.test_report_prints_what_the_design_holds import ReportCase

SURVEY = r"""
function surveyProject() {
  const p = project();
  p.measurements = [
    { id: 'm1', ssid: 'Wide Sample', mac: '02:00:00:00:00:01', security: 'Personal',
      channelByCenterFrequencyDefinedNarrowChannels: [5180, 5200, 5220, 5240] },
    { id: 'm2', ssid: "Sample's iPhone", mac: '02:00:00:00:00:02',
      channelByCenterFrequencyDefinedNarrowChannels: [5180] },
    { id: 'm3', ssid: 'HotspotAB12', mac: '02:00:00:00:00:03',
      channelByCenterFrequencyDefinedNarrowChannels: [2437] },
    { id: 'm4', ssid: 'MiFi Sample 9', mac: '02:00:00:00:00:04',
      channelByCenterFrequencyDefinedNarrowChannels: [2412] },
  ];
  p.surveys = [{ id: 's1', floorPlanId: 'fA', routePoints: [],
    wifiTracks: [{ accessPointMeasurementIds: ['m1', 'm2', 'm3', 'm4'] }] }];
  return p;
}
"""


class InterferenceTablePrintsWhatItHolds(ReportCase):

    def test_every_column_has_a_width_and_the_bssid_stays_whole(self):
        self.run_block(SURVEY + r"""
          open(surveyProject());
          const html = render('interference', {});
          const t = floorPart(html, '<table class="rep-ap-table rep-hotspot-table">', '</table>');
          const heads = (t.match(/<th[^>]*>[^<]*<\/th>/g) || []).map(h => h.replace(/<[^>]+>/g, ''));
          const widths = (t.match(/<col style="width:([\d.]+)%">/g) || [])
            .map(s => parseFloat(s.replace(/[^\d.]/g, '')));
          eq('one width per column', widths.length, heads.length);
          check('widths add to 100%: ' + widths, Math.abs(widths.reduce((a, b) => a + b, 0) - 100) < 0.01);
          const cat = widths[heads.indexOf('Category')], bssid = widths[heads.indexOf('BSSID')];
          check('Category is wide enough for "Wide-channel Wi-Fi": ' + cat, cat >= 14);
          check('BSSID is wide enough for 17 characters: ' + bssid, bssid >= 15);
          check('the BSSID cell cannot wrap', t.indexOf('class="rep-az rep-bssid"') >= 0);
          check('"Seen on" is the floor, not "Fl <floor>"', t.indexOf('Fl Ground') < 0
                && t.indexOf('>Ground Sample<') >= 0);
          const withChannel = render('interference', { channel: true });
          const t2 = floorPart(withChannel, '<table class="rep-ap-table rep-hotspot-table">', '</table>');
          const heads2 = (t2.match(/<th[^>]*>[^<]*<\/th>/g) || []);
          const w2 = (t2.match(/<col style="width:([\d.]+)%">/g) || []).map(s => parseFloat(s.replace(/[^\d.]/g, '')));
          eq('Channel(s) adds a column and a width', [heads2.length, w2.length], [heads.length + 1, heads.length + 1]);
          check('widths still add to 100% with Channel(s): ' + w2, Math.abs(w2.reduce((a, b) => a + b, 0) - 100) < 0.01);
        """)

    def test_the_table_is_a_page_that_can_turn_like_the_other_tables(self):
        self.run_block(SURVEY + r"""
          open(surveyProject());
          const html = render('interference', {});
          check('it carries a page key and kind',
                html.indexOf('data-page-key="hotspot-table" data-page-kind="table"') >= 0);
          check('it has the Auto / Portrait / Landscape picker',
                html.indexOf('data-for="hotspot-table"') >= 0);
        """)

    def test_the_floor_map_says_how_many_low_severity_it_leaves_unnamed(self):
        self.run_block(SURVEY + r"""
          open(surveyProject());
          const html = render('interference', { overview: true });
          const sec = floorPart(html, '<h2 class="rep-floor-title">Ground Sample', '</section>');
          check('the floor heading counts all four: ' + sec.slice(0, 200),
                /4 interferers detected/.test(sec));
          check('only the High one is named', sec.indexOf('Wide Sample') >= 0
                && sec.indexOf('HotspotAB12') < 0);
          check('it says the other three are not listed: ' + sec.slice(0, 700),
                /3 low-severity not listed/.test(sec));
          check('the heading is the floor name, not "Floor " + name',
                sec.indexOf('Floor Ground Sample') < 0);
        """)


FAKE_DOM = r"""
/* The calls orientCover and seatFooter make, and no others. Order numbers
   stand in for document position. */
let order = 0;
function el(tag, classes, attrs) {
  const n = { tagName: tag, cls: new Set(classes || []), attrs: attrs || {}, children: [],
              parentElement: null, order: order++ };
  n.classList = {
    contains: c => n.cls.has(c),
    add: c => { n.cls.add(c); },
    toggle(c, on) { if (on) n.cls.add(c); else n.cls.delete(c); },
  };
  n.getAttribute = k => (k in n.attrs ? n.attrs[k] : null);
  n.setAttribute = (k, v) => { n.attrs[k] = String(v); };
  n.inserted = [];
  n.insertAdjacentHTML = (where, html) => { n.inserted.push([where, html]); };
  n.textContent = '';
  n.compareDocumentPosition = o => (o.order > n.order ? 4 : 2);
  n.appendChild = c => {
    if (c.parentElement) c.parentElement.children.splice(c.parentElement.children.indexOf(c), 1);
    c.parentElement = n; n.children.push(c); c.order = order++; return c;
  };
  Object.defineProperty(n, 'previousElementSibling', { get() {
    const sib = n.parentElement ? n.parentElement.children : [];
    return sib[sib.indexOf(n) - 1] || null;
  }});
  const all = () => n.children.reduce((a, c) => a.concat([c], c.all()), []);
  n.all = all;
  n.querySelector = sel => n.querySelectorAll(sel)[0] || null;
  n.querySelectorAll = sel => {
    const keep = sel === '[data-page-key]' ? c => 'data-page-key' in c.attrs
      : sel === '[data-page-kind="cover"]' ? c => c.attrs['data-page-kind'] === 'cover'
      : sel === '.rep-seg-cell' ? c => c.cls.has('rep-seg-cell')
      : sel === '.rep-orient-now' ? c => c.cls.has('rep-orient-now')
      : sel === '.rep-floor-title' ? c => c.cls.has('rep-floor-title')
      : sel === 'table' ? c => c.tagName === 'TABLE'
      : () => false;
    return all().filter(keep);
  };
  return n;
}
function adopt(parent, kids) { kids.forEach(k => parent.appendChild(k)); return parent; }
function section(landscape, key) {
  const attrs = key ? { 'data-page-key': key, 'data-page-kind': 'table' } : {};
  return el('SECTION', landscape ? ['rep-floor-section', 'rep-oriented', 'is-landscape']
                                 : ['rep-floor-section'], attrs);
}
function cover() { return el('SECTION', ['rep-cover', 'rep-oriented'], { 'data-page-key': 'cover', 'data-page-kind': 'cover' }); }
function footer() { return el('FOOTER', ['rep-doc-foot']); }
"""


class TheCoverAndFooterFollowTheSheetsThatPrint(ReportCase):

    def test_five_portrait_sheets_outvote_one_landscape_notes_page(self):
        """BOM, Summary and Coverage: one keyed landscape page, five unkeyed
        portrait ones. The cover must follow the five."""
        self.run_block(FAKE_DOM + r"""
          const orientCover = E('orientCover');
          const host = adopt(el('DIV'), [cover(), section(false), section(false), section(false),
            section(false), section(false), section(true, 'notes:fl-0'), footer()]);
          orientCover(host, {});
          check('the cover is portrait', !host.children[0].cls.has('is-landscape'));
        """)

    def test_a_report_of_landscape_sheets_still_gets_a_landscape_cover(self):
        self.run_block(FAKE_DOM + r"""
          const orientCover = E('orientCover');
          const host = adopt(el('DIV'), [cover(), section(true, 'placement:a'),
            section(true, 'placement:b'), section(false, 'key:a'), footer()]);
          orientCover(host, {});
          check('the cover is landscape', host.children[0].cls.has('is-landscape'));
        """)

    def test_a_tie_goes_to_the_sheet_bound_against_the_cover(self):
        self.run_block(FAKE_DOM + r"""
          const orientCover = E('orientCover');
          let host = adopt(el('DIV'), [cover(), section(true, 'a'), section(false), footer()]);
          orientCover(host, {});
          check('landscape first, so landscape', host.children[0].cls.has('is-landscape'));
          host = adopt(el('DIV'), [cover(), section(false), section(true, 'a'), footer()]);
          orientCover(host, {});
          check('portrait first, so portrait', !host.children[0].cls.has('is-landscape'));
        """)

    def test_a_cover_set_by_hand_is_left_alone(self):
        self.run_block(FAKE_DOM + r"""
          const orientCover = E('orientCover');
          const host = adopt(el('DIV'), [cover(), section(false), section(false), footer()]);
          orientCover(host, { pageOrient: { cover: 'landscape' } });
          check('landscape because it was asked for', host.children[0].cls.has('is-landscape'));
        """)

    def test_the_footer_moves_into_a_landscape_last_page(self):
        self.run_block(FAKE_DOM + r"""
          const seatFooter = E('seatFooter');
          const notes = section(true, 'notes:fl-0');
          const inner = footer();                    // the notes page's own footer
          notes.appendChild(inner);
          const root = footer();
          const host = adopt(el('DIV'), [cover(), section(false), notes, root]);
          seatFooter(host);
          check('the document footer is inside the notes page', root.parentElement === notes);
          check('the notes page keeps its own footer', inner.parentElement === notes);
          check('nothing follows the notes page at the root',
                host.children[host.children.length - 1] === notes);
        """)

    def test_the_footer_stays_put_after_a_portrait_last_page(self):
        self.run_block(FAKE_DOM + r"""
          const seatFooter = E('seatFooter');
          const root = footer();
          const host = adopt(el('DIV'), [cover(), section(false), section(false), root]);
          seatFooter(host);
          check('still a direct child', root.parentElement === host);
        """)

    def test_seating_twice_changes_nothing(self):
        self.run_block(FAKE_DOM + r"""
          const seatFooter = E('seatFooter');
          const notes = section(true, 'notes:fl-0');
          const root = footer();
          const host = adopt(el('DIV'), [cover(), notes, root]);
          seatFooter(host); seatFooter(host);
          eq('one footer in the notes page', notes.children.length, 1);
        """)


class TheGalleryOffersOnlyWhatCanWork(ReportCase):

    def test_interference_is_marked_when_the_project_has_no_survey(self):
        self.run_block(r"""
          open();                                         // a design: no measurements
          E('renderTemplateGallery')();
          const html = els.templateGallery.innerHTML;
          const card = floorPart(html, 'tpl-interference', 'tpl-bom');
          check('named', card.indexOf('Interference / Rogue Devices') >= 0);
          check('marked, not "Available": ' + card.slice(0, 400),
                card.indexOf('Not for this project') >= 0 && card.indexOf('>Available<') < 0);
          check('with the reason on the card', /no survey walk/.test(card));
          check('and nothing to click', card.slice(0, card.indexOf('rep-template-card-top'))
                .indexOf('data-fn="selectReport"') < 0);
          const other = floorPart(html, 'tpl-summary', 'tpl-coverage');
          check('every other card is untouched', other.indexOf('>Available<') >= 0);
        """)

    def test_selecting_it_is_refused_with_the_reason(self):
        self.run_block(r"""
          open();
          const before = E('currentReportId');
          window.selectReport('interference');
          eq('the report did not change', E('currentReportId'), before);
          check('the reason was shown: ' + JSON.stringify(toasts),
                toasts.some(t => /no survey walk/.test(t.msg)));
        """)

    def test_it_is_offered_when_the_project_has_a_survey(self):
        self.run_block(SURVEY + r"""
          open(surveyProject());
          E('renderTemplateGallery')();
          const card = floorPart(els.templateGallery.innerHTML, 'tpl-interference', 'tpl-bom');
          check('available: ' + card.slice(0, 300), card.indexOf('>Available<') >= 0);
          window.selectReport('interference');
          eq('selected', E('currentReportId'), 'interference');
        """)

    def test_a_project_with_no_access_points_offers_only_what_can_say_something(self):
        self.run_block(r"""
          const p = project(); p.accessPoints = []; p.radios = [];
          open(p);
          const why = E('reportUnavailableReason');
          ['placement', 'aim', 'location', 'bom', 'coverage', 'design'].forEach(id =>
            check(id + ' is marked', /no access points/.test(why(id))));
          eq('the summary still works', why('summary'), '');
          eq('so does the audit', why('audit'), '');
        """)

    def test_the_aim_sheet_is_not_refused_for_an_all_omni_project(self):
        """Its own 'Include omni APs' option lists them, so refusing would
        take away something that works."""
        self.run_block(r"""
          open();
          eq('aim is offered', E('reportUnavailableReason')('aim'), '');
        """)


class SharedHelpersTheReportsRelyOn(ReportCase):

    def test_a_street_number_is_not_a_storey_and_a_floor_word_after_an_underscore_is(self):
        """"200 Sample TF_Overall Plan" headed its sheet "Floor 200", and
        "Block B_Level 02" - a floor word after an underscore - was missed."""
        self.run_block(r"""
          const n = WD.storeyNumber;
          eq('a street number', n('200 Sample TF_Overall Plan background', null, []), null);
          eq('a three-digit leading number', n('120 Main', null, []), null);
          eq('a CAD sheet name', n('Block B_Level 02 RCP', null, []), 2);
          eq('an ordinary floor word', n('Level 4', null, []), 4);
          eq('an ordinal', n('3rd Floor', null, []), 3);
          eq('a short leading number is still a storey', n('01 - Ground', null, []), 1);
          eq('no digit run from a longer number', n('2026 plan', null, []), null);
        """)

    def test_floors_come_in_building_then_storey_order_not_name_order(self):
        self.run_block(r"""
          const p = project();
          p.floorPlans = [
            { id: 'a', name: 'Floor 2 Mezzanine', width: 100, height: 100 },
            { id: 'b', name: 'Floor 1 Warehouse Level 1', width: 100, height: 100 },
            { id: 'c', name: 'Yard', width: 100, height: 100 },
            { id: 'd', name: 'Level 1', width: 100, height: 100 },
          ];
          p.buildings = { w: { id: 'w', name: 'Warehouse' }, o: { id: 'o', name: 'Office' } };
          p.buildingFloors = {
            a: { buildingId: 'w', floorPlanId: 'a' }, b: { buildingId: 'w', floorPlanId: 'b' },
            d: { buildingId: 'o', floorPlanId: 'd' },
          };
          open(p);
          const order = E('sortedFloorOrder')({}).map(f => f.id);
          eq('Office, then Warehouse by storey, then the unbuilt plan', order, ['d', 'b', 'a', 'c']);
        """)

    def test_an_ap_with_no_radio_is_not_called_directional(self):
        self.run_block(r"""
          const p = project();
          p.accessPoints.push({ id: 'bare', name: 'Bare AP', location: { floorPlanId: 'fA', coord: { x: 5, y: 5 } }, noteIds: [] });
          open(p);
          eq('no radio, so nothing to aim', E('apIsOmniOnly')(p.accessPoints[p.accessPoints.length - 1]), true);
          const html = render('aim', {});
          check('it is not on the Aim Sheet by default: ' + html.slice(0, 200), html.indexOf('Bare AP') < 0);
        """)


LISTENING_PRELUDE_FROM = "addEventListener(){}, removeEventListener(){},\n  matchMedia"
LISTENING_PRELUDE_TO = ("addEventListener(t, f){ (window.__listeners = window.__listeners || {})[t] = f; }, "
                        "removeEventListener(){},\n  matchMedia")


class APrintedReportIsOnWhitePaper(ReportCase):
    """The app opens dark. Printing from it put dark-theme colours on white:
    the BOM's procurement notes at about 2.4:1 with the bold word at 1.2:1,
    dark chips and stat cards, and near-black margins on a PDF saved with
    background graphics on. The page is the light theme while it prints."""

    def run_listening(self, checks: str):
        from tests import test_report_prints_what_the_design_holds as base
        self.assertIn(LISTENING_PRELUDE_FROM, base.PRELUDE,
                      "the shared prelude moved; this test captures listeners through it")
        original = base.PRELUDE
        base.PRELUDE = original.replace(LISTENING_PRELUDE_FROM, LISTENING_PRELUDE_TO)
        try:
            self.run_block(checks)
        finally:
            base.PRELUDE = original

    def test_the_page_registers_for_both_print_events(self):
        self.run_listening(r"""
          check('beforeprint is listened for', typeof (window.__listeners || {}).beforeprint === 'function');
          check('afterprint is listened for', typeof (window.__listeners || {}).afterprint === 'function');
        """)

    def test_printing_switches_to_light_and_afterwards_puts_the_theme_back(self):
        self.run_listening(r"""
          const root = document.documentElement;
          root.setAttribute('data-theme', 'dark');
          window.__listeners.beforeprint();
          eq('light while printing', root.getAttribute('data-theme'), 'light');
          window.__listeners.beforeprint();                       // a second event changes nothing
          window.__listeners.afterprint();
          eq('dark again afterwards', root.getAttribute('data-theme'), 'dark');
          root.setAttribute('data-theme', 'light');
          window.__listeners.beforeprint(); window.__listeners.afterprint();
          eq('a light page stays light', root.getAttribute('data-theme'), 'light');
          let stored = null;
          try { stored = localStorage.getItem('wd-theme'); } catch (e) {}
          eq('the stored choice is never written', stored, null);
        """)


class AnEmptyProjectSaysSo(ReportCase):

    def test_a_project_with_no_access_points_does_not_say_to_drop_a_file(self):
        self.run_block(r"""
          const p = project(); p.accessPoints = []; p.radios = [];
          open(p);                                         // a file IS open
          const html = render('location', {});
          check('it says what is true: ' + html, /no access points in it/.test(html));
          check('it does not send anyone to re-open the file', html.indexOf('Drop an .esx') < 0);
        """)

    def test_with_nothing_open_the_drop_message_is_still_there(self):
        self.run_block(r"""
          const none = { accessPoints: [], radios: [], antennas: {}, floorPlans: [], buildings: {}, buildingFloors: {}, images: {}, imageUrls: {}, measurements: [], measuredRadios: [], surveys: [], projectName: '' };
          E('(function (p) { proj = p; fileName = ""; })')(none);
          const html = render('location', {});
          check('drop message with no file: ' + html, html.indexOf('Drop an .esx') >= 0);
        """)


class CoverageIsHonestAboutWhatItDraws(ReportCase):

    def test_two_aps_on_one_spot_get_two_readable_numbers(self):
        self.run_block(r"""
          const p = project();
          // Zed-AP1 is at (100,100) on fA; put another AP exactly on it.
          p.accessPoints.push({ id: 'twin', name: 'Twin-AP', location: { floorPlanId: 'fA', coord: { x: 100, y: 100 } }, noteIds: [] });
          p.radios.push({ id: 'rt', accessPointId: 'twin', radioTechnology: 'IEEE802_11', antennaTypeId: 'omni1',
            transmitPower: 15, channelByCenterFrequencyDefinedNarrowChannels: [5180] });
          open(p);
          const html = render('coverage', {});
          const ground = floorPart(html, 'data-floor-id="fA"', 'data-floor-id="fB"');
          const spots = (ground.match(/class="rep-cov-mark" transform="translate\(([^)]*)\)"/g) || []);
          eq('every AP has a number box', spots.length, 7);
          eq('no two boxes on the same spot', new Set(spots).size, spots.length);
          check('the moved one says which AP it belongs to', ground.indexOf('class="rep-cov-lead"') >= 0);
        """)

    def test_a_default_is_starred_not_printed_as_a_stored_value(self):
        self.run_block(r"""
          open();                                  // Zed-AP2 has transmitPower null
          const html = render('coverage', {});
          const row = floorPart(html, 'Zed-AP2<', '</tr>');
          check('the assumed power carries a star: ' + row, /15 dBm\*/.test(row));
          const stored = floorPart(html, 'Zed-AP1<', '</tr>');
          check('a stored power does not', /20 dBm</.test(stored) && stored.indexOf('dBm*') < 0);
          check('the page says what the star means', /stores no value for this/.test(html));
        """)

    def test_a_floor_with_no_scale_draws_no_invented_cell(self):
        self.run_block(r"""
          const p = project();
          delete p.floorPlans[1].metersPerUnit;
          open(p);
          const html = render('coverage', {});
          const upper = floorPart(html, 'data-floor-id="fB"');
          check('no cell circles on the unscaled floor', upper.split('Methodology')[0].indexOf('class="rep-cov-cell"') < 0);
          check('the numbers are still there', upper.indexOf('class="rep-cov-mark"') >= 0);
          check('it says why: ', /has no scale/.test(upper));
          const ground = floorPart(html, 'data-floor-id="fA"', 'data-floor-id="fB"');
          check('a scaled floor still draws its cells', ground.indexOf('class="rep-cov-cell"') >= 0);
        """)

    def test_only_aps_that_are_drawn_are_numbered_and_the_rest_are_named(self):
        self.run_block(r"""
          const p = project();
          p.accessPoints.push({ id: 'bare', name: 'Bare-AP', location: { floorPlanId: 'fA', coord: { x: 10, y: 10 } }, noteIds: [] });
          p.accessPoints.push({ id: 'adrift', name: 'Adrift-AP', noteIds: [] });
          p.radios.push({ id: 'ra', accessPointId: 'adrift', radioTechnology: 'IEEE802_11', antennaTypeId: 'omni1' });
          open(p);
          const html = render('coverage', {});
          const nums = (html.match(/<td class="rep-num">(\d+)<\/td>/g) || []).map(x => +x.replace(/\D/g, ''));
          eq('the table numbers run 1..n with no gap', nums, nums.map((_, i) => i + 1));
          check('both are named under the table: ' + html.slice(html.indexOf('Not on the map'), html.indexOf('Not on the map') + 200),
                /Not on the map \(2\)/.test(html) && html.indexOf('Bare-AP \u2014 no radio') >= 0
                && html.indexOf('Adrift-AP \u2014 on no floor plan') >= 0);
        """)

    def test_a_tri_band_ap_is_drawn_from_its_5_ghz_radio_and_says_so(self):
        self.run_block(r"""
          const p = project();
          // Zed-AP1: add a 2.4 GHz radio BEFORE its 5 GHz one in file order, and a 6 GHz one.
          p.radios.unshift({ id: 'r24', accessPointId: 'ap1', radioTechnology: 'IEEE802_11', antennaTypeId: 'omni1',
            transmitPower: 20, channelByCenterFrequencyDefinedNarrowChannels: [2412] });
          p.radios.push({ id: 'r6', accessPointId: 'ap1', radioTechnology: 'IEEE802_11', antennaTypeId: 'omni1',
            transmitPower: 20, channelByCenterFrequencyDefinedNarrowChannels: [5975] });
          open(p);
          const row = floorPart(render('coverage', {}), 'Zed-AP1<', '</tr>');
          check('5 GHz, not the first-listed 2.4: ' + row, row.indexOf('5 GHz') >= 0 && row.indexOf('2.4 GHz') < 0);
          check('it names how many radios there are', /1 of 3 radios/.test(row));
        """)


class EveryPageCanBeTurned(ReportCase):
    """"Match all pages" and the per-page picker went straight past every
    section that had no page key - a BOM's tables, the Summary, the Coverage
    legend. They always printed portrait between landscape sheets."""

    def test_an_unkeyed_section_gets_a_key_a_kind_and_a_picker(self):
        self.run_block(FAKE_DOM + r"""
          E('(function () { currentReportId = "bom"; })')();
          const keyEveryPage = E('keyEveryPage');
          const withTable = section(false);
          const heading = el('H2', ['rep-floor-title']); heading.textContent = 'Access point quantities (12)';
          withTable.appendChild(heading); withTable.appendChild(el('TABLE'));
          const plain = section(false);
          const host = adopt(el('DIV'), [cover(), withTable, plain, footer()]);
          keyEveryPage(host, {});
          eq('named for its heading, count dropped', withTable.attrs['data-page-key'], 'sec:bom:access-point-quantities');
          eq('a table is a table page', withTable.attrs['data-page-kind'], 'table');
          check('it is an oriented page', withTable.cls.has('rep-oriented'));
          check('it has the Auto / Portrait / Landscape picker',
                withTable.inserted.length === 1 && /data-for="sec:bom:access-point-quantities"/.test(withTable.inserted[0][1]));
          eq('a page with no table is a text page', plain.attrs['data-page-kind'], 'text');
          check('with no heading it still gets a distinct key', /^sec:bom:page-/.test(plain.attrs['data-page-key']));
          check('the cover and footer are left alone', host.children[0].inserted.length === 0 && !('data-page-key' in host.children[3].attrs));
        """)

    def test_a_page_that_already_has_a_key_is_left_alone(self):
        self.run_block(FAKE_DOM + r"""
          const keyEveryPage = E('keyEveryPage');
          const keyed = section(true, 'placement:fA');
          const host = adopt(el('DIV'), [cover(), keyed, footer()]);
          keyEveryPage(host, {});
          eq('same key', keyed.attrs['data-page-key'], 'placement:fA');
          eq('no second picker', keyed.inserted.length, 0);
        """)

    def test_two_pages_with_one_heading_get_two_keys(self):
        self.run_block(FAKE_DOM + r"""
          E('(function () { currentReportId = "design"; })')();
          const keyEveryPage = E('keyEveryPage');
          function titled(t) { const s = section(false); const h = el('H2', ['rep-floor-title']); h.textContent = t; s.appendChild(h); return s; }
          const a = titled('Findings'), b = titled('Findings');
          keyEveryPage(adopt(el('DIV'), [cover(), a, b, footer()]), {});
          check('distinct: ' + a.attrs['data-page-key'] + ' / ' + b.attrs['data-page-key'],
                a.attrs['data-page-key'] !== b.attrs['data-page-key']);
        """)

    def test_match_all_pages_reaches_a_section_that_had_no_key(self):
        """The whole point: after keying, matchAllPageOrient finds every page."""
        self.run_block(FAKE_DOM + r"""
          // The real handler reads the page's DOM; drive the two calls it makes.
          const keyEveryPage = E('keyEveryPage');
          E('(function () { currentReportId = "summary"; })')();
          const plain = section(false), other = section(false);
          const host = adopt(el('DIV'), [cover(), plain, other, footer()]);
          keyEveryPage(host, {});
          const keys = host.querySelectorAll('[data-page-key]').map(n => n.attrs['data-page-key']);
          eq('three pages carry a key: the cover and both sections', keys.length, 3);
        """)


class EverythingInAPageNamesItsPage(unittest.TestCase):
    """Measured in Firefox 157 through its own print pipeline (geckodriver's
    Print Page). A sectioned floor set to Match-all-landscape printed
    ``LLLLPPPPPLLLLL`` - the first section landscape, every later one portrait -
    and a 150-row Coverage table printed ``LLLLLLLLPPLLLLL``, its later sheets
    portrait with the right-hand column clipped; Chromium printed all landscape
    in both. A sheet takes its name from the first box on it, and a sheet that
    starts part-way through a page starts on a row or a cell, whose own name is
    the unnamed default. Naming every descendant gave all landscape. What CI can
    hold is that the rule is still there, for both orientations, after the rule
    that names the page itself."""

    def setUp(self):
        from pathlib import Path
        self.css = (Path(__file__).resolve().parent.parent / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")

    def test_every_descendant_of_a_page_carries_the_pages_name(self):
        import re
        page_p = re.search(r"\.rep-oriented \{ page: placementPortrait; \}", self.css)
        page_l = re.search(r"\.rep-oriented\.is-landscape \{ page: placementLandscape; \}", self.css)
        kids_p = re.search(r"\.rep-oriented \* \{ page: placementPortrait; \}", self.css)
        kids_l = re.search(r"\.rep-oriented\.is-landscape \* \{ page: placementLandscape; \}", self.css)
        self.assertTrue(page_p and page_l, "the page's own name moved")
        self.assertTrue(kids_p, "a sheet that starts on a row has no portrait name of its own")
        self.assertTrue(kids_l, "a sheet that starts on a row has no landscape name of its own")
        self.assertLess(kids_p.start(), kids_l.start(), "landscape must come after portrait to win")


class AMapNumberIsReadableOnEitherSheet(ReportCase):
    """Found by forcing a 600 x 6000 plan to landscape: its long edge then
    prints in 5.75in and a number sized at 1.35% of it came out at 5.6pt."""

    def test_the_floor_leaves_a_number_at_least_6pt_on_the_worst_landscape_sheet(self):
        self.run_block(r"""
          const frac = E('MAP_FONT_FLOOR_FRAC');
          const worstLongEdgeIn = E('SHEET_W_IN') - E('SHEET_CHROME_IN') - E('SHEET_SLACK_IN');
          const pt = frac * worstLongEdgeIn * 72;
          check('a 6pt floor on the worst sheet, got ' + pt.toFixed(2) + 'pt', pt >= 6);
        """)

    def test_the_coverage_number_uses_it_on_a_tall_plan(self):
        self.run_block(r"""
          const p = project();
          p.floorPlans[0].width = 600; p.floorPlans[0].height = 6000;
          p.accessPoints.forEach(a => { if (a.location.floorPlanId === 'fA') { a.location.coord = { x: 300, y: 3000 }; } });
          open(p);
          const html = render('coverage', {});
          const ground = floorPart(html, 'data-floor-id="fA"', 'data-floor-id="fB"');
          const m = ground.match(/class="rep-cov-num"[^>]*font-size="([\d.]+)"/);
          const floor = 6000 * E('MAP_FONT_FLOOR_FRAC');
          check('the number is at least the floor on the 6000-unit edge: ' + (m && m[1]) + ' vs ' + floor, m && parseFloat(m[1]) >= floor - 0.01);
        """)


    def test_the_section_letters_on_an_ultra_wide_plan_are_not_sized_from_its_short_edge(self):
        """Sized from the shorter cell edge, a letter on a 9000 x 500 plan came
        out at 4.5pt on a portrait sheet."""
        self.run_block(r"""
          const p = project();
          p.floorPlans[0].width = 9000; p.floorPlans[0].height = 500;
          p.accessPoints.forEach(a => { if (a.location.floorPlanId === 'fA') { a.location.coord.x *= 8; a.location.coord.y = 250; } });
          open(p);
          const html = render('placement', { segmented: true, segCols: 3, segRows: 1, nameKey: 'never', inclOmni: true });
          const sizes = (html.match(/class="rep-grid-label[^"]*" font-size="([\d.]+)"/g) || [])
            .map(x => parseFloat(x.match(/font-size="([\d.]+)"/)[1]));
          check('there are section letters', sizes.length > 0);
          const floor = 3000 * E('MAP_FONT_FLOOR_FRAC');          // one cell is 3000 units wide
          sizes.forEach(z => check('a letter of ' + z + ' is under the floor ' + floor, z >= floor - 0.01));
        """)


class TheInstallationMapIsAFittedPlanPage(ReportCase):

    def test_each_floor_map_is_a_plan_page_and_its_table_is_a_sibling(self):
        self.run_block(r"""
          open();
          const html = render('location', {});
          const at = html.indexOf('data-page-key="loc-map:fA"');
          check('the floor has a map page', at >= 0);
          const open_tag = html.slice(html.lastIndexOf('<section', at), html.indexOf('>', at) + 1);
          check('it is a fitted plan page: ' + open_tag,
                /rep-placement-page/.test(open_tag) && /data-page-kind="plan"/.test(open_tag)
                && /data-floor-id="fA"/.test(open_tag));
          const end = html.indexOf('</section>', at);
          check('the AP table is not inside the map page', html.slice(at, end).indexOf('rep-loc-table') < 0);
          const table = html.indexOf('data-page-key="loc-table:fA"', end);
          check('the table follows as a page of its own', table > end);
          const between = html.slice(end, table);
          check('with nothing but its own opening tag between: ' + between,
                /^<\/section><section class="rep-loc-page[^>]*$/.test(between));
        """)


class BoxesThatLandOnEachOtherAreSpreadApart(ReportCase):

    def test_the_helper_gives_every_box_a_free_slot_and_keeps_order(self):
        self.run_block(r"""
          const spread = E('spreadBoxes');
          const items = [];
          for (let i = 0; i < 6; i++) items.push({ x: 100, y: 100, w: 20, h: 10 });   // six on one spot
          items.push({ x: 500, y: 500, w: 20, h: 10 });                              // one alone
          const out = spread(items);
          eq('one result per item, in order', out.length, 7);
          eq('the first stays where it wanted to be', [out[0].cx, out[0].cy, out[0].moved], [100, 100, false]);
          eq('the one alone is not moved', out[6].moved, false);
          for (let i = 0; i < out.length; i++) for (let j = i + 1; j < out.length; j++) {
            const hit = Math.abs(out[i].cx - out[j].cx) < (out[i].w + out[j].w) / 2
                     && Math.abs(out[i].cy - out[j].cy) < (out[i].h + out[j].h) / 2;
            check('boxes ' + i + ' and ' + j + ' do not overlap', !hit);
          }
          check('the five that had to move say so', out.slice(1, 6).every(b => b.moved));
        """)

    def test_two_radios_on_one_design_map_spot_get_two_readable_labels(self):
        self.run_block(r"""
          const p = project();
          // a second 5 GHz radio on Zed-AP1: two markers at one position
          p.radios.push({ id: 'dup', accessPointId: 'ap1', radioTechnology: 'IEEE802_11', antennaTypeId: 'omni1',
            transmitPower: 10, channelByCenterFrequencyDefinedNarrowChannels: [5200] });
          open(p);
          const html = render('design', { channelMap: true });
          const ground = floorPart(html, 'data-page-key="drmap-FIVE:fA"', 'data-page-key="drmap-FIVE:fB"');
          const spots = ground.match(/class="rep-dr-mark" transform="translate\(([^)]*)\)"/g) || [];
          check('the map has its markers: ' + spots.length, spots.length >= 7);
          eq('no two on one spot', new Set(spots).size, spots.length);
        """)


if __name__ == "__main__":
    unittest.main()
