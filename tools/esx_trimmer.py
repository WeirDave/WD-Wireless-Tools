"""
WD Wireless Tools — ESX Trimmer

Ekahau's CAD import routinely lands a building drawing on a canvas many times
its size — 10000x7500 with the plan occupying 15-20% of it is typical.  The
whole canvas ships inside the .esx, so the file is mostly empty pixels.

This module crops each floor plan image to its content and rebases every piece
of coordinate metadata by the same offset, so the project still opens correctly
in Ekahau.

Coordinate space
----------------
Every coordinate in an .esx — access points, wall points, area polygons,
reference-point projections, survey route points — lives in *full image pixel
space*, the same space as the floor plan's own ``cropMinX/Y/MaxX/Y`` rectangle.
That was verified against 109 real projects: 2832 of 2832 coordinates fell
inside their floor's crop rect.  Because they share one space, a physical crop
is a single translation applied uniformly to all of them, including the crop
rect itself.  There is no double-application hazard.

What it refuses
---------------
The tool would rather do nothing than corrupt a project, so it refuses per
floor and explains why:

  * SVG floor plans — there is no pixel grid to crop.
  * Floors carrying a ``bitmapImageId`` — a second image at a different
    resolution.  Every such floor observed in the survey was SVG-backed, so
    this costs nothing today; supporting it means cropping both images at an
    exact resolution ratio, which has never been testable against real data.
  * Populated ``gpsReferencePoints`` — geo-anchored plans, shape never observed
    (0 of 173 floors), so the correct offset behaviour is unknown.
  * Content that already fills most of the canvas — nothing worth reclaiming.
  * Empty floor plans — cropping to nothing is worse than leaving them alone.

``wallSegments.json``, ``wallTypes.json`` and ``metersPerUnit`` are never
touched; ``metersPerUnit`` is asserted byte-identical after the rewrite and
aborts the whole file if it ever moves, because scale drift silently ruins
every attenuation calculation downstream.

Pillow is imported lazily.  It is not in requirements.txt on purpose: adding a
hard dependency to every fresh install to serve one optional tool is a bad
trade on a locked-down machine.
"""
from __future__ import annotations

import io
import json
import shutil
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Files whose entries carry `location.coord` and a `location.floorPlanId`.
POINT_FILES = {
    "accessPoints.json": "accessPoints",
    "wallPoints.json": "wallPoints",
    "interferers.json": "interferers",
    "pictureNotes.json": "pictureNotes",
}

# Files whose entries carry a top-level `floorPlanId` and an `area` polygon.
AREA_FILES = {
    "areas.json": "areas",
    "attenuationAreas.json": "attenuationAreas",
    "exclusionAreas.json": "exclusionAreas",
}

# Never rewritten, listed so the intent is explicit rather than implied by
# absence.  AP position lives only in accessPoints.json; the radio files
# reference an AP by id and carry no geometry of their own.
NEVER_TOUCH = (
    "wallSegments.json",
    "wallTypes.json",
    "simulatedRadios.json",
    "measuredRadios.json",
    "accessPointMeasurements.json",
    "notes.json",
    "requirements.json",
    "buildingFloors.json",
    "surveyLookups.json",
)

DEFAULT_MARGIN = 10
# Above this fraction of the canvas there is nothing worth reclaiming.
FILL_SKIP_RATIO = 0.90
# Column/row is "content" once it holds this share of the darkest column's ink.
DENSITY_CUTOFF = 0.001
INK_THRESHOLD = 245


class TrimError(Exception):
    """Raised when a file must not be trimmed at all."""


@dataclass
class FloorResult:
    floor_id: str
    name: str
    action: str               # "trimmed" | "skipped" | "refused"
    reason: str = ""
    old_size: tuple | None = None
    new_size: tuple | None = None
    offset: tuple | None = None

    @property
    def trimmed(self) -> bool:
        return self.action == "trimmed"


