"""Who owns a project is visible on the row, and unknown is its own answer.

"in Cloud Manager the owner button or toggle really should be colour
differentiated - make the user side one colour and other users another
colour for the different owners."

Two things are checked here and they are the same thing from either end.

**The colour**, because a list of ninety has to answer "whose is this"
without a hover. His projects carry the cloud accent down the edge of the
cell, other people's carry the orange the owner address is already written
in, and the Owner toggle above the list carries the same two colours on the
side each of its buttons selects.

**The third state**, which is the one that had no mark at all. A project
Ekahau lists no owner for rendered identically to one he owns - so when a
gate read those as somebody else's and withheld thirty of his own projects,
there was nothing on screen that could have shown it. It now carries a grey
edge and says `owner unknown`, and it stays in the selection: an empty owner
field is ordinary for a project nobody has shared.

The selection split is driven rather than described. The rows are ticked the
way he ticks them and the three buckets the share dialog is built from are
read back out of the page afterwards, because "unknown is still offered" is
a claim about what the code does and not about what the stylesheet says.

Every project, site and address here is invented; the server is a stub.
"""
from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PORT_HINT = 8951
ME = "me@example.invalid"
MATE = "colleague@example.invalid"

from tests import browsers as _browsers                        # noqa: E402

try:  # pragma: no cover - availability varies by machine
    from selenium import webdriver
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

BROWSERS = _browsers.triple()


def _free_port(start):
    for port in range(start, start + 40):
        with contextlib.closing(socket.socket()) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port near %d" % start)


#: One of each answer, and the third is the point.
ROWS = [
    ("c-mine", "Riverside Survey", ME),
    ("c-theirs", "Northgate Survey", MATE),
    ("c-unknown", "Lakeside Survey", ""),
]


def _data():
    matched = []
    for cid, name, owner in ROWS:
        matched.append({
            "cloud": {"id": cid, "name": name, "owner": owner,
                      "mtime": 2000, "sharedWith": [], "meta": "2 hr ago",
                      "hasSite": True},
            "local": {"path": "D:\\E\\%s.esx" % name, "name": name,
                      "folder": "Surveys", "mtime": 2000, "meta": "2 hr ago"},
            "matchType": "id", "staleness": None, "namesDiffer": False,
            "comparison": None,
        })
    return {"currentUser": ME, "summary": {"matched": len(matched)},
            "matched": matched, "cloudOnly": [], "localOnly": [],
            "orphans": {"cloudOnly": [], "localOnly": []}}


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
        #: Without this the page decides there is no server and skips every
        #: server-backed path, including the owner filter's own default.
        if self.path.startswith("/api/"):
            return self._send({"ok": True, "settings": {}})
        return super().do_GET()

    def do_POST(self):
        with contextlib.suppress(Exception):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.endswith("/get_data"):
            return self._send(_data())
        if self.path.endswith("/get_duplicates"):
            return self._send({"clusters": []})
        return self._send({"ok": True})


#: The edge colour actually painted on each cloud cell, by project id.
EDGE = """
const out = {};
document.querySelectorAll('.ledger-row').forEach(function (row) {
  const cell = row.querySelector('.lr-cell.cloud');
  if (!cell) return;
  const chk = row.querySelector('.rowchk');
  const name = (cell.textContent || '').trim().split('\\n')[0];
  const cls = Array.prototype.filter.call(
    cell.classList, c => c.indexOf('own-') === 0).join(',');
  const dot = cell.querySelector('.own-dot');
  const ds = dot ? getComputedStyle(dot) : null;
  out[name.slice(0, 18)] = {
    cls: cls,
    dot: dot ? dot.getAttribute('data-own') : null,
    //: The edge is the sync status and is deliberately not ours; it is read
    //: so the test can say if ownership ever takes it over again.
    edge: getComputedStyle(cell).boxShadow,
    paint: ds ? [ds.backgroundColor, ds.boxShadow].join(' | ') : null,
    size: ds ? [ds.width, ds.height].join('x') : null,
    tag: !!cell.querySelector('.owner-tag.unknown'),
    key: chk ? chk.getAttribute('data-k') : null,
  };
});
return JSON.stringify(out);
"""

#: The three buckets the share dialog is built from, after ticking.
SPLIT = """
//: A real click, not `checked = true` plus a synthetic event. The page
//: wires these through its own handler, and setting the property ticks the
//: box while the selection behind it stays empty - which reads here as the
//: feature being broken and is the harness lying.
document.querySelectorAll('.rowchk').forEach(function (c) {
  if (!c.checked) c.click();
});
return JSON.stringify({
  owned: (window._bulkShareOwnedIds || []),
  unproven: (window._bulkShareUnproven || []).map(x => x.id),
  notMine: (window._bulkShareNotMine || []).map(x => x.id),
});
"""


