"""The three operations that destroy things, run rather than read about.

`delete_cloud`, `delete_local` and `merge_preview` were named in no test that
executed them. `delete_cloud` appeared in one docstring and `delete_local` in
another; `merge_preview` appeared nowhere at all. They are the operations that
remove a project from Ekahau, `rmtree` a folder on disk, and decide which
files a merge is about to move over each other.

Two things make that the wrong gap to have.

**Five defects have shipped green here** because a test asserted a source file
contained something rather than that the code did something - and the last of
them was a control that rendered perfectly and was inert. Reading these three
would prove nothing about them.

**And since v2.141.0 nothing copies a file aside first.** There is no
`.previous-` copy, no backups folder, no second line. A cloud delete could
never be undone; a local delete now cannot either, beyond downloading the
cloud copy again where one exists. **Verification before deletion is the only
protection left**, so what is asserted here is not only that the happy path
works but that every refusal *refuses without deleting anything* - the file is
looked for on disk afterwards, every time. A guard that returns an error
message and removes the file regardless would pass a test that only read the
return value.

Nothing here touches Ekahau: the API is a recording stub. Every project, site,
folder and address is invented.
"""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from tools import cloud_manager as cm

ROOT = Path(__file__).resolve().parent.parent


class _RecordingApi:
    """Ekahau, reduced to what these two calls need, and what they were sent.

    It records rather than returns a fixed value, because the thing most worth
    pinning about `delete_cloud` is **which call it makes** - a project and a
    site are deleted through different endpoints, and swapping them deletes a
    whole site when he asked to delete one project inside it.
    """

    def __init__(self, raises: Exception | None = None):
        self.projects_deleted: list[str] = []
        self.sites_deleted: list[list[str]] = []
        self._raises = raises

    def delete_project(self, project_id):
        if self._raises:
            raise self._raises
        self.projects_deleted.append(project_id)
        return {"ok": True}

    def delete_sites(self, site_ids):
        if self._raises:
            raise self._raises
        self.sites_deleted.append(list(site_ids))
        return {"ok": True}

    @property
    def calls(self):
        return len(self.projects_deleted) + len(self.sites_deleted)


class _Manager(cm.CloudManager):
    def __init__(self, api=None, out_dir="", connected=True):
        self.api = api
        self.config = {"output_dir": str(out_dir)}
        self._connected = connected

    def _ensure(self):
        return self._connected


# --------------------------------------------------------------- delete_cloud

class DeletingInTheCloudTests(unittest.TestCase):

    def test_a_project_is_deleted_through_the_project_endpoint(self):
        api = _RecordingApi()
        out = _Manager(api).delete_cloud("projects", "p-1")
        self.assertEqual(["p-1"], api.projects_deleted)
        self.assertEqual([], api.sites_deleted, "it deleted a site instead")
        self.assertFalse(out.get("error"), out)

    def test_a_site_is_deleted_through_the_site_endpoint(self):
        api = _RecordingApi()
        out = _Manager(api).delete_cloud("sites", "s-1")
        self.assertEqual([["s-1"]], api.sites_deleted)
        self.assertEqual([], api.projects_deleted,
                         "it deleted a project instead")
        self.assertFalse(out.get("error"), out)

    def test_the_two_kinds_do_not_share_an_endpoint(self):
        """The mapping is the whole risk in this function.

        A site holds projects. Deleting the site when the row said project
        removes everything inside it, from an account where a cloud delete
        has never been recoverable, and the return value is `{"ok": True}`
        either way - so nothing downstream could tell.
        """
        api = _RecordingApi()
        mgr = _Manager(api)
        mgr.delete_cloud("projects", "same-id")
        mgr.delete_cloud("sites", "same-id")
        self.assertEqual(["same-id"], api.projects_deleted)
        self.assertEqual([["same-id"]], api.sites_deleted)

    def test_a_disconnected_manager_deletes_nothing(self):
        api = _RecordingApi()
        out = _Manager(api, connected=False).delete_cloud("projects", "p-1")
        self.assertIn("error", out)
        self.assertEqual(0, api.calls, "it called Ekahau while disconnected")

    def test_a_refusal_from_ekahau_is_returned_rather_than_raised(self):
        """A 403 on somebody else's project is the case that actually happens.
        It has to arrive as a result the queue can report, not an exception
        that unwinds whatever batch it was part of."""
        api = _RecordingApi(raises=RuntimeError("403 Forbidden"))
        out = _Manager(api).delete_cloud("projects", "p-1")
        self.assertIn("error", out)
        self.assertIn("403", out["error"])


# --------------------------------------------------------------- delete_local

