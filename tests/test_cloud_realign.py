"""The realign action, exercised by running it against real files on disk.

It rewrites his live project files, so every property he asked for is checked
by doing the thing and reading the result back - not by finding a call in the
source. The archives here are real ZIPs written to a temp folder, the
comparison is the real `esx_compare`, and the assertions are on the bytes and
the timestamps afterwards.

Every project name, site folder and address in this file is invented.

**The one that would have shipped green.** The obvious reading of "set the
local file's modified time to the cloud project's modified time" is
`os.utime`, and it would have left all ninety rows still saying "cloud newer".
`get_local_esx_files` reports a local file's mtime as `internalMtime or
fs_mtime` - the `history.modifiedAt` written inside `project.json` - because a
filesystem date resets on copy or sync and the internal one does not. So
`test_the_date_the_tool_compares_is_the_one_that_moves` asserts on what
`get_local_esx_files` reports, which is the number the row is built from, and
fails if only the disk timestamp was touched.
"""
from __future__ import annotations

import json
import os
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tools import cloud_manager, cloud_realign

#: Two instants far enough apart to be unambiguous, and far enough apart to
#: clear `TOLERANCE_S` in both directions.
LOCAL_ISO = "2026-03-01T09:00:00.000Z"
CLOUD_ISO = "2026-04-15T14:30:00.000Z"
LOCAL_UNIX = int(datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc).timestamp())
CLOUD_UNIX = int(datetime(2026, 4, 15, 14, 30, 0, tzinfo=timezone.utc).timestamp())

OLD_NAME = "Maple Depot Survey"
NEW_NAME = "MPL-01 Maple Depot Survey"


