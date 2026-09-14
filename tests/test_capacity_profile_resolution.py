"""Resolving a template's profiles against the project it is applied to.

Reported from a real new-site run: a project created from scratch — DWG
imported, walls drawn, saved — refused the built-in template with a wall of
profile names and the advice to "re-capture the template", which was useless
because re-capturing was not the problem.

Two faults, and the first was mine. **The shipped example template carried
hand-authored profile names that Ekahau does not use.** Checked against 109 real
projects, the stock names are `Generic Wi-Fi 6E Laptop`, `Normal SLA (2 Mbps)`
and `Conferencing, GoToMeeting`; the template said
`Generic Wi-Fi 6E Laptop, Wi-Fi 6 2x2:2 160MHz`, `Normal SLA` and
`Conferencing`. Four of its five names matched nothing.

**And resolution was exact-match only.** Ekahau mints fresh uuids per project,
so a name is the only thing that crosses between two files — but the same stock
profile is spelled differently across Ekahau versions and across the panel it is
read from. Matching now falls back to the stem before the comma or the bracket.

What it must never do is guess. Ekahau ships *both* `Conferencing, GoToMeeting`
and `Conferencing, Lync/Skype`, so a template row saying `Conferencing` is
genuinely ambiguous and is reported as such, with both candidates named.
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

from tools import capacity_profiles as cap  # noqa: E402

# Verified against 109 projects in the user's own Ekahau Projects folder.
STOCK_DEVICES = [
    "Generic Barcode Scanner", "Generic Smartphone", "Generic VoIP Phone",
    "Generic Tablet", "Generic Laptop",
    "Generic Wi-Fi 6E Smartphone", "Generic Wi-Fi 6E Laptop",
]
STOCK_USAGES = [
    "Normal SLA (2 Mbps)", "Low SLA (1 Mbps)", "High SLA (4 Mbps)",
    "Background Sync", "Conferencing, GoToMeeting", "Conferencing, Lync/Skype",
    "Streaming, Video",
]


def fresh_project(path):
    """A project as Ekahau creates one: stock profiles, a plan, no areas."""
    members = {
        "project.json": {"project": {"id": "p", "name": "New Site"}},
        "floorPlans.json": {"floorPlans": [
            {"id": "f1", "name": "FLR1", "width": 2000.0, "height": 1500.0,
             "metersPerUnit": 0.05, "bitmapImageId": "img-1"},
        ]},
        "deviceProfiles.json": {"deviceProfiles": [
            {"id": "dev-%d" % i, "name": n} for i, n in enumerate(STOCK_DEVICES)]},
        "usageProfiles.json": {"usageProfiles": [
            {"id": "use-%d" % i, "name": n} for i, n in enumerate(STOCK_USAGES)]},
        "requirements.json": {"requirements": [
            {"id": "req-1", "name": "Ekahau Best Practices", "isDefault": True}]},
        "areas.json": {"areas": []},
        "wallPoints.json": {"wallPoints": [
            {"id": "wp1", "location": {"floorPlanId": "f1", "coord": {"x": 200.0, "y": 300.0}}},
            {"id": "wp2", "location": {"floorPlanId": "f1", "coord": {"x": 800.0, "y": 700.0}}},
        ]},
        "wallSegments.json": {"wallSegments": [{"id": "ws1", "wallPoints": ["wp1", "wp2"]}]},
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, json.dumps(body))
        z.writestr("image-img-1", bytes([0x89]) + b"PNG fixture")
    return path


def template(device, usage, requirement="Ekahau Best Practices"):
    """A minimal one-row template naming the profiles however we please."""
    return {
        "name": "Test", "schema": 2, "requirementName": requirement,
        "devicesPerOccupant": 1.0, "profileDefs": {},
        "items": [{"device": device, "usage": usage,
                   "perOccupant": 1.0, "shareOfTotal": 1.0, "capturedCount": 100}],
    }


class StemMatching(unittest.TestCase):
    """The rule: the part before the comma or the bracket is what crosses."""

    def test_a_bracketed_rate_is_not_part_of_the_identity(self):
        self.assertEqual(cap._base_name("Normal SLA"),
                         cap._base_name("Normal SLA (2 Mbps)"))

    def test_a_trailing_product_name_is_not_part_of_the_identity(self):
        self.assertEqual(cap._base_name("Conferencing"),
                         cap._base_name("Conferencing, GoToMeeting"))

    def test_a_radio_spec_is_not_part_of_the_identity(self):
        self.assertEqual(cap._base_name("Generic Wi-Fi 6E Laptop, Wi-Fi 6 2x2:2 160MHz"),
                         cap._base_name("Generic Wi-Fi 6E Laptop"))

    def test_two_different_stock_devices_do_not_collapse(self):
        """The failure this guards: writing laptops as 6E laptops, silently."""
        self.assertNotEqual(cap._base_name("Generic Laptop"),
                            cap._base_name("Generic Wi-Fi 6E Laptop"))

    def test_the_two_conferencing_profiles_share_a_stem(self):
        """Which is why "Conferencing" alone has to be refused, not guessed."""
        self.assertEqual(cap._base_name("Conferencing, GoToMeeting"),
                         cap._base_name("Conferencing, Lync/Skype"))


class ResolvingAgainstAFreshProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.esx = Path(fresh_project(self.dir / "new-site.esx"))

    def tearDown(self):
        self.tmp.cleanup()

    def apply(self, tpl, name="out.esx"):
        return cap.apply_to(self.esx, self.dir / name, tpl, 100)

    def test_the_exact_stock_name_applies(self):
        r = self.apply(template("Generic Wi-Fi 6E Laptop", "Normal SLA (2 Mbps)"))
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["profilesCreated"], [], "the stock profile was there")

    def test_a_template_written_with_a_shorter_name_still_applies(self):
        """His case: a saved template saying "Normal SLA"."""
        r = self.apply(template("Generic Wi-Fi 6E Laptop", "Normal SLA"))
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["profilesCreated"], [])

    def test_a_template_written_with_a_longer_name_still_applies(self):
        r = self.apply(template(
            "Generic Wi-Fi 6E Laptop, Wi-Fi 6 2x2:2 160MHz", "Normal SLA (2 Mbps)"))
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["profilesCreated"], [])

    def test_resolution_never_matches_on_an_id(self):
        """Ids are per-project, so a matching id would be a coincidence."""
        tpl = template("Generic Wi-Fi 6E Laptop", "Normal SLA (2 Mbps)")
        tpl["items"][0]["device"] = "dev-6"        # a real id in this project
        r = self.apply(tpl)
        self.assertFalse(r["ok"])
        self.assertIn("does not have", r["error"])

    def test_an_ambiguous_stem_is_refused_and_both_candidates_named(self):
        r = self.apply(template("Generic Wi-Fi 6E Laptop", "Conferencing"))
        self.assertFalse(r["ok"])
        self.assertIn("more than one", r["error"])
        self.assertIn("GoToMeeting", r["error"])
        self.assertIn("Lync/Skype", r["error"])

    def test_nothing_is_written_when_a_profile_cannot_be_resolved(self):
        r = self.apply(template("Nonexistent Device", "Normal SLA (2 Mbps)"),
                       name="nope.esx")
        self.assertFalse(r["ok"])
        self.assertFalse((self.dir / "nope.esx").exists())

    def test_the_message_says_ekahau_ships_these_as_stock(self):
        """"Re-capture the template" was the wrong advice and cost a report."""
        r = self.apply(template("Nonexistent Device", "Normal SLA (2 Mbps)"))
        self.assertIn("stock content", r["error"])

    def test_the_message_names_what_is_missing_and_what_kind(self):
        r = self.apply(template("Nonexistent Device", "Normal SLA (2 Mbps)"))
        self.assertIn("device profile", r["error"])
        self.assertIn("Nonexistent Device", r["error"])


class TheShippedExampleTemplate(unittest.TestCase):
    """It must name profiles Ekahau actually ships, or it applies to nothing."""

    def setUp(self):
        path = ROOT / "templates" / "Office_Wi-Fi_6E_example_capacitytemplate.json"
        self.tpl = json.loads(path.read_text(encoding="utf-8"))

    def test_every_device_it_names_is_stock(self):
        for item in self.tpl["items"]:
            with self.subTest(device=item["device"]):
                self.assertIn(item["device"], STOCK_DEVICES)

    def test_every_usage_it_names_is_stock(self):
        for item in self.tpl["items"]:
            with self.subTest(usage=item["usage"]):
                self.assertIn(item["usage"], STOCK_USAGES)

    def test_it_applies_to_a_brand_new_project_without_creating_anything(self):
        """The whole point of shipping an example: it works out of the box."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            esx = fresh_project(d / "new-site.esx")
            r = cap.apply_to(esx, d / "out.esx", self.tpl, 120)
            self.assertTrue(r["ok"], r.get("error"))
            self.assertEqual(r["profilesCreated"], [])
            self.assertEqual(r["floorsWritten"], ["FLR1"])


if __name__ == "__main__":
    unittest.main()
