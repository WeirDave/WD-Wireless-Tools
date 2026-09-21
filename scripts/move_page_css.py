#!/usr/bin/env python3
"""Move each page's embedded <style> block into the shared stylesheet.

Backlog item 8. Run once; it is kept because the reasoning is the valuable part
and because a second page growing a block later should be moved the same way.

**The move is verbatim, and that is the safety property.** The CSS text is not
reformatted, reordered, merged or scoped, except for the six selectors named
below. Appending each block to the end of ``wd-tools.css`` keeps every rule in
the same cascade position it already had: an embedded ``<style>`` sits after the
``<link>`` in document order, so a page rule already beat a stylesheet rule of
equal specificity, and a page rule appended after the whole stylesheet still
does.

**The one thing that cannot move verbatim is Settings and Setup.** They define
eleven selectors in common and six of those have drifted *on purpose* - Setup
is the first-run wizard and is scaled up throughout: larger type, more padding,
bigger dots and hit areas. In one file the two collide and whichever is appended
second wins on both pages, which silently shrinks Setup or inflates Settings.

They cannot be told apart by body class either - **both pages carry
``tool-home``**. What does tell them apart is ``.setup-wrap``, the wrapper Setup
already has around its whole document, so Setup's six are scoped to it. That
raises their specificity from (0,0,1,0) to (0,0,2,0), which is what makes them
win on Setup while Settings keeps the unscoped rule. Three of the six match
elements that JavaScript builds into ``.sf-list`` and are never in the initial
DOM, which is why the rule-level half of the verification exists at all.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SHARED = WEB / "assets" / "wd-tools.css"

#: Appended in this order. Settings before Setup so that reading the stylesheet
#: shows the base rule and then the wizard's override of it, which is the order
#: they are explained in.
PAGES = [
    "ap-rename.html", "capacity.html", "plantrim.html", "prep.html",
    "walls.html", "pages/landing.html", "settings.html", "setup.html",
]

#: The six that drifted deliberately. Setup's copy of each is scoped; Settings'
#: copy moves as it is.
SETUP_SCOPED = [
    ".cloud-status",
    ".cloud-status .dot",
    ".sf-item",
    '.sf-item input[type="text"]',
    ".sf-handle",
    ".sf-remove",
]

HEADINGS = {
    "ap-rename.html": "AP Labeler",
    "capacity.html": "Capacity",
    "plantrim.html": "PlanTrim",
    "prep.html": "Prep",
    "walls.html": "Quick Walls",
    "pages/landing.html": "The public landing page",
    "settings.html": "Settings",
    "setup.html": "Setup - the first-run wizard",
}

NOTES = {
    "settings.html":
        "Eleven of these are also defined for Setup below, and six of those\n"
        "   have drifted on purpose. Read the Setup section before changing\n"
        "   any of them: merging the two is what this split exists to stop.",
    "setup.html":
        "Setup is the first-run wizard and is scaled up throughout - larger\n"
        "   type, more padding, bigger dots and hit areas. Six selectors it\n"
        "   shares with Settings are scoped to `.setup-wrap` for that reason,\n"
        "   because both pages carry `body.tool-home` and nothing else tells\n"
        "   them apart. They are two components that share a spelling, not one\n"
        "   component defined twice.",
    "pages/landing.html":
        "Served from the site root by .github/workflows/pages.yml, with\n"
        "   assets/ copied beside it - so it loads this stylesheet like every\n"
        "   other page.",
}


def style_block(text: str):
    m = re.search(r"([ \t]*)<style[^>]*>(.*?)</style>[ \t]*\n?", text, re.S)
    return m


def scope_setup(css: str) -> str:
    """Prefix Setup's six shared selectors with `.setup-wrap`.

    Only a selector that is exactly one of the six is touched. A rule whose
    selector merely starts with one of them is already more specific and
    already distinguishes itself.
    """
    out, count = [], 0
    for line in css.split("\n"):
        m = re.match(r"^(\s*)([^{}/]+?)(\s*\{.*)$", line)
        if m:
            indent, sels, rest = m.groups()
            parts = [s.strip() for s in sels.split(",")]
            if parts and all(p in SETUP_SCOPED for p in parts):
                sels = ", ".join(".setup-wrap " + p for p in parts)
                count += 1
                out.append(indent + sels + rest)
                continue
        out.append(line)
    if count != len(SETUP_SCOPED):
        raise SystemExit(
            "expected to scope %d Setup selectors, scoped %d - the block has "
            "been reformatted and this script's line matching no longer holds"
            % (len(SETUP_SCOPED), count))
    return "\n".join(out)


def main() -> int:
    shared = SHARED.read_text(encoding="utf-8")
    if "Moved out of the pages" in shared:
        print("already moved - nothing to do")
        return 0

    chunks = []
    for page in PAGES:
        path = WEB / page
        text = path.read_text(encoding="utf-8")
        m = style_block(text)
        if not m:
            print("  %-22s no <style> block, skipped" % page)
            continue
        css = m.group(2).strip("\n")
        if page == "setup.html":
            css = scope_setup(css)
        note = NOTES.get(page, "")
        header = ("/* %s\n   ---------------------------------------------------\n"
                  "   Moved out of %s.%s */\n"
                  % (HEADINGS[page], page, ("\n\n   " + note) if note else ""))
        chunks.append(header + css + "\n")
        # Take the block out of the page, leaving everything else byte for byte.
        path.write_text(text[:m.start()] + text[m.end():], encoding="utf-8")
        print("  %-22s moved %4d lines" % (page, css.count("\n") + 1))

    banner = (
        "\n\n"
        "/* ===================================================================\n"
        "   Moved out of the pages\n"
        "   ===================================================================\n"
        "\n"
        "   Eight pages carried their own <style> block - 831 lines of it. They\n"
        "   are here now, appended verbatim and in one place, so that a change\n"
        "   to a shared component is made once.\n"
        "\n"
        "   **Appended, and the position is load-bearing.** An embedded block\n"
        "   sits after the <link> in document order, so a page rule already beat\n"
        "   a stylesheet rule of equal specificity; at the end of this file it\n"
        "   still does. Moving any of this earlier can flip a tie without a\n"
        "   single selector changing, which is the kind of break that shows up\n"
        "   as two pixels in a screenshot and is obvious in computed styles -\n"
        "   see scripts/capture_computed_styles.py.\n"
        "   =================================================================== */\n\n")
    SHARED.write_text(shared.rstrip("\n") + banner + "\n\n".join(chunks),
                      encoding="utf-8")
    print("appended %d blocks to %s" % (len(chunks), SHARED.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
