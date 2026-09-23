"""His template is the default; Ekahau's is the fallback. Both tools agree.

**"We should only have two: the profile that I made and the default. That's
it. And the default should end up being whatever the customer creates. Ekahau
should always be the fallback, not the primary."**

It was the other way round in Prep, and the two tools disagreed about it.
Measured in Firefox before the change:

* Quick Walls listed `WD Template` first, starred, selected.
* Prep listed `Ekahau Default` first **and selected it**, because it rendered
  the templates in the order the server returned them - alphabetical - and set
  no `selected` attribute at all, so the browser chose option one. Preparing a
  project therefore applied Ekahau's stock types unless he noticed the dropdown
  and changed it, and his saved `walls.default_template` was ignored.

The ordering and the choice now live in `wd-shared.js` and both tools call
them, so the two cannot drift apart again. These tests run those functions
rather than looking for their names: `WD.chooseWallTemplate` deleted and
replaced with `list[0]` passes a substring check and fails here.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"
WALLS_JS = (ROOT / "web" / "assets" / "js" / "walls.js").read_text(encoding="utf-8")
PREP_JS = (ROOT / "web" / "assets" / "js" / "prep.js").read_text(encoding="utf-8")

NODE_TIMEOUT_S = 120

#: Slice the block of WD.* assignments out of wd-shared.js and evaluate it.
#: Bounded by two markers that are both assignments, so nothing between them
#: can be half-included - the failure mode CLAUDE.md records for these probes.
PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('  WD.EKAHAU_TEMPLATE =');
const b = src.indexOf('  WD.sortNavMenus = function', a);
if (a < 0 || b < 0) throw new Error('the wall-template block moved in wd-shared.js');
const WD = {};
eval(src.slice(a, b));
const t = (name, count) => ({ name, count, file: name + '_walltemplate.json',
                              wallTypes: new Array(count).fill({}) });
"""


def run_node(body: str, extra_args=()):
    """Run a probe and return its one JSON line.

    `encoding="utf-8"` is not optional: node prints the real em dash in these
    labels, and Windows' default cp1252 decode turns it into something that
    compares equal to nothing - green in CI, red here.

    A non-zero exit raises with everything the probe said, and empty output
    raises too, because a probe that prints nothing otherwise passes every
    assertion about what it did not find.
    """
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    proc = subprocess.run([node, "-e", PRELUDE + body, str(SHARED_JS), *extra_args],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=NODE_TIMEOUT_S)
    if proc.returncode != 0:
        raise AssertionError((proc.stdout + proc.stderr).strip())
    out = proc.stdout.strip()
    if not out:
        raise AssertionError("the probe printed nothing: "
                             + (proc.stderr.strip() or "(no stderr either)"))
    return json.loads(out)


class HisComesFirstAndEkahauIsTheFallback(unittest.TestCase):

    def test_his_templates_sort_above_ekahaus(self):
        got = run_node("""
            const list = [t('Ekahau Default', 21), t('WD Template', 26), t('Site Survey', 9)];
            console.log(JSON.stringify(WD.wallTemplateOrder(list).map(x => x.name)));
        """)
        self.assertEqual(got, ["WD Template", "Site Survey", "Ekahau Default"],
                         "Ekahau's template is not last")

    def test_with_no_saved_default_it_opens_on_one_of_his(self):
        """The case that was wrong. Alphabetically Ekahau wins; it must not."""
        got = run_node("""
            const list = [t('Ekahau Default', 21), t('WD Template', 26)];
            console.log(JSON.stringify(WD.chooseWallTemplate(list, '').name));
        """)
        self.assertEqual(got, "WD Template")

    def test_the_saved_default_wins_when_it_still_exists(self):
        got = run_node("""
            const list = [t('Ekahau Default', 21), t('WD Template', 26), t('Site Survey', 9)];
            console.log(JSON.stringify(WD.chooseWallTemplate(list, 'Site Survey').name));
        """)
        self.assertEqual(got, "Site Survey")

    def test_a_saved_default_that_has_been_deleted_falls_back_to_his(self):
        got = run_node("""
            const list = [t('Ekahau Default', 21), t('WD Template', 26)];
            console.log(JSON.stringify(WD.chooseWallTemplate(list, 'Gone').name));
        """)
        self.assertEqual(got, "WD Template",
                         "a stale default sent it to Ekahau's rather than his")

    def test_ekahau_is_chosen_only_when_he_has_nothing(self):
        """That is what 'fallback' means, and it still has to work."""
        got = run_node("""
            const list = [t('Ekahau Default', 21)];
            console.log(JSON.stringify(WD.chooseWallTemplate(list, '').name));
        """)
        self.assertEqual(got, "Ekahau Default")

    def test_an_empty_list_chooses_nothing_rather_than_throwing(self):
        got = run_node("console.log(JSON.stringify(WD.chooseWallTemplate([], '')));")
        self.assertIsNone(got)

    def test_a_default_saved_under_the_old_synthetic_name_still_means_ekahau(self):
        """Quick Walls used to offer a built-in entry called `Ekahau Defaults`."""
        got = run_node("""
            const list = [t('Ekahau Default', 21), t('WD Template', 26)];
            console.log(JSON.stringify(WD.chooseWallTemplate(list, 'Ekahau Defaults').name));
        """)
        self.assertEqual(got, "Ekahau Default")

    def test_the_label_says_which_is_which(self):
        """"Ekahau default and Standard layout should be the same - I don't
        know what the difference is." Two rows that do not say what they are."""
        got = run_node("""
            console.log(JSON.stringify([
              WD.wallTemplateLabel(t('WD Template', 26)),
              WD.wallTemplateLabel(t('Ekahau Default', 21)),
              WD.wallTemplateLabel(t('One', 1)),
            ]));
        """)
        self.assertEqual(got[0], "WD Template — yours · 26 types")
        self.assertEqual(got[1], "Ekahau Default — fallback · 21 types")
        self.assertEqual(got[2], "One — yours · 1 type", "plural not handled")


