"""Every tracked text file is stored with LF, whatever is on disk.

A 32-line change to `cloud.js` arrived as a **20,434-line diff** - the whole
file deleted and re-added - because the blob went in with CRLF while `main`
holds LF. Nothing failed. The suite was green, the file was correct, and the
change was unreadable in the history and would have conflicted with every
other session touching that file.

**`core.autocrlf` does not stop this**, which is the part worth knowing. It
is a filter on `git add`, and the content-staging route this repository uses
when two sessions share a file -

    git hash-object -w --stdin

- bypasses every filter unless it is given `--path`. So the safeguard is off
  exactly where the tree is most contended.

`.gitattributes` is not a counter-example either. `*.bat text eol=crlf` is a
**checkout** instruction: the working tree gets CRLF and the blob stays LF.
So the invariant is total and needs no allowlist - at the time this was
written all 506 text blobs in the tree were LF, batch files included.

This reads the **index**, not `HEAD`, so a staged file is checked before it
is committed rather than after. In a clean checkout the two are the same,
which is what CI sees.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Git's own rule for deciding a file is not text.
BINARY_SNIFF = 8000


def _git(*args: str) -> bytes:
    return subprocess.run(("git",) + args, cwd=ROOT,
                          capture_output=True, check=True).stdout


def staged_blobs():
    """(path, sha) for everything in the index, as one call rather than one
    per file - there are several hundred and a process each is a minute."""
    out = _git("ls-files", "-s", "-z").decode("utf-8").split("\0")
    for line in out:
        if not line:
            continue
        meta, _, path = line.partition("\t")
        mode, sha, _stage = meta.split()
        if mode == "160000":            # a submodule has no blob
            continue
        yield path, sha


def blob_bodies(pairs):
    """Read every blob in one `cat-file --batch`, in the order asked for."""
    pairs = list(pairs)
    if not pairs:
        return
    spec = "".join(sha + "\n" for _path, sha in pairs).encode()
    out = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT,
                         input=spec, capture_output=True, check=True).stdout
    at = 0
    for path, _sha in pairs:
        end = out.index(b"\n", at)
        header = out[at:end].decode("utf-8", "replace").split()
        if len(header) != 3 or header[1] != "blob":
            at = end + 1
            continue
        size = int(header[2])
        yield path, out[end + 1:end + 1 + size]
        at = end + 1 + size + 1         # the trailing newline batch adds


class EveryTrackedFileIsStoredWithLf(unittest.TestCase):

    def test_no_staged_text_blob_holds_a_carriage_return(self):
        offenders = []
        for path, body in blob_bodies(staged_blobs()):
            if b"\x00" in body[:BINARY_SNIFF]:
                continue                # git would call this binary too
            if b"\r" in body:
                offenders.append((path, body.count(b"\r\n"),
                                  body.count(b"\r") - body.count(b"\r\n")))
        self.assertEqual(
            [], offenders,
            "these files are stored with carriage returns while the rest of "
            "the repository is stored with LF, so a small edit to one of them "
            "will be committed as a whole-file rewrite - "
            "(path, CRLF count, lone CR count): %s\n"
            "Convert the blob rather than the working tree: read it, replace "
            "\r+\n with \n, and re-stage it." % (offenders,))

    def test_the_check_is_actually_looking_at_something(self):
        """A batch reader that silently returns nothing passes the test above
        on any tree at all, which is the failure this file exists to catch one
        layer up. So it is asserted that blobs were really read, and that
        their contents are the ones on disk."""
        bodies = dict(blob_bodies(staged_blobs()))
        self.assertGreater(len(bodies), 100,
                           "the index read returned almost nothing")
        self.assertIn("README.md", bodies)
        self.assertEqual(
            (ROOT / "README.md").read_bytes().replace(b"\r\n", b"\n"),
            bodies["README.md"].replace(b"\r\n", b"\n"),
            "the blob read back is not the file it names")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
