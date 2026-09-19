"""A comparison describes two files at a moment, and stops when they move.

Comparing a pair downloads the cloud copy and diffs it member by member, and
the answer is kept so he is not asked to wait for it twice - "I shouldn't have
to recheck twice". The map's own comment says it is "cleared when the pair
changes on either side". Nothing cleared it.

So: compare a pair at 09:00 and it is identical. The cloud copy is saved from
Ekahau at 10:00. The next refresh reports `cloud_newer` - and the stored 09:00
verdict still said settled, `comparisonIsSettled` agreed, `isOutOfSync`
returned false, and `stalenessBadgeHtml` draws **no action at all** on a
settled row. The newer cloud copy became invisible, and stayed invisible until
the page was reloaded.

Either date moving retires the answer. Re-asking costs one button; not asking
costs him whatever somebody else changed.

The whole of `cloud.js` is evaluated, so the retirement is measured through
the same functions the chip, the filter and the row's controls all use.

Every project, site and path here is invented.
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
globalThis.requestAnimationFrame = fn => setTimeout(fn, 0);
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
const BS = String.fromCharCode(92);
const WD = { esc: s => String(s == null ? '' : s), toast: () => {},
             api: async () => ({}), toggleMenu: () => {} };
WD.escAttr = WD.esc;
WD.escJsStr = s => String(s == null ? '' : s)
  .split(BS).join(BS + BS).split("'").join(BS + "'");
globalThis.WD = WD;
globalThis.toast = () => {};
globalThis.showModal = () => {};
globalThis.hideModal = () => {};
globalThis.window = globalThis;

const ME = 'me@example.invalid';
const CLOUD_ID = 'c-1';
const LOCAL = 'D:/Ekahau Projects/SITE1 Riverside/SITE1 Riverside Baseline.esx';

// The comparison is the thing on test, so the server answer is fixed: the two
// files are identical, which is what makes the row settle.
const IDENTICAL = { identical: true, designDiffers: false, nameState: 'match' };
globalThis.fetch = async (url, opts) => ({
  ok: true,
  json: async () => (String(url).endsWith('/compare_with_cloud')
    ? Object.assign({}, IDENTICAL) : {}),
});

const tail = `
;globalThis.__set = (k, v) => {
  switch (k) {
    case 'data': data = v; break;
    case 'currentTab': currentTab = v; break;
    case 'activeFilter': activeFilter = v; break;
    default: throw new Error('no setter for ' + k);
  }
};
globalThis.__cacheSize = () => _compareResults.size;
`;
(0, eval)(src + tail);

function pairAt(cloudMtime, localMtime, staleness) {
  return {
    cloud: { id: CLOUD_ID, name: 'SITE1 Riverside Baseline', mtime: cloudMtime,
             owner: ME, siteName: '', hasSite: true },
    local: { name: 'SITE1 Riverside Baseline', path: LOCAL, mtime: localMtime,
             isDir: false },
    matchType: 'id', namesDiffer: false, staleness: staleness || null,
    status: 'synced',
  };
}

function loadPair(p) {
  __set('data', { currentUser: ME, summary: { matched: 1 }, matched: [p],
                  cloudOnly: [], localOnly: [], orphans: { cloudOnly: [] } });
  __set('currentTab', 'projects');
  __set('activeFilter', 'all');
  indexRowData();
}

(async () => {
  const out = {};

  // 09:00 - he presses Check. The pair is identical and the row settles.
  const atNine = pairAt(100, 100, 'cloud_newer');
  loadPair(atNine);
  await settlePair(CLOUD_ID, LOCAL, { quiet: true });
  out.cached = __cacheSize();

  const rowNine = { kind: 'projects', matchType: 'id', staleness: 'cloud_newer',
                    cloud: atNine.cloud, local: atNine.local };
  out.settledWhenUnchanged = !isOutOfSync(rowNine);
  out.badgeWhenUnchanged = stalenessBadgeHtml(rowNine);

  // 10:00 - somebody saves the cloud copy. The refresh brings a newer date.
  const atTen = pairAt(9999, 100, 'cloud_newer');
  loadPair(atTen);
  const rowTen = { kind: 'projects', matchType: 'id', staleness: 'cloud_newer',
                   cloud: atTen.cloud, local: atTen.local };
  out.stillSettledAfterCloudMoved = !isOutOfSync(rowTen);
  out.badgeAfterCloudMoved = stalenessBadgeHtml(rowTen);

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
class AStoredComparisonRetiresWhenThePairMoves(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_the_comparison_was_actually_stored(self):
        """Otherwise the rest of this file is testing an empty map."""
        self.assertEqual(1, self.out["cached"], self.out)

    def test_while_nothing_moves_the_row_stays_settled(self):
        """The point of keeping the answer at all - he is not asked twice."""
        self.assertTrue(self.out["settledWhenUnchanged"], self.out)
        self.assertEqual("", self.out["badgeWhenUnchanged"].strip(),
                         "a settled pair drew an action anyway")

    def test_once_the_cloud_copy_moves_the_row_asks_again(self):
        self.assertFalse(
            self.out["stillSettledAfterCloudMoved"],
            "a comparison taken before the cloud copy changed was still "
            "reporting the pair as settled")

    def test_and_the_row_offers_the_download_again(self):
        """A settled row draws no action, which is how the newer cloud copy
        became invisible rather than merely unremarked."""
        badge = self.out["badgeAfterCloudMoved"]
        self.assertTrue(badge.strip(), "the row offered nothing at all")
        self.assertIn("Cloud newer", badge)


if __name__ == "__main__":
    unittest.main()
