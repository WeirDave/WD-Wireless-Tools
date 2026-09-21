"""The ZIP update path, driven end to end, with nothing left to trust.

**This path had no test at all**, which is why the hole in it survived: the
suite had thirty-odd tests about detecting which kind of install this is and
none that ran an install. It is also the path he updates from in the morning,
so the first thing here is the ordinary case - a release with a valid checksum
lands, and the files on disk afterwards are the ones out of the archive.

The finding it was written for: ``zip_update`` warned and carried on when a
release published **no** ``.sha256`` asset. CLAUDE.md said the updater
"refuses a download whose checksum does not match", and that was true for a
mismatch and not for an absence - which is the case that matters, because
whoever can serve the ZIP has no reason to serve a manifest beside it. The
same branch existed in ``install.ps1`` and ``install.sh``.

Nothing here reaches the network. ``fetch_latest_release`` and ``_download``
are replaced with a fake release served out of a temp directory, so the whole
of ``zip_update`` runs - download, verify, extract, validate payload, back up,
install - against a real archive built by ``scripts/build_release.py``.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import updater

TAG = "v9.9.9"
VERSION = "9.9.9"
ASSET = f"WD-Wireless-Tools-{TAG}.zip"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


class ZipUpdateHarness(unittest.TestCase):
    """A whole fake install, a whole fake release, and no network."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-zipupd-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.install = self.tmp / "install"
        self.serve = self.tmp / "serve"
        self.serve.mkdir(parents=True)

        # A payload small enough to read in a failure message and complete
        # enough for _validate_payload, which is the step that decides whether
        # what arrived is a release at all.
        self.cfg = updater.CONFIG.__class__(
            name="Test App",
            repo="example/test-app",
            install_root=self.install,
            version_path="web/assets/versions.json",
            version_key="suite",
            asset_template="WD-Wireless-Tools-{tag}.zip",
            payload_files=("server.py",),
            payload_dirs=("tools", "web"),
            user_data_dir=self.tmp / "userdata",
        )

        self._write_tree(self.install, "1.0.0", marker="old")
        self.archive = self._build_archive("2.0.0", marker="new")

    # ── fixtures ────────────────────────────────────────────────

    def _write_tree(self, root: Path, version: str, marker: str):
        (root / "tools").mkdir(parents=True, exist_ok=True)
        (root / "web" / "assets").mkdir(parents=True, exist_ok=True)
        (root / "server.py").write_text(f"# {marker}\n", encoding="utf-8")
        (root / "tools" / "thing.py").write_text(f"# {marker}\n", encoding="utf-8")
        (root / "web" / "assets" / "versions.json").write_text(
            json.dumps({"suite": version}), encoding="utf-8")

    def _build_archive(self, version: str, marker: str) -> Path:
        staging = self.tmp / f"stage-{marker}"
        self._write_tree(staging, version, marker)
        out = self.serve / ASSET
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(staging.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(staging).as_posix())
        return out

    def _release(self, *, with_checksum=True, checksum_text=None):
        assets = {ASSET: "http://example.invalid/" + ASSET}
        if with_checksum:
            sums = self.serve / (ASSET + ".sha256")
            sums.write_text(
                checksum_text if checksum_text is not None
                else f"{_sha256(self.archive)}  {ASSET}\n",
                encoding="utf-8")
            assets[ASSET + ".sha256"] = "http://example.invalid/" + ASSET + ".sha256"
        return {"tag": TAG, "version": "2.0.0", "assets": assets, "notes": ""}

    def _run(self, release):
        """Drive the real zip_update with the network replaced by the temp dir."""
        def fake_download(url, dest):
            name = url.rsplit("/", 1)[-1]
            src = self.serve / name
            if not src.is_file():
                raise updater.UpdateError(f"Download failed (HTTP 404): {url}")
            shutil.copyfile(src, dest)

        said = []
        with mock.patch.object(updater, "fetch_latest_release",
                               return_value=release), \
             mock.patch.object(updater, "_download", fake_download):
            return updater.zip_update(root=self.install, log=said.append,
                                      cfg=self.cfg), said

    def installed_marker(self):
        return (self.install / "server.py").read_text(encoding="utf-8").strip()

    def installed_version(self):
        return json.loads(
            (self.install / "web" / "assets" / "versions.json")
            .read_text(encoding="utf-8"))["suite"]


