"""Squirrel's Organize page, ten faults from the second functional review.

Each test drives the operation that was wrong - the organizer route, or the
real ``organizer.js`` function in Node - in a throwaway user directory with
invented site folders.

* **Reset Defaults also reset Settings -> Default subfolders**
  (``subfolders`` and ``subfolder_names``), which this page does not own.
* **Migrate renamed from the shipped names**, so after one migration the
  folders were "Pictures" and a second migration looked for "images".
* **An extension typed without a dot** ("png") was saved and never matched.
* **A "/" in a destination name** broke Organize for every site, with an
  error about a folder that could not be read.
* **Create Folder's {date} was the UTC date**, a day ahead in the evening
  west of Greenwich.
* **Squirrel's own extracted floor plans were listed as unreferenced** -
  they are named after the floor, not after an ``imageName``.
* **Organize made a folder Default subfolders had removed** in every site,
  empty, and with nothing moved no undo log was written to take it back.
* **The preview's "(1)" names ignored unticked and redirected files**, so it
  showed a name execute did not write.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from tools import folder_organizer as fo  # noqa: E402
from tools import settings  # noqa: E402

HDR = {"X-WD-Wireless-Tools": "1"}
ORGANIZER_JS = ROOT / "web" / "assets" / "js" / "organizer.js"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "user"
        home.mkdir()
        for p in (patch.object(settings, "SETTINGS_FILE", home / "settings.json"),
                  patch.object(fo, "CONFIG_DIR", home),
                  patch.object(fo, "UNDO_DIR", home / "organizer_undo")):
            p.start()
            self.addCleanup(p.stop)
        settings.save_settings(settings.load_settings())
        self.client = server.app.test_client()
        self.root = Path(self.tmp.name) / "projects"
        self.root.mkdir()

    def org(self, action, body=None):
        return self.client.post("/api/organizer/" + action, json=body or {},
                                headers=HDR).get_json()

    def settings_patch(self, patch_):
        r = self.client.post("/api/settings/update", json={"patch": patch_},
                             headers=HDR).get_json()
        self.assertTrue(r.get("ok"), r)

    def global_settings(self):
        return self.client.post("/api/settings/get", json={},
                                headers=HDR).get_json()["settings"]["global"]

    def site(self, name, *files):
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            (d / f).write_bytes(b"x")
        return d


class ResetLeavesDefaultSubfoldersAloneTests(Base):
    def test_reset_keeps_what_settings_saved(self):
        self.settings_patch({"global": {
            "subfolders": ["images", "floorplans", "reports", "subfolder1"],
            "subfolder_names": {"subfolder1": "As-Built"}}})
        self.org("set_config", {"config": {"image_ext": [".bmp"]}})
        self.assertTrue(self.org("reset_config")["ok"])
        g = self.global_settings()
        self.assertEqual(g["subfolders"], ["images", "floorplans", "reports", "subfolder1"])
        self.assertEqual(g["subfolder_names"].get("subfolder1"), "As-Built")
        # ...and what this page owns is reset.
        self.assertIn(".png", self.org("get_config")["config"]["image_ext"])
        made = self.org("create_project_folder", {"name": "Sample Site", "root": str(self.root)})
        self.assertIn("As-Built", made["subfolders"])


class ExtensionsWithoutADotTests(Base):
    def test_png_typed_without_a_dot_still_sorts(self):
        self.org("set_config", {"config": {"image_ext": ["png", "JPG"]}})
        self.site("Sample Site", "photo.png", "shot.jpg")
        s = self.org("scan", {"root": str(self.root)})
        moves = {m["name"]: m["target"] for x in s["sites"] for m in x["moves"]}
        self.assertEqual(moves, {"photo.png": "images", "shot.jpg": "images"})


class ASlashInADestinationNameTests(Base):
    def test_it_is_refused_naming_the_field_and_nothing_is_saved(self):
        r = self.org("set_config", {"config": {"subfolder_names": {
            "images": "photos/2026", "floorplans": "floorplans", "reports": "reports"}}})
        self.assertFalse(r["ok"])
        self.assertIn("images", r["error"])
        self.assertIn("photos/2026", r["error"])
        self.assertEqual(self.org("get_config")["config"]["subfolder_names"]["images"], "images")

    def test_organize_still_works_when_one_was_saved_some_other_way(self):
        self.settings_patch({"global": {"subfolder_names": {"images": "photos/2026"}}})
        self.site("Sample Site", "photo.png")
        e = self.org("execute", {"root": str(self.root)})
        self.assertEqual(e["totals"]["errors"], 0, e)
        self.assertEqual(e["totals"]["images"], 1, e)


class ExtractedFloorPlansAreReferencedTests(Base):
    def test_the_extracted_plan_is_not_unreferenced(self):
        site = self.site("Site B")
        esx = site / "Site B.esx"
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 40
        with zipfile.ZipFile(esx, "w") as z:
            z.writestr("floorPlans.json", json.dumps({"floorPlans": [
                {"id": "f1", "name": "Level 1", "imageId": "i1", "bitmapImageId": "i2"}]}))
            z.writestr("images.json", json.dumps({"images": [
                {"id": "i1", "imageName": "L1-plan-rev3.png", "imageFormat": "PNG"},
                {"id": "i2", "imageName": "L1-plan-rev3-bitmap.png", "imageFormat": "PNG"}]}))
            z.writestr("image-i1", png)
            z.writestr("image-i2", png)
        x = self.org("extract_floorplans", {"path": str(esx), "selections": [{"id": "f1"}]})
        written = sorted(w["file"] for w in x["written"])
        self.assertEqual(written, ["Level 1 (raster).png", "Level 1.png"])
        (site / "floorplans" / "Stray sketch.png").write_bytes(png)
        s = self.org("scan", {"root": str(self.root)})
        unref = [u["name"] for st in s["sites"] for u in st["unreferenced"]]
        self.assertEqual(unref, ["Stray sketch.png"])


class AFolderDefaultSubfoldersRemovedTests(Base):
    def setUp(self):
        super().setUp()
        self.settings_patch({"global": {"subfolders": ["images", "floorplans"]}})

    def test_organize_does_not_make_it_when_nothing_goes_there(self):
        self.site("Site One", "photo.png")
        self.site("Site Two", "Survey.esx")
        self.org("execute", {"root": str(self.root)})
        self.assertFalse((self.root / "Site One" / "reports").exists())
        self.assertFalse((self.root / "Site Two" / "reports").exists())
        self.assertTrue((self.root / "Site One" / "images" / "photo.png").is_file())

    def test_it_is_made_when_a_file_goes_there_and_undo_removes_it(self):
        self.site("Site One", "summary.docx")
        e = self.org("execute", {"root": str(self.root)})
        self.assertEqual(e["totals"]["reports"], 1, e)
        self.assertTrue((self.root / "Site One" / "reports" / "summary.docx").is_file())
        self.assertTrue(self.org("undo", {"root": str(self.root)})["ok"])
        self.assertTrue((self.root / "Site One" / "summary.docx").is_file())
        self.assertFalse((self.root / "Site One" / "reports").exists())

    def test_the_preview_does_not_list_it_as_missing(self):
        self.site("Site One", "photo.png")
        s = self.org("scan", {"root": str(self.root)})
        self.assertEqual(sorted(s["sites"][0]["missing_subs"]), ["floorplans", "images"])


class PreviewNamesFollowTheChoicesTests(Base):
    """Two files that rename to one name: "a.png" and "A.png" cannot both be
    on most disks, so the clash is made with a prefix rule instead."""

    def setUp(self):
        super().setUp()
        self.org("set_config", {"config": {"rename": {"strip_prefix": "x-"}}})
        self.site("Site One", "plan.png", "x-plan.png")

    def names(self, **choices):
        s = self.org("scan", dict(root=str(self.root), **choices))
        return {m["name"]: m["renamed_to"] for m in s["sites"][0]["moves"]}

    def test_with_everything_ticked_the_second_gets_a_number(self):
        self.assertEqual(self.names(), {"plan.png": None, "x-plan.png": "plan (1).png"})

    def test_unticking_the_first_gives_the_second_its_own_name_as_execute_does(self):
        excluded = [{"folder": "Site One", "name": "plan.png"}]
        self.assertEqual(self.names(excluded=excluded)["x-plan.png"], "plan.png")
        self.org("execute", {"root": str(self.root), "excluded": excluded})
        self.assertTrue((self.root / "Site One" / "images" / "plan.png").is_file())

    def test_sending_the_first_elsewhere_gives_the_second_its_own_name(self):
        overrides = [{"folder": "Site One", "name": "plan.png", "target": "floorplans"}]
        self.assertEqual(self.names(overrides=overrides)["x-plan.png"], "plan.png")
        self.org("execute", {"root": str(self.root), "overrides": overrides})
        self.assertTrue((self.root / "Site One" / "images" / "plan.png").is_file())
        self.assertTrue((self.root / "Site One" / "floorplans" / "plan.png").is_file())


def _node(probe: str, *args: str, env: dict | None = None) -> dict:
    r = subprocess.run(["node", "-e", probe, str(ORGANIZER_JS), *args],
                       capture_output=True, encoding="utf-8", timeout=30,
                       env=dict(os.environ, **(env or {})))
    if r.returncode:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout)


SLICE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(sig) {
  const a = src.indexOf(sig);
  if (a < 0) throw new Error(sig + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
"""

