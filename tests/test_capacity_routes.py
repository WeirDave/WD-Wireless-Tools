"""The Capacity endpoints, driven through Flask's test client.

Deliberately not through a real server on a port: binding one is a step that has
hung this work before, and nothing here needs a socket to be exercised.
"""
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import server  # noqa: E402
from tools import capacity_profiles as cap  # noqa: E402
from test_capacity_profiles import build_esx  # noqa: E402

HDR = {"X-WD-Wireless-Tools": "1"}


class CapacityRouteTests(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.esx = build_esx(Path(self.tmp.name) / "src.esx")
        self.bytes = Path(self.esx).read_bytes()
        self._orig_dir = cap.USER_DIR
        cap.USER_DIR = Path(self.tmp.name) / "capacity"

    def tearDown(self):
        cap.USER_DIR = self._orig_dir
        self.tmp.cleanup()

    def _post(self, action, data=None, query="", json_body=None):
        if json_body is not None:
            return self.client.post("/api/capacity/" + action + query,
                                    json=json_body, headers=HDR)
        return self.client.post("/api/capacity/" + action + query,
                                data=data, headers=HDR)

    def test_the_page_is_served(self):
        r = self.client.get("/capacity")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"WD Capacity", r.data)

    def test_analyze_reads_the_uploaded_project(self):
        r = self._post("analyze", self.bytes, "?name=src.esx")
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["totalDevices"], 1500)
        self.assertEqual(len(body["rows"]), 6)

    def test_analyze_without_a_file_is_refused(self):
        r = self._post("analyze", b"", "?name=x.esx")
        self.assertEqual(r.status_code, 400)

    def test_derive_returns_per_person_ratios(self):
        got = self._post("analyze", self.bytes, "?name=src.esx").get_json()
        r = self._post("derive", json_body={"extracted": got, "occupants": 500,
                                            "name": "Office"}).get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["devicesPerOccupant"], 3.0)

    def test_save_then_list_then_plan(self):
        got = self._post("analyze", self.bytes, "?name=src.esx").get_json()
        tpl = self._post("derive", json_body={"extracted": got, "occupants": 500,
                                              "name": "Office"}).get_json()
        saved = self._post("save", json_body={"template": tpl}).get_json()
        self.assertTrue(saved["ok"])

        listed = self._post("templates", json_body={}).get_json()
        mine = [t for t in listed["templates"] if t["name"] == "Office"]
        self.assertEqual(len(mine), 1)

        plan = self._post("plan", self.bytes,
                          "?name=src.esx&template=%s&occupants=200&replace=0"
                          % mine[0]["_file"]).get_json()
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["totalDevices"], 600)

    def test_plan_against_a_template_that_is_gone_says_so(self):
        r = self._post("plan", self.bytes,
                       "?name=src.esx&template=nope_capacitytemplate.json&occupants=200")
        self.assertEqual(r.status_code, 404)
        self.assertIn("no longer", r.get_json()["error"])

    def test_an_unknown_action_is_a_404_not_a_crash(self):
        r = self._post("wat", json_body={})
        self.assertEqual(r.status_code, 404)

    def test_nothing_is_written_to_the_uploaded_project(self):
        before = Path(self.esx).read_bytes()
        got = self._post("analyze", self.bytes, "?name=src.esx").get_json()
        tpl = self._post("derive", json_body={"extracted": got, "occupants": 500,
                                              "name": "Office"}).get_json()
        saved = self._post("save", json_body={"template": tpl}).get_json()
        self._post("plan", self.bytes,
                   "?name=src.esx&template=%s&occupants=200&replace=1" % saved["file"])
        # Preview must stay a preview - the whole safety posture rests on it.
        self.assertEqual(Path(self.esx).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
