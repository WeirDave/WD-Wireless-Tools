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

Pillow ships in requirements.txt, so a normal install already has it, and the
installers' dependency probe checks for it.  It is still imported lazily: both
install scripts treat a pip failure as a warning and carry on, so on a machine
where the wheel will not install the rest of the suite keeps working and only
this tool has to explain itself.
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
    #: "auto" when the bounds were detected, "manual" when the user drew them.
    source: str = "auto"
    #: The box actually used, in image pixels, so the page can draw it back.
    box: tuple | None = None
    #: Objects a drawn box would leave off the plan, named and located so the
    #: page can mark them on the canvas instead of reporting a bare count.
    stranded: list = field(default_factory=list)
    stranded_count: int = 0
    #: How many were pulled to the crop edge, when the user asked for that.
    clamped_count: int = 0

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


#: How an object is described to the user when it falls outside a drawn box.
#: A count of 13 is unactionable; "Note: Rev A" sitting at 9,100 x 300 is not.
_KIND_LABELS = {
    "accessPoints.json": "Access point",
    "wallPoints.json": "Wall point",
    "interferers.json": "Interferer",
    "pictureNotes.json": "Picture note",
    "areas.json": "Area",
    "attenuationAreas.json": "Attenuation area",
    "exclusionAreas.json": "Exclusion area",
    "referencePoints.json": "Reference point",
}


def _floor_coords(members: dict, floor_id: str):
    """Yield ``(coord, kind, name)`` for every coordinate on one floor.

    One traversal, used to bound the coordinates, to find the ones a drawn box
    would leave behind, and to name them. Separate copies of this walk would
    drift, and the consequence of missing a carrier is an object stranded off
    the plan - so the kind and the name ride along with the coordinate rather
    than being looked up again somewhere else.
    """
    def take(c):
        if isinstance(c, dict) and isinstance(c.get("x"), (int, float)):
            return c
        return None

    for name, key in POINT_FILES.items():
        kind = _KIND_LABELS.get(name, key)
        for item in _entries(members, name, key):
            loc = item.get("location") or {}
            if loc.get("floorPlanId") == floor_id:
                c = take(loc.get("coord"))
                if c:
                    yield c, kind, item.get("name") or item.get("title") or ""

    for name, key in AREA_FILES.items():
        kind = _KIND_LABELS.get(name, key)
        for item in _entries(members, name, key):
            if item.get("floorPlanId") == floor_id:
                label = item.get("name") or ""
                for c in item.get("area") or []:
                    c = take(c)
                    if c:
                        yield c, kind, label

    for item in _entries(members, "referencePoints.json", "referencePoints"):
        # floorPlanId is per projection: one physical point can be projected
        # onto several floors, so filter inside the list, not outside it.
        label = item.get("name") or ""
        for proj in item.get("projections") or []:
            if proj.get("floorPlanId") == floor_id:
                c = take(proj.get("coord"))
                if c:
                    yield c, "Reference point", label

    for name in _survey_members(members):
        for survey in _entries(members, name, "surveys"):
            if survey.get("floorPlanId") != floor_id:
                continue
            label = survey.get("name") or ""
            for leg in survey.get("routePoints") or []:
                # routePoints is a list of lists, and the coordinate sits
                # directly under `location` rather than `location.coord`.
                for rp in (leg if isinstance(leg, list) else [leg]):
                    if isinstance(rp, dict):
                        c = take(rp.get("location"))
                        if c:
                            yield c, "Survey route point", label


#: Most a refusal will itemise. Enough to see the pattern; a survey walk can
#: strand thousands of route points and a list that long helps nobody.
MAX_STRANDED_LISTED = 40


def _describe(item) -> str:
    """"Access point 'AP-12' at 9100, 300" - something a person can act on."""
    label = f" '{item['name']}'" if item.get("name") else ""
    return f"{item['kind']}{label} at {item['x']:.0f}, {item['y']:.0f}"


