"""A vector plan keeps the page behind its drawing when it is cropped.

A crop of an SVG moves its viewBox. A length written as a percentage is a
percentage of the viewBox, so a white page drawn at ``width="100%"`` from the
origin stopped covering a window that no longer started at the origin, and the
drawing was left on transparency - grey lines on black wherever the plan was
shown on something dark. The drawing itself was never touched, which is why the
same file can also be put right afterwards.

These hold three things: a crop resolves page percentages to the lengths they
stood for, a file an earlier crop left behind is repaired when it is saved
again, and a percentage measured against anything other than the page is
refused rather than guessed. The last class renders the result in a real
browser, because "the attribute says 1000" is not the same claim as "the plan
is white".
"""
from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import time
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from tests import browsers as _browsers
from tools import esx_trimmer as trimmer

from tests.test_esx_trimmer import FLOOR_A, IMG_A, SCALE_A, _plan, make_project

try:
    from PIL import Image
    HAVE_PILLOW = True
except ImportError:  # pragma: no cover - depends on environment
    HAVE_PILLOW = False

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

ROOT = Path(__file__).resolve().parents[1]
PLANTRIM_JS = ROOT / "web" / "assets" / "js" / "plantrim.js"
NODE_TIMEOUT_S = 120

W, H = 1000, 750
BOX = [550, 400, 950, 700]
DRAWING = (b'<g stroke="#808080" fill="none" stroke-width="3">'
           b'<rect x="600" y="450" width="300" height="200"/>'
           b'<line x1="600" y1="550" x2="900" y2="550"/></g>')
PAGE_100 = b'<rect width="100%" height="100%" fill="white"/>'


def _svg(inner: bytes, root: bytes = b'width="1000" height="750"') -> bytes:
    return (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
            + root + b">" + inner + b"</svg>")


# What every crop before the fix wrote for BOX: the viewBox moved to where the
# crop started, the percentages left as they were.
LEFT_BY_AN_EARLIER_TRIM = _svg(
    PAGE_100 + DRAWING, b'width="400" height="300" viewBox="550 400 400 300"')


def _project(path: Path, blob: bytes, w=W, h=H) -> Path:
    return make_project(path, plans=[_plan(FLOOR_A, IMG_A, w, h, SCALE_A)],
                        images={IMG_A: blob})


def _image(path: Path) -> bytes:
    with zipfile.ZipFile(path) as z:
        return z.read("image-" + IMG_A)


