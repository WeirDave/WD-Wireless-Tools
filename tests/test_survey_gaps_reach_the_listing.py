"""A local file's missing survey data has to reach the page, not just the scan.

v2.236.0 counted `surveyGaps` for every local `.esx` and every row-level
control read it, and the Projects list showed none: `build_projects_data` and
`build_sites_data` rebuild each local file field by field, and the count was
not one of the fields copied. The tests of the controls handed them a row that
already carried the count, so they passed whatever the server sent.

This runs the real listing builders over a real folder: one `.esx` whose
surveys name sample files it does not contain, one that carries them, and one
with no surveys at all. The count has to arrive on each local file, wherever
the builder puts it. Every name is invented.
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import cloud_manager as cm

ME = "pat@example.invalid"
SURVEY = {"id": "s1", "floorPlanId": "fp1",
          "wifiTracks": [{"binaryFileId": "t1"}, {"binaryFileId": "t2"}],
          "spectrumSessions": [{"chunks": ["c1"]}]}


def _esx(project_id, with_samples, with_surveys=True):
    members = {"project.json": json.dumps({"project": {
        "id": project_id, "name": "Invented " + project_id,
        "history": {"createdBy": ME, "modifiedAt": "2026-01-02T03:04:05Z"}}})}
    if with_surveys:
        members["survey-s1.json"] = json.dumps({"surveys": [SURVEY]})
        if with_samples:
            for name in ("track-t1.bin", "track-t2.bin", "spectrum-c1.bin"):
                members[name] = b"x"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in members.items():
            z.writestr(name, body)
    return buf.getvalue()


class _Api:
    user_email = ME

    def get_sites(self):
        return [{"siteId": "site-m", "name": "Invented Main Campus"}]

    def get_dataset_listing(self):
        return [{"id": pid, "siteName": "Invented Main Campus", "siteId": "site-m",
                 "type": "SIMULATED_PROJECT",
                 "datasetUsers": [{"username": ME, "role": "OWNER"}]}
                for pid in ("proj-hollow", "proj-whole", "proj-plain")]

    def get_projects(self):
        return [{"id": pid, "name": "Invented " + pid,
                 "history": {"createdBy": ME, "modifiedAt": "2026-01-02T03:04:05Z"}}
                for pid in ("proj-hollow", "proj-whole", "proj-plain")]


def _local_files(node, found=None):
    """Every local `.esx` dict, wherever a builder nested it."""
    found = [] if found is None else found
    if isinstance(node, dict):
        if str(node.get("path", "")).lower().endswith(".esx"):
            found.append(node)
        for v in node.values():
            _local_files(v, found)
    elif isinstance(node, list):
        for v in node:
            _local_files(v, found)
    return found


class _Case(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wd-gaps-listing-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        folder = self.root / "Invented Main Campus"
        folder.mkdir()
        (folder / "Invented proj-hollow.esx").write_bytes(_esx("proj-hollow", False))
        (folder / "Invented proj-whole.esx").write_bytes(_esx("proj-whole", True))
        (folder / "Invented proj-plain.esx").write_bytes(
            _esx("proj-plain", False, with_surveys=False))
        cm.save_manual_matches([])
        cm.save_not_matches([])
        self.addCleanup(cm.save_manual_matches, [])
        cm._ESX_META_CACHE.clear()

    def gaps(self, payload):
        got = {Path(f["path"]).stem: f.get("surveyGaps")
               for f in _local_files(payload)}
        self.assertEqual({"Invented proj-hollow", "Invented proj-whole",
                          "Invented proj-plain"}, set(got), got)
        return got


class TheProjectsListCarriesTheCountTests(_Case):

    def test_a_short_file_arrives_with_its_missing_count(self):
        got = self.gaps(cm.build_projects_data(_Api(), str(self.root)))
        self.assertEqual(3, got["Invented proj-hollow"])

    def test_a_whole_file_and_a_file_with_no_surveys_arrive_with_none(self):
        got = self.gaps(cm.build_projects_data(_Api(), str(self.root)))
        self.assertEqual(0, got["Invented proj-whole"])
        self.assertEqual(0, got["Invented proj-plain"])


class TheSitesTreeCarriesTheCountTests(_Case):

    def test_a_short_file_arrives_with_its_missing_count(self):
        got = self.gaps(cm.build_sites_data(_Api(), str(self.root)))
        self.assertEqual(3, got["Invented proj-hollow"])
        self.assertEqual(0, got["Invented proj-whole"])


if __name__ == "__main__":
    unittest.main()