@dataclass
class TrimReport:
    source: Path
    floors: list = field(default_factory=list)
    bytes_before: int = 0
    bytes_after: int = 0
    written: bool = False

    @property
    def trimmed_count(self) -> int:
        return sum(1 for f in self.floors if f.trimmed)

    @property
    def saved_bytes(self) -> int:
        return max(0, self.bytes_before - self.bytes_after)

    @property
    def grew(self) -> bool:
        return bool(self.written and self.bytes_after > self.bytes_before)

    def summary(self) -> str:
        parts = [
            f"{self.source.name}: {self.trimmed_count} of {len(self.floors)} floor plans trimmed"
        ]
        if self.bytes_before and self.bytes_after:
            delta = self.bytes_after - self.bytes_before
            pct = abs(delta) / self.bytes_before * 100
            word = "larger" if delta > 0 else "smaller"
            parts.append(f"{_mb(self.bytes_before)} -> {_mb(self.bytes_after)} ({pct:.0f}% {word})")
        return ", ".join(parts)


def _mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


def _require_pillow():
    try:
        from PIL import Image  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise TrimError(
            "Trimming needs the Pillow imaging library, which is not installed.\n"
            "Install it with:  python -m pip install Pillow"
        ) from exc
    from PIL import Image
    return Image


def image_kind(blob: bytes) -> str:
    """Identify an image from its magic bytes rather than trusting metadata."""
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if blob[:2] == b"\xff\xd8":
        return "JPEG"
    head = blob[:512].lstrip()
    if head[:5] == b"<?xml" or head[:4] == b"<svg":
        return "SVG"
    return "UNKNOWN"


def png_size(blob: bytes) -> tuple | None:
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", blob[16:24])
    return w, h


