"""The Settings page can be read, reached and left by everyone who uses it.

A design review of the page found five separate ways it let a person down, each
of which looked fine on a mouse-driven screen:

* Enter or Space on the open section's heading folded the only section on a wide
  window and left an empty page. The CSS only stopped the mouse.
* Twenty-odd fields had no accessible name: the labels sat above them as text
  and were tied to nothing, the page had no heading and no main landmark, and a
  group of radio buttons was a row of loose inputs.
* The primary buttons were white on the Cloud blue, 2.77:1, and the muted
  overview text on the dark page was 3.86:1.
* Nothing said an edit was still unsaved, Cancel threw edits away without
  asking, and Save and Cancel were offered on sections that have nothing to save.
* Forget Login and Reset Organizer Defaults act at once, not on Save, and said
  neither that nor what they would touch.

What is held here is resolved or driven rather than read off the source: the
colours are the painted ones, the handlers are the real functions run in Node
against stubs, and the markup is parsed.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tests.test_every_tool_has_its_own_brand import (
    CSS, Palette, _contrast, _parts, _rules,
)

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "settings.html").read_text(encoding="utf-8")
JS_PATH = ROOT / "web" / "assets" / "js" / "settings-page.js"
NODE_TIMEOUT_S = 60


class _Page(HTMLParser):
    """The Settings markup: headings, landmarks, and what names each field."""

    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.main = 0
        self.summaries_with_h2 = 0
        self.summaries = 0
        self._in_summary = False
        self.ids: set[str] = set()
        self.label_for: set[str] = set()
        self.labels: list[dict] = []
        self.fields: list[dict] = []
        self._label: dict | None = None
        self.fieldsets: list[dict] = []
        self._fs: list[dict] = []
        self.classes: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.classes.update((a.get("class") or "").split())
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "h1":
            self.h1 += 1
        if tag == "main":
            self.main += 1
        if tag == "summary":
            self.summaries += 1
            self._in_summary = True
        if tag == "h2" and self._in_summary:
            self.summaries_with_h2 += 1
        if tag == "fieldset":
            fs = {"legend": False, "radios": 0}
            self._fs.append(fs)
            self.fieldsets.append(fs)
        if tag == "legend" and self._fs:
            self._fs[-1]["legend"] = True
        if tag == "label":
            self._label = {"for": a.get("for"), "wraps": False}
            self.labels.append(self._label)
            if a.get("for"):
                self.label_for.add(a["for"])
        if tag in ("input", "select", "textarea"):
            kind = (a.get("type") or "text") if tag == "input" else tag
            f = {"id": a.get("id"), "type": kind, "aria": a.get("aria-label"),
                 "wrapped": self._label is not None, "name": a.get("name")}
            self.fields.append(f)
            if self._label is not None:
                self._label["wraps"] = True
            if kind == "radio" and self._fs:
                self._fs[-1]["radios"] += 1

    def handle_endtag(self, tag):
        if tag == "summary":
            self._in_summary = False
        if tag == "label":
            self._label = None
        if tag == "fieldset" and self._fs:
            self._fs.pop()


def _page() -> _Page:
    p = _Page()
    p.feed(HTML)
    return p


class TheMarkupHasStructureAndNames(unittest.TestCase):
    def test_one_heading_one_landmark_and_a_heading_per_section(self):
        p = _page()
        self.assertEqual(p.h1, 1, "the page title is a heading")
        self.assertEqual(p.main, 1, "the settings are the main landmark")
        self.assertEqual((p.summaries, p.summaries_with_h2), (9, 9),
                         "each section title is a heading inside its summary")

    def test_every_field_that_is_typed_into_or_chosen_from_has_a_name(self):
        p = _page()
        unnamed = []
        for f in p.fields:
            if f["type"] in ("hidden", "file"):
                continue
            named = (f["wrapped"] or f["aria"]
                     or (f["id"] and f["id"] in p.label_for))
            if not named:
                unnamed.append(f["id"] or f["name"] or f["type"])
        self.assertEqual(unnamed, [], "no accessible name")

    def test_no_label_is_left_pointing_at_nothing(self):
        p = _page()
        orphans = [l for l in p.labels
                   if not l["wraps"] and not (l["for"] and l["for"] in p.ids)]
        self.assertEqual(orphans, [])

    def test_each_group_of_radio_buttons_is_a_fieldset_with_a_legend(self):
        p = _page()
        groups = [fs for fs in p.fieldsets if fs["radios"]]
        self.assertEqual(len(groups), 3, "merge rule, default view, sites open as")
        for fs in groups:
            self.assertTrue(fs["legend"], "a group of radios names itself")

    def test_the_three_radio_groups_share_one_set_of_rules(self):
        """`s-radios` had no CSS at all, so 'Sites open as' fell back to the
        uppercase grey of an ordinary label while its two siblings did not."""
        self.assertNotIn("s-radios", _page().classes)


PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(marker) {
  const a = src.indexOf(marker);
  if (a < 0) throw new Error(marker + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
const code = [
  slice('  function setDirty('), slice('  function syncFooter('), slice('  function wireEditing('),
  slice('  function confirmDiscard('), slice('  SP.cancel = function'),
  slice('  function pinSummaries('), slice('  SP.forgetLogin = function'),
  slice('  SP.resetOrganizer = function'), slice('  SP.goSection = function'),
].join(';\n');

const SCENARIOS = JSON.parse(process.argv[2]);
const out = {};
for (const name of Object.keys(SCENARIOS)) {
  const sc = SCENARIOS[name];
  const calls = [];
  let dirty = false;
  const handlers = {};
  const footer = { cls: new Set(), classList: { toggle(c, on) { on ? footer.cls.add(c) : footer.cls.delete(c); } } };
  const mark = { hidden: true };
  const main = { addEventListener(ev, fn) { (handlers[ev] = handlers[ev] || []).push(fn); } };
  const open = (sc.open || []).map(ro => ({ hasAttribute: (n) => n === 'data-readonly' && ro }));
  const secs = ['sec-general', 'sec-cloud', 'sec-report'].map((id) => ({
    id, open: id === 'sec-general', scrolled: false,
    scrollIntoView() { this.scrolled = true; },
  }));
  const history = { urls: [], replaceState(a, b, url) { this.urls.push(url); } };
  let hashSet = false;
  const location = { reload() { calls.push('reload'); }, set hash(v) { hashSet = true; }, get hash() { return ''; } };
  let marked = 0;
  const markNav = () => { marked++; };
  const document = {
    getElementById(id) { return { sFooter: footer, sDirty: mark }[id] || secs.find((x) => x.id === id) || null; },
    querySelector(sel) { return sel === '.s-main' ? main : null; },
    querySelectorAll(sel) {
      if (sel === 'details.s-section[open]') return open;
      if (sel === 'details.s-section > summary') return sums;
      if (sel === 'details.s-section') return secs;
      return [];
    },
  };
  const winHandlers = {};
  let wide = !!sc.wide;
  const mqListeners = [];
  const window = {
    history,
    addEventListener(ev, fn) { winHandlers[ev] = fn; },
    matchMedia() { return { get matches() { return wide; }, addEventListener(ev, fn) { mqListeners.push(fn); } }; },
  };
  const sums = [0, 1].map(() => {
    const el = { attrs: {}, clicks: [],
      setAttribute(k, v) { el.attrs[k] = v; }, removeAttribute(k) { delete el.attrs[k]; },
      addEventListener(ev, fn) { el.clicks.push(fn); } };
    return el;
  });
  const confirms = [];
  const confirm = (m) => { confirms.push(m); return sc.confirm !== false; };
  const API = (a) => { calls.push('api:' + a); return { then(f) { f({ ok: true, settings: {} }); return this; } }; };
  const WD = { toast() {} };
  const SP = {};
  const settings = {};
  const checkCloud = () => {}, populate = () => {};
  const body = code + `;
    ${sc.drive}
  `;
  const result = new Function('document', 'window', 'location', 'confirm', 'API', 'WD', 'SP', 'settings',
    'checkCloud', 'populate', 'calls', 'handlers', 'winHandlers', 'footer', 'mark', 'sums', 'confirms',
    'mqListeners', 'setWide', 'history', 'markNav', 'secs',
    'var dirty = false;\n' + body)(document, window, location, confirm, API, WD, SP, settings,
    checkCloud, populate, calls, handlers, winHandlers, footer, mark, sums, confirms, mqListeners,
    (v) => { wide = v; }, history, markNav, secs);
  out[name] = { result, calls, confirms, footer: [...footer.cls], dirtyShown: mark.hidden === false,
                open: secs.filter((x) => x.open).map((x) => x.id), scrolled: secs.some((x) => x.scrolled),
                urls: history.urls, hashSet, marked };
}
process.stdout.write(JSON.stringify(out));
"""

