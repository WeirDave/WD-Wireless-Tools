"""A survey's samples are separate files, and a download has to bring them.

"The survey files on the local drive do not contain signal strength and noise
samples ... they are separate binary files inside the zip and are missing."

Right. A survey record lists its Wi-Fi tracks (`binaryFileId`) and spectrum
sessions (`chunks`) and holds none of the samples: those are the zip's
`track-<id>.bin` and `spectrum-<id>.bin`. Cloud Manager built a download from
the batch response and the floor-plan images and stopped, and wrote the
surveys as one `surveys.json` that Ekahau never writes. Every project it
downloaded, pulled, or synced back after an upload kept its survey records and
lost everything they pointed at - and nothing said so, because the row's date
matched the cloud's and a comparison of two copies built the same way found no
difference.

**These tests run the real code.** `download_project` is the real method,
reading from a fake Ekahau that serves distinct bytes per file and records
every URL asked for; the pull is the real `verify_replace_local`; the
comparison is the real `compare_esx`; the row is rendered by the real
`rowDetailHtml`. Nothing asserts that a source file contains a string.

Every project, id and name here is invented.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import esx_compare, esx_survey_data

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

ISO = "2026-08-01T08:00:00.000Z"
NAME = "SITE1 Survey Baseline"


def _served(file_id: str) -> bytes:
    """What the fake Ekahau returns for one file: different for every id, so a
    member filed under the wrong name cannot pass."""
    return b"BIN:" + file_id.encode("ascii") + b":" + bytes(range(64))


def _survey(sid, tracks=(), chunks=(), status=None):
    rec = {"id": sid, "name": "Walk " + sid, "floorPlanId": "fp1",
           "wifiTracks": [{"binaryFileId": t, "scannings": []} for t in tracks],
           "spectrumSessions": [{"chunks": list(chunks)}] if chunks else [],
           "routePoints": []}
    if status:
        rec["status"] = status
    return rec


def _batch(surveys=()):
    doc = {"project": {"id": "cloud-1", "name": NAME,
                       "history": {"modifiedAt": ISO}},
           "images": [{"id": "img1"}],
           "floorPlans": [{"id": "fp1", "name": "Level 1"}],
           "accessPoints": [{"id": "ap-1", "name": "AP-001"}]}
    if surveys:
        doc["surveys"] = list(surveys)
    return doc


class _Resp:
    status_code = 200

    def __init__(self, content=b"", doc=None):
        self.content = content
        self._doc = doc

    def raise_for_status(self):
        pass

    def json(self):
        return self._doc


class _FakeHttp:
    """The binary half of Ekahau: `.../imageFiles/<id>` and
    `.../binaryFiles/<id>`. `refuse` makes one id fail."""

    def __init__(self, refuse=()):
        self.urls = []
        self.refuse = set(refuse)

    def get(self, url, **kw):
        self.urls.append(url)
        file_id = url.split("?")[0].rsplit("/", 1)[-1]
        if file_id in self.refuse:
            raise RuntimeError("404 Not Found for " + file_id)
        return _Resp(content=_served(file_id))


def _api(batch, refuse=()):
    from tools import cloud_manager as cm

    class _Api(cm.EkahauAPI):
        def get(self, path):
            if path.endswith("/batch"):
                return _Resp(doc=batch)
            return _Resp(doc={"name": NAME, "history": {"modifiedAt": ISO}})

    api = _Api.__new__(_Api)
    api.http = _FakeHttp(refuse)
    api.csrf_token = "t"
    return api


def _open(data):
    return zipfile.ZipFile(io.BytesIO(data))


class TheDownloadCarriesTheSurveyDataTests(unittest.TestCase):

    def setUp(self):
        self.batch = _batch([
            _survey("s1", tracks=("t1", "t2"), chunks=("c1",)),
            _survey("s2", tracks=("t3",), status="DELETED"),
        ])
        self.api = _api(self.batch)
        self.out = self.api.download_project("cloud-1")
        self.assertIn("esx", self.out, self.out)
        self.z = _open(self.out["esx"])
        self.addCleanup(self.z.close)

    def test_every_track_and_spectrum_file_is_in_the_archive_unaltered(self):
        names = set(self.z.namelist())
        for member, file_id in (("track-t1.bin", "t1"),
                                ("track-t2.bin", "t2"),
                                ("spectrum-c1.bin", "c1")):
            self.assertIn(member, names)
            self.assertEqual(_served(file_id), self.z.read(member),
                             member + " holds the wrong bytes")

    def test_each_survey_is_its_own_file_and_there_is_no_merged_one(self):
        names = set(self.z.namelist())
        self.assertIn("survey-s1.json", names)
        self.assertNotIn("surveys.json", names,
                         "Ekahau never writes a merged surveys.json, and "
                         "Ekahau Pro does not read one")
        doc = json.loads(self.z.read("survey-s1.json"))
        self.assertEqual(["s1"], [s["id"] for s in doc["surveys"]])
        self.assertEqual(["t1", "t2"],
                         [t["binaryFileId"] for t in doc["surveys"][0]["wifiTracks"]])

    def test_a_deleted_survey_brings_nothing(self):
        names = set(self.z.namelist())
        self.assertNotIn("survey-s2.json", names)
        self.assertNotIn("track-t3.bin", names)
        self.assertFalse([u for u in self.api.http.urls if u.endswith("/t3?redirect=true")],
                         "a deleted survey's file was fetched")

    def test_the_binaries_come_from_binaryFiles_and_the_plans_from_imageFiles(self):
        urls = self.api.http.urls
        self.assertTrue(any("/cloud-1/binaryFiles/t1?redirect=true" in u for u in urls), urls)
        self.assertTrue(any("/cloud-1/binaryFiles/c1?redirect=true" in u for u in urls), urls)
        self.assertTrue(any("/cloud-1/imageFiles/img1?redirect=true" in u for u in urls), urls)

    def test_the_design_documents_are_still_written(self):
        names = set(self.z.namelist())
        for member in ("version", "project.json", "accessPoints.json",
                       "floorPlans.json", "image-img1"):
            self.assertIn(member, names)

    def test_the_archive_has_nothing_its_surveys_point_at_missing(self):
        self.assertEqual([], esx_survey_data.missing_in_bytes(self.out["esx"]))

    def test_progress_counts_every_file_fetched(self):
        seen = []
        _api(self.batch).download_project(
            "cloud-1", progress_cb=lambda **kw: seen.append(kw))
        text = " ".join(str(k.get("message", "")) for k in seen)
        self.assertIn("1 floor plan image and 3 survey files", text)
        self.assertIn("file 4 of 4", text)


class ADownloadThatCameOutShortIsAnErrorTests(unittest.TestCase):

    def test_a_track_that_cannot_be_fetched_fails_the_download(self):
        api = _api(_batch([_survey("s1", tracks=("t1", "t2"))]), refuse=("t2",))
        out = api.download_project("cloud-1")
        self.assertIn("error", out)
        self.assertNotIn("esx", out, "a hollow archive was handed back as a file")
        self.assertIn("track-t2.bin", out["error"])

    def test_a_spectrum_chunk_that_cannot_be_fetched_fails_the_download(self):
        api = _api(_batch([_survey("s1", chunks=("c1",))]), refuse=("c1",))
        out = api.download_project("cloud-1")
        self.assertIn("error", out)
        self.assertNotIn("esx", out)

    def test_a_project_with_no_surveys_is_not_held_to_a_survey_standard(self):
        out = _api(_batch()).download_project("cloud-1")
        self.assertIn("esx", out, out)
        names = _open(out["esx"]).namelist()
        self.assertFalse([n for n in names if n.startswith(
            esx_survey_data.SURVEY_MEMBER_PREFIXES)], names)


def _esx_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, body)
    return buf.getvalue()


def _project(surveys, layout):
    """An archive in either layout. `merged` is what Cloud Manager used to
    write; `split` is what Ekahau writes. Binaries are included only when
    asked for, through `layout` ending in `+bins`."""
    members = {"version": "2.0",
               "project.json": json.dumps({"project": {
                   "id": "cloud-1", "name": NAME,
                   "history": {"modifiedAt": ISO}}}),
               "accessPoints.json": json.dumps({"accessPoints": []})}
    if layout.startswith("merged"):
        members["surveys.json"] = json.dumps({"surveys": surveys})
    else:
        for s in surveys:
            members["survey-%s.json" % s["id"]] = json.dumps({"surveys": [s]})
    if layout.endswith("+bins"):
        for s in surveys:
            for t in s["wifiTracks"]:
                members["track-%s.bin" % t["binaryFileId"]] = _served(t["binaryFileId"])
            for sess in s["spectrumSessions"]:
                for c in sess["chunks"]:
                    members["spectrum-%s.bin" % c] = _served(c)
    return _esx_bytes(members)


SURVEYS = [_survey("s1", tracks=("t1", "t2"), chunks=("c1",))]


class TheGapIsReadFromTheArchiveItselfTests(unittest.TestCase):

    def test_a_merged_copy_without_binaries_reports_every_missing_file(self):
        gaps = esx_survey_data.missing_in_bytes(_project(SURVEYS, "merged"))
        self.assertEqual({"survey-s1.json", "track-t1.bin", "track-t2.bin",
                          "spectrum-c1.bin"}, set(gaps))

    def test_a_split_copy_without_binaries_reports_the_binaries(self):
        gaps = esx_survey_data.missing_in_bytes(_project(SURVEYS, "split"))
        self.assertEqual({"track-t1.bin", "track-t2.bin", "spectrum-c1.bin"},
                         set(gaps))

    def test_a_complete_copy_reports_nothing(self):
        self.assertEqual([], esx_survey_data.missing_in_bytes(
            _project(SURVEYS, "split+bins")))

    def test_a_project_that_only_predicts_reports_nothing(self):
        self.assertEqual([], esx_survey_data.missing_in_bytes(
            _esx_bytes({"version": "2.0", "accessPoints.json": "{}"})))

    def test_a_deleted_survey_is_not_a_gap(self):
        deleted = [_survey("s9", tracks=("t9",), status="DELETED")]
        self.assertEqual([], esx_survey_data.missing_in_bytes(
            _project(deleted, "split")))


class TwoShortCopiesAreNotIdenticalTests(unittest.TestCase):
    """The comparison's blind spot: it diffs what one side has and the other
    lacks, so two copies lacking the same thing differ in nothing."""

    def test_two_copies_both_missing_the_samples_are_not_called_identical(self):
        hollow = _project(SURVEYS, "split")
        res = esx_compare.compare_esx(hollow, hollow, local_file_stem=NAME)
        self.assertFalse(res["identical"])
        self.assertTrue(res["surveyDataIncomplete"])
        self.assertEqual({"local": 3, "cloud": 3}, res["surveyGaps"])
        self.assertIn("Survey data is incomplete", res["summary"])
        self.assertIn("signal and noise", res["summary"])
        self.assertNotIn("Identical", res["summary"])

    def test_two_complete_copies_are_still_identical(self):
        full = _project(SURVEYS, "split+bins")
        res = esx_compare.compare_esx(full, full, local_file_stem=NAME)
        self.assertTrue(res["identical"], res)
        self.assertFalse(res["surveyDataIncomplete"])
        self.assertEqual({"local": 0, "cloud": 0}, res["surveyGaps"])

    def test_a_hollow_local_against_a_complete_cloud_names_the_local_side(self):
        res = esx_compare.compare_esx(_project(SURVEYS, "merged"),
                                      _project(SURVEYS, "split+bins"),
                                      local_file_stem=NAME)
        self.assertFalse(res["identical"])
        self.assertTrue(res["designDiffers"])
        self.assertEqual(0, res["surveyGaps"]["cloud"])
        self.assertEqual(4, res["surveyGaps"]["local"])
        self.assertIn("the local file is missing 4 survey files", res["summary"])
        self.assertNotIn("the cloud copy is missing", res["summary"])
        members = {d["member"] for d in res["differences"]}
        self.assertIn("track-t1.bin", members)


class TheListingFlagsAShortFileTests(unittest.TestCase):

    def setUp(self):
        from tools import cloud_manager as cm
        self.cm = cm
        cm._ESX_META_CACHE.clear()
        self.addCleanup(cm._ESX_META_CACHE.clear)
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-survey-gaps-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        site = self.tmp / "SITE1 Riverside"
        site.mkdir()
        (site / "Complete.esx").write_bytes(_project(SURVEYS, "split+bins"))
        (site / "Short.esx").write_bytes(_project(SURVEYS, "merged"))

    def test_the_short_file_carries_its_gap_count_and_the_complete_one_none(self):
        found = {f["name"]: f for f in self.cm.get_local_esx_files(str(self.tmp))}
        self.assertEqual(0, found["Complete"]["surveyGaps"])
        self.assertEqual(4, found["Short"]["surveyGaps"])


class APullRepairsAShortFileTests(unittest.TestCase):
    """The end of it: a short local file, the real pull, the real download."""

    def setUp(self):
        from tools import cloud_manager as cm, sync_state
        self.cm = cm
        cm._ESX_META_CACHE.clear()
        self.addCleanup(cm._ESX_META_CACHE.clear)
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-survey-pull-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        real = sync_state.STATE_FILE
        sync_state.STATE_FILE = self.tmp / "sync_state.json"
        self.addCleanup(lambda: setattr(sync_state, "STATE_FILE", real))
        self.root = self.tmp / "projects"
        (self.root / "SITE1 Riverside").mkdir(parents=True)
        self.path = self.root / "SITE1 Riverside" / (NAME + ".esx")
        self.path.write_bytes(_project(SURVEYS, "merged"))

    def _mgr(self):
        mgr = self.cm.CloudManager.__new__(self.cm.CloudManager)
        mgr.config = {"output_dir": str(self.root)}
        mgr._ensure = lambda: True
        mgr.api = _api(_batch(SURVEYS))
        return mgr

    def test_pulling_over_a_short_file_leaves_it_complete(self):
        before = esx_survey_data.missing_in_file(self.path)
        self.assertTrue(before, "the fixture must start short")
        out = self._mgr().verify_replace_local("cloud-1", str(self.path))
        self.assertFalse(out.get("error"), out)
        self.assertEqual([], esx_survey_data.missing_in_file(self.path))
        with zipfile.ZipFile(self.path) as z:
            self.assertEqual(_served("t1"), z.read("track-t1.bin"))
            self.assertEqual(_served("c1"), z.read("spectrum-c1.bin"))

    def test_a_pull_that_cannot_fetch_the_samples_leaves_the_file_as_it_was(self):
        mgr = self._mgr()
        mgr.api = _api(_batch(SURVEYS), refuse=("t2",))
        before = self.path.read_bytes()
        out = mgr.verify_replace_local("cloud-1", str(self.path))
        self.assertIn("error", out)
        self.assertEqual(before, self.path.read_bytes())


NODE_SCRIPT = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[process.argv.length - 1], "utf8");
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block = slice('function ownershipBlock(', '\nfunction _isExternal(')
            + slice('function comparisonIsSettled(', '\nfunction isOutOfSync(')
            + slice('const ICONS = {', '\nfunction siteDigest(')
            + slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)');
const WD = { esc: s => String(s == null ? '' : s),
             escAttr: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'),
             escJsStr: s => String(s == null ? '' : s) };
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function np(s) { return String(s == null ? '' : s).replace(/\\/g, '/'); }
function p(s) { return a(np(s)); }
const noop = () => {};
const calls = [];
const fn = new Function('WD','e','a','p','np','currentTab','opEnqueue','toast','pyApi','showConfirmModal','_clearStaleness','_scheduleOpRefresh','selectedSyncItems','clearSelection','renderRows',
  block + '\nreturn { rowDetailHtml };');
const api = fn(WD,e,a,p,np,'projects',noop,noop,async()=>({}),async()=>true,noop,noop,()=>[],noop,noop);
__DELEGATED__
const row = (gaps, matchType, staleness) => ({
  kind: 'projects', matchType: matchType, status: 'synced',
  staleness: staleness || null, differenceKind: null,
  cloud: { id: 'c1', name: 'SITE1 Survey Baseline', mtime: 100 },
  local: { path: 'C:/projects/SITE1/SITE1 Survey Baseline.esx',
           name: 'SITE1 Survey Baseline', mtime: 100, surveyGaps: gaps },
});
const html = (g, m, s) => api.rowDetailHtml(row(g, m, s), false);
const out = {};
out.short = html(4, 'id');
out.shortOne = html(1, 'id');
out.complete = html(0, 'id');
out.shortGuessed = html(4, 'fuzzy');
out.shortStale = html(4, 'id', 'cloud_newer');
const hit = delegated(out.short, 'verifyReplaceLocal');
out.hit = hit && { args: hit.args, disabled: hit.disabled };
console.log(JSON.stringify(out));
""".replace("__DELEGATED__", "")


class TheRowSaysSoAndOffersTheRepairTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node is not installed")
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from delegated import DELEGATED_JS
        script = NODE_SCRIPT.replace("const row = (gaps",
                                     DELEGATED_JS + "\nconst row = (gaps", 1)
        r = subprocess.run(["node", "-e", script, str(CLOUD_JS)],
                           capture_output=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout)

    def test_a_short_file_says_what_is_missing_even_though_the_dates_agree(self):
        self.assertIn("Survey data is missing from this local file: 4 files",
                      self.out["short"])
        self.assertIn("signal and noise samples", self.out["short"])

    def test_one_file_is_worded_as_one(self):
        self.assertIn(": 1 file of signal and noise samples its surveys refer to is not in it",
                      self.out["shortOne"])

    def test_a_complete_file_gets_no_band_at_all(self):
        self.assertEqual("", self.out["complete"])

    def test_the_repair_reaches_the_pull_with_this_pairs_arguments(self):
        hit = self.out["hit"]
        self.assertIsNotNone(hit, "no Re-download survey data control on the row")
        self.assertEqual(["c1", "C:/projects/SITE1/SITE1 Survey Baseline.esx",
                          "SITE1 Survey Baseline", 100, 100], hit["args"])
        self.assertFalse(hit["disabled"])
        self.assertIn("Re-download survey data", self.out["short"])

    def test_a_guessed_pairing_is_told_and_not_offered_an_overwrite(self):
        self.assertIn("Survey data is missing", self.out["shortGuessed"])
        self.assertNotIn("verifyReplaceLocal", self.out["shortGuessed"])

    def test_a_row_that_already_offers_a_download_does_not_offer_two(self):
        self.assertEqual(1, self.out["shortStale"].count('data-fn="verifyReplaceLocal"'))