class AVerifiedReleaseStillInstalls(ZipUpdateHarness):
    """The regression guard. He installs from this path in the morning.

    Tightening the checksum rule is worth nothing if it also refuses the
    release that *is* signed, so this runs first and asserts on the files
    afterwards rather than on the return value alone.
    """

    def test_a_release_with_a_valid_checksum_installs(self):
        result, said = self._run(self._release())
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["changed"])
        self.assertEqual("2.0.0", result["newVersion"])
        self.assertEqual("1.0.0", result["previousVersion"])

    def test_the_files_on_disk_are_the_ones_out_of_the_archive(self):
        self._run(self._release())
        self.assertEqual("# new", self.installed_marker())
        self.assertEqual("2.0.0", self.installed_version())
        self.assertEqual(
            "# new",
            (self.install / "tools" / "thing.py").read_text(encoding="utf-8").strip())

    def test_the_previous_install_is_kept_beside_it(self):
        result, _ = self._run(self._release())
        backup = Path(result["backup"])
        self.assertTrue(backup.is_dir(), f"no backup at {backup}")
        self.assertEqual(
            "# old",
            (backup / "server.py").read_text(encoding="utf-8").strip())

    def test_it_says_the_checksum_was_verified(self):
        _, said = self._run(self._release())
        self.assertIn("Checksum verified.", said)


class AnUnverifiableReleaseIsRefused(ZipUpdateHarness):
    """The finding. Absence and mismatch are the same answer now."""

    def assert_nothing_was_installed(self):
        self.assertEqual("# old", self.installed_marker())
        self.assertEqual("1.0.0", self.installed_version())

    def test_no_checksum_published_refuses(self):
        with self.assertRaises(updater.UpdateError) as caught:
            self._run(self._release(with_checksum=False))
        self.assertIn("no checksum", str(caught.exception).lower())
        self.assert_nothing_was_installed()

    def test_the_refusal_says_what_to_do_about_it(self):
        """A refusal he cannot act on is a dead end.

        This fires on a release whose asset build failed part-way, which is a
        state this repository has genuinely been in, so the message has to
        name the releases page rather than only reporting the fault.
        """
        with self.assertRaises(updater.UpdateError) as caught:
            self._run(self._release(with_checksum=False))
        self.assertIn(self.cfg.releases_url, str(caught.exception))

    def test_a_checksum_that_does_not_match_refuses(self):
        with self.assertRaises(updater.UpdateError) as caught:
            self._run(self._release(checksum_text="0" * 64 + f"  {ASSET}\n"))
        self.assertIn("mismatch", str(caught.exception).lower())
        self.assert_nothing_was_installed()

    def test_a_malformed_checksum_file_refuses(self):
        with self.assertRaises(updater.UpdateError) as caught:
            self._run(self._release(checksum_text="not a hash at all\n"))
        self.assertIn("malformed", str(caught.exception).lower())
        self.assert_nothing_was_installed()

    def test_a_checksum_asset_that_cannot_be_fetched_refuses(self):
        """Listed but unreachable is still unverified.

        The API says the asset exists and the download of it fails. Carrying
        on here would reopen the hole from the other side.
        """
        release = self._release()
        (self.serve / (ASSET + ".sha256")).unlink()
        with self.assertRaises(updater.UpdateError):
            self._run(release)
        self.assert_nothing_was_installed()


class AnUnsafeArchiveIsRefused(ZipUpdateHarness):
    """The zip-slip guard, driven rather than read.

    CPython's own ``extractall`` drops ``..`` components before writing, which
    is why the audit recorded this as not currently exploitable. The guard is
    still the thing that is supposed to say no, and it said yes to a sibling
    directory - ``../extracted-elsewhere/x`` resolves outside ``extracted``
    and passed a ``startswith`` test. See
    ``tests/test_one_answer_about_containment.py``.
    """

    def _archive_with_member(self, member_name: str) -> Path:
        out = self.serve / ASSET
        out.unlink(missing_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("server.py", "# new\n")
            z.writestr("tools/thing.py", "# new\n")
            z.writestr("web/assets/versions.json", json.dumps({"suite": "2.0.0"}))
            z.writestr(member_name, "payload\n")
        self.archive = out
        return out

    def test_a_member_climbing_out_of_the_staging_tree_is_refused(self):
        self._archive_with_member("../escaped.txt")
        with self.assertRaises(updater.UpdateError) as caught:
            self._run(self._release())
        self.assertIn("unsafe path", str(caught.exception).lower())

    def test_a_member_landing_in_a_sibling_with_a_shared_prefix_is_refused(self):
        """The exact shape the old guard let through.

        ``extracted-elsewhere`` begins with ``extracted``, so the string
        comparison said it was inside the staging directory. It is not.
        """
        self._archive_with_member("../extracted-elsewhere/escaped.txt")
        with self.assertRaises(updater.UpdateError) as caught:
            self._run(self._release())
        self.assertIn("unsafe path", str(caught.exception).lower())

    def test_an_absolute_member_is_refused(self):
        self._archive_with_member("/etc/escaped.txt")
        with self.assertRaises(updater.UpdateError) as caught:
            self._run(self._release())
        self.assertIn("unsafe path", str(caught.exception).lower())


if __name__ == "__main__":
    unittest.main()
