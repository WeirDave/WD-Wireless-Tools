"""Automated safety tests for WD Wireless Tools.

**Running the tests must never be able to touch his real user directory.**

`tools/user_dir.py` and the `WD_USER_DIR` override exist because an automated
sweep wrote into `~/.wd_wireless_tools` and cost him eight saved defaults and
his wall template. The override works - `test_user_dir_is_the_only_door.py`
checks every module honours it - but it only protects a run that remembers to
set it, and remembering is not a mechanism.

It failed again on 2026-09-16. A test written that morning called the template
store without isolating it, so running the suite seeded two files straight into
his live templates folder. Nobody had done anything wrong by the standard of
"patch `USER_DIR` in `setUp`"; the standard is the problem, because a new test
is written by somebody who does not know it exists.

So the variable is set **here**, in the package `__init__`, which Python
executes before it imports a single test module - and therefore before any
module that reads `WD_USER_DIR` at import time can read it. There is no test
file that can opt out by forgetting.

An already-set `WD_USER_DIR` is respected, so CI or a caller can still choose
the location.

**The directory is removed when the run ends, and that is a correction.** It
used to be left behind deliberately, reasoning that the evidence should still
be there when a test fails over what it wrote, and that "the OS clears the temp
tree anyway". The second half is not true on Windows - nothing clears `%TEMP%`
- so 143 of these were sitting on his machine when the dev toolbar's
housekeeping action first counted them, one per suite run since the rule was
written.

The evidence argument survives, so `WD_KEEP_TEST_USER_DIR=1` keeps the
directory and prints where it is. The default is to clean up after ourselves,
because the alternative turned out to be leaving a directory on his disk every
time anybody ran the tests.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile

if not os.environ.get("WD_USER_DIR"):
    _OURS = tempfile.mkdtemp(prefix="wd-tests-userdir-")
    os.environ["WD_USER_DIR"] = _OURS

    if os.environ.get("WD_KEEP_TEST_USER_DIR"):
        print("test user dir kept at %s" % _OURS)
    else:
        @atexit.register
        def _remove_test_user_dir():
            # Never allowed to fail the run. A suite that went red because it
            # could not tidy up would be a worse trade than the directory.
            shutil.rmtree(_OURS, ignore_errors=True)
