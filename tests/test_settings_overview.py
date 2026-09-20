"""Every tool's settings are listed on the Settings page, and the list is live.

He asked for "an overview of the settings for each of the tools", and the two
ways that request can be answered badly are both guarded here.

The first is a list written out by hand, which is a list that stops being true.
The overview is rendered from `web/assets/settings-registry.json` - the file a
new setting is already required to be added to - so a registered setting turns
up in it without anyone remembering. `EverySectionIsShown` fails if a registry
section has no host on the page, which is what would happen to a tool nobody
thought about.

The second is a list that describes rather than reports: labels with no values,
or a row that says "true" where a person needs to read "On".
`TheOverviewReportsRealValues` runs the real renderer against a real settings
map and reads the rows back out of the markup it produces.
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
SETTINGS_HTML = WEB / "settings.html"
SETTINGS_JS = WEB / "assets" / "js" / "settings-page.js"
REGISTRY = WEB / "assets" / "settings-registry.json"
NODE_TIMEOUT_S = 120


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _hosted_sections() -> list:
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'class="s-overview" data-section="([^"]+)"', html):
        out.extend(part.strip() for part in m.group(1).split(","))
    return out


class EverySectionIsShown(unittest.TestCase):
    def test_no_registry_section_is_left_out(self):
        want = {r.get("section") for r in _registry()["settings"] if r.get("section")}
        have = set(_hosted_sections())
        self.assertEqual(
            want - have, set(),
            "these tools have registered settings and no overview on the "
            "Settings page, so nothing there says they exist: "
            + ", ".join(sorted(want - have)))

    def test_no_section_is_listed_twice(self):
        listed = _hosted_sections()
        dupes = sorted({s for s in listed if listed.count(s) > 1})
        self.assertEqual(dupes, [],
                         "a section shown in two places prints its settings "
                         "twice: " + ", ".join(dupes))

    def test_every_hosted_section_is_a_real_one(self):
        want = {r.get("section") for r in _registry()["settings"] if r.get("section")}
        stray = sorted(set(_hosted_sections()) - want)
        self.assertEqual(stray, [],
                         "these hosts name a section the registry does not "
                         "have, so they render empty: " + ", ".join(stray))


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheOverviewReportsRealValues(unittest.TestCase):
    """The renderer, run against a settings map, with the rows read back."""

    SETTINGS = {
        "global": {"output_dir": "D:/Projects", "subfolders": ["plans", "photos"],
                   "subfolder_names": {}, "custom_destinations": []},
        "cloud": {"merge_rule": "newer", "default_owner_filter": "others",
                  "live_interval_ms": 45000},
        "report": {"client_name": "Northwind Traders", "prepared_by": "",
                   "project_ref": "PO-2026-0042", "revision": "Rev B",
                   "include_revision_in_filename": False,
                   "units": "feet", "segment_granularity": "standard"},
        "walls": {"reveal_source_after_save": True, "units": "inches",
                  "default_template": "Site standard", "auto_apply_template": True},
        "plantrim": {"margin_preset": "tight", "margin_custom_ft": 2.5},
        "organizer": {"image_ext": [".png"], "plan_ext": [], "report_ext": [],
                      "report_keywords": [], "json_report_keywords": [],
                      "skip_dirs": [], "create_folder_template": "",
                      "rename": {"a": 1, "b": 2}},
        "rename": {"profiles": {"one": {}}},
        "aprename": {"templates": ["x"], "defaults": {}},
    }

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  var WHERE = {');
        const b = src.indexOf('  function loadOverviews() {');
        if (a < 0 || b < 0) throw new Error('the overview renderer moved');

        const registry = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
        const settings = JSON.parse(process.argv[3]);
        const hosts = JSON.parse(process.argv[4]).map(function (sec) {
          return { sec: sec, html: '',
                   getAttribute: function () { return sec; },
                   set innerHTML(v) { this.html = v; },
                   get innerHTML() { return this.html; } };
        });
        global.document = { querySelectorAll: () => hosts };
        const WD = { esc: (s) => String(s) };
        eval(src.slice(a, b));
        renderOverviews(registry);
        const out = {};
        const RE = new RegExp(
          '<span class="s-ov-label">([^<]*)</span>'
          + '<span class="s-ov-val([^"]*)">([^<]*)</span>'
          + '(?:<span class="s-ov-where">([^<]*)</span>)?', 'g');
        hosts.forEach(function (h) {
          const rows = [];
          let m;
          RE.lastIndex = 0;
          while ((m = RE.exec(h.html))) {
            rows.push({ label: m[1], empty: m[2].indexOf('is-empty') > -1,
                        value: m[3], where: m[4] || null });
          }
          out[h.sec] = rows;
        });
        console.log(JSON.stringify(out));
    """

    def rows(self) -> dict:
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(SETTINGS_JS), str(REGISTRY),
             json.dumps(self.SETTINGS), json.dumps(_hosted_sections())],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_it_prints_the_value_that_is_saved(self):
        rows = {r["label"]: r for r in self.rows()["report"]}
        self.assertEqual(rows["Client / company"]["value"], "Northwind Traders")
        self.assertEqual(rows["Project reference"]["value"], "PO-2026-0042")
        self.assertEqual(rows["Revision"]["value"], "Rev B")

    def test_a_switch_reads_as_on_or_off_rather_than_true_or_false(self):
        rows = {r["label"]: r for r in self.rows()["report"]}
        self.assertEqual(rows["Include revision in file name"]["value"], "Off")
        walls = {r["label"]: r for r in self.rows()["walls"]}
        self.assertEqual(walls["Auto-apply the default template on open"]["value"], "On")

    def test_an_unset_value_says_so_rather_than_printing_nothing(self):
        rows = {r["label"]: r for r in self.rows()["report"]}
        self.assertTrue(rows["Prepared by"]["empty"],
                        "an empty setting has to read as Not set, or the row "
                        "looks like a rendering fault")

    def test_a_setting_whose_control_is_elsewhere_says_where(self):
        walls = {r["label"]: r for r in self.rows()["walls"]}
        self.assertEqual(walls["Default wall template"]["where"],
                         "Changed in Quick Walls.")
        pt = {r["label"]: r for r in self.rows()["plantrim"]}
        self.assertEqual(pt["Trim margin (how much room to leave around the building)"]["where"], "Changed in PlanTrim.")

    def test_a_setting_controlled_here_carries_no_signpost(self):
        """The control is a few lines above; pointing at it would be noise -
        and pointing at the wrong tool would be worse."""
        rows = {r["label"]: r for r in self.rows()["report"]}
        self.assertIsNone(rows["Client / company"]["where"])
        cloud = {r["label"]: r for r in self.rows()["cloud"]}
        self.assertIsNone(cloud["Default view (All / Mine / Others)"]["where"])

    def test_a_family_of_settings_reports_how_many_are_saved(self):
        sq = {r["label"]: r for r in self.rows()["squirrel"]}
        row = [v for k, v in sq.items() if "ename" in k]
        self.assertTrue(row, "the rename family has no row")
        self.assertEqual(row[0]["value"], "2 items saved")

    def test_every_registered_setting_gets_a_row(self):
        rows = self.rows()
        shown = sum(len(v) for v in rows.values())
        registered = len(_registry()["settings"])
        self.assertEqual(
            shown, registered,
            "%d settings are registered and %d rows were rendered - a "
            "setting with no row is a setting nobody can find"
            % (registered, shown))


