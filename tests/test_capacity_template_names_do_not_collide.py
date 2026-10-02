"""Saving a capacity template never writes over a different template.

`save_template` wrote to the file its name maps to with no look at what was
already there, so a template was lost four ways: a new one saved under a name
already in use, Duplicate pressed twice (both proposed "<name> (copy)"), a
rename in the editor onto another template's name - which overwrote that one
and then deleted the original as "the old file" - and two names that differ
only in punctuation, because "Lab #1" and "Lab 1" are one file. On Windows and
macOS a fifth: renaming "Invented office" to "invented office" wrote the same
file and then deleted it, because the route compared the two names as
strings.

Driven through `/api/capacity/build` with invented templates; the page half
runs the real `capacity.js` in Node.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import server  # noqa: E402
from tools import capacity_profiles as cap  # noqa: E402

HDR = {"X-WD-Wireless-Tools": "1"}
CAPACITY_JS = ROOT / "web" / "assets" / "js" / "capacity.js"


def _can_symlink(where: Path) -> bool:
    probe = where / "probe-target"
    probe.write_text("x", encoding="utf-8")
    try:
        os.symlink(probe, where / "probe-link")
    except (OSError, NotImplementedError):
        return False
    finally:
        for p in (where / "probe-link", probe):
            try:
                p.unlink()
            except OSError:
                pass
    return True


def _case_insensitive(where: Path) -> bool:
    probe = where / "CaseProbe"
    probe.write_text("x", encoding="utf-8")
    try:
        return (where / "caseprobe").exists()
    finally:
        probe.unlink()


class Base(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        orig = cap.USER_DIR
        cap.USER_DIR = Path(self.tmp.name) / "capacity"
        cap.USER_DIR.mkdir()
        self.addCleanup(setattr, cap, "USER_DIR", orig)

    def build(self, name, per, replaces=None):
        spec = {"name": name, "items": [
            {"device": "Invented Laptop", "usage": "Invented Usage", "perOccupant": per}]}
        r = self.client.post("/api/capacity/build",
                             json={"spec": spec, "replaces": replaces}, headers=HDR)
        return r.get_json()

    def mine(self):
        """File -> (name, devices per person), for the user's own templates."""
        out = {}
        for t in self.client.post("/api/capacity/templates", json={},
                                  headers=HDR).get_json()["templates"]:
            if not t["_builtin"]:
                out[t["_file"]] = (t["name"], t["devicesPerOccupant"])
        return out


