"""Point `WD_USER_DIR` at scratch before any test can import a tools module.

**The filename is load-bearing.** `python -m unittest discover -s tests`, which
is the command CLAUDE.md tells everyone to run, imports the files in `tests/`
as top-level modules in sorted order - it does not execute `tests/__init__.py`
at all. So the isolation cannot live in the package init, and it has to sort
before every other `test_*.py`. `0` sorts before every letter. Renaming this
file, or adding one that sorts earlier and imports `tools.*`, silently removes
the protection.

Why it needs to happen at import rather than in `setUp`: the modules that own
user data read `WD_USER_DIR` **once, at import**, into module-level constants.
By the time any `setUp` runs, `tools.template_store.USER_DIR` is already fixed.

What this protects, concretely. An automated sweep once wrote into his live
`~/.wd_wireless_tools`: eight saved report defaults came out wrong, one of them
hiding every omni AP from two reports, and his wall template was overwritten.
`tools/user_dir.py` was written that night. It worked - and it still was not
enough, because it only protects a process that remembers to set the variable.

On 2026-09-16 a test written that morning called the template store without
isolating it, and running the suite seeded two files directly into his live
templates folder. That test was not written badly by the standard in force; the
standard was "every author remembers", which is not a mechanism. This is the
mechanism.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

#: Captured **before** the redirect below, or it is the scratch path and this
#: file cheerfully asserts that scratch is not scratch.
REAL = Path.home() / ".wd_wireless_tools"


def _isolate() -> None:
    """Point the home directory *and* the override at the same scratch tree.

    `WD_USER_DIR` alone is not enough, and the reason is worth keeping. Several
    modules still build `Path.home() / ".wd_wireless_tools"` for themselves
    rather than calling `user_dir()` - `test_user_dir_is_the_only_door.py` is
    the open ticket for that and names them. Setting only the override moves
    the modules that honour it and leaves the others pointing at his real home,
    so the suite ends up half-isolated: the half that ignores the override
    still writes to his data, and tests that compare one against the other
    start failing for a reason that has nothing to do with them.

    Redirecting `HOME`/`USERPROFILE` as well covers the modules that have not
    been migrated yet, and keeps both halves agreeing about where user data is
    while that migration finishes.
    """
    if os.environ.get("WD_USER_DIR"):
        return
    home = tempfile.mkdtemp(prefix="wd-tests-home-")
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home
    # Same location `Path.home() / ".wd_wireless_tools"` now resolves to, so a
    # migrated module and an unmigrated one agree.
    os.environ["WD_USER_DIR"] = str(Path(home) / ".wd_wireless_tools")


_isolate()

#: Imported *after* the variables are set, deliberately.
from tools import user_dir as user_dir_module  # noqa: E402


class TheSuiteCannotReachHisRealUserDirectory(unittest.TestCase):

    def test_the_override_is_set_before_anything_reads_it(self):
        self.assertTrue(os.environ.get("WD_USER_DIR"),
                        "WD_USER_DIR is unset, so every user-data write in "
                        "this run lands in his real home directory")

    def test_it_does_not_resolve_to_his_real_directory(self):
        resolved = user_dir_module.user_dir().resolve()
        self.assertNotEqual(resolved, REAL.resolve(),
                            "the suite is pointed at his live user data")

    def test_the_owning_modules_followed_it(self):
        """Imported here as a spot check; the full sweep is in
        `test_user_dir_is_the_only_door.py`, which runs each module in a
        subprocess. This one catches the case that file cannot: a module
        already imported into *this* process before the variable was set.
        """
        import tools.template_store as template_store
        import tools.settings as settings

        here = user_dir_module.user_dir().resolve()
        for label, path in (("template_store.USER_DIR", template_store.USER_DIR),
                            ("settings.SETTINGS_FILE", Path(settings.SETTINGS_FILE))):
            with self.subTest(path=label):
                try:
                    Path(path).resolve().relative_to(here)
                except ValueError:
                    self.fail(f"{label} is {path}, outside {here} - a test "
                              f"that touches it writes to his real data")


if __name__ == "__main__":
    unittest.main()
