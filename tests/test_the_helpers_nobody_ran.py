"""Eight small public functions, none of which any test had executed.

Backlog item 12. Small does not mean harmless: `scan_text` is rule zero's
detector, `default_roots` decides what a delete is allowed to look at, and
`parse_version` decides whether an update is offered at all. Each one is a
handful of lines, and a handful of lines is exactly what gets changed without
anybody running it.

One of these is worth pointing at directly. `housekeeping.scan_text` carries
the docstring *"Separate and public so the tests can exercise the detector
directly without building a file tree for every case"* - it was pulled out of
its caller for testing, and then no test ever called it. That is the shape the
audit was looking for.
"""
from __future__ import annotations

import logging
import os
import unittest
from pathlib import Path
from unittest import mock

from tools import applog, housekeeping, image_format, manual, share_recipients
from tools import updater
from tools.cloud_manager import human_size


class HumanSizeTests(unittest.TestCase):
    """What a row says a file weighs."""

    def test_the_units_change_at_the_right_thresholds(self):
        self.assertEqual("0 B", human_size(0))
        self.assertEqual("1 B", human_size(1))
        self.assertEqual("1023 B", human_size(1023))
        self.assertEqual("1 KB", human_size(1024))
        self.assertEqual("1024 KB", human_size(1048575))
        self.assertEqual("1.0 MB", human_size(1048576))

    def test_a_real_project_size_reads_sensibly(self):
        self.assertEqual("6.2 MB", human_size(6_500_000))

    def test_nothing_at_all_is_zero_rather_than_a_crash(self):
        """`if not b` catches None as well as 0, which is the point - a
        listing with no size on a row must not take the page down."""
        self.assertEqual("0 B", human_size(None))

    def test_megabytes_keep_one_decimal_and_kilobytes_keep_none(self):
        """Deliberate: 1.4 MB is a useful distinction and 879.3 KB is not."""
        self.assertEqual("1.4 MB", human_size(1_500_000))
        self.assertEqual("879 KB", human_size(900_000))


class ParseVersionTests(unittest.TestCase):
    """What decides whether an update is offered.

    `cmp_version` is tested elsewhere; this is the part that turns a tag into
    numbers, and it is forgiving on purpose because it is fed release tags,
    `versions.json` values and whatever a user has in an install folder.
    """

    def test_a_plain_version_becomes_a_tuple(self):
        self.assertEqual((2, 156, 0), updater.parse_version("2.156.0"))

    def test_a_leading_v_is_ignored(self):
        self.assertEqual((2, 156, 0), updater.parse_version("v2.156.0"))

    def test_nothing_usable_is_an_empty_tuple_rather_than_an_error(self):
        for text in (None, "", "   ", "not a version"):
            with self.subTest(text=text):
                self.assertEqual((), updater.parse_version(text))

    def test_an_empty_version_compares_below_everything(self):
        """The consequence of the line above, and the one that matters:
        an unreadable local version must not look newer than the release."""
        self.assertLess(updater.cmp_version("", "2.0.0"), 0)

    def test_it_takes_every_run_of_digits(self):
        self.assertEqual((1, 2, 3, 4), updater.parse_version("1.2.3-rc4"))


class LooksLikeEmailTests(unittest.TestCase):
    """The check in front of the one file rule zero singles out.

    `share_recipients.json` holds real colleagues' addresses. Every address
    here is invented at an RFC 2606 documentation domain.
    """

    def test_an_ordinary_address_is_accepted(self):
        for value in ("someone@example.com", "first.last@example.org",
                      "a+tag@sub.example.test"):
            with self.subTest(value=value):
                self.assertTrue(share_recipients.looks_like_email(value))

    def test_surrounding_whitespace_does_not_matter(self):
        self.assertTrue(share_recipients.looks_like_email("  x@example.com \n"))

    def test_something_that_is_not_an_address_is_refused(self):
        for value in ("", None, "   ", "someone", "someone@", "@example.com",
                      "someone@example", "two@signs@example.com",
                      "has space@example.com"):
            with self.subTest(value=value):
                self.assertFalse(share_recipients.looks_like_email(value))

    def test_classify_keeps_both_halves(self):
        """One malformed entry must not throw away four correct ones - the
        function's own docstring is the requirement."""
        result = share_recipients.classify(
            "ok@example.com, broken, also.ok@example.org")
        self.assertEqual(["ok@example.com", "also.ok@example.org"],
                         result["valid"])
        self.assertEqual(["broken"], result["invalid"])


