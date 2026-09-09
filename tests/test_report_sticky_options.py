"""Report sidebar options are remembered, per report type.

The complaint: "some things should be on by default and stay on by default
based on the user so that you don't have to keep checking the same damn radio
buttons all the time". Only four text fields were remembered; the other
thirty-seven checkboxes, radios and selects reset to their shipped values on
every report.

Two decisions this file holds.

**Keyed by report type, not shared by option id.** The shipped defaults
deliberately differ - the Antenna Aim Sheet starts with omni APs excluded and
every other report includes them - and worse, the same option id means
different things in different reports: `overview` is "per-floor mini-maps" on
the Aim Sheet and "include per-floor detection map" on Interference, and
`signOff` is sign-off *columns* on one and a sign-off *block* on the other.
Sharing by id would corrupt values, not merely surprise someone.

**A sidebar change stays with the document; one button makes it the default.**
Same split the Cloud Manager owner filter settled on, for the same reason: a
stray click must not become permanent. The button is next to the boxes rather
than on a settings page, because visiting a settings page forty-one times is
not an improvement on ticking boxes forty-one times.

And the bug found while building it, guarded below: `_deep_merge` cannot remove
a key, so "use the shipped defaults again" saved successfully and changed
nothing. A keyed store has to be replaced, not merged.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"

from tools import settings as suite_settings  # noqa: E402


class StickyStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-sticky-")) / "settings.json"

    def test_it_ships_empty_so_nothing_needs_migrating(self):
        """An absent entry falls back to the option's own shipped default, so a
        new report or a new option needs no migration and cannot be stranded -
        which is what went wrong the last time values moved storage layer."""
        self.assertEqual(suite_settings.DEFAULTS["report"]["report_defaults"], {})

    def test_a_saved_set_round_trips(self):
        suite_settings.update_settings(
            {"report": {"report_defaults": {"placement": {"showCones": True}}}},
            _path=self.tmp)
        got = suite_settings.load_settings(_path=self.tmp)["report"]["report_defaults"]
        self.assertEqual(got, {"placement": {"showCones": True}})

    def test_a_saved_set_can_be_removed_again(self):
        """The bug. Deep-merging {} into an existing map keeps every old entry,
        so "Use shipped defaults" reported success and did nothing."""
        suite_settings.update_settings(
            {"report": {"report_defaults": {"placement": {"showCones": True}}}},
            _path=self.tmp)
        suite_settings.update_settings({"report": {"report_defaults": {}}},
                                       _path=self.tmp)
        got = suite_settings.load_settings(_path=self.tmp)["report"]["report_defaults"]
        self.assertEqual(got, {}, "a keyed store must be replaced, not merged")

    def test_removing_one_report_leaves_the_others(self):
        suite_settings.update_settings(
            {"report": {"report_defaults": {"placement": {"showCones": True},
                                            "aim": {"compass": False}}}},
            _path=self.tmp)
        suite_settings.update_settings(
            {"report": {"report_defaults": {"aim": {"compass": False}}}},
            _path=self.tmp)
        got = suite_settings.load_settings(_path=self.tmp)["report"]["report_defaults"]
        self.assertEqual(got, {"aim": {"compass": False}})

    def test_it_does_not_disturb_the_rest_of_the_report_settings(self):
        """His client name, revision and units live alongside it."""
        suite_settings.update_settings(
            {"report": {"client_name": "Acme", "revision": "v3.1"}}, _path=self.tmp)
        suite_settings.update_settings(
            {"report": {"report_defaults": {"placement": {"showCones": True}}}},
            _path=self.tmp)
        rep = suite_settings.load_settings(_path=self.tmp)["report"]
        self.assertEqual(rep["client_name"], "Acme")
        self.assertEqual(rep["revision"], "v3.1")

    def test_only_declared_paths_are_replaced(self):
        """Replace-not-merge is a deliberate exception, not the rule. Anything
        else must keep merging, or an unrelated patch would wipe siblings."""
        self.assertIn(("report", "report_defaults"), suite_settings.REPLACE_NOT_MERGE)
        suite_settings.update_settings({"report": {"client_name": "A"}}, _path=self.tmp)
        suite_settings.update_settings({"report": {"revision": "r"}}, _path=self.tmp)
        rep = suite_settings.load_settings(_path=self.tmp)["report"]
        self.assertEqual(rep["client_name"], "A", "a normal patch wiped a sibling")


class StickyWiring(unittest.TestCase):
    def setUp(self):
        self.js = REPORT_JS.read_text(encoding="utf-8")

    def test_the_store_is_keyed_by_report_type(self):
        """Not by option id - see the module docstring for the two ids whose
        meaning differs between reports."""
        self.assertIn("function reportOptionDefaults(id)", self.js)
        self.assertIn("savedReportDefaults[id]", self.js)
        self.assertIn("next[currentReportId] = collectSidebarValues();", self.js)

    def test_choosing_a_report_seeds_the_saved_values(self):
        start = self.js.index("window.selectReport = function (id)")
        body = self.js[start:self.js.index("\n  };", start)]
        self.assertIn("reportOptionDefaults(id)", body,
                      "without this the saved defaults are stored and never used")

    def test_a_sidebar_change_is_not_a_settings_write(self):
        """A stray click must not become permanent. Units is the one exception
        and predates this - it is a person-level preference, not a document
        one."""
        start = self.js.index("window.setOpt = function (cb)")
        body = self.js[start:self.js.index("\n  };", start)]
        writes = body.count("settings/update")
        self.assertLessEqual(writes, 1, "setOpt should not persist option values")
        if writes:
            self.assertIn("id === 'units'", body)

    def test_the_shared_text_fields_stay_out_of_the_per_report_store(self):
        """Client, prepared-by, reference and revision are one value across
        every report and already stored globally. Copying them into the
        per-report store would create a second source for them."""
        start = self.js.index("function collectSidebarValues()")
        body = self.js[start:self.js.index("\n  }", start)]
        self.assertIn("SETTING_IDS.indexOf(opt.id) !== -1", body)
        self.assertIn("opt.type === 'text'", body)
        self.assertIn("opt.id.charAt(0) === '_'", body)

    def test_the_state_is_on_screen_and_stays_current(self):
        """A remembered default that is not visible is the owner-filter trap."""
        self.assertIn("rep-remembered-state", self.js)
        self.assertIn("function refreshRememberedState()", self.js)
        start = self.js.index("window.setOpt = function (cb)")
        body = self.js[start:self.js.index("\n  };", start)]
        self.assertIn("refreshRememberedState()", body)

    def test_both_actions_are_reachable(self):
        self.assertIn("window.saveReportOptionDefaults", self.js)
        self.assertIn("window.clearReportOptionDefaults", self.js)
        self.assertIn('onclick="saveReportOptionDefaults()"', self.js)
        self.assertIn('onclick="clearReportOptionDefaults()"', self.js)


if __name__ == "__main__":
    unittest.main()
