"""Attenuation-area presets: the ones the app ships, and the ones he keeps.

Quick Walls' Attenuation Areas tab offers presets that go into a project's own
attenuation area list. Two come with the app (``web/assets/attenuation-area-
presets.json``, read-only, replaced by every update). Anything he keeps from
a project lives in the user directory instead, so an update never touches it and
it follows him from project to project.

**Never in a wall template.** Wall templates carry wall types and nothing else;
an attenuation area is a different kind of object in a different member of the
project, and mixing the two in one file would make "apply this template" mean
two things. Presets have their own file.

Presets are written in the units they are measured in - feet and dB per foot -
and converted to Ekahau's metres by the page when they go into a project.

Every value is checked here as well as in the page: this file is read back on
the next launch, and a hand-edited or half-written one must cost the bad entry,
not the tab.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from pathlib import Path

from tools.user_dir import user_dir

USER_DIR = user_dir()
STORE = USER_DIR / "attenuation-area-presets.json"
SHIPPED = (Path(__file__).resolve().parent.parent
           / "web" / "assets" / "attenuation-area-presets.json")

BANDS = ("TWO", "FIVE", "SIX")
MAX_PRESETS = 100
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _number(value, what, allow_none=False):
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value < 0:
        raise ValueError(what + " must be a number, 0 or more.")
    return float(value)


def clean(preset) -> dict:
    """The preset as it will be stored, or ``ValueError`` saying what is wrong."""
    if not isinstance(preset, dict):
        raise ValueError("A preset must be an object.")
    name = " ".join(str(preset.get("name") or "").split())
    if not name:
        raise ValueError("Give the preset a name.")
    if len(name) > 80:
        raise ValueError("The preset name is longer than 80 characters.")
    color = str(preset.get("color") or "")
    if not _COLOR.match(color):
        raise ValueError("The colour must look like #RRGGBB.")
    lower = _number(preset.get("lowerEdgeFt", 0), "The lower edge")
    upper = _number(preset.get("upperEdgeFt"), "The upper edge", allow_none=True)
    if upper is not None and upper <= lower:
        raise ValueError("The upper edge must be above the lower edge, or empty.")
    raw = preset.get("attenuationDbPerFt")
    if not isinstance(raw, dict):
        raise ValueError("The loss per foot is missing.")
    loss = {b: _number(raw.get(b), "The loss at " + b) for b in BANDS}
    return {"name": name, "color": color.upper(), "lowerEdgeFt": lower,
            "upperEdgeFt": upper, "attenuationDbPerFt": loss}


def _read(path: Path) -> list:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    items = data.get("presets") if isinstance(data, dict) else None
    out = []
    for item in items if isinstance(items, list) else []:
        try:
            out.append(clean(item))
        except ValueError:
            continue
    return out


def shipped() -> list:
    return [dict(p, builtin=True) for p in _read(SHIPPED)]


def kept() -> list:
    return [dict(p, builtin=False) for p in _read(STORE)]


def _key(name) -> str:
    return " ".join(str(name or "").split()).casefold()


def all_presets() -> list:
    """The built-ins, then his own. A kept preset that shares a name with a
    built-in is not listed: the built-in is the one that applies."""
    base = shipped()
    taken = {_key(p["name"]) for p in base}
    return base + [p for p in kept() if _key(p["name"]) not in taken]


def _write(items: list) -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    # Through a temp file in the same directory, then renamed over the top, so a
    # crash midway leaves the previous presets intact.
    fd, tmp = tempfile.mkstemp(dir=str(USER_DIR), prefix=".area-presets-",
                               suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"presets": items}, f, indent=1)
        os.replace(tmp, STORE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(preset) -> list:
    """Keep this preset (replacing one of his own with the same name)."""
    item = clean(preset)
    if _key(item["name"]) in {_key(p["name"]) for p in shipped()}:
        raise ValueError("“%s” is a built-in preset, so it cannot be "
                         "replaced. Keep it under another name." % item["name"])
    mine = [{k: v for k, v in p.items() if k != "builtin"} for p in kept()]
    at = next((i for i, p in enumerate(mine)
               if _key(p["name"]) == _key(item["name"])), None)
    if at is None:
        if len(mine) >= MAX_PRESETS:
            raise ValueError("There are already %d kept presets; remove one "
                             "first." % MAX_PRESETS)
        mine.append(item)
    else:
        mine[at] = item
    _write(mine)
    return all_presets()


def delete(name) -> list:
    """Remove one of his own presets. A built-in cannot be removed."""
    if _key(name) in {_key(p["name"]) for p in shipped()}:
        raise ValueError("“%s” is a built-in preset and cannot be "
                         "removed." % name)
    mine = [{k: v for k, v in p.items() if k != "builtin"} for p in kept()]
    left = [p for p in mine if _key(p["name"]) != _key(name)]
    if len(left) == len(mine):
        raise ValueError("There is no kept preset named “%s”." % name)
    _write(left)
    return all_presets()
