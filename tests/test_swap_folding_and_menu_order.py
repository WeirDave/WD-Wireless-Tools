"""Two things he asked for by name, neither of which had a test.

**"quick walls visual swap need expand all collapse all and should be collapsed
by default please"** and **"in the main menu sort items alphabetically"**. Both
shipped - the folding in v2.103.2, the menu order in v2.103.5 - and nothing in
the suite would have noticed either one going away again.

The folding half is guarded on two axes on purpose, because it has already
failed on the axis that was not being checked. Thirteen state assertions passed
while "Collapse all" rendered *underneath* the count badge, in a crushed header
nobody could use - state was right and the layout was not. So the geometry is
asserted here as well as the behaviour: the controls get their own row, the row
sits clear of the badge, and the badge is not allowed to grow into a block.

The menu half drives the real `WD.sortNavMenus` in Node against a deliberately
shuffled menu. Sorting happens at runtime, so reading the HTML proves nothing
about the order anyone actually sees - the function has to be run.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALLS_HTML = (ROOT / "web" / "walls.html").read_text(encoding="utf-8")
SWAP_JS = (ROOT / "web" / "assets" / "js" / "walls-swap.js").read_text(encoding="utf-8")
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"
CSS = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")

NODE_TIMEOUT_S = 120


class TheSelectionOpensCollapsed(unittest.TestCase):
    """"should be collapsed by default" - the default is the whole request."""

    def test_the_state_records_what_is_open_not_what_is_shut(self):
        """The flag is `expandedTypes`, and that direction matters.

        With a `collapsedTypes` set, a group is open unless something has
        explicitly closed it - so every newly-selected group defaults to open
        and the request is inverted. Nothing is closed at the moment a
        selection is made, which is exactly when the default applies.
        """
        self.assertIn("expandedTypes", SWAP_JS)
        self.assertNotIn(
            "collapsedTypes", SWAP_JS,
            "the fold state has been inverted back to recording what is shut, "
            "which makes a fresh selection open by default")

    def test_a_new_selection_starts_with_nothing_expanded(self):
        marker = "state.expandedTypes.clear();"
        self.assertIn(
            marker, SWAP_JS,
            "nothing clears the expanded set, so a new selection inherits "
            "whatever the last one had open")

    def test_toggling_one_group_keeps_the_screen_reader_in_step(self):
        fn = SWAP_JS[SWAP_JS.index("window.toggleSwapGroupCollapse"):][:1200]
        self.assertIn("aria-expanded", fn)
        self.assertIn("updateCollapseAllButton()", fn,
                      "folding one group has to re-decide whether Expand all "
                      "and Collapse all are still available")


class BothFoldAllControlsExist(unittest.TestCase):

    def setUp(self):
        self.row = re.search(r'<div class="swap-foldall">(.*?)</div>',
                             WALLS_HTML, re.S)
        self.assertIsNotNone(self.row, "the fold-all row is gone from walls.html")

    def test_two_named_buttons_rather_than_one_that_changes_its_mind(self):
        """A single toggle cannot express the half-open case.

        It read "Collapse all" whenever anything was open, so asking for the
        other one meant pressing it twice and watching what happened.
        """
        block = self.row.group(1)
        for btn_id, label, handler in (
                ("swapExpandAllBtn", "Expand all", "expandAllSwapGroups"),
                ("swapCollapseAllBtn", "Collapse all", "collapseAllSwapGroups")):
            with self.subTest(button=label):
                self.assertIn(f'id="{btn_id}"', block)
                self.assertIn(f">{label}</button>", block)
                self.assertIn(f'data-fn="{handler}"', block)
                self.assertIn(f"window.{handler} =", SWAP_JS,
                              f"{handler} has no handler behind it")

    def test_each_starts_disabled_because_nothing_is_selected_yet(self):
        block = self.row.group(1)
        self.assertEqual(block.count(" disabled"), 2,
                         "a fold-all button is live before there is anything "
                         "to fold")

    def test_each_is_disabled_exactly_when_it_would_do_nothing(self):
        fn = SWAP_JS[SWAP_JS.index("function updateCollapseAllButton"):][:900]
        self.assertIn("anyShut", fn)
        self.assertIn("anyOpen", fn)
        self.assertRegex(fn, r"expandBtn\.disabled\s*=\s*!keys\.length\s*\|\|\s*!anyShut")
        self.assertRegex(fn, r"collapseBtn\.disabled\s*=\s*!keys\.length\s*\|\|\s*!anyOpen")


class TheControlsGetTheirOwnRow(unittest.TestCase):
    """The defect that thirteen passing state assertions did not see.

    "Collapse all" was laid out into the panel header beside the count badge
    and rendered underneath it. Measured in a browser afterwards: the badge had
    stretched to the full height of the header. These are the source-level
    conditions for that not recurring; the measurement itself needs a browser
    and was run in Chrome, Edge and Firefox (badge 19-20px, buttons side by
    side on a row of their own, clear of the badge).
    """

    def test_the_row_is_its_own_flex_line_outside_the_header(self):
        rule = re.search(r"\.swap-foldall\s*\{([^}]*)\}", CSS)
        self.assertIsNotNone(rule, ".swap-foldall has no rule")
        self.assertIn("flex", rule.group(1))
        self.assertNotIn("swap-foldall", re.search(
            r'<div class="swap-panel-header">(.*?)</div>', WALLS_HTML, re.S).group(1),
            "the fold-all controls are back inside the panel header, which is "
            "where they were crushed under the count badge")

    def test_the_count_badge_cannot_stretch(self):
        rule = re.search(r"\.swap-sel-count\s*\{([^}]*)\}", CSS)
        self.assertIsNotNone(rule, ".swap-sel-count has no rule")
        body = rule.group(1)
        self.assertIn("flex: 0 0 auto", body,
                      "the badge is allowed to flex again - it grew to the "
                      "full header height last time")
        self.assertIn("nowrap", body)


class TheNavigationMenuIsAlphabetical(unittest.TestCase):
    """Driven, not read. The order is produced at runtime by sortNavMenus."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node is not installed")

    def _run(self, script: str):
        # encoding is explicit: Node prints the real U+25B8 for the section
        # markers, and Windows' default cp1252 decode turns them into
        # something that compares equal to nothing.
        proc = subprocess.run(
            [self.node, "-e", script, str(SHARED_JS)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            self.fail(proc.stderr.strip() or proc.stdout.strip())
        return proc.stdout.strip()

    #: A menu in the order pages used to carry it, with the Tools and Help
    #: blocks below the separator that the sort must not reach into.
    SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('WD.sortNavMenus = function');
const b = src.indexOf('WD.toggleMenu = function', a);
if (a < 0 || b < 0) throw new Error('sortNavMenus is not in wd-shared.js');
const WD = {};
eval(src.slice(a, b));

// A DOM with just what the function reaches for.
function el(tag, className, text, href) {
  return {
    tagName: tag, className: className || '', textContent: text || '',
    _href: href || null,
    getAttribute(n) { return n === 'href' ? this._href : null; },
    classList: { contains: (c) => (className || '').split(/\s+/).indexOf(c) >= 0 },
    parentNode: null,
  };
}
const kids = [
  el('DIV', 'menu-section', '▸ Navigation'),
  el('A', 'menu-item', '⌂ Home', '/'),
  el('A', 'menu-item', '· Cloud Manager', '/cloud'),
  el('A', 'menu-item', '· Quick Walls', '/walls'),
  el('A', 'menu-item', '· Report', '/report'),
  el('A', 'menu-item', '· Scale', '/scale'),
  el('A', 'menu-item', '· PlanTrim', '/plantrim'),
  el('A', 'menu-item', '· AP Labeler', '/aprename'),
  el('A', 'menu-item', '· Capacity', '/capacity'),
  el('A', 'menu-item', '· Prep', '/prep'),
  el('A', 'menu-item', '· Squirrel', '/squirrel'),
  el('DIV', 'menu-sep', ''),
  el('DIV', 'menu-section', '▸ Tools'),
  el('A', 'menu-item', '· Suite Settings', '/settings'),
  el('DIV', 'menu-sep', ''),
  el('DIV', 'menu-section', '▸ Help'),
  el('A', 'menu-item', '· User Manual', '/manual'),
  el('A', 'menu-item', '· Report a Bug', 'https://example.com/issues'),
];
const parent = {
  children: kids,
  insertBefore(node, ref) {
    // The real DOM treats "insert before yourself" as leaving you where you
    // are. Removing first and then looking the reference up loses it, and
    // every item lands at the end of the menu.
    if (ref === node) return;
    const at = this.children.indexOf(node);
    if (at >= 0) this.children.splice(at, 1);
    const to = ref ? this.children.indexOf(ref) : this.children.length;
    this.children.splice(to < 0 ? this.children.length : to, 0, node);
  },
};
kids.forEach(k => {
  k.parentNode = parent;
  // Both names: the walk uses nextElementSibling and the reinsertion uses
  // nextSibling. With only the first defined, every item is appended to the
  // end of the menu instead of after the heading - which is what happened.
  for (const prop of ['nextElementSibling', 'nextSibling']) {
    Object.defineProperty(k, prop, {
      get() { return parent.children[parent.children.indexOf(this) + 1] || null; },
    });
  }
});
const root = {
  querySelectorAll: (sel) => parent.children.filter(
    k => (k.className || '').split(/\s+/).indexOf(sel.replace('.', '')) >= 0),
};

WD.sortNavMenus(root);
console.log(JSON.stringify(parent.children.map(k => k.textContent)));
"""

    def test_home_is_pinned_first_and_the_tools_sort_after_it(self):
        order = json.loads(self._run(self.SCRIPT))
        nav = [t.lstrip("·⌂▸ ").strip()
               for t in order[1:order.index("▸ Tools") - 1]]
        self.assertEqual(
            nav,
            ["Home", "AP Labeler", "Capacity", "Cloud Manager", "PlanTrim",
             "Prep", "Quick Walls", "Report", "Scale", "Squirrel"],
            "the navigation block is not Home-then-alphabetical")

    def test_it_does_not_reach_past_the_separator(self):
        """Tools and Help are separate blocks their authors arranged."""
        order = json.loads(self._run(self.SCRIPT))
        tail = order[order.index("▸ Tools"):]
        self.assertEqual(
            [t.lstrip("·▸ ").strip() for t in tail],
            ["Tools", "Suite Settings", "", "Help", "User Manual", "Report a Bug"],
            "the sort has reordered a block below the separator")

    def test_every_page_runs_the_sort(self):
        """A function nothing calls sorts nothing."""
        shared = SHARED_JS.read_text(encoding="utf-8")
        self.assertIn("WD.sortNavMenus()", shared,
                      "sortNavMenus is defined and never called")
        pages = [p for p in (ROOT / "web").glob("*.html")
                 if "menu-section" in p.read_text(encoding="utf-8")]
        self.assertGreater(len(pages), 10)
        missing = [p.name for p in pages
                   if "wd-shared.js" not in p.read_text(encoding="utf-8")]
        self.assertEqual(missing, [],
                         f"pages whose menu is never sorted: {missing}")


if __name__ == "__main__":
    unittest.main()