def content_bounds(image, margin: int = DEFAULT_MARGIN):
    """Bounding box of the drawn content, by row/column ink density.

    A strict min/max over dark pixels is defeated by JPEG ringing and stray
    speckle — one dark pixel in a corner and the box is the whole canvas.
    Summing ink per row and per column and cutting at a small percentile
    ignores that noise while still catching genuine thin linework.
    """
    grey = image.convert("L")
    w, h = grey.size
    # Subsample very large canvases; a 10000x7500 plan does not need every
    # pixel inspected to find its edges.
    step = max(1, min(w, h) // 1200)
    px = grey.load()
    cols = [0] * w
    rows = [0] * h
    for y in range(0, h, step):
        for x in range(0, w, step):
            if px[x, y] < INK_THRESHOLD:
                cols[x] += 1
                rows[y] += 1

    def span(counts):
        total = sum(counts)
        if not total:
            return None
        cutoff = max(1, int(DENSITY_CUTOFF * total))
        hits = [i for i, c in enumerate(counts) if c >= cutoff]
        return (hits[0], hits[-1]) if hits else None

    sx, sy = span(cols), span(rows)
    if not sx or not sy:
        return None
    x0 = max(0, sx[0] - margin)
    y0 = max(0, sy[0] - margin)
    x1 = min(w, sx[1] + 1 + margin)
    y1 = min(h, sy[1] + 1 + margin)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _floor_coord_bbox(members: dict, floor_id: str):
    """Bounding box of every coordinate that belongs to one floor.

    The crop must never land inside this box or metadata would end up off the
    image, so it is unioned into the final bounds.
    """
    xs, ys = [], []

    def take(c):
        if isinstance(c, dict) and isinstance(c.get("x"), (int, float)):
            xs.append(float(c["x"]))
            ys.append(float(c["y"]))

    for name, key in POINT_FILES.items():
        for item in _entries(members, name, key):
            loc = item.get("location") or {}
            if loc.get("floorPlanId") == floor_id:
                take(loc.get("coord"))

    for name, key in AREA_FILES.items():
        for item in _entries(members, name, key):
            if item.get("floorPlanId") == floor_id:
                for c in item.get("area") or []:
                    take(c)

    for item in _entries(members, "referencePoints.json", "referencePoints"):
        # floorPlanId is per projection: one physical point can be projected
        # onto several floors, so filter inside the list, not outside it.
        for proj in item.get("projections") or []:
            if proj.get("floorPlanId") == floor_id:
                take(proj.get("coord"))

    for name in _survey_members(members):
        for survey in _entries(members, name, "surveys"):
            if survey.get("floorPlanId") != floor_id:
                continue
            for leg in survey.get("routePoints") or []:
                # routePoints is a list of lists, and the coordinate sits
                # directly under `location` rather than `location.coord`.
                for rp in (leg if isinstance(leg, list) else [leg]):
                    if isinstance(rp, dict):
                        take(rp.get("location"))

    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _entries(members: dict, name: str, key: str):
    doc = members.get(name)
    if not isinstance(doc, dict):
        return []
    items = doc.get(key)
    return items if isinstance(items, list) else []


def _survey_members(members: dict):
    return [n for n in members if n.startswith("survey-") and n.endswith(".json")]


def _shift_coord(c, dx: float, dy: float) -> bool:
    if isinstance(c, dict) and isinstance(c.get("x"), (int, float)):
        c["x"] = float(c["x"]) - dx
        c["y"] = float(c["y"]) - dy
        return True
    return False


def offset_metadata(members: dict, floor_id: str, dx: float, dy: float) -> dict:
    """Subtract (dx, dy) from every coordinate belonging to *floor_id*."""
    counts = {}

    def bump(k, n=1):
        if n:
            counts[k] = counts.get(k, 0) + n

    for name, key in POINT_FILES.items():
        n = 0
        for item in _entries(members, name, key):
            loc = item.get("location") or {}
            if loc.get("floorPlanId") == floor_id:
                n += _shift_coord(loc.get("coord"), dx, dy)
        bump(name, n)

    for name, key in AREA_FILES.items():
        n = 0
        for item in _entries(members, name, key):
            if item.get("floorPlanId") == floor_id:
                for c in item.get("area") or []:
                    n += _shift_coord(c, dx, dy)
        bump(name, n)

    n = 0
    for item in _entries(members, "referencePoints.json", "referencePoints"):
        for proj in item.get("projections") or []:
            if proj.get("floorPlanId") == floor_id:
                n += _shift_coord(proj.get("coord"), dx, dy)
    bump("referencePoints.json", n)

    for name in _survey_members(members):
        n = 0
        for survey in _entries(members, name, "surveys"):
            if survey.get("floorPlanId") != floor_id:
                continue
            for leg in survey.get("routePoints") or []:
                for rp in (leg if isinstance(leg, list) else [leg]):
                    if isinstance(rp, dict):
                        n += _shift_coord(rp.get("location"), dx, dy)
        bump(name, n)

    return counts


def _crop_image(blob: bytes, box, kind: str) -> bytes:
    """Crop and re-encode, keeping a JPEG as close to its original as possible."""
    Image = _require_pillow()
    im = Image.open(io.BytesIO(blob))
    im.load()
    out = io.BytesIO()
    cropped = im.crop(box)
    if kind == "PNG":
        cropped.save(out, format="PNG", optimize=True)
    elif kind == "JPEG":
        # A crop forces one re-encode. Reusing the source's own quantization
        # tables and chroma sampling keeps that generation as close to the
        # original as JPEG allows: picking a `quality` number instead either
        # throws away detail the source had or inflates the file describing
        # detail it never had. Pillow's quality="keep" cannot be used because
        # cropping detaches the image from its original JPEG.
        if cropped.mode not in ("RGB", "L"):
            cropped = cropped.convert("RGB")
        kwargs = {"optimize": True}
        try:
            from PIL import JpegImagePlugin
            qtables = getattr(im, "quantization", None)
            sampling = JpegImagePlugin.get_sampling(im)
            if qtables:
                kwargs["qtables"] = qtables
            if isinstance(sampling, int):
                kwargs["subsampling"] = sampling
        except Exception:
            # Any surprise in the source's tables: fall back to a high quality
            # rather than failing the trim.
            kwargs = {"optimize": True, "quality": 92}
        try:
            cropped.save(out, format="JPEG", **kwargs)
        except (TypeError, ValueError, OSError):
            out = io.BytesIO()
            cropped.save(out, format="JPEG", quality=92, optimize=True)
    else:  # pragma: no cover - guarded by the caller
        raise TrimError(f"cannot crop image kind {kind}")
    return out.getvalue()


def _plan_floor(members: dict, plan: dict, images: dict, margin: int) -> tuple:
    """Decide what to do with one floor. Returns (FloorResult, box or None)."""
    fid = plan.get("id")
    name = plan.get("name") or "(unnamed)"

    def refuse(reason):
        return FloorResult(fid, name, "refused", reason), None

    def skip(reason):
        return FloorResult(fid, name, "skipped", reason), None

    if plan.get("gpsReferencePoints"):
        return refuse("floor plan is geo-anchored (gpsReferencePoints is populated)")
    if plan.get("bitmapImageId"):
        return refuse(
            "floor plan carries a second image (bitmapImageId) at another resolution; "
            "cropping one and not the other would corrupt the project"
        )

    image_id = plan.get("imageId")
    blob = images.get(image_id)
    if not image_id or blob is None:
        return refuse("floor plan image is missing from the archive")

    kind = image_kind(blob)
    if kind == "SVG":
        return refuse("floor plan is an SVG; there is no pixel grid to crop")
    if kind == "UNKNOWN":
        return refuse("unrecognised image format")

    Image = _require_pillow()
    im = Image.open(io.BytesIO(blob))
    w, h = im.size

    declared_w, declared_h = plan.get("width"), plan.get("height")
    if declared_w and abs(float(declared_w) - w) > 0.5:
        return refuse(
            f"floorPlans.json says {declared_w:.0f}x{declared_h:.0f} but the image is {w}x{h}"
        )

    bounds = content_bounds(im, margin=margin)
    if bounds is None:
        return skip("floor plan has no detectable content")

    # The crop must contain the drawing, every coordinate, and whatever region
    # Ekahau itself is displaying. Union all three, then clamp.
    x0, y0, x1, y1 = bounds
    coord_box = _floor_coord_bbox(members, fid)
    if coord_box:
        x0 = min(x0, coord_box[0] - margin)
        y0 = min(y0, coord_box[1] - margin)
        x1 = max(x1, coord_box[2] + margin)
        y1 = max(y1, coord_box[3] + margin)

    rect = _existing_crop_rect(plan, w, h)
    if rect:
        x0 = min(x0, rect[0])
        y0 = min(y0, rect[1])
        x1 = max(x1, rect[2])
        y1 = max(y1, rect[3])

    x0 = int(max(0, min(x0, w)))
    y0 = int(max(0, min(y0, h)))
    x1 = int(max(0, min(x1, w)))
    y1 = int(max(0, min(y1, h)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return skip("content bounds collapsed to nothing")

    if (x1 - x0) * (y1 - y0) >= FILL_SKIP_RATIO * w * h:
        return skip(f"content already fills {(x1-x0)*(y1-y0)/(w*h)*100:.0f}% of the canvas")

    return (
        FloorResult(fid, name, "trimmed", old_size=(w, h),
                    new_size=(x1 - x0, y1 - y0), offset=(x0, y0)),
        (x0, y0, x1, y1),
    )


def _existing_crop_rect(plan: dict, w: int, h: int):
    """Ekahau's own display rectangle, if it is a real sub-rectangle.

    An identity rect (0,0,width,height) carries no information.  A real one is
    kept and translated with everything else — his CAD imports all have one,
    and it is the closest thing the file has to a statement of what matters.
    """
    keys = ("cropMinX", "cropMinY", "cropMaxX", "cropMaxY")
    if not all(isinstance(plan.get(k), (int, float)) for k in keys):
        return None
    x0, y0, x1, y1 = (float(plan[k]) for k in keys)
    if x1 <= x0 or y1 <= y0:
        return None
    if x0 <= 0 and y0 <= 0 and x1 >= w and y1 >= h:
        return None
    return x0, y0, x1, y1


def _rebase_crop_rect(plan: dict, dx: float, dy: float, new_w: int, new_h: int) -> None:
    keys = ("cropMinX", "cropMinY", "cropMaxX", "cropMaxY")
    if not all(isinstance(plan.get(k), (int, float)) for k in keys):
        return
    plan["cropMinX"] = max(0.0, float(plan["cropMinX"]) - dx)
    plan["cropMinY"] = max(0.0, float(plan["cropMinY"]) - dy)
    plan["cropMaxX"] = min(float(new_w), float(plan["cropMaxX"]) - dx)
    plan["cropMaxY"] = min(float(new_h), float(plan["cropMaxY"]) - dy)


def analyze(source: Path, margin: int = DEFAULT_MARGIN) -> TrimReport:
    """Report what trimming would do, without writing anything."""
    return _run(Path(source), None, margin, dry_run=True)


def trim(source: Path, dest: Path | None = None, margin: int = DEFAULT_MARGIN,
         in_place: bool = False) -> TrimReport:
    """Trim *source* into *dest* (or alongside it) and return a report.

    Never writes over the input while working: the archive is built at a
    temporary path and moved into place only once it is complete.
    """
    source = Path(source)
    if in_place:
        dest = source
    elif dest is None:
        dest = source.with_name(source.stem + " (trimmed)" + source.suffix)
    return _run(source, Path(dest), margin, dry_run=False)


def _run(source: Path, dest: Path | None, margin: int, dry_run: bool) -> TrimReport:
    if not source.exists():
        raise TrimError(f"no such file: {source}")

    report = TrimReport(source=source, bytes_before=source.stat().st_size)
    raw: dict = {}
    with zipfile.ZipFile(source) as z:
        names = z.namelist()
        for n in names:
            raw[n] = z.read(n)

    members: dict = {}
    for n, blob in raw.items():
        if n.endswith(".json"):
            try:
                members[n] = json.loads(blob.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                members[n] = None

    plans_doc = members.get("floorPlans.json")
    plans = (plans_doc or {}).get("floorPlans") if isinstance(plans_doc, dict) else None
    if not plans:
        raise TrimError("no floorPlans.json — this does not look like an Ekahau project")

    images = {n[len("image-"):]: blob for n, blob in raw.items() if n.startswith("image-")}

    scale_before = {p.get("id"): p.get("metersPerUnit") for p in plans}
    new_images: dict = {}
    # Members we actually rewrote. Everything else is copied through byte for
    # byte, so wallSegments.json and friends stay bit-identical rather than
    # merely equivalent after a re-serialisation.
    dirty: set = set()

    for plan in plans:
        result, box = _plan_floor(members, plan, images, margin)
        report.floors.append(result)
        if box is None or dry_run:
            continue

        x0, y0, x1, y1 = box
        blob = images[plan["imageId"]]
        kind = image_kind(blob)
        new_images[plan["imageId"]] = _crop_image(blob, box, kind)

        touched = offset_metadata(members, plan["id"], float(x0), float(y0))
        dirty.update(name for name, count in touched.items() if count)
        dirty.add("floorPlans.json")
        new_w, new_h = x1 - x0, y1 - y0
        _rebase_crop_rect(plan, float(x0), float(y0), new_w, new_h)
        plan["width"] = float(new_w)
        plan["height"] = float(new_h)

    # Scale is never a thing we adjust; if it moved, something is very wrong
    # and the whole file must be abandoned rather than half-written.
    for plan in plans:
        if plan.get("metersPerUnit") != scale_before.get(plan.get("id")):
            raise TrimError(
                f"metersPerUnit changed for floor {plan.get('name')!r} — aborting without writing"
            )

    protected = dirty.intersection(NEVER_TOUCH)
    if protected:
        raise TrimError(
            "refusing to rewrite protected member(s): " + ", ".join(sorted(protected))
        )

    if dry_run:
        report.bytes_after = report.bytes_before
        return report

    tmp = Path(str(dest) + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            n = info.filename
            if n.startswith("image-") and n[len("image-"):] in new_images:
                zout.writestr(n, new_images[n[len("image-"):]])
            elif n in dirty and members.get(n) is not None:
                zout.writestr(n, json.dumps(members[n], indent=1))
            else:
                zout.writestr(info, raw[n])

    shutil.move(str(tmp), str(dest))
    report.bytes_after = Path(dest).stat().st_size
    report.written = True
    return report
