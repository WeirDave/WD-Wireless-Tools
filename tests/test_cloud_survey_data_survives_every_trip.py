"""A project's survey and radio data survives every trip through Cloud Manager.

Every earlier test of this had one step in it: a download that was checked, an
upload that was checked, a guard that was checked on its own. The failure this
exists for was not in a step. Cloud Manager downloaded a project, kept its
survey records and dropped the signal, noise and radio-mapping files behind
them - and nothing said so, because each step was correct about what it was
handed. The loss only shows when the *whole chain* is run and the bytes at the
end are compared with the bytes at the start.

So this runs the real code end to end against a stand-in for Ekahau's HTTP
surface only (`_Cloud`, behind `requests`' own method names): the real
`EkahauAPI` builds a download from the batch and the binary files, the real
upload sends the archive in three requests, the real manager lists, renames,
files, replaces, pulls and writes back. The stand-in does what Ekahau does -
it ingests an uploaded archive into a batch plus separately fetched binaries,
and answers 404 for a binary it was never given - which is what makes a hollow
upload visible as a hollow download.

Each case ends by comparing, member for member, the survey and radio files in
the archive on disk with the ones the project started with. `MEMBERS` is the
fixture's whole measured-data set; a trip that loses one fails by name.

Every project, site, address and person here is invented.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools import cloud_manager as cm
from tools import esx_survey_data as sd
from tools import sync_state

ME = "pat@example.invalid"
SITE = "Invented Main Campus"
SITE_ID = "site-m"

#: The measured data in the fixture: two Wi-Fi tracks and a spectrum session
#: on one survey, a second survey, a Cisco radio-mapping file on the floor
#: plan, and a deleted survey that owns nothing and must not be expected.
SURVEYS = [
    {"id": "sv1", "floorPlanId": "fp1", "status": "CREATED",
     "wifiTracks": [{"binaryFileId": "bt1"}, {"binaryFileId": "bt2"}],
     "spectrumSessions": [{"chunks": ["bc1", "bc2"]}]},
    {"id": "sv2", "floorPlanId": "fp1", "status": "CREATED",
     "wifiTracks": [{"binaryFileId": "bt3"}], "spectrumSessions": []},
    {"id": "sv3", "floorPlanId": "fp1", "status": "DELETED",
     "wifiTracks": [{"binaryFileId": "bt-gone"}], "spectrumSessions": []},
]
FLOOR_PLANS = [{"id": "fp1", "name": "Floor 1",
                "ciscoWcsRadioMappingDataId": "bw1"}]

#: member name -> bytes. Distinct, non-trivial bytes per member, so a swap or
#: a truncation shows as a difference and not just as a presence.
BINARIES = {
    "track-bt1.bin": b"\x01signal-one" * 40,
    "track-bt2.bin": b"\x02signal-two" * 50,
    "track-bt3.bin": b"\x03signal-three" * 30,
    "spectrum-bc1.bin": b"\x04noise-one" * 60,
    "spectrum-bc2.bin": b"\x05noise-two" * 20,
    "wcs-bw1.csv": b"ap,radio,x,y\nAP1,r1,1,2\n",
}
MEMBERS = sorted(BINARIES) + ["survey-sv1.json", "survey-sv2.json"]
IMAGE = b"\x89PNG-invented-floor-plan" * 25


def _project_json(project_id, name, modified):
    return {"project": {"id": project_id, "name": name,
                        "history": {"createdBy": ME, "modifiedAt": modified}}}


def make_esx(project_id, name, modified="2026-06-01T00:00:00Z", *,
             samples=True, layout="per-survey", surveys=SURVEYS):
    """A synthetic Ekahau archive. `samples=False` is the file the old
    download wrote: records, no files behind them. `layout="merged"` is the
    single `surveys.json` that download used to produce."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("version", "2.0")
        z.writestr("project.json", json.dumps(_project_json(project_id, name, modified)))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": FLOOR_PLANS}))
        z.writestr("images.json", json.dumps({"images": [{"id": "img1"}]}))
        z.writestr("accessPoints.json", json.dumps({"accessPoints": [
            {"id": "ap1", "name": "Invented-AP-001"}]}))
        z.writestr("image-img1", IMAGE)
        if layout == "per-survey":
            for s in surveys:
                z.writestr(sd.survey_member(s["id"]), json.dumps({"surveys": [s]}))
        else:
            z.writestr("surveys.json", json.dumps({"surveys": surveys}))
        if samples:
            for member, body in BINARIES.items():
                z.writestr(member, body)
    return buf.getvalue()


