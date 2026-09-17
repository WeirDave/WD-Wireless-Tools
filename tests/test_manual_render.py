"""The user manual has to be reachable, complete, and readable on a wide screen.

Two bugs are held here, both reported the same day after the manual was opened
for the first time.

1. **Home's "User Manual" link opened one tool's guide.** It pointed at
   `/guide`, which is the Quick Walls guide. Nine tools are documented in
   `docs/USER_MANUAL.md` and no route served that file at all, so the manual
   was unreachable from inside the product that ships it.

2. **The page was a narrow strip.** `.guide-content` pins its column to a
   fixed width, which on a large monitor leaves most of the display empty -
   "completely ridiculous and terrible UX", and the reason `/manual` is a
   two-column layout with a contents rail rather than another centred column.

The rest guards the converter in `tools/manual.py`, which exists because the
install has no markdown library in Python or in the vendored JS. It handles
the subset the manual uses; these tests are what says so when the manual grows
something it does not handle.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import manual as manual_render  # noqa: E402

MANUAL_MD = manual_render.MANUAL_PATH.read_text(encoding="utf-8")
HOME = (ROOT / "web" / "home.html").read_text(encoding="utf-8")
SHELL = (ROOT / "web" / "manual.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")


class TheManualIsReachable(unittest.TestCase):
    """Bug 1. A document nobody can open is not documentation."""

    def test_home_links_to_the_manual_and_not_to_one_tools_guide(self):
        link = re.search(r'<a[^>]*href="([^"]+)"[^>]*>User Manual</a>', HOME)
        self.assertIsNotNone(link, "Home has no User Manual link at all")
        self.assertEqual(
            link.group(1), "/manual",
            "Home's User Manual link points somewhere else. It pointed at "
            "/guide once, which is the Quick Walls guide - one tool of nine.")

    def test_the_server_serves_the_manual(self):
        self.assertIn('@app.route("/manual")', SERVER)

    def test_every_tool_page_can_reach_the_manual(self):
        """Each tool's Help menu offers the manual, at that tool's section.

        The per-tool guides only cover five tools; the manual covers all of
        them. A tool with neither is a dead end for anyone looking for help
        while they are standing in it.
        """
        # setup.html is the first-run page and deliberately has no menu at
        # all; the suite's own menu test exempts it for the same reason.
        pages = sorted(p for p in (ROOT / "web").glob("*.html")
                       if p.name not in ("manual.html", "setup.html"))
        missing = [p.name for p in pages
                   if "/manual" not in p.read_text(encoding="utf-8")]
        self.assertEqual(missing, [],
                         f"pages with no route to the manual: {missing}")


class TheManualUsesTheScreen(unittest.TestCase):
    """Bug 2. The complaint was a long narrow strip on a large monitor."""

    def test_the_layout_is_a_contents_rail_beside_the_article(self):
        block = re.search(r"\.manual-layout\s*\{([^}]*)\}", CSS)
        self.assertIsNotNone(block, ".manual-layout has no rule")
        body = block.group(1)
        self.assertIn("grid", body)
        self.assertRegex(body, r"grid-template-columns:\s*\d+px\s+minmax",
                         "the rail-plus-article grid is gone")

    def test_the_article_is_not_pinned_to_the_guide_pages_narrow_column(self):
        block = re.search(r"\.manual-article\s*\{([^}]*)\}", CSS)
        self.assertIsNotNone(block, ".manual-article has no rule")
        self.assertRegex(
            block.group(1), r"max-width:\s*none",
            "the manual article has picked up a fixed width again - that is "
            "the bug this page was built to fix")

    def test_the_sidebar_stays_put_while_the_article_scrolls(self):
        block = re.search(r"\.manual-toc\s*\{([^}]*)\}", CSS)
        self.assertIsNotNone(block)
        self.assertIn("sticky", block.group(1),
                      "a contents rail that scrolls away is a contents list")

    def test_the_shell_has_both_substitution_markers(self):
        self.assertIn(manual_render.TOC_MARKER, SHELL)
        self.assertIn(manual_render.BODY_MARKER, SHELL)


class TheConverterHandlesWhatTheManualContains(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html, cls.headings = manual_render.render_markdown(MANUAL_MD)
        cls.toc = manual_render.contents_headings(cls.headings)

    def test_every_tag_it_opens_it_closes(self):
        """Unbalanced markup does not error, it just renders wrong."""
        for tag in ("ul", "ol", "li", "table", "thead", "tbody", "tr",
                    "blockquote", "p", "pre", "code", "strong", "em"):
            with self.subTest(tag=tag):
                opened = len(re.findall(rf"<{tag}[ >]", self.html))
                closed = len(re.findall(rf"</{tag}>", self.html))
                self.assertEqual(opened, closed, f"<{tag}> is unbalanced")

    def test_no_markdown_survives_into_the_output(self):
        """Asterisks on screen are what a half-converted document looks like."""
        self.assertNotIn("**", self.html, "unconverted bold markers")
        self.assertNotIn("\x00", self.html, "an inline placeholder leaked")
        self.assertEqual(re.findall(r"^#{1,6} ", self.html, re.M), [],
                         "unconverted headings")

    def test_bold_that_spans_a_line_wrap_still_converts(self):
        """The first version rendered list items one line at a time.

        A hard-wrapped file puts emphasis across the break constantly, and
        `**Sending it up is not built` / `  yet.**` came out with the
        asterisks showing. This is that case, reduced - the continuation
        is indented, which is the shape the manual uses and the shape
        `_list()` requires.
        """
        html, _ = manual_render.render_markdown(
            "- **Local newer** - yours is newer. **Sending it up\n"
            "  is not built yet.**")
        self.assertNotIn("**", html)
        self.assertIn("<strong>Sending it up is not built yet.</strong>", html)

    def test_every_in_page_link_lands_on_something(self):
        """The manual's own Contents list is 17 links into its own headings."""
        ids = set(re.findall(r'id="([^"]+)"', self.html))
        broken = sorted({a for a in re.findall(r'href="#([^"]+)"', self.html)
                         if a not in ids})
        self.assertEqual(broken, [], f"dead in-page links: {broken}")

    def test_the_contents_rail_lists_every_section(self):
        want = {m.strip() for m in re.findall(r"^## (.+)$", MANUAL_MD, re.M)}
        want -= {"User Manual", "Contents"}   # the title block, not a section
        have = {text for level, text, _ in self.toc if level == 2}
        self.assertEqual(want - have, set(),
                         f"sections missing from the rail: {sorted(want - have)}")

    def test_the_rail_does_not_list_the_title_block(self):
        have = {text for _, text, _ in self.toc}
        self.assertNotIn("Contents", have)
        self.assertNotIn("User Manual", have)

    def test_the_page_makes_no_third_party_requests(self):
        """A local-first tool should not fetch a "telemetry: none" badge.

        The manual carries three shields.io badges for GitHub's benefit.
        Serving them in-app would have the page that promises the tool talks to
        nobody talk to somebody to say so.
        """
        page = manual_render.render_page(MANUAL_MD, SHELL)
        remote = re.findall(r'<img[^>]+src="(https?://[^"]+)"', page)
        self.assertEqual(remote, [], f"remote images on the manual page: {remote}")

    def test_paths_written_for_githubs_view_are_rewritten(self):
        page = manual_render.render_page(MANUAL_MD, SHELL)
        self.assertNotIn("../web/", page)
        self.assertNotIn("../README.md", page)
        self.assertIn('src="/assets/', page)

    def test_the_tool_images_at_the_top_survive(self):
        """They are raw HTML in the markdown, which is a separate path."""
        page = manual_render.render_page(MANUAL_MD, SHELL)
        self.assertGreaterEqual(page.count('<img src="/assets/'), 5)

    def test_headings_are_anchored_with_githubs_slug_rule(self):
        """The manual links to `#data-privacy-and-security` in its own text."""
        self.assertEqual(manual_render._slug("Data, Privacy, and Security"),
                         "data-privacy-and-security")
        self.assertEqual(manual_render._slug("AP Labeler"), "ap-labeler")

    def test_a_missing_marker_is_an_error_rather_than_a_blank_page(self):
        with self.assertRaises(ValueError):
            manual_render.render_page("# Hi", "<html><body></body></html>")


class TheRenderedPageIsWhatTheRouteReturns(unittest.TestCase):

    def test_the_served_page_carries_the_manual(self):
        page = manual_render.render_page()
        self.assertIn('id="manualArticle"', page)
        self.assertIn('id="manualTocList"', page)
        for section in ("Quick Walls", "AP Labeler", "Troubleshooting"):
            with self.subTest(section=section):
                self.assertIn(f'>{section}<', page)


if __name__ == "__main__":
    unittest.main()
