"""Rewrite inline `onclick="..."` attributes as delegated `data-action` ones.

Backlog item 10. A Content-Security-Policy without `'unsafe-inline'` is the
second line of defence behind 264 `innerHTML` assignments, and inline event
attributes are exactly what such a policy forbids - so every control has to
move to the delegated dispatcher in `wd-shared.js` before a page can carry one.

**This is a mechanical rewriter for the shapes that are mechanical, and it
refuses everything else.** A conversion that guessed would silently produce a
control that renders and does nothing, which is the defect class this
repository has shipped four times. So it handles five forms and reports the
rest for a person to do by hand:

    fn()                        -> data-action="call" data-fn="fn"
    fn('literal')               -> ... data-arg="literal"
    fn(this.value)              -> ... data-arg-value="1"
    event.stopPropagation()     -> data-action="noop"
    WD.toggleMenu(event,'x')    -> data-action="menu" data-menu="x"

Anything with two arguments, arithmetic, a ternary or a call inside a call is
left alone and printed. Run it, read what it could not do, and convert those
by hand.

    python scripts/convert_inline_handlers.py web/home.html [...]
    python scripts/convert_inline_handlers.py --check web/home.html

`--check` writes nothing and exits non-zero if anything is left, which is what
the test uses.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

#: Every event this suite wires from markup. `load` and `error` are left out:
#: they fire on `<img>`/`<body>` before a delegated listener can usefully see
#: them, and nothing in the converted pages uses them.
EVENTS = ("click", "change", "input", "submit", "keyup", "keydown",
          "dblclick", "blur", "focus", "contextmenu", "wheel")

ATTR = re.compile(
    r'\son(' + "|".join(EVENTS) + r')="([^"]*)"', re.I)

CALL_NONE = re.compile(r"^([\w.$]+)\(\)$")
CALL_LITERAL = re.compile(r"^([\w.$]+)\(\s*'([^']*)'\s*\)$")
CALL_VALUE = re.compile(r"^([\w.$]+)\(\s*this\.value\s*\)$")
CALL_THIS = re.compile(r"^([\w.$]+)\(\s*this\s*\)$")
CALL_EVENT = re.compile(r"^([\w.$]+)\(\s*event\s*\)$")
MENU = re.compile(r"^WD\.toggleMenu\(\s*event\s*,\s*'([^']*)'\s*\)$")
STOP_ONLY = re.compile(r"^event\.stopPropagation\(\)$")


def _attrs(pairs) -> str:
    return "".join(' %s="%s"' % (k, html.escape(str(v), quote=True))
                   for k, v in pairs)


def convert_one(event: str, body: str):
    """The replacement attributes for one handler, or None if it is not one
    of the mechanical shapes."""
    code = html.unescape(body).strip().rstrip(";").strip()
    prefix = "data-action" if event == "click" else "data-action-" + event

    if STOP_ONLY.match(code):
        return _attrs([(prefix, "noop")])

    m = MENU.match(code)
    if m:
        return _attrs([(prefix, "menu"), ("data-menu", m.group(1))])

    for pattern, extra in ((CALL_NONE, []),
                           (CALL_VALUE, [("data-arg-value", "1")]),
                           (CALL_THIS, [("data-arg-this", "1")]),
                           (CALL_EVENT, [("data-arg-event", "1")])):
        m = pattern.match(code)
        if m:
            return _attrs([(prefix, "call"), ("data-fn", m.group(1))] + extra)

    m = CALL_LITERAL.match(code)
    if m:
        return _attrs([(prefix, "call"), ("data-fn", m.group(1)),
                       ("data-arg", m.group(2))])

    return None


def convert_text(text: str):
    """Returns (new_text, converted_count, [unconverted bodies])."""
    left = []
    count = 0

    def sub(match):
        nonlocal count
        replacement = convert_one(match.group(1).lower(), match.group(2))
        if replacement is None:
            left.append("on%s=\"%s\"" % (match.group(1), match.group(2)))
            return match.group(0)
        count += 1
        return replacement

    return ATTR.sub(sub, text), count, left


def main(argv) -> int:
    check = "--check" in argv
    paths = [Path(a) for a in argv if not a.startswith("-")]
    if not paths:
        print(__doc__)
        return 2

    total_left = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        new, count, left = convert_text(text)
        total_left += len(left)
        if check:
            status = "clean" if not left else "%d left" % len(left)
            print("%-28s %s" % (path.name, status))
        else:
            if new != text:
                path.write_text(new, encoding="utf-8")
            print("%-28s converted %d, left %d" % (path.name, count, len(left)))
        for body in left:
            print("    %s" % body)
    return 1 if (check and total_left) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
