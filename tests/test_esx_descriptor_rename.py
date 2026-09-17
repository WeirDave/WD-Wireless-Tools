"""One descriptor, typed once, across many sites at a time.

His convention for a project file is **<site folder name><separator><what kind
of file it is>**. An earlier pass here read it as "the file name equals the
folder name" and he corrected that:

    "So I'm talking about the ESX files. They're partially named with the site
    name / folder name, but not entirely - they're also going to have
    information on what kind of file it is. But when I go to rename them, for
    example I had a whole bunch that were named with just the prefix and
    didn't add additional information on facilities, and now I need to do
    that."

And then the thing that decides the shape of the whole feature:

    "I've already done it for the folders / site names."

The folders are finished and authoritative. So the prefix never has to be
typed - it is read from the folder each file is sitting in - and the job that
is left is bulk: many files, one descriptor. Selecting a set that spans
several sites and typing the descriptor once has to land each file correctly,
because each file reads its own folder.

The safety argument is in which rows come back ticked. A file carrying only
the prefix is the job and is ticked. A file already carrying a descriptor
would have that descriptor thrown away, so it is listed, its loss is spelled
out, and it is not ticked.

Every site name, folder name and descriptor in this file is invented.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tools.rename_manager import RenameManager, split_folder_prefix


def build(root: Path, tree: dict) -> None:
    """tree: {folder name: [file name, ...]}"""
    for folder, files in tree.items():
        d = root / folder
        d.mkdir(parents=True, exist_ok=True)
        for name in files:
            (d / name).write_bytes(b"not really a project")


class ReadingANameAsPrefixAndDescriptor(unittest.TestCase):
    """Where the prefix ends. The dialog and the batch both ask this, so they
    have to answer it the same way or they will disagree about one file."""

    def test_the_folder_name_and_nothing_else(self):
        self.assertEqual(("", ""),
                         split_folder_prefix("Riverside Depot", "Riverside Depot"))

    def test_the_folder_name_then_a_descriptor(self):
        self.assertEqual((" - ", "Predictive"),
                         split_folder_prefix("Riverside Depot - Predictive",
                                             "Riverside Depot"))

    def test_any_of_the_separators_he_might_use(self):
        for joined, sep in (("Depot_Predictive", "_"),
                            ("Depot-Predictive", "-"),
                            ("Depot Predictive", " "),
                            ("Depot.Predictive", "."),
                            ("Depot - Predictive", " - ")):
            with self.subTest(joined=joined):
                self.assertEqual((sep, "Predictive"),
                                 split_folder_prefix(joined, "Depot"))

    def test_a_longer_word_starting_with_the_folder_name_is_not_a_prefix(self):
        """The check that earns its keep. Without the separator requirement a
        folder called "North" claims "Northside", and every rename built on
        that has moved the boundary by four characters."""
        self.assertIsNone(split_folder_prefix("Northside", "North"))
        self.assertIsNone(split_folder_prefix("Northside - Predictive", "North"))

    def test_a_different_site_entirely_is_not_a_prefix(self):
        self.assertIsNone(
            split_folder_prefix("Harbour Point - Predictive", "Riverside Depot"))

    def test_capitalisation_does_not_decide_it(self):
        self.assertEqual((" - ", "Predictive"),
                         split_folder_prefix("RIVERSIDE DEPOT - Predictive",
                                             "Riverside Depot"))


class TheSeparatorIsReadOffHisFiles(unittest.TestCase):
    """Chosen wrong, it is applied to every file in the batch at once, and
    undoing that by hand is the tedium this feature exists to remove."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rm = RenameManager()
        self.addCleanup(self.tmp.cleanup)

    def test_it_takes_the_one_he_already_uses_most(self):
        build(self.root, {
            "Riverside Depot": ["Riverside Depot - Predictive.esx"],
            "Harbour Point": ["Harbour Point - Post Install.esx"],
            "North Campus": ["North Campus_Predictive.esx"],
        })
        r = self.rm.detect_descriptor_separator(str(self.root))
        self.assertTrue(r["ok"])
        self.assertEqual(" - ", r["separator"])
        self.assertTrue(r["detected"])

    def test_it_says_so_when_there_is_nothing_to_read_it_from(self):
        """A bare prefix everywhere is exactly his starting position, and a
        guess presented as a reading would be worse than a stated default."""
        build(self.root, {"Riverside Depot": ["Riverside Depot.esx"]})
        r = self.rm.detect_descriptor_separator(str(self.root))
        self.assertFalse(r["detected"])
        self.assertEqual(" - ", r["separator"])

    def test_an_underscore_house_style_is_honoured(self):
        build(self.root, {
            "Riverside Depot": ["Riverside Depot_Predictive.esx",
                                "Riverside Depot_Post Install.esx"],
            "Harbour Point": ["Harbour Point_Predictive.esx"],
        })
        self.assertEqual("_",
                         self.rm.detect_descriptor_separator(str(self.root))["separator"])

    def test_the_general_separator_sniffer_cannot_answer_this(self):
        """`detect_rename_style` skips .esx files outright, which is every
        file this feature is about. Kept as a test so a later tidy-up does not
        collapse the two."""
        build(self.root, {
            "Riverside Depot": ["Riverside Depot_Predictive.esx"],
        })
        self.assertEqual("", self.rm.detect_rename_style(str(self.root))["separator"])
        self.assertEqual("_",
                         self.rm.detect_descriptor_separator(str(self.root))["separator"])


