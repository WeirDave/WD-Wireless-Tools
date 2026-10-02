"""The update does what the About panel offered, and says truthfully how it failed.

Two defects, both driven here against real repositories on disk - a bare
"remote" and a clone - with GitHub redirected to local paths through
`url.insteadOf` in a scratch global git config. Nothing leaves the machine.

* **A clone that follows a branch was offered "N new commits on main", and
  "Update now" did nothing.** The status check asks `remote_branch_state()`;
  the update asked `git_update(channel="release")`, which compares tags, and
  for a branch the newest tag is never newer than versions.json. The panel
  then said "Already up to date" with the clone still behind.

* **A failed "Switch to git updates" left a half-converted install.** `git
  init` and `remote add` ran before the fetch; when the fetch failed the
  empty `.git` stayed, the folder read as a git install, converting was
  refused from then on, and the next "Update now" jumped to the newest tag.
  The page also claimed "Nothing was left half-installed" on every failure.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import updater
from tests.test_updater import _make_install

ROOT = Path(__file__).resolve().parent.parent
WHO = ["-c", "user.email=tester@example.invalid", "-c", "user.name=Tester"]


def _git(args, cwd):
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def _set_version(root: Path, version: str):
    (root / "web" / "assets" / "versions.json").write_text(
        json.dumps({"suite": version}), encoding="utf-8")


@unittest.skipUnless(updater.git_available(), "git is not installed")
class _Repos(unittest.TestCase):
    """A seed repository, its bare remote, and a scratch global git config."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.gitconfig = self.base / "gitconfig"
        self.gitconfig.write_text("", encoding="utf-8")
        env = mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": str(self.gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1",
        })
        env.start()
        self.addCleanup(env.stop)
        # The settings dump before an update is not what is under test.
        dump = mock.patch.object(updater, "_dump_settings_first",
                                 return_value=None)
        dump.start()
        self.addCleanup(dump.stop)

        self.seed = self.base / "seed"
        _make_install(self.seed, "1.0.0")
        _git(["init", "-q", "-b", "main"], self.seed)
        self.commit("1.0.0")
        _git(["tag", "v1.0.0"], self.seed)
        self.remote = self.base / "remote.git"
        _git(["clone", "-q", "--bare", str(self.seed), str(self.remote)], self.base)
        _git(["remote", "add", "origin", str(self.remote)], self.seed)

    def tearDown(self):
        self.temp.cleanup()

    def commit(self, msg):
        _git(["add", "-A"], self.seed)
        _git([*WHO, "commit", "-q", "-m", msg], self.seed)

    def push(self):
        _git(["push", "-q", "--tags", "origin", "main"], self.seed)

    def cfg(self, root):
        return dataclasses.replace(updater.CONFIG, repo="Invented/Repo",
                                   install_root=root, rescuable_globs=())

    def head(self, root):
        return _git(["rev-parse", "HEAD"], root).strip()


class ABranchThatMovedIsPulledTests(_Repos):
    """The clone follows main; main gains commits that do not bump the version
    and are not tagged - the state every branch follower is in between
    releases."""

    def setUp(self):
        super().setUp()
        self.clone = self.base / "install"
        _git(["clone", "-q", str(self.remote), str(self.clone)], self.base)
        (self.seed / "notes.txt").write_text("a", encoding="utf-8")
        self.commit("fix a")
        (self.seed / "notes.txt").write_text("b", encoding="utf-8")
        self.commit("fix b")
        self.push()
        self.tip = self.head(self.seed)

    def test_update_now_moves_the_branch_to_the_remote_tip(self):
        cfg = self.cfg(self.clone)
        self.assertTrue(updater.remote_branch_state(cfg=cfg)["behind"])

        result = updater.perform_update(mode=None, cfg=cfg)

        self.assertTrue(result["changed"])
        self.assertEqual(self.head(self.clone), self.tip)
        self.assertFalse(updater.remote_branch_state(cfg=cfg)["behind"])
        # Still on the branch, not detached at a tag.
        self.assertEqual(
            _git(["rev-parse", "--abbrev-ref", "HEAD"], self.clone).strip(), "main")

    def test_the_panel_says_the_install_follows_the_branch(self):
        info = updater.detect_install(cfg=self.cfg(self.clone))
        self.assertEqual(info["method"], "git")
        self.assertEqual(info["ref"], "main")
        self.assertIn("main", info["reason"])

    def test_a_maintainers_clone_is_still_refused(self):
        """Edited tracked files make it a development checkout, and a bare
        update on one is refused exactly as before: nothing moves."""
        (self.clone / "server.py").write_text("work in progress", encoding="utf-8")
        cfg = self.cfg(self.clone)
        self.assertTrue(updater.is_dev_checkout(cfg=cfg))
        before = self.head(self.clone)

        with self.assertRaises(updater.UpdateError):
            updater.perform_update(mode=None, cfg=cfg)

        self.assertEqual(self.head(self.clone), before)
        self.assertEqual((self.clone / "server.py").read_bytes(), b"work in progress")


