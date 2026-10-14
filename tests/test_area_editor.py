"""WD.AreaEditor - drawing the requirement area, for Prep and for Capacity.

The Node half runs wd-areaeditor.js whole on a real WD.PlanView, drives it
with the mouse and keyboard events the page would receive, and asserts what
arrives at the page's own callbacks (the outline set, the outline committed,
the refusal sentence). The shapes it refuses are the shapes
tools.capacity_profiles.polygon_problem refuses, checked against each other
below, because the page and the server each hold the rules and a drift
between them is a drawing the page accepts and the server drops.

Where the page does not draw, nothing here claims it does: the same editor in
a real browser, on both pages, is tests/test_area_drawing_browser.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import capacity_profiles as cap  # noqa: E402
from tests.test_plan_view import HARNESS, PLANVIEW_JS  # noqa: E402

AREA_JS = ROOT / "web" / "assets" / "js" / "wd-areaeditor.js"
needs_node = unittest.skipUnless(shutil.which("node"), "Node.js is not installed")


def node(body):
    prelude = HARNESS + "eval(fs.readFileSync(process.argv[2], 'utf8'));\n"
    r = subprocess.run(["node", "-e", prelude + body, str(PLANVIEW_JS), str(AREA_JS)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


# The plan is 100 x 50 units drawn on a 200 x 100 image at scale 1, so a point
# on the screen is twice its plan coordinates: the scaling is proved by every
# assertion, as in the box editor's.
EDITOR = r"""
let outline = null, committed = [], refused = [], modes = [];
const ed = WD.AreaEditor.create({
  get: () => outline, set: p => { outline = p; }, commit: p => committed.push(p),
  size: () => ({ w: 100, h: 50 }), enabled: () => true,
  shown: () => null,
  onMode: m => modes.push(m), onReject: m => refused.push(m),
});
const pv = WD.PlanView.create({ canvas, overlay: ed.overlay,
  dragPans: (e, p, v) => !ed.claims(e, p, v),
  onDown: ed.onDown, onMove: ed.onMove, onUp: ed.onUp });