class TheHelpersNameTheMembersExactlyTests(unittest.TestCase):
    """The member names are the contract with Ekahau Pro: one letter off and
    the file opens with surveys and no samples, which is the defect."""

    def test_the_member_names(self):
        self.assertEqual("track-t1.bin", esx_survey_data.track_member("t1"))
        self.assertEqual("spectrum-c1.bin", esx_survey_data.spectrum_member("c1"))
        self.assertEqual("survey-s1.json", esx_survey_data.survey_member("s1"))
        self.assertEqual("wcs-m1.csv", esx_survey_data.wcs_member("m1"))

    def test_expected_members_lists_each_once_and_skips_the_deleted(self):
        surveys = [
            _survey("s1", tracks=("t1", "t1", "t2"), chunks=("c1",)),
            _survey("s2", tracks=("t3",), status="DELETED"),
        ]
        plans = [{"id": "fp1", "ciscoWcsRadioMappingDataId": "m1"},
                 {"id": "fp2", "ciscoWcsRadioMappingDataId": "m2",
                  "status": "DELETED"},
                 {"id": "fp3"}]
        self.assertEqual(
            ["survey-s1.json", "track-t1.bin", "track-t2.bin",
             "spectrum-c1.bin", "wcs-m1.csv"],
            esx_survey_data.expected_members(surveys, plans))

    def test_surveys_in_reads_either_layout_and_does_not_double_count(self):
        both = _esx_bytes({
            "survey-s1.json": json.dumps({"surveys": [_survey("s1")]}),
            "surveys.json": json.dumps({"surveys": [_survey("s1"),
                                                    _survey("s2")]})})
        with zipfile.ZipFile(io.BytesIO(both)) as z:
            self.assertEqual(["s1", "s2"],
                             sorted(s["id"] for s in esx_survey_data.surveys_in(z)))

    def test_missing_members_includes_a_radio_mapping_file(self):
        data = _esx_bytes({"floorPlans.json": json.dumps({"floorPlans": [
            {"id": "fp1", "ciscoWcsRadioMappingDataId": "m1"}]})})
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertEqual(["wcs-m1.csv"],
                             esx_survey_data.missing_members(z))

    def test_an_unreadable_file_reports_nothing_rather_than_raising(self):
        tmp = Path(tempfile.mkdtemp(prefix="wd-survey-bad-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        bad = tmp / "bad.esx"
        bad.write_bytes(b"not a zip")
        self.assertEqual([], esx_survey_data.missing_in_file(bad))
        self.assertEqual([], esx_survey_data.missing_in_bytes(b"not a zip"))


PLAN_PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
const sandbox = { console, JSON, Math, Set, Map, RegExp, Number };
sandbox.data = JSON.parse(process.argv[2]);
sandbox.iOwn = () => true;
sandbox.selectedSyncItems = () => [];
vm.createContext(sandbox);
vm.runInContext(
  slice('const PULLABLE_MATCH_TYPES', 'function compareResultFor(')
  + slice('function syncEverythingPlan(', '\nfunction _syncRowsHtml(')
  + '\nglobalThis.__plan = syncEverythingPlan();', sandbox);
const p = sandbox.__plan;
const names = (rows) => (rows || []).map(r => r.cloudName);
console.log(JSON.stringify({ down: names(p.down), up: names(p.up),
  inSync: names(p.inSync), shortLocal: names(p.shortLocal),
  downGaps: (p.down || []).map(r => r.surveyGaps) }));
"""


def _plan_for(pairs):
    data = {"currentUser": "me@example.invalid", "matched": pairs,
            "cloudOnly": [], "localOnly": [], "orphans": {"cloudOnly": []}}
    r = subprocess.run(["node", "-e", PLAN_PROGRAM, str(CLOUD_JS),
                        json.dumps(data)], capture_output=True,
                       encoding="utf-8", timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


def _pair(name, gaps, staleness=None, match="id"):
    return {"cloud": {"id": "c-" + name, "name": name, "mtime": 5000},
            "local": {"path": "D:\\E\\" + name + ".esx", "name": name,
                      "mtime": 5000, "surveyGaps": gaps},
            "matchType": match, "staleness": staleness,
            "divergence": None, "namesDiffer": False}


class SyncAllNoLongerCallsAShortFileMatchingTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node is not installed")

    def test_in_step_by_date_and_short_by_content_is_downloaded(self):
        got = _plan_for([_pair("Short", 4), _pair("Whole", 0)])
        self.assertEqual(["Short"], got["down"])
        self.assertEqual([4], got["downGaps"])
        self.assertEqual(["Whole"], got["inSync"])

    def test_a_guessed_pairing_is_never_pulled_over(self):
        got = _plan_for([_pair("Guess", 4, match="fuzzy")])
        self.assertEqual([], got["down"])

    def test_a_newer_short_file_is_not_sent_up(self):
        got = _plan_for([_pair("Edited", 4, staleness="local_newer"),
                         _pair("EditedWhole", 0, staleness="local_newer")])
        self.assertEqual(["Edited"], got["shortLocal"])
        self.assertEqual(["EditedWhole"], got["up"],
                         "the ordinary newer-local push must still run")
        self.assertNotIn("Edited", got["up"])


COUNT_PROGRAM = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
let stored = null;
function compareResultFor() { return stored; }
const block = slice('function comparisonIsSettled(', '\n/* Is this cloud project filed under no site');
const api = new Function('compareResultFor', block + '\nreturn { comparisonIsSettled, isOutOfSync };')(compareResultFor);
const out = {};
out.hollowBothSides = api.comparisonIsSettled({ designDiffers: false, nameState: 'same', surveyDataIncomplete: true });
out.sameAndWhole = api.comparisonIsSettled({ designDiffers: false, nameState: 'same', surveyDataIncomplete: false });
out.shortNoDates = api.isOutOfSync({ local: { surveyGaps: 3 }, staleness: null });
out.wholeNoDates = api.isOutOfSync({ local: { surveyGaps: 0 }, staleness: null });
stored = { designDiffers: false, nameState: 'same', surveyDataIncomplete: true };
out.shortAndComparedHollow = api.isOutOfSync({ local: { surveyGaps: 3 }, staleness: 'cloud_newer' });
console.log(JSON.stringify(out));
"""


class TheCountsAndTheSettledTestAgreeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node is not installed")
        r = subprocess.run(["node", "-e", COUNT_PROGRAM, str(CLOUD_JS)],
                           capture_output=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout)

    def test_two_hollow_copies_are_not_settled(self):
        self.assertFalse(self.out["hollowBothSides"])
        self.assertTrue(self.out["sameAndWhole"])

    def test_a_short_file_counts_as_out_of_sync_with_no_date_difference(self):
        self.assertTrue(self.out["shortNoDates"])
        self.assertFalse(self.out["wholeNoDates"])

    def test_a_comparison_that_found_both_hollow_does_not_retire_it(self):
        self.assertTrue(self.out["shortAndComparedHollow"])


PUSH_PROGRAM = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
const block = slice('async function pushLocalOverCloud(', '/* The badge used to be');
const enqueued = [], asked = [];
let answer = true;
const e = (s) => String(s == null ? '' : s);
const showConfirmModal = async (title, body, label) => { asked.push({ title, body, label }); return answer; };
const _enqueuePushLocalOverCloud = (...a) => enqueued.push(a);
const PROVEN_MATCH_TYPES = new Set(['id', 'manual']);
const f = new Function('e', 'showConfirmModal', '_enqueuePushLocalOverCloud', 'PROVEN_MATCH_TYPES',
  block + '\nreturn pushLocalOverCloud;')(e, showConfirmModal, _enqueuePushLocalOverCloud, PROVEN_MATCH_TYPES);
(async () => {
  const out = {};
  await f('c1', 'p.esx', 'Local', 'Cloud', 'id');
  out.wholeAsked = asked.length; out.wholeSent = enqueued.length;
  asked.length = 0; enqueued.length = 0;
  answer = false;
  await f('c1', 'p.esx', 'Local', 'Cloud', 'id', 3);
  out.declinedAsked = asked.length; out.declinedSent = enqueued.length;
  out.body = asked[0] && asked[0].body;
  asked.length = 0; enqueued.length = 0;
  answer = true;
  await f('c1', 'p.esx', 'Local', 'Cloud', 'id', 3);
  out.acceptedSent = enqueued.length;
  console.log(JSON.stringify(out));
})();
"""


class ReplacingTheCloudWithAShortFileAsksFirstTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node is not installed")
        r = subprocess.run(["node", "-e", PUSH_PROGRAM, str(CLOUD_JS)],
                           capture_output=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_whole_file_goes_up_with_no_question_as_before(self):
        self.assertEqual(0, self.out["wholeAsked"])
        self.assertEqual(1, self.out["wholeSent"])

    def test_a_short_file_asks_and_declining_sends_nothing(self):
        self.assertEqual(1, self.out["declinedAsked"])
        self.assertEqual(0, self.out["declinedSent"])
        self.assertIn("cannot be undone", self.out["body"])
        self.assertIn("3 files", self.out["body"])

    def test_a_short_file_goes_up_once_he_says_so(self):
        """Friction, not a wall: the samples may be gone everywhere."""
        self.assertEqual(1, self.out["acceptedSent"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