class HisOwnVocabularyIsOffered(unittest.TestCase):
    """"Offer his existing descriptors rather than inventing a taxonomy."

    A hardcoded list of guesses is wrong the first time he invents a word, and
    there is no way to know from here what words he uses.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rm = RenameManager()
        self.addCleanup(self.tmp.cleanup)

    def test_the_commonest_come_first_with_their_counts(self):
        build(self.root, {
            "Riverside Depot": ["Riverside Depot - Predictive.esx",
                                "Riverside Depot - Post Install.esx"],
            "Harbour Point": ["Harbour Point - Predictive.esx"],
            "North Campus": ["North Campus - Predictive.esx",
                             "North Campus - Validation.esx"],
        })
        got = self.rm.scan_descriptors(str(self.root))["descriptors"]
        self.assertEqual({"text": "Predictive", "count": 3}, got[0])
        self.assertEqual({"Post Install", "Validation"},
                         {d["text"] for d in got[1:]})

    def test_a_bare_prefix_contributes_no_descriptor(self):
        build(self.root, {"Riverside Depot": ["Riverside Depot.esx"]})
        self.assertEqual([], self.rm.scan_descriptors(str(self.root))["descriptors"])

    def test_a_file_named_after_another_site_contributes_nothing(self):
        """Its tail is not a descriptor, it is the rest of somebody else's
        name, and offering it as a word he uses would be a fiction."""
        build(self.root, {"Riverside Depot": ["Harbour Point - Predictive.esx"]})
        self.assertEqual([], self.rm.scan_descriptors(str(self.root))["descriptors"])


class ThePreviewSaysWhatWouldHappen(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rm = RenameManager()
        self.addCleanup(self.tmp.cleanup)

    def preview(self, descriptor="Facilities", **kw):
        r = self.rm.preview_add_descriptor(str(self.root), descriptor, **kw)
        self.assertTrue(r["ok"], r.get("error"))
        return {it["current"]: it for it in r["items"]}, r

    def test_each_file_takes_its_own_folders_name(self):
        """The whole point of the bulk shape: one descriptor typed once, and
        files in three different sites all land correctly because the prefix
        is read per file rather than typed."""
        build(self.root, {
            "Riverside Depot": ["Riverside Depot.esx"],
            "Harbour Point": ["Harbour Point.esx"],
            "North Campus Building 4": ["North Campus Building 4.esx"],
        })
        items, _ = self.preview()
        self.assertEqual("Riverside Depot - Facilities.esx",
                         items["Riverside Depot.esx"]["new_name"])
        self.assertEqual("Harbour Point - Facilities.esx",
                         items["Harbour Point.esx"]["new_name"])
        self.assertEqual("North Campus Building 4 - Facilities.esx",
                         items["North Campus Building 4.esx"]["new_name"])

    def test_a_bare_prefix_is_the_job_and_is_ticked(self):
        build(self.root, {"Riverside Depot": ["Riverside Depot.esx"]})
        items, _ = self.preview()
        it = items["Riverside Depot.esx"]
        self.assertEqual("add", it["status"])
        self.assertTrue(it["selected"])
        self.assertEqual("", it["losing"])

    def test_a_file_that_already_says_something_is_not_ticked(self):
        """Applying the descriptor would throw the existing one away. Listed,
        with the loss spelled out, and left for him to tick."""
        build(self.root, {
            "Riverside Depot": ["Riverside Depot - Predictive.esx"],
        })
        items, _ = self.preview()
        it = items["Riverside Depot - Predictive.esx"]
        self.assertEqual("replace", it["status"])
        self.assertFalse(it["selected"])
        self.assertEqual("Predictive", it["losing"])

    def test_a_file_already_correct_is_shown_and_does_nothing(self):
        build(self.root, {
            "Riverside Depot": ["Riverside Depot - Facilities.esx"],
        })
        items, _ = self.preview()
        it = items["Riverside Depot - Facilities.esx"]
        self.assertEqual("already_correct", it["status"])
        self.assertFalse(it["selected"])

    def test_a_prefix_naming_another_site_is_corrected_and_shown(self):
        """"Since the folders are now authoritative, that file is misnamed.
        Show it in the preview so he can see it's being corrected, rather than
        silently rewriting it."

        A single wrong token has nothing worth keeping, so it is ticked.
        """
        build(self.root, {"Riverside Depot": ["Depot99.esx"]})
        items, _ = self.preview()
        it = items["Depot99.esx"]
        self.assertEqual("fix_prefix", it["status"])
        self.assertTrue(it["selected"])
        self.assertEqual("Riverside Depot - Facilities.esx", it["new_name"])

    def test_a_wrong_prefix_with_a_tail_is_not_ticked_either(self):
        """Two things would change at once and one of them is a loss, so this
        is his call rather than the default."""
        build(self.root, {
            "Riverside Depot": ["Harbour Point - Predictive.esx"],
        })
        items, _ = self.preview()
        it = items["Harbour Point - Predictive.esx"]
        self.assertEqual("replace", it["status"])
        self.assertFalse(it["selected"])
        self.assertEqual("Predictive", it["losing"])

    def test_two_files_that_would_collide_are_blocked_and_say_why(self):
        build(self.root, {
            "Riverside Depot": ["Riverside Depot.esx", "Depot99.esx"],
        })
        items, _ = self.preview()
        for name in ("Riverside Depot.esx", "Depot99.esx"):
            with self.subTest(name=name):
                self.assertEqual("collision", items[name]["status"])
                self.assertFalse(items[name]["selected"])
                self.assertIn("same name", items[name]["reason"])

    def test_a_name_already_taken_in_the_folder_is_blocked(self):
        build(self.root, {
            "Riverside Depot": ["Riverside Depot.esx",
                                "Riverside Depot - Facilities.esx"],
        })
        items, _ = self.preview()
        self.assertEqual("collision", items["Riverside Depot.esx"]["status"])
        self.assertIn("already in this folder",
                      items["Riverside Depot.esx"]["reason"])

    def test_the_detected_separator_is_used_unless_one_is_given(self):
        build(self.root, {
            "Riverside Depot": ["Riverside Depot_Predictive.esx",
                                "Riverside Depot.esx"],
        })
        items, r = self.preview()
        self.assertEqual("_", r["separator"])
        self.assertEqual("Riverside Depot_Facilities.esx",
                         items["Riverside Depot.esx"]["new_name"])

        items, r = self.preview(separator=" - ")
        self.assertEqual("Riverside Depot - Facilities.esx",
                         items["Riverside Depot.esx"]["new_name"])

    def test_the_counts_add_up_to_the_list(self):
        build(self.root, {
            "Riverside Depot": ["Riverside Depot.esx"],
            "Harbour Point": ["Harbour Point - Predictive.esx",
                              "Harbour Point - Facilities.esx"],
        })
        _, r = self.preview()
        self.assertEqual(len(r["items"]), sum(r["counts"].values()))
        self.assertEqual(1, r["counts"]["add"])
        self.assertEqual(1, r["counts"]["replace"])
        self.assertEqual(1, r["counts"]["already_correct"])

    def test_non_esx_files_are_left_completely_alone(self):
        """Floor plans and photos live in these folders too and are not his
        project files."""
        build(self.root, {
            "Riverside Depot": ["Riverside Depot.esx", "floorplan.pdf",
                                "front door.jpg"],
        })
        _, r = self.preview()
        self.assertEqual(["Riverside Depot.esx"],
                         [it["current"] for it in r["items"]])

    def test_a_missing_root_is_an_error_rather_than_an_empty_list(self):
        """An empty list reads as "nothing to do", which is the wrong thing to
        tell someone whose folder is not where they think it is."""
        r = self.rm.preview_add_descriptor(str(self.root / "nope"), "Facilities")
        self.assertFalse(r["ok"])
        self.assertIn("root", r["error"].lower())


class ApplyingItRenamesAndCanBeUndone(unittest.TestCase):
    """"Preview before applying, always, and rename files rather than copying.
    These are live project files.\""""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.home.cleanup)
        # Undo logs go under the user directory; keep them out of his.
        self._prev = os.environ.get("WD_USER_DIR")
        os.environ["WD_USER_DIR"] = self.home.name
        import importlib
        import tools.user_dir
        import tools.rename_manager as rmod
        importlib.reload(tools.user_dir)
        importlib.reload(rmod)
        self.rmod = rmod
        self.rm = rmod.RenameManager()

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("WD_USER_DIR", None)
        else:
            os.environ["WD_USER_DIR"] = self._prev
        import importlib
        import tools.user_dir
        import tools.rename_manager
        importlib.reload(tools.user_dir)
        importlib.reload(tools.rename_manager)

    def names(self):
        return sorted(p.name for p in self.root.rglob("*.esx"))

    def test_the_files_move_rather_than_multiply(self):
        build(self.root, {
            "Riverside Depot": ["Riverside Depot.esx"],
            "Harbour Point": ["Harbour Point.esx"],
        })
        r = self.rm.preview_add_descriptor(str(self.root), "Facilities")
        picked = [it for it in r["items"] if it["selected"]]
        out = self.rm.execute_add_descriptor(picked)

        self.assertEqual(2, out["renamed"])
        self.assertEqual(["Harbour Point - Facilities.esx",
                          "Riverside Depot - Facilities.esx"], self.names())

    def test_nothing_that_was_not_ticked_is_touched(self):
        build(self.root, {
            "Riverside Depot": ["Riverside Depot.esx",
                                "Riverside Depot - Predictive.esx"],
        })
        r = self.rm.preview_add_descriptor(str(self.root), "Facilities")
        picked = [it for it in r["items"] if it["selected"]]
        self.rm.execute_add_descriptor(picked)
        self.assertIn("Riverside Depot - Predictive.esx", self.names())
        self.assertIn("Riverside Depot - Facilities.esx", self.names())

    def test_it_refuses_to_write_over_a_file_that_is_already_there(self):
        build(self.root, {
            "Riverside Depot": ["Riverside Depot.esx",
                                "Riverside Depot - Facilities.esx"],
        })
        (self.root / "Riverside Depot" / "Riverside Depot - Facilities.esx"
         ).write_bytes(b"the one that already exists")
        out = self.rm.execute_add_descriptor([{
            "path": str(self.root / "Riverside Depot" / "Riverside Depot.esx"),
            "new_name": "Riverside Depot - Facilities.esx",
        }])
        self.assertEqual(0, out["renamed"])
        self.assertEqual(1, out["skipped"])
        self.assertEqual(b"the one that already exists",
                         (self.root / "Riverside Depot"
                          / "Riverside Depot - Facilities.esx").read_bytes())

    def test_undo_puts_every_name_back(self):
        """A bulk rename across many projects is the accident he cannot
        absorb, so there has to be a way back from one."""
        build(self.root, {
            "Riverside Depot": ["Riverside Depot.esx"],
            "Harbour Point": ["Harbour Point.esx"],
            "North Campus": ["North Campus.esx"],
        })
        before = self.names()
        r = self.rm.preview_add_descriptor(str(self.root), "Facilities")
        self.rm.execute_add_descriptor([it for it in r["items"] if it["selected"]])
        self.assertNotEqual(before, self.names())

        back = self.rm.undo_last("descriptor")
        self.assertTrue(back["ok"])
        self.assertEqual(3, back["reverted"])
        self.assertEqual([], back["errors"])
        self.assertEqual(before, self.names())

    def test_its_undo_log_is_its_own(self):
        """The cleanup-rules pass writes one too. Sharing a file would mean
        undoing one operation reverted the other."""
        self.assertNotEqual(self.rmod._undo_path("bulk"),
                            self.rmod._undo_path("descriptor"))


class ThePageCanActuallyReachIt(unittest.TestCase):
    """A backend nothing routes to is a backend nobody has.

    `/api/rename/<action>` 404s on an unregistered name, and the Rename page
    reads the reply for exactly one of its calls - which is how the settings
    bug on this page went unnoticed for as long as it did.
    """

    def test_every_action_the_page_calls_is_registered(self):
        import server
        js = (Path(__file__).resolve().parent.parent / "web" / "assets"
              / "js" / "rename.js").read_text(encoding="utf-8")
        import re
        called = set(re.findall(r"renameApi\('([a-z_]+)'", js))
        missing = sorted(a for a in called if a not in server.RENAME_ACTIONS)
        self.assertEqual([], missing,
                         "the page calls these and the server has no route: %s"
                         % missing)

    def test_the_four_new_ones_are_among_them(self):
        import server
        for action in ("detect_descriptor_separator", "scan_descriptors",
                       "preview_add_descriptor", "execute_add_descriptor"):
            with self.subTest(action=action):
                self.assertIn(action, server.RENAME_ACTIONS)

    def test_applying_goes_through_the_preview_shape(self):
        """The page may only send rows it has shown him. Both fields the
        renamer needs come straight off a preview row, so there is no path
        that renames something the preview never drew."""
        js = (Path(__file__).resolve().parent.parent / "web" / "assets"
              / "js" / "rename.js").read_text(encoding="utf-8")
        body = js[js.index("async function doRename()"):]
        block = body[body.index("if (tab === 'esx')"):body.index("} else if (tab === 'rules')")]
        self.assertIn("_renameState.items.filter", block)
        self.assertIn("x.selected", block)
        self.assertIn("'already_correct'", block)
        self.assertIn("'collision'", block)


class NothingHereCarriesARealName(unittest.TestCase):
    """Rule zero, checked on the module rather than trusted.

    The descriptors and the separator are read off disk at the moment they are
    asked for. If a list of words ever gets hardcoded here, that is a list
    somebody wrote down from his real projects.
    """

    def test_the_module_ships_no_list_of_descriptors(self):
        src = (Path(__file__).resolve().parent.parent
               / "tools" / "rename_manager.py").read_text(encoding="utf-8")
        block = src[src.index("def scan_descriptors("):]
        block = block[:block.index("\n    def ")]
        self.assertIn("_esx_files", block)
        self.assertNotIn("[\"", block.split('"""')[2])

    def test_the_only_separators_named_are_punctuation(self):
        from tools.rename_manager import DEFAULT_DESCRIPTOR_SEPARATOR
        self.assertTrue(
            all(c in " -_." for c in DEFAULT_DESCRIPTOR_SEPARATOR))


if __name__ == "__main__":
    unittest.main()
