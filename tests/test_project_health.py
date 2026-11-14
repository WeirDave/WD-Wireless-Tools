"""Project Preflight reads a project and ranks what is wrong with it.

The fixture is built here, synthetic, and deliberately imperfect: two floors,
a duplicated name, a generic name, an AP with no model, one on no floor, one
with an unset mount height and a directional antenna with no bearing, a wall
type whose name states a height the file does not carry, and a survey record
whose samples are not in the archive. A clean project passes everything and
proves nothing, so there is a clean one too, to show the check can say "fine".
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import project_health

ROOT = Path(__file__).resolve().parent.parent


def _esx(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, body if isinstance(body, (bytes, str))
                       else json.dumps(body))
    return buf.getvalue()


def _ap(i, name, model="Model A", floor="f1"):
    return {"id": f"ap{i}", "name": name, "model": model,
            "location": {"floorPlanId": floor} if floor else {}}


def _radio(i, height=3.0, direction=None, antenna="omni", **extra):
    r = {"id": f"r{i}", "accessPointId": f"ap{i}", "antennaHeight": height,
         "antennaTypeId": antenna, "enabled": True}
    if direction is not None:
        r["antennaDirection"] = direction
    r.update(extra)
    return r


COMMON = {
    "floorPlans.json": {"floorPlans": [{"id": "f1", "name": "Ground"},
                                       {"id": "f2", "name": "Upper"}]},
    "antennaTypes.json": {"antennaTypes": [
        {"id": "omni", "name": "Ceiling omni"},
        {"id": "dir", "name": "Panel 90", "directional": True}]},
}


def imperfect() -> bytes:
    aps = [
        _ap(1, "Lobby AP"), _ap(2, "lobby ap "),            # one name twice
        _ap(3, "AP12"),                                     # generic
        _ap(4, "Atrium North", model=""),                   # no model
        _ap(5, "Dock East", floor="gone"),                  # on no floor plan
        _ap(6, "Hall West"),                                # height + bearing
        _ap(7, "Clean One"),
    ]
    radios = [_radio(i) for i in (1, 2, 3, 4, 5, 7)]
    radios.append(_radio(6, height=0.2, antenna="dir"))
    return _esx({
        **COMMON,
        "accessPoints.json": {"accessPoints": aps},
        "simulatedRadios.json": {"simulatedRadios": radios},
        "wallTypes.json": {"wallTypes": [
            {"id": "w1", "name": "Warehouse Rack Wall - 16ft", "thickness": 0.1},
            {"id": "w2", "name": "Drywall", "thickness": 0.1}]},
        "wallSegments.json": {"wallSegments": [
            {"wallTypeId": "w1"}, {"wallTypeId": "w1"}, {"wallTypeId": "w2"}]},
        "survey-s1.json": {"surveys": [{
            "id": "s1", "wifiTracks": [{"binaryFileId": "b1"}]}]},
    })


def clean() -> bytes:
    return _esx({
        **COMMON,
        "accessPoints.json": {"accessPoints": [
            _ap(1, "Lobby North"), _ap(2, "Lobby South", floor="f2")]},
        "simulatedRadios.json": {"simulatedRadios": [_radio(1), _radio(2)]},
        "wallTypes.json": {"wallTypes": [
            {"id": "w2", "name": "Drywall", "thickness": 0.1}]},
        "wallSegments.json": {"wallSegments": [{"wallTypeId": "w2"}]},
    })


def by_id(result):
    return {f["id"]: f for f in result["findings"]}


class TheCheckFindsWhatIsWrong(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.result = project_health.check_bytes(imperfect())
        cls.f = by_id(cls.result)

    def test_it_reads_the_project(self):
        self.assertTrue(self.result["ok"], self.result)
        self.assertEqual(7, self.result["accessPoints"])
        self.assertEqual(2, self.result["floors"])
        self.assertFalse(self.result["clean"])

    def test_names_that_differ_only_in_case_and_space_are_one_name(self):
        self.assertEqual(2, self.f["dupName"]["count"])
        self.assertEqual("fix", self.f["dupName"]["severity"])

    def test_a_generic_name_is_found_and_a_real_one_is_not(self):
        g = self.f["genericName"]
        self.assertEqual(1, g["count"])
        self.assertEqual(["AP12"], g["examples"])

    def test_no_model_no_floor_and_no_height_each_find_their_access_point(self):
        self.assertEqual(["Atrium North"], self.f["noModel"]["examples"])
        self.assertEqual(["Dock East"], self.f["noFloor"]["examples"])
        self.assertEqual(["Hall West"], self.f["noHeight"]["examples"])

    def test_a_directional_antenna_without_a_bearing_is_a_fix(self):
        a = self.f["noAzimuth"]
        self.assertEqual(["Hall West"], a["examples"])
        self.assertEqual("fix", a["severity"])

    def test_a_wall_type_naming_a_height_it_does_not_have_is_found(self):
        w = self.f["wallHeight"]
        self.assertEqual(["Warehouse Rack Wall - 16ft"], w["examples"])
        self.assertEqual("/walls", w["tool"]["href"])

    def test_a_survey_whose_samples_are_not_in_the_file_is_a_fix(self):
        s = self.f["surveyGaps"]
        self.assertEqual("fix", s["severity"])
        self.assertEqual(1, s["count"], "one track is named and not in the file")
        self.assertEqual("/cloud", s["tool"]["href"])

    def test_every_finding_says_where_it_is_fixed(self):
        for f in self.result["findings"]:
            self.assertTrue(f["tool"] or f["fixIn"],
                            f"{f['id']} names no tool and no place to fix it")
            if f["tool"]:
                self.assertTrue(f["tool"]["href"].startswith("/"), f)

    def test_fixes_come_before_checks(self):
        ranks = [project_health.SEVERITY_ORDER[f["severity"]]
                 for f in self.result["findings"]]
        self.assertEqual(sorted(ranks), ranks)

    def test_the_summary_counts_findings_by_severity(self):
        s = self.result["summary"]
        self.assertEqual(len(self.result["findings"]), sum(s.values()))
        self.assertGreater(s["fix"], 0)
        self.assertGreater(s["check"], 0)

    def test_examples_are_capped_but_the_count_is_not(self):
        aps = [_ap(i, f"Room {i}", model="") for i in range(1, 13)]
        r = project_health.check_bytes(_esx({
            **COMMON, "accessPoints.json": {"accessPoints": aps},
            "simulatedRadios.json": {"simulatedRadios": [_radio(i) for i in range(1, 13)]}}))
        f = by_id(r)["noModel"]
        self.assertEqual(12, f["count"])
        self.assertEqual(project_health.EXAMPLES, len(f["examples"]))


class TheCheckCanSayFine(unittest.TestCase):

    def test_a_clean_project_has_no_findings(self):
        r = project_health.check_bytes(clean())
        self.assertTrue(r["ok"])
        self.assertTrue(r["clean"], r["findings"])
        self.assertEqual({"fix": 0, "check": 0, "note": 0}, r["summary"])

    def test_a_project_with_no_surveys_is_not_missing_survey_data(self):
        self.assertNotIn("surveyGaps", by_id(project_health.check_bytes(clean())))

    def test_an_auto_height_wall_alone_is_not_a_finding(self):
        # Auto is the shipped default and a deliberate choice, not a defect.
        r = project_health.check_bytes(_esx({
            **COMMON,
            "wallTypes.json": {"wallTypes": [{"id": "w", "name": "Shelf, Warehouse"}]},
            "wallSegments.json": {"wallSegments": [{"wallTypeId": "w"}]}}))
        self.assertNotIn("wallHeight", by_id(r))

    def test_a_radio_that_is_off_or_not_wifi_does_not_need_a_height(self):
        r = project_health.check_bytes(_esx({
            **COMMON,
            "accessPoints.json": {"accessPoints": [_ap(1, "Lobby North"), _ap(2, "Lobby South")]},
            "simulatedRadios.json": {"simulatedRadios": [
                _radio(1, height=0.0, enabled=False),
                _radio(2, height=0.0, radioTechnology="BLUETOOTH")]}}))
        self.assertNotIn("noHeight", by_id(r))


class TheCheckReadsAnOpenArchive(unittest.TestCase):

    def test_check_zip_is_what_the_path_and_bytes_forms_both_run(self):
        import io as _io
        with zipfile.ZipFile(_io.BytesIO(imperfect())) as zf:
            direct = project_health.check_zip(zf)
        self.assertEqual(direct, project_health.check_bytes(imperfect()))


class TheCheckRefusesToGuess(unittest.TestCase):

    def test_something_that_is_not_a_zip_is_an_error_not_a_clean_bill(self):
        r = project_health.check_bytes(b"this is not an archive")
        self.assertFalse(r["ok"])
        self.assertIn("error", r)
        self.assertNotIn("clean", r)

    def test_a_missing_file_is_an_error(self):
        r = project_health.check_path(ROOT / "no-such-project.esx")
        self.assertFalse(r["ok"])

    def test_a_member_that_is_not_json_is_skipped_not_fatal(self):
        r = project_health.check_bytes(_esx({
            **COMMON, "accessPoints.json": "{ not json",
            "simulatedRadios.json": {"simulatedRadios": []}}))
        self.assertTrue(r["ok"])
        self.assertEqual(0, r["accessPoints"])

    def test_it_writes_nothing(self):
        d = Path(tempfile.mkdtemp(prefix="wd-health-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = d / "project.esx"
        p.write_bytes(imperfect())
        before = (p.read_bytes(), p.stat().st_mtime_ns, sorted(os.listdir(d)))
        project_health.check_path(p)
        self.assertEqual(before, (p.read_bytes(), p.stat().st_mtime_ns,
                                  sorted(os.listdir(d))))


NAMES = ["", "  ", "AP", "AP12", "ap-03", "AP #5", "AP_5", "Simulated AP-001",
         "Measured AP 4", "simulated   ap", "Access Point", "Access Point 7",
         "00:11:22:33:44:55", "aa-bb-cc-dd-ee-ff", "0011.2233.4455",
         "Lobby AP", "AP12 Lobby", "Rack AP-1", "Lobby North", "Hall West 2"]


@unittest.skipUnless(shutil.which("node"), "Report's own rule is run with Node")
class TheNameRuleMatchesReport(unittest.TestCase):
    """Report's `drGenericName` and this module's `generic_name` are one rule in
    two languages. Run the real JavaScript over the same names."""

    def test_the_two_agree_on_every_name(self):
        src = (ROOT / "web/assets/js/report.js").read_text(encoding="utf-8")
        a = src.index("  function drGenericName(name) {")
        self.assertGreaterEqual(a, 0, "drGenericName moved")
        b, depth, seen = a, 0, False
        while b < len(src) and not (seen and depth == 0):
            if src[b] == "{":
                depth += 1
                seen = True
            elif src[b] == "}":
                depth -= 1
            b += 1
        probe = (src[a:b] + "\nconst names = " + json.dumps(NAMES)
                 + ";\nconsole.log(JSON.stringify(names.map(drGenericName)));")
        r = subprocess.run(["node", "-e", probe], capture_output=True,
                           encoding="utf-8", timeout=30)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        js = json.loads(r.stdout)
        py = [project_health.generic_name(n) for n in NAMES]
        self.assertEqual(js, py)
        self.assertTrue(any(js), "the probe found nothing generic - it proves nothing")
        self.assertTrue(any(not x for x in js))


if __name__ == "__main__":
    unittest.main()
