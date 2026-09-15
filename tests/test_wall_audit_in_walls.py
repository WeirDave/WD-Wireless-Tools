"""The wall audit, reached from inside Quick Walls.

It used to be a module with no route and no interface: it found real problems
in real jobs and there was no way to run it. It now lives with the wall-type
list, which is where the fix is made - a height is a property of the type, so
the tool that edits types is the tool that should be reporting this.

The rule itself stays in tools/wall_audit.py and is reached over
/api/walls/audit. That is deliberate. A wall-type rule written twice in this
codebase once had the Report printing a hex colour where the Labeler printed a
name, and only one of the two ever got fixed.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from server import API_REQUEST_HEADER, app
from tools import wall_audit

ROOT = Path(__file__).resolve().parent.parent
WALLS_JS = ROOT / "web" / "assets" / "js" / "walls.js"
WALLS_HTML = ROOT / "web" / "walls.html"


def shelf(**over):
    """A type whose name states a height - the only shape that is a finding."""
    w = {"id": "shelf-1", "name": "Rack Wall - 16ft", "thickness": 1.5,
         "propagationProperties": [
             {"band": "FIVE", "attenuationFactor": 18.0}]}
    w.update(over)
    return w


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def post(self, payload):
        r = self.client.post("/api/walls/audit", json=payload,
                             headers={API_REQUEST_HEADER: "1"})
        try:
            return r.status_code, r.get_json()
        finally:
            r.close()

    def test_it_reports_a_name_stating_a_height_the_file_lacks(self):
        code, body = self.post({
            "wallTypes": [shelf()],
            "segmentCounts": {"shelf-1": 52},
        })
        self.assertEqual(code, 200)
        self.assertEqual(len(body["findings"]), 1)
        f = body["findings"][0]
        self.assertEqual(f["wallType"], "Rack Wall - 16ft")
        self.assertEqual(f["segments"], 52)
        self.assertEqual(f["wallTypeId"], "shelf-1")
        self.assertTrue(f["suggestedFt"], "a finding with no suggestion is not actionable")

    def test_a_type_that_already_has_a_height_is_not_reported(self):
        code, body = self.post({
            "wallTypes": [shelf(upperEdge=10.0)],
            "segmentCounts": {"shelf-1": 52},
        })
        self.assertEqual(body["findings"], [])

    def test_a_type_nobody_has_drawn_with_is_not_reported(self):
        """The list is about what is on the plan, not what the project could
        draw. Reporting unused types would bury the ones that matter."""
        code, body = self.post({"wallTypes": [shelf()], "segmentCounts": {}})
        self.assertEqual(body["findings"], [])

    def test_a_name_that_states_no_height_is_not_reported(self):
        code, body = self.post({
            "wallTypes": [{"id": "w", "name": "Concrete", "thickness": 0.2}],
            "segmentCounts": {"w": 40},
        })
        self.assertEqual(body["findings"], [])

    def test_the_tally_and_the_raw_segments_agree(self):
        """The editor sends a tally because it has already counted; the folder
        sweep sends segments. Both must reach the same verdict."""
        by_tally = self.post({"wallTypes": [shelf()],
                              "segmentCounts": {"shelf-1": 3}})[1]["findings"]
        by_segments = self.post({
            "wallTypes": [shelf()],
            "wallSegments": [{"wallTypeId": "shelf-1"}] * 3})[1]["findings"]
        self.assertEqual(by_tally, by_segments)

    def test_nonsense_does_not_500(self):
        for payload in ({}, {"wallTypes": None}, {"wallTypes": [{}]},
                        {"wallTypes": [shelf()], "segmentCounts": {"nope": 5}}):
            with self.subTest(payload=payload):
                code, body = self.post(payload)
                self.assertEqual(code, 200)
                self.assertIn("findings", body)


class OneImplementationTests(unittest.TestCase):
    def test_the_editor_does_not_reimplement_the_rule(self):
        """If the name list or the height table appears in walls.js, there are
        two rules and they will drift."""
        js = WALLS_JS.read_text(encoding="utf-8")
        self.assertIn("/api/walls/audit", js)
        for token in ("cubicle", "bookshelf", "PARTIAL_HEIGHT"):
            self.assertNotIn(token, js,
                             f"the audit rule is leaking into the page ({token})")

    def test_the_folder_sweep_and_the_editor_share_a_function(self):
        src = (ROOT / "tools" / "wall_audit.py").read_text(encoding="utf-8")
        self.assertIn("def audit_members", src)
        body = src[src.index("def audit_project"):src.index("def audit_members")]
        self.assertIn("audit_members", body,
                      "audit_project must go through the shared seam, not copy it")


class AutoIsNeverTheFindingTests(unittest.TestCase):
    """Auto is the correct default, so it is never what gets reported.

    Two corrections got this here. First: racking that really does run to the
    deck should be modelled floor to ceiling, exactly as Ekahau intends, so a
    type on Auto is not a defect. Then, when the panel still asked about it:
    Ekahau *ships* "Shelf, Warehouse" on Auto, so a freshly imported project was
    queried on the way in about a state nobody had chosen. In his words - "if
    we're importing a new ESX file then by default they have the warehouse shelf
    being Auto... Why are we asking about that off the beginning?"

    What is left is the contradiction: a name stating a height the file does not
    carry. Noise trains someone to click past prompts that might one day matter,
    so the bar for showing one at all is a disagreement in the data.
    """

    def test_the_panel_says_auto_is_fine(self):
        """It must not read as though Auto is the problem - that is the state
        Ekahau ships and the one he expects."""
        js = WALLS_JS.read_text(encoding="utf-8")
        body = js[js.index("function renderWallAudit"):]
        body = body[:body.index("function dismissAuditFinding")]
        self.assertIn("Auto is the default and is usually right", body)
        self.assertIn("name", body, "it should say what actually disagrees")
        for verdict in ("should not", "wrong", "mistake", "incorrect"):
            self.assertNotIn(verdict, body,
                             f"the panel calls a legitimate model {verdict!r}")

    def test_leave_as_is_leaves_the_type_alone(self):
        """Dismissing writes nothing: Auto is already what the file says, and
        the name is his to keep or rename."""
        js = WALLS_JS.read_text(encoding="utf-8")
        body = js[js.index("function dismissAuditFinding"):]
        body = body[:body.index("// Applying the suggestion")]
        self.assertNotIn("upperEdge", body,
                         "saying it reaches must not set a height")
        self.assertIn("_auditAccepted", body)

    def test_a_dismissal_does_not_follow_him_to_another_project(self):
        js = WALLS_JS.read_text(encoding="utf-8")
        self.assertIn("_auditAccepted = new Set();", js)
        load = js[js.index("esxZip = await JSZip.loadAsync"):]
        self.assertIn("_auditAccepted = new Set();", load[:200],
                      "opening another project has to ask again")


class PanelTests(unittest.TestCase):
    """The panel is only useful if it is next to the thing it is about and its
    buttons call functions that exist."""

    def test_the_panel_sits_with_the_wall_list(self):
        html = WALLS_HTML.read_text(encoding="utf-8")
        self.assertIn('id="wallAudit"', html)
        self.assertLess(html.index('id="wallAudit"'), html.index('id="wallList"'),
                        "the finding belongs above the list it refers to")

    def test_every_function_the_panel_calls_exists(self):
        """A button wired to a name that does not exist renders fine and does
        nothing - this repo has shipped that more than once."""
        js = WALLS_JS.read_text(encoding="utf-8")
        panel = js[js.index("function renderWallAudit"):]
        panel = panel[:panel.index("\nfunction renderAll")]
        called = set(re.findall(r'onclick="([A-Za-z_$][\w$]*)\(', panel))
        self.assertTrue(called, "the panel should offer at least one action")
        for name in called:
            self.assertRegex(
                js, r"\bfunction\s+" + re.escape(name) + r"\s*\(",
                f"the panel calls {name}(), which is not defined in walls.js")

    def test_the_fix_writes_the_same_field_the_editor_writes(self):
        js = WALLS_JS.read_text(encoding="utf-8")
        body = js[js.index("function applyAuditHeight"):]
        body = body[:body.index("\nfunction renderAll")]
        self.assertIn("upperEdge", body)
        self.assertIn("lowerEdge", body)
        self.assertNotIn("fetch(", body, "applying a height writes nothing to disk")

    def test_a_failed_check_does_not_block_the_editor(self):
        """The audit is an opinion about the project. If the call fails the
        wall list still has to work."""
        js = WALLS_JS.read_text(encoding="utf-8")
        body = js[js.index("async function refreshWallAudit"):]
        body = body[:body.index("\nfunction renderWallAudit")]
        self.assertIn("catch", body)


if __name__ == "__main__":
    unittest.main()
