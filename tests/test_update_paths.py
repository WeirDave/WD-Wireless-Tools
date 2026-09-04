"""End-to-end upgrade harness for the update mechanism.

Every scenario here builds a throwaway install in a temp directory and updates
it against a local fixture remote — never GitHub and never the real install —
then asserts two things: the git state the install ends in, and what the user
would have been shown.

It exists because the update path had a bug that no unit test could see. The
launcher ran a bare ``git pull`` while every install path deliberately leaves
HEAD detached at a release tag, so from the first update onward every launch
printed git's own "You are not currently on a branch. See git-pull(1) for
details." The pieces were each correct; the combination was not. Only running a
real install through a real upgrade shows that.

Run it on its own with:

    python -m unittest tests.test_update_paths -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import updater
from tools.updater import AppConfig, UpdateError

ROOT = Path(__file__).resolve().parent.parent
HAVE_GIT = shutil.which("git") is not None

# Committing needs an identity, and the machine running this may not have one.
GIT_ID = ["-c", "user.email=harness@example.invalid", "-c", "user.name=Harness"]


def git(args, cwd: Path, check=True):
    proc = subprocess.run(["git"] + args, cwd=str(cwd),
                          capture_output=True, text=True, timeout=60)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed in {cwd}:\n{proc.stderr}")
    return proc


def head_state(root: Path) -> dict:
    """How the install's HEAD actually sits — the thing the bug was about."""
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], root, check=False).stdout.strip()
    tag = git(["describe", "--tags", "--exact-match"], root, check=False).stdout.strip()
    commit = git(["rev-parse", "HEAD"], root, check=False).stdout.strip()
    upstream = git(["rev-parse", "--abbrev-ref", "@{u}"], root, check=False)
    return {
        "detached": branch == "HEAD",
        "branch": None if branch == "HEAD" else branch,
        "tag": tag or None,
        "commit": commit,
        "has_upstream": upstream.returncode == 0,
    }


