"""Four functions that decide something, none of which any test had run.

Backlog item 12. These are not helpers - each one answers a question the tool
then acts on:

* `sync_state.verdict_for` - which of the five states a pair is in, and
  therefore whether Sync will touch it at all.
* `cloud_realign.find_candidates` - which pairs the realign action will
  consider writing to.
* `prep_pipeline.stale_placeholder_areas` - which areas a re-run may replace.
* `wall_inject.inject_into_members` - what a wall template actually adds.

The first two are the interesting pair, because both are deliberately *not*
using the obvious field, and a later reader who does not know that would
"simplify" them straight back into the bug they were written to avoid.
"""
from __future__ import annotations

import copy
import json
import unittest

from tools import cloud_realign, prep_pipeline, sync_state, wall_inject


FLOOR = "floor-ground"
LOCAL = "C:/Projects/Example Site/example-campus.esx"


def record(local_path=LOCAL, cloud_mtime=1_000_000, local_mtime=1_000_000):
    return {"localPath": local_path,
            "cloudMtime": cloud_mtime,
            "localMtime": local_mtime}


class VerdictForTests(unittest.TestCase):
    """The four-state answer the row and the Sync dialog are built from."""

    def verdict(self, pairs, cloud_mtime, local_mtime, local_path=LOCAL):
        return sync_state.verdict_for(pairs, "cloud-1", local_path,
                                      cloud_mtime, local_mtime)

    def test_neither_side_moved_is_in_sync(self):
        pairs = {"cloud-1": record()}
        self.assertEqual(sync_state.IN_SYNC,
                         self.verdict(pairs, 1_000_000, 1_000_000))

    def test_only_the_cloud_moved(self):
        pairs = {"cloud-1": record()}
        self.assertEqual(sync_state.CLOUD_CHANGED,
                         self.verdict(pairs, 1_009_999, 1_000_000))

    def test_only_the_local_file_moved(self):
        pairs = {"cloud-1": record()}
        self.assertEqual(sync_state.LOCAL_CHANGED,
                         self.verdict(pairs, 1_000_000, 1_009_999))

    def test_both_moved_is_a_divergence(self):
        """The state nothing resolves automatically."""
        pairs = {"cloud-1": record()}
        self.assertEqual(sync_state.BOTH_CHANGED,
                         self.verdict(pairs, 1_009_999, 1_009_999))

    def test_a_pair_with_no_record_is_unknown_rather_than_in_sync(self):
        """An unrecorded pair looks exactly like an unchanged one from the
        dates alone. Answering "in sync" would be a guess presented as fact."""
        self.assertEqual(sync_state.UNKNOWN, self.verdict({}, 1, 1))
        self.assertEqual(sync_state.UNKNOWN, self.verdict(None, 1, 1))

    def test_a_local_file_that_moved_on_disk_is_unknown(self):
        """The record describes a path. A different path is a different file,
        and guessing is how the wrong project gets overwritten.
        """
        pairs = {"cloud-1": record(local_path="C:/Elsewhere/renamed.esx")}
        self.assertEqual(sync_state.UNKNOWN,
                         self.verdict(pairs, 1_000_000, 1_000_000))

    def test_the_path_comparison_survives_slashes_and_case(self):
        """Windows gives the same file back with either separator, and a
        false "unknown" on every row would make the feature useless."""
        pairs = {"cloud-1": record(local_path=LOCAL)}
        other = LOCAL.replace("/", chr(92)).upper()
        self.assertEqual(sync_state.IN_SYNC,
                         self.verdict(pairs, 1_000_000, 1_000_000, other))

    def test_a_missing_timestamp_anywhere_is_unknown(self):
        for kwargs in ({"cloud_mtime": 0}, {"local_mtime": 0}):
            with self.subTest(recorded=kwargs):
                pairs = {"cloud-1": record(**kwargs)}
                self.assertEqual(sync_state.UNKNOWN,
                                 self.verdict(pairs, 1_000_000, 1_000_000))
        for now in ((0, 1_000_000), (1_000_000, 0)):
            with self.subTest(now=now):
                pairs = {"cloud-1": record()}
                self.assertEqual(sync_state.UNKNOWN, self.verdict(pairs, *now))

    def test_a_small_difference_is_within_tolerance(self):
        """Filesystems and APIs disagree by a second or two about the same
        write; treating that as a change would report everything diverged."""
        pairs = {"cloud-1": record()}
        self.assertEqual(
            sync_state.IN_SYNC,
            self.verdict(pairs, 1_000_000 + sync_state.TOLERANCE_S,
                         1_000_000 + sync_state.TOLERANCE_S))

    def test_moving_backwards_counts_as_moving(self):
        """A project restored from an older copy has changed. Calling it
        unchanged would let the other side silently overwrite it."""
        pairs = {"cloud-1": record()}
        self.assertEqual(sync_state.CLOUD_CHANGED,
                         self.verdict(pairs, 900_000, 1_000_000))

    def test_the_cloud_id_is_looked_up_as_a_string(self):
        """Ekahau ids arrive from JSON as strings and from some callers as
        whatever they were stored as."""
        pairs = {"12345": record()}
        self.assertEqual(
            sync_state.IN_SYNC,
            sync_state.verdict_for(pairs, 12345, LOCAL, 1_000_000, 1_000_000))


