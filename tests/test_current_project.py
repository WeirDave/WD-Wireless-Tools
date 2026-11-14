"""The current project is one fact the whole suite shares.

Quick Walls, Prep and Report each used to keep a private "opened from disk"
path and the drop-box tools kept none. These tests hold the store itself, and
then the routes and the three tools that read it, run for real rather than
read: a control that says "open the current project" is only as good as the
call that arrives behind it.

Every path here is invented and lives in a temp folder. The real
`current_project.json` holds real project paths and is never opened.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

_SANDBOX = tempfile.TemporaryDirectory(prefix="wd-cp-user-")
os.environ["WD_USER_DIR"] = _SANDBOX.name

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from tools import current_project as cp  # noqa: E402

HDR = {"X-WD-Wireless-Tools": "1"}


def _make(folder: Path, name: str, body: bytes = b"PK-not-really") -> Path:
    p = folder / name
    p.write_bytes(body)
    return p


class _Store(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-cp-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patcher = mock.patch.object(cp, "store_path",
                                    lambda: self.tmp / "store" / cp.STORE_NAME)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.proj = self.tmp / "projects"
        self.proj.mkdir()


class TheStoreTests(_Store):

    def test_nothing_is_current_to_begin_with(self):
        self.assertIsNone(cp.current())
        self.assertEqual([], cp.recent())

    def test_choosing_a_project_makes_it_current_and_recent(self):
        a = _make(self.proj, "Alpha.esx")
        r = cp.set_current(a)
        self.assertTrue(r["ok"])
        self.assertEqual("Alpha.esx", cp.current()["name"])
        self.assertTrue(cp.current()["exists"])
        self.assertEqual(["Alpha.esx"], [x["name"] for x in cp.recent()])

    def test_only_an_esx_that_exists_can_be_chosen(self):
        for bad in (self.proj / "missing.esx",
                    _make(self.proj, "notes.txt"),
                    self.proj, "", None):
            self.assertFalse(cp.set_current(bad)["ok"], bad)
        self.assertIsNone(cp.current())
        self.assertFalse((self.tmp / "store" / cp.STORE_NAME).exists(),
                         "a refused choice still wrote the store")

    def test_the_newest_is_first_and_a_repeat_moves_not_duplicates(self):
        a, b = _make(self.proj, "Alpha.esx"), _make(self.proj, "Bravo.esx")
        cp.set_current(a)
        cp.set_current(b)
        cp.set_current(a)
        self.assertEqual(["Alpha.esx", "Bravo.esx"],
                         [x["name"] for x in cp.recent()])

    @unittest.skipUnless(os.name == "nt", "only Windows reads paths without case")
    def test_the_same_file_spelled_in_another_case_is_one_entry(self):
        a = _make(self.proj, "Alpha.esx")
        cp.set_current(a)
        cp.set_current(str(a).upper())
        self.assertEqual(1, len(cp.recent()))

    def test_the_list_is_capped(self):
        for i in range(cp.MAX_RECENT + 5):
            cp.set_current(_make(self.proj, f"P{i:02}.esx"))
        names = [x["name"] for x in cp.recent()]
        self.assertEqual(cp.MAX_RECENT, len(names))
        self.assertEqual(f"P{cp.MAX_RECENT + 4:02}.esx", names[0])

    def test_only_chosen_paths_are_known(self):
        a = _make(self.proj, "Alpha.esx")
        other = _make(self.proj, "Elsewhere.esx")
        cp.set_current(a)
        self.assertTrue(cp.is_known(str(a)))
        self.assertFalse(cp.is_known(str(other)),
                         "a file nobody chose was treated as readable")
        self.assertFalse(cp.is_known(""))
        self.assertFalse(cp.is_known(None))

    def test_using_a_project_off_the_list_is_refused(self):
        other = _make(self.proj, "Elsewhere.esx")
        r = cp.use(str(other))
        self.assertFalse(r["ok"])
        self.assertIsNone(cp.current())

    def test_using_a_listed_project_makes_it_current_again(self):
        a, b = _make(self.proj, "Alpha.esx"), _make(self.proj, "Bravo.esx")
        cp.set_current(a)
        cp.set_current(b)
        self.assertTrue(cp.use(str(a))["ok"])
        self.assertEqual("Alpha.esx", cp.current()["name"])

    def test_a_listed_project_that_moved_says_so_and_is_not_current(self):
        a = _make(self.proj, "Alpha.esx")
        b = _make(self.proj, "Bravo.esx")
        cp.set_current(a)
        cp.set_current(b)
        a.unlink()
        listed = {x["name"]: x for x in cp.recent()}
        self.assertFalse(listed["Alpha.esx"]["exists"])
        r = cp.use(str(a))
        self.assertFalse(r["ok"])
        self.assertIn("moved or deleted", r["error"])
        self.assertEqual("Bravo.esx", cp.current()["name"])

    def test_a_current_project_that_was_deleted_is_not_readable(self):
        a = _make(self.proj, "Alpha.esx")
        cp.set_current(a)
        a.unlink()
        self.assertIsNone(cp.current_path())
        self.assertFalse(cp.current()["exists"])

    def test_forgetting_the_current_one_keeps_it_on_the_list(self):
        a = _make(self.proj, "Alpha.esx")
        cp.set_current(a)
        cp.forget()
        self.assertIsNone(cp.current())
        self.assertEqual(1, len(cp.recent()))

    def test_forgetting_a_path_removes_it_everywhere(self):
        a, b = _make(self.proj, "Alpha.esx"), _make(self.proj, "Bravo.esx")
        cp.set_current(a)
        cp.set_current(b)
        cp.forget(str(b))
        self.assertIsNone(cp.current())
        self.assertEqual(["Alpha.esx"], [x["name"] for x in cp.recent()])
        self.assertFalse(cp.is_known(str(b)))

    def test_clearing_forgets_everything(self):
        cp.set_current(_make(self.proj, "Alpha.esx"))
        cp.clear()
        self.assertIsNone(cp.current())
        self.assertEqual([], cp.recent())

    def test_a_damaged_store_reads_as_empty_and_is_not_fatal(self):
        (self.tmp / "store").mkdir()
        (self.tmp / "store" / cp.STORE_NAME).write_text("{ not json",
                                                        encoding="utf-8")
        self.assertIsNone(cp.current())
        a = _make(self.proj, "Alpha.esx")
        self.assertTrue(cp.set_current(a)["ok"])

    def test_concurrent_choices_do_not_lose_one_another(self):
        files = [_make(self.proj, f"C{i}.esx") for i in range(10)]
        threads = [threading.Thread(target=cp.set_current, args=(f,))
                   for f in files]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(10, len(cp.recent()))

    def test_it_stores_nothing_but_paths_and_times(self):
        cp.set_current(_make(self.proj, "Alpha.esx"))
        doc = json.loads((self.tmp / "store" / cp.STORE_NAME).read_text("utf-8"))
        self.assertEqual({"version", "current", "recent"}, set(doc))
        self.assertEqual({"path", "opened"}, set(doc["recent"][0]))


class TheRoutesTests(_Store):

    def setUp(self):
        super().setUp()
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        self.walls_before = dict(server._WALLS_PROJECT)
        self.prep_before = dict(server._PREP_PROJECT)
        self.picked_before = dict(server._PICKED_ESX)
        self.addCleanup(self._restore)

    def _restore(self):
        server._WALLS_PROJECT.update(self.walls_before)
        server._PREP_PROJECT.update(self.prep_before)
        server._PICKED_ESX.clear()
        server._PICKED_ESX.update(self.picked_before)

    def post(self, url, body=None, **kw):
        return self.client.post(url, json=body or {}, headers=HDR, **kw)

    def test_current_reports_nothing_then_the_choice(self):
        r = self.post("/api/project/current").get_json()
        self.assertTrue(r["ok"])
        self.assertIsNone(r["current"])
        a = _make(self.proj, "Alpha.esx")
        cp.set_current(a)
        r = self.post("/api/project/current").get_json()
        self.assertEqual("Alpha.esx", r["current"]["name"])
        self.assertEqual(1, len(r["recent"]))

    def test_the_file_route_sends_the_current_project_and_nothing_else(self):
        a = _make(self.proj, "Alpha.esx", b"alpha-bytes")
        _make(self.proj, "Other.esx", b"other-bytes")
        cp.set_current(a)
        # No path is accepted: whatever a request says, it is the current one.
        r = self.post("/api/project/file", {"path": str(self.proj / "Other.esx")})
        self.assertEqual(200, r.status_code)
        self.assertEqual(b"alpha-bytes", r.data)
        self.assertIn("Alpha.esx", r.headers["X-WD-File-Name"])

    def test_the_file_route_refuses_when_nothing_is_current_or_it_moved(self):
        self.assertEqual(404, self.post("/api/project/file").status_code)
        a = _make(self.proj, "Alpha.esx")
        cp.set_current(a)
        a.unlink()
        self.assertEqual(404, self.post("/api/project/file").status_code)

    def test_use_refuses_a_path_that_was_never_chosen(self):
        other = _make(self.proj, "Elsewhere.esx")
        r = self.post("/api/project/use", {"path": str(other)}).get_json()
        self.assertFalse(r["ok"])
        self.assertIsNone(cp.current())

    def test_a_listed_project_can_be_read_by_report_but_a_stranger_cannot(self):
        a = _make(self.proj, "Alpha.esx", b"alpha")
        stranger = _make(self.proj, "Stranger.esx", b"nope")
        cp.set_current(a)
        ok = self.post("/api/report/open_esx", {"path": str(a)})
        self.assertEqual(200, ok.status_code)
        self.assertEqual(b"alpha", ok.data)
        bad = self.post("/api/report/open_esx", {"path": str(stranger)})
        self.assertEqual(403, bad.status_code)

    def test_quick_walls_opens_the_current_project_without_a_dialog(self):
        a = _make(self.proj, "Alpha.esx")
        cp.set_current(a)
        with mock.patch("tools.folder_organizer._tk_dialog_result",
                        side_effect=AssertionError("a dialog was opened")):
            r = self.post("/api/walls/pick", {"useCurrent": True}).get_json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(str(a), server._WALLS_PROJECT["path"])

    def test_prep_opens_the_current_project_without_a_dialog(self):
        a = _make(self.proj, "Alpha.esx", b"12345")
        cp.set_current(a)
        with mock.patch("tools.folder_organizer._tk_dialog_result",
                        side_effect=AssertionError("a dialog was opened")):
            r = self.post("/api/prep/pick", {"useCurrent": True}).get_json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(5, r["bytes"])
        self.assertEqual(str(a), server._PREP_PROJECT["path"])

    def test_use_current_with_nothing_current_is_a_sentence_not_a_dialog(self):
        for url in ("/api/walls/pick", "/api/prep/pick"):
            with mock.patch("tools.folder_organizer._tk_dialog_result",
                            side_effect=AssertionError("a dialog was opened")):
                r = self.post(url, {"useCurrent": True}).get_json()
            self.assertFalse(r["ok"], url)
            self.assertIn("Choose it again", r["error"])

    def test_choosing_in_the_dialog_makes_it_current_for_every_tool(self):
        a = _make(self.proj, "Alpha.esx")
        with mock.patch("tools.folder_organizer._tk_dialog_result",
                        return_value={"ran": True, "path": str(a), "why": ""}):
            self.assertTrue(self.post("/api/walls/pick").get_json()["ok"])
        self.assertEqual("Alpha.esx", cp.current()["name"])
        b = _make(self.proj, "Bravo.esx")
        with mock.patch("tools.folder_organizer._tk_dialog_result",
                        return_value={"ran": True, "path": str(b), "why": ""}):
            self.assertTrue(self.post("/api/prep/pick").get_json()["ok"])
        self.assertEqual("Bravo.esx", cp.current()["name"])

    def test_the_dialog_opens_in_the_current_projects_folder(self):
        sub = self.proj / "site-visit"
        sub.mkdir()
        cp.set_current(_make(sub, "Alpha.esx"))
        seen = {}

        def fake(code, *a, **k):
            seen["code"] = code
            return {"ran": True, "path": "", "why": ""}

        with mock.patch("tools.folder_organizer._tk_dialog_result", fake):
            self.post("/api/project/pick")
        self.assertIn(repr(str(sub)), seen["code"])

    def test_a_cancelled_dialog_changes_nothing(self):
        a = _make(self.proj, "Alpha.esx")
        cp.set_current(a)
        with mock.patch("tools.folder_organizer._tk_dialog_result",
                        return_value={"ran": True, "path": "", "why": ""}):
            r = self.post("/api/project/pick").get_json()
        self.assertEqual("cancelled", r["code"])
        self.assertEqual("Alpha.esx", cp.current()["name"])

    def test_a_picker_that_cannot_open_is_not_called_a_cancel(self):
        with mock.patch("tools.folder_organizer._tk_dialog_result",
                        return_value={"ran": False, "path": "", "why": "no display"}):
            r = self.post("/api/project/pick").get_json()
        self.assertEqual("picker_unavailable", r["code"])

    def test_forget_and_clear_are_routes(self):
        a = _make(self.proj, "Alpha.esx")
        cp.set_current(a)
        self.post("/api/project/forget")
        self.assertIsNone(cp.current())
        self.post("/api/project/clear")
        self.assertEqual([], cp.recent())

    def _health_fixture(self):
        from tests import test_project_health as fx
        return fx

    def test_the_check_reads_the_current_project_where_it_lies(self):
        fx = self._health_fixture()
        a = _make(self.proj, "Alpha.esx", fx.imperfect())
        cp.set_current(a)
        r = self.post("/api/project/health").get_json()
        self.assertTrue(r["ok"], r)
        self.assertEqual("Alpha.esx", r["source"])
        self.assertFalse(r["clean"])
        self.assertIn("dupName", {f["id"] for f in r["findings"]})

    def test_the_check_reads_a_dropped_project_from_the_body(self):
        fx = self._health_fixture()
        cp.set_current(_make(self.proj, "Alpha.esx", fx.imperfect()))
        r = self.client.post("/api/project/health", data=fx.clean(), headers=HDR,
                             content_type="application/octet-stream").get_json()
        self.assertTrue(r["ok"], r)
        self.assertEqual("dropped", r["source"])
        self.assertTrue(r["clean"], "the body was ignored and the current project was read")

    def test_the_check_with_no_project_says_so(self):
        r = self.post("/api/project/health")
        self.assertEqual(404, r.status_code)
        self.assertIn("Choose one", r.get_json()["error"])

    def test_the_check_on_something_that_is_not_a_project_is_an_error(self):
        r = self.client.post("/api/project/health", data=b"not a zip", headers=HDR,
                             content_type="application/octet-stream").get_json()
        self.assertFalse(r["ok"])

    def test_the_routes_need_the_local_api_header(self):
        r = self.client.post("/api/project/current", json={})
        self.assertEqual(403, r.status_code)


if __name__ == "__main__":
    unittest.main()
