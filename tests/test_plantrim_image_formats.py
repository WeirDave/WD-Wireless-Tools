"""PlanTrim crops every raster format it can re-encode as itself, and names the rest.

The backlog item this closes said "Pillow already reads all three" of BMP, WBMP
and GIF. **Two of the three.** Pillow ships no WBMP codec in either direction -
asserted below against the installed Pillow rather than taken on trust - so the
item asked for something one third of which is not available, and finding that
out is most of the work. WBMP is doubly out of reach: it has no magic number
either, so only ``images.json`` can name one.

Every test here trims a real ``.esx`` end to end and then opens the image that
comes back out of the archive. A test that only asserted ``"GIF"`` appears in
``image_kind`` would pass with the whole crop path deleted - see CLAUDE.md
"A test that would pass with the feature deleted is not a test". The assertions
are: the floor was cropped, the bytes that came back are still the format that
went in, and the picture is the same picture.
"""
from __future__ import annotations

import io
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from tools import esx_trimmer as trimmer
from tools import image_format

from tests.test_esx_trimmer import (
    FLOOR_A, FLOOR_B, IMG_A, IMG_B, SCALE_A, SCALE_B,
    _drawing, _plan, make_project,
)

try:
    from PIL import Image
    HAVE_PILLOW = True
except ImportError:  # pragma: no cover - depends on environment
    HAVE_PILLOW = False


# The formats a crop can round-trip. Ekahau also accepts WBMP, which is absent
# on purpose and has a test of its own saying why.
ROUND_TRIP = ("PNG", "JPEG", "BMP", "GIF", "TIFF", "WEBP")


def _one_floor_project(path: Path, blob: bytes, *, declared_format=None) -> Path:
    """An .esx with a single floor carrying *blob* as its plan."""
    extra = None
    if declared_format is not None:
        extra = {"images.json": {"images": [
            {"id": IMG_A, "imageFormat": declared_format,
             "resolutionWidth": 400.0, "resolutionHeight": 300.0},
        ]}}
    return make_project(
        path,
        plans=[_plan(FLOOR_A, IMG_A, 400, 300, SCALE_A)],
        images={IMG_A: blob},
        extra_members=extra,
    )


def _plan_image(path: Path, image_id: str = IMG_A) -> bytes:
    with zipfile.ZipFile(path) as z:
        return z.read("image-" + image_id)


