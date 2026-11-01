"""Nine tools on Home never leave a tile alone on a row, at any window width.

The launcher was `repeat(auto-fill, minmax(300px, 1fr))`. Nine tiles do not
divide into what that gives: 4 + 4 + 1 on a wide monitor, 2 + 2 + 2 + 2 + 1 on
a narrow window, one orphan each time. The tiles are in alphabetical order on
purpose - the page is used every day, so a tool stays where the hand expects
it - which rules out reordering to hide the gap. The stylesheet instead fixes
three columns on a wide window and, in the two-column band, lets the ninth
tile take the whole last row.

The second half of that is a container query, because the window query it
replaced counted the scrollbar and the grid does not: for the 15px where a
classic scrollbar made the grid two columns, the window still said three.
That is only visible in a real browser with a real scrollbar, so this drives
one - Firefox, Chrome and Edge - across a sweep of widths and asks the
property rather than a column count: **the last row is full, or is one tile
that spans it.**

The server is `http.server` over `web/`, never `server.py`.
"""
from __future__ import annotations

import time
import unittest
from pathlib import Path

from tests import browsers as _browsers

ROOT = Path(__file__).resolve().parent.parent
WIDTHS = [420, 560, 640, 700, 800, 900, 960, 985, 1000, 1100, 1280, 1600, 1799, 1800, 1920, 2400]

ROWS = """
const tiles = [...document.querySelectorAll('.launcher a.tile')];
const launcher = document.querySelector('.launcher').getBoundingClientRect();
const rows = {};
tiles.forEach(t => { const r = t.getBoundingClientRect(); (rows[Math.round(r.top)] = rows[Math.round(r.top)] || []).push(r); });
const keys = Object.keys(rows).map(Number).sort((a, b) => a - b);
const perRow = keys.map(k => rows[k].length);
const lastRow = rows[keys[keys.length - 1]];
const cols = Math.max(...perRow);
const lastSpans = lastRow.length === 1 && lastRow[0].width >= launcher.width - 1;
return { cols, perRow, lastIsFull: lastRow.length === cols, lastSpans, tiles: tiles.length,
         scrolls: document.documentElement.scrollWidth > document.documentElement.clientWidth };
"""


def _make(kind, binary):
    class _Case(unittest.TestCase):
        driver = None
        server = None

        @classmethod
        def setUpClass(cls):
            cls.driver = _browsers.make_driver(kind, binary)
            if cls.driver is None:
                raise unittest.SkipTest(f"{kind} is not available")
            cls.server = _browsers.serve_directory(ROOT / "web")

        @classmethod
        def tearDownClass(cls):
            if cls.driver is not None:
                _browsers.shut_down(cls.driver)
            if cls.server is not None:
                _browsers.stop_server(cls.server)

        def _measure(self, width):
            d = self.driver
            d.set_window_size(width, 1000)
            d.get(f"http://127.0.0.1:{self.server.server_address[1]}/home.html")
            deadline = time.time() + 5
            while time.time() < deadline and not d.execute_script(
                    "return document.querySelectorAll('.launcher a.tile').length === 9"):
                time.sleep(0.05)
            return d.execute_script(ROWS)

        def test_no_tile_is_ever_alone_on_a_row_unless_it_spans_the_row(self):
            for w in WIDTHS:
                with self.subTest(width=w):
                    m = self._measure(w)
                    self.assertEqual(m["tiles"], 9)
                    self.assertTrue(m["lastIsFull"] or m["lastSpans"],
                                    f"last row is a lone tile that does not span it: {m['perRow']}")

        def test_three_columns_on_a_wide_window_and_the_page_never_scrolls_sideways(self):
            for w in (1920, 2400):
                with self.subTest(width=w):
                    m = self._measure(w)
                    self.assertEqual(m["perRow"], [3, 3, 3])
            for w in WIDTHS:
                with self.subTest(width=w, check="no sideways scroll"):
                    self.assertFalse(self._measure(w)["scrolls"])

    _Case.__name__ = _Case.__qualname__ = f"HomeGridIn{kind.title()}"
    return _Case


for _kind, _binary in _browsers.triple():
    _c = _make(_kind, _binary)
    globals()[_c.__name__] = _c
del _c


if __name__ == "__main__":
    unittest.main()
