"""The list, after the design pass - the properties, not the paint.

"it just needs to look and feel Pro level." It sits next to Ekahau AI Pro on
his screen all day, and it was losing that comparison for four structural
reasons rather than decorative ones:

* emoji were standing in for an icon set, at 24px beside 12px type
* rows swapped content under the cursor - the date out, seven buttons in
* the middle lane stacked up to four controls, so a row that needed a decision
  stood three times the height of the ones around it
* and the flat list was the workspace, when "the user doesn't really care about
  all of the files all at once - they only care about individual sites and
  files"

Everything below is a rule that, if it breaks, brings one of those back. The
rendering assertions run the real functions out of `cloud.js` in Node rather
than looking for strings, because a control is verified by running its handler:
four defects have shipped green here on a substring assertion.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "web" / "assets" / "js" / "cloud.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")

PROBE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from), b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('slice not found: ' + from);
  return source.slice(a, b);
}
const WD = {
  esc: s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
};
WD.escAttr = WD.esc;
WD.escJsStr = s => String(s == null ? '' : s).replace(/['\\]/g, '\\$&');
function e(s){return WD.esc(s);} function a(s){return WD.escAttr(s);}
function j(s){return WD.escJsStr(s);}
function p(s){return a(String(s==null?'':s).replace(/\\/g,'/'));}
function pj(s){return j(String(s==null?'':s).replace(/\\/g,'/'));}
let currentTab='projects', selected=new Set(), activeFilter='all';
const data={currentUser:'me@example.com'};
const _compareResults=new Map();
const navigator={platform:'Win32'};
function charDiff(x,y){return {a:e(x),b:e(y)};}
function dupHintFor(){return '';}
function previewBadge(){return '';}
function canPullFromCloud(r){return ['id','manual','exact'].includes(r.matchType);}

// `siteDigest` asks `isOutOfSync` whether a pair still counts as wanting
// something, so the real one comes along rather than a stub - the count is the
// whole point of the digest.
const block = slice('function comparisonIsSettled(', '\nfunction _isExternal(')
            + slice('const ICONS = {', '\nfunction localByPath(');
const api = {};
eval(block + '\nObject.assign(api,{ic,rowMenu,menuItem,rdAction,siteDigest,siteDigestHtml,'
   + 'matchBadgeHtml,gutCell,cloudCell,localCell,rowDetailHtml,_compareKey});');

const cloud = (o) => Object.assign({id:'c1',name:'Alpha Survey',meta:'2 hr ago',mtime:2,owner:'me@example.com'}, o);
const local = (o) => Object.assign({path:'D:/E/Alpha Survey.esx',name:'Alpha Survey',meta:'2 hr ago',mtime:1}, o);
const pair = (o) => Object.assign({status:'synced',kind:'projects',matchType:'id',
  cloud:cloud(),local:local(),key:'k'}, o);

const out = {};
out.cleanBand   = api.rowDetailHtml(pair(), false);
out.mismatchBand= api.rowDetailHtml(pair({status:'mismatch',matchType:'exact',
                    local:local({name:'Alpha Survey v2'})}), false);
out.staleBand   = api.rowDetailHtml(pair({staleness:'cloud_newer'}), false);
out.orphanCloud = api.rowDetailHtml(pair({status:'orphan',local:null}), false);
out.orphanLocal = api.rowDetailHtml(pair({status:'orphan',cloud:null}), false);
out.guessedBand = api.rowDetailHtml(pair({staleness:'local_newer',matchType:'fuzzy'}), false);

out.gutSynced   = api.gutCell(pair());
out.gutMismatch = api.gutCell(pair({status:'mismatch'}));
out.gutOrphan   = api.gutCell(pair({status:'orphan',local:null}));

out.cloudCell   = api.cloudCell(pair(), new Set());
out.localCell   = api.localCell(pair(), new Set());
out.otherOwner  = api.cloudCell(pair({cloud:cloud({owner:'someone.else@example.com'})}), new Set());

const kids = (n, bad) => ({
  matched: Array.from({length:n}, (_, i) => ({cloud:cloud({id:'k'+i}), local:local(),
             namesDiffer: i < bad, staleness:null})),
  cloudOnly: [], localOnly: [],
});
const siteRow = (children, open) => ({status:'synced',kind:'sites',matchType:'exact',
  cloud:{id:'s1',name:'Riverside Block A',meta:'',children},
  local:{path:'D:/E/Riverside Block A',name:'Riverside Block A',meta:'',isDir:true,children},
  toggle:{key:'site:s1',open,hasKids:true},key:'s'});
out.siteClear     = api.cloudCell(siteRow(kids(4,0), false), new Set());
out.siteAttention = api.cloudCell(siteRow(kids(4,2), false), new Set());
out.siteEmpty     = api.cloudCell(siteRow({matched:[],cloudOnly:[],localOnly:[]}, false), new Set());
out.siteBand      = api.rowDetailHtml(siteRow(kids(4,2), false), false);

console.log(JSON.stringify(out));
"""


