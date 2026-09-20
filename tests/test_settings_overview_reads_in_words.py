"""The settings list prints what the control says, not what the file stores.

The per-tool "What is saved" lists went out in v2.150.0 printing the stored
value: `coarse` where the control reads "Fewer pages - larger sections",
`newer` where Cloud Manager's says "Keep newer (by timestamp)", `30000` for an
interval nobody thinks about in milliseconds, and `others` for a view called
Others.

It is the same defect as the Report printing `#6B6B6B` as a section heading
while the Labeler said Gray, and it has the same cost: a setting cannot be
found by the words on its own control, and a list meant to answer "what is this
set to" answers in a vocabulary that exists nowhere on screen.

The labels live in `settings-registry.json` next to the setting they belong to.
That puts them one edit away from the thing they describe, and it makes the
important test possible: **the values the registry can name must be exactly the
values the tool accepts.** Without that, a new choice added to a tool prints raw
and nothing says so - which is how the list came to be wrong in the first place.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SETTINGS_JS = WEB / "assets" / "js" / "settings-page.js"
SETTINGS_HTML = WEB / "settings.html"
REGISTRY = WEB / "assets" / "settings-registry.json"
CLOUD_JS = WEB / "assets" / "js" / "cloud.js"
REPORT_JS = WEB / "assets" / "js" / "report.js"
WALLS_JS = WEB / "assets" / "js" / "walls.js"
PLANTRIM_HTML = WEB / "plantrim.html"
NODE_TIMEOUT_S = 120


def _entries() -> dict:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {r["key"]: r for r in reg["settings"] if r.get("key")}


class TheNamedValuesAreTheValuesTheToolAccepts(unittest.TestCase):
    """The guard that keeps the labels honest. Each of these reads the list
    from wherever the tool really declares it, so adding a choice to a tool and
    forgetting the registry fails here rather than printing raw on screen."""

    def _bracket_list(self, path: Path, name: str) -> set:
        m = re.search(name + r"\s*=\s*\[([^\]]*)\]", path.read_text(encoding="utf-8"))
        self.assertIsNotNone(m, "%s moved in %s" % (name, path.name))
        return set(re.findall(r"'([^']+)'", m.group(1)))

    def check(self, key: str, accepted: set):
        named = set((_entries()[key].get("values") or {}).keys())
        self.assertTrue(named, "%s has no value labels, so it prints raw" % key)
        self.assertEqual(
            named - accepted, set(),
            "%s names a value the tool rejects: %s"
            % (key, ", ".join(sorted(named - accepted))))
        self.assertEqual(
            accepted - named, set(),
            "%s has a value with no label, so the list prints it raw: %s"
            % (key, ", ".join(sorted(accepted - named))))

    def test_the_merge_rules(self):
        self.check("cloud.merge_rule",
                   self._bracket_list(CLOUD_JS, "const MERGE_RULES"))

    def test_the_owner_filters(self):
        self.check("cloud.default_owner_filter",
                   self._bracket_list(CLOUD_JS, "OWNER_FILTERS"))

    def test_the_section_sizes(self):
        js = REPORT_JS.read_text(encoding="utf-8")
        body = js[js.index("var SEG_GRANULARITY = {"):]
        body = body[:body.index("};")]
        self.check("report.segment_granularity",
                   set(re.findall(r"(\w+):\s*\{", body)))

    def test_the_report_units(self):
        """`fetchSettings` is what decides whether a stored unit is honoured;
        anything else falls back to feet."""
        js = REPORT_JS.read_text(encoding="utf-8")
        m = re.search(r"if \(u === '(\w+)' \|\| u === '(\w+)'\) unitsPref = u;", js)
        self.assertIsNotNone(m, "the units check in fetchSettings moved")
        self.check("report.units", {m.group(1), m.group(2)})

    def test_the_wall_units(self):
        js = WALLS_JS.read_text(encoding="utf-8")
        m = re.search(r"saved\.units === '(\w+)' \|\| saved\.units === '(\w+)'", js)
        self.assertIsNotNone(m, "the units check in loadWallsPrefs moved")
        self.check("walls.units", {m.group(1), m.group(2)})

    def test_the_trim_margins(self):
        """PlanTrim's own control is the authority here rather than
        `MARGIN_PRESET_FEET`, because `custom` is a real stored value and is
        not one of the presets."""
        html = PLANTRIM_HTML.read_text(encoding="utf-8")
        block = html[html.index('id="ptbMargin"'):]
        block = block[:block.index("</select>")]
        self.check("plantrim.margin_preset",
                   set(re.findall(r'<option value="([^"]+)"', block)))


class ALabelledValueReadsLikeItsControl(unittest.TestCase):
    """Where the control is on the Settings page, the list beneath it must not
    use different words for the same thing - two vocabularies for one setting
    is how "a settled row that stopped asking" gets written down."""

    def _option_labels(self, select_id: str) -> dict:
        html = SETTINGS_HTML.read_text(encoding="utf-8")
        block = html[html.index('id="%s"' % select_id):]
        block = block[:block.index("</select>")]
        out = {}
        for value, label in re.findall(r'<option value="([^"]*)"[^>]*>(.*?)</option>',
                                       block, re.S):
            out[value] = (label.replace("&mdash;", "—")
                               .replace("&hellip;", "…").strip())
        return out

    def test_the_section_sizes_match_their_own_control(self):
        named = _entries()["report.segment_granularity"]["values"]
        for value, label in self._option_labels("sRepSegGranularity").items():
            with self.subTest(value=value):
                self.assertEqual(named.get(value), label)

    def test_the_report_units_match_their_own_control(self):
        named = _entries()["report.units"]["values"]
        for value, label in self._option_labels("sRepUnits").items():
            with self.subTest(value=value):
                self.assertEqual(named.get(value), label)

    def test_the_merge_rules_match_their_own_radios(self):
        html = SETTINGS_HTML.read_text(encoding="utf-8")
        named = _entries()["cloud.merge_rule"]["values"]
        found = re.findall(
            r'name="mergeRule" value="([^"]+)">\s*([^<&]+)', html)
        self.assertEqual(len(found), len(named), "a merge rule radio is missing")
        for value, label in found:
            with self.subTest(value=value):
                self.assertEqual(named.get(value), label.strip())


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheRendererUsesThem(unittest.TestCase):
    """`describe` run directly, because the mapping is the whole change."""

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  function describe(v, entry) {');
        if (a < 0) throw new Error('describe moved');
        const end = src.indexOf('  function familyCount(');
        if (end < 0) throw new Error('familyCount moved');
        eval(src.slice(a, end));
        const cases = JSON.parse(process.argv[2]);
        console.log(JSON.stringify(cases.map(function (c) {
          return describe(c.value, c.entry);
        })));
    """

    def describe(self, cases):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(SETTINGS_JS), json.dumps(cases)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_known_value_prints_its_label(self):
        entry = _entries()["report.segment_granularity"]
        got = self.describe([{"value": "coarse", "entry": entry},
                             {"value": "standard", "entry": entry}])
        self.assertEqual(got, ["Fewer pages — larger sections", "Standard"])

    def test_the_merge_rule_and_owner_filter_read_in_words(self):
        got = self.describe([
            {"value": "newer", "entry": _entries()["cloud.merge_rule"]},
            {"value": "others", "entry": _entries()["cloud.default_owner_filter"]},
        ])
        self.assertEqual(got, ["Keep newer (by timestamp)", "Others"])

    def test_an_unknown_value_is_printed_rather_than_dropped(self):
        """A value nobody planned for is still information - the Ekahau colour
        table settled this for the same reason. Hiding it would leave the row
        looking like a setting that is not set."""
        entry = _entries()["cloud.merge_rule"]
        self.assertEqual(self.describe([{"value": "overwrite", "entry": entry}]),
                         ["overwrite"])

    def test_a_setting_with_no_labels_is_unaffected(self):
        entry = _entries()["walls.default_template"]
        self.assertEqual(self.describe([{"value": "Site standard", "entry": entry}]),
                         ["Site standard"])

    def test_booleans_and_empties_are_unchanged(self):
        entry = _entries()["walls.auto_apply_template"]
        got = self.describe([{"value": True, "entry": entry},
                             {"value": False, "entry": entry},
                             {"value": "", "entry": entry},
                             {"value": None, "entry": entry}])
        self.assertEqual(got, ["On", "Off", None, None])

    def test_an_interval_is_read_in_seconds(self):
        entry = _entries()["cloud.live_interval_ms"]
        got = self.describe([{"value": 30000, "entry": entry},
                             {"value": 1000, "entry": entry},
                             {"value": 120000, "entry": entry},
                             {"value": 60000, "entry": entry},
                             {"value": 2500, "entry": entry}])
        self.assertEqual(got, ["30 seconds", "1 second", "2 minutes",
                               "1 minute", "2.5 seconds"])

    def test_a_distance_is_read_in_feet(self):
        entry = _entries()["plantrim.margin_custom_ft"]
        self.assertEqual(
            self.describe([{"value": 2.5, "entry": entry},
                           {"value": 1, "entry": entry}]),
            ["2.5 feet", "1 foot"])

    def test_a_unit_it_cannot_parse_prints_as_stored(self):
        entry = dict(_entries()["cloud.live_interval_ms"])
        self.assertEqual(self.describe([{"value": "soon", "entry": entry}]),
                         ["soon"])


