"""A ZIP update does not delete a template the user edited or added.

A git install keeps an edited shipped template because git knows what the
shipped copy was. A ZIP install replaced the whole `templates/` folder, so a
template edited in place - or one the user dropped into that folder - went with
it. Each ZIP install now writes down what it shipped, and the next update keeps
whatever differs, copying it into the user's own folder where the app reads it
in preference to a shipped one.

Every test runs the real update (`zip_update`, with the network replaced by a
release built here) against a throwaway install and a throwaway user folder,
then asks those folders what is in them.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import updater

TEMPLATE = "Brick_walltemplate.json"


def _write_tree(cfg, root: Path, version: str, templates: dict):
    for name in cfg.payload_files:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{version} {name}", encoding="utf-8")
    for name in cfg.payload_dirs:
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "marker.txt").write_text(version, encoding="utf-8")
    (root / "web" / "assets").mkdir(parents=True, exist_ok=True)
    (root / "web" / "assets" / "versions.json").write_text(
        json.dumps({"suite": version}), encoding="utf-8")
    for name, text in templates.items():
        (root / "templates" / name).write_text(text, encoding="utf-8")


class _Install(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-zipkeep-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.install = self.tmp / "install"
        self.userdir = self.tmp / "user"
        self.userdir.mkdir()
        self.cfg = replace(updater.CONFIG, install_root=self.install,
                           user_data_dir=self.userdir)

    def _release(self, version: str, templates: dict) -> tuple[Path, Path]:
        tree = self.tmp / f"release-{version}"
        _write_tree(self.cfg, tree, version, templates)
        archive = self.tmp / f"release-{version}.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for p in tree.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(tree).as_posix())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        return archive, digest

    def _update_to(self, version: str, templates: dict):
        archive, digest = self._release(version, templates)
        tag = f"v{version}"
        name = self.cfg.asset_name(tag)
        release = {"version": version, "tag": tag,
                   "assets": {name: "https://example.test/a",
                              name + ".sha256": "https://example.test/b"}}

        def download(url, dest):
            if url.endswith("/b"):
                Path(dest).write_text(digest + "  " + name, encoding="utf-8")
            else:
                shutil.copyfile(archive, dest)

        with mock.patch.object(updater, "fetch_latest_release",
                               lambda cfg=None, timeout=None: release), \
                mock.patch.object(updater, "_download", download):
            return updater.zip_update(self.install, cfg=self.cfg)

    def _installed(self, name=TEMPLATE) -> str:
        return (self.install / "templates" / name).read_text("utf-8")

    def _kept(self, name=TEMPLATE) -> Path:
        return self.userdir / "templates" / name


class AnEditedTemplateSurvivesTests(_Install):

    def test_a_template_edited_in_place_is_kept_as_the_users_copy(self):
        _write_tree(self.cfg, self.install, "1.0.0", {TEMPLATE: "shipped"})
        updater.record_shipped_files(self.install, "1.0.0", self.cfg)
        (self.install / "templates" / TEMPLATE).write_text("my edit", "utf-8")

        result = self._update_to("1.1.0", {TEMPLATE: "shipped, improved"})

        self.assertEqual([TEMPLATE], result["rescuedTemplates"])
        self.assertEqual("my edit", self._kept().read_text("utf-8"))
        self.assertEqual("shipped, improved", self._installed(),
                         "the release's own copy is what is installed")

    def test_a_template_nobody_edited_is_not_copied_and_takes_the_release(self):
        _write_tree(self.cfg, self.install, "1.0.0", {TEMPLATE: "shipped"})
        updater.record_shipped_files(self.install, "1.0.0", self.cfg)

        result = self._update_to("1.1.0", {TEMPLATE: "shipped, improved"})

        self.assertEqual([], result["rescuedTemplates"])
        self.assertFalse(self._kept().exists(),
                         "an unedited template must not pin the old version")
        self.assertEqual("shipped, improved", self._installed())

    def test_a_copy_the_user_already_has_is_not_overwritten(self):
        _write_tree(self.cfg, self.install, "1.0.0", {TEMPLATE: "shipped"})
        updater.record_shipped_files(self.install, "1.0.0", self.cfg)
        (self.install / "templates" / TEMPLATE).write_text("older edit", "utf-8")
        self._kept().parent.mkdir(parents=True)
        self._kept().write_text("newer personal copy", "utf-8")

        self._update_to("1.1.0", {TEMPLATE: "x"})

        self.assertEqual("newer personal copy", self._kept().read_text("utf-8"))

    def test_the_next_update_compares_against_what_this_one_shipped(self):
        _write_tree(self.cfg, self.install, "1.0.0", {TEMPLATE: "shipped"})
        updater.record_shipped_files(self.install, "1.0.0", self.cfg)
        self._update_to("1.1.0", {TEMPLATE: "v1.1 text"})
        # Nothing was edited since 1.1.0, so 1.2.0 must not treat the changed
        # file as an edit.
        result = self._update_to("1.2.0", {TEMPLATE: "v1.2 text"})
        self.assertEqual([], result["rescuedTemplates"])
        self.assertEqual("v1.2 text", self._installed())


class ATemplateTheUserAddedSurvivesTests(_Install):

    def test_a_file_the_release_does_not_ship_is_kept_even_with_no_record(self):
        # An install made before the record existed: only a file the release
        # does not contain can be told apart from a shipped one.
        _write_tree(self.cfg, self.install, "1.0.0",
                    {TEMPLATE: "shipped", "Mine_walltemplate.json": "mine"})

        result = self._update_to("1.1.0", {TEMPLATE: "shipped, improved"})

        self.assertEqual(["Mine_walltemplate.json"], result["rescuedTemplates"])
        self.assertEqual("mine", self._kept("Mine_walltemplate.json")
                         .read_text("utf-8"))
        self.assertFalse(self._kept().exists())

    def test_a_record_for_another_version_is_not_trusted(self):
        _write_tree(self.cfg, self.install, "1.0.0", {TEMPLATE: "shipped"})
        updater.record_shipped_files(self.install, "0.9.0", self.cfg)
        (self.install / "templates" / TEMPLATE).write_text("edit", "utf-8")

        result = self._update_to("1.1.0", {TEMPLATE: "improved"})

        # Without a record that matches, an edit cannot be told from a release
        # change, so nothing that the release also ships is kept.
        self.assertEqual([], result["rescuedTemplates"])


class AFailedKeepStopsTheUpdateTests(_Install):

    def test_nothing_is_replaced_when_the_copy_cannot_be_made(self):
        _write_tree(self.cfg, self.install, "1.0.0", {TEMPLATE: "shipped"})
        updater.record_shipped_files(self.install, "1.0.0", self.cfg)
        (self.install / "templates" / TEMPLATE).write_text("my edit", "utf-8")

        with mock.patch.object(updater.shutil, "copy2",
                               side_effect=OSError("disk full")):
            with self.assertRaises(updater.UpdateError) as caught:
                self._update_to("1.1.0", {TEMPLATE: "improved"})

        self.assertTrue(caught.exception.intact)
        self.assertEqual("my edit", self._installed())
        self.assertEqual("1.0.0", updater.local_version(self.install, self.cfg))



class TheKeepIsCallableOnItsOwnTests(_Install):

    def test_rescue_zip_edits_returns_what_it_kept_and_says_so(self):
        _write_tree(self.cfg, self.install, "1.0.0", {TEMPLATE: "shipped"})
        updater.record_shipped_files(self.install, "1.0.0", self.cfg)
        (self.install / "templates" / TEMPLATE).write_text("my edit", "utf-8")
        new_tree = self.tmp / "new"
        _write_tree(self.cfg, new_tree, "1.1.0", {TEMPLATE: "improved"})
        said = []

        kept = updater.rescue_zip_edits(self.install, new_tree, "1.0.0",
                                        self.cfg, said.append)

        self.assertEqual([TEMPLATE], kept)
        self.assertEqual("my edit", self._kept().read_text("utf-8"))
        self.assertTrue(said and TEMPLATE in said[0], said)

    def test_nothing_is_kept_when_there_is_nothing_to_keep(self):
        _write_tree(self.cfg, self.install, "1.0.0", {TEMPLATE: "shipped"})
        updater.record_shipped_files(self.install, "1.0.0", self.cfg)
        new_tree = self.tmp / "new"
        _write_tree(self.cfg, new_tree, "1.1.0", {TEMPLATE: "improved"})
        self.assertEqual([], updater.rescue_zip_edits(
            self.install, new_tree, "1.0.0", self.cfg))

if __name__ == "__main__":
    unittest.main()
