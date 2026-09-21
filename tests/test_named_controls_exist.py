"""The app only points at controls that exist - now on every page, not one.

The rule is old and it was earned: the Sync dialog spent a release telling him
to use **Local newer · replace cloud** while that button was greyed out for
every row he had, and he reasonably concluded the tool was lying to him. The
guard written afterwards, ``TheAppOnlyPointsAtControlsThatExistTests``, reads
``cloud.js`` and nothing else - a suite-wide rule enforced on the one page that
had already been caught.

v2.150.0 walked straight into the gap. Settings gained "Open Report and use
**Edit report settings**" in the same change that renamed that button to
**Cover image…**: instruction on one page, control on another, guard blind to
both. It was found by looking at a screenshot, which is not a mechanism.

**Two earlier attempts at a wider version passed with that defect in place**,
and not repeating them is most of the design:

* searching the raw source matched a **comment** in ``report.js`` explaining
  why the button had been renamed - the old name sat in prose, in quotes, and
  read as a label. Comments are stripped before anything is searched, by a
  scanner rather than a regex, because ``'http://x'`` inside a string is not a
  comment and a regex that thinks it is deletes the rest of the line.
* searching for ``>Name<`` across ``web/`` matched **the instruction itself**.
  A page that says "use <b>Cover image</b>" contains that string, so counting
  it made every instruction satisfy itself. Bolded markup is removed from the
  haystack before the needles are looked for.

And the third thing, which is why a plain search finds nothing either way:
labels here are **built by concatenation**. ``'Cover image' + '\\u2026'`` never
appears as ``Cover image…`` anywhere in the source. Adjacent string literals
joined by ``+`` are folded together before the corpus is built.

``TheCheckCanFailTests`` is the important class. A guard for a defect that has
already been fixed proves nothing unless it is shown to fail on that defect, so
it reconstructs each of the three ways this went wrong and requires each to be
caught.
"""
from __future__ import annotations

import unittest

from scripts.audit_named_controls import (
    build_corpus, named_controls, satisfied_by, normalise,
    strip_comments, label_corpus,
)


class EveryNamedControlExistsTests(unittest.TestCase):

    def setUp(self):
        self.corpus = build_corpus()
        self.rows = named_controls()

    def test_the_guard_has_something_to_check(self):
        """A guard matching nothing is not a passing guard.

        The narrow version keyed only on arrow glyphs, and when the last
        arrow-badge instruction was reworded it silently had no subjects left
        - which it reported, because that had already happened once.
        """
        self.assertGreater(len(self.rows), 0,
                           "no instructional control names found at all - "
                           "has the phrasing changed?")

    def test_every_control_the_app_names_is_one_it_renders(self):
        missing = [(f, n) for f, n in self.rows
                   if not satisfied_by(self.corpus, n)]
        self.assertEqual(
            [], missing,
            "the app tells someone to use a control that nothing renders: "
            + "; ".join("%s says %r" % (f, n) for f, n in missing))

    def test_it_reads_more_than_cloud_manager(self):
        """The whole point of this file. If it ever narrows back to one page,
        the cross-page instruction that started this goes unguarded again."""
        files = {f for f, _ in self.rows}
        self.assertGreater(
            len(files), 1,
            "only one file carries an instruction - this is back to the "
            "narrow guard it was written to replace")


