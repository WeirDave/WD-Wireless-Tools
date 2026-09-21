"""The CSS that applies to a page, wherever it happens to live.

Several tests check that a rule exists and reaches a particular page - that the
AP Labeler's sidebar does not scroll, that PlanTrim's stage has a drawing
cursor. Each of them read the page's HTML, because that is where the rule was
when it was written: every one of these pages carried its own ``<style>``
block.

Backlog item 8 moved all eight of those blocks into ``wd-tools.css``, and every
one of those tests failed. **Not one of them was testing the location** - the
location was incidental, and hard-coding it meant a change that moved no rule
and altered no computed value broke seventeen tests.

So the question is asked properly here: give it a page, get back everything
that styles it. A rule found through this is a rule the browser will apply,
which is what the callers meant, and the next time the CSS moves this is the
only file that has to know.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SHARED = WEB / "assets" / "wd-tools.css"


def page_blocks(page: str) -> str:
    """Whatever the page still carries inline. Usually nothing now."""
    path = WEB / page
    text = path.read_text(encoding="utf-8")
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))


def css_for(page: str) -> str:
    """Every rule that can apply to *page*: the shared sheet plus its own block.

    In cascade order - the linked stylesheet first, then anything embedded,
    which is the order the browser sees them in and therefore the order that
    decides a tie.
    """
    return SHARED.read_text(encoding="utf-8") + "\n" + page_blocks(page)


def rule_for(page: str, selector: str) -> str:
    """The body of the first rule whose selector is exactly *selector*.

    Returns ``""`` when there is none. Matched on the whole selector rather
    than as a substring, so ``.ar-sidebar`` does not return the rule for
    ``.ar-sidebar .foo``.
    """
    css = css_for(page)
    pattern = re.compile(
        r"(?:^|[\n};])\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", re.S)
    m = pattern.search(css)
    return m.group(1) if m else ""
