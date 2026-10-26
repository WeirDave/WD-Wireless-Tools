"""A test that skips when a library is missing is only a test if CI installs it.

`test_dev_toolbar_does_not_print.py` reads back the PDF Firefox prints with
PyMuPDF and skips when the import fails. Nothing listed PyMuPDF, so on every
runner it skipped and was reported as a pass - the same way around three
hundred browser tests once were until `selenium` was added to
`requirements-dev.txt`.

This lists the third-party libraries that tests import behind a skip, and
requires each to be in `requirements-dev.txt` (or `requirements.txt`, for the
ones the product also needs). A new entry here is a decision that the runner
carries that library.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

#: import name -> the distribution that provides it
OPTIONAL_TEST_IMPORTS = {
    "pymupdf": "pymupdf",
    "selenium": "selenium",
}


def _requirement_names() -> set:
    names = set()
    for name in ("requirements.txt", "requirements-dev.txt"):
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(re.split(r"[<>=!~\[; ]", line, 1)[0].lower())
    return names


class WhatATestImportsIsInstalledInCi(unittest.TestCase):

    def test_every_library_a_test_skips_without_is_listed(self):
        listed = _requirement_names()
        used = set()
        for path in TESTS.glob("*.py"):
            if path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8")
            for module in OPTIONAL_TEST_IMPORTS:
                if re.search(rf"^\s*(?:import|from)\s+{module}\b", text, re.M):
                    used.add(module)
        missing = [OPTIONAL_TEST_IMPORTS[m] for m in sorted(used)
                   if OPTIONAL_TEST_IMPORTS[m] not in listed]
        self.assertEqual([], missing,
                         "tests import these but no requirements file lists them, "
                         "so CI skips the tests that need them")

    def test_the_list_is_not_empty(self):
        """The check above would pass vacuously if nothing were found."""
        listed = _requirement_names()
        self.assertIn("selenium", listed)
        self.assertIn("pymupdf", listed)


if __name__ == "__main__":
    unittest.main()
