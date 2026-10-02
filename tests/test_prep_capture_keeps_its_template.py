"""A capacity template captured in Prep stays the one selected.

Capturing a template on the Areas stage saves it, selects it, and reloads the
lists. The reload picks the saved default unless the picker has been touched,
and capturing did not count as touching it - so the template he had just made
was replaced by the default the moment it appeared, and the next preview ran
with the default.

The real ``loadTemplates`` and ``prepCaptureSave`` are sliced out of
``prep.js`` by counting braces and run in Node with a small ``<select>`` whose
value follows its ``selected`` option, the way a browser's does.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"

PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function fn(head) {
  const a = src.indexOf(head);
  if (a < 0) throw new Error(head + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
function select() {
  const el = { _html: '', value: '', options: [] };
  Object.defineProperty(el, 'innerHTML', { get() { return this._html; }, set(h) {
    this._html = h;
    this.options = [...h.matchAll(/<option value="([^"]*)"( selected)?/g)]
      .map(m => ({ value: m[1], sel: !!m[2] }));
    const s = this.options.find(o => o.sel) || this.options[0];
    this.value = s ? s.value : ''; } });
  return el;
}
const els = { prepWallTpl: select(), prepCapTpl: select(),
              prepCaptureName: { value: 'Invented Studio' } };
function $(id) {
  return els[id] || (els[id] = { value: '', checked: true, disabled: false,
                                 textContent: '', classList: { remove() {} } });
}
const esc = String, escAttr = String;
const window = {};
var wallTemplates = [], capTemplates = [], savedWallTemplateName = '';
var savedCapTemplate = 'default-tpl.json', capTplTouched = false;
let capList = [{ _file: 'default-tpl.json', name: 'Default' }];
const toasts = [];
const WD = { savedWallTemplateName: () => Promise.resolve(''), wallTemplateOrder: x => x,
  chooseWallTemplate: (l) => l[0], wallTemplateLabel: t => t.name,
  toast: (m) => toasts.push(m) };
function fetch(url) {
  if (url === '/api/capacity/save') {
    capList.push({ _file: 'invented-studio.json', name: 'Invented Studio' });
    return Promise.resolve({ json: () => ({ ok: true, file: 'invented-studio.json' }) });
  }
  if (url === '/api/prep/templates') {
    return Promise.resolve({ json: () => ({ ok: true, wall: [{ file: 'w.json', name: 'W' }],
                                            capacity: capList.slice() }) });
  }
  throw new Error('unexpected ' + url);
}
function disableStep() {} function enableStep() {}
const previews = [];
function syncStepUi() { previews.push($('prepCapTpl').value); }
var capture = { derived: { name: 'x', items: [] } };
let closed = 0;
eval(fn('  function loadTemplates()'));
window.prepCaptureClose = () => { closed++; };
eval(fn('  window.prepCaptureSave = function'));
loadTemplates().then(() => {
  window.prepCaptureSave();
  setTimeout(() => console.log(JSON.stringify({
    selected: $('prepCapTpl').value, previews, closed, toasts })), 50);
}).catch(e => { console.error(e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ACapturedTemplateStaysSelected(unittest.TestCase):
    def test_the_reload_after_capture_keeps_the_new_template(self):
        r = subprocess.run(["node", "-e", PROBE, str(PREP_JS)],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["closed"], 1, out)
        self.assertEqual(out["selected"], "invented-studio.json",
                         "the saved default replaced the template just captured")
        # The preview that runs after the reload uses it too.
        self.assertEqual(out["previews"][-1], "invented-studio.json", out)


if __name__ == "__main__":
    unittest.main()