MIGRATE = SLICE + r"""
(async () => {
  const typed = JSON.parse(process.argv[2]);
  const fields = { cfgSubImages: typed.images, cfgSubPlans: typed.floorplans, cfgSubReports: typed.reports };
  global.document = { getElementById: id => ({ value: fields[id] }) };
  global.currentRoot = '/invented';
  global.cachedConfig = { subfolder_names: JSON.parse(process.argv[3]) };
  global.confirm = () => true; global.toast = () => {}; global.doScan = () => {};
  const sent = [];
  global.api = async (a, b) => { sent.push([a, b]); return { ok: true, renamed: 0, skipped: 0 }; };
  eval(slice('async function migrateSubfolders() {') + ';global.migrateSubfolders = migrateSubfolders;');
  await migrateSubfolders();
  console.log(JSON.stringify(sent));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""

DATE = SLICE + r"""
const RealDate = Date;
const fixed = new RealDate('2026-10-02T03:30:00Z');
global.Date = class extends RealDate { constructor(...a) { if (a.length) super(...a); else super(fixed.getTime()); } };
eval(slice('function _rememberedToken(token) {') + ';global._rememberedToken=_rememberedToken;');
console.log(JSON.stringify({ date: _rememberedToken('date') }));
"""

NAMES = SLICE + r"""
(async () => {
  const cb = (site, file, checked) => ({ dataset: { site, file }, checked });
  const boxes = [cb('Site One', 'plan.png', false), cb('Site One', 'x-plan.png', true)];
  const selects = [];
  const span = { dataset: { renamedSite: 'Site One', renamedFile: 'x-plan.png' }, textContent: '(→ plan (1).png)', hidden: false };
  global.document = { querySelectorAll: q =>
    q.includes('input[data-file]') ? boxes : q.includes('select.dest-select') ? selects
      : q.includes('span.renamed') ? [span] : [] };
  global.scanData = { ok: true }; global.currentRoot = '/invented';
  const sent = [], pending = [];
  global.api = (a, b) => { sent.push([a, b]); return new Promise(r => pending.push(r)); };
  eval(slice('function organizeChoices() {') + ';global.organizeChoices=organizeChoices;');
  eval('var _namesSeq = 0;' + slice('async function refreshMoveNamesNow() {') + ';global.refreshMoveNamesNow=refreshMoveNamesNow;');
  const first = refreshMoveNamesNow();    // an older change...
  const second = refreshMoveNamesNow();   // ...and the newest
  pending[1]({ ok: true, sites: [{ folder: 'Site One', moves: [{ name: 'x-plan.png', renamed_to: null }] }] });
  await second;
  pending[0]({ ok: true, sites: [{ folder: 'Site One', moves: [{ name: 'x-plan.png', renamed_to: 'plan (1).png' }] }] });
  await first;
  console.log(JSON.stringify({ sent, text: span.textContent, hidden: span.hidden }));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePageTests(unittest.TestCase):
    def test_migrate_renames_from_the_saved_name(self):
        sent = _node(MIGRATE, json.dumps({"images": "Photos", "floorplans": "floorplans", "reports": "reports"}),
                     json.dumps({"images": "Pictures", "floorplans": "floorplans", "reports": "reports"}))
        self.assertEqual(sent, [["migrate_subfolders", {"root": "/invented", "renames": {"Pictures": "Photos"}}]])

    def test_migrate_after_saving_still_moves_the_shipped_name(self):
        sent = _node(MIGRATE, json.dumps({"images": "Pictures", "floorplans": "floorplans", "reports": "reports"}),
                     json.dumps({"images": "Pictures", "floorplans": "floorplans", "reports": "reports"}))
        self.assertEqual(sent, [["migrate_subfolders", {"root": "/invented", "renames": {"images": "Pictures"}}]])

    def test_create_folder_date_is_the_local_date(self):
        # 03:30 UTC on 2 October is the evening of 1 October in Los Angeles.
        out = _node(DATE, env={"TZ": "America/Los_Angeles"})
        self.assertEqual(out["date"], "2026-10-01")

    def test_a_changed_tick_asks_again_and_a_stale_reply_is_dropped(self):
        out = _node(NAMES)
        self.assertEqual(out["sent"][0], ["scan", {
            "root": "/invented", "excluded": [{"folder": "Site One", "name": "plan.png"}],
            "overrides": []}])
        self.assertEqual(out["text"], "")
        self.assertTrue(out["hidden"])


if __name__ == "__main__":
    unittest.main()
