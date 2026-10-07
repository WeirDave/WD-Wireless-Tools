"""A row of buttons does not start on the pixel the sentence ends.

"we need spacing in this modal, the text is jammed up against the buttons."

Measured before the fix, in Chrome, Edge and Firefox, on the real `Check all 3?`
dialog with the real stylesheet: the gap between the last paragraph's bottom and
the first button's top was **0px**. Not tight - none.

`.modal-actions` set `display`, `gap` and `justify-content` and no top margin at
all. It went unnoticed because the modals anyone had looked at hard - the share
dialog, peek, compare - had each grown their own spacing, and three utility
classes existed for the same purpose. What was left on the bare rule was the
plain confirm dialogs, which is most of them: nineteen across the suite were
sitting at zero.

The four that space their buttons with padding inside a scrolling flex body are
deliberately left alone; this is for the ones that had nothing.

**Measured, not grepped.** The stylesheet is applied to the real page in a real
browser and the resulting gap is read off the box. Asserting that the rule
contains `margin-top: 16px` would pass with the selector renamed, with a later
rule overriding it, or with the element removed from the modal entirely.
"""
from __future__ import annotations

from tests import browsers as _browsers

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "web" / "assets" / "wd-tools.css"
CLOUD_HTML = ROOT / "web" / "cloud.html"

BROWSERS = _browsers.triple()

#: The body `checkAllUncompared()` really passes, for three pairs.
BODY = (
    "<p>Compares each pair and reports what actually differs.</p>"
    "<p class=\"sub\"><b>Nothing is changed</b> on either side \u2014 not the "
    "cloud, not your local files.</p>"
    "<p class=\"sub\">Each comparison downloads that project's cloud copy to "
    "compare it, so 3 downloads will run. They are queued and each reports its "
    "own result.</p>"
)

PROBE = r"""
const out = {};
const body = document.getElementById('confirmActionBody');
const acts = document.querySelector('#confirmActionModal .modal-actions');
const last = body.lastElementChild;
const lb = last.getBoundingClientRect();
const btn = acts.querySelector('.btn').getBoundingClientRect();
out.gap = Math.round(btn.top - lb.bottom);
out.buttonHeight = Math.round(btn.height);
/* Every modal-actions on the page, so a modal that manages its own spacing is
   distinguishable from one that has none. */
out.all = [...document.querySelectorAll('.modal-actions')].map(a => {
  const cs = getComputedStyle(a);
  const overlay = a.closest('.modal-overlay');
  return { id: (overlay && overlay.id) || '',
           total: parseFloat(cs.marginTop) + parseFloat(cs.paddingTop) };
});
return out;
"""


def _page() -> str:
    css = CSS.read_text(encoding="utf-8")
    html = CLOUD_HTML.read_text(encoding="utf-8")
    i = html.index('<div class="modal-overlay" id="confirmActionModal">')
    j = html.index("</div>\n\n", i) + len("</div>")
    modal = html[i:j]
    modal = modal.replace('id="confirmActionBody"></div>',
                          'id="confirmActionBody">' + BODY + "</div>")
    modal = modal.replace('class="modal-overlay"', 'class="modal-overlay show"')
    #: Every other modal on the page comes along, so the sweep below is real.
    rest = html[html.index('<div class="modal-overlay"'):]
    return (f"<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<style>{css}</style>"
            f"<style>.modal-overlay.show {{ display:flex !important; "
            f"opacity:1 !important; visibility:visible !important; }}</style>"
            f"</head><body class=\"wd\">{modal}{rest}</body></html>")


class _TheButtonsHaveRoom(unittest.TestCase):
    """Driven in a browser, because the question is a distance in pixels. The
    tests are written once; a class per browser is made from them below."""

    kind = ""
    binary = ""

    @classmethod
    def setUpClass(cls):
        if not Path(cls.binary).exists():
            raise unittest.SkipTest(f"{cls.kind} is not installed")
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-modal-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        (cls.tmp / "modal.html").write_text(_page(), encoding="utf-8")
        server = _browsers.serve_directory(cls.tmp)
        cls.addClassCleanup(_browsers.stop_server, server)
        d = _browsers.make_driver(cls.kind, cls.binary)
        if d is None:
            raise unittest.SkipTest(f"{cls.kind} would not start")
        try:
            d.set_page_load_timeout(60)
            d.set_window_size(1280, 900)
            d.get("http://127.0.0.1:%d/modal.html" % server.server_address[1])
            cls.out = d.execute_script(PROBE)
        finally:
            # Not a bare quit() in a try/except: a driver that has stopped
            # answering raises there, the exception is swallowed, and the
            # browser it started outlives the run.
            _browsers.shut_down(d)

    def test_the_text_is_not_jammed_against_the_buttons(self):
        """The reported defect, as a measurement. It was 0."""
        self.assertGreaterEqual(
            self.out["gap"], 12,
            f"only {self.out['gap']}px between the last line and the buttons")

    def test_and_not_so_far_that_they_read_as_a_separate_thing(self):
        """A dialog is one object. The buttons belong to the sentence above
        them, so the gap stays under the height of a button."""
        self.assertLess(self.out["gap"], self.out["buttonHeight"] * 1.5)

    def test_no_modal_in_the_suite_is_left_at_zero(self):
        """Nineteen were. The bare rule is what most modals get, so the bare
        rule is where the spacing has to live."""
        flat = [m for m in self.out["all"] if m["total"] < 12]
        self.assertEqual([], flat,
                         f"modals with no room above their buttons: {flat}")


def _case(kind, binary):
    return type(f"TheButtonsHaveRoomIn{kind.title()}", (_TheButtonsHaveRoom,),
                {"kind": kind, "binary": binary})


TheButtonsHaveRoomInFirefox = _case(*BROWSERS[0])
TheButtonsHaveRoomInChrome = _case(*BROWSERS[1])
TheButtonsHaveRoomInEdge = _case(*BROWSERS[2])
TheButtonsHaveRoomInSafari = _case(*BROWSERS[3]) if len(BROWSERS) > 3 else None
# The base class is not a test of any browser; keep the loader from running it.
del _TheButtonsHaveRoom
