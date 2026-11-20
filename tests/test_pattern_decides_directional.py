"""An antenna that Ekahau labels omni but whose pattern is a beam is directional.

An .esx antenna type has a `directional` flag, which is Ekahau's library label,
and a stored radiation pattern, which is the antenna. A wide-beam wall-mount
access point is labelled `directional: false` while its pattern peaks at 9 dBi,
falls about 30 dB behind it and keeps a half-power beam near 100 degrees. The
report trusted the label: the AP was "omni", the Antenna Aim Sheet left it off,
and no map drew a cone for it, although the design aimed it.

* a pattern with a clear beam makes an antenna directional whatever the label
  says, and it is then listed on the Aim Sheet and given a cone at its azimuth;
* an antenna that is flat to within a few dB stays omni;
* a deep null behind an otherwise round pattern (a body shadow) stays omni - it
  is the width of the beam that makes an antenna directional, not the depth of
  a notch;
* a label that says directional is never overruled;
* with no stored beam width the specs page shows the width measured from the
  pattern, marked "~" as approximate, and a stored width is printed as stored;
* an all-omni project still has no beam widths, so its specs page stays off.

The patterns are invented: a parabola of gain around a peak bearing.

Every test drives the real `report.js` against the stub DOM of
`test_report_prints_what_the_design_holds`.
"""
from __future__ import annotations

import unittest

from tests.test_report_placement_aim import KIT
from tests.test_report_prints_what_the_design_holds import ReportCase

PATTERNS = r"""
/* gain(angle) for angles 0..358 in steps of 2 */
function plane(fn) {
  const gains = [];
  for (let a = 0; a < 360; a += 2) gains.push({ angle: a, gain: fn(a) });
  return { alignmentAngle: 270, gains };
}
const away = (a, from) => { const d = Math.abs(a - from) % 360; return Math.min(d, 360 - d); };
/* A beam: 9 dBi at 270, 3 dB down at about 50 degrees either side. */
const beam = (k) => plane(a => 9 - k * away(a, 270) * away(a, 270));
function antenna(id, name, flag, hplane, eplane, extra) {
  const a = Object.assign({ id, name, apCoupling: 'INTERNAL_ANTENNA', frequencyBand: 'FIVE',
                            maxGain: 9, hplane, eplane }, extra || {});
  if (flag !== undefined) a.directional = flag;
  return a;
}
function withAntennas(list, radioAnt) {
  const p = build([floor('f1', 'Level', 1000, 800)], [
    { n: 1, x: 300, y: 300, radios: [{ ant: radioAnt, dir: 135 }] },
  ]);
  list.forEach(a => { p.antennas[a.id] = a; });
  return p;
}
"""


