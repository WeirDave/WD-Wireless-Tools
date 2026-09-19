"""Read every published release note and report what does not belong there.

Release notes are as public as the tree, and nothing was reading them. The
rule-zero scanners read tracked files and commit objects; a release body lives
on GitHub, so it has never been covered. This closes that, and checks the
house style at the same time.

Run it after publishing, or before a sweep of `gh release edit`:

    python scripts/audit_release_notes.py            # all releases
    python scripts/audit_release_notes.py --limit 15

**It prints categories and counts, never values.** A report that quotes the
thing it is complaining about republishes it, which is the trap that put a
scrubbed site code back into the message of the commit that scrubbed it.

Exit status is 1 if anything is found, so it can gate a script.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from test_no_real_world_data import detect_findings  # noqa: E402

#: The automated attribution trailer. It carries an address at a real domain,
#: which the rule-zero detector correctly notices and which is not personal
#: data - it is the same line on every commit.
TRAILER = re.compile(r"^\s*Co-authored-by:.*$", re.M | re.I)

#: Standard and format names shaped like a site code are cleared by the
#: detector itself - see ALLOWED_TECHNICAL_TERMS in
#: tests/test_no_real_world_data.py, which is the one place to add one.
#: A second copy here would be a second opinion about the same question.

#: Style. Each of these is a way a note stops being about the software.
STYLE = {
    "first person": re.compile(
        r"\b(I|I'm|I've|I'd|we|we're|we've|my|our|us)\b"),
    "addresses the reader": re.compile(r"\b(you|your|you're|yours)\b", re.I),
    "names the reporter": re.compile(r"\b(he|his|him|the user said|he said)\b"),
    "narrates how it was found": re.compile(
        r"\b(screenshot|photograph(?:ed)?|measured at his|as discussed|"
        r"in the thread|this session|the session that|was reported|"
        r"he reported|you reported|the report came)\b", re.I),
    "self-assessment or apology": re.compile(
        r"\b(my (?:mistake|fault|regression|defect)|one thing I got wrong|"
        r"what I got wrong|sorry|apolog|the valuable part|I introduced)\b",
        re.I),
    #: Quoted *speech*, not a quoted error message. Reproducing the exact
    #: wording of an error belongs in a note - it is what someone searches
    #: for - so a long quotation is only flagged when it talks the way a
    #: person does, in the first or second person.
    "quotes someone": re.compile(
        r'"[^"\n]{0,200}\b(I|I\'m|you|your|we|my|me|don\'t|doesn\'t|'
        r'can\'t|didn\'t|isn\'t)\b[^"\n]{0,200}"'),
}

#: Context about the person rather than the product.
PRIVACY = {
    "the reporter's environment": re.compile(
        r"\b(work machine|work network|corporate network|his employer|"
        r"his account|his machine|his install|his archive|his workflow)\b",
        re.I),
    "the size of the reporter's data": re.compile(
        r"\bhis\b[^.\n]{0,30}\b\d+\b|\b\d+\b[^.\n]{0,20}\bof his\b", re.I),
}


def bodies(limit: int | None) -> dict[str, str]:
    args = ["gh", "release", "list", "--json", "tagName"]
    if limit:
        args += ["--limit", str(limit)]
    else:
        args += ["--limit", "1000"]
    tags = [r["tagName"] for r in json.loads(
        subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", check=True).stdout)]
    out = {}
    for tag in tags:
        r = subprocess.run(["gh", "release", "view", tag, "--json", "body",
                            "--jq", ".body"],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            out[tag] = r.stdout
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    notes = bodies(args.limit)
    print(f"release notes read: {len(notes)}\n")

    dirty = Counter()
    rows = []
    for tag, body in notes.items():
        stripped = TRAILER.sub("", body)
        row = {}
        for cat, vals in detect_findings(stripped).items():
            row["RULE ZERO: " + cat] = len(vals)
        for name, rx in {**PRIVACY, **STYLE}.items():
            n = len(rx.findall(stripped))
            if n:
                row[name] = n
        if row:
            rows.append((tag, row))
            for k, v in row.items():
                dirty[k] += v

    for tag, row in rows:
        print(f"  {tag:12s} " + ", ".join(f"{n}x {c}" for c, n in row.items()))

    print(f"\n  clean: {len(notes) - len(rows)} of {len(notes)}")
    if dirty:
        print("  totals:")
        for cat, n in sorted(dirty.items(), key=lambda kv: -kv[1]):
            print(f"    {n:4d}  {cat}")
    return 1 if rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
