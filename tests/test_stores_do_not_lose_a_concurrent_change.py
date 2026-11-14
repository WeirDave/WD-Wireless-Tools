"""Two requests changing the same store at once both land.

The server answers requests on several threads. A store that reads its file,
changes the copy and writes it back loses a change when two requests do that at
the same time: both read the same old file and the second write replaces the
first. Writing the file atomically (so it is never half-written) does not help
with that; serialising the read-change-write does.

Each test runs the real store function from several threads, with the read made
slow so the threads genuinely overlap, and asks the file what it holds.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import cloud_manager, plantrim_store, settings, share_recipients

THREADS = 6


def _slow(real, delay=0.03):
    """The same function, taking long enough that unlocked threads overlap."""
    def wrapper(*args, **kwargs):
        out = real(*args, **kwargs)
        time.sleep(delay)
        return out
    return wrapper


def _together(fn, count=THREADS):
    failures = []

    def run(n):
        try:
            fn(n)
        except BaseException as e:  # noqa: BLE001 - reported below
            failures.append(e)

    threads = [threading.Thread(target=run, args=(n,)) for n in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not any(t.is_alive() for t in threads), "a store call never returned"
    if failures:
        raise failures[0]


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-conc-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class RecipientsTests(_Tmp):

    def test_addresses_remembered_at_once_are_all_remembered(self):
        with mock.patch.object(share_recipients, "store_path",
                               lambda: self.tmp / "r.json"), \
                mock.patch.object(share_recipients, "_load",
                                  _slow(share_recipients._load)):
            _together(lambda n: share_recipients.remember(f"p{n}@example.test"))
            held = {r["email"] for r in share_recipients.recent()}
        self.assertEqual({f"p{n}@example.test" for n in range(THREADS)}, held)


class SettingsTests(_Tmp):

    def test_settings_changed_at_once_are_all_kept(self):
        path = self.tmp / "settings.json"
        with mock.patch.object(settings, "load_settings",
                               _slow(settings.load_settings)):
            _together(lambda n: settings.update_settings(
                {"cloud": {f"concurrent_{n}": n}}, _path=path))
        saved = json.loads(path.read_text(encoding="utf-8"))["cloud"]
        self.assertEqual({f"concurrent_{n}" for n in range(THREADS)},
                         {k for k in saved if k.startswith("concurrent_")})


class MatchesTests(_Tmp):

    def test_pairs_marked_not_a_match_at_once_are_all_recorded(self):
        with mock.patch.object(cloud_manager, "CONFIG_DIR", self.tmp), \
                mock.patch.object(cloud_manager, "NOT_MATCH_FILE",
                                  self.tmp / "nm.json"), \
                mock.patch.object(cloud_manager, "load_not_matches",
                                  _slow(cloud_manager.load_not_matches)):
            _together(lambda n: cloud_manager.CloudManager.mark_not_match(
                None, f"cloud-{n}", f"C:/p/{n}.esx"))
            held = cloud_manager.load_not_matches.__wrapped__() \
                if hasattr(cloud_manager.load_not_matches, "__wrapped__") \
                else None
        data = json.loads((self.tmp / "nm.json").read_text(encoding="utf-8"))
        self.assertEqual({f"cloud-{n}" for n in range(THREADS)},
                         {p["cloudId"] for p in data["pairs"]})


class BoxesTests(_Tmp):

    def test_boxes_saved_for_different_projects_at_once_are_all_kept(self):
        boxes = {"floor-1": [0.1, 0.1, 0.5, 0.5]}
        with mock.patch.object(plantrim_store, "USER_DIR", self.tmp), \
                mock.patch.object(plantrim_store, "STORE", self.tmp / "b.json"), \
                mock.patch.object(plantrim_store, "_load_all",
                                  _slow(plantrim_store._load_all)):
            _together(lambda n: plantrim_store.save(f"project-{n}", boxes))
        data = json.loads((self.tmp / "b.json").read_text(encoding="utf-8"))
        self.assertEqual({f"project-{n}" for n in range(THREADS)}, set(data))


if __name__ == "__main__":
    unittest.main()
