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


@unittest.skipIf(Image is None, "Pillow is required to build the fixture")
class OpenedFromDisk(unittest.TestCase):
    """The picker path, where nothing is uploaded.

    A dropped file has no filesystem path, so the whole archive has to travel
    for the preview and again for the run - and his projects run to a couple of
    hundred megabytes. Opened through the picker the server reads the file where
    it lies and writes the prepared copy back beside it, which is also the
    folder he is about to reopen in Ekahau.

    The path lives on the server and only there: no action here accepts one from
    the browser.
    """

    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.esx = make_esx(root / "Carnation Farms.esx")
        self.before = self.esx.read_bytes()

        self._cap_dir, cap.USER_DIR = cap.USER_DIR, root / "capacity"
        self._ts_user, template_store.USER_DIR = template_store.USER_DIR, root / "walls"
        self._ts_builtin, template_store.BUILTIN_DIR = (
            template_store.BUILTIN_DIR, root / "walls-builtin")
        template_store.USER_DIR.mkdir(parents=True)
        template_store.BUILTIN_DIR.mkdir(parents=True)
        server.ts.save("Prep Walls", [wall_type("Framery Pod")])
        self.wall_file = next(t["file"] for t in server.ts.scan()["templates"])

        self._picked = dict(server._PREP_PROJECT)
        server._PREP_PROJECT["path"] = str(self.esx)
        server._PREP_PROJECT["written"] = None

    def tearDown(self):
        server._PREP_PROJECT.update(self._picked)
        cap.USER_DIR = self._cap_dir
        template_store.USER_DIR = self._ts_user
        template_store.BUILTIN_DIR = self._ts_builtin
        self.tmp.cleanup()

    def post(self, action, query=""):
        """Note the empty body - that is the point of this path."""
        return self.client.post(f"/api/prep/{action}?source=disk&{query}",
                                data=b"", headers=HDR,
                                content_type="application/octet-stream")

    def test_it_previews_without_the_archive_being_uploaded(self):
        res = self.post("plan", f"steps=trim,walls&wallTemplate={self.wall_file}")
        body = res.get_json()
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["fromDisk"])
        self.assertEqual(body["step"]["trim"]["trimmedCount"], 1)

    def test_it_names_the_project_from_the_path_not_the_query(self):
        res = self.post("plan", f"name=wrong.esx&steps=walls&wallTemplate={self.wall_file}")
        self.assertEqual(res.get_json()["source"], "Carnation Farms.esx")

    def test_the_prepared_copy_lands_beside_the_original(self):
        res = self.post("run", f"steps=trim,walls&wallTemplate={self.wall_file}")
        body = res.get_json()
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["written"])
        self.assertEqual(body["filename"], "Carnation Farms (prepared).esx")
        self.assertEqual(Path(body["dir"]), self.esx.parent)
        self.assertTrue(Path(body["path"]).is_file())
        # no archive in the response - the file is already where he wants it
        self.assertNotIn("X-WD-Prep-Report", res.headers)
        self.assertLess(len(res.data), 4096)

    def test_the_original_is_not_touched(self):
        self.post("run", f"steps=trim,walls&wallTemplate={self.wall_file}")
        self.assertEqual(self.esx.read_bytes(), self.before)

    def test_a_second_run_will_not_overwrite_the_prepared_file_unasked(self):
        """The hazard this guard exists for.

        A second run re-derives everything from the original, which is untouched
        and therefore still has all the work to do - so it would write the
        prepared file again. By then that may be the file he opened in Ekahau
        and has been drawing in. Nothing in the archive distinguishes "output I
        made" from "output I have since worked in", so he is asked.
        """
        self.post("run", f"steps=trim,walls&wallTemplate={self.wall_file}")
        prepared = self.esx.with_name("Carnation Farms (prepared).esx")
        self.assertTrue(prepared.is_file())
        prepared.write_bytes(b"an hour of drawing")   # stand in for his work

        again = self.post("run", f"steps=trim,walls&wallTemplate={self.wall_file}")
        self.assertEqual(again.status_code, 409)
        body = again.get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "exists")
        self.assertEqual(body["filename"], "Carnation Farms (prepared).esx")
        self.assertIn("overwrite that work", body["error"])
        self.assertEqual(prepared.read_bytes(), b"an hour of drawing")

    def test_replacing_is_possible_once_it_is_asked_for(self):
        self.post("run", f"steps=trim,walls&wallTemplate={self.wall_file}")
        prepared = self.esx.with_name("Carnation Farms (prepared).esx")
        prepared.write_bytes(b"stale")
        again = self.post("run", f"steps=trim,walls&replace=1&wallTemplate={self.wall_file}")
        body = again.get_json()
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["written"])
        self.assertNotEqual(prepared.read_bytes(), b"stale")
        self.assertEqual(sorted(q.name for q in self.esx.parent.glob("*.esx")),
                         ["Carnation Farms (prepared).esx", "Carnation Farms.esx"],
                         "preparing again piled up another copy")

    def test_a_project_that_has_moved_is_refused_rather_than_guessed_at(self):
        self.esx.unlink()
        res = self.post("plan", f"steps=walls&wallTemplate={self.wall_file}")
        self.assertEqual(res.status_code, 404)
        self.assertIn("Open it again", res.get_json()["error"])

    def test_reveal_takes_no_path_from_the_browser(self):
        """The one rule that keeps a localhost tool from shelling out on
        whatever a page hands it."""
        import inspect
        src = inspect.getsource(server.api_prep)
        marker = src[src.index('if action == "reveal"'):]
        marker = marker[:marker.index("if action ==", 10)]
        self.assertNotIn("request.args", marker)
        self.assertNotIn("request.get_json", marker)
        self.assertIn("_PREP_PROJECT", marker)

    def test_forget_clears_what_the_server_remembers(self):
        self.client.post("/api/prep/forget", headers=HDR, json={})
        self.assertIsNone(server._PREP_PROJECT["path"])
        res = self.post("plan", f"steps=walls&wallTemplate={self.wall_file}")
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
