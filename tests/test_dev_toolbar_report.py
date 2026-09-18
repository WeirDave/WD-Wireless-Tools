"""The realign report, rendered by the real function and read back.

`renderReport` is what turns the server's answer into the thing he reads
before deciding to write to ninety files, so the questions here are about
what it *says*: does a skipped file carry its reason, does the preview say
plainly that nothing has happened, does a failure look different from a skip.

The function is sliced out of `wd-dev-actions.js` and executed - it is the
code under test, not a paraphrase of it - with the genuine `WD.esc` from
`wd-shared.js`, because a project named with an ampersand or an angle bracket
is exactly what turns a readable report into broken markup.

Every project name and site folder here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTIONS_JS = ROOT / "web" / "assets" / "js" / "wd-dev-actions.js"
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const actions = fs.readFileSync(process.argv[1], 'utf8');
const shared  = fs.readFileSync(process.argv[2], 'utf8');

function slice(text, from, to) {
  const a = text.indexOf(from);
  if (a < 0) throw new Error('not found: ' + from);
  const b = to ? text.indexOf(to, a) : text.length;
  if (b < 0) throw new Error('no end for: ' + from);
  return text.slice(a, b);
}

/* `WD.esc` escapes by round-tripping through a div's textContent, so it
   needs that one DOM call and nothing else. This is the HTML fragment
   serialisation for a text node - `&`, `<` and `>`, and deliberately not
   quotes, which is what a browser does here. The real thing is exercised in
   a real DOM by the browser test; this keeps the renderer runnable in CI. */
globalThis.document = {
  createElement() {
    let text = '';
    return {
      set textContent(v) { text = String(v); },
      get textContent() { return text; },
      get innerHTML() {
        return text.replace(/&/g, '&amp;')
                   .replace(/</g, '&lt;')
                   .replace(/>/g, '&gt;');
      },
    };
  },
};

// the genuine escaper
const WD = {};
eval(slice(shared, '  WD.esc = function', '  WD.escAttr'));
globalThis.WD = WD;

// the genuine renderer and its helpers, straight out of the shipped file
eval(slice(actions, '  function esc(s)', '  Dev.toolbarInnerHtml'));
eval(slice(actions, '  function realignReport(', '  Dev.realignPreview'));
"""