class SaveModeTests(unittest.TestCase):
    """Which image modes have to be converted before a format will take them.

    Getting this wrong is a crash on save, in PlanTrim, on whichever format the
    user happened to have.
    """

    def test_a_format_that_cannot_hold_transparency_converts(self):
        self.assertEqual("RGB", image_format.save_mode("bmp", "RGBA"))
        self.assertEqual("L", image_format.save_mode("bmp", "LA"))

    def test_gif_goes_to_a_palette(self):
        for mode in ("RGBA", "RGB", "LA"):
            with self.subTest(mode=mode):
                self.assertEqual("P", image_format.save_mode("gif", mode))

    def test_a_mode_the_format_already_takes_is_left_alone(self):
        self.assertIsNone(image_format.save_mode("bmp", "RGB"))
        self.assertIsNone(image_format.save_mode("webp", "RGBA"))

    def test_an_unknown_format_leaves_the_image_alone(self):
        self.assertIsNone(image_format.save_mode("png", "RGBA"))
        self.assertIsNone(image_format.save_mode("tiff", "RGBA"))

    def test_the_format_name_is_case_insensitive(self):
        """Callers pass it from a file extension, which arrives however the
        user typed it."""
        self.assertEqual("RGB", image_format.save_mode("BMP", "RGBA"))
        self.assertEqual("P", image_format.save_mode("Gif", "RGBA"))


class GetLoggerTests(unittest.TestCase):

    def test_it_is_the_suite_s_own_logger(self):
        self.assertEqual(applog.LOGGER_NAME, applog.get_logger().name)

    def test_the_same_logger_comes_back_every_time(self):
        """Anything else and a handler installed once would not be seen by the
        next caller."""
        self.assertIs(applog.get_logger(), applog.get_logger())

    def test_it_is_not_the_root_logger(self):
        """The root sits at WARNING and `wd` at INFO deliberately, so library
        chatter cannot rotate the useful part out."""
        self.assertIsNot(applog.get_logger(), logging.getLogger())


class RenderTocTests(unittest.TestCase):
    """The manual's sidebar."""

    ENTRIES = [(2, "Cloud Manager", "cloud-manager"),
               (3, "When both sides have changed", "when-both-sides-have-changed"),
               (2, "Quick Walls", "quick-walls")]

    def test_every_entry_becomes_a_link_to_its_own_anchor(self):
        html = manual.render_toc(self.ENTRIES)
        self.assertIn('href="#cloud-manager"', html)
        self.assertIn('href="#when-both-sides-have-changed"', html)
        self.assertIn('href="#quick-walls"', html)

    def test_a_sub_heading_is_marked_and_a_top_one_is_not(self):
        lines = manual.render_toc(self.ENTRIES).split("\n")
        self.assertNotIn("manual-toc-sub", lines[0])
        self.assertIn("manual-toc-sub", lines[1])
        self.assertNotIn("manual-toc-sub", lines[2])

    def test_the_list_is_flat_rather_than_nested(self):
        """Nested lists would give the filter box a second problem: a parent
        that matches nothing still has to stay visible when a child does."""
        html = manual.render_toc(self.ENTRIES)
        self.assertNotIn("<ul", html)
        self.assertNotIn("<li", html)
        self.assertEqual(3, len(html.split("\n")))

    def test_a_heading_with_markup_in_it_is_rendered_not_printed(self):
        html = manual.render_toc([(2, "Use **Sync** first", "use-sync-first")])
        self.assertIn("<strong>Sync</strong>", html)

    def test_no_entries_is_an_empty_string_rather_than_an_error(self):
        self.assertEqual("", manual.render_toc([]))


