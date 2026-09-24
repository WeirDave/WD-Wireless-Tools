"""A rename with a token left blank is shown, and never offered to Apply.

With no CSV, Folder Convention takes each token's value from a field on the
page. A field left empty produced a name carrying ``__site_code__`` with
status ``rename``, and Apply wrote that placeholder onto the folder. The row
is ``incomplete`` now: still listed, with the warning naming the token, and
left out of what Apply sends.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import tools.rename_manager as rm_module  # noqa: E402

HDR = {"X-WD-Wireless-Tools": "1"}
RENAME_JS = ROOT / "web" / "assets" / "js" / "rename.js"


class ServerMarksTheRowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        state = base / "state"
        state.mkdir()
        self.patchers = [
            patch.object(rm_module, "CONFIG_DIR", state),
            patch.object(rm_module, "DIRECTORY_PATH", state / "site_directory.json"),
        ]
        for p in self.patchers:
            p.start()
        self.client = server.app.test_client()
        self.root = base / "projects"
        (self.root / "Alpha Site").mkdir(parents=True)

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.tmp.cleanup()

    def preview(self, values):
        return self.client.post("/api/rename/preview_folder_rename", json={
            "root": str(self.root), "format": "{site_code} - {folder}",
            "manual_values": values,
        }, headers=HDR).get_json()

    def test_a_blank_value_is_incomplete_and_names_the_token(self):
        row = self.preview({"site_code": ""})["renames"][0]
        self.assertEqual(row["status"], "incomplete")
        self.assertIn("{site_code}", " ".join(row["warnings"]))

    def test_a_filled_value_is_still_a_rename(self):
        row = self.preview({"site_code": "ZZ01"})["renames"][0]
        self.assertEqual(row["status"], "rename")
        self.assertEqual(row["new_name"], "ZZ01 - Alpha Site")


PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(name) {
  const a = src.indexOf('function ' + name + '(');
  if (a < 0) throw new Error(name + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
const els = {};
const el = id => els[id] || (els[id] = { id, innerHTML: '', textContent: '', disabled: false });
global.document = { getElementById: el };
global.esc = s => String(s);
let _renameState = { items: JSON.parse(process.argv[2]) };
eval(slice('_renderTokenPreview'));
_renderTokenPreview('folders');
console.log(JSON.stringify({
  disabled: el('renameApplyBtn').disabled,
  count: el('renamePreviewCount').textContent,
  list: el('renamePreviewList').innerHTML,
}));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePageDoesNotOfferItTests(unittest.TestCase):
    def render(self, items):
        r = subprocess.run(["node", "-e", PROBE, str(RENAME_JS), json.dumps(items)],
                           capture_output=True, encoding="utf-8", timeout=30)
        if r.returncode:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout)

    def test_apply_is_disabled_when_every_row_is_incomplete(self):
        out = self.render([{"current": "Alpha Site",
                            "new_name": "__site_code__ - Alpha Site",
                            "status": "incomplete",
                            "warnings": ["Missing value for {site_code}"]}])
        self.assertTrue(out["disabled"])
        self.assertIn("1 needs a value", out["count"])
        self.assertIn("Missing value for {site_code}", out["list"])

    def test_apply_still_works_for_the_complete_rows(self):
        out = self.render([
            {"current": "A", "new_name": "__x__ - A", "status": "incomplete",
             "warnings": ["Missing value for {x}"]},
            {"current": "B", "new_name": "B2", "status": "rename", "warnings": []},
        ])
        self.assertFalse(out["disabled"])
        self.assertIn("1 to rename", out["count"])


if __name__ == "__main__":
    unittest.main()
