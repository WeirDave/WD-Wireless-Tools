"""A file picker that cannot open must not look like a picker you cancelled.

The report was "I selected the option and there was nothing that allowed me to
move forward", and that is exactly what the code did. `_tk_dialog` caught every
exception and returned the empty string; both `pick` routes turned the empty
string into `No file selected`; and every page suppresses that message on
purpose, because it reads as a cancel and a cancel should be silent.

So three different situations collapsed into one, and the one they collapsed
into was the silent one. Driven in Chrome, Edge and Firefox against the exact
response the server sends in that case, clicking **Open from disk...** left the
page unchanged by a single character: no toast, no editor, no hint, nothing.

What is tested here is the distinction, at all three levels it has to survive:
the helper that runs the dialog, the route that reports it, and the page that
has to do something useful with it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.folder_organizer import _tk_dialog, _tk_dialog_result  # noqa: E402

PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"
WALLS_JS = ROOT / "web" / "assets" / "js" / "walls.js"
NODE_TIMEOUT_S = 120


class TheHelperTellsTheThreeApart(unittest.TestCase):
    """No GUI is opened here - these are ordinary subprocesses that print."""

    def test_a_chosen_path_comes_back(self):
        res = _tk_dialog_result("print('C:\\\\somewhere\\\\a project.esx')")
        self.assertTrue(res["ran"])
        self.assertEqual(res["path"], "C:\\somewhere\\a project.esx")
        self.assertEqual(res["why"], "")

    def test_a_cancel_is_ran_with_no_path(self):
        """The dialog opened and the person chose nothing. Stays silent."""
        res = _tk_dialog_result("print('')")
        self.assertTrue(res["ran"], "a cancel must not be reported as a failure")
        self.assertEqual(res["path"], "")

    def test_a_dialog_that_cannot_run_says_so(self):
        """Tk missing, no window station, a crashed interpreter."""
        res = _tk_dialog_result(
            "import sys; sys.stderr.write('no display name\\n'); sys.exit(1)")
        self.assertFalse(res["ran"])
        self.assertEqual(res["path"], "")
        self.assertTrue(res["why"], "a failure has to carry a reason")
        self.assertIn("closed immediately", res["why"])

    def test_the_childs_own_message_is_kept(self):
        res = _tk_dialog_result(
            "import sys; sys.stderr.write('TclError: no display\\n'); sys.exit(1)")
        self.assertIn("TclError", res["why"])

    def test_a_dialog_nobody_answers_times_out_and_says_so(self):
        res = _tk_dialog_result("import time; time.sleep(30)", timeout=1)
        self.assertFalse(res["ran"])
        self.assertIn("did not respond", res["why"])

    def test_the_old_helper_still_returns_just_the_path(self):
        """Existing callers are untouched; only the new ones distinguish."""
        self.assertEqual(_tk_dialog("print('/tmp/x.esx')"), "/tmp/x.esx")
        self.assertEqual(_tk_dialog("import sys; sys.exit(1)"), "")


class TheRoutesReportIt(unittest.TestCase):
    def setUp(self):
        import server
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        self.headers = {"X-WD-Wireless-Tools": "1"}

    def _pick(self, route, result):
        with mock.patch("tools.folder_organizer._tk_dialog_result",
                        return_value=result):
            r = self.client.post(route, headers=self.headers)
            try:
                return r.get_json()
            finally:
                r.close()

    def test_prep_says_the_picker_was_unavailable(self):
        body = self._pick("/api/prep/pick",
                          {"path": "", "ran": False, "why": "no display"})
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "picker_unavailable")
        self.assertIn("no display", body["error"])

    def test_walls_says_the_picker_was_unavailable(self):
        body = self._pick("/api/walls/pick",
                          {"path": "", "ran": False, "why": "no display"})
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "picker_unavailable")

    def test_a_cancel_keeps_the_wording_every_page_suppresses(self):
        """Changing this string would start toasting every cancel."""
        for route in ("/api/prep/pick", "/api/walls/pick"):
            with self.subTest(route=route):
                body = self._pick(route, {"path": "", "ran": True, "why": ""})
                self.assertFalse(body["ok"])
                self.assertEqual(body["code"], "cancelled")
                self.assertEqual(body["error"], "No file selected")

    def test_the_two_are_not_the_same_answer(self):
        """The whole defect in one assertion."""
        cancelled = self._pick("/api/prep/pick",
                               {"path": "", "ran": True, "why": ""})
        broken = self._pick("/api/prep/pick",
                            {"path": "", "ran": False, "why": "no display"})
        self.assertNotEqual(cancelled["error"], broken["error"])
        self.assertNotEqual(cancelled.get("code"), broken.get("code"))


PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from);
  if (a < 0) throw new Error('could not find ' + from);
  const b = src.indexOf(to, a);
  if (b < 0) throw new Error('could not find ' + to);
  return src.slice(a, b + to.length);
}

const log = { toasts: [], browseOpened: 0, editorOpened: 0 };

const stubEl = function (id) {
  return {
    id: id, value: '', textContent: '', title: '', disabled: false,
    innerHTML: '', style: {}, classList: { add() {}, remove() {} },
    click() { if (id === 'fileInput') log.browseOpened++; },
  };
};
const els = {};
global.document = {
  getElementById(id) { return (els[id] = els[id] || stubEl(id)); },
  querySelector(sel) { return (els[sel] = els[sel] || stubEl(sel)); },
  querySelectorAll() { return []; },
  addEventListener() {},
};
global.WD = { toast(m, k) { log.toasts.push(String(m)); }, esc: s => s };
global.window = global;
"""