def stranded_objects(members: dict, floor_id: str, box):
    """Objects on *floor_id* that a crop to *box* would leave off the plan.

    Returns ``(items, total)``. Each item names what the object is, what it is
    called and where it sits, because the only useful thing to tell someone
    whose crop was refused is which things are in the way - a bare count sends
    them widening the box until the title block is back inside it, which is the
    one outcome the box was drawn to avoid.
    """
    x0, y0, x1, y1 = box
    items, total = [], 0
    seen = set()
    for c, kind, name in _floor_coords(members, floor_id):
        x, y = float(c["x"]), float(c["y"])
        if x0 <= x <= x1 and y0 <= y <= y1:
            continue
        total += 1
        # Areas and survey walks contribute many coordinates each; listing one
        # per object is what a person can read.
        key = (kind, name)
        if key in seen and name:
            continue
        seen.add(key)
        if len(items) < MAX_STRANDED_LISTED:
            items.append({"kind": kind, "name": name,
                          "x": round(x, 1), "y": round(y, 1)})
    return items, total


def _floor_coord_bbox(members: dict, floor_id: str):
    """Bounding box of every coordinate that belongs to one floor.

    The crop must never land inside this box or metadata would end up off the
    image, so it is unioned into the final bounds.
    """
    xs, ys = [], []
    for c, _kind, _name in _floor_coords(members, floor_id):
        xs.append(float(c["x"]))
        ys.append(float(c["y"]))
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


def _shift_coord(c, dx: float, dy: float, clamp=None) -> bool:
    """Translate one coordinate, optionally holding it inside the new canvas.

    *clamp* is the new ``(width, height)``. Without it a coordinate outside the
    crop goes negative and the object lands off the drawing, which is why that
    case is refused by default. With it the object is pulled to the nearest
    edge: still visible, still selectable in Ekahau, and no longer where it
    was - which is a trade the user has to make knowingly, not one made for
    them.
    """
    if isinstance(c, dict) and isinstance(c.get("x"), (int, float)):
        x = float(c["x"]) - dx
        y = float(c["y"]) - dy
        if clamp:
            x = min(max(x, 0.0), float(clamp[0]))
            y = min(max(y, 0.0), float(clamp[1]))
        c["x"] = x
        c["y"] = y
        return True
    return False


def offset_metadata(members: dict, floor_id: str, dx: float, dy: float,
                    clamp=None) -> dict:
    """Subtract (dx, dy) from every coordinate belonging to *floor_id*.

    With *clamp* set to the new ``(width, height)``, anything that would end up
    outside the cropped canvas is pulled to its edge instead of going negative.
    """
    counts = {}

    def bump(k, n=1):
        if n:
            counts[k] = counts.get(k, 0) + n

    for name, key in POINT_FILES.items():
        n = 0
        for item in _entries(members, name, key):
            loc = item.get("location") or {}
            if loc.get("floorPlanId") == floor_id:
                n += _shift_coord(loc.get("coord"), dx, dy, clamp)
        bump(name, n)

    for name, key in AREA_FILES.items():
        n = 0
        for item in _entries(members, name, key):
            if item.get("floorPlanId") == floor_id:
                for c in item.get("area") or []:
                    n += _shift_coord(c, dx, dy, clamp)
        bump(name, n)

    n = 0
    for item in _entries(members, "referencePoints.json", "referencePoints"):
        for proj in item.get("projections") or []:
            if proj.get("floorPlanId") == floor_id:
                n += _shift_coord(proj.get("coord"), dx, dy, clamp)
    bump("referencePoints.json", n)

    for name in _survey_members(members):
        n = 0
        for survey in _entries(members, name, "surveys"):
            if survey.get("floorPlanId") != floor_id:
                continue
            for leg in survey.get("routePoints") or []:
                for rp in (leg if isinstance(leg, list) else [leg]):
                    if isinstance(rp, dict):
                        n += _shift_coord(rp.get("location"), dx, dy, clamp)
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


