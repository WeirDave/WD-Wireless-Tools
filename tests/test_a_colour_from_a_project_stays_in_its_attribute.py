"""A colour read out of a project file cannot leave the attribute it is written to.

`WD.safeColor` accepted `rgb(` followed by anything up to a `)`, so

    rgb(1" data-action="call" data-fn="WD.api" x="2)

passed untouched, closed the `style` attribute it was written into and added
two more. The CSP stops script, but the action dispatcher resolves any dotted
path over `window`, so an injected `data-action` / `data-fn` becomes a call
made with the page's own authority when the card is clicked. A hostile project
file is a normal thing to meet here: they arrive by email.

The check is on behaviour. The real `safeColor` and `escAttr` are cut out of
`wd-shared.js`, the real card renderers are cut out of `walls.js`, and a
hostile colour is pushed through them. The markup that comes back has its
attributes read the way a browser reads them, and the card must still have only
the attributes the renderer wrote. A stub that passes everything through is not
used - that is what hid this.

Every colour here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "assets" / "js"

HARNESS = r"""
const fs = require('fs');
const [shared, walls] = process.argv.slice(2).map(p => fs.readFileSync(p, 'utf8'));

// Cut one function out by counting braces, so nothing after it comes along.
function cut(src, marker) {
  const a = src.indexOf(marker);
  if (a < 0) throw new Error('moved: ' + marker);
  let b = src.indexOf('{', a), depth = 0;
  for (; b < src.length; b++) {
    if (src[b] === '{') depth++;
    else if (src[b] === '}' && --depth === 0) { b++; break; }
  }
  return src.slice(a, b);
}

const WD = {};
eval(cut(shared, 'WD.escAttr = function'));
eval(cut(shared, 'WD.safeColor = function'));
const escAttr = WD.escAttr, safeColor = WD.safeColor;
// WD.esc escapes through textContent: & < > and not the quote.
const esc = s => s == null ? '' : String(s).replace(/&/g, '&amp;')
  .replace(/</g, '&lt;').replace(/>/g, '&gt;');

let rendered = {};
const document = { getElementById: id => ({ set innerHTML(v) { rendered[id] = v; } }) };
let wallTypes = [];
const fmtThickness = x => String(x), mToDisplay = x => x, unitLabel = () => 'm';
const heightBadge = () => '';
eval(cut(walls, 'function getKeybindMap'));
eval(cut(walls, 'function areaCard'));
eval(cut(walls, 'function renderWallCard'));
eval(cut(walls, 'function renderHotkeyPanel'));

// Attribute names of every start tag, read the way a browser reads them.
function tags(html) {
  const out = [];
  const tag = /<([a-zA-Z][\w-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>/g;
  let m;
  while ((m = tag.exec(html))) {
    const attrs = {};
    const attr = /([^\s=\/"'<>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
    let a;
    while ((a = attr.exec(m[2]))) {
      attrs[a[1]] = a[2] !== undefined ? a[2] : a[3] !== undefined ? a[3] : a[4] !== undefined ? a[4] : '';
    }
    out.push({ name: m[1], attrs });
  }
  return out;
}

const HOSTILE = [
  'rgb(1" data-action="call" data-fn="WD.api" x="2)',
  'rgba(1,2,3,.5)" onmouseover="x',
  'hsl(1" data-injected="1',
  '#fff" data-injected="1',
  'red; background:url(//x.invalid/)',
];
const GOOD = ['#FF0000', '#abc', 'rgb(255, 0, 0)', 'rgba(1,2,3,.5)',
              'hsl(120, 50%, 50%)', 'rgb(255 0 0 / 50%)'];

const result = { safe: {}, good: {}, cards: [], keybind: null };
for (const c of HOSTILE) result.safe[c] = safeColor(c);
for (const c of GOOD) result.good[c] = safeColor(c);

function injected(html) {
  return tags(html).filter(t => 'data-injected' in t.attrs || 'onmouseover' in t.attrs
    || t.attrs['data-fn'] === 'WD.api' || /url\(/.test(t.attrs.style || '')).length;
}

for (const c of HOSTILE) {
  const area = areaCard('Invented', c, 'meta', '');
  wallTypes = [{ name: 'Invented', color: c, keybindNumber: 3, propagationProperties: [] }];
  const card = renderWallCard(wallTypes[0], 0);
  renderHotkeyPanel();
  result.cards.push({
    colour: c,
    area: injected(area), card: injected(card), slot: injected(rendered.hotkeySlots),
    areaStyle: tags(area)[0].attrs.style,
    cardStyle: tags(card)[0].attrs.style,
  });
}

// A keybind number is written into markup, so it is a number whatever it holds.
const evil = '"><img src=x data-injected=1>';
wallTypes = [{ name: 'Invented', color: '#123456', keybindNumber: evil, propagationProperties: [] }];
const html = renderWallCard(wallTypes[0], 0);
result.keybind = { injected: injected(html), rawTag: html.includes('<img') };

console.log(JSON.stringify(result));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class AColourFromAProjectStaysInItsAttribute(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp(prefix="wd-colour-"))
        cls.addClassCleanup(shutil.rmtree, tmp, True)
        script = tmp / "harness.js"
        script.write_text(HARNESS, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(script), str(JS / "wd-shared.js"), str(JS / "walls.js")],
            capture_output=True, encoding="utf-8", timeout=60)
        if proc.returncode != 0:
            raise AssertionError((proc.stdout + proc.stderr).strip())
        cls.out = json.loads(proc.stdout)

    def test_a_colour_with_a_quote_in_it_is_refused(self):
        for colour, kept in self.out["safe"].items():
            with self.subTest(colour=colour):
                self.assertEqual("#888", kept)

    def test_real_colours_are_still_accepted(self):
        for colour, kept in self.out["good"].items():
            with self.subTest(colour=colour):
                self.assertEqual(colour, kept)

    def test_no_card_gains_an_attribute_from_a_hostile_colour(self):
        for card in self.out["cards"]:
            with self.subTest(colour=card["colour"]):
                self.assertEqual(0, card["area"], "attribute injected into area card")
                self.assertEqual(0, card["card"], "attribute injected into wall card")
                self.assertEqual(0, card["slot"], "attribute injected into shortcut slot")

    def test_the_card_still_carries_a_colour_when_the_one_given_is_refused(self):
        for card in self.out["cards"]:
            with self.subTest(colour=card["colour"]):
                self.assertEqual("--wall-color:#888", card["cardStyle"])
                self.assertEqual("--wall-color:#888", card["areaStyle"])

    def test_a_keybind_number_is_a_number_by_the_time_it_is_printed(self):
        self.assertEqual(0, self.out["keybind"]["injected"])
        self.assertFalse(self.out["keybind"]["rawTag"])


if __name__ == "__main__":
    unittest.main()
