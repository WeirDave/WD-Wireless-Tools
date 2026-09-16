"""Sharing with several people, and not retyping their addresses every time.

Both of these came from the same complaint: he was typing colleagues'
addresses from memory, one at a time, every time he shared a project.

**Every address in this file is invented**, at an RFC 2606 documentation
domain. The real list lives only on his machine, in the user data directory,
and nothing from it is ever copied into this repository - not into a fixture,
not into a screenshot, not to reproduce a bug. See `tools/share_recipients.py`.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import cloud_manager as cm
from tools import share_recipients as sr


class _Isolated(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        patcher = patch.object(sr, "user_dir", lambda: self.home)
        patcher.start()
        self.addCleanup(patcher.stop)


# ------------------------------------------------------------- parsing ----

class SeveralAddressesInOneFieldTests(unittest.TestCase):
    """"how come I can't add more than one with a comma or semicolon" """

    def test_commas_semicolons_spaces_and_newlines_all_work(self):
        for text in (
            "one@example.com,two@example.org",
            "one@example.com; two@example.org",
            "one@example.com two@example.org",
            "one@example.com\ntwo@example.org",
            "one@example.com;,  \n two@example.org",
        ):
            with self.subTest(text=text):
                self.assertEqual(["one@example.com", "two@example.org"],
                                 sr.split_addresses(text))

    def test_a_pasted_mail_client_list_keeps_only_the_addresses(self):
        """Pasting out of an email client is a normal thing to do."""
        pasted = "Ada Example <ada@example.com>; Bo Sample <bo@example.net>"
        self.assertEqual(["ada@example.com", "bo@example.net"],
                         sr.split_addresses(pasted))

    def test_order_is_kept_and_duplicates_are_not(self):
        self.assertEqual(
            ["a@example.com", "b@example.com"],
            sr.split_addresses("a@example.com, b@example.com, A@example.com"))

    def test_one_bad_entry_does_not_discard_the_good_ones(self):
        """The whole reason both halves are returned.

        Refusing the field because the fifth address is malformed throws away
        four correct ones and makes him retype all five.
        """
        out = sr.classify("good@example.com, notanemail, also@example.org")
        self.assertEqual(["good@example.com", "also@example.org"], out["valid"])
        self.assertEqual(["notanemail"], out["invalid"])

    def test_nothing_at_all_is_not_an_error(self):
        self.assertEqual([], sr.split_addresses(""))
        self.assertEqual([], sr.split_addresses(None))


# --------------------------------------------------------------- store ----

class RememberingWhoHeSharedWithTests(_Isolated):
    """"is it possible to remember who you shared with" """

    def test_it_starts_empty_and_says_so_rather_than_failing(self):
        self.assertEqual([], sr.recent())

    def test_most_recently_used_comes_first(self):
        sr.remember(["first@example.com"])
        sr.remember(["second@example.org"])
        self.assertEqual(["second@example.org", "first@example.com"],
                         [r["email"] for r in sr.recent()])

    def test_the_order_holds_when_the_clock_cannot_tell_them_apart(self):
        """Windows ticks about every 15ms; two writes share a timestamp.

        This is not a hypothetical - it is what the first version did, and it
        passed here and failed in CI, which is the worst way to find it. The
        clock is for display; the order is a counter, and a counter cannot
        tie.
        """
        with patch.object(sr, "_now", lambda: "2026-09-16T12:00:00.000000+00:00"):
            sr.remember(["first@example.com"])
            sr.remember(["second@example.org"])
            sr.remember(["third@example.net"])
        self.assertEqual(
            ["third@example.net", "second@example.org", "first@example.com"],
            [r["email"] for r in sr.recent()])

    def test_one_batch_keeps_the_order_he_typed_them(self):
        with patch.object(sr, "_now", lambda: "2026-09-16T12:00:00.000000+00:00"):
            sr.remember(["ada@example.com", "bo@example.org", "cy@example.net"])
        self.assertEqual(["ada@example.com", "bo@example.org", "cy@example.net"],
                         [r["email"] for r in sr.recent()])

    def test_sharing_with_someone_again_moves_them_up_and_counts(self):
        sr.remember(["a@example.com"])
        sr.remember(["b@example.org"])
        sr.remember(["a@example.com"])
        top = sr.recent()[0]
        self.assertEqual("a@example.com", top["email"])
        self.assertEqual(2, top["count"])

    def test_an_address_he_removes_stays_removed(self):
        sr.remember(["keep@example.com", "drop@example.org"])
        out = sr.forget("drop@example.org")
        self.assertTrue(out["ok"])
        self.assertTrue(out["removed"])
        self.assertEqual(["keep@example.com"],
                         [r["email"] for r in sr.recent()])

    def test_forgetting_someone_who_was_never_there_is_not_an_error(self):
        out = sr.forget("nobody@example.com")
        self.assertTrue(out["ok"])
        self.assertFalse(out["removed"])

    def test_the_list_is_bounded(self):
        sr.remember([f"person{n}@example.com" for n in range(sr.MAX_REMEMBERED + 25)])
        self.assertLessEqual(len(sr.recent()), sr.MAX_REMEMBERED)

    def test_a_malformed_entry_is_never_remembered(self):
        """Offering a typo back next time is worse than not remembering."""
        sr.remember(["fine@example.com", "not-an-address"])
        self.assertEqual(["fine@example.com"], [r["email"] for r in sr.recent()])

    def test_a_corrupt_file_reads_as_empty_rather_than_raising(self):
        sr.store_path().write_text("{ this is not json", encoding="utf-8")
        self.assertEqual([], sr.recent())
        sr.remember(["after@example.com"])
        self.assertEqual(["after@example.com"], [r["email"] for r in sr.recent()])

    def test_it_is_written_where_the_rest_of_his_settings_live(self):
        sr.remember(["x@example.com"])
        self.assertEqual(self.home, sr.store_path().parent)
        self.assertEqual("share_recipients.json", sr.store_path().name)


# ------------------------------------------------------------- sharing ----

class _StubApi:
    """Records the one call that should be made, and answers like Ekahau."""

    def __init__(self, per_email=None):
        self.calls = []
        self._per_email = per_email or {}

    def bulk_add_shares(self, project_ids, emails, role="READ_USER"):
        self.calls.append({"projectIds": list(project_ids),
                           "emails": list(emails), "role": role})
        return [{"projectId": project_ids[0],
                 "responsePerEmailAddress":
                     {e: self._per_email.get(e, "") for e in emails}}]


class SharingWithSeveralPeopleTests(_Isolated):

    def _manager(self, per_email=None):
        mgr = cm.CloudManager.__new__(cm.CloudManager)
        mgr._ensure = lambda: True
        mgr.api = _StubApi(per_email)
        return mgr

    def test_the_limit_was_never_the_api(self):
        """One request carrying every address, not one request each.

        `emailAddresses` has always been an array on Ekahau's endpoint, so
        there is nothing to loop and nothing to present as atomic that isn't.
        """
        mgr = self._manager()
        mgr.add_shares("proj", ["a@example.com; b@example.org c@example.net"])
        self.assertEqual(1, len(mgr.api.calls))
        self.assertEqual(["a@example.com", "b@example.org", "c@example.net"],
                         mgr.api.calls[0]["emails"])

    def test_each_recipient_is_reported_separately(self):
        mgr = self._manager({"bad@example.org": "User not found"})
        out = mgr.add_shares("proj", ["ok@example.com", "bad@example.org"])
        by_email = {r["email"]: r for r in out["results"]}
        self.assertTrue(by_email["ok@example.com"]["ok"])
        self.assertFalse(by_email["bad@example.org"]["ok"])
        self.assertIn("not found", by_email["bad@example.org"]["message"])

    def test_only_the_ones_that_worked_are_remembered(self):
        mgr = self._manager({"bad@example.org": "User not found"})
        mgr.add_shares("proj", ["ok@example.com", "bad@example.org"])
        self.assertEqual(["ok@example.com"], [r["email"] for r in sr.recent()])

    def test_a_malformed_entry_is_reported_without_blocking_the_rest(self):
        mgr = self._manager()
        out = mgr.add_shares("proj", ["good@example.com", "oops"])
        self.assertEqual(["good@example.com"], mgr.api.calls[0]["emails"])
        self.assertTrue(out["ok"])
        bad = [r for r in out["results"] if not r["ok"]]
        self.assertEqual(["oops"], [r["email"] for r in bad])

    def test_nothing_usable_is_an_error_rather_than_an_empty_request(self):
        mgr = self._manager()
        out = mgr.add_shares("proj", ["nope", "also nope"])
        self.assertIn("error", out)
        self.assertEqual([], mgr.api.calls)

    def test_the_single_recipient_path_still_answers_as_it_did(self):
        """Older callers and the bulk form both still use it."""
        mgr = self._manager()
        out = mgr.add_share("proj", "solo@example.com")
        self.assertTrue(out["ok"])
        self.assertEqual("solo@example.com", out["email"])


# ------------------------------------------------- reachable and private ----

class ItIsReachableFromThePageTests(unittest.TestCase):

    def test_every_action_the_page_calls_exists_on_the_server(self):
        import server
        for action in ("add_shares", "recent_recipients", "forget_recipient"):
            self.assertIn(action, server.CLOUD_ACTIONS, action)

    def test_the_page_offers_the_controls(self):
        root = Path(__file__).resolve().parent.parent
        js = (root / "web" / "assets" / "js" / "cloud.js").read_text(encoding="utf-8")
        html = (root / "web" / "cloud.html").read_text(encoding="utf-8")
        for needle in ("add_shares", "recent_recipients", "forget_recipient",
                       "_shareChipsAdd", "_shareSuggestShow", "_shareForget"):
            self.assertIn(needle, js, needle)
        for needle in ("shareChips", "shareSuggest", "shareRecent"):
            self.assertIn(needle, html, needle)

    def test_it_survives_a_wipe_because_the_export_carries_it(self):
        from tools import settings_backup
        self.assertIn("share_recipients.json", settings_backup.EXPORT_FILES)


class ItNeverLeavesHisMachineTests(unittest.TestCase):
    """This file holds real colleagues' addresses. It is not ours to publish."""

    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent

    def test_the_store_is_gitignored(self):
        body = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("share_recipients.json", body)

    def test_no_recipient_store_is_tracked(self):
        out = subprocess.run(["git", "ls-files"], cwd=str(self.root),
                             capture_output=True, text=True)
        if out.returncode != 0:
            self.skipTest("git unavailable")
        self.assertEqual(
            [], [p for p in out.stdout.split() if p.endswith("share_recipients.json")])

    def test_it_is_not_in_the_release_payload(self):
        from tools import updater
        names = (list(updater.CONFIG.payload_files)
                 + list(updater.CONFIG.payload_dirs))
        self.assertNotIn("share_recipients.json", names)

    def test_nothing_is_sent_anywhere_but_ekahau(self):
        """The remembered list is read locally and posted to no one.

        The only outbound use of an address is the share call itself, which is
        what he asked for. There is no telemetry path to add one to later.
        """
        body = (self.root / "tools" / "share_recipients.py").read_text(encoding="utf-8")
        for forbidden in ("requests.", "urllib", "http://", "https://", "socket"):
            self.assertNotIn(forbidden, body, forbidden)


if __name__ == "__main__":
    unittest.main()
