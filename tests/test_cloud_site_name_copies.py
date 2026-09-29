"""A site name on the Sites tab copies when clicked.

"Make site names clickable/copyable."

The whole site row already opens and closes the site, so a click anywhere on it
was taken - including a click at the end of dragging across the name to select
it, which folded the site away under the selection. Now the name itself is a
button that copies the name as stored, and the row toggle ignores a click that
ends a text selection.

Driven through the real `cloudCell` / `localCell`, the handler pulled back out
of the rendered markup, and the real delegated row-toggle listener. Every name
here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.delegated import DELEGATED_JS

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
function fakeEl(id) {
  return { id, innerHTML: '', textContent: '', value: '', dataset: {}, style: {},
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){}, setAttribute(){},
    getAttribute(){ return null; }, querySelector(){ return null; },
    querySelectorAll(){ return []; }, appendChild(){}, removeChild(){},
    remove(){}, focus(){}, select(){}, click(){} };
}
const listeners = {};
const written = [];
const toasts = [];
let clipboardWorks = true;
let execResult = true;
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl, String,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: { getElementById(id){ return fakeEl(id); },
    querySelector(){ return fakeEl(); }, querySelectorAll(){ return []; },
    createElement(){ return fakeEl(); },
    addEventListener(type, fn){ (listeners[type] = listeners[type] || []).push(fn); },
    execCommand(cmd){ if (cmd === 'copy') written.push(['exec', sandbox.__lastTa]); return execResult; },
    body: fakeEl(), documentElement: fakeEl() },
  navigator: { platform: 'Win32', clipboard: { writeText: async (t) => {
    if (!clipboardWorks) throw new Error('denied');
    written.push(['clipboard', t]);
  } } },
  location: { href: 'file:///cloud.html', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  alert(){}, confirm(){ return true; },
  requestAnimationFrame: (f) => setTimeout(f, 0),
  WD: { esc: s => String(s == null ? '' : s).replace(/[&<>"']/g,
          c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
        applyVersions(){}, toast(){} },
};
sandbox.WD.escAttr = sandbox.WD.esc;
sandbox.WD.escJsStr = s => String(s == null ? '' : s).replace(/['\\]/g, '\\$&');
sandbox.window = sandbox;
vm.createContext(sandbox);
try { vm.runInContext(source, sandbox, { filename: 'cloud.js' }); }
catch (err) { if (!/addEventListener|null|undefined/.test(err.message)) throw err; }
""" + DELEGATED_JS + r"""

const input = JSON.parse(process.argv[2]);
sandbox.__data = { currentUser: 'me@example.invalid', matched: [], cloudOnly: [],
  localOnly: [], orphans: { cloudOnly: [], localOnly: [] } };
vm.runInContext("data = __data; currentTab = 'sites'; activeFilter = 'all';", sandbox);
sandbox.toast = (msg, kind) => toasts.push([kind || '', msg]);
/* The fallback's textarea: remember its value so the exec copy can report it. */
sandbox.document.createElement = () => {
  const el = fakeEl();
  return new Proxy(el, { set(t, k, v) { t[k] = v; if (k === 'value') sandbox.__lastTa = v; return true; } });
};

(async () => {
  const out = {};
  if (input.row) {
    sandbox.__row = input.row;
    out.cloudCell = input.row.cloud ? vm.runInContext('cloudCell(__row, new Set())', sandbox) : '';
    out.localCell = input.row.local ? vm.runInContext('localCell(__row, new Set())', sandbox) : '';
    clipboardWorks = input.clipboardWorks !== false;
    execResult = input.execResult !== false;
    out.hits = [];
    for (const cell of [out.cloudCell, out.localCell]) {
      const hit = delegated(cell, 'copySiteName');
      out.hits.push(hit ? { args: hit.args, stops: hit.stops, button: /^<button/.test(hit.tag) } : null);
      if (hit) await sandbox.copySiteName.apply(null, hit.args);
    }
    await new Promise(r => setTimeout(r, 0));
  }
  if (input.toggle) {
    const toggled = [];
    sandbox.toggleFolder = (k) => toggled.push(k);
    const row = { dataset: { toggle: 'site:x' }, contains: () => true };
    const target = (inButton) => ({ closest(sel) {
      if (/button/.test(sel)) return inButton ? {} : null;
      if (/is-openable/.test(sel)) return row;
      return null;
    } });
    const click = (t) => (listeners.click || []).forEach(fn =>
      fn({ target: t, preventDefault(){}, stopPropagation(){} }));
    sandbox.getSelection = () => ({ isCollapsed: true, toString: () => '', anchorNode: null });
    click(target(false));
    out.plainClick = toggled.length;
    click(target(true));
    out.afterButtonClick = toggled.length;
    sandbox.getSelection = () => ({ isCollapsed: false, toString: () => 'Birch', anchorNode: {} });
    click(target(false));
    out.afterSelectingClick = toggled.length;
  }
  out.written = written;
  out.toasts = toasts;
  process.stdout.write(JSON.stringify(out));
})().catch(err => { console.error(err.stack || err.message); process.exit(1); });
"""


