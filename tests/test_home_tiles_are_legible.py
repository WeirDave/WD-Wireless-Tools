"""The Home page names every tool in a colour it can read, and in its own icon.

Home is the one page that has to identify nine tools at a glance, and the only
label that does it is the tile's name. It was set in the raw brand colour, which
is fine for a 22px title on a tinted bar and not for 16px bold text on a card:
on the dark theme Capacity's name measured 2.55:1 and Report's 2.97:1, and on the
light theme Prep's was 1.98:1. The tool pages do not have the problem because
they carry a legible `--tool-title` per theme; Home never did.

Resolved the way the browser resolves it, so what is checked is the colour that
is painted, not the text of a rule:

* every tile name clears 4.5:1 on the card and on the card's hover wash, in
  both themes;
* the nine accents are nine different colours in each theme;
* no two tiles share an icon (Capacity and Prep both used the suite logo, so
  two of nine tiles were indistinguishable);
* each tile is named by its own heading and described by its own line, and a
  version is blank until it arrives rather than the literal "v...";
* the "last opened" mark is written by a tool page and read by Home, driven in
  Node against stubs - a store with no writer is invisible.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

from test_every_tool_has_its_own_brand import (
    CSS, Palette, _blocks, _contrast,
)

ROOT = Path(__file__).resolve().parent.parent
HOME = (ROOT / "web" / "home.html").read_text(encoding="utf-8")
SHARED = (ROOT / "web" / "assets" / "js" / "wd-shared.js").read_text(encoding="utf-8")
NODE_TIMEOUT_S = 60


class _Tiles(HTMLParser):
    """The tiles of the launcher, with what each one is made of."""

    def __init__(self):
        super().__init__()
        self.tiles: list[dict] = []
        self.cur: dict | None = None
        self.ids: dict[str, str] = {}
        self._text_for: str | None = None
        self.h1 = 0
        self.main = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "h1":
            self.h1 += 1
        if tag == "main":
            self.main += 1
        cls = (a.get("class") or "").split()
        if tag == "a" and "tile" in cls:
            tone = next((c[6:] for c in cls if c.startswith("tile--")), "")
            self.cur = {"tone": tone, "href": a.get("href"), "labelledby": a.get("aria-labelledby"),
                        "describedby": a.get("aria-describedby"), "icon": None, "name_tag": None,
                        "ver": None}
            self.tiles.append(self.cur)
        if self.cur is not None:
            if tag == "img" and "tile-icon" not in cls and self.cur["icon"] is None:
                self.cur["icon"] = a.get("src")
            if "tile-name" in cls:
                self.cur["name_tag"] = tag
                self.cur["name_id"] = a.get("id")
            if "tile-ver" in cls:
                self.cur["ver"] = ""
                self._text_for = "ver"
        if a.get("id"):
            self.ids[a["id"]] = tag

    def handle_endtag(self, tag):
        if tag == "a" and self.cur is not None:
            self.cur = None
        if tag == "div":
            self._text_for = None

    def handle_data(self, data):
        if self.cur is not None and self._text_for == "ver":
            self.cur["ver"] += data


def _tiles() -> _Tiles:
    p = _Tiles()
    p.feed(HOME)
    return p


def _mix(a, b, pct):
    return tuple(x * pct + y * (1 - pct) for x, y in zip(a, b))


class _HomePalette(Palette):
    """`Palette` for the Home body, with the two things its resolver lacks:
    `black` in a colour-mix, and the tile's own blocks."""

    def __init__(self, theme: str):
        super().__init__(theme, "tool-home")
        self.theme = theme
        css = CSS.read_text(encoding="utf-8")
        self.tile = _blocks(css, r"\.tile")
        if theme == "light":
            self.tile.update(_blocks(css, r'\[data-theme="light"\] \.tile'))

    def resolve(self, value, depth=0):
        m = re.fullmatch(r"color-mix\(in srgb,\s*(.+?)\s+(\d+)%\s*,\s*black\)", value.strip())
        if m:
            return _mix(self.resolve(m.group(1), depth + 1), (0.0, 0.0, 0.0), int(m.group(2)) / 100)
        return super().resolve(value, depth)

    def accent(self, tone: str):
        css = CSS.read_text(encoding="utf-8")
        own = _blocks(css, rf"\.tile--{tone}")
        if self.theme == "light":
            own.update(_blocks(css, rf'\[data-theme="light"\] \.tile--{tone}'))
        return self.resolve(own["--tile-accent"])

    def title(self, tone: str):
        acc = self.accent(tone)
        formula = self.tile["--tile-title"]
        m = re.fullmatch(r"color-mix\(in srgb,\s*var\(--tile-accent\)\s+(\d+)%\s*,\s*(white|black)\)", formula)
        assert m, "tile title formula changed shape: " + formula
        toward = (1.0, 1.0, 1.0) if m.group(2) == "white" else (0.0, 0.0, 0.0)
        return _mix(acc, toward, int(m.group(1)) / 100)

    def card(self):
        return self.resolve("var(--card-bg)")

    def hover(self, tone: str):
        css = CSS.read_text(encoding="utf-8")
        pct = 12 if self.theme == "dark" else 8
        # The hover background is the tint over the page, not over the card.
        return _mix(self.accent(tone), self.resolve("var(--bg)"), pct / 100)


