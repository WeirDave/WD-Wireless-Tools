"""A directional AP with no cone says why, and AP Installation can turn cones off.

An installer package for directional access points was printed and the maps
carried the directional marker for each one - and no cone. The cone is drawn
from the azimuth the project stores for the antenna; a directional antenna with
none has nothing to point along, and the sheet said nothing, so the report read
as broken. The AP Installation sidebar also had no control for cones at all,
although its description promises them.

* the sidebar offers "Show aiming cones on directional APs", on by default;
* a directional AP with no azimuth is named under the map - on a whole-floor
  map and on a sectioned one - and the cone it cannot have is not invented;
* nothing is said when every directional AP has an azimuth, when the cones
  are switched off, or when the floor is all omni;
* the key files such an AP under the directional swatch, as its marker is.

Every test drives the real `report.js` against the stub DOM of
`test_report_prints_what_the_design_holds`, and reads the markup printed.
"""
from __future__ import annotations

import unittest

from tests.test_report_placement_aim import KIT
from tests.test_report_prints_what_the_design_holds import ReportCase

# Spliced into the Node program; the sentence the note carries.
NOTE = "no azimuth saved in the project"
LOC = "{ inclOmni: true, signOff: false, showCones: true, segmented: false }"
LOC_OFF = "{ inclOmni: true, signOff: false, showCones: false, segmented: false }"


