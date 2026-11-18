"""A site's "N of M files" has to say which control hid the other files.

A site line read "2 of 7 files" with two rows underneath. The other five were
other people's projects, hidden by the Owner toggle on its default, Mine - but
the line only said they did not "match the filter you have on", and the Owner
toggle is not a thing a reader connects to a count in a site's header. Five
files existed as a number and nowhere else.

The digest now keeps the two causes apart: `byOwner` (the Owner toggle) and
`byFilter` (the status chips). This renders the real `siteDigest` /
`siteDigestHtml` out of `cloud.js` and reads what the line says.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"

PROBE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from), b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('slice not found: ' + from);
  return source.slice(a, b);
}
const WD = { esc: s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])) };
WD.escAttr = WD.esc;
function a(s){return WD.escAttr(s);}
let currentTab='sites', selected=new Set(), activeFilter='all';
const _compareResults=new Map();

const block = slice('function comparisonIsSettled(', '\nfunction _isExternal(')
            + slice('const ICONS = {', '\nfunction localByPath(');
const api = {};
eval(block + '\nObject.assign(api,{siteDigest,siteDigestHtml});');

const mine = (id) => ({id, name:id, owner:'me@example.com'});
const theirs = (id) => ({id, name:id, owner:'someone.else@example.com'});
const pair = (c) => ({cloud:c, local:null});
// Two of mine and five of somebody else's, none of them paired locally.
const children = {
  matched: [],
  cloudOnly: [mine('m1'), mine('m2'),
              theirs('o1'), theirs('o2'), theirs('o3'), theirs('o4'), theirs('o5')],
  localOnly: [],
};
const isMine = (row) => (row.cloud && row.cloud.owner) === 'me@example.com';
const isTheirs = (row) => !isMine(row);

const text = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
const title = (html) => (/title="([^"]*)"/.exec(html) || [])[1] || '';
const line = (opts) => {
  const d = api.siteDigest(children, opts);
  const html = api.siteDigestHtml({cloud:{children}, digest:d});
  return {d, text: text(html), title: title(html), html};
};

const out = {};
out.mine   = line({passOwner: isMine, ownerMode: 'mine'});
out.others = line({passOwner: isTheirs, ownerMode: 'others'});
out.all    = line({ownerMode: 'all'});
// Owner on Mine AND a status filter that drops one of mine.
out.both   = line({passOwner: isMine, ownerMode: 'mine',
                   passFilter: (status, r) => r.cloud.id !== 'm2'});
// A status filter alone, owner on All.
out.statusOnly = line({ownerMode: 'all',
                   passFilter: (status, r) => r.cloud.id === 'm1'});
console.log(JSON.stringify(out));
"""


class TheSiteCountNamesWhatHidTheRestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("node is not installed")
        d = tempfile.mkdtemp()
        try:
            f = Path(d) / "probe.js"
            f.write_text(PROBE, encoding="utf-8")
            r = subprocess.run(["node", str(f), str(CLOUD_JS)],
                               capture_output=True, text=True, timeout=60,
                               encoding="utf-8")
            if r.returncode != 0:
                raise AssertionError((r.stdout + r.stderr).strip())
            cls.out = json.loads(r.stdout)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_on_mine_the_five_hidden_files_are_attributed_to_the_owner_filter(self):
        o = self.out["mine"]
        self.assertEqual((o["d"]["total"], o["d"]["shown"]), (7, 2))
        self.assertEqual((o["d"]["byOwner"], o["d"]["byFilter"]), (5, 0))
        self.assertIn("2 of 7 files", o["text"])
        self.assertIn("5 from other owners hidden", o["text"])
        self.assertNotIn("hidden by filter", o["text"])
        self.assertIn("Owner filter (Mine)", o["title"])
        self.assertIn("choose All", o["title"])

    def test_on_others_it_is_the_users_own_files_that_are_hidden(self):
        o = self.out["others"]
        self.assertEqual((o["d"]["shown"], o["d"]["byOwner"]), (5, 2))
        self.assertIn("5 of 7 files", o["text"])
        self.assertIn("2 yours hidden", o["text"])
        self.assertIn("Owner filter (Others)", o["title"])

    def test_two_filters_are_counted_apart_and_add_up(self):
        o = self.out["both"]
        d = o["d"]
        self.assertEqual((d["shown"], d["byOwner"], d["byFilter"]), (1, 5, 1))
        self.assertEqual(d["shown"] + d["byOwner"] + d["byFilter"], d["total"])
        self.assertIn("5 from other owners hidden", o["text"])
        self.assertIn("1 hidden by filter", o["text"])

    def test_a_status_filter_alone_does_not_blame_the_owner_filter(self):
        o = self.out["statusOnly"]
        self.assertEqual((o["d"]["byOwner"], o["d"]["byFilter"]), (0, 6))
        self.assertIn("6 hidden by filter", o["text"])
        self.assertNotIn("owner", o["text"].lower())
        self.assertNotIn("Owner filter", o["title"])

    def test_nothing_hidden_says_nothing_about_filters(self):
        o = self.out["all"]
        self.assertFalse(o["d"]["narrowed"])
        self.assertIn("7 files", o["text"])
        self.assertNotIn("hidden", o["text"])
        self.assertIsNone(re.search(r"\d+ of \d+", o["text"]))


if __name__ == "__main__":
    unittest.main()
