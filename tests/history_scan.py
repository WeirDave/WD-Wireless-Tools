"""Scan git history for the same things the working-tree guard scans for.

`test_no_real_world_data.py` reads `git ls-files` - the tree checked out right
now. That is the whole product as shipped, and it is not the whole exposure:
the repository is public, so **every commit message and every blob ever
committed is published too**, and none of that was ever being checked.

It matters because it already happened. A survey on 2026-09-17 found
site-code-shaped tokens surviving in blobs on `main` and in commit messages -
including the message of the very commit that removed them from the files,
which is the "scrub without quoting" trap: a commit message that names the
identifier it just deleted republishes it.

**This module only finds things. It never prints them.** Callers get counts,
object ids and paths, so a failing test can say where to look without putting
the value back in a log, a CI transcript or a terminal scrollback.

Kept next to the test rather than in `tools/` on purpose: it is test support,
not product code, and `tools/` ships in the release payload.
"""
from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Blobs worth reading as text. A history scan walks every version of every
#: file ever committed, so this is about keeping the run short as much as
#: about correctness.
TEXT_SUFFIXES = (".py", ".js", ".html", ".css", ".md", ".json", ".txt",
                 ".yml", ".yaml", ".ps1", ".sh", ".bat", ".command")

#: Vendored bundles are somebody else's code and full of minified noise.
SKIP_PREFIXES = ("web/assets/lib/",)

#: A blob larger than this is a bundle or a data dump, not prose.
MAX_BLOB_BYTES = 400_000

#: The git identity on a commit is the author's own, and the Co-Authored-By
#: trailer is machine-generated. Neither is workplace data, and both would
#: otherwise flag on every single commit.
_TRAILER = re.compile(
    r"^(Co-Authored-By|Co-authored-by|Signed-off-by|Reported-by):.*$", re.M)


def git_available() -> bool:
    try:
        out = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=str(ROOT),
                             capture_output=True, timeout=30)
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _git(*args: str, binary: bool = False, timeout: int = 300):
    out = subprocess.run(["git"] + list(args), cwd=str(ROOT),
                         capture_output=True, timeout=timeout)
    if out.returncode != 0:
        return b"" if binary else ""
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def message_body(raw: str) -> str:
    """A commit message with the machine-written identity lines removed."""
    return _TRAILER.sub("", raw)


def scan_commit_messages(rev: str, detect) -> dict:
    """{short sha: {category: count}} for every commit reachable from `rev`.

    `detect(text) -> {category: set_of_values}` is passed in so this module
    never has to hold a copy of the rules; the guard owns those.
    """
    # `%x00` asks git to *emit* a NUL. Passing a literal one as a command
    # argument is a ValueError on Windows, and a NUL cannot occur inside a
    # commit message - so it is the one separator the scanned text cannot
    # forge. The `%`s here are git's placeholders, not Python's.
    raw = _git("log", "--format=%x00%H%n%B", rev)
    found = {}
    for chunk in raw.split("\x00"):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        sha, _, body = chunk.partition("\n")
        sha = sha.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        hits = detect(message_body(body))
        if hits:
            found[sha[:8]] = {c: len(v) for c, v in hits.items()}
    return found


def _interesting(path: str) -> bool:
    low = path.lower()
    if any(path.startswith(p) for p in SKIP_PREFIXES):
        return False
    return low.endswith(TEXT_SUFFIXES)


def scan_blobs(rev: str, detect) -> dict:
    """{short blob sha: {"paths": [...], "categories": {cat: count}}}.

    Blobs are read through a single `git cat-file --batch` process. One
    subprocess per blob is minutes; this is seconds, and history scanning is
    only worth having if it is cheap enough to leave switched on.
    """
    listing = _git("rev-list", "--objects", rev).splitlines()
    wanted: dict[str, set[str]] = defaultdict(set)
    for line in listing:
        sha, _, path = line.partition(" ")
        if not path or not _interesting(path):
            continue
        wanted[sha].add(path)
    if not wanted:
        return {}

    proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=str(ROOT),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        payload = ("\n".join(wanted) + "\n").encode("ascii")
        out, _ = proc.communicate(payload, timeout=600)
    finally:
        if proc.poll() is None:
            proc.kill()

    found: dict[str, dict] = {}
    pos = 0
    while pos < len(out):
        nl = out.find(b"\n", pos)
        if nl < 0:
            break
        header = out[pos:nl].decode("ascii", "replace").split()
        pos = nl + 1
        if len(header) < 3:
            continue
        sha, _kind, size = header[0], header[1], int(header[2])
        body, pos = out[pos:pos + size], pos + size + 1
        if size > MAX_BLOB_BYTES or b"\0" in body[:2048]:
            continue
        hits = detect(body.decode("utf-8", "replace"))
        if hits:
            found[sha[:8]] = {
                "paths": sorted(wanted.get(sha, ())),
                "categories": {c: len(v) for c, v in hits.items()},
            }
    return found
