from __future__ import annotations

import json
import tempfile
import time
from unittest import mock
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import updater


def _make_install(root: Path, version: str = "2.5.0"):
    """Minimal tree that looks like a release install."""
    (root / "web" / "assets").mkdir(parents=True)
    (root / "web" / "assets" / "versions.json").write_text(
        json.dumps({"suite": version}), encoding="utf-8")
    for name in updater.PAYLOAD_FILES:
        (root / name).write_text("x", encoding="utf-8")
    for name in updater.PAYLOAD_DIRS:
        (root / name).mkdir(exist_ok=True)
    return root


class VersionCompareTests(unittest.TestCase):
    def test_ordering(self):
        self.assertEqual(updater.cmp_version("2.6.0", "2.5.0"), 1)
        self.assertEqual(updater.cmp_version("2.5.0", "2.6.0"), -1)
        self.assertEqual(updater.cmp_version("2.5.0", "2.5.0"), 0)

    def test_double_digit_segments_are_not_compared_as_text(self):
        self.assertEqual(updater.cmp_version("2.10.0", "2.9.0"), 1)
        self.assertEqual(updater.cmp_version("2.5.10", "2.5.9"), 1)

    def test_uneven_lengths_pad_with_zero(self):
        self.assertEqual(updater.cmp_version("2.5", "2.5.0"), 0)
        self.assertEqual(updater.cmp_version("2.5.1", "2.5"), 1)

    def test_leading_v_is_tolerated(self):
        self.assertEqual(updater.cmp_version("v2.6.0", "2.5.0"), 1)

    def test_missing_version_sorts_below_anything(self):
        self.assertEqual(updater.cmp_version("2.5.0", ""), 1)


class DetectInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = _make_install(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_zip_install_without_git_offers_zip(self):
        with patch.object(updater, "git_available", return_value=False),              patch.object(updater, "git_install_plan",
                          return_value={"needed": True, "possible": False,
                                        "method": None, "message": "no"}):
            info = updater.detect_install(self.root)
        self.assertEqual(info["method"], "zip")
        self.assertFalse(info["isGitInstall"])
        self.assertFalse(info["canConvertToGit"])

    def test_conversion_is_offered_when_git_can_be_installed(self):
        """Git being absent is not a dead end on Windows — winget installs it
        in seconds, so the git route stays on offer."""
        with patch.object(updater, "git_available", return_value=False),              patch.object(updater, "git_install_plan",
                          return_value={"needed": True, "possible": True,
                                        "method": "winget", "message": "ok"}):
            info = updater.detect_install(self.root)
        self.assertEqual(info["method"], "zip")
        self.assertTrue(info["canConvertToGit"])

    def test_zip_install_with_git_can_convert(self):
        with patch.object(updater, "git_available", return_value=True):
            info = updater.detect_install(self.root)
        self.assertEqual(info["method"], "zip")
        self.assertTrue(info["canConvertToGit"])

    def test_git_install_uses_the_git_path(self):
        (self.root / ".git").mkdir()

        def fake_git(args, cwd, check=True):
            if args[:2] == ["rev-parse", "--abbrev-ref"]:
                out = "main\n"          # on a branch
            elif args[0] == "rev-list":
                out = "0\n"             # nothing unpushed
            elif args[0] == "status":
                out = ""                # clean tree
            else:
                out = ""
            return type("P", (), {"stdout": out, "returncode": 0})()

        with patch.object(updater, "git_available", return_value=True), \
             patch.object(updater, "_run_git", side_effect=fake_git):
            info = updater.detect_install(self.root)
        self.assertEqual(info["method"], "git")
        self.assertTrue(info["isGitInstall"])
        self.assertFalse(info["isDevCheckout"])

    def test_git_checkout_without_git_installed_is_manual(self):
        (self.root / ".git").mkdir()
        with patch.object(updater, "git_available", return_value=False):
            info = updater.detect_install(self.root)
        self.assertEqual(info["method"], "manual")

    def test_current_version_is_read_from_versions_json(self):
        with patch.object(updater, "git_available", return_value=False):
            info = updater.detect_install(self.root)
        self.assertEqual(info["currentVersion"], "2.5.0")


def _git(args, cwd):
    import subprocess
    return subprocess.run(["git"] + args, cwd=str(cwd),
                          capture_output=True, text=True)


@unittest.skipUnless(updater.git_available(), "git is not installed")
class DevCheckoutGuardTests(unittest.TestCase):
    """A maintainer's working copy must not be auto-updated, but an ordinary
    user who installs by cloning must be. Both look identical on disk — the
    repo ships tests/ and .github/ — so the distinction is git state."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.origin = base / "origin"
        self.clone = base / "clone"
        self.origin.mkdir()
        _git(["init", "--bare", "--initial-branch=main"], self.origin)

        seed = base / "seed"
        _make_install(seed)
        # The repo ships these, so every user clone has them too. They are
        # exactly what a file-marker heuristic would misread as "developer".
        for extra in ("tests", ".github", "scripts"):
            (seed / extra).mkdir(exist_ok=True)
            (seed / extra / "placeholder").write_text("x", encoding="utf-8")
        (seed / "BACKLOG.md").write_text("x", encoding="utf-8")
        (seed / "CLAUDE.md").write_text("x", encoding="utf-8")
        _git(["init", "--initial-branch=main"], seed)
        _git(["add", "-A"], seed)
        _git(["-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "v1"], seed)
        _git(["tag", "v2.5.0"], seed)
        _git(["remote", "add", "origin", str(self.origin)], seed)
        _git(["push", "--quiet", "origin", "main", "--tags"], seed)

        _git(["clone", "--quiet", str(self.origin), str(self.clone)], base)

    def tearDown(self):
        self.temp.cleanup()

    def test_a_users_fresh_clone_is_not_a_dev_checkout(self):
        """The regression that matters: a clone contains tests/ and .github/,
        so a file-marker heuristic would wrongly block every git user."""
        self.assertTrue((self.clone / "tests").exists())
        self.assertFalse(updater.is_dev_checkout(self.clone))

    def test_detached_at_a_tag_is_a_normal_install(self):
        _git(["-c", "advice.detachedHead=false", "checkout", "v2.5.0"], self.clone)
        self.assertFalse(updater.is_dev_checkout(self.clone))

    def test_unpushed_commits_mark_a_dev_checkout(self):
        (self.clone / "server.py").write_text("changed", encoding="utf-8")
        _git(["add", "-A"], self.clone)
        _git(["-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "wip"], self.clone)
        self.assertTrue(updater.is_dev_checkout(self.clone))

    def test_modified_tracked_files_mark_a_dev_checkout(self):
        (self.clone / "server.py").write_text("edited", encoding="utf-8")
        self.assertTrue(updater.is_dev_checkout(self.clone))

    def test_untracked_files_alone_do_not(self):
        (self.clone / "Site.esx").write_text("x", encoding="utf-8")
        self.assertFalse(updater.is_dev_checkout(self.clone))

    def test_a_zip_install_is_never_a_dev_checkout(self):
        plain = Path(self.temp.name) / "zip"
        _make_install(plain)
        self.assertFalse(updater.is_dev_checkout(plain))

    def test_detect_install_reports_dev_for_a_working_copy(self):
        (self.clone / "server.py").write_text("edited", encoding="utf-8")
        info = updater.detect_install(self.clone)
        self.assertEqual(info["method"], "dev")
        self.assertTrue(info["isDevCheckout"])

    def test_detect_install_reports_git_for_a_clean_clone(self):
        info = updater.detect_install(self.clone)
        self.assertEqual(info["method"], "git")
        self.assertFalse(info["isDevCheckout"])

    def test_perform_update_refuses_on_a_dev_checkout(self):
        with patch.object(updater, "detect_install",
                          return_value={"method": "dev", "isDevCheckout": True}):
            with self.assertRaises(updater.UpdateError) as ctx:
                updater.perform_update()
        self.assertIn("development checkout", str(ctx.exception))


class PayloadValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = _make_install(Path(self.temp.name), version="2.6.0")

    def tearDown(self):
        self.temp.cleanup()

    def test_accepts_a_complete_tree(self):
        self.assertEqual(updater._validate_payload(self.root, "2.6.0"), "2.6.0")

    def test_rejects_a_missing_file(self):
        (self.root / "server.py").unlink()
        with self.assertRaises(updater.UpdateError):
            updater._validate_payload(self.root, "2.6.0")

    def test_rejects_a_missing_directory(self):
        import shutil
        shutil.rmtree(self.root / "tools")
        with self.assertRaises(updater.UpdateError):
            updater._validate_payload(self.root, "2.6.0")

    def test_rejects_a_version_that_disagrees_with_the_tag(self):
        with self.assertRaises(updater.UpdateError) as ctx:
            updater._validate_payload(self.root, "2.7.0")
        self.assertIn("2.7.0", str(ctx.exception))


class DirtyPathTests(unittest.TestCase):
    def _porcelain(self, text):
        return type("P", (), {"stdout": text, "returncode": 0})()

    def test_untracked_files_do_not_block_an_update(self):
        """git pull only conflicts on tracked files — an untracked .esx or note
        sitting in the folder is harmless and must not stop the update."""
        with patch.object(updater, "_run_git",
                          return_value=self._porcelain("?? notes.txt\n?? Site.esx\n")):
            self.assertEqual(updater._dirty_paths(Path(".")), [])

    def test_modified_tracked_files_are_reported(self):
        with patch.object(updater, "_run_git",
                          return_value=self._porcelain(" M server.py\n M templates/A.json\n")):
            self.assertEqual(updater._dirty_paths(Path(".")),
                             ["server.py", "templates/A.json"])

    def test_mixed_output_keeps_only_tracked_changes(self):
        with patch.object(updater, "_run_git",
                          return_value=self._porcelain(" M server.py\n?? scratch/\n")):
            self.assertEqual(updater._dirty_paths(Path(".")), ["server.py"])


class GitUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = _make_install(Path(self.temp.name))
        (self.root / ".git").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_refuses_when_tracked_files_are_locally_modified(self):
        with patch.object(updater, "rescue_dirty_templates", return_value=[]), \
             patch.object(updater, "_dirty_paths", return_value=["server.py"]):
            with self.assertRaises(updater.UpdateError) as ctx:
                updater.git_update(self.root)
        self.assertIn("server.py", str(ctx.exception))

    def test_refuses_without_a_git_folder(self):
        import shutil
        shutil.rmtree(self.root / ".git")
        with self.assertRaises(updater.UpdateError):
            updater.git_update(self.root)

    def test_already_current_does_not_check_anything_out(self):
        """Detaching HEAD to land on the commit it already points at changes
        nothing but looks alarming in a healthy clone."""
        calls = []

        def fake_run(args, cwd, check=True):
            calls.append(args)
            if args[0] == "tag":
                return type("P", (), {"stdout": "v2.5.0\n", "returncode": 0})()
            return type("P", (), {"stdout": "", "returncode": 0})()

        with patch.object(updater, "rescue_dirty_templates", return_value=[]),              patch.object(updater, "_dirty_paths", return_value=[]),              patch.object(updater, "_run_git", side_effect=fake_run):
            result = updater.git_update(self.root)   # tree is v2.5.0

        self.assertFalse(result["changed"])
        self.assertEqual(result["newVersion"], "2.5.0")
        self.assertEqual([c for c in calls if "checkout" in c], [],
                         "no checkout should run when already current")

    def test_checks_out_the_highest_release_tag(self):
        calls = []

        def fake_run(args, cwd, check=True):
            calls.append(args)
            if args[0] == "tag":
                return type("P", (), {"stdout": "v2.4.0\nv2.10.0\nv2.9.0\n", "returncode": 0})()
            return type("P", (), {"stdout": "", "returncode": 0})()

        with patch.object(updater, "rescue_dirty_templates", return_value=[]), \
             patch.object(updater, "_dirty_paths", return_value=[]), \
             patch.object(updater, "_run_git", side_effect=fake_run):
            result = updater.git_update(self.root)

        self.assertEqual(result["target"], "v2.10.0")
        checkout = [c for c in calls if "checkout" in c][0]
        self.assertIn("v2.10.0", checkout)


class GitInstallPlanTests(unittest.TestCase):
    def test_no_plan_needed_when_git_is_present(self):
        with patch.object(updater, "git_available", return_value=True):
            plan = updater.git_install_plan()
        self.assertFalse(plan["needed"])
        self.assertTrue(plan["possible"])

    def test_winget_makes_it_possible_on_windows(self):
        with patch.object(updater, "git_available", return_value=False),              patch.object(updater, "winget_available", return_value=True),              patch.object(updater.os, "name", "nt"):
            plan = updater.git_install_plan()
        self.assertTrue(plan["needed"])
        self.assertTrue(plan["possible"])
        self.assertEqual(plan["method"], "winget")

    def test_windows_without_winget_explains_the_fallback(self):
        with patch.object(updater, "git_available", return_value=False),              patch.object(updater, "winget_available", return_value=False),              patch.object(updater.os, "name", "nt"):
            plan = updater.git_install_plan()
        self.assertTrue(plan["needed"])
        self.assertFalse(plan["possible"])
        self.assertIn("ZIP", plan["message"])

    def test_non_windows_describes_rather_than_runs(self):
        with patch.object(updater, "git_available", return_value=False),              patch.object(updater.os, "name", "posix"):
            plan = updater.git_install_plan()
        self.assertTrue(plan["needed"])
        self.assertFalse(plan["possible"])

    def test_install_git_refuses_when_it_cannot_succeed(self):
        with patch.object(updater, "git_install_plan",
                          return_value={"needed": True, "possible": False,
                                        "method": None, "message": "blocked here"}):
            with self.assertRaises(updater.UpdateError) as ctx:
                updater.install_git()
        self.assertIn("blocked here", str(ctx.exception))

    def test_install_git_is_a_noop_when_already_present(self):
        with patch.object(updater, "git_available", return_value=True):
            result = updater.install_git()
        self.assertTrue(result["ok"])
        self.assertFalse(result["installed"])


class ConfigPortabilityTests(unittest.TestCase):
    """The updater is meant to port to the sibling apps by editing CONFIG."""

    def test_urls_derive_from_the_repo_field(self):
        cfg = updater.AppConfig(
            name="Example", repo="Someone/Example",
            install_root=Path("."), version_path="v.json", version_key="app",
            asset_template="Example-{tag}.zip",
            payload_files=(), payload_dirs=(),
            user_data_dir=Path("."))
        self.assertEqual(cfg.api_latest,
                         "https://api.github.com/repos/Someone/Example/releases/latest")
        self.assertEqual(cfg.clone_url, "https://github.com/Someone/Example.git")
        self.assertEqual(cfg.asset_name("v1.2.3"), "Example-v1.2.3.zip")

    def test_asset_template_can_use_the_bare_version(self):
        cfg = updater.AppConfig(
            name="E", repo="a/b", install_root=Path("."),
            version_path="v.json", version_key="app",
            asset_template="E-{version}.zip",
            payload_files=(), payload_dirs=(), user_data_dir=Path("."))
        self.assertEqual(cfg.asset_name("v1.2.3"), "E-1.2.3.zip")

    def test_version_is_read_through_the_configured_path_and_key(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "meta").mkdir()
            (root / "meta" / "v.json").write_text(json.dumps({"app": "9.9.9"}),
                                                  encoding="utf-8")
            cfg = updater.AppConfig(
                name="E", repo="a/b", install_root=root,
                version_path="meta/v.json", version_key="app",
                asset_template="E-{tag}.zip",
                payload_files=(), payload_dirs=(), user_data_dir=root)
            self.assertEqual(updater.local_version(root, cfg), "9.9.9")

    def test_wd_config_matches_the_release_builder(self):
        """CONFIG.payload_* must stay in step with scripts/build_release.py, or
        a ZIP update would replace a different set of files than it ships."""
        import re as _re
        src = (Path(__file__).resolve().parent.parent
               / "scripts" / "build_release.py").read_text(encoding="utf-8")
        files = set(_re.findall(r'"([^"]+)",', src.split("ROOT_FILES = (")[1].split(")")[0]))
        dirs = set(_re.findall(r'"([^"]+)"',
                               src.split("ROOT_DIRECTORIES = (")[1].split(")")[0]))
        self.assertEqual(set(updater.CONFIG.payload_files), files)
        self.assertEqual(set(updater.CONFIG.payload_dirs), dirs)



class _Resp:
    def __init__(self, status=200, headers=None, payload=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.headers = headers or {}
        self._payload = payload or {
            "tag_name": "v9.9.9", "html_url": "https://example.invalid/r",
            "body": "notes", "assets": [],
        }

    def json(self):
        return self._payload


class ReleaseLookupCostTests(unittest.TestCase):
    """How many requests one session spends on GitHub's sixty-an-hour.

    The allowance is counted per IP address, not per person, so an office
    behind one NAT shares it. Every /api/update/status used to be a fresh
    request - one per page load on which About was opened - and so did every
    update run, which is how a day of updating spends the hour and the next
    single click reports a limit the person did not cause.
    """

    def setUp(self):
        updater._RELEASE_CACHE.update(
            {"at": 0.0, "data": None, "etag": None, "blocked_until": 0.0})

    def tearDown(self):
        self.setUp()

    def test_repeated_checks_cost_one_request(self):
        calls = []

        def get(url, *a, **k):
            calls.append(url)
            return _Resp(headers={"ETag": '"abc"'})

        with mock.patch("requests.get", get):
            for _ in range(8):
                updater.fetch_latest_release()
        self.assertEqual(len(calls), 1,
                         "eight checks should not be eight requests")

    def test_a_recheck_sends_the_etag_so_github_can_answer_free(self):
        """A 304 does not count against the allowance."""
        seen = []

        def get(url, headers=None, **k):
            seen.append(dict(headers or {}))
            if len(seen) == 1:
                return _Resp(headers={"ETag": '"abc"'})
            return _Resp(status=304, headers={"ETag": '"abc"'})

        with mock.patch("requests.get", get):
            first = updater.fetch_latest_release()
            updater._RELEASE_CACHE["at"] = 0.0        # let the TTL lapse
            again = updater.fetch_latest_release()

        self.assertEqual(first, again)
        self.assertNotIn("If-None-Match", seen[0])
        self.assertEqual(seen[1].get("If-None-Match"), '"abc"',
                         "the second request has to carry the ETag or the "
                         "answer cannot be a free 304")

    def test_being_limited_says_when_it_clears(self):
        reset = int(time.time()) + 1800

        def get(url, *a, **k):
            return _Resp(status=403, headers={"X-RateLimit-Remaining": "0",
                                              "X-RateLimit-Reset": str(reset)})

        with mock.patch("requests.get", get):
            with self.assertRaises(updater.UpdateError) as caught:
                updater.fetch_latest_release()

        msg = str(caught.exception)
        self.assertIn("rate-limiting", msg)
        self.assertIn(time.strftime("%H:%M", time.localtime(reset)), msg,
                      "a limit the user can wait out should say until when")
        self.assertIn("network address", msg,
                      "it is shared per network, which is why it can happen "
                      "to someone who did nothing")

    def test_it_does_not_keep_asking_while_limited(self):
        reset = int(time.time()) + 1800
        calls = []

        def get(url, *a, **k):
            calls.append(url)
            return _Resp(status=403, headers={"X-RateLimit-Remaining": "0",
                                              "X-RateLimit-Reset": str(reset)})

        with mock.patch("requests.get", get):
            for _ in range(5):
                with self.assertRaises(updater.UpdateError):
                    updater.fetch_latest_release()
        self.assertEqual(len(calls), 1,
                         "spending a request to be told again that there are "
                         "none left makes it worse")

    def test_a_limit_does_not_hide_a_result_already_known(self):
        def ok(url, *a, **k):
            return _Resp(headers={"ETag": '"abc"'})

        def limited(url, *a, **k):
            return _Resp(status=429, headers={"X-RateLimit-Remaining": "0"})

        with mock.patch("requests.get", ok):
            known = updater.fetch_latest_release()
        updater._RELEASE_CACHE["at"] = 0.0
        with mock.patch("requests.get", limited):
            still = updater.fetch_latest_release()
        self.assertEqual(known, still,
                         "the last known release is more use than an error")

    def test_a_network_failure_falls_back_to_what_is_known(self):
        with mock.patch("requests.get", lambda *a, **k: _Resp(headers={})):
            known = updater.fetch_latest_release()
        updater._RELEASE_CACHE["at"] = 0.0

        def dead(*a, **k):
            raise OSError("getaddrinfo failed")

        with mock.patch("requests.get", dead):
            self.assertEqual(updater.fetch_latest_release(), known)

class BlockedApiTests(unittest.TestCase):
    """git works, api.github.com does not - and the check has to survive that.

    Reported by the user, about his work machine: "I wasn't using the updater at
    work because it was messing up and giving me time out error messages and it
    was just faster for me to go to my open terminal window hit the up arrow one
    time... and then just pull it down."

    Both halves of that are the finding. `git pull` from his terminal worked, so
    github.com over git was fine; the in-app check reached for api.github.com
    for every install, which a corporate network will commonly block or
    throttle while leaving git alone. A minute of waiting, then a timeout, on a
    machine perfectly able to update itself.
    """

    def setUp(self):
        from server import app
        self.client = app.test_client()

    def _status(self):
        return json.loads(self.client.get("/api/update/status").data)

    def test_a_git_install_answers_with_the_api_unreachable(self):
        blew_up = []

        def dead_api(*a, **kw):
            blew_up.append(kw.get("timeout"))
            raise updater.UpdateError("Could not reach GitHub: timed out")

        with patch.object(updater, "detect_install", return_value={
                    "isGitInstall": True, "currentVersion": "2.5.0",
                    "releasesUrl": "https://github.com/o/r/releases",
                    "method": "git"}), \
             patch.object(updater, "remote_release_tag", return_value="v2.9.0"), \
             patch.object(updater, "fetch_latest_release", side_effect=dead_api):
            out = self._status()

        self.assertTrue(out["updateAvailable"],
                        "git knew there was a newer release; the API was not needed")
        self.assertEqual(out["latest"]["version"], "2.9.0")
        self.assertEqual(out["latestSource"], "git")
        self.assertIn("notesError", out, "and it says why the notes are missing")
        self.assertEqual(blew_up, [updater.NOTES_TIMEOUT],
                         "the optional call gets the short wait, not the full minute")

    def test_being_up_to_date_is_decided_by_git_too(self):
        with patch.object(updater, "detect_install", return_value={
                    "isGitInstall": True, "currentVersion": "2.9.0",
                    "releasesUrl": "https://github.com/o/r/releases",
                    "method": "git"}), \
             patch.object(updater, "remote_release_tag", return_value="v2.9.0"), \
             patch.object(updater, "fetch_latest_release",
                          side_effect=updater.UpdateError("blocked")):
            out = self._status()
        self.assertFalse(out["updateAvailable"])
        self.assertEqual(out["latest"]["tag"], "v2.9.0")

    def test_the_notes_are_used_when_the_api_does_answer(self):
        with patch.object(updater, "detect_install", return_value={
                    "isGitInstall": True, "currentVersion": "2.5.0",
                    "releasesUrl": "https://github.com/o/r/releases",
                    "method": "git"}), \
             patch.object(updater, "remote_release_tag", return_value="v2.9.0"), \
             patch.object(updater, "fetch_latest_release", return_value={
                    "tag": "v2.9.0", "version": "2.9.0", "notes": "what changed",
                    "url": "https://github.com/o/r/releases/tag/v2.9.0",
                    "assets": {}}):
            out = self._status()
        self.assertEqual(out["latest"]["notes"], "what changed")
        self.assertEqual(out["latestSource"], "git")

    def test_notes_from_a_different_tag_are_not_pinned_to_this_one(self):
        """The API's idea of latest can lag its own tags. Git said v2.9.0, so
        notes for something else do not belong on it."""
        with patch.object(updater, "detect_install", return_value={
                    "isGitInstall": True, "currentVersion": "2.5.0",
                    "releasesUrl": "https://github.com/o/r/releases",
                    "method": "git"}), \
             patch.object(updater, "remote_release_tag", return_value="v2.9.0"), \
             patch.object(updater, "fetch_latest_release", return_value={
                    "tag": "v2.8.0", "version": "2.8.0", "notes": "older notes",
                    "url": "https://github.com/o/r/releases/tag/v2.8.0",
                    "assets": {}}):
            out = self._status()
        self.assertEqual(out["latest"]["tag"], "v2.9.0")
        self.assertEqual(out["latest"]["notes"], "")

    def test_a_zip_install_still_uses_the_api(self):
        """It has no remote to ask, so nothing changes for it."""
        asked = []
        with patch.object(updater, "detect_install", return_value={
                    "isGitInstall": False, "currentVersion": "2.5.0",
                    "releasesUrl": "https://github.com/o/r/releases",
                    "method": "zip"}), \
             patch.object(updater, "remote_release_tag",
                          side_effect=AssertionError("must not ask git")), \
             patch.object(updater, "fetch_latest_release", side_effect=lambda *a, **k: (
                    asked.append(True) or {"tag": "v2.9.0", "version": "2.9.0",
                                           "notes": "n", "url": "u", "assets": {}})):
            out = self._status()
        self.assertEqual(out["latestSource"], "api")
        self.assertTrue(out["updateAvailable"])
        self.assertTrue(asked)

    def test_git_failing_falls_back_to_the_api(self):
        with patch.object(updater, "detect_install", return_value={
                    "isGitInstall": True, "currentVersion": "2.5.0",
                    "releasesUrl": "https://github.com/o/r/releases",
                    "method": "git"}), \
             patch.object(updater, "remote_release_tag", return_value=None), \
             patch.object(updater, "fetch_latest_release", return_value={
                    "tag": "v2.9.0", "version": "2.9.0", "notes": "n",
                    "url": "u", "assets": {}}):
            out = self._status()
        self.assertEqual(out["latestSource"], "api")
        self.assertTrue(out["updateAvailable"])

    def test_both_failing_still_reports_the_install(self):
        with patch.object(updater, "detect_install", return_value={
                    "isGitInstall": True, "currentVersion": "2.5.0",
                    "releasesUrl": "https://github.com/o/r/releases",
                    "method": "git"}), \
             patch.object(updater, "remote_release_tag", return_value=None), \
             patch.object(updater, "fetch_latest_release",
                          side_effect=updater.UpdateError("Could not reach GitHub")):
            out = self._status()
        self.assertIsNone(out["latest"])
        self.assertIn("latestError", out)
        self.assertEqual(out["install"]["currentVersion"], "2.5.0",
                         "the install facts are still useful with no network")


class NoInteractivePromptTests(unittest.TestCase):
    """Nothing here runs on a terminal, so git must never wait for one.

    A git subprocess that asks for a username hangs until the timeout, and on
    Windows the credential manager can raise a dialog - on a desktop nobody is
    sitting at, since these sessions are driven remotely.
    """

    def test_every_git_call_refuses_to_prompt(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen.update(kw.get("env") or {})
            return mock.Mock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            updater._run_git(["status", "--porcelain"], Path("."))

        self.assertEqual(seen.get("GIT_TERMINAL_PROMPT"), "0")
        self.assertEqual(seen.get("GCM_INTERACTIVE"), "never")
        self.assertIn("GIT_ASKPASS", seen)
        self.assertIn("PATH", seen, "and it still inherits the real environment")

    def test_a_local_command_is_not_blamed_on_the_network(self):
        import subprocess as sp
        with patch("subprocess.run",
                   side_effect=sp.TimeoutExpired(cmd="git", timeout=20)):
            with self.assertRaises(updater.UpdateError) as caught:
                updater._run_git(["status", "--porcelain"], Path("."))
        msg = str(caught.exception)
        self.assertIn("status", msg, "it names the command that stalled")
        self.assertIn("does not use the network", msg)
        self.assertNotIn("proxy", msg)

    def test_a_network_command_says_so_and_says_what_to_try(self):
        import subprocess as sp
        with patch("subprocess.run",
                   side_effect=sp.TimeoutExpired(cmd="git", timeout=120)):
            with self.assertRaises(updater.UpdateError) as caught:
                updater._run_git(["fetch", "--tags", "origin"], Path("."))
        msg = str(caught.exception)
        self.assertIn("fetch", msg)
        self.assertIn("proxy", msg)
        self.assertIn("terminal", msg, "which is what actually worked for him")

    def test_local_commands_do_not_wait_two_minutes(self):
        """A `git status` that needs longer than this is not slow, it is stuck."""
        self.assertLessEqual(updater.LOCAL_GIT_TIMEOUT, 30)
        self.assertLess(updater.LOCAL_GIT_TIMEOUT, updater.GIT_TIMEOUT)


class RemoteTagTests(unittest.TestCase):
    """Reading the newest release tag straight off the remote."""

    def _with_output(self, out, code=0):
        proc = mock.Mock(returncode=code, stdout=out, stderr="")
        return patch.object(updater, "_run_git", return_value=proc)

    def test_it_picks_the_newest_by_version_not_by_order(self):
        with self._with_output(
                "aaa\trefs/tags/v2.10.0\n"
                "bbb\trefs/tags/v2.9.0\n"
                "ccc\trefs/tags/v2.98.0\n"
                "ddd\trefs/tags/v2.100.0\n"):
            self.assertEqual(updater.remote_release_tag(Path(".")), "v2.100.0")

    def test_it_ignores_anything_that_is_not_a_release_tag(self):
        with self._with_output(
                "aaa\trefs/tags/v2.9.0\n"
                "bbb\trefs/tags/nightly\n"
                "ccc\trefs/tags/v3.0.0-rc1\n"
                "ddd\trefs/tags/release-2020\n"):
            self.assertEqual(updater.remote_release_tag(Path(".")), "v2.9.0")

    def test_no_tags_is_not_an_answer(self):
        with self._with_output(""):
            self.assertIsNone(updater.remote_release_tag(Path(".")))

    def test_a_failed_command_returns_none_rather_than_raising(self):
        """It is an optimisation - the API is still there to fall back on."""
        with self._with_output("", code=128):
            self.assertIsNone(updater.remote_release_tag(Path(".")))
        with patch.object(updater, "_run_git",
                          side_effect=updater.UpdateError("timed out")):
            self.assertIsNone(updater.remote_release_tag(Path(".")))

    def test_it_does_not_wait_as_long_as_a_fetch(self):
        """Someone is watching a panel that has not opened yet."""
        self.assertLess(updater.GIT_LS_REMOTE_TIMEOUT, updater.GIT_TIMEOUT)
        captured = {}

        def spy(args, cwd, check=True, timeout=None):
            captured["timeout"] = timeout
            return mock.Mock(returncode=0, stdout="", stderr="")

        with patch.object(updater, "_run_git", side_effect=spy):
            updater.remote_release_tag(Path("."))
        self.assertEqual(captured["timeout"], updater.GIT_LS_REMOTE_TIMEOUT)


class ClientChecksThroughTheServerTests(unittest.TestCase):
    """The browser must not call api.github.com itself.

    It used to, with no timeout on the request at all, so on a network that
    blocks api.github.com the About panel hung and then reported that GitHub
    could not be reached - on a machine where git worked perfectly. The server
    can answer the same question from git, so the page asks the server.
    """

    SHARED = Path(__file__).resolve().parent.parent / "web" / "assets" / "js" / "wd-shared.js"

    def setUp(self):
        self.src = self.SHARED.read_text(encoding="utf-8")

    def test_the_update_check_calls_our_own_endpoint(self):
        self.assertIn("fetch('/api/update/status'", self.src)

    def test_nothing_fetches_the_github_api_directly(self):
        """The constant may survive as documentation; a call to it may not."""
        self.assertNotIn("fetch(WD_API_LATEST", self.src)
        for line in self.src.splitlines():
            if "fetch(" in line and "api.github.com" in line:
                self.fail("the browser is calling GitHub directly: " + line.strip())

    def test_it_still_tells_a_rate_limit_apart_from_a_dead_network(self):
        """"Not a problem with your install" is only true for one of them."""
        self.assertIn("ratelimit", self.src)
        self.assertIn("rate.?limit", self.src)


if __name__ == "__main__":
    unittest.main()
