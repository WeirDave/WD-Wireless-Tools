"""The Change / Audit report as a document: what is on the page.

The comparison arithmetic is covered by ``test_change_audit_compare``. This is
the other half - that the numbers reach the page, that the page says what it
did to them, and that the state before a second file is chosen is useful rather
than blank.

``renderAuditReport`` is sliced out of report.js and run. Every assertion reads
the returned HTML. The card was marked "Coming soon" for a long time, and the
thing that has to stay true now that it is not is that picking it produces a
document rather than an empty canvas.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"

NODE_TIMEOUT_S = 120

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
globalThis.window = globalThis;
const WD = {
  esc: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                     .replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  escAttr: s => String(s == null ? '' : s).replace(/"/g, '&quot;'),
};
globalThis.WD = WD;

/* ── stubs for what the renderer reaches outside itself ─────────────────── */
const M_TO_FT = 3.28084;
/* The number formatting is taken from report.js rather than copied here. A
   copy of it in this file was the reason a real defect in ``fmt`` showed up as
   a puzzling test failure instead of a finding: the stub had the same bug, so
   the two agreed and neither was right. Anything a test is going to make an
   assertion about is the shipped code or it is nothing. */
eval(slice('  function fmtLength(meters, opts, digits)', '\n  function formatReadableDate('));
function radioIsDirectional(r) { return !!(r && typeof r.antennaDirection === 'number'); }
function floorPlanImageUrl(fp) { return 'blob:' + fp.id; }
function apNotesPages() { return '<!--notes-->'; }
function sortedFloorOrder() { return proj.floorPlans.slice(); }
const REPORT_FOOTER = '<footer class="rep-doc-foot"></footer>';

const ctx = {
  dateStr: '2026-01-01', dateReadable: '1 January 2026',
  cover: () => '<div class="cover"></div>',
  inlineHeader: () => '<div class="inline-head"></div>',
};
globalThis.ctx = ctx;

// The comparison and the renderer, exactly as shipped.
eval(slice('  var DEFAULT_MOVE_THRESHOLD_M =', '\n  window.WDCompare'));
eval(slice('  var CHANGE_WORDS = {', '\n  function renderAimReport('));

/* ── builders, same shapes the comparison test uses ─────────────────────── */
function floor(id, name, w, h, mpu) {
  return { id: id, name: name, width: w == null ? 800 : w,
           height: h == null ? 600 : h, metersPerUnit: mpu == null ? 0.05 : mpu };
}
function ap(id, name, floorId, x, y, extra) {
  return Object.assign({
    id: id, name: name, vendor: 'Vendor', model: 'Model-X',
    location: floorId === null ? {} : { floorPlanId: floorId, coord: { x: x, y: y } },
  }, extra || {});
}
function radio(apId, extra) {
  return Object.assign({ accessPointId: apId, radioTechnology: 'IEEE802_11',
                         antennaDirection: 90, antennaTilt: -10,
                         antennaHeight: 3.0, antennaMounting: 'CEILING',
                         antennaTypeId: 'ant-1' }, extra || {});
}
function project(floors, aps, radios, extra) {
  return Object.assign({
    projectName: 'Fixture', projectId: 'p1',
    floorPlans: floors, accessPoints: aps, radios: radios || [],
    antennas: { 'ant-1': { id: 'ant-1', name: 'Panel 30' },
                'ant-2': { id: 'ant-2', name: 'Omni 3dBi' } },
    buildings: {}, buildingFloors: {}, images: {}, imageUrls: {}, notes: {},
  }, extra || {});
}
globalThis.floor = floor; globalThis.ap = ap;
globalThis.radio = radio; globalThis.project = project;

/* The module-level state the renderer reads. In this scope they are globals,
   which is what lets a test put the tool into a given state. */
globalThis.proj = project([], []);
globalThis.baseline = null;
globalThis.baselineName = '';
globalThis.baselineError = '';
globalThis.fileName = 'after.esx';

function setUp(before, after, bName) {
  globalThis.baseline = before;
  globalThis.baselineName = bName || 'before.esx';
  globalThis.proj = after;
  globalThis.baselineError = '';
}
globalThis.setUp = setUp;

function render(o) { return renderAuditReport(proj.accessPoints, o || {}, ctx); }
globalThis.render = render;

function textOf(html) {
  return html.replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&')
             .replace(/&#8212;|&mdash;/g, '—')
             .replace(/\s+/g, ' ').trim();
}
globalThis.textOf = textOf;

/* The rows of the table whose heading starts with `title`. */
function rowsUnder(html, title) {
  const re = new RegExp('<h2[^>]*>' + title + '[\\s\\S]*?<tbody>([\\s\\S]*?)</tbody>');
  const m = html.match(re);
  if (!m) return null;
  return (m[1].match(/<tr[^>]*>[\s\S]*?<\/tr>/g) || []).map(r =>
    (r.match(/<td[^>]*>[\s\S]*?<\/td>/g) || []).map(c => textOf(c)));
}
globalThis.rowsUnder = rowsUnder;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function eq(what, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) failures.push(what + '\n     got:  ' + g + '\n     want: ' + w);
}
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = NODE_PRELUDE + "eval(" + json.dumps(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(REPORT_JS)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"node did not finish within {NODE_TIMEOUT_S}s") from exc


class NodeCase(unittest.TestCase):
    def run_checks(self, checks: str):
        proc = run_node(checks)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class BeforeASecondFileIsChosenTests(NodeCase):
    """The starting state. It is the one every user sees first."""

    def test_it_says_what_to_do_and_names_the_control_that_does_it(self):
        self.run_checks(r"""
          globalThis.baseline = null;
          const html = render({});
          const t = textOf(html);
          check('it names the button', t.indexOf('Choose the earlier .esx') !== -1);
          check('and where the button is',
                /options panel/.test(t) && /left/.test(t));
          check('and which file is which',
                /before/i.test(t) && /after/i.test(t));
          check('and that nothing is written',
                /Nothing is written to either file/.test(t));
          done();
        """)

    def test_the_control_it_names_is_one_that_really_renders(self):
        """Pointing at a control that does not exist is the Sync dialog fault.

        The prose bolds a button label; that exact label has to be produced by
        the option panel, not merely described in a sentence.
        """
        proc = run_node(r"""
          globalThis.baseline = null;
          const named = (render({}).match(/<b>([^<]+)<\/b>/g) || [])
            .map(s => s.replace(/<\/?b>/g, ''));
          check('the prose names controls at all', named.length > 0);
          // Every bolded label that looks like a control, not a word like
          // "before", must appear as a rendered label somewhere in report.js.
          const controls = named.filter(n => /…$|Earlier project/.test(n));
          check('at least one control is named', controls.length > 0);
          const missing = controls.filter(n => source.indexOf(n) === -1);
          eq('every named control exists', missing, []);
          done();
        """)
        if proc.returncode != 0:
            self.fail((proc.stderr or proc.stdout or "node failed").strip())

    def test_a_refused_file_says_why_on_the_page(self):
        self.run_checks(r"""
          globalThis.baseline = null;
          globalThis.baselineError = 'That .esx has no access points in it.';
          const t = textOf(render({}));
          check('the reason is shown', t.indexOf('no access points in it') !== -1);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TheDocumentTests(NodeCase):
    FIXTURE = r"""
      const F = [floor('f1', 'Level 1'), floor('f2', 'Level 2')];
      const beforeAps = [
        ap('a1', 'AP-101', 'f1', 100, 100),
        ap('a2', 'AP-102', 'f1', 300, 200),
        ap('a3', 'AP-103', 'f2', 200, 200),
        ap('gone', 'AP-199', 'f1', 600, 400),
      ];
      const afterAps = [
        ap('a1', 'AP-101', 'f1', 100, 100),                     // untouched
        ap('a2', 'AP-102', 'f1', 400, 200),                     // moved 5 m
        ap('a3', 'AP-103-R', 'f2', 200, 200),                   // renamed
        ap('new', 'AP-200', 'f1', 500, 500),                    // added
      ];
      setUp(project(F, beforeAps, beforeAps.map(a => radio(a.id))),
            project(F, afterAps, afterAps.map(a => radio(a.id))));
    """

    def test_both_filenames_are_on_the_page_and_which_is_which(self):
        self.run_checks(self.FIXTURE + r"""
          const rows = rowsUnder(render({}), 'What is being compared');
          check('the table is there', !!rows);
          eq('before names the chosen file', rows[0].slice(0, 2), ['Before', 'before.esx']);
          eq('after names the open file', rows[1].slice(0, 2), ['After', 'after.esx']);
          done();
        """)

    def test_the_counts_carry_the_change_on_each_line(self):
        self.run_checks(self.FIXTURE + r"""
          const rows = rowsUnder(render({}), 'Before and after');
          const apRow = rows.find(r => r[0] === 'Access points');
          eq('four before, four after, no net change', apRow, ['Access points', '4', '4', '0']);
          eq('one added', rows.find(r => r[0] === 'Added')[2], '1');
          eq('one removed', rows.find(r => r[0] === 'Removed')[1], '1');
          eq('two changed', rows.find(r => r[0] === 'Changed')[2], '2');
          eq('one unchanged', rows.find(r => r[0] === 'Unchanged')[2], '1');
          done();
        """)

    def test_a_changed_ap_gets_one_row_naming_everything_that_changed(self):
        self.run_checks(self.FIXTURE + r"""
          const rows = rowsUnder(render({}), 'Changed');
          eq('two rows, one per AP', rows.length, 2);
          const moved = rows.find(r => r[0] === 'AP-102');
          check('the mover is listed', !!moved);
          check('on its floor', moved[1] === 'Level 1');
          check('and says it moved, with a distance: ' + moved[2],
                /Moved/.test(moved[2]) && /ft/.test(moved[2]));
          const renamed = rows.find(r => r[0] === 'AP-103-R');
          check('the rename says both names: ' + renamed[2],
                /AP-103/.test(renamed[2]) && /AP-103-R/.test(renamed[2]));
          done();
        """)

    def test_added_and_removed_each_get_their_own_table(self):
        self.run_checks(self.FIXTURE + r"""
          const html = render({});
          eq('one added', rowsUnder(html, 'Added').map(r => r[0]), ['AP-200']);
          eq('one removed', rowsUnder(html, 'Removed').map(r => r[0]), ['AP-199']);
          // A removed AP's floor comes from the file it was in.
          eq('removed names its own floor', rowsUnder(html, 'Removed')[0][1], 'Level 1');
          done();
        """)

    def test_the_threshold_is_stated_on_the_document(self):
        """Whoever reads this has to know what was left out of it."""
        self.run_checks(self.FIXTURE + r"""
          const t = textOf(render({ moveThreshold: '1' }));
          check('the threshold is named in the chosen unit: ' + t.slice(0, 400),
                /3\.3 ft or more/.test(t));
          const m = textOf(render({ moveThreshold: '1', units: 'meters' }));
          check('and follows the units setting', /1\.00 m or more/.test(m));
          done();
        """)

    def test_the_units_option_reaches_the_distances(self):
        self.run_checks(self.FIXTURE + r"""
          const ft = rowsUnder(render({}), 'Changed').find(r => r[0] === 'AP-102')[2];
          const m  = rowsUnder(render({ units: 'meters' }), 'Changed')
                       .find(r => r[0] === 'AP-102')[2];
          check('feet by default: ' + ft, /16\.4 ft/.test(ft));
          check('metres when asked: ' + m, /5\.00 m/.test(m));
          done();
        """)

    def test_the_notes_pages_come_last(self):
        """Unbounded in length, so nothing anyone looks up by position may sit
        behind them - see tests/test_ap_notes_last.py."""
        self.run_checks(self.FIXTURE + r"""
          const html = render({});
          const notes = html.indexOf('<!--notes-->');
          check('the notes are there', notes !== -1);
          check('and nothing follows them', html.slice(notes + 12).trim() === '');
          done();
        """)

    def test_an_identical_pair_says_so_rather_than_printing_nothing(self):
        self.run_checks(r"""
          const F = [floor('f1', 'Level 1')];
          const A = [ap('a1', 'AP-101', 'f1', 100, 100)];
          const R = A.map(a => radio(a.id));
          setUp(project(F, A, R), project(F, A, R));
          const t = textOf(render({}));
          check('it says nothing changed', /Nothing changed/.test(t));
          check('and that it looked: ' + t,
                /the same in both files/.test(t));
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TheOverlayTests(NodeCase):
    FIXTURE = TheDocumentTests.FIXTURE

    def test_each_kind_of_change_is_marked_on_the_plan(self):
        self.run_checks(self.FIXTURE + r"""
          const html = render({});
          check('a moved AP is drawn where it was', /rep-aud-was/.test(html));
          check('with a line to where it is now', /rep-aud-move/.test(html));
          check('an added AP is marked', /rep-aud-added/.test(html));
          check('a removed AP is marked', /rep-aud-removed/.test(html));
          check('and an unchanged one is still shown', /rep-aud-same/.test(html));
          done();
        """)

    def test_the_key_names_every_mark_in_words(self):
        """These print, often in mono. Colour alone is not a legend."""
        self.run_checks(self.FIXTURE + r"""
          const t = textOf(render({}));
          ['Added', 'Changed', 'Was here', 'Removed', 'Unchanged'].forEach(function (w) {
            check('the key says "' + w + '"', t.indexOf(w) !== -1);
          });
          done();
        """)

    def test_the_overlay_can_be_turned_off(self):
        self.run_checks(self.FIXTURE + r"""
          const off = render({ overlay: false });
          check('no plan is drawn', !/rep-aud-added/.test(off));
          check('but the tables are still there', /Changed/.test(textOf(off)));
          done();
        """)

    def test_a_re_cropped_floor_is_explained_on_the_page(self):
        """Correcting the numbers silently would be its own defect."""
        self.run_checks(r"""
          const bF = [floor('f1', 'Level 1', 1000, 800)];
          const aF = [floor('f1', 'Level 1', 700, 500)];
          const bAps = [ap('a1', 'AP-1', 'f1', 300, 300), ap('a2', 'AP-2', 'f1', 500, 400),
                        ap('a3', 'AP-3', 'f1', 700, 600), ap('a4', 'AP-4', 'f1', 400, 500)];
          const aAps = bAps.map(a => ap(a.id, a.name, 'f1',
                                        a.location.coord.x - 150, a.location.coord.y - 150));
          setUp(project(bF, bAps), project(aF, aAps));
          const html = render({});
          const t = textOf(html);
          check('the section is there', /re-cropped/.test(t));
          check('it explains why it matters: ' + t.slice(0, 900),
                /would be reported as having moved/.test(t));
          const rows = rowsUnder(html, 'Floor plans that were re-cropped');
          eq('the floor, both sizes and the shift',
             rows[0], ['Level 1', '1000×800', '700×500', '-150, -150 px']);
          check('and nothing was reported as moved', !/Moved/.test(t));
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ANumberEndingInZeroKeepsItsZeroTests(NodeCase):
    """Found while building this report, and it was already shipping.

    ``fmt`` trimmed a trailing zero that says nothing - 12.50 is 12.5 - with
    ``toFixed(dp).replace(/\\.?0+$/, '')``. Asked for no decimals there is no
    decimal point to stop the match, so it ate the number's own digits:
    ``fmt(20, 0)`` returned "2". One caller does that in shipped output, the
    transmit power on an AP Placement Map label, so a design carrying 20 dBm
    printed **2 dBm** on the sheet an installer works from.

    This file used to carry its own copy of ``fmt`` as a stub. The copy had the
    same bug, so the two agreed with each other and the defect showed up as a
    confusing failure rather than a finding. The prelude slices the real one in
    now, which is the general rule: what a test asserts about is the shipped
    code or it is nothing.
    """

    def test_whole_numbers_survive_intact(self):
        self.run_checks(r"""
          eq('twenty', fmt(20, 0), '20');
          eq('one hundred', fmt(100, 0), '100');
          eq('a due-south azimuth', fmt(180, 0), '180');
          eq('negative', fmt(-150, 0), '-150');
          eq('and one that never had a zero', fmt(23, 0), '23');
          eq('zero itself', fmt(0, 0), '0');
          done();
        """)

    def test_a_pointless_decimal_zero_is_still_dropped(self):
        """The behaviour that was wanted, which must not be lost in the fix."""
        self.run_checks(r"""
          eq('12.50 reads as 12.5', fmt(12.5, 2), '12.5');
          eq('10.0 reads as 10', fmt(10, 1), '10');
          eq('and a real decimal is kept', fmt(12.34, 2), '12.34');
          eq('100.0 keeps its hundred', fmt(100, 1), '100');
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TheCardIsNoLongerComingSoonTests(NodeCase):
    """The gallery would not open it at all while the status said otherwise.

    The registry is evaluated rather than read: ``selectReport`` returns early
    on ``status: 'coming-soon'``, so the value is what decides whether the card
    can be opened, and reading it out of the built object is the only way to
    know what the page will see.
    """

    #: The whole REPORTS registry, built for real. It is a plain object literal
    #: whose entries name render functions, so those are stubbed to something
    #: recognisable and the object is the thing under test.
    PRELUDE = r"""
      const REGISTRY = slice('  var REPORTS = {', '\n  renderTemplateGallery();');
      /* Whatever the registry names and this scope does not have: a preview
         becomes an empty string, everything else a stub that remembers what it
         was called. Derived from the block rather than listed, so a report
         added later does not have to be added here too - a hand-written list
         is how a new card gets skipped silently. */
      (REGISTRY.match(/\b[A-Za-z_$][\w$]*\b/g) || []).forEach(function (n) {
        if (n in globalThis) return;
        try { (0, eval)(n); return; } catch (err) {
          if (!(err instanceof ReferenceError)) return;
        }
        if (/^PREVIEW_/.test(n)) { globalThis[n] = ''; return; }
        globalThis[n] = function named() {};
        globalThis[n].wdName = n;
      });
      eval(REGISTRY);
      globalThis.REPORTS = REPORTS;
    """

    def run_checks(self, checks: str):
        super().run_checks(self.PRELUDE + checks)

    def test_the_audit_card_is_ready_and_has_a_renderer(self):
        self.run_checks(r"""
          eq('the card is ready', REPORTS.audit.status, 'ready');
          check('and it has a renderer',
                typeof REPORTS.audit.render === 'function');
          /* The real renderer, not a stub: this prelude already evaluated it,
             so the registry is wired to the function under test in the rest of
             this file rather than to something invented here. */
          eq('which is the audit one', REPORTS.audit.render.name,
             'renderAuditReport');
          check('and it is the same function this file tests',
                REPORTS.audit.render === renderAuditReport);
          done();
        """)

    def test_nothing_is_marked_coming_soon_any_more(self):
        """It was the last one. If a new card arrives unfinished this fails,
        which is the right moment to decide whether that is intended."""
        self.run_checks(r"""
          const soon = Object.keys(REPORTS)
            .filter(k => REPORTS[k].status === 'coming-soon');
          eq('no card is unopenable', soon, []);
          done();
        """)

    def test_every_card_has_a_renderer_the_gallery_can_call(self):
        """A card the gallery opens onto nothing is the same fault pointing
        the other way."""
        self.run_checks(r"""
          const broken = Object.keys(REPORTS)
            .filter(k => typeof REPORTS[k].render !== 'function');
          eq('every card renders', broken, []);
          done();
        """)

    def test_the_panel_offers_the_file_picker_and_the_threshold(self):
        self.run_checks(r"""
          const ids = REPORTS.audit.sidebar.map(o => o.id);
          const types = REPORTS.audit.sidebar.map(o => o.type || 'check');
          check('there is a file picker', types.indexOf('baseline-button') !== -1);
          check('a movement threshold', ids.indexOf('moveThreshold') !== -1);
          check('and the overlay can be turned off', ids.indexOf('overlay') !== -1);
          // The picker comes first: it is the one thing without which nothing
          // else on the panel does anything.
          eq('the picker leads the panel', types[0], 'baseline-button');
          done();
        """)

    def test_the_threshold_default_matches_what_the_comparison_uses(self):
        """Two numbers for one thing is how the report comes to state a
        threshold it did not apply."""
        self.run_checks(r"""
          const opt = REPORTS.audit.sidebar.find(o => o.id === 'moveThreshold');
          eq('half a metre, as the comparison has it',
             Number(opt.default), DEFAULT_MOVE_THRESHOLD_M);
          done();
        """)

    def test_the_picker_has_its_own_input_separate_from_the_drop_zone(self):
        """Reusing #fileInput would replace the project being reported on.

        Parsed rather than matched as text: two inputs with the same id would
        satisfy a substring check and break the page.
        """
        html = (ROOT / "web" / "report.html").read_text(encoding="utf-8")
        ids = re.findall(r'<input[^>]*type="file"[^>]*id="([^"]+)"', html)
        self.assertIn("fileInput", ids)
        self.assertIn("baselineInput", ids)
        self.assertEqual(len(ids), len(set(ids)), "two file inputs share an id")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