class TheCheckCanFailTests(unittest.TestCase):
    """Each of the three ways a wider guard was got wrong, reconstructed.

    A check that cannot fail is the thing this repository has been bitten by
    most often, so these assert the failure rather than the success.
    """

    def test_a_control_that_is_renamed_away_is_caught(self):
        """The v2.150.0 defect itself: instruction on one page, control on
        another, and the control renamed out from under it."""
        corpus = normalise("<button>Cover image\u2026</button>")
        self.assertFalse(satisfied_by(corpus, "Edit report settings"))
        self.assertTrue(satisfied_by(corpus, "Cover image\u2026"))

    def test_a_comment_explaining_a_rename_is_not_taken_for_a_label(self):
        """The first failed attempt. `report.js` carries a comment saying why
        the button stopped being called "Edit report settings"; the old name
        is in it, in quotes, and it read as evidence the button still exists.
        """
        source = (
            "/* Renamed from 'Edit report settings' in v2.150.0, because it\n"
            "   opens one field rather than a settings screen. */\n"
            "var label = 'Cover image' + '\\u2026';\n"
        )
        corpus = normalise(label_corpus(strip_comments(source)))
        self.assertNotIn("Edit report settings", corpus,
                         "a comment was read as a control label")
        self.assertFalse(satisfied_by(corpus, "Edit report settings"))

    def test_a_url_inside_a_string_is_not_read_as_a_comment(self):
        """The trap in stripping comments with a regex: it eats the rest of
        the line, and the labels on it go with it."""
        source = "var a = 'https://example.invalid/x'; var b = 'Cover image';"
        kept = strip_comments(source)
        self.assertIn("Cover image", kept)
        self.assertIn("https://example.invalid/x", kept)

    def test_a_quote_inside_a_regular_expression_does_not_open_a_string(self):
        """This is the bug that made the first version of this guard useless,
        and it was in the stripper rather than in the idea.

        ``report.js`` really contains ``/[<>:"/\\\\|?*\\x00-\\x1f]/g``. A scanner
        that knows only about quotes sees that ``"``, decides a string has
        started, and never finds its end - so every comment after it in the
        file survives as though it were code, including the one naming the old
        button. The guard then read that comment as evidence the button still
        existed and passed on the very defect it was written for.
        """
        source = (
            'var clean = s.replace(/[<>:"/\\\\|?*]/g, " ");\n'
            "/* A comment after it, naming 'Edit report settings'. */\n"
            "var label = 'Cover image';\n"
        )
        kept = strip_comments(source)
        self.assertNotIn("Edit report settings", kept,
                         "the regex swallowed the scanner and the comment "
                         "survived as though it were code")
        self.assertIn("Cover image", kept, "the stripper ate real code")

    def test_a_division_is_not_mistaken_for_a_regular_expression(self):
        """The other half of that. Treating every slash as a regex would
        swallow real code and take labels with it."""
        source = "var ratio = width / height; var label = 'Cover image';"
        kept = strip_comments(source)
        self.assertIn("Cover image", kept)
        self.assertIn("width / height", kept)

    def test_the_stripper_leaves_report_js_readable(self):
        """The end-to-end version of both: the real file, and the real comment.

        If this ever passes while the comment survives, the guard is inert
        again and nothing else in this file would say so.
        """
        from pathlib import Path
        js = (Path(__file__).resolve().parent.parent
              / "web" / "assets" / "js" / "report.js").read_text(encoding="utf-8")
        stripped = strip_comments(js)
        self.assertEqual(
            1, js.count("Edit report settings"),
            "the comment this guards against has been reworded or duplicated "
            "- point it at another one, or drop this test rather than letting "
            "it pass on nothing")
        self.assertEqual(0, stripped.count("Edit report settings"),
                         "the comment survived the stripper")
        # And it did not simply delete the file.
        self.assertGreater(len(stripped), len(js) * 0.5)

    def test_the_instruction_does_not_satisfy_itself(self):
        """The second failed attempt. The page carrying "use <b>Name</b>"
        contains that string, so searching the page for it always succeeded."""
        from scripts.audit_named_controls import html_text
        page = "<p>Open Report and use <b>Edit report settings</b>.</p>"
        corpus = normalise(html_text(page))
        self.assertNotIn("Edit report settings", corpus)
        self.assertFalse(satisfied_by(corpus, "Edit report settings"))

    def test_a_label_built_by_concatenation_is_still_found(self):
        """Without this the guard fails on every correct instruction in the
        suite, which is worse than not having it - it would be turned off."""
        source = "h += '<button>' + 'Cover image' + '\\u2026' + '</button>';"
        corpus = normalise(label_corpus(strip_comments(source)))
        self.assertTrue(satisfied_by(corpus, "Cover image\u2026"))

    def test_a_route_is_satisfied_only_when_every_step_exists(self):
        """"Menu → About" is two controls and an instruction to open one then
        the other. Both have to be real; one of them being real is not enough.
        """
        both = normalise("<button>Menu</button><button>About</button>")
        self.assertTrue(satisfied_by(both, "Menu \u2192 About"))
        half = normalise("<button>Menu</button>")
        self.assertFalse(satisfied_by(half, "Menu \u2192 About"))

    def test_a_button_whose_own_label_carries_an_arrow_is_not_split_up(self):
        """"Cloud → Local" is one button. Splitting it and checking the halves
        would pass on a page that renders neither."""
        whole = normalise("<button>Cloud \u2192 Local</button>")
        self.assertTrue(satisfied_by(whole, "Cloud \u2192 Local"))
        halves = normalise("<button>Cloud</button><button>Local</button>")
        # It still passes as a route - which is correct, because a page with a
        # Cloud control and a Local control does let somebody follow it - but
        # the whole-string match has to be tried first or a renamed button
        # would be silently accepted by its own halves.
        self.assertTrue(satisfied_by(halves, "Cloud \u2192 Local"))
        self.assertFalse(satisfied_by(normalise("<button>Cloud</button>"),
                                      "Cloud \u2192 Local"))


