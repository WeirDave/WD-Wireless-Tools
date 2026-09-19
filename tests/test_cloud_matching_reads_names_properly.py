"""What the matcher reads out of a project name, and what it does with it.

Seven findings from the audit, all in the engine that decides which local .esx
belongs to which cloud project. None of them is loud - a wrong pair looks like
a pair - which is why they are measured here rather than read.

* **Three-digit building numbers.** The regex capped the number at two digits
  and then backtracked into the `bld` alternative, capturing the **g** of
  "Bldg". So `Bldg 100` and `Bldg 200` both read as building "G", the guard
  saw no conflict, and two different buildings at one address auto-paired -
  which is the exact case the guard exists for. `Bldg 3` vs `Bldg 5` still
  worked, which is why it looked fine.

* **Years read as street numbers.** The first run of 3-6 digits was taken as a
  street number, so "Survey 2025" and "Survey 2026" were held back with
  "Street numbers don't match" - a refusal on a pair of ordinary survey names.

* **The site-code pass had no similarity floor.** The fuzzy pass wants more
  than 0.5; the code pass wanted only equal site codes, and the badge says
  "the site codes match and the names are close" while nothing checked the
  second half. Those pairs carry `namesDiffer`, so Sync offered to rename one
  to the other.

* **Pairing depended on Ekahau's listing order.** Each cloud project took its
  own best local file as it was reached, so a weaker claimant listed first won
  a file a later one matched far better - and the order is whatever the
  listing returns, which moves when any project is saved.

* **`exact` was case-sensitive** despite the docstring promising "case +
  whitespace normalized", so a pair differing only in capitals was demoted to
  `fuzzy` - which is excluded from pushing and pulling, so Local -> Cloud was
  greyed out for names that read the same word for word.

* **A stale not-a-match outlived the file it was about.** The entry is keyed
  on cloud id and local path, and nothing prunes it - so deleting a local file
  and downloading the cloud project into the same folder produced a pair
  carrying Ekahau's own project id on both sides that still refused to pair,
  with nothing on screen explaining why.

* **The `.esx` metadata cache could not see a same-second rewrite.** Keyed on
  path and whole-second mtime, so a file rewritten within the same second - or
  arriving from a sync client that preserves the timestamp - served the
  previous project id, name and date.

Every project, site and address here is invented.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
import unittest
import zipfile

from tools import cloud_manager as cm


def cloud(pid, name, **kw):
    return dict(id=pid, name=name, mtime=200, **kw)


def local(name, path=None, **kw):
    return dict(name=name, path=path or ("D:/Ekahau Projects/" + name + ".esx"),
                mtime=200, **kw)


class WhatItReadsOutOfAName(unittest.TestCase):

    def test_a_building_number_of_any_length_is_read_as_the_number(self):
        for name, want in [("Bldg 3", "3"), ("Bldg B", "B"),
                           ("Building 12", "12"), ("Bldg 99", "99"),
                           ("Bldg 100", "100"), ("BLDG 123", "123"),
                           ("bldg. 250", "250"), ("Building 100", "100")]:
            with self.subTest(name=name):
                self.assertEqual(want, cm._building_token(name))

    def test_two_different_buildings_at_one_address_are_held_apart(self):
        """The case the guard was written for, at three digits."""
        why = cm.discriminators_reason("SITE1 1200 Main St Bldg 100",
                                       "SITE1 1200 Main St Bldg 200")
        self.assertTrue(why, "two different buildings were not told apart")
        self.assertIn("uilding", why)

    def test_a_year_is_not_a_street_number(self):
        self.assertIsNone(cm._street_number("SITE1 Survey 2025"))
        self.assertIsNone(cm._street_number("SITE1 Survey 2026"))

    def test_two_surveys_a_year_apart_are_not_refused_over_it(self):
        why = cm.discriminators_reason("SITE1 Survey 2025", "SITE1 Survey 2026")
        self.assertNotIn("Street", str(why or ""),
                         "a year was reported as a street number")

    def test_a_real_street_number_still_counts(self):
        self.assertEqual("1200", cm._street_number("SITE1 1200 Main St"))
        why = cm.discriminators_reason("SITE1 1200 Main St", "SITE1 1400 Main St")
        self.assertIn("Street", str(why or ""))


class ASharedSiteCodeIsNotEnoughOnItsOwn(unittest.TestCase):

    def test_names_with_nothing_in_common_are_not_paired_on_the_code(self):
        a, b = "SITE2 Rooftop Antenna Replacement", "SITE2 Basement Parking Garage"
        self.assertLess(cm.fuzzy_similarity(a, b), 0.2, "fixture is not far enough apart")
        out = cm.build_matches([cloud("c1", a)], [local(b)])
        self.assertEqual([], out["matched"],
                         "two unrelated projects were paired on the site code alone")

    def test_they_are_held_back_with_a_reason_rather_than_dropped(self):
        a, b = "SITE2 Rooftop Antenna Replacement", "SITE2 Basement Parking Garage"
        out = cm.build_matches([cloud("c1", a)], [local(b)])
        held = out.get("heldBack") or []
        self.assertTrue(held, "the pair vanished instead of being offered")
        self.assertTrue(str(held[0].get("reason") or "").strip())

    def test_a_shared_code_with_close_names_still_pairs(self):
        """Refusing is only correct if it refuses the right thing."""
        out = cm.build_matches([cloud("c1", "SITE2 Riverside Baseline")],
                               [local("SITE2 Riverside Baseline Survey")])
        self.assertTrue(out["matched"], "a genuine site-code pair was refused")


class TheAnswerDoesNotDependOnEkahausListingOrder(unittest.TestCase):

    A = "Harbour Point Site Survey Old Archive"
    B = "Harbour Point Site Survey B"
    L = "Harbour Point Site Survey"

    def _paired(self, order):
        out = cm.build_matches([cloud("c" + n[:2], n) for n in order],
                               [local(self.L)])
        return [p["cloud"]["name"] for p in out["matched"]]

    def test_the_better_match_wins_whichever_is_listed_first(self):
        first = self._paired([self.A, self.B])
        second = self._paired([self.B, self.A])
        self.assertEqual(first, second,
                         "the pairing changed when the listing order did")
        self.assertEqual([self.B], first,
                         "the weaker claimant took the file")


class AnExactNameIsExactAfterCaseAndSpacing(unittest.TestCase):

    def test_capitals_alone_do_not_demote_the_match(self):
        out = cm.build_matches([cloud("c1", "SITE1 Riverside")],
                               [local("site1 riverside")])
        self.assertTrue(out["matched"])
        self.assertEqual("exact", out["matched"][0]["matchType"])

    def test_a_double_space_alone_does_not_demote_the_match(self):
        out = cm.build_matches([cloud("c1", "SITE1 Riverside")],
                               [local("SITE1  Riverside")])
        self.assertTrue(out["matched"])
        self.assertEqual("exact", out["matched"][0]["matchType"])

    def test_the_difference_is_still_reported_so_a_rename_is_offered(self):
        out = cm.build_matches([cloud("c1", "SITE1 Riverside")],
                               [local("site1 riverside")])
        self.assertTrue(out["matched"][0]["namesDiffer"],
                        "the names really are spelled differently")

    def test_genuinely_different_names_are_not_called_exact(self):
        out = cm.build_matches([cloud("c1", "SITE1 Riverside")],
                               [local("SITE1 Westgate")])
        got = out["matched"][0]["matchType"] if out["matched"] else None
        self.assertNotEqual("exact", got)


class EkahausOwnIdOutranksAStaleNotAMatch(unittest.TestCase):

    def test_a_pair_sharing_the_project_id_pairs_despite_the_entry(self):
        """The entry is keyed on cloud id and local path and nothing prunes it.
        Delete the local file, download the cloud project into the same folder,
        and the new file carries Ekahau's own id - which is proof of identity,
        not a heuristic."""
        excluded = {cm._nm_pair_key("cid-1", "D:/Ekahau Projects/Riverside.esx")}
        out = cm.build_matches(
            [cloud("cid-1", "Riverside Phase 2", projectId="cid-1")],
            [local("Riverside", projectId="cid-1")],
            excluded=excluded)
        self.assertTrue(out["matched"],
                        "a pair sharing Ekahau's project id refused to pair")
        self.assertEqual("id", out["matched"][0]["matchType"])

    def test_a_not_a_match_still_holds_where_there_is_no_id(self):
        """It is his statement about two files, and without the id there is
        nothing stronger to overrule it."""
        excluded = {cm._nm_pair_key("cid-1", "D:/Ekahau Projects/Riverside.esx")}
        out = cm.build_matches([cloud("cid-1", "Riverside")],
                               [local("Riverside")], excluded=excluded)
        self.assertEqual([], out["matched"])


class TheMetadataCacheNoticesARewrite(unittest.TestCase):

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.esx = self.dir / "Survey.esx"

    def _write(self, name, pid, pad=b""):
        with zipfile.ZipFile(self.esx, "w") as z:
            z.writestr("project.json", json.dumps(
                {"project": {"id": pid, "name": name,
                             "history": {"modifiedAt": "2026-09-19T00:00:00Z"}}}))
            if pad:
                z.writestr("pad.bin", pad)

    def test_a_rewrite_with_the_same_timestamp_is_not_served_from_cache(self):
        """A sync client that preserves the original timestamp is the ordinary
        way this happens, and the stale answer is a project id."""
        self._write("Old Name", "id-old")
        mt = int(self.esx.stat().st_mtime)
        self.assertEqual("Old Name", cm._esx_meta(self.esx, mt).get("projectName"))

        self._write("New Name", "id-new", pad=b"x" * 64)
        os.utime(self.esx, (mt, mt))
        got = cm._esx_meta(self.esx, int(self.esx.stat().st_mtime))
        self.assertEqual("New Name", got.get("projectName"))
        self.assertEqual("id-new", got.get("projectId"))


if __name__ == "__main__":
    unittest.main()