class TileNamesAreLegible(unittest.TestCase):
    def test_there_are_nine_tiles(self):
        self.assertEqual(len(_tiles().tiles), 9)

    def test_every_name_clears_four_and_a_half_to_one_in_both_themes(self):
        for theme in ("dark", "light"):
            pal = _HomePalette(theme)
            for t in _tiles().tiles:
                tone = t["tone"]
                with self.subTest(theme=theme, tile=t["href"]):
                    self.assertGreaterEqual(round(_contrast(pal.title(tone), pal.card()), 2), 4.5,
                                            "on the card")
                    self.assertGreaterEqual(round(_contrast(pal.title(tone), pal.hover(tone)), 2), 4.5,
                                            "on the hover wash")

    def test_the_accents_are_nine_different_colours_in_each_theme(self):
        for theme in ("dark", "light"):
            pal = _HomePalette(theme)
            seen: dict[tuple, str] = {}
            for t in _tiles().tiles:
                rgb = tuple(round(c, 3) for c in pal.accent(t["tone"]))
                with self.subTest(theme=theme, tile=t["href"]):
                    self.assertNotIn(rgb, seen, "same colour as " + seen.get(rgb, ""))
                seen[rgb] = t["href"]

    def test_a_tile_outline_is_not_the_only_thing_that_names_a_tool(self):
        """The name is text in its own right, so a softened outline at rest does
        not remove the identification - but it must still be visible against
        the card in the dark theme, where the card is close to the page."""
        pal = _HomePalette("dark")
        for t in _tiles().tiles:
            with self.subTest(tile=t["href"]):
                edge = _mix(pal.accent(t["tone"]), pal.card(), 0.6)
                self.assertGreater(_contrast(edge, pal.resolve("var(--bg)")), 1.5)


class EveryTileHasItsOwnIcon(unittest.TestCase):
    def test_no_two_tiles_share_an_icon(self):
        seen: dict[str, str] = {}
        for t in _tiles().tiles:
            with self.subTest(tile=t["href"]):
                self.assertIsNotNone(t["icon"])
                self.assertNotIn(t["icon"], seen, "same icon as " + seen.get(t["icon"], ""))
                seen[t["icon"]] = t["href"]

    def test_every_icon_is_a_file_that_ships(self):
        for t in _tiles().tiles:
            with self.subTest(tile=t["href"]):
                self.assertTrue((ROOT / "web" / t["icon"].lstrip("/")).is_file(), t["icon"])


class TheTilesCanBeNavigatedByName(unittest.TestCase):
    def test_the_page_has_one_main_and_one_title(self):
        p = _tiles()
        self.assertEqual((p.main, p.h1), (1, 1))

    def test_each_tile_is_named_by_a_heading_and_described_by_its_line(self):
        p = _tiles()
        for t in p.tiles:
            with self.subTest(tile=t["href"]):
                self.assertEqual(t["name_tag"], "h2")
                self.assertEqual(p.ids.get(t["labelledby"]), "h2")
                self.assertIn(t["describedby"], p.ids)

    def test_a_version_is_blank_until_it_arrives(self):
        for t in _tiles().tiles:
            with self.subTest(tile=t["href"]):
                self.assertEqual((t["ver"] or "").strip(), "",
                                 "a placeholder is read aloud and stays if the fetch fails")


