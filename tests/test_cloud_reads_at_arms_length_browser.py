"""Cloud Manager's list and its Sync plan read at arm's length.

Measured at 1366x1080 before the change: project names 12.5px, dates 11px,
type tags 10.5px, the sentence under a row and every row button 12px. And the
Sync everything plan - three tables in the shared confirm dialog - was about
430px wide, so "What differs", file names and "Download" broke mid-word.

Driven against the real page with a stub server; every project, site and
address is invented.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

from tests import browsers as _browsers
from tests.test_cloud_shows_who_owns_a_project import HAVE_SELENIUM, _driver

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
ME = "me@example.invalid"
T = 1790000000
BROWSERS = _browsers.triple()


def _pair(i, name, stale=None, dc=0, dl=0):
    return {"cloud": {"id": "c%d" % i, "name": name, "owner": ME, "mtime": T + dc,
                      "sharedWith": [], "meta": "2 hr ago", "hasSite": True,
                      "siteId": "s1", "siteName": "Invented Campus"},
            "local": {"path": "D:\\P\\%s.esx" % name, "name": name,
                      "folder": "Invented Campus", "mtime": T + dl, "meta": "3 hr ago"},
            "matchType": "id", "score": 1.0, "namesDiffer": False,
            "staleness": stale, "divergence": None, "comparison": None,
            "differenceKind": None}


def _data():
    matched = [_pair(1, "Invented Campus - Level 1"),
               _pair(2, "Invented Campus - Level 2", "cloud_newer", dc=7200),
               _pair(3, "Invented Campus - Level 3", "local_newer", dl=7200)]
    cloud_only = [{"id": "c9", "name": "Invented Campus - Parking", "owner": ME,
                   "mtime": T, "sharedWith": [], "meta": "1 day ago",
                   "hasSite": True, "siteId": "s1", "siteName": "Invented Campus"}]
    return {"currentUser": ME, "matched": matched, "mismatches": [],
            "cloudOnly": cloud_only, "localOnly": [], "heldBack": [],
            "summary": {"matched": 3, "cloudOnly": 1, "localOnly": 0, "heldBack": 0},
            "orphans": {"cloudOnly": [], "localOnly": []}}


def _dups():
    """Two copies of one invented file, a month old and a day old."""
    now = int(time.time())
    items = [{"side": "local", "path": "D:\\P\\Invented Copy.esx",
              "name": "Invented Copy", "size": 1000, "mtime": now - 30 * 86400,
              "owner": "", "matched": False},
             {"side": "local", "path": "D:\\Old\\Invented Copy.esx",
              "name": "Invented Copy", "size": 900, "mtime": now - 86400,
              "owner": "", "matched": False}]
    return {"clusters": [{"key": "inventedcopy", "displayName": "Invented Copy",
                          "items": items, "sides": {"cloud": 0, "local": 2},
                          "shape": "local-only", "newestId": items[1]["path"],
                          "largestId": items[0]["path"]}],
            "summary": {"total": 1, "mixed": 0, "localOnly": 1, "cloudOnly": 0}}


class _Stub(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._send({"ok": True, "settings": {}})
        return super().do_GET()

    def do_POST(self):
        with contextlib.suppress(Exception):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.endswith("/get_data"):
            return self._send(_data())
        if self.path.endswith("/get_duplicates"):
            return self._send(_dups())
        return self._send({"ok": True})


SIZES = """
const px = s => parseFloat(getComputedStyle(s).fontSize);
const all = sel => Array.prototype.map.call(document.querySelectorAll(sel), px);
return {names: all('.ledger-row .lr-cell .cell-name'),
        meta: all('.ledger-row .cell-meta'),
        detail: all('.row-detail .rd-text')};
"""

PLAN = """
const m = document.querySelector('#confirmActionModal .modal');
const r = m.getBoundingClientRect();
const ok = document.getElementById('confirmActionOkBtn').getBoundingClientRect();
const heads = Array.prototype.map.call(
  m.querySelectorAll('table.sync-plan th'), function (th) {
    const lh = parseFloat(getComputedStyle(th).lineHeight) ||
               parseFloat(getComputedStyle(th).fontSize) * 1.3;
    return {text: th.textContent.trim(), lines: Math.round(
      (th.getBoundingClientRect().height - 12) / lh)};
  });
return {width: r.width, okBottom: ok.bottom, okTop: ok.top, vh: innerHeight,
        heads: heads};
"""


class CloudManagerReads(unittest.TestCase):

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

    def open(self, w, h):
        drv = self.driver
        drv.set_window_size(w, h)
        url = "http://127.0.0.1:%d/cloud.html" % self.port
        drv.get(url)
        drv.execute_script("""
          const a = document.getElementById('appScreen');
          if (a) a.style.display = 'flex';
          const l = document.getElementById('loginScreen');
          if (l) l.style.display = 'none';
          try { switchTab('projects'); } catch (e) {}
          try { setOwnerFilterUI('all'); } catch (e) {}
          try { refreshData(false); } catch (e) {}
        """)
        for _ in range(80):
            if drv.execute_script(
                    "return document.querySelectorAll('.ledger-row').length"):
                break
            time.sleep(0.25)
        time.sleep(0.5)

    def test_the_list_is_at_the_readable_sizes(self):
        self.open(1366, 1000)
        s = self.driver.execute_script(SIZES)
        self.assertTrue(s["names"] and s["meta"] and s["detail"], s)
        self.assertGreaterEqual(min(s["names"]), 15, s)
        self.assertGreaterEqual(min(s["meta"]), 13, s)
        self.assertGreaterEqual(min(s["detail"]), 14, s)

    def test_the_sync_plan_is_wide_enough_and_its_button_is_on_screen(self):
        for w, h in ((1366, 768), (1366, 1000)):
            with self.subTest(size=(w, h)):
                self.open(w, h)
                self.driver.execute_script("syncEverything();")
                time.sleep(1.0)
                p = self.driver.execute_script(PLAN)
                self.assertGreaterEqual(p["width"], 900, p)
                self.assertTrue(p["heads"], p)
                for head in p["heads"]:
                    self.assertLessEqual(head["lines"], 1, p)
                self.assertGreaterEqual(p["okTop"], 0, p)
                self.assertLessEqual(p["okBottom"], p["vh"], p)
                self.driver.execute_script("_resolveConfirmAction(false);")


    def test_a_duplicate_shows_its_date_once(self):
        """Past a week the relative date is itself a short date, and the row
        printed "September 21, 2026 at 2:13 PM · Sep 21, 2026"."""
        self.open(1366, 1000)
        self.driver.execute_script("switchTab('duplicates');")
        dates = []
        for _ in range(40):
            dates = self.driver.execute_script(
                "return Array.prototype.map.call(document.querySelectorAll("
                "'.dup-item-date'), function (d) { return d.textContent; });")
            if dates:
                break
            time.sleep(0.25)
        self.assertEqual(len(dates), 2, dates)
        old, recent = dates
        self.assertNotIn("·", old)
        self.assertIn("ago", recent)


def _case(kind, binary):
    return type("%sCloudManagerReadsTests" % kind.capitalize(),
                (CloudManagerReads,), {"kind": kind, "binary": binary})


FirefoxCloudManagerReadsTests = _case(*BROWSERS[0])
ChromeCloudManagerReadsTests = _case(*BROWSERS[1])
EdgeCloudManagerReadsTests = _case(*BROWSERS[2])
SafariCloudManagerReadsTests = _case(*BROWSERS[3]) if len(BROWSERS) > 3 else None

del CloudManagerReads


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
