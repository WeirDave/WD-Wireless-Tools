"""A bulk button that is off has to say why, and until now none of them could.

`updateBulkBar` writes six careful explanations - "Select 2+ local folders to
compare", "Bulk delete only works on cloud-only or local-only rows", and so on.
Every one of them went into `el.dataset.disabledTitle`, which nothing in
`cloud.js`, nothing in `wd-tools.css` and nothing in the tooltip delegation
ever read. The greyed button was the whole message.

The attribute was not the only problem. The buttons were disabled with the DOM
`disabled` property, and a disabled button emits no pointer events at all - so
even putting the reason in `title` would not have shown it, and clicking to ask
was impossible by construction. That is why the fix is `aria-disabled` plus a
class: it greys the same way and still announces as unavailable, while leaving
the element hoverable and clickable so the reason can be reached.

Verified in Firefox as well as here: with nothing selected every bulk button
reads `aria-disabled="true"`, `opacity: 0.5`, `cursor: not-allowed`; a real
mouse click on "Overwrite from cloud..." raises the toast "Select one or more
Name-matches pairs to verify (download cloud - overwrite local)" and does NOT
open the confirm behind it.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"


class TheReasonIsReachable(unittest.TestCase):

    def setUp(self):
        self.source = CLOUD_JS.read_text(encoding="utf-8")
        # The comments explain what the old code did, in the old code's own
        # words, so "is it gone" is a question about the code only.
        self.code = re.sub(r"/\*.*?\*/", "", self.source, flags=re.S)
        self.code = re.sub(r"^\s*//.*$", "", self.code, flags=re.M)
        self.set_btn = self.code[self.code.index("const setBtn = (id,"):]
        self.set_btn = self.set_btn[:self.set_btn.index("\n  };") + 4]

    def test_the_reason_goes_somewhere_that_is_rendered(self):
        """`title` is read by the browser. `dataset.disabledTitle` was read by
        nothing at all."""
        self.assertIn("el.title", self.set_btn)
        self.assertNotIn("dataset.disabledTitle", self.code)

    def test_a_disabled_bulk_button_still_receives_events(self):
        """The DOM `disabled` property is what made the reason unreachable:
        no hover, no click, no tooltip."""
        self.assertIn("el.disabled = false;", self.set_btn)
        self.assertNotIn("el.disabled = !enabled;", self.code)
        self.assertIn("aria-disabled", self.set_btn)

    def test_the_button_still_announces_itself_as_unavailable(self):
        """Dropping `disabled` without this would leave a control that reads as
        available to a screen reader and does nothing."""
        self.assertIn("el.setAttribute('aria-disabled', enabled ? 'false' : 'true')",
                      self.set_btn)

    def test_the_enabled_tooltip_is_not_lost_when_it_comes_back(self):
        """The old version only ever wrote `title` and never restored it, so a
        button that went off and on again kept whichever text it last had."""
        self.assertIn("dataset.baseTitle", self.set_btn)

    def test_clicking_a_disabled_button_is_intercepted_before_its_handler(self):
        """Each of these has an inline onclick. A capture-phase listener on the
        document runs before the target's own handler, and stopPropagation
        there is what keeps the real action from firing."""
        block = self.code[self.code.index("function _wireDisabledBulkReasons"):]
        block = block[:block.index("_wireDisabledBulkReasons();")]
        self.assertIn("'.bulk-btn.is-disabled'", block)
        self.assertIn("ev.stopPropagation()", block)
        self.assertIn("ev.preventDefault()", block)
        self.assertIn("}, true);", block)      # capture phase, not bubble
        self.assertIn("toast(btn.title", block)

    def test_the_guard_is_actually_installed(self):
        self.assertIn("\n_wireDisabledBulkReasons();", self.source)


class ItStillLooksDisabled(unittest.TestCase):
    """Swapping `disabled` for an attribute must not quietly make an unusable
    button look usable."""

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")

    def test_aria_disabled_buttons_are_greyed_and_show_the_right_cursor(self):
        block = self.css[self.css.index('.btn[aria-disabled="true"] {'):]
        block = block[:block.index("}")]
        self.assertIn("opacity: var(--opacity-disabled)", block)
        self.assertIn("cursor: not-allowed", block)

    def test_they_do_not_lift_on_hover_like_a_live_button(self):
        self.assertIn('.btn[aria-disabled="true"]:hover', self.css)
        block = self.css[self.css.index('.btn[aria-disabled="true"]:hover'):]
        block = block[:block.index("}")]
        self.assertIn("transform: none", block)
        self.assertIn("box-shadow: none", block)

    def test_the_disabled_opacity_matches_the_attribute_version(self):
        """Two different greys for the same state would read as two states."""
        native = re.search(r"\.btn:disabled \{([^}]*)\}", self.css).group(1)
        self.assertIn("var(--opacity-disabled)", native)


class EveryDisabledStateNamesWhatToDo(unittest.TestCase):
    """A reason that only restates the rule leaves him no next move. Each one
    has to name the selection that would switch the button on."""

    def test_each_bulk_button_has_a_disabled_reason(self):
        source = CLOUD_JS.read_text(encoding="utf-8")
        block = source[source.index("const setBtn = (id,"):source.index("\nfunction isProjectSyncItem")]
        for btn in ("bulkSyncTo", "bulkSyncFrom", "bulkVerifyBtn", "bulkShareBtn",
                    "bulkDeleteBtn", "compareBtn", "bulkMoveBtn"):
            with self.subTest(button=btn):
                call = block[block.index(f"setBtn('{btn}'"):]
                call = call[:call.index(");")]
                # Third argument onwards is the reason; a bare gate with no
                # explanation is the state this file exists to prevent.
                self.assertRegex(call, r"'[^']{15,}'",
                                 f"{btn} is gated with no reason to show")


if __name__ == "__main__":
    unittest.main()
