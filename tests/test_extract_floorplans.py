"""Extracted floor plans must open in whatever the extension claims they are.

Reported as "extract floorplans not working, the png seems to be invalid", and
that is exactly what it was: intact bytes with a lying filename.

Floor plan images live inside an .esx as `image-<uuid>` with no extension, and
they are not all PNG. The sniffer knew PNG, JPEG, GIF, WEBP, BMP and TIFF, and
fell back to `.png` for anything else - so an SVG floor plan, which is text and
has no magic number, was written out as an XML document called `.png`. Every
image viewer refuses it. Across the user's projects that was 11 floor plans,
including one in live work.

The write path was never at fault: `Path.write_bytes` is binary, and the
extracted bytes were verified byte-identical to the archive member before any
of this changed. Distinguishing the two mattered - a text-mode bug and a naming
bug present identically, and only one of them was real.

So there is no `.png` fallback any more. A recognised magic number wins; where
the bytes say nothing, `imageFormat` from images.json is believed, which is the
only way to name a format that cannot be sniffed at all; and where neither can
say, the file is `.bin` rather than a confident wrong name.
"""
from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tools.folder_organizer import (FolderOrganizer, _image_ext_from_bytes,
                                    _sniff_image_format)

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d76360000000020001e221bc330000000049454e44ae426082")
JPEG_HEAD = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
SVG_DOC = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
           b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
           b'<rect width="10" height="10"/></svg>')
GIF_HEAD = b"GIF89a\x01\x00\x01\x00"
BMP_HEAD = b"BM\x36\x00\x00\x00\x00\x00\x00\x00"


class SnifferTests(unittest.TestCase):
    def test_svg_is_recognised(self):
        """The whole bug: this used to return "" and fall through to .png."""
        self.assertEqual(_sniff_image_format(SVG_DOC[:64]), "svg")
        self.assertEqual(_image_ext_from_bytes(SVG_DOC), ".svg")

    def test_an_svg_without_the_xml_declaration_is_recognised(self):
        self.assertEqual(_sniff_image_format(b'<svg xmlns="x"></svg>'), "svg")

    def test_a_byte_order_mark_does_not_hide_an_svg(self):
        self.assertEqual(_sniff_image_format(b"\xef\xbb\xbf" + SVG_DOC[:40]), "svg")

    def test_leading_whitespace_does_not_hide_an_svg(self):
        self.assertEqual(_sniff_image_format(b"\n  " + SVG_DOC[:40]), "svg")

    def test_the_raster_formats_still_work(self):
        for blob, ext in ((PNG_1PX, ".png"), (JPEG_HEAD, ".jpg"),
                          (GIF_HEAD, ".gif"), (BMP_HEAD, ".bmp")):
            with self.subTest(ext=ext):
                self.assertEqual(_image_ext_from_bytes(blob), ext)

    def test_the_declaration_names_a_format_that_cannot_be_sniffed(self):
        """WBMP is on Ekahau's supported list and has no magic number."""
        self.assertEqual(_image_ext_from_bytes(b"\x00\x00\x08\x08junk", "WBMP"), ".wbmp")

    def test_the_bytes_beat_the_declaration_when_they_disagree(self):
        """The bytes are what the file is; the declaration is only a claim."""
        self.assertEqual(_image_ext_from_bytes(PNG_1PX, "JPEG"), ".png")

    def test_unidentifiable_bytes_are_not_called_png(self):
        """The old .png fallback is what produced the unopenable files."""
        self.assertEqual(_image_ext_from_bytes(b"\x01\x02\x03\x04nonsense"), ".bin")
        self.assertEqual(_image_ext_from_bytes(b"\x01\x02\x03\x04", "MYSTERY"), ".bin")


