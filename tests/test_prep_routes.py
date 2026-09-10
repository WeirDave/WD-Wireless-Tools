"""The preparation endpoint, driven through Flask's test client.

Same posture as the Capacity and PlanTrim route tests: no socket, because
binding one has hung this work before and nothing here needs it.

The route is deliberately thin - it resolves two template pickers to two
templates and hands everything to the pipeline. What is worth testing here is
the seam: that the order stays the pipeline's business rather than becoming
something a query string can set, that a template that has been deleted is a
refusal rather than a silent no-op, and that nothing is written over.
"""
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import server  # noqa: E402
from tools import capacity_profiles as cap  # noqa: E402
from tools import template_store  # noqa: E402
from test_prep_pipeline import (  # noqa: E402
    TEMPLATE, Image, W, canvas_area, make_esx, wall_type)

HDR = {"X-WD-Wireless-Tools": "1"}


@unittest.skipIf(Image is None, "Pillow is required to build the fixture")
class PrepRouteTests(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        self.esx = make_esx(root / "Project.esx")
        self.bytes = self.esx.read_bytes()

        # Both stores pointed at the sandbox, so a test never reads or writes
        # the templates the person running it actually uses.
        self._cap_dir, cap.USER_DIR = cap.USER_DIR, root / "capacity"
        self._ts_user, template_store.USER_DIR = template_store.USER_DIR, root / "walls"
        self._ts_builtin, template_store.BUILTIN_DIR = (
            template_store.BUILTIN_DIR, root / "walls-builtin")
        template_store.USER_DIR.mkdir(parents=True)
        template_store.BUILTIN_DIR.mkdir(parents=True)

        server.ts.save("Prep Walls", [wall_type("Framery Pod")])
        cap.save_template(dict(TEMPLATE))
        self.cap_file = cap.list_templates()["templates"][0]["_file"]
        self.wall_file = next(t["file"] for t in server.ts.scan()["templates"])

    def tearDown(self):
        cap.USER_DIR = self._cap_dir
        template_store.USER_DIR = self._ts_user
        template_store.BUILTIN_DIR = self._ts_builtin
        self.tmp.cleanup()

    def post(self, action, query="", body=None):
        return self.client.post(f"/api/prep/{action}?{query}",
                                data=self.bytes if body is None else body,
                                headers=HDR,
                                content_type="application/octet-stream")

    def report(self, response):
        return json.loads(unquote(response.headers["X-WD-Prep-Report"]))

    # ── what the pickers are filled from ────────────────────────────────────

    def test_templates_lists_both_kinds(self):
        res = self.client.post("/api/prep/templates", headers=HDR)
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual([t["name"] for t in body["wall"]], ["Prep Walls"])
        self.assertEqual(body["wall"][0]["count"], 1)
        # The shipped examples are listed alongside the saved one, which is
        # the point of the picker - so membership, not an exact list.
        self.assertIn("Office", [t["name"] for t in body["capacity"]])

    def test_an_unknown_action_is_a_404(self):
        self.assertEqual(self.client.post("/api/prep/paint", headers=HDR,
                                          data=b"x").status_code, 404)

    # ── the preview ─────────────────────────────────────────────────────────

    def test_plan_previews_without_writing(self):
        res = self.post("plan", f"name=Project.esx&steps=trim,walls&"
                                f"wallTemplate={self.wall_file}")
        body = res.get_json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["steps"], ["trim", "walls"])
        self.assertEqual([a["name"] for a in body["step"]["walls"]["add"]],
                         ["Framery Pod"])
        self.assertEqual(self.esx.read_bytes(), self.bytes)

    def test_the_order_is_not_something_the_query_string_can_set(self):
        """The steps arrive as a set. Asking for them backwards gets them in
        the order that works, not a refusal and not the order asked for."""
        res = self.post("plan", f"steps=walls,areas,trim&"
                                f"wallTemplate={self.wall_file}&"
                                f"capacityTemplate={self.cap_file}&occupants=40")
        self.assertEqual(res.get_json()["steps"], ["trim", "areas", "walls"])

    def test_no_file_is_a_refusal(self):
        res = self.client.post("/api/prep/plan", data=b"", headers=HDR,
                               content_type="application/octet-stream")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["ok"])

    def test_a_template_that_is_gone_is_named_rather_than_ignored(self):
        for query, word in ((f"steps=walls&wallTemplate=vanished{template_store.TPL_SUFFIX}",
                             "wall template"),
                            ("steps=areas&capacityTemplate=vanished.json&occupants=40",
                             "capacity template")):
            with self.subTest(query=query):
                res = self.post("plan", query)
                self.assertEqual(res.status_code, 404)
                self.assertIn(word, res.get_json()["error"])

    # ── the run ─────────────────────────────────────────────────────────────

    def test_run_hands_back_a_prepared_archive_and_a_summary(self):
        res = self.post("run", f"name=Project.esx&steps=trim,areas,walls&"
                               f"wallTemplate={self.wall_file}&"
                               f"capacityTemplate={self.cap_file}&occupants=40")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Project (prepared).esx", res.headers["Content-Disposition"])

        summary = self.report(res)
        self.assertEqual(summary["ran"], ["trim", "areas", "walls"])
        self.assertEqual(summary["trimmed"], 1)
        self.assertEqual(summary["wallTypesAdded"], ["Framery Pod"])
        self.assertEqual(summary["areasWritten"], ["Floor 1"])

        with zipfile.ZipFile(__import__("io").BytesIO(res.data)) as z:
            floor = json.loads(z.read("floorPlans.json"))["floorPlans"][0]
            self.assertLess(floor["width"], W, "the returned project was not trimmed")
            self.assertEqual(len(json.loads(z.read("areas.json"))["areas"]), 1)

    def test_the_summary_stays_inside_what_a_header_can_carry(self):
        """A truncated header is a page that silently renders nothing."""
        res = self.post("run", f"steps=trim,areas,walls&"
                               f"wallTemplate={self.wall_file}&"
                               f"capacityTemplate={self.cap_file}&occupants=40")
        self.assertLess(len(res.headers["X-WD-Prep-Report"]), 4096)

    def test_the_project_on_disk_is_never_written_to(self):
        self.post("run", f"steps=trim,areas,walls&wallTemplate={self.wall_file}&"
                         f"capacityTemplate={self.cap_file}&occupants=40")
        self.assertEqual(self.esx.read_bytes(), self.bytes)
        self.assertEqual([p.name for p in self.esx.parent.iterdir()
                          if p.suffix == ".esx"], ["Project.esx"],
                         "the route left a backup or a copy behind")

    def test_an_already_prepared_project_comes_back_as_a_message_not_a_file(self):
        first = self.post("run", f"steps=trim,walls&wallTemplate={self.wall_file}")
        self.assertEqual(first.status_code, 200)

        again = self.client.post(
            f"/api/prep/run?steps=trim,walls&wallTemplate={self.wall_file}",
            data=first.data, headers=HDR, content_type="application/octet-stream")
        body = again.get_json()
        self.assertTrue(body["ok"], body)
        self.assertFalse(body["written"])
        self.assertIn("already prepared", body["note"])

    def test_a_step_with_no_template_is_refused_before_anything_runs(self):
        res = self.post("run", "steps=walls")
        self.assertEqual(res.status_code, 400)
        self.assertIn("wall template", res.get_json()["error"])

    def test_retighten_can_be_turned_off(self):
        esx = make_esx(Path(self.tmp.name) / "Again.esx", walls=True,
                       areas=[canvas_area()])
        blob = esx.read_bytes()
        res = self.post("plan", f"steps=areas&capacityTemplate={self.cap_file}&"
                                f"occupants=40&retighten=0", body=blob)
        self.assertNotIn("retighten", res.get_json()["step"]["areas"])

        res = self.post("plan", f"steps=areas&capacityTemplate={self.cap_file}&"
                                f"occupants=40", body=blob)
        self.assertEqual(
            [r["newBasis"] for r in res.get_json()["step"]["areas"]["retighten"]],
            ["walls"])


if __name__ == "__main__":
    unittest.main()
