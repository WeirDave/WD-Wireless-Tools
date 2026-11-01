"""The Home page names every tool in a colour it can read, and in its own icon.

Home is the one page that has to identify nine tools at a glance, and the only
label that does it is the tile's name. It was set in the raw brand colour, which
is fine for a 22px title on a tinted bar and not for 16px bold text on a card:
on the dark theme Capacity's name measured 2.55:1 and Report's 2.97:1, and on the
light theme Prep's was 1.98:1. The tool pages do not have the problem because
they carry a legible `--tool-title` per theme; Home never did.

Resolved the way the browser resolves it, so what is checked is the colour that
is painted, not the text of a rule:

* a tile's outline and name are the tool's own brand colour, unmixed (a
  redesign paled them and the colours were asked for back);
* the nine accents are nine different colours in each theme;
* no two tiles share an icon (Capacity and Prep both used the suite logo, so
  two of nine tiles were indistinguishable);
* each tile is named by its own heading and described by its own line, and a
  version is blank until it arrives rather than the literal "v...";
* the "last opened" mark is written by a tool page and read by Home, driven in
  Node against stubs - a store with no writer is invisible;
* the tiles stay in alphabetical order (the page is used every day, so a tool
  stays where the hand expects it), and a letter jumps to the tool it starts;
* where two tools overlap, the tile itself says which to pick - it was a
  sentence in a tooltip, which a touch screen never shows.

How the nine tiles fall into columns is asked of a real browser, in
`test_home_grid_browser.py`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tests.test_every_tool_has_its_own_brand import (
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
        self.notes: dict[str, str] = {}
        self.section_labelledby: str | None = None
        self._note_for: str | None = None
        self._text_for: str | None = None
        self.h1 = 0
        self.main = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "h1":
            self.h1 += 1
        if tag == "main":
            self.main += 1
        if tag == "section" and a.get("aria-labelledby"):
            self.section_labelledby = a["aria-labelledby"]
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
            if "tile-name" in cls:
                self.cur["name"] = ""
                self._text_for = "name"
            if "tile-note" in cls:
                self._note_for = a.get("id")
                self.notes[self._note_for] = ""
        if a.get("id"):
            self.ids[a["id"]] = tag

    def handle_endtag(self, tag):
        if tag == "a" and self.cur is not None:
            self.cur = None
        if tag == "div":
            self._text_for = None
            self._note_for = None
        if tag in ("h2", "h3"):
            self._text_for = None

    def handle_data(self, data):
        if self.cur is not None and self._text_for == "ver":
            self.cur["ver"] += data
        if self.cur is not None and self._text_for == "name":
            self.cur["name"] += data
        if self._note_for is not None:
            self.notes[self._note_for] += data


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

    def card(self):
        return self.resolve("var(--card-bg)")



class TileColoursAreTheToolsBrand(unittest.TestCase):
    def test_there_are_nine_tiles(self):
        self.assertEqual(len(_tiles().tiles), 9)

    def test_the_name_and_the_outline_are_the_tools_own_brand_colour(self):
        """He asked for the colours back after a redesign made the outlines
        neutral and paled the names. Both are the brand itself, unmixed, and
        the brand is the one the tool page uses."""
        css = CSS.read_text(encoding="utf-8")
        rule = re.search(r"\n\.tile \{([^}]*)\}", css)
        self.assertTrue(rule, ".tile rule not found")
        self.assertIn("border: 2.5px solid var(--tile-accent)", rule.group(1))
        self.assertIn("--tile-title: var(--tile-accent)", rule.group(1))
        for theme in ("dark", "light"):
            pal = _HomePalette(theme)
            self.assertEqual(pal.tile["--tile-title"], "var(--tile-accent)")
            for t in _tiles().tiles:
                with self.subTest(theme=theme, tile=t["href"]):
                    self.assertIsNotNone(pal.accent(t["tone"]))

    def test_the_accents_are_nine_different_colours_in_each_theme(self):
        for theme in ("dark", "light"):
            pal = _HomePalette(theme)
            seen: dict[tuple, str] = {}
            for t in _tiles().tiles:
                rgb = tuple(round(c, 3) for c in pal.accent(t["tone"]))
                with self.subTest(theme=theme, tile=t["href"]):
                    self.assertNotIn(rgb, seen, "same colour as " + seen.get(rgb, ""))
                seen[rgb] = t["href"]

    def test_the_hover_wash_is_the_tools_colour(self):
        css = CSS.read_text(encoding="utf-8")
        m = re.search(r"\n\.tile:hover, \.tile:focus-visible \{([^}]*)\}", css)
        self.assertTrue(m)
        self.assertIn("color-mix(in srgb, var(--tile-accent)", m.group(1))


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


class TheTilesStayWhereTheHandExpectsThem(unittest.TestCase):
    def test_the_tiles_are_in_alphabetical_order(self):
        names = [t["name"].strip() for t in _tiles().tiles]
        self.assertEqual(names, sorted(names, key=str.lower))

    def test_overlapping_tools_say_which_to_pick_on_the_tile(self):
        p = _tiles()
        by_href = {t["href"]: t for t in p.tiles}
        for href, mentions in (("/plantrim", "Prep"), ("/prep", "PlanTrim"), ("/walls", "Prep")):
            with self.subTest(tile=href):
                ids = by_href[href]["describedby"].split()
                notes = [p.notes[i] for i in ids if i in p.notes]
                self.assertTrue(notes, "no note on the tile")
                self.assertTrue(any(mentions in n for n in notes), notes)


class TheTilesCanBeNavigatedByName(unittest.TestCase):
    def test_the_page_has_one_main_and_one_title(self):
        p = _tiles()
        self.assertEqual((p.main, p.h1), (1, 1))

    def test_each_tile_is_named_by_a_heading_and_described_by_its_line(self):
        p = _tiles()
        for t in p.tiles:
            with self.subTest(tile=t["href"]):
                self.assertEqual(t["name_tag"], "h3")
                self.assertEqual(p.ids.get(t["labelledby"]), "h3")
                for ident in t["describedby"].split():
                    self.assertIn(ident, p.ids)

    def test_the_tiles_sit_under_one_labelled_heading(self):
        p = _tiles()
        self.assertEqual(p.section_labelledby, "launcher-h")
        self.assertEqual(p.ids.get("launcher-h"), "h2")

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
  const attrs = { 'aria-describedby': 'td-x' };
  return { href, cls, text, kids, attrs,
           classList: { add: c => cls.add(c) },
           getAttribute: k => (k in attrs ? attrs[k] : null),
           setAttribute: (k, v) => { attrs[k] = v; },
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
  prepDescribedBy: tiles['/prep'].attrs['aria-describedby'],
  cloud: [...tiles['/cloud'].cls], cloudLabels: tiles['/cloud'].kids.length }));
""")
        self.assertEqual(out["prep"], ["is-last"])
        self.assertEqual(out["prepLabels"], ["Last opened"])
        self.assertEqual(out["prepDescribedBy"], "td-x tl-prep",
                         "the mark is part of the tile's description")
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


