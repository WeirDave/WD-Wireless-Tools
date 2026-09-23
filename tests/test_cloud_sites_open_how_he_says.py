"""How the Sites tree opens is his choice, and it sticks.

"I want them expanded - all of them - and I want it to stick."

The site-first redesign shipped one answer: a site holding something that
needs a decision opens, and a site with nothing to say stays shut. That was
a reasonable judgement - opening ninety sites at once was the wall the
redesign existed to remove, and a list of names with nothing under them was
the wall before it. It was still a judgement about his list rather than a
fact about it, and there was no way for him to disagree.

So it is `cloud.tree_default_open`, a preference: server-side in
`settings.json`, one control on the Settings page, and it follows him to
another machine. `attention` stays the shipped default so nobody else's
install changes.

**Expand all and Collapse all are unaffected.** They are this-visit controls
and always were; the setting decides what he opens on, which is the thing
that was resetting.

Driven through the real `closeSitesOnFirstSight`, because the question is
what the tree does rather than what the value is.

Every site and project name here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
REGISTRY = ROOT / "web" / "assets" / "settings-registry.json"
NODE_TIMEOUT_S = 120


class TheDefaultIsDeclaredAndUnchanged(unittest.TestCase):

    def test_the_server_ships_the_old_behaviour(self):
        """Adding a choice must not move anybody who never makes one."""
        from tools import settings
        self.assertEqual("attention",
                         settings.DEFAULTS["cloud"]["tree_default_open"])

    def test_it_is_declared_as_a_preference(self):
        """A preference follows the person and lives server-side. In
        `localStorage` it would be per-browser, which is the two-store bug
        the registry exists to stop."""
        entries = json.loads(REGISTRY.read_text(encoding="utf-8"))["settings"]
        mine = [e for e in entries if e.get("key") == "cloud.tree_default_open"]
        self.assertEqual(1, len(mine), "not declared, or declared twice")
        self.assertEqual("preference", mine[0]["category"])
        self.assertEqual("settings", mine[0]["home"])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheTreeOpensTheWayHeSaidTests(unittest.TestCase):
    """`closeSitesOnFirstSight` decides which sites start closed."""

    PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
function cut(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
const sandbox = { console, JSON, Math, Set, Map, RegExp, Number, String, Boolean, Object };
vm.createContext(sandbox);
const mode = process.argv[3];
vm.runInContext(
    'let collapsed = new Set();'
  + 'let currentTab = "sites";'
  + 'let _treeClosedFor = null;'
  + 'let _treeOpenMode = ' + JSON.stringify(mode) + ';'
  + 'function _passOwnerForCounts(){ return true; }'
  + 'function isOutOfSync(r){ return !!(r && r.staleness); }'
  + cut('function siteDigest(', '\nfunction siteDigestHtml(')
  + cut('function closeSitesOnFirstSight(', '\nfunction collapseAllSites('),
  sandbox);
sandbox.data = JSON.parse(process.argv[2]);
vm.runInContext('closeSitesOnFirstSight()', sandbox);
process.stdout.write(vm.runInContext(
  'JSON.stringify(Array.from(collapsed).sort())', sandbox));
"""

    @staticmethod
    def _site(cid, *, needs):
        """One site. `needs` decides whether anything in it wants him."""
        kid = {
            "cloud": {"id": cid + "-p", "name": "SITE1 Riverside Survey",
                      "mtime": 2000, "owner": "me@example.invalid"},
            "local": {"path": "D:\\E\\SITE1 Riverside\\Survey.esx",
                      "name": "SITE1 Riverside Survey", "mtime": 1000},
            "matchType": "id", "namesDiffer": False,
            "staleness": "cloud_newer" if needs else None,
            "comparison": None,
        }
        children = {"matched": [kid], "cloudOnly": [], "localOnly": []}
        return {
            "cloud": {"id": cid, "name": "SITE" + cid, "children": children,
                      "owner": "me@example.invalid"},
            "local": {"path": "D:\\E\\SITE" + cid, "name": "SITE" + cid,
                      "isDir": True, "children": children},
            "matchType": "exact", "staleness": None, "namesDiffer": False,
        }

    def closed(self, mode):
        data = {"currentUser": "me@example.invalid",
                "matched": [self._site("A", needs=True),
                            self._site("B", needs=False)],
                "cloudOnly": [], "localOnly": [],
                "orphans": {"cloudOnly": [], "localOnly": []}}
        r = subprocess.run(
            ["node", "-e", self.PROGRAM, str(CLOUD_JS), json.dumps(data), mode],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError("probe failed:\n" + (r.stderr or "")[-2500:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_all_opens_every_site(self):
        """What he asked for: nothing starts closed."""
        self.assertEqual([], self.closed("all"))

    def test_attention_keeps_the_shipped_split(self):
        """The site with work opens; the finished one stays shut."""
        self.assertEqual(["site:B"], self.closed("attention"))

    def test_none_closes_every_site(self):
        self.assertEqual(["site:A", "site:B"], self.closed("none"))

    def test_every_value_the_page_offers_does_something_different(self):
        """A radio the reader cannot act on is worse than no radio.

        Read from the registry and *run*, rather than checked for as a
        string in `cloud.js`: the question is whether picking it changes
        what the tree does, and a value that appears in the source and is
        never reached would satisfy a substring and nothing else.
        """
        values = json.loads(REGISTRY.read_text(encoding="utf-8"))["settings"]
        declared = [e for e in values
                    if e.get("key") == "cloud.tree_default_open"][0]["values"]
        seen = {}
        for value in declared:
            with self.subTest(value=value):
                seen[value] = tuple(self.closed(value))
        self.assertEqual(
            len(set(seen.values())), len(seen),
            "two of the offered values open the tree identically, so one of "
            "them is a radio that does nothing: %s" % seen)

    def test_an_unknown_value_falls_back_to_the_shipped_behaviour(self):
        """A settings file edited by hand, or a value from a newer build,
        must not produce a fourth behaviour nobody designed."""
        self.assertEqual(["site:B"], self.closed("something-else"))


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheSettingsPageSavesItTests(unittest.TestCase):
    """The page half: read the saved value, and send it back on save.

    A control that renders and is dropped from the patch is the shape this
    repository keeps finding - the report orientation setting posted the
    wrong envelope and saved nothing while reporting success.
    """

    PROGRAM = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const radios = {};
function mk(name, value) {
  return {name: name, value: value, checked: false, type: 'radio'};
}
['all','attention','none'].forEach(v => {
  (radios.setTreeOpen = radios.setTreeOpen || []).push(mk('setTreeOpen', v));
});
['all','mine','others'].forEach(v => {
  (radios.setowner = radios.setowner || []).push(mk('setowner', v));
});
globalThis.document = {
  querySelectorAll: (sel) => {
    const m = /name="([^"]+)"/.exec(sel);
    const list = (m && radios[m[1]]) || [];
    list.forEach = Array.prototype.forEach.bind(list);
    return list;
  },
  getElementById: () => ({ value: '', checked: false, textContent: '' }),
};
const saved = JSON.parse(process.argv[2]);
// The two functions under test, taken whole out of the shipped file.
const a = src.indexOf('    var treeOpen = c.tree_default_open');
if (a < 0) throw new Error('the read half is gone');
const readLine = src.slice(a, src.indexOf('});', a) + 3);
eval('(function(c){' + readLine + '})(saved.cloud || {})');
process.stdout.write(JSON.stringify({
  checked: (radios.setTreeOpen.find(r => r.checked) || {}).value || null,
}));
"""

    SAVE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const checked = process.argv[2];

/* The save function, sliced out rather than the whole file evaluated.

   Evaluating the module runs its `init()`, which wants a page. Counting
   braces from the declaration is the pattern this suite uses, and the
   `if (a < 0) throw` matters: without it a renamed function slices from
   index -1 and the probe silently tests something else. */
const a = src.indexOf('  SP.save = function () {');
if (a < 0) throw new Error('SP.save has moved or been renamed');
let b = a, depth = 0, seen = false;
while (b < src.length && !(seen && depth === 0)) {
  if (src[b] === '{') { depth++; seen = true; }
  else if (src[b] === '}') depth--;
  b++;
}
/* Both ends come off: the header, and the `}` the brace count stopped on.
   Leaving the closing brace makes `new Function` throw on an unexpected
   token, which reads like the page is broken rather than the slice. */
const whole = src.slice(a, b);
const body = whole
  .replace('  SP.save = function () {', '')
  .replace(/\}\s*$/, '');

const radios = {setTreeOpen: [], setowner: [], mergeRule: []};
const mk = (name, value, on) => ({name, value, checked: !!on, type: 'radio'});
['all','attention','none'].forEach(v =>
  radios.setTreeOpen.push(mk('setTreeOpen', v, v === checked)));
['all','mine','others'].forEach(v =>
  radios.setowner.push(mk('setowner', v, v === 'mine')));
['ask','newer','both','skip'].forEach(v =>
  radios.mergeRule.push(mk('mergeRule', v, v === 'newer')));

/* Everything the real `SP.save` touches on an element. Stubbing one
   property at a time and re-running is the slow way; the failure it
   produces ("cannot read 'length' of undefined") reads like the page is
   broken rather than like the stub is thin, so the list is generous. */
const field = () => ({ value: '', checked: false, textContent: '',
                       innerHTML: '', style: {}, options: [],
                       selectedIndex: -1, dataset: {}, disabled: false,
                       files: [], children: [],
                       classList: { add(){}, remove(){}, toggle(){},
                                    contains(){ return false; } },
                       querySelectorAll: () => [], querySelector: () => null,
                       addEventListener(){}, appendChild(){} });
const document = {
  querySelectorAll: (sel) => {
    const m = /name="([^"]+)"/.exec(sel);
    const list = (m && radios[m[1]]) || [];
    list.forEach = Array.prototype.forEach.bind(list);
    return list;
  },
  getElementById: field,
};
const sent = [];
const API = (endpoint, payload) => {
  sent.push({endpoint, payload});
  return Promise.resolve({ ok: true });
};
const settings = {cloud: {default_owner_filter: 'mine', merge_rule: 'newer'}};
const _subfolders = [], _subfolderNames = {};
const collectCustomDests = () => [];
const splitComma = (s) => [];
const announceSave = () => {};
const toast = () => {};
/* Read off the function rather than discovered one failure at a time:
     sed -n '/SP.save = function/,/^  };/p' settings-page.js |
       grep -oE "[a-zA-Z_][a-zA-Z0-9_.]*\(" | sort -u
   Leaving one out stops the body partway, which would hide a write that
   comes after it. */
const loadOverviews = () => {};
const loadWallTemplates = () => {};

const WD = { escAttr: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
             esc: s => String(s == null ? '' : s), toast(){} };

const NAMES = ['document','API','settings','_subfolders','_subfolderNames',
               'collectCustomDests','splitComma','announceSave','toast',
               'loadOverviews','loadWallTemplates','WD'];
const VALUES = [document, API, settings, _subfolders, _subfolderNames,
                collectCustomDests, splitComma, announceSave, toast,
                loadOverviews, loadWallTemplates, WD];
new Function(...NAMES, body)(...VALUES);

setTimeout(() => {
  const call = sent.find(c => /settings\/update/.test(c.endpoint)) || sent[0] || {};
  process.stdout.write(JSON.stringify({
    endpoint: call.endpoint || null,
    patch: (call.payload && call.payload.patch) || null,
  }));
  process.exit(0);
}, 30);
"""

    def run_save(self, checked):
        r = subprocess.run(
            ["node", "-e", self.SAVE,
             str(ROOT / "web" / "assets" / "js" / "settings-page.js"), checked],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError("save probe failed: "
                                 + (r.stdout + r.stderr).strip()[-2000:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def run_js(self, saved):
        r = subprocess.run(
            ["node", "-e", self.PROGRAM,
             str(ROOT / "web" / "assets" / "js" / "settings-page.js"),
             json.dumps(saved)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError("probe failed:\n" + (r.stderr or "")[-2000:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_saved_value_is_the_one_ticked(self):
        got = self.run_js({"cloud": {"tree_default_open": "all"}})
        self.assertEqual("all", got["checked"])

    def test_nothing_saved_shows_the_shipped_default(self):
        got = self.run_js({"cloud": {}})
        self.assertEqual("attention", got["checked"])

    def test_saving_actually_sends_it(self):
        """`SP.save` is run and the request it makes is read back.

        Checking that the key appears in the `cloud` block of the source
        would be an assertion about characters - and this repository has
        shipped five defects behind exactly that, the nearest being the
        report orientation setting, which posted a patch the server did not
        read and reported success. So the real save runs against a stub API
        and the patch it sends is the thing asserted.
        """
        got = self.run_save(checked="all")
        self.assertEqual("settings/update", got["endpoint"])
        self.assertEqual("all", got["patch"]["cloud"]["tree_default_open"],
                         "the page saved everything except this")

    def test_saving_does_not_disturb_the_setting_beside_it(self):
        """The two radio groups are read by the same loop shape, and a
        mistake there is silent."""
        got = self.run_save(checked="none")
        self.assertEqual("none", got["patch"]["cloud"]["tree_default_open"])
        self.assertIn("default_owner_filter", got["patch"]["cloud"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