class _Fixture:
    """A fake WD-Wireless-Tools remote with a release history.

    Shaped like the real thing where the updater looks: versions.json, the
    payload files and directories, and vN.N.N tags on a main branch.
    """

    def __init__(self, base: Path, versions=("2.28.0", "2.29.0", "2.30.0")):
        self.base = base
        self.origin = base / "origin.git"
        self.work = base / "seed"
        self.versions = list(versions)
        self._build()

    def _write_tree(self, root: Path, version: str):
        (root / "web" / "assets").mkdir(parents=True, exist_ok=True)
        (root / "web" / "assets" / "versions.json").write_text(
            json.dumps({"suite": version, "walls": "7.0", "report": "2.0"}, indent=2),
            encoding="utf-8")
        for d in ("tools", "templates", "docs", "tests", "scripts", ".github"):
            (root / d).mkdir(parents=True, exist_ok=True)
            (root / d / "placeholder.txt").write_text(version, encoding="utf-8")
        for f in ("server.py", "requirements.txt", "LICENSE", "README.md",
                  "install.ps1", "install.sh"):
            (root / f).write_text(f"# {version}\n", encoding="utf-8")
        (root / "Start WD Wireless Tools.bat").write_text(
            "@echo off\r\nREM no git pull here\r\npython server.py\r\n", encoding="utf-8")
        (root / "Start WD Wireless Tools.command").write_text(
            "#!/bin/bash\n# no git pull here\npython3 server.py\n", encoding="utf-8")
        (root / "templates" / "WD Template_walltemplate.json").write_text(
            json.dumps({"name": "WD Template", "version": version}), encoding="utf-8")

    def _build(self):
        self.origin.mkdir(parents=True)
        git(["init", "--bare", "--initial-branch=main"], self.origin)
        self.work.mkdir(parents=True)
        git(["init", "--initial-branch=main"], self.work)
        for v in self.versions:
            self._write_tree(self.work, v)
            git(["add", "-A"], self.work)
            git(GIT_ID + ["commit", "-m", f"v{v}"], self.work)
            git(["tag", f"v{v}"], self.work)
        git(["remote", "add", "origin", str(self.origin)], self.work)
        git(["push", "--quiet", "origin", "main", "--tags"], self.work)

    def add_release(self, version: str):
        """Publish a newer release, as GitHub would between two updates."""
        self._write_tree(self.work, version)
        git(["add", "-A"], self.work)
        git(GIT_ID + ["commit", "-m", f"v{version}"], self.work)
        git(["tag", f"v{version}"], self.work)
        git(["push", "--quiet", "origin", "main", "--tags"], self.work)
        self.versions.append(version)

    # -- the two ways a user ends up with an install --------------------
    def zip_install(self, target: Path, version: str) -> Path:
        """A ZIP install: the payload on disk with no .git at all."""
        src = self.base / f"_zip-{version}"
        if src.exists():
            shutil.rmtree(src)
        src.mkdir(parents=True)
        self._write_tree(src, version)
        shutil.copytree(src, target)
        return target

    def git_install(self, target: Path, version: str | None = None) -> Path:
        """A git install, exactly as install.ps1 makes one: clone, then check
        out the release tag, which leaves HEAD detached."""
        git(["clone", "--quiet", str(self.origin), str(target)], self.base)
        git(["fetch", "--tags", "--prune", "origin"], target)
        ref = f"v{version or self.versions[-1]}"
        git(["-c", "advice.detachedHead=false", "checkout", "--force", ref], target)
        return target

    def config(self, install_root: Path | None = None) -> AppConfig:
        """An AppConfig pointed at the fixture rather than the real repo.

        `clone_url` is derived from `repo` on the real config, so the harness
        overrides it to the local bare repo — nothing here may touch GitHub.
        """
        origin = str(self.origin)

        class _FixtureConfig(AppConfig):
            @property
            def clone_url(self) -> str:
                return origin

        return _FixtureConfig(
            name="Harness",
            repo="example/harness",
            install_root=install_root or (self.base / "unused"),
            version_path="web/assets/versions.json",
            version_key="suite",
            asset_template="Harness-{version}.zip",
            payload_files=("server.py", "requirements.txt", "LICENSE", "README.md",
                           "install.ps1", "install.sh",
                           "Start WD Wireless Tools.bat",
                           "Start WD Wireless Tools.command"),
            payload_dirs=("tools", "web", "templates", "docs"),
            user_data_dir=self.base / "userdata",
            rescuable_globs=("templates/*_walltemplate.json",),
        )


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class UpdatePathTests(unittest.TestCase):
    """Each test is one route a real install can take through the updater."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.fx = _Fixture(self.base)
        self.cfg = self.fx.config()
        self.said = []

    def say(self, msg):
        self.said.append(str(msg))

    def transcript(self):
        return "\n".join(self.said)

    def assertNoRawGit(self, text):
        """Nothing git says to a developer should reach an installer."""
        for phrase in ("git-pull(1)", "fatal:", "error:", "usage: git",
                       "not currently on a branch",
                       "Please specify which branch"):
            self.assertNotIn(phrase, text,
                             f"raw git text surfaced to the user:\n{text}")

    def version_of(self, root: Path):
        return updater.local_version(root, self.cfg)

    # ---------------------------------------------------------- scenarios
    def test_fresh_git_install_then_update(self):
        root = self.fx.git_install(self.base / "git-install", "2.28.0")
        self.assertEqual(self.version_of(root), "2.28.0")
        res = updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertTrue(res["ok"])
        self.assertEqual(res["newVersion"], "2.30.0")
        st = head_state(root)
        self.assertTrue(st["detached"], "installs are pinned to a release tag")
        self.assertEqual(st["tag"], "v2.30.0")
        self.assertNoRawGit(self.transcript())

    def test_update_when_already_newest_changes_nothing(self):
        root = self.fx.git_install(self.base / "newest", "2.30.0")
        before = head_state(root)
        res = updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertFalse(res["changed"])
        self.assertEqual(head_state(root)["commit"], before["commit"])
        self.assertIn("newest", self.transcript().lower())
        self.assertNoRawGit(self.transcript())

    def test_second_update_after_a_new_release_lands(self):
        """The path that produced the reported bug: update, then update again."""
        root = self.fx.git_install(self.base / "twice", "2.28.0")
        updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertEqual(self.version_of(root), "2.30.0")
        self.fx.add_release("2.31.0")
        res = updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertEqual(res["newVersion"], "2.31.0")
        self.assertEqual(head_state(root)["tag"], "v2.31.0")
        self.assertNoRawGit(self.transcript())

    def test_zip_install_converted_to_git_then_updated_twice(self):
        """ZIP -> convert -> update -> update. Conversion pins to the installed
        version deliberately, so the first update is what moves it forward."""
        root = self.fx.zip_install(self.base / "converted", "2.28.0")
        self.assertFalse(updater.is_git_install(root, self.cfg))

        conv = updater.convert_to_git(root, log=self.say, cfg=self.cfg)
        self.assertTrue(conv["ok"])
        self.assertEqual(conv["newVersion"], "2.28.0", "convert must not also upgrade")
        self.assertEqual(head_state(root)["tag"], "v2.28.0")

        first = updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertEqual(first["newVersion"], "2.30.0")

        self.fx.add_release("2.31.0")
        second = updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertEqual(second["newVersion"], "2.31.0")
        self.assertEqual(head_state(root)["tag"], "v2.31.0")
        self.assertNoRawGit(self.transcript())

    def test_install_already_detached_updates_cleanly(self):
        """Every install in the wild is in this state. It must not need a fix."""
        root = self.fx.git_install(self.base / "detached", "2.28.0")
        self.assertTrue(head_state(root)["detached"])
        res = updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertEqual(res["newVersion"], "2.30.0")
        self.assertNoRawGit(self.transcript())

    def test_install_left_on_a_branch_still_updates(self):
        """Someone who cloned by hand sits on main with an upstream. The update
        must move them to the release tag rather than refusing."""
        root = self.base / "on-branch"
        git(["clone", "--quiet", str(self.fx.origin), str(root)], self.base)
        git(["-c", "advice.detachedHead=false", "checkout", "--force", "v2.28.0"], root)
        git(["checkout", "-B", "main", "origin/main"], root)
        git(["reset", "--hard", "v2.28.0"], root)
        self.assertFalse(head_state(root)["detached"])
        res = updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertEqual(res["newVersion"], "2.30.0")
        self.assertEqual(head_state(root)["tag"], "v2.30.0")
        self.assertNoRawGit(self.transcript())

    def test_dirty_tracked_file_is_refused_in_plain_language(self):
        root = self.fx.git_install(self.base / "dirty", "2.28.0")
        (root / "server.py").write_text("# edited by hand\n", encoding="utf-8")
        with self.assertRaises(UpdateError) as cm:
            updater.git_update(root, log=self.say, cfg=self.cfg)
        msg = str(cm.exception)
        self.assertIn("server.py", msg)
        self.assertNoRawGit(msg)
        # and nothing moved
        self.assertEqual(self.version_of(root), "2.28.0")

    def test_untracked_file_does_not_block_an_update(self):
        root = self.fx.git_install(self.base / "untracked", "2.28.0")
        (root / "site survey.esx").write_text("not ours", encoding="utf-8")
        res = updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertEqual(res["newVersion"], "2.30.0")
        self.assertTrue((root / "site survey.esx").exists(),
                        "an update must not delete the user's own files")

    def test_customized_template_is_rescued_rather_than_blocking(self):
        root = self.fx.git_install(self.base / "tpl", "2.28.0")
        tpl = root / "templates" / "WD Template_walltemplate.json"
        tpl.write_text(json.dumps({"name": "WD Template", "mine": True}), encoding="utf-8")
        with patch("tools.template_store.rescue_dirty_builtin",
                   return_value={"ok": True, "rescued": True}) as resc:
            res = updater.git_update(root, log=self.say, cfg=self.cfg)
        resc.assert_called()
        self.assertEqual(res["newVersion"], "2.30.0")
        self.assertIn("WD Template_walltemplate.json", res["rescuedTemplates"])

    def test_no_network_reports_plainly_and_changes_nothing(self):
        root = self.fx.git_install(self.base / "offline", "2.28.0")
        git(["remote", "set-url", "origin",
             "https://nonexistent.invalid/whatever.git"], root)
        before = head_state(root)["commit"]
        with self.assertRaises(UpdateError) as cm:
            updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertNoRawGit(str(cm.exception))
        self.assertEqual(head_state(root)["commit"], before)

    def test_missing_git_is_reported_not_crashed(self):
        root = self.fx.git_install(self.base / "nogit", "2.28.0")
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            with self.assertRaises(UpdateError) as cm:
                updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertIn("Git is not installed", str(cm.exception))

    def test_missing_origin_is_repaired_rather_than_failing(self):
        root = self.fx.git_install(self.base / "noremote", "2.28.0")
        git(["remote", "remove", "origin"], root)
        res = updater.git_update(root, log=self.say, cfg=self.cfg)
        self.assertEqual(res["newVersion"], "2.30.0")

    def test_zip_install_is_not_mistaken_for_a_git_install(self):
        root = self.fx.zip_install(self.base / "plainzip", "2.29.0")
        self.assertFalse(updater.is_git_install(root, self.cfg))
        with self.assertRaises(UpdateError):
            updater.git_update(root, log=self.say, cfg=self.cfg)

    # ------------------------------------------------- the shipped launcher
    def test_shipped_launchers_do_not_run_git_pull(self):
        """The actual bug. A launcher that pulls fights the tag-pinned model
        and prints git's own error on every start."""
        for name in ("Start WD Wireless Tools.bat", "Start WD Wireless Tools.command"):
            with self.subTest(launcher=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                stripped = "\n".join(
                    ln for ln in text.splitlines()
                    if not ln.strip().startswith(("REM", "#"))
                )
                self.assertNotIn("git pull", stripped)

    def test_a_detached_install_would_have_failed_a_bare_git_pull(self):
        """Proves the diagnosis rather than assuming it: on the state every
        install is left in, `git pull` is exactly what produced the message the
        user saw."""
        root = self.fx.git_install(self.base / "provebug", "2.28.0")
        self.assertTrue(head_state(root)["detached"])
        proc = git(["pull"], root, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not currently on a branch",
                      (proc.stderr + proc.stdout).lower())


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class UpdateMessageTests(unittest.TestCase):
    """What the user is shown when git fails, independent of the scenario."""

    def test_every_known_failure_has_plain_wording(self):
        class P:
            def __init__(self, err):
                self.stderr, self.stdout = err, ""
        cases = {
            "fatal: You are not currently on a branch.": "release",
            "fatal: could not resolve host: github.com": "network",
            "error: Your local changes would be overwritten by checkout": "edited",
            "fatal: Unable to create '/x/.git/index.lock': File exists": "running",
            "fatal: not a git repository": "git install",
        }
        for err, expect in cases.items():
            with self.subTest(err=err):
                msg = updater._friendly_git_error(["checkout"], P(err))
                self.assertNotIn("fatal:", msg)
                self.assertNotIn("git-pull(1)", msg)
                self.assertIn(expect, msg.lower())

    def test_an_unknown_failure_still_reads_as_a_sentence(self):
        class P:
            stderr = "fatal: something nobody predicted"
            stdout = ""
        msg = updater._friendly_git_error(["checkout"], P())
        self.assertNotIn("fatal:", msg)
        self.assertTrue(msg.endswith("."))
        self.assertIn("Copy Diagnostics", msg)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
