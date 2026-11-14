"""An update replaces the install completely or leaves it exactly as it was.

What it did before: `copy2` over each top-level file - `server.py` among them -
and then `rmtree` of each payload folder followed by a move. A file held open
on Windows stopped `rmtree` partway, and the install was a new `server.py`
beside a half-deleted `tools/`. Nothing stopped two updates running at once
either, and a request could pick any mode or channel.

Every test here runs the real function against a throwaway install and asks
the install folder what is in it, not the return value.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server
from tools import updater


def _make_tree(cfg, root: Path, label: str):
    for name in cfg.payload_files:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{label} {name}", encoding="utf-8")
    for name in cfg.payload_dirs:
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "marker.txt").write_text(label, encoding="utf-8")


class TheInstallIsAllOrNothingTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-install-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.install = self.tmp / "install"
        self.new = self.tmp / "new"
        self.cfg = replace(updater.CONFIG, install_root=self.install)
        _make_tree(self.cfg, self.install, "old")
        _make_tree(self.cfg, self.new, "new")

    def _snapshot(self):
        return {p.relative_to(self.install).as_posix(): p.read_text("utf-8")
                for p in sorted(self.install.rglob("*")) if p.is_file()}

    def test_a_good_install_replaces_everything_and_leaves_nothing_aside(self):
        updater._install_payload(self.new, self.install, self.cfg)
        for name in self.cfg.payload_dirs:
            self.assertEqual("new", (self.install / name / "marker.txt")
                             .read_text("utf-8"))
        for name in self.cfg.payload_files:
            self.assertEqual(f"new {name}",
                             (self.install / name).read_text("utf-8"))
        stray = [p.name for p in self.install.iterdir()
                 if p.name.endswith((".wd-old", ".wd-new"))]
        self.assertEqual([], stray)

    def test_a_folder_that_will_not_move_leaves_the_old_install_whole(self):
        real_move = shutil.move
        seen = []

        def third_folder_fails(src, dst):
            seen.append(dst)
            if len(seen) == 3:
                raise OSError("a file in it is held open")
            return real_move(src, dst)

        before = self._snapshot()
        with mock.patch.object(updater.shutil, "move", third_folder_fails):
            with self.assertRaises(updater._InstallRolledBack):
                updater._install_payload(self.new, self.install, self.cfg)
        self.assertEqual(before, self._snapshot(),
                         "the install is not as it was")

    def test_a_top_level_file_that_will_not_copy_leaves_the_old_install_whole(self):
        real_copy = shutil.copy2
        seen = []

        def second_file_fails(src, dst, *a, **k):
            seen.append(dst)
            if len(seen) == 2:
                raise OSError("disk full")
            return real_copy(src, dst, *a, **k)

        before = self._snapshot()
        with mock.patch.object(updater.shutil, "copy2", second_file_fails):
            with self.assertRaises(updater._InstallRolledBack):
                updater._install_payload(self.new, self.install, self.cfg)
        self.assertEqual(before, self._snapshot())

    def test_an_undo_that_fails_is_reported_as_a_failed_install(self):
        real_move = shutil.move
        real_replace = os.replace
        seen = []

        def second_folder_fails(src, dst):
            seen.append(dst)
            if len(seen) == 2:
                raise OSError("disk full")
            return real_move(src, dst)

        def cannot_put_back(src, dst):
            if str(src).endswith(".wd-old"):
                raise OSError("handle held")
            return real_replace(src, dst)

        with mock.patch.object(updater.shutil, "move", second_folder_fails), \
                mock.patch.object(updater.os, "replace", cannot_put_back):
            with self.assertRaises(OSError) as ctx:
                updater._install_payload(self.new, self.install, self.cfg)
        self.assertNotIsInstance(ctx.exception, updater._InstallRolledBack)


class OneUpdateAtATimeTests(unittest.TestCase):

    def test_a_second_update_is_refused_while_one_runs(self):
        entered = threading.Event()
        release = threading.Event()
        outcome = {}

        def slow_detect(*a, **k):
            entered.set()
            release.wait(5)
            raise updater.UpdateError("stopped by the test")

        def first():
            try:
                updater.perform_update()
            except updater.UpdateError as e:
                outcome["first"] = str(e)

        with mock.patch.object(updater, "detect_install", slow_detect):
            t = threading.Thread(target=first)
            t.start()
            self.assertTrue(entered.wait(5))
            self.assertTrue(updater.update_running())
            with self.assertRaises(updater.UpdateError) as ctx:
                updater.perform_update()
            self.assertIn("already running", str(ctx.exception))
            self.assertTrue(ctx.exception.intact)
            release.set()
            t.join(5)
        self.assertEqual("stopped by the test", outcome["first"],
                         "the first update did not run to its own end")
        self.assertFalse(updater.update_running(),
                         "the lock was not released after the update ended")

    def test_the_lock_is_released_when_an_update_raises_something_odd(self):
        with mock.patch.object(updater, "detect_install",
                               side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                updater.perform_update()
        self.assertFalse(updater.update_running())

    def test_restart_is_refused_while_an_update_runs(self):
        client = server.app.test_client()
        with mock.patch.object(updater, "update_running", return_value=True), \
                mock.patch.object(server.threading, "Thread") as thread:
            r = client.post("/api/restart", data="{}",
                            content_type="application/json",
                            headers={server.API_REQUEST_HEADER: "1"})
        self.assertEqual(409, r.status_code)
        thread.assert_not_called()


class AZipUpdateIsForAZipInstallTests(unittest.TestCase):

    def test_a_zip_update_over_a_git_install_is_refused(self):
        info = {"method": "git", "isGitInstall": True, "gitAvailable": True,
                "isDevCheckout": False}
        with mock.patch.object(updater, "detect_install", return_value=info), \
                mock.patch.object(updater, "_dump_settings_first"), \
                mock.patch.object(updater, "zip_update") as zipped:
            with self.assertRaises(updater.UpdateError):
                updater.perform_update(mode="zip")
        zipped.assert_not_called()

    def test_a_zip_install_still_updates_from_a_zip(self):
        info = {"method": "zip", "isGitInstall": False, "gitAvailable": False,
                "isDevCheckout": False}
        with mock.patch.object(updater, "detect_install", return_value=info), \
                mock.patch.object(updater, "_dump_settings_first"), \
                mock.patch.object(updater, "zip_update",
                                  return_value={"ok": True}) as zipped:
            self.assertEqual({"ok": True}, updater.perform_update(mode="zip"))
        zipped.assert_called_once()

    def test_the_route_refuses_any_channel_but_release(self):
        client = server.app.test_client()
        with mock.patch.object(updater, "perform_update") as ran:
            r = client.post("/api/update", data=json.dumps({"channel": "main"}),
                            content_type="application/json",
                            headers={server.API_REQUEST_HEADER: "1"})
        self.assertEqual(400, r.status_code)
        ran.assert_not_called()

    def test_a_refused_update_still_answers_when_detect_install_fails(self):
        client = server.app.test_client()
        with mock.patch.object(
                updater, "perform_update",
                side_effect=updater.UpdateError("refused for a reason")), \
                mock.patch.object(updater, "detect_install",
                                  side_effect=updater.UpdateError("git hung")):
            r = client.post("/api/update", data="{}",
                            content_type="application/json",
                            headers={server.API_REQUEST_HEADER: "1"})
        body = r.get_json()
        self.assertEqual("refused for a reason", body["error"],
                         "the real refusal was replaced by the handler's own")


class _Resp:
    ok = True
    status_code = 200

    def __init__(self, chunks, per_chunk_sleep=0):
        self._chunks = chunks

    def iter_content(self, chunk_size=0):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class DownloadsAreBoundedTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-dl-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_only_https_is_downloaded(self):
        with mock.patch("requests.get") as get:
            with self.assertRaises(updater.UpdateError):
                updater._download("http://example.invalid/x.zip",
                                  self.tmp / "x")
        get.assert_not_called()

    def test_a_download_past_the_size_cap_is_stopped(self):
        with mock.patch.object(updater, "DOWNLOAD_MAX_BYTES", 100), \
                mock.patch("requests.get",
                           return_value=_Resp([b"x" * 60, b"x" * 60])):
            with self.assertRaises(updater.UpdateError) as ctx:
                updater._download("https://example.invalid/x.zip",
                                  self.tmp / "x")
        self.assertIn("larger", str(ctx.exception))

    def test_a_download_past_the_time_cap_is_stopped(self):
        ticks = iter([0.0, 0.0, 5000.0, 5000.0, 5000.0])
        with mock.patch.object(updater.time, "monotonic",
                               lambda: next(ticks)), \
                mock.patch("requests.get",
                           return_value=_Resp([b"a", b"b", b"c"])):
            with self.assertRaises(updater.UpdateError) as ctx:
                updater._download("https://example.invalid/x.zip",
                                  self.tmp / "x")
        self.assertIn("too long", str(ctx.exception))

    def test_an_ordinary_download_is_written(self):
        with mock.patch("requests.get",
                        return_value=_Resp([b"abc", b"def"])):
            updater._download("https://example.invalid/x.zip", self.tmp / "x")
        self.assertEqual(b"abcdef", (self.tmp / "x").read_bytes())


class GroupShareActionsDoNotActOnSilenceTests(unittest.TestCase):
    """A request that leaves a field out must not take the destructive
    reading of it."""

    def _post(self, action, body):
        client = server.app.test_client()
        return client.post("/api/cloud/" + action, data=json.dumps(body),
                           content_type="application/json",
                           headers={server.API_REQUEST_HEADER: "1"})

    def test_toggle_group_share_needs_an_explicit_enable(self):
        for body in ({"projectId": "p", "groupId": "g"},
                     {"projectId": "p", "groupId": "g", "enable": "yes"},
                     {"projectId": "p", "groupId": "g", "enable": None}):
            with mock.patch.object(server.cm, "toggle_group_share") as toggled:
                r = self._post("toggle_group_share", body)
            self.assertEqual(400, r.status_code, body)
            toggled.assert_not_called()

    def test_toggle_group_share_passes_an_explicit_choice_through(self):
        for value in (True, False):
            with mock.patch.object(server.cm, "toggle_group_share",
                                   return_value={"ok": True}) as toggled:
                r = self._post("toggle_group_share",
                               {"projectId": "p", "groupId": "g",
                                "enable": value})
            self.assertEqual(200, r.status_code)
            self.assertIs(toggled.call_args[0][4], value)

    def test_refresh_group_shares_is_a_dry_run_unless_told_otherwise(self):
        for body, expected in (({}, True), ({"dryRun": None}, True),
                               ({"dryRun": True}, True),
                               ({"dryRun": False}, False)):
            with mock.patch.object(server.cm, "refresh_group_shares",
                                   return_value={"ok": True}) as refreshed:
                self._post("refresh_group_shares", body)
            self.assertIs(refreshed.call_args[0][1], expected, body)


if __name__ == "__main__":
    unittest.main()
