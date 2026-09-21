"""An HTML attribute needs the attribute escaper, not the text one.

`WD.esc` escapes by round-tripping through `textContent`, so it converts `&`,
`<` and `>` and **leaves the double quote alone** - which is correct, because a
quote needs no escaping in element text. `WD.escAttr` escapes the quote and the
apostrophe as well. The two are not interchangeable, and the one that looks
like the general-purpose escaper is the one that is wrong inside an attribute.

**This was live.** An AP name is read straight out of the `.esx` and rendered
into the preview table as `title="' + esc(curTxt) + '"`. A project whose AP was
named

    <img src=x onerror="...">" onmouseover="..." HOSTILE

closed the `title` attribute on its own quote and everything after it parsed as
further attributes, so a real `onmouseover` handler landed on two `<td>` cells
and ran when the pointer crossed them. The *text* on either side of it was
escaped correctly the whole time, which is why reading the line did not show
it: the bug is in the quoting of the attribute, not in the escaping of the
content. Driving a hostile `.esx` through AP Labeler in Firefox is what found
it.

Twenty-five call sites across seven files had the same shape. Two other files -
`walls-swap.js` and `settings-page.js` - had already grown their own local
`esc` that escapes the quote, which is the same "three private copies of the
answer" pattern that `WD.readableOn` exists to stop; they were left correct and
switched to the shared helper.

So this file is a guard rather than a unit test: it reads the shipped JavaScript
and fails if an attribute value is ever built with the text escaper again.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JS_DIR = ROOT / "web" / "assets" / "js"


def _comment_lines(text: str) -> set:
    """Line numbers that hold nothing but a comment.

    Tracked across lines rather than tested one at a time: the notes in
    these files are `/* ... */` blocks several paragraphs long, and only the
    first line of one starts with a comment marker. A line-at-a-time test
    passed the opening line and then fired on the third paragraph - which,
    when the paragraph is the one *explaining* the bug being checked for, is
    a check that fires on its own explanation.

    A comment trailing real code does not count: that line still carries the
    code the checks are looking at.
    """
    out = set()
    in_block = False
    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if in_block:
            out.add(number)
            if "*/" in stripped:
                in_block = False
                # Code after the close is still code.
                if stripped.split("*/", 1)[1].strip():
                    out.discard(number)
            continue
        if stripped.startswith("//"):
            out.add(number)
            continue
        if stripped.startswith("/*"):
            out.add(number)
            if "*/" not in stripped:
                in_block = True
            elif stripped.split("*/", 1)[1].strip():
                out.discard(number)
    return out

# `attr="` immediately followed by a call to a text escaper, in any of the four
# ways this codebase builds markup.
TEXT_ESCAPER_IN_ATTR = [
    re.compile(r"""(\w[\w-]*)\s*=\s*"\s*\+\s*(?:WD\.)?\b(esc|e)\s*\("""),
    re.compile(r"""(\w[\w-]*)\s*=\s*"'\s*\+\s*(?:WD\.)?\b(esc|e)\s*\("""),
    re.compile(r"""(\w[\w-]*)\s*=\s*\\?"\$\{\s*(?:WD\.)?(esc|e)\s*\("""),
    re.compile(r"""(\w[\w-]*)\s*=\s*'\s*\+\s*(?:WD\.)?\b(esc|e)\s*\("""),
]

#: `JSON.stringify(x).replace(/"/g, '&quot;')`, which is not an escaper.
#:
#: **Two call sites had this and the guard above could not see either**, so
#: they survived the v2.146.1 pass and were found by the 2026-09-20 sweep:
#: the rename-profile Apply and Delete buttons, and Cloud Manager's share
#: recipient suggestions.
#:
#: Why it looks right: `stringify` escapes the double quote and the
#: backslash, and the replace turns the quotes it added into entities so
#: they cannot close the attribute. What it never touches is the
#: **ampersand**. So a value containing the six characters `&quot;` passes
#: through intact, the browser decodes that entity to a real quote when it
#: reads the attribute, and the JavaScript string ends there. A profile
#: named `x&quot;);alert(1);//` ran in Firefox, Chrome and Edge.
#:
#: The rule this encodes: an escaper is a function that exists for the job.
#: A pipeline of string operations assembled at the call site is a fourth
#: private opinion about escaping, and this codebase has paid for three.
STRINGIFY_AS_AN_ESCAPER = re.compile(
    r"""JSON\.stringify\s*\([^)]*\)\s*\.\s*replace\s*\(""")