def _plan_floor(members: dict, plan: dict, images: dict, margin: int,
                manual_box=None, outside_policy: str = "refuse") -> tuple:
    """Decide what to do with one floor. Returns (FloorResult, box or None).

    *manual_box* is an ``(x0, y0, x1, y1)`` rectangle in image pixels that the
    user drew. Automatic detection reads a title block and a drawing frame as
    content, which is why a bare floor plate trims and a titled CAD sheet does
    not; a drawn box says what to keep and is taken at its word.
    """
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

    if manual_box is not None:
        return _plan_manual(members, plan, fid, name, manual_box, w, h, refuse, skip,
                            policy=outside_policy)

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


MIN_MANUAL_SIDE = 8


def _plan_manual(members, plan, fid, name, box, w, h, refuse, skip,
                 policy: str = "refuse") -> tuple:
    """Honour a drawn box, refusing only what cannot be made safe.

    A drawn box is deliberately *not* unioned with the detected content or with
    Ekahau's own display rectangle. Both of those include the drawing frame and
    the title block, which is the whole reason the box exists - widening it back
    out would quietly undo the drag.

    What is not negotiable is that everything on the floor stays on the plan. A
    box that leaves an AP or a wall point outside the kept region would put that
    object at a negative coordinate, so that is refused with a count rather than
    written and explained afterwards.
    """
    try:
        x0, y0, x1, y1 = (int(round(float(v))) for v in box)
    except (TypeError, ValueError):
        return refuse("the drawn area could not be read as a rectangle")

    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    x0 = max(0, min(x0, w))
    y0 = max(0, min(y0, h))
    x1 = max(0, min(x1, w))
    y1 = max(0, min(y1, h))

    if x1 - x0 < MIN_MANUAL_SIDE or y1 - y0 < MIN_MANUAL_SIDE:
        return refuse("the drawn area is too small to crop to")

    items, outside = _coords_outside(members, fid, (x0, y0, x1, y1))
    if outside and policy != "clamp":
        # "Widen the box" is the one piece of advice that cannot work here: the
        # strays are out by the sheet margin, so widening far enough to catch
        # them puts the title block back inside the crop, which is what the box
        # was drawn to exclude. Name what is in the way instead, and leave the
        # decision where it belongs.
        what = ", ".join(_describe(i) for i in items[:4])
        more = f" and {outside - 4} more" if outside > 4 else ""
        result = FloorResult(
            fid, name, "refused",
            f"{outside} object{'s' if outside != 1 else ''} would be left off the "
            f"plan by this crop: {what}{more}. Cropping anyway puts them at a "
            "negative coordinate, off the drawing. If they are import leftovers, "
            "delete them in Ekahau and trim again - that is the clean fix. "
            "Otherwise choose 'Keep them on the edge' to pull them to the crop "
            "boundary, or redraw the box to take them in.",
            old_size=(w, h), source="manual", box=(x0, y0, x1, y1))
        result.stranded = items
        result.stranded_count = outside
        return result, None

    if (x1 - x0) >= w and (y1 - y0) >= h:
        return skip("the drawn area covers the whole canvas")

    result = FloorResult(fid, name, "trimmed", old_size=(w, h),
                         new_size=(x1 - x0, y1 - y0), offset=(x0, y0),
                         source="manual", box=(x0, y0, x1, y1))
    if outside:
        result.stranded = items
        result.stranded_count = outside
        result.clamped_count = outside
    return result, (x0, y0, x1, y1)


def _coords_outside(members: dict, floor_id: str, box):
    """What this floor would leave outside *box*: ``(items, total)``."""
    bbox = _floor_coord_bbox(members, floor_id)
    if not bbox:
        return [], 0
    x0, y0, x1, y1 = box
    # _floor_coord_bbox is the union of every coordinate on the floor, so if it
    # sits inside the box then so does every point that formed it, and the
    # expensive walk can be skipped.
    if bbox[0] >= x0 and bbox[1] >= y0 and bbox[2] <= x1 and bbox[3] <= y1:
        return [], 0
    return stranded_objects(members, floor_id, box)


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


def analyze(source: Path, margin: int = DEFAULT_MARGIN, boxes=None,
             outside_policy: str = "refuse") -> TrimReport:
    """Report what trimming would do, without writing anything."""
    return _run(Path(source), None, margin, dry_run=True, boxes=boxes,
                outside_policy=outside_policy)