class EveryHomeHasAName(unittest.TestCase):
    """The signpost half, and it was wrong on the day it shipped.

    A setting whose control is not on the Settings page carries a `home`, and
    the list turns that into "Changed in <tool>." from a map written by hand.
    The map said `rename-tool`; the registry says `rename-page`. The result was
    that both rename rows rendered **no signpost at all** - indistinguishable
    from a setting that is changed on the Settings page, which is the opposite
    of the truth. Three other keys named modals that had already been deleted.

    Nothing could have caught it by reading either file alone, so this compares
    them: every home in use must have a name, and a name with no home in use is
    dead weight that hides the next typo.
    """

    def _map(self) -> dict:
        js = SETTINGS_JS.read_text(encoding="utf-8")
        block = js[js.index("var WHERE = {"):]
        block = block[:block.index("};")]
        return dict(re.findall(r"'([^']+)':\s*'([^']+)'", block))

    def _homes_in_use(self) -> set:
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        return {r.get("home") for r in reg["settings"]
                if r.get("home") and r.get("home") != "settings"}

    def test_every_home_in_use_has_a_tool_name(self):
        missing = sorted(self._homes_in_use() - set(self._map()))
        self.assertEqual(
            missing, [],
            "these settings are changed on a tool and the list says nothing, "
            "so they read as though they are set on the Settings page: "
            + ", ".join(missing))

    def test_no_name_is_kept_for_a_home_nobody_uses(self):
        stale = sorted(set(self._map()) - self._homes_in_use())
        self.assertEqual(
            stale, [],
            "these named homes are unused; a dead entry beside a live one is "
            "how a typo goes unnoticed: " + ", ".join(stale))

    def test_the_names_are_the_tools_as_they_are_labelled(self):
        """"Changed in organizer-tool." would be worse than nothing."""
        known = {"Cloud Manager", "Quick Walls", "Report", "Squirrel", "Rename",
                 "AP Labeler", "PlanTrim", "Scale", "Capacity", "Prep"}
        for home, name in self._map().items():
            with self.subTest(home=home):
                self.assertIn(name, known,
                              "%s is named %r, which is not how any tool in "
                              "the suite is labelled" % (home, name))

if __name__ == "__main__":
    unittest.main()
