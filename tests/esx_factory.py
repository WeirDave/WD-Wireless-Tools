"""Generate tiny, fictional Ekahau-like ESX archives for tests.

The fixtures intentionally contain no data copied from a real project.  ESX
files are ZIP archives, so these tests only create the JSON members needed by
the parsers under test.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


PROJECT_ID = "00000000-0000-4000-8000-000000000001"
SURVEY_ID = "00000000-0000-4000-8000-000000000002"



def _access_point(i: int, floors: int, placed: bool) -> dict:
    """One access point, optionally standing somewhere on a floor plan.

    Laid out on a 6-wide grid inside the 1600x1200 sheet, inset from the edges
    so nothing sits exactly on a boundary - a coordinate of 0 hides an
    off-by-one that a coordinate of 120 does not.
    """
    ap = {"id": f"ap-{i}", "name": f"AP {i + 1}"}
    if not placed:
        return ap
    col, row = i % 6, i // 6
    ap["location"] = {
        "floorPlanId": f"floor-{i % max(1, floors)}",
        "coord": {"x": 120.0 + col * 260.0, "y": 120.0 + row * 200.0, "z": 0.0},
    }
    return ap


def make_esx(
    path: Path,
    *,
    project_id: str = PROJECT_ID,
    author: str = "engineer@example.com",
    floors: int = 1,
    aps: int = 2,
    measurements: int = 3,
    surveys: int = 1,
    referenced_images: tuple[str, ...] = ("floor-one.png",),
    project_type: str | None = "Design",
    placed: bool = False,
) -> Path:
    """Create a minimal deterministic ESX archive and return *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    members: dict[str, object] = {
        "project.json": {
            "project": {
                "id": project_id,
                "name": "Sample Project",
                "history": {
                    "createdBy": author,
                    "modifiedAt": "2026-01-02T03:04:05Z",
                },
            }
        },
        "floorPlans.json": {
            # width/height are what every coordinate in the project is measured
            # against, and a real floor plan always carries them. Omitting them
            # made every consumer fall back to 1, so a whole plan was one unit
            # across and anything reasoning about distance on it was working in
            # fractions without knowing.
            "floorPlans": [{"id": f"floor-{i}", "name": f"Floor {i + 1}",
                            "width": 1600, "height": 1200,
                            "metersPerUnit": 0.05}
                           for i in range(floors)]
        },
        # `placed` puts each AP on a floor plan at a real coordinate, spread
        # over a grid. Off by default because most callers only count APs, and
        # an AP with no location is a legal - if unusual - state that several
        # tests rely on. Anything measuring *where* an AP is needs it on.
        "accessPoints.json": {
            "accessPoints": [_access_point(i, floors, placed)
                             for i in range(aps)]
        },
        "accessPointMeasurements.json": {
            "accessPointMeasurements": [{"id": f"measurement-{i}"}
                                         for i in range(measurements)]
        },
        "images.json": {
            "images": [{"id": f"image-{i}", "imageName": name}
                       for i, name in enumerate(referenced_images)]
        },
    }
    if surveys:
        members[f"survey-{SURVEY_ID}.json"] = {
            "surveys": [{"id": f"survey-{i}"} for i in range(surveys)]
        }
    if project_type in {"Design", "Hybrid"}:
        members["simulatedRadios.json"] = {"simulatedRadios": []}
    if project_type in {"Measured", "Hybrid"}:
        members["measuredRadios.json"] = {"measuredRadios": []}

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("version", "1.0")
        for name, body in members.items():
            archive.writestr(name, json.dumps(body, separators=(",", ":")))
    return path
