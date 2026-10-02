"""A cloud project filed in no site, paired with a local file in a site
folder, keeps its newer/older state in the Sites view.

`build_sites_data` cross-matches cloud projects that are in no site against
the local files still unpaired in each site folder. The pair it moved into the
site's `children.matched` was rebuilt from three keys - `matchType`, `score`,
`namesDiffer` - so `staleness`, `divergence`, `comparison` and
`differenceKind` were dropped. The row showed no newer/older state and Sync
everything filed the pair as in sync. The direct matcher has always had them;
this asks the Sites view the same question and compares.

Every name invented; Ekahau is a stub.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import cloud_manager as cm
from tools import sync_state as ss


def _esx(path: Path, pid: str, name: str, modified: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps({"project": {
            "id": pid, "name": name, "history": {"modifiedAt": modified}}}))


class _Api:
    def get_sites(self):
        return [{"id": "s1", "name": "Maple Court"}]

    def get_dataset_listing(self):
        return []  # the cloud project is filed in no site

    def get_projects(self):
        return [{"id": "p1", "name": "Maple Court Tower B",
                 "history": {"modifiedAt": "2026-09-30T00:00:00Z"}}]


class TheCrossMatchedPairKeepsItsStateTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        real = ss.STATE_FILE
        ss.STATE_FILE = self.root / "sync_state.json"
        self.addCleanup(lambda: setattr(ss, "STATE_FILE", real))
        _esx(self.root / "proj" / "Maple Court" / "Maple Court Tower B.esx",
             "local-x", "Maple Court Tower B", "2026-08-01T00:00:00Z")

    def _site_pair(self):
        d = cm.build_sites_data(_Api(), str(self.root / "proj"))
        holders = ([(p.get("cloud") or p.get("local")) for p in d["matched"]]
                   + list(d["localOnly"]))
        pairs = [m for h in holders if h and h.get("children")
                 for m in h["children"]["matched"]]
        self.assertEqual(1, len(pairs), d)
        return pairs[0]

    def test_the_cloud_copy_reads_as_newer(self):
        pair = self._site_pair()
        self.assertTrue(pair["cloud"].get("unassigned"))
        self.assertEqual("cloud_newer", pair.get("staleness"))

    def test_it_carries_what_the_direct_matcher_says(self):
        pair = self._site_pair()
        direct = cm.build_matches([dict(pair["cloud"])], [dict(pair["local"])])
        expected = direct["matched"][0]
        for key in ("staleness", "divergence", "comparison", "differenceKind",
                    "matchType", "namesDiffer"):
            with self.subTest(key=key):
                self.assertIn(key, pair)
                self.assertEqual(expected[key], pair[key])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
