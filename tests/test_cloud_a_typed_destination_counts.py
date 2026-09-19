"""A destination he typed is the destination, even if he never clicked a row.

Move to site auto-guesses a destination and fills the box with it. If he
disagrees, clicks the field and types a site name in full, the box shows what
he typed - and the move went to the guess.

`_resolveDest` read `t.destValue`, which only `_taPick` and `_taPickNew` ever
wrote, so text that was typed and never clicked was not a destination at all.
`_taBlur` then rewrote the visible text back from `destValue`, on a 150ms
timer, so nothing on screen ever admitted it: the field he had just filled in
still read what he typed while the file went somewhere else.

Committing on blur alone is not enough. A click on Move lands well inside that
150ms, so the typed text is committed at confirm time as well - that is the
ordering that actually bit.

An exact name is that site; anything else is a new one, which is what the list
offers while he is typing.

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
NODE_TIMEOUT_S = 120

NODE_SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}

// The typeahead, whole: the commit, the blur, both pick paths and the
// resolver. Sliced together so nothing between them is stubbed.
const block = slice('function _taDisplayText(', '\nasync function confirmMoveToSite(');

const boxes = {};
function fakeInput(idx, value) {
  return { dataset: { idx: String(idx) }, value: value, hidden: false,
           select: () => {}, focus: () => {} };
}
/* The slice reaches the destination preview, which writes into real elements.
   A generic stand-in keeps that on its ordinary path rather than making the
   probe depend on the preview being stubbed out. */
function fakeEl() {
  return { className: '', innerHTML: '', textContent: '', hidden: false,
           value: '', dataset: {}, style: {},
           classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
           setAttribute() {}, getAttribute: () => null, removeAttribute() {},
           appendChild: c => c, remove() {}, focus() {}, select() {},
           querySelector: () => null, querySelectorAll: () => [] };
}
globalThis.document = {
  getElementById: () => fakeEl(),
  querySelector: () => null,
  querySelectorAll: () => [],
};
globalThis.e = s => String(s == null ? '' : s);
globalThis.a = globalThis.e;
globalThis._outputDir = 'D:/Ekahau Projects';
globalThis._refreshPathPreview = () => {};
globalThis._renderMoveSource = () => {};
globalThis._setDestPreview = () => {};
globalThis._taGetList = () => null;
globalThis._taRenderList = () => '';
globalThis._taHighlight = -1;
globalThis._taApplyHighlight = () => {};
globalThis.toast = () => {};

const fn = new Function(block + `
  return { _taCommitTyped, _taPick, _taPickNew, _resolveDest, _taDisplayText,
           _taTargetFor, _taGetInput };
`);

// The sites he could move into, and the one file being moved.
globalThis._moveToSiteSites = [
  { name: 'Harbour Point North', id: 's-1', localFolder: 'Harbour Point North' },
  { name: 'Westgate Depot', id: 's-2', localFolder: 'Westgate Depot' },
];
globalThis._moveToSiteTargets = [];
globalThis._TA_MAX_RESULTS = 20;

const api = fn();
globalThis._taGetInput = (idx) => boxes[String(idx)] || null;
globalThis._taTargetFor = (idx) =>
  idx === 'global' ? _moveToSiteTargets[0] : _moveToSiteTargets[parseInt(idx, 10)];

function freshTarget(guessIdx) {
  _moveToSiteTargets.length = 0;
  _moveToSiteTargets.push({
    kind: 'local', path: 'D:/Ekahau Projects/Loose/Survey.esx', name: 'Survey',
    destValue: 'i:' + guessIdx, destAuto: true,
  });
}

const out = {};

// He disagrees with the guess and types the other site's name in full.
freshTarget(0);
boxes['0'] = fakeInput(0, 'Westgate Depot');
api._taCommitTyped('0', boxes['0'].value);
out.typedExisting = api._resolveDest(_moveToSiteTargets[0]);

// A name that is not any site is the new-site case the list offers.
freshTarget(0);
boxes['0'] = fakeInput(0, 'Eastfield Annexe');
api._taCommitTyped('0', boxes['0'].value);
out.typedNew = api._resolveDest(_moveToSiteTargets[0]);

// Case and stray spaces are still that site, not a new one beside it.
freshTarget(0);
boxes['0'] = fakeInput(0, '  westgate depot ');
api._taCommitTyped('0', boxes['0'].value);
out.typedCasing = api._resolveDest(_moveToSiteTargets[0]);

// Untouched: the guess stands.
freshTarget(1);
boxes['0'] = fakeInput(0, api._taDisplayText(_moveToSiteTargets[0]));
api._taCommitTyped('0', boxes['0'].value);
out.untouched = api._resolveDest(_moveToSiteTargets[0]);

// An emptied box is not an instruction to forget where it was going.
freshTarget(1);
boxes['0'] = fakeInput(0, '   ');
api._taCommitTyped('0', boxes['0'].value);
out.emptied = api._resolveDest(_moveToSiteTargets[0]);

process.stdout.write(JSON.stringify(out));
"""

_PROBE = {}


def probe():
    if not _PROBE:
        proc = subprocess.run(
            ["node", "-e", NODE_SCRIPT, str(CLOUD_JS)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError("node failed:\n" + proc.stderr)
        _PROBE.update(json.loads(proc.stdout))
    return _PROBE


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class WhatHeTypedIsWhereItGoes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_typing_an_existing_site_sends_it_there(self):
        got = self.out["typedExisting"]
        self.assertTrue(got["ready"], got)
        self.assertEqual("Westgate Depot", got["siteName"],
                         "it went to the guess, not to what he typed")
        self.assertEqual("s-2", got["siteId"])

    def test_typing_a_name_that_is_not_a_site_offers_to_create_it(self):
        got = self.out["typedNew"]
        self.assertTrue(got["ready"], got)
        self.assertEqual("Eastfield Annexe", got["folder"], got)
        self.assertIsNone(got["siteId"], got)

    def test_case_and_stray_spaces_still_mean_that_site(self):
        """Otherwise typing a site's own name creates a second one beside it."""
        got = self.out["typedCasing"]
        self.assertEqual("s-2", got["siteId"], got)

    def test_a_box_he_never_touched_keeps_the_guess(self):
        got = self.out["untouched"]
        self.assertTrue(got["ready"], got)
        self.assertEqual("Westgate Depot", got["siteName"], got)

    def test_an_emptied_box_does_not_forget_the_destination(self):
        got = self.out["emptied"]
        self.assertTrue(got["ready"], got)
        self.assertEqual("Westgate Depot", got["siteName"], got)


if __name__ == "__main__":
    unittest.main()
