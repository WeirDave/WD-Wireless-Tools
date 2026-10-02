"""A download leaves no folder behind that nobody asked for.

* **An expired sign-in mid-operation.** Rename, delete, create site, assign
  and download returned `str(e)`, so the page showed raw "401 Client Error:
  Unauthorized for url: ..." text and kept the dead session. They now go
  through the same path as the listing: the plain sign-in-again message and
  `sessionExpired`. And the download made its site folder before fetching a
  byte, so a failed one left a new, empty folder that the list then showed as
  a local-only site.
* **A project in no cloud site.** It lands in a new folder named after the
  project and is then sorted under a site with Move to site. That folder
  stayed behind, holding only the empty default subfolders. The page now asks
  for it to be tidied, and the server removes it only when no file is in it.

The cloud is a stub that answers 401, as `requests` would deliver it. Every
name and address here is invented.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import requests

from tests import cloud_vm
from tools import cloud_manager as cm


def _resp401(url):
    r = requests.Response()
    r.status_code = 401
    r.reason = "Unauthorized"
    r.url = url
    r._content = b""
    return r


class _Http401:
    cookies = None
    headers = {}

    def get(self, url, **kw):
        return _resp401(url)

    def request(self, method, url, **kw):
        return _resp401(url)


class _Case(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wd-dl-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)


class AnExpiredSessionMidOperationTests(_Case):

    def _mgr(self):
        api = cm.EkahauAPI([], "invented-token")
        api.http = _Http401()
        api.user_email = "pat@example.invalid"
        mgr = cm.CloudManager.__new__(cm.CloudManager)
        mgr.api = api
        mgr.config = {"output_dir": str(self.root)}
        return mgr

    def _assert_expired(self, mgr, r):
        self.assertEqual(cm.CloudManager.SESSION_EXPIRED, r.get("error"), r)
        self.assertTrue(r.get("sessionExpired"), r)
        self.assertIsNone(mgr.api, "the dead session was kept for the next call")

    def test_rename_delete_create_and_assign_say_sign_in_again(self):
        calls = {
            "rename_cloud": lambda m: m.rename_cloud("projects", "p-1", "Quay North"),
            "delete_cloud": lambda m: m.delete_cloud("projects", "p-1"),
            "create_site": lambda m: m.create_site("Quay"),
            "assign_to_site": lambda m: m.assign_to_site("s-1", "p-1"),
        }
        for name, call in calls.items():
            with self.subTest(name):
                mgr = self._mgr()
                self._assert_expired(mgr, call(mgr))

    def test_a_failed_download_says_sign_in_again_and_makes_no_folder(self):
        mgr = self._mgr()
        r = mgr.download_project("p-1", "Quay")
        self._assert_expired(mgr, r)
        self.assertEqual([], sorted(p.name for p in self.root.iterdir()))


class _FakeApi:
    user_email = "pat@example.invalid"

    def download_project(self, pid, progress_cb=None):
        return {"esx": b"PK-invented", "name": "Pier Nine Survey"}


class _Mgr(cm.CloudManager):
    def __init__(self, root):
        self.api = _FakeApi()
        self.config = {"output_dir": str(root)}

    def _ensure(self):
        return True


#: The real `downloadThenMove` for a project in no cloud site, then the real
#: `confirmMoveToSite` with a destination picked; reports the move it sends.
UNFILED = r"""
const DL = JSON.parse(%s);
s.__set('data', { currentUser: 'pat@example.invalid', matched: [], cloudOnly: [],
                  localOnly: [], orphans: { cloudOnly: [] } });
s._setRowBusy = () => {};
s.runWithProgress = async (spec, fn) => fn('op-1');
s._openMoveToSitePicker = async () => {};
let moveArgs = null;
s.pyApi = async (m, ...args) => {
  if (m === 'download_project') return DL;
  if (m === 'move_local_to_site') { moveArgs = args; return { ok: true }; }
  return { ok: true };
};
await s.downloadThenMove('p-9', 'Pier Nine Survey');
const t = s.__get('_moveToSiteTargets');
t[0].destValue = '__new__'; t[0].destNewName = 'Pier Nine';
await s.confirmMoveToSite();
for (let i = 0; i < 5; i++) await settle();
out(moveArgs);
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class AnUnfiledDownloadLeavesNoFolderTests(_Case):

    def test_the_project_named_folder_is_gone_after_the_move(self):
        mgr = _Mgr(self.root)
        (self.root / "Pier Nine").mkdir()
        dl = mgr.download_project("p-9", "Pier Nine Survey")
        self.assertTrue(dl.get("ok"), dl)
        args = cloud_vm.run(UNFILED % json.dumps(json.dumps(dl)))
        self.assertTrue(args, "the page never asked for the move")
        path, folder, tidy = (list(args) + [None, None, None])[:3]
        mv = mgr.move_local_to_site(path, folder, tidy_source=bool(tidy))
        self.assertTrue(mv.get("ok"), mv)
        self.assertTrue((self.root / "Pier Nine" / "Pier Nine Survey.esx").is_file())
        self.assertFalse((self.root / "Pier Nine Survey").exists(),
                         "the empty project-named folder was left behind")
        self.assertEqual(["Pier Nine"],
                         [f["name"] for f in cm.get_local_folders(str(self.root))])


class TidyingNeverRemovesAFileTests(_Case):

    def test_a_folder_holding_any_file_stays(self):
        mgr = _Mgr(self.root)
        dl = mgr.download_project("p-9", "Pier Nine Survey")
        keep = self.root / "Pier Nine Survey" / "reports" / "notes.txt"
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_text("invented", encoding="utf-8")
        mv = mgr.move_local_to_site(dl["path"], "Pier Nine", tidy_source=True)
        self.assertTrue(mv.get("ok"), mv)
        self.assertTrue(keep.is_file())
        self.assertNotIn("removedFolder", mv)

    def test_without_the_request_nothing_is_tidied(self):
        mgr = _Mgr(self.root)
        dl = mgr.download_project("p-9", "Pier Nine Survey")
        mgr.move_local_to_site(dl["path"], "Pier Nine")
        self.assertTrue((self.root / "Pier Nine Survey").is_dir())


if __name__ == "__main__":
    unittest.main()
