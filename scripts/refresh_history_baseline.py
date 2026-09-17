"""Record what the published history already carries, so new additions fail.

The history guard is a ratchet, not a gate. Making it fail on what is already
committed would pin CI red until somebody rewrote published history - which is
a decision for the repository's owner, taken deliberately, not something to be
forced by a test landing on a Tuesday. So the known findings are enumerated
here by object id, the guard ignores exactly those, and anything new fails
immediately.

Two properties follow, and both are the point:

* a commit that adds workplace data to a message or a file **cannot land**
* the outstanding debt is a file you can read, with a count in it, instead of
  a thing somebody has to remember

Run it after a deliberate history rewrite, and the file should get shorter.
If it ever gets longer without a very good reason, that is the ratchet
slipping.

    python scripts/refresh_history_baseline.py

**It records object ids only.** No value from the history is written into it -
the whole problem is values that got published, and a baseline quoting them
would publish them again in a tracked file.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import history_scan                      # noqa: E402
from tests.test_no_real_world_data import (         # noqa: E402
    BASELINE_PATH, detect_findings,
)


def main() -> int:
    if not history_scan.git_available():
        print("not a git checkout - nothing to record")
        return 1

    messages = history_scan.scan_commit_messages("HEAD", detect_findings)
    blobs = history_scan.scan_blobs("HEAD", detect_findings)

    payload = {
        "_readme": (
            "Findings already present in published history, by object id. "
            "The history guard ignores exactly these and fails on anything "
            "else, so new workplace data cannot be committed while the "
            "existing debt stays visible. Regenerate with "
            "scripts/refresh_history_baseline.py. Object ids only - never "
            "values."
        ),
        "recorded": date.today().isoformat(),
        "commit_messages": sorted(messages),
        "blobs": sorted(blobs),
        "counts": {
            "commit_messages": len(messages),
            "blobs": len(blobs),
            "paths": len({p for b in blobs.values() for p in b["paths"]}),
        },
    }
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n",
                             encoding="utf-8")
    print("recorded %d commit message(s) and %d blob(s) across %d path(s)"
          % (payload["counts"]["commit_messages"],
             payload["counts"]["blobs"], payload["counts"]["paths"]))
    print("written to", BASELINE_PATH.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
