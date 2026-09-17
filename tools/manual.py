"""Serve `docs/USER_MANUAL.md` as a page you can actually read.

The manual existed and no route served it. The Home page's "User Manual" link
pointed at `/guide`, which is the **Quick Walls** guide - one tool out of nine -
so the manual was unreachable from inside the product it documents.

**Why this file exists rather than a dependency.** `requirements.txt` carries
flask, waitress, requests, browser_cookie3, cryptography, keyring and pillow,
and nothing else; `web/assets/lib/` vendors jszip, mammoth and pdf.js, and no
markdown renderer. Rendering the manual meant adding a third-party package to
the install - on a tool that is under InfoSec review at his workplace - or
writing the subset the manual actually uses. The manual uses eleven constructs
and this converts those eleven. It is not a CommonMark implementation and does
not pretend to be: `MARKDOWN_FEATURES` below is the contract, and
`tests/test_manual_render.py` asserts the real file still parses to the shape
those tests expect. If the manual grows a construct this does not handle, the
test that counts headings, tables and code blocks is what will say so.

Two rendering decisions that are not pass-through, both deliberate:

* **Remote badge images are dropped.** The manual's three `img.shields.io`
  badges are README furniture, and one of them says "telemetry: none". Serving
  them from the app would have the local-first tool make three requests to a
  third party to render the page that promises it does not. They mean nothing
  in-app anyway - nobody needs a badge telling them the thing they have open
  runs locally.
* **Relative paths are rewritten**, because the manual's links are written for
  GitHub's view of `docs/`: `../web/assets/x.png` becomes `/assets/x.png` and
  `../README.md` becomes `/`. Anchors are left alone - the manual's own
  Contents list uses GitHub's slug rules, so `_slug()` reproduces them exactly
  or that list breaks.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL_PATH = ROOT / "docs" / "USER_MANUAL.md"

#: The constructs this converter supports. The manual is allowed to use these
#: and nothing else. Quoted in the test that guards the contract.
MARKDOWN_FEATURES = (
    "atx-headings", "fenced-code", "tables", "blockquotes",
    "unordered-lists", "ordered-lists", "nested-lists", "thematic-breaks",
    "links", "images", "inline-code", "emphasis", "raw-html-lines",
)

#: Image hosts whose images are furniture rather than content. See module docs.
DROPPED_IMAGE_HOSTS = ("img.shields.io",)

_SENTINEL = "\x00"


# --------------------------------------------------------------------------
# inline
# --------------------------------------------------------------------------

def _slug(text: str) -> str:
    """GitHub's heading-anchor rule, because the manual's Contents relies on it.

    Lowercase, drop everything that is not a word character, space or hyphen,
    then spaces to hyphens. `Data, Privacy, and Security` ->
    `data-privacy-and-security`, which is exactly what the manual links to.
    """
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[`*_]", "", text)
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s]+", "-", text)


def _rewrite_href(href: str) -> str:
    """Turn a path written for GitHub's `docs/` view into a served path."""
    if href.startswith("../web/"):
        return "/" + href[len("../web/"):]
    if href in ("../README.md", "../README.MD"):
        return "/"
    if href.startswith("../"):
        return "/" + href[3:]
    return href


def _is_external(href: str) -> bool:
    return href.startswith("http://") or href.startswith("https://")