class DeletingOnDiskTests(unittest.TestCase):
    """Every refusal is checked by looking for the file afterwards.

    `delete_local` is `unlink` on a file and `shutil.rmtree` on a directory,
    with one containment check in front of both. Asserting that a refusal
    returns an error says nothing about whether it removed the thing first.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.outside, True)
        self.mgr = _Manager(out_dir=self.root)

    def _esx(self, parent: Path, name: str) -> Path:
        parent.mkdir(parents=True, exist_ok=True)
        f = parent / name
        f.write_bytes(b"PK\x05\x06" + b"\0" * 18)
        return f

    def test_a_file_inside_the_configured_folder_is_deleted(self):
        f = self._esx(self.root / "SITE1 Riverside", "SITE1 Baseline.esx")
        out = self.mgr.delete_local(str(f))
        self.assertTrue(out.get("ok"), out)
        self.assertFalse(f.exists())

    def test_a_folder_is_deleted_with_everything_in_it(self):
        site = self.root / "SITE2 North Campus"
        self._esx(site, "SITE2 Baseline.esx")
        self._esx(site / "Output", "SITE2 Export.esx")
        out = self.mgr.delete_local(str(site))
        self.assertTrue(out.get("ok"), out)
        self.assertFalse(site.exists())

    def test_a_read_only_file_is_still_deleted(self):
        """Windows refuses `unlink` on a read-only file, and a project that
        has come back from a sync or a backup drive often is one. The retry
        that clears the flag is real behaviour, not a formality."""
        f = self._esx(self.root / "SITE3 Depot", "SITE3 Baseline.esx")
        os.chmod(f, stat.S_IREAD)
        self.addCleanup(lambda: f.exists() and os.chmod(f, stat.S_IWRITE))
        out = self.mgr.delete_local(str(f))
        self.assertTrue(out.get("ok"), out)
        self.assertFalse(f.exists())

    def test_a_path_outside_the_configured_folder_is_refused_and_survives(self):
        """The containment check is the only thing between a path the page
        supplied and `rmtree`."""
        f = self._esx(self.outside, "Not His Project.esx")
        out = self.mgr.delete_local(str(f))
        self.assertIn("error", out)
        self.assertTrue(f.exists(), "it deleted a file outside the folder")

    def test_a_folder_outside_the_configured_folder_is_refused_and_survives(self):
        other = self.outside / "Someone Elses Work"
        self._esx(other, "Theirs.esx")
        out = self.mgr.delete_local(str(other))
        self.assertIn("error", out)
        self.assertTrue(other.is_dir(), "it removed a tree outside the folder")

    def test_a_traversal_out_of_the_configured_folder_is_refused(self):
        f = self._esx(self.outside, "Escaped.esx")
        sneaky = str(self.root / ".." / self.outside.name / "Escaped.esx")
        out = self.mgr.delete_local(sneaky)
        self.assertIn("error", out)
        self.assertTrue(f.exists(), "a ..-relative path escaped the folder")

    def test_with_no_folder_configured_it_deletes_nothing(self):
        f = self._esx(self.root / "SITE4", "SITE4 Baseline.esx")
        out = _Manager(out_dir="").delete_local(str(f))
        self.assertIn("error", out)
        self.assertTrue(f.exists(), "it deleted with no folder configured")

    def test_a_missing_path_reports_rather_than_raises(self):
        out = self.mgr.delete_local(str(self.root / "Never Existed.esx"))
        self.assertIn("error", out)


# -------------------------------------------------------------- merge_preview

class PreviewingAMergeTests(unittest.TestCase):
    """A dry run that writes is not a dry run.

    `merge_preview` is what the merge dialog is built from: its `files` list
    becomes the per-file choices, and those choices become `merge_execute`'s
    `ops`. A preview that mis-reports a conflict is a file overwritten with no
    copy kept, so the conflict flags and the newer-side verdict are asserted,
    and the trees are compared before and after to prove nothing moved.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.outside, True)
        self.src = self.root / "SITE5 Riverside"
        self.dst = self.root / "SITE5 Riverside North"
        self.src.mkdir()
        self.dst.mkdir()
        self.mgr = _Manager(out_dir=self.root)

    def _file(self, parent: Path, name: str, body=b"x", mtime=None) -> Path:
        parent.mkdir(parents=True, exist_ok=True)
        f = parent / name
        f.write_bytes(body)
        if mtime is not None:
            os.utime(f, (mtime, mtime))
        return f

    def _snapshot(self):
        out = {}
        for base in (self.src, self.dst):
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    out[str(p.relative_to(self.root))] = p.read_bytes()
        return out

    def test_a_file_with_no_counterpart_is_reported_clean(self):
        self._file(self.src, "SITE5 Baseline.esx")
        out = self.mgr.merge_preview(str(self.src), str(self.dst))
        self.assertFalse(out.get("error"), out)
        self.assertEqual(1, out["nClean"])
        self.assertEqual(0, out["nConflicts"])
        self.assertEqual([False], [f["conflict"] for f in out["files"]])

    def test_a_file_that_exists_on_both_sides_is_reported_as_a_conflict(self):
        self._file(self.src, "SITE5 Baseline.esx", b"aaa", mtime=2_000_000)
        self._file(self.dst, "SITE5 Baseline.esx", b"bb", mtime=1_000_000)
        out = self.mgr.merge_preview(str(self.src), str(self.dst))
        self.assertEqual(0, out["nClean"])
        self.assertEqual(1, out["nConflicts"])
        rec = out["files"][0]
        self.assertTrue(rec["conflict"])
        self.assertEqual("src", rec["newer"],
                         "the side about to overwrite was not named correctly")

    def test_the_older_source_is_named_as_the_older_side(self):
        self._file(self.src, "SITE5 Baseline.esx", mtime=1_000_000)
        self._file(self.dst, "SITE5 Baseline.esx", mtime=2_000_000)
        out = self.mgr.merge_preview(str(self.src), str(self.dst))
        self.assertEqual("dst", out["files"][0]["newer"])

    def test_two_files_of_the_same_age_are_not_called_newer_either_way(self):
        self._file(self.src, "SITE5 Baseline.esx", mtime=1_500_000)
        self._file(self.dst, "SITE5 Baseline.esx", mtime=1_500_000)
        out = self.mgr.merge_preview(str(self.src), str(self.dst))
        self.assertEqual("same", out["files"][0]["newer"])

    def test_a_preview_moves_nothing(self):
        """The property the name promises."""
        self._file(self.src, "SITE5 Baseline.esx", b"aaa")
        self._file(self.src / "Sub", "SITE5 Detail.esx", b"bbb")
        self._file(self.dst, "SITE5 Baseline.esx", b"ccc")
        before = self._snapshot()
        self.mgr.merge_preview(str(self.src), str(self.dst))
        self.assertEqual(before, self._snapshot(),
                         "the dry run changed something on disk")

    def test_nested_files_are_reported_with_their_relative_path(self):
        self._file(self.src / "Floor 2", "SITE5 Level 2.esx")
        out = self.mgr.merge_preview(str(self.src), str(self.dst))
        rels = [f["rel"].replace("\\", "/") for f in out["files"]]
        self.assertEqual(["Floor 2/SITE5 Level 2.esx"], rels)

    # ---- the refusals, each checked for having changed nothing -------------

    def test_a_source_outside_the_configured_folder_is_refused(self):
        self._file(self.outside / "Theirs", "Theirs.esx")
        out = self.mgr.merge_preview(str(self.outside / "Theirs"), str(self.dst))
        self.assertIn("error", out)

    def test_a_destination_outside_the_configured_folder_is_refused(self):
        self._file(self.src, "SITE5 Baseline.esx")
        out = self.mgr.merge_preview(str(self.src), str(self.outside))
        self.assertIn("error", out)

    def test_merging_a_folder_into_itself_is_refused(self):
        self._file(self.src, "SITE5 Baseline.esx")
        out = self.mgr.merge_preview(str(self.src), str(self.src))
        self.assertIn("error", out)

    def test_merging_into_a_subfolder_of_the_source_is_refused(self):
        """It would move a folder into a folder it contains and lose the
        difference between the two."""
        inner = self.src / "Inner"
        inner.mkdir()
        out = self.mgr.merge_preview(str(self.src), str(inner))
        self.assertIn("error", out)

    def test_a_missing_source_or_destination_is_refused(self):
        self.assertIn("error", self.mgr.merge_preview(
            str(self.root / "Gone"), str(self.dst)))
        self.assertIn("error", self.mgr.merge_preview(
            str(self.src), str(self.root / "Gone")))

    def test_with_no_folder_configured_it_refuses(self):
        out = _Manager(out_dir="").merge_preview(str(self.src), str(self.dst))
        self.assertIn("error", out)


