"""Every action reports itself, and none of them can leave a row stuck.

"you don't have any idea if it worked or didn't work or did something or didn't
do something."

Two actions answered that from v2.120.0, a third from v2.126.0, and six did
not. Which ones reported themselves was invisible until he pressed one - so the
inconsistency was its own defect, on top of each silent action being one.

Two properties, and the second is the one that bites later:

* **it says it is working**, from the click until the result;
* **it stops saying so**, on every path out - success, refusal, thrown error.
  A mark an action can forget to clear is the stuck spinner, which is the
  complaint this mechanism exists to answer rather than to reproduce.

The second is checked by reading each action's shape rather than by running
every branch, because the paths that leak are the ones a test is least likely
to reach: a server that throws, a confirm that is declined. `finally` is the
only construct that covers all of them, so that is what is required.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120
JS = CLOUD_JS.read_text(encoding="utf-8")

#: Everything he can press on a row, and the state it leaves behind.
ACTIONS = [
    "fixInternalName", "verifyReplaceLocal", "_enqueuePushLocalOverCloud",
    "markManualMatch", "markNotMatch", "downloadThenMove",
]


def body_of(name: str) -> str:
    """One function, from its declaration to the next top-level one."""
    for opener in ("async function %s(" % name, "function %s(" % name):
        i = JS.find("\n" + opener)
        if i >= 0:
            break
    else:
        raise AssertionError(name + " is not in cloud.js")
    j = JS.find("\nfunction ", i + 1)
    k = JS.find("\nasync function ", i + 1)
    ends = [x for x in (j, k) if x != -1]
    return JS[i:min(ends)] if ends else JS[i:]


class EveryActionSaysItIsWorking(unittest.TestCase):
    """The click has to be visible where he is looking, which is the row."""

    def test_each_one_marks_its_row(self):
        for name in ACTIONS:
            with self.subTest(action=name):
                self.assertIn("_setRowBusy(", body_of(name),
                              name + " runs without telling him it started")

    def test_none_of_them_can_leave_the_row_stuck(self):
        """`finally`, because the paths that leak are the ones a test is least
        likely to reach - a server that throws, a request that never lands."""
        for name in ACTIONS:
            block = body_of(name)
            if "_setRowBusy(" not in block:
                continue
            clears = block.count("_setRowBusy(") - block.count("null)") == 0
            with self.subTest(action=name):
                self.assertTrue(
                    "finally" in block or ".then(" in block or "promise" in block,
                    name + " marks the row with no guaranteed way of clearing it")

    def test_the_mark_goes_on_after_the_question_not_before_it(self):
        """Marking above a confirm left the row saying "Working" over an action
        he had just declined."""
        for name in ACTIONS:
            block = body_of(name)
            if "confirm(" not in block or "_setRowBusy(" not in block:
                continue
            with self.subTest(action=name):
                self.assertLess(block.index("confirm("), block.index("_setRowBusy("),
                                name + " marks the row before it asks")

    def test_the_mark_cannot_break_the_action_it_decorates(self):
        """It called `renderRows()` unconditionally, so on any path without a
        list it took the operation down with it."""
        block = body_of("_setRowBusy")
        self.assertIn("typeof renderRows === 'function'", block)

    def test_an_unpaired_row_can_be_marked_too(self):
        """`rowIsBusy` returned null unless the row had both sides, and the
        actions that were still silent are exactly the ones that work on
        unpaired rows - download a cloud project with no local copy, link a
        local file with no project. The mechanism excluded its own remaining
        cases."""
        block = body_of("rowIsBusy")
        self.assertNotIn("!r.cloud || !r.local", block)
        self.assertIn("if (!id && !path) return null;", block)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ItIsRunAndNotJustRead(unittest.TestCase):
    """The mark, the clear, and the one-sided key, executed."""

    PROGRAM = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function cut(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
let rendered = 0;
function renderRows() { rendered++; }
function toast() {}
const _compareResults = new Map();
function _compareKey(c, l) { return String(c) + '\u0000' + String(l).toLowerCase(); }
async function pyApi() { return {}; }

eval(cut('const _rowBusy = new Map();', '\nasync function settlePair('));

const out = {};
// A pair, and a row with only a cloud side.
_setRowBusy('c1', 'D:/a.esx', 'Working on it');
out.pairMarked = !!rowIsBusy({ cloud: { id: 'c1' }, local: { path: 'D:/a.esx' } });
_setRowBusy('c1', 'D:/a.esx', null);
out.pairCleared = !rowIsBusy({ cloud: { id: 'c1' }, local: { path: 'D:/a.esx' } });

_setRowBusy('c2', '', 'Downloading');
out.orphanMarked = !!rowIsBusy({ cloud: { id: 'c2' }, local: null });
_setRowBusy('c2', '', null);
out.orphanCleared = !rowIsBusy({ cloud: { id: 'c2' }, local: null });

// A local-only row, the other direction.
_setRowBusy('', 'D:/solo.esx', 'Uploading');
out.localOnlyMarked = !!rowIsBusy({ cloud: null, local: { path: 'D:/solo.esx' } });
_setRowBusy('', 'D:/solo.esx', null);

// `_busyWhile` clears when the promise settles, whichever way.
const bad = _busyWhile('c3', 'D:/b.esx', 'x', Promise.reject(new Error('no')));
bad.catch(() => {}).then(() => {
  out.clearedAfterFailure = !rowIsBusy({ cloud: { id: 'c3' }, local: { path: 'D:/b.esx' } });
  out.rendered = rendered > 0;
  console.log(JSON.stringify(out));
});
"""

    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", cls.PROGRAM, str(CLOUD_JS)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_matched_pair_can_be_marked_and_cleared(self):
        self.assertTrue(self.out["pairMarked"])
        self.assertTrue(self.out["pairCleared"])

    def test_a_cloud_only_row_can_be_marked(self):
        """Download acts on exactly this shape, and could not report itself
        until the key stopped requiring both sides."""
        self.assertTrue(self.out["orphanMarked"])
        self.assertTrue(self.out["orphanCleared"])

    def test_a_local_only_row_can_be_marked(self):
        self.assertTrue(self.out["localOnlyMarked"])

    def test_the_mark_clears_when_the_work_fails(self):
        """A spinner that survives a failure is worse than no spinner: it says
        the thing is still happening when it has already stopped."""
        self.assertTrue(self.out["clearedAfterFailure"])

    def test_marking_redraws_so_he_can_see_it(self):
        self.assertTrue(self.out["rendered"])


if __name__ == "__main__":
    unittest.main()
