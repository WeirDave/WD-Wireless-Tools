"""Building a capacity template in Capacity itself, and applying what was built.

"we don't have any way to adjust that template and capacity is the only place
in which the template can exist" ... "it needs to be built utilizing the stuff
that's in [Ekahau] So that they can choose you know the device types the
amount of devices etc". A template is now built from rows of device profile,
usage profile and devices per person, picked from the profiles in the open
project, and saved through `/api/capacity/build`.

Driven through Flask's test client with an invented project.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import server  # noqa: E402
from tools import capacity_profiles as cap  # noqa: E402
from test_capacity_profiles import build_esx  # noqa: E402

HDR = {"X-WD-Wireless-Tools": "1"}


class Base(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.esx = build_esx(Path(self.tmp.name) / "src.esx")
        self.bytes = Path(self.esx).read_bytes()
        orig = cap.USER_DIR
        cap.USER_DIR = Path(self.tmp.name) / "capacity"
        self.addCleanup(setattr, cap, "USER_DIR", orig)

    def analyze(self):
        r = self.client.post("/api/capacity/analyze?name=src.esx", data=self.bytes, headers=HDR)
        return r.get_json()

    def build(self, spec, replaces=None):
        r = self.client.post("/api/capacity/build", json={"spec": spec, "replaces": replaces},
                             headers=HDR)
        return r.get_json()


class TheProjectOffersItsProfiles(Base):
    def test_every_device_and_usage_profile_is_offered_with_its_definition(self):
        a = self.analyze()["available"]
        self.assertTrue(a["devices"])
        self.assertTrue(a["usages"])
        for name in a["devices"]:
            self.assertTrue(a["defs"]["devices"][name], name)
        for name in a["usages"]:
            self.assertTrue(a["defs"]["usages"][name], name)


class BuildTemplateItself(unittest.TestCase):
    """`cap.build_template` on its own: what the route saves is what it
    returns."""

    def test_rows_become_per_person_numbers_and_shares(self):
        t = cap.build_template({"name": "Invented", "items": [
            {"device": "D1", "usage": "U1", "perOccupant": 1.5},
            {"device": "D2", "usage": "U2", "perOccupant": "0.5"}]})
        self.assertTrue(t["ok"], t)
        self.assertEqual([i["perOccupant"] for i in t["items"]], [1.5, 0.5])
        self.assertEqual([i["shareOfTotal"] for i in t["items"]], [0.75, 0.25])
        self.assertEqual(t["devicesPerOccupant"], 2.0)

    def test_a_row_missing_a_profile_is_named(self):
        t = cap.build_template({"name": "Invented", "items": [
            {"device": "D1", "usage": "", "perOccupant": 1}]})
        self.assertFalse(t["ok"])
        self.assertIn("row 1", t["error"])


class ATemplateIsBuiltFromRows(Base):
    def spec(self, **over):
        a = self.analyze()["available"]
        spec = {"name": "Invented office", "description": "two phones",
                "items": [{"device": a["devices"][0], "usage": a["usages"][0], "perOccupant": 1},
                          {"device": a["devices"][-1], "usage": a["usages"][-1], "perOccupant": 0.5}],
                "defs": a["defs"]}
        spec.update(over)
        return spec

    def test_it_saves_and_is_listed(self):
        r = self.build(self.spec())
        self.assertTrue(r["ok"], r)
        names = [t["name"] for t in self.client.post(
            "/api/capacity/templates", json={}, headers=HDR).get_json()["templates"]]
        self.assertIn("Invented office", names)
        self.assertAlmostEqual(r["template"]["devicesPerOccupant"], 1.5)

    def test_it_carries_only_the_profiles_it_uses(self):
        spec = self.spec()
        r = self.build(spec)
        used_devices = {i["device"] for i in spec["items"]}
        self.assertEqual(set(r["template"]["profileDefs"]["devices"]), used_devices)

    def test_a_row_with_no_number_is_refused_and_says_which(self):
        spec = self.spec()
        spec["items"][1]["perOccupant"] = 0
        r = self.build(spec)
        self.assertFalse(r["ok"])
        self.assertIn("row 2", r["error"])

    def test_a_template_with_no_name_is_refused(self):
        r = self.build(self.spec(name="  "))
        self.assertFalse(r["ok"])
        self.assertIn("name", r["error"])

    def test_renaming_in_the_editor_does_not_leave_the_old_one(self):
        first = self.build(self.spec(name="Old name"))
        second = self.build(self.spec(name="New name"), replaces=first["file"])
        self.assertTrue(second["ok"], second)
        files = [t["_file"] for t in self.client.post(
            "/api/capacity/templates", json={}, headers=HDR).get_json()["templates"]
                 if not t.get("_builtin")]
        self.assertEqual(files, [second["file"]])

    def test_a_shipped_example_is_never_deleted_by_a_rename(self):
        builtin = next(t for t in self.client.post(
            "/api/capacity/templates", json={}, headers=HDR).get_json()["templates"]
                       if t.get("_builtin"))
        r = self.build(self.spec(name="My copy"), replaces=builtin["_file"])
        self.assertTrue(r["ok"])
        files = [t["_file"] for t in self.client.post(
            "/api/capacity/templates", json={}, headers=HDR).get_json()["templates"]]
        self.assertIn(builtin["_file"], files)

    def test_what_was_built_applies_with_the_numbers_typed(self):
        r = self.build(self.spec())
        plan = self.client.post(
            "/api/capacity/plan?name=src.esx&template=%s&occupants=40&existing=devices"
            % quote(r["file"]), data=self.bytes, headers=HDR).get_json()
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["totalDevices"], 60)


if __name__ == "__main__":
    unittest.main()
