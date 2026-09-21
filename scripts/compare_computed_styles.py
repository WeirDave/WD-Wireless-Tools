#!/usr/bin/env python3
"""Compare two captures and report what actually changed on screen.

Usage:
    python scripts/compare_computed_styles.py <baseline-dir> <after-dir>

Exit 0 when nothing a reader could see has moved, 1 otherwise.

**A difference here is not automatically a defect**, and the report is written
to be read rather than to be a pass/fail light. Moving a declaration into the
stylesheet legitimately changes where it came from; what must not change is
what an element computes to. So the computed half is the strict one, and the
rule half is advisory - it says which selectors changed cascade position, which
is the list to read when the computed half disagrees.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

#: Properties whose value legitimately differs between two runs of the same
#: page and says nothing about the CSS.
#:
#: Nothing layout-affecting is in here on purpose. It would be easy to silence
#: a real regression by adding `width` to this list, and a comparison that can
#: be quieted that way is not worth running.
NOISE = {
    # An animation's current position depends on when the capture happened.
    "animation-delay", "animation-play-state", "transition-delay",
    # Firefox reports the resolved URL of a blob or a data URI, which carries a
    # per-run identifier.
    "background-image", "border-image-source", "list-style-image",
    # Scrollbar geometry moves with content that has not settled.
    "scrollbar-color", "scrollbar-width",
}


def load(d: Path):
    out = {}
    for path in sorted(d.glob("*.json")):
        out[path.name] = json.loads(path.read_text(encoding="utf-8"))
    return out


def describe(el) -> str:
    bits = [el["tag"]]
    if el["id"]:
        bits.append("#" + el["id"])
    if el["cls"]:
        bits.append("." + ".".join(el["cls"].split()[:3]))
    return "".join(bits)


def compare_computed(base, after, name, findings):
    b, a = base["computed"], after["computed"]
    if len(b) != len(a):
        findings.append(
            (name, "the page has a different number of elements: "
                   "%d then %d - this is not a CSS-only change" % (len(b), len(a))))
        return
    for eb, ea in zip(b, a):
        if eb["tag"] != ea["tag"]:
            findings.append((name, "element %d changed from <%s> to <%s>"
                                   % (eb["i"], eb["tag"], ea["tag"])))
            continue
        for prop, vb in eb["props"].items():
            if prop in NOISE:
                continue
            va = ea["props"].get(prop)
            if va != vb:
                findings.append(
                    (name, "%s (element %d) %s: %r -> %r"
                           % (describe(eb), eb["i"], prop, vb, va)))


def compare_rules(base, after):
    """Advisory: which selectors moved, appeared or vanished."""
    def by_sel(blob):
        out = defaultdict(list)
        for r in blob["rules"]:
            out[(r["media"] + r["selector"]).strip()].append(r)
        return out
    b, a = by_sel(base), by_sel(after)
    gone = sorted(set(b) - set(a))
    new = sorted(set(a) - set(b))
    moved = []
    for sel in sorted(set(b) & set(a)):
        if [r["decls"] for r in b[sel]] != [r["decls"] for r in a[sel]]:
            moved.append(sel)
    return gone, new, moved


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    base_dir, after_dir = Path(sys.argv[1]), Path(sys.argv[2])
    base, after = load(base_dir), load(after_dir)

    only_base = sorted(set(base) - set(after))
    only_after = sorted(set(after) - set(base))
    if only_base or only_after:
        print("captures do not line up:")
        for n in only_base:
            print("  only in baseline: " + n)
        for n in only_after:
            print("  only in after:    " + n)
        return 1

    findings = []
    rule_notes = []
    for name in sorted(base):
        compare_computed(base[name], after[name], name, findings)
        gone, new, moved = compare_rules(base[name], after[name])
        if gone or new or moved:
            rule_notes.append((name, gone, new, moved))

    print("=" * 74)
    print("COMPUTED STYLE DIFFERENCES  (these are what a reader would see)")
    print("=" * 74)
    if not findings:
        print("  none - every element computes to exactly what it did before")
    else:
        # Grouped, because one changed rule shows up on every element it
        # matches and an ungrouped list buries the count.
        by_page = defaultdict(list)
        for name, msg in findings:
            by_page[name].append(msg)
        for name in sorted(by_page):
            msgs = by_page[name]
            print("\n%s  (%d)" % (name, len(msgs)))
            for msg in msgs[:25]:
                print("    " + msg)
            if len(msgs) > 25:
                print("    ... and %d more" % (len(msgs) - 25))
    print()
    print("=" * 74)
    print("CASCADE CHANGES  (advisory - read these when the above is not empty)")
    print("=" * 74)
    if not rule_notes:
        print("  none")
    for name, gone, new, moved in rule_notes:
        print("\n%s" % name)
        for sel in gone[:12]:
            print("    selector no longer defined anywhere: %s" % sel)
        for sel in new[:12]:
            print("    selector is new:                     %s" % sel)
        for sel in moved[:12]:
            print("    declarations for this changed:       %s" % sel)
        extra = max(0, len(gone) - 12) + max(0, len(new) - 12) + max(0, len(moved) - 12)
        if extra:
            print("    ... and %d more" % extra)
    print()
    print("total computed differences: %d" % len(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