def build_esx(path: Path, floors) -> Path:
    """*floors* is a list of dicts: name, blob, format, optional bitmap blob."""
    plans, images, members = [], [], {}
    for i, f in enumerate(floors):
        fid, iid = f"floor-{i}", f"img-{i}"
        plan = {"id": fid, "name": f["name"], "imageId": iid,
                "width": 100.0, "height": 100.0, "metersPerUnit": 0.05}
        images.append({"id": iid, "imageFormat": f["format"],
                       "resolutionWidth": 100.0, "resolutionHeight": 100.0})
        members["image-" + iid] = f["blob"]
        if f.get("bitmap"):
            bid = f"bmp-{i}"
            plan["bitmapImageId"] = bid
            images.append({"id": bid, "imageFormat": f["bitmap_format"],
                           "resolutionWidth": 400.0, "resolutionHeight": 400.0})
            members["image-" + bid] = f["bitmap"]
        plans.append(plan)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("version", "1.0")
        z.writestr("project.json", json.dumps({"project": {"id": "p1"}}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": plans}))
        z.writestr("images.json", json.dumps({"images": images}))
        for name, blob in members.items():
            z.writestr(name, blob)
    return path


class ExtractTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.out = self.base / "out"
        self.fo = FolderOrganizer()

    def extract(self, floors):
        esx = build_esx(self.base / "p.esx", floors)
        ids = [f"floor-{i}" for i in range(len(floors))]
        res = self.fo.extract_floorplans(str(esx), floor_ids=ids, out_dir=str(self.out))
        self.assertTrue(res["ok"], res.get("error"))
        return res, {p.name: p for p in self.out.iterdir()}

    def test_an_svg_floor_plan_comes_out_as_svg(self):
        res, files = self.extract([
            {"name": "Level 1", "blob": SVG_DOC, "format": "SVG"}])
        self.assertIn("Level 1.svg", files)
        self.assertNotIn("Level 1.png", files)
        ET.fromstring(files["Level 1.svg"].read_bytes())   # must parse

    def test_a_png_floor_plan_still_comes_out_as_png(self):
        res, files = self.extract([
            {"name": "Level 1", "blob": PNG_1PX, "format": "PNG"}])
        self.assertIn("Level 1.png", files)

    def test_a_jpeg_floor_plan_is_not_called_png(self):
        res, files = self.extract([
            {"name": "Level 1", "blob": JPEG_HEAD, "format": "JPEG"}])
        self.assertIn("Level 1.jpg", files)

    def test_the_bytes_on_disk_are_the_bytes_in_the_archive(self):
        """The write path was never the bug; this keeps it that way."""
        res, files = self.extract([
            {"name": "Level 1", "blob": SVG_DOC, "format": "SVG"},
            {"name": "Level 2", "blob": PNG_1PX, "format": "PNG"}])
        self.assertEqual(files["Level 1.svg"].read_bytes(), SVG_DOC)
        self.assertEqual(files["Level 2.png"].read_bytes(), PNG_1PX)

    def test_a_raster_companion_is_extracted_alongside_the_vector(self):
        """An SVG plan usually carries a raster render; both are wanted."""
        res, files = self.extract([{
            "name": "Level 1", "blob": SVG_DOC, "format": "SVG",
            "bitmap": JPEG_HEAD, "bitmap_format": "JPEG"}])
        self.assertIn("Level 1.svg", files)
        self.assertIn("Level 1 (raster).jpg", files)
        self.assertEqual(res["written_count"], 2)

    def test_the_companion_is_named_so_the_two_are_told_apart(self):
        res, files = self.extract([{
            "name": "Level 1", "blob": SVG_DOC, "format": "SVG",
            "bitmap": JPEG_HEAD, "bitmap_format": "JPEG"}])
        names = {w["name"] for w in res["written"]}
        self.assertEqual(names, {"Level 1", "Level 1 (raster)"})

    def test_a_plan_whose_bitmap_is_its_own_image_is_not_written_twice(self):
        esx = self.base / "same.esx"
        build_esx(esx, [{"name": "Level 1", "blob": PNG_1PX, "format": "PNG"}])
        with zipfile.ZipFile(esx) as z:
            members = {n: z.read(n) for n in z.namelist()}
        doc = json.loads(members["floorPlans.json"])
        doc["floorPlans"][0]["bitmapImageId"] = doc["floorPlans"][0]["imageId"]
        members["floorPlans.json"] = json.dumps(doc).encode()
        with zipfile.ZipFile(esx, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in members.items():
                z.writestr(n, b)
        res = self.fo.extract_floorplans(str(esx), floor_ids=["floor-0"],
                                         out_dir=str(self.out))
        self.assertEqual(res["written_count"], 1)

    def test_files_are_named_for_the_floor_not_the_uuid(self):
        res, files = self.extract([
            {"name": "22.APT.03 - One Marina", "blob": PNG_1PX, "format": "PNG"}])
        self.assertTrue(any(f.startswith("22.APT.03") for f in files), files)
        self.assertFalse(any(f.startswith("image-") for f in files))

    def test_a_missing_image_is_reported_once_not_silently_skipped(self):
        esx = self.base / "gone.esx"
        build_esx(esx, [{"name": "Level 1", "blob": PNG_1PX, "format": "PNG"}])
        with zipfile.ZipFile(esx) as z:
            members = {n: z.read(n) for n in z.namelist() if not n.startswith("image-")}
        with zipfile.ZipFile(esx, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in members.items():
                z.writestr(n, b)
        res = self.fo.extract_floorplans(str(esx), floor_ids=["floor-0"],
                                         out_dir=str(self.out))
        self.assertEqual(res["written_count"], 0)
        self.assertEqual(res["error_count"], 1)

    def test_an_unknown_format_lands_as_bin_rather_than_a_broken_png(self):
        res, files = self.extract([
            {"name": "Level 1", "blob": b"\x07\x07\x07\x07mystery", "format": "MYSTERY"}])
        self.assertIn("Level 1.bin", files)
        self.assertNotIn("Level 1.png", files)


if __name__ == "__main__":
    unittest.main()
