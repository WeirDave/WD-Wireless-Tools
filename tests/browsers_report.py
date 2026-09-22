"""Print which browsers this machine has, and whether selenium can drive.

Run as a workflow step so the answer is in the transcript before any test
depends on it. The failure being designed out is a silent skip: a browser
test that does not run leaves nothing behind but a slightly smaller number,
and nobody reads a test count.

Exits 0 whatever it finds. It is a report, not a gate - the gate is
`tests/test_ci_runs_the_browser_tests.py`, which can say what it wants in a
failure message. A step that both reports and fails would stop printing the
rest of the inventory at the first problem, which is the half worth having.
"""
from __future__ import annotations

import sys

from tests import browsers


def main() -> int:
    try:
        import selenium
        sel = getattr(selenium, "__version__", "installed")
    except ImportError:
        sel = None

    print("platform          :", sys.platform)
    print("on CI             :", browsers.on_ci())
    print("selenium          :", sel or "NOT INSTALLED - every browser test "
                                        "in this suite will skip")
    for kind in ("firefox", "chrome", "edge"):
        found = browsers.find(kind)
        print("%-18s: %s" % (kind,
                             found if browsers.installed(kind)
                             else "not found"))
    have = browsers.available()
    print("drivable          :", ", ".join(have) if have else "none")
    if not have:
        print()
        print(browsers.why_missing())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
