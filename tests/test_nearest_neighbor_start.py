"""AP Labeler, Nearest Neighbor: the start of the walk is the engineer's to pick.

The walk used to begin at whichever AP sat nearest the top-left corner of the
group, with no way to say otherwise. On a plan whose numbering has to begin at
the entrance, the stairwell or the far end of a corridor that is simply the
wrong AP, and everything after it follows from the first one.

Clicking an AP on the plan while Nearest Neighbor is selected now makes it the
start for that floor; clicking it again hands the choice back to Auto. These
tests run the real sortProximity and the real click handler in Node.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AP_JS = ROOT / "web" / "assets" / "js" / "ap-rename.js"

NODE_TIMEOUT_S = 120

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');

function slice(from, to) {
  const a = source.indexOf(from), b = source.indexOf(to);
  if (a < 0) throw new Error('moved: ' + from);
  if (b < 0) throw new Error('moved: ' + to);
  return source.slice(a, b);
}
// Count braces rather than slicing to the next function: anything inserted
// between two functions would otherwise be swallowed.
function whole(from) {
  const a = source.indexOf(from);
  if (a < 0) throw new Error('moved: ' + from);
  let b = a, depth = 0, seen = false;
  while (b < source.length && !(seen && depth === 0)) {
    if (source[b] === '{') { depth++; seen = true; }
    else if (source[b] === '}') depth--;
    b++;
  }
  return source.slice(a, b);
}

eval(slice('  function sortProximity(aps, startId) {', '  function sortSnake(aps, floor)'));
eval(slice('  function _dist(a, b) {', '  function sortByRow(aps, reverse'));

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
function names(p) { return p.map(a => a.id).join(''); }
function len(p) {
  let t = 0;
  for (let i = 1; i < p.length; i++) t += _dist(p[i - 1], p[i]);
  return t;
}
"""


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = NODE_PRELUDE + "eval(" + json.dumps(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(AP_JS)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s - a Node startup "
            f"timeout, not a failure of the code under test.") from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheWalkStartsWhereHeSaidTests(unittest.TestCase):

    def run_block(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_a_picked_ap_comes_first_and_the_walk_continues_from_it(self):
        """Along a corridor, starting in the middle goes to the nearer
        neighbour, then on to the rest - not back to the end it would have
        started at."""
        self.run_block("""
          var aps = [{id:'A',x:0,y:0},{id:'B',x:100,y:0},{id:'C',x:230,y:0},
                     {id:'D',x:370,y:0},{id:'E',x:530,y:0}];
          check('Auto starts at the left end: ' + names(sortProximity(aps)),
                names(sortProximity(aps)) === 'ABCDE');
          var from = sortProximity(aps, 'C');
          check('C first, then the nearer side: ' + names(from),
                names(from) === 'CBADE');
          var end = sortProximity(aps, 'E');
          check('starting at the far end walks back along the corridor: ' +
                names(end), names(end) === 'EDCBA');
          done();
        """)

    def test_every_start_is_honoured_and_nothing_is_lost(self):
        """Whatever AP is picked it is first, and every AP appears once -
        a dropped or repeated name would reach an installer's drawing."""
        self.run_block("""
          var seed = 5;
          function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff;
                           return seed / 0x7fffffff; }
          for (var t = 0; t < 30; t++) {
            var n = 3 + Math.floor(rnd() * 25), aps = [];
            for (var i = 0; i < n; i++) {
              aps.push({id:'p'+i, x: Math.round(rnd()*1200), y: Math.round(rnd()*800)});
            }
            var pick = 'p' + Math.floor(rnd() * n);
            var out = sortProximity(aps, pick), seen = {};
            out.forEach(function (a) { seen[a.id] = 1; });
            check('picked AP first at n=' + n, out[0].id === pick);
            check('count kept at n=' + n,
                  out.length === n && Object.keys(seen).length === n);
          }
          done();
        """)

    def test_a_pick_the_set_does_not_hold_falls_back_to_the_corner(self):
        """A pick left from another floor, colour or project must not number
        from nowhere."""
        self.run_block("""
          var aps = [{id:'A',x:5,y:5},{id:'B',x:300,y:40},{id:'C',x:90,y:260},
                     {id:'D',x:700,y:300}];
          check('unknown id behaves as Auto',
                names(sortProximity(aps, 'gone')) === names(sortProximity(aps)));
          check('null behaves as Auto',
                names(sortProximity(aps, null)) === names(sortProximity(aps)));
          done();
        """)

    def test_a_pair_honours_the_pick_too(self):
        self.run_block("""
          var two = [{id:'A',x:1,y:1},{id:'B',x:9,y:9}];
          check('Auto: top-left first', names(sortProximity(two)) === 'AB');
          check('picked second goes first', names(sortProximity(two, 'B')) === 'BA');
          check('a lone AP is fine', names(sortProximity([two[0]], 'A')) === 'A');
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ClickingAnApPicksTheStartTests(unittest.TestCase):
    """The click handler itself, with the page's state stubbed."""

    HARNESS = r"""
      eval(whole('  function isProximity() {'));
      eval(whole('  window.arStartClick = function (apId) {') + ';');
      eval(whole('  window.arStartReset = function () {') + ';');
      var window = global.window || {};
      var S, order, _zoom, toasts, redraws;
      function setup(o) {
        S = { currentFloor: o.floor === undefined ? 'f1' : o.floor,
              startAp: o.startAp || {},
              aps: [{id:'a1',name:'AP-001'},{id:'a2',name:'AP-002'}] };
        order = o.order || 'proximity';
        _zoom = { suppressClick: !!o.suppress };
        toasts = []; redraws = 0;
      }
      function $(id) { return { value: order }; }
      function toast(m) { toasts.push(m); }
      function updateAll() { redraws++; }
    """

    def run_block(self, checks: str):
        # The handlers are assigned to `window.`, so give them one to land on.
        full = ("var window = {};\n" + self.HARNESS.replace(
            "var window = global.window || {};", "") + checks)
        result = run_node(full)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_a_click_sets_the_start_for_that_floor_and_redraws(self):
        self.run_block("""
          setup({});
          window.arStartClick('a2');
          check('start recorded for the floor on screen', S.startAp.f1 === 'a2');
          check('numbers were recalculated', redraws === 1);
          check('he is told which AP: ' + toasts, /AP-002/.test(toasts[0]));
          done();
        """)

    def test_clicking_the_start_again_returns_to_auto(self):
        self.run_block("""
          setup({ startAp: { f1: 'a2' } });
          window.arStartClick('a2');
          check('start cleared', !('f1' in S.startAp));
          check('and redrawn', redraws === 1);
          done();
        """)

    def test_another_floors_start_is_left_alone(self):
        self.run_block("""
          setup({ startAp: { f2: 'a1' } });
          window.arStartClick('a2');
          check('f2 untouched', S.startAp.f2 === 'a1');
          check('f1 set', S.startAp.f1 === 'a2');
          done();
        """)

    def test_it_does_nothing_in_any_other_ordering(self):
        """Manual has its own meaning for a click on an AP."""
        self.run_block("""
          setup({ order: 'manual' });
          window.arStartClick('a1');
          check('manual: no start recorded', !('f1' in S.startAp));
          check('manual: no redraw', redraws === 0);
          setup({ order: 'row-ltr' });
          window.arStartClick('a1');
          check('rows: no start recorded', !('f1' in S.startAp));
          done();
        """)

    def test_it_does_nothing_on_the_unplaced_tab(self):
        self.run_block("""
          setup({ floor: '__unplaced' });
          window.arStartClick('a1');
          check('nothing recorded', Object.keys(S.startAp).length === 0);
          check('no redraw', redraws === 0);
          done();
        """)

    def test_the_click_that_ends_a_pan_is_not_a_pick(self):
        self.run_block("""
          setup({ suppress: true });
          window.arStartClick('a1');
          check('no start from a pan', !('f1' in S.startAp));
          check('the flag is spent', _zoom.suppressClick === false);
          window.arStartClick('a1');
          check('the next click counts', S.startAp.f1 === 'a1');
          done();
        """)

    def test_the_reset_button_clears_only_this_floor(self):
        self.run_block("""
          setup({ startAp: { f1: 'a1', f2: 'a2' } });
          window.arStartReset();
          check('this floor cleared', !('f1' in S.startAp));
          check('the other kept', S.startAp.f2 === 'a2');
          check('redrawn', redraws === 1);
          done();
        """)


if __name__ == "__main__":
    unittest.main()