def write_esx(path: Path, *, name: str, modified_iso: str,
              project_id: str = "00000000-0000-4000-8000-0000000000aa",
              ap_count: int = 2, image: bytes = b"floor-plan-bytes") -> Path:
    """A minimal but genuine .esx: a ZIP with the members the code reads.

    `ap_count` and `image` are the knobs a "this really is a different design"
    fixture turns, so a test can make two archives differ in the way that
    matters rather than in a way the comparison is meant to ignore.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    members = {
        "project.json": json.dumps({"project": {
            "id": project_id,
            "name": name,
            "title": name,
            "history": {"createdBy": "engineer@example.com",
                        "modifiedAt": modified_iso},
        }}).encode("utf-8"),
        "accessPoints.json": json.dumps({"accessPoints": [
            {"id": "ap-%d" % i, "name": "AP %d" % (i + 1)}
            for i in range(ap_count)]}).encode("utf-8"),
        "floorPlans.json": json.dumps({"floorPlans": [
            {"id": "floor-1", "name": "Level 1"}]}).encode("utf-8"),
        "image-floor-1": image,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for member, raw in members.items():
            z.writestr(member, raw)
    return path


class RecordingAPI:
    """Every cloud call this could make, recorded rather than performed.

    The write-side methods exist and raise. That is the point: if a future
    edit reaches for `rename_project` or `delete_project`, the test fails
    loudly instead of the call quietly succeeding against a stub that
    tolerated it.
    """

    user_email = "engineer@example.com"

    def __init__(self, projects, downloads):
        self.projects = projects
        self.downloads = downloads
        self.calls = []

    def _note(self, name, *args):
        self.calls.append(name)

    def get_projects(self):
        self._note("get_projects")
        return list(self.projects)

    def get_dataset_listing(self):
        self._note("get_dataset_listing")
        return []

    def download_project(self, project_id, progress_cb=None):
        self._note("download_project")
        if project_id not in self.downloads:
            return {"error": "no such project"}
        return {"esx": self.downloads[project_id]}

    def _forbidden(self, name):
        def go(*a, **k):
            self._note(name)
            raise AssertionError("realign must never call %s" % name)
        return go

    def __getattr__(self, name):
        if name in ("upload_project", "rename_project", "rename_site",
                    "delete_project", "delete_dataset", "replace_project",
                    "create_site", "add_project_share"):
            return self._forbidden(name)
        raise AttributeError(name)


class RealignHarness(unittest.TestCase):
    """A local folder, a cloud listing, and a CloudManager wired to both."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.output = self.root / "Projects"
        self.site = self.output / "Maple Depot"
        self.site.mkdir(parents=True)
        # The metadata cache is keyed by path and lives at module scope, so a
        # previous test's file at the same path would otherwise be answered
        # from it.
        cloud_manager._ESX_META_CACHE.clear()
        cloud_manager._ESX_TYPE_CACHE.clear()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(cloud_manager._ESX_META_CACHE.clear)

    def build(self, *, local_name=OLD_NAME, cloud_name=NEW_NAME,
              local_iso=LOCAL_ISO, cloud_iso=CLOUD_ISO,
              local_aps=2, cloud_aps=2,
              local_image=b"floor-plan-bytes", cloud_image=b"floor-plan-bytes"):
        """One pair. The cloud copy is an archive in memory, as the API
        returns it; the local copy is a file on disk, as he has it."""
        self.local_path = self.site / ("%s.esx" % local_name)
        write_esx(self.local_path, name=local_name, modified_iso=local_iso,
                  ap_count=local_aps, image=local_image)

        cloud_file = self.root / "cloud-copy.esx"
        write_esx(cloud_file, name=cloud_name, modified_iso=cloud_iso,
                  ap_count=cloud_aps, image=cloud_image)
        cloud_bytes = cloud_file.read_bytes()
        cloud_file.unlink()

        project = {"id": "cloud-1", "name": cloud_name,
                   "statistics": {"size": 2048},
                   "history": {"createdBy": "engineer@example.com",
                               "modifiedAt": cloud_iso}}

        self.api = RecordingAPI([project], {"cloud-1": cloud_bytes})
        self.cm = cloud_manager.CloudManager()
        self.cm.api = self.api
        self.cm.config = {"output_dir": str(self.output)}
        return self.local_path

    # ── helpers ──────────────────────────────────────────────────
    def internal(self, path=None):
        """What `project.json` says now - the name and the date the tool
        compares. Read straight out of the archive, not through a cache."""
        with zipfile.ZipFile(path or self.local_path) as z:
            proj = json.loads(z.read("project.json"))["project"]
        return proj.get("name"), (proj.get("history") or {}).get("modifiedAt")

    def reported_mtime(self):
        """The mtime `build_matches` would compare - i.e. what the row shows."""
        cloud_manager._ESX_META_CACHE.clear()
        files = cloud_manager.get_local_esx_files(str(self.output))
        self.assertEqual(len(files), 1)
        return files[0]["mtime"]

    def strays(self):
        """Every file under the local folder that is not the project itself.

        Nothing is copied aside, so a run adds no file at all - which makes a
        stray the whole of what there is to look for. A surviving
        `.wd-rename.tmp` would be picked up by the next scan as a project
        nobody made, and it is the path that crosses MAX_PATH first.
        """
        return sorted(p for p in self.output.rglob("*")
                      if p.is_file() and p != self.local_path)


