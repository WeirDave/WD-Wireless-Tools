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
