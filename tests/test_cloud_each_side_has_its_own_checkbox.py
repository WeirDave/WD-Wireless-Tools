"""Ticking the cloud side must not delete the local file as well.

A matched row has a checkbox on each side, and the two are meant to be
independent: a cloud delete cannot be undone and a local one can be (download
it again), so they are not the same decision and must not be one control.

The Sites tab gives each side its own key (`s-c:` / `s-l:`) and so do nested
project rows (`ct-c:` / `ct-l:`). The **Projects tab** set neither, and both
cells fall back to `r.key` - so the two checkboxes carried the same `data-k`,
one tick selected the pair, and `bulkDelete` expanded that pair into a cloud
item *and* a local item. Ticking the cloud box on the Projects tab deleted the
local `.esx` too, while the local box beside it still rendered unticked.

Since v2.141.0 nothing copies a file aside first, so the local `.esx` is gone.

**This evaluates the whole of `cloud.js`.** Slicing functions out of it means
stubbing whatever the slice missed, and a stub that invents a contract tests
the stub - which is how the `datasetId` mismatch shipped green. The file is a
classic script, so its top-level declarations become globals; its module state
is declared with `let`, which is why the setters are appended to the source
rather than assigned from outside.

Every project, site and path here is invented.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CLOUD_HTML = ROOT / "web" / "cloud.html"
NODE_TIMEOUT_S = 120

NODE_SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const html = fs.readFileSync(process.argv[2], 'utf8');

function mkEl(tag, attrs) {
  attrs = attrs || {};
  const classes = new Set((attrs.class || '').split(/\s+/).filter(Boolean));
  const el = {
    tagName: (tag || 'div').toUpperCase(), id: attrs.id || '',
    dataset: {}, hidden: false, textContent: '', innerHTML: '', value: '',
    disabled: false, checked: false, style: {}, children: [], _classes: classes,
    _attrs: attrs,
    classList: { add: c => classes.add(c), remove: c => classes.delete(c),
      contains: c => classes.has(c),
      toggle: (c, on) => { if (on === undefined) on = !classes.has(c);
        if (on) classes.add(c); else classes.delete(c); } },
    setAttribute: (k, v) => { el._attrs[k] = v; },
    getAttribute: k => (k in el._attrs ? el._attrs[k] : null),
    removeAttribute: k => { delete el._attrs[k]; },
    addEventListener: () => {}, removeEventListener: () => {},
    appendChild: c => { el.children.push(c); return c; },
    removeChild: () => {}, remove: () => {}, focus: () => {}, blur: () => {},
    click: () => {}, closest: () => null, contains: () => false,
    scrollIntoView: () => {},
    getBoundingClientRect: () => ({top:0,left:0,width:0,height:0,bottom:0,right:0}),
    querySelector: () => null, querySelectorAll: () => [],
    insertAdjacentHTML: () => {},
  };
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith('data-')) el.dataset[k.slice(5)] = v;
  }
  return el;
}

const ELS = [];
const tagRe = /<(button|span|div|input|details|summary|label|select|option|textarea|section|p|a|h1|h2|h3|ul|li|nav|header|footer)\b([^>]*)>/g;
let m;
while ((m = tagRe.exec(html)) !== null) {
  const attrs = {};
  let am; const aRe = /([A-Za-z_:][-A-Za-z0-9_:.]*)(?:="([^"]*)")?/g;
  while ((am = aRe.exec(m[2])) !== null) attrs[am[1]] = am[2] === undefined ? '' : am[2];
  ELS.push(mkEl(m[1], attrs));
}
const byId = new Map(ELS.filter(e => e.id).map(e => [e.id, e]));
function matches(el, sel) {
  sel = sel.trim();
  if (!sel) return false;
  const x = /^\[data-filter="([^"]+)"\]$/.exec(sel);
  if (x) return el.dataset.filter === x[1];
  if (sel === '[data-filter]') return !!el.dataset.filter;
  if (sel.startsWith('#')) return el.id === sel.slice(1);
  if (sel.startsWith('.')) {
    return sel.slice(1).split(/[.\s]/).filter(Boolean).every(c => el._classes.has(c));
  }
  return el.tagName === sel.toUpperCase();
}
globalThis.document = {
  getElementById: id => byId.get(id) || null,
  querySelectorAll: sel => ELS.filter(e => sel.split(',').some(s => matches(e, s))),
  querySelector: sel => ELS.find(e => sel.split(',').some(s => matches(e, s))) || null,
  createElement: t => mkEl(t),
  addEventListener: () => {}, removeEventListener: () => {},
  body: mkEl('body'), documentElement: mkEl('html'),
  scrollingElement: Object.assign(mkEl('html'), { scrollTop: 0 }),
};
const store = {};
globalThis.localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; },
};
globalThis.navigator = { platform: 'Win32' };
globalThis.location = { href: 'http://localhost/cloud.html', search: '' };
globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });
globalThis.requestAnimationFrame = fn => setTimeout(fn, 0);
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
const BS = String.fromCharCode(92);
const WD = {
  esc: s => String(s == null ? '' : s).replace(/[&<>"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])),
  toast: () => {}, api: async () => ({}), toggleMenu: () => {},
};
WD.escAttr = WD.esc;
WD.escJsStr = s => String(s == null ? '' : s)
  .split(BS).join(BS + BS).split("'").join(BS + "'");
globalThis.WD = WD;
globalThis.toast = () => {};
globalThis.showModal = () => {};
globalThis.hideModal = () => {};
globalThis.window = globalThis;

const tail = `
;globalThis.__set = (k, v) => {
  switch (k) {
    case 'data': data = v; break;
    case 'currentTab': currentTab = v; break;
    case 'activeFilter': activeFilter = v; break;
    case 'selected': selected = v; break;
    default: throw new Error('no setter for ' + k);
  }
};
globalThis.__rowData = () => rowData;
`;
(0, eval)(src + tail);

const ME = 'me@example.invalid';
const cloud = { id: 'c-1', name: 'SITE1 Riverside Baseline', mtime: 200,
                owner: ME, siteName: 'SITE1 Riverside', hasSite: true };
const local = { name: 'SITE1 Riverside Baseline', mtime: 200, isDir: false,
                path: 'D:/Ekahau Projects/SITE1 Riverside/SITE1 Riverside Baseline.esx' };

__set('data', { currentUser: ME, summary: { matched: 1 },
  matched: [{ cloud, local, matchType: 'id', namesDiffer: false,
              staleness: null, status: 'synced' }],
  cloudOnly: [], localOnly: [], orphans: { cloudOnly: [] } });
__set('currentTab', 'projects');
__set('activeFilter', 'all');
indexRowData();

const out = {};
const markup = renderLedger(() => true);
const keys = [...markup.matchAll(/class="row-chk"[^>]*data-k="([^"]*)"/g)].map(x => x[1]);
if (!keys.length) {
  // Fall back to any checkbox carrying a key, so a class rename does not
  // silently turn this into a test of nothing.
  for (const x of markup.matchAll(/<input[^>]*data-k="([^"]*)"[^>]*>/g)) keys.push(x[1]);
}
out.checkboxKeys = keys;
out.rowDataKeys = Object.keys(__rowData()).sort();

// Tick the cloud side only, exactly as a click would, and read back what the
// bulk bar resolved it to.
const cloudKey = keys.find(k => /(^|:)c/.test(k) && k !== keys[1]) || keys[0];
__set('selected', new Set([cloudKey]));
const resolved = [];
for (const k of [cloudKey]) {
  const d = __rowData()[k];
  resolved.push(d ? d.kind : 'missing');
}
out.tickedCloudResolvesTo = resolved;

// What the dialog says when both sides are selected. `bulkDelete` fills the
// real elements parsed out of cloud.html, so this reads back what he sees.
function dialogFor(keys) {
  __set('selected', new Set(keys));
  const sub = byId.get('deleteSub');
  const title = byId.get('deleteTitle');
  if (sub) sub.innerHTML = '';
  if (title) title.textContent = '';
  bulkDelete();
  return { sub: (sub && sub.innerHTML) || '', title: (title && title.textContent) || '' };
}
const cloudOnlyKey = keys.find(k => k.startsWith('s-c:'));
const localOnlyKey = keys.find(k => k.startsWith('s-l:'));
out.bothSides = dialogFor([cloudOnlyKey, localOnlyKey].filter(Boolean));
out.cloudOnly = dialogFor([cloudOnlyKey].filter(Boolean));

process.stdout.write(JSON.stringify(out));
process.exit(0);
"""