# Each scenario is a body of JS run against the real functions; its last
# `return` is what comes back.
SCENARIOS = {
    # a real edit marks the page, the file picker does not
    "edit": {"open": [False],
             "drive": "wireEditing(); handlers.input[0]({ target: { id: 'sRepClient' } });"
                      "return null;"},
    "import_picker": {"open": [False],
             "drive": "wireEditing(); handlers.change[0]({ target: { id: 'sImportFile' } });"
                      "return null;"},
    # sections with nothing to save lose Save and Cancel until something changes
    "readonly_clean": {"open": [True], "drive": "syncFooter(); return null;"},
    "readonly_dirty": {"open": [True],
             "drive": "wireEditing(); handlers.change[0]({ target: { id: 'sRepUnits' } }); return null;"},
    "editable_clean": {"open": [False], "drive": "syncFooter(); return null;"},
    "mixed_open": {"open": [True, False], "drive": "syncFooter(); return null;"},
    # Cancel
    "cancel_clean": {"open": [False], "drive": "SP.cancel(); return null;"},
    "cancel_dirty_declined": {"open": [False], "confirm": False,
             "drive": "setDirty(true); SP.cancel(); return null;"},
    "cancel_dirty_accepted": {"open": [False],
             "drive": "setDirty(true); SP.cancel(); return null;"},
    # the open section's heading must not fold, at any width
    "summary": {"drive":
             "pinSummaries(); var ev = { prevented: false, preventDefault() { this.prevented = true; } };"
             "sums[0].clicks[0](ev); return { prevented: ev.prevented, attrs: sums[0].attrs };"},
    # choosing a card
    "go_section": {"drive": "SP.goSection('report'); return null;"},
    "go_nowhere": {"drive": "SP.goSection('nonsense'); return null;"},
    # actions that do not wait for Save
    "forget_declined": {"confirm": False, "drive": "SP.forgetLogin(); return null;"},
    "forget_accepted": {"drive": "SP.forgetLogin(); return null;"},
    "reset_declined": {"confirm": False, "drive": "SP.resetOrganizer(); return null;"},
    "reset_accepted": {"drive": "SP.resetOrganizer(); return null;"},
}


