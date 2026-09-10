"""The AP Labeler sidebar has to work in a small window.

The panel carries the naming pattern, scope, ordering, the colour sequence
(which grows with the project), the manual numbering controls and the preview.
It was one long `overflow-y: auto` column, and that is subtly the wrong shape:
`.ar-preview` is `flex:1`, so inside a scrolling parent it never gets a bounded
height. Its own scrollbar therefore never engaged, the table grew to whatever
the project needed, and Undo went below the fold part-way through a manual run.

So: the settings scroll, and the preview and numbering controls are docked and
stay put. `min-height:0` on the scroller is what lets a flex child actually
shrink rather than being sized by its content.

Folding comes from wd-shared.js, the same implementation Quick Walls uses -
two copies writing to localStorage is two chances to disagree about the key.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AP_HTML = ROOT / "web" / "ap-rename.html"
AP_JS = ROOT / "web" / "assets" / "js" / "ap-rename.js"
WALLS_JS = ROOT / "web" / "assets" / "js" / "walls-swap.js"
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"


class TheSettingsScrollAndTheControlsStay(unittest.TestCase):

    def setUp(self):
        self.html = AP_HTML.read_text(encoding="utf-8")

    def test_the_sidebar_itself_no_longer_scrolls(self):
        """A single scrolling column is what stopped the preview being
        bounded, so the column holds two regions instead."""
        rule = re.search(r"\.tool-aprename \.ar-sidebar \{[^}]*\}", self.html).group(0)
        self.assertIn("overflow:hidden", rule)
        self.assertNotIn("overflow-y:auto", rule)

    def test_the_scroll_region_can_actually_shrink(self):
        """Without min-height:0 a flex child is sized by its content and the
        overflow never engages - which is the whole bug, one level down."""
        rule = re.search(r"\.tool-aprename \.ar-side-scroll \{[^}]*\}", self.html).group(0)
        self.assertIn("min-height:0", rule)
        self.assertIn("overflow-y:auto", rule)

    def test_the_preview_is_bounded_so_it_scrolls_instead_of_growing(self):
        rule = re.search(r"\.tool-aprename \.ar-side-dock \.ar-preview \{[^}]*\}",
                         self.html).group(0)
        self.assertIn("max-height", rule)

    def test_the_numbering_controls_are_docked_not_scrolled(self):
        """Losing Undo below the fold during a long manual run is the
        frustration this panel rework is about."""
        dock = self.html[self.html.index('<div class="ar-side-dock">'):]
        self.assertIn('id="arManualPanel"', dock)
        self.assertIn('id="arManualUndo"', dock)
        self.assertIn('id="arManualClear"', dock)
        self.assertIn('id="arManualNext"', dock)
        self.assertIn('id="arPreview"', dock)

    def test_the_preview_header_stays_put_while_the_rows_scroll(self):
        rule = re.search(r"\.tool-aprename \.ar-preview th\s*\{[^}]*\}", self.html).group(0)
        self.assertIn("position:sticky", rule)


class FoldingIsOneImplementation(unittest.TestCase):

    def test_the_labeler_sections_fold(self):
        html = AP_HTML.read_text(encoding="utf-8")
        for key in ("pattern", "scope", "ordering"):
            with self.subTest(section=key):
                self.assertIn('data-fold="%s"' % key, html)
        self.assertIn("data-fold-toggle", html)

    def test_both_tools_use_the_shared_one(self):
        self.assertIn("WD.mountFolds = function", SHARED_JS.read_text(encoding="utf-8"))
        self.assertIn("WD.mountFolds({", AP_JS.read_text(encoding="utf-8"))
        self.assertIn("WD.mountFolds({", WALLS_JS.read_text(encoding="utf-8"))

    def test_neither_tool_kept_a_private_copy(self):
        walls = WALLS_JS.read_text(encoding="utf-8")
        self.assertNotIn("function readFolded()", walls)
        self.assertNotIn("function writeFolded(", walls)

    def test_folded_sections_survive_a_reload(self):
        """A Set has no length, so [].slice.call(set) returns an empty array -
        every fold persisted as "nothing folded" and nothing ever stayed shut."""
        shared = SHARED_JS.read_text(encoding="utf-8")
        block = shared[shared.index("WD.mountFolds = function"):]
        block = block[:block.index("WD.mountSplitter")]
        self.assertIn("Array.from(set)", block)
        self.assertNotIn("[].slice.call(set)", block)

    def test_a_fold_header_is_reachable_without_a_mouse(self):
        html = AP_HTML.read_text(encoding="utf-8")
        head = html[html.index('data-fold="pattern"'):]
        head = head[:head.index("</div>")]
        self.assertIn('tabindex="0"', head)
        self.assertIn('role="button"', head)


class ShowAllWasNeverWired(unittest.TestCase):
    """renderPreviewTable takes the items; _arShowAll called it bare, so it
    threw on the first line and the button did nothing at all - silently, on
    every project, for as long as it has existed."""

    def test_show_all_passes_the_items(self):
        source = AP_JS.read_text(encoding="utf-8")
        block = source[source.index("window._arShowAll = function"):]
        block = block[:block.index("};")]
        self.assertIn("renderPreviewTable(S.preview", block)
        self.assertNotIn("renderPreviewTable();", block)


class TheLabelerResizesLikeQuickWalls(unittest.TestCase):
    """Quick Walls has a draggable, persisted-width splitter. The Labeler
    having one too is the consistency rule, not a nicety."""

    def test_the_splitter_is_mounted_from_the_shared_implementation(self):
        source = AP_JS.read_text(encoding="utf-8")
        self.assertIn("WD.mountSplitter({", source)
        self.assertIn("splitter: 'arSplitter'", source)
        self.assertIn("key: 'wd.aprename.sidebarWidth'", source)


if __name__ == "__main__":
    unittest.main()
