"""Unproven ownership is not the same as somebody else's ownership.

"there were like 30-odd not-shared files and it only allowed me to share
three of them ... I know the majority of the files are mine."

**Every one of the thirty was his.** The gate asked `list_project_shares`
who owned each project, and that endpoint has nothing to say about a project
nobody has ever shared - which is the entire set somebody working through a
"not shared" filter has selected. No owner came back, "no owner" was read as
"not yours", and his own work was withheld from him.

The three that went through were the three that already had a share, so the
share list had an OWNER row to return. The arithmetic in the report is the
shape of the bug rather than a coincidence: it is not a sample, it is every
project with a share.

### Why nothing caught it

The fixture every existing bulk-share test is built on answers

    {pid: [{"username": ME, "role": "OWNER"}]}

for every project asked about. That is the one case the real endpoint does
not always produce, so the stub encoded the assumption the gate was wrong
about and the tests could only ever agree with it.

### The rule this pins

A project is mine, provably somebody else's, or unproven - three states, and
the third is not the second. Only a strong source may refuse: the dataset
listing and the share list each carry an explicit OWNER row, and either of
them naming somebody else is proof. `history.createdBy` may confirm that a
project is mine and may never conclude that it is not, because ownership can
be transferred and the creator does not move with it.

Everything unproven is attempted. Ekahau answers 403 for a project that is
not ours, and a refusal he can read and retry is better than a control that
quietly did nothing.

Every project, address and site here is invented.
"""
from __future__ import annotations

import unittest

from tools import cloud_manager

ME = "me@example.invalid"
MATE = "colleague@example.invalid"
GUEST = "guest@example.invalid"


class _Api:
    """The three sources ownership can be derived from, each independently
    able to answer nothing - which is the condition under test."""

    def __init__(self, datasets=None, projects=None, shares=None, me=ME):
        self.user_email = me
        self._datasets = datasets
        self._projects = projects
        self._shares = shares or {}
        self.shared = []
        self.share_calls = []

    def get_dataset_listing(self):
        if self._datasets is None:
            raise RuntimeError("no dataset listing")
        return self._datasets

    def get_projects(self):
        if self._projects is None:
            raise RuntimeError("no project listing")
        return self._projects

    def list_project_shares(self, pid):
        self.share_calls.append(pid)
        return self._shares.get(pid, {})

    def bulk_add_shares(self, project_ids, emails, role):
        self.shared.append(list(project_ids))
        return [{"responsePerEmailAddress": {e: "" for e in emails}}]


def _cm(api):
    cm = cloud_manager.CloudManager.__new__(cloud_manager.CloudManager)
    cm.api = api
    cm._ensure = lambda: True
    return cm


def _owned(pid, who):
    return {"id": pid, "datasetUsers": [{"username": who, "role": "OWNER"}]}


def _unowned(pid):
    return {"id": pid, "datasetUsers": []}


def _made_by(pid, who):
    return {"id": pid, "history": {"createdBy": who}}


class TheReportedCase(unittest.TestCase):
    """His selection, at his numbers."""

    def _his_account(self, shared_count=3, total=33):
        """Every project his; the first few shared, the rest never shared."""
        datasets = [
            _owned("p%d" % i, ME) if i <= shared_count else _unowned("p%d" % i)
            for i in range(1, total + 1)]
        projects = [_made_by("p%d" % i, ME) for i in range(1, total + 1)]
        #: The share endpoint answers for a shared project and says nothing
        #: about an unshared one, which is the whole mechanism.
        shares = {"p%d" % i: {"p%d" % i: [{"username": ME, "role": "OWNER"}]}
                  for i in range(1, shared_count + 1)}
        return _Api(datasets, projects, shares)

    def test_all_thirty_three_of_his_projects_are_shared(self):
        api = self._his_account()
        out = _cm(api).bulk_share(["p%d" % i for i in range(1, 34)], [GUEST])
        self.assertEqual([], out.get("skipped"),
                         "his own projects were withheld from him")
        self.assertEqual(33, out["ownedCount"])
        self.assertEqual(33, len(api.shared[0]),
                         "the share request did not carry every project")

    def test_the_selection_keeps_the_order_it_was_given(self):
        """The page pairs the answer back up with the rows it sent."""
        api = self._his_account()
        ids = ["p%d" % i for i in range(1, 34)]
        out = _cm(api).bulk_share(ids, [GUEST])
        self.assertEqual(ids, out["ownedIds"])

    def test_the_listing_answers_for_all_of_them_without_asking_one_by_one(self):
        """Thirty-three round trips to decide whether to make one is its own
        reason not to do it that way, and the listing is the source the rows
        on screen already use - which is the half that matters."""
        api = self._his_account()
        _cm(api).bulk_share(["p%d" % i for i in range(1, 34)], [GUEST])
        self.assertEqual(
            [], api.share_calls,
            "the share endpoint was asked about projects the listing had "
            "already placed: %s" % api.share_calls[:5])


