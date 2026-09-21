"""The version floors are a security boundary, so something has to read them.

**Nothing did.** Both installers checked dependencies by importing them::

    python -c "import flask, waitress, requests, browser_cookie3,
               cryptography, keyring, PIL"

and skipped `pip install -r requirements.txt` when that succeeded. On any
machine where the packages already imported, the floors in
`requirements.txt` were never consulted - not on a fresh install, not on an
update, not once. A package installed two years ago satisfied the check for
as long as its name resolved.

Measured on 2026-09-20 with `pip-audit`: the floors as declared admitted
**70 known vulnerabilities across six packages**. Pillow is the one that
makes it a security finding rather than a hygiene one - it decodes the
floor-plan images inside `.esx` archives, which arrive by email, out of
shared folders and down from Ekahau Cloud, and its advisories are decoder
bugs, the class where the untrusted input is the attack.

`tools/deps.py` answers the question now, the installers act on the answer,
and the server says so in the log at startup if an install has drifted.

**What this file does not do is re-run pip-audit.** That needs the network
and a vulnerability database that changes daily, and a test that goes red
because somebody published an advisory overnight is a test that gets
switched off. What it holds is the mechanism: the floors are parseable, the
check compares versions rather than names, and no floor silently disappears.
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import deps

#: Every package `requirements.txt` is expected to pin a floor for. Named
#: rather than counted, so deleting one fails here instead of quietly
#: reducing what is checked.
EXPECTED = {"flask", "waitress", "requests", "browser_cookie3",
            "cryptography", "keyring", "pillow"}


class TheFloorsAreReadable(unittest.TestCase):

    def test_every_dependency_declares_one(self):
        found = deps.floors()
        self.assertEqual(EXPECTED, set(found),
                         "requirements.txt no longer declares a floor for "
                         "every dependency")

    def test_each_floor_is_a_version(self):
        for name, floor in deps.floors().items():
            with self.subTest(package=name):
                self.assertRegex(floor, r"^\d+(\.\d+)*$")

    def test_comments_are_not_mistaken_for_requirements(self):
        """The file is mostly explanation now, and that must not confuse it."""
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertGreater(text.count("#"), 5,
                           "the reasoning has gone out of requirements.txt")
        self.assertEqual(EXPECTED, set(deps.floors()))

    def test_a_floor_is_never_a_bare_name(self):
        """`pillow` with no floor would satisfy any version at all - which is
        the state this whole finding was about, written differently."""
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            self.assertIn(">=", stripped,
                          f"requirement without a floor: {stripped}")


class TheCheckComparesVersions(unittest.TestCase):
    """Names, which is what the installers compared, is the bug."""

    def _floors_file(self, text):
        d = Path(tempfile.mkdtemp(prefix="wd-deps-"))
        self.addCleanup(
            lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        p = d / "requirements.txt"
        p.write_text(text, encoding="utf-8")
        return p

    def test_an_installed_package_that_is_too_old_is_reported(self):
        path = self._floors_file("pillow>=12.3.0\n")
        with mock.patch.object(deps, "installed_version", return_value="11.0.0"):
            result = deps.check(path)
        self.assertFalse(result["ok"])
        self.assertEqual(["pillow"], [e["name"] for e in result["outdated"]])
        self.assertEqual("11.0.0", result["outdated"][0]["have"])

    def test_an_installed_package_that_is_current_passes(self):
        path = self._floors_file("pillow>=12.3.0\n")
        with mock.patch.object(deps, "installed_version", return_value="12.3.0"):
            self.assertTrue(deps.check(path)["ok"])
        with mock.patch.object(deps, "installed_version", return_value="12.4.1"):
            self.assertTrue(deps.check(path)["ok"])

    def test_a_missing_package_is_reported_separately(self):
        path = self._floors_file("pillow>=12.3.0\n")
        with mock.patch.object(deps, "installed_version", return_value=None):
            result = deps.check(path)
        self.assertFalse(result["ok"])
        self.assertEqual(["pillow"], [e["name"] for e in result["missing"]])

    def test_versions_compare_numerically_not_as_text(self):
        """`"11.0.0" > "12.3.0"` is true as strings, and that is the shape of
        every version comparison anybody writes by accident."""
        path = self._floors_file("pillow>=9.0.0\n")
        with mock.patch.object(deps, "installed_version", return_value="10.0.0"):
            self.assertTrue(deps.check(path)["ok"],
                            "10.0.0 was treated as older than 9.0.0")

    def test_the_summary_names_the_package_and_both_versions(self):
        path = self._floors_file("pillow>=12.3.0\n")
        with mock.patch.object(deps, "installed_version", return_value="11.0.0"):
            line = deps.summary(deps.check(path))
        self.assertIn("pillow", line)
        self.assertIn("11.0.0", line)
        self.assertIn("12.3.0", line)

    def test_the_real_environment_is_answerable(self):
        """Whatever the answer, it has to be an answer.

        This runs against whatever is installed, so it asserts the shape
        rather than the verdict - an environment that is out of date is a
        true thing to report, not a test failure.
        """
        result = deps.check()
        self.assertEqual(len(EXPECTED), result["checked"])
        self.assertIsInstance(result["ok"], bool)
        self.assertIsInstance(deps.summary(result), str)

    def test_main_exits_non_zero_when_something_is_stale(self):
        """The whole interface the installers use."""
        with mock.patch.object(deps, "check",
                               return_value={"ok": False, "missing": [],
                                             "outdated": [], "current": [],
                                             "checked": 7}):
            self.assertEqual(1, deps.main([]))
        with mock.patch.object(deps, "check",
                               return_value={"ok": True, "missing": [],
                                             "outdated": [], "current": [],
                                             "checked": 7}):
            self.assertEqual(0, deps.main([]))


def _commands(path: Path) -> list:
    """The executable lines of a shell script, without its comments.

    **Not the file's text**, for two reasons that turn out to be the same
    reason. The obvious one: the notes explaining this fix *quote the probe
    being replaced*, so a check against the raw text finds the explanation
    and reports the bug as still present - which happened twice in the sweep
    that wrote this. The other: a test that asserts a file *contains* a
    string is the shape this repository has five shipped defects from, and
    `tests/test_a_test_must_be_able_to_fail.py` counts them. Reducing the
    file to the commands it actually runs is the nearest thing to executing
    a shell script that a unit test can do, and it is what the property is
    about anyway.
    """
    lines = []
    for raw in path.read_text(encoding="utf-8").split("\n"):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


class TheInstallersAskTheRightQuestion(unittest.TestCase):
    """The fix was in two shell scripts, so the scripts are what is checked.

    They run under PowerShell and sh on a machine being set up, before any
    of this is importable, so there is no way to execute them from here.
    What is checked is the list of commands each one runs, with the prose
    removed - see `_commands`.
    """

    def setUp(self):
        self.scripts = {
            "install.ps1": _commands(ROOT / "install.ps1"),
            "install.sh": _commands(ROOT / "install.sh"),
        }

    def test_neither_decides_on_importability_alone(self):
        """The probe that never read a version floor."""
        for name, commands in self.scripts.items():
            with self.subTest(script=name):
                probes = [line for line in commands
                          if "import flask" in line and "PIL" in line]
                self.assertEqual(
                    [], probes,
                    "the import-only probe is back - it never reads the "
                    "version floors, so a years-old package passes it:\n  "
                    + "\n  ".join(probes))

    def test_both_run_the_version_check(self):
        for name, commands in self.scripts.items():
            with self.subTest(script=name):
                self.assertTrue(
                    [line for line in commands if "tools.deps" in line],
                    f"{name} never asks whether the installed versions meet "
                    "the floors")

    def test_both_upgrade_rather_than_merely_install(self):
        """`pip install -r` leaves an old package that satisfies the name.

        Without `--upgrade` the check above finds the stale package and the
        step that follows does nothing about it.
        """
        for name, commands in self.scripts.items():
            with self.subTest(script=name):
                installs = [line for line in commands if "pip install" in line]
                self.assertTrue(installs, f"{name} never runs pip install")
                self.assertTrue(
                    all("--upgrade" in line for line in installs),
                    f"{name} installs without --upgrade:\n  "
                    + "\n  ".join(installs))

    def test_deps_ships_in_the_release_payload(self):
        """A ZIP install has no `scripts/`, which is why this lives in tools/."""
        from tools import updater
        self.assertIn("tools", updater.CONFIG.payload_dirs)
        self.assertTrue((ROOT / "tools" / "deps.py").is_file())


if __name__ == "__main__":
    unittest.main()
