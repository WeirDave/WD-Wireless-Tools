"""AP Labeler shows a floor plan whatever images.json calls it.

PlanTrim had this fault first: a floor plan member in an .esx carries no
extension, so the only name for its format is ``imageFormat`` in images.json,
and that label is not always what the bytes are. The Labeler believed the label
- and defaulted a missing one to PNG - so a vector plan labelled PNG, or not
labelled at all, was handed to the browser as ``image/png``. The browser refuses
SVG text typed that way, and the floor came up empty on the dark stage while a
raster floor in the same project displayed normally.

Both tools now type the blob through ``WD.imageMime`` in wd-shared.js, which
reads the bytes first and falls back to the label. These tests run the Labeler's
real ``loadFloorImage`` against the real shared helper and assert the type of
the blob it builds - the thing the browser decides on.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELER_JS = ROOT / "web" / "assets" / "js" / "ap-rename.js"
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"

NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const labeler = fs.readFileSync(process.argv[1], 'utf8');
const shared = fs.readFileSync(process.argv[2], 'utf8');

const sa = shared.indexOf('  var IMAGE_MIME = {');
const sb = shared.indexOf('  /* ── The Ekahau AP palette');
if (sa < 0 || sb < 0) throw new Error('image type helpers moved');
const WD = {};
eval(shared.slice(sa, sb));

function fn(src, head) {
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

const made = [];
class Blob { constructor(parts, opts) { this.type = (opts && opts.type) || ''; made.push(this); } }
const URL = { createObjectURL: () => 'blob:x' };

let S;
eval(fn(labeler, 'function loadFloorImage(floor) {'));

const text = (s) => new Uint8Array([...s].map(c => c.charCodeAt(0)));
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 13, 10, 26, 10, 0, 0]);

async function typeFor(bytes, declared) {
  made.length = 0;
  S = {
    floorImageUrls: {},
    imageFormats: declared === undefined ? {} : { img1: declared },
    zip: { file: (name) => name === 'image-img1'
             ? { async: () => Promise.resolve(bytes) } : null },
  };
  await loadFloorImage({ id: 'f1', imageId: 'img1' });
  if (made.length !== 1) throw new Error('expected one blob, got ' + made.length);
  return made[0].type;
}
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheLabelerTypesAPlanByWhatItIsTests(unittest.TestCase):

    def run_js(self, body: str) -> dict:
        script = PRELUDE + "(async () => {" + body + "})().catch(e => {" \
            " console.error(e && e.stack || e); process.exit(1); });"
        r = subprocess.run(["node", "-e", script, str(LABELER_JS), str(SHARED_JS)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout)

    def test_a_vector_plan_labelled_png_is_typed_as_svg(self):
        out = self.run_js("""
          console.log(JSON.stringify({
            t: await typeFor(text('<?xml version="1.0"?><svg/>'), 'PNG') }));
        """)
        self.assertEqual(out["t"], "image/svg+xml")

    def test_a_vector_plan_with_no_label_is_typed_as_svg(self):
        """The old code defaulted a missing imageFormat to PNG."""
        out = self.run_js("""
          console.log(JSON.stringify({
            t: await typeFor(text('\\n  <svg xmlns="x"/>')) }));
        """)
        self.assertEqual(out["t"], "image/svg+xml")

    def test_a_raster_labelled_svg_is_typed_as_what_it_is(self):
        out = self.run_js("""
          console.log(JSON.stringify({ t: await typeFor(PNG, 'SVG') }));
        """)
        self.assertEqual(out["t"], "image/png")

    def test_a_correct_label_still_works(self):
        out = self.run_js("""
          console.log(JSON.stringify({
            svg: await typeFor(text('<svg/>'), 'SVG'),
            png: await typeFor(PNG, 'PNG'),
            jpeg: await typeFor(new Uint8Array([0xff, 0xd8, 0xff, 0xe0]), 'JPEG'),
          }));
        """)
        self.assertEqual(out, {"svg": "image/svg+xml", "png": "image/png",
                               "jpeg": "image/jpeg"})


if __name__ == "__main__":
    unittest.main()