pv.setImage(img);
pv.view.scale = 1; pv.view.x = 0; pv.view.y = 0;
function drag(x0, y0, x1, y1) {
  fire('canvas', 'mousedown', { clientX: x0, clientY: y0 });
  fire('window', 'mousemove', { clientX: x1, clientY: y1 });
  fire('window', 'mouseup', { clientX: x1, clientY: y1 });
}
function click(x, y, detail) {
  fire('canvas', 'mousedown', { clientX: x, clientY: y });
  fire('window', 'mouseup', { clientX: x, clientY: y, detail: detail || 1 });
}
function key(k) { return ed.onKey({ key: k }); }
const out = () => console.log(JSON.stringify({ outline, committed, refused, modes }));
"""


@needs_node
class DrawingARectangle(unittest.TestCase):

    def test_a_drag_in_rectangle_mode_commits_four_corners_in_plan_units(self):
        out = node(EDITOR + "ed.start('rect'); drag(20, 10, 120, 70); out();")
        self.assertEqual(out["committed"], [[[10, 5], [60, 5], [60, 35], [10, 35]]])
        self.assertEqual(out["outline"], out["committed"][0])
        self.assertEqual(out["modes"], ["rect", "idle"], "the tool puts itself down")

    def test_dragging_up_and_left_gives_the_same_rectangle(self):
        out = node(EDITOR + "ed.start('rect'); drag(120, 70, 20, 10); out();")
        self.assertEqual(out["committed"], [[[10, 5], [60, 5], [60, 35], [10, 35]]])

    def test_a_stray_click_does_not_cost_the_tool(self):
        out = node(EDITOR + "ed.start('rect'); click(40, 40); out();")
        self.assertEqual(out["committed"], [])
        self.assertEqual(out["modes"], ["rect"], "still in rectangle mode")

    def test_a_drag_off_the_plan_is_held_inside_it(self):
        out = node(EDITOR + "ed.start('rect'); drag(20, 10, 390, 290); out();")
        self.assertEqual(out["committed"][0][2], [100, 50])

    def test_without_the_tool_a_drag_on_empty_plan_draws_nothing(self):
        out = node(EDITOR + "drag(20, 10, 120, 70); out();")
        self.assertEqual(out["committed"], [])
        self.assertIsNone(out["outline"])


@needs_node
class DrawingAShape(unittest.TestCase):

    def test_clicks_make_corners_and_enter_finishes(self):
        out = node(EDITOR + "ed.start('poly'); click(20, 20); click(180, 20); click(180, 80); "
                            "const kept = key('Enter'); out();")
        self.assertEqual(out["committed"], [[[10, 10], [90, 10], [90, 40]]])
        self.assertEqual(out["modes"], ["poly", "idle"])

    def test_clicking_the_first_corner_finishes(self):
        out = node(EDITOR + "ed.start('poly'); click(20, 20); click(180, 20); click(180, 80); "
                            "click(22, 21); out();")
        self.assertEqual(len(out["committed"][0]), 3, "the closing click adds no corner")

    def test_a_double_click_finishes_without_a_duplicate_corner(self):
        out = node(EDITOR + "ed.start('poly'); click(20, 20); click(180, 20); click(180, 80, 1); "
                            "click(180, 80, 2); out();")
        self.assertEqual(out["committed"], [[[10, 10], [90, 10], [90, 40]]])

    def test_enter_with_too_few_corners_says_so_and_keeps_drawing(self):
        out = node(EDITOR + "ed.start('poly'); click(20, 20); click(180, 20); key('Enter'); out();")
        self.assertEqual(out["refused"], ["An area needs at least three corners."])
        self.assertEqual(out["committed"], [])
        self.assertEqual(out["modes"], ["poly"])

    def test_backspace_takes_the_last_corner_back(self):
        out = node(EDITOR + "ed.start('poly'); click(20, 20); click(180, 20); click(180, 80); "
                            "click(20, 80); key('Backspace'); key('Enter'); out();")
        self.assertEqual(out["committed"], [[[10, 10], [90, 10], [90, 40]]])

    def test_escape_cancels_and_leaves_nothing(self):
        out = node(EDITOR + "ed.start('poly'); click(20, 20); click(180, 20); key('Escape'); out();")
        self.assertEqual(out["committed"], [])
        self.assertEqual(out["modes"], ["poly", "idle"])

    def test_a_shape_that_crosses_itself_is_refused_in_the_page_words(self):
        out = node(EDITOR + "ed.start('poly'); click(20, 20); click(180, 80); click(180, 20); "
                            "click(20, 80); key('Enter'); out();")
        self.assertEqual(out["refused"], ["The outline crosses itself."])
        self.assertEqual(out["committed"], [])
        self.assertEqual(out["modes"], ["poly"], "he can still back out the last corner")

    def test_keys_belong_to_the_tool_only_while_it_is_drawing(self):
        out = node(EDITOR + "console.log(JSON.stringify([key('Escape'), key('Enter'), key('Backspace')]));")
        self.assertEqual(out, [False, False, False])


@needs_node
class ChangingAnOutline(unittest.TestCase):
    START = "outline = [[10, 5], [60, 5], [60, 35], [10, 35]];"

    def test_dragging_a_corner_moves_that_corner_only(self):
        out = node(EDITOR + self.START + "drag(120, 70, 160, 90); out();")
        self.assertEqual(out["outline"], [[10, 5], [60, 5], [80, 45], [10, 35]])
        self.assertEqual(out["committed"], [out["outline"]])

    def test_a_corner_cannot_be_dragged_off_the_plan(self):
        out = node(EDITOR + self.START + "drag(120, 70, 380, 290); out();")
        self.assertEqual(out["outline"][2], [100, 50])

    def test_dragging_the_dot_on_an_edge_adds_a_corner(self):
        out = node(EDITOR + self.START + "drag(70, 10, 70, 2); out();")
        self.assertEqual(len(out["outline"]), 5)
        self.assertEqual(out["outline"][1], [35, 1])

    def test_pressing_a_corner_or_a_dot_without_moving_changes_nothing(self):
        out = node(EDITOR + self.START + "drag(120, 70, 121, 70); drag(70, 10, 70, 10); out();")
        self.assertEqual(out["outline"], [[10, 5], [60, 5], [60, 35], [10, 35]])
        self.assertEqual(out["committed"], [])

    def test_a_move_that_would_cross_the_outline_is_undone_and_explained(self):
        out = node(EDITOR + self.START + "drag(120, 70, 0, 70); out();")
        self.assertEqual(out["outline"], [[10, 5], [60, 5], [60, 35], [10, 35]])
        self.assertEqual(out["refused"], ["The outline crosses itself."])
        self.assertEqual(out["committed"], [])

    def test_the_view_pans_everywhere_except_on_a_corner(self):
        out = node(EDITOR + self.START + """
