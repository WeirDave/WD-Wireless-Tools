"""Merging several folders with "Keep newer" keeps the newest copy.

Two source folders and the destination each held `plan.esx`; the first source
held the newest. The preview judged both sources against the destination as
it was before the run, so both read "incoming is newer", the page sent
`overwrite` for both, and the second - older - copy overwrote the first. The
newest work was gone, and which copy survived was decided by the order the
folders were listed in.

Now the page sends `newer`, and the server decides on what the destination
holds when that file's turn comes. Driven end to end: the real preview, the
real `confirmMerge` from cloud.js (`tests/cloud_vm.py`), and the real execute
on real files.

Names that differ only in case are one file on Windows and macOS, so two
sources carrying `report.pdf` and `Report.pdf` collide too.

Every folder and file name here is invented.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from tests import cloud_vm
from tools import cloud_manager as cm


class _Mgr(cm.CloudManager):
    def __init__(self, root):
        self.api = None
        self.config = {"output_dir": str(root)}

    def _ensure(self):
        return True


def _write(p, text, mtime):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    os.utime(p, (mtime, mtime))


#: The real `confirmMerge`, every file ticked, "Keep newer" chosen; it reports
#: what it would send to `merge_execute_many`.
CONFIRM = r"""
const PREVIEW = JSON.parse(%s);
s.__set('mergeState', { preview: PREVIEW, dstPath: PREVIEW.dstPath, dstName: PREVIEW.dstName });
const boxes = [];
PREVIEW.sources.forEach((src, si) => src.files.forEach((f, i) =>
  boxes.push({ checked: true, dataset: { s: String(si), i: String(i) } })));
s.document.querySelectorAll = (sel) => (sel.indexOf('mfile-chk') >= 0 ? boxes : []);
s.document.querySelector = (sel) => (sel.indexOf('mrule') >= 0 ? { value: 'newer' } : null);
let sent = null;
s.pyApi = async (m, ...args) => {
  if (m === 'merge_execute_many') { sent = args[0]; return { ok: true, results: [] }; }
  return { ok: true };
};
await s.confirmMerge();
out(sent);
"""


class _Case(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wd-merge-newest-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.mgr = _Mgr(self.root)
        self.dst = self.root / "Harbour Hall"
        self.dst.mkdir()
        self.now = time.time()

    def _src(self, name, files):
        d = self.root / name
        for rel, (text, age) in files.items():
            _write(d / rel, text, self.now - age)
        return d


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class KeepNewerAcrossSeveralSourcesTests(_Case):

    def _merge_as_the_page_does(self, sources):
        prev = self.mgr.merge_preview_many([str(s) for s in sources], str(self.dst))
        self.assertNotIn("error", prev)
        merges = cloud_vm.run(CONFIRM % json.dumps(json.dumps(prev)))
        self.assertTrue(merges, "the page sent nothing")
        res = self.mgr.merge_execute_many(merges, str(self.dst))
        self.assertTrue(res.get("ok"), res)
        return res

    def test_the_newest_copy_survives_whichever_folder_is_listed_first(self):
        _write(self.dst / "plan.esx", "DEST-OLDEST", self.now - 3000)
        alpha = self._src("Alpha Wing", {"plan.esx": ("ALPHA-NEWEST", 100)})
        bravo = self._src("Bravo Wing", {"plan.esx": ("BRAVO-MIDDLE", 1000)})
        self._merge_as_the_page_does([alpha, bravo])
        self.assertEqual("ALPHA-NEWEST",
                         (self.dst / "plan.esx").read_text(encoding="utf-8"))
        # The older incoming copy was left where it was, not destroyed.
        self.assertEqual("BRAVO-MIDDLE",
                         (bravo / "plan.esx").read_text(encoding="utf-8"))

    def test_the_other_order_gives_the_same_answer(self):
        _write(self.dst / "plan.esx", "DEST-OLDEST", self.now - 3000)
        alpha = self._src("Alpha Wing", {"plan.esx": ("ALPHA-NEWEST", 100)})
        bravo = self._src("Bravo Wing", {"plan.esx": ("BRAVO-MIDDLE", 1000)})
        self._merge_as_the_page_does([bravo, alpha])
        self.assertEqual("ALPHA-NEWEST",
                         (self.dst / "plan.esx").read_text(encoding="utf-8"))

    def test_a_destination_newer_than_every_source_is_kept(self):
        _write(self.dst / "plan.esx", "DEST-NEWEST", self.now - 10)
        alpha = self._src("Alpha Wing", {"plan.esx": ("ALPHA", 100)})
        bravo = self._src("Bravo Wing", {"plan.esx": ("BRAVO", 1000)})
        self._merge_as_the_page_does([alpha, bravo])
        self.assertEqual("DEST-NEWEST",
                         (self.dst / "plan.esx").read_text(encoding="utf-8"))


class ThePreviewSaysWhatTheFileWillMeetTests(_Case):

    def test_the_second_source_is_judged_against_the_first(self):
        """It meets the first source's copy, not the destination's."""
        _write(self.dst / "plan.esx", "DEST-OLDEST", self.now - 3000)
        alpha = self._src("Alpha Wing", {"plan.esx": ("ALPHA-NEWEST", 100)})
        bravo = self._src("Bravo Wing", {"plan.esx": ("BRAVO-MIDDLE", 1000)})
        prev = self.mgr.merge_preview_many([str(alpha), str(bravo)], str(self.dst))
        second = prev["sources"][1]["files"][0]
        self.assertEqual("dst", second["newer"])
        self.assertEqual("Alpha Wing", second["alsoIn"])


class TheServerDecidesKeepNewerTests(_Case):

    def test_newer_overwrites_only_an_older_destination_copy(self):
        _write(self.dst / "a.esx", "OLD", self.now - 900)
        _write(self.dst / "b.esx", "NEW", self.now - 10)
        src = self._src("Charlie Wing", {"a.esx": ("IN-A", 100), "b.esx": ("IN-B", 100)})
        res = self.mgr.merge_execute(str(src), str(self.dst),
                                     [{"rel": "a.esx", "action": "newer"},
                                      {"rel": "b.esx", "action": "newer"}])
        self.assertEqual((1, 1), (res["overwritten"], res["skipped"]), res)
        self.assertEqual("IN-A", (self.dst / "a.esx").read_text(encoding="utf-8"))
        self.assertEqual("NEW", (self.dst / "b.esx").read_text(encoding="utf-8"))

    def test_newer_moves_a_file_the_destination_does_not_have(self):
        src = self._src("Charlie Wing", {"c.esx": ("IN-C", 100)})
        res = self.mgr.merge_execute(str(src), str(self.dst),
                                     [{"rel": "c.esx", "action": "newer"}])
        self.assertEqual(1, res["moved"], res)


class NamesThatDifferOnlyInCaseCollideTests(_Case):

    def test_report_and_Report_from_two_sources_are_flagged(self):
        alpha = self._src("Alpha Wing", {"report.pdf": ("a", 100)})
        bravo = self._src("Bravo Wing", {"Report.pdf": ("b", 100)})
        prev = self.mgr.merge_preview_many([str(alpha), str(bravo)], str(self.dst))
        second = prev["sources"][1]["files"][0]
        self.assertTrue(second["conflict"], prev)
        self.assertEqual("Alpha Wing", second["fromSource"])
        self.assertEqual(1, prev["nCrossSource"])


if __name__ == "__main__":
    unittest.main()