def probe():
    """Render the real cells once, and cache it for every class in the file."""
    if getattr(probe, "_cache", None) is None:
        d = tempfile.mkdtemp()
        try:
            f = Path(d) / "probe.js"
            f.write_text(PROBE, encoding="utf-8")
            r = subprocess.run(
                ["node", str(f), str(ROOT / "web" / "assets" / "js" / "cloud.js")],
                capture_output=True, text=True, timeout=60,
                # Without this, node's stdout is decoded with the machine's
                # locale - cp1252 on his - and every arrow in a label comes
                # back mangled. It passes in CI, which is UTF-8, and fails on
                # the one machine that matters.
                encoding="utf-8")
            if r.returncode != 0:
                raise AssertionError("node failed: " + (r.stderr or r.stdout))
            probe._cache = json.loads(r.stdout)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return probe._cache


def strip(html):
    return re.sub(r"<[^>]+>", " ", html)


needs_node = unittest.skipIf(shutil.which("node") is None, "node is not installed")


@needs_node
class OnlyARowThatWantsSomethingGetsASecondLineTests(unittest.TestCase):
    """The rule the whole list leans on.

    A band under a row means: this one needs you. The first render of the
    redesign broke it within a minute - "Check what differs" is offered on any
    pair, so every in-sync row grew a band holding a warning icon, no sentence
    and one button. With ninety-seven folders that is not a list any more.
    """

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_a_clean_pair_has_no_band_at_all(self):
        self.assertEqual("", self.out["cleanBand"])

    def test_a_site_row_never_has_one(self):
        """Its digest says what is inside; the files carry their own bands."""
        self.assertEqual("", self.out["siteBand"])

    def test_every_other_state_does_have_one(self):
        for key in ("mismatchBand", "staleBand", "orphanCloud", "orphanLocal"):
            with self.subTest(state=key):
                self.assertTrue(self.out[key], key + " lost its band")

    def test_a_band_always_says_something_in_words(self):
        """A band with buttons and no sentence is the shape of the defect
        above: something to click and nothing telling him why."""
        for key in ("mismatchBand", "staleBand", "orphanCloud", "orphanLocal"):
            with self.subTest(state=key):
                text = strip(self.out[key])
                # Strip the button labels; a sentence has to survive.
                for label in re.findall(r"<span>([^<]*)</span>", self.out[key]):
                    text = text.replace(label, "")
                self.assertGreater(len(text.strip()), 25, key + " has no sentence")

    def test_comparing_is_still_always_reachable(self):
        """It left the band, so it has to be somewhere. It is in the row
        menu - otherwise this would be a feature removed by a layout change."""
        self.assertIn("checkRealDifference(", self.out["cloudCell"])


