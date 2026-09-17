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

    def setUp(self):
        start = CLOUD_JS.index("function startRename(")
        self.start_rename = CLOUD_JS[start:CLOUD_JS.index(
            "\n/* The site or folder this thing sits in", start)]

    @staticmethod
    def body(name):
        """The source of one function, by name."""
        fn = CLOUD_JS[CLOUD_JS.index("function %s(" % name):]
        return fn[:fn.index("\n}")]

    def test_it_says_what_is_being_changed(self):
        """His phrase, and the right spec."""
        self.assertIn('id="renameWhat"', CLOUD_HTML)
        self.assertIn("You are renaming", self.start_rename)

    def test_it_shows_where_the_thing_lives(self):
        """The specific fact he was trying to read off the greyed-out list."""
        self.assertIn("_renameContainerName", self.start_rename)

    def test_the_folder_and_the_current_name_are_both_labelled_facts(self):
        """"folder / site name" - his own answer to which name he meant.

        Both are on screen at rest, each under a label of its own. The folder
        used to be a lowercase aside on the end of the name line, which is
        where a fact goes when it has been thought of as context rather than
        as the string he is trying to type.
        """
        self.assertIn("Folder / site name", self.start_rename)
        self.assertIn("Cloud site", self.start_rename)
        for key in ("Current file name", "Current folder name",
                    "Current project name", "Current site name"):
            self.assertIn(key, self.start_rename)
        self.assertIn("rename-what-key", self.start_rename)
        self.assertIn("rename-what-folder", self.start_rename)
        self.assertIn("rename-what-name", self.start_rename)

    def test_the_current_name_carries_its_extension(self):
        """What is on disk is `<name>.esx`, so that is what is shown."""
        self.assertIn("name + suffix", self.start_rename)
        self.assertIn(".esx", self.body("_renameSuffix"))

    def test_a_local_item_shows_its_full_path(self):
        """Two sites can own a folder of the same name; the path settles it."""
        self.assertIn("Full path", self.start_rename)
        self.assertIn("rename-what-path", self.start_rename)

    def test_nothing_in_the_dialog_is_truncated(self):
        """"it would be better if it was easily readable and lengthy than if
        it's brief." The dialog is widened rather than the strings shortened.
        """
        self.assertIn(".modal.modal-rename", CSS)
        self.assertIn('class="modal modal-rename"', CLOUD_HTML)
        block = CSS[CSS.index(".rename-what {"):CSS.index(".rename-insert {")]
        self.assertNotIn("text-overflow", block)
        self.assertNotIn("white-space: nowrap", block)
        self.assertIn("overflow-wrap: anywhere", block)

    def test_the_dialog_does_not_judge_the_name_he_types(self):
        """The apparatus he cut. "No just skip that idea for now, I just need
        you to add the site name to the rename modal."

        Two passes read more into "folder / site name" than was there - first
        that the file name should equal the folder name, then a whole
        prefix-and-descriptor scheme - and both are gone. The dialog shows him
        what he asked to see and gets out of the way.
        """
        for gone in ("_renameMatch", "_renameMatchState", "_renameSplit",
                     "_renameUsePrefix", "_renameDescriptor", "_renameSeparator"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, CLOUD_JS)
        self.assertNotIn("renameMatch", CLOUD_HTML)
        self.assertNotIn("rename-match", CSS)

    def test_only_one_thing_is_offered_to_click(self):
        """One button, doing the one thing he asked for. The second one went
        with the scheme it belonged to."""
        self.assertEqual(1, self.start_rename.count("rename-insert-btn"))
        self.assertIn("Insert &ldquo;", self.start_rename)

    def test_the_field_is_prefilled_and_the_caret_waits_at_the_end(self):
        """Not select-all. He is adding to a name, not replacing one.

        "I had a whole bunch that were named with just the prefix and didn't
        add additional information on facilities, and now I need to do that."
        With the whole value selected, the first character typed deletes the
        prefix that was already correct.
        """
        self.assertIn("input.value = name;", self.start_rename)
        self.assertNotIn("input.select();", self.start_rename)
        self.assertIn("input.setSelectionRange(input.value.length, input.value.length);",
                      self.start_rename)

    def test_the_container_name_can_be_inserted_not_just_read(self):
        """Showing it saves him nothing if he still has to type it."""
        self.assertIn('id="renameInsert"', CLOUD_HTML)
        self.assertIn("_renameInsert(", CLOUD_JS)
        insert = self.body("_renameInsert")
        self.assertIn("selectionStart", insert)
        self.assertIn("setSelectionRange", insert)

    def test_inserting_adds_to_the_name_rather_than_replacing_it(self):
        """Caught by driving it: the first version wiped the name.

        The field opens with everything selected so he can retype. That made
        the insert button replace the selection - turning "Survey 30" into
        "North Campus" - which is the opposite of "I want to use the folder
        name as part of the name".
        """
        insert = self.body("_renameInsert")
        self.assertIn("wholeThing", insert)
        self.assertIn("start = end = value.length", insert)

    def test_there_is_a_live_preview_of_the_result(self):
        self.assertIn('id="renamePreview"', CLOUD_HTML)
        self.assertIn('oninput="_renamePreview()"', CLOUD_HTML)
        preview = self.body("_renamePreview")
        self.assertIn("rename-preview-from", preview)
        self.assertIn("rename-preview-to", preview)

    def test_the_preview_shows_the_extension_for_a_local_file(self):
        """He renames the file on disk; the suffix is part of the outcome."""
        self.assertIn(".esx", self.body("_renameSuffix"))
        self.assertIn("renameTarget.suffix", self.body("_renamePreview"))

    def test_an_unchanged_or_empty_name_says_so(self):
        preview = self.body("_renamePreview")
        self.assertIn("Unchanged", preview)
        self.assertIn("Enter a name", preview)

    def test_a_site_is_not_described_as_being_inside_something(self):
        fn = self.body("_renameContainerName")
        self.assertIn("if (kind === 'sites') return '';", fn)


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

    def test_the_sync_arrows_carry_their_direction_as_words(self):
        """The two he misread. Words fix legibility and direction together."""
        self.assertIn('<span class="ib-label">Cloud → Local</span>', CLOUD_JS)
        self.assertIn('<span class="ib-label">Local → Cloud</span>', CLOUD_JS)

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
        hide = CSS[CSS.index("@media (max-width: 1100px)"):]
        hide = hide[:hide.index("\n}\n")]
        self.assertIn(".ib-label { display: none; }", hide)


class EveryFilterSaysWhatItSelectsTests(unittest.TestCase):

    def setUp(self):
        self.cards = re.findall(
            r'<div class="dash-card [^"]*" data-filter="([a-z-]+)"([^>]*)>',
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

    def test_a_tooltip_is_reachable_without_a_mouse(self):
        """The cards were plain divs, so nothing but a pointer could reach them."""
        for key, attrs in self.cards:
            with self.subTest(filter=key):
                self.assertIn('tabindex="0"', attrs)
                self.assertIn('role="button"', attrs)
        self.assertIn("_wireFilterCardKeys", CLOUD_JS)
        self.assertIn(".dash-card:focus-visible", CSS)


if __name__ == "__main__":
    unittest.main()