class ThePatternDecidesWhenTheLabelSaysOmni(ReportCase):

    def run_js(self, body: str) -> None:
        self.run_block(KIT + PATTERNS + body)

    def test_a_beam_labelled_omni_is_directional_and_gets_a_cone(self):
        self.run_js(r"""
          const wide = antenna('w1', 'Sample Wall Panel 5GHz', false, beam(0.0012), beam(0.004));
          open(withAntennas([wide], 'w1'));
          const aim = render('aim', { inclOmni: false, signOff: false, shortLabels: false });
          const row = aimRow(aim, 'Zed-AP1');
          check('listed on the Aim Sheet with its azimuth: ' + row, />135°/.test(row) && !/omni/.test(row));
          const m = markersOf(render('location', { inclOmni: true, signOff: false, showCones: true, segmented: false }));
          check('a directional marker', /rep-mark--dir/.test(m[0].cls));
          eq('with a cone along the azimuth', m[0].cone, 135);
        """)

    def test_a_flat_pattern_stays_omni(self):
        self.run_js(r"""
          const flat = antenna('o2', 'Sample Ceiling 5GHz', false, plane(a => 3 + 0.5 * Math.sin(a * Math.PI / 180)),
                               plane(a => 1));
          open(withAntennas([flat], 'o2'));
          const aim = render('aim', { inclOmni: true, signOff: false, shortLabels: false });
          check('called omni: ' + aimRow(aim, 'Zed-AP1'), /omni/.test(aimRow(aim, 'Zed-AP1')));
          eq('no cone', markersOf(render('location', { inclOmni: true, signOff: false, showCones: true, segmented: false }))[0].cone, null);
        """)

    def test_a_gentle_lean_is_not_a_beam(self):
        # 6 dB of lean over a half circle: a wide arc and a small spread.
        self.run_js(r"""
          const lean = antenna('l3', 'Sample Lean 5GHz', false, plane(a => 3 + 3 * Math.cos((a - 90) * Math.PI / 180)),
                               plane(a => 1));
          open(withAntennas([lean], 'l3'));
          const aim = render('aim', { inclOmni: true, signOff: false, shortLabels: false });
          check('still omni: ' + aimRow(aim, 'Zed-AP1'), /omni/.test(aimRow(aim, 'Zed-AP1')));
        """)

    def test_a_deep_null_behind_a_round_pattern_is_not_a_beam(self):
        self.run_js(r"""
          const shadow = antenna('s4', 'Sample Shadowed 5GHz', false,
                                 plane(a => away(a, 90) <= 30 ? -12 : 0), plane(a => 0));
          open(withAntennas([shadow], 's4'));
          const aim = render('aim', { inclOmni: true, signOff: false, shortLabels: false });
          check('still omni: ' + aimRow(aim, 'Zed-AP1'), /omni/.test(aimRow(aim, 'Zed-AP1')));
        """)

    def test_a_label_that_says_directional_is_never_overruled(self):
        self.run_js(r"""
          const flat = antenna('d5', 'Sample Sector 5GHz', true, plane(a => 3), plane(a => 3));
          open(withAntennas([flat], 'd5'));
          const aim = render('aim', { inclOmni: false, signOff: false, shortLabels: false });
          check('listed even with a flat stored pattern', !/omni/.test(aimRow(aim, 'Zed-AP1')));
        """)

    def test_the_specs_page_prints_the_measured_width_marked_approximate(self):
        self.run_js(r"""
          const wide = antenna('w1', 'Sample Wall Panel 5GHz', false, beam(0.0012), beam(0.004));
          open(withAntennas([wide], 'w1'));
          const off = E('(function () { return REPORTS.location.sidebar.find(function (s) { return s.id === "specs"; }); })')();
          check('the specs option is available', !off.disabledWhen(E('(function () { return proj; })')()));
          const html = render('location', { inclOmni: true, signOff: false, specs: true, segmented: false });
          const h = /~(\d+)° h-beam/.exec(html), v = /~(\d+)° v-beam/.exec(html);
          check('a horizontal width, marked approximate', h && +h[1] >= 95 && +h[1] <= 110);
          check('a vertical width, marked approximate', v && +v[1] >= 50 && +v[1] <= 60);
        """)

    def test_a_stored_width_is_printed_as_stored(self):
        self.run_js(r"""
          const wide = antenna('w1', 'Sample Wall Panel 5GHz', false, beam(0.0012), beam(0.004),
                               { beamWidthHorizontal: 70, beamWidthVertical: 30 });
          open(withAntennas([wide], 'w1'));
          const html = render('location', { inclOmni: true, signOff: false, specs: true, segmented: false });
          check('the stored horizontal width is printed', html.indexOf('70° h-beam') >= 0);
          check('the stored vertical width is printed', html.indexOf('30° v-beam') >= 0);
          check('neither is marked approximate', !/~\d+° [hv]-beam/.test(html));
        """)

    def test_an_all_omni_project_still_has_no_beam_widths(self):
        self.run_js(r"""
          const flat = antenna('o2', 'Sample Ceiling 5GHz', false, plane(a => 3), plane(a => 1));
          const p = withAntennas([flat], 'o2');
          open(p);
          const opt = E('(function () { return REPORTS.location.sidebar.find(function (s) { return s.id === "specs"; }); })')();
          check('the specs option stays disabled', opt.disabledWhen(p) === true);
        """)


if __name__ == "__main__":
    unittest.main()
