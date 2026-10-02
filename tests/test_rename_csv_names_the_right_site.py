"""A CSV rename names each folder after its own row, and never writes a token.

Four faults from one review, all on Squirrel's Rename page with a CSV site
directory loaded:

* **The first id inside the folder name won.** With ids ST1 and ST12, the
  folder "ST12 Old Annex" was renamed after ST1, because "st1" is a substring
  of "st12 old annex". An id now counts only on a token boundary and only
  when one id matches (the longer wins when one is a prefix of the other);
  a match on part of an address is a guess, so its row is ``check`` - shown,
  and left out of what Apply sends - and every row says how it was matched.
* **A header with a space was offered as ``{Site Code}``**, which the format
  reader never fills, so ``{Site Code} - Lakeside`` was previewed as a rename.
  Headers are stripped, each gets a ``\\w+`` token key the token bar and the
  server share, and any ``{...}`` left over makes the row incomplete.
* **``{date}`` and ``{folder}`` never filled with a CSV loaded.**
* **Saving a profile under a name already saved replaced it silently.**

Driven through ``/api/rename/*`` in a throwaway state directory, with
invented sites. The page half runs the real ``rename.js`` in Node.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import tools.rename_manager as rm_module  # noqa: E402

HDR = {"X-WD-Wireless-Tools": "1"}
RENAME_JS = ROOT / "web" / "assets" / "js" / "rename.js"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        state = base / "state"
        state.mkdir()
        for p in (patch.object(rm_module, "CONFIG_DIR", state),
                  patch.object(rm_module, "DIRECTORY_PATH", state / "site_directory.json"),
                  patch.object(rm_module, "PROFILES_PATH", state / "rename_profiles.json"),
                  patch.object(rm_module, "UNDO_DIR", state / "rename_undo")):
            p.start()
            self.addCleanup(p.stop)
        self.client = server.app.test_client()
        self.root = base / "projects"
        self.root.mkdir()

    def call(self, action, body):
        return self.client.post("/api/rename/" + action, json=body,
                                headers=HDR).get_json()

    def folders(self, *names):
        for n in names:
            (self.root / n).mkdir()

    def load(self, csv_text, **column_map):
        r = self.call("load_directory", {"csv_text": csv_text,
                                         "column_map": column_map})
        self.assertTrue(r.get("ok"), r)
        return r

    def preview(self, fmt):
        r = self.call("preview_folder_rename", {"root": str(self.root),
                                                "format": fmt})
        self.assertTrue(r.get("ok"), r)
        return {row["current"]: row for row in r["renames"]}

    def applied(self, rows):
        """What the page sends to execute: the ``rename`` rows only."""
        return [r for r in rows.values() if r["status"] == "rename"]


class AFolderIsMatchedToItsOwnSiteTests(Base):
    CSV = ("site_code,site_name,address\n"
           "ST1,Riverside Clinic,12 Harbour Lane Northgate\n"
           "ST12,Old Annex Depot,40 Quarry Road Eastfield\n")

    def test_a_longer_id_is_not_taken_for_a_shorter_one(self):
        self.folders("ST12 Old Annex", "ST1 Riverside")
        self.load(self.CSV, primary="site_code")
        rows = self.preview("{site_code} - {site_name}")
        self.assertEqual(rows["ST12 Old Annex"]["new_name"], "ST12 - Old Annex Depot")
        self.assertEqual(rows["ST1 Riverside"]["new_name"], "ST1 - Riverside Clinic")

    def test_an_exact_id_wins(self):
        self.folders("ST12")
        self.load(self.CSV, primary="site_code")
        row = self.preview("{site_code} - {site_name}")["ST12"]
        self.assertEqual(row["new_name"], "ST12 - Old Annex Depot")
        self.assertEqual(row["method"], "exact")

    def test_the_longer_of_two_prefix_ids_wins(self):
        self.folders("ST1-A Wing")
        self.load("site_code,site_name\nST1,Riverside Clinic\nST1-A,Riverside Wing\n",
                  primary="site_code")
        row = self.preview("{site_code} - {site_name}")["ST1-A Wing"]
        self.assertEqual(row["new_name"], "ST1-A - Riverside Wing")

    def test_two_unrelated_ids_in_one_name_are_not_guessed(self):
        self.folders("ST1 and ST12 shared")
        self.load(self.CSV, primary="site_code")
        row = self.preview("{site_code} - {site_name}")["ST1 and ST12 shared"]
        self.assertEqual(row["status"], "unmatched")
        self.assertIsNone(row["new_name"])

    def test_execute_renames_the_folder_after_its_own_site(self):
        self.folders("ST12 Old Annex")
        self.load(self.CSV, primary="site_code")
        rows = self.preview("{site_code} - {site_name}")
        r = self.call("execute_folder_rename", {"root": str(self.root),
                                                "renames": self.applied(rows)})
        self.assertTrue(r["ok"], r)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ["ST12 - Old Annex Depot"])

    def test_a_partial_address_match_is_shown_for_a_look_and_not_applied(self):
        self.folders("Harbour Northgate")
        self.load(self.CSV, primary="site_code", address="address")
        rows = self.preview("{site_code} - {site_name}")
        row = rows["Harbour Northgate"]
        self.assertEqual(row["status"], "check")
        self.assertEqual(row["method"], "address-partial")
        self.assertEqual(row["new_name"], "ST1 - Riverside Clinic")
        self.assertTrue(any("address" in w for w in row["warnings"]), row)
        self.assertEqual(self.applied(rows), [])


class ACsvHeaderIsAToken(Base):
    def test_a_header_with_a_space_is_offered_as_a_token_that_fills(self):
        self.folders("Lakeside")
        self.load("Site Code,Site Name\nLS9,Lakeside\n", primary="Site Name")
        offered = [t["key"] for t in self.call("get_tokens", {})["tokens"] if t.get("csv")]
        self.assertEqual(offered, ["Site_Code", "Site_Name"])
        fmt = "{" + offered[0] + "} - {" + offered[1] + "}"
        row = self.preview(fmt)["Lakeside"]
        self.assertEqual((row["new_name"], row["status"]), ("LS9 - Lakeside", "rename"))

    def test_a_brace_left_unfilled_is_incomplete_never_a_rename(self):
        self.folders("Lakeside")
        self.load("Site Code,Site Name\nLS9,Lakeside\n", primary="Site Name")
        row = self.preview("{Site Code} - {Site_Name}")["Lakeside"]
        self.assertEqual(row["status"], "incomplete")
        self.assertIn("{Site Code}", " ".join(row["warnings"]))

    def test_a_space_after_the_comma_in_the_header_row(self):
        self.folders("Lakeside")
        r = self.call("load_directory", {"csv_text": "site_code, site_name\nLS9, Lakeside\n",
                                         "column_map": {"primary": "site_name"}})
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r["headers"], ["site_code", "site_name"])
        row = self.preview("{site_code} - {site_name}")["Lakeside"]
        self.assertEqual(row["new_name"], "LS9 - Lakeside")


class DateAndFolderFillWithACsvTests(Base):
    def test_date_and_folder_fill(self):
        self.folders("Lakeside")
        self.load("site_code,site_name\nLS9,Lakeside\n", primary="site_name")
        row = self.preview("{site_code} - {folder} ({date})")["Lakeside"]
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(row["new_name"], f"LS9 - Lakeside ({today})")
        self.assertEqual(row["status"], "rename")


class SavingOverAProfileAsksTests(Base):
    def test_the_server_reports_a_name_already_saved_and_keeps_it(self):
        self.assertTrue(self.call("save_profile", {"name": "Main", "folder_format": "{site_code}"})["ok"])
        r = self.call("save_profile", {"name": "Main", "folder_format": "{date}"})
        self.assertFalse(r["ok"])
        self.assertTrue(r["conflict"])
        self.assertIn('"Main"', r["error"])
        kept = self.call("list_profiles", {})["profiles"]["Main"]["folder_format"]
        self.assertEqual(kept, "{site_code}")

    def test_overwrite_replaces_it(self):
        self.call("save_profile", {"name": "Main", "folder_format": "{site_code}"})
        r = self.call("save_profile", {"name": "Main", "folder_format": "{date}", "overwrite": True})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.call("list_profiles", {})["profiles"]["Main"]["folder_format"], "{date}")


PAGE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const mode = process.argv[2];
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
const els = {};
const el = id => els[id] || (els[id] = { id, innerHTML: '', textContent: '', disabled: false, value: '' });
global.document = { getElementById: el };
global.esc = s => String(s);
(async () => {
  if (mode === 'preview') {
    global._renameState = { items: JSON.parse(process.argv[3]) };
    eval(slice('function _renderTokenPreview(') + ';global._renderTokenPreview=_renderTokenPreview;');
    _renderTokenPreview('folders');
    console.log(JSON.stringify({ disabled: el('renameApplyBtn').disabled,
      count: el('renamePreviewCount').textContent, list: el('renamePreviewList').innerHTML }));
    return;
  }
  // save: the server answers "conflict" the first time; the page asks, naming it.
  const answer = process.argv[3] === 'yes';
  el('renameProfileNameInput').value = 'Main';
  const sent = [], asked = [], toasts = [];
  global.renameApi = async (action, body) => {
    sent.push([action, body]);
    if (action !== 'save_profile') return {};
    return body.overwrite ? { ok: true } : { ok: false, conflict: true, existing: 'Main', error: 'taken' };
  };
  global.confirm = q => { asked.push(q); return answer; };
  global.toast = (m, k) => toasts.push([m, k || '']);
  global._getRuleValues = () => ({});
  global.showRenameProfiles = () => {};
  eval(slice('async function doSaveRenameProfile(') + ';global.doSaveRenameProfile=doSaveRenameProfile;');
  await doSaveRenameProfile();
  console.log(JSON.stringify({ sent, asked, toasts }));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePageTests(unittest.TestCase):
    def run_page(self, *args):
        r = subprocess.run(["node", "-e", PAGE, str(RENAME_JS), *args],
                           capture_output=True, encoding="utf-8", timeout=30)
        if r.returncode:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout)

    def test_a_row_to_check_is_counted_says_how_it_matched_and_is_not_applied(self):
        out = self.run_page("preview", json.dumps([
            {"current": "Harbour Northgate", "new_name": "ST1 - Riverside Clinic",
             "status": "check", "method": "address-partial",
             "warnings": ["Matched only on part of the address - check this is the right site"]},
        ]))
        self.assertTrue(out["disabled"])
        self.assertIn("1 to check", out["count"])
        self.assertIn("matched on part of address", out["list"])

    def test_the_match_method_is_on_a_rename_row(self):
        out = self.run_page("preview", json.dumps([
            {"current": "ST12 Old Annex", "new_name": "ST12 - Old Annex Depot",
             "status": "rename", "method": "contains-id", "warnings": []},
        ]))
        self.assertFalse(out["disabled"])
        self.assertIn("matched on id in name", out["list"])

    def test_saving_over_a_profile_asks_by_name_and_a_no_keeps_it(self):
        out = self.run_page("save", "no")
        self.assertEqual(len(out["asked"]), 1)
        self.assertIn('"Main"', out["asked"][0])
        self.assertEqual([b.get("overwrite") for a, b in out["sent"]], [None])

    def test_a_yes_resends_with_overwrite(self):
        out = self.run_page("save", "yes")
        self.assertEqual([b.get("overwrite") for a, b in out["sent"]], [None, True])
        self.assertIn('Profile "Main" saved', [m for m, k in out["toasts"]])


if __name__ == "__main__":
    unittest.main()
