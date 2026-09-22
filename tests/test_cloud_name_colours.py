"""What colour a name actually comes out, read from a browser.

"Currently the sites are labelled in blue and the files are labelled using
white text, and the sites have a nice border ... I hope they don't go the
other direction." And later, when half of it had: "in Cloud we now for
whatever reason don't have the local file names for the folders coloured the
same as cloud."

**A test already existed to protect this and it did not.** It asserted that
`wd-tools.css` contains the string

    .ledger.tree .tree-parent .lr-cell.local .cell-name { color: var(--green); }

and that string was present the entire time the folder name was rendering
white - because a later rule in the same stylesheet set it back to
`var(--text)`, and the cascade does not care which rule a test can find. The
string was there and the colour was not. That is the failure this repository
has shipped five times: an assertion about source text standing in for an
assertion about behaviour.

There is a second thing a text assertion cannot see. `--green` is `#15803d`
with no dark-theme value - 3.45:1 on this surface, against 6.24:1 for the
blue opposite it. The rule can be present, win the cascade, and still not
produce a colour anyone would call green.

So this renders the real markup with the real stylesheet and reads
`getComputedStyle` back, then computes contrast from the pixels rather than
from the token names. It fails on the override, on a flattened token, and on
anything else that makes a name come out the wrong colour, however it gets
there.

Every project and site name here is invented.
"""
from __future__ import annotations

from tests import browsers as _browsers

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"
FIREFOX = _browsers.find("firefox")
NODE_TIMEOUT_S = 180

