"""The default wall template is chosen, not inherited from the last Apply.

`getDefaultTemplate()` in `walls.js` decides two things: which option the
Template bar's picker starts on, and - the one that matters - which template
**Auto-apply on open** puts into every project as it is opened.

Nothing ever chose it. `applySelectedTemplate()` ended with
`setLastTemplate(name)`, so the value was simply whatever template was last
applied. Pressing **Apply** on Ekahau Default once, to start one project's wall
list over, made Ekahau Default the template every project opened afterwards was
given - silently, with no control anywhere to see it or put it back. The
registry called it "Default wall template" and there was no such control.

There is one now, on the Settings page under Quick Walls, and the implicit
write is gone. These hold both halves, by running the real functions:

  * applying a template must not write `default_template`;
  * the Settings page must offer the templates that exist, keep a saved value
    that names a template which has since been deleted rather than quietly
    replacing it, and never write an empty default just because the template
    list has not arrived yet.

That last one is the merge rule of v2.149.0 wearing different clothes: a
control that defaults to empty when it cannot see its options will erase a
saved value the first time anything else on the page is saved.
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
WALLS_JS = WEB / "assets" / "js" / "walls.js"
SETTINGS_JS = WEB / "assets" / "js" / "settings-page.js"
SETTINGS_HTML = WEB / "settings.html"
REGISTRY = WEB / "assets" / "settings-registry.json"
NODE_TIMEOUT_S = 120


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ApplyingATemplateDoesNotChangeTheDefault(unittest.TestCase):
    """The real `applySelectedTemplate`, run against recording stubs."""

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('async function applySelectedTemplate()');
        if (a < 0) throw new Error('applySelectedTemplate moved');
        let b = a, depth = 0, seen = false;
        while (b < src.length && !(seen && depth === 0)) {
          if (src[b] === '{') { depth++; seen = true; }
          else if (src[b] === '}') depth--;
          b++;
        }

        const writes = [];
        const chosen = process.argv[2];
        globalThis.document = { getElementById: () => ({ value: chosen }) };
        globalThis.getTemplates = () => ([
          { name: 'WD Template', wallTypes: [{ name: 'Drywall' }] },
          { name: 'Ekahau Default', wallTypes: [{ name: 'Brick' }] },
        ]);
        globalThis.mergeTemplateTypes = () => ({ added: 1, updated: 0, kept: [] });
        globalThis.renderAll = () => {};
        globalThis.keptPhrase = () => '';
        globalThis.showToast = (m) => writes.push('toast');
        globalThis.wallTypes = [{ name: 'Drywall' }];
        globalThis._ekahauDefaults = { wallTypes: [{ name: 'Brick' }] };
        // Anything that would persist the default. If the code under test
        // calls one of these, the old behaviour is back.
        globalThis.setLastTemplate = (n) => writes.push('setLastTemplate:' + n);
        globalThis._persistWallsPref = (p) => writes.push('persist:' + JSON.stringify(p));
        globalThis.WD = { api: (action, body) => {
          writes.push('api:' + action + ':' + JSON.stringify(body || {}));
          return Promise.resolve({ ok: true });
        } };

        eval(src.slice(a, b));
        Promise.resolve(applySelectedTemplate()).then(function () {
          console.log(JSON.stringify(writes));
        }).catch(function (e) {
          console.log(JSON.stringify(['ERROR:' + e.message]));
        });
    """

    def writes_for(self, template_name: str) -> list:
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(WALLS_JS), template_name],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_applying_writes_no_preference_at_all(self):
        writes = self.writes_for("Ekahau Default")
        offenders = [w for w in writes if not w.startswith("toast")]
        self.assertEqual(
            offenders, [],
            "applying a template to this project changed what every later "
            "project gets: " + ", ".join(offenders))

    def test_it_still_applies_the_template(self):
        """The removal must not take the feature with it."""
        self.assertIn("toast", self.writes_for("WD Template"),
                      "Apply stopped doing anything at all")

    # There is deliberately no "walls.js contains no writer" assertion here.
    # It was written and removed: `loadWallsPrefs` legitimately writes
    # `default_template` once, carrying the pre-settings.json browser value
    # across, so the check only passed by matching a spelling that migration
    # happens not to use. `test_applying_writes_no_preference_at_all` above
    # runs the path that actually had the bug.


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheSettingsControlOffersWhatExists(unittest.TestCase):
    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  function renderDefaultTemplateChoices(');
        if (a < 0) throw new Error('renderDefaultTemplateChoices moved');
        let b = a, depth = 0, seen = false;
        while (b < src.length && !(seen && depth === 0)) {
          if (src[b] === '{') { depth++; seen = true; }
          else if (src[b] === '}') depth--;
          b++;
        }

        const templates = JSON.parse(process.argv[2]);
        const saved = process.argv[3];
        const sel = { innerHTML: '', value: null };
        const note = { hidden: null, textContent: '' };
        // When argv[4] is given it is the set of ids the real page has, so
        // an id the registry names and the page lacks resolves to null here
        // exactly as it would in a browser.
        const known = process.argv[4] ? JSON.parse(process.argv[4]) : null;
        const has = (id) => (known === null || known.indexOf(id) > -1);
        globalThis.document = { getElementById: (id) =>
          (id === 'sWallsDefaultTpl' && has(id) ? sel
           : id === 'sWallsDefaultTplMissing' && has(id) ? note : null) };
        const WD = { esc: (s) => String(s), escAttr: (s) => String(s) };

        eval(src.slice(a, b));
        renderDefaultTemplateChoices(templates, saved);
        const options = [];
        const RE = /<option value="([^"]*)">([^<]*)<\/option>/g;
        let m;
        while ((m = RE.exec(sel.innerHTML))) options.push([m[1], m[2]]);
        console.log(JSON.stringify({ options: options, value: sel.value,
                                     noteHidden: note.hidden,
                                     note: note.textContent }));
    """

    def render(self, templates, saved):
        return self.render_with_ids(templates, saved, None)

    def render_with_ids(self, templates, saved, ids):
        """`ids` limits which element ids the stub document knows about, so a
        caller can hand it the ids `settings.html` really has."""
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(SETTINGS_JS),
             json.dumps(templates), saved,
             json.dumps(ids) if ids is not None else ""],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    TEMPLATES = [{"name": "WD Template"}, {"name": "Ekahau Default"},
                 {"name": "Site standard"}]

    def test_every_saved_template_is_offered(self):
        got = self.render(self.TEMPLATES, "")
        names = [v for v, _ in got["options"]]
        for t in ("WD Template", "Ekahau Default", "Site standard"):
            self.assertIn(t, names)

    def test_there_is_a_way_to_turn_it_off(self):
        """Auto-apply with no default already does nothing. Offering that
        state explicitly is the difference between a setting he can clear and
        one he can only point somewhere else."""
        got = self.render(self.TEMPLATES, "")
        self.assertIn("", [v for v, _ in got["options"]],
                      "there is no None option, so a default cannot be removed")
        self.assertEqual(got["value"], "")

    def test_the_saved_one_is_the_one_selected(self):
        got = self.render(self.TEMPLATES, "Site standard")
        self.assertEqual(got["value"], "Site standard")

    def test_a_deleted_template_is_kept_and_explained(self):
        """His setting, not ours to clear - and silently snapping to another
        template would change what auto-apply puts in his projects."""
        got = self.render(self.TEMPLATES, "Old site pack")
        self.assertIn("Old site pack", [v for v, _ in got["options"]],
                      "the saved value was dropped, so saving the page would "
                      "replace it with whatever happened to be first")
        self.assertEqual(got["value"], "Old site pack")
        self.assertIs(got["noteHidden"], False,
                      "nothing tells him auto-apply is doing nothing")
        self.assertIn("Auto-apply", got["note"])

    def test_no_such_warning_when_the_default_is_real(self):
        for saved in ("Site standard", ""):
            with self.subTest(saved=saved):
                self.assertIs(self.render(self.TEMPLATES, saved)["noteHidden"], True)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class SavingDoesNotEraseADefaultItCannotSee(unittest.TestCase):
    """The v2.149.0 merge-rule shape. The template list is fetched separately
    from the settings, so the select can legitimately be empty when a save
    happens - and writing '' then turns his default off for him."""

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  SP.save = function () {');
        const b = src.indexOf('  SP.exportSettings');
        if (a < 0 || b < 0) throw new Error('SP.save moved');

        const optionCount = parseInt(process.argv[2], 10);
        const selected = process.argv[3];
        const settings = { walls: { default_template: 'Site standard' },
                           cloud: {}, report: {} };
        const blank = { value: '', checked: false, options: { length: 0 } };
        globalThis.document = {
          getElementById: (id) => (id === 'sWallsDefaultTpl'
            ? { value: selected, options: { length: optionCount } }
            : blank),
          querySelectorAll: () => [],
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

    def patch(self, option_count, selected):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(SETTINGS_JS),
             str(option_count), selected],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_an_unpopulated_select_keeps_the_saved_default(self):
        patch = self.patch(0, "")
        self.assertEqual(
            patch["walls"]["default_template"], "Site standard",
            "saving the page before the template list arrived turned his "
            "default template off")

    def test_a_populated_select_is_believed(self):
        self.assertEqual(self.patch(3, "WD Template")["walls"]["default_template"],
                         "WD Template")

    def test_choosing_none_really_clears_it(self):
        """The other direction, and it has to work or None is decoration."""
        self.assertEqual(self.patch(3, "")["walls"]["default_template"], "",
                         "None was ignored, so the default cannot be removed")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheTemplateBarSaysWhatAutoApplyWillDo(unittest.TestCase):
    """`Auto-apply on open` used to be a tick box with no statement of what it
    would apply, which was survivable only while the answer was "whatever you
    last applied" and therefore in recent memory. The template is set on
    another page now, so the bar says which one - beside the control rather
    than in a tooltip, because it is a decision rather than a detail.

    The third state is the one worth the code: the default naming a template
    that has since been deleted, where the tick box is on and nothing happens.
    """

    PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('function renderAutoApplyNote(');
        if (a < 0) throw new Error('renderAutoApplyNote moved');
        let b = a, depth = 0, seen = false;
        while (b < src.length && !(seen && depth === 0)) {
          if (src[b] === '{') { depth++; seen = true; }
          else if (src[b] === '}') depth--;
          b++;
        }

        const def = process.argv[2] === '' ? null : process.argv[2];
        const tpls = JSON.parse(process.argv[3]);
        const classes = [];
        const host = { innerHTML: '', classList: {
          add: (c) => classes.push(c),
          remove: (c) => { const i = classes.indexOf(c); if (i > -1) classes.splice(i, 1); },
        } };
        globalThis.document = { getElementById: () => host };
        globalThis.getDefaultTemplate = () => def;
        globalThis.esc = (s) => String(s);

        eval(src.slice(a, b));
        renderAutoApplyNote(tpls);
        console.log(JSON.stringify({ html: host.innerHTML, classes: classes }));
    """

    TEMPLATES = [{"name": "WD Template"}, {"name": "Site standard"}]

    def note(self, default_name, templates=None):
        r = subprocess.run(
            ["node", "-e", self.PROBE, str(WALLS_JS), default_name,
             json.dumps(self.TEMPLATES if templates is None else templates)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_it_names_the_template_that_will_be_applied(self):
        got = self.note("Site standard")
        self.assertIn("Site standard", got["html"],
                      "the tick box does not say what it will apply")
        self.assertNotIn("is-missing", got["classes"])

    def test_it_says_when_there_is_no_default(self):
        got = self.note("")
        self.assertIn("No default", got["html"])
        self.assertNotIn("is-missing", got["classes"])

    def test_a_deleted_default_is_called_out_rather_than_named_as_normal(self):
        got = self.note("Old site pack")
        self.assertIn("Old site pack", got["html"])
        self.assertIn("no longer exists", got["html"],
                      "the tick box is on and nothing will happen, and this "
                      "reads exactly like the working case")
        self.assertIn("is-missing", got["classes"])

    def test_it_points_at_the_page_that_sets_it(self):
        """A statement of a setting he cannot act on is half a message."""
        for name in ("Site standard", "", "Old site pack"):
            with self.subTest(default=name):
                self.assertIn("/settings#walls", self.note(name)["html"])

    REFRESH_PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('async function refreshTemplateBar()');
        if (a < 0) throw new Error('refreshTemplateBar moved');
        let b = a, depth = 0, seen = false;
        while (b < src.length && !(seen && depth === 0)) {
          if (src[b] === '{') { depth++; seen = true; }
          else if (src[b] === '}') depth--;
          b++;
        }

        let noteRendered = false;
        const els = {
          templateSelect: { innerHTML: '', value: 'WD Template' },
          autoApplyCheck: { checked: false },
          tplApplyBtn: { disabled: false },
        };
        globalThis.document = { getElementById: (id) => els[id] || null };
        globalThis.loadTemplatesFromServer = () => Promise.resolve();
        globalThis.ensureEkahauDefaultsLoaded = () => Promise.resolve();
        globalThis._tplCache = [{ name: 'WD Template', wallTypes: [1] }];
        globalThis._ekahauDefaults = null;
        globalThis.getDefaultTemplate = () => 'WD Template';
        globalThis.getAutoApply = () => true;
        globalThis.esc = (s) => String(s);
        globalThis.escAttr = (s) => String(s);
        globalThis.renderAutoApplyNote = () => { noteRendered = true; };

        eval(src.slice(a, b));
        Promise.resolve(refreshTemplateBar()).then(function () {
          console.log(JSON.stringify({ noteRendered: noteRendered }));
        }).catch(function (e) {
          console.log(JSON.stringify({ error: e.message }));
        });
    """

    def test_the_bar_actually_renders_the_note(self):
        """The other half, and the one a direct call cannot see: a renderer
        nothing calls produces no note at all, and every assertion above would
        still pass."""
        r = subprocess.run(
            ["node", "-e", self.REFRESH_PROBE, str(WALLS_JS)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        got = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertIsNone(got.get("error"), got.get("error"))
        self.assertTrue(got.get("noteRendered"),
                        "the template bar never asks for the note, so nothing "
                        "on that screen says which template auto-apply uses")

    ARRIVE_PROBE = r"""
        const fs = require('fs');
        const src = fs.readFileSync(process.argv[1], 'utf8');
        const a = src.indexOf('  function openHashSection() {');
        if (a < 0) throw new Error('openHashSection moved');
        let b = a, depth = 0, seen = false;
        while (b < src.length && !(seen && depth === 0)) {
          if (src[b] === '{') { depth++; seen = true; }
          else if (src[b] === '}') depth--;
          b++;
        }

        const ids = JSON.parse(process.argv[3]);
        let landed = null;
        global.location = { hash: process.argv[2] };
        global.document = { getElementById: (id) => (ids.indexOf(id) < 0 ? null
          : (landed = { id: id, open: false,
                        scrollIntoView() { this.scrolled = true; } })) };
        eval(src.slice(a, b));
        openHashSection();
        console.log(JSON.stringify(landed
          ? { id: landed.id, open: landed.open, scrolled: !!landed.scrolled }
          : null));
    """

    def test_the_link_lands_on_the_quick_walls_section(self):
        """Not "the page contains that id" - the link is followed. The hash
        is taken from the note this code really renders, and handed to the
        Settings page's own handler against the sections that page really
        has, so a renamed section or a mistyped hash fails here rather than
        dropping him at the top of a long page."""
        html = self.note("Site standard")["html"]
        self.assertIn("#", html, "the note links nowhere")
        hash_ = "#" + html.split('href="/settings', 1)[1].split('"', 1)[0].lstrip("#")
        ids = sorted(set(re.findall(r'id="(sec-[^"]+)"',
                                    SETTINGS_HTML.read_text(encoding="utf-8"))))
        r = subprocess.run(
            ["node", "-e", self.ARRIVE_PROBE, str(SETTINGS_JS), hash_,
             json.dumps(ids)],
            capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        landed = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertIsNotNone(
            landed, "the template bar links to a Settings section that does "
                    "not exist, so the link lands at the top of the page: " + hash_)
        self.assertTrue(landed["open"] and landed["scrolled"],
                        "the section was reached but not opened and scrolled to")

class TheRegistryAgrees(unittest.TestCase):
    def test_it_records_the_control_and_where_it_lives(self):
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        entry = next(r for r in reg["settings"]
                     if r.get("key") == "walls.default_template")
        self.assertEqual(entry.get("home"), "settings")
        self.assertEqual(entry.get("control"), "sWallsDefaultTpl")

    def test_the_control_it_names_really_renders(self):
        """Run rather than read: the renderer is given a document holding
        only the ids `settings.html` actually has, so a control the registry
        names and the page does not have produces no options at all."""
        ids = set(re.findall(r'id="([^"]+)"',
                             SETTINGS_HTML.read_text(encoding="utf-8")))
        got = TheSettingsControlOffersWhatExists().render_with_ids(
            [{"name": "WD Template"}], "", sorted(ids))
        self.assertTrue(
            got["options"],
            "the registry names sWallsDefaultTpl and nothing on the Settings "
            "page has that id, so the control renders nothing")


if __name__ == "__main__":
    unittest.main()
