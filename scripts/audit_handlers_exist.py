"""Every control the user can click must reach a handler that exists.

The `↑ Local newer · replace cloud` button was in the markup, its tests
asserted the markup contained `pushLocalOverCloud(`, and it did - and he could
not use it for days. A name in an `onclick` is a string until something calls
it, so this collects every handler named in every page and in every string of
markup the JS builds, and reports the ones nothing defines.

Static, so it is fast and needs no browser: a definition is
`window.NAME =`, `function NAME(`, `NAME = function`, `NAME: function`,
`const NAME =` / `let NAME =` / `var NAME =`, or `WD.NAME =`.

Run: python scripts/audit_handlers_exist.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: `onclick="foo(1)"` in a page, and `onclick=\"foo(` built inside a JS string.
CALL_IN_ATTR = re.compile(
    r"""on(?:click|change|input|submit|keydown|keyup|focus|blur|dblclick|
         contextmenu|mousedown|mouseup|mouseover|mouseenter|mouseleave)
        \s*=\s*(?P<q>["'\\]{1,2})(?P<body>.*?)(?P=q)""",
    re.X | re.I | re.S)

#: the first identifier being called inside that attribute
CALLS = re.compile(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(")

#: things that are not page handlers
BUILTIN = {
    "if", "for", "while", "switch", "return", "typeof", "new", "function",
    "catch", "alert", "confirm", "prompt", "parseInt", "parseFloat", "Number",
    "String", "Boolean", "Array", "Object", "JSON", "Math", "Date", "RegExp",
    "setTimeout", "setInterval", "clearTimeout", "encodeURIComponent",
    "decodeURIComponent", "event", "this", "console", "document", "window",
}


def definitions(js_text: str) -> set[str]:
    out: set[str] = set()
    for pat in (
        r"window\.([A-Za-z_$][\w$]*)\s*=",
        r"function\s+([A-Za-z_$][\w$]*)\s*\(",
        r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function",
        r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*\(",
        r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*async\s*\(",
        r"([A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s*)?function",
        r"WD\.([A-Za-z_$][\w$]*)\s*=",
    ):
        out |= set(re.findall(pat, js_text))
    return out


def main() -> int:
    js_files = sorted((WEB / "assets" / "js").glob("*.js"))
    html_files = sorted(WEB.glob("*.html")) + sorted((WEB / "pages").glob("*.html"))

    defined: set[str] = set()
    for f in js_files:
        defined |= definitions(f.read_text(encoding="utf-8", errors="replace"))
    # inline <script> in pages defines handlers too
    for f in html_files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for block in re.findall(r"<script\b[^>]*>(.*?)</script>", text, re.S | re.I):
            defined |= definitions(block)

    used: dict[str, list[str]] = {}
    for f in html_files + js_files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in CALL_IN_ATTR.finditer(text):
            body = m.group("body")
            for name in CALLS.findall(body):
                if name in BUILTIN:
                    continue
                where = "%s:%d" % (f.relative_to(ROOT).as_posix(),
                                   text[:m.start()].count("\n") + 1)
                used.setdefault(name, []).append(where)

    missing = {n: w for n, w in used.items() if n not in defined}

    print("handlers referenced from an event attribute: %d" % len(used))
    print("of those, nothing defines: %d" % len(missing))
    if missing:
        print()
        for name in sorted(missing):
            places = missing[name]
            print("  %-34s %s%s" % (name, places[0],
                                    ("  (+%d more)" % (len(places) - 1))
                                    if len(places) > 1 else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
