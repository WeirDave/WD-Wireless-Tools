"""Prep says so when a saved box was not used, and does not forget it.

A "(prepared)" copy keeps the project id, so the box drawn on the full-size
original comes back with it. The server sets such a box aside
(``boxesSetAside``) instead of cropping the smaller sheet a second time. The
page has two jobs with it: say plainly, in the Trim panel, why the floor is
automatic this time, and keep the box stored for the original when it saves
the boxes it does have - PlanTrim does the same with its own ``setAside``.

The real ``prep.js`` runs in Node against a stubbed server; what is asserted is
what reaches the panel and what is sent to ``plantrim/boxes_save``.
"""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREP_JS = ROOT / "web" / "assets" / "js" / "prep.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const els = {};
function el(id) {
  if (!els[id]) els[id] = {
    id, innerHTML: '', textContent: '', value: '', checked: false, hidden: false,
    disabled: false, style: {}, files: [], title: '', options: [], children: [],
    classList: { add() {}, remove() {}, toggle() {} },
    listeners: {}, addEventListener(t, f) { this.listeners[t] = f; }, click() {},
  };
  return els[id];
}
el('prepStep-trim').checked = true;
el('prepMargin').value = 'normal';
const docListeners = {};
global.document = { getElementById: el, addEventListener(t, f) { docListeners[t] = f; },
                    querySelector: () => null, visibilityState: 'visible' };
global.window = global;
const saves = [];
global.WD = {
  esc: s => String(s), escAttr: s => String(s).replace(/"/g, '&quot;'),
  toast() {}, applyVersions() {}, savedWallTemplateName: () => Promise.resolve(''),
  wallTemplateOrder: l => l, chooseWallTemplate: () => null, wallTemplateLabel: t => t.name,
  api: (action, body) => { if (action === 'plantrim/boxes_save') saves.push(body);
                           return Promise.resolve({ ok: true, settings: {} }); },
};
const calls = [];
const FLOORS = [{ id: 'f1', name: 'Invented Ground', w: 1200, h: 900 },
                { id: 'f2', name: 'Invented Upper', w: 1200, h: 900 }];
const ASIDE = { f1: [400, 300, 1600, 1200] };
global.fetch = (url) => {
  calls.push(url);
  const body = url.indexOf('/prep/plan') >= 0
    ? { ok: true, steps: ['trim'], project: { projectId: 'prj-invented', floors: FLOORS,
          boxes: {}, boxesSetAside: ASIDE },
        step: { trim: { trimmedCount: 0, floorCount: 2, floors: [
          { id: 'f1', name: 'Invented Ground', action: 'skipped',
            reason: 'content already fills 100% of the canvas' },
          { id: 'f2', name: 'Invented Upper', action: 'skipped',
            reason: 'content already fills 100% of the canvas' }] } } }
    : url.indexOf('/prep/templates') >= 0 ? { ok: true, wall: [], capacity: [] }
    : { ok: true };
  return Promise.resolve({ json: () => Promise.resolve(body), ok: true,
                           headers: { get: () => null } });
};
const flush = () => new Promise(r => setTimeout(r, 0));
const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function param(url, name) {
  const m = new RegExp('[?&]' + name + '=([^&]*)').exec(url || '');
  return m ? decodeURIComponent(m[1]) : null;
}
function last() { return calls.filter(u => u.indexOf('/prep/plan') >= 0).pop(); }
(async () => {
  eval(src);
  docListeners.DOMContentLoaded();
  for (let i = 0; i < 5; i++) await flush();
  el('fileInput').listeners.change({ target: { files: [{ name: 'Invented (prepared).esx',
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) }], value: '' } });
  for (let i = 0; i < 8; i++) await flush();

  const panel = el('prepTrimFloors').innerHTML;
  check('the panel says the box was set aside: ' + panel,
        /Invented Ground<\/b>: the box saved for this floor was set aside/.test(panel)
        && /already been cropped/.test(panel));
  check('and only for the floor it belongs to', !/Invented Upper<\/b>: the box/.test(panel));

  window.prepMapSelect('f2');
  window.prepTrimDraw();
  for (let i = 0; i < 5; i++) await flush();
  const sent = JSON.parse(param(last(), 'boxes') || '{}');
  check('the set-aside box is not sent to be cropped to: ' + JSON.stringify(sent),
        sent.f2 && !sent.f1);
  const saved = saves.length ? saves[saves.length - 1].boxes : {};
  check('it stays stored for the original: ' + JSON.stringify(saved),
        saved.f1 && saved.f1.join() === '400,300,1600,1200' && saved.f2);

  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ASetAsideBoxIsNamedAndKept(unittest.TestCase):
    def test_the_panel_names_it_and_the_store_keeps_it(self):
        r = subprocess.run(["node", "-e", HARNESS, str(PREP_JS)],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())


if __name__ == "__main__":
    unittest.main()