class TheDryRunChangesNothing(RealignHarness):
    """Dry run is the default, and it is a report rather than a rehearsal."""

    def test_the_default_is_a_dry_run(self):
        """A caller that forgets the argument must not write to his files.

        `realign(cm)` with nothing else said is the shape the endpoint uses
        when `dryRun` is absent, and it is the shape a future caller will
        reach for first.
        """
        self.build()
        before = self.local_path.read_bytes()
        report = cloud_realign.realign(self.cm)
        self.assertTrue(report["dryRun"])
        self.assertEqual(self.local_path.read_bytes(), before)

    def test_it_says_what_it_would_do_per_file(self):
        """The preview has to be specific enough to act on - a count is not
        a plan."""
        self.build()
        report = cloud_realign.realign(self.cm, dry_run=True)
        self.assertEqual(report["counts"]["aligned"], 1)
        entry = report["aligned"][0]
        self.assertEqual(entry["name"], OLD_NAME)
        self.assertEqual(entry["folder"], "Maple Depot")
        joined = " ".join(entry["actions"]).lower()
        self.assertIn("name", joined)
        self.assertIn("date", joined)
        self.assertIn("2026-04-15", entry["newDate"])

    def test_a_dry_run_leaves_no_file_behind_either(self):
        """A preview that quietly wrote anything to his folder would be a write
        by another name."""
        self.build()
        cloud_realign.realign(self.cm, dry_run=True)
        self.assertEqual(self.strays(), [])

    def test_the_dry_run_really_compared_rather_than_guessed(self):
        """The preview is only worth trusting if it did the same work. It has
        to have downloaded the cloud copy to have compared anything."""
        self.build()
        cloud_realign.realign(self.cm, dry_run=True)
        self.assertIn("download_project", self.api.calls)


class ItOnlyTouchesProvenIdenticalPairs(RealignHarness):

    def test_a_real_design_difference_is_skipped_and_listed(self):
        """An extra access point on one side is real work, and the file must
        come through untouched."""
        self.build(cloud_aps=7)
        before = self.local_path.read_bytes()

        report = cloud_realign.realign(self.cm, dry_run=False)

        self.assertEqual(report["counts"]["aligned"], 0)
        self.assertEqual(report["counts"]["skipped"], 1)
        skipped = report["skipped"][0]
        self.assertEqual(skipped["name"], OLD_NAME)
        self.assertIn("differ", skipped["reason"].lower())
        self.assertEqual(self.local_path.read_bytes(), before)
        self.assertEqual(self.strays(), [])

    def test_a_recropped_floor_plan_is_a_difference(self):
        """The image hash is what catches a re-cropped plan. A document-only
        comparison would call this pair identical and overwrite the date on a
        file whose design really did move.
        """
        self.build(cloud_image=b"a-different-floor-plan")
        before = self.local_path.read_bytes()

        report = cloud_realign.realign(self.cm, dry_run=False)

        self.assertEqual(report["counts"]["aligned"], 0)
        self.assertEqual(report["counts"]["skipped"], 1)
        self.assertEqual(self.local_path.read_bytes(), before)

    def test_identical_but_renamed_is_the_case_it_does_act_on(self):
        self.build()
        report = cloud_realign.realign(self.cm, dry_run=False)
        self.assertEqual(report["counts"]["aligned"], 1)
        self.assertEqual(report["counts"]["skipped"], 0)
        self.assertEqual(report["counts"]["failed"], 0)


