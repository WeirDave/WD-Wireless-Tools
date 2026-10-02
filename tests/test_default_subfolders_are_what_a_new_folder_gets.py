"""Settings → Default subfolders decides what a new site folder is given.

Settings and Setup both save `global.subfolders` - with add, remove and
reorder controls, under the words "Created automatically in new site
folders" - and the one resolver every folder-maker uses never read it.
Removing "reports" did not stop it being made; a subfolder added there was
never made at all.

Held where folders are actually made: Squirrel's `create_project_folder`,
Cloud Manager's `create_local_folder`, and the Create Folder dialog's ticked
boxes (the real `organizer.js`, in Node). And the other half: a built-in left
off the list is still where Squirrel sorts files to, because "do not pre-make
an empty reports folder" is not "stop sorting reports".

The settings are written through `/api/settings/update` with a patch envelope,
the way the Settings page writes them, into a throwaway user directory.
"""
from __future__ import annotations

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
from tools import cloud_manager as cm  # noqa: E402
from tools import folder_organizer as fo  # noqa: E402
from tools import settings  # noqa: E402

HDR = {"X-WD-Wireless-Tools": "1"}
ORGANIZER_JS = ROOT / "web" / "assets" / "js" / "organizer.js"


class _Mgr(cm.CloudManager):
    def __init__(self, out_dir):
        self.api = None
        self.config = {"output_dir": str(out_dir)}

    def _ensure(self):
        return True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "user"
        home.mkdir()
        for p in (patch.object(settings, "SETTINGS_FILE", home / "settings.json"),
                  patch.object(fo, "CONFIG_DIR", home)):
            p.start()
            self.addCleanup(p.stop)
        settings.save_settings(settings.load_settings())
        self.root = Path(self.tmp.name) / "sites"
        self.root.mkdir()
        self.client = server.app.test_client()

    def save(self, subfolders, names):
        r = self.client.post("/api/settings/update", headers=HDR, json={
            "patch": {"global": {"subfolders": subfolders, "subfolder_names": names}}})
        self.assertTrue(r.get_json()["ok"])

    def made(self, site):
        return sorted(p.name for p in (self.root / site).iterdir() if p.is_dir())


class ANewSiteFolderGetsTheList(Base):
    def test_a_removed_subfolder_is_not_made_and_an_added_one_is(self):
        self.save(["images", "floorplans", "subfolder"],
                  {"images": "images", "floorplans": "floorplans",
                   "subfolder": "Invented Photos"})
        r = fo.FolderOrganizer().create_project_folder("Invented Site", str(self.root))
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.made("Invented Site"), ["Invented Photos", "floorplans", "images"])
        self.assertEqual(r["subfolders"], ["images", "floorplans", "Invented Photos"])

    def test_the_order_is_the_lists(self):
        self.save(["reports", "images"], {"reports": "Invented Reports", "images": "images"})
        r = fo.FolderOrganizer().create_project_folder("Invented Site", str(self.root))
        self.assertEqual(r["subfolders"], ["Invented Reports", "images"])

    def test_cloud_manager_makes_the_same_folders(self):
        self.save(["images", "subfolder"], {"images": "images", "subfolder": "Invented Photos"})
        r = _Mgr(self.root).create_local_folder("Invented Site")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(self.made("Invented Site"), ["Invented Photos", "images"])

    def test_with_nothing_changed_all_three_are_made(self):
        r = fo.FolderOrganizer().create_project_folder("Invented Site", str(self.root))
        self.assertEqual(r["subfolders"], ["images", "floorplans", "reports"])


class OrganizingStillSortsToARemovedBuiltIn(Base):
    def test_a_report_still_goes_to_reports(self):
        self.save(["images", "floorplans"], {"images": "images", "floorplans": "floorplans"})
        cfg = fo._load_config()
        self.assertEqual(fo._classify(Path("invented-survey.docx"), cfg), "reports")
        self.assertEqual(fo._dest_name(cfg, "reports"), "reports")
        self.assertIn("reports", fo._effective_skip(cfg))

    def test_an_added_subfolder_takes_no_files_and_is_not_scanned_into(self):
        self.save(["images", "subfolder"], {"images": "images", "subfolder": "Invented Photos"})
        cfg = fo._load_config()
        for name in ("a.png", "b.dwg", "c.docx", "d.pdf"):
            self.assertNotEqual(fo._classify(Path(name), cfg), "subfolder", name)
        self.assertIn("invented photos", fo._effective_skip(cfg))


# The Create Folder dialog: which boxes are ticked when it opens.
PICKER_PROBE = r"""
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
let scanData = null;
let cachedConfig = JSON.parse(process.argv[2]);
const escAttr = s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
  .replace(/</g, '&lt;').replace(/>/g, '&gt;');
const host = { innerHTML: '' };
const document = { getElementById: id => (id === 'newFolderSubs' ? host : null) };
eval(slice('function destinationList(cfg) {'));
eval(slice('function destinationCssClass(key) {'));
eval(slice('function _defaultSubfolderNames(cfg) {'));
eval(slice('function _renderSubfolderPicker() {'));
_renderSubfolderPicker();
const rows = host.innerHTML.split('</label>').filter(Boolean).map(r => ({
  name: (/class="org-sub-name-input" value="([^"]*)"/.exec(r) || [])[1],
  checked: /class="org-sub-cb" checked/.test(r),
}));
console.log(JSON.stringify(rows));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheCreateFolderDialogTicksTheList(unittest.TestCase):
    def rows(self, cfg):
        r = subprocess.run(["node", "-e", PICKER_PROBE, str(ORGANIZER_JS), json.dumps(cfg)],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_ticked_is_the_list_in_its_order_and_the_rest_is_offered(self):
        rows = self.rows({"subfolders": ["floorplans", "subfolder"],
                          "subfolder_names": {"floorplans": "Invented Plans",
                                              "subfolder": "Invented Photos"}})
        self.assertEqual([r["name"] for r in rows if r["checked"]],
                         ["Invented Plans", "Invented Photos"])
        self.assertEqual(sorted(r["name"] for r in rows if not r["checked"]),
                         ["images", "reports"])

    def test_with_no_list_saved_every_destination_is_ticked(self):
        rows = self.rows({})
        self.assertEqual([r["name"] for r in rows if r["checked"]],
                         ["images", "floorplans", "reports"])


if __name__ == "__main__":
    unittest.main()
