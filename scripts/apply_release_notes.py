"""Put a committed release note onto its GitHub release.

A release note lives at ``docs/releases/vX.Y.Z.md`` and is published by
committing it. ``auto-release.yml`` publishes a short stub, because the
commit message is the better record and the wrong document to publish; the
hand-written note replaced it only when somebody ran ``gh release edit`` on a
machine that had ``gh``. That is a step to remember, and this repository has
already measured what happens to steps that have to be remembered.

``.github/workflows/release-notes.yml`` runs this twice over: on a push that
changes a note (the release usually exists already), and when a release build
finishes (the note may have been committed first). Both converge on the same
question - is there a note for this tag, and does the release exist - so the
order the two arrive in does not matter.

Usage::

    apply_release_notes.py --changed BEFORE AFTER   # notes changed in a push
    apply_release_notes.py --tag v2.175.3           # one tag, if it has a note

A note whose release does not exist yet is skipped, not an error: the release
build will pick it up when it finishes.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTES_DIR = "docs/releases"
TAG_RE = re.compile(r"^v\d+(\.\d+)+$")
ZERO_SHA = "0" * 40


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, capture_output=True,
                          encoding="utf-8", check=check)


def changed_notes(before: str, after: str) -> list[str]:
    """Tags whose note was added or changed between two commits."""
    if not before or before == ZERO_SHA:
        before = f"{after}~1"
    out = _run("git", "diff", "--name-only", "--diff-filter=AM",
               before, after, "--", NOTES_DIR).stdout
    tags = []
    for line in out.splitlines():
        p = Path(line)
        if p.parent.as_posix() == NOTES_DIR and p.suffix == ".md" \
                and TAG_RE.match(p.stem):
            tags.append(p.stem)
    return sorted(set(tags))


def apply(tag: str) -> str:
    """Replace the notes on ``tag``'s release. Returns what happened."""
    if not TAG_RE.match(tag):
        raise ValueError(f"not a release tag: {tag!r}")
    note = ROOT / NOTES_DIR / f"{tag}.md"
    if not note.is_file():
        return f"{tag}: no note committed - left as it is"
    if _run("gh", "release", "view", tag, check=False).returncode != 0:
        return f"{tag}: no release yet - the release build will apply it"
    _run("gh", "release", "edit", tag, "--notes-file", str(note))
    return f"{tag}: notes applied from {NOTES_DIR}/{tag}.md"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--changed", nargs=2, metavar=("BEFORE", "AFTER"))
    g.add_argument("--tag")
    a = ap.parse_args(argv)
    tags = changed_notes(*a.changed) if a.changed else [a.tag]
    for tag in tags:
        print(apply(tag))
    if not tags:
        print("No release notes changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
