"""The Report types a floor plan image by what the file is, not what it is called.

`readImageAsUrl` took the type from `images.json`'s `imageFormat` alone. Every
other tool goes through `WD.imageMime`, which reads the bytes first, because a
plan labelled PNG that is really an SVG is refused outright when its blob is
typed `image/png` - and the floor then renders blank in every map the Report
draws.

The real `readImageAsUrl` is cut out of report.js and the real `WD.imageMime`
out of wd-shared.js; the archive and the blob are stand-ins that record the
type they were given. The image bytes are a few invented ones.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "assets" / "js"

PROGRAM = r"""
const fs = require('fs');
const [shared, report] = process.argv.slice(1, 3).map(p => fs.readFileSync(p, 'utf8'));
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
eval('var IMAGE_MIME = ' + shared.match(/var IMAGE_MIME = (\{[^}]*\})/)[1] + ';');
eval(cut(shared, 'WD.sniffImageMime = function'));
eval(cut(shared, 'WD.imageMime = function'));

class Blob { constructor(parts, opts) { this.type = opts ? opts.type : ''; } }
const made = [];
const URL = { createObjectURL: b => { made.push(b.type); return 'blob:invented/' + made.length; } };
const bytesOf = s => Uint8Array.from(Buffer.from(s, 'latin1'));
const FILES = {
  'image-svg-as-png': bytesOf('<svg xmlns="http://www.w3.org/2000/svg"></svg>'),
  'image-png-as-svg': bytesOf('\x89PNG\r\n\x1a\n....'),
  'image-jpeg-unlabelled': bytesOf('\xff\xd8\xff\xe0....'),
  'image-unknown-labelled-gif': bytesOf('....'),
};
const esxZip = { file: n => FILES[n] ? { async: async kind => {
  return kind === 'blob' ? new Blob([FILES[n]]) : FILES[n]; } } : null };
const proj = { imageUrls: {}, images: {
  'svg-as-png': { imageFormat: 'PNG' },
  'png-as-svg': { imageFormat: 'SVG' },
  'jpeg-unlabelled': {},
  'unknown-labelled-gif': { imageFormat: 'GIF' },
} };
eval(cut(report, 'async function readImageAsUrl'));

(async () => {
  const types = {};
  for (const id of Object.keys(proj.images)) {
    made.length = 0;
    await readImageAsUrl(id);
    types[id] = made[0];
  }
  // A second ask for the same plan reuses the first object URL.
  made.length = 0;
  await readImageAsUrl('svg-as-png');
  console.log(JSON.stringify({ types, reused: made.length === 0,
                               missing: await readImageAsUrl('nope') }));
})();
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheReportTypesAFloorPlanByItsBytes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", PROGRAM, str(JS / "wd-shared.js"),
                            str(JS / "report.js")],
                           capture_output=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_an_svg_labelled_png_is_typed_as_an_svg(self):
        self.assertEqual("image/svg+xml", self.out["types"]["svg-as-png"])

    def test_a_png_labelled_svg_is_typed_as_a_png(self):
        self.assertEqual("image/png", self.out["types"]["png-as-svg"])

    def test_an_unlabelled_jpeg_is_still_recognised(self):
        self.assertEqual("image/jpeg", self.out["types"]["jpeg-unlabelled"])

    def test_the_label_is_used_when_the_bytes_say_nothing(self):
        self.assertEqual("image/gif", self.out["types"]["unknown-labelled-gif"])

    def test_a_plan_is_read_once_and_a_missing_one_is_null(self):
        self.assertTrue(self.out["reused"])
        self.assertIsNone(self.out["missing"])


if __name__ == "__main__":
    unittest.main()