class ASaveOverAnotherTemplateIsRefused(Base):
    def test_a_new_template_under_a_name_in_use_is_refused_and_the_first_kept(self):
        first = self.build("Invented Office", 1.0)
        self.assertTrue(first["ok"], first)
        second = self.build("Invented Office", 3.0)
        self.assertFalse(second["ok"])
        self.assertIn('A template called "Invented Office" already exists', second["error"])
        self.assertEqual(self.mine(), {first["file"]: ("Invented Office", 1.0)})

    def test_duplicating_twice_does_not_lose_the_first_copy(self):
        self.build("Invented Office", 1.0)
        self.assertTrue(self.build("Invented Office (copy)", 2.0)["ok"])
        again = self.build("Invented Office (copy)", 5.0)
        self.assertFalse(again["ok"])
        self.assertIn(("Invented Office (copy)", 2.0), self.mine().values())

    def test_renaming_onto_another_template_keeps_both(self):
        alpha = self.build("Alpha Invented", 1.1)
        beta = self.build("Beta Invented", 2.2)
        r = self.build("Beta Invented", 1.1, replaces=alpha["file"])
        self.assertFalse(r["ok"])
        self.assertEqual(self.mine(), {alpha["file"]: ("Alpha Invented", 1.1),
                                       beta["file"]: ("Beta Invented", 2.2)})

    def test_names_that_differ_only_in_punctuation_do_not_share_a_file(self):
        self.build("Lab #1", 1.0)
        r = self.build("Lab 1", 4.0)
        self.assertFalse(r["ok"])
        self.assertIn('"Lab #1"', r["error"], "it names the template already there")
        self.assertEqual(list(self.mine().values()), [("Lab #1", 1.0)])

    def test_saving_the_template_being_edited_under_its_own_name_still_works(self):
        first = self.build("Invented Office", 1.0)
        r = self.build("Invented Office", 2.5, replaces=first["file"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.mine(), {first["file"]: ("Invented Office", 2.5)})

    def test_a_rename_to_a_free_name_still_removes_the_old_file(self):
        first = self.build("Invented Office", 1.0)
        r = self.build("Invented Studio", 1.0, replaces=first["file"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.mine(), {r["file"]: ("Invented Studio", 1.0)})


class ACaseOnlyRenameKeepsTheTemplate(Base):
    """On a case-insensitive disk the new name and the old one are one file.

    Linux's disks are case-sensitive, so the aliasing is reproduced with a
    symbolic link: two names, one file, which is exactly what Windows and
    macOS make of "Invented_Office" and "invented_office". The second test
    runs the real thing wherever the disk is case-insensitive.
    """

    def test_two_names_for_one_file_do_not_delete_it(self):
        if not _can_symlink(cap.USER_DIR):
            self.skipTest("symbolic links are not available here")
        first = self.build("Invented Office", 1.0)
        new_file = cap._safe_filename("invented office")
        os.symlink(cap.USER_DIR / first["file"], cap.USER_DIR / new_file)
        r = self.build("invented office", 2.0, replaces=first["file"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.mine(), {new_file: ("invented office", 2.0)})

    def test_on_a_case_insensitive_disk(self):
        if not _case_insensitive(cap.USER_DIR):
            self.skipTest("this disk is case-sensitive")
        first = self.build("Invented Office", 1.0)
        r = self.build("invented office", 2.0, replaces=first["file"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(list(self.mine().values()), [("invented office", 2.0)])


# The real page in Node: Duplicate proposes a name nobody has, and a refusal
# from the server is shown in the editor.
PAGE_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const TEMPLATES = JSON.parse(process.argv[2]);
const els = {};
function el(id) {
  if (!els[id]) els[id] = {
    id, innerHTML: '', textContent: '', value: '', checked: false, hidden: false,
    disabled: false, style: {}, files: [],
    classList: { add() {}, remove() {}, contains() { return false; } },
    listeners: {}, addEventListener(t, f) { this.listeners[t] = f; }, click() {}, focus() {},
  };
  return els[id];
}
global.document = { readyState: 'complete', getElementById: el,
                    querySelector: () => null, querySelectorAll: () => [],
                    createElement: () => ({ click() {}, remove() {} }),
                    body: { appendChild() {} } };
global.window = global;
global.setTimeout = (f) => 0;
global.WD = {
  esc: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  escAttr: s => String(s).replace(/&/g, '&amp;').replace(/'/g, '&#39;')
                         .replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  toast() {},
  api: () => Promise.resolve({ ok: true, settings: {} }),
};
const REFUSAL = 'A template called "Invented Office (copy)" already exists.';
global.fetch = (url) => {
  const body = url.indexOf('/templates') >= 0 ? { templates: TEMPLATES }
    : url.indexOf('/build') >= 0 ? { ok: false, exists: true, error: REFUSAL }
    : { ok: false, error: 'not under test' };
  return Promise.resolve({ json: () => Promise.resolve(body), headers: { get: () => null } });
};
const flush = () => new Promise(r => Promise.resolve().then(r));
(async () => {
  eval(src);
  for (let i = 0; i < 10; i++) await flush();
  const out = {};
  window.capChoose(TEMPLATES[0]._file);
  window.capDuplicateChosen();
  out.duplicate = el('capEdName').value;
  window.capChoose(TEMPLATES[TEMPLATES.length - 1]._file);
  window.capEditChosen();
  out.myCopy = el('capEdName').value;
  window.capEdSave();
  for (let i = 0; i < 10; i++) await flush();
  out.error = el('capEdError').textContent;
  out.errorShown = !el('capEdError').hidden;
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class DuplicateProposesAFreeName(unittest.TestCase):
    TEMPLATES = [
        {"_file": "Invented_Office_capacitytemplate.json", "_builtin": False,
         "name": "Invented Office", "items": []},
        {"_file": "Invented_Office_copy_capacitytemplate.json", "_builtin": False,
         "name": "Invented Office (copy)", "items": []},
        # Punctuation is dropped from the file name, so this one holds the
        # file "(copy 2)" would be saved under.
        {"_file": "Invented_Office_copy_2_capacitytemplate.json", "_builtin": False,
         "name": "Invented Office [copy 2]", "items": []},
        {"_file": "Invented_Example_my_copy_capacitytemplate.json", "_builtin": False,
         "name": "Invented Example (my copy)", "items": []},
        {"_file": "Invented_Example_capacitytemplate.json", "_builtin": True,
         "name": "Invented Example (example)", "items": []},
    ]

    def run_page(self):
        r = subprocess.run(["node", "-e", PAGE_HARNESS, str(CAPACITY_JS),
                            json.dumps(self.TEMPLATES)],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_duplicate_skips_every_name_already_taken(self):
        self.assertEqual(self.run_page()["duplicate"], "Invented Office (copy 3)")

    def test_editing_a_shipped_example_skips_a_copy_already_made(self):
        self.assertEqual(self.run_page()["myCopy"], "Invented Example (my copy 2)")

    def test_the_servers_refusal_is_shown_in_the_editor(self):
        out = self.run_page()
        self.assertTrue(out["errorShown"])
        self.assertIn("already exists", out["error"])


if __name__ == "__main__":
    unittest.main()