@needs_node
class TheMiddleLaneIsOneLineTests(unittest.TestCase):
    """"the little Check Link in the center column, which by the way is getting
    rather crowded now."

    It stacked up to four controls between two long project names, so a row
    needing a decision was three times the height of its neighbours and the
    list had a ragged edge down its middle. It carries the verdict and nothing
    else; every action is in the band, which has the full width for real
    labels.
    """

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_the_lane_holds_no_buttons_in_any_state(self):
        for key in ("gutSynced", "gutMismatch", "gutOrphan"):
            with self.subTest(state=key):
                self.assertNotIn("<button", self.out[key])

    def test_the_lane_says_what_was_determined_not_how_sure_it_feels(self):
        """"instead of 'same file' we should have, you know, exact match."

        He is right, and it ran through the whole vocabulary. "Same file" was
        the name of a *pairing* - both copies carry Ekahau's project id - and
        nothing had been compared, so the label claimed more than was known.
        It says what it established: same project.

        `Exact match` is reserved for the finding that earns it, a content
        comparison that came back identical, and this asserts it is *not* used
        for a mere pairing - which is the mistake being corrected.
        """
        self.assertIn("match-badge", self.out["gutSynced"])
        self.assertIn("Same project", strip(self.out["gutSynced"]))
        self.assertNotIn("Exact match", strip(self.out["gutSynced"]))

    def test_an_unpaired_row_says_which_side_it_is_on(self):
        self.assertIn("Cloud only", strip(self.out["gutOrphan"]))

    def test_the_verdict_carries_one_marker_and_not_two(self):
        """The chips gained a coloured dot and kept the tick, tilde, question
        mark and star they had been carrying in their own text, so a row read
        "* / Same file"."""
        spec = JS[JS.index("const MATCH_BADGE_SPEC = {"):]
        spec = spec[:spec.index("\n};")]
        for label in re.findall(r"label: '([^']+)'", spec):
            with self.subTest(label=label):
                self.assertNotRegex(label, r"^[\u2713~?\u2605]")


@needs_node
class EveryRowActionIsAWordTests(unittest.TestCase):
    """"I forgot what hybrid meant, or external for that matter."

    Each side of a row carried up to seven circular emoji buttons, revealed on
    hover, with the file's date faded out to make room for them. One menu per
    side now, opening on a click, every item a labelled word.
    """

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_each_side_offers_exactly_one_control_at_rest(self):
        for key in ("cloudCell", "localCell"):
            with self.subTest(cell=key):
                self.assertEqual(1, self.out[key].count('<details class="row-menu"'))

    def test_the_menu_opens_on_a_click_and_never_on_hover(self):
        """A menu that opens because the pointer crossed it is unusable in a
        dense list, and is the hover-reveal he ruled out."""
        self.assertIn('<details class="row-menu"', self.out["cloudCell"])
        self.assertNotIn(".row-menu:hover .row-menu-items", CSS)

    def test_every_item_in_it_is_a_word(self):
        for key in ("cloudCell", "localCell"):
            items = re.findall(r'<button class="row-menu-item[^"]*"[^>]*>(.*?)</button>',
                               self.out[key], re.S)
            self.assertGreater(len(items), 2, key)
            for html in items:
                label = strip(html).strip()
                with self.subTest(cell=key, item=label[:30]):
                    self.assertGreater(len(label), 4, "an icon with no word")

    def test_the_date_no_longer_disappears_under_the_cursor(self):
        """Fading the meta out to make room for the buttons meant content
        swapped in and out on every row the mouse crossed. It was the loudest
        thing on the page and it is gone."""
        self.assertNotIn(".lr-cell:hover .cell-meta", CSS)
        self.assertIn("cell-meta", self.out["cloudCell"])

    def test_the_destructive_item_is_marked_as_such(self):
        for key in ("cloudCell", "localCell"):
            with self.subTest(cell=key):
                self.assertIn('class="row-menu-item danger"', self.out[key])


@needs_node
class HisOwnNameIsNotNewsTests(unittest.TestCase):
    """The owner tag rendered whenever the cloud project had an owner, and
    every project he owns has one - so a hundred rows each carried the same
    thirty-character address of the person reading them, which at 1366 pushed
    the file name onto a second line."""

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_his_own_address_is_not_printed(self):
        self.assertNotIn("me@example.com", strip(self.out["cloudCell"]))

    def test_somebody_else_still_is(self):
        self.assertIn("someone.else@example.com", strip(self.out["otherOwner"]))