#: A value interpolated into an event attribute without going through the
#: JS-string escaper. The handlers in this suite are wired with inline
#: `onclick`, so this is the sink that matters most.
EVENT_ATTRS = (
    "click", "change", "input", "mousedown", "mouseup", "mouseover",
    "mouseenter", "mouseleave", "keydown", "keyup", "keypress", "submit",
    "focus", "blur", "dblclick", "contextmenu", "error", "load",
)
#: Interpolations that are safe in a handler without an escaper at the point
#: of use: a loop index, a literal, `this`, `event`, and the escapers.
#:
#: `esc` and `e` are **not** on this list. They escape for element text and
#: leave the apostrophe, which is what let a CSV column header out of a
#: JavaScript string in `rename.js` - the same distinction the rest of this
#: file is about, one sink further along.
_SAFE_IN_HANDLER = re.compile(
    r"^(?:WD\.)?(?:escJsStr|escAttr|a|j|pj|encodeURIComponent"
    r"|Number|parseInt|parseFloat)\s*\(|"
    r"^(?:i|j|k|n|idx|index|this|event|true|false|null|-?\d+)$")

#: Named values that are escaped where they are assigned rather than where
#: they are used, or that are a whole call expression a caller built.
#:
#: Every one is listed with the file it lives in, so adding a name here is a
#: decision about one place rather than a hole opened everywhere. **Read the
#: assignment before adding to this.** The point of the check is that the
#: escaping is visible; an entry here is a promise that it is visible three
#: lines up instead.
_ESCAPED_AT_ASSIGNMENT = {
    # `const jid = escJsStr(g.id)` / `const safe = WD.escJsStr(r.email)`
    ("walls-swap.js", "jid"),
    ("cloud.js", "safe"),
    # `const kAttr = j(cl.key)` / `const iidAttr = j(...)`
    ("cloud.js", "kAttr"),
    ("cloud.js", "iidAttr"),
    # `const arg = a(JSON.stringify(where))` - stringify then the attribute
    # escaper, which escapes the ampersand *first*, so an entity written
    # into the value stays an entity. This is the correct form of the thing
    # `test_no_value_is_escaped_by_stringify_and_a_replace` rejects.
    ("cloud.js", "arg"),
    # A whole `fn('escaped', 'args')` string the caller assembled;
    # `menuItem` and `rdAction` only place it. The callers' escaping is what
    # `tests/test_cloud_sync_direction.py` executes and pins.
    ("cloud.js", "call"),
    # `newOpId()` is `'op-' + Math.random().toString(36)`.
    ("cloud.js", "op.id"),
    # One of two literal element ids chosen by a ternary above.
    ("rename.js", "inputId"),
    # 'portrait' / 'landscape', passed in by the two call sites below it.
    ("report.js", "val"),
    # `const val = 'i:' + i` - the index into the suggestion list.
    ("cloud.js", "val"),
}


