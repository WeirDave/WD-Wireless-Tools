"""A report is printed on someone else's machine, so its fonts have to exist there.

He printed a report through Adobe PDF and got a log file where the PDF should
have been:

    CascadiaCode-Regular not found, using Courier.
    %%[ Error: invalidfont; OffendingCommand: show ]%%
    %%[ Flushing: rest of job (to end-of-file) will be ignored ]%%
    %%[ Warning: PostScript error. No PDF file produced. ]%%

**The missing generic fallback was not the cause, and a test for one would have
passed on the broken stylesheet.** The stack was

    --mono: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;

which ends in `monospace` and always did. Nothing ever fell back. `SF Mono` is
not on Windows, so Windows resolved **Cascadia Code** - a font that arrives with
Windows Terminal and VS Code, so it is on a developer's machine and on almost
nobody else's. Firefox printed to the Adobe PDF PostScript driver, referenced
the face by its PostScript name, Distiller could not embed it, and abandoned
the job.

So there are two rules here and the second is the one that matters:

  * every stack ends in a generic family - cheap, mechanical, and would not
    have caught this;
  * **every named face in a stack ships with an operating system.** A font that
    resolves on the machine that built the report and not on the machine that
    prints it is the whole defect, and preferring a developer font is how it
    happened.

The allowlist is deliberately short. Adding to it means arguing that the face
is present on a stock install of Windows, macOS or Linux - or embedding it as a
web font so it travels with the document, which is the other legitimate answer
and is not what was being done here.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

GENERIC = {
    "monospace", "sans-serif", "serif", "cursive", "fantasy",
    "system-ui", "ui-monospace", "ui-sans-serif", "ui-serif", "ui-rounded",
    "math", "emoji", "fangsong",
}

#: Values that are not a font stack at all.
NOT_A_STACK = {"inherit", "initial", "unset", "revert", "revert-layer"}

#: Faces that arrive with an operating system, or are a browser keyword for
#: whatever the system uses. Each one is here because it ships, not because it
#: looks nice.
OS_SHIPPED = {
    # keywords resolving to whatever the platform provides
    "-apple-system", "blinkmacsystemfont",
    # Windows
    "consolas", "segoe ui", "segoe ui emoji", "segoe ui symbol", "tahoma",
    "calibri", "cambria", "candara", "arial", "times new roman",
    "courier new", "georgia", "verdana", "trebuchet ms", "lucida console",
    # macOS
    "menlo", "monaco", "helvetica", "helvetica neue", "geneva", "avenir",
    "avenir next", "sf mono", "san francisco", "apple color emoji",
    # Linux / cross-platform free faces that distributions ship
    "dejavu sans", "dejavu sans mono", "dejavu serif",
    "liberation sans", "liberation mono", "liberation serif",
    "noto sans", "noto color emoji", "ubuntu", "ubuntu mono", "cantarell",
}


#: `font-family:` and the custom properties that hold a stack for it.
#:
#: Scanning only `font-family` was this file's own version of the bug it is
#: about. Almost every rule in the suite says `font-family: var(--mono)`, so the
#: stack that actually reaches the printer lives in `--mono` - and a check that
#: never reads it passed happily on `'SF Mono', 'Cascadia Code', ...`, the exact
#: declaration that produced a PostScript error log instead of a PDF. Found by
#: putting the broken stack back and watching the suite stay green.
_STACK_RE = re.compile(
    r"(?:font-family|--(?:mono|sans|serif)[\w-]*)\s*:\s*([^;}\n]+)")


def _declarations():
    """(file, line, raw stack) for every font stack in anything served."""
    for path in sorted(WEB.rglob("*")):
        if path.suffix not in (".css", ".html", ".js"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # Comments hold example CSS and prose; neither is served.
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        for m in _STACK_RE.finditer(text):
            raw = m.group(1).strip()
            raw = re.sub(r"!important\s*$", "", raw).strip().rstrip(";").strip()
            if not raw:
                continue
            yield (path.relative_to(ROOT).as_posix(),
                   text[:m.start()].count("\n") + 1, raw)


def _faces(stack: str):
    for part in stack.split(","):
        face = part.strip().strip("'\"").strip()
        if face:
            yield face


class EveryStackEndsInAGenericFamily(unittest.TestCase):
    """The cheap half. A stack that dead-ends at a named font gives a print
    engine nothing to substitute, which is how a missing face becomes a failed
    job rather than a slightly different letterform."""

    def test_no_declaration_dead_ends_at_a_named_font(self):
        offenders = []
        for where, line, stack in _declarations():
            if stack.startswith("var(") or stack.lower() in NOT_A_STACK:
                continue
            last = list(_faces(stack))[-1].lower()
            if last not in GENERIC and not last.startswith("var("):
                offenders.append("%s:%d  %s" % (where, line, stack))
        self.assertEqual(
            [], offenders,
            "these font stacks end at a named font, so a machine without it "
            "has nothing to fall back to:\n  " + "\n  ".join(offenders))

    def test_the_variables_themselves_end_in_a_generic(self):
        """Almost every rule uses `var(--mono)` or `var(--sans)`, so checking
        the rules without checking the variables checks nothing."""
        css = (WEB / "assets" / "wd-tools.css").read_text(encoding="utf-8")
        found = dict(re.findall(r"(--(?:mono|sans|serif)[\w-]*)\s*:\s*([^;]+);", css))
        self.assertTrue(found, "no font variables found; have they been renamed?")
        for name, stack in found.items():
            with self.subTest(variable=name):
                last = list(_faces(stack))[-1].lower()
                self.assertIn(last, GENERIC,
                              "%s ends at %r" % (name, last))


class EveryNamedFaceShipsWithAnOperatingSystem(unittest.TestCase):
    """The half that would have caught the failure.

    The broken stack had a generic fallback and never reached it. What broke
    the print was *preferring* a font that only a developer's machine has.
    """

    def test_no_stack_prefers_a_font_that_may_not_be_installed(self):
        offenders = []
        for where, line, stack in _declarations():
            if stack.startswith("var(") or stack.lower() in NOT_A_STACK:
                continue
            for face in _faces(stack):
                low = face.lower()
                if low in GENERIC or low in OS_SHIPPED or low.startswith("var("):
                    continue
                offenders.append("%s:%d  %r in %s" % (where, line, face, stack))
        self.assertEqual(
            [], offenders,
            "these name a face that does not ship with an operating system. "
            "It will resolve on the machine that built the report and not on "
            "the machine that prints it - which is how 'Cascadia Code' turned "
            "a report into a PostScript error log. Use an OS face, or embed "
            "the font so it travels with the document:\n  "
            + "\n  ".join(offenders))

    def test_the_font_that_broke_it_is_not_referenced_anywhere(self):
        """Named, because this is the one that cost him a document."""
        for where, line, stack in _declarations():
            with self.subTest(where=where, line=line):
                self.assertNotIn("cascadia", stack.lower())

    def test_the_mono_stack_covers_windows_and_macos_and_a_generic(self):
        """Fixing this for Windows by naming only a Windows face would fail
        the same way on a Mac, which is the other half of what he asked for."""
        css = (WEB / "assets" / "wd-tools.css").read_text(encoding="utf-8")
        stack = re.search(r"--mono\s*:\s*([^;]+);", css)
        self.assertIsNotNone(stack, "--mono moved")
        faces = [f.lower() for f in _faces(stack.group(1))]
        self.assertIn("consolas", faces, "no face that ships with Windows")
        self.assertTrue({"menlo", "monaco", "sf mono"} & set(faces),
                        "no face that ships with macOS")
        self.assertEqual(faces[-1], "monospace")

    def test_the_sans_stack_covers_both_too(self):
        css = (WEB / "assets" / "wd-tools.css").read_text(encoding="utf-8")
        stack = re.search(r"--sans\s*:\s*([^;]+);", css)
        self.assertIsNotNone(stack, "--sans moved")
        faces = [f.lower() for f in _faces(stack.group(1))]
        self.assertTrue({"-apple-system", "blinkmacsystemfont", "helvetica neue"}
                        & set(faces), "nothing resolving to the macOS UI face")
        self.assertTrue({"segoe ui", "tahoma", "arial"} & set(faces),
                        "nothing that ships with Windows")
        self.assertEqual(faces[-1], "sans-serif")


class NothingIsFetchedFromTheNetwork(unittest.TestCase):
    """The suite runs offline and the printing happens behind a corporate
    proxy. A face fetched at print time is a blank page waiting to happen, and
    the strict policy forbids it anyway.

    Collected rather than searched for by name: naming `fonts.googleapis.com`
    catches Google and misses every other host, and the property is that
    **nothing** is fetched.
    """

    def _remote_font_sources(self):
        found = set()
        for path in sorted(WEB.rglob("*")):
            if path.suffix not in (".css", ".html"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
            for block in re.findall(r"@font-face\s*\{([^}]*)\}", text):
                for url in re.findall(r"url\(\s*['\"]?([^)'\"]+)", block):
                    if re.match(r"https?:|//", url.strip()):
                        found.add((path.name, url.strip()))
            for m in re.finditer(
                    r"""<link[^>]+rel=['\"]?stylesheet[^>]*>""", text, re.I):
                href = re.search(r"""href=['\"]([^'\"]+)""", m.group(0))
                if href and re.match(r"https?:|//", href.group(1).strip()):
                    found.add((path.name, href.group(1).strip()))
        return found

    def test_no_font_or_stylesheet_comes_from_off_this_machine(self):
        remote = sorted(self._remote_font_sources())
        self.assertEqual(
            [], remote,
            "these are fetched over the network, so they are missing on a "
            "machine that cannot reach them and the text falls back silently "
            "or not at all: " + ", ".join("%s -> %s" % r for r in remote))


if __name__ == "__main__":
    unittest.main()
