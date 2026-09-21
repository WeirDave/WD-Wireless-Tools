#!/usr/bin/env python3
"""Every control the app tells someone to use, and whether it exists.

The rule is old: telling him to use a button nothing renders is worse than
saying nothing, and it shipped once - the Sync dialog spent a release
recommending a control greyed out for every row he had. The *guard* was
narrow: it read ``cloud.js`` and nothing else, so a cross-page instruction
went unchecked, and v2.150.0 walked into exactly that. The Settings page
gained "Open Report and use **Edit report settings**" in the same change that
renamed the button to **Cover image…**.

Two earlier attempts at a wider version passed with that defect in place, and
avoiding how they failed is most of what this file does:

* searching the raw source matched a **comment** in ``report.js`` explaining
  why the button had been renamed - the old name was in prose, in quotes, and
  read as a label. So comments are stripped before anything is searched.
* searching for ``>Name<`` across ``web/`` matched **the instruction itself**,
  because the page carrying it contains ``<b>Name</b>``. So instructional
  markup is removed from the haystack before the needles are looked for.

The third problem is how labels are written here. ``'Cover image' + '\\u2026'``
never appears as ``Cover image…`` anywhere in the source, so a literal search
finds nothing however the corpus is built. Adjacent string literals joined by
``+`` are folded together before the corpus is built, which is what makes a
concatenated label findable.

Run it to see the inventory; ``tests/test_named_controls_exist.py`` is the
guard.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: A control named in prose is emphasised. Two shapes count as naming one:
#: an instructional verb immediately before it, or an arrow glyph in it - the
#: badge style this suite uses for its sync directions. Both come from
#: `TheAppOnlyPointsAtControlsThatExistTests`, which this generalises.
#:
#: **Three things had to widen after this missed a fourth instance.** Quick
#: Walls' tips panel said "Click <strong>#</strong> on any wall type" for seven
#: minor versions after that button became the word "Set key", and every gate
#: here was shut against it: the panel emphasises with `<strong>` and this read
#: only `<b>`; the verb was "Click" and this read only "use"; and with neither
#: an arrow nor "use" it was never collected at all. Widening found a fifth as
#: well - Cloud Manager's help telling him to click "Link anyway", which
#: nothing has ever rendered.
_EMPH = r"(?:b|strong)"
BOLD = re.compile(r"<" + _EMPH + r">((?:&#\d+;|&\w+;|[^<])*?)</" + _EMPH + r">")

#: The verbs that turn an emphasised phrase into an instruction. "Use" was the
#: only one, which made the guard's reach an accident of how a sentence had
#: been phrased rather than of what it was telling someone to do.
_VERBS = (r"(?:use|click|press|choose|select|pick|open|tick|untick|hit|tap"
          r"|go\s+to|head\s+to)")
USE_NAMED = re.compile(r"\b" + _VERBS + r"\s+(?:on\s+|the\s+)?<" + _EMPH
                       + r"[^>]*>((?:&#\d+;|&\w+;|[^<])*?)</" + _EMPH + r">",
                       re.I)

#: A control in somebody else's program, opted out at the sentence rather than
#: in a list that would rot: `<b data-external="Python installer">`. The
#: landing page tells people to tick "Add Python to PATH", which is real and is
#: never going to be rendered by this app. The attribute says whose it is,
#: which an allowlist somewhere else could not.
EXTERNAL = re.compile(r"<" + _EMPH + r"\s[^>]*\bdata-external\b[^>]*>"
                      r"((?:&#\d+;|&\w+;|[^<])*?)</" + _EMPH + r">")

ARROWS = ("&#11014;", "&#11015;", "⬆", "⬇", "→", "←")

#: Words that are emphasis rather than the name of a control. A bolded "not",
#: "before" or a bare number is not something anyone goes looking for.
NOT_A_CONTROL = re.compile(r"^(?:[\d.,%]+|[a-z]{1,4}|yes|no|not|never|always|"
                           r"before|after|now|none|all|and|or)$", re.I)


#: After one of these, a `/` begins a regular expression rather than dividing
#: something. The list is the practical one: a value cannot appear here, so a
#: slash cannot be division.
_REGEX_MAY_FOLLOW = set("(,=:[!&|?{};+-*%~^<>") | {""}
_REGEX_MAY_FOLLOW_WORDS = {"return", "typeof", "case", "in", "of", "new",
                           "delete", "void", "do", "else", "yield", "await"}


def _regex_can_start_here(out) -> bool:
    """Whether the `/` about to be read opens a regular expression."""
    j = len(out) - 1
    while j >= 0 and out[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return True
    ch = out[j]
    if ch in _REGEX_MAY_FOLLOW:
        return True
    if ch.isalnum() or ch in "_$":
        k = j
        while k >= 0 and (out[k].isalnum() or out[k] in "_$"):
            k -= 1
        return "".join(out[k + 1:j + 1]) in _REGEX_MAY_FOLLOW_WORDS
    return False


def strip_comments(src: str) -> str:
    """Remove // and /* */ comments without eating them out of strings.

    A one-pass scanner rather than a regex, because `'http://x'` inside a
    string literal is not a comment and a regex that thinks it is deletes the
    rest of the line - labels included.

    **Regular expressions have to be recognised too, and this is not fussiness.**
    `report.js` contains ``/[<>:"/\\\\|?*\\x00-\\x1f]/g``. A scanner that knows
    only about quotes sees the ``"`` inside that character class, decides a
    string has started, and never finds its end - so every comment in the rest
    of the file survives as though it were code. That is exactly how the first
    attempt at this guard passed with the defect in place: it read a comment in
    `report.js` naming the old button and took it for a label. The bug was in
    the stripper, not in the idea.
    """
    out = []
    i, n = 0, len(src)
    quote = None
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if quote:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(nxt)
                    i += 2
                    continue
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch == "/" and _regex_can_start_here(out):
            # Skip the literal whole, character class and all, so nothing
            # inside it is mistaken for a quote or a comment.
            out.append(ch)
            i += 1
            in_class = False
            while i < n:
                c = src[i]
                if c == "\\" and i + 1 < n:
                    out.append(c)
                    out.append(src[i + 1])
                    i += 2
                    continue
                if c == "\n":
                    break        # not a regex after all; give up on it
                out.append(c)
                i += 1
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    break
            continue
        out.append(ch)
        i += 1
    return "".join(out)


STRING = re.compile(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"|`((?:[^`\\]|\\.)*)`",
                    re.S)


def _unescape(s: str) -> str:
    """A JS string literal's body as the text it renders as.

    ``\\u2026`` matters here even though this codebase writes the character
    itself: a label that does use an escape still reaches the screen as the
    character, so a corpus that kept the escape would not contain the label
    anyone is told to look for.
    """
    s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), s)
    return (s.replace("\\'", "'").replace('\\"', '"').replace("\\`", "`")
             .replace("\\\\", "\\").replace("\\n", "\n").replace("\\t", "\t"))


def label_corpus(src: str) -> str:
    """Everything in *src* that could be a label, as one searchable blob.

    String literals joined by ``+`` are folded together, because that is how
    most labels in this suite are written and a literal search cannot
    otherwise see them.
    """
    pieces = []
    pos = 0
    pending = []
    for m in STRING.finditer(src):
        body = _unescape(next(g for g in m.groups() if g is not None))
        between = src[pos:m.start()]
        # Adjacent literals with nothing but a `+` (and whitespace) between
        # them are one string as far as the reader is concerned.
        if pending and re.fullmatch(r"\s*\+\s*", between):
            pending.append(body)
        else:
            if pending:
                pieces.append("".join(pending))
            pending = [body]
        pos = m.end()
    if pending:
        pieces.append("".join(pending))
    return "\n".join(pieces)


def html_text(src: str) -> str:
    """The text and attribute values of an HTML page, with <b> removed.

    The instruction is what is being checked, so it must not also be the
    evidence - a page saying "use <b>Cover image</b>" contains that string,
    and counting it would make every instruction self-satisfying.
    """
    src = BOLD.sub(" ", src)
    return src


def normalise(label: str) -> str:
    """The comparable form of a label: entities resolved, spacing flattened."""
    s = label
    for ent, ch in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&#39;", "'"), ("&hellip;", "…"),
                    ("&nbsp;", " "), ("&#8594;", "→"), ("&#8592;", "←"),
                    ("&#11014;", "⬆"), ("&#11015;", "⬇")):
        s = s.replace(ent, ch)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    s = re.sub(r"<[^>]*>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def web_files():
    for path in sorted(WEB.rglob("*")):
        if path.suffix.lower() in (".html", ".js") and path.is_file():
            if "node_modules" in path.parts:
                continue
            yield path


def build_corpus() -> str:
    """Every label the app can render, from every page and script."""
    blobs = []
    for path in web_files():
        src = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix.lower() == ".js":
            src = strip_comments(src)
            blobs.append(label_corpus(src))
        else:
            blobs.append(html_text(src))
    return normalise("\n".join(blobs))


def named_controls():
    """(file, label) for every control the app's own prose points at."""
    found = []
    for path in web_files():
        src = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix.lower() == ".js":
            src = strip_comments(src)
        names = {m for m in BOLD.findall(src)
                 if any(a in m for a in ARROWS)}
        names |= set(USE_NAMED.findall(src))
        names -= {normalise(m) for m in EXTERNAL.findall(src)}
        names -= set(EXTERNAL.findall(src))
        for raw in names:
            if "${" in raw or "' +" in raw or '" +' in raw:
                continue          # a template, pinned where the label is built
            label = normalise(raw)
            if not label or NOT_A_CONTROL.match(label):
                continue
            found.append((path.relative_to(ROOT).as_posix(), label))
    return sorted(set(found))


def satisfied_by(corpus: str, name: str) -> bool:
    """Whether *name* is a control the app really renders.

    A bolded name is usually one label - "Cloud → Local" is a single button,
    arrow and all - so the whole string is tried first. Where it is not found,
    the arrow is read as a route instead: "Menu → About" is two controls and
    an instruction to open one and then the other, and it is satisfied when
    every step of it exists. Trying the whole string first is what keeps a
    button whose own label contains an arrow from being split apart.
    """
    if name in corpus:
        return True
    if "→" not in name:
        return False
    steps = [normalise(s) for s in name.split("→")]
    return all(s and s in corpus for s in steps)


def main() -> int:
    # The names printed here contain arrows, and Windows decodes this stream as
    # cp1252, so printing one raised UnicodeEncodeError and the inventory died
    # part-way through its own list. The same trap as passing `encoding="utf-8"`
    # to a Node probe: the machine that reports the fault is the one nobody
    # trusts, because CI is UTF-8 and never sees it.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    corpus = build_corpus()
    rows = named_controls()
    missing = [(f, n) for f, n in rows if not satisfied_by(corpus, n)]
    print(f"{len(rows)} control names found in instructional prose, "
          f"across {len({f for f, _ in rows})} files")
    for f, n in rows:
        mark = "ok" if satisfied_by(corpus, n) else "MISSING"
        print(f"  [{mark:>7}] {f}: {n!r}")
    if missing:
        print(f"\n{len(missing)} named control(s) that nothing renders:")
        for f, n in missing:
            print(f"  {f}: {n!r}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