class TheMenuButtonReportsAndEscapeCloses(unittest.TestCase):
    """The hamburger on every page says whether its menu is open, and Escape
    closes it. Driven against the real functions; the wiring call is asserted
    through the page's own start-up handler, because a listener nobody
    registers is invisible."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node is not installed")

    def test_escape_closes_an_open_menu_and_the_button_says_so(self):
        code = ";\n".join([_slice(SHARED, "  WD.syncMenuButtons = function"),
                           _slice(SHARED, "  WD.wireMenuEscape = function"), ""])
        init = _slice(SHARED, "  document.addEventListener('DOMContentLoaded', function () {")
        script = """
const WD = {};
const attrs = {};
const menu = { open: true, classList: { contains: c => c === 'open' && menu.open, remove: c => { if (c === 'open') menu.open = false; } } };
const btn = { getAttribute: k => (k === 'data-menu' ? 'm' : k === 'title' ? 'Menu' : (k in attrs ? attrs[k] : null)),
              setAttribute: (k, v) => { attrs[k] = v; }, hasAttribute: k => k in attrs };
let keydown = null;
global.document = {
  getElementById: id => (id === 'm' ? menu : null),
  querySelectorAll: sel => (sel === '[data-action="menu"]' ? [btn] : sel.indexOf('.main-menu.open') === 0 ? (menu.open ? [menu] : []) : []),
  addEventListener: (type, fn) => { if (type === 'keydown') keydown = fn; },
};
""" + code + """
WD.syncMenuButtons();
const before = attrs['aria-expanded'];
// The page's start-up handler is what registers the listener.
const names = ['syncThemeUI','syncMenuButtons','wireMenuEscape','rememberTool','markLastTool','wireTileJump','syncFavicon','applyVersions','checkServerVersion','checkForUpdates','checkSetup','wireSettingsLinks','sortNavMenus'];
const ran = [];
names.forEach(n => { WD[n] = WD[n] || (() => { ran.push(n); }); });
const origWire = WD.wireMenuEscape;
WD.wireMenuEscape = () => { ran.push('wireMenuEscape'); origWire(); };
let handler = null;
document.addEventListener = (type, fn) => { if (type === 'DOMContentLoaded') handler = fn; else if (type === 'keydown') keydown = fn; };
%s
handler();
keydown({ key: 'Enter' });
const afterEnter = [menu.open, attrs['aria-expanded']];
keydown({ key: 'Escape' });
console.log(JSON.stringify({ before, afterEnter, afterEsc: [menu.open, attrs['aria-expanded']], label: attrs['aria-label'], wired: ran.indexOf('wireMenuEscape') > -1 }));
""" % (init + ");",)
        proc = subprocess.run([self.node, "-e", script], capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if proc.returncode:
            raise AssertionError((proc.stdout + proc.stderr).strip())
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(out["before"], "true")
        self.assertEqual(out["afterEnter"], [True, "true"])
        self.assertEqual(out["afterEsc"], [False, "false"])
        self.assertEqual(out["label"], "Menu")
        self.assertTrue(out["wired"], "the start-up handler never registers the Escape listener")


class TheMenuAndTheTilesAreUsableFromTheKeyboard(unittest.TestCase):
    """Driven against the real functions: Escape hands focus back to the
    button, the arrow keys walk the menu, focus leaving it closes it, a menu
    opened from the keyboard takes focus, and a letter jumps to the tool."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node is not installed")
        cls.code = ";\n".join([_slice(SHARED, "  WD.syncMenuButtons = function"),
                               _slice(SHARED, "  WD.toggleMenu = function"),
                               _slice(SHARED, "  WD.wireMenuEscape = function"),
                               _slice(SHARED, "  WD.jumpToTile = function"),
                               _slice(SHARED, "  WD.wireTileJump = function"), ""])

    def _run(self, body: str):
        script = """
const WD = {};
let focused = null;
const handlers = {};
function el(name, extra) {
  return Object.assign({ name, focus() { focused = this; }, tagName: 'A', closest: () => null }, extra || {});
}
const items = [el('a'), el('b'), el('c')];
const btn = el('btn', { tagName: 'BUTTON' });
const outside = el('outside');
const menu = { id: 'm', open: false, parentNode: null,
  classList: { contains: c => c === 'open' && menu.open, add: c => { if (c === 'open') menu.open = true; },
               remove: c => { if (c === 'open') menu.open = false; } },
  contains: n => items.indexOf(n) > -1,
  querySelector: () => items[0],
  querySelectorAll: () => items };
const wrap = { contains: n => items.indexOf(n) > -1 || n === btn };
menu.parentNode = wrap;
items.forEach(i => { i.closest = () => wrap; });
btn.closest = () => wrap;
const tiles = ['Cloud Manager', 'Capacity', 'Prep', 'PlanTrim', 'Squirrel'].map(n =>
  el(n, { querySelector: () => ({ textContent: n }) }));
global.document = {
  get activeElement() { return focused; },
  getElementById: id => (id === 'm' ? menu : null),
  querySelector: sel => (sel === '.launcher' ? {} : sel.indexOf('.main-menu.open') === 0 ? (menu.open ? menu : null)
                          : sel.indexOf('[data-action="menu"]') === 0 ? btn : null),
  querySelectorAll: sel => (sel === '[data-action="menu"]' ? [] : sel.indexOf('.launcher a.tile') === 0 ? tiles
                            : sel.indexOf('.main-menu.open') === 0 ? (menu.open ? [menu] : []) : []),
  addEventListener: (t, f) => { handlers[t] = f; },
};
global.setTimeout = () => 0;
""" + self.code + "\n(async () => {\n" + body + "\n})().catch(e => { console.error(e && e.stack || e); process.exit(1); });\n"
        proc = subprocess.run([self.node, "-e", script], capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if proc.returncode:
            raise AssertionError((proc.stdout + proc.stderr).strip())
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_escape_hands_focus_back_to_the_button_only_when_it_was_in_the_menu(self):
        out = self._run("""
WD.wireMenuEscape();
menu.open = true; focused = items[1];
handlers.keydown({ key: 'Escape', preventDefault() {} });
const fromInside = [menu.open, focused === btn];
menu.open = true; focused = outside;
handlers.keydown({ key: 'Escape', preventDefault() {} });
console.log(JSON.stringify({ fromInside, fromOutside: [menu.open, focused === outside] }));
""")
        self.assertEqual(out["fromInside"], [False, True])
        self.assertEqual(out["fromOutside"], [False, True], "focus elsewhere must not be pulled to the button")

    def test_the_arrow_keys_home_and_end_walk_the_menu(self):
        out = self._run("""
WD.wireMenuEscape();
menu.open = true; focused = btn;
const path = [];
for (const k of ['ArrowDown', 'ArrowDown', 'ArrowDown', 'ArrowDown', 'ArrowUp', 'End', 'Home']) {
  handlers.keydown({ key: k, preventDefault() {} });
  path.push(items.indexOf(focused));
}
console.log(JSON.stringify(path));
""")
        self.assertEqual(out, [0, 1, 2, 0, 2, 2, 0])

    def test_arrow_keys_do_nothing_when_focus_is_elsewhere_on_the_page(self):
        out = self._run("""
WD.wireMenuEscape();
menu.open = true; focused = outside;
let prevented = false;
handlers.keydown({ key: 'ArrowDown', preventDefault() { prevented = true; } });
console.log(JSON.stringify({ prevented, stayed: focused === outside }));
""")
        self.assertEqual(out, {"prevented": False, "stayed": True})

    def test_focus_leaving_the_menu_closes_it_and_focus_inside_does_not(self):
        out = self._run("""
WD.wireMenuEscape();
menu.open = true;
handlers.focusin({ target: items[0] });
const inside = menu.open;
handlers.focusin({ target: outside });
console.log(JSON.stringify({ inside, afterOutside: menu.open }));
""")
        self.assertEqual(out, {"inside": True, "afterOutside": False})

    def test_a_menu_opened_from_the_keyboard_takes_focus_and_one_opened_by_mouse_does_not(self):
        out = self._run("""
WD.toggleMenu({ detail: 0, stopPropagation() {} }, 'm');
const byKeyboard = focused === items[0];
menu.open = false; focused = null;
WD.toggleMenu({ detail: 1, stopPropagation() {} }, 'm');
console.log(JSON.stringify({ byKeyboard, byMouse: focused }));
""")
        self.assertEqual(out, {"byKeyboard": True, "byMouse": None})

    def test_a_letter_focuses_the_first_tool_and_the_same_letter_moves_to_the_next(self):
        out = self._run("""
WD.wireTileJump();
const seen = [];
for (const k of ['c', 'c', 'c', 'p', 'p', 's', 'z']) {
  let prevented = false;
  handlers.keydown({ key: k, target: { tagName: 'BODY' }, preventDefault() { prevented = true; } });
  seen.push([k, focused ? focused.name : null, prevented]);
}
console.log(JSON.stringify(seen));
""")
        self.assertEqual(out, [["c", "Cloud Manager", True], ["c", "Capacity", True], ["c", "Cloud Manager", True],
                               ["p", "Prep", True], ["p", "PlanTrim", True], ["s", "Squirrel", True],
                               ["z", "Squirrel", False]])

    def test_typing_in_a_field_or_with_a_modifier_or_with_a_menu_open_does_not_jump(self):
        out = self._run("""
WD.wireTileJump();
const tries = [
  { key: 'c', target: { tagName: 'INPUT' } },
  { key: 'c', target: { tagName: 'BODY' }, ctrlKey: true },
  { key: 'Enter', target: { tagName: 'BODY' } },
];
for (const t of tries) handlers.keydown(Object.assign({ preventDefault() {} }, t));
const afterThree = focused;
menu.open = true;
handlers.keydown({ key: 'c', target: { tagName: 'BODY' }, preventDefault() {} });
console.log(JSON.stringify({ afterThree, withMenu: focused }));
""")
        self.assertEqual(out, {"afterThree": None, "withMenu": None})


if __name__ == "__main__":
    unittest.main()
