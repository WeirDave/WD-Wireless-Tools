"""A modal must contain everything needed to finish the job inside it.

Three reports in a row, one cause: Cloud Manager's dialogs were built as thin
wrappers over an action rather than as screens you can work in. The backdrop
is not a reference surface - it is dimmed on purpose, it may be scrolled
somewhere else, and on a small window the relevant row may not be on it at
all.

* Delete: "it greys the background out so you can't remember what it is
  you're deleting to double check."
* Rename: "I click on the pencil to rename it and of course it blurs out the
  background again and I can't see what I'm doing in order to rename it. So we
  need to really have that built into the modal - 'this is what you're
  changing' kind of thing."
* And the filters beside them: "I forgot what hybrid meant, or external for
  that matter."

Renaming is the harder of the two, because it is composition rather than
confirmation: he is writing a new name and the thing he needs - the folder it
sits in, which his naming convention uses - was behind the overlay. Showing it
is half the job; the other half is letting him put it in the name without
retyping it.

Asked which name he meant, he answered "folder / site name" - the folder *is*
the site. The dialog carries both that and the current name as labelled facts,
and one click puts the folder name in the field.

Two passes over this went further than he asked - reading the folder name as
the whole file name, then building a prefix-and-descriptor apparatus on top of
it - and he cut both back:

    "no just skip that idea for now, I just need you to add the site name to
    the rename modal."

So what is held here is that, and no more: the two names on screen at rest, the
field pre-filled, the caret at the end rather than round the whole value
because he is adding to a name rather than replacing one, one click to insert
the folder name, and nothing truncated.

Every name here is invented.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = (ROOT / "web" / "assets" / "js" / "cloud.js").read_text(encoding="utf-8")
CLOUD_HTML = (ROOT / "web" / "cloud.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")


class TheRenameDialogStandsOnItsOwnTests(unittest.TestCase):
    """Moved to `tests/test_cloud_rename_dialog_driven.py` in v2.156.0.

    This class held fifteen assertions against the *text* of `cloud.js`,
    `cloud.html` and `wd-tools.css` - `assertIn('id="renameWhat"', CLOUD_HTML)`,
    `assertIn("Folder / site name", start_rename)`, and so on. It is the file
    the 2026-09-18 audit named first under **A34, tests that pin wording rather
    than property**.

    The audit was right, and the reason is worth keeping where the old tests
    were: every one of those passes on an element nothing writes to and on a
    label built into a string that is never assigned. They describe a dialog
    that may or may not exist.

    `startRename` is run against a readable DOM now, and the assertions are
    about what it puts on screen. The conversion found something the source
    checks could not: nothing had ever checked that opening the dialog fills
    the preview, so deleting that call passed the whole file.

    The rest of this file - the delete dialog, the filter legends, the focus
    rings - is unchanged and still here.
    """


class IconButtonsSayWhatTheyDoTests(unittest.TestCase):
    """"we've got small little icons in there to do stuff with, and until you
    have them memorized they're difficult to figure out what it is we're
    doing. And we have plenty of real estate and we're not using it."

    A label beside the glyph, readable at rest. Not a tooltip - hover is no
    use while you are deciding which button to press.
    """

    def setUp(self):
        self.buttons = re.findall(r"<button[^>]*>(?:&#\d+;)(?:<span[^>]*>[^<]*</span>)?</button>",
                                  CLOUD_JS)

    def test_no_control_is_left_as_a_bare_glyph(self):
        bare = [b for b in self.buttons if "ib-label" not in b]
        # The disclosure chevron and the count badge are shapes rather than
        # actions, and carry their meaning in position and number.
        bare = [b for b in bare
                if "tree-chevron" not in b and "src-badge" not in b]
        self.assertEqual([], bare, "glyph-only controls left: %s" % bare)

    def test_the_sync_actions_carry_their_direction_as_words(self):
        """The two he misread. Words fix legibility and direction together.

        `ib-label` was a span revealed beside an emoji arrow in the middle
        lane. Both directions are full-width labelled buttons in the band under
        the row now, so the words are the control rather than an annotation on
        one - which is what this test was asking for in the first place.
        """
        self.assertIn("'Cloud \u2192 Local'", CLOUD_JS)
        self.assertIn("'Local \u2192 Cloud'", CLOUD_JS)

    def test_no_row_action_is_an_icon_with_no_word(self):
        """"I forgot what hybrid meant, or external for that matter."

        The row menus replaced about a dozen emoji circles a side. The menu's
        own button is the single exception and carries a title and an
        aria-label; everything inside it has to be a word.
        """
        import re as _re
        items = _re.findall(r"menuItem\('([a-z]+)',\s*(.+?),", CLOUD_JS, _re.S)
        self.assertGreater(len(items), 10)
        for icon, label in items:
            with self.subTest(item=label[:40]):
                self.assertNotEqual("", label.strip())
                self.assertGreater(len(label.strip()), 4)

    def test_the_everyday_pull_is_named_in_words(self):
        """His routine operation after every design, per the workflow note."""
        self.assertIn("Download over local", CLOUD_JS)

    def test_labels_are_visible_at_rest_rather_than_on_hover(self):
        block = CSS[CSS.index(".ib-label {"):]
        block = block[:block.index("}")]
        self.assertNotIn("display: none", block)
        self.assertNotIn("opacity: 0", block)

    def test_the_wide_layout_is_the_one_that_is_designed(self):
        """"let the small screen people suffer... as long as it's functional."

        Labels are the default and the narrow case is the exception, not the
        other way round - designing for narrow first is what produced the
        cramped row.
        """
        #: The block about labels, not merely the first one at this width.
        #: The ledger gutter token has a 1100px rule of its own now, and "the
        #: first @media at 1100" was never what this test meant.
        blocks, rest = [], CSS
        marker = "@media (max-width: 1100px)"
        while marker in rest:
            rest = rest[rest.index(marker) + len(marker):]
            blocks.append(rest[:rest.index("\n}\n")] if "\n}\n" in rest else rest)
        hide = next((b for b in blocks if ".ib-label" in b), "")
        self.assertIn(".ib-label { display: none; }", hide)


class EveryFilterSaysWhatItSelectsTests(unittest.TestCase):

    def setUp(self):
        # The filters were `.dash-card` divs until the header redesign; they
        # are now buttons on the summary line and inside the "More filters"
        # menu. What is being checked is unchanged and is the point: every
        # filter says what it selects, because "I forgot what hybrid meant, or
        # external for that matter."
        self.cards = re.findall(
            r'<button class="(?:sum-count|wd-menu-item)"[^>]*?'
            r'data-filter="([a-z-]+)"([^>]*)>',
            CLOUD_HTML)

    def test_there_are_cards_to_check(self):
        self.assertGreater(len(self.cards), 10)

    def test_every_filter_card_has_a_definition(self):
        missing = [k for k, attrs in self.cards if "title=" not in attrs]
        self.assertEqual([], missing, "filters with no tooltip: %s" % missing)

    def test_no_tooltip_merely_restates_its_own_label(self):
        """A tooltip that repeats the label looks like help and is not.

        Same lesson as the Squirrel tile descriptions.
        """
        for key, attrs in self.cards:
            with self.subTest(filter=key):
                tip = re.search(r'title="([^"]+)"', attrs)
                self.assertIsNotNone(tip)
                text = tip.group(1)
                self.assertGreater(len(text), 40, text)
                self.assertNotEqual(text.lower().rstrip("."),
                                    key.replace("-", " "))

    def test_the_two_he_could_not_remember_are_defined_from_the_data(self):
        """"I forgot what hybrid meant, or external for that matter."

        Both are written from what the filter actually selects - the Ekahau
        project type, and who owns the project - rather than from the word.
        """
        tips = {k: re.search(r'title="([^"]+)"', a).group(1)
                for k, a in self.cards if "title=" in a}
        self.assertIn("HYBRID_PROJECT", tips["type-hybrid"])
        self.assertIn("predictive", tips["type-hybrid"].lower())
        self.assertIn("survey", tips["type-hybrid"].lower())
        self.assertIn("owned by somebody else", tips["external"].lower())

    def test_the_neighbouring_owner_toggles_are_covered_too(self):
        """He would have hit these next."""
        for owner in ("all", "mine", "others"):
            with self.subTest(owner=owner):
                m = re.search(r'<button class="owner-btn" data-owner="%s"([^>]*)>'
                              % owner, CLOUD_HTML)
                self.assertIsNotNone(m, owner)
                self.assertIn("title=", m.group(1))

    def test_a_filter_is_reachable_without_a_mouse(self):
        """The requirement is unchanged; the mechanism got simpler.

        The filters were plain `<div>`s, so reaching them without a pointer
        needed `tabindex="0"`, `role="button"`, a key handler in JS and a focus
        style - four things standing in for what an element already does. They
        are real `<button>`s since the header redesign, which are focusable and
        activatable by Enter and Space with no help at all, so the scaffolding
        went with them.

        What is still asserted is the property: every filter is a control the
        keyboard can reach, and focus is visible when it gets there.
        """
        markup = re.findall(
            r'(<button class="(?:sum-count|wd-menu-item)"[^>]*?'
            r'data-filter="[a-z-]+"[^>]*>)', CLOUD_HTML)
        self.assertEqual(len(self.cards), len(markup),
                         "every filter must be a real button")
        for tag in markup:
            with self.subTest(tag=tag[:60]):
                self.assertNotIn('role="button"', tag,
                                 "a <button> does not need to claim it is one")
        self.assertIn(".sum-count:focus-visible", CSS)
        self.assertIn(".wd-menu-item:focus-visible", CSS)


if __name__ == "__main__":
    unittest.main()
