"""The whole of the real cloud.js, run under Node with a document cut down
to what its functions touch.

Most Cloud Manager probes slice one function out of the file and stub its
neighbours. That proves the function, and misses the bug that lives between
two of them - a count that reads one key shape while the checkboxes write
another, a path used after the call that moved it. Here every function is the
shipping one; only the boundary is replaced:

* `pyApi` (the server) is a recorder the probe sets,
* `showConfirmModal`, `confirm`, `toast` and `opEnqueue` are the probe's to
  replace, and the defaults record and agree,
* `document.getElementById` hands back a plain element, created on first ask
  and kept, so a probe can read what the code wrote to it.

`WD.esc`, `WD.escAttr` and `WD.escJsStr` are the real ones from
wd-shared.js, so an escaping bug shows up as the user would see it.

A probe is the body of an async function. It talks to the page through `s`
(the window), reads a top-level `let` with `s.__get('name')`, sets one with
`s.__set('name', value)`, and finishes with `out(value)`. A probe that throws,
or never calls `out`, fails the test loudly rather than returning `{}`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "assets" / "js"
NODE_TIMEOUT_S = 120
HAVE_NODE = shutil.which("node") is not None

_MARK = "__CLOUD_VM_OUT__"

PRELUDE = r"""
const fs = require('fs'), vm = require('vm');
const [sharedPath, cloudPath] = process.argv.slice(1, 3);
function mkEl(id) {
  return {
    id, _attrs: {}, style: {}, dataset: {}, hidden: false, checked: false,
    value: '', textContent: '', innerHTML: '', title: '', disabled: false,
    classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      toggle(c, on) { if (on === undefined) on = !this._s.has(c);
                      on ? this._s.add(c) : this._s.delete(c); return on; },
      contains(c) { return this._s.has(c); } },
    addEventListener() {}, removeEventListener() {},
    setAttribute(k, v) { this._attrs[k] = String(v); },
    getAttribute(k) { return this._attrs[k] ?? null; },
    removeAttribute(k) { delete this._attrs[k]; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    appendChild() {}, removeChild() {}, focus() {}, select() {},
    setSelectionRange() {}, closest() { return null; }, scrollIntoView() {},
    insertAdjacentHTML() {},
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; },
  };
}
const els = new Map();
const document = {
  getElementById(id) { if (!els.has(id)) els.set(id, mkEl(id)); return els.get(id); },
  querySelector() { return null; }, querySelectorAll() { return []; },
  addEventListener() {},
  // WD.esc writes textContent and reads innerHTML; a browser escapes & < >
  // on the way through, and so does this.
  createElement(t) {
    const el = mkEl(t); let tc = '';
    Object.defineProperty(el, 'textContent', { get() { return tc; }, set(v) { tc = String(v); } });
    Object.defineProperty(el, 'innerHTML', {
      get() { return tc.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
      set(v) { tc = String(v); } });
    return el;
  },
  body: mkEl('body'), documentElement: mkEl('html'),
  readyState: 'complete', visibilityState: 'visible',
};
const s = {
  console, document, setTimeout: () => 0, clearTimeout() {}, setInterval() { return 0; },
  clearInterval() {}, requestAnimationFrame() {},
  navigator: { platform: 'Win32', clipboard: null },
  localStorage: { _m: {}, getItem(k) { return this._m[k] ?? null; },
                  setItem(k, v) { this._m[k] = String(v); }, removeItem(k) { delete this._m[k]; } },
  sessionStorage: { getItem() { return null; }, setItem() {} },
  location: { search: '', href: 'http://127.0.0.1/', hash: '' }, history: { replaceState() {} },
  fetch: async () => { throw new Error('a probe reached fetch - stub pyApi'); },
  CSS: { escape: x => x }, URLSearchParams, Map, Set, Promise, JSON, Math, Date,
  Array, Object, String, Number, RegExp, Error,
  getComputedStyle() { return {}; },
  matchMedia() { return { matches: false, addEventListener() {} }; },
  els,
};
s.window = s; s.addEventListener = () => {}; s.removeEventListener = () => {};
vm.createContext(s);
vm.runInContext(fs.readFileSync(sharedPath, 'utf8'), s, { filename: 'wd-shared.js' });
if (!s.WD || !s.WD.escAttr) throw new Error('wd-shared.js did not define WD.escAttr');
if (s.WD.esc('R&D <x>') !== 'R&amp;D &lt;x&gt;') throw new Error('WD.esc is not escaping here');
let src = fs.readFileSync(cloudPath, 'utf8');
src += '\n;globalThis.__get = (n) => eval(n); globalThis.__set = (n, v) => eval(n + " = v");';
vm.runInContext(src, s, { filename: 'cloud.js' });
// The real functions, now the file has defined them; the probe may replace
// the boundary ones after this line.
s.toasts = [];
s.toast = (m, k) => { s.toasts.push([k, m]); };
s.showModal = () => {};
s.closeModal = () => {};
s.confirms = [];
s.showConfirmModal = async (title, body) => { s.confirms.push({ title, body }); return true; };
s.confirm = (m) => { s.confirms.push({ title: '', body: m }); return true; };
s.calls = [];
s.pyApi = async (m, ...args) => { s.calls.push({ m, args }); return { ok: true }; };
s.opEnqueue = (spec) => ({ id: 'op-1', promise: Promise.resolve().then(() => spec.run('op-1')) });
s._scheduleOpRefresh = () => {};
s.refreshData = () => {};
function out(v) { process.stdout.write('\n__CLOUD_VM_OUT__' + JSON.stringify(v) + '\n'); }
const text = (html) => String(html || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
const settle = () => new Promise(r => setImmediate(r));
"""


def run(probe: str, timeout: int = NODE_TIMEOUT_S):
    """Run `probe` against the real cloud.js and return what it `out()`s."""
    program = (PRELUDE + "\n(async () => {\n" + probe + "\n})()"
               ".catch(e => { console.error(e && e.stack || e); process.exit(1); });\n")
    r = subprocess.run(
        ["node", "-e", program, str(JS / "wd-shared.js"), str(JS / "cloud.js")],
        capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip()[-4000:])
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith(_MARK)]
    if not lines:
        raise AssertionError("the probe never reported:\n"
                             + (r.stdout + r.stderr).strip()[-4000:])
    return json.loads(lines[-1][len(_MARK):])
