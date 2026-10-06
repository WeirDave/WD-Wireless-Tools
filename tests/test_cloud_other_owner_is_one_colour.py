"""Somebody else's project is drawn in one colour, controls included.

"if the cloud manager is going to use a different color to indicate other
people's projects then it needs to use that color throughout including the
buttons and such."

It was two colours. The name and the owner address on a colleague's row were
violet; the ownership dot in front of the name and the Others button above the
list were orange - and orange already meant "not shared" on the summary row.
The buttons on the row were the app's blue whoever owned it.

So everything that says "somebody else's" now reads one pair of tokens,
`--owner-other` for marks and text and `--owner-other-fill` for a filled
control, and the row and the band under it remap the accent to that pair so
the recommended button, the tick box and the row menu follow without a rule
per control.

Everything is read off the rendered page in both themes - the computed colour
of each element, compared with the colour the token resolves to - because a
rule that does not reach its element is exactly what left the dot orange while
the name beside it was violet.

Every project and address here is invented; the server is a stub.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
import unittest
from functools import partial
from pathlib import Path

from tests import browsers as _browsers                        # noqa: E402
from tests.test_cloud_shows_who_owns_a_project import (       # noqa: E402
    HAVE_SELENIUM, ME, MATE, WEB, _Stub, _driver)

BROWSERS = _browsers.triple()


def _row(cid, name, owner):
    #: Cloud newer and never compared, so each row has a band underneath
    #: with a recommended (filled) button in it - the control in question.
    return {
        "cloud": {"id": cid, "name": name, "owner": owner, "mtime": 3000,
                  "sharedWith": [ME] if owner != ME else [],
                  "meta": "1 hr ago", "hasSite": True},
        "local": {"path": "D:\\E\\%s.esx" % name, "name": name,
                  "folder": "Surveys", "mtime": 1000, "meta": "3 hr ago"},
        "matchType": "id", "staleness": "cloud_newer", "namesDiffer": False,
        "comparison": None,
    }


def _data():
    matched = [_row("c-mine", "Riverside Survey", ME),
               _row("c-theirs", "Harbor Survey", MATE)]
    return {"currentUser": ME, "summary": {"matched": len(matched)},
            "matched": matched, "cloudOnly": [], "localOnly": [],
            "orphans": {"cloudOnly": [], "localOnly": []}}


class _TwoOwners(_Stub):
    def do_POST(self):
        with contextlib.suppress(Exception):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.endswith("/get_data"):
            return self._send(_data())
        if self.path.endswith("/get_duplicates"):
            return self._send({"clusters": []})
        return self._send({"ok": True})


#: Every colour that says whose a project is, plus what the tokens resolve
#: to, in the theme currently on the page.
PROBE = """
const kill = document.createElement('style');
kill.textContent = '*, *::before { transition: none !important; }';
document.head.appendChild(kill);
//: A token resolved through a real element, so `#7c3aed` and
//: `rgb(124, 58, 237)` compare equal.
function rgb(v) {
  const s = document.createElement('span');
  s.style.color = v;
  document.body.appendChild(s);
  const c = getComputedStyle(s).color;
  s.remove();
  return c;
}
const root = getComputedStyle(document.documentElement);
const tok = n => rgb(root.getPropertyValue(n).trim());
function row(name) {
  return Array.prototype.find.call(
    document.querySelectorAll('.ledger-row'), function (r) {
      const n = r.querySelector('.lr-cell.cloud .cell-name');
      return n && n.textContent.indexOf(name) === 0;
    });
}
function marks(name) {
  const r = row(name);
  if (!r) return null;
  const cell = r.querySelector('.lr-cell.cloud');
  const det = r.nextElementSibling;
  const band = det && det.classList.contains('row-detail') ? det : null;
  const btn = band && band.querySelector('.rd-btn.primary');
  const tag = cell.querySelector('.owner-tag.other');
  const chk = cell.querySelector('.rowchk');
  return {
    dot: getComputedStyle(cell.querySelector('.own-dot')).backgroundColor,
    name: getComputedStyle(cell.querySelector('.cell-name')).color,
    tag: tag ? getComputedStyle(tag).color : null,
    chk: chk ? getComputedStyle(chk).accentColor : null,
    band: !!band,
    btn: btn ? getComputedStyle(btn).backgroundColor : null,
  };
}
function toggle(which, active) {
  const b = document.querySelector('.owner-btn[data-owner="' + which + '"]');
  const was = b.classList.contains('active');
  b.classList.toggle('active', active);
  const out = active ? getComputedStyle(b).backgroundColor
                     : getComputedStyle(b, '::before').backgroundColor;
  b.classList.toggle('active', was);
  return out;
}
const out = {
  other: tok('--owner-other'), fill: tok('--owner-other-fill'),
  mine: tok('--owner-mine'), orange: tok('--orange'),
  theirs: marks('Harbor'), yours: marks('Riverside'),
  othersDot: toggle('others', false), othersOn: toggle('others', true),
  mineDot: toggle('mine', false),
};
kill.remove();
return JSON.stringify(out);
"""


class OtherOwnerIsOneColour(unittest.TestCase):

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
        cls.server = _browsers.ExclusiveServer(
            ("127.0.0.1", 0), partial(_TwoOwners, directory=str(WEB)))
        cls.port = cls.server.server_address[1]
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
          try { switchTab('projects'); } catch (e) {}
          try { setOwnerFilterUI('all'); } catch (e) {}
          try { refreshData(false); } catch (e) {}
        """)
        #: Both rows and both bands, bounded and loud - a later refresh can
        #: replace the first render, so wait for the finished shape.
        deadline = time.monotonic() + 45
        got = None
        while time.monotonic() < deadline:
            got = json.loads(self.driver.execute_script(PROBE))
            if (got["theirs"] and got["yours"] and got["theirs"]["btn"]
                    and got["yours"]["btn"]):
                break
            time.sleep(0.25)
        self.assertTrue(got and got["theirs"] and got["yours"],
                        "the two rows never finished drawing: %r" % got)

    def _read(self, theme):
        self.driver.execute_script(
            "document.documentElement.setAttribute('data-theme', arguments[0]);",
            theme)
        return json.loads(self.driver.execute_script(PROBE))

    def test_everything_on_a_colleagues_row_is_the_other_owner_colour(self):
        for theme in ("dark", "light"):
            with self.subTest(theme=theme):
                g = self._read(theme)
                t = g["theirs"]
                for what in ("dot", "name", "tag", "chk"):
                    self.assertEqual(
                        g["other"], t[what],
                        "the %s on somebody else's row is not the other-owner "
                        "colour in the %s theme: %r" % (what, theme, g))
                self.assertTrue(t["band"], "the row lost its action band")
                self.assertEqual(
                    g["fill"], t["btn"],
                    "the recommended button on somebody else's row is not in "
                    "their colour in the %s theme: %r" % (theme, g))

    def test_the_owner_toggle_uses_the_same_colours_as_the_rows(self):
        for theme in ("dark", "light"):
            with self.subTest(theme=theme):
                g = self._read(theme)
                self.assertEqual(g["other"], g["othersDot"], g)
                self.assertEqual(g["fill"], g["othersOn"], g)
                self.assertEqual(g["mine"], g["mineDot"], g)

    def test_your_own_row_keeps_your_colour(self):
        """The remap is scoped to the colleague's row. A rule that leaked
        would paint every button violet and the colour would mean nothing."""
        for theme in ("dark", "light"):
            with self.subTest(theme=theme):
                g = self._read(theme)
                y = g["yours"]
                self.assertEqual(g["mine"], y["dot"], g)
                self.assertNotEqual(g["other"], g["mine"], g)
                self.assertTrue(y["btn"], "your row lost its button: %r" % g)
                self.assertNotEqual(
                    g["fill"], y["btn"],
                    "your own row's button is in the other-owner colour: %r" % g)

    def test_orange_is_not_an_ownership_colour(self):
        """Orange is the Not-shared card's colour; it was also the dot and
        the Others button, which is the split this file exists for."""
        for theme in ("dark", "light"):
            with self.subTest(theme=theme):
                g = self._read(theme)
                for v in (g["theirs"]["dot"], g["othersDot"], g["othersOn"],
                          g["theirs"]["tag"]):
                    self.assertNotEqual(g["orange"], v, g)

    def test_the_others_filter_notice_is_the_other_owner_colour(self):
        self.driver.execute_script("setOwnerFilterUI('others');")
        deadline = time.monotonic() + 20
        colour = None
        while time.monotonic() < deadline:
            colour = self.driver.execute_script("""
              const n = document.getElementById('ownerFilterNotice');
              if (!n || n.hidden || !n.classList.contains('is-others')) return null;
              const s = document.createElement('span');
              s.style.color = getComputedStyle(document.documentElement)
                .getPropertyValue('--owner-other').trim();
              document.body.appendChild(s);
              const want = getComputedStyle(s).color;
              s.remove();
              return [getComputedStyle(n).borderLeftColor, want];
            """)
            if colour:
                break
            time.sleep(0.25)
        self.assertTrue(colour, "the Others notice never appeared")
        self.assertEqual(colour[1], colour[0])


def _case(kind, binary):
    return type("%sOtherOwnerIsOneColourTests" % kind.capitalize(),
                (OtherOwnerIsOneColour,), {"kind": kind, "binary": binary})


FirefoxOtherOwnerIsOneColourTests = _case(*BROWSERS[0])
ChromeOtherOwnerIsOneColourTests = _case(*BROWSERS[1])
EdgeOtherOwnerIsOneColourTests = _case(*BROWSERS[2])
SafariOtherOwnerIsOneColourTests = _case(*BROWSERS[3]) if len(BROWSERS) > 3 else None

del OtherOwnerIsOneColour


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
