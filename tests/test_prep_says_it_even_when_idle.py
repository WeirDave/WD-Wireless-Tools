"""A Prep run that changes nothing still names every step it ran.

Reported three times, the last time as "fuck quickwalls not working inside
prep either", and the step was working every time. The gap was never in the
pipeline - it was in the one branch of the page nobody had looked at.

v2.103.1 rewrote `didWhat` so a step that had nothing to do says so. But both
result renderers reach `didWhat` **only when a file was written**:

    if (!r.written) { host.innerHTML = r.note || 'Nothing needed doing.'; return; }

His projects are exactly the case that branch catches. He applies his wall
template in Quick Walls before Prep ever sees the file, and by the second run
the plans are already trimmed - so nothing is written, and all three steps were
summed up in one generic line that named none of them. From outside that is
indistinguishable from Prep not running the wall step at all.

The pipeline was sending everything needed the whole time: the JSON on that
path carries `ran`, `failed` and `step.walls.skip`. Nothing read it.

Both paths are covered here - the download route and the open-from-disk route,
which is the one he actually uses - because a fix to one of them is how this
stayed half-fixed once already. Everything is synthetic.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from server import API_REQUEST_HEADER, app  # noqa: E402
from test_prep_trim_options import make_esx  # noqa: E402
from tools.template_store import TemplateStore  # noqa: E402

PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"
PLANTRIM_HTML = ROOT / "web" / "plantrim.html"

PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(a, b) {
  const i = src.indexOf(a), j = src.indexOf(b, i);
  if (i < 0 || j < 0) throw new Error('missing ' + a);
  return src.slice(i, j);
}
globalThis.plural = (n, w) => (n === 1 ? w : w + 's');
globalThis.WD = { esc: s => String(s) };
globalThis.esc = s => String(s);
eval(slice('  function didWhat(', '\n  /* Opened from disk'));
eval(slice('  function summaryOf(r)', '  function renderWritten('));
const plain = s => s.replace(/<[^>]*>/g, '');
"""


