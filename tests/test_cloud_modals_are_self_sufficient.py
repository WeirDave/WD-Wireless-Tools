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
            "\nfunction _renameContainerName", start)]

    def test_it_says_what_is_being_changed(self):
        """His phrase, and the right spec."""
        self.assertIn('id="renameWhat"', CLOUD_HTML)
        self.assertIn("You are renaming", self.start_rename)

    def test_it_shows_where_the_thing_lives(self):
        """The specific fact he was trying to read off the greyed-out list."""
        self.assertIn("_renameContainerName", self.start_rename)
        self.assertIn(" in ", self.start_rename)

    def test_the_field_is_prefilled_so_he_edits_rather_than_retypes(self):
        self.assertIn("input.value = name;", self.start_rename)
        self.assertIn("input.select();", self.start_rename)

    def test_the_container_name_can_be_inserted_not_just_read(self):
        """Showing it saves him nothing if he still has to type it."""
        self.assertIn('id="renameInsert"', CLOUD_HTML)
        self.assertIn("_renameInsert(", CLOUD_JS)
        insert = CLOUD_JS[CLOUD_JS.index("function _renameInsert("):]
        insert = insert[:insert.index("\n}")]
        self.assertIn("selectionStart", insert)
        self.assertIn("setSelectionRange", insert)

    def test_inserting_adds_to_the_name_rather_than_replacing_it(self):
        """Caught by driving it: the first version wiped the name.

        The field opens with everything selected so he can retype. That made
        the insert button replace the selection - turning "Survey 30" into
        "North Campus" - which is the opposite of "I want to use the folder
        name as part of the name".
        """
        insert = CLOUD_JS[CLOUD_JS.index("function _renameInsert("):]
        insert = insert[:insert.index("\n}")]
        self.assertIn("wholeThing", insert)
        self.assertIn("start = end = value.length", insert)

    def test_there_is_a_live_preview_of_the_result(self):
        self.assertIn('id="renamePreview"', CLOUD_HTML)
        self.assertIn('oninput="_renamePreview()"', CLOUD_HTML)
        preview = CLOUD_JS[CLOUD_JS.index("function _renamePreview("):]
        preview = preview[:preview.index("\n}\n")]
        self.assertIn("rename-preview-from", preview)
        self.assertIn("rename-preview-to", preview)

    def test_the_preview_shows_the_extension_for_a_local_file(self):
        """He renames the file on disk; the suffix is part of the outcome."""
        preview = CLOUD_JS[CLOUD_JS.index("function _renamePreview("):]
        preview = preview[:preview.index("\n}\n")]
        self.assertIn(".esx", preview)

    def test_an_unchanged_or_empty_name_says_so(self):
        preview = CLOUD_JS[CLOUD_JS.index("function _renamePreview("):]
        preview = preview[:preview.index("\n}\n")]
        self.assertIn("Unchanged", preview)
        self.assertIn("Enter a name", preview)

    def test_a_site_is_not_described_as_being_inside_something(self):
        fn = CLOUD_JS[CLOUD_JS.index("function _renameContainerName("):]
        fn = fn[:fn.index("\n}")]
        self.assertIn("if (kind === 'sites') return '';", fn)


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
