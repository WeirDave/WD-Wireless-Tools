from __future__ import annotations

import json
import tempfile
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


if __name__ == "__main__":
    unittest.main()
