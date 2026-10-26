"""`install.ps1` can update an install under Windows PowerShell 5.1.

The script runs with `$ErrorActionPreference = 'Stop'`. In Windows PowerShell
5.1 a native command's stderr becomes a terminating error under that setting,
and git reports progress there when it succeeds: `From <url>` after a fetch,
`HEAD is now at ...` after a checkout. So `Invoke-Git` threw on the first line
of a perfectly good update, in the shell that ships with Windows. PowerShell 7
does not do this, which is why it looked fine from a developer's machine.

This runs the real `Invoke-Git`, cut out of `install.ps1`, in `powershell.exe`
against throwaway repositories. It is skipped where that shell does not exist
(the macOS runner); the Windows jobs run it. Every name here is invented.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "install.ps1"

POWERSHELL_51 = shutil.which("powershell.exe") or shutil.which("powershell")
GIT = shutil.which("git")

IDENTITY = ["-c", "user.name=Invented Person", "-c", "user.email=invented@example.com"]


def _function_source(name: str) -> str:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    start = text.index(f"function {name} {{")
    depth, i = 0, text.index("{", start)
    while True:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1


def _git(cwd, *args):
    subprocess.run(["git", *IDENTITY, *args], cwd=cwd, check=True,
                   capture_output=True, encoding="utf-8", timeout=60)


@unittest.skipUnless(POWERSHELL_51 and GIT, "needs powershell.exe and git")
class InvokeGitUnderStopTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-install-ps1-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        bare, seed, work = cls.tmp / "bare.git", cls.tmp / "seed", cls.tmp / "work"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True,
                       capture_output=True, timeout=60)
        subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True,
                       capture_output=True, timeout=60)
        (seed / "a.txt").write_text("one", encoding="utf-8")
        _git(seed, "add", "a.txt")
        _git(seed, "commit", "-q", "-m", "first")
        _git(seed, "branch", "-M", "main")
        _git(seed, "push", "-q", "origin", "main")
        subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True,
                       capture_output=True, timeout=60)
        cls.seed, cls.work, cls.releases = seed, work, 0

    def advance_remote(self):
        """The remote moves on, so the next fetch has something to report on
        stderr. Each test does this for itself, so none depends on the order
        the others ran in."""
        type(self).releases += 1
        tag = f"v1.0.{self.releases}"
        (self.seed / "a.txt").write_text(tag, encoding="utf-8")
        _git(self.seed, "commit", "-q", "-am", tag)
        _git(self.seed, "tag", tag)
        _git(self.seed, "push", "-q", "origin", "main", "--tags")
        return tag

    def run_ps(self, body: str):
        program = (
            "$ErrorActionPreference = 'Stop'\n"
            + _function_source("Invoke-Git") + "\n"
            + f"$wd = '{self.work}'\n" + body)
        return subprocess.run(
            [POWERSHELL_51, "-NoProfile", "-NonInteractive", "-Command", program],
            capture_output=True, encoding="utf-8", timeout=120)

    def test_a_fetch_that_reports_on_stderr_is_not_an_error(self):
        self.advance_remote()
        r = self.run_ps("Invoke-Git -Arguments @('fetch','--tags','origin') "
                        "-WorkDir $wd | Out-Null\nWrite-Output 'FETCHED'")
        self.assertIn("FETCHED", r.stdout, r.stdout + r.stderr)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)

    def test_a_checkout_that_reports_on_stderr_is_not_an_error(self):
        tag = self.advance_remote()
        # Fetched here, outside the shell under test, so it is the checkout
        # that reports on stderr there and not the fetch.
        subprocess.run(["git", "-C", str(self.work), "fetch", "-q", "--tags", "origin"],
                       check=True, capture_output=True, timeout=60)
        r = self.run_ps(
            "Invoke-Git -Arguments @('-c','advice.detachedHead=false','checkout',"
            f"'--force','{tag}') -WorkDir $wd | Out-Null\nWrite-Output 'CHECKED-OUT'")
        self.assertIn("CHECKED-OUT", r.stdout, r.stdout + r.stderr)

    def test_a_real_failure_still_throws_with_gits_words(self):
        r = self.run_ps(
            "try { Invoke-Git -Arguments @('checkout','no-such-ref-here') -WorkDir $wd "
            "| Out-Null; Write-Output 'NO-THROW' } "
            "catch { Write-Output ('THREW: ' + $_.Exception.Message) }")
        self.assertIn("THREW:", r.stdout, r.stdout + r.stderr)
        self.assertIn("no-such-ref-here", r.stdout)
        self.assertNotIn("NO-THROW", r.stdout)

    def test_allow_failure_still_returns_instead_of_throwing(self):
        r = self.run_ps(
            "Invoke-Git -Arguments @('checkout','no-such-ref-here') -WorkDir $wd "
            "-AllowFailure | Out-Null\nWrite-Output 'CONTINUED'")
        self.assertIn("CONTINUED", r.stdout, r.stdout + r.stderr)

    def test_the_output_comes_back_as_text_lines(self):
        r = self.run_ps(
            "$tags = Invoke-Git -Arguments @('tag','--list','v*') -WorkDir $wd\n"
            "Write-Output ('TAGS=' + (($tags | ForEach-Object { $_.GetType().Name }) "
            "-join ','))")
        self.assertIn("TAGS=", r.stdout, r.stdout + r.stderr)
        self.assertNotIn("ErrorRecord", r.stdout)


if __name__ == "__main__":
    unittest.main()
