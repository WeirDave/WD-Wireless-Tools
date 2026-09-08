"""A label that will not fit on the map must not be placed off the map.

The placement search walks outwards from each AP looking for ground no other
label or dot has taken - sixteen angles over three rings. It asked one question
of each candidate, `collides()`, which compares the label against other labels
and against the dots. Nothing asked whether the candidate was still on the plan.

So a tight group of APs near an edge would exhaust the near positions, walk out,
and find its first unoccupied spot off the side of the drawing. The SVG clips at
its viewBox, so the label did not spill onto the sheet where someone would
notice a layout problem - it silently disappeared. The AP kept its dot and lost
its number, on a drawing an installer works from.

Measured on a fixture with 29 APs packed against the right-hand edge of a
10000x7500 plan, rendered through the real report:

    before   19 of 29 labels off the plan, by up to 71px
    after     0 of 29 - every label placed, pulled inboard with a leader line

Segmented maps already computed these bounds and used them to nudge
`preferSide`. They were a preference; they are a constraint. On a full-plan map
there were no bounds at all, which is why this only ever bit the whole-floor
placement report.

What is deliberately *not* clamped: the AP dot itself, and a directional cone.
A dot sits where the AP sits, and a cone points where the antenna points. Moving
either would misreport the survey to make the picture tidier, so an AP a few
plan units from the edge still has a dot that laps over it by a fraction of a
pixel. That is the drawing being honest.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"


class MarkerLabelBounds(unittest.TestCase):
    def setUp(self):
        self.js = REPORT_JS.read_text(encoding="utf-8")
        start = self.js.index("function buildAntennaMarkers(")
        self.body = self.js[start:self.js.index("\n  function ", start + 10)]

    def test_the_plan_edge_is_known_to_the_placer(self):
        self.assertIn("var labelBounds", self.body)
        self.assertIn("function onPlan(r)", self.body)
        self.assertIn("function pullOntoPlan(r)", self.body)

    def test_a_full_plan_map_has_bounds_at_all(self):
        """cellBounds is only set for segmented maps. Without a fallback the
        whole-floor map - the one this bug was reported on - has no edge."""
        self.assertRegex(self.body, r"labelBounds\s*=\s*cellBounds")
        self.assertIn("scaleW", self.body.split("var labelBounds")[1][:400])
        self.assertIn("scaleH", self.body.split("var labelBounds")[1][:400])

    def test_being_on_the_plan_is_part_of_accepting_a_candidate(self):
        """The whole fix. If this reverts to collides() alone, labels go back
        to walking off the edge and vanishing."""
        m = re.search(r"for \(var i = 0; i < cands\.length; i\+\+\) \{(.{0,400}?)\n      \}",
                      self.body, re.S)
        self.assertIsNotNone(m, "the candidate loop moved; re-point this test")
        loop = m.group(1)
        self.assertIn("onPlan(rect)", loop,
                      "a candidate is accepted without asking whether it is "
                      "still on the map")
        self.assertIn("collides(rect)", loop)

    def test_the_last_resort_stays_on_the_plan(self):
        """When every clear position is taken the label doubles up - but a
        doubled-up label is readable and an absent one is not."""
        tail = self.body[self.body.index("if (!chosen)"):]
        self.assertIn("pullOntoPlan(", tail[:600])

    def test_the_bounds_allow_for_the_stroke(self):
        """An SVG stroke straddles the edge it is drawn on, so a pill placed
        exactly on the boundary still loses half its outline to the clip."""
        self.assertIn("var edgeInset = sw / 2;", self.body)

    def test_the_dot_and_the_cone_are_not_moved(self):
        """Both report where something physically is or points. Clamping them
        would make the drawing tidier and wrong."""
        self.assertNotIn("pullOntoPlan({ x: c.x - dotSize", self.body)
        cone = self.body[self.body.index("isDirectional && showCones"):][:600]
        self.assertNotIn("pullOntoPlan", cone)
        self.assertNotIn("onPlan", cone)


if __name__ == "__main__":
    unittest.main()
