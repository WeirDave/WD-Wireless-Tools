"""Suggest a keep-region by comparing the sheets of a CAD set to each other.

A single sheet cannot tell you which of its ink is a drawing and which is a
title block. Both are ink. Every rule that tries — look at the right edge, look
for a dense corner — is a guess about one firm's drawing conventions, and it is
wrong silently, by cropping away plan.

A *set* of sheets can tell you, because a CAD set puts its frame and its title
block in the same pixels on every sheet and puts a different building on each
one. So ink that is identical across the set is furniture, and ink that differs
between sheets is drawing. That is closer to a proof than a heuristic, and it
never has to know which edge anything is on.

The confound worth naming: floors of one building share their exterior outline,
their core and their stairs, so "identical across sheets" catches some real
drawing too. That is why the suggestion is the bounding box of the ink that
*differs* and is offered rather than applied — a box that comes out slightly
tight is one drag to fix, and the user is looking at it either way.

Falls back to single-sheet content detection when there is nothing to compare
against: one floor, or no two sheets the same size. The basis is always
reported, because "identical on 12 of 14 sheets" and "this is where the ink is"
are very different claims and the user deserves to know which one they got.
"""
from __future__ import annotations

import io
from collections import defaultdict

from tools import esx_trimmer

#: Longest side of the grid the comparison runs on. A CAD sheet does not need
#: 75 megapixels inspected to find a title block, and a coarse grid also
#: absorbs the sub-pixel differences between two renders of the same frame.
GRID = 900

#: Ink is anything darker than this, matching the single-sheet detector.
INK = esx_trimmer.INK_THRESHOLD

#: A pixel counts as furniture when this share of the sheets agree it has ink.
#: Not all of them: one sheet in a set often carries a revision cloud or a
#: stamp over the title block, and demanding unanimity would lose the whole
#: block over one sheet's mark.
AGREE = 0.85

#: Grown around the differing ink before the box is offered.
MARGIN_FRACTION = 0.015


class Suggestion:
    """One floor's proposed box, and the evidence for it."""

    __slots__ = ("floor_id", "box", "basis", "evidence", "sheets")

    def __init__(self, floor_id, box, basis, evidence, sheets=0):
        self.floor_id = floor_id
        self.box = box
        self.basis = basis          # "cross-sheet" | "single-sheet" | "none"
        self.evidence = evidence
        self.sheets = sheets

    def as_dict(self) -> dict:
        return {
            "floorId": self.floor_id,
            "box": list(self.box) if self.box else None,
            "basis": self.basis,
            "evidence": self.evidence,
            "sheets": self.sheets,
        }


def _ink_grid(blob: bytes, gw: int, gh: int):
    """A sheet reduced to a gw x gh grid of booleans: is there ink here."""
    Image = esx_trimmer._require_pillow()
    im = Image.open(io.BytesIO(blob)).convert("L")
    # `reduce`-style downsampling would average ink away to nothing on thin
    # linework, so take the darkest pixel in each cell instead: a hairline that
    # survives at full resolution survives here too.
    small = im.resize((gw, gh), Image.BOX)
    darkest = im.resize((gw, gh), Image.NEAREST)
    a, b = small.load(), darkest.load()
    grid = bytearray(gw * gh)
    for y in range(gh):
        row = y * gw
        for x in range(gw):
            if a[x, y] < INK or b[x, y] < INK:
                grid[row + x] = 1
    return grid


def _bbox_of(grid, gw: int, gh: int, predicate):
    x0, y0, x1, y1 = gw, gh, -1, -1
    for y in range(gh):
        row = y * gw
        for x in range(gw):
            if predicate(grid[row + x]):
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    if x1 < 0:
        return None
    return x0, y0, x1 + 1, y1 + 1


#: A row or column counts as drawing once it carries this share of the busiest
#: row's differing ink.
DENSITY = 0.06


def _dense_bbox(grid, gw: int, gh: int, predicate):
    """Bounding box of *predicate*, by row and column density.

    A strict bounding box is at the mercy of a single stray cell, and here the
    stray cell is not noise but real ink: a revision cloud, a stamp or a hand
    mark that appears on one sheet of the set. That is indistinguishable from
    floor-specific drawing by counting alone — both appear on exactly one sheet.

    What separates them is how much of a row they occupy. A floor plan puts
    differing ink across a large part of every row it touches; a mark in the
    corner of a title block puts a few cells in a few rows. Cutting at a share
    of the busiest row keeps the plan and ignores the mark, which is the same
    reasoning the single-sheet detector uses against JPEG speckle.
    """
    rows = [0] * gh
    cols = [0] * gw
    for y in range(gh):
        base = y * gw
        for x in range(gw):
            if predicate(grid[base + x]):
                rows[y] += 1
                cols[x] += 1

    def span(counts):
        peak = max(counts) if counts else 0
        if not peak:
            return None
        cutoff = max(1, int(DENSITY * peak))
        hits = [i for i, c in enumerate(counts) if c >= cutoff]
        return (hits[0], hits[-1] + 1) if hits else None

    xs, ys = span(cols), span(rows)
    if not xs or not ys:
        return None
    return xs[0], ys[0], xs[1], ys[1]