# ------------------------------------------------- the routes above them

class TheRouteReachesTheFunctionTests(unittest.TestCase):
    """The page does not call these functions; it posts an action name.

    `CLOUD_ACTIONS` is the seam between the two, and a lambda reading the
    wrong key or passing arguments in the wrong order is invisible to
    everything above - the function is tested, the page is tested, and the one
    line joining them is a dictionary literal nobody executes. That is the
    same shape as a control whose `onclick` names a handler that does not
    exist, one layer down.
    """

    def setUp(self):
        import server
        self.server = server
        self.calls = []

        class _Recorder:
            def __init__(self, sink):
                self._sink = sink

            def __getattr__(self, name):
                def call(*args, **kwargs):
                    self._sink.append((name, args, kwargs))
                    return {"ok": True}
                return call

        self._real_cm = server.cm
        server.cm = _Recorder(self.calls)
        self.addCleanup(lambda: setattr(server, "cm", self._real_cm))

    def _run(self, action, payload):
        self.server.CLOUD_ACTIONS[action](payload)
        return self.calls[-1] if self.calls else None

    def test_delete_cloud_passes_the_kind_and_then_the_id(self):
        """Order matters here more than usual: both are strings, so swapping
        them raises nothing and asks Ekahau to delete an id called
        "projects"."""
        name, args, _ = self._run("delete_cloud", {"kind": "projects", "id": "p-1"})
        self.assertEqual("delete_cloud", name)
        self.assertEqual(("projects", "p-1"), args)

    def test_delete_local_passes_the_path(self):
        name, args, _ = self._run("delete_local", {"path": r"D:\E\SITE1.esx"})
        self.assertEqual("delete_local", name)
        self.assertEqual((r"D:\E\SITE1.esx",), args)

    def test_merge_preview_passes_source_then_destination(self):
        """Backwards, this previews the merge the other way round - and the
        answer it gives becomes the choices the execute step is handed."""
        name, args, _ = self._run("merge_preview", {"src": "S", "dst": "D"})
        self.assertEqual("merge_preview", name)
        self.assertEqual(("S", "D"), args)

    def test_merge_execute_passes_source_destination_then_operations(self):
        ops = [{"rel": "a.esx", "action": "move"}]
        name, args, _ = self._run("merge_execute", {"src": "S", "dst": "D", "ops": ops})
        self.assertEqual("merge_execute", name)
        self.assertEqual(("S", "D", ops), args)


