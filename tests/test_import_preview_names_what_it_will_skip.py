"""The import preview says which entries of the file it will not write.

An import writes only the files an export itself produces. Anything else is
refused - including credential file names in any spelling - and the preview has
to say so, or a bundle's contents would be dropped without being named.

The real `showImportPreview`, `line` and `short` are cut out of
`settings-page.js` and run against a recording stand-in for the page, with the
server's real answer to a hostile bundle as the input.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent

from tools import settings, settings_backup

PAGE_JS = ROOT / "web" / "assets" / "js" / "settings-page.js"

PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(marker) {
  const a = src.indexOf(marker);
  if (a < 0) throw new Error(marker + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
const els = {};
const document = { getElementById: id => (els[id] = els[id] || { textContent: '', innerHTML: '', disabled: false }) };
const WD = { esc: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
             toast: () => {}, showModal: () => {} };
eval(slice('function short(') + '\n' + slice('function line(') + '\n' + slice('function showImportPreview('));
showImportPreview(JSON.parse(process.argv[2]));
process.stdout.write(JSON.stringify({ detail: els.sImportDetail.innerHTML }));
"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class ThePreviewNamesWhatItWillSkipTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-prev-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        p = mock.patch.object(settings, "SETTINGS_FILE", self.tmp / "settings.json")
        p.start()
        self.addCleanup(p.stop)

    def _detail(self, files):
        bundle = {"schema": settings_backup.SCHEMA_VERSION,
                  "files": {k: {"text": "{}"} for k in files}}
        preview = settings_backup.preview_import(bundle, root=self.tmp)
        r = subprocess.run(["node", "-e", PROBE, str(PAGE_JS), json.dumps(preview)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout)["detail"]

    def test_a_refused_file_is_named(self):
        detail = self._detail(["Cookies.json", "config.json"])
        self.assertIn("will be skipped", detail)
        self.assertIn("<code>Cookies.json</code>", detail)
        self.assertNotIn("<code>config.json</code>", detail.split("will be skipped")[1])

    def test_nothing_is_said_when_nothing_is_refused(self):
        self.assertNotIn("will be skipped", self._detail(["config.json"]))

    def test_a_name_is_escaped_before_it_is_shown(self):
        detail = self._detail(["<img src=x onerror=alert(1)>.json"])
        self.assertNotIn("<img", detail)
        self.assertIn("&lt;img", detail)


if __name__ == "__main__":
    unittest.main()
