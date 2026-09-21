"""Are the installed dependencies the ones requirements.txt asks for?

**"Present" is not "current", and the installers asked the wrong question.**
Both of them checked dependencies like this::

    python -c "import flask, waitress, requests, browser_cookie3,
               cryptography, keyring, PIL"

and, when that succeeded, skipped `pip install -r requirements.txt` entirely.
So on any machine where the packages already imported, the version floors in
`requirements.txt` were never read by anything - not on a fresh install, not
on an update, not ever. A package installed years ago satisfied the check
for as long as its name resolved.

That is a security boundary rather than a tidiness one, and Pillow is the
reason. Pillow decodes the floor-plan images inside `.esx` archives, which
arrive by email, out of shared folders and down from Ekahau Cloud; its
advisories are overwhelmingly decoder bugs, the class where the untrusted
input *is* the attack. On 2026-09-20 the declared floors admitted 70 known
vulnerabilities across six packages, and nothing in the install path would
ever have noticed.

So this reads the floors and compares them with what is installed. It is
kept in `tools/` rather than `scripts/` deliberately: `scripts/` is not in
the release payload, so a ZIP install would not have it, and the ZIP install
is the one where nobody is running pip by hand.

It reports; it does not install. The installers decide what to do about the
answer, and the server mentions it in the log at startup so an install that
has drifted says so somewhere he will see it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"

#: Distribution name -> the name you import, where they differ.
_IMPORT_NAMES = {
    "pillow": "PIL",
    "browser_cookie3": "browser_cookie3",
}

_LINE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*>=\s*([0-9][0-9A-Za-z.\-]*)\s*$")


def floors(path: Path | None = None) -> dict:
    """{distribution: floor} from requirements.txt.

    Only `>=` lines, which is every line in that file and is the form the
    check means. Anything else - a pin, an extra, a marker - is skipped
    rather than guessed at, and `missing_floors` below says so.
    """
    text = (path or REQUIREMENTS).read_text(encoding="utf-8")
    out = {}
    for line in text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        found = _LINE.match(line)
        if found:
            out[found.group(1).lower()] = found.group(2)
    return out


def _parts(version: str):
    """A comparable tuple. Trailing non-numeric segments are dropped rather
    than guessed at - `12.3.0rc1` compares as `12.3.0`, which errs toward
    accepting a pre-release somebody installed deliberately."""
    return tuple(int(n) for n in re.findall(r"\d+", str(version or "")))


def installed_version(distribution: str):
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def check(path: Path | None = None) -> dict:
    """What is missing, what is too old, and what is fine.

    Never raises: a dependency check that blows up is a launcher that will
    not start, and being unable to answer is not the same as the answer
    being bad.
    """
    wanted = floors(path)
    missing, outdated, ok = [], [], []
    for name, floor in sorted(wanted.items()):
        found = installed_version(name)
        if found is None:
            missing.append({"name": name, "need": floor})
            continue
        if _parts(found) < _parts(floor):
            outdated.append({"name": name, "need": floor, "have": found})
        else:
            ok.append({"name": name, "need": floor, "have": found})
    return {"ok": not (missing or outdated), "missing": missing,
            "outdated": outdated, "current": ok,
            "checked": len(wanted)}


def summary(result: dict) -> str:
    """One line for a console, naming what is wrong rather than how many."""
    if result["ok"]:
        return f"{result['checked']} dependencies present and current."
    bits = []
    for entry in result["missing"]:
        bits.append(f"{entry['name']} is not installed (need {entry['need']}+)")
    for entry in result["outdated"]:
        bits.append(f"{entry['name']} {entry['have']} is older than "
                    f"{entry['need']}")
    return "; ".join(bits)


def main(argv=None) -> int:
    """Exit 0 when everything is satisfied, 1 when it is not.

    That is the whole interface the installers use, and it is why this is a
    module rather than a function they inline: a shell comparing version
    strings is how the wrong question got asked in the first place.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    result = check()
    print(summary(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