class TheGatesThatLetTheFourthOneThroughTests(unittest.TestCase):
    """Quick Walls' tips panel said "Click **#** on any wall type" for seven
    minor versions after that button became the word **Set key**.

    This guard was already in the suite and green the whole time, because every
    gate in it was shut against that sentence at once:

    * it emphasised with ``<strong>`` and the pattern read only ``<b>``;
    * the verb was "Click" and the pattern read only "use";
    * and with neither an arrow nor "use", the name was never collected, so
      there was nothing to check against the corpus.

    Any one of the three would have been enough to miss it, which is why all
    three are asserted separately - a later narrowing of any single gate puts
    the same class of defect back, and the other two tests would still pass.

    Widening it turned up a fifth instance immediately: Cloud Manager's help
    told him to click "Link anyway" on a held-back row, and nothing in the app
    has ever rendered that. The real controls are "This is the one", "Not this
    one" and "None of these".
    """

    #: The sentence as it actually shipped, in `web/walls.html`, v2.115.0
    #: through v2.162.0.
    QUICK_WALLS = ('<p>Click <strong>#</strong> on any wall type to pick a '
                   'slot from a menu.</p>')

    def names_in(self, markup):
        from scripts.audit_named_controls import BOLD, USE_NAMED, ARROWS, EXTERNAL
        names = {m for m in BOLD.findall(markup)
                 if any(a in m for a in ARROWS)}
        names |= set(USE_NAMED.findall(markup))
        names -= set(EXTERNAL.findall(markup))
        return {normalise(n) for n in names}

    def test_the_sentence_that_got_through_is_collected_now(self):
        self.assertIn("#", self.names_in(self.QUICK_WALLS),
                      "the instruction that shipped for seven versions is "
                      "still invisible to this guard")

    def test_and_it_would_be_reported_missing(self):
        """Collected is not enough - it has to fail against a corpus where the
        button is the word it became."""
        corpus = normalise("<button>Set key</button><button>Key 3</button>")
        self.assertFalse(satisfied_by(corpus, "#"))
        self.assertTrue(satisfied_by(corpus, "Set key"))

    def test_strong_counts_as_naming_a_control(self):
        """Gate one. The pages emphasise with `<strong>`; `cloud.js` uses
        `<b>`, and the pattern was written against the file that had already
        been caught."""
        self.assertIn("Set key",
                      self.names_in("<p>Click <strong>Set key</strong>.</p>"))

    def test_more_than_one_verb_introduces_an_instruction(self):
        """Gate two. Reaching only "use" made the guard's scope an accident of
        how a sentence happened to be phrased."""
        for verb in ("Click", "Press", "Choose", "Select", "Pick", "Open",
                     "Tick", "Hit", "Tap", "Use"):
            with self.subTest(verb=verb):
                self.assertIn("Set key",
                              self.names_in(f"<p>{verb} <b>Set key</b>.</p>"))

    def test_an_intervening_word_does_not_hide_it(self):
        for phrase in ("Click the <b>Set key</b>", "Click on <b>Set key</b>"):
            with self.subTest(phrase=phrase):
                self.assertIn("Set key", self.names_in(f"<p>{phrase}.</p>"))

    def test_emphasis_that_is_not_an_instruction_is_left_alone(self):
        """The widening must not turn every bolded word into a control, or the
        guard becomes noise and gets switched off."""
        quiet = ("<p><b>Held back but you know better?</b> The row lists "
                 "candidates.</p>")
        self.assertEqual(set(), self.names_in(quiet))

    def test_a_control_in_another_program_can_be_opted_out(self):
        """The landing page tells people to tick **Add Python to PATH**, which
        is real, is in the Python installer, and is never going to be rendered
        here. The opt-out is on the sentence rather than in a list somewhere
        else, so it cannot drift away from the thing it excuses."""
        theirs = ('<p>tick <b data-external="Python installer">Add Python to '
                  'PATH</b> in the installer.</p>')
        self.assertEqual(set(), self.names_in(theirs))
        ours = "<p>tick <b>Add Python to PATH</b> in the installer.</p>"
        self.assertIn("Add Python to PATH", self.names_in(ours),
                      "the opt-out is being applied to everything")

    def test_the_help_panels_are_in_scope_now(self):
        """The end-to-end claim. `walls.html` carries instructional prose in a
        tips panel, and the guard has to be reading it."""
        rows = named_controls()
        files = {f for f, _ in rows}
        self.assertIn("web/walls.html", files,
                      "Quick Walls' tips panel is not being read")


class TheNarrowGuardStillAppliesTests(unittest.TestCase):
    """This widens the rule; it does not replace the original.

    The Cloud Manager version checks the same property against `cloud.js` with
    its own corpus, and two checks of one property that disagree is a state
    worth noticing rather than an argument for deleting one.
    """

    def test_the_cloud_manager_guard_is_still_in_the_suite(self):
        """Imported rather than looked for in the file, so a class that has
        been renamed away or left un-runnable fails here too."""
        import importlib
        mod = importlib.import_module("tests.test_cloud_push_is_reachable")
        cls = getattr(mod, "TheAppOnlyPointsAtControlsThatExistTests", None)
        self.assertIsNotNone(cls, "the Cloud Manager guard has gone")
        tests = [n for n in dir(cls) if n.startswith("test_")]
        self.assertTrue(tests, "it is there but has no tests in it")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
