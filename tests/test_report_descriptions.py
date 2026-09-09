"""Every report template says what it is, who reads it, and what comes out.

He could not tell his own report types apart and had forgotten why several
existed. The names do not carry it: "AP Placement Map", "Predictive Design /
AP Placement" and "AP Installation" all put access points on a floor plan.

What separates them is not their contents - it is who the sheet is for and how
many pages land on the desk. So those two facts sit on the face of the card.
They used to be behind a Details toggle, which meant telling nine templates
apart required expanding nine cards one at a time.

Written for someone meeting the tool cold, because the community post is live
and that is a real audience now.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"

FIELD = re.compile(r"(label|description|readBy|output|bestFor|docName|status):\s*'((?:\\.|[^'])*)'")


def reports():
    src = REPORT_JS.read_text(encoding="utf-8")
    starts = [(m.group(1), m.start()) for m in re.finditer(r"\n    ([a-z]+): \{\n", src)]
    out = {}
    for i, (rid, pos) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(src)
        region = src[pos:end]
        if "docName:" not in region:
            continue
        found = {}
        for m in FIELD.finditer(region):
            found.setdefault(m.group(1), m.group(2))
        out[rid] = found
    return out


class ReportDescriptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports = reports()

    def test_every_template_is_found(self):
        self.assertGreaterEqual(len(self.reports), 9)

    def test_each_one_says_what_it_is_who_reads_it_and_what_comes_out(self):
        for rid, r in self.reports.items():
            with self.subTest(report=rid):
                for field in ("description", "readBy", "output"):
                    self.assertIn(field, r, f"{rid} has no {field}")
                    self.assertGreater(len(r[field].strip()), 10,
                                       f"{rid}.{field} is too short to explain anything")

    def test_the_three_that_all_draw_aps_on_a_plan_differ_on_what_you_get(self):
        """The reason he could not tell them apart. Their contents overlap; the
        page count on the desk does not."""
        outputs = {rid: self.reports[rid]["output"]
                   for rid in ("placement", "predictive", "location")}
        self.assertEqual(len(set(outputs.values())), 3,
                         f"these must not describe the same output: {outputs}")

    def test_no_two_reports_share_a_description(self):
        seen = {}
        for rid, r in self.reports.items():
            d = r.get("description", "")
            self.assertNotIn(d, seen,
                             f"{rid} and {seen.get(d)} describe themselves identically")
            seen[d] = rid

    def test_a_description_does_not_just_restate_the_title(self):
        for rid, r in self.reports.items():
            with self.subTest(report=rid):
                self.assertNotEqual(r["description"].strip().lower(),
                                    r["label"].strip().lower())

    def test_the_facts_are_on_the_card_not_behind_the_toggle(self):
        """Expanding nine cards to compare them is the problem, not the fix."""
        src = REPORT_JS.read_text(encoding="utf-8")
        top = src[src.index("'<div class=\"rep-template-card-top\">'"):
                  src.index("'<div class=\"rep-template-detail\"'")]
        self.assertIn("r.readBy", top, "who it is for must render on the card face")
        self.assertIn("r.output", top, "what you get must render on the card face")


if __name__ == "__main__":
    unittest.main()
