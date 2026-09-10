"""Remember the keep-region a user drew, per project and per floor.

Drawing a rectangle on fourteen CAD sheets once is a fair ask. Doing it again
every time the project is re-opened is not, and a tool that forgets is a tool
people stop using half way through a set.

The boxes live in the user-data directory rather than inside the ``.esx``.
Writing our own member into someone's project archive is a liberty - Ekahau
owns that file format, the file syncs to their cloud, and a member it does not
recognise is at best ignored and at worst dropped on the next save. Keeping the
boxes beside the app costs nothing and cannot corrupt anything.

Keyed by the project's own id where it has one. A project with no id falls back
to its filename, which is weaker - renaming the file loses the boxes - but a
weak key beats no memory at all, and nothing is lost that cannot be redrawn.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

USER_DIR = Path.home() / ".wd_wireless_tools"
STORE = USER_DIR / "plantrim-boxes.json"

#: Keep the file from growing without bound as projects come and go.
MAX_PROJECTS = 200


def _load_all() -> dict:
    try:
        with STORE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_all(data: dict) -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    # Written through a temporary file in the same directory so a crash midway
    # leaves the previous boxes intact rather than a half-written file.
    fd, tmp = tempfile.mkstemp(dir=str(USER_DIR), prefix=".plantrim-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, STORE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _clean_boxes(boxes) -> dict:
    """Keep only what looks like ``{floorId: [x0, y0, x1, y1]}``."""
    out = {}
    if not isinstance(boxes, dict):
        return out
    for floor_id, box in boxes.items():
        if not isinstance(floor_id, str) or not isinstance(box, (list, tuple)):
            continue
        if len(box) != 4:
            continue
        try:
            out[floor_id] = [float(v) for v in box]
        except (TypeError, ValueError):
            continue
    return out


def load(project_id: str) -> dict:
    if not project_id:
        return {}
    return _clean_boxes(_load_all().get(project_id))


def save(project_id: str, boxes) -> dict:
    """Store *boxes* for *project_id*; an empty map forgets the project."""
    if not project_id:
        return {}
    data = _load_all()
    cleaned = _clean_boxes(boxes)
    if cleaned:
        data[project_id] = cleaned
    else:
        data.pop(project_id, None)

    if len(data) > MAX_PROJECTS:
        # Oldest-inserted first: dicts preserve insertion order, and the project
        # just written was re-inserted at the end.
        for key in list(data)[: len(data) - MAX_PROJECTS]:
            data.pop(key, None)

    _write_all(data)
    return cleaned


def forget(project_id: str) -> None:
    data = _load_all()
    if data.pop(project_id, None) is not None:
        _write_all(data)
