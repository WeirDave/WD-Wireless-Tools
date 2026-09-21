"""Merging several folders into one, with real files on a real disk.

The single-folder merge has existed for a long time; doing it eight times in a
row by hand is what this replaces. The part that is not a loop is the reason
the feature needed writing rather than the page calling the old call in a
``for``:

**Two sources can each carry a file of the same name.** Previewed one at a time
they both read "no conflict", because neither is in the destination *yet*. Run
one after the other, the first moves cleanly and the second lands on top of it -
or gets date-stamped - and nothing warned him, because at the moment he was
looking at the preview it was true. ``merge_preview_many`` walks the sources in
the order they will run and carries what each will place forward into the next,
so that collision is on screen before anything moves.

Everything here moves files for real and then looks at the disk. A merge that
reported four moves and moved nothing would pass any assertion about its return
value; the assertions are about what is in the destination afterwards.

Every folder, project and site name here is invented.
"""
from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from tools import cloud_manager as cm


class _Manager(cm.CloudManager):
    def __init__(self, out_dir):
        self.api = None
        self.config = {"output_dir": str(out_dir)}

    def _ensure(self):
        return True


def _write(path: Path, text: str, mtime=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(path, (mtime, mtime))
    return path


class _Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wd-mergemany-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.mgr = _Manager(self.root)
        self.dst = self.root / "SITE9 Consolidated"
        self.dst.mkdir()

    def _src(self, name, files):
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            _write(d / rel, text)
        return d

    def _ops(self, preview, action="move"):
        """Every file in a preview, with one action, in source order."""
        return [{"srcPath": s["srcPath"],
                 "ops": [{"rel": f["rel"], "action": action} for f in s["files"]]}
                for s in preview["sources"]]


class ThePreviewCoversEverySourceTests(_Base):

    def test_each_source_is_reported_with_its_own_counts(self):
        a = self._src("SITE9 East", {"a.esx": "A", "notes/one.txt": "1"})
        b = self._src("SITE9 West", {"b.esx": "B"})
        p = self.mgr.merge_preview_many([str(a), str(b)], str(self.dst))
        self.assertNotIn("error", p)
        self.assertEqual(2, p["nSources"])
        self.assertEqual(["SITE9 East", "SITE9 West"],
                         [s["srcName"] for s in p["sources"]])
        self.assertEqual([2, 1], [len(s["files"]) for s in p["sources"]])
        self.assertEqual(3, p["nClean"])
        self.assertEqual(0, p["nConflicts"])

    def test_a_file_already_in_the_destination_is_a_conflict(self):
        _write(self.dst / "a.esx", "already here")
        a = self._src("SITE9 East", {"a.esx": "A"})
        p = self.mgr.merge_preview_many([str(a)], str(self.dst))
        self.assertEqual(1, p["nConflicts"])
        self.assertTrue(p["sources"][0]["files"][0]["conflict"])
        # Not a cross-source one: it was there before the run started.
        self.assertEqual(0, p["nCrossSource"])

    def test_two_sources_carrying_the_same_name_collide_in_the_preview(self):
        """The case a loop over merge_preview cannot see."""
        a = self._src("SITE9 East", {"Report.pdf": "east"})
        b = self._src("SITE9 West", {"Report.pdf": "west"})
        p = self.mgr.merge_preview_many([str(a), str(b)], str(self.dst))

        first = p["sources"][0]["files"][0]
        second = p["sources"][1]["files"][0]
        self.assertFalse(first["conflict"], "the first one really is clean")
        self.assertTrue(second["conflict"],
                        "the second would land on the first and nothing said so")
        self.assertEqual(1, p["nCrossSource"])
        self.assertEqual(1, p["nConflicts"])

    def test_the_collision_names_the_folder_it_will_collide_with(self):
        """"Conflict" with no other party is not something he can act on."""
        a = self._src("SITE9 East", {"Report.pdf": "east"})
        b = self._src("SITE9 West", {"Report.pdf": "west"})
        p = self.mgr.merge_preview_many([str(a), str(b)], str(self.dst))
        self.assertEqual("SITE9 East", p["sources"][1]["files"][0]["fromSource"])

    def test_a_cross_source_collision_does_not_claim_to_know_which_is_newer(self):
        """There is no file to compare against yet - the other one has not
        moved. Claiming "incoming is newer" would be inventing a comparison."""
        a = self._src("SITE9 East", {"Report.pdf": "east"})
        b = self._src("SITE9 West", {"Report.pdf": "west"})
        p = self.mgr.merge_preview_many([str(a), str(b)], str(self.dst))
        self.assertEqual("unknown", p["sources"][1]["files"][0]["newer"])

    def test_three_sources_carrying_the_same_name_all_point_at_the_first(self):
        a = self._src("SITE9 East", {"Report.pdf": "east"})
        b = self._src("SITE9 West", {"Report.pdf": "west"})
        c = self._src("SITE9 North", {"Report.pdf": "north"})
        p = self.mgr.merge_preview_many([str(a), str(b), str(c)], str(self.dst))
        self.assertEqual(2, p["nCrossSource"])
        for s in p["sources"][1:]:
            self.assertEqual("SITE9 East", s["files"][0]["fromSource"])

    def test_the_order_of_the_sources_decides_which_one_is_clean(self):
        """It is the run order, so it has to be the preview order too."""
        a = self._src("SITE9 East", {"Report.pdf": "east"})
        b = self._src("SITE9 West", {"Report.pdf": "west"})
        p = self.mgr.merge_preview_many([str(b), str(a)], str(self.dst))
        self.assertEqual("SITE9 West", p["sources"][0]["srcName"])
        self.assertFalse(p["sources"][0]["files"][0]["conflict"])
        self.assertEqual("SITE9 West", p["sources"][1]["files"][0]["fromSource"])

    def test_the_same_name_in_different_subfolders_is_not_a_collision(self):
        a = self._src("SITE9 East", {"plans/a.pdf": "east"})
        b = self._src("SITE9 West", {"surveys/a.pdf": "west"})
        p = self.mgr.merge_preview_many([str(a), str(b)], str(self.dst))
        self.assertEqual(0, p["nCrossSource"])


class ARefusedSourceDoesNotSinkTheRunTests(_Base):
    """Refusing eight folders because one is wrong is the guard firing on his
    normal case - see CLAUDE.md, "Unrecoverable earns friction, not refusal"."""

    def test_a_missing_folder_is_named_and_the_rest_go_ahead(self):
        a = self._src("SITE9 East", {"a.esx": "A"})
        gone = self.root / "SITE9 Nowhere"
        p = self.mgr.merge_preview_many([str(a), str(gone)], str(self.dst))
        self.assertEqual(1, p["nSources"])
        self.assertEqual(["SITE9 Nowhere"], [r["name"] for r in p["refused"]])
        self.assertTrue(p["refused"][0]["reason"].strip())

    def test_the_destination_selected_as_its_own_source_is_refused_by_name(self):
        a = self._src("SITE9 East", {"a.esx": "A"})
        p = self.mgr.merge_preview_many([str(a), str(self.dst)], str(self.dst))
        self.assertEqual(1, p["nSources"])
        self.assertEqual([self.dst.name], [r["name"] for r in p["refused"]])

    def test_a_parent_of_the_destination_is_refused(self):
        """Merging a folder into its own child would walk the child too."""
        parent = self.root / "SITE9 Parent"
        inner = parent / "Inner"
        inner.mkdir(parents=True)
        _write(parent / "a.esx", "A")
        p = self.mgr.merge_preview_many([str(parent)], str(inner))
        self.assertIn("error", p)

    def test_nothing_usable_at_all_is_an_error_carrying_the_reasons(self):
        p = self.mgr.merge_preview_many([str(self.root / "gone")], str(self.dst))
        self.assertIn("error", p)
        self.assertTrue(p["error"].strip())

    def test_an_empty_selection_is_refused(self):
        for value in ([], None, [""]):
            with self.subTest(value=value):
                self.assertIn("error",
                              self.mgr.merge_preview_many(value, str(self.dst)))

    def test_a_missing_destination_is_refused_before_anything_is_walked(self):
        a = self._src("SITE9 East", {"a.esx": "A"})
        p = self.mgr.merge_preview_many([str(a)], str(self.root / "nowhere"))
        self.assertIn("error", p)

    def test_no_local_folder_set_is_refused(self):
        mgr = _Manager("")
        mgr.config["output_dir"] = ""
        self.assertIn("error", mgr.merge_preview_many(["x"], "y"))
        self.assertIn("error", mgr.merge_execute_many([{"srcPath": "x"}], "y"))


class TheFilesReallyMoveTests(_Base):
    """The assertions are about the disk afterwards, not the return value."""

    def test_every_source_lands_in_the_destination(self):
        a = self._src("SITE9 East", {"a.esx": "A", "notes/one.txt": "1"})
        b = self._src("SITE9 West", {"b.esx": "B"})
        p = self.mgr.merge_preview_many([str(a), str(b)], str(self.dst))
        r = self.mgr.merge_execute_many(self._ops(p), str(self.dst))

        self.assertTrue(r["ok"], r)
        self.assertEqual(3, r["moved"])
        self.assertEqual("A", (self.dst / "a.esx").read_text(encoding="utf-8"))
        self.assertEqual("1", (self.dst / "notes" / "one.txt").read_text(encoding="utf-8"))
        self.assertEqual("B", (self.dst / "b.esx").read_text(encoding="utf-8"))
        # And they are gone from where they were.
        self.assertFalse((a / "a.esx").exists())
        self.assertFalse((b / "b.esx").exists())

    def test_a_source_folder_is_never_removed_by_the_merge_itself(self):
        """Deleting it is a separate, visible decision on the page."""
        a = self._src("SITE9 East", {"a.esx": "A"})
        p = self.mgr.merge_preview_many([str(a)], str(self.dst))
        self.mgr.merge_execute_many(self._ops(p), str(self.dst))
        self.assertTrue(a.is_dir(), "the merge removed the source folder")

    def test_skip_leaves_the_file_where_it_was(self):
        a = self._src("SITE9 East", {"a.esx": "A"})
        p = self.mgr.merge_preview_many([str(a)], str(self.dst))
        r = self.mgr.merge_execute_many(self._ops(p, "skip"), str(self.dst))
        self.assertEqual(1, r["skipped"])
        self.assertTrue((a / "a.esx").exists())
        self.assertFalse((self.dst / "a.esx").exists())

    def test_overwrite_replaces_the_destination_copy(self):
        _write(self.dst / "a.esx", "OLD")
        a = self._src("SITE9 East", {"a.esx": "NEW"})
        p = self.mgr.merge_preview_many([str(a)], str(self.dst))
        r = self.mgr.merge_execute_many(self._ops(p, "overwrite"), str(self.dst))
        self.assertEqual(1, r["overwritten"])
        self.assertEqual("NEW", (self.dst / "a.esx").read_text(encoding="utf-8"))

    def test_keep_both_leaves_two_files_and_loses_neither(self):
        """The one action whose whole promise is that nothing is lost."""
        _write(self.dst / "a.esx", "OLD", mtime=time.time() - 5000)
        a = self._src("SITE9 East", {})
        _write(a / "a.esx", "NEW", mtime=time.time())
        p = self.mgr.merge_preview_many([str(a)], str(self.dst))
        r = self.mgr.merge_execute_many(self._ops(p, "keepboth"), str(self.dst))
        self.assertEqual(1, r["keptboth"])
        bodies = sorted(f.read_text(encoding="utf-8")
                        for f in self.dst.iterdir() if f.is_file())
        self.assertEqual(["NEW", "OLD"], bodies)

    def test_a_cross_source_collision_handled_as_keep_both_loses_neither(self):
        """The case the preview exists to surface, carried through to the disk."""
        a = self._src("SITE9 East", {})
        b = self._src("SITE9 West", {})
        _write(a / "Report.pdf", "east", mtime=time.time() - 5000)
        _write(b / "Report.pdf", "west", mtime=time.time())
        p = self.mgr.merge_preview_many([str(a), str(b)], str(self.dst))
        self.assertEqual(1, p["nCrossSource"])
        self.mgr.merge_execute_many(self._ops(p, "keepboth"), str(self.dst))
        bodies = sorted(f.read_text(encoding="utf-8")
                        for f in self.dst.iterdir() if f.is_file())
        self.assertEqual(["east", "west"], bodies)

    def test_without_the_bulk_preview_the_second_copy_would_be_lost(self):
        """The defect this feature exists to prevent, demonstrated.

        Previewing each source on its own reports no conflict for either, so
        every file would be actioned as a plain move - and the second one
        overwrites the first without anything having said so.
        """
        a = self._src("SITE9 East", {})
        b = self._src("SITE9 West", {})
        _write(a / "Report.pdf", "east")
        _write(b / "Report.pdf", "west")
        one = self.mgr.merge_preview(str(a), str(self.dst))
        two = self.mgr.merge_preview(str(b), str(self.dst))
        self.assertFalse(one["files"][0]["conflict"])
        self.assertFalse(two["files"][0]["conflict"],
                         "the single preview already sees it - this test is moot")
        # The bulk preview is the one that catches it.
        bulk = self.mgr.merge_preview_many([str(a), str(b)], str(self.dst))
        self.assertTrue(bulk["sources"][1]["files"][0]["conflict"])

    def test_one_source_failing_does_not_stop_the_others(self):
        """The ones that ran have moved real files; unwinding is not on offer."""
        a = self._src("SITE9 East", {"a.esx": "A"})
        b = self._src("SITE9 West", {"b.esx": "B"})
        merges = [{"srcPath": str(self.root / "gone"),
                   "ops": [{"rel": "x", "action": "move"}]},
                  {"srcPath": str(a), "ops": [{"rel": "a.esx", "action": "move"}]},
                  {"srcPath": str(b), "ops": [{"rel": "b.esx", "action": "move"}]}]
        r = self.mgr.merge_execute_many(merges, str(self.dst))
        self.assertTrue(r["ok"])
        self.assertEqual(1, r["nFailed"])
        self.assertEqual(2, r["moved"])
        self.assertTrue((self.dst / "a.esx").exists())
        self.assertTrue((self.dst / "b.esx").exists())

    def test_a_failure_is_named_so_it_can_be_reported(self):
        r = self.mgr.merge_execute_many(
            [{"srcPath": str(self.root / "SITE9 Nowhere"), "ops": []}], str(self.dst))
        row = r["results"][0]
        self.assertEqual("SITE9 Nowhere", row["srcName"])
        self.assertIn("error", row)

    def test_a_file_outside_the_source_cannot_be_dragged_in(self):
        """`..` in a relative path is how a merge reaches somewhere it was
        never pointed at. The single-folder path guards it; the bulk path has
        to inherit that rather than route around it."""
        outside = _write(self.root / "secret.txt", "not yours")
        a = self._src("SITE9 East", {"a.esx": "A"})
        r = self.mgr.merge_execute_many(
            [{"srcPath": str(a),
              "ops": [{"rel": "../secret.txt", "action": "move"}]}], str(self.dst))
        self.assertTrue(outside.exists(), "a file outside the source was moved")
        self.assertFalse((self.dst / "secret.txt").exists())
        self.assertEqual(0, r["moved"])


class TheBulkActionsAreReachableTests(unittest.TestCase):
    """A method that is not routed cannot be called from the page."""

    def test_both_are_in_the_route_table(self):
        import server
        self.assertIn("merge_preview_many", server.CLOUD_ACTIONS)
        self.assertIn("merge_execute_many", server.CLOUD_ACTIONS)

    def test_the_routes_pass_what_the_page_sends(self):
        import server
        seen = {}

        class FakeCm:
            def merge_preview_many(self, srcs, dst):
                seen["preview"] = (srcs, dst)
                return {"ok": True}

            def merge_execute_many(self, merges, dst):
                seen["execute"] = (merges, dst)
                return {"ok": True}

        real = server.cm
        server.cm = FakeCm()
        try:
            server.CLOUD_ACTIONS["merge_preview_many"]({"srcs": ["a", "b"], "dst": "d"})
            server.CLOUD_ACTIONS["merge_execute_many"](
                {"merges": [{"srcPath": "a", "ops": []}], "dst": "d"})
        finally:
            server.cm = real
        self.assertEqual((["a", "b"], "d"), seen["preview"])
        self.assertEqual(([{"srcPath": "a", "ops": []}], "d"), seen["execute"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
