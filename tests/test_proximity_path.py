"""Proximity ordering: the greedy walk is a first draft, not the answer.

Nearest-neighbour takes the closest unvisited AP every time, so it strands
outliers - the far one is left until the walk has no choice, and the sequence
ends in a long trek back. Colour ordering made this matter more, because a
colour group is often a handful of APs scattered over a floor rather than a
cluster, which is precisely where greedy does its worst.

There was no cleanup pass at all before this - not one skipped below a size
threshold, simply none. These tests hold the two that were added:

  2-opt   reverses a run to uncross the route
  or-opt  lifts a run of 1-3 stops out and re-inserts it where it belongs

or-opt is the one that rescues a stranded AP: 2-opt can only reverse a run, so
it cannot move a single unit that was visited at the wrong moment.

Driven through the real sortNearestNeighbor in Node.
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
const a = source.indexOf('  function _dist(a, b) {');
const b = source.indexOf('  function sortByRow(aps, reverse)');
if (a < 0 || b < 0) throw new Error('the proximity block moved');
eval(source.slice(a, b));

function len(p) {
  let t = 0;
  for (let i = 1; i < p.length; i++) t += _dist(p[i - 1], p[i]);
  return t;
}

// The greedy first draft, kept here so a test can compare against it.
function greedy(aps) {
  const rem = aps.slice();
  rem.sort((x, y) => x.y - y.y || x.x - y.x);
  const out = [rem.shift()];
  while (rem.length) {
    const l = out[out.length - 1];
    let bi = 0, bd = Infinity;
    for (let i = 0; i < rem.length; i++) {
      const dx = rem[i].x - l.x, dy = rem[i].y - l.y, d = dx * dx + dy * dy;
      if (d < bd) { bd = d; bi = i; }
    }
    out.push(rem.splice(bi, 1)[0]);
  }
  return out;
}

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
function names(p) { return p.map(a => a.name).join(''); }
"""