class FindCandidatesTests(unittest.TestCase):

    @staticmethod
    def data(*matched):
        return {"matched": list(matched)}

    def test_only_pairs_where_the_cloud_reads_newer_are_candidates(self):
        picked = cloud_realign.find_candidates(self.data(
            {"id": "a", "staleness": "cloud_newer"},
            {"id": "b", "staleness": "local_newer"},
            {"id": "c", "staleness": "same"},
        ))
        self.assertEqual(["a"], [p["id"] for p in picked])

    def test_the_rename_heuristic_is_deliberately_not_the_filter(self):
        """The function's docstring is the requirement.

        `difference == "renamed"` is the name-based guess. Using it to choose
        what to write to would make a guess load-bearing; every candidate is
        settled by a content comparison afterwards instead. A pair the
        heuristic calls "content" and the comparison finds identical is
        precisely the case the action was built for.
        """
        picked = cloud_realign.find_candidates(self.data(
            {"id": "renamed", "staleness": "cloud_newer", "difference": "renamed"},
            {"id": "content", "staleness": "cloud_newer", "difference": "content"},
        ))
        self.assertEqual({"renamed", "content"}, {p["id"] for p in picked})

    def test_unmatched_projects_are_not_candidates(self):
        """Only a matched pair has two sides to compare."""
        picked = cloud_realign.find_candidates({
            "matched": [],
            "cloudOnly": [{"id": "x", "staleness": "cloud_newer"}],
            "localOnly": [{"id": "y", "staleness": "cloud_newer"}],
        })
        self.assertEqual([], picked)

    def test_nothing_at_all_is_an_empty_list(self):
        for data in ({}, {"matched": None}, {"matched": []}):
            with self.subTest(data=data):
                self.assertEqual([], cloud_realign.find_candidates(data))


class StalePlaceholderAreasTests(unittest.TestCase):
    """Which areas a Prep re-run may replace, and which are the user's."""

    def members(self, *, area_points=None, walls=True, aps=False):
        floor = {"id": FLOOR, "name": "Ground", "width": 400.0, "height": 300.0,
                 "metersPerUnit": 0.05}
        canvas = [{"x": 0.0, "y": 0.0}, {"x": 400.0, "y": 0.0},
                  {"x": 400.0, "y": 300.0}, {"x": 0.0, "y": 300.0}]
        members = {
            "floorPlans.json": {"floorPlans": [floor]},
            "areas.json": {"areas": [{
                "id": "area-1", "floorPlanId": FLOOR,
                "area": area_points if area_points is not None else canvas,
                "capacityItems": [{"id": "cap-1"}],
            }]},
            "wallPoints.json": {"wallPoints": []},
            "wallSegments.json": {"wallSegments": []},
            "accessPoints.json": {"accessPoints": []},
        }
        if walls:
            members["wallPoints.json"]["wallPoints"] = [
                {"id": "wp%d" % i,
                 "location": {"floorPlanId": FLOOR,
                              "coord": {"x": 50.0 + i * 40, "y": 60.0 + i * 20}}}
                for i in range(4)]
            members["wallSegments.json"]["wallSegments"] = [
                {"id": "ws1", "wallPoints": ["wp0", "wp1"]},
                {"id": "ws2", "wallPoints": ["wp1", "wp2"]},
                {"id": "ws3", "wallPoints": ["wp2", "wp3"]},
            ]
        if aps:
            members["accessPoints.json"]["accessPoints"] = [
                {"id": "ap%d" % i, "name": "AP%d" % i,
                 "location": {"floorPlanId": FLOOR,
                              "coord": {"x": 80.0 + i * 50, "y": 90.0 + i * 30}}}
                for i in range(3)]
        return members

    def test_a_whole_canvas_area_with_something_better_to_measure_is_stale(self):
        found = prep_pipeline.stale_placeholder_areas(self.members(walls=True))
        self.assertEqual(["area-1"], [a["areaId"] for a in found])
        self.assertEqual("walls", found[0]["newBasis"])
        self.assertEqual("Ground", found[0]["floorName"])

    def test_an_area_the_user_drew_is_never_stale(self):
        """Only the whole-canvas shape can be told apart from his own work.

        This is the load-bearing condition: anything else on the plan is a
        polygon somebody chose, and replacing it would be Prep overwriting a
        decision.
        """
        drawn = [{"x": 40.0, "y": 40.0}, {"x": 300.0, "y": 40.0},
                 {"x": 300.0, "y": 250.0}, {"x": 40.0, "y": 250.0}]
        self.assertEqual([], prep_pipeline.stale_placeholder_areas(
            self.members(area_points=drawn, walls=True)))

    def test_nothing_better_to_measure_means_nothing_to_redo(self):
        """Without this a re-run replaces the area with an identical one and
        calls it progress."""
        self.assertEqual([], prep_pipeline.stale_placeholder_areas(
            self.members(walls=False, aps=False)))

    def test_an_area_with_no_capacity_items_is_not_ours(self):
        m = self.members(walls=True)
        m["areas.json"]["areas"][0].pop("capacityItems")
        self.assertEqual([], prep_pipeline.stale_placeholder_areas(m))

    def test_an_area_on_a_floor_that_is_gone_is_skipped(self):
        m = self.members(walls=True)
        m["areas.json"]["areas"][0]["floorPlanId"] = "floor-that-was-deleted"
        self.assertEqual([], prep_pipeline.stale_placeholder_areas(m))

    def test_a_project_with_no_areas_at_all(self):
        self.assertEqual([], prep_pipeline.stale_placeholder_areas({}))