class OnlyAProvenOwnerMayRefuse(unittest.TestCase):

    def _run(self, api, ids=("p1",)):
        return _cm(api).bulk_share(list(ids), [GUEST])

    def test_a_colleagues_project_is_still_refused(self):
        out = self._run(_Api([_owned("p1", MATE)], [_made_by("p1", MATE)]))
        self.assertEqual(["p1"], [s["projectId"] for s in out["skipped"]])
        self.assertEqual(MATE, out["skipped"][0]["owner"])
        self.assertEqual(0, out["ownedCount"])

    def test_the_share_list_can_also_prove_it_is_not_his(self):
        """The listing is asked first, but it is not the only proof."""
        out = self._run(_Api(
            [_unowned("p1")], [_made_by("p1", "")],
            {"p1": {"p1": [{"username": MATE, "role": "OWNER"}]}}))
        self.assertEqual(["p1"], [s["projectId"] for s in out["skipped"]])

    def test_created_by_someone_else_is_not_proof_and_is_attempted(self):
        """Ownership transfers; the creator does not move with it."""
        out = self._run(_Api([_unowned("p1")], [_made_by("p1", MATE)]))
        self.assertEqual([], out["skipped"])
        self.assertEqual(["p1"], out["unprovenIds"])

    def test_created_by_him_is_enough_to_confirm(self):
        out = self._run(_Api([_unowned("p1")], [_made_by("p1", ME)]))
        self.assertEqual(1, out["ownedCount"])
        self.assertEqual([], out["unprovenIds"])

    def test_knowing_nothing_at_all_attempts_rather_than_refuses(self):
        """And the request really carries it.

        "does a share attempt produce an outgoing request, or is it dropped
        by the gate?" - it was dropped, so there was never an API error to
        find. Counting the payload is the only way to tell those apart, and
        asserting the return value alone would not have.
        """
        api = _Api([], [])
        out = _cm(api).bulk_share(["p1"], [GUEST])
        self.assertEqual([], out["skipped"])
        self.assertEqual(["p1"], out["unprovenIds"])
        self.assertEqual([["p1"]], api.shared,
                         "nothing was sent to Ekahau, so Ekahau never had "
                         "the chance to allow it")

    def test_not_knowing_who_we_are_is_not_evidence_about_anyone_else(self):
        """An empty `user_email` once meant every project failed the test,
        because the comparison was against an empty string."""
        out = self._run(_Api([_owned("p1", MATE)], [_made_by("p1", MATE)],
                             me=""))
        self.assertEqual([], out["skipped"])
        self.assertEqual(1, out["ownedCount"])

    def test_an_endpoint_that_answers_a_list_does_not_refuse_everything(self):
        """The share endpoint's shape is asserted by one docstring and
        nothing else, and its siblings return lists. A guess about the shape
        must not read as an answer about ownership."""
        api = _Api(None, None, {"p1": [{"projectId": "p1", "users": []}]})
        out = self._run(api)
        self.assertEqual([], out["skipped"])

    def test_the_error_only_appears_when_every_one_is_someone_elses(self):
        out = self._run(_Api([_owned("p1", MATE), _owned("p2", MATE)],
                             [_made_by("p1", MATE), _made_by("p2", MATE)]),
                        ids=("p1", "p2"))
        self.assertIn("belongs to someone else", out["error"])
        self.assertEqual(2, len(out["skipped"]))


