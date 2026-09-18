"""Which way the data moves, and what to do when it cannot move that way.

Two reports, one root cause: the page knew things it was not saying on screen.

**The arrows.** "I just realized the sync buttons are arrows pointing
backwards... when I hover over it it says 'pull cloud to local'." The arrows
were in fact consistent with the layout - the ledger puts **Cloud on the left
and Local on the right**, so a right arrow really is cloud to local - but the
buttons said only `Sync →`, so the only way to learn the direction was to
hover, immediately before an operation that overwrites a file. The fix is to
say it in words on the control.

**The dead label.** "it says local newer but I can't click it to do anything,
and then I hit the checkbox and I can't sync it either. I thought we fixed
that." Nothing had regressed - pushing a local file up over an existing cloud
project genuinely was not built, because the upload this client has creates a
*second* cloud project instead of replacing the one already there. But the app
expressed that as a status with no adjacent remedy and the explanation buried
in a `title`, which reads exactly like a broken button.

**It is built now.** `replace_cloud_project` composes it - upload, verify the
new copy is really his file, and only then delete the old one - and the row
calls it. The order is the safety: deleting first would turn a failed upload
into a missing shared project, while deleting last turns one into a duplicate
that can be removed.

It is offered only on a *proven* pair, which is narrower than the download.
A pull keeps what it replaced in `backups/`; a push deletes the old cloud
project and cloud deletes do not come back. A name-only match therefore still
gets the shown-and-unavailable treatment, with a reason.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = (ROOT / "web" / "assets" / "js" / "cloud.js").read_text(encoding="utf-8")
CLOUD_HTML = (ROOT / "web" / "cloud.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")


class TheDirectionIsReadableWithoutHoveringTests(unittest.TestCase):

    def _button(self, element_id: str) -> str:
        m = re.search(r'<button[^>]*id="%s".*?</button>' % element_id,
                      CLOUD_HTML, re.S)
        self.assertIsNotNone(m, element_id + " is missing")
        return m.group(0)

    def test_the_columns_are_cloud_left_and_local_right(self):
        """The layout the arrows have to agree with.

        If this ever flips, the labels below become wrong and the tests that
        pin them should fail rather than quietly describing the old order.
        """
        legend = CLOUD_HTML[CLOUD_HTML.index('class="col-legend"'):]
        legend = legend[:legend.index("</div>")]
        self.assertLess(legend.index("legCloud"), legend.index("legLocal"))

    def test_each_bulk_button_names_its_direction_in_words(self):
        pull = self._button("bulkSyncTo")
        push = self._button("bulkSyncFrom")
        self.assertIn("Cloud", pull)
        self.assertIn("Local", pull)
        self.assertIn("Cloud", push)
        self.assertIn("Local", push)

    def test_the_words_match_what_the_button_actually_does(self):
        """The half that a glyph alone cannot get wrong or right."""
        pull = self._button("bulkSyncTo")
        push = self._button("bulkSyncFrom")
        self.assertIn("bulkSync('to-local')", pull)
        self.assertLess(pull.index("Cloud"), pull.index("Local"),
                        "the cloud-to-local button reads local-to-cloud")
        self.assertIn("bulkSync('to-cloud')", push)
        self.assertLess(push.index("Local"), push.index("Cloud"),
                        "the local-to-cloud button reads cloud-to-local")

    def test_a_bare_arrow_is_no_longer_the_whole_label(self):
        for element_id in ("bulkSyncTo", "bulkSyncFrom"):
            with self.subTest(button=element_id):
                label = re.sub(r"<[^>]+>", "", self._button(element_id))
                label = label.replace("&#8594;", "").replace("&#8592;", "").strip()
                self.assertTrue(label, "nothing but an arrow")
                self.assertNotEqual("Sync", label)

    def test_the_row_actions_lead_with_the_direction_too(self):
        """This asserted a *tooltip* inside a class called "readable without
        hovering", which was the one place the direction could not be read
        without hovering. It is the button's own face now:

            [→ Cloud → Local]   [← Local → Cloud]   [≠ Not a match]

        so the assertion moved to the label and the call beside it, which pins
        the pairing a tooltip never could - a label reading one direction over
        a handler doing the other is the defect worth catching.
        """
        band = CLOUD_JS[CLOUD_JS.index("function rowDetailHtml("):]
        band = band[:band.index("\nfunction stalenessBadgeHtml(")]
        to_local = band.index("'Cloud \u2192 Local'")
        to_cloud = band.index("'Local \u2192 Cloud'")
        self.assertIn("syncRow('to-local'", band[to_local:to_local + 400])
        self.assertIn("syncRow('to-cloud'", band[to_cloud:to_cloud + 400])
        self.assertLess(to_local, to_cloud,
                        "the recommended direction is no longer first")

    def test_the_old_vocabulary_is_gone_from_the_tooltips(self):
        """Two names for one direction is how the confusion started."""
        self.assertNotIn("Push local \\u2192 cloud", CLOUD_JS)
        self.assertNotIn("Pull cloud \\u2192 local", CLOUD_JS)


class AnUnavailableActionIsShownRatherThanAbsentTests(unittest.TestCase):

    def setUp(self):
        """The refused action is drawn by a shared helper now.

        `rdUnavailable` and `rdConfirmPair` are used by both staleness
        branches, so they sit above them - and a slice starting at
        `local_newer` cut them off, which made a passing property look like a
        regression. The slice starts at the helpers.
        """
        start = CLOUD_JS.index("function rdUnavailable(")
        self.block = CLOUD_JS[start:CLOUD_JS.index("function gutCell", start)]

    def test_the_row_offers_a_push_control_at_all(self):
        """The whole complaint: a status with nothing beside it to click."""
        self.assertIn("<button", self.block)
        self.assertIn("Local \u2192 Cloud", self.block)

    def test_it_is_marked_unavailable_rather_than_merely_looking_dead(self):
        self.assertIn('aria-disabled="true"', self.block)
        self.assertIn("is-disabled", self.block)

    def test_clicking_it_explains_instead_of_doing_nothing(self):
        """Hover is not where anyone looks before deciding a button is broken."""
        wiring = CLOUD_JS[CLOUD_JS.index("function _wireDisabledBulkReasons"):]
        wiring = wiring[:wiring.index("\n}")]
        self.assertIn("gut-arrow.is-disabled", wiring)
        self.assertIn("toast(", wiring)

    def test_a_proven_pair_gets_a_working_control(self):
        """It is built now, and this is the assertion that says so.

        `replace_cloud_project` shipped in v2.104.6 with its server route and
        nothing calling it, so the row went on saying "not built yet" about
        code that was already there. The button is wired; the claim is gone.
        """
        self.assertIn("canPushToCloud(r)", self.block)
        self.assertIn("pushLocalOverCloud(", self.block)
        self.assertNotIn("not built", self.block)

    def test_the_control_states_the_order_that_makes_it_safe(self):
        """Upload, verify, then delete - never the other way round.

        A delete that runs first turns a failed upload into a missing shared
        project. A delete that runs last turns one into a duplicate, which is
        visible and removable. He has been bitten by duplicates twice, so the
        row says which order it uses rather than leaving him to trust it.
        """
        low = self.block.lower()
        self.assertIn("only then removes the old", low)
        self.assertIn("if the upload fails nothing is deleted", low)

    def test_an_unproven_pair_is_still_shown_and_still_unavailable(self):
        """The original complaint must not come back for the other case.

        Pulling is offered on a name-only match because the replaced local file
        is kept in `backups/`. Replacing the cloud copy deletes the old project
        and a cloud delete does not come back, so a name-only pair gets the
        greyed control and a reason - shown and unavailable, never absent.
        """
        self.assertIn('aria-disabled="true"', self.block)
        self.assertIn("PUSHABLE_MATCH_TYPES", CLOUD_JS)
        low = self.block.lower()
        self.assertIn("cannot be undone", low)
        self.assertIn("link", low)

    def test_the_control_that_lifts_the_refusal_is_beside_it(self):
        """Stronger than the tooltip this replaces, and the fix for a real
        defect: the old message said to "confirm the pair with the Link
        button", and Link is only ever drawn on an *unpaired* row. On a
        guessed pair it named a control that was not on screen anywhere.

        Confirm this pair is rendered in the same band as the refusal, and it
        is the call that promotes a guess to a match he made himself.
        """
        self.assertIn("Confirm this pair", self.block)
        self.assertIn("markManualMatch(", self.block)

    def test_nothing_is_at_risk_is_still_said(self):
        """Sync never replaces a newer file with an older one, and says so."""
        self.assertIn("newer", self.block.lower())

    def test_the_greyed_control_is_styled_as_unavailable(self):
        self.assertIn(".gut-arrow.is-disabled", CSS)


if __name__ == "__main__":
    unittest.main()