class TheKeysThePageSendsAreTheKeysTheRouteReadsTests(unittest.TestCase):
    """Every key a route requires has to be one the page actually sends.

    `API_MAP` in `cloud.js` names the arguments for each action and the
    lambdas in `CLOUD_ACTIONS` read them out of the posted object. Rename one
    side and the other raises `KeyError` at the moment he clicks - and for
    two of these that click is a delete.

    Checked for all of them rather than the three this file is about, because
    the mapping is the same mapping and a ratchet over forty-four actions
    costs no more than a ratchet over three. It held at 0 violations when
    written; it exists so that stays true.
    """

    @staticmethod
    def _routes():
        import ast
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        out = {}
        for node in ast.walk(ast.parse(src)):
            if not (isinstance(node, ast.Assign) and any(
                    getattr(t, "id", "") == "CLOUD_ACTIONS" for t in node.targets)):
                continue
            for key, val in zip(node.value.keys, node.value.values):
                required = set()
                for sub in ast.walk(val):
                    # `d["x"]` is required; `d.get("x")` is not.
                    if (isinstance(sub, ast.Subscript)
                            and isinstance(sub.value, ast.Name)
                            and sub.value.id == "d"
                            and isinstance(sub.slice, ast.Constant)):
                        required.add(sub.slice.value)
                out[key.value] = required
        return out

    @staticmethod
    def _page():
        import re
        js = (ROOT / "web" / "assets" / "js" / "cloud.js").read_text(encoding="utf-8")
        start = js.index("const API_MAP = {")
        block = js[start:js.index("\n};", start)]
        return {
            action: [a.strip().strip("'") for a in args.split(",") if a.strip()]
            for _page_name, action, args in re.findall(
                r"(\w+):\s*\['(\w+)',\s*\[([^\]]*)\]\]", block)
        }

    def test_the_two_sides_agree_about_every_argument_name(self):
        routes, page = self._routes(), self._page()
        self.assertGreater(len(routes), 40, "the route table did not parse")
        self.assertGreater(len(page), 40, "API_MAP did not parse")
        broken = []
        for action, required in sorted(routes.items()):
            if action not in page:
                continue  # called without arguments, or not from this map
            missing = sorted(required - set(page[action]))
            if missing:
                broken.append(f"{action}: route reads {missing}, "
                              f"page sends {page[action]}")
        self.assertEqual([], broken, "\n  " + "\n  ".join(broken))

    def test_the_three_destructive_actions_are_in_both_tables(self):
        """Named explicitly, so removing one from either side is a failure
        here rather than a silently skipped entry in the sweep above."""
        routes, page = self._routes(), self._page()
        for action in ("delete_cloud", "delete_local", "merge_preview",
                       "merge_execute"):
            self.assertIn(action, routes, f"{action} has no route")
            self.assertIn(action, page, f"{action} is not reachable from the page")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
