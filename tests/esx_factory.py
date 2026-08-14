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
            "floorPlans": [{"id": f"floor-{i}", "name": f"Floor {i + 1}"}
                           for i in range(floors)]
        },
        "accessPoints.json": {
            "accessPoints": [{"id": f"ap-{i}", "name": f"AP {i + 1}"}
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