@unittest.skipUnless(HAVE_PILLOW, "Pillow is not installed")
class EveryRoundTrippableRasterIsCroppedTests(unittest.TestCase):
    """The whole point of the item: these six used to be two."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_each_format_is_cropped_and_comes_back_as_itself(self):
        for fmt in ROUND_TRIP:
            with self.subTest(fmt=fmt):
                src = _one_floor_project(self.tmp / f"in-{fmt}.esx", _drawing(fmt=fmt))
                out = self.tmp / f"out-{fmt}.esx"
                report = trimmer.trim(src, out)

                floor = report.floors[0]
                self.assertEqual(
                    floor.action, "trimmed",
                    f"{fmt} floor was {floor.action}: {floor.reason}")

                cropped = _plan_image(out)
                # It is still the format it was. A crop that quietly handed back
                # a PNG under the same image id would pass a size assertion.
                self.assertEqual(trimmer.image_kind(cropped), fmt)
                # And it is genuinely smaller than the 400x300 canvas.
                im = Image.open(io.BytesIO(cropped))
                self.assertLess(im.size[0], 400, f"{fmt} was not cropped")
                self.assertLess(im.size[1], 300, f"{fmt} was not cropped")

    def test_the_crop_keeps_the_drawing_rather_than_merely_shrinking_it(self):
        """A crop to the wrong region is still smaller. Check what survived.

        The fixture draws a rectangle outline at (120,80)-(260,210) on white.
        After the crop that outline must still be there: dark pixels on all four
        edges of the returned image, within the margin PlanTrim leaves.
        """
        for fmt in ROUND_TRIP:
            with self.subTest(fmt=fmt):
                src = _one_floor_project(self.tmp / f"ink-{fmt}.esx", _drawing(fmt=fmt))
                out = self.tmp / f"inkout-{fmt}.esx"
                trimmer.trim(src, out)

                im = Image.open(io.BytesIO(_plan_image(out))).convert("L")
                w, h = im.size
                px = im.load()
                dark = [(x, y) for y in range(h) for x in range(w) if px[x, y] < 128]
                self.assertTrue(dark, f"{fmt} crop kept no drawing at all")
                xs = [x for x, _ in dark]
                ys = [y for _, y in dark]
                # The rectangle is 140x130. Allow for the crop margin and for
                # JPEG/GIF re-encoding softening the outermost pixels.
                self.assertGreaterEqual(max(xs) - min(xs), 120,
                                        f"{fmt} lost the width of the drawing")
                self.assertGreaterEqual(max(ys) - min(ys), 110,
                                        f"{fmt} lost the height of the drawing")


@unittest.skipUnless(HAVE_PILLOW, "Pillow is not installed")
class WbmpIsRefusedByNameTests(unittest.TestCase):
    """Ekahau accepts WBMP; nothing here can crop one. Both halves are asserted."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_pillow_still_has_no_wbmp_codec(self):
        """The reason the item could not be fully delivered, asserted not assumed.

        If a future Pillow gains WBMP this fails, which is the correct moment to
        reopen the item rather than a nuisance.
        """
        Image.init()
        self.assertNotIn("WBMP", Image.OPEN)
        self.assertNotIn("WBMP", Image.SAVE)

    def test_a_wbmp_has_no_magic_number_to_sniff(self):
        # Type 0, fixed header 0, then width and height. Nothing distinguishing.
        self.assertEqual(image_format.sniff(b"\x00\x00\x90\x03\xf0\x02"), "")

    def test_the_refusal_names_the_format_from_images_json(self):
        src = _one_floor_project(
            self.tmp / "wbmp.esx", b"\x00\x00\x90\x03\xf0\x02" + b"\x00" * 900,
            declared_format="WBMP")
        report = trimmer.analyze(src)
        floor = report.floors[0]
        self.assertEqual(floor.action, "refused")
        self.assertIn("WBMP", floor.reason)
        # And not the shrug it used to be.
        self.assertNotIn("unrecognised", floor.reason)

    def test_bytes_nothing_recognises_and_nothing_declares_still_say_so(self):
        src = _one_floor_project(self.tmp / "junk.esx", b"\x00\x00" + b"\x00" * 900)
        report = trimmer.analyze(src)
        self.assertEqual(report.floors[0].action, "refused")
        self.assertIn("unrecognised", report.floors[0].reason)

    def test_a_declaration_never_beats_a_magic_number(self):
        """The bytes are what the file is. A wrong label must not win.

        This is the fault that named an SVG floor plan `.png`, pointing the
        other way: believing images.json over the bytes would refuse a perfectly
        croppable PNG because a stale declaration said WBMP.
        """
        src = _one_floor_project(self.tmp / "mislabelled.esx",
                                 _drawing(fmt="PNG"), declared_format="WBMP")
        out = self.tmp / "mislabelled-out.esx"
        report = trimmer.trim(src, out)
        self.assertEqual(report.floors[0].action, "trimmed")
        self.assertEqual(trimmer.image_kind(_plan_image(out)), "PNG")