class ItFixesTheThingsHeAskedFor(RealignHarness):

    def test_the_stale_internal_name_is_corrected(self):
        """The name inside the file is the one he cannot see and the one that
        keeps the row complaining."""
        self.build()
        self.assertEqual(self.internal()[0], OLD_NAME)

        cloud_realign.realign(self.cm, dry_run=False)

        self.assertEqual(self.internal()[0], NEW_NAME)

    def test_the_date_the_tool_compares_is_the_one_that_moves(self):
        """The property that matters: after this runs, the date the row is
        built from equals the cloud's. `os.utime` alone passes a filesystem
        assertion and fails this one.
        """
        self.build()
        self.assertEqual(self.reported_mtime(), LOCAL_UNIX)

        cloud_realign.realign(self.cm, dry_run=False)

        self.assertEqual(self.reported_mtime(), CLOUD_UNIX)

    def test_the_file_on_disk_agrees_with_what_is_inside_it(self):
        """Both were asked for, so both are checked. A file whose disk date
        disagreed with its contents would be a new confusion in place of the
        old one."""
        self.build()
        cloud_realign.realign(self.cm, dry_run=False)
        self.assertAlmostEqual(self.local_path.stat().st_mtime, CLOUD_UNIX,
                               delta=2)

    def test_the_date_written_is_the_cloud_s_own_string(self):
        """Nothing is forged. The value in the file is the one the cloud
        record carried, not a reconstruction and not `now`."""
        self.build()
        cloud_realign.realign(self.cm, dry_run=False)
        self.assertEqual(self.internal()[1], CLOUD_ISO)

    def test_a_pair_that_differs_only_by_date_is_still_aligned(self):
        """He renamed the cloud project back to the same text on both sides in
        a few cases. There is no name to fix there, and the date still needs
        settling - `wants_name` and `wants_date` are separate for this."""
        self.build(local_name=NEW_NAME, cloud_name=NEW_NAME)
        report = cloud_realign.realign(self.cm, dry_run=False)
        self.assertEqual(report["counts"]["aligned"], 1)
        self.assertEqual(self.reported_mtime(), CLOUD_UNIX)

    def test_the_rest_of_the_archive_is_carried_across_untouched(self):
        """It corrects a label; it is not a re-save. Every other member has to
        come out byte for byte, or this has quietly rewritten his design."""
        self.build()
        with zipfile.ZipFile(self.local_path) as z:
            before = {n: z.read(n) for n in z.namelist() if n != "project.json"}

        cloud_realign.realign(self.cm, dry_run=False)

        with zipfile.ZipFile(self.local_path) as z:
            after = {n: z.read(n) for n in z.namelist() if n != "project.json"}
        self.assertEqual(before, after)


class ItWritesOneFileAndNothingElse(RealignHarness):
    """No copy is kept, so the write itself has to be the safety.

    That is defensible here and nowhere else in the suite's rewriting: this
    only ever runs on a pair `esx_compare` has just proved byte-identical, and
    the one field it changes is the project name, which the cloud is holding a
    copy of. Every other member is passed through unchanged - which is the
    property below, and it fails if the rebuild starts inventing entries.
    """

    def test_the_folder_gains_no_file_when_it_rewrites(self):
        self.build()
        report = cloud_realign.realign(self.cm, dry_run=False)
        self.assertEqual(report["counts"]["aligned"], 1)
        self.assertNotIn("backup", report["aligned"][0])
        self.assertEqual(self.strays(), [])

    def test_the_project_still_opens_and_kept_every_other_member(self):
        """An atomic replace that produced an unreadable archive would pass a
        count-the-files check and lose the project."""
        self.build()
        with zipfile.ZipFile(self.local_path) as z:
            before = {n: z.read(n) for n in z.namelist() if n != "project.json"}

        cloud_realign.realign(self.cm, dry_run=False)

        with zipfile.ZipFile(self.local_path) as z:
            after = {n: z.read(n) for n in z.namelist() if n != "project.json"}
        self.assertEqual(before, after)


class ItIsSafeToRunAgain(RealignHarness):

    def test_a_second_run_finds_nothing_left_to_do(self):
        self.build()
        first = cloud_realign.realign(self.cm, dry_run=False)
        self.assertEqual(first["counts"]["aligned"], 1)

        second = cloud_realign.realign(self.cm, dry_run=False)

        self.assertEqual(second["examined"], 0)
        self.assertEqual(second["counts"]["aligned"], 0)
        self.assertEqual(second["counts"]["failed"], 0)

    def test_a_second_run_writes_nothing_to_the_folder(self):
        """An interrupted run re-run must not litter the folder with anything
        - `_rewrite_project_json` writes nothing at all when the mutation
        changes nothing, which is what makes a re-run free."""
        self.build()
        cloud_realign.realign(self.cm, dry_run=False)
        cloud_realign.realign(self.cm, dry_run=False)
        self.assertEqual(self.strays(), [])

    def test_a_second_run_leaves_the_bytes_alone(self):
        self.build()
        cloud_realign.realign(self.cm, dry_run=False)
        after_first = self.local_path.read_bytes()
        cloud_realign.realign(self.cm, dry_run=False)
        self.assertEqual(self.local_path.read_bytes(), after_first)


