"""Prepare stays greyed out until every stage has been opened, and a finished
run says it is finished.

Two things were wrong on Prep's one screen. The only button on it was Prepare,
so nothing said the stages down the left were the thing to click next, and a
project that needed nothing changed could be prepared without ever opening one.
And after a run the page stayed exactly as it was with a small green line under
it, which looked like unfinished business: the one tool in the suite that never
said it was done.

The real `prep.js` is loaded in Node over a recording DOM, a project is
"dropped", and the controls are driven the way a person would: stages opened
one by one, Prepare pressed, and the Finish button pulled back out of the
rendered result and run. What is asserted is what the page then does.
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests.area_stub import with_area_stub  # noqa: E402
from tests.test_the_multiplier_is_shown import PREP_HARNESS, PREP_JS  # noqa: E402

MARK = "  window.prepStage('areas');"

PLAN = {
    "ok": True, "steps": ["trim", "areas", "walls"], "project": {},
    "step": {
        "trim": {"trimmedCount": 1, "repairedCount": 0, "floorCount": 1,
                 "floors": [{"id": "f1", "name": "Ground", "action": "trimmed",
                             "source": "auto", "oldSize": [800, 600],
                             "newSize": [400, 300], "offset": [10, 10],
                             "areaSavedPct": 50}]},
        "areas": {"ok": True, "willWrite": 1, "occupants": 200, "totalDevices": 600,
                  "devicesPerPerson": 3,
                  "floors": [{"floorPlanId": "f1", "floorName": "Ground", "action": "add"}]},
        "walls": {"add": [{"name": "Invented wall"}], "update": [], "unchanged": 0},
    },
}

RAN = {"ok": True, "ran": ["trim", "areas", "walls"], "failed": []}
DOWNLOAD_REPORT = dict(RAN, trimmed=1, floorCount=1, areasWritten=["f1"],
                       wallTypesAdded=["Invented wall"], wallTypesUpdated=[])
DISK_RESULT = dict(RAN, written=True, filename="Invented (prepared).esx",
                   dir="D:/Invented", path="D:/Invented/Invented (prepared).esx",
                   step={"trim": {"trimmedCount": 1, "floorCount": 1},
                         "areas": {"floorsWritten": ["f1"]},
                         "walls": {"add": [{"name": "Invented wall"}], "update": [],
                                   "unchanged": 0}})

TAIL = r"""
  const MODE = process.argv[4];
  const REPORT = JSON.parse(process.argv[5]);
  const calls = [];
  const removed = [];
  el('editor').classList.remove = (c) => removed.push(c);
  document.querySelector = () => null;
  window.scrollTo = () => {};
  document.createElement = () => ({ click() {}, remove() {}, style: {} });
  ['trim', 'areas', 'walls'].forEach(s => { el('prepStep-' + s).checked = true; });
  const json = (b) => Promise.resolve({ json: () => Promise.resolve(b), ok: true,
                                        status: 200, headers: { get: () => null } });
  global.fetch = (url) => {
    calls.push(url);
    if (url.indexOf('/prep/plan') >= 0) return json(PLAN);
    if (url.indexOf('/prep/pick') >= 0) return json({ ok: true, name: 'Invented.esx', dir: 'D:/Invented' });
    if (url.indexOf('/prep/run') >= 0) {
      if (MODE === 'disk') return json(REPORT);
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(REPORT),
        headers: { get: (h) => h === 'X-WD-Prep-Report' ? encodeURIComponent(JSON.stringify(REPORT)) : null },
        blob: () => Promise.resolve({}) });
    }
    return json({ ok: true, settings: {} });
  };
  const flushAll = async () => { for (let i = 0; i < 10; i++) await flush(); };
  const btn = el('prepGoBtn');
  const snap = () => ({ disabled: btn.disabled, label: btn.textContent, title: btn.title,
    note: el('prepGoNote').innerHTML,
    marks: ['trim', 'areas', 'walls'].map(s => el('prepSeen-' + s).textContent) });
  const loadProject = async () => {
    if (MODE === 'disk') { window.prepOpenFromDisk(); }
    else {
      el('fileInput').listeners.change({ target: { files: [{ name: 'Invented.esx',
        arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) }], value: '' } });
    }
    await flushAll();
  };
  const out = {};
  await loadProject();
  out.opened = snap();
  window.prepStage('areas');  out.areasOpened = snap();
  window.prepStage('walls');  out.allOpened = snap();

  window.prepRun(); out.duringRun = snap(); await flushAll();
  out.afterRun = Object.assign(snap(), { html: el('prepResult').innerHTML });
  const m = /data-fn="(\w+)"[^>]*>Finish</.exec(el('prepResult').innerHTML);
  out.finishFn = m && m[1];
  if (!m) throw new Error('no Finish button in: ' + el('prepResult').innerHTML);
  window[out.finishFn]();
  out.afterFinish = Object.assign(snap(), {
    result: el('prepResult').innerHTML, dropzone: el('dropzone').style.display,
    removed, forgot: calls.filter(c => c.indexOf('/prep/forget') >= 0).length,
    badge: el('fileBadge').style.display });

  // The next project starts from nothing looked at.
  await loadProject();
  out.nextProject = snap();

  // A stage left out is not asked for.
  el('prepStep-areas').checked = false;
  window.prepSyncStepUi(); await flushAll();
  out.areasOff = snap();
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def drive(mode, report):
    head = PREP_HARNESS[:PREP_HARNESS.index(MARK)]
    script = with_area_stub(head) + TAIL
    r = subprocess.run(["node", "-e", script, str(PREP_JS), json.dumps(PLAN), "200",
                        mode, json.dumps(report)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout)


needs_node = unittest.skipUnless(shutil.which("node"), "Node.js is not installed")


@needs_node
class PrepareWaitsUntilEveryStageHasBeenOpened(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.run_ = drive("download", DOWNLOAD_REPORT)

    def test_a_project_just_opened_cannot_be_prepared_yet(self):
        o = self.run_["opened"]
        self.assertTrue(o["disabled"], "Prepare was live before two stages had been opened")
        self.assertEqual(o["label"], "Prepare")

    def test_the_footer_names_the_stages_still_to_open(self):
        o = self.run_["opened"]
        self.assertIn("Requirement areas", o["note"])
        self.assertIn("Wall types", o["note"])
        self.assertNotIn("Trim the canvas", o["note"], "Trim is the stage on screen")
        self.assertIn("Requirement areas", o["title"], "the greyed button says why on hover")

    def test_the_stage_cards_say_which_are_checked(self):
        self.assertEqual(self.run_["opened"]["marks"],
                         ["✓ Checked", "Click to check", "Click to check"])
        self.assertEqual(self.run_["areasOpened"]["marks"],
                         ["✓ Checked", "✓ Checked", "Click to check"])

    def test_opening_some_but_not_all_still_waits(self):
        o = self.run_["areasOpened"]
        self.assertTrue(o["disabled"])
        self.assertIn("Wall types", o["note"])
        self.assertNotIn("Requirement areas", o["note"])

    def test_opening_the_last_one_unlocks_prepare_with_the_usual_footer(self):
        o = self.run_["allOpened"]
        self.assertFalse(o["disabled"])
        self.assertNotIn("unlocks", o["note"])
        self.assertIn("Will write", o["note"], "the footer's account of the run is back")
        self.assertEqual(o["title"], "")

    def test_a_stage_that_is_ticked_off_is_not_asked_for(self):
        o = self.run_["areasOff"]
        self.assertIn("Wall types", o["note"])
        self.assertNotIn("Requirement areas", o["note"])
        self.assertEqual(o["marks"][1], "")

    def test_the_next_project_starts_with_nothing_looked_at(self):
        o = self.run_["nextProject"]
        self.assertTrue(o["disabled"])
        self.assertEqual(o["marks"], ["✓ Checked", "Click to check", "Click to check"])

    def test_the_button_is_busy_while_the_run_is_in_flight(self):
        d = self.run_["duringRun"]
        self.assertTrue(d["disabled"])
        self.assertEqual(d["label"], "Preparing…")


@needs_node
class AFinishedRunSaysSo(unittest.TestCase):

    def check(self, run, where):
        a = run["afterRun"]
        self.assertIn("Done", a["html"], where)
        self.assertIn("Invented", a["html"], where)
        self.assertIn("Not right?", a["html"], where)
        self.assertEqual(a["label"], "Prepare again", where)
        self.assertFalse(a["disabled"], where + ": a second pass must stay possible")
        self.assertEqual(run["finishFn"], "prepFinish", where)

        f = run["afterFinish"]
        self.assertEqual(f["result"], "", where + ": the result card goes with the project")
        self.assertEqual(f["dropzone"], "", where + ": the start screen is back")
        self.assertIn("active", f["removed"], where)
        self.assertEqual(f["badge"], "none", where)
        self.assertGreaterEqual(f["forgot"], 1, where + ": the server forgets the picked path")
        self.assertTrue(f["disabled"], where)
        self.assertEqual(f["label"], "Prepare", where)

    def test_a_downloaded_copy_ends_on_a_finished_card(self):
        run = drive("download", DOWNLOAD_REPORT)
        self.check(run, "download")
        self.assertIn("downloads another copy", run["afterRun"]["html"])

    def test_a_copy_written_beside_the_original_ends_on_a_finished_card(self):
        run = drive("disk", DISK_RESULT)
        self.check(run, "disk")
        html = run["afterRun"]["html"]
        self.assertIn("D:/Invented", html)
        self.assertIn("Show me the file", html)
        self.assertIn("asks before it replaces", html)


if __name__ == "__main__":
    unittest.main()