def _driver(kind, binary):
    try:
        if kind == "firefox":
            o = webdriver.FirefoxOptions()
            o.binary_location = binary
            o.add_argument("-headless")
            o.add_argument("--width=1600")
            o.add_argument("--height=1000")
            return webdriver.Firefox(options=o)
        if kind == "chrome":
            o = webdriver.ChromeOptions()
            o.binary_location = binary
            o.add_argument("--headless=new")
            o.add_argument("--no-sandbox")
            o.add_argument("--window-size=1600,1000")
            return webdriver.Chrome(options=o)
        o = webdriver.EdgeOptions()
        o.binary_location = binary
        o.add_argument("--headless=new")
        o.add_argument("--no-sandbox")
        o.add_argument("--window-size=1600,1000")
        return webdriver.Edge(options=o)
    except Exception:  # pragma: no cover - a missing driver is a skip
        return None


class OwnershipIsOnTheRow(unittest.TestCase):

    kind = None
    binary = None
    server = None
    driver = None

    @classmethod
    def setUpClass(cls):
        if cls.kind is None:
            raise unittest.SkipTest("base class")
        if not HAVE_SELENIUM:
            raise unittest.SkipTest("selenium is not installed")
        if not Path(cls.binary).exists():
            raise unittest.SkipTest("%s is not installed here" % cls.kind)
        cls.port = _free_port(PORT_HINT)
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", cls.port), partial(_Stub, directory=str(WEB)))
        cls.addClassCleanup(cls._stop_server)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.driver = _driver(cls.kind, cls.binary)
        if cls.driver is None:
            raise unittest.SkipTest("%s would not start" % cls.kind)
        cls.addClassCleanup(cls._stop_driver)
        cls.driver.set_page_load_timeout(60)

    @classmethod
    def _stop_driver(cls):
        _browsers.shut_down(cls.driver)
        cls.driver = None

    @classmethod
    def _stop_server(cls):
        _browsers.stop_server(cls.server)
        cls.server = None

    def setUp(self):
        url = "http://127.0.0.1:%d/cloud.html" % self.port
        self.driver.get(url)
        with contextlib.suppress(Exception):
            self.driver.execute_script("localStorage.clear()")
        self.driver.get(url)
        self.driver.execute_script("""
          const a = document.getElementById('appScreen');
          if (a) a.style.display = 'flex';
          const l = document.getElementById('loginScreen');
          if (l) l.style.display = 'none';
          const u = document.getElementById('userEmail');
          if (u) u.textContent = arguments[0];
          try { switchTab('projects'); } catch (e) {}
          //: Otherwise the saved default hides the colleague's row and the
          //: test is only ever looking at two of the three answers.
          try { setOwnerFilterUI('all'); } catch (e) {}
          try { refreshData(false); } catch (e) {}
        """, ME)
        for _ in range(60):
            if self.driver.execute_script(
                    "return document.querySelectorAll('.ledger-row').length"):
                break
            time.sleep(0.25)

    def _edges(self):
        got = json.loads(self.driver.execute_script(EDGE))
        self.assertEqual(3, len(got), "expected three rows, got %r" % got)
        return {k.split()[0]: v for k, v in got.items()}

    # -- the colour ------------------------------------------------------

    def test_each_row_says_which_of_the_three_it_is(self):
        by_name = self._edges()
        self.assertEqual("mine", by_name["Riverside"]["dot"])
        self.assertEqual("theirs", by_name["Northgate"]["dot"])
        self.assertEqual("unknown", by_name["Lakeside"]["dot"])

    def test_the_three_are_painted_in_three_different_colours(self):
        """Read off the rendered dot, not off the stylesheet: a rule that
        does not reach the element is the failure being guarded against, and
        the first version of this feature was invisible for exactly that
        reason - it was overridden by the rule below."""
        paints = {n: v["paint"] for n, v in self._edges().items()}
        for name, paint in paints.items():
            with self.subTest(row=name):
                self.assertTrue(paint, "%s has no ownership dot" % name)
        self.assertEqual(
            3, len(set(paints.values())),
            "two of the three ownership states are drawn the same: %s"
            % paints)
        sizes = {v["size"] for v in self._edges().values()}
        self.assertNotIn("0px x 0px", sizes, "the dot has no size")

    def test_ownership_has_not_taken_over_the_sync_colour(self):
        """The cell's left edge is the sync status - green synced, amber
        mismatch, red cloud-only - and it is the first thing the list is read
        by. Ownership must have a channel of its own.

        The first version of this feature put ownership on that edge, which
        looked right in the stylesheet and was measurable only by rendering
        it. What is asserted is the property rather than the absence of one
        rule: three rows of the same sync status and three different owners
        have to carry the same edge, and the edge has to be the status
        colour the page uses elsewhere rather than any ownership colour.
        """
        edges = {n: v["edge"] for n, v in self._edges().items()}
        self.assertEqual(
            1, len(set(edges.values())),
            "these rows share a sync status and differ only in who owns "
            "them, so their edges must match - ownership has taken over the "
            "signal the list is read by: %s" % edges)
        painted = next(iter(edges.values()))
        own_colours = self.driver.execute_script("""
          const out = [];
          document.querySelectorAll('.own-dot').forEach(function (d) {
            out.push(getComputedStyle(d).backgroundColor);
          });
          return out;
        """)
        for colour in own_colours:
            rgb = colour.replace("rgba", "rgb").rsplit(",", 1)[0]
            if colour.startswith("rgba(0, 0, 0, 0"):
                continue          # the unknown dot is a ring, not a fill
            with self.subTest(colour=colour):
                self.assertNotIn(
                    rgb.split("(")[1], painted,
                    "the cell edge is being painted in an ownership colour: "
                    "%s is in %s" % (colour, painted))

    def test_the_project_with_no_owner_says_so_in_words(self):
        """Colour is never the only signal."""
        by_name = self._edges()
        self.assertTrue(by_name["Lakeside"]["tag"],
                        "a project with no owner carries no mark at all, "
                        "which is the state that hid the reported bug")
        self.assertFalse(by_name["Riverside"]["tag"])
        self.assertFalse(by_name["Northgate"]["tag"])

    def test_the_owner_toggle_carries_the_colours_of_the_rows_it_selects(self):
        colours = self.driver.execute_script("""
          /* **Transitions off before measuring.** `.owner-btn` transitions
             its background over 0.12s, so a computed style read straight
             after the class goes on returns the value it is coming *from* -
             transparent. A literal colour read back at 3.7% alpha is what
             that looks like, and it reads exactly like a rule that is not
             applying. */
          const kill = document.createElement('style');
          kill.textContent = '.owner-btn { transition: none !important; }';
          document.head.appendChild(kill);
          const out = {};
          ['mine', 'others', 'all'].forEach(function (which) {
            const b = document.querySelector('.owner-btn[data-owner="' + which + '"]');
            if (!b) return;
            document.querySelectorAll('.owner-btn').forEach(
              x => x.classList.remove('active'));
            b.classList.add('active');
            out[which] = getComputedStyle(b).backgroundColor;
          });
          kill.remove();
          return JSON.stringify(out);
        """)
        got = json.loads(colours)
        self.assertEqual(3, len(got), "the Owner toggle is not on the page")
        self.assertNotEqual(
            got["mine"], got["others"],
            "Mine and Others are the same colour, which is the thing asked "
            "for: %s" % got)

    # -- the selection ---------------------------------------------------

    def test_a_project_with_no_owner_stays_in_the_selection(self):
        """The reported bug, from the page's side. Ticking everything must
        leave only the one that provably belongs to somebody else out."""
        split = json.loads(self.driver.execute_script(SPLIT))
        self.assertIn("c-mine", split["owned"])
        self.assertIn(
            "c-unknown", split["owned"],
            "a project Ekahau lists no owner for was dropped from the "
            "selection - this is what turned thirty-three into three")
        self.assertEqual(["c-theirs"], split["notMine"])

    def test_it_is_offered_and_named_rather_than_offered_in_silence(self):
        split = json.loads(self.driver.execute_script(SPLIT))
        self.assertEqual(
            ["c-unknown"], split["unproven"],
            "the unconfirmed one is in the selection but not marked as "
            "unconfirmed, so the dialog cannot tell him which is which")


def _case(kind, binary):
    return type("%sOwnershipOnTheRowTests" % kind.capitalize(),
                (OwnershipIsOnTheRow,), {"kind": kind, "binary": binary})


FirefoxOwnershipOnTheRowTests = _case(*BROWSERS[0])
ChromeOwnershipOnTheRowTests = _case(*BROWSERS[1])
EdgeOwnershipOnTheRowTests = _case(*BROWSERS[2])

del OwnershipIsOnTheRow


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
