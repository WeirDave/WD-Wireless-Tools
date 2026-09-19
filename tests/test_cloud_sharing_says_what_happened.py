"""Sharing reports what Ekahau actually did, including when it does not know.

Four ways this said a share had landed when it had not.

**The verdict came from nine English words.** `_share_message_is_failure`
searched the per-address message for "not found", "invalid", "error" and six
others, and treated everything else as success. So "Access is forbidden", "No
such user", "403 Forbidden" and "Share limit reached" were all reported as
shared - and the address was then written into Recent Recipients, which is the
one thing that store exists to avoid. It was wrong the other way too: Ekahau's
external-invite success, "User not found - invitation sent", was reported as a
failure because it contains "not found".

Guessing in either direction is the problem. A message nobody recognises is
**unknown**, and unknown is reported as unknown, with Ekahau's own words
carried through, rather than being rounded to whichever answer is convenient.

**Bulk share always said yes.** It caught every exception into `emailError`
and then set `ok: True` regardless, with no `error` key - and the page only
tests `error`. A rate-limited or rejected bulk share toasted "Shared with A and
B on 8 projects", naming everyone, having shared with nobody.

**Changing a role could remove someone silently.** It is remove-then-add. The
remove was checked and the add was not, so a rejected re-add left the
colleague with no access at all, reported as their new role.

**A completed ownership transfer was reported as failed.** Ekahau answers with
an empty body, `.get(project_id)` on it returned `None`, and the transfer - a
thing this tool cannot undo - was announced as a failure. Every other write
helper in the file already has the empty-body fallback.

Every address, project and site here is invented.
"""
from __future__ import annotations

import unittest

from tools import cloud_manager as cm


ME = "me@example.invalid"
NEW_OWNER = "newowner@example.invalid"
COLLEAGUE = "colleague@example.invalid"


class _Api:
    """Ekahau's share surface, in the shapes `cloud_manager` actually reads.

    `list_project_shares` answers a dict keyed by project id, with `username`
    and `role` on each entry; the add and remove calls answer a list whose
    first entry carries `responsePerEmailAddress`. Copying those exactly is
    the point - a stub that invents the contract tests the stub.
    """

    def __init__(self, *, per_email=None, add_raises=False,
                 remove_raises=False, bulk_raises=False,
                 transfer_body=None, transfer_status=200, owner=ME):
        self.per_email = per_email or {}
        self.add_raises = add_raises
        self.remove_raises = remove_raises
        self.bulk_raises = bulk_raises
        self.transfer_body = transfer_body
        self.transfer_status = transfer_status
        self.owner = owner
        self.user_email = ME
        self.removed = []
        self.added = []
        self.bulk_calls = []

    # -- reads ---------------------------------------------------------
    def list_project_shares(self, project_id):
        return {project_id: [{"username": self.owner, "role": "OWNER"},
                             {"username": COLLEAGUE, "role": "READ_USER"}]}

    # -- writes --------------------------------------------------------
    def add_project_share(self, project_id, email, role):
        if self.add_raises:
            raise RuntimeError("Ekahau refused the re-add")
        self.added.append((project_id, email, role))
        return [{"responsePerEmailAddress": dict(self.per_email)}]

    def remove_project_share(self, project_id, email):
        if self.remove_raises:
            raise RuntimeError("remove refused")
        self.removed.append((project_id, email))
        return [{"success": True}]

    def bulk_add_shares(self, project_ids, emails, role):
        self.bulk_calls.append((tuple(project_ids), tuple(emails), role))
        if self.bulk_raises:
            raise RuntimeError("429 Too Many Requests")
        return [{"responsePerEmailAddress": dict(self.per_email)}]

    def transfer_ownership(self, project_id, current_owner, new_owner):
        return {"status": self.transfer_status, "result": self.transfer_body}


class _Mgr(cm.CloudManager):
    def __init__(self, api):
        self.api = api
        self.config = {"output_dir": ""}

    def _ensure(self):
        return True


def _remember_nothing(monkey):
    """Recent Recipients is real colleagues' addresses. Never touched here."""
    return monkey


class TheVerdictIsNotGuessedFromNineWords(unittest.TestCase):

    def test_a_message_nobody_recognises_is_not_called_success(self):
        for msg in ("Access is forbidden", "No such user", "403 Forbidden",
                    "Share limit reached",
                    "User is not a member of your organization"):
            with self.subTest(msg=msg):
                self.assertEqual("unknown", cm.share_message_verdict(msg), msg)

    def test_a_plain_failure_is_still_a_failure(self):
        for msg in ("Email address is invalid",
                    "Could not share with that address",
                    "Access denied"):
            with self.subTest(msg=msg):
                self.assertEqual("failed", cm.share_message_verdict(msg), msg)

    def test_an_empty_message_is_the_quiet_success(self):
        for msg in ("", None):
            with self.subTest(msg=msg):
                self.assertEqual("ok", cm.share_message_verdict(msg))

    def test_the_external_invite_is_a_success_not_a_failure(self):
        """Ekahau's own wording for inviting somebody outside the account. It
        contains "not found", which is why it used to be reported as failed."""
        self.assertEqual("ok",
                         cm.share_message_verdict("User not found - invitation sent"))
        self.assertEqual("ok",
                         cm.share_message_verdict("Added (external users cannot edit)"))

    def test_something_that_is_not_a_string_is_unknown(self):
        self.assertEqual("unknown", cm.share_message_verdict({"code": "USER_NOT_FOUND"}))


