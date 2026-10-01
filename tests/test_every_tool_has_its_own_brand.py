"""Every tool has its own colour, set once, and its title is legible on it.

"all tools should have their own unique color branding" - said when the
suite-wide visual refresh was planned, so a refresh that unified the look
would not unify the colours away. The shared look is type, spacing and
components; a tool is told apart by one colour, `--tool-accent`, set in the
brand block in `wd-tools.css` and nowhere else.

Resolved here the way the browser resolves it - custom properties, the
light-theme overrides, `color-mix(in srgb, ...)` - so what is checked is the
colour that is painted, not the text of the rule:

* every page with a `tool-*` body class (bar Home, Settings, Setup and the
  User Guide, which are the suite rather than a tool) has a brand;
* no two tools share one (Squirrel's organizer and rename pages are one tool);
* each title clears 3:1 - the WCAG floor for large text, and the title is
  22px bold - on its own tinted bar, in the dark theme and the light.

`tests/test_every_tool_header_carries_its_colour.py` is the browser half: it
measures that the bar really is painted with it.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "web" / "assets" / "wd-tools.css"
WEB = ROOT / "web"

#: The suite's own pages, deliberately neutral.
NOT_A_TOOL = {"tool-home", "tool-guide"}
#: One tool, two pages.
SAME_TOOL = {"tool-rename": "tool-organizer"}
#: Tint strengths the brand block applies to the bar, per theme.
TINT = {"dark": 0.18, "light": 0.14}


_RULES: list[tuple[str, str]] = []


def _rules(css: str) -> list[tuple[str, str]]:
    """(selector, body) for every innermost rule, comments removed first - a
    comment directly above a rule would otherwise be read as its selector."""
    if not _RULES:
        bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        _RULES.extend((" ".join(sel.split()), body)
                      for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", bare))
    return _RULES


def _parts(sel: str) -> list[str]:
    """A selector list split on its top-level commas - the ones not inside
    `:is(...)`. Matching the whole list with one regular expression
    backtracked exponentially on long lists and hung the suite."""
    out, depth, cur = [], 0, ""
    for ch in sel:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def _blocks(css: str, selector_re: str) -> dict[str, str]:
    """Custom properties declared in rules where one selector in the list
    matches `selector_re` in full."""
    out: dict[str, str] = {}
    for sel, body in _rules(css):
        if any(re.fullmatch(selector_re, part) for part in _parts(sel)):
            for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body):
                out[name] = value.strip()
    return out


def _hex(c: str) -> tuple[float, float, float]:
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


class Palette:
    def __init__(self, theme: str, tool: str):
        css = CSS.read_text(encoding="utf-8")
        self.vars = _blocks(css, r":root")
        if theme == "light":
            self.vars.update(_blocks(css, r'\[data-theme="light"\]'))
        self.vars.update(_blocks(css, r"body"))
        self.vars.update(_blocks(css, rf"body\.{tool}"))
        if theme == "light":
            # `[data-theme="light"] body.tool-x`, or the same inside `:is(...)`
            # alongside other tools.
            self.vars.update(_blocks(
                css, rf'\[data-theme="light"\] (?:body\.{tool}|:is\((?:[^()]*,\s*)?body\.{tool}(?:\s*,[^()]*)?\))'))

    def resolve(self, value: str, depth: int = 0) -> tuple[float, float, float]:
        if depth > 12:
            raise AssertionError("variable cycle at " + value)
        value = value.strip()
        m = re.fullmatch(r"var\((--[\w-]+)(?:\s*,\s*(.+))?\)", value)
        if m:
            if m.group(1) in self.vars:
                return self.resolve(self.vars[m.group(1)], depth + 1)
            if m.group(2):
                return self.resolve(m.group(2), depth + 1)
            raise AssertionError("undefined " + m.group(1))
        m = re.fullmatch(r"color-mix\(in srgb,\s*(.+?)\s+(\d+)%\s*,\s*(.+)\)", value)
        if m:
            a, p, b = self.resolve(m.group(1), depth + 1), int(m.group(2)) / 100, m.group(3).strip()
            other = (1.0, 1.0, 1.0) if b == "white" else self.resolve(b, depth + 1)
            return tuple(x * p + y * (1 - p) for x, y in zip(a, other))
        if value == "white":
            return (1.0, 1.0, 1.0)
        if re.fullmatch(r"#[0-9a-fA-F]{3,6}", value):
            return _hex(value)
        raise AssertionError("cannot resolve " + value)


def _lum(rgb):
    def ch(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _tool_classes() -> set[str]:
    found = set()
    for page in WEB.glob("*.html"):
        m = re.search(r'<body class="(tool-[\w-]+)', page.read_text(encoding="utf-8"))
        if m:
            found.add(m.group(1))
    return found - NOT_A_TOOL


class EveryToolHasItsOwnBrand(unittest.TestCase):
    def test_there_are_tools_to_check(self):
        self.assertGreaterEqual(len(_tool_classes()), 9)

    def test_every_tool_page_declares_a_brand(self):
        css = CSS.read_text(encoding="utf-8")
        for tool in sorted(_tool_classes()):
            with self.subTest(tool=tool):
                own = _blocks(css, rf"(?:[^,]*,\s*)*body\.{tool}(?:\s*,[^,]*)*")
                self.assertIn("--tool-accent", own, "no brand colour of its own")

    def test_no_two_tools_share_a_brand(self):
        for theme in ("dark", "light"):
            seen: dict[tuple, str] = {}
            for tool in sorted(_tool_classes()):
                if tool in SAME_TOOL:
                    continue
                rgb = tuple(round(c, 3) for c in Palette(theme, tool).resolve("var(--tool-accent)"))
                with self.subTest(theme=theme, tool=tool):
                    self.assertNotIn(rgb, seen, "same colour as " + seen.get(rgb, ""))
                seen[rgb] = tool

    def test_one_tool_on_two_pages_is_one_colour(self):
        for page, tool in SAME_TOOL.items():
            for theme in ("dark", "light"):
                with self.subTest(page=page, theme=theme):
                    self.assertEqual(Palette(theme, page).resolve("var(--tool-accent)"),
                                     Palette(theme, tool).resolve("var(--tool-accent)"))

    def test_every_title_is_legible_on_its_own_bar(self):
        for theme in ("dark", "light"):
            for tool in sorted(_tool_classes()):
                pal = Palette(theme, tool)
                base = pal.resolve("var(--navy)" if theme == "dark" else "var(--head-bg)")
                accent = pal.resolve("var(--tool-accent)")
                t = TINT[theme]
                bar = tuple(a * t + b * (1 - t) for a, b in zip(accent, base))
                title = pal.resolve("var(--tool-title)")
                with self.subTest(theme=theme, tool=tool):
                    self.assertGreaterEqual(round(_contrast(title, bar), 2), 3.0)


if __name__ == "__main__":
    unittest.main()
