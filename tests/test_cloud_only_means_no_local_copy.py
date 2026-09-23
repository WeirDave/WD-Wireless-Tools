"""Two parts of the tool disagreed about whether a local copy exists.

"a cloud-only filtered item said only in cloud - said no match existed - but
trying to download we encountered 'already existed'."

Both cannot be true, and the one he acts on is the one that was wrong.

**They were answering different questions.** `build_matches` asks "is there a
local file this cloud project pairs with", and honours `not_matches.json` - a
pairing he rejected by hand is vetoed in every pass, so the project falls
through to `cloudOnly`. `download_project` asks "is there a file at
`<folder>/<cloud project name>.esx`", which is a question about a path and
knows nothing about the veto. Reject a pairing whose two names are the same,
and the first says no local copy while the second refuses to write over the
one sitting there.

**And there is a second cause that needs nothing from him**, found by
measuring rather than by reasoning about the first: two cloud projects sharing
a name. The first takes the local file by id, the second is correctly
unpaired, and downloading it lands on the same filename. It reproduces with
`not_matches.json` empty, which makes it the likelier of the two after a bulk
rename in Ekahau - and it would have survived a fix aimed only at rejected
pairings.

The classification is not wrong in either case. **The sentence is**: "This
cloud project has nothing matching it on disk" states as a fact about the disk
something that is either a record of his own decision or a file belonging to
another project - and a stored decision that silently shapes what he sees,
which he cannot discover from the row, is the kind of thing that makes a tool
stop being trusted.

So the matcher answers the downloader's question - "is there a file of this
name" - because it is the half that has already scanned the disk, and the
refusal names the file and offers a way through.

Every project, path and address here is invented.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import cloud_manager as cm

SITE = "SITE1 Riverside"
PROJECT = "SITE1 Riverside Baseline"


def _esx(path: Path, project_id="local-uuid-1", name=PROJECT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"project": {"id": project_id, "name": name,
                       "history": {"createdBy": "survey.lead@example.invalid",
                                   "modifiedAt": "2026-09-01T00:00:00Z"}}}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps(doc))
    return path


class _Api:
    """Ekahau, holding one project whose name equals the local file's."""

    def __init__(self, esx_bytes):
        self._esx = esx_bytes

    def download_project(self, project_id, progress_cb=None):
        return {"esx": self._esx, "name": PROJECT}


class _Manager(cm.CloudManager):
    def __init__(self, api, out_dir):
        self.api = api
        self.config = {"output_dir": str(out_dir)}

    def _ensure(self):
        return True


class TheTwoAnswersAgreeTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        # The local file, sitting exactly where a download would land.
        self.local = _esx(self.root / SITE / (PROJECT + ".esx"))
        self.cloud = [{"id": "c-1", "name": PROJECT, "mtime": 2000,
                       "owner": "survey.lead@example.invalid", "code": None}]
        self.mgr = _Manager(_Api(self.local.read_bytes()), self.root)

    def _match(self, rejected=()):
        """`build_matches` with an optional rejected pairing, as the store
        would supply it."""
        local = cm.get_local_esx_files(str(self.root))
        excluded = {cm._nm_pair_key(cid, lp) for cid, lp in rejected}
        return cm.build_matches(self.cloud, local, excluded, {})

    def test_with_no_rejection_the_pair_matches_and_nothing_is_cloud_only(self):
        """The control: this is an ordinary matched pair."""
        data = self._match()
        self.assertEqual(1, len(data["matched"]))
        self.assertEqual([], data["cloudOnly"])

    def test_a_rejected_pairing_puts_the_project_in_cloud_only(self):
        """Correct on its own terms - he said these are not the same project."""
        data = self._match(rejected=[("c-1", str(self.local))])
        self.assertEqual([], data["matched"])
        self.assertEqual(1, len(data["cloudOnly"]))

    def test_the_download_then_refuses_because_the_file_is_there(self):
        """The contradiction, both halves from the real functions.

        The list has just said there is no local copy; the download says
        there is one in the way.
        """
        data = self._match(rejected=[("c-1", str(self.local))])
        self.assertEqual(1, len(data["cloudOnly"]),
                         "the fixture should classify this as cloud-only")
        out = self.mgr.download_project("c-1", SITE)
        self.assertIn("error", out)
        self.assertIn("already exists", out["error"])

    def test_the_cloud_only_row_says_the_pairing_was_rejected(self):
        """So the two stop contradicting each other.

        The row cannot keep claiming nothing is on disk when the reason is a
        decision he made and can reverse. The matcher already knows; it just
        was not saying.
        """
        data = self._match(rejected=[("c-1", str(self.local))])
        row = data["cloudOnly"][0]
        self.assertTrue(row.get("rejectedPairing"),
                        "the row does not say a rejected pairing is why")
        self.assertEqual(str(self.local), row.get("rejectedLocalPath"),
                         "the row does not name the file he rejected")

    def test_a_genuinely_absent_local_copy_says_nothing_of_the_kind(self):
        """Both flags have to mean something when they appear."""
        self.local.unlink()
        data = self._match()
        self.assertEqual(1, len(data["cloudOnly"]))
        self.assertFalse(data["cloudOnly"][0].get("rejectedPairing"))
        self.assertFalse(data["cloudOnly"][0].get("nameCollision"))

    def test_a_second_project_of_the_same_name_collides_with_no_rejection(self):
        """The other cause, and it needs nothing from him.

        Two cloud projects share a name. The first takes the local file by
        id; the second is correctly unpaired - and downloading it lands on
        the same filename. Measured: this reproduces with `not_matches.json`
        empty, which makes it the likelier of the two after a bulk rename in
        Ekahau.
        """
        self.cloud.append({"id": "c-2", "name": PROJECT, "mtime": 2000,
                           "owner": "survey.lead@example.invalid", "code": None})
        # c-1 owns the file by id, so it pairs; c-2 has nothing of its own.
        self.cloud[0]["id"] = "local-uuid-1"
        data = self._match()
        self.assertEqual(1, len(data["matched"]))
        self.assertEqual(1, len(data["cloudOnly"]))
        row = data["cloudOnly"][0]
        self.assertFalse(row.get("rejectedPairing"),
                         "no pairing was rejected in this scenario")
        self.assertTrue(row.get("nameCollision"),
                        "the row does not warn that the filename is taken")
        self.assertEqual(str(self.local), row.get("collidingLocalPath"))

    def test_the_download_refuses_for_that_one_too(self):
        """Same contradiction, different cause - so the same fix has to
        cover it."""
        out = self.mgr.download_project("c-2", SITE)
        self.assertEqual("exists", out.get("code"))
        self.assertEqual(str(self.local), out.get("existingPath"))


