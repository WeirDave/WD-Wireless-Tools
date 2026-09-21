"""The two pairing decisions he makes by hand, and the stores behind them.

Cloud Manager pairs a cloud project with a local `.esx` by guessing from names
and ids. Two controls let him overrule that guess, and both are *persistent*:

* **"Confirm this pair"** writes a manual match. It promotes a guessed pairing
  to one he made himself, which is what unlocks the actions that overwrite a
  file - so a bug here is a bug about which file gets replaced.
* **"Not a match"** writes a not-match, so two things that look alike are never
  paired again.

Six of the server actions behind them - `mark_manual_match`,
`unmark_manual_match`, `list_manual_matches`, `mark_not_match`,
`unmark_not_match`, `list_not_matches` - were named in no test file at all.
That is backlog item 4, and it is the last of the Cloud Manager audit.

**They are reads and bookkeeping, which is why this was P3** - none of them can
lose a project. What they can do is make the ledger pair the wrong two things,
quietly and permanently, and the failure looks like the matcher being wrong
rather than like a stored decision being wrong.

The key deserves the most attention. A pair is filed under cloud id and local
path with the path normalised - backslashes to forward, lower-cased - so the
same file named two ways is one decision. Get that wrong and a decision he made
on Monday stops applying on Tuesday because something handed the path over with
the other slash.

Every project, path and address here is invented.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import cloud_manager as cm

CLOUD_A = "11111111-aaaa-4000-8000-000000000001"
CLOUD_B = "22222222-bbbb-4000-8000-000000000002"
LOCAL_A = r"C:\Projects\SITE1 Riverside\SITE1 - Design.esx"
LOCAL_B = r"C:\Projects\SITE2 Lakeside\SITE2 - Design.esx"


class _Mgr(cm.CloudManager):
    """A manager with the stores reachable and nothing else.

    None of the six touches the network or a project file, which is the point
    of them - so the object is built without ``__init__`` rather than by
    standing up a session.
    """

    def __init__(self):
        self.api = None
        self.config = {}

    def _ensure(self):
        return True


class _StoreCase(unittest.TestCase):
    """Both stores start empty for every test.

    ``WD_USER_DIR`` is set in ``tests/__init__`` before any module that reads
    it is imported, so these files are already inside a scratch directory and
    his real ones are unreachable. Emptying them here is about the test not
    depending on what ran before it.
    """

    def setUp(self):
        self.mgr = _Mgr()
        cm.save_manual_matches([])
        cm.save_not_matches([])
        self.addCleanup(cm.save_manual_matches, [])
        self.addCleanup(cm.save_not_matches, [])


class TheManualMatchIsRememberedTests(_StoreCase):

    def test_a_pair_he_confirms_is_written_and_listed(self):
        r = self.mgr.mark_manual_match(CLOUD_A, LOCAL_A, "Riverside", "SITE1 - Design")
        self.assertTrue(r["ok"], r)
        listed = self.mgr.list_manual_matches()
        self.assertTrue(listed["ok"])
        self.assertEqual([CLOUD_A], [p["cloudId"] for p in listed["pairs"]])
        self.assertEqual([LOCAL_A], [p["localPath"] for p in listed["pairs"]])

    def test_the_names_are_kept_so_the_list_can_be_read(self):
        """A stored decision that shows two opaque ids cannot be reviewed."""
        self.mgr.mark_manual_match(CLOUD_A, LOCAL_A, "Riverside", "SITE1 - Design")
        pair = self.mgr.list_manual_matches()["pairs"][0]
        self.assertEqual("Riverside", pair["cloudName"])
        self.assertEqual("SITE1 - Design", pair["localName"])

    def test_it_survives_being_read_back_from_disk(self):
        self.mgr.mark_manual_match(CLOUD_A, LOCAL_A)
        self.assertTrue(cm.MANUAL_MATCH_FILE.exists())
        self.assertEqual(1, len(cm.load_manual_matches()))

    def test_confirming_the_same_pair_twice_does_not_duplicate_it(self):
        self.mgr.mark_manual_match(CLOUD_A, LOCAL_A)
        again = self.mgr.mark_manual_match(CLOUD_A, LOCAL_A)
        self.assertTrue(again["already"])
        self.assertEqual(1, len(cm.load_manual_matches()))

    def test_the_same_file_named_two_ways_is_one_decision(self):
        """Backslashes, forward slashes and case all describe one file.

        A decision that stops applying because something handed the path over
        with the other slash reads as the matcher being wrong, not as the store
        being wrong, which is what makes it expensive to find.
        """
        self.mgr.mark_manual_match(CLOUD_A, LOCAL_A)
        again = self.mgr.mark_manual_match(CLOUD_A, LOCAL_A.replace("\\", "/").lower())
        self.assertTrue(again.get("already"), again)
        self.assertEqual(1, len(cm.load_manual_matches()))

    def test_unconfirming_removes_only_that_pair(self):
        self.mgr.mark_manual_match(CLOUD_A, LOCAL_A)
        self.mgr.mark_manual_match(CLOUD_B, LOCAL_B)
        r = self.mgr.unmark_manual_match(CLOUD_A, LOCAL_A)
        self.assertTrue(r["ok"])
        self.assertEqual(1, r["removed"])
        self.assertEqual([CLOUD_B],
                         [p["cloudId"] for p in cm.load_manual_matches()])

    def test_unconfirming_matches_however_the_path_is_written(self):
        self.mgr.mark_manual_match(CLOUD_A, LOCAL_A)
        r = self.mgr.unmark_manual_match(CLOUD_A, LOCAL_A.replace("\\", "/").upper())
        self.assertEqual(1, r["removed"])
        self.assertEqual([], cm.load_manual_matches())

    def test_unconfirming_something_that_was_never_confirmed_is_not_an_error(self):
        r = self.mgr.unmark_manual_match(CLOUD_A, LOCAL_A)
        self.assertTrue(r["ok"])
        self.assertEqual(0, r["removed"])

    def test_both_halves_are_required(self):
        """Half a pair would file a decision under a key nothing can match."""
        for cid, path in ((None, LOCAL_A), (CLOUD_A, ""), ("", "")):
            with self.subTest(cloudId=cid, localPath=path):
                self.assertIn("error", self.mgr.mark_manual_match(cid, path))
                self.assertIn("error", self.mgr.unmark_manual_match(cid, path))
        self.assertEqual([], cm.load_manual_matches())

    def test_the_list_says_where_the_file_is(self):
        """It is his data; being able to find the file is part of owning it."""
        listed = self.mgr.list_manual_matches()
        self.assertEqual(str(cm.MANUAL_MATCH_FILE), listed["file"])

    def test_a_corrupt_store_reads_as_empty_rather_than_raising(self):
        cm.MANUAL_MATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
        cm.MANUAL_MATCH_FILE.write_text("{ not json", encoding="utf-8")
        self.assertEqual([], cm.load_manual_matches())
        self.assertTrue(self.mgr.list_manual_matches()["ok"])

    def test_a_half_written_entry_is_dropped_on_read(self):
        cm.MANUAL_MATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
        cm.MANUAL_MATCH_FILE.write_text(json.dumps({"pairs": [
            {"cloudId": CLOUD_A, "localPath": LOCAL_A},
            {"cloudId": CLOUD_B},
            {"localPath": LOCAL_B},
        ]}), encoding="utf-8")
        self.assertEqual([CLOUD_A], [p["cloudId"] for p in cm.load_manual_matches()])


class TheNotAMatchIsRememberedTests(_StoreCase):

    def test_a_refused_pair_is_written_and_listed(self):
        r = self.mgr.mark_not_match(CLOUD_A, LOCAL_A, "Riverside", "SITE1 - Design")
        self.assertTrue(r["ok"], r)
        listed = self.mgr.list_not_matches()
        self.assertEqual([CLOUD_A], [p["cloudId"] for p in listed["pairs"]])

    def test_refusing_the_same_pair_twice_does_not_duplicate_it(self):
        self.mgr.mark_not_match(CLOUD_A, LOCAL_A)
        again = self.mgr.mark_not_match(CLOUD_A, LOCAL_A)
        self.assertTrue(again["already"])
        self.assertEqual(1, len(cm.load_not_matches()))

    def test_the_same_file_named_two_ways_is_one_refusal(self):
        self.mgr.mark_not_match(CLOUD_A, LOCAL_A)
        again = self.mgr.mark_not_match(CLOUD_A, LOCAL_A.replace("\\", "/").lower())
        self.assertTrue(again.get("already"), again)
        self.assertEqual(1, len(cm.load_not_matches()))

    def test_taking_a_refusal_back_removes_only_that_pair(self):
        self.mgr.mark_not_match(CLOUD_A, LOCAL_A)
        self.mgr.mark_not_match(CLOUD_B, LOCAL_B)
        r = self.mgr.unmark_not_match(CLOUD_A, LOCAL_A)
        self.assertEqual(1, r["removed"])
        self.assertEqual([CLOUD_B], [p["cloudId"] for p in cm.load_not_matches()])

    def test_both_halves_are_required(self):
        for cid, path in ((None, LOCAL_A), (CLOUD_A, ""), ("", "")):
            with self.subTest(cloudId=cid, localPath=path):
                self.assertIn("error", self.mgr.mark_not_match(cid, path))
        self.assertEqual([], cm.load_not_matches())

    def test_the_set_the_matcher_reads_is_keyed_the_same_way(self):
        """`not_matches_set` is what the ledger consults while pairing.

        If it keyed differently from the writer, a refusal would be stored and
        then never consulted - which looks exactly like the control doing
        nothing.
        """
        self.mgr.mark_not_match(CLOUD_A, LOCAL_A)
        s = cm.not_matches_set()
        self.assertIn(cm._nm_pair_key(CLOUD_A, LOCAL_A), s)
        self.assertIn(cm._nm_pair_key(CLOUD_A, LOCAL_A.replace("\\", "/")), s)


class ConfirmingAPairCancelsARefusalTests(_StoreCase):
    """The two stores are opposites, so holding both for one pair is a state
    with no meaning - and whichever the matcher read first would decide it.

    `mark_manual_match` prunes the not-match deliberately. Nothing does the
    reverse, and that asymmetry is worth pinning rather than discovering.
    """

    def test_confirming_a_pair_drops_it_from_the_not_matches(self):
        self.mgr.mark_not_match(CLOUD_A, LOCAL_A)
        self.assertEqual(1, len(cm.load_not_matches()))
        self.mgr.mark_manual_match(CLOUD_A, LOCAL_A)
        self.assertEqual([], cm.load_not_matches())
        self.assertEqual(1, len(cm.load_manual_matches()))

    def test_it_drops_the_refusal_however_the_path_was_written(self):
        self.mgr.mark_not_match(CLOUD_A, LOCAL_A)
        self.mgr.mark_manual_match(CLOUD_A, LOCAL_A.replace("\\", "/").lower())
        self.assertEqual([], cm.load_not_matches())

    def test_confirming_one_pair_leaves_another_refusal_alone(self):
        self.mgr.mark_not_match(CLOUD_A, LOCAL_A)
        self.mgr.mark_not_match(CLOUD_B, LOCAL_B)
        self.mgr.mark_manual_match(CLOUD_A, LOCAL_A)
        self.assertEqual([CLOUD_B], [p["cloudId"] for p in cm.load_not_matches()])

    def test_refusing_a_pair_does_not_drop_a_manual_match(self):
        """The asymmetry, asserted so a later change has to mean it.

        If this ever becomes symmetric it should be because somebody decided
        that, not because the two happened to be written the same way.
        """
        self.mgr.mark_manual_match(CLOUD_A, LOCAL_A)
        self.mgr.mark_not_match(CLOUD_A, LOCAL_A)
        self.assertEqual(1, len(cm.load_manual_matches()))
        self.assertEqual(1, len(cm.load_not_matches()))


class TheRouteTableCarriesThePairInOrderTests(unittest.TestCase):
    """`CLOUD_ACTIONS` is a dict literal nobody executes.

    The method can be right and unreachable, and a lambda reading the wrong key
    hands it `None` - invisible to any test of the method itself. The argument
    *order* matters here for the same reason it does on a delete: these two
    identify which two things get paired.
    """

    ACTIONS = ("mark_manual_match", "unmark_manual_match", "list_manual_matches",
               "mark_not_match", "unmark_not_match", "list_not_matches")

    def test_every_one_of_them_is_routed(self):
        import server
        for action in self.ACTIONS:
            with self.subTest(action=action):
                self.assertIn(action, server.CLOUD_ACTIONS)

    def test_each_route_hands_over_what_the_page_sends(self):
        import server
        seen = {}

        class FakeCm:
            def mark_manual_match(self, cloud_id, local_path, cloud_name="", local_name=""):
                seen["mark"] = (cloud_id, local_path, cloud_name, local_name)
                return {"ok": True}

            def unmark_manual_match(self, cloud_id, local_path):
                seen["unmark"] = (cloud_id, local_path)
                return {"ok": True}

            def list_manual_matches(self):
                seen["list"] = True
                return {"ok": True}

            def mark_not_match(self, cloud_id, local_path, cloud_name="", local_name=""):
                seen["nm"] = (cloud_id, local_path, cloud_name, local_name)
                return {"ok": True}

            def unmark_not_match(self, cloud_id, local_path):
                seen["unnm"] = (cloud_id, local_path)
                return {"ok": True}

            def list_not_matches(self):
                seen["listnm"] = True
                return {"ok": True}

        body = {"cloudId": CLOUD_A, "localPath": LOCAL_A,
                "cloudName": "Riverside", "localName": "SITE1 - Design"}
        real = server.cm
        server.cm = FakeCm()
        try:
            for action in self.ACTIONS:
                server.CLOUD_ACTIONS[action](dict(body))
        finally:
            server.cm = real

        self.assertEqual((CLOUD_A, LOCAL_A, "Riverside", "SITE1 - Design"), seen["mark"])
        self.assertEqual((CLOUD_A, LOCAL_A), seen["unmark"])
        self.assertEqual((CLOUD_A, LOCAL_A, "Riverside", "SITE1 - Design"), seen["nm"])
        self.assertEqual((CLOUD_A, LOCAL_A), seen["unnm"])
        self.assertTrue(seen["list"])
        self.assertTrue(seen["listnm"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
