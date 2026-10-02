"""install.sh, run for real against local stand-ins for GitHub.

Two defects, each driven by running the script itself:

* **It overwrote itself while running.** The ZIP path copies the new release
  over the install folder, install.sh included, and bash reads a script as it
  runs. It carried on at the old byte offset in the new file: the dependency
  step and "Ready" never ran, and it exited 127. The body is now one function
  called on the last line, so it is all read before any of it runs.

* **It discarded edits.** The git path ran `checkout --force`, which throws
  away every edit to a tracked file except the wall templates it rescues
  first. It now stops and names them, as the in-app updater does.

GitHub is never reached: `curl` is a stub on PATH serving files from a
folder, and `origin` is a local bare repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = ROOT / "install.sh"
WHO = ["-c", "user.email=tester@example.invalid", "-c", "user.name=Tester"]

CURL_STUB = r"""#!/usr/bin/env bash
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift 2;; -H) shift 2;; -*) shift;; *) url="$1"; shift;; esac
done
case "$url" in
  *api.github.com*) body="{\"tag_name\": \"v$STUB_TAG\"}";;
  *) f="$STUB_DIR/${url##*/}"; [ -f "$f" ] || exit 22; body="";;
esac
if [ -n "$out" ]; then
  if [ -n "$body" ]; then printf '%s' "$body" > "$out"; else cp "$f" "$out"; fi
else
  printf '%s' "$body"
