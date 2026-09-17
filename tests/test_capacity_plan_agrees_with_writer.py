"""The preview must not promise a run the writer will refuse.

Found by running Prep over every one of Ekahau's sample projects: two of twenty
produced a preview saying *"your area - adding 6 capacity items, your outline is
not changed"*, with the button enabled - and then answered the click with HTTP
400, because the project does not carry the device profiles the template names.

The writer was right to refuse. Capacity items pointing at profiles the file
does not contain open quietly wrong, which is worse than not writing. The fault
was that **only the writer knew**: `apply_to` resolved the template's profiles
and `plan_application` did not, so the preview could not see the refusal coming
and the failure was only ever discovered by clicking.

The invariant these tests hold is the one that matters: **if the plan says a
floor will be written, the writer must not then refuse it for missing
profiles.** Anything else is a preview that lies.
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

PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"


def project(path: Path, devices, usages, requirements=("Ekahau Best Practices",)):
    """A project carrying exactly the profiles named, and one drawn wall."""
    members = {
        "floorPlans.json": {"floorPlans": [
            {"id": "f1", "name": "FLR1", "width": 2000.0, "height": 1500.0,
             "metersPerUnit": 0.05, "bitmapImageId": "img-1"}]},
        "deviceProfiles.json": {"deviceProfiles": [
            {"id": "dev-%d" % i, "name": n} for i, n in enumerate(devices)]},
        "usageProfiles.json": {"usageProfiles": [
            {"id": "use-%d" % i, "name": n} for i, n in enumerate(usages)]},
        "requirements.json": {"requirements": [
            {"id": "req-%d" % i, "name": n, "isDefault": i == 0}
            for i, n in enumerate(requirements)]},
        "areas.json": {"areas": []},
        "wallPoints.json": {"wallPoints": [
            {"id": "wp1", "location": {"floorPlanId": "f1",
                                       "coord": {"x": 200.0, "y": 300.0}}},
            {"id": "wp2", "location": {"floorPlanId": "f1",
                                       "coord": {"x": 800.0, "y": 700.0}}}]},
        "wallSegments.json": {"wallSegments": [
            {"id": "ws1", "wallPoints": ["wp1", "wp2"]}]},
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, json.dumps(body))
        z.writestr("image-img-1", bytes([0x89]) + b"PNG fixture")
    return path


def template(device, usage, requirement="Ekahau Best Practices"):
    return {
        "name": "Test", "schema": 2, "requirementName": requirement,
        "devicesPerOccupant": 1.0, "profileDefs": {},
        "items": [{"device": device, "usage": usage,
                   "perOccupant": 1.0, "shareOfTotal": 1.0,
                   "capturedCount": 100}],
    }


class ThePlanSeesWhatTheWriterSees(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _has_profiles(self):
        return project(self.dir / "good.esx",
                       ["Generic Wi-Fi 6E Laptop"], ["Normal SLA (2 Mbps)"])

    def _lacks_profiles(self):
        """Exactly the two sample projects' situation: no 6E device profile."""
        return project(self.dir / "bare.esx",
                       ["Generic Laptop"], ["Normal SLA (2 Mbps)"])

    def test_a_project_missing_the_profiles_is_refused_by_the_plan(self):
        plan = cap.plan_application(self._lacks_profiles(),
                                    template("Generic Wi-Fi 6E Laptop",
                                             "Normal SLA (2 Mbps)"), 100)
        self.assertFalse(plan["ok"], "the preview said this would work")
        self.assertIn("Generic Wi-Fi 6E Laptop", plan["error"])
        self.assertTrue(plan.get("missing"))

    def test_the_plan_and_the_writer_give_the_same_answer(self):
        """The invariant. A green plan followed by a refusal is the bug."""
        for build, label in ((self._has_profiles, "has them"),
                             (self._lacks_profiles, "lacks them")):
            with self.subTest(project=label):
                esx = build()
                tpl = template("Generic Wi-Fi 6E Laptop", "Normal SLA (2 Mbps)")
                plan = cap.plan_application(esx, tpl, 100)
                wrote = cap.apply_to(esx, self.dir / ("out-%s.esx" % label[:3]),
                                     tpl, 100)
                self.assertEqual(
                    bool(plan["ok"]), bool(wrote["ok"]),
                    "plan said ok=%s, writer said ok=%s" % (plan["ok"], wrote["ok"]))

    def test_a_project_that_has_them_still_plans_normally(self):
        plan = cap.plan_application(self._has_profiles(),
                                    template("Generic Wi-Fi 6E Laptop",
                                             "Normal SLA (2 Mbps)"), 100)
        self.assertTrue(plan["ok"], plan.get("error"))
        self.assertEqual(plan["willWrite"], 1)

    def test_the_probe_does_not_change_the_project(self):
        """Resolving creates profiles as a side effect, so it runs on a copy."""
        esx = self._lacks_profiles()
        before = esx.read_bytes()
        cap.plan_application(esx, template("Generic Wi-Fi 6E Laptop",
                                           "Normal SLA (2 Mbps)"), 100)
        self.assertEqual(esx.read_bytes(), before,
                         "planning wrote to the project it was only reading")

    def test_a_missing_requirement_profile_is_caught_too(self):
        plan = cap.plan_application(self._has_profiles(),
                                    template("Generic Wi-Fi 6E Laptop",
                                             "Normal SLA (2 Mbps)",
                                             requirement="No Such Requirement"), 100)
        self.assertFalse(plan["ok"])
        self.assertIn("No Such Requirement", plan["error"])

    def test_nothing_to_write_is_not_reported_as_a_profile_problem(self):
        """A project whose every floor is already done must not be blocked.

        Resolving profiles for a run that writes no areas would also leave new
        profiles behind to explain, which is why the writer returns early there.
        """
        esx = project(self.dir / "done.esx",
                      ["Generic Laptop"], ["Normal SLA (2 Mbps)"])
        with zipfile.ZipFile(esx) as z:
            members = {n: z.read(n) for n in z.namelist()}
        members["areas.json"] = json.dumps({"areas": [{
            "id": "a1", "name": "Done", "floorPlanId": "f1",
            "area": [{"x": 1.0, "y": 1.0}, {"x": 9.0, "y": 1.0},
                     {"x": 9.0, "y": 9.0}],
            "capacityItems": [{"identifier": "x", "deviceCount": 5,
                               "usageProfileId": "use-0",
                               "deviceProfileId": "dev-0"}],
        }]}).encode()
        with zipfile.ZipFile(esx, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in members.items():
                z.writestr(n, b)
        plan = cap.plan_application(esx, template("Generic Wi-Fi 6E Laptop",
                                                  "Normal SLA (2 Mbps)"), 100)
        self.assertTrue(plan["ok"], plan.get("error"))
        self.assertEqual(plan["willWrite"], 0)


class ThePageOffersTheRunThatCanHappen(unittest.TestCase):
    """A step that refuses no longer costs him the other two.

    This class used to assert the opposite - that any refusal disabled the
    button - because the pipeline abandoned the whole pass when one step could
    not run. That is exactly what he reported: "no trimming happened and no
    quick walls", when both of those had worked and were thrown away because
    the areas step could not resolve a profile name against the project.

    The steps that can run now do, and the refusal is reported beside the
    result rather than in place of it.
    """

    def setUp(self):
        self.js = PREP_JS.read_text(encoding="utf-8")
        start = self.js.index("function renderPreview(")
        self.body = self.js[start:self.js.index(chr(10) + "  function ", start + 10)]

    def test_a_refusal_no_longer_disables_the_button(self):
        self.assertNotIn("var blocked = false;", self.body)
        self.assertNotIn("blocked = true;", self.body)

    def test_a_refusal_is_collected_so_it_can_be_named(self):
        self.assertIn("refused.push(", self.body)
        self.assertGreaterEqual(self.body.count("refused.push("), 3,
                                "every 'cannot' branch has to record itself")

    def test_the_button_says_what_it_will_leave_out(self):
        self.assertIn("cannot run on this project", self.body)

    def test_a_run_with_nothing_left_to_do_is_still_refused(self):
        """Offering a pass that cannot do anything at all is the other error."""
        self.assertIn("Nothing can run on this project", self.body)

    def test_the_card_says_the_rest_still_runs(self):
        """The reader is looking at a reason and needs to know whether it costs
        the whole pass or only this part of it."""
        self.assertIn("The other steps still run", self.body)

    def test_the_result_names_what_did_not_run(self):
        """Written-but-incomplete has to read as incomplete, on the download
        path and on the write-beside-the-original path alike - the download one
        carries its report in a header, and the refusal was missing from it."""
        # It used to be asserted by counting two copies of the sentence, one
        # per renderer. There is one copy now, in `missedBlock`, and the
        # stronger claim is that every renderer goes through it - including the
        # no-change path, which had no refusal reporting at all.
        self.assertEqual(self.js.count("One part of the pass did not run"), 1)
        for fn in ("renderWritten", "renderResult", "renderNothingToDo"):
            with self.subTest(renderer=fn):
                body = self.js[self.js.index("function " + fn):]
                body = body[:body.index("\n  }\n")]
                self.assertIn("missedBlock", body,
                              f"{fn} does not report a step that declined")


if __name__ == "__main__":
    unittest.main()
