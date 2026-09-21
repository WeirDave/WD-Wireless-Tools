"""What lands in somebody's install folder, and what deliberately does not.

Backlog item 11. `build_release.py` ships whole directories - `tools`, `web`,
`templates`, `docs` - which is the right default and means a directory added
later is included without anybody having to remember. The cost is that a
directory added for the maintainers is included too, silently, and nothing
said so.

Three of the four are entirely user-facing. `docs` is the one that is not:

* `USER_MANUAL.md` and `wall-types.md` are what somebody who downloaded a
  wireless tool wants.
* `docs/releases` is 168 files of internal changelog, and was already excluded
  with the reasoning written beside it.
* `docs/audits` is a 718-line whole-tool engineering audit, and
  `docs/reverse-engineering` is three browser capture scripts and a README
  about Ekahau's undocumented API. Both shipped in every ZIP until v2.156.0
  for no reason other than that nobody looked after `releases` was excluded.

**This is tidiness rather than exposure**, and the difference is worth keeping
straight so nobody escalates it later. The repository is public, so none of it
is secret; the audit was checked for reported speech and carries none; and
`test_no_real_world_data.py` already reads every tracked file, so there is
nothing of his sites or colleagues in any of it.

The check is the *shape* of the payload rather than a list of filenames, so
adding a page or a tool does not fail it and adding a directory of internal
notes does.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_release  # noqa: E402


def payload_relative():
    """Every shipped path, relative to the repository root, posix-style.

    `iter_release_files` yields `(source, relative)` - the second is the name
    the file takes inside the ZIP, which is the one that matters here.
    """
    return [Path(relative).as_posix()
            for _source, relative in build_release.iter_release_files()]


class TheDownloadCarriesOnlyWhatAReaderWantsTests(unittest.TestCase):

    def setUp(self):
        self.files = payload_relative()
        self.docs = [f for f in self.files if f.startswith("docs/")]

    def test_the_payload_is_not_empty(self):
        """A guard over a payload that failed to build would pass on nothing."""
        self.assertGreater(len(self.files), 50, self.files[:5])

    def test_the_user_manual_ships(self):
        self.assertIn("docs/USER_MANUAL.md", self.docs)

    def test_the_wall_type_reference_ships(self):
        """It explains the values in the shipped template, so it belongs with
        the template."""
        self.assertIn("docs/wall-types.md", self.docs)

    def test_no_internal_engineering_notes_ship(self):
        strays = [f for f in self.docs
                  if f.split("/")[1] in ("audits", "releases", "reverse-engineering")]
        self.assertEqual(
            [], strays,
            "these are notes for whoever maintains this, not for whoever "
            "downloaded it: " + ", ".join(strays))

    def test_docs_ships_files_rather_than_directories_of_them(self):
        """The rule, stated as a rule: anything under `docs/` that is filed in
        a subdirectory is internal until somebody says otherwise.

        Written this way round on purpose. A list of allowed filenames fails
        every time the manual gains a companion; this fails when a *directory*
        appears, which is the thing that has twice turned out to be internal.
        """
        nested = sorted({f.split("/")[1] for f in self.docs if f.count("/") > 1})
        self.assertEqual(
            [], nested,
            "a new directory under docs/ is in the download. If it is for the "
            "reader, add it to this test; if it is for the maintainers, add it "
            "to EXCLUDED_DIRECTORY_PARTS in scripts/build_release.py: "
            + ", ".join(nested))

    def test_the_three_code_directories_still_ship(self):
        """The exclusion must not have caught anything it should not."""
        for top in ("tools", "web", "templates"):
            with self.subTest(directory=top):
                self.assertTrue(any(f.startswith(top + "/") for f in self.files),
                                "nothing ships from " + top)

    def test_the_wall_template_is_still_in_the_download(self):
        """It is the one file in `templates/` he would notice missing."""
        self.assertTrue(
            any(f.startswith("templates/") and f.endswith(".json")
                for f in self.files),
            "no wall template in the payload")


class TheExclusionIsDeclaredWhereItIsReadableTests(unittest.TestCase):

    def test_the_excluded_directories_are_named(self):
        self.assertEqual({"releases", "audits", "reverse-engineering"},
                         build_release.EXCLUDED_DIRECTORY_PARTS)

    def test_excluding_a_directory_really_removes_it(self):
        """The mechanism, not just the constant.

        `EXCLUDED_DIRECTORY_PARTS` matching on any path *part* is what makes it
        work at any depth, and is also what would make a careless entry - say
        "web" - empty the payload. This checks the removal happens and that it
        is the only thing that happened.
        """
        before = set(payload_relative())
        original = build_release.EXCLUDED_DIRECTORY_PARTS
        build_release.EXCLUDED_DIRECTORY_PARTS = original | {"templates"}
        try:
            after = set(payload_relative())
        finally:
            build_release.EXCLUDED_DIRECTORY_PARTS = original
        removed = before - after
        self.assertTrue(removed, "excluding a directory removed nothing")
        self.assertTrue(all(f.startswith("templates/") for f in removed),
                        "it removed something else as well: "
                        + ", ".join(sorted(removed - {f for f in removed
                                                      if f.startswith("templates/")})))
        self.assertEqual(set(), after - before, "it added something")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
