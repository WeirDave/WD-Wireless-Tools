"""A landscape report: the cover turns with it, and section maps fill the sheet.

Two faults, both measured by printing the AP Placement Map through Chromium and
reading the PDF back:

* **The cover never turned.** It carried no page key, so the orientation pass
  never saw it and even "Match all pages" went straight past it. Every
  landscape report opened on one upright sheet.
* **Section maps were sized for portrait whatever the sheet was.** The limits
  were fixed at 6.9in by 7.48in, so a section page turned landscape printed an
  11in-wide sheet with a 6.9in map in the middle. Measured after the fix: 9.46in
  on the same section.

And two found on the way, by the same measurement:

* On a tall building the Key Plan thumbnail is 90px wide at the plan's aspect,
  about 2in tall, which pushed the section map off the sheet in portrait - the
  header printed on one sheet and the map on the next. It is capped now, and the
  map is sized from what is actually above it.
* On Auto a sectioned floor always stayed portrait, whatever shape its sections
  were, while a whole-floor map on Auto picked the way round that prints it
  bigger. It uses the same test now.

These run the real functions in Node over a small stand-in for the DOM: the
questions are all about which class ends up on which page and what size is
written, which is what the print stylesheet reads.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function fn(sig) {
  const a = src.indexOf(sig);
  if (a < 0) throw new Error('moved: ' + sig);
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b) + '\n';
}
function constant(name) {
  const m = src.match(new RegExp('var ' + name + ' = [^;]+;'));
  if (!m) throw new Error('moved: ' + name);
  return m[0] + '\n';
}
let code = '';
['SHEET_W_IN', 'SHEET_H_IN', 'ROTATE_GAIN', 'SEG_HEAD_IN', 'SEG_INDEX_HEAD_IN',
 'SEG_BELOW_IN', 'SEG_FOOT_IN', 'SEG_FOOT_CONF_IN', 'KEY_PLAN_W_IN', 'KEY_PLAN_MAX_H_IN'].forEach(n => { code += constant(n); });
['function pageOrientMode(', 'function orientCover(', 'function segOverlayRatio(',
 'function segPrintSizeIn(', 'function sizeAntennaSegmentForPrint(',
 'function segmentedFloorWantsLandscape(', 'function keyPlanHeightIn(', 'function footerBelowIn(',
 'function resizeSegmentsForPrint('].forEach(s => { code += fn(s); });
eval(code);

// Just enough DOM: classes, attributes, inline custom properties, parents,
// and the handful of selector shapes these functions use.
class El {
  constructor(cls, attrs, kids) {
    this.cls = new Set((cls || '').split(' ').filter(Boolean));
    this.attrs = attrs || {};
    this.kids = kids || [];
    this.kids.forEach(k => { k.parent = this; });
    this.props = {};
    const self = this;
    this.classList = {
      contains: (c) => self.cls.has(c),
      toggle: (c, on) => { if (on) self.cls.add(c); else self.cls.delete(c); },
    };
    this.style = {
      setProperty: (k, v) => { self.props[k] = v; },
      getPropertyValue: (k) => self.props[k] || '',
    };
    this.textContent = '';
    this.tagName = 'SECTION';
  }
  // The calls orientCover makes since the cover began counting every sheet.
  get children() { return this.kids; }
  compareDocumentPosition(o) {
    let root = this; while (root.parent) root = root.parent;
    const order = [root].concat(root.all());
    return order.indexOf(o) > order.indexOf(this) ? 4 : 2;
  }
  getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; }
  matches(sel) {
    const not = sel.match(/:not\((.*)\)$/);
    if (not) return this.matches(sel.slice(0, not.index)) && !this.matches(not[1]);
    const parts = sel.match(/\.[\w-]+|\[[\w-]+(="[^"]*")?\]/g) || [];
    return parts.every(p => {
      if (p[0] === '.') return this.cls.has(p.slice(1));
      const m = p.match(/\[([\w-]+)(?:="([^"]*)")?\]/);
      return m[2] === undefined ? m[1] in this.attrs : this.attrs[m[1]] === m[2];
    });
  }
  closest(sel) {
    for (let e = this; e; e = e.parent) if (e.matches(sel)) return e;
    return null;
  }
  all() { return this.kids.flatMap(k => [k].concat(k.all())); }
  querySelectorAll(sel) {
    const steps = sel.split(' ');
    return this.all().filter(e => {
      if (!e.matches(steps[steps.length - 1])) return false;
      let at = e.parent;
      for (let i = steps.length - 2; i >= 0; i--) {
        while (at && at !== this && !at.matches(steps[i])) at = at.parent;
        if (!at || at === this) return false;
        at = at.parent;
      }
      return true;
    });
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

function cover() {
  return new El('rep-cover rep-oriented', { 'data-page-key': 'cover', 'data-page-kind': 'cover' },
                [new El('rep-orient-now')]);
}
function page(key, landscape, sections) {
  const kids = [];
  for (let i = 0; i < (sections || 0); i++) kids.push(new El('rep-seg-cell'));
  return new El('rep-oriented' + (landscape ? ' is-landscape' : ''), { 'data-page-key': key }, kids);
}
// A section sheet: a key plan thumbnail at the plan's aspect and a map
// overlay covering `w` x `h` plan units.
function sectionOverlay(w, h, planW, planH) {
  const loc = new El('rep-seg-locator');
  loc.style.setProperty('--w', String(planW || 3000));
  loc.style.setProperty('--h', String(planH || 1200));
  const ov = new El('rep-overview-plan', { 'data-seg': '1', 'data-seg-x0': '0', 'data-seg-y0': '0',
                                          'data-seg-x1': String(w), 'data-seg-y1': String(h) });
  return { sheet: new El('rep-seg-cell', {}, [loc, ov]), overlay: ov };
}
const inches = (v) => parseFloat(v);

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


class _NodeProbe(unittest.TestCase):
    def check(self, body: str):
        program = PRELUDE + "eval(" + json.dumps(body) + ");"
        r = subprocess.run(["node", "-e", program, str(REPORT_JS)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheCoverFollowsTheReport(_NodeProbe):
    def test_the_rendered_cover_is_a_page_the_orientation_pass_can_find(self):
        """The original fault: the real cover markup had no page key, so
        nothing - not Auto, not Match all pages - could ever turn it."""
        self.check("""
          eval(fn('function orientPickerHtml(') + fn('function renderCover('));
          globalThis.WD = { esc: String, escAttr: String };
          globalThis.proj = { floorPlans: [{}] };
          globalThis.coverImage = null;
          globalThis.siteName = () => 'Example Site';
          const html = renderCover(3, '2026-01-01', { coverBrand: 'Report' }, 'APs', {}, {});
          check('the cover has no page key', /class="rep-cover[^"]*"[^>]*data-page-key="cover"/.test(html));
          check('the cover is not on a named page', /class="rep-cover rep-oriented/.test(html));
          check('the cover has no orientation picker', /rep-orient[^-]/.test(html));
          done();
        """)

    def test_the_orientation_pass_turns_the_cover(self):
        """Run through applyPageOrientation, which is what every report
        calls - not only orientCover on its own."""
        self.check("""
          eval(fn('function autoOrientationFor(') + fn('function seatFooter(') + fn('function applyPageOrientation('));
          const c = cover();
          const host = new El('', {}, [c, page('placement:f1', true), page('key:f1', false)]);
          host.kids[1].attrs['data-page-kind'] = 'plan';
          host.kids[2].attrs['data-page-kind'] = 'plan';
          host.kids[2].cls.add('is-landscape');
          applyPageOrientation(host, {});
          check('the pass did not turn the cover', c.classList.contains('is-landscape'));
          done();
        """)

    def test_a_landscape_report_gets_a_landscape_cover(self):
        self.check("""
          const c = cover();
          const host = new El('', {}, [c, page('placement:f1', true), page('key:f1', true)]);
          orientCover(host, {});
          check('the cover stayed upright in an all-landscape report', c.classList.contains('is-landscape'));
          check('the picker does not say what Auto chose: ' + c.kids[0].textContent,
                /auto .*landscape/.test(c.kids[0].textContent));
          done();
        """)

    def test_a_portrait_report_keeps_a_portrait_cover(self):
        self.check("""
          const c = cover();
          c.classList.toggle('is-landscape', true);   // left over from a previous render
          const host = new El('', {}, [c, page('placement:f1', false), page('key:f1', false)]);
          orientCover(host, {});
          check('the cover turned in an upright report', !c.classList.contains('is-landscape'));
          done();
        """)

    def test_sheets_are_counted_not_elements(self):
        """Eight landscape section sheets are one element. A single upright
        compass page must not outvote them."""
        self.check("""
          const c = cover();
          const host = new El('', {}, [c, page('placement:f1', true, 8), page('compass', false)]);
          orientCover(host, {});
          check('one portrait page outvoted eight landscape sheets', c.classList.contains('is-landscape'));
          done();
        """)

    def test_a_tie_goes_to_the_page_after_the_cover(self):
        self.check("""
          const a = cover();
          orientCover(new El('', {}, [a, page('p1', true), page('p2', false)]), {});
          check('tie did not follow the first page (landscape)', a.classList.contains('is-landscape'));
          const b = cover();
          orientCover(new El('', {}, [b, page('p1', false), page('p2', true)]), {});
          check('tie did not follow the first page (portrait)', !b.classList.contains('is-landscape'));
          done();
        """)

    def test_a_choice_made_for_the_cover_wins(self):
        """It carries a picker like every other page, and Match all pages
        reaches it through its page key."""
        self.check("""
          const c = cover();
          const host = new El('', {}, [c, page('placement:f1', true)]);
          orientCover(host, { pageOrient: { cover: 'portrait' } });
          check('a portrait choice was overridden', !c.classList.contains('is-landscape'));
          check('the cover has no page key for Match all pages to find',
                host.querySelectorAll('[data-page-key]').indexOf(c) > -1);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class SectionMapsFillTheSheet(_NodeProbe):
    def test_a_landscape_section_uses_the_width_of_the_sheet(self):
        """The fault as reported: an 11in sheet with a 6.9in map on it."""
        self.check("""
          const s = sectionOverlay(1500, 900);
          const pg = page('placement:f1', true); pg.kids.push(s.sheet); s.sheet.parent = pg;
          sizeAntennaSegmentForPrint(s.overlay);
          const w = inches(s.overlay.props['--print-w']), h = inches(s.overlay.props['--print-h']);
          check('landscape section still sized for portrait: ' + w + 'in', w > 9);
          check('wider than the printable width: ' + w, w <= 10.0);
          check('taller than a landscape sheet leaves room for: ' + h, h <= 7.45 - 1.0);
          check('distorted: ' + (w / h), Math.abs(w / h - 1500 / 900) < 0.01);
          done();
        """)

    def test_portrait_is_unchanged_for_an_ordinary_section(self):
        """Everybody printing portrait gets exactly what they had."""
        self.check("""
          const s = sectionOverlay(1500, 1200);
          const pg = page('placement:f1', false); pg.kids.push(s.sheet); s.sheet.parent = pg;
          sizeAntennaSegmentForPrint(s.overlay);
          check('portrait section moved: ' + s.overlay.props['--print-w'],
                s.overlay.props['--print-w'] === '6.900in');
          done();
        """)

    def test_a_tall_buildings_key_plan_does_not_push_the_map_off_the_sheet(self):
        """1200x2600 plan: the thumbnail was 2in tall and the map was still
        given 7.48in, so the header and the map landed on different sheets."""
        self.check("""
          check('the thumbnail is not capped: ' + keyPlanHeightIn(sectionOverlay(1, 1, 1200, 2600).sheet),
                keyPlanHeightIn(sectionOverlay(1, 1, 1200, 2600).sheet) <= 1.1);
          const s = sectionOverlay(1200, 1300, 1200, 2600);
          const pg = page('placement:f1', false); pg.kids.push(s.sheet); s.sheet.parent = pg;
          sizeAntennaSegmentForPrint(s.overlay);
          const h = inches(s.overlay.props['--print-h']);
          const above = SEG_HEAD_IN + keyPlanHeightIn(s.sheet);
          check('header, map and key overrun a portrait sheet: ' + (above + h + SEG_BELOW_IN),
                above + h + SEG_BELOW_IN <= SHEET_H_IN + 1e-9);
          done();
        """)

    def test_the_placement_pass_applies_auto_to_a_sectioned_floor(self):
        """The decision above is only worth anything if the pass that runs
        after every render uses it, and records it where the page can see."""
        self.check("""
          eval(fn('function planAspect(') + fn('function sizePlacementPlansForPrint(')
               + constant('SHEET_CHROME_IN') + constant('SHEET_SLACK_IN'));
          function floor(w, h) {
            const pg = new El('rep-placement-page rep-oriented', { 'data-page-key': 'placement:f1' },
                              [new El('rep-orient-now')]);
            for (let i = 0; i < 2; i++) {
              const s = sectionOverlay(w, h); pg.kids.push(s.sheet); s.sheet.parent = pg;
            }
            return pg;
          }
          const wide = floor(3000, 1400), tall = floor(1200, 2600);
          sizePlacementPlansForPrint(new El('', {}, [wide, tall]), {});
          check('a wide sectioned floor stayed upright on Auto', wide.classList.contains('is-landscape'));
          check('a tall sectioned floor turned on Auto', !tall.classList.contains('is-landscape'));
          check('the picker does not say what Auto chose: ' + wide.kids[0].textContent,
                /auto .*landscape/.test(wide.kids[0].textContent));
          const forced = floor(1200, 2600);
          sizePlacementPlansForPrint(new El('', {}, [forced]),
                                     { pageOrient: { 'placement:f1': 'landscape' } });
          check('an explicit landscape was ignored', forced.classList.contains('is-landscape'));
          done();
        """)

    def test_auto_turns_a_sectioned_floor_only_when_it_prints_bigger(self):
        """The same bargain a whole-floor map makes: turning the paper has to
        buy ROTATE_GAIN in scale. Wide sections turn, tall ones do not, and a
        section only slightly wider than tall is not worth the turn."""
        self.check("""
          function floorOf(w, h, n) {
            const pg = page('placement:f1', false);
            for (let i = 0; i < n; i++) {
              const s = sectionOverlay(w, h); pg.kids.push(s.sheet); s.sheet.parent = pg;
            }
            return pg;
          }
          check('wide sections stayed upright', segmentedFloorWantsLandscape(floorOf(3000, 1400, 2)));
          check('tall sections turned', !segmentedFloorWantsLandscape(floorOf(1200, 2600, 2)));
          check('a near-square section turned', !segmentedFloorWantsLandscape(floorOf(1500, 1200, 2)));
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheNameListUsesALandscapeSheet(_NodeProbe):
    """On a landscape sheet the AP name list was one narrow column down the
    left of 10in of paper: 24 names ran the footer onto a sheet of its own,
    and 70 took three sheets where portrait takes two. It now runs in two
    columns side by side - measured: 24 names on one sheet, 70 on two.

    A name is copied onto hardware by hand and is never wrapped, so the two
    columns are only offered when every name fits half the sheet. These run
    the real renderer; the print stylesheet only acts on the class once the
    page has been turned landscape."""

    def render(self, names):
        return """
          eval(constant('KEY_PAIR_MAX_CHARS') + fn('function renderApNameKeySection('));
          globalThis.WD = { esc: String, escAttr: String };
          globalThis.apLabel = (ap, kind) => kind === 'short' ? ap.short : ap.name;
          globalThis.orientPickerHtml = () => '';
          globalThis.referencePageHead = () => '<h2>AP Labels</h2>';
          globalThis.renderReportFooter = () => '<footer></footer>';
          globalThis.structuredSegments = () => null;
          globalThis.labelerPattern = null;
          const names = %s;
          const html = renderApNameKeySection({ id: 'f1', name: 'Floor 1' },
            names.map((n, i) => ({ id: 'a' + i, name: n, short: String(i + 1) })), {}, {}, 0);
        """ % json.dumps(names)

    def test_short_names_are_offered_two_columns_with_a_header_for_each(self):
        self.check(self.render(["AP %d" % i for i in range(1, 25)]) + """
          check('no two-column class on a list of short names', /rep-key-table--pairs/.test(html));
          const head = (html.match(/<div class="rep-key-pairs-head"[^]*?<[/]div>/) || [''])[0];
          check('the two-column header does not head both columns: ' + head,
                (head.match(/Full AP name/g) || []).length === 2);
          check('a name went missing', (html.match(/<tr>/g) || []).length === 25);
          done();
        """)

    def test_a_name_too_long_for_half_the_sheet_keeps_one_column(self):
        long = "BLDG-EXAMPLE-NORTH-WAREHOUSE-MEZZANINE-LEVEL-2-AP-017"
        self.check(self.render(["AP 1", long]) + """
          check('a long name was put in a half-width column',
                !/rep-key-table--pairs/.test(html) && !/rep-key-pairs-head/.test(html));
          check('the long name was altered', html.indexOf(LONG) > -1);
          done();
        """.replace("LONG", json.dumps(long)))


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheCompassRoseIsDrawnWhole(_NodeProbe):
    """N, E, S and W were centred 158 units out on a 320-unit drawing whose
    edge is 160 out, so the outer half of each letter was cut off on every
    printed compass page, portrait and landscape alike. Runs the real
    renderer and checks every label's extent against the drawing it is in.

    The degree ring's print size (under 6pt on a landscape sheet until it was
    enlarged there) is a property of the printed PDF, not of this markup, and
    was measured there: 6.2pt and up in landscape, 6.4pt and up in portrait."""

    def test_every_direction_letter_fits_inside_the_drawing(self):
        self.check("""
          eval(fn('function renderCompassReferencePage('));
          globalThis.orientPickerHtml = () => '';
          const html = renderCompassReferencePage({}, {});
          const vb = (html.match(/viewBox="([^"]+)"/) || [])[1].split(' ').map(Number);
          // Font sizes in viewBox units, as the stylesheet sets them; half a
          // capital's advance and half its height are both under 0.5em.
          const em = { 'rep-comp-cardinal': 19, 'rep-comp-intercard': 17 };
          const re = /<text x="([^"]+)" y="([^"]+)" class="(rep-comp-(?:cardinal|intercard))[^"]*"[^>]*>([A-Z]+)</g;
          let m, n = 0;
          while ((m = re.exec(html))) {
            n++;
            const x = +m[1], y = +m[2], half = em[m[3]] * 0.5 * Math.max(1, m[4].length * 0.75);
            check(m[4] + ' runs off the drawing: centre ' + x.toFixed(1) + ',' + y.toFixed(1),
                  x - half >= vb[0] && x + half <= vb[0] + vb[2]
                  && y - em[m[3]] * 0.5 >= vb[1] && y + em[m[3]] * 0.5 <= vb[1] + vb[3]);
          }
          check('expected 8 direction labels, found ' + n, n === 8);
          done();
        """)


if __name__ == "__main__":
    unittest.main()