class TheAnswerSaysWhatWasNotConfirmed(unittest.TestCase):
    """Attempted and confirmed are different, and the page says which."""

    def test_unproven_projects_are_counted_separately_from_confirmed_ones(self):
        api = _Api([_owned("p1", ME), _unowned("p2")],
                   [_made_by("p1", ME), _made_by("p2", "")])
        out = _cm(api).bulk_share(["p1", "p2"], [GUEST])
        self.assertEqual(2, out["ownedCount"])
        self.assertEqual(["p2"], out["unprovenIds"])
        self.assertEqual(1, out["unprovenCount"])
        self.assertEqual(["p1", "p2"], api.shared[0],
                         "the unproven one was counted but not sent")


class TheTwoHelpersDoWhatTheyClaim(unittest.TestCase):
    """`owner_in` and `cloud_owner_map` are the whole derivation, so they are
    exercised directly as well as through `bulk_share` - a helper covered
    only by its caller is one refactor away from being covered by nothing."""

    def test_owner_in_finds_the_owner_row_whatever_the_case(self):
        self.assertEqual(ME, cloud_manager.owner_in(
            [{"username": "a@example.invalid", "role": "READ_USER"},
             {"username": ME.upper(), "role": "owner"}]))

    def test_owner_in_answers_empty_rather_than_guessing(self):
        """An unshared project has nobody to name, and that is ordinary."""
        self.assertEqual("", cloud_manager.owner_in([]))
        self.assertEqual("", cloud_manager.owner_in(None))
        self.assertEqual("", cloud_manager.owner_in(
            [{"username": MATE, "role": "WRITE_USER"}]))

    def test_cloud_owner_map_pairs_the_owner_with_the_creator(self):
        api = _Api([_owned("p1", ME), _unowned("p2")],
                   [_made_by("p1", ME), _made_by("p2", MATE)])
        self.assertEqual({"p1": (ME, ME), "p2": ("", MATE)},
                         cloud_manager.cloud_owner_map(api))

    def test_cloud_owner_map_survives_either_listing_being_unavailable(self):
        """Each half is a separate request and either can fail on its own.
        Half an answer is still worth having; an exception is not."""
        self.assertEqual({"p1": ("", ME)},
                         cloud_manager.cloud_owner_map(
                             _Api(None, [_made_by("p1", ME)])))
        self.assertEqual({"p1": (ME, "")},
                         cloud_manager.cloud_owner_map(
                             _Api([_owned("p1", ME)], None)))
        self.assertEqual({}, cloud_manager.cloud_owner_map(_Api(None, None)))


class ThePickerKeepsWhatHeTicked(unittest.TestCase):
    """`refresh_group_shares` carried the same closed gate, on the path that
    takes the projects he ticked in the picker - so a project it could not
    place was removed from a choice he had already made, without saying so."""

    def _api(self):
        api = _Api([_unowned("p1"), _owned("p2", MATE), _unowned("p3")],
                   [_made_by("p1", ME), _made_by("p2", MATE),
                    _made_by("p3", "")])
        api.get_user_group = lambda name: {"groupId": "g1",
                                           "groupName": name,
                                           "members": [{"email": GUEST}]}
        return api

    def _ids(self, out):
        for key in ("projectIds", "projects", "wouldRefresh", "ids"):
            if key in out:
                v = out[key]
                return [p.get("id", p) if isinstance(p, dict) else p
                        for p in (v or [])]
        raise AssertionError("no project list in the answer: %r" % (out,))

    def test_an_unshared_project_survives_the_picker(self):
        out = _cm(self._api()).refresh_group_shares(
            project_ids=["p1", "p2", "p3"], dry_run=True)
        self.assertNotIn("error", out, out.get("error", ""))
        ids = self._ids(out)
        self.assertIn("p1", ids, "a project he ticked was dropped in silence")
        self.assertIn("p3", ids, "an unplaceable project was dropped too")
        self.assertNotIn("p2", ids, "a colleague's project was not refused")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
