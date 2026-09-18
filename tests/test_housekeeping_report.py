"""The housekeeping report, rendered by the real function and read back.

He reads this before deciding to delete thousands of things, so the questions
here are about what it *says*: does it lead with the workplace-data count,
does it say plainly what is being kept and why, does it never print the value
it matched on.

The renderers are sliced out of `wd-dev-actions.js` and executed - the code
under test, not a paraphrase - with the genuine `WD.esc`.

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

/* `WD.esc` escapes by round-tripping through a div's textContent, so it needs
   that one DOM call and nothing else. This is the HTML fragment serialisation
   for a text node - `&`, `<` and `>`, and deliberately not quotes. The real
   thing runs in a real DOM in the browser test. */
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

const WD = {};
eval(slice(shared, '  WD.esc = function', '  WD.escAttr'));
globalThis.WD = WD;

// esc/plural from the top of the file, then the housekeeping renderers.
eval(slice(actions, '  function esc(s)', '  function fileLine('));
// Single-line markers only: the checked-out file has CRLF endings, so a
// marker spanning two lines silently never matches. `indexOf(to, a)`
// searches forward from the start marker, so the bare register line finds
// the housekeeping one rather than the realign one above it.
eval(slice(actions, '  function mb(bytes)', '  WD.Dev.register({'));
"""


