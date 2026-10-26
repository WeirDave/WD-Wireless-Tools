"""The stale-server banner has one owner, and it does not poll.

`wd-shared.js` carried two checks. `WD.checkServerVersion` compares
`versions.json` on disk against what the server started with, on page load and
when the window regains focus. An older, unconnected `checkServerVersion` below
it fetched `/api/version` the moment the script loaded and again every 30
seconds, in every open tab; it drew the same `#wdStaleBanner` element from a
different condition, removed the real banner whenever its own condition was
false, and its Restart button posted to `/api/restart` without the header the
server requires, so the request was refused and the banner waited out a
20-second deadline.

The real script is loaded into a stand-in page and everything it does at load
is recorded. Nothing here talks to a server.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "web" / "assets" / "js" / "wd-shared.js"

PROGRAM = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');

function el() {
  const e = { style: {}, dataset: {}, hidden: false, children: [], classList: {
      add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, setAttribute() {}, getAttribute: () => null,
    appendChild(c) { return c; }, prepend() {}, remove() {}, insertBefore() {},
    querySelector: () => null, querySelectorAll: () => [], closest: () => null,
    getBoundingClientRect: () => ({ top: 0, left: 0, width: 0, height: 0 }) };
  return e;
}
const fetches = [], intervals = [], listeners = {};
const document = {
  getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
  createElement: () => el(), body: el(), documentElement: el(), head: el(),
  currentScript: { src: 'http://127.0.0.1:8675/assets/js/wd-shared.js' },
  addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
  readyState: 'loading', visibilityState: 'visible', title: '',
};
const ctx = {
  console, document, Map, Set, Promise, JSON, Math, Date, Array, Object, String,
  Number, RegExp, Error, URL, URLSearchParams,
  navigator: { platform: 'Win32', userAgent: 'stand-in' }, screen: {},
  location: { protocol: 'http:', origin: 'http://127.0.0.1:8675', pathname: '/', search: '', hash: '', href: 'http://127.0.0.1:8675/' },
  history: { replaceState() {} },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  getComputedStyle: () => ({}),
  requestAnimationFrame() {}, setTimeout: () => 0, clearTimeout() {},
  setInterval: (fn, ms) => { intervals.push(ms); return intervals.length; },
  clearInterval() {},
  fetch: (url, init) => { fetches.push(String(url)); return new Promise(() => {}); },
  addEventListener: (t, f) => { (listeners['window:' + t] = listeners['window:' + t] || []).push(f); },
  removeEventListener() {},
  innerWidth: 1200, innerHeight: 800,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: 'wd-shared.js' });
console.log(JSON.stringify({
  loadedWD: typeof ctx.WD === 'object' && typeof ctx.WD.checkServerVersion === 'function',
  versionFetchesAtLoad: fetches.filter(u => u.includes('/api/version')).length,
  intervals,
}));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class OneStaleServerCheckTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", PROGRAM, str(SHARED)],
                           capture_output=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_script_loaded_and_still_has_its_check(self):
        """So the other assertions are about the real script."""
        self.assertTrue(self.out["loadedWD"], self.out)

    def test_nothing_asks_the_server_for_its_version_just_by_loading(self):
        self.assertEqual(0, self.out["versionFetchesAtLoad"], self.out)

    def test_no_thirty_second_poll_is_started(self):
        self.assertNotIn(30000, self.out["intervals"], self.out)


if __name__ == "__main__":
    unittest.main()