@needs_node
class ASiteSaysWhetherItIsWorthOpeningTests(unittest.TestCase):
    """"the user doesn't really care about all of the files all at once - they
    only care about individual sites and files."

    The sites start closed, so the one line each of them gets has to answer
    "is there anything for me in here" without being opened.
    """

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_a_clean_site_says_so_and_stays_quiet(self):
        text = strip(self.out["siteClear"])
        self.assertIn("4 files", text)
        self.assertIn("all in sync", text)
        self.assertIn("is-clear", self.out["siteClear"])

    def test_a_site_that_wants_something_counts_it(self):
        text = strip(self.out["siteAttention"])
        self.assertIn("2 need", text)
        self.assertIn("is-attention", self.out["siteAttention"])

    def test_an_empty_site_says_empty_rather_than_zero_files(self):
        self.assertIn("empty", strip(self.out["siteEmpty"]))

    def test_the_page_does_not_open_on_everything_at_once(self):
        """It closed every site, and that went too far.

        "At least before I understood what was going on even if it was ugly."
        Opening on a list of site names is not the work - the digest says a
        site is worth opening, not what is in it - and opening all of them is
        the wall this change existed to remove.

        So the split is by whether there is anything to do. A site holding a
        decision opens itself; a site where everything is in sync stays shut.
        The first thing on screen is the work that wants him.
        """
        block = JS[JS.index("function closeSitesOnFirstSight()"):]
        block = block[:block.index("\n}\n")]
        self.assertIn("collapsed.add(", block)
        self.assertIn("siteDigest(", block),
        self.assertIn("attention", block)
        self.assertIn("unpaired", block)

    def test_closing_them_happens_once_and_not_on_every_refresh(self):
        """Live refresh runs every few seconds. Re-closing the sites each time
        would shut whatever he had just opened while he was reading it."""
        block = JS[JS.index("function closeSitesOnFirstSight()"):]
        block = block[:block.index("\n}")]
        self.assertIn("_treeClosedFor", block)
        self.assertIn("return", block)

    def test_a_search_opens_whatever_it_found(self):
        """A closed site hiding its own search hits reads as a broken search."""
        self.assertIn("_searching = !!q", JS)
        self.assertIn("(_searching && childHit(children))", JS)


class NothingIsDrawnWithAnEmojiTests(unittest.TestCase):
    """Emoji were doing the work of an icon set: an arrow at 24px next to 12px
    text, plus a bin, a paperclip, an eye, a flag and a pair of people in
    circles, each rendered by whatever font the platform picked. They never
    share a weight or an optical size with the type around them, and that is
    most of why the list read as assembled rather than designed."""

    LEDGER_RENDERERS = ("function gutCell(", "function cloudCell(",
                        "function localCell(", "function rowDetailHtml(",
                        "function stalenessBadgeHtml(")

    EMOJI = re.compile(
        "[\U0001F300-\U0001FAFF\u2b00-\u2bff\u2190-\u21ff\u2600-\u27bf]")

    def body(self, marker):
        start = JS.index(marker)
        end = JS.index("\nfunction ", start + 1)
        return JS[start:end]

    def test_the_renderers_emit_no_emoji_and_no_html_entity_for_one(self):
        for marker in self.LEDGER_RENDERERS:
            src = self.body(marker)
            # Comments explain what was removed and may name the old glyph.
            src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
            src = re.sub(r"(?m)^\s*//.*$", "", src)
            with self.subTest(fn=marker):
                found = self.EMOJI.findall(src)
                # → in a button label is type, not an icon, and he reads the
                # direction off it.
                found = [c for c in found if c not in "\u2192\u2190"]
                self.assertEqual([], found, "emoji left in " + marker)
                self.assertNotRegex(src, r"&#1[0-9]{4};")

    def test_there_is_one_icon_set_and_it_inherits_its_colour(self):
        block = CSS[CSS.index("\n.ic {"):]
        block = block[:block.index("}")]
        self.assertIn("stroke: currentColor", block)
        self.assertIn("fill: none", block)

    def test_every_icon_the_code_asks_for_actually_exists(self):
        """A typo in an icon name renders an empty string, which is a silently
        missing icon rather than an error."""
        spec = JS[JS.index("const ICONS = {"):]
        spec = spec[:spec.index("\n};")]
        defined = set(re.findall(r"^\s*([a-zA-Z]+):\s*'", spec, re.M))
        used = set(re.findall(r"\bic\('([a-zA-Z]+)'", JS))
        used |= set(re.findall(r"(?:menuItem|rdAction|rdUnavailable)\('([a-zA-Z]+)'", JS))
        self.assertTrue(used)
        self.assertEqual(set(), used - defined, "icon asked for but never drawn")