_PROBE = {}


def probe():
    """Run the page's own code once and cache it at module level, so neither
    class depends on which of them unittest happens to run first."""
    if not _PROBE:
        proc = subprocess.run(
            ["node", "-e", NODE_SCRIPT, str(CLOUD_JS), str(CLOUD_HTML)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError("node failed:\n" + proc.stderr)
        _PROBE.update(json.loads(proc.stdout))
    return _PROBE


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class EachSideOfAMatchedProjectIsItsOwnDecision(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_the_row_renders_two_checkboxes(self):
        self.assertEqual(2, len(self.out["checkboxKeys"]),
                         self.out["checkboxKeys"])

    def test_the_two_sides_do_not_share_one_key(self):
        """One tick must not be able to mean both sides. A cloud delete cannot
        be undone; a local one can be. They are not the same decision."""
        a, b = self.out["checkboxKeys"]
        self.assertNotEqual(a, b,
                            "both checkboxes carry the same key, so ticking "
                            "the cloud side selects the local file as well")

    def test_the_cloud_side_resolves_to_a_cloud_only_item(self):
        """Not to a pair - `bulkDelete` expands a pair into both sides."""
        self.assertEqual(["cloud"], self.out["tickedCloudResolvesTo"],
                         self.out["tickedCloudResolvesTo"])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheDeleteDialogDoesNotContradictItself(unittest.TestCase):
    """A dialog for an irreversible action cannot be wrong about what it does.

    The cloud sentence was attached to "any cloud item is selected", so a
    selection holding both sides read: "Permanently delete ... Once this runs,
    none of the cloud side will exist anymore ... **Local copies (if any) are
    not touched.**" - in adjacent sentences, while the run deleted them.
    """

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_it_does_not_promise_the_local_copy_is_safe_while_deleting_it(self):
        sub = self.out["bothSides"]["sub"].lower()
        self.assertTrue(sub, "the dialog was not filled")
        self.assertNotIn("not touched", sub,
                         "the dialog promised the local copy was untouched "
                         "while deleting it: " + sub)

    def test_a_mixed_selection_is_not_titled_as_cloud_only(self):
        self.assertNotIn("from Ekahau Cloud", self.out["bothSides"]["title"],
                         self.out["bothSides"]["title"])

    def test_a_cloud_only_selection_still_says_the_local_copy_is_safe(self):
        """The sentence is worth keeping where it is true - it is the reason
        he can delete a cloud project without worrying about his own file."""
        sub = self.out["cloudOnly"]["sub"].lower()
        self.assertIn("not touched", sub, sub)
        self.assertIn("from Ekahau Cloud", self.out["cloudOnly"]["title"])


if __name__ == "__main__":
    unittest.main()