class ACropKeepsThePage(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _crop(self, blob, box=BOX, w=W, h=H):
        src = _project(self.tmp / "in.esx", blob, w, h)
        rep = trimmer.trim(src, self.tmp / "out.esx", boxes={FLOOR_A: box})
        self.assertEqual(rep.floors[0].action, "trimmed", rep.floors[0].reason)
        return _image(self.tmp / "out.esx")

    def test_a_page_at_100_percent_becomes_the_page_it_was(self):
        out = self._crop(_svg(PAGE_100 + DRAWING))
        self.assertIn(b'viewBox="550 400 400 300"', out)
        self.assertIn(b'<rect width="1000" height="750" fill="white"/>', out)
        self.assertNotIn(b"%", out.split(b"?>", 1)[1])

    def test_the_drawing_is_copied_through_untouched(self):
        out = self._crop(_svg(PAGE_100 + DRAWING))
        self.assertTrue(out.endswith(DRAWING + b"</svg>"))

    def test_percentages_are_of_the_viewbox_where_there_is_one(self):
        """User units that are not pixels: 100% is the viewBox, not the width."""
        out = self._crop(_svg(PAGE_100 + DRAWING,
                              b'width="1000" height="750" viewBox="0 0 200 150"'))
        self.assertIn(b'<rect width="200" height="150" fill="white"/>', out)

    def test_each_axis_takes_its_own_side_and_r_takes_the_diagonal(self):
        out = self._crop(_svg(
            b'<circle cx="50%" cy="50%" r="10%"/>'
            b"<line x1='25%' y1='20%' x2='75%' y2='80%'/>" + DRAWING))
        self.assertIn(b'cx="500" cy="375"', out)
        self.assertIn(b"x1='250' y1='150' x2='750' y2='600'", out)
        diag = ((W * W + H * H) / 2) ** 0.5 * 0.1
        self.assertIn(f'r="{trimmer._svg_num(diag)}"'.encode(), out)

    def test_a_page_at_a_fixed_size_is_left_exactly_as_it_was(self):
        body = b'<rect x="0" y="0" width="1000" height="750" fill="white"/>' + DRAWING
        out = self._crop(_svg(body))
        self.assertTrue(out.endswith(body + b"</svg>"))

    def test_a_percentage_the_crop_does_not_move_is_left_alone(self):
        """A gradient stop is a percentage of the gradient, not of the page."""
        grad = (b'<defs><linearGradient id="g"><stop offset="50%" stop-color="red"/>'
                b"</linearGradient></defs>")
        out = self._crop(_svg(grad + DRAWING))
        self.assertIn(b'offset="50%"', out)

    def test_a_percentage_inside_a_nested_frame_is_refused(self):
        blob = _svg(b'<svg x="10" y="10" width="200" height="200">'
                    b'<rect width="100%" height="100%"/></svg>' + DRAWING)
        src = _project(self.tmp / "in.esx", blob)
        rep = trimmer.trim(src, self.tmp / "out.esx", boxes={FLOOR_A: BOX})
        self.assertEqual(rep.floors[0].action, "refused")
        self.assertIn("percentages", rep.floors[0].reason)
        self.assertIsNone(trimmer.repair_svg(blob))

    def test_only_a_percentage_of_another_box_is_unresolvable(self):
        nested = b'<svg width="200" height="200"><rect width="100%"/></svg>'
        bbox = b'<clipPath clipPathUnits="objectBoundingBox"><rect width="50%"/></clipPath>'
        self.assertTrue(trimmer.svg_percentages_unresolvable(_svg(nested + DRAWING)))
        self.assertTrue(trimmer.svg_percentages_unresolvable(_svg(bbox + DRAWING)))
        self.assertFalse(trimmer.svg_percentages_unresolvable(_svg(PAGE_100 + DRAWING)))
        # A nested frame with no percentages in it has nothing to get wrong.
        self.assertFalse(trimmer.svg_percentages_unresolvable(
            _svg(b'<svg width="200" height="200"/>' + DRAWING)))


class AnEarlierTrimIsRepairedOnSave(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.src = _project(self.tmp / "old.esx", LEFT_BY_AN_EARLIER_TRIM, 400, 300)

    def test_saving_with_nothing_to_cut_still_puts_the_page_back(self):
        rep = trimmer.trim(self.src, self.tmp / "out.esx")
        self.assertEqual(rep.trimmed_count, 0)
        self.assertEqual(rep.repaired_count, 1)
        self.assertTrue(rep.written)
        out = _image(self.tmp / "out.esx")
        # The smallest page that reaches the far edge of what is shown.
        self.assertIn(b'<rect width="950" height="700" fill="white"/>', out)
        self.assertIn(b'viewBox="550 400 400 300"', out)
        self.assertTrue(out.endswith(DRAWING + b"</svg>"))

    def test_analysis_reports_the_repair_without_writing_it(self):
        before = self.src.read_bytes()
        res = trimmer.api_analyze(str(self.src))
        self.assertEqual(res["repairedCount"], 1)
        self.assertTrue(res["floors"][0]["repaired"])
        self.assertEqual(self.src.read_bytes(), before)

    def test_cutting_it_again_measures_from_the_page_it_had(self):
        rep = trimmer.trim(self.src, self.tmp / "out.esx",
                           boxes={FLOOR_A: [20, 20, 380, 280]})
        self.assertEqual(rep.floors[0].action, "trimmed")
        out = _image(self.tmp / "out.esx")
        self.assertIn(b'<rect width="950" height="700" fill="white"/>', out)
        self.assertIn(b'viewBox="570 420 360 260"', out)

    def test_a_plan_no_crop_has_touched_is_never_repaired(self):
        """Ekahau writes no viewBox; its percentages are already right."""
        self.assertIsNone(trimmer.repair_svg(_svg(PAGE_100 + DRAWING)))

    def test_a_crop_from_the_origin_moved_nothing_and_needs_nothing(self):
        blob = _svg(PAGE_100 + DRAWING, b'width="400" height="300" viewBox="0 0 400 300"')
        self.assertIsNone(trimmer.repair_svg(blob))

    def test_a_repaired_file_is_not_repaired_twice(self):
        trimmer.trim(self.src, self.tmp / "once.esx")
        rep = trimmer.trim(self.tmp / "once.esx", self.tmp / "twice.esx")
        self.assertEqual(rep.repaired_count, 0)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePageShowsAndSavesTheRepair(unittest.TestCase):
    HARNESS = r"""
    const fs = require('fs');
    const src = fs.readFileSync(process.argv[1], 'utf8');
    function slice(a, b) {
      const i = src.indexOf(a), j = src.indexOf(b, i);
      if (i < 0 || j < 0) throw new Error('missing ' + a);
      return src.slice(i, j);
    }
    const calls = [];
    const ctx = new Proxy({}, {
      get: (t, k) => k in t ? t[k] : (...a) => calls.push([k, t.fillStyle]),
      set: (t, k, v) => { t[k] = v; return true; },
    });
    const canvas = { width: 1200, height: 800, getContext: () => ctx };
    globalThis.$ = id => canvas;
    globalThis.drawProposed = () => {};
    globalThis.box = { boxes: {}, current: 'f1', img: { width: 400, height: 300 },
                       view: { scale: 2, x: 10, y: 20 } };
    eval(slice('  function toScreen(ix, iy)', '  function framedRegion('));
    eval(slice('  function draw() {', '  function drawProposed('));
    eval(slice('  function hasWork(res)', '  function busy('));
    eval(slice('  function floorState(rep, id)', '  // Ekahau lets the customer name a floor'));
    """

    def run_node(self, script):
        proc = subprocess.run(["node", "-e", self.HARNESS + script, str(PLANTRIM_JS)],
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError("node failed:\n" + proc.stderr)
        return json.loads(proc.stdout)

    def test_the_plan_is_drawn_on_a_white_page(self):
        calls = self.run_node("draw(); console.log(JSON.stringify(calls));")
        names = [c[0] for c in calls]
        self.assertLess(names.index("fillRect"), names.index("drawImage"))
        self.assertEqual(calls[names.index("fillRect")][1], "#fff")

    def test_a_repair_alone_is_enough_to_save(self):
        out = self.run_node(
            "console.log(JSON.stringify([hasWork({trimmedCount: 0, repairedCount: 1}),"
            " hasWork({trimmedCount: 0, repairedCount: 0})]));")
        self.assertEqual(out, [True, False])

    def test_the_floor_strip_says_a_floor_will_be_repaired(self):
        out = self.run_node(
            "console.log(JSON.stringify(floorState({floors: [{id: 'f1', action: 'skipped',"
            " reason: 'content already fills 100% of the canvas', repaired: true}]}, 'f1')));")
        self.assertEqual(out["word"], "Repair")
        self.assertIn("restored when you save", out["detail"])


@unittest.skipUnless(HAVE_SELENIUM and HAVE_PILLOW, "selenium or Pillow is not installed")
class TheCroppedPlanIsWhiteInABrowser(unittest.TestCase):
    """Chrome, Edge and Firefox, per the standing rule."""

    @staticmethod
    def _driver(kind, binary):
        if not Path(binary).exists():
            return None
        try:
            if kind == "firefox":
                o = webdriver.FirefoxOptions()
                o.binary_location = binary
                o.add_argument("-headless")
                return webdriver.Firefox(options=o)
            if kind == "chrome":
                o = webdriver.ChromeOptions()
                o.binary_location = binary
                o.add_argument("--headless=new")
                o.add_argument("--no-sandbox")
                return webdriver.Chrome(options=o)
            o = webdriver.EdgeOptions()
            o.binary_location = binary
            o.add_argument("--headless=new")
            return webdriver.Edge(options=o)
        except (WebDriverException, OSError):
            return None

    def _pixels(self, driver, blob):
        """The plan's top-left corner and its middle, on a dark page."""
        url = "data:image/svg+xml;base64," + base64.b64encode(blob).decode()
        driver.get("data:text/html,<body style='margin:0;background:%23202020'>"
                   "<img id='p' src='" + url + "'></body>")
        time.sleep(0.5)
        shot = Image.open(io.BytesIO(driver.get_screenshot_as_png())).convert("RGB")
        return shot.getpixel((5, 5)), shot.getpixel((200, 20))

    def test_before_and_after_the_fix(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = _project(tmp / "in.esx", _svg(PAGE_100 + DRAWING))
            trimmer.trim(src, tmp / "cut.esx", boxes={FLOOR_A: BOX})
            cut = _image(tmp / "cut.esx")
            old = _project(tmp / "old.esx", LEFT_BY_AN_EARLIER_TRIM, 400, 300)
            trimmer.trim(old, tmp / "fixed.esx")
            fixed = _image(tmp / "fixed.esx")

        started = 0
        for kind, binary in _browsers.triple():
            driver = self._driver(kind, binary)
            if driver is None:
                continue
            started += 1
            try:
                driver.set_window_size(800, 600)
                with self.subTest(browser=kind):
                    # The shape the fault left behind really is dark, so the
                    # two assertions after it are not passing on a blank page.
                    self.assertEqual(self._pixels(driver, LEFT_BY_AN_EARLIER_TRIM)[0],
                                     (32, 32, 32))
                    self.assertEqual(self._pixels(driver, cut), ((255,) * 3,) * 2)
                    self.assertEqual(self._pixels(driver, fixed), ((255,) * 3,) * 2)
            finally:
                _browsers.shut_down(driver)
        if not started:
            self.skipTest(_browsers.why_missing())


if __name__ == "__main__":
    unittest.main()
