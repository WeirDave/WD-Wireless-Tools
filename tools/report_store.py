"""
Report assets that belong to the install, not to a browser.

The cover image is install configuration: the same logo goes on every report
this machine produces.  Keeping it in the browser made it per-browser and
per-profile, so clearing site data or switching from Chrome to Edge silently
lost it.  It lives on disk instead, in the same user-data directory as the wall
templates -- ``~/.wd_wireless_tools`` -- which sits outside the install tree and
is therefore untouched by either update path.  See ``tools/updater.py``:
``CONFIG.user_data_dir`` is never a payload target, so neither ``git pull`` nor
a ZIP extraction can reach these files.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

from tools.settings import SETTINGS_DIR

# Deliberately a sibling of settings.json and templates/, all under the one
# directory the updater is required to leave alone.
REPORT_DIR = SETTINGS_DIR / "report"
COVER_STEM = "cover"

MAX_COVER_BYTES = 25 * 1024 * 1024

# Extension is decided here from the sniffed bytes rather than trusted from the
# upload, so a mislabelled or hostile filename cannot pick where this lands.
_SIGNATURES = (
    (".png", b"\x89PNG\r\n\x1a\n", "image/png"),
    (".jpg", b"\xff\xd8\xff", "image/jpeg"),
    (".gif", b"GIF87a", "image/gif"),
    (".gif", b"GIF89a", "image/gif"),
)

ACCEPTED_LABEL = "PNG, JPEG, WebP, GIF or SVG"


def _sniff(data: bytes):
    """Return (extension, content type) for supported image bytes, else None."""
    for ext, magic, ctype in _SIGNATURES:
        if data.startswith(magic):
            return ext, ctype
    # RIFF....WEBP
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    head = data[:512].lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        if b"<svg" in data[:4096].lower():
            return ".svg", "image/svg+xml"
    return None


def _existing() -> Path | None:
    if not REPORT_DIR.is_dir():
        return None
    for p in sorted(REPORT_DIR.glob(COVER_STEM + ".*")):
        if p.is_file():
            return p
    return None


def cover_info() -> dict:
    """Describe the stored cover image, if there is one."""
    p = _existing()
    if not p:
        return {"ok": True, "exists": False, "folder": str(REPORT_DIR)}
    st = p.stat()
    return {
        "ok": True,
        "exists": True,
        "folder": str(REPORT_DIR),
        "path": str(p),
        "name": p.name,
        "bytes": st.st_size,
        # Lets the page bust its own cache without guessing at headers.
        "version": int(st.st_mtime),
    }


def cover_path() -> Path | None:
    return _existing()


def save_cover(data: bytes, original_name: str = "") -> dict:
    """Validate and store *data* as the cover image, replacing any previous one."""
    if not data:
        return {"ok": False, "error": "That file was empty."}
    if len(data) > MAX_COVER_BYTES:
        mb = len(data) / (1024 * 1024)
        return {"ok": False,
                "error": f"That image is {mb:.1f} MB. Pick one under "
                         f"{MAX_COVER_BYTES // (1024 * 1024)} MB."}
    sniffed = _sniff(data)
    if not sniffed:
        shown = os.path.basename(original_name or "that file")
        return {"ok": False,
                "error": f"{shown} is not an image this can use. Use {ACCEPTED_LABEL}."}
    ext, ctype = sniffed

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    dest = REPORT_DIR / (COVER_STEM + ext)

    # Written to a temporary file in the same directory and moved into place, so
    # a failure part-way through cannot leave a half-written cover behind.
    fd, tmp = tempfile.mkstemp(dir=str(REPORT_DIR), prefix=".cover-", suffix=ext)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return {"ok": False, "error": f"Could not save the image: {e}"}

    # A format change means the old file has a different name; drop it.
    for other in REPORT_DIR.glob(COVER_STEM + ".*"):
        if other.is_file() and other != dest:
            try:
                other.unlink()
            except OSError:
                pass

    info = cover_info()
    info["contentType"] = ctype
    return info


def delete_cover() -> dict:
    removed = False
    if REPORT_DIR.is_dir():
        for p in REPORT_DIR.glob(COVER_STEM + ".*"):
            if p.is_file():
                try:
                    p.unlink()
                    removed = True
                except OSError as e:
                    return {"ok": False, "error": f"Could not remove the image: {e}"}
    return {"ok": True, "removed": removed, "exists": False}


# ── Finding a dropped project on disk ──────────────────────────────────────
# The folder the .esx sits in is what names the saved report, and a browser
# file input cannot say what it is: a drop hands the page a name and some bytes
# and nothing else.  The native picker knows, which is why "Open another..."
# has always produced a better file name than the drop zone on the front page
# -- and the drop zone is the front door, so most reports were named without
# the site in them.
#
# The bytes are already on the machine, so the folder is answerable here: look
# the file up under the Local project folder and report the folder it was found
# in.  Nothing is opened and nothing is written; only the folder *name* travels
# back, which is the one piece the file name needs.
#
# It answers only when it is certain.  Two projects of the same name in two
# folders is a real shape -- the same survey kept per building -- so a match is
# confirmed by byte size as well as by name, and an ambiguous answer is refused
# rather than guessed at.  A wrong site on an installer's drawing is worse than
# no site.

_LOOKUP_SKIP_DIRS = {"backups", "backup", "output", "outputs", "archive",
                     "archives", "node_modules", "__pycache__", ".git"}

# A survey tree is client / site / project deep in practice.  The cap is what
# keeps this a lookup rather than a drive scan: a mis-set Local project folder
# pointing at C:\ must come back with an answer, not hold the request open.
MAX_LOOKUP_DEPTH = 4
MAX_LOOKUP_DIRS = 4000


def _lookup_root() -> str:
    from tools import settings as suite_settings
    try:
        cfg = suite_settings.load_settings().get("global") or {}
    except Exception:
        return ""
    return (cfg.get("output_dir") or "").strip()


def locate_project_folder(file_name: str, size=None) -> dict:
    """Name the folder a dropped .esx came from, when that can be known.

    Returns ``{"ok": True, "folder": "<name>"}`` only for a single unambiguous
    match.  Every other outcome carries a ``reason`` the page can put into
    words, because "the site is missing from the file name" with no explanation
    is exactly the state this is fixing.
    """
    name = (file_name or "").strip()
    if not name or not name.lower().endswith(".esx"):
        return {"ok": False, "reason": "not_a_project"}
    root_raw = _lookup_root()
    if not root_raw:
        return {"ok": False, "reason": "no_root"}
    try:
        root = Path(root_raw).expanduser()
        if not root.is_dir():
            return {"ok": False, "reason": "no_root"}
    except (OSError, ValueError):
        return {"ok": False, "reason": "no_root"}

    try:
        want_size = int(size) if size is not None else None
    except (TypeError, ValueError):
        want_size = None

    wanted = name.lower()
    hits = []
    seen_dirs = 0
    stack = [(root, 0)]
    while stack:
        here, depth = stack.pop()
        seen_dirs += 1
        if seen_dirs > MAX_LOOKUP_DIRS:
            return {"ok": False, "reason": "too_big"}
        try:
            entries = list(os.scandir(here))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 > MAX_LOOKUP_DEPTH:
                        continue
                    if entry.name.startswith(".") or entry.name.lower() in _LOOKUP_SKIP_DIRS:
                        continue
                    stack.append((Path(entry.path), depth + 1))
                elif entry.name.lower() == wanted:
                    if want_size is not None and entry.stat().st_size != want_size:
                        continue
                    hits.append(Path(entry.path))
            except OSError:
                continue

    folders = {p.parent.name for p in hits}
    if not folders:
        return {"ok": False, "reason": "not_found"}
    if len(folders) > 1:
        return {"ok": False, "reason": "ambiguous", "count": len(folders)}
    return {"ok": True, "folder": folders.pop()}


# ── Column grid calibration ────────────────────────────────────────────────
# Two labelled intersections per floor, from which a grid reference for any
# point on that floor follows. See the "Column grid references" block in
# report.js for the arithmetic and for why the grid is declared rather than
# read off the drawing.
#
# **It does not go in the .esx, and that is not a preference.** Ekahau has no
# member for it, so a round trip through the cloud - or through Ekahau AI Pro
# itself - would drop it silently, and the reference would stop appearing with
# nothing to say why. It lives here, beside the cover image, in the one
# directory both update paths are required to leave alone.
#
# Keyed by the project's own id and the floor plan's own id rather than by
# their names, because both get renamed and neither rename should cost the
# calibration.

GRIDS_PATH = REPORT_DIR / "grids.json"

# A calibration is six numbers and an axis. There is no reason for this file to
# grow, and a cap means a corrupted or hand-edited one fails as a sentence
# rather than as a memory error.
MAX_GRIDS_BYTES = 2 * 1024 * 1024


def _blank_grids() -> dict:
    return {"version": 1, "projects": {}}


def load_grids() -> dict:
    """Every saved calibration, or an empty structure.

    A missing, unreadable or malformed file reads as "nothing is calibrated",
    which is the same state as a fresh install: the Grid column shows a dash
    and the report is otherwise unchanged. Losing a calibration is an
    inconvenience; refusing to open the tool over it would not be.
    """
    try:
        if not GRIDS_PATH.is_file():
            return _blank_grids()
        if GRIDS_PATH.stat().st_size > MAX_GRIDS_BYTES:
            return _blank_grids()
        data = json.loads(GRIDS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _blank_grids()
    if not isinstance(data, dict) or not isinstance(data.get("projects"), dict):
        return _blank_grids()
    return data


def _write_json(path: Path, data: dict) -> None:
    """Build alongside and rename over the top, so the file is either entirely
    the old one or entirely the new one and never half of either."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_grids(data: dict) -> None:
    _write_json(GRIDS_PATH, data)