class TheInstallationReportAndItsCones(ReportCase):

    def run_js(self, body: str) -> None:
        self.run_block(KIT + body.replace("@NOTE@", NOTE)
                       .replace("@LOC@", LOC).replace("@LOC_OFF@", LOC_OFF))

    def test_the_sidebar_offers_the_cone_control_and_it_is_on_by_default(self):
        self.run_block(r"""
          const opt = E('(function () { return REPORTS.location.sidebar.find(function (s) { return s.id === "showCones"; }); })')();
          check('AP Installation lists the cone option', !!opt);
          eq('on by default', opt && opt.default, true);
        """)

    def test_cones_are_drawn_where_there_is_an_azimuth_and_can_be_switched_off(self):
        self.run_js(r"""
          open(build([floor('f1', 'Level', 1000, 800)], [
            { n: 1, x: 200, y: 200, radios: [{ ant: 'dir1', dir: 90 }] },
            { n: 2, x: 400, y: 200, radios: [{ ant: 'omni1' }] },
          ]));
          const on = markersOf(render('location', @LOC@));
          eq('the cone follows the azimuth', on.find(x => x.text === '1').cone, 90);
          eq('an omni gets none', on.find(x => x.text === '2').cone, null);
          const off = markersOf(render('location', @LOC_OFF@));
          eq('switched off, no cone', off.find(x => x.text === '1').cone, null);
        """)

    def test_a_directional_ap_with_no_azimuth_is_named_under_the_map(self):
        self.run_js(r"""
          open(build([floor('f1', 'Level', 1000, 800)], [
            { n: 1, x: 200, y: 200, radios: [{ ant: 'dir1', dir: null }] },
            { n: 2, x: 400, y: 200, radios: [{ ant: 'dir1', dir: 90 }] },
            { n: 3, x: 600, y: 200, radios: [{ ant: 'omni1' }] },
          ]));
          const html = render('location', @LOC@);
          const note = /<div class="rep-overview-note">1 directional AP has[^<]*<\/div>/.exec(html);
          check('one sentence about one AP', !!note);
          check('it says why: ' + (note && note[0]), note && note[0].indexOf('@NOTE@') >= 0);
          check('it names Zed-AP1 and only that one',
                note && note[0].indexOf('Zed-AP1') >= 0 && note[0].indexOf('Zed-AP2') < 0
                  && note[0].indexOf('Zed-AP3') < 0);
          const m = markersOf(html);
          eq('and no cone is invented for it', m.find(x => x.text === '1').cone, null);
          check('it is still the directional marker', /rep-mark--dir/.test(m.find(x => x.text === '1').cls));
          eq('the AP that has an azimuth keeps its cone', m.find(x => x.text === '2').cone, 90);
        """)

    def test_a_sectioned_floor_says_it_too(self):
        self.run_js(r"""
          open(build([floor('f1', 'Level', 1000, 800)], [
            { n: 1, x: 200, y: 200, radios: [{ ant: 'dir1', dir: null }] },
            { n: 2, x: 800, y: 600, radios: [{ ant: 'dir1', dir: 90 }] },
          ]));
          const html = render('location', { inclOmni: true, signOff: false, showCones: true,
                                            segmented: true, segCols: 2, segRows: 2 });
          check('the floor was split into sections', html.indexOf('Floor plan split into') >= 0);
          const note = /<div class="rep-overview-note">1 directional AP has[^<]*<\/div>/.exec(html);
          check('the sectioned floor says it, naming the AP: ' + (note && note[0]),
                note && note[0].indexOf('@NOTE@') >= 0 && note[0].indexOf('Zed-AP1') >= 0);
        """)

    def test_nothing_is_said_when_there_is_nothing_to_say(self):
        self.run_js(r"""
          open(build([floor('f1', 'Level', 1000, 800)], [
            { n: 1, x: 200, y: 200, radios: [{ ant: 'dir1', dir: 135 }] },
            { n: 2, x: 400, y: 200, radios: [{ ant: 'omni1' }] },
          ]));
          check('every directional AP has an azimuth: no note',
                render('location', @LOC@).indexOf('@NOTE@') < 0);
          open(build([floor('f1', 'Level', 1000, 800)], [
            { n: 1, x: 200, y: 200, radios: [{ ant: 'dir1', dir: null }] },
          ]));
          check('cones switched off: nothing to explain',
                render('location', @LOC_OFF@).indexOf('@NOTE@') < 0);
          open(build([floor('f1', 'Level', 1000, 800)], [
            { n: 1, x: 200, y: 200, radios: [{ ant: 'omni1' }] },
          ]));
          check('an all-omni floor: no note', render('location', @LOC@).indexOf('@NOTE@') < 0);
        """)

    def test_a_long_list_of_names_is_cut_and_counted(self):
        self.run_js(r"""
          const aps = [];
          for (let i = 1; i <= 15; i++) aps.push({ n: i, x: 50 + i * 55, y: 300, radios: [{ ant: 'dir1', dir: null }] });
          open(build([floor('f1', 'Level', 1000, 800)], aps));
          const html = render('location', @LOC@);
          const note = /<div class="rep-overview-note">15 directional APs have[^<]*<\/div>/.exec(html);
          check('plural, with the count', !!note);
          check('twelve names and the rest counted: ' + (note && note[0].slice(-160)),
                note && /and 3 more\./.test(note[0]) && note[0].indexOf('Zed-AP12') >= 0
                  && note[0].indexOf('Zed-AP13') < 0);
        """)

    def test_the_key_files_a_directional_ap_without_an_azimuth_under_directional(self):
        self.run_js(r"""
          open(build([floor('f1', 'Level', 1000, 800)], [
            { n: 1, x: 200, y: 200, color: '#FF0000', radios: [{ ant: 'dir1', dir: null }] },
            { n: 2, x: 400, y: 200, color: '#0068FF', radios: [{ ant: 'omni1' }] },
          ]));
          const html = render('location', @LOC@);
          const key = (html.match(/<div class="rep-overview-key">[\s\S]*?<\/div>/) || [''])[0];
          check('red (the directional AP) is under the directional swatch: ' + key,
                /rep-key-swatch dir"[^>]*background:#ff0000/i.test(key));
          check('blue (the omni AP) is under the omni swatch',
                /rep-key-swatch omni"[^>]*background:#0068ff/i.test(key));
        """)


if __name__ == "__main__":
    unittest.main()
