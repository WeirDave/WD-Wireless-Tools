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
that." Nothing regressed. Pushing a local file up over an existing cloud
project has never been built, because the upload this client has creates a
*second* cloud project instead of replacing the one already there. But the app
expressed that as a status with no adjacent remedy and the explanation buried
in a `title`, which reads exactly like a broken button.

So the action is now shown and unavailable rather than absent, and clicking it
says why - the treatment the bulk buttons already had.
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

    def test_the_row_arrows_lead_with_the_direction_too(self):
        self.assertIn("Cloud → Local: apply the cloud name", CLOUD_JS)
        self.assertIn("Local → Cloud: apply the local name", CLOUD_JS)

    def test_the_old_vocabulary_is_gone_from_the_tooltips(self):
        """Two names for one direction is how the confusion started."""
        self.assertNotIn("Push local \\u2192 cloud", CLOUD_JS)
        self.assertNotIn("Pull cloud \\u2192 local", CLOUD_JS)


class AnUnavailableActionIsShownRatherThanAbsentTests(unittest.TestCase):

    def setUp(self):
        start = CLOUD_JS.index("if (s === 'local_newer')")
        self.block = CLOUD_JS[start:CLOUD_JS.index("function gutCell", start)]

    def test_the_row_offers_a_push_control_at_all(self):
        """The whole complaint: a status with nothing beside it to click."""
        self.assertIn("<button", self.block)
        self.assertIn("Local &#8594; Cloud", self.block)

    def test_it_is_marked_unavailable_rather_than_merely_looking_dead(self):
        self.assertIn('aria-disabled="true"', self.block)
        self.assertIn("is-disabled", self.block)

    def test_clicking_it_explains_instead_of_doing_nothing(self):
        """Hover is not where anyone looks before deciding a button is broken."""
        wiring = CLOUD_JS[CLOUD_JS.index("function _wireDisabledBulkReasons"):]
        wiring = wiring[:wiring.index("\n}")]
        self.assertIn("gut-arrow.is-disabled", wiring)
        self.assertIn("toast(", wiring)

    def test_the_reason_names_the_duplicate_it_would_create(self):
        """The accurate reason, and the one that matters to him right now.

        `upload/initiate` takes a filename and no project id, so uploading
        over an existing project makes a second one. That is not a
        hypothetical - it is how two identical projects under different names
        appear in a cloud account.
        """
        self.assertIn("second cloud project", self.block)
        self.assertIn("duplicate", self.block.lower())

    def test_it_still_says_not_built_rather_than_cannot(self):
        """What Ekahau's API could do here has never been established.

        Saying "cannot" would state something about his own tool that nobody
        has tested. The Sync confirm settled on this vocabulary already.
        """
        self.assertIn("not built yet", self.block)
        self.assertNotIn("Ekahau cannot", self.block)

    def test_it_says_what_to_do_in_the_meantime(self):
        self.assertIn("project in ekahau and save it to the cloud",
                      self.block.lower())

    def test_nothing_is_at_risk_is_still_said(self):
        """Sync never replaces a newer file with an older one, and says so."""
        self.assertIn("never", self.block.lower())
        self.assertIn("older", self.block.lower())

    def test_the_greyed_control_is_styled_as_unavailable(self):
        self.assertIn(".gut-arrow.is-disabled", CSS)


if __name__ == "__main__":
    unittest.main()