#: One site, one file under it - the smallest tree that has all three levels.
RENDER = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
function fakeEl() {
  return { innerHTML: '', textContent: '', value: '', checked: false,
    hidden: false, dataset: {}, style: {}, children: [], parentElement: null,
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){}, setAttribute(){},
    getAttribute(){ return null; }, removeAttribute(){}, closest(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){}, scrollIntoView(){},
    getBoundingClientRect(){ return { top:0, left:0, width:0, height:0 }; } };
}
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: { getElementById(){ return fakeEl(); }, querySelector(){ return fakeEl(); },
    querySelectorAll(){ return []; }, createElement(){ return fakeEl(); },
    addEventListener(){}, body: fakeEl(), documentElement: fakeEl() },
  navigator: { platform: 'Win32', clipboard: { writeText: async () => {} } },
  location: { href: 'file:///cloud.html', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  alert(){}, confirm(){ return true; }, prompt(){ return null; },
  requestAnimationFrame: (f) => setTimeout(f, 0),
  WD: { esc: s => String(s == null ? '' : s).replace(/[&<>"]/g,
          c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
        applyVersions(){}, toast(){} },
};
sandbox.WD.escAttr = sandbox.WD.esc;
sandbox.WD.escJsStr = s => String(s == null ? '' : s).replace(/['\\]/g, '\\$&');
sandbox.window = sandbox;
vm.createContext(sandbox);
try { vm.runInContext(source, sandbox, { filename: 'cloud.js' }); }
catch (err) { if (!/addEventListener|null|undefined/.test(err.message)) throw err; }

const ME = 'me@example.invalid';
const SITE = 'A100 Riverside Block';
const kid = { cloud: { id: 'p1', name: SITE + ' - Survey 1', owner: ME,
                       hasSite: true, meta: '2 hr ago', sharedWith: [] },
              local: { path: 'D:\\E\\' + SITE + '\\' + SITE + ' - Survey 1.esx',
                       name: SITE + ' - Survey 1', folder: SITE, meta: '14 Aug' },
              matchType: 'id', staleness: null, namesDiffer: false };
const children = { matched: [kid], cloudOnly: [], localOnly: [] };
vm.runInContext('data = ' + JSON.stringify({
  currentUser: ME, summary: { matched: 1 },
  matched: [{ cloud: { id: 's1', name: SITE, owner: ME, hasSite: true,
                       meta: '2 hr ago', sharedWith: [], children },
              local: { path: 'D:\\E\\' + SITE, name: SITE, isDir: true,
                       meta: '14 Aug', children },
              matchType: 'exact', staleness: null, namesDiffer: false }],
  cloudOnly: [], localOnly: [], orphans: { cloudOnly: [], localOnly: [] },
}) + ";currentTab = 'sites'; activeFilter = 'all'; activeLetter = '';"
   + 'collapsed = new Set();', sandbox);
process.stdout.write(vm.runInContext(
  'renderLedger(function () { return true; })', sandbox));
"""

READ_COLOURS = """
const q = (s) => document.querySelector(s);
const col = (el) => el ? getComputedStyle(el).color : null;
return JSON.stringify({
  siteCloud: col(q('.ledger.tree .tree-parent .lr-cell.cloud .cell-name')),
  siteLocal: col(q('.ledger.tree .tree-parent .lr-cell.local .cell-name')),
  fileCloud: col(q('.ledger-row.tree-child .lr-cell.cloud .cell-name')),
  fileLocal: col(q('.ledger-row.tree-child .lr-cell.local .cell-name')),
  surface:   getComputedStyle(document.body).backgroundColor,
});
"""


def _rgb(css_colour):
    m = re.findall(r"[\d.]+", css_colour or "")
    return tuple(int(float(x)) for x in m[:3]) if len(m) >= 3 else None


def _lum(c):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = c
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


@unittest.skipUnless(Path(FIREFOX).exists(), "Firefox is not installed")
@unittest.skipUnless(shutil.which("node"), "node is not installed")
class NameColoursAreWhatTheyLookLikeTests(unittest.TestCase):

    colours: dict = {}

    @classmethod
    def setUpClass(cls):
        try:
            from selenium import webdriver
            from selenium.webdriver.firefox.options import Options
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("selenium is not installed")

        r = subprocess.run(["node", "-e", RENDER, str(CLOUD_JS)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError("render failed:\n" + (r.stderr or "")[-2500:])

        #: Registered here rather than in `tearDownClass`, because a browser
        #: that will not start raises out of this method and `tearDownClass`
        #: then never runs - which is one of the ways a temp directory is left
        #: behind for good.
        cls._tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls._tmp, True)
        page = Path(cls._tmp) / "ledger.html"
        page.write_text(
            "<!doctype html><html><head><meta charset='utf-8'><style>"
            + CSS.read_text(encoding="utf-8")
            + "</style><style>body{margin:0;background:var(--bg)}</style>"
            + "</head><body>" + r.stdout + "</body></html>",
            encoding="utf-8")

        opts = Options()
        opts.binary_location = FIREFOX
        opts.add_argument("-headless")
        drv = webdriver.Firefox(options=opts)
        try:
            drv.get(page.as_uri())
            cls.colours = json.loads(drv.execute_script(READ_COLOURS))
        finally:
            drv.quit()

    # -- the hierarchy he asked for, read off the page ----------------------

    def test_a_cloud_site_name_is_blue(self):
        r, g, b = _rgb(self.colours["siteCloud"])
        self.assertGreater(b, r + 40, self.colours["siteCloud"])
        self.assertGreater(b, g + 20, self.colours["siteCloud"])

    def test_a_local_folder_name_is_green(self):
        """The regression. A later rule set this to `--text` and the test
        that was guarding it could not see the cascade."""
        r, g, b = _rgb(self.colours["siteLocal"])
        self.assertGreater(g, r + 60, self.colours["siteLocal"])
        self.assertGreater(g, b + 60, self.colours["siteLocal"])

    def test_file_names_stay_plain_on_both_sides(self):
        """"the files are labelled using white text" - the third level, and
        the one that must not gain a colour."""
        for side in ("fileCloud", "fileLocal"):
            r, g, b = _rgb(self.colours[side])
            spread = max(r, g, b) - min(r, g, b)
            self.assertLess(spread, 25, f"{side} is tinted: {self.colours[side]}")
            self.assertGreater(min(r, g, b), 150, self.colours[side])

    def test_the_three_levels_are_three_different_colours(self):
        site_c = _rgb(self.colours["siteCloud"])
        site_l = _rgb(self.colours["siteLocal"])
        file_l = _rgb(self.colours["fileLocal"])
        self.assertGreater(_distance(site_c, site_l), 100)
        self.assertGreater(_distance(site_l, file_l), 100)

    # -- and readable, which a token name cannot tell you -------------------

    def test_both_site_names_are_readable_on_the_surface(self):
        """`--green` was 3.45:1 here while the blue opposite it was 6.24:1,
        so the rule could win the cascade and still look flat. AA for body
        text is 4.5:1."""
        bg = _rgb(self.colours["surface"])
        for side in ("siteCloud", "siteLocal"):
            ratio = _contrast(_rgb(self.colours[side]), bg)
            self.assertGreaterEqual(
                round(ratio, 2), 4.5,
                f"{side} is {ratio:.2f}:1 on {self.colours['surface']}")

    def test_the_two_sides_are_within_reach_of_each_other(self):
        """"coloured the same as cloud" is about weight as much as hue: one
        side bright and the other dim is what the regression looked like."""
        bg = _rgb(self.colours["surface"])
        c = _contrast(_rgb(self.colours["siteCloud"]), bg)
        l = _contrast(_rgb(self.colours["siteLocal"]), bg)
        self.assertLess(abs(c - l), 1.5,
                        f"cloud {c:.2f}:1 against local {l:.2f}:1")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