class AnUnknownAnswerIsCarriedThroughToHim(unittest.TestCase):

    def setUp(self):
        self.remembered = []
        self._real = cm.share_recipients.remember
        cm.share_recipients.remember = lambda emails: self.remembered.extend(emails)
        self.addCleanup(setattr, cm.share_recipients, "remember", self._real)

    def test_an_unknown_reply_is_not_reported_as_shared(self):
        api = _Api(per_email={COLLEAGUE: "Access is forbidden"})
        out = _Mgr(api).add_shares("p1", [COLLEAGUE], "READ_USER")

        row = out["results"][0]
        self.assertFalse(row["ok"], out)
        self.assertEqual("unknown", row.get("verdict"), out)
        self.assertIn("forbidden", row["message"].lower())
        self.assertEqual([], out["shared"], out)

    def test_an_unknown_reply_is_not_remembered_as_a_recipient(self):
        api = _Api(per_email={COLLEAGUE: "No such user"})
        _Mgr(api).add_shares("p1", [COLLEAGUE], "READ_USER")
        self.assertEqual([], self.remembered,
                         "an address Ekahau would not confirm was remembered")

    def test_a_real_success_still_shares_and_is_remembered(self):
        api = _Api(per_email={})
        out = _Mgr(api).add_shares("p1", [COLLEAGUE], "READ_USER")
        self.assertTrue(out["ok"], out)
        self.assertEqual([COLLEAGUE], out["shared"])
        self.assertEqual([COLLEAGUE], self.remembered)


class BulkShareDoesNotClaimWhatItDidNotDo(unittest.TestCase):

    def setUp(self):
        self._real = cm.share_recipients.remember
        cm.share_recipients.remember = lambda emails: None
        self.addCleanup(setattr, cm.share_recipients, "remember", self._real)

    def test_a_refused_bulk_share_is_reported_as_an_error(self):
        api = _Api(bulk_raises=True)
        out = _Mgr(api).bulk_share(["p1", "p2"], [COLLEAGUE],
                                   "READ_USER", False, None, "", "READ_USER")
        self.assertTrue(out.get("error"),
                        "a bulk share that shared with nobody reported success: "
                        + repr(out))
        self.assertIn("429", str(out.get("error")))

    def test_a_successful_bulk_share_still_reports_success(self):
        api = _Api()
        out = _Mgr(api).bulk_share(["p1", "p2"], [COLLEAGUE],
                                   "READ_USER", False, None, "", "READ_USER")
        self.assertTrue(out.get("ok"), out)
        self.assertFalse(out.get("error"), out)
        self.assertEqual(1, len(api.bulk_calls))


class ChangingARoleNeverLosesSomebodyQuietly(unittest.TestCase):

    def test_a_failed_re_add_says_they_now_have_no_access(self):
        """Remove-then-add. If the add is refused, the colleague is gone -
        and the old code returned the new role as though it had worked."""
        api = _Api(add_raises=True)
        out = _Mgr(api).change_share_role("p1", COLLEAGUE,
                                          "WRITE_USER")

        self.assertTrue(out.get("error"), out)
        msg = str(out.get("error")).lower()
        self.assertIn("no access", msg, out)
        self.assertIn(COLLEAGUE, msg)

    def test_a_working_role_change_is_still_reported_as_done(self):
        api = _Api()
        out = _Mgr(api).change_share_role("p1", COLLEAGUE,
                                          "WRITE_USER")
        self.assertTrue(out.get("ok"), out)
        self.assertFalse(out.get("error"), out)


class AnOwnershipTransferIsReportedAsWhatItWas(unittest.TestCase):

    def test_an_empty_body_on_success_is_not_a_failure(self):
        """Ekahau answers this one with no body. Every other write helper in
        the file already allows for that; this one did not, and announced a
        transfer this tool cannot undo as having failed."""
        api = _Api(transfer_body={}, transfer_status=200)
        out = _Mgr(api).transfer_ownership("p1", NEW_OWNER)
        self.assertTrue(out.get("ok"), out)
        self.assertFalse(out.get("error"), out)

    def test_an_explicit_success_is_a_success(self):
        api = _Api(transfer_body={"p1": "SUCCESS"})
        out = _Mgr(api).transfer_ownership("p1", NEW_OWNER)
        self.assertTrue(out.get("ok"), out)

    def test_an_explicit_refusal_is_still_a_failure(self):
        api = _Api(transfer_body={"p1": "DENIED"}, transfer_status=200)
        out = _Mgr(api).transfer_ownership("p1", NEW_OWNER)
        self.assertTrue(out.get("error"), out)

    def test_a_non_2xx_status_is_a_failure_whatever_the_body(self):
        api = _Api(transfer_body={}, transfer_status=403)
        out = _Mgr(api).transfer_ownership("p1", NEW_OWNER)
        self.assertTrue(out.get("error"), out)

    def test_a_list_body_does_not_crash_into_an_attribute_error(self):
        api = _Api(transfer_body=[], transfer_status=200)
        out = _Mgr(api).transfer_ownership("p1", NEW_OWNER)
        self.assertNotIn("attribute", str(out.get("error", "")).lower(), out)


if __name__ == "__main__":
    unittest.main()