def run(payload):
    r = subprocess.run(
        ["node", "-e", PROGRAM, str(CLOUD_JS), json.dumps(payload)],
        capture_output=True, text=True, encoding="utf-8",
        timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip()[-2500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


CLOUD_NAME = "Birch & Bramble's \"North\" Depot"
LOCAL_NAME = "Birch & Bramble's North Depot"


def site(name=CLOUD_NAME):
    return {"id": "site-bb", "name": name, "meta": "",
            "children": {"matched": [], "cloudOnly": [], "localOnly": []}}


def folder(name=LOCAL_NAME):
    return {"path": "D:/Esx/" + name, "name": name, "isDir": True, "meta": "",
            "children": {"matched": [], "cloudOnly": [], "localOnly": []}}


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ASiteNameCopiesTests(unittest.TestCase):

    def test_both_names_on_a_mismatched_site_row_copy_exactly_as_stored(self):
        row = {"kind": "sites", "status": "mismatch", "key": "s:bb",
               "cloud": site(), "local": folder()}
        got = run({"row": row})
        self.assertEqual([{"args": [CLOUD_NAME], "stops": True, "button": True},
                          {"args": [LOCAL_NAME], "stops": True, "button": True}],
                         got["hits"])
        # The copied text is the name, not the character-diff markup around it.
        self.assertEqual([["clipboard", CLOUD_NAME], ["clipboard", LOCAL_NAME]],
                         got["written"])
        self.assertEqual("success", got["toasts"][0][0])
        self.assertIn(CLOUD_NAME, got["toasts"][0][1])

    def test_the_name_is_still_shown_inside_the_button(self):
        row = {"kind": "sites", "status": "synced", "key": "s:bb",
               "cloud": site(LOCAL_NAME), "local": folder()}
        got = run({"row": row})
        self.assertIn("Birch &amp; Bramble&#39;s North Depot</button>",
                      got["cloudCell"])
        self.assertIn("Birch &amp; Bramble&#39;s North Depot</button>",
                      got["localCell"])

    def test_a_project_row_does_not_turn_its_name_into_a_copy_button(self):
        row = {"kind": "projects", "status": "synced", "key": "p:x",
               "cloud": {"id": "p1", "name": "Survey", "meta": ""},
               "local": {"path": "D:/Esx/Survey.esx", "name": "Survey", "meta": ""}}
        got = run({"row": row})
        self.assertEqual([None, None], got["hits"])
        self.assertIn("Survey.esx", got["cloudCell"])

    def test_a_refused_clipboard_falls_back_and_still_copies(self):
        row = {"kind": "sites", "status": "orphan", "key": "c:bb",
               "cloud": site(LOCAL_NAME), "local": None}
        got = run({"row": row, "clipboardWorks": False})
        self.assertEqual([["exec", LOCAL_NAME]], got["written"])
        self.assertEqual("success", got["toasts"][0][0])

    def test_a_copy_that_cannot_happen_says_so(self):
        row = {"kind": "sites", "status": "orphan", "key": "c:bb",
               "cloud": site(LOCAL_NAME), "local": None}
        got = run({"row": row, "clipboardWorks": False, "execResult": False})
        self.assertEqual("error", got["toasts"][0][0])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheRowStillOpensTests(unittest.TestCase):

    def test_a_plain_click_opens_but_the_name_and_a_selection_do_not(self):
        got = run({"toggle": True})
        self.assertEqual(1, got["plainClick"], "a click on the row opens the site")
        self.assertEqual(1, got["afterButtonClick"], "the copy button does not toggle")
        self.assertEqual(1, got["afterSelectingClick"],
                         "finishing a text selection does not fold the site away")


if __name__ == "__main__":
    unittest.main()
