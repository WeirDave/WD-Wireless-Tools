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