class ScanTextTests(unittest.TestCase):
    """Rule zero's detector, pulled out for testing and then never tested.

    Its own docstring says it is "separate and public so the tests can exercise
    the detector directly". This is that.
    """

    def test_clean_text_scores_nothing(self):
        for text in ("", "a perfectly ordinary sentence",
                     "Project Example Campus, floor 3"):
            with self.subTest(text=text[:30]):
                self.assertEqual(0, housekeeping.scan_text(text))

    def test_a_documentation_domain_is_not_a_hit(self):
        """Every address in this repository is at an RFC 2606 domain, so they
        must not light up the scanner that looks for real ones."""
        self.assertEqual(0, housekeeping.scan_text(
            "write to someone@example.com or other@example.org"))

    def test_an_address_at_an_unknown_domain_is_a_hit(self):
        """`.test` is the right TLD for this and `example.com` is not.

        RFC 2606 reserves `.test`, so rule zero's own scanner allows it - but
        `housekeeping._ALLOWED_EMAIL_DOMAINS` lists the `example.*` domains
        by name and does not include it. That gap is what lets a fixture be
        both harmless in the repository and a hit for the detector under test.
        An `example.com` address here would pass the detector and prove
        nothing.
        """
        self.assertGreaterEqual(
            housekeeping.scan_text("contact person@a-company-we-invented.test"), 1)

    def test_hits_accumulate_rather_than_saturating(self):
        one = housekeeping.scan_text("a@one-invented-domain.test")
        two = housekeeping.scan_text(
            "a@one-invented-domain.test and b@two-invented.test")
        self.assertGreater(two, one)

    def test_it_is_fast_on_a_long_run_with_no_match(self):
        """The bounded-quantifier lesson, kept executable.

        The obvious email pattern backtracks quadratically on a long run of its
        own character class with no `@` in it - which is what a log file is.
        One 393 KB file took 163 seconds and the first real survey never
        finished. This is the same shape, and it has to stay quick.
        """
        import time
        blob = "abcdefghijklmnopqrstuvwxyz0123456789." * 8000   # no @ anywhere
        started = time.monotonic()
        housekeeping.scan_text(blob)
        self.assertLess(time.monotonic() - started, 5.0,
                        "the scanning regex has lost its bounds")


class DefaultRootsTests(unittest.TestCase):
    """Where housekeeping is allowed to look.

    The failure direction here is toward deleting more, which is why the
    module returns a dict a test can redirect rather than hard-coded paths.
    """

    def test_it_names_every_root_the_caller_expects(self):
        roots = housekeeping.default_roots()
        self.assertEqual({"worktrees", "temp", "scratch", "desktop",
                          "downloads"}, set(roots))

    def test_every_root_is_a_path(self):
        for name, value in housekeeping.default_roots().items():
            with self.subTest(root=name):
                self.assertIsInstance(value, Path)

    def test_the_scratch_root_sits_inside_the_temp_root(self):
        """Not beside it. A sibling of `%TEMP%` is a sibling of the whole
        user profile on some machines."""
        roots = housekeeping.default_roots()
        self.assertEqual(roots["temp"], roots["scratch"].parent)

    def test_the_temp_root_follows_the_environment(self):
        with mock.patch.dict(os.environ, {"TEMP": "Z:/scratch-temp"},
                             clear=False):
            roots = housekeeping.default_roots()
        self.assertEqual(Path("Z:/scratch-temp"), roots["temp"])

    def test_no_root_is_a_drive_root(self):
        """`C:/` as a root is how a scan came to walk the whole drive. The
        parent of a worktree directory near the top of a drive is the drive.
        """
        for name, value in housekeeping.default_roots().items():
            with self.subTest(root=name):
                self.assertNotEqual(value, value.parent,
                                    "%s is a filesystem root" % name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