const claims = [[120, 70], [140, 40], [70, 10], [300, 250]].map(
  ([x, y]) => ed.claims({}, { x, y }, pv));
ed.start('rect');
console.log(JSON.stringify([claims, ed.claims({}, { x: 300, y: 250 }, pv)]));
""")
        self.assertEqual(out, [[True, False, True, False], True],
                         "a corner and an edge dot; not the middle; everything while drawing")

    def test_switched_off_it_takes_no_drag(self):
        out = node(EDITOR.replace("enabled: () => true", "enabled: () => false")
                   + "ed.start('rect'); drag(20, 10, 120, 70); out();")
        self.assertEqual(out["committed"], [])
        self.assertEqual(out["modes"], [])


@needs_node
class TheRulesAreTheServers(unittest.TestCase):
    SHAPES = {
        "two corners": [[0, 0], [50, 50]],
        "a sliver": [[0, 0], [100, 0], [100, 3]],
        "a straight line": [[0, 0], [50, 0], [100, 0]],
        "a bow tie": [[0, 0], [100, 100], [100, 0], [0, 100]],
        "a rectangle": [[0, 0], [100, 0], [100, 60], [0, 60]],
        "an L": [[300, 200], [900, 200], [900, 400], [600, 400], [600, 700], [300, 700]],
        "a star that crosses": [[0, 0], [100, 0], [20, 60], [50, -40], [80, 60]],
        "a dent": [[0, 0], [100, 0], [100, 100], [50, 20], [0, 100]],
    }

    def test_the_page_and_the_server_refuse_the_same_shapes_in_the_same_words(self):
        page = node("console.log(JSON.stringify(Object.entries("
                    + json.dumps(self.SHAPES) + ").map(([k, v]) => [k, WD.AreaEditor.problem(v)])));")
        server = [[k, cap.polygon_problem([tuple(p) for p in v])] for k, v in self.SHAPES.items()]
        self.assertEqual(page, server)
        # and it is not agreeing about nothing
        self.assertEqual(sum(1 for _k, why in page if why), 5)

    def test_an_outline_is_sent_rounded_and_only_if_it_is_one(self):
        out = node("""console.log(JSON.stringify(WD.AreaEditor.param({
  a: [[1.23456, 2], [3, 4.5], [6, 7]], b: [[1, 2]], c: null})));""")
        self.assertEqual(json.loads(out), {"a": [{"x": 1.23, "y": 2}, {"x": 3, "y": 4.5},
                                                  {"x": 6, "y": 7}]})
        self.assertEqual(node("console.log(JSON.stringify(WD.AreaEditor.param({})));"), "")


CONTROLS = r"""
const els = {};
function el(id) {
  return els[id] = els[id] || { id, disabled: false, textContent: '', attrs: {},
    setAttribute(k, v) { this.attrs[k] = v; },
    classList: { toggle(c, on) { (els[id].cls = els[id].cls || {})[c] = !!on; } } };
}
globalThis.document = { getElementById: id => /^wdArea/.test(id) ? el(id) : null };
let outline = null, cleared = 0, can = true, why = '';
const ed = WD.AreaEditor.create({
  get: () => outline, set: p => { outline = p; }, commit() {},
  size: () => ({ w: 100, h: 50 }), enabled: () => can,
  onMode: () => WD.AreaEditor.sync(),
});
WD.AreaEditor.bind({ editor: ed, floor: () => ({ id: 'f1', name: 'Level 2' }),
  drawn: () => outline, enabled: () => can, why: () => why,
  clear: () => { cleared++; outline = null; } });