class AttributeEscaping(unittest.TestCase):

    def test_no_attribute_is_built_with_the_text_escaper(self):
        """Every `attr="..."` interpolation uses escAttr, a(), or WD.escAttr.

        A hit here is not necessarily exploitable - the value may be a constant
        this file controls - but the shape is the one that was exploitable, and
        allowing the safe-looking cases back in is how the unsafe ones return.
        """
        offenders = []
        for path in sorted(JS_DIR.glob("*.js")):
            for lineno, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
                for pattern in TEXT_ESCAPER_IN_ATTR:
                    for match in pattern.finditer(line):
                        offenders.append(
                            f"{path.name}:{lineno} attribute `{match.group(1)}` "
                            f"uses `{match.group(2)}(` - use the attribute escaper")
        self.assertEqual(
            [], offenders,
            "attribute values must use escAttr/a(), which escapes the quote:\n  "
            + "\n  ".join(offenders))

    def test_no_value_is_escaped_by_stringify_and_a_replace(self):
        """The shape that got past the check above, twice.

        Checked against the bug: restoring either call site fails this.
        """
        offenders = []
        for path in sorted(JS_DIR.glob("*.js")):
            text = path.read_text(encoding="utf-8", errors="replace")
            # A comment naming the shape is the *fix* explaining itself. A
            # check that fires on its own explanation teaches the next
            # session to delete the explanation, which is how the reason
            # for a rule gets lost.
            comments = _comment_lines(text)
            for lineno, line in enumerate(text.split("\n"), 1):
                if lineno in comments:
                    continue
                if STRINGIFY_AS_AN_ESCAPER.search(line):
                    offenders.append(f"{path.name}:{lineno} {line.strip()[:90]}")
        self.assertEqual(
            [], offenders,
            "`JSON.stringify(x).replace(...)` is not an escaper - it leaves "
            "the ampersand, so `&quot;` in the value becomes a real quote "
            "when the browser reads the attribute. Use WD.escJsStr:\n  "
            + "\n  ".join(offenders))

    def test_every_event_attribute_escapes_what_it_interpolates(self):
        """A handler is a JavaScript string inside an HTML attribute.

        Two layers of decoding sit between the source and the code that
        runs, which is why the escaper for it is its own function. A value
        dropped in raw is a call site waiting to become the next one of
        these.
        """
        # The attribute *value* only. Taking the rest of the line instead
        # swept up every interpolation in the markup that follows the
        # handler and reported forty-odd icons and loop counters, which is
        # the noise that gets a check switched off.
        attr = re.compile(
            r"""\bon(?:""" + "|".join(EVENT_ATTRS) + r""")\s*=\s*"((?:[^"]|\\")*)"|"""
            r"""\bon(?:""" + "|".join(EVENT_ATTRS) + r""")\s*=\s*\\"((?:[^\\]|\\[^"])*)\\\"""")
        slot = re.compile(r"'\s*\+\s*([^+]{1,120}?)\s*\+\s*'|\$\{([^{}]{1,120})\}")

        offenders = []
        for path in sorted(JS_DIR.glob("*.js")):
            for lineno, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
                for found in attr.finditer(line):
                    value = found.group(1) or found.group(2) or ""
                    for match in slot.finditer(value):
                        expr = (match.group(1) or match.group(2) or "").strip()
                        if not expr or _SAFE_IN_HANDLER.match(expr):
                            continue
                        if (path.name, expr) in _ESCAPED_AT_ASSIGNMENT:
                            continue
                        # A ternary between two literals carries no value.
                        if re.fullmatch(r"[^'\"]*\?\s*'[^']*'\s*:\s*'[^']*'", expr):
                            continue
                        offenders.append(
                            f"{path.name}:{lineno} `{expr}` in an event attribute")
        self.assertEqual(
            [], offenders,
            "these interpolate into an inline handler with no JS-string "
            "escaper - use WD.escJsStr:\n  " + "\n  ".join(offenders))

    def test_the_two_escapers_differ_on_the_quote(self):
        """The distinction this whole file rests on, asserted directly.

        If `WD.esc` ever starts escaping the quote this guard becomes
        unnecessary; it should fail loudly rather than quietly stay true.
        """
        shared = (JS_DIR / "wd-shared.js").read_text(encoding="utf-8")

        esc_body = re.search(r"WD\.esc\s*=\s*function[^}]*?\{(.*?)\n  \};",
                             shared, re.S)
        self.assertIsNotNone(esc_body, "WD.esc not found in wd-shared.js")
        self.assertIn("textContent", esc_body.group(1),
                      "WD.esc is expected to escape via textContent, which "
                      "does not touch the double quote")

        attr_body = re.search(r"WD\.escAttr\s*=\s*function[^}]*?\{(.*?)\n  \};",
                              shared, re.S)
        self.assertIsNotNone(attr_body, "WD.escAttr not found in wd-shared.js")
        for needed in ('&quot;', '&#39;', '&amp;', '&lt;', '&gt;'):
            self.assertIn(needed, attr_body.group(1),
                          f"WD.escAttr must produce {needed}")


if __name__ == "__main__":
    unittest.main()
