"""The browser tests have to actually run somewhere, and CI is that somewhere.

**Fourteen files drive Firefox, Chrome and Edge**, and they are the pattern
the rest of this repository is measured against: a control is verified by
running it, not by finding its name. Around 300 test methods sit behind
`from selenium import webdriver` and a binary that has to exist.

**None of them ran in CI.** `selenium` was never installed there, so every
one skipped and the run reported a pass - roughly 3,121 tests on the runner
against 3,424 on a machine with browsers, and nothing anywhere stated the
difference. The cost was not hypothetical:
`test_nothing_in_the_strip_writes_to_anything` went red when v2.163.0 added
the Exit control to the dev strip and stayed red through **four releases**.
CI could not see it, and on a machine that has browsers it read as three
identical red lines every run, which is easy to write off as noise. It was,
by me, repeatedly.

The same shape as the node gap this file is modelled on, one level up: the
tests that prove behaviour were the ones not running.

Three parts, because no one of them is enough:

* **`test_ci_can_drive_a_browser` runs only on a runner.** It is the one
  that would actually catch a regression, and a skip is an acceptable answer
  on a laptop and never on the build everyone trusts.
* **The workflow checks run everywhere**, including on a machine with no
  browser, because reading the pipeline is the only way to check it off a
  runner. They parse the steps rather than searching the text - the
  explanatory comment in `tests.yml` names `requirements-dev.txt`, so a
  substring assertion would survive deleting the step it exists to protect.
* **The path check runs everywhere too.** A hardcoded install location is a
  machine's answer, not a fact, and fourteen copies of one is fourteen ways
  to start skipping silently on a runner whose image moved a binary.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests import browsers                                    # noqa: E402
from tests.test_ci_runs_the_node_tests import workflow_steps   # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
TESTS_DIR = ROOT / "tests"

#: GitHub Actions sets this on every runner. It is the only thing that
#: separates "a developer with no browser" from "the build everyone trusts".
IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"


class TheRunnerCanActuallyDriveABrowser(unittest.TestCase):

    @unittest.skipUnless(IN_CI, "only CI is required to have a browser")
    def test_ci_has_selenium(self):
        """Without it every browser test skips, whatever browsers are here."""
        try:
            import selenium  # noqa: F401
        except ImportError:  # pragma: no cover - the failure being guarded
            self.fail("selenium is not installed on the runner, so all ~300 "
                      "browser tests skipped and this run reported a pass "
                      "over them - install requirements-dev.txt")

    @unittest.skipUnless(IN_CI and sys.platform.startswith("win"),
                         "browsers are required on the Windows runner")
    def test_ci_can_drive_a_browser(self):
        """The one that would have caught it.

        If this fails, the tests that drive real controls did not run and
        said nothing about it.

        **Required on the Windows runner specifically**, and that is a
        choice rather than an oversight. The Windows image ships Firefox,
        Chrome and Edge; the macOS images do not reliably ship any of them,
        and installing browsers there would mean adding third-party actions
        to a pipeline that currently uses none - a supply-chain decision,
        not a testing one, and not one to take quietly inside a test file.

        Windows is also where this matters: it is what he runs, what the
        release targets, and - per the print rules - Firefox there is the
        engine whose behaviour decides the report. One runner that really
        drives the controls closes the gap this file exists for. If macOS
        coverage is wanted too, that is a deliberate conversation about
        which actions to trust.

        The inventory step prints what every runner found either way, so a
        macOS image that gains a browser will be visible rather than
        assumed.
        """
        self.assertTrue(
            browsers.available(),
            "no browser on the Windows runner, so every test that drives a "
            "real control skipped: " + browsers.why_missing())


class TheWorkflowInstallsWhatThoseTestsNeed(unittest.TestCase):
    """Readable off a runner, so a laptop can check the pipeline too."""

    @staticmethod
    def _script(path: Path = WORKFLOW) -> str:
        """Everything the runner will execute, comments removed.

        `workflow_steps` returns one dict per step and keeps only the first
        line of a value, so the body of a `run: |` block never reaches it -
        which is where the install commands are. Reading the file directly
        gets them, and dropping `#` lines first keeps the trap the node
        guard documents: the comment above the step names the things the
        step does, so a plain substring search over the raw file would pass
        on the explanation after the step itself was deleted.
        """
        return "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#"))

    def setUp(self):
        self.steps = workflow_steps(WORKFLOW)
        self.runs = self._script()

    def test_the_reader_drops_the_explanation(self):
        """The parser is load-bearing, so it is checked before it is
        trusted - a comment naming the step must not count as the step."""
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="wd-wf-"))
        self.addCleanup(__import__("shutil").rmtree, d, True)
        f = d / "w.yml"
        f.write_text("steps:\n"
                     "  # pip install -r requirements-dev.txt - explaining\n"
                     "  - name: Real\n    run: echo hello\n",
                     encoding="utf-8")
        self.assertNotIn("requirements-dev.txt", self._script(f))
        self.assertIn("echo hello", self._script(f))

    def test_there_are_steps_to_read(self):
        """A parser that silently matched nothing would pass for ever."""
        self.assertGreater(len(self.steps), 3, self.steps)

    def test_the_dev_requirements_are_installed(self):
        self.assertIn(
            "requirements-dev.txt", self.runs,
            "nothing on the runner installs the test-only dependencies, so "
            "every browser test will skip there and the run will still be "
            "green")

    @staticmethod
    def _required(path: Path) -> list:
        """The package names a requirements file actually asks for.

        Parsed rather than searched. Both of the questions below are about
        what `pip install -r` will do, and a substring answers a different
        one: `requirements.txt` explains at length why each floor is set,
        so a comment mentioning a package would read as a dependency, and
        the shipped-list check is the one where a false negative puts
        something on his machine.
        """
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            out.append(re.split(r"[<>=!~;\[ ]", line, 1)[0].strip().lower())
        return out

    def test_the_dev_requirements_file_asks_for_selenium(self):
        f = ROOT / "requirements-dev.txt"
        self.assertTrue(f.is_file(), "requirements-dev.txt is gone")
        self.assertIn("selenium", self._required(f))

    def test_selenium_is_not_shipped_to_him(self):
        """`requirements.txt` is in the release payload and both installers
        run it against his machine. A test dependency there is installed on
        every machine that runs the tool, for nothing."""
        self.assertNotIn("selenium", self._required(ROOT / "requirements.txt"))

    def test_the_browser_inventory_is_printed(self):
        """A skip nobody can see is the thing being fixed, so the runner
        states what it found rather than leaving it to a test count."""
        self.assertIn("tests.browsers_report", self.runs)


class NoTestHardcodesWhereABrowserLives(unittest.TestCase):
    """Fourteen copies of an install path is fourteen silent skips waiting.

    They are a machine's answer, not a fact: right on his box, wrong on a
    runner, wrong on a Mac, wrong where Firefox was installed per-user. The
    resolver asks instead, and this keeps the copies from coming back.
    """

    #: `browsers.py` is allowed to know where browsers live - it is the
    #: point of it. This file is allowed because it has to name the markers
    #: in order to search for them, and writing them in pieces to dodge its
    #: own check would hide from a reader what it looks for.
    ALLOWED = {"browsers.py", "test_ci_runs_the_browser_tests.py"}

    def test_no_test_file_carries_an_install_path(self):
        offenders = []
        for f in sorted(TESTS_DIR.glob("*.py")):
            if f.name in self.ALLOWED:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            for marker in ("Program Files", "/Applications/",
                           "/usr/bin/firefox"):
                if marker in text:
                    offenders.append(f"{f.name} ({marker})")
        self.assertEqual(
            offenders, [],
            "these hardcode where a browser lives instead of asking "
            "`tests.browsers.find`, so they will skip silently wherever the "
            "guess is wrong: %s" % offenders)

    def test_the_resolver_never_answers_with_a_path_that_exists_by_accident(self):
        """`Path("").exists()` is the current directory, which is true - so
        an empty answer would turn "no browser" into "this folder is
        Firefox" for every `Path(BINARY).exists()` guard in the suite."""
        self.assertTrue(browsers.NOT_INSTALLED)
        self.assertFalse(Path(browsers.NOT_INSTALLED).exists())

    def test_it_reports_every_browser_rather_than_only_the_present_ones(self):
        """Returning just what is installed would shrink the matrix quietly
        instead of leaving a skip that can be counted."""
        self.assertEqual(["firefox", "chrome", "edge"],
                         [k for k, _ in browsers.triple()])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
