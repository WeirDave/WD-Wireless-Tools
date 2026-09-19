"""The Duplicates tab deletes through the same dialog as everything else.

Every destructive control on that tab - "Keep newest, delete rest", "Delete
checked", "Delete all extras", the per-row bin - funnels into
`_bulkDeleteItems`, and that called `window.confirm()` with a newline-joined
list of names and sizes. For local copies that is merely thin. For cloud
projects it is the same `delete_cloud` the main list wraps in a dialog naming
the site, the date and who else has access, on a delete nobody can undo.

Three things were wrong with it:

* **Browsers truncate a long native dialog.** "Delete all extras" can hand it
  every unmatched item in every cluster, so the one control most likely to
  destroy a lot was the one least likely to show what it was destroying. The
  main list's dialog was rewritten for exactly this - it used to show eight
  and "and 12 more".
* **It led with a size.** `_row_meta` leaves size off deliberately: cloud
  projects are stored uncompressed and local `.esx` are deflated, so the same
  project reads several times different on the two sides. In a dialog whose
  only job is "is this the one I mean?", that number is worse than none.
* **It never said who would lose access.**

The whole of `cloud.js` is evaluated, so the dialog is built by the real
function from the real markup.

Every project, site, folder and address here is invented.
"""
from __future__ import annotations

import json
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
      contains: c => classes.has(c), toggle: () => {} },
    setAttribute: (k, v) => { el._attrs[k] = v; },
    getAttribute: k => (k in el._attrs ? el._attrs[k] : null),
    removeAttribute: () => {}, addEventListener: () => {},
    removeEventListener: () => {}, appendChild: c => c, removeChild: () => {},
    remove: () => {}, focus: () => {}, blur: () => {}, click: () => {},
    closest: () => null, contains: () => false, scrollIntoView: () => {},
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
globalThis.document = {
  getElementById: id => byId.get(id) || null,
  querySelectorAll: () => [], querySelector: () => null,
  createElement: t => mkEl(t), addEventListener: () => {},
  body: mkEl('body'), documentElement: mkEl('html'),
  scrollingElement: Object.assign(mkEl('html'), { scrollTop: 0 }),
};
const store = {};
globalThis.localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; },
};
globalThis.navigator = { platform: 'Win32' };
globalThis.location = { href: 'http://localhost/cloud.html', search: '' };
globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });
globalThis.requestAnimationFrame = fn => setTimeout(fn, 0);
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
const BS = String.fromCharCode(92);
const WD = { esc: s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])),
  toast: () => {}, api: async () => ({}), toggleMenu: () => {} };
WD.escAttr = WD.esc;
WD.escJsStr = s => String(s == null ? '' : s)
  .split(BS).join(BS + BS).split("'").join(BS + "'");
globalThis.WD = WD;
globalThis.toast = () => {};
globalThis.hideModal = () => {};
globalThis.window = globalThis;

// A native dialog here is the defect. If one is reached, the probe says so.
let nativeConfirms = 0;
globalThis.confirm = () => { nativeConfirms++; return false; };

const tail = `
;globalThis.__set = (k, v) => {
  switch (k) {
    case 'data': data = v; break;
    case 'dupData': dupData = v; break;
    case 'currentTab': currentTab = v; break;
    default: throw new Error('no setter for ' + k);
  }
};
`;
(0, eval)(src + tail);

// The styled dialog, captured rather than shown.
let shown = null;
globalThis.showModal = () => {};
globalThis.showConfirmModal = (title, body, label) => {
  shown = { title, body, label };
  return Promise.resolve(false);          // he declines: nothing may be sent
};
const sent = [];
globalThis.pyApi = async (fn, ...args) => { sent.push({ fn, args }); return { ok: true }; };
globalThis.refreshData = () => {};

const ME = 'me@example.invalid';
const CLOUD = {
  id: 'c-1', name: 'SITE1 Riverside Baseline', mtime: 200, owner: ME,
  siteName: 'SITE1 Riverside', meta: 'changed 12 Sep',
  // `build_sites_data` puts plain addresses in here, not objects.
  sharedWith: ['colleague@example.invalid'],
};
__set('currentTab', 'duplicates');
__set('data', { currentUser: ME, summary: { matched: 1 },
  matched: [{ cloud: CLOUD, local: { name: CLOUD.name, path: 'D:/E/A/x.esx' },
              matchType: 'id', namesDiffer: false, staleness: null,
              status: 'synced' }],
  cloudOnly: [], localOnly: [], orphans: { cloudOnly: [] } });
indexRowData();

const out = {};
(async () => {
  await _bulkDeleteItems([
    { side: 'cloud', id: 'c-1', name: 'SITE1 Riverside Baseline', size: 12345678 },
    { side: 'local', path: 'D:/Ekahau Projects/SITE1 Riverside/Baseline.esx',
      name: 'Baseline', size: 2345678 },
  ], 'k1');

  out.nativeConfirms = nativeConfirms;
  out.shown = shown;
  out.sent = sent.map(s => s.fn);
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})().catch(err => { process.stderr.write(String(err && err.stack || err)); process.exit(1); });
"""

_PROBE = {}


def probe():
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
class TheDuplicatesTabUsesTheRealDialog(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_no_native_dialog_is_used(self):
        self.assertEqual(0, self.out["nativeConfirms"],
                         "a cloud delete was confirmed through window.confirm")

    def test_declining_sends_nothing(self):
        self.assertEqual([], self.out["sent"],
                         "it deleted despite the confirmation being declined")

    def test_it_names_every_item_rather_than_counting_them(self):
        body = self.out["shown"]["body"]
        self.assertIn("SITE1 Riverside Baseline", body)
        self.assertIn("Baseline", body)
        self.assertNotIn("more", body.split("You are deleting")[-1][:200].lower(),
                         "the list was abbreviated: " + body)

    def test_a_cloud_item_carries_its_site_and_date(self):
        body = self.out["shown"]["body"]
        self.assertIn("SITE1 Riverside", body)
        self.assertIn("changed 12 Sep", body)

    def test_it_says_who_loses_access(self):
        self.assertIn("colleague@example.invalid", self.out["shown"]["body"])

    def test_a_local_copy_is_placed_by_its_folder(self):
        """Two local duplicates share a name; the folder is what tells them
        apart, and it is the only thing that can."""
        self.assertIn("SITE1 Riverside", self.out["shown"]["body"])

    def test_it_does_not_lead_with_a_size(self):
        """`_row_meta` leaves size off on purpose - the two sides store the
        same project very differently, so the number disagrees with itself."""
        self.assertNotIn("12345678", self.out["shown"]["body"])
        self.assertNotIn("11.8 MB", self.out["shown"]["body"])

    def test_the_title_says_the_cloud_is_involved(self):
        self.assertIn("Ekahau Cloud", self.out["shown"]["title"])


if __name__ == "__main__":
    unittest.main()