def node(body: str):
    program = PRELUDE + body
    r = subprocess.run(["node", "-e", program, str(ACTIONS_JS), str(SHARED_JS)],
                       capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError("node failed:\n" + r.stdout + r.stderr)
    return json.loads(r.stdout)


def render(result, is_preview):
    """Run the real renderer and hand back the HTML plus its plain text."""
    body = """
    const html = realignReport(%s, %s);
    const text = html.replace(/<[^>]*>/g, ' ').replace(/\\s+/g, ' ').trim();
    process.stdout.write(JSON.stringify({ html: html, text: text }));
    """ % (json.dumps(result), "true" if is_preview else "false")
    return node(body)


ALIGNED = {"name": "Maple Depot Survey", "folder": "Maple Depot",
           "path": "C:/Projects/Maple Depot/Maple Depot Survey.esx",
           "actions": ["Set the name inside the file to match the cloud",
                       "Set the modified date to the cloud's"],
           "newDate": "2026-04-15T14:30:00.000Z"}

SKIPPED = {"name": "Birch Yard Walkthrough", "folder": "Birch Yard",
           "reason": "The designs genuinely differ - 3 access points added."}

FAILED = {"name": "Cedar Annexe Survey", "folder": "Cedar Annexe",
          "error": "Could not fetch the cloud copy: timed out"}


def report(**kw):
    base = {"ok": True, "dryRun": True, "examined": 0,
            "aligned": [], "skipped": [], "failed": [],
            "counts": {"aligned": 0, "skipped": 0, "failed": 0}}
    base.update(kw)
    base["counts"] = {k: len(base[k]) for k in ("aligned", "skipped", "failed")}
    base["examined"] = sum(base["counts"].values())
    return base


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class APreviewSaysNothingHasHappened(unittest.TestCase):

    def test_the_preview_says_so_in_words(self):
        """He reads this on a phone. "Nothing has been changed" has to be on
        screen, not implied by a button label he cannot see."""
        out = render(report(aligned=[ALIGNED]), True)
        self.assertIn("Nothing has been changed", out["text"])

    def test_the_preview_is_phrased_as_a_conditional(self):
        out = render(report(aligned=[ALIGNED]), True)
        self.assertIn("would be aligned", out["text"])

    def test_the_real_run_is_not(self):
        """The same numbers under a past tense. If the two read alike he
        cannot tell from the report which one he just did."""
        out = render(report(aligned=[ALIGNED], dryRun=False), False)
        self.assertNotIn("Nothing has been changed", out["text"])
        self.assertNotIn("would be aligned", out["text"])
        self.assertIn("aligned", out["text"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ItNamesEveryFileAndWhatHappensToIt(unittest.TestCase):

    def test_an_aligned_file_carries_its_actions(self):
        out = render(report(aligned=[ALIGNED]), True)
        self.assertIn("Maple Depot Survey", out["text"])
        self.assertIn("Set the name inside the file", out["text"])
        self.assertIn("Set the modified date", out["text"])

    def test_an_aligned_file_shows_the_date_it_would_get(self):
        out = render(report(aligned=[ALIGNED]), True)
        self.assertIn("2026-04-15", out["text"])

    def test_a_skipped_file_carries_its_reason(self):
        """The requirement was that genuine differences are skipped **and
        listed**. A count of skips he cannot investigate is not that."""
        out = render(report(skipped=[SKIPPED]), True)
        self.assertIn("Birch Yard Walkthrough", out["text"])
        self.assertIn("designs genuinely differ", out["text"])

    def test_a_failure_carries_its_error(self):
        out = render(report(failed=[FAILED]), False)
        self.assertIn("Cedar Annexe Survey", out["text"])
        self.assertIn("timed out", out["text"])

    def test_a_skip_and_a_failure_are_told_apart(self):
        """Different headings and different classes, because "we chose not
        to" and "we could not" call for different responses from him."""
        out = render(report(skipped=[SKIPPED], failed=[FAILED]), False)
        self.assertIn("Skipped", out["text"])
        self.assertIn("Failed", out["text"])
        # The property is the distinction, not the class names - see the
        # same change in test_housekeeping_report.py.
        import re
        skip = re.search(r'<span class="([^"]+)">The designs genuinely', out["html"])
        fail = re.search(r'<span class="([^"]+)">Could not fetch', out["html"])
        self.assertTrue(skip and fail)
        self.assertNotEqual(skip.group(1), fail.group(1))

    def test_a_backup_location_is_shown_for_a_file_that_was_rewritten(self):
        """He has been sent to the wrong place for an overwritten file
        before. Where the copy went belongs in the report."""
        entry = dict(ALIGNED,
                     backup="C:/Projects/backups/Maple Depot/"
                            "Maple Depot Survey.previous-20260415-143000.esx")
        out = render(report(aligned=[entry], dryRun=False), False)
        self.assertIn("previous-20260415-143000.esx", out["text"])

    def test_a_warning_about_the_disk_date_is_surfaced(self):
        entry = dict(ALIGNED, warning="Contents updated, but the file's date "
                                      "on disk could not be set: denied")
        out = render(report(aligned=[entry], dryRun=False), False)
        self.assertIn("could not be set", out["text"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheTallyAndTheEdges(unittest.TestCase):

    def test_the_tally_matches_the_lists(self):
        out = render(report(aligned=[ALIGNED], skipped=[SKIPPED],
                            failed=[FAILED]), True)
        self.assertRegex(out["text"], r"Examined 3 pairs")

    def test_one_pair_is_singular(self):
        """A tool that says "1 pairs" reads as unfinished."""
        out = render(report(aligned=[ALIGNED]), True)
        self.assertIn("1 pair.", out["text"])
        self.assertNotIn("1 pairs", out["text"])

    def test_nothing_to_do_says_so_rather_than_showing_empty_headings(self):
        out = render(report(), True)
        self.assertIn("Nothing to do", out["text"])

    def test_a_missing_answer_is_not_rendered_as_success(self):
        body = """
        const html = realignReport(null, true);
        process.stdout.write(JSON.stringify({ html: html, text: html }));
        """
        out = node(body)
        self.assertIn("No answer from the server", out["text"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class NamesAreEscaped(unittest.TestCase):
    """A project name is user data and this is HTML. The real `WD.esc` runs
    here for the same reason the sync-direction tests use the real
    `escJsStr`: the apostrophe case is what turns a working control into a
    broken one."""

    def test_angle_brackets_in_a_name_do_not_become_markup(self):
        entry = dict(ALIGNED, name="<script>alert(1)</script> Depot")
        out = render(report(aligned=[entry]), True)
        self.assertNotIn("<script>", out["html"])
        self.assertIn("&lt;script&gt;", out["html"])

    def test_an_ampersand_survives_as_itself(self):
        entry = dict(SKIPPED, name="Maple & Birch Depot")
        out = render(report(skipped=[entry]), True)
        self.assertIn("&amp;", out["html"])
        self.assertIn("Maple & Birch Depot", out["text"].replace("&amp;", "&"))


if __name__ == "__main__":
    unittest.main()