def _slice(src: str, start: str) -> str:
    """From `start` to the matching close brace, counted."""
    a = src.index(start)
    depth, seen, b = 0, False, a
    while b < len(src) and not (seen and depth == 0):
        if src[b] == "{":
            depth += 1
            seen = True
        elif src[b] == "}":
            depth -= 1
        b += 1
    return src[a:b]


class TheLastToolIsWrittenByATool_AndReadByHome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node is not installed")
        paths = SHARED[SHARED.index("  var _TOOL_PATHS"):]
        paths = paths[:paths.index("};") + 2]
        cls.code = ";\n".join([paths, _slice(SHARED, "  WD.rememberTool = function"),
                              _slice(SHARED, "  WD.markLastTool = function"), ""])

    def _run(self, body: str):
        script = """
const WD = {};
const store = {};
global.localStorage = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
function stubTile(href) {
  const kids = [];
  const text = { appended: [], querySelector: sel => (sel === '.tile-last' ? kids.find(k => k.className === 'tile-last') || null : null),
                 appendChild: n => { kids.push(n); } };
  const cls = new Set();
  return { href, cls, text, kids,
           classList: { add: c => cls.add(c) },
           querySelector: sel => (sel === '.tile-text' ? text : null) };
}
const tiles = {};
['/cloud', '/squirrel', '/prep'].forEach(h => { tiles[h] = stubTile(h); });
global.document = {
  querySelector: sel => (sel === '.launcher' ? { querySelector: s => {
    const m = /href="([^"]+)"/.exec(s); return m ? (tiles[m[1]] || null) : null; } } : null),
  createElement: () => ({ className: '', textContent: '' }),
};
global.window = { location: { pathname: '/' } };
""" + self.code + "\n(async () => {\n" + body + "\n})().catch(e => { console.error(e && e.stack || e); process.exit(1); });\n"
        proc = subprocess.run([self.node, "-e", script], capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if proc.returncode:
            raise AssertionError((proc.stdout + proc.stderr).strip())
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_a_tool_page_records_itself_and_the_squirrel_pages_are_one_tool(self):
        out = self._run("""
const seen = {};
for (const p of ['/cloud', '/organizer', '/rename', '/squirrel/rename', '/settings', '/']) {
  for (const k of Object.keys(store)) delete store[k];
  window.location.pathname = p;
  WD.rememberTool();
  seen[p] = store['wd-last-tool'] || null;
}
console.log(JSON.stringify(seen));
""")
        self.assertEqual(out, {"/cloud": "/cloud", "/organizer": "/squirrel", "/rename": "/squirrel",
                               "/squirrel/rename": "/squirrel", "/settings": None, "/": None})

    def test_home_marks_the_recorded_tile_once_and_leaves_the_rest(self):
        out = self._run("""
store['wd-last-tool'] = '/prep';
WD.markLastTool();
WD.markLastTool();
console.log(JSON.stringify({
  prep: [...tiles['/prep'].cls], prepLabels: tiles['/prep'].kids.map(k => k.textContent),
  cloud: [...tiles['/cloud'].cls], cloudLabels: tiles['/cloud'].kids.length }));
""")
        self.assertEqual(out["prep"], ["is-last"])
        self.assertEqual(out["prepLabels"], ["Last opened"])
        self.assertEqual((out["cloud"], out["cloudLabels"]), ([], 0))

    def test_nothing_recorded_marks_nothing(self):
        out = self._run("""
WD.markLastTool();
console.log(JSON.stringify(Object.values(tiles).map(t => [...t.cls].length + t.kids.length)));
""")
        self.assertEqual(out, [0, 0, 0])

    def test_a_path_that_is_no_longer_a_tile_marks_nothing(self):
        out = self._run("""
store['wd-last-tool'] = '/gone';
WD.markLastTool();
console.log(JSON.stringify(Object.values(tiles).map(t => [...t.cls].length + t.kids.length)));
""")
        self.assertEqual(out, [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