def trim(source: Path, dest: Path | None = None, margin: int = DEFAULT_MARGIN,
         in_place: bool = False, boxes=None,
         outside_policy: str = "refuse") -> TrimReport:
    """Trim *source* into *dest* (or alongside it) and return a report.

    Never writes over the input while working: the archive is built at a
    temporary path and moved into place only once it is complete.
    """
    source = Path(source)
    if in_place:
        dest = source
    elif dest is None:
        dest = source.with_name(source.stem + " (trimmed)" + source.suffix)
    return _run(source, Path(dest), margin, dry_run=False, boxes=boxes,
                outside_policy=outside_policy)


def _run(source: Path, dest: Path | None, margin: int, dry_run: bool,
         boxes=None, outside_policy: str = "refuse") -> TrimReport:
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
        result, box = _plan_floor(members, plan, images, margin,
                                  manual_box=(boxes or {}).get(plan.get("id")),
                                  outside_policy=outside_policy)
        report.floors.append(result)
        if box is None or dry_run:
            continue

        x0, y0, x1, y1 = box
        blob = images[plan["imageId"]]
        kind = image_kind(blob)
        new_images[plan["imageId"]] = _crop_image(blob, box, kind)

        # Only a deliberate "keep them on the edge" clamps; otherwise a
        # coordinate outside the crop would have been refused already, so there
        # is nothing to pull in and nothing to move by accident.
        clamp = (x1 - x0, y1 - y0) if result.clamped_count else None
        touched = offset_metadata(members, plan["id"], float(x0), float(y0), clamp)
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


# ---------------------------------------------------------------------------
# Web API — thin JSON wrappers used by /api/plantrim/<action>.
#
# Everything above is a plain library; nothing below it changes behaviour, it
# only shapes results for the browser and keeps server.py free of file dialogs.
# ---------------------------------------------------------------------------

def _floor_json(f: FloorResult) -> dict:
    saved = None
    if f.old_size and f.new_size:
        before = f.old_size[0] * f.old_size[1]
        after = f.new_size[0] * f.new_size[1]
        saved = round((1 - after / before) * 100) if before else 0
    return {
        "id": f.floor_id,
        "name": f.name,
        "action": f.action,
        "reason": f.reason,
        "oldSize": list(f.old_size) if f.old_size else None,
        "newSize": list(f.new_size) if f.new_size else None,
        "offset": list(f.offset) if f.offset else None,
        "areaSavedPct": saved,
        "source": f.source,
        "box": list(f.box) if f.box else None,
        "stranded": f.stranded,
        "strandedCount": f.stranded_count,
        "clampedCount": f.clamped_count,
    }


def _report_json(report: TrimReport, dest: Path | None = None) -> dict:
    return {
        "ok": True,
        "source": str(report.source),
        "sourceName": report.source.name,
        "dest": str(dest) if dest else None,
        "floors": [_floor_json(f) for f in report.floors],
        "trimmedCount": report.trimmed_count,
        "floorCount": len(report.floors),
        "bytesBefore": report.bytes_before,
        "bytesAfter": report.bytes_after,
        "written": report.written,
        "summary": report.summary(),
    }


def api_analyze(path: str, margin: int = DEFAULT_MARGIN, boxes=None,
                outside_policy: str = "refuse") -> dict:
    try:
        return _report_json(analyze(Path(path), margin=int(margin), boxes=boxes,
                                   outside_policy=outside_policy))
    except TrimError as exc:
        return {"ok": False, "error": str(exc)}


def api_trim_to(path: str, dest: str, margin: int = DEFAULT_MARGIN,
                boxes=None, outside_policy: str = "refuse") -> dict:
    """Trim *path* into an explicit *dest*, for the upload/download flow."""
    try:
        report = trim(Path(path), Path(dest), margin=int(margin), boxes=boxes,
                      outside_policy=outside_policy)
        return _report_json(report, dest=Path(dest))
    except TrimError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # pragma: no cover - surfaced to the UI
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