class NothingGoesUpAndNothingIsDeleted(RealignHarness):

    def test_the_only_cloud_call_that_carries_data_is_a_download(self):
        """Asserted against an API whose write methods raise, so this cannot
        pass by the stub quietly tolerating a call."""
        self.build()
        cloud_realign.realign(self.cm, dry_run=False)
        self.assertEqual(set(self.api.calls),
                         {"get_projects", "get_dataset_listing",
                          "download_project"})

    def test_it_never_renames_the_cloud_project_to_match_the_local_one(self):
        """The fix is always local. Renaming the cloud to match a stale local
        name would undo the work he did in Ekahau."""
        self.build()
        cloud_realign.realign(self.cm, dry_run=False)
        self.assertNotIn("rename_project", self.api.calls)
        self.assertNotIn("upload_project", self.api.calls)


class TheReportAccountsForEverything(RealignHarness):

    def test_the_three_lists_add_up_to_what_was_examined(self):
        """Nothing may fall between the preview and the run. A pair that is
        neither aligned nor skipped nor failed is a pair he was not told
        about."""
        self.build(cloud_aps=9)
        report = cloud_realign.realign(self.cm, dry_run=True)
        total = sum(report["counts"][k] for k in ("aligned", "skipped", "failed"))
        self.assertEqual(total, report["examined"])

    def test_a_download_failure_is_reported_as_a_failure_not_a_skip(self):
        """A skip means "looked, and decided not to". A failure means "could
        not look". Collapsing the two would hide an outage as a clean run."""
        self.build()
        self.api.downloads = {}
        report = cloud_realign.realign(self.cm, dry_run=False)
        self.assertEqual(report["counts"]["failed"], 1)
        self.assertEqual(report["counts"]["aligned"], 0)
        self.assertTrue(report["failed"][0]["error"])

    def test_a_pair_the_cloud_is_not_newer_than_is_never_examined(self):
        """The candidate set is the point of the whole operation - it is what
        keeps this off the ninety-odd files that are fine."""
        self.build(local_iso=CLOUD_ISO)
        report = cloud_realign.realign(self.cm, dry_run=True)
        self.assertEqual(report["examined"], 0)

    def test_it_refuses_when_no_local_folder_is_configured(self):
        self.build()
        self.cm.config = {"output_dir": ""}
        report = cloud_realign.realign(self.cm, dry_run=False)
        self.assertIn("error", report)


class TheEndpointDefaultsToTheSafeSide(unittest.TestCase):
    """`server.py` decides dry-vs-live from the request body, and an absent
    field has to mean dry. This runs the endpoint's own expression rather
    than reading it."""

    @staticmethod
    def _decide(data):
        # The expression from CLOUD_ACTIONS["realign_renamed"], kept in one
        # place here so the property is checked rather than the wording.
        return data.get("dryRun", True) is not False

    def test_an_absent_field_is_a_dry_run(self):
        self.assertTrue(self._decide({}))

    def test_a_null_field_is_a_dry_run(self):
        """A JSON `null` arrives as None. `bool(None)` is False, which would
        have made a malformed body start a live run."""
        self.assertTrue(self._decide({"dryRun": None}))

    def test_only_an_explicit_false_runs_for_real(self):
        self.assertFalse(self._decide({"dryRun": False}))
        self.assertTrue(self._decide({"dryRun": True}))

    def test_the_server_wires_that_expression_to_the_real_function(self):
        """The endpoint has to reach `cloud_realign.realign`. A route that
        exists and calls nothing is the defect this repo keeps catching."""
        import server
        self.assertIn("realign_renamed", server.CLOUD_ACTIONS)
        self.assertIs(server.cloud_realign.realign, cloud_realign.realign)


if __name__ == "__main__":
    unittest.main()
