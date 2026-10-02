"""Two local files carrying one Ekahau project id pair with the right cloud copy.

Saving a project under a new name in Ekahau keeps its project id, so a folder
can hold "Predictive Design.esx" and "Predictive Design - with DWG.esx" that
are both, by id, the same project. The id pass took the first one
alphabetically. With the DWG file saved to the cloud, the cloud copy paired
with the *older* file: the file being worked on was listed local-only, the
older one disappeared behind the cloud's name, "Check what differs" compared
the cloud copy against the wrong file and reported real changes in seventeen
parts, and "Download over local" would have overwritten the older file with
the newer design.

The listing is driven through the real disk scan. Every name is invented.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import cloud_manager as cm

CLOUD_ISO = "2026-10-02T01:00:00Z"


class TheRightFileIsPairedTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wd-sameid-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        cm._ESX_META_CACHE.clear()
        self.addCleanup(cm._ESX_META_CACHE.clear)
        folder = self.root / "SITE1 Riverside"
        folder.mkdir()
        self._esx(folder / "Predictive Design.esx", "2026-09-01T00:00:00Z")
        self._esx(folder / "Predictive Design - with DWG.esx",
                  "2026-10-02T00:00:00Z")

    @staticmethod
    def _esx(path, iso):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("project.json", json.dumps({"project": {
                "id": "pid-1", "name": "Predictive Design",
                "history": {"modifiedAt": iso}}}))

    def _list(self, cloud_name):
        local = [{"path": f["path"], "name": f["name"], "code": "",
                  "isDir": False, "folder": f["folder"], "size": f["size"],
                  "mtime": f["mtime"], "projectId": f["projectId"]}
                 for f in cm.get_local_esx_files(str(self.root))]
        self.assertEqual(2, len(local), "the probe needs both files on disk")
        cloud = [{"id": "pid-1", "name": cloud_name, "code": "",
                  "mtime": cm._parse_cloud_mtime(
                      {"history": {"modifiedAt": CLOUD_ISO}})}]
        r = cm.build_matches(cloud, local, set(), {})
        return ([m["local"]["name"] for m in r["matched"]],
                [l["name"] for l in r["localOnly"]])

    def test_the_file_named_like_the_cloud_project_wins(self):
        """His case: alphabetically the other file came first."""
        self.assertEqual((["Predictive Design - with DWG"],
                          ["Predictive Design"]),
                         self._list("Predictive Design - with DWG"))

    def test_and_the_other_way_round(self):
        self.assertEqual((["Predictive Design"],
                          ["Predictive Design - with DWG"]),
                         self._list("Predictive Design"))

    def test_with_no_name_to_go_on_the_nearest_date_wins(self):
        """A cloud project renamed since: the copy closest to it in time is
        the likelier one, and the other file still gets its own row."""
        self.assertEqual((["Predictive Design - with DWG"],
                          ["Predictive Design"]),
                         self._list("Riverside Final"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
