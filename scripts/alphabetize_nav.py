"""Reorder nav menus and landing cards alphabetically across the suite.

Canonical order (by displayed tool name):
    Cloud Manager   href="/cloud"       href="cloud/"
    Quick Walls     href="/walls"       href="walls/"
    Report          href="/report"      href="report/"
    Scale           href="/scale"       href="scale/"
    Squirrel        href="/organizer"   href="organizer/"

For nav menus: find any consecutive run of 5 <a class="(menu|help-menu)-item"
lines (each linking to one of the five paths) and re-sort by canonical order.
For landing cards: find any consecutive run of 5 <a class="card"> BLOCKS and
re-sort by canonical order (each block spans several lines).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Canonical order — first item is the KEY string that identifies which tool
# the link/card belongs to. Search for this substring in href attributes.
ORDER = ['/cloud', '/walls', '/report', '/scale', '/organizer']
# For hosted-index.html which uses relative paths:
ORDER_RELATIVE = ['cloud/', 'walls/', 'report/', 'scale/', 'organizer/']

HTML_FILES = [
    'web/home.html', 'web/cloud.html', 'web/walls.html', 'web/organizer.html',
    'web/scale.html', 'web/report.html', 'web/guide.html',
    'web/guide-cloud.html', 'web/guide-organizer.html',
    'web/pages/hosted-index.html',
]


def which_tool(href, order):
    """Return the index in `order` of the tool that this href belongs to, or -1."""
    for i, key in enumerate(order):
        if key in href:
            return i
    return -1


def reorder_nav_lines(text, order):
    """Find consecutive runs of nav <a> items and sort them.

    A run is identified as a maximal sequence of consecutive lines where each
    line contains href="XXX" with XXX matching one of the order keys, and each
    key appears exactly once in the run (so runs like Home->tool_link->tool_link
    -> Tools_section stay isolated).
    """
    lines = text.splitlines(keepends=True)
    out = []
    i = 0
    changed = False
    while i < len(lines):
        # Look ahead — try to find a run of exactly 5 lines whose href-key values
        # are a permutation of the canonical set.
        run_end = i
        keys_seen = set()
        for j in range(i, min(i + 5, len(lines))):
            m = re.search(r'href="([^"]+)"', lines[j])
            if not m:
                break
            k = which_tool(m.group(1), order)
            if k < 0:
                break
            if k in keys_seen:
                break
            keys_seen.add(k)
            run_end = j + 1
        run_size = run_end - i
        if run_size == 5 and keys_seen == set(range(5)):
            # We have a full 5-tool run — reorder.
            run_lines = lines[i:run_end]
            run_lines.sort(key=lambda L: which_tool(re.search(r'href="([^"]+)"', L).group(1), order))
            if run_lines != lines[i:run_end]:
                changed = True
            out.extend(run_lines)
            i = run_end
        else:
            out.append(lines[i])
            i += 1
    return ''.join(out), changed


def reorder_landing_cards(text, order):
    """Landing-card blocks look like:
        <a class="card blue" href="cloud/">
          ...several lines...
        </a>
    Match maximal runs of 5 consecutive <a class="card ..."> blocks and sort.
    """
    # Pattern: <a class="card ..." href="XXX">...</a>
    pattern = re.compile(r'(<a class="card[^"]*" href="([^"]+)"[\s\S]*?</a>)')
    # Find all card blocks with their positions and href
    matches = list(pattern.finditer(text))
    if not matches:
        return text, False

    # Group consecutive card blocks (no gap between them beyond whitespace)
    # Simpler: assume the file has ONE block of 5 cards. If len(matches)==5,
    # reorder them and reinsert.
    if len(matches) != 5:
        return text, False
    hrefs = [m.group(2) for m in matches]
    positions = [which_tool(h, order) for h in hrefs]
    if any(p < 0 for p in positions):
        return text, False
    if positions == sorted(positions):
        return text, False  # already sorted

    # Extract the between-cards separators (usually whitespace/newlines)
    blocks = [m.group(1) for m in matches]
    sorted_pairs = sorted(zip(positions, blocks))
    sorted_blocks = [b for _, b in sorted_pairs]
    # Rebuild: replace each original card in order with the newly-sorted card
    new_text_parts = []
    last_end = 0
    for i, m in enumerate(matches):
        new_text_parts.append(text[last_end:m.start()])
        new_text_parts.append(sorted_blocks[i])
        last_end = m.end()
    new_text_parts.append(text[last_end:])
    return ''.join(new_text_parts), True


for rel in HTML_FILES:
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    original = s
    # Try both relative and absolute path orders
    for order in (ORDER, ORDER_RELATIVE):
        new_s, changed_nav = reorder_nav_lines(s, order)
        new_s, changed_cards = reorder_landing_cards(new_s, order)
        s = new_s
    if s != original:
        p.write_text(s, encoding='utf-8', newline='')
        print(f'CHANGED: {rel}')
    else:
        print(f'no change: {rel}')
