from __future__ import annotations

import json
import re
import shutil
import subprocess
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


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class AboutPanelFreshnessTests(unittest.TestCase):
    """Opening About is the act of asking, so it has to actually ask.

    Reported: "I refreshed on the page and there wasn't an update available or
    didn't say anything so then I went into about and then when I went to about
    it said I had the latest version but I clicked the button anyway and then it
    told me that there was a new release... when you bring up the about... it
    should literally look for the latest release at that point without hitting
    the button."

    Two causes, both here. Opening the panel rendered a cached answer and never
    checked, and that cache was good for twenty-four hours - so the panel said
    "you have the latest version" on the strength of something it had been told
    the day before, and a release had landed since.
    """

    SHARED = Path(__file__).resolve().parent.parent / "web" / "assets" / "js" / "wd-shared.js"

    HARNESS = r"""
    const fs = require('fs');
    const src = fs.readFileSync(process.argv[1], 'utf8');
    function slice(a, b) {
      const i = src.indexOf(a), j = src.indexOf(b, i);
      if (i < 0 || j < 0) throw new Error('missing ' + a);
      return src.slice(i, j);
    }
    const store = {};
    globalThis.localStorage = {
      getItem: k => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: k => { delete store[k]; }
    };
    eval(slice('  var WD_UPDATE_CACHE_KEY', '  function _cmpVer'));
    const HOUR = 60 * 60 * 1000;
    """

    def run_js(self, script):
        proc = subprocess.run(["node", "-e", self.HARNESS + script, str(self.SHARED)],
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node failed: " + proc.stderr)
        return json.loads(proc.stdout)

    def test_a_days_old_answer_is_no_longer_treated_as_current(self):
        out = self.run_js("""
          _writeUpdateCache({ checkedAt: Date.now() - 24 * HOUR,
                              latestVersion: '2.9.0', isNewer: false });
          console.log(JSON.stringify({ kept: !!_readUpdateCache() }));
        """)
        self.assertFalse(out["kept"])

    def test_a_check_from_two_hours_ago_is_stale_too(self):
        """His laptop had been open for days; an hour is the new budget."""
        out = self.run_js("""
          _writeUpdateCache({ checkedAt: Date.now() - 2 * HOUR,
                              latestVersion: '2.9.0', isNewer: false });
          console.log(JSON.stringify({ kept: !!_readUpdateCache() }));
        """)
        self.assertFalse(out["kept"])

    def test_a_recent_answer_is_still_reused(self):
        """The point is freshness, not refusing to remember anything."""
        out = self.run_js("""
          _writeUpdateCache({ checkedAt: Date.now() - 5 * 60 * 1000,
                              latestVersion: '2.9.0', isNewer: false });
          const v = _readUpdateCache();
          console.log(JSON.stringify({ kept: !!v, version: v && v.latestVersion }));
        """)
        self.assertTrue(out["kept"])
        self.assertEqual(out["version"], "2.9.0")

    def test_the_background_budget_is_an_hour_not_a_day(self):
        out = self.run_js("""
          console.log(JSON.stringify({ ttl: WD_UPDATE_TTL_MS }));
        """)
        self.assertEqual(out["ttl"], 60 * 60 * 1000)

    def test_a_rate_limit_is_still_respected_while_it_lasts(self):
        """Checking more often must not mean ignoring GitHub saying stop."""
        out = self.run_js("""
          _writeUpdateCache({ checkedAt: Date.now(), error: true,
                              kind: 'ratelimit', resetAt: Date.now() + 10 * 60 * 1000 });
          const held = _readUpdateCache();
          _writeUpdateCache({ checkedAt: Date.now(), error: true,
                              kind: 'ratelimit', resetAt: Date.now() - 60 * 1000 });
          console.log(JSON.stringify({ held: !!held, expired: !!_readUpdateCache() }));
        """)
        self.assertTrue(out["held"], "a live rate limit is remembered")
        self.assertFalse(out["expired"], "and forgotten once it has passed")

    def test_opening_about_runs_a_real_check(self):
        src = self.SHARED.read_text(encoding="utf-8")
        body = src[src.index("WD.openAbout = function"):]
        body = body[:body.index("WD.closeAbout")]
        self.assertIn("WD.checkForUpdates({ force: true })", body,
                      "opening About must ask, not recite")

    def test_it_still_shows_what_it_knew_while_asking(self):
        """A panel that blanks itself for a second on every open is worse."""
        src = self.SHARED.read_text(encoding="utf-8")
        body = src[src.index("WD.openAbout = function"):]
        body = body[:body.index("WD.closeAbout")]
        self.assertLess(body.index("_readUpdateCache"),
                        body.index("WD.checkForUpdates"))


class TheDevCheckoutIsToldWhatToRunTests(unittest.TestCase):
    """The one install that had no way forward, and it is the maintainer's own.

    `detect_install()` on this repo returns method "dev", and that is correct:
    clicking Update on a maintainer's clone would check out a release tag over
    in-progress work and detach HEAD, so there deliberately is no button.

    What was missing is the other half. The panel said "This is a development
    checkout - update it with git so your work isn't checked out from under
    you." That names a tool, not a command. A git install gets a command and a
    Copy button; a ZIP install gets a command and a Copy button; this case got
    one sentence and a dead end - which is how the in-app updater lost the only
    person using it, who went back to running `git pull` by hand.

    Verified in Firefox against the real panel with the endpoint's reply
    rewritten to report a newer release: the dev case renders
    `git -C "<the install folder>" pull`, and clicking Copy puts exactly that
    on the clipboard.
    """

    SHARED = Path(__file__).resolve().parent.parent / "web" / "assets" / "js" / "wd-shared.js"

    def setUp(self):
        src = self.SHARED.read_text(encoding="utf-8")
        body = src[src.index("function showPrimary()"):]
        self.body = body[:body.index("function run(")]
        self.dev = self.body[self.body.index("if (info.method === 'dev')"):]
        self.dev = self.dev[:self.dev.index("if (info.method === 'manual')")]
        self.src = src

    def test_it_names_the_command_not_just_the_tool(self):
        self.assertIn("pull", self.dev)
        self.assertIn("wd-update-cmd", self.dev)

    def test_the_command_carries_the_folder_so_it_runs_from_anywhere(self):
        """He reads these sessions on a phone and runs the command later, in
        whatever shell is open. A bare `git pull` in the wrong directory
        either fails or updates something else."""
        self.assertIn("info.root", self.dev)
        self.assertIn("git -C", self.dev)

    def test_it_offers_the_same_copy_button_the_other_installs_get(self):
        self.assertIn("wd-update-copyBtn", self.dev)
        self.assertIn("wire();", self.dev)

    def test_there_is_still_no_update_button_on_a_dev_checkout(self):
        """The reason the case exists at all. An Update button here would
        detach HEAD over uncommitted work."""
        self.assertNotIn("wd-update-goBtn", self.dev)

    def test_it_says_what_would_happen_rather_than_only_that_it_will_not(self):
        self.assertIn("detach HEAD", self.dev)

    def test_copy_copies_the_command_beside_it(self):
        """There is more than one command in this panel now. A Copy button
        hardwired to the bootstrap line would hand over the wrong one while
        reading as the right one - which is this repo's usual failure, a
        control that looks correct and does something else."""
        wire = self.src[self.src.index("host.querySelectorAll('.wd-update-copyBtn')"):]
        wire = wire[:wire.index("\n    }")]
        self.assertIn("closest('.wd-update-cmdRow')", wire)
        self.assertIn("querySelector('.wd-update-cmd')", wire)
        self.assertIn("|| config.bootstrapCommand", wire,
                      "and still falls back to what it used to copy")


class DevPullTests(unittest.TestCase):
    """The one update a maintainer's clone can safely do to itself.

    `is_dev_checkout()` blocks `git_update` because that checks out a release
    *tag*, which on a working copy means a detached HEAD with your branch left
    behind. `dev_pull` moves the branch you are already on, and only forward,
    so the hazard the guard exists for is not reachable through it.

    Every refusal below was exercised against a real clone before being written
    down: a dirty tree (this repo's own, mid-session), a detached HEAD, and a
    branch carrying a commit that is not upstream. In all three the working
    copy was checked afterwards and nothing had moved.
    """

    def setUp(self):
        self.src = (Path(__file__).resolve().parent.parent
                    / "tools" / "updater.py").read_text(encoding="utf-8")
        body = self.src[self.src.index("def dev_pull("):]
        self.body = body[:body.index("def convert_to_git")]

    def test_it_never_checks_out_a_tag(self):
        """The whole difference between this and the blocked path.

        Asked of the git commands, not of the text: the word "checkout" is
        all over the prose here ("development checkout", and the advice to run
        `git checkout main`), and matching on that tests the comments."""
        calls = re.findall(r'_run_git\(\[([^\]]*)\]', self.body)
        verbs = [c.split(",")[0].strip().strip('"') for c in calls]
        self.assertNotIn("checkout", verbs)
        self.assertEqual(sorted(set(verbs)), ["pull", "rev-list", "rev-parse"])
        self.assertNotIn("_latest_release_tag", self.body)

    def test_the_pull_is_fast_forward_only(self):
        """Without --ff-only a divergent branch gets a merge commit nobody
        asked for, made by a button press."""
        self.assertIn('"pull", "--ff-only"', self.body)

    def test_it_refuses_a_dirty_tree_and_names_the_files(self):
        self.assertIn("_dirty_paths(root)", self.body)
        self.assertIn("uncommitted changes to", self.body)

    def test_it_refuses_a_detached_head(self):
        """There is no branch to move, and pulling would be meaningless."""
        self.assertIn('"rev-parse", "--abbrev-ref", "HEAD"', self.body)
        self.assertIn("detached HEAD", self.body)

    def test_a_branch_ahead_of_origin_is_explained_not_just_failed(self):
        """git's own failure here came back as "the update could not finish,
        try again" - true, useless, and trying again fails identically."""
        self.assertIn("origin/{branch}..HEAD", self.body)
        # The sentence is wrapped in the source, so the halves are asserted
        # separately; the assembled wording was read off a real clone that had
        # one unpushed commit, and then a second.
        self.assertIn("not on GitHub, so this cannot ", self.body)
        self.assertIn('"fast-forward.', self.body)
        self.assertIn("your work is safe", self.body)
        self.assertIn('"1 commit that is"', self.body)

    def test_whether_anything_arrived_is_measured_on_the_commit(self):
        """A pull of three documentation commits with no version bump reported
        "Already up to date", which reads as the button having done nothing."""
        self.assertIn("head_before != head_after", self.body)
        self.assertIn("rev-list", self.body)
        self.assertNotIn('changed": cmp_version', self.body)


class DevPullIsOptInOnlyTests(unittest.TestCase):
    """A bare "update me" on a working copy is still refused. Only the named
    mode gets through, so a future caller that forgets to pass one cannot
    detach HEAD over in-progress work."""

    def setUp(self):
        root = Path(__file__).resolve().parent.parent
        src = (root / "tools" / "updater.py").read_text(encoding="utf-8")
        block = src[src.index("def perform_update("):]
        sep = chr(10) * 3
        self.block = (block[:block.index(sep)]
                      if sep in block else block)
        self.server = (root / "server.py").read_text(encoding="utf-8")

    def test_the_guard_still_rejects_an_unqualified_update(self):
        self.assertIn('if info.get("isDevCheckout"):', self.block)
        self.assertIn("raise UpdateError", self.block)

    def test_only_the_named_mode_is_let_through(self):
        self.assertIn('if mode == "dev_pull":', self.block)
        guard_at = self.block.index('if info.get("isDevCheckout"):')
        mode_at = self.block.index('if mode == "dev_pull":')
        raise_at = self.block.index("raise UpdateError", guard_at)
        self.assertLess(mode_at, raise_at,
                        "the exception must be inside the guard, before it raises")

    def test_the_route_accepts_it(self):
        self.assertIn('"dev_pull"', self.server)
        self.assertIn('mode not in (None, "git", "zip", "convert", "dev_pull")',
                      self.server)


class DevPullButtonTests(unittest.TestCase):
    """The panel offers it, and asks for it by name."""

    SHARED = Path(__file__).resolve().parent.parent / "web" / "assets" / "js" / "wd-shared.js"

    def setUp(self):
        src = self.SHARED.read_text(encoding="utf-8")
        self.src = src
        body = src[src.index("if (info.method === 'dev')"):]
        self.dev = body[:body.index("if (info.method === 'manual')")]

    def test_there_is_a_button(self):
        self.assertIn("wd-update-pullBtn", self.dev)
        self.assertIn("Pull now", self.dev)

    def test_it_asks_for_the_mode_by_name(self):
        self.assertIn("run('dev_pull')", self.src)

    def test_it_is_still_not_the_ordinary_update_button(self):
        """wd-update-goBtn sends mode null, which perform_update refuses on a
        development checkout. It must not appear in this branch."""
        self.assertNotIn("wd-update-goBtn", self.dev)

    def test_it_says_what_it_will_and_will_not_do(self):
        self.assertIn("detach HEAD", self.dev)
        self.assertIn("uncommitted work", self.dev)

    def test_the_typed_command_is_still_offered(self):
        """A refusal has to leave somewhere to go."""
        self.assertIn("wd-update-cmd", self.dev)
        self.assertIn("wd-update-copyBtn", self.dev)

    def test_the_busy_state_names_what_is_happening(self):
        self.assertIn("'Pulling", self.src)


class ABranchCheckoutIsAskedADifferentQuestionTests(unittest.TestCase):
    """Why he refreshed the home page all night and was never offered anything.

    The release check asks "is there a tag newer than my versions.json". For
    anyone who tracks a branch that is permanently false, because the version
    bump is committed to the branch **before** the tag is pushed - so a pull
    always leaves versions.json equal to, or ahead of, the newest tag.

    Measured on his own install while investigating: versions.json said
    2.100.20 and the newest tag was v2.100.19. `cmp_version` therefore returned
    -1 and `updateAvailable` was false, and would have stayed false however
    many times he refreshed. The feature was not removed; it could not fire.

    `remote_branch_state()` asks the question that does apply: does the branch
    point at a commit this clone does not have.
    """

    SRC = Path(__file__).resolve().parent.parent / "tools" / "updater.py"
    SERVER = Path(__file__).resolve().parent.parent / "server.py"

    def setUp(self):
        self.src = self.SRC.read_text(encoding="utf-8")
        body = self.src[self.src.index("def remote_branch_state("):]
        self.body = body[:body.index("\ndef fetch_latest_release")]

    def test_being_up_to_date_costs_nothing_but_one_ls_remote(self):
        """This runs on every page load, and a fetch writes to the repository.

        Up to date is the common case and must stay read-only: ls-remote for
        the branch head, cat-file to ask whether the object store already has
        that commit, and an early return. The fetch exists only past that
        return, where it buys the exact number of commits - "4 commits behind"
        is a fact he can act on; "there are new commits" is a rumour."""
        calls = re.findall(r'_run_git\(\[([^\]]*)\]', self.body)
        verbs = [c.split(",")[0].strip().strip('"') for c in calls]
        self.assertIn("ls-remote", verbs)
        self.assertIn("cat-file", verbs)
        marker = "if head == sha:" + chr(10) + "            return state"
        early_return = self.body.index(marker)
        fetch_at = self.body.index('"fetch"')
        self.assertLess(early_return, fetch_at,
                        "the fetch must sit past the up-to-date return")

    def test_the_count_is_only_paid_for_when_behind(self):
        self.assertIn("if not have:", self.body)
        self.assertIn('"behindBy"', self.body)
        self.assertIn('"rev-list", "--count", "HEAD.." + sha', self.body)

    def test_the_docstring_does_not_still_claim_it_never_fetches(self):
        """It did, until the count was added. A comment that describes the
        previous design is worse than none."""
        doc = self.body[:self.body.index('"""', self.body.index('"""') + 3)]
        self.assertNotIn("Deliberately no fetch", doc)

    def test_behind_is_decided_by_counting_not_by_having_the_object(self):
        """Not academic: the fetch this makes brings the object in, so an
        object test would see it on the very next call and report up to date
        while the checkout was still four commits back - the banner appearing
        once and then vanishing. It also gets "ahead" right, so unpushed work
        of his own never reads as an update waiting."""
        self.assertIn('state["behind"] = n > 0', self.body)
        self.assertNotIn('"behind": not have', self.body)

    def test_a_detached_head_says_nothing(self):
        """That is what an ordinary release install looks like, and there the
        tag comparison is the right question."""
        self.assertIn('if not branch or branch == "HEAD":', self.body)
        self.assertIn("return None", self.body)

    def test_a_bad_sha_is_not_trusted(self):
        self.assertIn("re.fullmatch", self.body)

    def test_the_endpoint_offers_an_update_when_the_branch_moved(self):
        server = self.SERVER.read_text(encoding="utf-8")
        block = server[server.index("def api_update_status"):]
        block = block[:block.index("@app.route", 10)]
        self.assertIn("updater.remote_branch_state()", block)
        self.assertIn('or bool(branch and branch.get("behind"))', block)

    def test_the_tag_comparison_is_still_there_for_everyone_else(self):
        server = self.SERVER.read_text(encoding="utf-8")
        block = server[server.index("def api_update_status"):]
        block = block[:block.index("@app.route", 10)]
        self.assertIn("updater.cmp_version(version, current) > 0", block)


@unittest.skipUnless(updater.git_available(), "git is not installed")
class RemoteBranchStateAgainstRealClonesTests(unittest.TestCase):
    """Driven against real repositories rather than asserted about."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.origin = base / "origin"
        self.clone = base / "clone"
        self.origin.mkdir()
        _git(["init", "--bare", "--initial-branch=main"], self.origin)

        seed = base / "seed"
        _make_install(seed)
        _git(["init", "--initial-branch=main"], seed)
        _git(["add", "-A"], seed)
        _git(["-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "one"], seed)
        _git(["remote", "add", "origin", str(self.origin)], seed)
        _git(["push", "--quiet", "origin", "main"], seed)
        self.seed = seed
        _git(["clone", "--quiet", str(self.origin), str(self.clone)], base)

    def tearDown(self):
        self.temp.cleanup()

    def test_a_clone_level_with_its_branch_is_not_behind(self):
        state = updater.remote_branch_state(self.clone)
        self.assertIsNotNone(state)
        self.assertEqual(state["branch"], "main")
        self.assertFalse(state["behind"])

    def test_a_clone_whose_branch_moved_on_is_behind(self):
        """The case he is in every time a release ships."""
        (self.seed / "README.md").write_text("more", encoding="utf-8")
        _git(["add", "-A"], self.seed)
        _git(["-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "two"],
             self.seed)
        _git(["push", "--quiet", "origin", "main"], self.seed)

        state = updater.remote_branch_state(self.clone)
        self.assertTrue(state["behind"],
                        "the branch moved and the clone has not got the commit")

    def test_a_clone_that_is_ahead_is_not_reported_as_behind(self):
        """Unpushed work of his own is not an update waiting for him."""
        (self.clone / "README.md").write_text("mine", encoding="utf-8")
        _git(["add", "-A"], self.clone)
        _git(["-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "local"],
             self.clone)
        state = updater.remote_branch_state(self.clone)
        self.assertFalse(state["behind"])


    def test_asking_twice_still_says_behind(self):
        """The fetch this makes must not convince the next check it is current.

        The first version asked `cat-file -e` alone - "do I have this object" -
        and its own fetch brought the object in, so the second check saw it and
        reported up to date while the checkout was still four commits back. The
        banner appeared and then vanished on the next page load. Counting the
        commits between is the question that does not change underneath itself.
        """
        for i in range(3):
            (self.seed / "BACKLOG.md").write_text("later %d" % i, encoding="utf-8")
            _git(["add", "-A"], self.seed)
            _git(["-c", "user.email=t@t", "-c", "user.name=T",
                  "commit", "-m", "later %d" % i], self.seed)
        _git(["push", "--quiet", "origin", "main"], self.seed)

        first = updater.remote_branch_state(self.clone)
        second = updater.remote_branch_state(self.clone)
        self.assertTrue(first["behind"], "the first look must see it")
        self.assertTrue(second["behind"],
                        "and so must the second, after the fetch")
        self.assertEqual(first["behindBy"], 3)
        self.assertEqual(second["behindBy"], 3)

    def test_it_counts_the_commits(self):
        """"4 commits behind" is a fact he can act on. "There are new commits"
        is a rumour."""
        for i in range(4):
            (self.seed / "BACKLOG.md").write_text("n %d" % i, encoding="utf-8")
            _git(["add", "-A"], self.seed)
            _git(["-c", "user.email=t@t", "-c", "user.name=T",
                  "commit", "-m", "n %d" % i], self.seed)
        _git(["push", "--quiet", "origin", "main"], self.seed)
        self.assertEqual(updater.remote_branch_state(self.clone)["behindBy"], 4)

    def test_being_level_costs_no_fetch_and_reports_nothing(self):
        state = updater.remote_branch_state(self.clone)
        self.assertFalse(state["behind"])
        self.assertEqual(state["behindBy"], 0)

    def test_unpushed_work_of_his_own_is_not_an_update(self):
        (self.clone / "BACKLOG.md").write_text("mine", encoding="utf-8")
        _git(["add", "-A"], self.clone)
        _git(["-c", "user.email=t@t", "-c", "user.name=T",
              "commit", "-m", "local only"], self.clone)
        state = updater.remote_branch_state(self.clone)
        self.assertFalse(state["behind"])
        self.assertEqual(state["behindBy"], 0)

    def test_a_detached_checkout_returns_nothing(self):
        _git(["-c", "advice.detachedHead=false", "checkout", "HEAD"], self.clone)
        _git(["checkout", "--detach"], self.clone)
        self.assertIsNone(updater.remote_branch_state(self.clone))

    def test_a_tree_that_is_not_a_git_install_returns_nothing(self):
        plain = Path(self.temp.name) / "plain"
        _make_install(plain)
        self.assertIsNone(updater.remote_branch_state(plain))


class ACancelledCheckIsNotAFailedOneTests(unittest.TestCase):
    """The other half of why he saw nothing.

    The check starts on DOMContentLoaded and takes about 600ms. Navigating
    inside that window - a refresh, or clicking through to a tool, which every
    page in the suite does - rejects the fetch. That rejection was written to
    the cache as `kind: network`, and a cached error suppresses the check for
    thirty minutes, so every page load afterwards returned the stale error
    instead of asking. One mistimed click bought half an hour of silence.

    Measured at roughly one load in five before the guard, and zero of ten
    after it - then zero of six in each of Firefox, Chrome and Edge, because
    pagehide and beforeunload do not behave identically across engines.
    """

    SHARED = Path(__file__).resolve().parent.parent / "web" / "assets" / "js" / "wd-shared.js"

    def setUp(self):
        self.src = self.SHARED.read_text(encoding="utf-8")

    def test_leaving_the_page_is_recorded(self):
        self.assertIn("addEventListener('pagehide'", self.src)
        self.assertIn("addEventListener('beforeunload'", self.src)
        self.assertIn("_navigatingAway = true", self.src)

    def test_a_check_cut_off_by_navigation_is_not_cached(self):
        body = self.src[self.src.index("WD.checkForUpdates = function"):]
        body = body[:body.index("function _maybeShowUpdateBanner")]
        catch = body[body.index(".catch(function (err)"):]
        self.assertIn("if (_navigatingAway || _isAbortError(err))", catch)
        guard = catch.index("_navigatingAway")
        write = catch.index("_writeUpdateCache(errState)")
        self.assertLess(guard, write, "the guard must come before the write")

    def test_a_real_network_failure_is_still_reported(self):
        """Suppressing everything that looks like a cancelled request would
        also suppress the genuine one, and About would lose its ability to say
        GitHub was unreachable."""
        fn = self.src[self.src.index("function _isAbortError"):]
        fn = fn[:fn.index("\n  }") + 4]
        self.assertIn("err.name === 'AbortError'", fn)
        for over_broad in ("Failed to fetch", "NetworkError"):
            with self.subTest(pattern=over_broad):
                self.assertNotIn(over_broad, fn)

    def test_the_error_is_still_written_for_a_real_failure(self):
        body = self.src[self.src.index("WD.checkForUpdates = function"):]
        self.assertIn("_writeUpdateCache(errState)", body)
        self.assertIn("_renderUpdateError(errState)", body)


class TheBannerSaysSomethingTrueTests(unittest.TestCase):
    """"Update available: v2.100.19" to someone already running 2.100.20 is
    not an update, it is a contradiction - and he is exactly that person."""

    SHARED = Path(__file__).resolve().parent.parent / "web" / "assets" / "js" / "wd-shared.js"

    def setUp(self):
        src = self.SHARED.read_text(encoding="utf-8")
        self.src = src
        self.banner = src[src.index("function _renderUpdateBanner"):]
        self.banner = self.banner[:self.banner.index("function _removeUpdateBanner")]

    def test_a_branch_update_is_worded_as_one(self):
        self.assertIn("New commits on", self.banner)
        self.assertIn("behind the branch it follows", self.banner)

    def test_a_release_update_still_names_the_version(self):
        self.assertIn("Update available: v", self.banner)

    def test_dismissing_a_branch_update_keys_on_the_commit(self):
        """The version does not move between branch pushes, so keying the
        dismissal on it would mean one dismissal silenced the banner for
        good."""
        maybe = self.src[self.src.index("function _maybeShowUpdateBanner"):]
        maybe = maybe[:maybe.index("function _renderUpdateBanner")]
        self.assertIn("state.branch ? ('branch:' + state.branchAt)", maybe)
        self.assertIn("state.branch ? ('branch:' + state.branchAt)", self.banner)


if __name__ == "__main__":
    unittest.main()


class TheHostileCasesStayCalmTests(unittest.TestCase):
    """Every way git can refuse, asked of the thing the user actually sees.

    The update check shells out to git now, and a subprocess has more ways to
    go wrong than an HTTP call does. The bar is not that these are handled
    somewhere - it is that the status endpoint still answers, with a short
    reason, and that nothing raw from git reaches the page. A traceback on the
    home page is worse than no update check at all, because the check is an
    optimisation and the page is the whole product.

    `_run_git` converts every one of these into `UpdateError`, and both remote
    lookups swallow that and return None. These tests hold the conversion at
    both ends: the function returns None, and the request comes back 200.
    """

    def setUp(self):
        from server import app
        self.client = app.test_client()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".git").mkdir()

    def _status(self):
        res = self.client.get("/api/update/status")
        return res.status_code, json.loads(res.data)

    def _failing_git(self, exc=None, returncode=1, stderr=""):
        """subprocess.run replaced by one specific way of going wrong."""
        def run(*a, **kw):
            if exc is not None:
                raise exc
            return subprocess.CompletedProcess(a[0] if a else [], returncode,
                                               stdout="", stderr=stderr)
        return patch.object(updater.subprocess, "run", side_effect=run)

    # ------------------------------------------------------ the five cases --

    def test_git_is_not_on_the_path(self):
        with self._failing_git(exc=FileNotFoundError(2, "not found")):
            self.assertFalse(updater.git_available())
            self.assertIsNone(updater.remote_branch_state(self.tmp))
            self.assertIsNone(updater.remote_release_tag(self.tmp))

    def test_there_is_no_git_folder(self):
        bare = self.tmp / "nogit"
        bare.mkdir()
        self.assertFalse(updater.is_git_install(bare))
        self.assertIsNone(updater.remote_branch_state(bare))

    def test_the_network_is_unreachable(self):
        with self._failing_git(returncode=128, stderr=(
                "fatal: unable to access 'https://github.com/o/r/': "
                "Could not resolve host: github.com")):
            self.assertIsNone(updater.remote_branch_state(self.tmp))
            self.assertIsNone(updater.remote_release_tag(self.tmp))

    def test_the_remote_refuses_authentication(self):
        with self._failing_git(returncode=128, stderr=(
                "remote: Invalid username or password.\n"
                "fatal: Authentication failed for "
                "'https://github.com/o/r/'")):
            self.assertIsNone(updater.remote_branch_state(self.tmp))
            self.assertIsNone(updater.remote_release_tag(self.tmp))

    def test_a_subprocess_that_never_returns(self):
        with self._failing_git(
                exc=subprocess.TimeoutExpired(cmd="git ls-remote", timeout=30)):
            self.assertIsNone(updater.remote_branch_state(self.tmp))
            self.assertIsNone(updater.remote_release_tag(self.tmp))

    def test_git_is_present_but_cannot_be_executed(self):
        """OSError that is not FileNotFoundError - a blocked or unreadable git.

        This one escaped. `FileNotFoundError` had its own branch and every
        caller guards on `UpdateError`, so a `PermissionError` from a policy
        that blocks the binary went straight past both and out of the request.
        """
        with self._failing_git(exc=PermissionError(13, "Access is denied")):
            self.assertIsNone(updater.remote_branch_state(self.tmp))
            self.assertIsNone(updater.remote_release_tag(self.tmp))

    # ------------------------------------------- and the page still answers --

    def test_the_status_endpoint_survives_every_one_of_them(self):
        cases = {
            "git missing": FileNotFoundError(2, "not found"),
            "git unrunnable": PermissionError(13, "Access is denied"),
            "never returns": subprocess.TimeoutExpired(cmd="git", timeout=30),
            "some new OSError": OSError(99, "something nobody predicted"),
        }
        for name, exc in cases.items():
            with self.subTest(case=name):
                with self._failing_git(exc=exc), \
                     patch.object(updater, "detect_install", return_value={
                         "isGitInstall": True, "currentVersion": "2.5.0",
                         "releasesUrl": "https://github.com/o/r/releases",
                         "method": "git"}), \
                     patch.object(updater, "fetch_latest_release",
                                  side_effect=updater.UpdateError("no api")):
                    code, out = self._status()
                self.assertEqual(200, code, f"{name} took the endpoint down")
                self.assertFalse(out.get("updateAvailable"))
                self.assertTrue(out.get("trackingLabel"),
                                "the panel still has to say what it follows")

    def test_a_failure_message_never_carries_raw_git_output(self):
        """Whatever git printed, the user gets a sentence, not a transcript.

        Multi-line stderr on screen is the shape of the thing that gets
        reported as "there was an error and it is too long to type".
        """
        noisy = ("remote: Invalid username or password.\n"
                 "fatal: Authentication failed for 'https://github.com/o/r/'\n"
                 "hint: see https://example.invalid/auth for more\n")
        proc = subprocess.CompletedProcess(["git", "fetch"], 128,
                                           stdout="", stderr=noisy)
        message = updater._friendly_git_error(["fetch"], proc)
        self.assertNotIn("\n", message, "the message is one line")
        for fragment in ("remote:", "fatal:", "hint:", "Invalid username"):
            self.assertNotIn(fragment, message,
                             f"raw git output leaked: {fragment}")
