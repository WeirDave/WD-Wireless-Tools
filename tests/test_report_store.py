"""Report settings and cover image storage.

The point of these is less the happy path than the location: a cover image that
lands anywhere inside the install tree is destroyed by the next update, which is
the exact trap the wall templates already had to be dug out of.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import report_store, settings as suite_settings  # noqa: E402
from tools import updater  # noqa: E402


PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'


class ReportStoreLocationTests(unittest.TestCase):
    """Where the files live is the part an update can get wrong."""

    def test_report_assets_live_in_the_protected_user_data_dir(self):
        cfg = updater.CONFIG
        self.assertEqual(
            report_store.REPORT_DIR.parent.resolve(),
            cfg.user_data_dir.resolve(),
            "cover images must sit directly under the updater's user_data_dir",
        )
        self.assertEqual(
            suite_settings.SETTINGS_FILE.parent.resolve(),
            cfg.user_data_dir.resolve(),
            "settings.json must sit under the updater's user_data_dir",
        )

    def test_report_assets_are_not_inside_the_install_tree(self):
        # Both update paths rewrite the install tree; anything under it is lost.
        install = Path(updater.__file__).resolve().parents[1]
        for path in (report_store.REPORT_DIR, suite_settings.SETTINGS_FILE):
            with self.assertRaises(ValueError, msg=f"{path} is inside the install tree"):
                path.resolve().relative_to(install)

    def test_report_dir_is_not_a_payload_target(self):
        cfg = updater.CONFIG
        # An update replaces these wholesale, so the report directory must not
        # share a name with any of them.
        self.assertNotIn("report", cfg.payload_dirs)
        self.assertNotIn(report_store.REPORT_DIR.name, cfg.payload_files)


class ReportSettingsDefaultsTests(unittest.TestCase):
    def test_report_section_carries_the_report_defaults(self):
        rep = suite_settings.DEFAULTS["report"]
        for key in ("client_name", "prepared_by", "project_ref", "revision"):
            self.assertIn(key, rep)
        self.assertIs(rep["include_revision_in_filename"], True)

    def test_report_defaults_survive_a_round_trip(self, ):
        import copy, json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            patch = {"report": {"client_name": "Acme", "revision": "v2.0",
                                "include_revision_in_filename": False}}
            out = suite_settings.update_settings(patch, _path=path)
            self.assertEqual(out["report"]["client_name"], "Acme")
            self.assertEqual(out["report"]["revision"], "v2.0")
            self.assertIs(out["report"]["include_revision_in_filename"], False)
            # untouched keys keep their defaults rather than disappearing
            self.assertEqual(out["report"]["prepared_by"], "")
            reloaded = suite_settings.load_settings(_path=path)
            self.assertEqual(reloaded["report"]["revision"], "v2.0")


class CoverValidationTests(unittest.TestCase):
    def setUp(self):
        self._orig = report_store.REPORT_DIR
        self._tmp = __import__("tempfile").TemporaryDirectory()
        report_store.REPORT_DIR = Path(self._tmp.name) / "report"

    def tearDown(self):
        report_store.REPORT_DIR = self._orig
        self._tmp.cleanup()

    def test_accepts_the_documented_formats(self):
        for data, ext in ((PNG, ".png"), (JPEG, ".jpg"), (GIF, ".gif"),
                          (WEBP, ".webp"), (SVG, ".svg")):
            res = report_store.save_cover(data, "cover" + ext)
            self.assertTrue(res.get("ok"), res)
            self.assertTrue(res["name"].endswith(ext), res["name"])

    def test_extension_comes_from_the_bytes_not_the_name(self):
        # A PNG named .jpg is still stored as a PNG; a hostile name cannot pick
        # where this lands.
        res = report_store.save_cover(PNG, "payload.jpg")
        self.assertTrue(res["ok"])
        self.assertTrue(res["name"].endswith(".png"))

    def test_rejects_a_non_image(self):
        res = report_store.save_cover(b"just some text, not an image", "notes.txt")
        self.assertFalse(res["ok"])
        self.assertIn("notes.txt", res["error"])

    def test_rejects_an_empty_file(self):
        self.assertFalse(report_store.save_cover(b"", "empty.png")["ok"])

    def test_rejects_an_oversized_file(self):
        big = PNG + b"\x00" * report_store.MAX_COVER_BYTES
        res = report_store.save_cover(big, "huge.png")
        self.assertFalse(res["ok"])
        self.assertIn("MB", res["error"])

    def test_replacing_with_another_format_leaves_one_file(self):
        report_store.save_cover(PNG, "a.png")
        report_store.save_cover(JPEG, "b.jpg")
        found = sorted(p.name for p in report_store.REPORT_DIR.glob("cover.*"))
        self.assertEqual(found, ["cover.jpg"])

    def test_a_rejected_upload_leaves_the_existing_image_alone(self):
        report_store.save_cover(PNG, "good.png")
        report_store.save_cover(b"nope", "bad.txt")
        self.assertTrue(report_store.cover_info()["exists"])
        self.assertTrue(report_store.cover_path().name.endswith(".png"))

    def test_delete_removes_it(self):
        report_store.save_cover(PNG, "a.png")
        res = report_store.delete_cover()
        self.assertTrue(res["ok"])
        self.assertFalse(report_store.cover_info()["exists"])

    def test_info_reports_absence_without_erroring(self):
        info = report_store.cover_info()
        self.assertTrue(info["ok"])
        self.assertFalse(info["exists"])


if __name__ == "__main__":
    unittest.main()
