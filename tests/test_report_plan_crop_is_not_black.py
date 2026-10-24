"""A transparent floor plan must not print as a black rectangle.

A CAD floor plan is an SVG whose page is not painted, so most of its pixels
are transparent. The Report crops a plan onto a canvas and re-encodes it as a
JPEG, which has no alpha: pixels nobody painted come out black. Every
section of an AP Placement Map printed as black with the plan lines lost in
it. PlanTrim and Prep had already been fixed for the same symptom by painting
white underneath; the Report's own crops had not.

These run the real `cropAntennaSegment` and `autocropOverlay` against a canvas
that keeps real pixels and encodes the way a JPEG does (transparent -> black),
so the assertion is on what would be printed, not on the source containing a
fill. The plan is mostly transparent with one dark box on it.
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

PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');

// Slice a function out by counting braces, so an insertion between two
// functions cannot be swallowed and a nested close cannot end it early.
function slice(head) {
  const a = src.indexOf(head);
  if (a < 0) throw new Error(head + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}

// A canvas that holds RGBA pixels, transparent until something is painted.
class Canvas {
  constructor() { this.width = 300; this.height = 150; this.px = null; }
  alloc() {
    if (!this.px || this.px.length !== this.width * this.height * 4)
      this.px = new Uint8ClampedArray(this.width * this.height * 4);
  }
  getContext() {
    const c = this; c.alloc();
    return {
      fillStyle: '#000',
      fillRect(x, y, w, h) {
        if (String(this.fillStyle).toLowerCase() !== '#fff' && this.fillStyle !== '#ffffff') {
          throw new Error('probe only knows white fills, saw ' + this.fillStyle);
        }
        for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) {
          const o = (j * c.width + i) * 4; c.px[o] = c.px[o+1] = c.px[o+2] = c.px[o+3] = 255;
        }
      },
      drawImage(img, a, b, d, e, f, g, h, k) {
        let sx = 0, sy = 0, sw = img.naturalWidth, sh = img.naturalHeight, dx, dy, dw, dh;
        if (arguments.length === 5) { dx = a; dy = b; dw = d; dh = e; }
        else { sx = a; sy = b; sw = d; dh = k; sh = e; dx = f; dy = g; dw = h; }
        for (let j = 0; j < dh; j++) for (let i = 0; i < dw; i++) {
          const X = Math.floor(sx + (i + 0.5) * sw / dw), Y = Math.floor(sy + (j + 0.5) * sh / dh);
          if (!img.opaqueAt(X, Y)) continue;          // transparent source: nothing painted
          const o = ((dy + j) * c.width + dx + i) * 4;
          c.px[o] = c.px[o+1] = c.px[o+2] = 20; c.px[o+3] = 255;
        }
      },
      getImageData(x, y, w, h) { return { data: c.px }; },
    };
  }
  toBlob(cb) {
    // What a JPEG encoder does with an alpha channel: drop it, so anything
    // transparent is whatever the colour channels hold - black.
    const out = new Uint8ClampedArray(this.px.length);
    for (let o = 0; o < this.px.length; o += 4) {
      const a = this.px[o + 3];
      out[o] = a ? this.px[o] : 0; out[o+1] = a ? this.px[o+1] : 0;
      out[o+2] = a ? this.px[o+2] : 0; out[o+3] = 255;
    }
    cb({ px: out, width: this.width, height: this.height });
  }
}
const blobs = [];
globalThis.document = { createElement: (t) => { if (t !== 'canvas') throw new Error(t); return new Canvas(); } };
globalThis.URL = { createObjectURL: (b) => { blobs.push(b); return 'blob:probe' + blobs.length; } };

// A 1000x500 plan, transparent but for one dark box at x 400-600, y 200-300.
function makeImg() {
  const L = {};
  return {
    complete: true, naturalWidth: 1000, naturalHeight: 500,
    opaqueAt: (x, y) => x >= 400 && x < 600 && y >= 200 && y < 300,
    addEventListener(t, f) { (L[t] = L[t] || []).push(f); },
    set src(v) { this._src = v; setTimeout(() => (L.load || []).forEach(f => f()), 0); },
    get src() { return this._src; },
  };
}
const blackFraction = (b) => {
  let n = 0; for (let o = 0; o < b.px.length; o += 4) if (!b.px[o] && !b.px[o+1] && !b.px[o+2]) n++;
  return n / (b.px.length / 4);
};
const fails = [];
const check = (what, cond) => { if (!cond) fails.push(what); };

eval(slice('function whiteCanvas(w, h) {'));
eval(slice('function cropAntennaSegment(overlayEl) {'));
eval(slice('function autocropOverlay(overlayEl) {'));
globalThis.sizeAntennaSegmentForPrint = () => {};

(async () => {
  // 1. The section crop: a 600x300 window of the plan holding the box.
  {
    const img = makeImg();
    const attrs = { 'data-orig-w': '1000', 'data-orig-h': '500', 'data-seg-x0': '200',
                    'data-seg-y0': '100', 'data-seg-x1': '800', 'data-seg-y1': '400' };
    const el = { getAttribute: (k) => attrs[k], setAttribute: (k, v) => { attrs[k] = v; },
                 querySelector: (s) => (s === 'img' ? img : null) };
    await cropAntennaSegment(el);
    check('the section crop produced an image', blobs.length === 1);
    const b = blobs[0];
    check('the section crop is mostly white, not black (black fraction '
          + (b && blackFraction(b).toFixed(3)) + ')', b && blackFraction(b) < 0.2);
    check('the corner of the section crop is white', b && b.px[0] === 255 && b.px[1] === 255);
  }

  // 2. The autocrop: it measures the plan on a white page, so transparent
  // margin is margin, and it crops to the box instead of finding "content"
  // everywhere and leaving the plan whole.
  {
    blobs.length = 0;
    const img = makeImg();
    const vbAttr = { viewBox: '0 0 1000 500' };
    const svg = { getAttribute: (k) => vbAttr[k] || '', setAttribute: (k, v) => { vbAttr[k] = v; },
                  querySelectorAll: () => [], style: {} };
    const css = {};
    const el = { querySelector: (s) => (s === 'img' ? img : s === 'svg' ? svg : null),
                 style: { setProperty: (k, v) => { css[k] = v; } } };
    await autocropOverlay(el);
    check('the autocrop cropped the plan to its content', blobs.length === 1);
    const w = css['--w'];
    check('the autocrop narrowed the view to the box (width ' + w + ')', w && w < 900);
    const b = blobs[0];
    check('no black beyond the box in the autocrop (black fraction '
          + (b && blackFraction(b).toFixed(3)) + ')', b && blackFraction(b) < 0.5);
  }
  if (fails.length) { console.error(fails.join('\n')); process.exit(1); }
  process.exit(0);
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ATransparentPlanDoesNotPrintBlack(unittest.TestCase):
    def test_the_report_crops_paint_white_under_a_transparent_plan(self):
        r = subprocess.run(["node", "-e", PROBE, str(REPORT_JS)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())


if __name__ == "__main__":
    unittest.main()
