"""What an image actually is, from its bytes — one copy of the magic numbers.

There were two copies before. ``folder_organizer`` sniffed a floor plan to name
an extract; ``esx_trimmer`` sniffed the same bytes, with a narrower list, to
decide whether the plan could be cropped. The two disagreed about four formats,
and a disagreement about what a file *is* is the exact shape of the fault that
shipped the ``.png`` naming bug — see ``tests/test_extract_floorplans.py``.

**Naming a format and cropping one are different questions and the two lists
are deliberately different.** Anything with a magic number can be named.
Cropping needs Pillow to both read *and* write the format, because a crop is a
re-encode and a re-encode that changes what the file is would be a worse
outcome than refusing.

**WBMP is the case that is out of reach from both ends**, and it is worth
saying why so it is not attempted again. Ekahau lists it as a supported map
format, so a project really can carry one. It has no magic number — its first
bytes are ``00 00``, which is not a signature — so ``images.json``'s
``imageFormat`` is the only thing that can name it. And Pillow ships no WBMP
codec in either direction, so even a correctly identified one cannot be opened.
It is named from its declaration and refused by name.
"""
from __future__ import annotations

# Recognised from the bytes. Lower case throughout; callers that need Pillow's
# own spelling upper-case it.
def sniff(head: bytes) -> str:
    """Best-effort format name from a file's first bytes, or ``""``.

    Ekahau stores floor plan images as ``image-<uuid>`` with no extension, so
    the bytes are the only honest source for what one is.
    """
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    # SVG is text, so it has no magic number in the usual sense. Ekahau stores
    # CAD imports this way, and they are why extraction shipped broken: bytes
    # nothing recognised used to fall back to .png, producing an XML document
    # named .png that no image viewer will open.
    lead = head.lstrip(b"\xef\xbb\xbf").lstrip()
    if lead[:5] == b"<?xml" or lead[:4] == b"<svg":
        return "svg"
    return ""


# Rasters a crop can round-trip: Pillow reads and writes all six, verified
# against its own registry rather than assumed - `tests/test_image_format.py`
# asserts it against the installed Pillow, so a build without a codec fails
# here rather than halfway through somebody's project.
CROPPABLE_RASTERS = frozenset({"png", "jpeg", "bmp", "gif", "tiff", "webp"})

# Saving needs a mode the format can hold. Cropping never changes a mode, so
# these conversions only ever fire on a source that was already unusual.
_SAVE_MODES = {
    "bmp": {"RGBA": "RGB", "LA": "L"},
    "webp": {"P": "RGBA", "L": "RGB", "LA": "RGBA", "1": "RGB"},
    "gif": {"RGBA": "P", "RGB": "P", "LA": "P"},
}


def save_mode(kind: str, mode: str) -> str | None:
    """The mode *kind* must be converted to before saving, or None to leave it."""
    return _SAVE_MODES.get(kind.lower(), {}).get(mode)
