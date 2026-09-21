"""`WD_USER_DIR` has to move *everything*, or it protects nothing.

This exists because of what it cost. An automated sweep drove the real pages
against a real server, every page saved its options as you clicked them, and
with the user directory hard-coded in eight modules there was nowhere else for
those writes to go. Eight of his saved defaults came out wrong - one of them
hiding every omni AP from two reports - and the wall template he had built up
over months was overwritten. `tools/user_dir.py` and the `WD_USER_DIR`
override were written that night.

An override that one module ignores is worse than none, because it reads as
protection. So this checks the property rather than the wiring:

  * set `WD_USER_DIR` to a scratch directory
  * import every module that keeps user data
  * every path any of them will write to is under that directory

and separately, that nothing reconstructs the real path for itself.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _code_only(text: str) -> str:
    """The module with its docstrings and comments removed.

    Parsed rather than pattern-matched, because the thing being stripped is
    prose that legitimately quotes the path - the note explaining why
    `refused_roots` must not build it says what it used to build - and a
    line-based strip cannot tell a docstring's third line from code.
    """
    tree = ast.parse(text)
    drop = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            drop.update(range(body[0].lineno, body[0].end_lineno + 1))
    return "\n".join(
        line for number, line in enumerate(text.splitlines(), 1)
        if number not in drop and not line.lstrip().startswith("#"))

#: Every module that owns something under the user directory, and the
#: module-level names that hold a path into it.
OWNERS = {
    "tools.settings": ["SETTINGS_DIR", "SETTINGS_FILE"],
    "tools.template_store": ["USER_DIR"],
    "tools.plantrim_store": ["USER_DIR"],
    "tools.capacity_profiles": ["USER_DIR"],
    "tools.cloud_manager": ["CONFIG_DIR"],
    "tools.folder_organizer": ["CONFIG_DIR"],
    "tools.rename_manager": ["CONFIG_DIR"],
    # The log directory is user data like any other, and nothing was asking
    # this module where it had put it.
    "tools.applog": ["log_dir"],
}

PROBE = r"""
import importlib, json, sys
out = {}
for mod, names in json.loads(sys.argv[1]).items():
    m = importlib.import_module(mod)
    for n in names:
        v = getattr(m, n, None)
        if callable(v):
            v = v()
        out[mod + "." + n] = None if v is None else str(v)
# Resolved at call time rather than import time, so it is asked rather than read.
import tools.share_recipients as sr
out["tools.share_recipients.store_path()"] = str(sr.store_path())
print(json.dumps(out))
"""


class TheOverrideMovesEverything(unittest.TestCase):
    def test_every_user_data_path_follows_wd_user_dir(self):
        with tempfile.TemporaryDirectory(prefix="wd-isolation-") as tmp:
            env = dict(os.environ)
            env["WD_USER_DIR"] = tmp
            env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            r = subprocess.run([sys.executable, "-c", PROBE, json.dumps(OWNERS)],
                               capture_output=True, text=True, cwd=str(ROOT),
                               env=env, timeout=120)
            self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).strip())
            paths = json.loads(r.stdout.strip().splitlines()[-1])

        real = str(Path.home() / ".wd_wireless_tools")
        tmp_resolved = str(Path(tmp).resolve())
        for where, value in paths.items():
            self.assertIsNotNone(value, where + " is not defined any more - "
                                        "update OWNERS rather than deleting the check")
            self.assertFalse(
                value.startswith(real),
                where + " still points at the real user directory (" + value + "). "
                "It must go through tools.user_dir.user_dir().")
            self.assertTrue(
                str(Path(value).resolve()).startswith(tmp_resolved),
                where + " ignored WD_USER_DIR: " + value)

    def test_nothing_builds_the_real_path_for_itself(self):
        r"""One module reconstructing the user directory puts the override back.

        **This missed the one it was written to catch, and the 2026-09-20
        sweep found that by hand.** `housekeeping.refused_roots` - the list of
        places a sweep must never delete from - built the directory itself:

            home = Path.home()
            out = [home / ".wd_wireless_tools", home / "Dropbox"]

        Two statements. The check matched four *spellings*, every one of them
        a single expression, and none of them that one. So the guard passed
        while the module it was guarding against ignored `WD_USER_DIR`
        entirely - and in the direction that matters, because the override
        usually points inside `%TEMP%`, which is a folder the sweep *is*
        allowed to delete from.

        A list of spellings can only ever catch the spellings somebody
        thought of. The property is simpler and has no variants: **outside
        `user_dir.py`, no shipped module names the directory at all.** Every
        module that needs it asks `user_dir()`, so a literal in code is
        either a reconstruction or a hard-coded default, and both are the
        bug.

        Docstrings and comments are stripped first, and that half is not
        cosmetic: the fix for the finding above *explains* the old spelling
        in prose, and a guard that fires on the explanation teaches the next
        session to delete it.
        """
        offenders = []
        for py in sorted((ROOT / "tools").glob("*.py")) + [ROOT / "server.py"]:
            if py.name == "user_dir.py":
                continue                       # the one place that may know
            code = _code_only(py.read_text(encoding="utf-8"))
            if ".wd_wireless_tools" in code:
                lines = [l.strip() for l in code.splitlines()
                         if ".wd_wireless_tools" in l]
                offenders.append(
                    f"{py.relative_to(ROOT).as_posix()} ({lines[0][:80]})")
        self.assertEqual(
            offenders, [],
            "these name the user directory in code instead of calling "
            "tools.user_dir.user_dir():\n  " + "\n  ".join(offenders))


class TheSweepRefusesTheDirectoryThatIsActuallyInUse(unittest.TestCase):
    """`refused_roots` is a *deletion* boundary, so it gets its own check.

    It is not in `OWNERS` above because it returns a list rather than one
    path, and because the question is different: not "does this module write
    somewhere under the override" but "does the thing it refuses to touch
    follow the override".

    It did not. `refused_roots` read the hard-coded default, so on any run
    with `WD_USER_DIR` set the sweep's own refusal list named a directory
    nobody was using, and the directory that *was* in use was unlisted. That
    is the dangerous direction twice over: the override normally points
    inside `%TEMP%`, and `%TEMP%` is one of the three roots the sweep is
    allowed to delete from.

    Driven in a subprocess because the value is read at import.
    """

    PROBE = r"""
