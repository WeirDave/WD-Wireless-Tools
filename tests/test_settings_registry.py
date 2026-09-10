"""The rule about where a setting is allowed to live, enforced.

`web/assets/settings-registry.json` names every user-configurable setting in
the suite, which of the three categories it belongs to, and therefore which
store may hold it. These tests are what make that file the rule rather than a
description of it.

Two of them would each have caught a bug that shipped:

  * "no setting lives in two stores" is the merge rule and refresh interval,
    which sat in localStorage while the Suite Settings page read and wrote the
    same values in settings.json. The page showed a value that was not in
    force and saving there did nothing.
  * "every settings/update sends a patch envelope" is report page orientation,
    which posted `{report: {...}}` where the server reads `d["patch"]`. The
    call succeeded, merged an empty dict, and silently saved nothing.

The other two stop a setting being added with no way to reach it (which is how
`walls.reveal_source_after_save` ended up editable only by hand) and stop a
control being wired to a key nobody declared.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "web" / "assets" / "settings-registry.json"
SETTINGS_HTML = ROOT / "web" / "settings.html"
JS_DIR = ROOT / "web" / "assets" / "js"

REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
ENTRIES = REGISTRY["settings"]


def _flatten(node, prefix=""):
    """Every leaf key in DEFAULTS as a dotted path."""
    out = []
    for key, value in node.items():
        path = f"{prefix}{key}"
        # These paths are containers. Any other dict is a value in its own
        # right (page_orient, subfolder_names) and must not be walked into.
        if isinstance(value, dict) and path in (
            "global", "organizer", "cloud", "rename", "report", "walls",
            "organizer.rename", "rename.file_rules",
        ):
            out.extend(_flatten(value, path + "."))
        else:
            out.append(path)
    return out


def _registry_covers(key: str) -> bool:
    for entry in ENTRIES:
        if entry.get("key") == key:
            return True
        prefix = entry.get("key_prefix")
        if prefix and key.startswith(prefix):
            return True
    return False


class RegistryShape(unittest.TestCase):
    def test_every_entry_declares_a_known_category(self):
        known = set(REGISTRY["categories"])
        for entry in ENTRIES:
            with self.subTest(entry=entry.get("key") or entry.get("key_prefix")):
                self.assertIn(entry["category"], known)

    def test_the_categories_are_defined_in_the_registry_itself(self):
        """A future contributor has to meet the rule where the data is, not in
        a document they will never open.

        Two categories, not three: the hosted-mirror category existed only for
        the GitHub Pages build, where there was no server to save to. That is
        retired, so there is no server-when-present store any more."""
        self.assertEqual(set(REGISTRY["categories"]), {"preference", "ui-state"})
        for name in ("preference", "ui-state"):
            with self.subTest(category=name):
                definition = REGISTRY["categories"][name]["definition"]
                self.assertGreater(len(definition), 80,
                                   "the definition has to actually explain the category")
                self.assertTrue(REGISTRY["categories"][name]["store"])

    def test_every_entry_names_an_owner_and_a_home(self):
        for entry in ENTRIES:
            with self.subTest(entry=entry.get("key") or entry.get("key_prefix")):
                self.assertTrue(entry.get("owner"))
                self.assertTrue(entry.get("home"))


class EverySettingIsReachable(unittest.TestCase):
    """(d) A setting nobody can reach is not a setting."""

    def test_every_saved_setting_is_declared_in_the_registry(self):
        from tools.settings import DEFAULTS
        internal = set(REGISTRY["internal"]["keys"])
        missing = [k for k in _flatten(DEFAULTS)
                   if k not in internal and not _registry_covers(k)]
        self.assertEqual(missing, [], (
            "these are saved in settings.json but declared nowhere - add them to "
            f"settings-registry.json (or to its internal list): {missing}"))

    def test_settings_that_say_they_live_on_the_settings_page_are_on_it(self):
        html = SETTINGS_HTML.read_text(encoding="utf-8")
        missing = []
        for entry in ENTRIES:
            if entry.get("home") != "settings":
                continue
            control = entry.get("control")
            if not control:
                continue
            if f'id="{control}"' not in html and f'name="{control}"' not in html:
                missing.append(entry["key"])
        self.assertEqual(missing, [], f"declared on the Settings page but not there: {missing}")


class OneControlPerSetting(unittest.TestCase):
    """(a) Two controls for one setting is how two surfaces drift apart."""

    def test_no_settings_page_control_appears_twice(self):
        html = SETTINGS_HTML.read_text(encoding="utf-8")
        for entry in ENTRIES:
            control = entry.get("control")
            if not control or entry.get("home") != "settings":
                continue
            with self.subTest(key=entry["key"]):
                ids = html.count(f'id="{control}"')
                self.assertLessEqual(ids, 1,
                                     f"{control} is declared more than once on the Settings page")


class NoSettingInTwoStores(unittest.TestCase):
    """(b) The merge-rule bug, as a test."""

    def _js_sources(self):
        return {path.name: path.read_text(encoding="utf-8")
                for path in sorted(JS_DIR.glob("*.js"))}

    def test_retired_browser_keys_are_never_read_or_written_again(self):
        offenders = []
        for key in REGISTRY["retired_browser_keys"]["keys"]:
            for name, source in self._js_sources().items():
                for call in (f"getItem('{key}')", f'getItem("{key}")',
                             f"setItem('{key}'", f'setItem("{key}"'):
                    if call in source:
                        offenders.append(f"{name}: {call}")
        self.assertEqual(offenders, [], (
            "these keys moved to settings.json; reading or writing them again "
            f"recreates the two-store bug: {offenders}"))

    def test_a_server_setting_is_not_also_a_declared_browser_key(self):
        browser = {k["key"] for k in REGISTRY["browser_only"]["keys"]}
        retired = set(REGISTRY["retired_browser_keys"]["keys"])
        self.assertEqual(browser & retired, set(),
                         "a key cannot be both a live browser key and a retired one")

    def test_every_localstorage_key_in_the_suite_is_accounted_for(self):
        """A new localStorage key has to be a deliberate choice, not a habit."""
        declared = {k["key"] for k in REGISTRY["browser_only"]["keys"]}
        declared |= set(REGISTRY["retired_browser_keys"]["keys"])
        pattern = re.compile(r"""(?:get|set|remove)Item\(\s*['"]([a-zA-Z0-9._-]+)['"]""")
        undeclared = set()
        for name, source in self._js_sources().items():
            for key in pattern.findall(source):
                if key not in declared:
                    undeclared.add(f"{name}: {key}")
        self.assertEqual(undeclared, set(), (
            "browser storage used for something not in settings-registry.json. "
            "Decide which category it is and declare it, or move it to "
            f"settings.json: {sorted(undeclared)}"))


class SettingsWritesUseTheEnvelope(unittest.TestCase):
    """(c) The page-orientation bug, as a test.

    `/api/settings/update` reads `d["patch"]`. A call that posts the section
    directly succeeds, merges nothing, and reports success."""

    def test_every_settings_update_call_sends_a_patch(self):
        bad = []
        for path in sorted(JS_DIR.glob("*.js")):
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "settings/update" not in line:
                    continue
                if "patch:" not in line and "patch :" not in line:
                    bad.append(f"{path.name}:{line_no}: {line.strip()}")
        self.assertEqual(bad, [], (
            "settings/update without a patch envelope saves nothing and still "
            f"returns ok: {bad}"))

    def test_the_server_still_reads_the_patch_key(self):
        """If this ever changes, the test above is measuring the wrong thing."""
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('d.get("patch"', server)


if __name__ == "__main__":
    unittest.main()