@unittest.skipUnless(HAVE_PILLOW, "Pillow is not installed")
class MultipleFramesAreRefusedRatherThanFlattenedTests(unittest.TestCase):
    """A crop keeps frame one and drops the rest without erroring.

    That is the worst shape a loss can take - the file opens, the plan looks
    right, and whatever else was in it is gone - so it is refused instead.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _animated_gif(self) -> bytes:
        frames = []
        for shift in (0, 12):
            im = Image.new("RGB", (400, 300), "white")
            for x in range(120 + shift, 260 + shift):
                for y in range(80, 210):
                    if x in (120 + shift, 259 + shift) or y in (80, 209):
                        im.putpixel((x, y), (10, 10, 10))
            frames.append(im.convert("P"))
        buf = io.BytesIO()
        frames[0].save(buf, format="GIF", save_all=True,
                       append_images=frames[1:], duration=100)
        return buf.getvalue()

    def test_an_animated_gif_is_refused_and_says_how_many_frames(self):
        blob = self._animated_gif()
        # Guard the fixture: a single-frame GIF would make this test vacuous.
        self.assertGreater(Image.open(io.BytesIO(blob)).n_frames, 1)

        src = _one_floor_project(self.tmp / "anim.esx", blob)
        report = trimmer.analyze(src)
        floor = report.floors[0]
        self.assertEqual(floor.action, "refused")
        self.assertIn("frames", floor.reason)
        self.assertIn("GIF", floor.reason)

    def test_a_refused_floor_leaves_the_image_untouched(self):
        src = _one_floor_project(self.tmp / "anim2.esx", self._animated_gif())
        out = self.tmp / "anim2-out.esx"
        trimmer.trim(src, out)
        self.assertEqual(_plan_image(src), _plan_image(out))


@unittest.skipUnless(HAVE_PILLOW, "Pillow is not installed")
class TheCompanionRasterFollowsTheSameRuleTests(unittest.TestCase):
    """A vector plan's companion render used to be PNG-or-JPEG only."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _svg(self, w=400, h=300) -> bytes:
        return (f'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<rect x="120" y="80" width="140" height="130" fill="none" '
                f'stroke="black"/></svg>').encode("utf-8")

    def test_a_vector_plan_with_a_bmp_companion_is_cropped(self):
        plan = _plan(FLOOR_A, IMG_A, 400, 300, SCALE_A, bitmapImageId=IMG_B)
        src = make_project(
            self.tmp / "svg-bmp.esx",
            plans=[plan],
            images={IMG_A: self._svg(), IMG_B: _drawing(fmt="BMP")},
        )
        out = self.tmp / "svg-bmp-out.esx"
        report = trimmer.trim(src, out)

        self.assertEqual(report.floors[0].action, "trimmed",
                         report.floors[0].reason)
        # The companion took the same region and is still a BMP.
        companion = _plan_image(out, IMG_B)
        self.assertEqual(trimmer.image_kind(companion), "BMP")
        self.assertLess(Image.open(io.BytesIO(companion)).size[0], 400)


class TheMagicNumbersHaveOneHomeTests(unittest.TestCase):
    """Two sniffers disagreeing about what a file is, is how the .png bug shipped.

    ``folder_organizer`` names an extracted plan; ``esx_trimmer`` decides whether
    one can be cropped. They ask the same question of the same bytes, so they ask
    it in one place. This fails if either grows its own copy back.
    """

    SAMPLES = {
        "png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 16,
        "jpeg": b"\xff\xd8\xff\xe0" + b"\x00" * 16,
        "gif": b"GIF89a" + b"\x00" * 16,
        "bmp": b"BM" + b"\x00" * 16,
        "tiff": b"II*\x00" + b"\x00" * 16,
        "webp": b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 16,
        "svg": b'<?xml version="1.0"?><svg></svg>',
    }

    def test_both_modules_identify_every_sample_the_same_way(self):
        from tools import folder_organizer

        for name, blob in self.SAMPLES.items():
            with self.subTest(fmt=name):
                self.assertEqual(folder_organizer._sniff_image_format(blob), name)
                self.assertEqual(trimmer.image_kind(blob), name.upper())

    def test_the_croppable_list_is_checked_against_pillow_itself(self):
        """Not a hand-maintained list: ask the installed Pillow.

        A build missing a codec should fail here, loudly, rather than halfway
        through somebody's project.
        """
        if not HAVE_PILLOW:  # pragma: no cover - depends on environment
            self.skipTest("Pillow is not installed")
        Image.init()
        for name in image_format.CROPPABLE_RASTERS:
            with self.subTest(fmt=name):
                self.assertIn(name.upper(), Image.OPEN)
                self.assertIn(name.upper(), Image.SAVE)

    def test_svg_is_not_in_the_raster_list(self):
        """It is cropped by moving its viewBox, not by re-encoding pixels."""
        self.assertNotIn("svg", image_format.CROPPABLE_RASTERS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
