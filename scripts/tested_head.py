"""Name the pull request commit whose CI run already tested this exact tree.

``auto-release.yml`` used to run the whole four-job suite on every version
bump, after the pull request carrying that bump had already run the same suite
on the same code. That second run is roughly 27 minutes and it is the whole of
the wait between a merge and a release.

It may be skipped only when the tree being released is **provably the tree
that was tested**, not merely a tree with the same changes in it. A pull
request's CI run tests GitHub's merge ref, ``merge(base-at-the-time, head)``,
so this answers yes in exactly two shapes:

* **A merge commit whose tree is its second parent's tree, and whose first
  parent is an ancestor of that second parent.** The branch already contained
  everything main had, so the merge added nothing, and the merge ref the pull
  request tested was that same tree.
* **A single-parent commit** - a fast-forward, or a direct push. The commit is
  its own candidate, and only a successful pull-request run recorded against
  that exact commit can vouch for it; a direct push to main has none, and runs
  the suite as before.

Anything else prints nothing, and the release runs the suite. The workflow
then asks GitHub whether a *successful* pull-request run of ``tests.yml``
exists for the commit printed here; a failed, cancelled or missing run means
the suite runs. Every error on either side falls toward testing.

Usage::

    tested_head.py <sha>     # prints the candidate commit, or nothing
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(("git", *args), cwd=cwd, capture_output=True,
                          encoding="utf-8")


def _tree(sha: str, cwd: Path) -> str:
    r = _git("rev-parse", f"{sha}^{{tree}}", cwd=cwd)
    return r.stdout.strip() if r.returncode == 0 else ""


def candidate(sha: str, cwd: Path = ROOT) -> str:
    """The commit a pull-request run would have to have tested, or ''."""
    r = _git("rev-list", "--parents", "-n", "1", sha, cwd=cwd)
    if r.returncode != 0:
        return ""
    ids = r.stdout.split()
    if len(ids) == 2:
        return ids[0]
    if len(ids) != 3:
        return ""
    commit, first, second = ids
    here = _tree(commit, cwd)
    if not here or here != _tree(second, cwd):
        return ""
    if _git("merge-base", "--is-ancestor", first, second,
            cwd=cwd).returncode != 0:
        return ""
    return second


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: tested_head.py <sha>", file=sys.stderr)
        return 2
    found = candidate(args[0])
    if found:
        print(found)
    return 0


if __name__ == "__main__":
    sys.exit(main())
