"""Units and section size are set once, not by whichever report touched them last.

Both are suite preferences - `report.units` and `report.segment_granularity` -
and both were written implicitly from Report's **Configure** step. Changing one
report to metres wrote `units: 'meters'` into `settings.json`, so every report
configured afterwards started in metres. Same shape as the default wall
template taking the value of whatever was last applied, and just as silent: the
panel showed a per-report choice and said nothing about having changed a suite
setting.

They have controls on the Settings page now, under **Report**, and Configure
changes only the report in front of you.

Three things are held here, and the third is the one the change created rather
than fixed:

  * `setOpt` writes no preference;
  * the Settings page offers the values the tool accepts, reads them back and
    does not erase them when saving something unrelated;
  * **the options panel starts from the setting**. The render path has always
    used `unitsPref` (see `buildOpts`), while the panel read the value shipped
    in the option definition. Those agreed only because `setOpt` used to write
    both at once. With that write gone, a panel reading the shipped default
    would show "Feet" on a report rendering in metres.

A report type can still carry its own value through **Save these as my
defaults**, and that wins - a deliberate second level, which the Settings page
names rather than hides. Cloud Manager's merge rule spent four releases showing
a value that was not in force; the lesson was to say so, not to remove the
level.
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
REPORT_JS = WEB / "assets" / "js" / "report.js"
SETTINGS_JS = WEB / "assets" / "js" / "settings-page.js"
SETTINGS_HTML = WEB / "settings.html"
REGISTRY = WEB / "assets" / "settings-registry.json"
NODE_TIMEOUT_S = 120

BRACE_SLICE = """
        let b = a, depth = 0, seen = false;
        while (b < src.length && !(seen && depth === 0)) {
          if (src[b] === '{') { depth++; seen = true; }
          else if (src[b] === '}') depth--;
          b++;
        }
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ConfigureChangesOnlyThisReport(unittest.TestCase):
    """The real `setOpt`, run against recording stubs."""

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  window.setOpt = function (cb) {');
        if (a < 0) throw new Error('setOpt moved');
    """ + BRACE_SLICE + r"""
        const id = process.argv[2], value = process.argv[3];
        const writes = [];
        const currentOpts = {};
        const optOverrides = {};
        let settingsAvailable = true;
        const SETTING_IDS = ['clientName', 'preparedBy', 'projectRef', 'revision'];
        const pushSettings = (p) => {
          writes.push('pushSettings:' + JSON.stringify(p));
          return Promise.resolve({});
        };
        // Everything setOpt calls, so the real function runs to the end
        // rather than throwing partway and hiding a write that came after.
        const settingDefault = () => '';
        const refreshSettingBadge = () => {};
        const refreshRememberedState = () => {};
        const renderApFilter = () => {};
        const scheduleAutoSave = () => {};
        const window = {};
        let configureDirty = false;
        eval(src.slice(a, b));
        window.setOpt({
          value: value,
          getAttribute: (k) => (k === 'data-opt-id' ? id : 'select'),
        });
        console.log(JSON.stringify({ writes: writes, currentOpts: currentOpts }));
    """

    def run_opt(self, opt_id, value):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(REPORT_JS), opt_id, value],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_changing_units_writes_no_preference(self):
        got = self.run_opt("units", "meters")
        self.assertEqual(
            got["writes"], [],
            "switching one report to metres changed the starting point for "
            "every later report: " + ", ".join(got["writes"]))

    def test_changing_the_section_size_writes_no_preference(self):
        got = self.run_opt("segGranularity", "coarse")
        self.assertEqual(got["writes"], [], ", ".join(got["writes"]))

    def test_the_choice_still_reaches_this_report(self):
        """The removal must not take the per-report control with it."""
        self.assertEqual(self.run_opt("units", "meters")["currentOpts"]["units"],
                         "meters")
        self.assertEqual(
            self.run_opt("segGranularity", "coarse")["currentOpts"]["segGranularity"],
            "coarse")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePanelStartsFromTheSetting(unittest.TestCase):
    """`optStartValue` is what the panel, the diff against saved defaults and
    the render path all read. It has to answer with the setting for these two
    and with the option's own default for everything else."""

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  function suitePrefFor(id) {');
        const end = src.indexOf('  function shippedDefaultFor(');
        if (a < 0 || end < 0) throw new Error('optStartValue moved');

        const argv = JSON.parse(process.argv[2]);
        let unitsPref = argv.unitsPref;
        let segGranularityPref = argv.segPref;
        eval(src.slice(a, end));
        console.log(JSON.stringify({
          units: optStartValue({ id: 'units', type: 'select', default: 'feet' }),
          seg: optStartValue({ id: 'segGranularity', type: 'select', default: 'standard' }),
          other: optStartValue({ id: 'compass', type: 'checkbox', default: true }),
          otherSelect: optStartValue({ id: 'compassRef', type: 'select', default: 'always' }),
        }));
    """

    def start(self, units_pref, seg_pref):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(REPORT_JS),
             json.dumps({"unitsPref": units_pref, "segPref": seg_pref})],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_panel_shows_metres_when_the_setting_says_metres(self):
        got = self.start("meters", "coarse")
        self.assertEqual(
            got["units"], "meters",
            'the options panel would read "Feet" on a report that renders in '
            "metres, which is what the render path uses")
        self.assertEqual(got["seg"], "coarse")

    def test_it_agrees_with_the_setting_the_other_way_too(self):
        got = self.start("feet", "standard")
        self.assertEqual(got["units"], "feet")
        self.assertEqual(got["seg"], "standard")

    def test_every_other_option_keeps_its_own_default(self):
        """Only these two are suite-backed; widening it would make every
        option on every report answer to a setting that does not exist."""
        got = self.start("meters", "coarse")
        self.assertIs(got["other"], True)
        self.assertEqual(got["otherSelect"], "always")

    def test_an_unset_preference_falls_back_to_the_shipped_default(self):
        got = self.start("", "")
        self.assertEqual(got["units"], "feet")
        self.assertEqual(got["seg"], "standard")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheSettingsPageOwnsThem(unittest.TestCase):
    SAVE_PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  SP.save = function () {');
        const b = src.indexOf('  SP.exportSettings');
        if (a < 0 || b < 0) throw new Error('SP.save moved');

        const values = JSON.parse(process.argv[2]);
        const settings = { report: { units: 'meters', segment_granularity: 'coarse' },
                           cloud: {}, walls: {} };
        globalThis.document = {
          getElementById: (id) => ({ value: (id in values) ? values[id] : '',
                                     checked: false,
                                     options: { length: 1 } }),
          querySelectorAll: () => [],
        };
        let sent = null;
        const API = (_r, body) => { sent = body.patch; return { then: () => {} }; };
        const _subfolders = [], _subfolderNames = {};
        const collectCustomDests = () => [];
        const splitComma = () => [];
        const WD = { toast() {} };
        const SP = {};
        eval(src.slice(a, b));
        SP.save();
        console.log(JSON.stringify(sent));
    """

    def save(self, values):
        r = subprocess.run(
            ["node", "-e", self.SAVE_PROBE, str(SETTINGS_JS), json.dumps(values)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_both_are_written(self):
        patch = self.save({"sRepUnits": "meters", "sRepSegGranularity": "coarsest"})
        self.assertEqual(patch["report"]["units"], "meters")
        self.assertEqual(patch["report"]["segment_granularity"], "coarsest")

    def test_a_value_the_tool_does_not_accept_never_reaches_the_file(self):
        """`buildOpts` only recognises feet and meters; anything else would
        fall through to a report that silently renders in feet while the page
        claims otherwise."""
        patch = self.save({"sRepUnits": "furlongs", "sRepSegGranularity": ""})
        self.assertEqual(patch["report"]["units"], "feet")
        self.assertEqual(patch["report"]["segment_granularity"], "standard")

    def test_the_values_offered_are_the_values_the_tool_accepts(self):
        html = SETTINGS_HTML.read_text(encoding="utf-8")
        block = html[html.index('id="sRepSegGranularity"'):]
        offered = set(re.findall(r'value="([^"]+)"', block[:block.index("</select>")]))
        js = REPORT_JS.read_text(encoding="utf-8")
        body = js[js.index("var SEG_GRANULARITY = {"):]
        accepted = set(re.findall(r"(\w+):\s*\{", body[:body.index("};")]))
        self.assertEqual(offered, accepted,
                         "the Settings page and the report disagree about "
                         "which section sizes exist")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThereIsOnlyOneCopyOfThem(unittest.TestCase):
    """The registry's rule, made true of the stored data and not only of the
    code that writes it.

    `collectSidebarValues` already refuses to copy these two into
    `report.report_defaults`, so nothing writes a second copy. A settings file
    written before that guard can still hold one, and `selectReport` seeded
    `currentOpts` from that map wholesale - so the stale copy would win over
    the setting, which is a second store however it got there. A first pass at
    this change built a warning naming the reports that were overriding;
    skipping them on the way in is better, because it leaves nothing to warn
    about.
    """

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  window.selectReport = function (id) {');
        if (a < 0) throw new Error('selectReport moved');
""" + BRACE_SLICE + r"""
        const stored = JSON.parse(process.argv[2]);
        const PERSON_LEVEL_OPTS = ['units', 'segGranularity'];
        let currentOpts = {}, optOverrides = {}, currentReportId = null;
        let templateConfirmed = false, configureDirty = false;
        const REPORTS = { placement: { status: 'ready' } };
        const RETIRED_REPORTS = {};
        const reportOptionDefaults = () => stored;
        const renderTemplateGallery = () => {};
        const renderReportPreview = () => {};
        const renderReportOpts = () => {};
        const renderCoverSummary = () => {};
        const renderApFilter = () => {};
        const syncDocTitle = () => {};
        const goStage = () => {};
        const window = {};
        eval(src.slice(a, b));
        window.selectReport('placement');
        console.log(JSON.stringify(currentOpts));
    """

    def seeded(self, stored):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(REPORT_JS), json.dumps(stored)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_stale_per_report_copy_does_not_override_the_setting(self):
        got = self.seeded({"units": "meters", "segGranularity": "coarse",
                           "shortLabels": True})
        self.assertNotIn("units", got,
                         "a per-report copy of units was seeded, so it wins "
                         "over the setting and the Settings page shows a "
                         "value that is not in force")
        self.assertNotIn("segGranularity", got)

    def test_every_other_saved_option_is_still_seeded(self):
        """The skip must not take the per-report defaults with it."""
        got = self.seeded({"units": "meters", "shortLabels": True,
                           "inclOmni": False})
        self.assertIs(got["shortLabels"], True)
        self.assertIs(got["inclOmni"], False)


class TheRegistryAgrees(unittest.TestCase):
    def test_both_record_their_control_and_home(self):
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        by_key = {r.get("key"): r for r in reg["settings"]}
        for key, control in (("report.units", "sRepUnits"),
                             ("report.segment_granularity", "sRepSegGranularity")):
            with self.subTest(key=key):
                self.assertEqual(by_key[key].get("home"), "settings")
                self.assertEqual(by_key[key].get("control"), control)


if __name__ == "__main__":
    unittest.main()
