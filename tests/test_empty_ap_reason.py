"""An empty report says why it is empty, and names the thing to change.

Found by printing the Antenna Aim Sheet in Chrome, Edge and Firefox and reading
what came out: on a project with 44 access points, all omni, it said

    No APs selected — check the AP filter panel.

Three separate causes were being reported with one sentence, and two of them
have nothing to do with that panel. The aim sheet lists only directional APs, so
its own option hid all 44 — the panel was correct and he was being sent to fix
it. The report even has an accurate message of its own further down, which this
guard fires too early to reach.

Each cause now names itself and the control that answers it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(a, b) {
  const i = src.indexOf(a), j = src.indexOf(b, i);
  if (i < 0 || j < 0) throw new Error('missing ' + a);
  return src.slice(i, j);
}
// Stand-ins for the two things the reason depends on.
let proj = { accessPoints: [] };
let apDisabled = new Set();
function apIsOmniOnly(ap) { return !!ap.omni; }
eval(slice('  function emptyApReason(', '  function apMarkerLabel('));

function say(aps, disabled, inclOmni, inclDirectional) {
  proj.accessPoints = aps;
  apDisabled = new Set(disabled || []);
  return emptyApReason(inclOmni, inclDirectional);
}
"""


def run(script):
    proc = subprocess.run(["node", "-e", PRELUDE + script, str(REPORT_JS)],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=NODE_TIMEOUT_S)
    if proc.returncode != 0:
        raise AssertionError("node failed:\n" + proc.stderr)
    return json.loads(proc.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class WhyItIsEmpty(unittest.TestCase):
    def test_his_case_all_omni_on_the_aim_sheet(self):
        """44 omni APs, a report that excludes omni. The reported wording."""
        out = run("const aps=[]; for(let i=0;i<44;i++) aps.push({id:'a'+i, omni:true});"
                  "console.log(JSON.stringify(say(aps, [], false, true)));")
        self.assertIn("All 44 access points here are omni", out)
        self.assertIn('Include omni APs', out)
        self.assertNotIn("check the AP filter panel", out)

    def test_the_mirror_case_all_directional(self):
        out = run("const aps=[]; for(let i=0;i<7;i++) aps.push({id:'a'+i, omni:false});"
                  "console.log(JSON.stringify(say(aps, [], true, false)));")
        self.assertIn("All 7 access points here are directional", out)
        self.assertIn('Include directional APs', out)

    def test_one_ap_reads_as_singular(self):
        out = run("console.log(JSON.stringify("
                  "say([{id:'a', omni:true}], [], false, true)));")
        self.assertIn("All 1 access point here is omni", out)

    def test_the_panel_is_blamed_only_when_the_panel_is_the_cause(self):
        """Everything unticked by hand: the original message was right here."""
        out = run("const aps=[{id:'a',omni:true},{id:'b',omni:false}];"
                  "console.log(JSON.stringify(say(aps, ['a','b'], true, true)));")
        self.assertIn("AP filter panel", out)
        self.assertIn("unticked", out)

    def test_a_project_with_no_aps_says_so(self):
        out = run("console.log(JSON.stringify(say([], [], true, true)));")
        self.assertIn("no access points", out)

    def test_a_mixed_project_points_at_both_options(self):
        """Both kinds present and both excluded - no single cause to name."""
        out = run("const aps=[{id:'a',omni:true},{id:'b',omni:false}];"
                  "console.log(JSON.stringify(say(aps, [], false, false)));")
        self.assertIn("Include omni APs", out)
        self.assertIn("Include directional APs", out)

    def test_no_cause_is_reported_as_the_filter_panel_by_default(self):
        """The regression: one sentence standing in for every cause."""
        cases = [
            "say([{id:'a',omni:true}], [], false, true)",
            "say([{id:'a',omni:false}], [], true, false)",
            "say([], [], true, true)",
        ]
        for c in cases:
            with self.subTest(case=c):
                out = run("console.log(JSON.stringify(%s));" % c)
                self.assertNotIn("check the AP filter panel", out)


class TheGuardUsesIt(unittest.TestCase):
    def test_the_generic_sentence_is_gone_from_the_source(self):
        js = REPORT_JS.read_text(encoding="utf-8")
        self.assertNotIn("No APs selected — check the AP filter panel.", js)
        self.assertIn("emptyApReason(inclOmni, inclDirectional)", js)


if __name__ == "__main__":
    unittest.main()