class InjectIntoMembersTests(unittest.TestCase):
    """What a wall template actually adds to a project."""

    def members(self, existing=()):
        return {wall_inject.MEMBER: json.dumps({"wallTypes": list(existing)})}

    TEMPLATE = [
        {"id": "wt-brick", "name": "Brick", "color": "#B5651D",
         "thickness": 0.2},
        {"id": "wt-glass", "name": "Glass", "color": "#9FD8EF"},
    ]

    def test_a_missing_type_is_added(self):
        m = self.members()
        report = wall_inject.inject_into_members(m, self.TEMPLATE)
        names = [w["name"] for w in json.loads(m[wall_inject.MEMBER])["wallTypes"]]
        self.assertEqual(["Brick", "Glass"], names)
        self.assertEqual(2, len(report["add"]))

    def test_the_members_dict_is_changed_in_place(self):
        m = self.members()
        before = m[wall_inject.MEMBER]
        wall_inject.inject_into_members(m, self.TEMPLATE)
        self.assertNotEqual(before, m[wall_inject.MEMBER])

    def test_a_type_that_is_already_there_is_not_added_twice(self):
        m = self.members([{"id": "existing", "name": "Brick"}])
        wall_inject.inject_into_members(m, self.TEMPLATE)
        names = [w["name"] for w in json.loads(m[wall_inject.MEMBER])["wallTypes"]]
        self.assertEqual(1, names.count("Brick"))

    def test_a_template_id_that_is_already_taken_gets_a_fresh_one(self):
        """A template captured out of another project carries that project's
        ids, and two projects can legitimately collide. Overwriting whatever
        already answers to that id is the outcome being avoided.
        """
        m = self.members([{"id": "wt-brick", "name": "Something Else"}])
        wall_inject.inject_into_members(m, self.TEMPLATE)
        types = json.loads(m[wall_inject.MEMBER])["wallTypes"]
        ids = [w["id"] for w in types]
        self.assertEqual(len(ids), len(set(ids)), "an id was reused: %r" % ids)
        kept = next(w for w in types if w["name"] == "Something Else")
        self.assertEqual("wt-brick", kept["id"], "the existing type was moved")

    def test_a_free_template_id_is_kept(self):
        m = self.members()
        wall_inject.inject_into_members(m, self.TEMPLATE)
        types = json.loads(m[wall_inject.MEMBER])["wallTypes"]
        self.assertEqual("wt-brick",
                         next(w for w in types if w["name"] == "Brick")["id"])

    def test_the_template_structure_is_copied_rather_than_shared(self):
        """Injecting one template into two projects must not link them.

        The probe has to be a case that *writes* to the copy, or sharing the
        dict is invisible - found by mutation, because a version using the
        source object directly passed a gentler version of this test. So the
        first project is set up to force an id collision: the code assigns a
        fresh id, and if that was written into the template itself then the
        second project inherits the replacement.
        """
        template = copy.deepcopy(self.TEMPLATE)
        collides = self.members([{"id": "wt-brick", "name": "Something Else"}])
        wall_inject.inject_into_members(collides, template)

        self.assertEqual("wt-brick", template[0]["id"],
                         "the fresh id was written back into the template")

        clean = self.members()
        wall_inject.inject_into_members(clean, template)
        brick = next(w for w in json.loads(clean[wall_inject.MEMBER])["wallTypes"]
                     if w["name"] == "Brick")
        self.assertEqual("wt-brick", brick["id"],
                         "the second project inherited the first one's "
                         "replacement id")

    def test_a_project_with_no_wall_types_member_is_refused_with_a_reason(self):
        report = wall_inject.inject_into_members({}, self.TEMPLATE)
        self.assertTrue(report.get("error"))
        self.assertIn("wallTypes.json", report["error"])

    def test_the_preview_and_the_run_describe_themselves_identically(self):
        """The function's docstring is the requirement: a preview that is a
        second description of the work can drift from what happens."""
        m = self.members()
        preview = wall_inject.plan_into_members(copy.deepcopy(m), self.TEMPLATE)
        actual = wall_inject.inject_into_members(m, self.TEMPLATE)
        self.assertEqual(preview["add"], actual["add"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
