"""The Rename page could never save anything, on either half of the mistake.

`doRename()` posted `/api/settings/set` with `{settings: {rename: {...}}}`.

There is no `set` action. `SETTINGS_ACTIONS` in server.py is get / update /
needs_setup / complete_setup / reset_setup / get_destinations, so every call
came back **404 "unknown action: set"**. And the envelope was wrong as well:
`update` reads `d["patch"]`, never `d["settings"]`.

Those are the two bugs the settings registry already has tests for - "every
settings/update sends a patch envelope" exists because the Report page posted
`{report: {...}}` and saved nothing while reporting success. This is the same
pair, on the one page the registry names as `rename.`'s home.

Nothing noticed for two reasons. The reply was never read - it was a bare
`await fetch(...)` with no check - and the rename on the very next line went
ahead regardless, so the files were renamed correctly every time. Only the
settings were gone, and the page *reads* them back on arrival, which is exactly
what makes a page look like it remembers.

Measured before the fix, against the running server:

    settings/set   -> 404 {"error": "unknown action: set"}, file_rules unchanged
    settings/update -> 200 ok, file_rules.case == "upper" on the next get

And after, in Firefox: typing a strip-prefix, saving, then loading the page
fresh brings it back.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENAME_JS = ROOT / "web" / "assets" / "js" / "rename.js"
SERVER = ROOT / "server.py"
REGISTRY = ROOT / "web" / "assets" / "settings-registry.json"


class TheWriteGoesToAnEndpointThatExists(unittest.TestCase):

    def setUp(self):
        self.src = RENAME_JS.read_text(encoding="utf-8")
        self.code = re.sub(r"/\*.*?\*/", "", self.src, flags=re.S)
        self.code = re.sub(r"^\s*//.*$", "", self.code, flags=re.M)

    def test_settings_set_is_gone(self):
        self.assertNotIn("settings/set", self.code)

    def test_it_uses_update(self):
        self.assertIn("settings/update", self.code)

    def test_it_sends_a_patch_envelope(self):
        """`update` reads d["patch"]. A `settings` key saves nothing and still
        reports success, which is how the Report page lost its orientation."""
        self.assertIn("{ patch: { rename:", self.code)
        self.assertNotIn("{ settings: { rename:", self.code)

    def test_the_action_really_is_one_the_server_has(self):
        actions = SERVER.read_text(encoding="utf-8")
        block = actions[actions.index("SETTINGS_ACTIONS = {"):]
        block = block[:block.index("\n}")]
        available = set(re.findall(r'^\s*"([a-z_]+)":', block, re.M))
        used = set(re.findall(r"settings/([a-z_]+)", self.code))
        self.assertTrue(used, "the page should still be saving something")
        for action in used:
            with self.subTest(action=action):
                self.assertIn(action, available)


class TheReplyIsRead(unittest.TestCase):
    """A bare `await fetch(...)` is why a 404 went unnoticed through however
    many releases. If the save fails now it says so."""

    def setUp(self):
        src = RENAME_JS.read_text(encoding="utf-8")
        body = src[src.index("async function doRename()"):]
        self.body = body[:body.index("async function renameUndo")]

    def test_the_result_is_checked(self):
        self.assertIn("if (!res || !res.ok)", self.body)

    def test_a_failure_is_reported_and_distinguishes_itself_from_the_rename(self):
        """The rename still happens; only the remembering failed. Saying
        "rename failed" would be false."""
        self.assertIn("Renamed, but your rename settings could not be saved",
                      self.body)

    def test_the_rename_still_runs_even_if_saving_fails(self):
        """Losing a preference must not cost him the operation he asked for."""
        save_at = self.body.index("await remember(")
        run_at = self.body.index("execute_bulk_rename")
        self.assertLess(save_at, run_at)
        self.assertNotIn("return;", self.body[save_at:run_at])


class EverythingThePageLoadsIsAlsoSaved(unittest.TestCase):
    """Three values are read from settings on arrival. A value that is loaded
    and never written is a control that silently forgets, and the load is what
    makes it look like it does not."""

    def setUp(self):
        self.src = RENAME_JS.read_text(encoding="utf-8")

    def test_the_three_loaded_keys_are_all_written_somewhere(self):
        head = self.src[:self.src.index("async function doRename()")]
        loaded = set(re.findall(r"rnSettings\.([a-z_]+)", head))
        loaded |= {"file_rules"} if "rnSettings.file_rules" in head or \
            "rnSettings" in head and "file_rules" in head else set()
        self.assertIn("folder_format", loaded)
        self.assertIn("file_format", loaded)
        body = self.src[self.src.index("async function doRename()"):]
        for key in ("folder_format", "file_format", "file_rules"):
            with self.subTest(key=key):
                self.assertIn(key, body,
                              f"{key} is read on arrival and never written")

    def test_the_registry_says_this_page_is_where_they_live(self):
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        entry = next(e for e in reg["settings"]
                     if e.get("key_prefix") == "rename.")
        self.assertEqual(entry["category"], "preference")
        self.assertEqual(entry["home"], "rename-page")

    def test_they_are_saved_on_the_action_not_on_every_keystroke(self):
        """A write per character would hammer the settings file for a value
        that only matters when a rename is actually run."""
        self.assertNotIn("oninput=\"saveRenameSettings", self.src)
        body = self.src[self.src.index("async function doRename()"):]
        self.assertEqual(body.count("await remember("), 2)


if __name__ == "__main__":
    unittest.main()
