"""Move to Site pre-selects a destination. It has to be right or say nothing.

After a fresh round of uploads the picker opens with every project already
aimed at a site, marked "auto". The suggester behind it (`_suggestSiteFor` in
cloud.js) had none of the guards the server's cloud/local pairing has:

* a shared site code added a flat +1.0, so **any** name at the same code
  cleared the threshold - a project for one building was filed under another
  building of the same site;
* nothing compared building numbers, street numbers or survey phases;
* a tie went to whichever site sorted first, and the sorted list is
  alphabetical, so the answer was an accident of spelling;
* a "v3" tag on the project and not on the site diluted the similarity.

The suggestion is only worth showing when it is the one he would pick. Where
two sites fit equally, or the name conflicts with the only candidate, it must
stay empty - he can still choose, and an empty row is visible.

The discriminators are a JS port of `cloud_manager.discriminators_reason`, so
`ThePortAgreesWithTheServerTests` runs both over the same pairs.

Every site and project name here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tools import cloud_manager as cm

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 60

PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('function _extractSiteCode(');
const b = src.indexOf('async function assignOrphanToSite(');
if (a < 0 || b < 0 || b < a) throw new Error('suggester block moved');
eval(src.slice(a, b) + `
globalThis._api = { _suggestSiteFor, _discriminatorsConflict, _withoutVersionTags };
`);
const job = JSON.parse(process.argv[2]);
const api = globalThis._api;
let out;
if (job.kind === 'conflict') {
  out = job.pairs.map(([x, y]) => api._discriminatorsConflict(x, y));
} else if (job.kind === 'suggest') {
  out = job.cases.map(c => {
    const sites = c.sites.map(n => typeof n === 'string'
      ? { id: n, name: n, localFolder: '' } : n);
    const g = api._suggestSiteFor(c.item, sites, c.t || null);
    return g ? sites[g.idx].name : null;
  });
} else if (job.kind === 'strip') {
  out = job.names.map(n => api._withoutVersionTags(n).replace(/\s+/g, ' ').trim());
}
process.stdout.write(JSON.stringify(out));
"""


