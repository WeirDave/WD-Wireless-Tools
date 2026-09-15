"""The channel on a marker label is a channel, not a frequency.

Found by generating a real design project in Firefox and reading what the plan
actually said. Ekahau stores `channelByCenterFrequencyDefinedNarrowChannels` as
centre frequencies in MHz, and the marker label printed them raw: **"ch 2412"**,
which is channel 1, and **"ch 5660"**, which is channel 132.

The AP Installation table in the same document converts properly through
`freqToChannel()`. So one page of a deliverable said "ch 1" and the plan a few
pages earlier said "ch 2412" for the same access point, and nothing on either
page told the installer which to believe.

Two implementations of one conversion, disagreeing - the pattern that has
produced most of the defects in this repo.
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
eval(slice('  function freqToChannel(freqMHz)', '  function floorPlanForAp'));
"""


def run_node(script):
    proc = subprocess.run(["node", "-e", PRELUDE + script, str(REPORT_JS)],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=NODE_TIMEOUT_S)
    if proc.returncode != 0:
        raise AssertionError("node failed:\n" + proc.stderr)
    return json.loads(proc.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class FrequencyToChannel(unittest.TestCase):
    def test_the_frequencies_seen_on_his_project(self):
        """2412 and 5660 are what the label was printing verbatim."""
        out = run_node("console.log(JSON.stringify("
                       "[2412, 2437, 2462, 5180, 5660, 5745].map(freqToChannel)));")
        self.assertEqual(out, [1, 6, 11, 36, 132, 149])

    def test_six_gigahertz_converts_on_its_own_base(self):
        out = run_node("console.log(JSON.stringify([5955, 6115].map(freqToChannel)));")
        self.assertEqual(out, [1, 33])

    def test_a_number_that_is_already_a_channel_is_left_alone(self):
        """Below the 2.4GHz band base there is nothing to convert."""
        out = run_node("console.log(JSON.stringify([1, 6, 36].map(freqToChannel)));")
        self.assertEqual(out, [1, 6, 36])


class TheMarkerLabelConverts(unittest.TestCase):
    """Asserted on the source: both surfaces must go through the same helper."""

    def setUp(self):
        self.js = REPORT_JS.read_text(encoding="utf-8")

    def test_the_marker_label_converts_before_printing_ch(self):
        start = self.js.index("function apMarkerLabel(")
        block = self.js[start:start + 1600]
        self.assertIn("'ch ' + ch.map(freqToChannel)", block)

    def test_no_surface_prints_a_raw_frequency_after_the_word_ch(self):
        """The regression: any `'ch ' + <frequencies>` without the conversion."""
        self.assertNotIn("'ch ' + ch.join(", self.js)

    def test_the_ap_table_still_converts_too(self):
        self.assertIn("freqToChannel(ch[0])", self.js)


if __name__ == "__main__":
    unittest.main()
