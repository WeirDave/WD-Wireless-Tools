"""Refreshing the sharing group keeps each project's role, and a half-done
refresh says which projects lost the group.

`refresh_group_shares` pushes the group's current members by switching the
group off and back on. It read the role off the **first** project and applied
it to every one, so a refresh across a read-only and a writable project gave
one of them the other's access. And when the ON call failed after the OFF had
gone through, the group was gone from every project and all he saw was the raw
error. `bulk_share` has the same off-then-on, and the same silence.

Run against a stub of Ekahau's share surface; every name and address is
invented.
"""
from __future__ import annotations

import unittest

from tools import cloud_manager as cm

ME = "lead@example.invalid"
MATE = "mate@example.invalid"
GROUP_ID = "grp-1"
ROLES = {"proj-read": "READ_USER", "proj-write": "WRITE_USER",
         "proj-write-2": "WRITE_USER"}
NAMES = {"proj-read": "Hazel Annex", "proj-write": "Juniper Wing",
         "proj-write-2": "Linden Hall"}


class _R:
    status_code = 200


class _Api:
    user_email = ME

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on  # None, "off" or "on"

    def get_user_group(self, name):
        return {"groupId": GROUP_ID, "groupName": "My Sharing Group",
                "members": [{"email": MATE}]}

    def get_projects(self):
        return [{"id": pid, "name": NAMES[pid],
                 "history": {"createdBy": ME}} for pid in ROLES]

    def get_dataset_listing(self):
        return [{"id": pid, "datasetUsers": [
            {"role": "OWNER", "username": ME},
            {"role": role, "username": MATE}]} for pid, role in ROLES.items()]

    def list_project_shares(self, pid):
        return {pid: [{"role": "OWNER", "username": ME},
                      {"role": ROLES[pid], "username": MATE,
                       "groupId": GROUP_ID}]}

    def bulk_add_shares(self, ids, emails, role):
        return [{"responsePerEmailAddress": {e: "" for e in emails}}]

    def _write(self, method, path, body):
        on = body["projectUserGroupDto"]["toggleGroupShare"]
        self.calls.append((list(body["projectIds"]),
                           body["projectUserGroupDto"]["role"], on))
        if self.fail_on == ("on" if on else "off"):
            raise RuntimeError("429 rate limited")
        return _R()


class _Mgr(cm.CloudManager):
    def __init__(self, api):
        self.api = api
        self.config = {}

    def _ensure(self):
        return True


def _final_role_by_project(calls):
    """Replay the toggles: what group role each project ends up holding."""
    state = {}
    for ids, role, on in calls:
        for pid in ids:
            state[pid] = role if on else None
    return state


class EachProjectKeepsItsRoleTests(unittest.TestCase):

    def _refresh(self, **kw):
        api = _Api(**kw.pop("api_kw", {}))
        return _Mgr(api).refresh_group_shares(**kw), api

    def test_discovered_projects_end_at_the_role_they_had(self):
        out, api = self._refresh()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(ROLES, _final_role_by_project(api.calls))

    def test_picked_projects_end_at_the_role_they_had(self):
        out, api = self._refresh(project_ids=["proj-write", "proj-read"])
        self.assertTrue(out.get("ok"), out)
        self.assertEqual({"proj-write": "WRITE_USER", "proj-read": "READ_USER"},
                         _final_role_by_project(api.calls))
        self.assertEqual(2, out.get("count"))

    def test_a_failed_re_enable_names_every_project_left_without_the_group(self):
        out, api = self._refresh(project_ids=["proj-read"],
                                 api_kw={"fail_on": "on"})
        self.assertFalse(out.get("ok"))
        err = out.get("error") or ""
        self.assertIn("Hazel Annex", err)
        self.assertIn("no group share", err)
        self.assertIn("429 rate limited", err)
        self.assertEqual(["proj-read"], out.get("unsharedIds"))


class BulkShareSaysWhatTheGroupLostTests(unittest.TestCase):

    def test_a_failed_re_enable_names_the_projects(self):
        api = _Api(fail_on="on")
        out = _Mgr(api).bulk_share(["proj-read", "proj-write"], [],
                                   share_with_group=True, group_id=GROUP_ID,
                                   group_role="READ_USER")
        err = out.get("error") or ""
        self.assertIn("Hazel Annex", err)
        self.assertIn("Juniper Wing", err)
        self.assertIn("no group share", err)
        self.assertEqual(["proj-read", "proj-write"],
                         out.get("groupUnsharedIds"))

    def test_a_failed_off_says_nothing_about_losing_the_group(self):
        """OFF refused means nothing changed; claiming a loss would be false."""
        api = _Api(fail_on="off")
        out = _Mgr(api).bulk_share(["proj-read"], [], share_with_group=True,
                                   group_id=GROUP_ID)
        self.assertNotIn("no group share", out.get("error") or "")
        self.assertIsNone(out.get("groupUnsharedIds"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