def run_node(script: str, js_path: Path) -> dict:
    proc = subprocess.run(["node", "-e", PRELUDE + script, str(js_path)],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=NODE_TIMEOUT_S)
    if proc.returncode != 0:
        raise AssertionError("node failed:\n" + proc.stderr)
    return json.loads(proc.stdout)


PREP_HARNESS = r"""
eval(slice('window.prepOpenFromDisk = function () {', '\n  };'));
function $(id) { return document.getElementById(id); }
let fromDisk = false, fileBytes = null;
function openEditor(name) { log.editorOpened++; }
function preview() {}

global.fetch = function () {
  return Promise.resolve({ json: () => Promise.resolve(ANSWER) });
};
window.prepOpenFromDisk();
setTimeout(function () { console.log(JSON.stringify(log)); }, 50);
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePageDoesSomethingUseful(unittest.TestCase):
    """Driving the real handler, because the fault was that it did nothing."""

    def _prep(self, answer):
        return run_node("const ANSWER = %s;\n%s" % (json.dumps(answer),
                                                    PREP_HARNESS), PREP_JS)

    def test_an_unavailable_picker_says_so_and_opens_the_browse_dialog(self):
        out = self._prep({"ok": False, "code": "picker_unavailable",
                          "error": "Could not open the file picker."})
        self.assertEqual(len(out["toasts"]), 1, out)
        self.assertIn("Could not open the file picker", out["toasts"][0])
        self.assertIn("drop zone", out["toasts"][0],
                      "the message has to say what to do instead")
        self.assertEqual(out["browseOpened"], 1,
                         "a click that leads nowhere is the defect; "
                         "fall through to the ordinary file input")

    def test_a_cancel_stays_silent_and_opens_nothing(self):
        out = self._prep({"ok": False, "code": "cancelled",
                          "error": "No file selected"})
        self.assertEqual(out["toasts"], [])
        self.assertEqual(out["browseOpened"], 0,
                         "re-opening a dialog he just dismissed is its own bug")

    def test_a_chosen_file_opens_the_editor(self):
        out = self._prep({"ok": True, "name": "sample.esx", "dir": "C:/x"})
        self.assertEqual(out["editorOpened"], 1)
        self.assertEqual(out["browseOpened"], 0)


class BothPagesGotIt(unittest.TestCase):
    """Quick Walls has the same button and had the same dead end."""

    def test_quick_walls_handles_the_unavailable_picker(self):
        js = WALLS_JS.read_text(encoding="utf-8")
        body = js[js.index("async function openFromDisk"):]
        body = body[:body.index("window.openFromDisk")]
        self.assertIn("picker_unavailable", body)
        self.assertIn("fileInput.click()", body)

    def test_both_buttons_show_that_they_are_working(self):
        """The dialog can take a while; a button that looks idle reads as dead."""
        for path in (PREP_JS, WALLS_JS):
            with self.subTest(file=path.name):
                js = path.read_text(encoding="utf-8")
                self.assertIn("Opening\u2026", js)
                self.assertIn("dropzone-open-disk", js)


if __name__ == "__main__":
    unittest.main()
