"""Applying a template into an area he drew keeps that area's requirement.

The plan says only the devices are written into an area that is already
there, and his outline, name and colour were kept - but the writer also put
the template's `requirementId` on it. An area he had marked with a different
requirement (an invented "voice grade" one here) came out demanding the
template's instead, and nothing said so. An area with no requirement still
gets the template's, and an area the apply creates carries it as before.

Read back out of the archive `apply_to` wrote, because the requirement that
matters is the one Ekahau will open.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tools import capacity_profiles as cap  # noqa: E402
from test_capacity_profiles import FLOOR, build_esx  # noqa: E402

SQUARE = [{"x": 0, "y": 0}, {"x": 500, "y": 0}, {"x": 500, "y": 500}, {"x": 0, "y": 500}]


def areas_of(path):
    with zipfile.ZipFile(path) as zf:
        return {a["id"]: a for a in json.loads(zf.read("areas.json"))["areas"]}


class HisRequirementIsKept(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.template = cap.derive_template(
            cap.extract(Path(build_esx(self.dir / "seed.esx"))), 500, "Invented Office")
        self.assertTrue(self.template["ok"], self.template.get("error"))

    def project(self, area):
        """A project whose only area on FLOOR is `area`, with a second,
        invented requirement for it to point at."""
        built = Path(build_esx(self.dir / "built.esx", areas=[area]))
        out = self.dir / "src.esx"
        with zipfile.ZipFile(built) as zin, zipfile.ZipFile(out, "w") as zout:
            for name in zin.namelist():
                body = zin.read(name)
                if name == "requirements.json":
                    req = json.loads(body)
                    req["requirements"].append({"id": "req-voice",
                                                "name": "Invented Voice Grade"})
                    body = json.dumps(req).encode("utf-8")
                zout.writestr(name, body)
        return out

    def apply(self, src):
        dest = self.dir / "out.esx"
        r = cap.apply_to(src, dest, self.template, 100)
        self.assertTrue(r["ok"], r.get("error"))
        return r, areas_of(dest)

    def test_an_area_with_its_own_requirement_keeps_it(self):
        r, after = self.apply(self.project(
            {"id": "his-area", "floorPlanId": FLOOR, "requirementId": "req-voice",
             "area": SQUARE}))
        self.assertEqual(r["areasPopulated"], 1, "the devices went into his area")
        self.assertTrue(after["his-area"]["capacityItems"])
        self.assertEqual(after["his-area"]["requirementId"], "req-voice")

    def test_an_area_with_no_requirement_gets_the_templates(self):
        _r, after = self.apply(self.project(
            {"id": "his-area", "floorPlanId": FLOOR, "area": SQUARE}))
        got = after["his-area"].get("requirementId")
        self.assertTrue(got, "an area with nothing to lose takes the template's")
        self.assertNotEqual(got, "req-voice")


if __name__ == "__main__":
    unittest.main()
