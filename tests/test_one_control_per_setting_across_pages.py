"""A setting with two controls drifts, and the drift is silent.

The rule has been written down since v2.57.0 - one control, anywhere in the
suite - and the test that enforced it only ever looked *inside*
`web/settings.html`, so it could not see a second control on a tool page. Three
Cloud Manager settings had one: the merge rule, the default view and the live
interval were all on the Settings page and all rendered again in Cloud
Manager's own Settings modal.

**Two of them disagreed about what the legal values even were.** The tool
implements `MERGE_RULES = ['ask', 'newer', 'both', 'skip']` and rejects
anything else. Cloud Manager offered those four. The Settings page offered
`ask`, `skip` and `overwrite`:

  * `overwrite` is not a legal value, so choosing it and saving wrote a value
    `cloud.js` discards on load - the page said it had saved a choice that
    never took effect;
  * `newer` and `both` had no radio on the Settings page, so nothing was
    checked, and the save loop defaulted to `ask`. **Saving the Settings page
    for any reason at all** - changing the project folder, editing a Squirrel
    extension - therefore reset a merge rule of "Keep newer" or "Keep both"
    back to "Ask me each time", with no message.

These check the properties rather than the wording: the values offered are the
values the tool accepts, no `home: settings` control is rendered anywhere else,
and a save with nothing checked keeps what was saved instead of inventing a
default.
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
CLOUD_JS = WEB / "assets" / "js" / "cloud.js"
REGISTRY = WEB / "assets" / "settings-registry.json"
NODE_TIMEOUT_S = 120


def _registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["settings"]


class TheValuesOfferedAreTheValuesAccepted(unittest.TestCase):
    """A control offering a value its own tool throws away is a control that
    lies about having saved something."""

    def test_the_merge_rule_radios_match_the_tools_own_list(self):
        legal = re.search(r"const MERGE_RULES = \[([^\]]*)\]",
                          CLOUD_JS.read_text(encoding="utf-8"))
        self.assertIsNotNone(legal, "MERGE_RULES moved; this test needs updating")
        accepted = set(re.findall(r"'([^']+)'", legal.group(1)))

        html = SETTINGS_HTML.read_text(encoding="utf-8")
        offered = set(re.findall(r'name="mergeRule"[^>]*value="([^"]+)"', html))
        self.assertTrue(offered, "no merge-rule control on the Settings page")

        self.assertEqual(
            offered - accepted, set(),
            "the Settings page offers a merge rule the tool rejects: "
            + ", ".join(sorted(offered - accepted)))
        self.assertEqual(
            accepted - offered, set(),
            "a legal merge rule has no control, so choosing anything else "
            "silently replaces it: " + ", ".join(sorted(accepted - offered)))

    def test_the_owner_filter_radios_match_what_the_tool_validates(self):
        js = CLOUD_JS.read_text(encoding="utf-8")
        # `_validOwnerFilter` checks membership of this list, so the list is
        # the authority rather than the function body.
        block = re.search(r"OWNER_FILTERS\s*=\s*\[([^\]]*)\]", js)
        self.assertIsNotNone(block, "OWNER_FILTERS moved; this test needs updating")
        accepted = set(re.findall(r"'([^']+)'", block.group(1)))
        self.assertTrue(accepted, "OWNER_FILTERS read as empty")

        html = SETTINGS_HTML.read_text(encoding="utf-8")
        offered = set(re.findall(r'name="setowner"[^>]*value="([^"]+)"', html))
        self.assertEqual(offered, accepted,
                         "the Default view control and the tool disagree about "
                         "which owner filters exist")


class NoSettingHasASecondControl(unittest.TestCase):
    """The rule the old test could not reach: the second control was never on
    the Settings page, it was on the tool."""

    def test_nothing_declared_on_the_settings_page_is_rendered_elsewhere(self):
        offenders = []
        pages = [p for p in sorted(WEB.glob("*.html")) if p.name != "settings.html"]
        for entry in _registry():
            control = entry.get("control")
            if not control or entry.get("home") != "settings":
                continue
            for page in pages:
                text = page.read_text(encoding="utf-8")
                if f'id="{control}"' in text or f'name="{control}"' in text:
                    offenders.append("%s in %s" % (entry["key"], page.name))
        self.assertEqual(
            offenders, [],
            "these settings live on the Settings page and are rendered on a "
            "tool page as well, which is how two surfaces drift apart: "
            + ", ".join(offenders))


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class SavingKeepsWhatItCannotSee(unittest.TestCase):
    """The backstop. Even with the radios correct, a save must never invent a
    value for a control that happens not to be checked."""

    def _save_patch(self, saved_rule: str, checked: str | None,
                    values: dict | None = None, ticked: list | None = None) -> dict:
        program = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  SP.save = function () {');
        const b = src.indexOf('  SP.exportSettings');
        if (a < 0 || b < 0) throw new Error('SP.save moved');

        const saved = process.argv[2];
        const checked = process.argv[3] === '' ? null : process.argv[3];
        const settings = { cloud: { merge_rule: saved, default_owner_filter: 'others' } };

        // only the fields SP.save reads
        const values = JSON.parse(process.argv[4] || '{}');
        const defaults = {
          sOutputDir: '', sImageExt: '', sPlanExt: '', sReportExt: '',
          sPdfKw: '', sJsonKw: '', sSkipDirs: '', sCreateTpl: '',
          sLiveMs: '30000', sWallsReveal: '',
          sRepClient: '', sRepPreparedBy: '', sRepProjectRef: '',
          sRepRevision: '', sRepIncludeRev: '',
        };
        Object.keys(defaults).forEach(k => { if (!(k in values)) values[k] = defaults[k]; });
        const ticked = JSON.parse(process.argv[5] || '[]');
        global.document = {
          // `options` is read by the default-template field, which falls back
          // to the saved value when its list has not been fetched yet.
          getElementById: (id) => ({ value: values[id] || '',
                                     checked: ticked.indexOf(id) > -1,
                                     options: { length: values[id] ? 1 : 0 } }),
          querySelectorAll: (sel) => {
            if (sel.indexOf('mergeRule') > -1) {
              return ['ask', 'newer', 'both', 'skip'].map(v =>
                ({ value: v, checked: v === checked }));
            }
            if (sel.indexOf('setowner') > -1) {
              return ['all', 'mine', 'others'].map(v => ({ value: v, checked: false }));
            }
            return [];
          },
        };
        let sent = null;
        const API = (_route, body) => { sent = body.patch; return { then: () => {} }; };
        const _subfolders = [], _subfolderNames = {};
        const collectCustomDests = () => [];
        const splitComma = () => [];
        const WD = { toast() {} };
        const SP = {};
        eval(src.slice(a, b));
        SP.save();
        console.log(JSON.stringify(sent));
        """
        r = subprocess.run(
            ["node", "-e", program, str(SETTINGS_JS), saved_rule, checked or "",
             json.dumps(values or {}), json.dumps(ticked or [])],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_an_unchecked_merge_rule_keeps_the_saved_one(self):
        patch = self._save_patch("newer", None)
        self.assertEqual(
            patch["cloud"]["merge_rule"], "newer",
            'saving the Settings page replaced a merge rule of "Keep newer" '
            'with "Ask me each time"')

    def test_a_checked_merge_rule_is_the_one_that_is_written(self):
        patch = self._save_patch("newer", "skip")
        self.assertEqual(patch["cloud"]["merge_rule"], "skip")

    def test_the_owner_filter_is_carried_rather_than_dropped(self):
        patch = self._save_patch("ask", None)
        self.assertEqual(
            patch["cloud"]["default_owner_filter"], "others",
            "the Default view was lost by a save that did not mention it")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ReportDefaultsSaveFromTheirNewHome(unittest.TestCase):
    """The four report identity defaults and the file-name switch moved off a
    modal inside Report and onto the Settings page. A control that renders and
    is never read is the failure this catches: the fields would look right and
    saving would write empty strings over whatever was there.
    """

    def _patch(self, values, ticked):
        return SavingKeepsWhatItCannotSee._save_patch(
            SavingKeepsWhatItCannotSee(), "ask", None, values, ticked)

    def test_the_four_identity_fields_are_written(self):
        patch = self._patch({
            "sRepClient": "Northwind Traders",
            "sRepPreparedBy": "A. Surveyor",
            "sRepProjectRef": "PO-2026-0042",
            "sRepRevision": "Rev B",
        }, [])
        self.assertEqual(patch["report"]["client_name"], "Northwind Traders")
        self.assertEqual(patch["report"]["prepared_by"], "A. Surveyor")
        self.assertEqual(patch["report"]["project_ref"], "PO-2026-0042")
        self.assertEqual(patch["report"]["revision"], "Rev B")

    def test_surrounding_whitespace_is_dropped(self):
        """All four, not one - these end up in a printed report and in the
        saved file name, and only one of them used to be checked."""
        patch = self._patch({
            "sRepClient": "  Northwind Traders  ",
            "sRepPreparedBy": " A. Surveyor ",
            "sRepProjectRef": "  PO-2026-0042",
            "sRepRevision": "  Rev B  ",
        }, [])
        self.assertEqual(patch["report"]["client_name"], "Northwind Traders")
        self.assertEqual(patch["report"]["prepared_by"], "A. Surveyor")
        self.assertEqual(patch["report"]["project_ref"], "PO-2026-0042")
        self.assertEqual(patch["report"]["revision"], "Rev B")

    def test_opening_the_page_fills_them_in(self):
        """The other half, and the dangerous one. A field that renders but is
        never filled looks like a setting that was never saved - and the next
        save writes that emptiness over the real value. Nothing above would
        notice: the save reads the control, and the control would be blank."""
        shown = self._populate({
            "report": {"client_name": "Northwind Traders",
                       "prepared_by": "A. Surveyor",
                       "project_ref": "PO-2026-0042",
                       "revision": "Rev B",
                       "include_revision_in_filename": False},
        })
        self.assertEqual(shown["values"].get("sRepClient"), "Northwind Traders")
        self.assertEqual(shown["values"].get("sRepPreparedBy"), "A. Surveyor")
        self.assertEqual(shown["values"].get("sRepProjectRef"), "PO-2026-0042")
        self.assertEqual(shown["values"].get("sRepRevision"), "Rev B")
        self.assertIs(shown["checked"].get("sRepIncludeRev"), False)

    def test_the_filename_switch_defaults_to_on_when_nothing_is_saved(self):
        shown = self._populate({"report": {}})
        self.assertIs(shown["checked"].get("sRepIncludeRev"), True,
                      "an install that has never touched this must show it on, "
                      "because on is what the tool does")

    def _populate(self, settings: dict) -> dict:
        program = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  function populate() {');
        if (a < 0) throw new Error('populate moved');
        // The matching close brace, counted. Searching for a two-space
        // `}` finds it inside a four-space one, and slicing to wherever
        // the next function starts swallows anything inserted between
        // them - both have already cost a green run here.
        let b = a, depth = 0, seen = false;
        while (b < src.length && !(seen && depth === 0)) {
          if (src[b] === '{') { depth++; seen = true; }
          else if (src[b] === '}') depth--;
          b++;
        }

        const settings = JSON.parse(process.argv[2]);
        const values = {}, checked = {};
        const el = (id) => ({
          set value(v) { values[id] = v; }, get value() { return values[id]; },
          set checked(v) { checked[id] = v; }, get checked() { return checked[id]; },
        });
        const cache = {};
        global.document = {
          getElementById: (id) => (cache[id] = cache[id] || el(id)),
          querySelectorAll: () => { const a = []; a.forEach = Array.prototype.forEach; return a; },
        };
        const renderSubfolders = () => {}, renderCustomDests = () => {};
        const renderReportOverrideNote = () => {};
        eval(src.slice(a, b));
        populate();
        console.log(JSON.stringify({ values: values, checked: checked }));
        """
        r = subprocess.run(
            ["node", "-e", program, str(SETTINGS_JS), json.dumps(settings)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_filename_switch_is_written_both_ways(self):
        on = self._patch({}, ["sRepIncludeRev"])
        self.assertIs(on["report"]["include_revision_in_filename"], True)
        off = self._patch({}, [])
        self.assertIs(off["report"]["include_revision_in_filename"], False)

    def test_saving_report_defaults_does_not_disturb_the_other_tools(self):
        """One patch carries every section, so a new block is a chance to
        drop an old one."""
        patch = self._patch({"sRepClient": "Northwind Traders"}, [])
        for section in ("global", "organizer", "cloud", "walls", "report"):
            self.assertIn(section, patch, "the save dropped the %s section" % section)

@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheGearLandsOnTheControls(unittest.TestCase):
    """Cloud Manager's Settings modal was removed, so its gear button now
    navigates to the Settings page instead. That only replaces what was taken
    away if the person who clicked it can see the controls when they arrive.

    Both halves are executed rather than read. `openSettings` is run to get the
    URL it really navigates to, and the hash from that URL is fed to the real
    `openHashSection` against a document that knows only the ids `settings.html`
    actually contains - so a hash naming a section that does not exist, or one
    that opens the section below the fold without scrolling to it, fails here.
    """

    def _gear_url(self) -> str:
        program = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('function openSettings() {');
        if (a < 0) throw new Error('openSettings moved');
        const b = src.indexOf('}', a) + 1;
        let href = null;
        global.window = { location: { set href(v) { href = v; }, get href() { return href; } } };
        eval(src.slice(a, b));
        openSettings();
        console.log(JSON.stringify(href));
        """
        r = subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def _arrive(self, hash_: str) -> dict:
        ids = sorted(set(re.findall(r'id="(sec-[^"]+)"',
                                    SETTINGS_HTML.read_text(encoding="utf-8"))))
        program = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        // The function's own closing brace, not "wherever the next function
        // starts": a slice that runs to the next declaration swallows anything
        // inserted between them, which has already happened once. No line
        // ending appears in the search, so CRLF and LF both work.
        const a = src.indexOf('  function openHashSection() {');
        if (a < 0) throw new Error('openHashSection moved');
        // The matching close brace, counted. Searching for a two-space
        // `}` finds it inside a four-space one, and slicing to wherever
        // the next function starts swallows anything inserted between
        // them - both have already cost a green run here.
        let b = a, depth = 0, seen = false;
        while (b < src.length && !(seen && depth === 0)) {
          if (src[b] === '{') { depth++; seen = true; }
          else if (src[b] === '}') depth--;
          b++;
        }

        const ids = JSON.parse(process.argv[3]);
        const found = {};
        global.location = { hash: process.argv[2] };
        global.document = {
          getElementById: (id) => {
            if (ids.indexOf(id) < 0) return null;
            return (found[id] = { id: id, open: false,
                                  scrollIntoView() { this.scrolled = true; } });
          },
        };
        eval(src.slice(a, b));
        openHashSection();
        const el = Object.values(found)[0] || null;
        console.log(JSON.stringify(el ? { id: el.id, open: el.open,
                                          scrolled: !!el.scrolled } : null));
        """
        r = subprocess.run(
            ["node", "-e", program, str(SETTINGS_JS), hash_, json.dumps(ids)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_gear_names_a_section_that_exists(self):
        url = self._gear_url()
        self.assertTrue(url, "the gear button navigated nowhere")
        self.assertIn("#", url,
                      "the gear drops the person at the top of the Settings "
                      "page instead of at the Cloud Manager section")
        landed = self._arrive("#" + url.split("#", 1)[1])
        self.assertIsNotNone(
            landed,
            "the gear asks for a section `settings.html` does not have, so it "
            "opens nothing: " + url)

    def test_arriving_opens_the_section_and_scrolls_to_it(self):
        url = self._gear_url()
        landed = self._arrive("#" + url.split("#", 1)[1])
        self.assertTrue(landed["open"],
                        "the section was left collapsed, so the controls the "
                        "gear was clicked for are not on screen")
        self.assertTrue(landed["scrolled"],
                        "the section opened below the fold and nothing scrolled "
                        "to it - the Settings page is eight sections long")

    def test_a_hash_for_no_section_is_harmless(self):
        self.assertIsNone(self._arrive("#nosuchthing"))
        self.assertIsNone(self._arrive(""))


if __name__ == "__main__":
    unittest.main()