def node(body):
    program = PRELUDE + body
    r = subprocess.run(["node", "-e", program, str(ACTIONS_JS), str(SHARED_JS)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError("node failed:\n" + (r.stdout or "") + (r.stderr or ""))
    return json.loads(r.stdout)


def render(fn, payload):
    body = """
    const html = %s(%s);
    const text = html.replace(/<[^>]*>/g, ' ').replace(/\\s+/g, ' ').trim();
    process.stdout.write(JSON.stringify({ html: html, text: text }));
    """ % (fn, json.dumps(payload))
    return node(body)


def entry(**kw):
    base = {"path": "C:/Temp/wd-cloud-pull-a1", "name": "wd-cloud-pull-a1",
            "kind": "dir", "sizeBytes": 2_500_000, "files": 3,
            "truncated": False, "modified": 1_760_000_000, "idleHours": 30.0,
            "live": False, "liveReason": "", "dataFindings": 0,
            "deletable": True, "note": "A temp directory the suite made."}
    base.update(kw)
    return base


def survey(groups=None, processes=None, complete=True, **totals):
    groups = groups or []
    every = [e for g in groups for e in g["entries"]]

    def tot(entries):
        return {"count": len(entries),
                "sizeBytes": sum(e["sizeBytes"] for e in entries),
                "deletable": sum(1 for e in entries if e["deletable"]),
                "deletableBytes": sum(e["sizeBytes"] for e in entries if e["deletable"]),
                "live": sum(1 for e in entries if e["live"]),
                "withData": sum(1 for e in entries if e["dataFindings"]),
                "dataFindings": sum(e["dataFindings"] for e in entries)}
    for g in groups:
        g["totals"] = tot(g["entries"])
    out = {"ok": True, "groups": groups, "totals": tot(every),
           "processes": processes or [], "liveWindowMinutes": 20,
           "dataScanComplete": complete}
    out["totals"].update(totals)
    return out


def group(key="tests", title="Test suite leftovers", entries=None):
    return {"key": key, "title": title, "entries": entries or []}


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheDataQuestionComesFirst(unittest.TestCase):
    """It is not about disk space. It is that copies of his site data should
    not be scattered around, and that is the line he should read first."""

    def test_it_leads_with_the_workplace_data_count(self):
        out = render("renderSurvey", survey([group(entries=[
            entry(dataFindings=3, name="wd-cloud-pull-flagged")])]))
        lead = out["text"].split(" items ")[0]
        self.assertIn("workplace data", lead)
        self.assertIn("1 item carries", out["text"])

    def test_it_counts_the_signals_without_printing_them(self):
        out = render("renderSurvey", survey([group(entries=[
            entry(dataFindings=7)])]))
        self.assertIn("7 signals", out["text"])
        self.assertIn("values are deliberately not shown", out["text"])

    def test_a_clean_machine_says_so_plainly(self):
        out = render("renderSurvey", survey([group(entries=[entry()])]))
        self.assertIn("No workplace data found", out["text"])

    def test_a_truncated_scan_is_reported_as_a_floor(self):
        """A count that stopped early must not read as a total."""
        out = render("renderSurvey", survey(
            [group(entries=[entry(dataFindings=2)])], complete=False))
        self.assertIn("floor", out["text"])

    def test_a_truncated_scan_with_no_findings_is_still_qualified(self):
        out = render("renderSurvey", survey(
            [group(entries=[entry()])], complete=False))
        self.assertIn("partial answer", out["text"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ItSaysWhatIsKeptAndWhy(unittest.TestCase):

    def test_a_live_item_is_shown_with_its_reason(self):
        out = render("renderSurvey", survey([group(entries=[
            entry(name="live-session", live=True, deletable=False,
                  liveReason="Registered as a worktree - a session may be using it.")])]))
        self.assertIn("Kept", out["text"])
        self.assertIn("Registered as a worktree", out["text"])

    def test_a_desktop_item_says_it_will_not_be_deleted_from_there(self):
        out = render("renderSurvey", survey([group(
            key="listed", title="Ours, but somewhere we will not delete from",
            entries=[entry(name="cloud-flat-1920.png", deletable=False,
                           note="On your Desktop - listed only, never deleted from here.")])]))
        self.assertIn("never deleted from here", out["text"])

    def test_the_tally_separates_safe_from_in_use(self):
        out = render("renderSurvey", survey([group(entries=[
            entry(name="a"), entry(name="b", live=True, deletable=False)])]))
        self.assertIn("1 safe to remove", out["text"])
        self.assertIn("1 in use, left alone", out["text"])

    def test_a_long_list_is_capped_rather_than_dumped(self):
        """Three thousand lines is not a report he can read on a phone."""
        many = [entry(name="wd-cloud-pull-%d" % i) for i in range(40)]
        out = render("renderSurvey", survey([group(entries=many)]))
        self.assertIn("more of the same", out["text"])
        self.assertLess(out["text"].count("wd-cloud-pull-"), 20)

    def test_an_empty_machine_says_nothing_to_clean_up(self):
        out = render("renderSurvey", survey([]))
        self.assertIn("Nothing to clean up", out["text"])

    def test_sizes_are_human_readable(self):
        out = render("renderSurvey", survey([group(entries=[
            entry(sizeBytes=2_500_000_000)])]))
        self.assertIn("GB", out["text"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ProcessesAreListedWithAReason(unittest.TestCase):

    def test_a_process_says_what_it_is(self):
        out = render("renderSurvey", survey([], processes=[
            {"pid": 4242, "name": "geckodriver.exe",
             "why": "A WebDriver executable, started by a test run."}]))
        self.assertIn("geckodriver.exe", out["text"])
        self.assertIn("pid 4242", out["text"])
        self.assertIn("WebDriver executable", out["text"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheSweepReportAccountsForEverything(unittest.TestCase):

    def sweep(self, removed=(), skipped=(), failed=(), freed=0):
        return {"ok": True, "removed": list(removed), "skipped": list(skipped),
                "failed": list(failed),
                "counts": {"removed": len(removed), "skipped": len(skipped),
                           "failed": len(failed)},
                "freedBytes": freed}

    def test_it_says_how_much_was_freed(self):
        out = render("renderSweep", self.sweep(
            removed=[entry()], freed=1_500_000_000))
        self.assertIn("Removed 1 item", out["text"])
        self.assertIn("1.40 GB", out["text"])

    def test_a_skip_carries_its_reason(self):
        out = render("renderSweep", self.sweep(skipped=[
            dict(entry(name="woke-up"),
                 reason="Changed 2 minutes ago - assumed to be in use.")]))
        self.assertIn("woke-up", out["text"])
        self.assertIn("assumed to be in use", out["text"])

    def test_a_failure_carries_its_error(self):
        out = render("renderSweep", self.sweep(failed=[
            dict(entry(name="stuck"), error="in use by another process")]))
        self.assertIn("stuck", out["text"])
        self.assertIn("in use by another process", out["text"])

    def test_a_skip_and_a_failure_are_told_apart(self):
        out = render("renderSweep", self.sweep(
            skipped=[dict(entry(name="s"), reason="because")],
            failed=[dict(entry(name="f"), error="boom")]))
        self.assertIn("wd-dev-file-reason", out["html"])
        self.assertIn("wd-dev-file-error", out["html"])

    def test_a_missing_answer_is_not_rendered_as_success(self):
        for fn in ("renderSurvey", "renderSweep"):
            with self.subTest(fn=fn):
                out = render(fn, None)
                self.assertIn("No answer from the server", out["text"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class NamesAreEscaped(unittest.TestCase):
    """A path is data and this is HTML."""

    def test_angle_brackets_in_a_name_do_not_become_markup(self):
        out = render("renderSurvey", survey([group(entries=[
            entry(name="<script>alert(1)</script>")])]))
        self.assertNotIn("<script>", out["html"])
        self.assertIn("&lt;script&gt;", out["html"])


if __name__ == "__main__":
    unittest.main()