#: Cut one function out of a source file by counting braces from its opening
#: one. Ending the slice at "wherever the next function starts" swallows
#: anything inserted between them, and ending it at a two-space `}` stops at
#: the first nested block - both have produced green runs against code that
#: did not parse. `seen` is what makes it start counting at the first brace.
SLICE = r"""
function sliceFn(src, marker) {
  const a = src.indexOf(marker);
  if (a < 0) throw new Error('moved or renamed: ' + marker);
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    const c = src[b];
    if (c === '{') { depth++; seen = true; }
    else if (c === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
function fakeSelect() {
  return { innerHTML: '', value: '', options: [], disabled: false, checked: false };
}
"""


class TheTwoToolsRenderTheSameList(unittest.TestCase):
    """Driven, not read. Both render functions are run and their markup parsed.

    This replaces a set of assertions that the two files *contained*
    `WD.chooseWallTemplate(` - which is a string, and was true of Prep for the
    entire period Prep was opening on Ekahau's template. What matters is the
    option list that comes out, so that is what these read.
    """

    def _options(self, markup):
        """(label, selected) for each option in rendered markup."""
        out = []
        for m in re.finditer(r"<option\b([^>]*)>(.*?)</option>", markup, re.S):
            out.append((re.sub(r"\s+", " ", m.group(2)).strip(),
                        " selected" in m.group(1)))
        return out

    def test_quick_walls_lists_his_first_and_selects_it(self):
        markup = run_node(SLICE + """
            const pageSrc = fs.readFileSync(process.argv[2], 'utf8');
            const _tplCache = [t('Ekahau Default', 21), t('WD Template', 26)];
            let _ekahauDefaults = { name: 'Ekahau Defaults', wallTypes: [] };
            const sel = fakeSelect();
            const els = { templateSelect: sel, autoApplyCheck: fakeSelect(),
                          tplApplyBtn: fakeSelect(), autoApplyNote: null };
            global.document = { getElementById: (id) => els[id] || null };
            const loadTemplatesFromServer = async () => {};
            const ensureEkahauDefaultsLoaded = async () => {};
            const getDefaultTemplate = () => null;     // nothing saved yet
            const getAutoApply = () => false;
            const renderAutoApplyNote = () => {};
            const esc = (s) => String(s);
            const escAttr = (s) => String(s);
            eval(sliceFn(pageSrc, 'async function refreshTemplateBar()'));
            refreshTemplateBar().then(() => console.log(JSON.stringify(sel.innerHTML)));
        """, extra_args=[str(ROOT / "web" / "assets" / "js" / "walls.js")])
        opts = self._options(markup)
        self.assertEqual(len(opts), 2, f"expected two rows, got {opts}")
        self.assertTrue(opts[0][0].startswith("WD Template"), opts)
        self.assertTrue(opts[0][1], "his template is not the selected one")
        self.assertTrue(opts[1][0].startswith("Ekahau Default"), opts)
        self.assertFalse(opts[1][1], "Ekahau's template is selected")
        self.assertEqual(
            sum(1 for label, _ in opts if "Ekahau" in label), 1,
            "two Ekahau rows - the synthetic one is back, and it differs from "
            "the real one by a single character")

    def test_prep_lists_his_first_and_selects_it(self):
        markup = run_node(SLICE + """
            const pageSrc = fs.readFileSync(process.argv[2], 'utf8');
            const els = { prepWallTpl: fakeSelect(), prepCapTpl: fakeSelect() };
            const $ = (id) => els[id];
            let wallTemplates = [], capTemplates = [];
            let savedWallTemplateName = '';
            const esc = (s) => String(s);
            const escAttr = (s) => String(s);
            const plural = (n, w) => n === 1 ? w : w + 's';
            const disableStep = () => {};
            const syncStepUi = () => {};
            global.fetch = () => Promise.resolve({ json: () => Promise.resolve({
              ok: true,
              wall: [t('Ekahau Default', 21), t('WD Template', 26)],
              capacity: [{ name: 'Office', _file: 'o.json' }],
            })});
            WD.savedWallTemplateName = () => Promise.resolve('');
            eval(sliceFn(pageSrc, '  function loadTemplates()'));
            loadTemplates().then(() => console.log(JSON.stringify(els.prepWallTpl.innerHTML)));
        """, extra_args=[str(ROOT / "web" / "assets" / "js" / "prep.js")])
        opts = self._options(markup)
        self.assertEqual(len(opts), 2, f"expected two rows, got {opts}")
        self.assertTrue(opts[0][0].startswith("WD Template"),
                        f"Prep still opens on {opts[0][0]!r}")
        self.assertTrue(opts[0][1], "Prep selects nothing, so the browser picks "
                                    "option one - the defect this fixes")
        self.assertTrue(opts[1][0].startswith("Ekahau Default"), opts)


class OnlyTwoTemplatesShip(unittest.TestCase):

    def test_the_manifest_is_exactly_his_and_the_fallback(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from tools import template_store
        self.assertEqual(
            sorted(template_store.SHIPPED_TEMPLATES),
            ["Ekahau Default_walltemplate.json", "WD Template_walltemplate.json"],
            "a third template has been added to the shipped set")


if __name__ == "__main__":
    unittest.main()
