"""The vendored libraries are the ones `web/assets/lib/VENDORED.md` says.

They had no record at all: no version list, so a library could be years old and
nothing would say so - `mammoth.browser.min.js` carries no version banner and
its version could not be read from the file. Now each file's SHA-256 is in the
manifest, and a file that changes without the manifest changing fails here.

Where a file states its own version, that is checked too, so the table cannot
name one version while the file is another.
"""
from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "web" / "assets" / "lib"
MANIFEST = LIB / "VENDORED.md"

def _rows():
    rows = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.fullmatch(r"[0-9a-f]{64}", cells[3]):
            rows.append({"name": cells[0], "version": cells[1],
                         "file": cells[2], "sha256": cells[3]})
    return rows


class TheVendoredLibrariesMatchTheManifestTests(unittest.TestCase):

    def test_the_manifest_lists_every_library_file(self):
        listed = {r["file"] for r in _rows()}
        on_disk = {p.name for p in LIB.iterdir()
                   if p.is_file() and p.suffix in (".js", ".mjs")}
        self.assertEqual(on_disk, listed,
                         "a file in web/assets/lib is not in VENDORED.md, or "
                         "the other way round")

    def test_each_file_hashes_to_what_the_manifest_says(self):
        for row in _rows():
            with self.subTest(file=row["file"]):
                # Line endings normalised: a Windows checkout converts LF to
                # CRLF, and the manifest holds the hash of the file as
                # published (and as stored in git).
                data = (LIB / row["file"]).read_bytes().replace(b"\r\n", b"\n")
                actual = hashlib.sha256(data).hexdigest()
                self.assertEqual(
                    row["sha256"], actual,
                    f"{row['file']} changed without VENDORED.md changing")

    def test_a_version_the_file_states_is_the_version_listed(self):
        by_file = {r["file"]: r for r in _rows()}
        banner = (LIB / "jszip.min.js").read_bytes()[:400]
        want = ("JSZip v" + by_file["jszip.min.js"]["version"]).encode()
        self.assertTrue(want in banner, "jszip.min.js does not state the "
                                        "version the manifest lists")
        for name in ("pdf.min.mjs", "pdf.worker.min.mjs"):
            want = ('"%s"' % by_file[name]["version"]).encode()
            self.assertTrue(want in (LIB / name).read_bytes(),
                            f"{name} does not state version "
                            f"{by_file[name]['version']}")


if __name__ == "__main__":
    unittest.main()
