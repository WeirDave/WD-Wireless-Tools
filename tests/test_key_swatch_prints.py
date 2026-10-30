"""The colour dots in a report's key are on the paper, not just on the screen.

He photographed the Placement Map's key and it read "Access point" and
"Directional, cone shows aim" with a wide empty gap in front of each: the dots
that say which marker means what were not printed. A dot is a 10px circle whose
only content is its background colour, and Firefox does not print background
colours unless the element asks for them - so the dot kept its width, lost its
colour, and the key described markers nobody could match to the drawing.

**Why this prints rather than reads the stylesheet.** `print-color-adjust` in
the CSS proves a declaration exists, not that Firefox honours it on a span that
carries an inline `background`, which is how a colour-coded project draws it.
The PDF through Firefox's own pagination is the only thing that settles it,
and Firefox is what he prints from.

Both swatches are drawn the way the report draws them: one in the stylesheet's
own fallback grey (a project whose APs are not colour-coded), one in an inline
colour (a project that is). Skipped where selenium, PyMuPDF or Firefox is
missing, the same split `test_dev_toolbar_does_not_print.py` describes.
"""
from __future__ import annotations

import base64
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import browsers as _browsers

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "web" / "assets" / "wd-tools.css"

try:  # pragma: no cover - availability varies by machine
    from selenium.webdriver.common.print_page_options import PrintOptions
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

try:  # pragma: no cover
    import pymupdf
    HAVE_PYMUPDF = True
except ImportError:  # pragma: no cover
    HAVE_PYMUPDF = False

FIREFOX = _browsers.find("firefox")

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="wd-tools.css"></head>
<body style="background:#fff"><div id="key" style="padding:40px;font-size:16px">
<span class="rep-key-swatch omni"></span> Access point
&nbsp;&nbsp;&nbsp;
<span class="rep-key-swatch dir" style="background:#e11d48"></span> Directional cone shows aim
</div></body></html>"""


def _pixels(pdf: bytes):
    """(grey dots, red dots) found on the first sheet. A dot is 10 CSS px, so
    at 144 dpi a handful of pixels is already one; the counts are read as
    "any", not as a size."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(dpi=144)
    grey = red = 0
    s, n = pix.samples, pix.n
    for r, g, b in zip(s[0::n], s[1::n], s[2::n]):
        # #78716c is warm: red sits 12 above blue. Antialiased black text
        # passes through the same greys with r == g == b, so it cannot match.
        if abs(r - 0x78) < 5 and abs(g - 0x71) < 5 and abs(b - 0x6c) < 5 and r - b > 8:
            grey += 1
        elif r > 200 and g < 70 and b < 110:
            red += 1
    return grey, red


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
@unittest.skipUnless(HAVE_PYMUPDF, "PyMuPDF is not installed")
@unittest.skipUnless(Path(FIREFOX).exists(), "Firefox is not installed here")
class TheKeyDotsArePrinted(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-key-swatch-"))
        shutil.copy(CSS, cls.tmp / "wd-tools.css")
        (cls.tmp / "index.html").write_text(PAGE, encoding="utf-8")
        cls.server = _browsers.serve_directory(cls.tmp)
        cls.driver = _browsers.make_driver("firefox", FIREFOX)
        if cls.driver is None:
            _browsers.stop_server(cls.server)
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise unittest.SkipTest("Firefox would not start")

    @classmethod
    def tearDownClass(cls):
        _browsers.shut_down(cls.driver)
        _browsers.stop_server(cls.server)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def printed(self):
        self.driver.get("http://127.0.0.1:%d/index.html"
                        % self.server.server_address[1])
        return base64.b64decode(self.driver.print_page(PrintOptions()))

    def test_the_fallback_dot_is_on_the_sheet(self):
        grey, _ = _pixels(self.printed())
        self.assertGreater(grey, 20, "the grey key dot did not print")

    def test_a_colour_coded_dot_is_on_the_sheet(self):
        _, red = _pixels(self.printed())
        self.assertGreater(red, 20, "the coloured key dot did not print")


if __name__ == "__main__":
    unittest.main()