def _run() -> dict:
    r = subprocess.run(["node", "-e", PROBE, str(JS_PATH), json.dumps(SCENARIOS)],
                       capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheHandlersDoWhatThePageSays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Each scenario's `drive` is a function body; wrap it so `return` works.
        for sc in SCENARIOS.values():
            if not sc["drive"].lstrip().startswith("return (function"):
                sc["drive"] = "return (function () { " + sc["drive"] + " })();"
        cls.out = _run()

    def test_an_edit_marks_the_page_and_the_import_picker_does_not(self):
        self.assertTrue(self.out["edit"]["dirtyShown"])
        self.assertFalse(self.out["import_picker"]["dirtyShown"],
                         "choosing a file to import is an action, not an unsaved setting")

    def test_save_and_cancel_are_offered_only_where_there_is_something_to_save(self):
        o = self.out
        self.assertIn("is-readonly", o["readonly_clean"]["footer"])
        self.assertNotIn("is-readonly", o["readonly_dirty"]["footer"],
                         "an unsaved edit made elsewhere still needs its Save")
        self.assertNotIn("is-readonly", o["editable_clean"]["footer"])
        self.assertNotIn("is-readonly", o["mixed_open"]["footer"],
                         "one section with controls open is enough")

    def test_cancel_asks_before_it_discards_and_only_then(self):
        o = self.out
        self.assertEqual((o["cancel_clean"]["calls"], o["cancel_clean"]["confirms"]), (["reload"], []))
        self.assertEqual((o["cancel_dirty_declined"]["calls"], len(o["cancel_dirty_declined"]["confirms"])),
                         ([], 1))
        self.assertEqual((o["cancel_dirty_accepted"]["calls"], len(o["cancel_dirty_accepted"]["confirms"])),
                         (["reload"], 1))

    def test_the_only_open_section_cannot_be_folded(self):
        got = self.out["summary"]["result"]
        self.assertTrue(got["prevented"], "Enter and Space reach the summary as a click")
        self.assertEqual(got["attrs"].get("tabindex"), "-1",
                         "and the heading is out of the tab order")

    def test_choosing_a_card_shows_that_section_without_moving_the_page(self):
        o = self.out["go_section"]
        self.assertEqual(o["open"], ["sec-report"], "that section alone")
        self.assertFalse(o["scrolled"], "the cards are where the section is; do not move the page")
        self.assertFalse(o["hashSet"], "a hash change scrolls and flashes the section, "
                                       "which is for arriving from a tool")
        self.assertEqual(o["urls"], ["#report"], "the address still names the section")
        self.assertEqual(o["marked"], 1, "and the card is marked as current")

    def test_choosing_a_section_that_is_not_there_changes_nothing(self):
        o = self.out["go_nowhere"]
        self.assertEqual((o["open"], o["urls"], o["marked"]), (["sec-general"], [], 0))

    def test_forget_login_asks_and_says_what_it_does(self):
        self.assertEqual(self.out["forget_declined"]["calls"], [])
        acc = self.out["forget_accepted"]
        self.assertEqual(acc["calls"], ["api:cloud/forget_login"])
        self.assertRegex(acc["confirms"][0], r"(?i)sign in again")

    def test_reset_names_what_it_resets_and_that_it_is_not_part_of_save(self):
        self.assertEqual(self.out["reset_declined"]["calls"], [])
        said = self.out["reset_accepted"]["confirms"][0]
        self.assertRegex(said, r"(?i)rename rules")
        self.assertRegex(said, r"(?i)straight away")
        self.assertIn("api:settings/update", self.out["reset_accepted"]["calls"])


class _Colours(Palette):
    """`Palette` for Settings' body, taught `black` in a colour-mix."""

    def __init__(self, theme: str):
        super().__init__(theme, "tool-home")

    def resolve(self, value, depth=0):
        m = re.fullmatch(r"color-mix\(in srgb,\s*(.+?)\s+(\d+)%\s*,\s*black\)", value.strip())
        if m:
            a, p = self.resolve(m.group(1), depth + 1), int(m.group(2)) / 100
            return tuple(x * p for x in a)
        return super().resolve(value, depth)


def _every(selector: str, prop: str) -> list:
    """Every declaration of `prop` in a rule whose selector list names exactly
    `selector`, in order - for asserting that a value is never among them."""
    css = CSS.read_text(encoding="utf-8")
    return [v.strip() for sel, body in _rules(css) if selector in _parts(sel)
            for name, v in re.findall(r"(?<![\w-])([\w-]+)\s*:\s*([^;]+);", body)
            if name == prop]


def _final(selector: str, prop: str) -> str:
    """The last declaration of `prop` in a rule whose selector list names
    exactly `selector` - the one that wins between equals."""
    css = CSS.read_text(encoding="utf-8")
    value = None
    for sel, body in _rules(css):
        if selector in _parts(sel):
            for name, v in re.findall(r"(?<![\w-])([\w-]+)\s*:\s*([^;]+);", body):
                if name == prop:
                    value = v.strip()
    if value is None:
        raise AssertionError(f"{selector} no longer sets {prop}")
    return value


def _first(selector: str, prop: str) -> str:
    """The first declaration of `prop` in a rule naming `selector`: the base
    rule, before any small-screen override of the same property."""
    css = CSS.read_text(encoding="utf-8")
    for sel, body in _rules(css):
        if selector in _parts(sel):
            for name, v in re.findall(r"(?<![\w-])([\w-]+)\s*:\s*([^;]+);", body):
                if name == prop:
                    return v.strip()
    raise AssertionError(f"{selector} no longer sets {prop}")


class TheTextCanBeRead(unittest.TestCase):
    def test_a_primary_button_label_clears_four_and_a_half_to_one(self):
        for theme in ("dark", "light"):
            pal = _Colours(theme)
            white = (1.0, 1.0, 1.0)
            for state, sel in (("rest", ".btn-blue"), ("hover", ".btn-blue:hover")):
                with self.subTest(theme=theme, state=state):
                    fill = pal.resolve(_final(sel, "background"))
                    self.assertGreaterEqual(round(_contrast(white, fill), 2), 4.5)

    def test_the_update_banners_button_clears_four_and_a_half_to_one(self):
        for theme in ("dark", "light"):
            pal = _Colours(theme)
            fill = pal.resolve(_final(".wd-update-download", "background"))
            with self.subTest(theme=theme):
                self.assertGreaterEqual(round(_contrast((1.0, 1.0, 1.0), fill), 2), 4.5)

    def test_muted_text_on_the_settings_page_clears_four_and_a_half_to_one(self):
        """The overview's titles, empty values and where-it-lives lines, the
        re-run link, the drag and remove marks, and the update banner's detail."""
        selectors = [".s-ov-title", ".s-ov-row .s-ov-val.is-empty", ".s-ov-where",
                     ".settings-footer .rerun-link", ".sf-handle", ".sf-remove",
                     ".wd-update-detail"]
        for theme in ("dark", "light"):
            pal = _Colours(theme)
            for sel in selectors:
                ink = pal.resolve(_final(sel, "color"))
                # Page background, and the update banner's amber tint.
                for where, bg in (("page", pal.resolve("var(--bg)")),
                                  ("banner", pal.resolve("var(--amber-bg)"))):
                    if where == "banner" and sel != ".wd-update-detail":
                        continue
                    with self.subTest(theme=theme, selector=sel, on=where):
                        self.assertGreaterEqual(round(_contrast(ink, bg), 2), 4.5)

    def test_the_column_holds_its_width_between_sections(self):
        """It shrank to its content: a short section moved the list of sections
        270px sideways and snapped it back on the next one."""
        self.assertEqual(_final(".settings-wrap", "width"), "100%")


class _Sections(HTMLParser):
    """Each section's id and what it says about itself for the card."""

    def __init__(self):
        super().__init__()
        self.sections: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "details" and "s-section" in (a.get("class") or "").split():
            self.sections.append({"id": a["id"], "desc": a.get("data-nav-desc"),
                                  "icon": a.get("data-nav-icon")})


def _sections() -> list[dict]:
    p = _Sections()
    p.feed(HTML)
    return p.sections


NAV_PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('  function buildNav() {');
if (a < 0) throw new Error('buildNav moved');
let b = a, depth = 0, seen = false;
while (b < src.length && !(seen && depth === 0)) {
  if (src[b] === '{') { depth++; seen = true; }
  else if (src[b] === '}') depth--;
  b++;
}
const WD = { esc: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;'),
             escAttr: s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;') };
const nav = { innerHTML: '' };
const secs = JSON.parse(process.argv[2]).map(d => ({
  id: d.id, getAttribute: (n) => ({ 'data-nav-desc': d.desc, 'data-nav-icon': d.icon })[n] || null,
  querySelector: () => ({ textContent: d.title }), addEventListener() {},
}));
const document = { getElementById: () => nav, querySelectorAll: () => secs };
const markNav = () => {};
eval(src.slice(a, b) + ';buildNav();');
process.stdout.write(JSON.stringify({ html: nav.innerHTML }));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheSectionsAreCardsLikeHomes(unittest.TestCase):
    def test_every_section_says_what_is_in_it_and_has_an_icon_that_exists(self):
        secs = _sections()
        self.assertEqual(len(secs), 9)
        for sec in secs:
            with self.subTest(section=sec["id"]):
                self.assertTrue(sec["desc"], "a card says what is in its section")
                icon = ROOT / "web" / sec["icon"].lstrip("/")
                self.assertTrue(icon.is_file(), f"{sec['icon']} is not in web/")

    def test_no_two_sections_share_an_icon(self):
        icons = [s["icon"] for s in _sections()]
        self.assertEqual(len(icons), len(set(icons)),
                         "General, Subfolder Structure and Backup & restore all wore the suite logo")

    def test_the_cards_are_built_from_the_sections_with_name_line_and_icon(self):
        secs = [dict(s, title=s["id"].replace("sec-", "").title()) for s in _sections()]
        r = subprocess.run(["node", "-e", NAV_PROBE, str(JS_PATH), json.dumps(secs)],
                           capture_output=True, text=True, encoding="utf-8", timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        html = json.loads(r.stdout.strip().splitlines()[-1])["html"]
        cards = re.findall(r'<button type="button" class="s-nav-item"(.*?)</button>', html, flags=re.S)
        self.assertEqual(len(cards), 9)
        for card, sec in zip(cards, secs):
            with self.subTest(section=sec["id"]):
                self.assertIn(f'data-sec="{sec["id"]}"', card)
                self.assertIn('data-fn="SP.goSection"', card)
                self.assertIn(f'<span class="s-nav-name">{sec["title"]}</span>', card)
                self.assertIn(f'<span class="s-nav-desc">{sec["desc"]}</span>', card)
                self.assertIn(f'<img src="{sec["icon"]}" alt="">', card)

    def test_a_card_name_clears_four_and_a_half_to_one_on_the_card_and_when_open(self):
        css = CSS.read_text(encoding="utf-8")
        accents = dict(re.findall(
            r'\.s-nav-item\[data-sec="(sec-\w+)"\]\s*\{\s*--s-accent:\s*([^;]+);', css))
        accents["neutral"] = re.search(
            r"\.s-nav-item\s*\{\s*--s-accent:\s*([^;]+);", css).group(1)
        self.assertGreaterEqual(len(accents), 7, "six tool sections and the neutral one")
        formula = re.search(r"\.s-nav-item\s*\{[^}]*--s-title:\s*([^;]+);", css).group(1)
        m = re.fullmatch(r"color-mix\(in srgb,\s*var\(--s-accent\)\s+(\d+)%\s*,\s*var\(--text\)\)", formula.strip())
        self.assertTrue(m, "the card title formula changed shape: " + formula)
        share = int(m.group(1)) / 100
        cur = re.search(
            r"\.s-nav-item\.is-current\s*\{[^}]*background:\s*color-mix\(in srgb,\s*var\(--s-accent\)\s+(\d+)%",
            css)
        self.assertTrue(cur, "the open card's tint changed shape")
        open_tint = int(cur.group(1)) / 100
        self.assertEqual(_final(".s-nav-item.is-current .s-nav-name", "color"), "var(--text)",
                         "the open card names itself in the page's ink; the contrast below assumes it")
        self.assertGreaterEqual(open_tint, 0.2,
                                "the open card is only told apart from the rest by its tint and ring")
        for theme in ("dark", "light"):
            pal = _Colours(theme)
            card = pal.resolve("var(--card-bg)")
            ink = pal.resolve("var(--text)")
            for sec, acc in accents.items():
                a = pal.resolve(acc)
                title = tuple(x * share + y * (1 - share) for x, y in zip(a, ink))
                # The open card names itself in the page's own ink: on the
                # strong tint the mixed colour fell to 4.08:1 in the light theme.
                for state, bg in (("card", card),
                                  ("hover", tuple(x * 0.12 + y * 0.88 for x, y in zip(a, card))),
                                  ("open", tuple(x * open_tint + y * (1 - open_tint)
                                                 for x, y in zip(a, card)))):
                    with self.subTest(theme=theme, section=sec, state=state):
                        name = ink if state == "open" else title
                        self.assertGreaterEqual(round(_contrast(name, bg), 2), 4.5)

    def test_each_tool_section_has_its_own_colour(self):
        css = CSS.read_text(encoding="utf-8")
        accents = re.findall(
            r'\.s-nav-item\[data-sec="sec-\w+"\]\s*\{\s*--s-accent:\s*([^;]+);', css)
        self.assertEqual(len(accents), 6)
        self.assertEqual(len(set(accents)), 6, "two sections share a colour")


class SettingsLooksTheSameWhereverItOpens(unittest.TestCase):
    """Settings is a page of its own, and a panel over Home or over any tool.
    The panel was 860px wide, under the 1000px the page needs for its wide
    layout, so it always showed the narrow one - cards across the top, a third
    of the panel empty beneath a footer that floated mid-way - and nobody who
    opened Settings from a tool or from Home ever saw the page as it is on its
    own."""

    def test_the_panel_is_wide_enough_to_keep_the_cards_beside_the_section(self):
        width = _first(".wd-settings-panel", "width")
        m = re.fullmatch(r"min\((\d+)px,\s*100%\)", width)
        self.assertTrue(m, "the panel width changed shape: " + width)
        css = CSS.read_text(encoding="utf-8")
        narrow = int(re.search(
            r"@media \(max-width: (\d+)px\)\s*\{\s*\.s-layout \{ grid-template-columns: 1fr;", css).group(1))
        self.assertLessEqual(narrow, 600, "the cards stack above the section only on a phone-sized window")
        frame = int(m.group(1)) - 2        # the panel's own border
        self.assertGreater(frame, narrow,
                           f"a {frame}px frame is inside the stacked layout (up to {narrow}px)")

    def test_the_frame_is_fixed_and_only_the_settings_scroll(self):
        """What the page does is held in a real browser by
        test_settings_frame_holds_still_browser; this holds the rules it rests
        on, so a change to one fails here in a second rather than there."""
        self.assertEqual(_final(".settings-wrap", "overflow"), "clip",
                         "`hidden` would let a section's scrollIntoView scroll the frame away")
        self.assertEqual(_final(".s-main > .settings-footer", "position"), "static")
        self.assertEqual(
            _final(".s-main > details.s-section[open]::details-content", "overflow-y"), "auto",
            "Chrome and Edge make this internal box the flex item, so it has to be the scroller")
        self.assertEqual(_final(".s-main > details.s-section[open] > .s-body", "overflow-y"), "auto")

    def test_the_section_has_a_title_across_the_top_of_its_box(self):
        sel = ".s-main details.s-section[open] > summary"
        self.assertNotIn("absolute", _every(sel, "position"),
                         "the heading was hidden when the card named the section")
        self.assertIn("var(--s-accent", _final(sel, "border-bottom"))

    def test_the_panel_is_wider_than_it_was(self):
        m = re.fullmatch(r"min\((\d+)px,\s*100%\)", _first(".wd-settings-panel", "width"))
        self.assertTrue(m)
        self.assertGreaterEqual(int(m.group(1)), 1400)


if __name__ == "__main__":
    unittest.main()