class _Inline:
    """Inline pass. Stashes finished HTML so later rules cannot re-enter it."""

    def __init__(self):
        self.stash: list[str] = []

    def _keep(self, markup: str) -> str:
        self.stash.append(markup)
        return f"{_SENTINEL}{len(self.stash) - 1}{_SENTINEL}"

    def _image(self, m: re.Match) -> str:
        alt, src = m.group(1), m.group(2)
        if any(hostname in src for hostname in DROPPED_IMAGE_HOSTS):
            return ""
        src = _rewrite_href(src)
        return self._keep(
            f'<img src="{html.escape(src, quote=True)}" '
            f'alt="{html.escape(alt, quote=True)}">')

    def _link(self, m: re.Match) -> str:
        label, href = m.group(1), _rewrite_href(m.group(2))
        extra = ' target="_blank" rel="noopener"' if _is_external(href) else ""
        return self._keep(
            f'<a href="{html.escape(href, quote=True)}"{extra}>'
            f"{html.escape(label)}</a>")

    def render(self, text: str) -> str:
        text = re.sub(r"`([^`]+)`",
                      lambda m: self._keep(f"<code>{html.escape(m.group(1))}</code>"),
                      text)
        text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)", self._image, text)
        text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", self._link, text)
        text = html.escape(text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
        # Stashed markup can contain stashed markup (a link holding code), so
        # keep expanding until nothing is left rather than doing one pass.
        while _SENTINEL in text:
            text = re.sub(rf"{_SENTINEL}(\d+){_SENTINEL}",
                          lambda m: self.stash[int(m.group(1))], text)
        return text


def _inline(text: str) -> str:
    return _Inline().render(text)


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE = re.compile(r"^```\s*([\w-]*)\s*$")
_HR = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
_UL = re.compile(r"^(\s*)[-*]\s+(.*)$")
_OL = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_TABLE_RULE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _alignments(rule: str) -> list[str]:
    out = []
    for cell in _split_row(rule):
        left, right = cell.startswith(":"), cell.endswith(":")
        out.append("center" if left and right else
                   "right" if right else
                   "left" if left else "")
    return out


class _Renderer:
    def __init__(self, lines: list[str]):
        self.lines = lines
        self.i = 0
        self.out: list[str] = []
        self.headings: list[tuple[int, str, str]] = []
        self.seen_slugs: dict[str, int] = {}

    # -- helpers ---------------------------------------------------------
    def _peek(self, offset: int = 0) -> str | None:
        j = self.i + offset
        return self.lines[j] if j < len(self.lines) else None

    def _unique_slug(self, text: str) -> str:
        base = _slug(text)
        n = self.seen_slugs.get(base, 0)
        self.seen_slugs[base] = n + 1
        return base if n == 0 else f"{base}-{n}"

    # -- blocks ----------------------------------------------------------
    def _heading(self, hashes: str, text: str) -> None:
        level = len(hashes)
        slug = self._unique_slug(text)
        self.headings.append((level, text, slug))
        self.out.append(
            f'<h{level} id="{slug}">{_inline(text)}'
            f'<a class="manual-anchor" href="#{slug}" '
            f'aria-label="Link to this section">#</a></h{level}>')

    def _code_block(self, lang: str) -> None:
        self.i += 1
        body: list[str] = []
        while self.i < len(self.lines) and not self.lines[self.i].startswith("```"):
            body.append(self.lines[self.i])
            self.i += 1
        self.i += 1  # closing fence
        cls = f' class="language-{html.escape(lang, quote=True)}"' if lang else ""
        self.out.append(
            f"<pre><code{cls}>{html.escape(chr(10).join(body))}</code></pre>")

    def _table(self) -> None:
        header = _split_row(self.lines[self.i])
        aligns = _alignments(self.lines[self.i + 1])
        self.i += 2
        rows: list[list[str]] = []
        while self.i < len(self.lines) and self.lines[self.i].strip().startswith("|"):
            rows.append(_split_row(self.lines[self.i]))
            self.i += 1

        def cell(tag: str, value: str, idx: int) -> str:
            align = aligns[idx] if idx < len(aligns) else ""
            style = f' style="text-align:{align}"' if align else ""
            return f"<{tag}{style}>{_inline(value)}</{tag}>"

        parts = ["<table><thead><tr>"]
        parts += [cell("th", value, idx) for idx, value in enumerate(header)]
        parts.append("</tr></thead><tbody>")
        for row in rows:
            parts.append("<tr>")
            parts += [cell("td", value, idx) for idx, value in enumerate(row)]
            parts.append("</tr>")
        parts.append("</tbody></table>")
        self.out.append("".join(parts))

    def _blockquote(self) -> None:
        body: list[str] = []
        while self.i < len(self.lines) and self.lines[self.i].lstrip().startswith(">"):
            stripped = self.lines[self.i].lstrip()[1:]
            body.append(stripped[1:] if stripped.startswith(" ") else stripped)
            self.i += 1
        inner = _Renderer(body)
        inner.run()
        self.out.append(f"<blockquote>{''.join(inner.out)}</blockquote>")

    def _list(self) -> None:
        """One list, including nested ones, by indent width.

        A line that is indented but carries no marker continues the item above
        it - the manual wraps long bullets that way and dropping the remainder
        would silently lose half a sentence.

        **The item's lines are joined before the inline pass, not after.** They
        were rendered one at a time at first, which is wrong for any span that
        crosses the wrap: `**Sending it up is not built` / `yet.**` came out
        with the asterisks still in it, on screen, in the shipped page. Bold
        that spans a line break is not exotic - a hard-wrapped file is full of
        it - so the buffer below is the fix rather than rewrapping the manual.
        """
        stack: list[tuple[int, str]] = []  # (indent, tag)
        pending: list[str] | None = None

        def flush() -> None:
            """Emit the open item's text. Lands directly after its `<li>`."""
            nonlocal pending
            if pending is not None:
                self.out.append(_inline(" ".join(pending)))
                pending = None

        while self.i < len(self.lines):
            line = self.lines[self.i]
            ul, ol = _UL.match(line), _OL.match(line)
            if ul:
                indent, text, tag = len(ul.group(1)), ul.group(2), "ul"
            elif ol:
                indent, text, tag = len(ol.group(1)), ol.group(3), "ol"
            elif line.strip() and line.startswith((" ", "\t")) and pending is not None:
                pending.append(line.strip())
                self.i += 1
                continue
            else:
                break

            flush()
            while stack and indent < stack[-1][0]:
                self.out.append(f"</li></{stack.pop()[1]}>")
            if not stack or indent > stack[-1][0]:
                stack.append((indent, tag))
                self.out.append(f"<{tag}>")
            else:
                self.out.append("</li>")
            self.out.append("<li>")
            pending = [text]
            self.i += 1

        flush()
        while stack:
            self.out.append(f"</li></{stack.pop()[1]}>")

    def _paragraph(self) -> None:
        body: list[str] = []
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if (not line.strip() or line.startswith("<") or _HEADING.match(line)
                    or _FENCE.match(line) or _HR.match(line)
                    or _UL.match(line) or _OL.match(line)
                    or line.lstrip().startswith(">")
                    or line.strip().startswith("|")):
                break
            body.append(line.strip())
            self.i += 1
        if body:
            self.out.append(f"<p>{_inline(' '.join(body))}</p>")

    def run(self) -> None:
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if not line.strip():
                self.i += 1
                continue
            if line.startswith("<"):
                # Raw HTML line, emitted verbatim. The manual's decorative
                # header is a `<div>` with markdown inside it, so this stays
                # line-by-line rather than swallowing to the closing tag.
                self.out.append(re.sub(
                    r'(src|href)="([^"]+)"',
                    lambda m: f'{m.group(1)}="{_rewrite_href(m.group(2))}"',
                    line))
                self.i += 1
                continue
            fence = _FENCE.match(line)
            if fence:
                self._code_block(fence.group(1))
                continue
            heading = _HEADING.match(line)
            if heading:
                self._heading(heading.group(1), heading.group(2).strip())
                self.i += 1
                continue
            if _HR.match(line):
                self.out.append("<hr>")
                self.i += 1
                continue
            nxt = self._peek(1)
            if line.strip().startswith("|") and nxt and _TABLE_RULE.match(nxt):
                self._table()
                continue
            if line.lstrip().startswith(">"):
                self._blockquote()
                continue
            if _UL.match(line) or _OL.match(line):
                self._list()
                continue
            self._paragraph()


def render_markdown(text: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Return `(html, headings)` where headings is `[(level, text, slug), ...]`."""
    renderer = _Renderer(text.replace("\r\n", "\n").split("\n"))
    renderer.run()
    return "".join(renderer.out), renderer.headings


def contents_headings(headings) -> list[tuple[int, str, str]]:
    """The sidebar entries: `##`/`###` from after the manual's own Contents.

    Everything above that point is the title block - an `<h1>` logo banner and
    a `## User Manual` subtitle - which are the page's own name, not places to
    navigate to. Keyed off the Contents heading rather than a list of titles to
    skip, so renaming a section cannot silently drop it from the sidebar.
    """
    out, started = [], False
    for level, text, slug in headings:
        if not started:
            started = slug == "contents"
            continue
        if level in (2, 3):
            out.append((level, text, slug))
    return out


# --------------------------------------------------------------------------
# page assembly
# --------------------------------------------------------------------------

TOC_MARKER = "<!--MANUAL_TOC-->"
BODY_MARKER = "<!--MANUAL_BODY-->"
SHELL_PATH = ROOT / "web" / "manual.html"


def render_toc(entries) -> str:
    """The sidebar. Flat list of links, indented by level rather than nested.

    Nested `<ul>`s would give the filter box a second problem to solve - a
    parent that matches nothing still has to stay visible when a child does -
    for no gain at two levels deep.
    """
    out = []
    for level, text, slug in entries:
        cls = "manual-toc-item" + (" manual-toc-sub" if level == 3 else "")
        out.append(f'<a class="{cls}" href="#{slug}">{_inline(text)}</a>')
    return "\n".join(out)


def render_page(markdown_text: str | None = None,
                shell_text: str | None = None) -> str:
    """The served `/manual` page: the shell with the manual substituted in."""
    if markdown_text is None:
        markdown_text = MANUAL_PATH.read_text(encoding="utf-8")
    if shell_text is None:
        shell_text = SHELL_PATH.read_text(encoding="utf-8")
    body, headings = render_markdown(markdown_text)
    toc = render_toc(contents_headings(headings))
    if TOC_MARKER not in shell_text or BODY_MARKER not in shell_text:
        raise ValueError(
            "web/manual.html is missing a substitution marker - the page would "
            "serve an empty manual and look like a styling bug")
    return shell_text.replace(TOC_MARKER, toc).replace(BODY_MARKER, body)
