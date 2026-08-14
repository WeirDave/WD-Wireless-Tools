"""Create a sandbox folder full of fake .esx files for testing WD Cloud
Manager's file operations without touching real projects.

Usage:
    python scripts/make_test_projects.py              # default location
    python scripts/make_test_projects.py <path>       # custom location

Default location: C:/Users/<you>/WD-Cloud-Test  (on Windows)
                  ~/WD-Cloud-Test               (otherwise)

Each .esx is a minimal-but-valid ZIP file with a `project.json` inside so
the Cloud Manager scanner can extract the "author" metadata correctly.
That means:
- ~half the files show up as YOURS in the Owner filter
- ~half show up as SOMEONE ELSE'S
- names cover synced/mismatch/orphan/unassigned patterns
- sizes are realistic (100 KB – 5 MB) so the ledger looks lived-in

Re-running the script wipes the sandbox and re-creates it fresh, so you
can experiment freely — rename, move, delete, upload, undo — knowing
none of it touches your real Ekahau projects.
"""
from __future__ import annotations

import io
import json
import os
import random
import shutil
import sys
import zipfile
from pathlib import Path


YOU_EMAIL = "owner@example.com"
OTHER_EMAIL = "teammate@example.com"


SITES = [
    ("TEST1 - 100 Fake St, Anywhere, CA 90210",     YOU_EMAIL,   3),
    ("TEST2 - 200 Sample Ave, Somewhere, TX 75001", OTHER_EMAIL, 2),
    ("TEST3 - 300 Demo Blvd, Nowhere, NY 10001",    YOU_EMAIL,   4),
    ("TEST4 - 400 Mock Rd, Elsewhere, WA 98101",    OTHER_EMAIL, 2),
    ("TEST5 - Empty Site (no files)",               YOU_EMAIL,   0),
]


ROOT_FILES = [
    ("Unassigned Survey - Baseline.esx",   YOU_EMAIL),
    ("Orphan Predictive - Legacy.esx",     OTHER_EMAIL),
]


MISMATCH_FILES = [

    (0, "TEST1 - 100 Fake St, Anywhere - PD (old naming).esx", YOU_EMAIL),
]


def make_esx_bytes(project_name: str, author_email: str) -> bytes:
    """Build a minimal ZIP that survives the scanner's `project.json`
    author lookup. Also stuffs some random bytes so the file has a
    realistic size (100 KB – 5 MB) — otherwise every .esx would be tiny
    and the ledger wouldn't look real."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:

        z.writestr("version", "2.0")

        project = {
            "project": {"name": project_name, "id": "fake-" + str(random.randint(1000, 9999))},
            "history": {
                "createdBy": author_email,
                "modifiedBy": author_email,
                "createdAt": "2024-01-01T00:00:00Z",
                "modifiedAt": "2024-06-01T00:00:00Z",
            },
        }
        z.writestr("project.json", json.dumps(project, indent=2))


        target_bytes = random.randint(100 * 1024, 3 * 1024 * 1024)
        padding = os.urandom(target_bytes)
        z.writestr("_padding.bin", padding)
    return buf.getvalue()


def survey_phase(i: int) -> str:
    phases = ["Baseline", "Predictive", "Post-Install", "Validation", "AsBuilt"]
    return phases[i % len(phases)]


def make_site_files(site_name: str, site_code_prefix: str, n_files: int, author: str, out_dir: Path):
    """Populate a single site folder with N realistically-named .esx files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n_files):
        phase = survey_phase(i)
        fname = f"{site_code_prefix} - {phase}.esx"
        path = out_dir / fname
        path.write_bytes(make_esx_bytes(path.stem, author))


def default_location() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", str(Path.home())))
    else:
        base = Path.home()
    return base / "WD-Cloud-Test"


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default_location()
    if target.exists():
        print(f"Wiping existing sandbox at {target} ...")
        shutil.rmtree(target)
    target.mkdir(parents=True)

    total_files = 0


    for site_name, author, n_files in SITES:
        site_dir = target / site_name
        site_code = site_name.split(" - ", 1)[0]
        if n_files > 0:
            make_site_files(site_name, site_code, n_files, author, site_dir)
            total_files += n_files
        else:


            site_dir.mkdir(parents=True, exist_ok=True)


    for site_idx, fname, author in MISMATCH_FILES:
        site_name = SITES[site_idx][0]
        path = target / site_name / fname
        path.write_bytes(make_esx_bytes(path.stem, author))
        total_files += 1


    root_orphans_dir = target / "_Loose Files"
    root_orphans_dir.mkdir(parents=True, exist_ok=True)
    for fname, author in ROOT_FILES:
        path = root_orphans_dir / fname
        path.write_bytes(make_esx_bytes(path.stem, author))
        total_files += 1

    print(f"\nSandbox ready at:  {target}")
    print(f"  {len(SITES)} site folders  ·  {total_files} .esx files")
    print("\nNext steps in Cloud Manager:")
    print("  1. Menu -> Folder (or the Folder button in the top bar)")
    print(f"  2. Point at:  {target}")
    print("  3. Play — rename / move / delete / undo — nothing here is real.")
    print("\nRe-run this script any time to reset the sandbox.\n")


if __name__ == "__main__":
    main()
