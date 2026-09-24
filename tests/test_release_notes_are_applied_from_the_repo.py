"""A committed note reaches its release, and nothing else is touched.

``scripts/apply_release_notes.py`` is driven against a scratch git repository
with a stand-in ``gh`` that records every call it receives, so what is
asserted is the edit that would reach GitHub: which tag, which file.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import apply_release_notes as arn  # noqa: E402

FAKE_GH = """#!/bin/sh
echo "$*" >> "$GH_LOG"
if [ "$1 $2" = "release view" ]; then
  case " $GH_RELEASES " in *" $3 "*) exit 0 ;; esac
  exit 1
fi
exit 0
"""


@unittest.skipIf(os.name == "nt", "the stand-in gh is a POSIX shell script")
class ApplyReleaseNotesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        (self.repo / "docs" / "releases").mkdir(parents=True)
        bin_dir = base / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)
        self.log = base / "gh.log"
        self.log.write_text("", encoding="utf-8")
        self.env = patch.dict(os.environ, {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GH_LOG": str(self.log),
            "GH_RELEASES": "v9.1.0 v9.2.0",
        })
        self.env.start()
        self.root = patch.object(arn, "ROOT", self.repo)
        self.root.start()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.base_sha = self.commit({"README.md": "x"})

    def tearDown(self):
        self.root.stop()
        self.env.stop()
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True,
                              capture_output=True, encoding="utf-8").stdout.strip()

    def commit(self, files):
        for rel, text in files.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            self.git("add", rel)
        self.git("commit", "-q", "-m", "c")
        return self.git("rev-parse", "HEAD")

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines()

    def test_a_pushed_note_is_applied_to_its_release(self):
        after = self.commit({"docs/releases/v9.1.0.md": "# note"})
        arn.main(["--changed", self.base_sha, after])
        note = self.repo / "docs" / "releases" / "v9.1.0.md"
        self.assertIn(f"release edit v9.1.0 --notes-file {note}", self.calls())

    def test_only_the_notes_in_the_push_are_touched(self):
        mid = self.commit({"docs/releases/v9.1.0.md": "# old"})
        after = self.commit({"docs/releases/v9.2.0.md": "# new",
                             "docs/releases/README.md": "not a note"})
        arn.main(["--changed", mid, after])
        edits = [c for c in self.calls() if c.startswith("release edit")]
        self.assertEqual(len(edits), 1)
        self.assertTrue(edits[0].startswith("release edit v9.2.0 "))

    def test_a_note_for_an_unreleased_version_waits_rather_than_fails(self):
        after = self.commit({"docs/releases/v9.3.0.md": "# early"})
        self.assertEqual(arn.main(["--changed", self.base_sha, after]), 0)
        self.assertFalse([c for c in self.calls() if c.startswith("release edit")])

    def test_the_finished_release_build_applies_a_note_committed_first(self):
        self.commit({"docs/releases/v9.2.0.md": "# waiting"})
        arn.main(["--tag", "v9.2.0"])
        self.assertTrue(any(c.startswith("release edit v9.2.0 ")
                            for c in self.calls()))

    def test_a_release_without_a_committed_note_keeps_its_note(self):
        arn.main(["--tag", "v9.1.0"])
        self.assertEqual(self.calls(), [])

    def test_a_first_push_with_no_before_commit_still_works(self):
        after = self.commit({"docs/releases/v9.1.0.md": "# note"})
        arn.main(["--changed", "0" * 40, after])
        self.assertTrue(any(c.startswith("release edit v9.1.0 ")
                            for c in self.calls()))

    def test_something_that_is_not_a_tag_is_refused(self):
        with self.assertRaises(ValueError):
            arn.apply("v1; rm -rf /")


if __name__ == "__main__":
    unittest.main()