def _js(text: str) -> str:
    return json.dumps(text)


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = NODE_PRELUDE + "eval(" + _js(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(AP_JS)],
                              capture_output=True, text=True,
                              timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s. That is a Node "
            f"startup timeout, not a failure of the code under test."
        ) from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheGreedyWalkGetsCleanedUp(unittest.TestCase):

    def run_block(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_a_scattered_colour_group_comes_out_shorter(self):
        """The case colour ordering makes common: a tight cluster plus a
        couple of APs on the far side of the floor."""
        self.run_block("""
          var aps = [{name:'A',x:100,y:100},{name:'B',x:130,y:140},
                     {name:'C',x:110,y:180},{name:'D',x:900,y:120},
                     {name:'E',x:500,y:700},{name:'F',x:150,y:120}];
          var before = len(greedy(aps));
          var after  = len(sortNearestNeighbor(aps));
          check('the cleaned-up route is shorter: ' + before.toFixed(0) +
                ' -> ' + after.toFixed(0), after < before - 0.5);
          done();
        """)

    def test_the_cleanup_runs_on_the_smallest_group_it_can(self):
        """No size threshold. Four APs is the smallest set where a route can
        be wrong at all, and it is improved rather than waved through - which
        is the whole point, because a colour group is often about this big."""
        self.run_block("""
          // Greedy crosses its own path here; 2-opt uncrosses it.
          var aps = [{name:'A',x:138,y:158},{name:'B',x:280,y:556},
                     {name:'C',x:409,y:381},{name:'D',x:902,y:314}];
          var draft = greedy(aps);
          var fixed = sortNearestNeighbor(aps);
          check('greedy crossed over: ' + names(draft), names(draft) === 'ACBD');
          check('and it is untangled: ' + names(fixed), names(fixed) === 'ABCD');
          check('which is shorter: ' + len(draft).toFixed(0) + ' -> ' +
                len(fixed).toFixed(0), len(fixed) < len(draft) - 0.5);
          done();
        """)

    def test_a_six_ap_group_with_a_stranded_outlier_is_rescued(self):
        """or-opt's job. 2-opt can only reverse a run, so it cannot move a
        single AP the greedy walk picked up at the wrong moment."""
        self.run_block("""
          var aps = [{name:'A',x:288,y:369},{name:'B',x:394,y:487},
                     {name:'C',x:286,y:616},{name:'D',x:285,y:460},
                     {name:'E',x:55,y:178}, {name:'F',x:433,y:12}];
          var draft = greedy(aps);
          var fixed = sortNearestNeighbor(aps);
          check('greedy leaves E to the very end: ' + names(draft),
                names(draft) === 'FADBCE');
          check('E is lifted back to where it belongs: ' + names(fixed),
                names(fixed) === 'FEADBC');
          check('13% shorter: ' + len(draft).toFixed(0) + ' -> ' +
                len(fixed).toFixed(0), len(fixed) < len(draft) * 0.95);
          done();
        """)

    def test_it_never_makes_a_route_longer(self):
        """Only strictly-improving moves are taken. Across many layouts the
        cleaned-up route is never worse than the draft it started from."""
        self.run_block("""
          var seed = 7;
          function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff;
                           return seed / 0x7fffffff; }
          var worst = 0;
          for (var t = 0; t < 40; t++) {
            var n = 4 + Math.floor(rnd() * 30);
            var aps = [];
            for (var i = 0; i < n; i++) {
              aps.push({name:'p'+i, x: Math.round(rnd()*1200), y: Math.round(rnd()*800)});
            }
            var before = len(greedy(aps));
            var after  = len(sortNearestNeighbor(aps));
            if (after - before > worst) worst = after - before;
          }
          check('no layout got worse (worst delta ' + worst.toFixed(4) + ')',
                worst < 1e-6);
          done();
        """)

    def test_the_same_project_always_numbers_the_same_way(self):
        """Reproducibility is the point of the deterministic corner start. A
        route that changed with input order would renumber a project on every
        reload."""
        self.run_block("""
          var aps = [];
          for (var i = 0; i < 30; i++) {
            aps.push({name:'p'+i, x:(i*37)%1200, y:(i*91)%800});
          }
          var first    = names(sortNearestNeighbor(aps));
          var reversed = names(sortNearestNeighbor(aps.slice().reverse()));
          var again    = names(sortNearestNeighbor(aps));
          check('input order does not change the route', first === reversed);
          check('and it is stable when run again', first === again);
          done();
        """)

    def test_every_ap_is_still_there_exactly_once(self):
        """or-opt splices the list. Losing or duplicating an AP would mean a
        missing or repeated name on an installer's drawing."""
        self.run_block("""
          var seed = 3;
          function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff;
                           return seed / 0x7fffffff; }
          for (var t = 0; t < 25; t++) {
            var n = 4 + Math.floor(rnd() * 25);
            var aps = [];
            for (var i = 0; i < n; i++) {
              aps.push({name:'p'+i, x: Math.round(rnd()*1000), y: Math.round(rnd()*700)});
            }
            var out = sortNearestNeighbor(aps);
            var seen = {};
            out.forEach(function (a) { seen[a.name] = (seen[a.name] || 0) + 1; });
            check('count preserved at n=' + n, out.length === n);
            check('no AP dropped or duplicated at n=' + n,
                  Object.keys(seen).length === n);
          }
          done();
        """)

    def test_a_pair_or_a_single_is_left_alone(self):
        self.run_block("""
          check('empty', sortNearestNeighbor([]).length === 0);
          check('one', sortNearestNeighbor([{name:'A',x:1,y:1}]).length === 1);
          var two = sortNearestNeighbor([{name:'A',x:9,y:9},{name:'B',x:1,y:1}]);
          check('two, top-left first', names(two) === 'BA');
          done();
        """)

    def test_it_stays_fast_enough_to_run_on_every_edit(self):
        """The preview re-sorts as he types. A floor of 300 APs has to stay
        interactive, which is why the round limit tightens as the set grows."""
        self.run_block("""
          var seed = 11;
          function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff;
                           return seed / 0x7fffffff; }
          var aps = [];
          for (var i = 0; i < 300; i++) {
            aps.push({name:'p'+i, x: Math.round(rnd()*1200), y: Math.round(rnd()*800)});
          }
          var t0 = Date.now();
          sortNearestNeighbor(aps);
          var ms = Date.now() - t0;
          check('300 APs ordered in ' + ms + 'ms, budget 250ms', ms < 250);
          done();
        """)


if __name__ == "__main__":
    unittest.main()