class EscapeSequencesDoNotReachTheScreenTests(unittest.TestCase):
    """A literal backslash-u in a string is a bug with no symptom until someone
    reads the tooltip.

    It happened twice inside one session. A patch written in a raw string put
    `\\\\u2019` into the source, so the tooltip would have read "the two
    files\\u2019 contents"; and a shell heredoc turned `\\25BE` into an octal
    escape, which is how a chevron once rendered as "BE". Neither breaks a
    test, breaks the page, or shows up anywhere except in front of him.
    """

    SOURCES = ["web/assets/js/cloud.js", "web/assets/js/wd-shared.js",
               "web/cloud.html"]

    def test_no_double_escaped_unicode_anywhere_it_would_be_displayed(self):
        for rel in self.SOURCES:
            text = (ROOT / rel).read_text(encoding="utf-8")
            for n, line in enumerate(text.split("\n"), 1):
                with self.subTest(file=rel, line=n):
                    self.assertNotRegex(
                        line, r"\\\\u[0-9a-fA-F]{4}",
                        "a literal backslash-u would be printed, not the character")


class TheListUsesOneSetOfTokensTests(unittest.TestCase):
    """Six colours were each doing three jobs - green meant the local column,
    and "in sync", and "same file", and a primary button's border - so no
    colour meant anything. Four semantic ones, one control height, one row
    height, and the list stops inventing its own."""

    TOKENS = ("--ok:", "--attn:", "--danger:", "--accent:", "--ctl-h:", "--row-h:")

    def test_the_tokens_are_defined_for_both_themes(self):
        light = CSS[CSS.index('[data-theme="light"] {'):]
        light = light[:light.index("}")]
        for t in self.TOKENS:
            with self.subTest(token=t):
                self.assertIn(t, CSS)
        for t in ("--ok:", "--attn:", "--danger:", "--accent:"):
            with self.subTest(token=t, theme="light"):
                self.assertIn(t, light)

    def test_the_row_controls_share_one_height(self):
        for sel in (".rd-btn {", ".rd-note {", ".ghost-add {"):
            block = CSS[CSS.index(sel):]
            block = block[:block.index("}")]
            with self.subTest(rule=sel):
                self.assertIn("var(--ctl-h)", block)

    def test_the_status_bar_uses_the_semantic_colours(self):
        for status, token in (("synced", "--ok"), ("mismatch", "--attn"),
                              ("orphan", "--danger")):
            with self.subTest(status=status):
                rule = ".ledger-row.%s .lr-cell:not(.empty) { box-shadow: inset 3px 0 0 var(%s); }" % (status, token)
                self.assertIn(rule, CSS)

    def test_nothing_in_the_list_bounces_on_hover(self):
        """Scaling to 1.3 and lifting with a drop shadow is a fine gesture on a
        landing page and reads as a toy in a tool he uses all day."""
        self.assertIn(".gut-arrow:hover { transform: none; }", CSS)
        self.assertIn(".icon-btn:hover { transform: none; box-shadow: none; }", CSS)


@needs_node
class AGuessedPairIsRefusedAndToldWhyTests(unittest.TestCase):
    """Unrecoverable earns friction, not a wall - and the key goes next to the
    lock.

    Replacing a cloud project deletes the old one and a cloud delete does not
    come back, so a pairing WD only guessed at stays refused. The first pass of
    this redesign replaced the greyed control with the route out, which reads
    better and says less: it stopped naming what was being refused. Both are
    there now.

    The route out is also a real fix. The old message said to "confirm the pair
    with the Link button first", and Link is only ever drawn on an *unpaired*
    row - so on this row the app named a control that was nowhere on screen.
    """

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_the_refused_action_is_shown_rather_than_absent(self):
        html = self.out["guessedBand"]
        self.assertIn('aria-disabled="true"', html)
        self.assertIn("Local \u2192 Cloud", strip(html))

    def test_it_is_not_disabled_in_a_way_that_swallows_the_click(self):
        """The click is how he asks why. A `disabled` attribute eats it, and
        the reason then lives only in a tooltip."""
        html = self.out["guessedBand"]
        m = re.search(r'<button class="rd-btn is-disabled"[^>]*>', html)
        self.assertIsNotNone(m)
        self.assertNotIn(" disabled", m.group(0))

    def test_clicking_it_explains_instead_of_doing_nothing(self):
        wiring = JS[JS.index("function _wireDisabledBulkReasons()"):]
        wiring = wiring[:wiring.index("\n}")]
        self.assertIn("rd-btn.is-disabled", wiring)
        self.assertIn("toast(", wiring)

    def test_the_control_that_lifts_the_refusal_is_in_the_same_band(self):
        html = self.out["guessedBand"]
        self.assertIn("Confirm this pair", strip(html))
        self.assertIn("markManualMatch(", html)


if __name__ == "__main__":
    unittest.main()