def run_node(script):
    proc = subprocess.run(["node", "-e", PRELUDE + script, str(PREP_JS)],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=120)
    if proc.returncode != 0:
        raise AssertionError("node failed:\n" + proc.stderr)
    return json.loads(proc.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ANoChangeRunStillNamesEveryStep(unittest.TestCase):
    """The pipeline's own nested shape, which is what both the open-from-disk
    route and the nothing-to-do route hand the page."""

    def say(self, report):
        return run_node(
            "console.log(JSON.stringify({ text: plain(summaryOf("
            + json.dumps(report) + ")) }));")["text"]

    def test_wall_types_already_there_are_named_on_a_run_that_wrote_nothing(self):
        """His case, exactly."""
        text = self.say({
            "ok": True, "written": False, "ran": ["trim", "areas", "walls"],
            "failed": [],
            "step": {"trim": {"trimmedCount": 0, "floorCount": 2},
                     "areas": {"floorsWritten": []},
                     "walls": {"add": [], "skip": [{"name": f"W{i}"} for i in range(26)]}},
        })
        self.assertIn("wall type", text.lower(),
                      "the wall step ran and is not mentioned at all")
        self.assertIn("26", text)
        self.assertIn("already", text.lower())

    def test_all_three_steps_appear(self):
        text = self.say({
            "ok": True, "written": False, "ran": ["trim", "areas", "walls"],
            "failed": [],
            "step": {"trim": {"trimmedCount": 0, "floorCount": 3},
                     "areas": {"floorsWritten": []},
                     "walls": {"add": [], "skip": [{"name": "W"}]}},
        })
        for word in ("trim", "area", "wall type"):
            with self.subTest(step=word):
                self.assertIn(word, text.lower())

    def test_a_declined_step_is_still_named(self):
        text = self.say({
            "ok": True, "written": False, "ran": ["trim", "areas"],
            "failed": [{"step": "areas", "error": "no capacity template"}],
            "step": {"trim": {"trimmedCount": 0, "floorCount": 1}},
        })
        self.assertIn("did not add requirement areas", text.lower())

    def test_the_flat_header_shape_still_works(self):
        """The download path sends a flat report with no `step` key. One
        builder has to handle both or the fix lands on one route only."""
        text = self.say({"ran": ["walls"], "failed": [], "wallTypesAdded": [],
                         "wallTypesPresent": 26})
        self.assertIn("26", text)
        self.assertIn("already", text.lower())


class NeitherRendererShortCircuitsToAGenericLine(unittest.TestCase):
    """The specific regression. Both `renderWritten` and `renderResult` bailed
    out before the summary when nothing had been written."""

    def setUp(self):
        self.js = PREP_JS.read_text(encoding="utf-8")

    def test_the_old_generic_line_is_gone_from_both_renderers(self):
        self.assertNotIn("Nothing needed doing.", self.js,
                         "a run that changed nothing still says only that")

    def test_both_no_change_branches_go_through_the_summary(self):
        for fn in ("renderWritten", "renderResult"):
            with self.subTest(renderer=fn):
                body = self.js[self.js.index("function " + fn):]
                body = body[:body.index("\n  }\n")]
                self.assertIn("renderNothingToDo", body,
                              f"{fn} still has its own bail-out")

    def test_a_refusal_is_shown_on_the_no_change_path_too(self):
        body = self.js[self.js.index("function renderNothingToDo"):]
        body = body[:body.index("\n  }\n")]
        self.assertIn("missedBlock", body,
                      "a step that declined is invisible when nothing was written")


class PrepAndQuickWallsReadTheSameTemplates(unittest.TestCase):
    """The leading theory for this bug, and worth holding even though it was
    not the cause: if Prep loaded a bundled default while Quick Walls used the
    saved one, every synthetic test would pass and nothing useful would happen
    on his machine."""

    def test_one_store_serves_both(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("TemplateStore()"), 1,
                         "a second store is a second answer to 'which template'")
        # The Quick Walls scan action and Prep's template list are the same call.
        self.assertIn('"scan":         lambda d: ts.scan()', src)
        # Anchored on Prep's own handler - Capacity has a `templates` action
        # too, and matching the first one found tests the wrong route.
        prep = src[src.index('"wall": [{"name": t["name"]'):]
        self.assertIn("ts.scan()", prep[:400],
                      "Prep builds its template list from somewhere else")

    def test_the_run_uses_the_template_the_list_offered(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        block = src[src.index('wall_file = request.args.get("wallTemplate")'):]
        self.assertIn("ts.scan()", block[:400])
        self.assertIn('t.get("file") == wall_file', block[:400])

    def test_the_real_shipped_template_actually_lands_in_a_project(self):
        """Driven through the route with whatever template this install really
        has, rather than a fixture built to match the matcher."""
        tpl = next((t for t in TemplateStore().scan().get("templates", [])
                    if t.get("wallTypes")), None)
        if tpl is None:
            self.skipTest("no wall template on this install")
        tmp = Path(tempfile.mkdtemp(prefix="wd-prep-walls-"))
        try:
            src = make_esx(tmp / "in.esx")
            with zipfile.ZipFile(src) as z:
                members = {n: z.read(n) for n in z.namelist()}
            members["wallTypes.json"] = json.dumps({"wallTypes": []}).encode()
            bare = tmp / "bare.esx"
            with zipfile.ZipFile(bare, "w", zipfile.ZIP_DEFLATED) as z:
                for k, v in members.items():
                    z.writestr(k, v)

            client = app.test_client()
            r = client.post(
                "/api/prep/run?name=x.esx&steps=walls&wallTemplate="
                + tpl["file"], data=bare.read_bytes(),
                headers={API_REQUEST_HEADER: "1"})
            try:
                body = r.get_data()
                self.assertEqual(body[:2], b"PK",
                                 "the wall step wrote no file at all")
                import io
                with zipfile.ZipFile(io.BytesIO(body)) as z:
                    got = json.loads(z.read("wallTypes.json"))["wallTypes"]
            finally:
                r.close()
            self.assertEqual(len(got), len(tpl["wallTypes"]),
                             "the template did not reach the saved project")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ResetViewSaysWhatItResets(unittest.TestCase):
    """It resets the view - zoom and position - and deliberately not the
    rectangle or the margin. A button that threw away a drawn rectangle under
    the word "view" would destroy work, and the margin is a saved preference
    shared with Prep. `Back to automatic` is the control that discards a box.
    """

    def test_the_two_jobs_have_two_separate_buttons(self):
        html = PLANTRIM_HTML.read_text(encoding="utf-8")
        self.assertIn('id="ptbFit"', html)
        self.assertIn('id="ptbClear"', html)

    def test_the_tooltip_says_what_it_does_not_touch(self):
        html = PLANTRIM_HTML.read_text(encoding="utf-8")
        tip = html[html.index('id="ptbFit"'):]
        tip = tip[:tip.index("</button>")]
        for phrase in ("zoom", "Back to automatic", "margin"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, tip)

    def test_reset_ignores_any_rectangle_on_the_floor(self):
        js = (ROOT / "web" / "assets" / "js" / "plantrim.js").read_text(encoding="utf-8")
        body = js[js.index("window.ptbFitView = function"):]
        body = body[:body.index("\n  };")]
        self.assertIn("fitView(true)", body,
                      "reset re-frames whatever is drawn instead of going back")


class ThePreviewIsTheCropNotAnImpressionOfIt(unittest.TestCase):
    """The original complaint was that the margin did not visibly move the box.
    Half of that was the box never being drawn; the other half is that the
    preview has to be computed by the same code as the crop, or the two can
    drift and "what I saw is not what I got" arrives later."""

    def test_analyze_and_trim_are_the_same_function(self):
        src = (ROOT / "tools" / "esx_trimmer.py").read_text(encoding="utf-8")
        analyze = src[src.index("def analyze("):]
        analyze = analyze[:analyze.index("\ndef ")]
        self.assertIn("dry_run=True", analyze)
        self.assertIn("_run(", analyze)
        trim = src[src.index("def trim("):]
        trim = trim[:trim.index("\ndef ")]
        self.assertIn("dry_run=False", trim)
        self.assertIn("_run(", trim)

    def test_the_preview_and_the_saved_file_agree_at_every_margin(self):
        """Measured, both ways, rather than inferred from the source."""
        from tools import esx_trimmer
        tmp = Path(tempfile.mkdtemp(prefix="wd-preview-"))
        try:
            src = make_esx(tmp / "in.esx", mpu=0.5)
            for preset in esx_trimmer.MARGIN_PRESET_FEET:
                with self.subTest(preset=preset):
                    shown = esx_trimmer.analyze(src, margin=preset).floors[0]
                    dest = tmp / f"o-{preset}.esx"
                    saved = esx_trimmer.trim(src, dest, margin=preset).floors[0]
                    self.assertEqual(shown.action, saved.action)
                    self.assertEqual(shown.new_size, saved.new_size)
                    self.assertEqual(shown.offset, saved.offset)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_different_margin_is_a_different_preview(self):
        from tools import esx_trimmer
        tmp = Path(tempfile.mkdtemp(prefix="wd-preview2-"))
        try:
            src = make_esx(tmp / "in.esx", mpu=0.5)
            sizes = {esx_trimmer.analyze(src, margin=p).floors[0].new_size
                     for p in esx_trimmer.MARGIN_PRESET_FEET}
            self.assertEqual(len(sizes), len(esx_trimmer.MARGIN_PRESET_FEET),
                             f"two presets previewed the same box: {sizes}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
