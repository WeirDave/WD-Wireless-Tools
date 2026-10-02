"""A merge that would overwrite shows the choice before it does.

`#mergeConflictWrap` - "When a file already exists: Keep newer / Keep both /
Skip" - ships with the `hidden` attribute, and `[hidden]{display:none
!important}` in wd-tools.css beats an inline style. The dialog only ever set
`style.display`, so the choice was never on screen and the preset rule
quietly decided which copy of a conflicting file survived.

`tests/test_cloud_merge_many_page.py` stubs the radio, so it could not see
this. Here the real page is loaded in a real browser and what is measured is
whether the radios have a box. Every folder and file name is invented.
"""
from __future__ import annotations

import threading
import unittest
from functools import partial
from pathlib import Path

from tests import browsers as _browsers
from tests.test_cloud_reads_at_arms_length_browser import _Stub
from tests.test_cloud_shows_who_owns_a_project import HAVE_SELENIUM, _driver

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
BROWSERS = _browsers.triple()


def _preview(n_conflicts):
    files = [{"rel": "Invented Wing.esx", "conflict": bool(n_conflicts),
              "newer": "src", "srcMtime": 2, "dstMtime": 1,
              "srcSizeH": "1 MB", "dstSizeH": "1 MB"}]
    return {"sources": [{"srcPath": "D:/P/Invented Wing Old",
                         "srcName": "Invented Wing Old",
                         "nConflicts": n_conflicts, "files": files}],
            "refused": [], "nClean": 0 if n_conflicts else 1,
            "nConflicts": n_conflicts, "nCrossSource": 0}


SHOW = """
mergeState = {srcName: 'Invented Wing Old', dstName: 'Invented Wing',
              dstPath: 'D:/P/Invented Wing'};
showMergeModal(arguments[0]);
const radios = Array.prototype.map.call(
  document.querySelectorAll('#mergeModal input[name="mrule"]'),
  function (r) { const b = r.getBoundingClientRect();
                 return {value: r.value, w: b.width, h: b.height,
                         checked: r.checked}; });
const out = {radios: radios,
             wrapShown: getComputedStyle(
               document.getElementById('mergeConflictWrap')).display !== 'none'};
closeModal('mergeModal');
return out;
"""


class MergeConflictChoice(unittest.TestCase):

    kind = None
    binary = None

    @classmethod
    def setUpClass(cls):
        if cls.kind is None:
            raise unittest.SkipTest("base class")
        if not HAVE_SELENIUM:
            raise unittest.SkipTest("selenium is not installed")
        if not Path(cls.binary).exists():
            raise unittest.SkipTest("%s is not installed here" % cls.kind)
        cls.server = _browsers.ExclusiveServer(
            ("127.0.0.1", 0), partial(_Stub, directory=str(WEB)))
        cls.port = cls.server.server_address[1]
        cls.addClassCleanup(lambda: _browsers.stop_server(cls.server))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.driver = _driver(cls.kind, cls.binary)
        if cls.driver is None:
            raise unittest.SkipTest("%s would not start" % cls.kind)
        cls.addClassCleanup(lambda: _browsers.shut_down(cls.driver))
        cls.driver.set_page_load_timeout(60)
        cls.driver.set_script_timeout(20)
        cls.driver.get("http://127.0.0.1:%d/cloud.html" % cls.port)

    def test_a_conflict_shows_the_three_choices(self):
        out = self.driver.execute_script(SHOW, _preview(1))
        self.assertTrue(out["wrapShown"], out)
        self.assertEqual(["newer", "both", "skip"],
                         [r["value"] for r in out["radios"]], out)
        for r in out["radios"]:
            self.assertGreater(r["w"] * r["h"], 0,
                               "the %s choice has no box: %r" % (r["value"], out))
        self.assertEqual(1, sum(r["checked"] for r in out["radios"]), out)

    def test_no_conflict_hides_the_choice_again(self):
        """Shown once, then a clean merge: the choice must go away again,
        or it offers a decision about nothing."""
        self.driver.execute_script(SHOW, _preview(1))
        out = self.driver.execute_script(SHOW, _preview(0))
        self.assertFalse(out["wrapShown"], out)


def _case(kind, binary):
    return type("%sMergeConflictChoiceTests" % kind.capitalize(),
                (MergeConflictChoice,), {"kind": kind, "binary": binary})


FirefoxMergeConflictChoiceTests = _case(*BROWSERS[0])
ChromeMergeConflictChoiceTests = _case(*BROWSERS[1])
EdgeMergeConflictChoiceTests = _case(*BROWSERS[2])

del MergeConflictChoice


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