import json, os, sys
sys.path.insert(0, os.environ["WD_ROOT"])
from tools import housekeeping
from tools.user_dir import user_dir
print(json.dumps({
    "refused": [str(p) for p in housekeeping.refused_roots()],
    "userDir": str(user_dir()),
}))
"""

    def _probe(self, user_dir_value):
        env = dict(os.environ)
        env["WD_USER_DIR"] = user_dir_value
        env["WD_ROOT"] = str(ROOT)
        r = subprocess.run([sys.executable, "-c", self.PROBE],
                           capture_output=True, text=True, cwd=str(ROOT),
                           env=env, timeout=120)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_overridden_directory_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="wd-refused-") as tmp:
            out = self._probe(tmp)
            self.assertEqual(str(Path(tmp)), out["userDir"])
            refused = [str(Path(p).resolve()) for p in out["refused"]]
            self.assertIn(
                str(Path(tmp).resolve()), refused,
                "the sweep's refusal list does not contain the user directory "
                "that is actually in use: " + ", ".join(out["refused"]))

    def test_the_default_is_not_refused_in_its_place(self):
        """Naming the default while the override is set is the bug itself.

        Listing both would hide it - the real directory would be on the list
        and the test would pass - so this asserts the default is *absent*.
        """
        with tempfile.TemporaryDirectory(prefix="wd-refused-") as tmp:
            out = self._probe(tmp)
            default = str((Path.home() / ".wd_wireless_tools").resolve())
            refused = [str(Path(p).resolve()) for p in out["refused"]]
            self.assertNotIn(
                default, refused,
                "the sweep refuses the hard-coded default rather than the "
                "directory WD_USER_DIR points at")

    def test_with_no_override_it_is_the_default(self):
        """The override is an override; the shipped behaviour is unchanged."""
        env = dict(os.environ)
        env.pop("WD_USER_DIR", None)
        env["WD_ROOT"] = str(ROOT)
        r = subprocess.run([sys.executable, "-c", self.PROBE],
                           capture_output=True, text=True, cwd=str(ROOT),
                           env=env, timeout=120)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).strip())
        out = json.loads(r.stdout.strip().splitlines()[-1])
        refused = [str(Path(p).resolve()) for p in out["refused"]]
        self.assertIn(str((Path.home() / ".wd_wireless_tools").resolve()),
                      refused)


class TheOverrideIsDocumented(unittest.TestCase):
    def test_the_module_says_how_to_use_it(self):
        text = (ROOT / "tools" / "user_dir.py").read_text(encoding="utf-8")
        self.assertIn("WD_USER_DIR", text)
        # Read once at import, so setting it after a server starts does nothing
        # and a test that tries would be silently unprotected.
        self.assertIn("before the process starts", text)


if __name__ == "__main__":
    unittest.main()
