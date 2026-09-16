"""Prep names every step it ran, including the ones that had nothing to do.

Reported twice, the second time as "fuck quickwalls not working inside prep
either" - and both times the step was working. His projects already carry his
wall types, because he applies them in Quick Walls before Prep ever sees the
file. The step correctly adds nothing. The summary then named only the steps
that had changed something, so it said "trimmed 1 of 1 floor plan" and stopped:
wall types appeared nowhere, which from outside is indistinguishable from the
step never running.

Doing nothing because there is nothing to do is an outcome, and has to be said.
Three readings per step - did this, had nothing to do, could not run - and one
of them always applies.

Every assertion here fails against the previous build.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(a, b) {
  const i = src.indexOf(a), j = src.indexOf(b, i);
  if (i < 0 || j < 0) throw new Error('missing ' + a);
  return src.slice(i, j);
}
globalThis.plural = (n, w) => (n === 1 ? w : w + 's');
eval(slice('  function didWhat(', '\n  /* Opened from disk'));
const plain = s => s.replace(/<[^>]*>/g, '');
"""


def run_node(script):
    proc = subprocess.run(["node", "-e", PRELUDE + script, str(PREP_JS)],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=NODE_TIMEOUT_S)
    if proc.returncode != 0:
        raise AssertionError("node failed:\n" + proc.stderr)
    return json.loads(proc.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class EveryStepIsAccountedFor(unittest.TestCase):

    def say(self, report):
        return run_node(
            "console.log(JSON.stringify({ text: plain(didWhat("
            + json.dumps(report) + ")) }));")["text"]

    def test_wall_types_already_present_are_reported(self):
        """His case. The step ran, added nothing because there was nothing to
        add, and the summary used to omit it entirely."""
        text = self.say({"ran": ["trim", "walls"], "failed": [],
                         "trimmed": 1, "floorCount": 1,
                         "wallTypesAdded": [], "wallTypesPresent": 26})
        self.assertIn("wall type", text.lower(),
                      "the wall step ran and is not mentioned at all")
        self.assertIn("26", text)
        self.assertIn("already", text.lower())

    def test_nothing_to_trim_is_reported(self):
        text = self.say({"ran": ["trim"], "failed": [], "trimmed": 0,
                         "floorCount": 3})
        self.assertIn("trim", text.lower())

    def test_every_floor_already_had_an_area_is_reported(self):
        text = self.say({"ran": ["areas"], "failed": [], "areasWritten": []})
        self.assertIn("area", text.lower())
        self.assertIn("already", text.lower())

    def test_a_step_that_declined_is_named(self):
        text = self.say({"ran": ["trim", "areas", "walls"],
                         "failed": [{"step": "areas", "error": "no profiles"}],
                         "trimmed": 2, "floorCount": 2,
                         "wallTypesAdded": ["A"]})
        self.assertIn("did not add requirement areas", text.lower())

    def test_a_step_that_was_not_asked_for_is_not_mentioned(self):
        """Only steps he ticked. Reporting on one he turned off is noise."""
        text = self.say({"ran": ["trim"], "failed": [], "trimmed": 1,
                         "floorCount": 1})
        self.assertNotIn("wall type", text.lower())
        self.assertNotIn("requirement area", text.lower())

    def test_each_of_the_three_steps_produces_a_clause(self):
        text = self.say({"ran": ["trim", "areas", "walls"], "failed": [],
                         "trimmed": 0, "floorCount": 2, "areasWritten": [],
                         "wallTypesAdded": [], "wallTypesPresent": 26})
        for word in ("trim", "area", "wall type"):
            with self.subTest(step=word):
                self.assertIn(word, text.lower(),
                              f"a run of all three said nothing about {word}")

    def test_the_counts_that_are_reported_are_the_real_ones(self):
        text = self.say({"ran": ["trim", "walls"], "failed": [],
                         "trimmed": 2, "floorCount": 5,
                         "wallTypesAdded": ["A", "B", "C"]})
        self.assertIn("2", text)
        self.assertIn("5", text)
        self.assertIn("3", text)


class TheDownloadPathCarriesTheSameFacts(unittest.TestCase):
    """The dropped-file route builds its summary from a response header. A
    field missing there is a step that goes quiet on that path only, which is
    how this stayed half-fixed once already."""

    def test_the_header_carries_what_the_summary_needs(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        block = src[src.index("X-WD-Prep-Report"):]
        block = block[:block.index("return response")]
        for field in ("wallTypesAdded", "wallTypesPresent", "ran", "failed"):
            with self.subTest(field=field):
                self.assertIn(field, block,
                              f"{field} never reaches the page on the download path")


if __name__ == "__main__":
    unittest.main()