// A control is run by its handler, found the way the dispatcher finds it.
function press(markupId) {
  const html = WD.AreaEditor.controlsHtml();
  const m = new RegExp('id="' + markupId + '"[^>]*', 's').exec(html)[0];
  const fn = /data-fn="([^"]+)"/.exec(m)[1];
  const arg = (/data-arg="([^"]*)"/.exec(m) || [])[1];
  const f = fn.split('.').reduce((o, k) => o[k], globalThis.window);
  if (typeof f !== 'function') throw new Error(fn + ' is not a function');
  f(arg);
}
const state = () => ({ rect: els.wdAreaRect.disabled, clear: els.wdAreaClear.disabled,
  on: els.wdAreaRect.attrs['aria-pressed'], hint: els.wdAreaHint.textContent, mode: ed.mode() });
"""


@needs_node
class TheButtons(unittest.TestCase):

    def test_each_button_runs_a_real_handler(self):
        out = node(CONTROLS + "press('wdAreaRect'); const a = state(); press('wdAreaPoly');"
                              "const b = state(); console.log(JSON.stringify([a, b]));")
        self.assertEqual(out[0]["mode"], "rect")
        self.assertEqual(out[0]["on"], "true")
        self.assertEqual(out[1]["mode"], "poly", "pressing the other one switches to it")

    def test_pressing_the_tool_that_is_on_puts_it_down(self):
        out = node(CONTROLS + "press('wdAreaRect'); press('wdAreaRect'); console.log(JSON.stringify(state()));")
        self.assertEqual(out["mode"], "idle")
        self.assertEqual(out["on"], "false")

    def test_back_to_automatic_is_off_until_something_is_drawn_and_then_clears_it(self):
        out = node(CONTROLS + """
WD.AreaEditor.sync();
const before = state().clear;
outline = [[0, 0], [50, 0], [50, 30]]; WD.AreaEditor.sync();
const during = state().clear;
press('wdAreaClear');
console.log(JSON.stringify([before, during, cleared, outline, state().clear]));
""")
        self.assertEqual(out, [True, False, 1, None, True])

    def test_the_sentence_under_them_follows_the_state(self):
        out = node(CONTROLS + """
const idle = state().hint;
press('wdAreaPoly'); const poly = state().hint;
press('wdAreaPoly'); outline = [[0, 0], [50, 0], [50, 30]]; WD.AreaEditor.sync();
const has = state().hint;
can = false; why = 'Open a project to draw on its plan.'; WD.AreaEditor.sync();
console.log(JSON.stringify([idle, poly, has, state()]));
""")
        idle, poly, has, off = out
        self.assertIn("Nothing drawn on Level 2", idle)
        self.assertIn("Click each corner", poly)
        self.assertIn("The area you drew on Level 2", has)
        self.assertEqual(off["hint"], "Open a project to draw on its plan.")
        self.assertTrue(off["rect"], "the drawing buttons are off with the reason beside them")

    def test_a_press_while_it_is_not_allowed_does_nothing(self):
        out = node(CONTROLS + "can = false; press('wdAreaRect'); console.log(JSON.stringify(ed.mode()));")
        self.assertEqual(out, "idle")


if __name__ == "__main__":
    unittest.main()