class AReleaseInstallStillMovesToTheNewestTagTests(_Repos):
    """A detached install at a tag is unchanged: the newest release, not a
    branch."""

    def test_a_detached_install_checks_out_the_newest_tag(self):
        clone = self.base / "install"
        _git(["clone", "-q", str(self.remote), str(clone)], self.base)
        _git(["-c", "advice.detachedHead=false", "checkout", "-q", "v1.0.0"], clone)
        _set_version(self.seed, "1.1.0")
        self.commit("1.1.0")
        _git(["tag", "v1.1.0"], self.seed)
        (self.seed / "notes.txt").write_text("after the tag", encoding="utf-8")
        self.commit("after the tag")
        self.push()

        result = updater.perform_update(mode=None, cfg=self.cfg(clone))

        self.assertEqual(result["target"], "v1.1.0")
        self.assertEqual(updater.local_version(clone), "1.1.0")
        self.assertFalse((clone / "notes.txt").exists())


class AFailedConversionIsUndoneTests(_Repos):

    def setUp(self):
        super().setUp()
        self.install = self.base / "install"
        _make_install(self.install, "1.0.0")
        self.cfg_ = self.cfg(self.install)

    def route_github_to(self, path: Path):
        self.gitconfig.write_text(
            f'[url "{path.as_posix()}"]\n\tinsteadOf = {self.cfg_.clone_url}\n',
            encoding="utf-8")

    def backups(self):
        return sorted(p for p in self.base.iterdir()
                      if p.name.startswith("install.previous-"))

    def test_a_fetch_that_fails_leaves_no_git_folder(self):
        self.route_github_to(self.base / "nowhere.git")

        with self.assertRaises(updater.UpdateError) as ctx:
            updater.convert_to_git(root=self.install, cfg=self.cfg_)

        self.assertFalse((self.install / ".git").exists())
        info = updater.detect_install(root=self.install, cfg=self.cfg_)
        self.assertEqual(info["method"], "zip")
        # The copy taken first is kept, and the error says where.
        kept = self.backups()
        self.assertEqual(len(kept), 1)
        self.assertIn(str(kept[0]), str(ctx.exception))
        # Nothing in the folder changed, so the page may say so.
        self.assertTrue(ctx.exception.intact)

    def test_a_retry_converts_to_the_installed_version_not_the_newest(self):
        _set_version(self.seed, "2.0.0")
        self.commit("2.0.0")
        _git(["tag", "v2.0.0"], self.seed)
        self.push()
        self.route_github_to(self.base / "nowhere.git")
        with self.assertRaises(updater.UpdateError):
            updater.convert_to_git(root=self.install, cfg=self.cfg_)

        self.route_github_to(self.remote)
        result = updater.convert_to_git(root=self.install, cfg=self.cfg_)

        self.assertEqual(result["target"], "v1.0.0")
        self.assertEqual(updater.local_version(self.install), "1.0.0")


class ThePageIsToldWhetherTheInstallIsIntactTests(unittest.TestCase):
    """`/api/update` carries `intact`, and the panel's reassurance is drawn
    only when it is true."""

    def post(self, error):
        import server
        with mock.patch.object(server.updater, "perform_update",
                               side_effect=error), \
             mock.patch.object(server.updater, "detect_install",
                               return_value={"method": "zip"}):
            client = server.app.test_client()
            resp = client.post("/api/update", json={"mode": None},
                               headers={"X-WD-Wireless-Tools": "1"})
        return resp.get_json()

    def test_a_refusal_before_anything_was_written_is_intact(self):
        out = self.post(updater.UpdateError("refused"))
        self.assertIs(out["intact"], True)

    def test_a_failure_partway_is_not(self):
        out = self.post(updater.UpdateError("stopped partway", intact=False))
        self.assertIs(out["intact"], False)

    def test_an_unexpected_failure_is_not(self):
        with self.assertLogs("wd", "ERROR"):
            out = self.post(RuntimeError("boom"))
        self.assertIs(out["intact"], False)


RENDER_FAILED = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('    function renderFailed(res) {');
if (a < 0) throw new Error('renderFailed moved');
let b = a, depth = 0, seen = false;
while (b < src.length && !(seen && depth === 0)) {
  if (src[b] === '{') { depth++; seen = true; }
  else if (src[b] === '}') depth--;
  b++;
}
let drawn = null;
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const render = o => { drawn = o.body; };
const stepsHtml = () => '', alternativesHtml = () => '', wire = () => {};
const state = { localVersion: '1.0.0' }, info = null;
eval(src.slice(a, b));
const out = {};
for (const [k, res] of Object.entries(JSON.parse(process.argv[2]))) {
  drawn = null; renderFailed(res); out[k] = drawn;
}
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ThePanelOnlyReassuresWhenToldTests(unittest.TestCase):

    def render(self, cases):
        r = subprocess.run(
            ["node", "-e", RENDER_FAILED,
             str(ROOT / "web" / "assets" / "js" / "wd-shared.js"),
             json.dumps(cases)],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout)

    def test_the_reassurance_follows_the_server(self):
        out = self.render({
            "intact": {"error": "refused", "intact": True},
            "partway": {"error": "stopped partway", "intact": False},
            "unknown": {"error": "network"},
        })
        claim = "Nothing was left half-installed"
        self.assertTrue(claim in out["intact"])
        self.assertFalse(claim in out["partway"])
        self.assertFalse(claim in out["unknown"])
        # The server's message is still shown on every path.
        self.assertTrue("stopped partway" in out["partway"])


if __name__ == "__main__":
    unittest.main()
