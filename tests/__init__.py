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
the location. The directory is per-run and is left on disk deliberately: when a
test fails over what it wrote, the evidence is still there to look at, and the
OS clears the temp tree anyway.
"""
from __future__ import annotations

import os
import tempfile

if not os.environ.get("WD_USER_DIR"):
    os.environ["WD_USER_DIR"] = tempfile.mkdtemp(prefix="wd-tests-userdir-")