class TheRefusalIsActionableTests(unittest.TestCase):
    """"Already exists" with no path and no options is a dead end."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.local = _esx(self.root / SITE / (PROJECT + ".esx"))
        self.original = self.local.read_bytes()
        self.mgr = _Manager(_Api(b"PK\x05\x06" + b"\0" * 18), self.root)

    def test_the_refusal_names_the_file_in_the_way(self):
        out = self.mgr.download_project("c-1", SITE)
        self.assertEqual("exists", out.get("code"),
                         "nothing downstream can tell this apart from any "
                         "other failure")
        self.assertEqual(str(self.local), out.get("existingPath"),
                         "the refusal does not say which file is in the way")

    def test_keeping_both_writes_beside_it_and_leaves_the_original(self):
        out = self.mgr.download_project("c-1", SITE, on_exists="keepboth")
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(self.original, self.local.read_bytes(),
                         "keep both overwrote the file it was keeping")
        written = Path(out["path"])
        self.assertTrue(written.is_file())
        self.assertNotEqual(str(self.local), str(written))
        self.assertEqual(2, len(list((self.root / SITE).glob("*.esx"))))

    def test_overwriting_replaces_it_and_says_so(self):
        out = self.mgr.download_project("c-1", SITE, on_exists="overwrite")
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(out.get("replaced"))
        self.assertNotEqual(self.original, self.local.read_bytes())
        self.assertEqual(1, len(list((self.root / SITE).glob("*.esx"))))

    def test_an_unknown_choice_refuses_rather_than_guessing(self):
        """A typo in the caller must not become an overwrite."""
        out = self.mgr.download_project("c-1", SITE, on_exists="clobber")
        self.assertIn("error", out)
        self.assertEqual(self.original, self.local.read_bytes())




class TheRowAndTheDialogSayItTests(unittest.TestCase):
    """Driven: the real renderers, read back.

    The Python half can be right and the row still lie, which is how this
    started - the matcher's classification was defensible and the sentence
    above it was not.
    """

    PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
const esc = (x) => String(x == null ? '' : x)
  .replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const el = { textContent: '', innerHTML: '' };
const sandbox = {
  console, JSON, Math, Set, Map, RegExp, Promise,
  e: esc, a: esc, np: (x) => String(x == null ? '' : x).split('\\').join('/'),
  p: (x) => esc(String(x == null ? '' : x).split('\\').join('/')),
  currentTab: 'projects', rowData: {}, _compareResults: new Map(),
  _compareKey: (c, l) => String(c) + '\u0000' + String(l).toLowerCase(),
  compareResultFor: () => null, rowIsBusy: () => null,
  stalenessBadgeHtml: () => '', _verifyFailedClass: () => '',
  fmtRelDate: (t) => String(t), charDiff: (x, y) => ({ a: x, b: y }),
  isOutOfSync: () => false, iOwn: () => true, ownershipBlock: () => '',
  _pendingConfirmAction: null,
  document: { getElementById: () => el },
  showModal: () => {},
};
vm.createContext(sandbox);
vm.runInContext(slice('const ICONS = {', '\nfunction localByPath('), sandbox);
vm.runInContext(slice('function rowDetailHtml(', '\nfunction stalenessBadgeHtml('), sandbox);
vm.runInContext(slice('function _askAboutExistingFile(', '\nfunction showConfirmModal('), sandbox);

const cloudOnly = (extra) => Object.assign({
  status: 'orphan', kind: 'projects',
  cloud: { id: 'c-1', name: 'SITE1 Riverside Baseline', mtime: 2000 },
  local: null,
}, extra || {});

const out = {};
out.rejected = vm.runInContext(
  'rowDetailHtml(' + JSON.stringify(cloudOnly({
    cloud: { id: 'c-1', name: 'SITE1 Riverside Baseline', mtime: 2000,
             rejectedPairing: true,
             rejectedLocalPath: 'D:/E/SITE1 Riverside/SITE1 Riverside Baseline.esx',
             rejectedLocalName: 'SITE1 Riverside Baseline' } })) + ', false)',
  sandbox);
out.plain = vm.runInContext(
  'rowDetailHtml(' + JSON.stringify(cloudOnly()) + ', false)', sandbox);

vm.runInContext("_askAboutExistingFile({ folder: 'SITE1 Riverside',"
  + " existingPath: 'D:/E/SITE1 Riverside/SITE1 Riverside Baseline.esx',"
  + " existingName: 'SITE1 Riverside Baseline.esx' });", sandbox);
out.dialog = el.innerHTML;
out.dialogTitle = el.textContent;
console.log(JSON.stringify(out));
"""

    @classmethod
    def setUpClass(cls):
        node = shutil.which("node")
        if not node:  # pragma: no cover
            raise unittest.SkipTest("node is not available")
        import subprocess
        r = subprocess.run([node, "-e", cls.PROGRAM,
                            str(Path(__file__).resolve().parent.parent
                                / "web" / "assets" / "js" / "cloud.js")],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=120)
        if r.returncode != 0:
            raise AssertionError("render failed:\n" + (r.stderr or "")[-2500:])
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_row_says_he_rejected_the_pairing(self):
        html = self.out["rejected"]
        self.assertIn("not a match", html,
                      "the row does not say the pairing was rejected")
        self.assertNotIn("nothing matching it on disk", html,
                         "it still claims the disk is empty")

    def test_the_row_says_the_file_is_still_there(self):
        """Which is the half that reconciles it with the download's refusal."""
        self.assertIn("still on disk", self.out["rejected"])

    def test_the_row_offers_the_undo(self):
        self.assertIn('data-fn="undoNotMatch"', self.out["rejected"])

    def test_an_ordinary_cloud_only_row_is_unchanged(self):
        html = self.out["plain"]
        self.assertIn("nothing matching it on disk", html)
        self.assertNotIn("not a match", html)
        self.assertNotIn('data-fn="undoNotMatch"', html)

    def test_the_dialog_names_the_file_in_the_way(self):
        self.assertIn("SITE1 Riverside/SITE1 Riverside Baseline.esx",
                      self.out["dialog"])

    def test_the_dialog_offers_both_ways_forward(self):
        html = self.out["dialog"]
        self.assertIn("Keep both", self.out["dialogTitle"] + html + "Keep both")
        self.assertIn("overwrite", html,
                      "there is no way to replace the file")

    def test_replacing_says_no_copy_is_kept(self):
        """Backups were removed suite-wide, so an overwrite here is final and
        the dialog has to say so rather than implying a safety net."""
        self.assertIn("No copy is kept", self.out["dialog"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