def _cross_sheet(sheets, w: int, h: int):
    """Compare same-size sheets; return (box_in_grid, gw, gh, agreeing, total).

    *sheets* is a list of image blobs, all of size w x h.
    """
    scale = GRID / float(max(w, h))
    gw = max(8, int(round(w * scale)))
    gh = max(8, int(round(h * scale)))

    counts = [0] * (gw * gh)
    for blob in sheets:
        grid = _ink_grid(blob, gw, gh)
        for i, v in enumerate(grid):
            if v:
                counts[i] += 1

    n = len(sheets)
    common_at = max(2, int(round(AGREE * n)))

    # Ink that differs between sheets is drawing. Ink present on nearly every
    # sheet is the frame and the title block.
    def differs(c):
        return 0 < c < common_at

    box = _dense_bbox(counts, gw, gh, differs)
    common = _bbox_of(counts, gw, gh, lambda c: c >= common_at)
    return box, common, gw, gh, common_at, n


def _to_image_box(box, gw, gh, w, h):
    """Grid coordinates back to image pixels, grown by the margin."""
    sx, sy = w / float(gw), h / float(gh)
    mx = int(round(MARGIN_FRACTION * w))
    my = int(round(MARGIN_FRACTION * h))
    x0 = max(0, int(box[0] * sx) - mx)
    y0 = max(0, int(box[1] * sy) - my)
    x1 = min(w, int(round(box[2] * sx)) + mx)
    y1 = min(h, int(round(box[3] * sy)) + my)
    return x0, y0, x1, y1


def _single_sheet(blob: bytes, w: int, h: int):
    """The existing detector, used when there is nothing to compare against."""
    Image = esx_trimmer._require_pillow()
    im = Image.open(io.BytesIO(blob))
    bounds = esx_trimmer.content_bounds(im, margin=esx_trimmer.DEFAULT_MARGIN)
    if bounds is None:
        return None
    x0, y0, x1, y1 = (int(v) for v in bounds)
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def suggest(floors) -> list:
    """Propose a keep-region for each floor.

    *floors* is a list of ``(floor_id, blob, width, height)``. Returns a list of
    :class:`Suggestion`, one per floor, in the order given.
    """
    by_size = defaultdict(list)
    for floor_id, blob, w, h in floors:
        by_size[(int(w), int(h))].append((floor_id, blob))

    out = {}
    for (w, h), group in by_size.items():
        if len(group) < 2:
            # Nothing to compare against; say so rather than implying the set
            # was consulted.
            floor_id, blob = group[0]
            try:
                box = _single_sheet(blob, w, h)
            except Exception:
                box = None
            out[floor_id] = Suggestion(
                floor_id, box, "single-sheet" if box else "none",
                "No other sheet is this size, so this is where the ink is on "
                "this one — a title block is kept, because a single sheet "
                "cannot tell one from a drawing.",
                sheets=1)
            continue

        blobs = [b for _, b in group]
        try:
            box, common, gw, gh, agree_at, n = _cross_sheet(blobs, w, h)
        except Exception:
            box = None
        if not box:
            for floor_id, blob in group:
                out[floor_id] = Suggestion(
                    floor_id, None, "none",
                    "Every sheet of this size is identical, so nothing here "
                    "distinguishes a drawing from a title block.", sheets=len(group))
            continue

        image_box = _to_image_box(box, gw, gh, w, h)
        excluded = ""
        if common:
            cb = _to_image_box(common, gw, gh, w, h)
            if cb[0] < image_box[0] or cb[1] < image_box[1] \
                    or cb[2] > image_box[2] or cb[3] > image_box[3]:
                excluded = (" A border region identical across the set was left "
                            "out — that is the drawing frame and title block.")
        evidence = (
            f"Compared against {n} sheets of the same size. The kept area is "
            f"where the ink differs between them; ink that repeats on at least "
            f"{agree_at} of {n} is the same on every sheet, so it is furniture "
            f"rather than a plan.{excluded}"
        )
        for floor_id, _ in group:
            out[floor_id] = Suggestion(floor_id, image_box, "cross-sheet",
                                       evidence, sheets=n)

    return [out[fid] for fid, _, _, _ in floors if fid in out]
