"""The housekeeping action, exercised by pointing it at a fake machine.

It deletes things, so every safety property he asked for is checked by
building a tree, running the real `survey` and `sweep` against it, and
reading back what is on disk afterwards. Nothing here asserts on source text.

**Every root is injected.** `survey` and `sweep` take `roots`, so this never
sees his Dropbox, his project folder, his Desktop or the real `%TEMP%` - the
same reason `WD_USER_DIR` exists. A test for a delete tool that could reach
the real machine is not a test worth having.

Every project name, site folder and address in this file is invented.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import time
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from tools import housekeeping as hk

HOUR = 3600.0


def touch(path, text="x", age_hours=48.0, now=None):
    """A file, aged. Age is what decides live-versus-stale, so every fixture
    sets it explicitly rather than inheriting the clock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    when = (time.time() if now is None else now) - age_hours * HOUR
    os.utime(path, (when, when))
    return path


def make_dir(path, age_hours=48.0, now=None, files=(("note.txt", "x"),)):
    path.mkdir(parents=True, exist_ok=True)
    for name, text in files:
        touch(path / name, text, age_hours, now)
    when = (time.time() if now is None else now) - age_hours * HOUR
    os.utime(path, (when, when))
    return path


def make_esx(path, *, name="Sample Project", author="engineer@example.com",
             age_hours=48.0, now=None, valid=True, pad=0):
    """A project archive. `valid=False` writes bytes that are not a ZIP, which
    is what the suite's own error-path fixtures look like."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if valid:
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("project.json", json.dumps({"project": {
                "name": name, "title": name,
                "history": {"createdBy": author, "modifiedAt": "2026-01-01T00:00:00Z"},
            }}))
            if pad:
                z.writestr("padding.bin", b"0" * pad)
    else:
        path.write_bytes(b"not a zip at all" + b"0" * pad)
    when = (time.time() if now is None else now) - age_hours * HOUR
    os.utime(path, (when, when))
    return path


class Machine(unittest.TestCase):
    """A fake machine: a temp root, and every housekeeping root inside it."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.now = time.time()

        self.worktrees = self.base / "wd-worktrees"
        self.temp = self.base / "Temp"
        self.scratch = self.temp / "claude"
        self.desktop = self.base / "Desktop"
        self.downloads = self.base / "Downloads"
        # His, and off limits.
        self.dropbox = self.base / "Dropbox"
        self.projects = self.base / "Projects"
        for d in (self.worktrees, self.temp, self.scratch, self.desktop,
                  self.downloads, self.dropbox, self.projects):
            d.mkdir(parents=True, exist_ok=True)

        self.roots = {"worktrees": self.worktrees, "temp": self.temp,
                      "scratch": self.scratch, "desktop": self.desktop,
                      "downloads": self.downloads}

    def survey(self, **kw):
        kw.setdefault("roots", self.roots)
        kw.setdefault("now", self.now)
        kw.setdefault("registered", set())
        kw.setdefault("processes", [])
        kw.setdefault("project_folders", [str(self.projects)])
        return hk.survey(**kw)

    def sweep(self, paths, **kw):
        kw.setdefault("roots", self.roots)
        kw.setdefault("now", self.now)
        kw.setdefault("registered", set())
        kw.setdefault("processes", [])
        kw.setdefault("project_folders", [str(self.projects)])
        return hk.sweep(paths, **kw)

    def entries(self, report=None):
        report = report or self.survey()
        return {e["name"]: e for g in report["groups"] for e in g["entries"]}

    def worktree(self, name, age_hours=48.0):
        d = make_dir(self.worktrees / name, age_hours, self.now)
        (d / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
        when = self.now - age_hours * HOUR
        os.utime(d, (when, when))
        return d


class ItFindsWhatOurToolingLeft(Machine):

    def test_a_leaked_test_directory_is_found_and_offered(self):
        make_dir(self.temp / "wd-cloud-pull-abc123", 30, self.now)
        entry = self.entries()["wd-cloud-pull-abc123"]
        self.assertTrue(entry["deletable"])
        self.assertGreater(entry["idleHours"], 24)

    def test_a_leaked_python_temp_directory_is_found(self):
        make_dir(self.temp / "tmp4a9c2xkq", 30, self.now)
        self.assertIn("tmp4a9c2xkq", self.entries())

    def test_a_driver_executable_is_found(self):
        touch(self.temp / "geckodriver" / "x.exe", "bin", 30, self.now)
        self.assertIn("geckodriver", self.entries())

    def test_a_downloaded_release_zip_is_found(self):
        touch(self.temp / "WD-Wireless-Tools-v2.121.0.zip", "zip", 30, self.now)
        self.assertIn("WD-Wireless-Tools-v2.121.0.zip", self.entries())

    def test_something_that_is_not_ours_is_left_out_entirely(self):
        """Nothing is matched by looking like junk. A rule that loose would
        eventually match one of his folders."""
        make_dir(self.temp / "SomeVendorInstaller", 99, self.now)
        touch(self.temp / "his-notes.txt", "x", 99, self.now)
        names = self.entries()
        self.assertNotIn("SomeVendorInstaller", names)
        self.assertNotIn("his-notes.txt", names)

    def test_the_newest_is_listed_first(self):
        make_dir(self.temp / "wd-cloud-pull-old", 200, self.now)
        make_dir(self.temp / "wd-cloud-pull-new", 30, self.now)
        tests = [g for g in self.survey()["groups"] if g["key"] == "tests"][0]
        self.assertEqual([e["name"] for e in tests["entries"]][:2],
                         ["wd-cloud-pull-new", "wd-cloud-pull-old"])


class ItTellsLiveFromStale(Machine):

    def test_a_registered_worktree_is_live_and_not_offered(self):
        """The check the old convention was missing. `git worktree prune`
        walks straight past an abandoned worktree, so registration - not
        prune's exit code - is what says a session may still be in there."""
        d = self.worktree("live-session", age_hours=99)
        entry = self.entries(self.survey(registered={hk._norm(d)}))["live-session"]
        self.assertTrue(entry["live"])
        self.assertFalse(entry["deletable"])
        self.assertIn("worktree", entry["liveReason"].lower())

    def test_an_unregistered_worktree_is_offered_and_says_why(self):
        self.worktree("abandoned", age_hours=99)
        entry = self.entries()["abandoned"]
        self.assertTrue(entry["deletable"])
        self.assertIn("never tore it down", entry["note"])

    def test_a_folder_that_is_not_a_worktree_is_named_as_such(self):
        """Two of these sat invisible in the middle of the worktree
        convention: no git command was ever going to remove them."""
        make_dir(self.worktrees / "screenshots", 99, self.now)
        entry = self.entries()["screenshots"]
        self.assertEqual(entry["kind"], "stray-dir")
        self.assertIn("No git command", entry["note"])

    def test_something_touched_minutes_ago_is_left_alone(self):
        make_dir(self.temp / "wd-cloud-pull-busy",
                 age_hours=(hk.LIVE_WINDOW_MINUTES - 5) / 60.0, now=self.now)
        entry = self.entries()["wd-cloud-pull-busy"]
        self.assertTrue(entry["live"])
        self.assertFalse(entry["deletable"])
        self.assertIn("minutes ago", entry["liveReason"])

    def test_this_session_s_own_directory_is_never_offered(self):
        """The running server's log directory lives under a temp path during
        a test run and would otherwise look exactly like debris."""
        d = make_dir(self.temp / "wd-cloud-pull-mine", 99, self.now)
        entry = self.entries(self.survey(own_paths=[str(d)]))["wd-cloud-pull-mine"]
        self.assertTrue(entry["live"])
        self.assertIn("This session", entry["liveReason"])


class RegistrationIsFoundFromAnywhere(unittest.TestCase):
    """`registered_worktrees` asks git, and it must ask in the right place.

    It ran in the process's working directory, and the server is started from
    wherever the launcher is. Outside a repository `git worktree list` exits
    non-zero and returns nothing, so **every worktree looked abandoned** -
    including live ones. Found by driving the real action against the real
    machine rather than by any test here, which is the argument for doing
    that at least once per feature.

    The failure direction is what makes it worth a test: an empty answer
    means more things are offered for deletion, not fewer.
    """

    def test_it_finds_worktrees_from_an_unrelated_working_directory(self):
        with TemporaryDirectory() as elsewhere:
            here = os.getcwd()
            os.chdir(elsewhere)
            try:
                found = hk.registered_worktrees()
            finally:
                os.chdir(here)
        self.assertTrue(found, "no worktrees found from outside the repo - "
                               "every live one would be offered for deletion")
        self.assertIn(hk._norm(pathlib.Path(hk.__file__).resolve().parent.parent),
                      found)

    def test_a_directory_that_is_not_a_repository_yields_nothing_quietly(self):
        with TemporaryDirectory() as elsewhere:
            self.assertEqual(hk.registered_worktrees(repo=elsewhere), set())


class ItNeverTouchesHisFiles(Machine):

    def test_nothing_in_dropbox_is_listed(self):
        make_dir(self.dropbox / "wd-cloud-pull-decoy", 99, self.now)
        self.assertNotIn("wd-cloud-pull-decoy", self.entries())

    def test_nothing_in_his_project_folder_is_listed(self):
        make_dir(self.projects / "tmp4a9c2xkq", 99, self.now)
        self.assertNotIn("tmp4a9c2xkq", self.entries())

    def test_a_sweep_refuses_a_path_in_his_project_folder(self):
        """Asked directly, by path, and it still says no. The guard is not the
        UI not offering it."""
        d = make_dir(self.projects / "anything", 99, self.now)
        out = self.sweep([str(d)])
        self.assertEqual(out["counts"]["removed"], 0)
        self.assertEqual(out["counts"]["skipped"], 1)
        self.assertTrue(d.is_dir())

    def test_a_sweep_refuses_a_path_in_dropbox(self):
        d = make_dir(self.dropbox / "Projects", 99, self.now)
        out = self.sweep([str(d)])
        self.assertEqual(out["counts"]["removed"], 0)
        self.assertTrue(d.is_dir())

    def test_a_sweep_refuses_a_path_outside_every_root(self):
        d = make_dir(self.base / "Somewhere Else", 99, self.now)
        out = self.sweep([str(d)])
        self.assertEqual(out["counts"]["removed"], 0)
        self.assertTrue(d.is_dir())
        self.assertIn("not something it will delete",
                      out["skipped"][0]["reason"])

    def test_desktop_output_is_listed_but_never_deletable(self):
        """Almost certainly ours is not the standard for deleting from
        somebody's desktop. He is told, and he decides."""
        f = touch(self.desktop / "cloud-flat-1920.png", "img", 99, self.now)
        entry = self.entries()["cloud-flat-1920.png"]
        self.assertFalse(entry["deletable"])
        self.assertIn("Desktop", entry["note"])
        out = self.sweep([str(f)])
        self.assertEqual(out["counts"]["removed"], 0)
        self.assertTrue(f.exists())

    def test_his_own_desktop_files_are_not_listed_at_all(self):
        touch(self.desktop / "Tax return 2026.pdf", "x", 99, self.now)
        touch(self.desktop / "shopping.txt", "x", 99, self.now)
        names = self.entries()
        self.assertNotIn("Tax return 2026.pdf", names)
        self.assertNotIn("shopping.txt", names)


class TheWalkStopsAtHisFolders(Machine):
    """`_measure` walks a tree to size and scan it, and that walk has its own
    guard. Without a test the guard could be deleted and every
    does-not-list-his-stuff test would still pass, because those are about
    what gets *listed* - this is about what gets *read* once something is.

    The case it is for: a folder we own that contains, or links to, one of
    his. Sizing it is harmless; reading every file underneath it to grep for
    site codes is not.
    """

    def test_the_walk_does_not_descend_into_a_refused_folder(self):
        ours = make_dir(self.temp / "wd-cloud-pull-outer", 99, self.now,
                        files=(("ours.txt", "x" * 100),))
        his = make_dir(ours / "HisProjects", 99, self.now,
                       files=(("secret.txt", "y" * 100000),))

        size, files, _truncated, _f = hk._measure(ours, [his])

        self.assertLess(size, 1000, "it sized files inside a refused folder")
        self.assertEqual(files, 1)

    def test_the_walk_does_not_scan_inside_a_refused_folder(self):
        ours = make_dir(self.temp / "wd-cloud-pull-outer2", 99, self.now,
                        files=(("ours.txt", "nothing here"),))
        his = make_dir(ours / "HisProjects", 99, self.now,
                       files=(("notes.txt", "site ABCD7 survey"),))

        _s, _c, _t, findings = hk._measure(ours, [his])

        self.assertEqual(findings, 0,
                         "it read a file inside a refused folder")

    def test_without_the_guard_the_same_tree_would_be_read(self):
        """The control. If this did not find the file, the two tests above
        would pass for the wrong reason."""
        ours = make_dir(self.temp / "wd-cloud-pull-outer3", 99, self.now,
                        files=(("ours.txt", "nothing here"),))
        make_dir(ours / "HisProjects", 99, self.now,
                 files=(("notes.txt", "site ABCD7 survey"),))

        _s, _c, _t, findings = hk._measure(ours, [])

        self.assertGreater(findings, 0)


class TheHarnessClockIsHonoured(Machine):
    """`survey` and `sweep` take `now` so these tests are not racing the
    wall clock. If either ignored it, every liveness assertion here would be
    measuring something other than what it claims to."""

    def test_sweep_uses_the_clock_it_is_given(self):
        d = make_dir(self.temp / "wd-cloud-pull-clock", 99, self.now)
        # A clock far enough in the past that the entry reads as brand new.
        out = self.sweep([str(d)], now=self.now - 99 * HOUR)
        self.assertEqual(out["counts"]["removed"], 0)
        self.assertTrue(d.is_dir())

    def test_survey_uses_the_clock_it_is_given(self):
        make_dir(self.temp / "wd-cloud-pull-clock2", 99, self.now)
        entry = self.entries(self.survey(now=self.now - 99 * HOUR))
        self.assertTrue(entry["wd-cloud-pull-clock2"]["live"])


class TheSweepChecksAgainRatherThanTrusting(Machine):

    def test_it_removes_what_the_preview_offered(self):
        d = make_dir(self.temp / "wd-cloud-pull-gone", 99, self.now)
        out = self.sweep([str(d)])
        self.assertEqual(out["counts"]["removed"], 1)
        self.assertFalse(d.exists())
        self.assertGreater(out["freedBytes"], 0)

    def test_a_path_that_went_live_in_between_is_skipped(self):
        """The property that makes the preview safe to act on: it is not the
        preview's verdict that decides, it is a fresh one."""
        d = make_dir(self.temp / "wd-cloud-pull-woke", 99, self.now)
        preview = self.entries()["wd-cloud-pull-woke"]
        self.assertTrue(preview["deletable"])

        os.utime(d, (self.now, self.now))          # somebody started using it

        out = self.sweep([str(d)])
        self.assertEqual(out["counts"]["removed"], 0)
        self.assertEqual(out["counts"]["skipped"], 1)
        self.assertTrue(d.is_dir())
        self.assertIn("minutes ago", out["skipped"][0]["reason"])

    def test_a_registered_worktree_is_skipped_even_when_asked_for(self):
        d = self.worktree("still-working", age_hours=99)
        out = self.sweep([str(d)], registered={hk._norm(d)})
        self.assertEqual(out["counts"]["removed"], 0)
        self.assertTrue(d.is_dir())

    def test_a_removal_failure_is_reported_rather_than_swallowed(self):
        d = make_dir(self.temp / "wd-cloud-pull-stuck", 99, self.now)

        def refuse(path):
            raise OSError("in use by another process")

        out = self.sweep([str(d)], remover=refuse)
        self.assertEqual(out["counts"]["failed"], 1)
        self.assertIn("in use", out["failed"][0]["error"])
        self.assertTrue(d.is_dir())

    def test_the_three_lists_account_for_everything_asked_for(self):
        good = make_dir(self.temp / "wd-cloud-pull-a", 99, self.now)
        his = make_dir(self.projects / "b", 99, self.now)
        out = self.sweep([str(good), str(his)])
        total = sum(out["counts"][k] for k in ("removed", "skipped", "failed"))
        self.assertEqual(total, 2)


class WorkplaceDataIsCountedAndNeverQuoted(Machine):

    def test_a_synthetic_fixture_is_not_flagged(self):
        """The failure that made the first version useless: flagging on the
        `.esx` extension lit up 2,226 entries, every one of them a fixture
        the suite had written."""
        make_esx(self.temp / "wd-cloud-pull-x" / "Sample Project.esx",
                 name="Sample Project", author="engineer@example.com",
                 age_hours=99, now=self.now)
        self.assertEqual(self.entries()["wd-cloud-pull-x"]["dataFindings"], 0)

    def test_a_project_authored_at_a_real_domain_is_flagged(self):
        make_esx(self.temp / "wd-cloud-pull-y" / "Something.esx",
                 name="Something", author="someone@a-real-employer.test",
                 age_hours=99, now=self.now)
        self.assertGreater(self.entries()["wd-cloud-pull-y"]["dataFindings"], 0)

    def test_a_site_code_shaped_project_name_is_flagged(self):
        make_esx(self.temp / "wd-cloud-pull-z" / "p.esx",
                 name="ABCD7 Some Building", age_hours=99, now=self.now)
        self.assertGreater(self.entries()["wd-cloud-pull-z"]["dataFindings"], 0)

    def test_a_small_unreadable_esx_is_a_stub_not_a_project(self):
        """683 of these were being flagged - the suite writes dummy bytes to
        `.esx` paths to exercise error handling."""
        make_esx(self.temp / "wd-cloud-pull-s" / "stub.esx",
                 valid=False, age_hours=99, now=self.now)
        self.assertEqual(self.entries()["wd-cloud-pull-s"]["dataFindings"], 0)

    def test_a_large_unreadable_esx_goes_on_the_list(self):
        """A real project truncated by an interrupted copy is also not a valid
        ZIP. "I could not tell" belongs where he looks."""
        make_esx(self.temp / "wd-cloud-pull-t" / "big.esx", valid=False,
                 pad=hk._REAL_PROJECT_MIN_BYTES + 10, age_hours=99, now=self.now)
        self.assertGreater(self.entries()["wd-cloud-pull-t"]["dataFindings"], 0)

    def test_text_carrying_a_site_code_is_flagged(self):
        make_dir(self.temp / "wd-cloud-pull-n", 99, self.now,
                 files=(("note.txt", "checked ABCD7 today"),))
        self.assertGreater(self.entries()["wd-cloud-pull-n"]["dataFindings"], 0)

    def test_the_repository_s_own_placeholders_are_not_flagged(self):
        make_dir(self.temp / "wd-cloud-pull-p", 99, self.now,
                 files=(("note.txt", "SITE1 and TEST2 and ACME1"),))
        self.assertEqual(self.entries()["wd-cloud-pull-p"]["dataFindings"], 0)

    def test_the_report_never_carries_the_value_it_matched(self):
        """A report that quoted them would be one more copy of the thing being
        reported - the same trap as the scrub-without-quoting commit."""
        secret = "ABCD7"
        make_dir(self.temp / "wd-cloud-pull-q", 99, self.now,
                 files=(("note.txt", "site %s survey" % secret),))
        blob = json.dumps(self.survey())
        self.assertNotIn(secret, blob)

    def test_the_totals_add_the_findings_up(self):
        make_dir(self.temp / "wd-cloud-pull-1", 99, self.now,
                 files=(("a.txt", "ABCD7"),))
        make_dir(self.temp / "wd-cloud-pull-2", 99, self.now,
                 files=(("a.txt", "WXYZ9"),))
        totals = self.survey()["totals"]
        self.assertEqual(totals["withData"], 2)
        self.assertGreaterEqual(totals["dataFindings"], 2)


class VendoredCodeIsNotHisData(Machine):
    """Minified third-party bundles throw off every heuristic here.

    `tests/test_no_real_world_data.py` already skips `web/assets/lib/` for
    this reason - an AWS key prefix once turned up in that scan as a mangled
    variable name inside pdf.js. The same thing happened here the first time
    a worktree was surveyed: `jszip.min.js` and `mammoth.browser.min.js`
    produced six of the eighteen "signals" reported against a tree that is
    rule-zero clean by construction. Noise in this number is expensive,
    because it is the number he is meant to act on.
    """

    def test_a_vendored_bundle_is_not_scanned(self):
        lib = self.temp / "wd-cloud-pull-v" / "web" / "assets" / "lib"
        touch(lib / "some.min.js", "var ABCD7=1,WXYZ9=2;", 99, self.now)
        self.assertEqual(self.entries()["wd-cloud-pull-v"]["dataFindings"], 0)

    def test_the_same_content_anywhere_else_is_scanned(self):
        """The control. Without it the test above passes for the wrong
        reason - because nothing was read at all."""
        ours = self.temp / "wd-cloud-pull-w" / "src"
        touch(ours / "some.min.js", "var ABCD7=1,WXYZ9=2;", 99, self.now)
        self.assertGreater(self.entries()["wd-cloud-pull-w"]["dataFindings"], 0)

    def test_the_skip_is_written_without_a_backslash_literal(self):
        """Every entry is forward-slash only, compared against `as_posix()`.

        Writing Windows separators as string literals here went wrong during
        this very change - the patch script turned four backslashes into one
        and the constant silently stopped matching. It is the gotcha CLAUDE.md
        names, and this is the cheap guard against it coming back.
        """
        for part in hk._SKIP_PATH_PARTS:
            self.assertNotIn("\\", part)
            self.assertIn("/", part)


class TheScanCannotHangTheSurvey(Machine):

    def test_a_long_run_of_characters_does_not_take_forever(self):
        """The defect that made the first real run unusable: the unbounded
        email pattern backtracked quadratically on a log file, and one 393 KB
        file took 163 seconds. Bounding every quantifier fixed it."""
        make_dir(self.temp / "wd-cloud-pull-big", 99, self.now,
                 files=(("server.log", "a" * 300000),))
        start = time.monotonic()
        self.survey()
        self.assertLess(time.monotonic() - start, 5.0)

    def test_the_budget_is_reported_when_it_runs_out(self):
        budget = hk._Budget(seconds=-1)
        self.assertTrue(budget.spent())
        self.assertFalse(budget.complete)

    def test_a_spent_budget_still_sizes_everything(self):
        """Sizing is never budgeted. A size that silently stopped counting
        would be a lie about how much is out there."""
        make_dir(self.temp / "wd-cloud-pull-sz", 99, self.now,
                 files=(("a.txt", "x" * 5000),))
        report = self.survey()
        self.assertGreaterEqual(
            self.entries(report)["wd-cloud-pull-sz"]["sizeBytes"], 5000)


class ProcessesItWillOffer(unittest.TestCase):

    def rows(self, *rows):
        return lambda: list(rows)

    def test_a_driver_is_offered(self):
        out = hk.list_processes(self.rows(
            {"pid": 11, "name": "geckodriver.exe", "cmd": "geckodriver --port 1"}))
        self.assertEqual([p["pid"] for p in out], [11])

    def test_a_headless_browser_is_offered(self):
        out = hk.list_processes(self.rows(
            {"pid": 12, "name": "firefox.exe",
             "cmd": "firefox -headless -profile rust_mozprofile123"}))
        self.assertEqual([p["pid"] for p in out], [12])

    def test_his_own_browser_is_never_offered(self):
        """`taskkill /IM firefox.exe` would take down the window he is reading
        this in. His browser is in that process table too."""
        out = hk.list_processes(self.rows(
            {"pid": 13, "name": "firefox.exe", "cmd": "firefox.exe"},
            {"pid": 14, "name": "chrome.exe", "cmd": "chrome.exe --profile-directory=Default"}))
        self.assertEqual(out, [])

    def test_an_unrelated_process_is_never_offered(self):
        out = hk.list_processes(self.rows(
            {"pid": 15, "name": "explorer.exe", "cmd": "explorer.exe"}))
        self.assertEqual(out, [])

    def test_a_process_listing_that_fails_is_not_a_crash(self):
        def boom():
            raise OSError("no wmi")
        self.assertEqual(hk.list_processes(boom), [])


class TheSuiteCleansUpAfterItself(unittest.TestCase):
    """The ratchet. 12.73 GB was recovered from session debris, and the
    biggest single contributor was this suite: 1,314 directories from one
    `setUp` with no `tearDown`, 143 more from one per run left behind on
    purpose because "the OS clears the temp tree anyway" - which is not true
    on Windows. Measured after fixing them: 116 directories leaked per run
    before, 1 after, and that one is Chrome's own.

    So the rule is executable rather than written down. A new `mkdtemp` with
    no cleanup in its enclosing function fails here.

    **What it checks is that a cleanup is registered, not that it worked**,
    and the difference is a real leak it cannot see. `shutil.rmtree(...,
    ignore_errors=True)` on a directory Windows will not delete - because
    something still holds a handle on a file inside it - removes nothing and
    says nothing, and this check passes because the call is there. That
    happened on 2026-09-21: `send_file` keeps the file open until the
    response is closed, Flask's test client does not close it, and
    `test_the_server_answers_safely.py` left a `wd-cover-*` directory behind
    on every run. Two rules follow, and neither is enforceable from here:

    * **Register the release of the handle before the removal.** Cleanups
      run in reverse, so `addCleanup(response.close)` after
      `addCleanup(rmtree, d)` is what makes the removal succeed.
    * **Count, once, after a change that adds a temp directory.** Listing
      `%TEMP%` either side of a run is five seconds and it is the only thing
      that distinguishes a cleanup that ran from one that worked.
    """

    CLEANUP_MARKERS = ("rmtree", "addCleanup", "atexit", "TemporaryDirectory",
                       "cleanup")

    @staticmethod
    def _calls_mkdtemp(node):
        """A real `mkdtemp(...)` call, found in the tree rather than in the
        text. Matching the string instead made this file fail on itself -
        the checker mentions `mkdtemp` several times and calls it never.
        A checker that had to exempt itself would be a checker with a hole,
        so it was made precise instead."""
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            fn = inner.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else "")
            if name == "mkdtemp":
                return True
        return False

    def test_every_temp_directory_a_test_makes_is_cleaned_up(self):
        root = Path(__file__).resolve().parent
        unmanaged = []
        for path in sorted(root.glob("*.py")):
            src = path.read_text(encoding="utf-8")
            if "mkdtemp" not in src:
                continue
            tree = ast.parse(src)
            scopes = [n for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            scopes.extend(n for n in tree.body
                          if not isinstance(n, (ast.FunctionDef, ast.ClassDef)))
            for node in scopes:
                if not self._calls_mkdtemp(node):
                    continue
                segment = ast.get_source_segment(src, node) or ""
                if not any(m in segment for m in self.CLEANUP_MARKERS):
                    unmanaged.append("%s:%d" % (path.name, node.lineno))
        self.assertEqual(unmanaged, [],
                         "these make a temp directory and never remove it, "
                         "which is how 12.73 GB accumulated on his machine")


if __name__ == "__main__":
    unittest.main()
