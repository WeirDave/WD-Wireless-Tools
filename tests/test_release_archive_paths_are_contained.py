"""A release archive cannot write outside the folder it is extracted into.

Found in the security pass of 2026-09-20. `updater.py` checked containment with
a **string prefix** - ``str(target).startswith(str(extract.resolve()))`` - where
every other containment check in this codebase asks `relative_to`:
`_is_inside` in `folder_organizer`, `_assert_inside` in `cloud_manager`.

A prefix accepts a sibling whose name merely begins with the root's. A member
of ``../extracted-elsewhere/x`` resolves outside ``extracted`` and still starts
with the string ``.../extracted``, so it passed.

**It was not independently exploitable, and that is worth stating plainly** so
nobody reads this file as a near-miss. The archive is checksummed against the
`.sha256` published beside it on the same release, so getting a hostile member
as far as the extractor means already controlling the release - and a
controlled release can simply ship a hostile payload without any path trick.
What made it worth fixing is that it was the wrong question, in the one place
that asked it differently from everywhere else.

**The fix then shipped a worse defect than the one it fixed, past a green
suite**, and that is the more useful half of this file. It opened with
``root = extract.resolve()`` - the obvious name, and the wrong one, because
``root`` is `zip_update`'s *install* root, the folder the payload is copied
into forty lines further down. Everything after that line then pointed at the
staging directory: the payload was copied onto itself, the backup was a copy of
staging, and the install folder was never touched at all. ``finally`` deleted
the lot.

Restoring that line and running the tests below is how the symptom was
established rather than guessed. On Windows it raises ``Install failed partway
through: [WinError 32]`` and tells the user their previous copy is intact at a
path inside the temp directory that is deleted two lines later - so the message
naming the recovery point is itself wrong. Where that rename succeeds it is
worse, because the call returns ``changed: true`` carrying the new version
number and the install is untouched: told they were updated, still on the
version they started on.

Nothing caught it because **nothing had ever run `zip_update`** - the one
function that replaces a user's install had no test at all.
`TheRealUpdateRunsTests` below runs it and asks where the files went, which is
the only question that separates those two outcomes.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest import mock

from tools import updater


def contained(member: str, extract: Path) -> bool:
    """The check as `updater.py` now makes it."""
    target = (extract / member).resolve()
    try:
        target.relative_to(extract.resolve())
        return True
    except ValueError:
        return False


def contained_by_prefix(member: str, extract: Path) -> bool:
    """The check as it was, kept so the difference is demonstrable."""
    target = (extract / member).resolve()
    return str(target).startswith(str(extract.resolve()))


class TheContainmentCheckRefusesWhatItShouldTests(unittest.TestCase):
    """The rule on its own, at the level of one member name.

    `TheRealUpdateRunsTests` drives the same rule through `zip_update`; these
    enumerate the member shapes, which is cheaper here than building an archive
    per case.
    """

    def setUp(self):
        # Not created on disk: `resolve()` is pure-lexical for a path that does
        # not exist, which is what the check relies on, and creating them would
        # only add cleanup.
        self.extract = Path("C:/staging/extracted") if Path("C:/").exists() \
            else Path("/tmp/staging/extracted")

    def test_an_ordinary_member_is_allowed(self):
        for member in ("tools/updater.py", "web/home.html",
                       "docs/USER_MANUAL.md", "server.py"):
            with self.subTest(member=member):
                self.assertTrue(contained(member, self.extract))

    def test_a_climbing_member_is_refused(self):
        for member in ("../evil.py", "../../evil.py",
                       "tools/../../evil.py", "a/b/../../../evil.py"):
            with self.subTest(member=member):
                self.assertFalse(contained(member, self.extract))

    def test_a_sibling_that_starts_with_the_root_name_is_refused(self):
        """The case the string prefix let through.

        `extracted-elsewhere` begins with `extracted`, so the old check saw a
        path inside the root where there was none.
        """
        for member in ("../extracted-elsewhere/evil.py",
                       "../extracted2/evil.py",
                       "../extractedbackup/payload.py"):
            with self.subTest(member=member):
                self.assertFalse(contained(member, self.extract),
                                 "a sibling directory was accepted")

    def test_the_old_check_really_did_let_those_through(self):
        """Otherwise the three above prove nothing.

        A test for a fixed defect is worth having only if the defect can be
        shown; without this the sibling cases could be passing because nothing
        ever reached them.
        """
        let_through = [m for m in ("../extracted-elsewhere/evil.py",
                                   "../extracted2/evil.py",
                                   "../extractedbackup/payload.py")
                       if contained_by_prefix(m, self.extract)]
        self.assertEqual(3, len(let_through),
                         "the prefix form no longer accepts these, so this "
                         "test has stopped describing a real difference")

    def test_an_absolute_member_is_refused(self):
        """Some archivers store one; `Path('/x') / '/abs'` keeps the absolute."""
        member = "C:/Windows/System32/evil.dll" if Path("C:/").exists() \
            else "/etc/cron.d/evil"
        self.assertFalse(contained(member, self.extract))


class TheRealUpdateRunsTests(unittest.TestCase):
    """`zip_update` driven end to end, because nothing drove it before.

    Two network calls are replaced - `fetch_latest_release` and `_download` -
    and nothing else. The archive, the checksum, the extraction, the payload
    validation, the backup and the copy into the install folder are the real
    ones, so "did the update happen" is answered by looking at the install
    folder rather than at a return value the code also writes.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-ziptest-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.install = self.tmp / "install"
        self.cfg = replace(updater.CONFIG, install_root=self.install)
        self._make_tree(self.install, "1.0.0")
        # Something only the old copy has, so "did it change" is answerable
        # without reading a version number this test also wrote.
        (self.install / "web" / "old-marker.txt").write_text("old", "utf-8")

    def _make_tree(self, root: Path, version: str):
        for name in self.cfg.payload_files:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("payload " + name, encoding="utf-8")
        for name in self.cfg.payload_dirs:
            (root / name).mkdir(parents=True, exist_ok=True)
            (root / name / "keep.txt").write_text(version, encoding="utf-8")
        vp = root / self.cfg.version_path
        vp.parent.mkdir(parents=True, exist_ok=True)
        vp.write_text(json.dumps({self.cfg.version_key: version}),
                      encoding="utf-8")

    def _release_zip(self, version="1.1.0", extra_members=()):
        payload = self.tmp / ("payload-" + version)
        self._make_tree(payload, version)
        (payload / "web" / "new-marker.txt").write_text("new", encoding="utf-8")
        zip_path = self.tmp / ("release-" + version + ".zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            for path in sorted(payload.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(payload).as_posix())
            for member in extra_members:
                zf.writestr(member, "print('hostile')")
        return zip_path

    def _run(self, zip_path):
        tag = "v1.1.0"
        asset = self.cfg.asset_name(tag)
        release = {"version": "1.1.0", "tag": tag,
                   "assets": {asset: "https://example.invalid/" + asset,
                              asset + ".sha256": "https://example.invalid/sum"}}

        def fake_download(url, dest):
            if url.endswith("/sum"):
                dest.write_text(updater._sha256(zip_path) + "  " + asset,
                                encoding="utf-8")
            else:
                shutil.copy2(zip_path, dest)

        with mock.patch.object(updater, "fetch_latest_release",
                               return_value=release):
            with mock.patch.object(updater, "_download", fake_download):
                return updater.zip_update(root=self.install, cfg=self.cfg)

    # -- the install really moves -------------------------------------------

    def test_the_payload_lands_in_the_install_and_not_in_staging(self):
        """The assertion the shadowing bug fails.

        It asks the install folder rather than the return value, which is the
        whole point: under the bug the version number really did change, in a
        directory that was deleted a moment later.
        """
        result = self._run(self._release_zip())
        self.assertTrue(result["changed"])
        self.assertTrue((self.install / "web" / "new-marker.txt").is_file(),
                        "the new payload never reached the install folder")
        self.assertEqual(
            "1.1.0",
            json.loads((self.install / self.cfg.version_path)
                       .read_text(encoding="utf-8"))[self.cfg.version_key])

    def _copies_beside_the_install(self):
        return [p for p in self.install.parent.iterdir()
                if p.name.startswith(self.install.name + ".previous-v")]

    def test_the_backup_is_a_copy_of_the_install_rather_than_of_staging(self):
        """A backup that does not hold what it replaced is worse than none.

        It is the copy somebody reaches for, so its being wrong is discovered
        only at the moment it is needed - which is an install that failed
        partway, the one case the copy is still kept for.
        """
        real_move = shutil.move
        calls = []

        def move_then_fail(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("disk full")
            return real_move(src, dst)

        with mock.patch.object(updater.shutil, "move", move_then_fail):
            with self.assertRaises(updater.UpdateError) as ctx:
                self._run(self._release_zip())
        copies = self._copies_beside_the_install()
        self.assertEqual(1, len(copies), copies)
        self.assertIn(str(copies[0]), str(ctx.exception),
                      "the error does not say where the intact copy is")
        self.assertTrue((copies[0] / "web" / "old-marker.txt").is_file(),
                        "the backup does not hold the copy being replaced")

    def test_a_successful_update_leaves_no_copy_behind(self):
        result = self._run(self._release_zip())
        self.assertTrue(result["changed"])
        self.assertIsNone(result["backup"])
        self.assertEqual([], self._copies_beside_the_install())

    def test_an_update_that_is_already_current_changes_nothing(self):
        self._make_tree(self.install, "1.1.0")
        result = self._run(self._release_zip())
        self.assertFalse(result["changed"])
        self.assertFalse((self.install / "web" / "new-marker.txt").exists())

    def test_a_checksum_mismatch_refuses_the_download(self):
        zip_path = self._release_zip()
        other = self._release_zip(version="1.1.0-other")
        tag = "v1.1.0"
        asset = self.cfg.asset_name(tag)
        release = {"version": "1.1.0", "tag": tag,
                   "assets": {asset: "https://example.invalid/" + asset,
                              asset + ".sha256": "https://example.invalid/sum"}}

        def fake_download(url, dest):
            if url.endswith("/sum"):
                dest.write_text(updater._sha256(other) + "  x", encoding="utf-8")
            else:
                shutil.copy2(zip_path, dest)

        with mock.patch.object(updater, "fetch_latest_release",
                               return_value=release):
            with mock.patch.object(updater, "_download", fake_download):
                with self.assertRaises(updater.UpdateError) as caught:
                    updater.zip_update(root=self.install, cfg=self.cfg)
        self.assertIn("Checksum mismatch", str(caught.exception))
        self.assertFalse((self.install / "web" / "new-marker.txt").exists())

    # -- and a hostile member stops it --------------------------------------

    def test_a_climbing_member_refuses_the_whole_update(self):
        zip_path = self._release_zip(extra_members=["../escaped.py"])
        with self.assertRaises(updater.UpdateError) as caught:
            self._run(zip_path)
        self.assertIn("unsafe path", str(caught.exception))

    def test_nothing_is_written_anywhere_when_a_member_is_refused(self):
        """Checked before `extractall`, so not one member is written.

        Checking as it went would leave a half-replaced install, which for an
        update is the worst of the three outcomes.
        """
        zip_path = self._release_zip(extra_members=["../escaped.py"])
        with self.assertRaises(updater.UpdateError):
            self._run(zip_path)
        self.assertFalse((self.install / "web" / "new-marker.txt").exists())
        self.assertTrue((self.install / "web" / "old-marker.txt").is_file())
        self.assertEqual(
            "1.0.0",
            json.loads((self.install / self.cfg.version_path)
                       .read_text(encoding="utf-8"))[self.cfg.version_key])

    def test_a_sibling_that_starts_with_the_root_name_is_refused_for_real(self):
        """The case the string prefix accepted, through the real function."""
        zip_path = self._release_zip(
            extra_members=["../extracted-elsewhere/evil.py"])
        with self.assertRaises(updater.UpdateError):
            self._run(zip_path)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