def read_project_id(path):
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("project.json"))["project"]["id"]


def read_members(blob_or_path):
    src = io.BytesIO(blob_or_path) if isinstance(blob_or_path, bytes) else blob_or_path
    with zipfile.ZipFile(src) as z:
        return {n: z.read(n) for n in z.namelist()}


# ---------------------------------------------------------------------------
# The stand-in for Ekahau.
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status=200, body=b"", payload=None):
        self.status_code = status
        self.reason = {200: "OK", 404: "Not Found", 403: "Forbidden"}.get(status, "")
        self.ok = status < 400
        self.content = body
        self._payload = payload
        self.text = body.decode("utf-8", "replace") if isinstance(body, bytes) and payload is None else (
            json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            import requests
            raise requests.HTTPError("%s %s" % (self.status_code, self.reason),
                                     response=self)


class _Cloud:
    """The account: projects, their batch records, and the binary files."""

    def __init__(self):
        self.projects = {}      # id -> {"batch", "binaries", "images", "site"}
        self.uploads = {}       # fileUploadId -> bytes
        self.deleted = []
        self.n = 0
        #: ids of binaries Ekahau answers 404 for, whatever was uploaded.
        self.refuse_binaries = set()

    def _next(self, prefix):
        self.n += 1
        return "%s-%d" % (prefix, self.n)

    def ingest(self, blob):
        """What Ekahau does with an uploaded archive: records into the batch,
        files into the binary store, keyed by id. A file the archive does not
        contain is simply not stored."""
        members = read_members(blob)
        pid = self._next("cloud")
        batch, surveys, binaries, images = {}, [], {}, {}
        for name, body in members.items():
            if name == "version":
                continue
            if name.startswith("survey-") and name.endswith(".json"):
                surveys += json.loads(body)["surveys"]
            elif name == "surveys.json":
                seen = {s["id"] for s in surveys}
                surveys += [s for s in json.loads(body)["surveys"] if s["id"] not in seen]
            elif name.startswith(("track-", "spectrum-", "wcs-")):
                binaries[name.split("-", 1)[1].rsplit(".", 1)[0]] = body
            elif name.startswith("image-"):
                images[name[len("image-"):]] = body
            elif name.endswith(".json"):
                key = name[:-len(".json")]
                batch[key] = json.loads(body)[key]
        batch["surveys"] = surveys
        batch["project"]["id"] = pid
        self.projects[pid] = {"batch": batch, "binaries": binaries,
                              "images": images, "site": None}
        return pid

    def listing(self):
        out = []
        for pid, p in self.projects.items():
            proj = p["batch"]["project"]
            out.append({"id": pid, "name": proj["name"], "title": proj["name"],
                        "modifiedAt": proj["history"]["modifiedAt"],
                        "history": proj["history"]})
        return out


class _Http:
    def __init__(self, cloud):
        self.cloud = cloud

    @staticmethod
    def _path(url):
        return url.replace(cm.EKAHAU_URL, "")

    def get(self, url, allow_redirects=True, timeout=None, **_):
        path = self._path(url)
        c = self.cloud
        if path == "/site-management-api/v1/sites":
            return _Resp(payload=[{"siteId": SITE_ID, "name": SITE}])
        if path == "/site-management-api/v1/datasetListing":
            return _Resp(payload=[
                {"id": pid, "siteName": SITE if p["site"] else "",
                 "siteId": p["site"] or "", "type": "SIMULATED_PROJECT",
                 "datasetUsers": [{"username": ME, "role": "OWNER"}]}
                for pid, p in c.projects.items()])
        if path.startswith("/site-management-api/v1/datasets/"):
            return _Resp(payload={"type": "SIMULATED_PROJECT"})
        if path == cm.API_BASE:
            return _Resp(payload=c.listing())
        rest = path[len(cm.API_BASE) + 1:].split("?")[0].split("/")
        pid = rest[0]
        p = c.projects.get(pid)
        if p is None:
            return _Resp(404)
        if len(rest) == 1:
            return _Resp(payload=p["batch"]["project"])
        if rest[1:] == ["batch"]:
            return _Resp(payload=json.loads(json.dumps(p["batch"])))
        if rest[1] == "imageFiles" and rest[2] in p["images"]:
            return _Resp(body=p["images"][rest[2]])
        if rest[1] == "binaryFiles" and rest[2] in p["binaries"] \
                and rest[2] not in c.refuse_binaries:
            return _Resp(body=p["binaries"][rest[2]])
        return _Resp(404)

    def put(self, url, data=None, headers=None, timeout=None, **_):
        self.cloud.uploads[url] = bytes(data)
        return _Resp()

    def request(self, method, url, json=None, headers=None, timeout=None, **_):
        path = self._path(url)
        c = self.cloud
        if path == "/esxfileapi/v1/projects/upload/initiate":
            uid = c._next("u")
            return _Resp(payload={"url": "https://s3.invalid/" + uid,
                                  "fileUploadId": uid})
        if path.startswith("/esxfileapi/v1/projects/upload/commit"):
            uid = path.split("fileUploadId=")[1]
            c.ingest(c.uploads["https://s3.invalid/" + uid])
            return _Resp(payload={"ok": True})
        if path == cm.API_BASE + "/batch-delete":
            for pid in json["projects"]:
                c.projects.pop(pid, None)
                c.deleted.append(pid)
            return _Resp(payload={"ok": True})
        if path.endswith("/batch/update"):
            pid = path[len(cm.API_BASE) + 1:].split("/")[0]
            c.projects[pid]["batch"]["project"]["name"] = json["project"]["name"]
            return _Resp(payload={"ok": True})
        if "/datasets" in path and path.startswith("/site-management-api/v1/sites/"):
            sid = path.split("/")[4]
            for item in json:
                c.projects[item["datasetId"]]["site"] = sid
            return _Resp(payload={"ok": True})
        return _Resp(404)


class _Ekahau(cm.EkahauAPI):
    """The real API class over the stand-in transport."""

    def __init__(self, cloud):
        self.http = _Http(cloud)
        self.csrf_token = "t"
        self.user_email = ME
        self.failure = ""
        self.refused = False


class _Manager(cm.CloudManager):
    def __init__(self, api, out_dir):
        self.api = api
        self.config = {"output_dir": str(out_dir)}

    def _ensure(self):
        return True


class _Trip(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wd-survey-trip-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.site_dir = self.root / SITE
        self.site_dir.mkdir()
        self.cloud = _Cloud()
        self.api = _Ekahau(self.cloud)
        self.mgr = _Manager(self.api, self.root)
        sync_state.prune([])
        self.addCleanup(sync_state.prune, [])
        cm.save_manual_matches([])
        cm.save_not_matches([])
        self.addCleanup(cm.save_manual_matches, [])
        cm._ESX_META_CACHE.clear()
        patcher = mock.patch.object(time, "sleep", lambda *_: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def put_local(self, stem, blob):
        p = self.site_dir / (stem + ".esx")
        p.write_bytes(blob)
        return p

    def seed_cloud(self, blob, site=True):
        pid = self.cloud.ingest(blob)
        if site:
            self.cloud.projects[pid]["site"] = SITE_ID
        return pid

    def assertCarriesEverything(self, source, what):
        """Every measured-data member of the starting project is in `source`
        (a path or bytes), byte for byte, and nothing is reported missing."""
        got = read_members(source)
        for name in MEMBERS:
            self.assertIn(name, got, "%s: %s was lost" % (what, name))
        for name, body in BINARIES.items():
            self.assertEqual(body, got[name], "%s: %s came back different" % (what, name))
        self.assertEqual([], sd.missing_members(
            zipfile.ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source)),
            "%s: the archive's own records name files it does not hold" % what)
        self.assertNotIn("track-bt-gone.bin", got, "%s: a deleted survey's file appeared" % what)

    def cloud_binaries(self, pid):
        return set(self.cloud.projects[pid]["binaries"])


class TheFixtureIsWhatTheTestsClaim(_Trip):
    """The stand-in has to be able to *fail*, or every case below is a case
    for nothing."""

    def test_the_whole_fixture_passes_its_own_check(self):
        blob = make_esx("local-1", "Invented Whole")
        self.assertCarriesEverything(blob, "fixture")

    def test_the_old_hollow_download_fails_the_check(self):
        hollow = make_esx("local-1", "Invented Hollow", samples=False, layout="merged")
        with self.assertRaises(AssertionError):
            self.assertCarriesEverything(hollow, "hollow")
        #: Six sample files, plus the two per-survey records the old layout
        #: folded into one `surveys.json`.
        self.assertEqual(len(BINARIES) + 2, len(sd.missing_in_bytes(hollow)))

    def test_the_stand_in_cloud_serves_only_what_it_was_given(self):
        pid = self.seed_cloud(make_esx("local-1", "x", samples=False))
        self.assertEqual(set(), self.cloud_binaries(pid))
        self.assertEqual(404, self.api.http.get(
            cm.EKAHAU_URL + cm.API_BASE + "/%s/binaryFiles/bt1" % pid).status_code)


class AFirstUploadComesBackWhole(_Trip):

    def test_upload_then_write_back_keeps_every_survey_file(self):
        local = self.put_local("Invented Whole", make_esx("local-1", "Invented Whole"))
        out = self.mgr.upload_project(str(local), SITE_ID)
        self.assertTrue(out.get("syncedBack"), out)
        pid = out["datasetId"]
        self.assertEqual({"bt1", "bt2", "bt3", "bc1", "bc2", "bw1"},
                         self.cloud_binaries(pid), "the cloud was not given every file")
        self.assertCarriesEverything(local, "the local file after the first upload")

    def test_the_cloud_copy_downloads_whole_into_a_new_folder(self):
        local = self.put_local("Invented Whole", make_esx("local-1", "Invented Whole"))
        pid = self.mgr.upload_project(str(local), SITE_ID)["datasetId"]
        out = self.mgr.download_project(pid, "Invented Second Campus")
        self.assertNotIn("error", out, out)
        landed = list((self.root / "Invented Second Campus").glob("*.esx"))
        self.assertEqual(1, len(landed), out)
        self.assertCarriesEverything(landed[0], "a fresh download")


class AReplaceKeepsTheSurveyData(_Trip):

    def test_replacing_the_cloud_copy_sends_and_returns_every_file(self):
        old = self.seed_cloud(make_esx("seed", "Invented Whole", "2026-01-01T00:00:00Z"))
        self.cloud.projects[old]["batch"]["project"]["name"] = "Invented Whole"
        local = self.put_local("Invented Whole", make_esx(
            old, "Invented Whole", "2026-06-01T00:00:00Z"))
        out = self.mgr.replace_cloud_project(str(local), old)
        self.assertTrue(out.get("ok") or out.get("replaced"), out)
        self.assertIn(old, self.cloud.deleted, "the old cloud project was not removed")
        new = [p for p in self.cloud.projects][0]
        self.assertNotEqual(old, new)
        self.assertEqual({"bt1", "bt2", "bt3", "bc1", "bc2", "bw1"}, self.cloud_binaries(new))
        self.assertCarriesEverything(local, "the local file after a replace")

    def test_several_generations_never_shrink_the_data(self):
        local = self.put_local("Invented Whole", make_esx("local-1", "Invented Whole"))
        pid = self.mgr.upload_project(str(local), SITE_ID)["datasetId"]
        for generation in range(3):
            # A newer local save, then a replace, then a pull of the result.
            blob = read_members(local)
            edited = make_esx(pid, "Invented Whole", "2026-0%d-01T00:00:00Z" % (7 + generation))
            local.write_bytes(edited)
            os.utime(local, None)
            out = self.mgr.replace_cloud_project(str(local), pid)
            self.assertFalse(out.get("error"), (generation, out))
            pid = [p for p in self.cloud.projects][0]
            self.assertCarriesEverything(local, "generation %d" % generation)
            self.assertEqual(len(self.cloud.projects), 1,
                             "a replace left a second project in the cloud")


class AHollowCopyIsNeverTheOnlyCopy(_Trip):

    def test_a_short_local_file_is_not_sent_over_a_whole_cloud_project(self):
        whole = self.seed_cloud(make_esx("seed", "Invented Whole", "2026-01-01T00:00:00Z"))
        hollow = self.put_local("Invented Whole", make_esx(
            whole, "Invented Whole", "2026-06-01T00:00:00Z", samples=False, layout="merged"))
        before = dict(self.cloud.projects[whole]["binaries"])
        out = self.mgr.replace_cloud_project(str(hollow), whole)
        self.assertEqual("missing_survey_data", out.get("error"), out)
        self.assertIn(whole, self.cloud.projects, "the whole cloud project was deleted")
        self.assertEqual(before, self.cloud.projects[whole]["binaries"])
        self.assertEqual([], self.cloud.deleted)
        self.assertEqual(1, len(self.cloud.projects), "something was uploaded anyway")

    def test_even_when_forced_the_whole_project_stays_if_the_upload_reads_back_hollow(self):
        whole = self.seed_cloud(make_esx("seed", "Invented Whole", "2026-01-01T00:00:00Z"))
        hollow = self.put_local("Invented Whole", make_esx(
            whole, "Invented Whole", "2026-06-01T00:00:00Z", samples=False, layout="merged"))
        out = self.mgr.replace_cloud_project(
            str(hollow), whole, allow_missing_survey_data=True)
        self.assertTrue(out.get("error"), "a hollow upload was reported as a success: %r" % out)
        self.assertIn(whole, self.cloud.projects, "the whole cloud project was deleted")
        self.assertEqual({"bt1", "bt2", "bt3", "bc1", "bc2", "bw1"},
                         self.cloud_binaries(whole))
        self.assertEqual([], self.cloud.deleted)

    def test_a_cloud_copy_that_cannot_serve_its_files_is_not_written_over_a_whole_local_file(self):
        local = self.put_local("Invented Whole", make_esx(
            "local-1", "Invented Whole", "2026-01-01T00:00:00Z"))
        original = local.read_bytes()
        pid = self.seed_cloud(make_esx("seed", "Invented Whole", "2026-06-01T00:00:00Z"))
        self.cloud.refuse_binaries = {"bt2"}
        out = self.mgr.verify_replace_local(pid, str(local))
        self.assertTrue(out.get("error"), out)
        self.assertEqual(original, local.read_bytes(),
                         "a download that came out short replaced a whole file")
        self.assertEqual([], [p.name for p in self.site_dir.iterdir()
                              if p.suffix != ".esx"], "a temporary file was left behind")

    def test_a_cloud_project_that_holds_no_files_is_not_written_over_a_whole_local_file(self):
        local = self.put_local("Invented Whole", make_esx(
            "local-1", "Invented Whole", "2026-01-01T00:00:00Z"))
        original = local.read_bytes()
        pid = self.seed_cloud(make_esx("seed", "Invented Whole", "2026-06-01T00:00:00Z",
                                       samples=False))
        out = self.mgr.verify_replace_local(pid, str(local))
        self.assertTrue(out.get("error"), out)
        self.assertEqual(original, local.read_bytes())


class APullRepairsAShortFile(_Trip):

    def test_a_whole_cloud_copy_pulled_over_a_short_local_file_restores_everything(self):
        pid = self.seed_cloud(make_esx("seed", "Invented Whole", "2026-06-01T00:00:00Z"))
        local = self.put_local("Invented Whole", make_esx(
            pid, "Invented Whole", "2026-01-01T00:00:00Z", samples=False, layout="merged"))
        self.assertTrue(sd.missing_in_file(local), "the fixture is not short")
        out = self.mgr.verify_replace_local(pid, str(local))
        self.assertFalse(out.get("error"), out)
        self.assertCarriesEverything(local, "a short file after a pull")


class TheListingSaysWhichFileIsShort(_Trip):

    @staticmethod
    def _locals(node, found=None):
        found = [] if found is None else found
        if isinstance(node, dict):
            if str(node.get("path", "")).lower().endswith(".esx"):
                found.append(node)
            for v in node.values():
                TheListingSaysWhichFileIsShort._locals(v, found)
        elif isinstance(node, list):
            for v in node:
                TheListingSaysWhichFileIsShort._locals(v, found)
        return found

    def test_a_round_tripped_file_is_not_flagged_and_a_stripped_one_is(self):
        whole = self.put_local("Invented Whole", make_esx("local-1", "Invented Whole"))
        pid = self.mgr.upload_project(str(whole), SITE_ID)["datasetId"]
        hollow = self.put_local("Invented Hollow", make_esx(
            "local-2", "Invented Hollow", samples=False, layout="merged"))
        cm._ESX_META_CACHE.clear()
        data = cm.build_projects_data(self.api, str(self.root))
        gaps = {Path(f["path"]).stem: f.get("surveyGaps") for f in self._locals(data)}
        self.assertEqual(0, gaps.get("Invented Whole"), gaps)
        self.assertEqual(len(BINARIES) + 2, gaps.get("Invented Hollow"), gaps)

    def test_the_round_tripped_file_is_paired_with_its_cloud_project_by_id(self):
        whole = self.put_local("Invented Whole", make_esx("local-1", "Invented Whole"))
        pid = self.mgr.upload_project(str(whole), SITE_ID)["datasetId"]
        cm._ESX_META_CACHE.clear()
        data = cm.build_projects_data(self.api, str(self.root))
        rows = [m for m in data["matched"]
                if m["cloud"]["id"] == pid]
        self.assertEqual(1, len(rows), "the uploaded project is not paired with its file")
        self.assertEqual("Invented Whole", Path(rows[0]["local"]["path"]).stem)
        self.assertEqual(pid, read_project_id(rows[0]["local"]["path"]),
                         "the file does not carry the cloud project's own id")
        self.assertEqual([], data["cloudOnly"])
        self.assertEqual([], data["localOnly"])


if __name__ == "__main__":
    unittest.main()
