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

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
        """One module reconstructing `Path.home() / ".wd_wireless_tools"` is
        all it takes to put the override back where it was."""
        offenders = []
        for py in sorted((ROOT / "tools").glob("*.py")) + [ROOT / "server.py"]:
            if py.name == "user_dir.py":
                continue                       # the one place that may know
            text = py.read_text(encoding="utf-8")
            # strip comments and docstrings crudely - the path is named in
            # several explanations and that is not the same as building it
            code = "\n".join(
                line for line in text.splitlines()
                if not line.lstrip().startswith("#")
            )
            for needle in ('Path.home() / ".wd_wireless_tools"',
                           "Path.home() / '.wd_wireless_tools'",
                           'Path.home()/".wd_wireless_tools"',
                           'os.path.expanduser("~/.wd_wireless_tools")'):
                if needle in code:
                    offenders.append(py.relative_to(ROOT).as_posix())
                    break
        self.assertEqual(offenders, [],
                         "these build the user directory themselves instead of "
                         "calling tools.user_dir.user_dir(): " + ", ".join(offenders))


class TheOverrideIsDocumented(unittest.TestCase):
    def test_the_module_says_how_to_use_it(self):
        text = (ROOT / "tools" / "user_dir.py").read_text(encoding="utf-8")
        self.assertIn("WD_USER_DIR", text)
        # Read once at import, so setting it after a server starts does nothing
        # and a test that tries would be silently unprotected.
        self.assertIn("before the process starts", text)


if __name__ == "__main__":
    unittest.main()