def _clean_point(raw) -> dict | None:
    """One intersection: where it is, and what it is called.

    The payload arrives from the browser, so every field is re-derived here
    rather than trusted. A calibration that is nonsense produces a wrong bay
    number on an installer's drawing, and that is the one failure this feature
    is written to avoid.
    """
    if not isinstance(raw, dict):
        return None
    try:
        x = float(raw["x"])
        y = float(raw["y"])
        col = int(raw["col"])
        row = int(raw["row"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(map(math.isfinite, (x, y))):
        return None
    if col < 0 or row < 1:
        return None
    return {"x": x, "y": y, "col": col, "row": row}


def save_grid(project_id: str, floor_id: str, payload) -> dict:
    project_id = (project_id or "").strip()
    floor_id = (floor_id or "").strip()
    if not project_id or not floor_id:
        return {"ok": False, "error": "That floor could not be identified."}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "No calibration was received."}

    a = _clean_point(payload.get("a"))
    b = _clean_point(payload.get("b"))
    if not a or not b:
        return {"ok": False, "error": "Two labelled intersections are needed."}
    if a["col"] == b["col"] or a["row"] == b["row"]:
        return {"ok": False,
                "error": "The two intersections must differ in both directions."}

    axis = "y" if payload.get("lettersAxis") == "y" else "x"

    data = load_grids()
    data.setdefault("projects", {}).setdefault(project_id, {})[floor_id] = {
        "a": a, "b": b, "lettersAxis": axis,
    }
    _write_grids(data)
    return {"ok": True, "floors": data["projects"][project_id]}


def clear_grid(project_id: str, floor_id: str) -> dict:
    """Turn the reference off for one floor.

    Which is the documented answer for a grid this cannot model - an
    interrupted bay, a skewed or rotated grid, a building carrying two grids of
    its own. Printing something plausible instead is the failure.
    """
    # Stripped the way save_grid stores them, or removing the last floor left
    # an empty project behind under the stripped key.
    project_id = (project_id or "").strip()
    floor_id = (floor_id or "").strip()
    data = load_grids()
    floors = (data.get("projects") or {}).get(project_id)
    if not floors or floor_id not in floors:
        return {"ok": True, "floors": floors or {}}
    del floors[floor_id]
    if not floors:
        data["projects"].pop(project_id, None)
    _write_grids(data)
    return {"ok": True, "floors": floors}


def grids_for_project(project_id: str) -> dict:
    return {"ok": True,
            "floors": (load_grids().get("projects") or {}).get(
                (project_id or "").strip(), {})}


# ── Section grid memory ─────────────────────────────────────────────────────
#
# The Report's section grid - columns by rows, the crop on each floor and the
# combined cells - used to live for one session. Switching to another report
# type threw it away, and so did opening the next file, so the same site was
# set up again for every report.
#
# Same reasoning as the column grid above, and the same place: **not in the
# .esx**, which has no member for it, and **not a file in the project folder**,
# which sits in a synced tree that Cloud Manager scans and compares. Keyed by
# the project's own id and each floor plan's own id, so renaming either costs
# nothing.
#
# Two layers. A project's own entry is what that project was last set to. "last"
# is the most recent size set anywhere, which a project with no entry of its
# own starts from - crops and combined cells are drawn on one project's plans
# and are never carried to another.
#
# An entry with no size says "Auto" on purpose. Without it, choosing Auto on a
# project would be forgotten at once, because a project with no entry falls
# back to "last".

SECTIONS_PATH = REPORT_DIR / "section_grids.json"
MAX_SECTIONS_BYTES = 2 * 1024 * 1024

# The dialog's own limit (adjustGridCols / adjustGridRows clamp to 1..20).
MAX_SECTION_LINES = 20
MAX_SECTION_PROJECTS = 500
MAX_SECTION_FLOORS = 200


def _blank_sections() -> dict:
    return {"version": 1, "last": None, "projects": {}}


def load_sections() -> dict:
    """Everything remembered, or an empty structure.

    Unreadable reads as "nothing remembered", the state of a fresh install:
    the grid is Auto and the person sets it up as they did before. Losing the
    memory is an inconvenience; refusing to open the Report over it is not.
    """
    try:
        if not SECTIONS_PATH.is_file():
            return _blank_sections()
        if SECTIONS_PATH.stat().st_size > MAX_SECTIONS_BYTES:
            return _blank_sections()
        data = json.loads(SECTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _blank_sections()
    if not isinstance(data, dict) or not isinstance(data.get("projects"), dict):
        return _blank_sections()
    data.setdefault("last", None)
    return data


def _clean_size(cols, rows) -> dict | None:
    if isinstance(cols, bool) or isinstance(rows, bool):
        return None
    try:
        c, r = int(cols), int(rows)
    except (TypeError, ValueError):
        return None
    if not (1 <= c <= MAX_SECTION_LINES and 1 <= r <= MAX_SECTION_LINES):
        return None
    return {"cols": c, "rows": r}


def _clean_crop(raw) -> dict | None:
    """A crop is a rectangle inside the plan, as fractions of its width and
    height. Anything else would print a sheet of nothing."""
    if not isinstance(raw, dict):
        return None
    try:
        x, y, w, h = (float(raw[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(map(math.isfinite, (x, y, w, h))):
        return None
    eps = 1e-6
    if x < -eps or y < -eps or w <= 0 or h <= 0:
        return None
    if x + w > 1 + eps or y + h > 1 + eps:
        return None
    return {"x": max(0.0, x), "y": max(0.0, y), "w": w, "h": h}


def _clean_merge(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    size = _clean_size(raw.get("cols"), raw.get("rows"))
    groups = raw.get("groups")
    if not size or not isinstance(groups, list):
        return None
    out = []
    for g in groups[: MAX_SECTION_LINES * MAX_SECTION_LINES]:
        if not isinstance(g, dict):
            continue
        try:
            c0, c1, r0, r1 = (int(g[k]) for k in ("c0", "c1", "r0", "r1"))
        except (KeyError, TypeError, ValueError):
            continue
        if min(c0, c1, r0, r1) < 0 or max(c0, c1) >= size["cols"] \
                or max(r0, r1) >= size["rows"]:
            continue
        out.append({"c0": c0, "r0": r0, "c1": c1, "r1": r1})
    if not out:
        return None
    return {"cols": size["cols"], "rows": size["rows"], "groups": out}


def _clean_floor_map(raw, clean) -> dict:
    if not isinstance(raw, dict):
        return {}
    out = {}
    for floor_id, value in list(raw.items())[:MAX_SECTION_FLOORS]:
        fid = str(floor_id).strip()
        item = clean(value)
        if fid and item:
            out[fid] = item
    return out


def section_grid_for_project(project_id: str) -> dict:
    data = load_sections()
    return {"ok": True,
            "project": (data.get("projects") or {}).get(
                (project_id or "").strip()),
            "last": data.get("last")}


def save_section_grid(project_id: str, payload) -> dict:
    """Remember what this project's grid was left at.

    Every field is re-derived rather than trusted: the payload comes from the
    browser, and a size or a crop that is nonsense decides how many sheets a
    report prints.
    """
    project_id = (project_id or "").strip()
    if not project_id:
        return {"ok": False, "error": "That project could not be identified."}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "No grid was received."}

    entry = {}
    size = _clean_size(payload.get("segCols"), payload.get("segRows"))
    if size:
        entry.update(size)
    crops = _clean_floor_map(payload.get("cropBoxes"), _clean_crop)
    if crops:
        entry["cropBoxes"] = crops
    merges = _clean_floor_map(payload.get("segMerges"), _clean_merge)
    if merges:
        entry["segMerges"] = merges

    data = load_sections()
    projects = data.setdefault("projects", {})
    if size:
        data["last"] = size
    if not entry and data.get("last"):
        entry = {"auto": True}
    projects.pop(project_id, None)
    if entry:
        # Re-inserted last, so the oldest is what the cap drops.
        projects[project_id] = entry
        while len(projects) > MAX_SECTION_PROJECTS:
            projects.pop(next(iter(projects)))
    _write_json(SECTIONS_PATH, data)
    return {"ok": True, "project": entry or None, "last": data.get("last")}