fi
"""


def _usable():
    if os.name == "nt":
        return "`bash` on a Windows runner can be WSL's"
    for tool in ("bash", "git", "unzip"):
        if not shutil.which(tool):
            return f"{tool} is not installed"
    if not (shutil.which("sha256sum") or shutil.which("shasum")):
        return "no SHA-256 tool"
    return None


def _payload(root: Path, version: str, install_sh: str):
    for d in ("tools", "web/assets", "templates", "docs"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "server.py").write_text("# invented server\n", encoding="utf-8")
    (root / "requirements.txt").write_text("", encoding="utf-8")
    (root / "web/assets/versions.json").write_text(
        json.dumps({"suite": version}), encoding="utf-8")
    # The real dependency check needs real packages; this one answers
    # "satisfied", so the step runs and reports without touching pip.
    (root / "tools/deps.py").write_text("import sys; sys.exit(0)\n",
                                         encoding="utf-8")
    (root / "tools/__init__.py").write_text("", encoding="utf-8")
    (root / "docs/readme.md").write_text("docs\n", encoding="utf-8")
    (root / "Start WD Wireless Tools.command").write_text(
        "launcher\n", encoding="utf-8")
    (root / "install.sh").write_text(install_sh, encoding="utf-8")


class _Harness(unittest.TestCase):

    def setUp(self):
        why = _usable()
        if why:
            self.skipTest(why)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        gitconfig = self.base / "gitconfig"
        gitconfig.write_text("", encoding="utf-8")
        self.env = dict(os.environ)
        self.env.update({
            "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": str(gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            # The script looks for python3; make it the one running this.
            "PATH": os.pathsep.join([str(Path(sys.executable).parent),
                                     self.env.get("PATH", "")]),
        })
        self.script = INSTALL_SH.read_text(encoding="utf-8")

    def run_installer(self, app: Path):
        proc = subprocess.run(
            ["bash", "./install.sh", "--no-launch"], cwd=str(app),
            env=self.env, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120)
        return proc.returncode, proc.stdout + proc.stderr

    @staticmethod
    def version(app: Path):
        return json.loads(
            (app / "web/assets/versions.json").read_text(encoding="utf-8"))["suite"]


class AZipUpdateReplacingTheScriptRunsToTheEndTests(_Harness):

    def test_the_update_finishes_after_install_sh_is_replaced(self):
        # The new release's install.sh differs in length, as any edit makes it.
        first, rest = self.script.split("\n", 1)
        padding = "".join(f"# a longer header in a newer release, line {i}\n"
                          for i in range(40))
        newer_script = first + "\n" + padding + rest

        release = self.base / "release" / "WD-Wireless-Tools"
        _payload(release, "9.9.9", newer_script)
        served = self.base / "served"
        served.mkdir()
        asset = served / "WD-Wireless-Tools-v9.9.9.zip"
        with zipfile.ZipFile(asset, "w") as zf:
            for p in sorted(release.rglob("*")):
                zf.write(p, p.relative_to(release.parent).as_posix())
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        (served / (asset.name + ".sha256")).write_text(
            f"{digest}  {asset.name}\n", encoding="utf-8")

        stub_bin = self.base / "bin"
        stub_bin.mkdir()
        (stub_bin / "curl").write_text(CURL_STUB, encoding="utf-8")
        (stub_bin / "curl").chmod(0o755)
        self.env["PATH"] = str(stub_bin) + os.pathsep + self.env["PATH"]
        self.env.update({"STUB_DIR": str(served), "STUB_TAG": "9.9.9"})

        app = self.home / "app"
        _payload(app, "1.0.0", self.script)

        code, out = self.run_installer(app)

        self.assertEqual(code, 0, out)
        self.assertEqual(self.version(app), "9.9.9")
        self.assertTrue("Checking Python dependencies" in out, out)
        self.assertTrue("Ready:" in out, out)
        self.assertEqual((app / "install.sh").read_text(encoding="utf-8"),
                         newer_script)


class AGitUpdateKeepsEditsTests(_Harness):

    def setUp(self):
        super().setUp()
        seed = self.base / "seed"
        _payload(seed, "1.0.0", self.script)
        (seed / "templates/Invented_walltemplate.json").write_text(
            '{"wallTypes": []}\n', encoding="utf-8")
        self.git(["init", "-q", "-b", "main"], seed)
        self.git(["add", "-A"], seed)
        self.git([*WHO, "commit", "-q", "-m", "1.0.0"], seed)
        self.git(["tag", "v1.0.0"], seed)
        remote = self.base / "remote.git"
        self.git(["clone", "-q", "--bare", str(seed), str(remote)], self.base)
        self.app = self.home / "app"
        self.git(["clone", "-q", str(remote), str(self.app)], self.base)
        self.git(["-c", "advice.detachedHead=false", "checkout", "-q", "v1.0.0"],
                 self.app)
        (seed / "web/assets/versions.json").write_text(
            json.dumps({"suite": "1.1.0"}), encoding="utf-8")
        self.git([*WHO, "commit", "-q", "-am", "1.1.0"], seed)
        self.git(["tag", "v1.1.0"], seed)
        self.git(["push", "-q", "--tags", str(remote), "main"], seed)

    def git(self, args, cwd):
        proc = subprocess.run(["git", *args], cwd=str(cwd), env=self.env,
                              capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)}: {proc.stderr.strip()}")
        return proc.stdout

    def test_an_edited_tracked_file_stops_the_update_and_is_named(self):
        launcher = self.app / "Start WD Wireless Tools.command"
        launcher.write_text("launcher\nmy own line\n", encoding="utf-8")

        code, out = self.run_installer(self.app)

        self.assertNotEqual(code, 0, out)
        self.assertEqual(launcher.read_text(encoding="utf-8"),
                         "launcher\nmy own line\n")
        self.assertEqual(self.version(self.app), "1.0.0")
        self.assertTrue("Start WD Wireless Tools.command" in out, out)

    def test_a_clean_install_updates(self):
        (self.app / "my-notes.txt").write_text("untracked\n", encoding="utf-8")

        code, out = self.run_installer(self.app)

        self.assertEqual(code, 0, out)
        self.assertEqual(self.version(self.app), "1.1.0")
        self.assertTrue((self.app / "my-notes.txt").exists())

    def test_an_edited_wall_template_is_kept_and_does_not_block(self):
        tpl = self.app / "templates/Invented_walltemplate.json"
        tpl.write_text('{"wallTypes": ["mine"]}\n', encoding="utf-8")

        code, out = self.run_installer(self.app)

        self.assertEqual(code, 0, out)
        self.assertEqual(self.version(self.app), "1.1.0")
        kept = self.home / ".wd_wireless_tools/templates/Invented_walltemplate.json"
        self.assertEqual(kept.read_text(encoding="utf-8"), '{"wallTypes": ["mine"]}\n')


if __name__ == "__main__":
    unittest.main()