def run_node(job):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    r = subprocess.run([node, "-e", PROBE, str(CLOUD_JS), json.dumps(job)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout)


def suggest(item, sites, t=None):
    return run_node({"kind": "suggest",
                     "cases": [{"item": item, "sites": sites, "t": t}]})[0]


class TheSuggestionIsRightOrEmptyTests(unittest.TestCase):

    def test_the_site_that_fits_is_picked_despite_a_version_tag(self):
        got = suggest("SITE1 Bldg 5 v3",
                      ["SITE1 Bldg 5", "SITE1 Bldg 6", "SITE9 Annex"])
        self.assertEqual(got, "SITE1 Bldg 5")

    def test_another_building_of_the_same_site_is_not_a_match(self):
        # Bldg 7 has no site yet. Sharing a code with Bldg 5 and Bldg 6 used to
        # be enough to file it under whichever came first.
        got = suggest("SITE1 Bldg 7 v3", ["SITE1 Bldg 5", "SITE1 Bldg 6"])
        self.assertIsNone(got)

    def test_a_lone_candidate_in_the_wrong_building_is_not_a_match(self):
        # One candidate, so the tie rule cannot be what refuses it: the names
        # are close and the code is shared, and only the building says no.
        got = suggest("SITE1 Bldg 7 East Wing v3", ["SITE1 Bldg 5 East Wing"])
        self.assertIsNone(got)

    def test_a_shared_code_with_nothing_else_in_common_is_not_a_match(self):
        got = suggest("SITE2 Rooftop Antenna Replacement",
                      ["SITE2 Basement Parking Garage"])
        self.assertIsNone(got)

    def test_a_different_street_number_is_not_a_match(self):
        got = suggest("SITE3 1200 Example Ave v3", ["SITE3 1400 Example Ave"])
        self.assertIsNone(got)

    def test_a_tie_is_not_a_pick(self):
        # Both clear the floor by the same margin - the first in the list is
        # not an answer.
        got = suggest("SITE4 Wing Survey",
                      ["SITE4 East Wing", "SITE4 West Wing"])
        self.assertIsNone(got)

    def test_a_version_tag_does_not_cost_the_match(self):
        # Three tags on a one-word site name: unstripped it is a third of the
        # words and falls under the floor, stripped it is the whole name.
        got = suggest("Quarry v3 rev2 v1.2", ["Quarry", "Depot"])
        self.assertEqual(got, "Quarry")

    def test_a_clear_winner_among_close_names_is_still_picked(self):
        got = suggest("SITE4 East Wing v3",
                      ["SITE4 East Wing", "SITE4 West Wing"])
        self.assertEqual(got, "SITE4 East Wing")

    def test_a_year_is_not_a_street_number(self):
        got = suggest("SITE5 Survey 2026", ["SITE5 Survey 2025"])
        self.assertEqual(got, "SITE5 Survey 2025")

    def test_a_site_without_a_code_needs_the_names_to_agree(self):
        self.assertIsNone(suggest("Harbor Depot v3", ["Quarry Yard"]))
        self.assertEqual(suggest("Harbor Depot Dock Office v3",
                                 ["Harbor Depot Dock Office", "Quarry Yard"]),
                         "Harbor Depot Dock Office")

    def test_the_folder_a_local_file_sits_in_still_wins(self):
        sites = [{"id": "", "name": "North Yard", "localFolder": "North Yard"},
                 {"id": "", "name": "South Yard", "localFolder": "South Yard"}]
        t = {"kind": "local", "name": "Scan v3",
             "path": "C:/x/South Yard/Scan v3.esx"}
        self.assertEqual(suggest("Scan v3", sites, t), "South Yard")

    def test_only_version_tags_are_stripped(self):
        got = run_node({"kind": "strip", "names": [
            "SITE1 Bldg 5 v3", "SITE1 Rev2 Floor", "Survey v1.2 East",
            "Level2 Server", "Eve3 Annex"]})
        self.assertEqual(got, ["SITE1 Bldg 5", "SITE1 Floor", "Survey East",
                               "Level2 Server", "Eve3 Annex"])


class ThePortAgreesWithTheServerTests(unittest.TestCase):

    PAIRS = [
        ("SITE1 Bldg 5", "SITE1 Bldg 6"),
        ("SITE1 Bldg 100", "SITE1 Bldg 200"),
        ("SITE1 Building 100", "SITE1 Bldg 100"),
        ("SITE1 Bldg 2", "SITE1 Bldg 2 Annex"),
        ("SITE1 Bld A", "SITE1 Bldg B"),
        ("SITE1 1200 Main St", "SITE1 1400 Main St"),
        ("SITE1 1200 Main St", "SITE1 1200 Main St v3"),
        ("SITE1 Survey 2025", "SITE1 Survey 2026"),
        ("SITE1 Baseline", "SITE1 Remediation"),
        ("SITE1 Post-Install", "SITE1 postinstall"),
        ("SITE1 As-Built", "SITE1 As-Ran"),
        ("SITE1 TVR", "SITE1 Validation"),
        ("SITE1 Predictive", "SITE1 Baselines"),
        ("SITE1 Cleanroom East", "SITE1 Cleanroom West"),
        ("Plain Name", "Another Name"),
        ("SITE1 Bldg 5 v3", "SITE1 Bldg 5"),
    ]

    def test_the_two_agree_on_every_pair(self):
        js = run_node({"kind": "conflict", "pairs": [list(p) for p in self.PAIRS]})
        py = [cm.discriminators_reason(a, b) is not None for a, b in self.PAIRS]
        disagree = [p for p, x, y in zip(self.PAIRS, js, py) if x != y]
        self.assertEqual(disagree, [], "JS and Python disagree on these pairs")


if __name__ == "__main__":
    unittest.main()