REPORT_JS = WEB / "assets" / "js" / "report.js"


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ReportsBannerShowsWhatIsSaved(unittest.TestCase):
    """Report's banner is the only place on that page showing the four
    identity defaults, and they are set on the Settings page now - so it is
    the first thing seen on coming back, and it has to be right.

    It was not. The banner is painted by the template gallery, which runs
    before the settings fetch resolves, and nothing repainted it afterwards:
    four saved values read "Not set". Pre-existing - measured on v2.149.0 and
    on this change side by side, same result - but survivable only while the
    modal on that page was the one thing that changed them, because saving
    there repainted it.

    This asserts the repaint happens where the values arrive, by running
    `fetchSettings` against a stubbed API and recording whether the banner was
    asked to redraw.
    """

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  function fetchSettings() {');
        if (a < 0) throw new Error('fetchSettings moved');
        let b = a, depth = 0, seen = false;
        while (b < src.length && !(seen && depth === 0)) {
          if (src[b] === '{') { depth++; seen = true; }
          else if (src[b] === '}') depth--;
          b++;
        }

        const payload = JSON.parse(process.argv[2]);
        const calls = [];
        let settingsAvailable = false, labelerPattern = null;
        let unitsPref = 'feet', segGranularityPref = 'standard';
        const SEG_GRANULARITY = { standard: 1 };
        const applySettingsPayload = (p) => calls.push('apply:' + JSON.stringify(p || null));
        const renderSettingsBanner = () => calls.push('banner');
        const WD = { api: () => Promise.resolve({ ok: true, settings: payload }) };
        eval(src.slice(a, b));
        fetchSettings().then(function () {
          console.log(JSON.stringify(calls));
        }).catch(function (e) {
          console.log(JSON.stringify(['ERROR:' + e.message]));
        });
    """

    def calls(self, payload):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(REPORT_JS), json.dumps(payload)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_banner_is_repainted_when_the_settings_land(self):
        calls = self.calls({"report": {"client_name": "Northwind Traders",
                                       "revision": "Rev B"}})
        self.assertIn("banner", calls,
                      "nothing repaints the banner after the settings arrive, "
                      'so it goes on saying "Not set" about values that are set')

    def test_the_repaint_happens_after_the_values_are_applied(self):
        """Order matters: repainting first reads the old values and looks
        exactly like not repainting at all."""
        calls = self.calls({"report": {"client_name": "Northwind Traders"}})
        applied = [i for i, c in enumerate(calls) if c.startswith("apply:")]
        banner = [i for i, c in enumerate(calls) if c == "banner"]
        self.assertTrue(applied and banner, "one of the two calls never happened")
        self.assertGreater(banner[-1], applied[0],
                           "the banner was drawn before the values it shows")

if __name__ == "__main__":
    unittest.main()
