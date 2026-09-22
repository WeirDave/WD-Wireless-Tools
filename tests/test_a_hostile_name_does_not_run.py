"""Hostile values, through the real renderers, in all three browsers.

v2.146.1 fixed twenty-five attribute escapes after driving a crafted `.esx`
through AP Labeler and watching a handler fire. Its guard then pinned that
one shape - `attr="` immediately followed by the text escaper - and five more
survived it, because they were the same bug written differently:

* **`rename.js`** built the profile Apply and Delete handlers with
  ``JSON.stringify(name).replace(/"/g, '&quot;')``. That escapes the quote
  and the backslash and **not the ampersand**, so a name containing the six
  characters ``&quot;`` came through intact, the browser decoded the entity
  to a real quote when it read the attribute, and the JavaScript string
  closed early.
* **`cloud.js`** had the same expression three times, on the share chips,
  the recent-recipient list and the suggestion list. Those values come from
  `share_recipients.json`.
* **`rename.js`** again, in the token bar: a token key is a **CSV column
  header**, it went into a JavaScript string, and it was escaped with the
  *text* escaper, which leaves the apostrophe.
* **`walls.js`** interpolated `f.wallTypeId` - read straight out of the
  `.esx` - into two handlers with no escaper at all.

Every one of them is tested the way this repository requires: render with
the real function, pull the handler back **out of the rendered HTML**, click
it, and look at what happened. A substring assertion could not tell any of
these from the fix.

The escapers themselves are the shipped ones, sliced out of `wd-shared.js`,
so the test cannot pass against an escaper that stopped working.

`HOSTILE` is deliberately not a whole exploit: it sets a flag. What is being
asserted is that control reaches code the value was not supposed to become,
which the flag shows and a payload would only dress up.
"""
from __future__ import annotations

from tests import browsers as _browsers

import contextlib
import re
import socket
import sys
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JS = ROOT / "web" / "assets" / "js"
PORT_HINT = 8791

try:
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    HAVE_SELENIUM = True
except ImportError:  # pragma: no cover
    HAVE_SELENIUM = False

BROWSERS = [
    ("firefox", _browsers.find("firefox")),
    ("chrome", _browsers.find("chrome")),
    ("edge", _browsers.find("edge")),
]

#: Closes a `"`-delimited JavaScript string *via an HTML entity*, which is the
#: half every one of these missed. It also carries a bare apostrophe, for the
#: `'`-delimited case, and a tag for good measure.
HOSTILE = """x&quot;);window.__pwned=true;//' <img src=x onerror="window.__pwned=true">"""

#: A name with every character an escaper has to survive without mangling.
#: A guard that breaks these is worse than the bug - he has projects with
#: apostrophes and ampersands in their names.
ORDINARY = """O'Brien & Sons - "North" <Wing> \\ 50%"""


def _free_port(start):
    for port in range(start, start + 40):
        with contextlib.closing(socket.socket()) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port near %d" % start)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _driver(kind, binary):
    try:
        if kind == "firefox":
            opts = webdriver.FirefoxOptions()
            opts.binary_location = binary
            opts.add_argument("-headless")
            return webdriver.Firefox(options=opts)
        if kind == "chrome":
            opts = webdriver.ChromeOptions()
            opts.binary_location = binary
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            return webdriver.Chrome(options=opts)
        opts = webdriver.EdgeOptions()
        opts.binary_location = binary
        opts.add_argument("--headless=new")
        return webdriver.Edge(options=opts)
    except (WebDriverException, OSError):
        return None


def _slice_function(source: str, opening: str) -> str:
    """One function out of a shipped file, by counting braces.

    Slicing to "wherever the next function starts" swallows anything added
    between them, and ending at a two-space `}` finds the first *inner* one.
    Both went wrong here on 2026-09-20; counting braces is what survives an
    edit above or below. The `if not found` is not optional - without it a
    renamed function slices from -1 and the probe tests something else.
    """
    start = source.find(opening)
    if start < 0:
        raise AssertionError("slice marker moved: " + opening)
    end, depth, seen = start, 0, False
    while end < len(source) and not (seen and depth == 0):
        if source[end] == "{":
            depth += 1
            seen = True
        elif source[end] == "}":
            depth -= 1
        end += 1
    return source[start:end]


def _code_lines(text: str):
    """(number, line) for lines that are not inside a comment.

    Every note in these files is a `/* */` block several paragraphs long,
    and the notes about *these fixes* quote the handlers being fixed. A
    line search that does not skip them finds the explanation first.
    """
    in_block = False
    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if in_block:
            if "*/" in stripped:
                in_block = False
                rest = stripped.split("*/", 1)[1].strip()
                if rest:
                    yield number, line
            continue
        if stripped.startswith("//"):
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block = True
            continue
        yield number, line


def _first_code_line(text: str, matches, what: str) -> str:
    for _number, line in _code_lines(text):
        if matches(line):
            return line
    raise AssertionError(what + " moved - this probe is testing nothing")


def _escapers() -> str:
    """The three shipped escapers, so nothing here is a re-implementation."""
    shared = (JS / "wd-shared.js").read_text(encoding="utf-8")
    parts = ["window.WD = window.WD || {};"]
    for marker in ("WD.esc = function", "WD.escAttr = function",
                   "WD.escJsStr = function"):
        start = shared.find(marker)
        if start < 0:
            raise AssertionError("escaper moved: " + marker)
        end, depth, seen = start, 0, False
        while end < len(shared) and not (seen and depth == 0):
            if shared[end] == "{":
                depth += 1
                seen = True
            elif shared[end] == "}":
                depth -= 1
            end += 1
        parts.append(shared[start:end] + ";")
    return "\n".join(parts)


def _dispatcher() -> str:
    """The real `WD.actions`, lifted rather than re-implemented.

    Backlog item 10 moved these renderers off inline `onclick` and onto
    delegated `data-action` attributes, so clicking a rendered button now goes
    through the dispatcher. A probe that stubbed it would be asserting about a
    dispatcher this repository does not ship - and the argument handling is
    exactly the part a hostile value has to survive.
    """
    shared = (JS / "wd-shared.js").read_text(encoding="utf-8")
    marker = "WD.actions = (function () {"
    start = shared.find(marker)
    if start < 0:
        raise AssertionError("WD.actions moved - this probe cannot dispatch")
    end, depth, seen = start, 0, False
    while end < len(shared) and not (seen and depth == 0):
        if shared[end] == "{":
            depth += 1
            seen = True
        elif shared[end] == "}":
            depth -= 1
        end += 1
    end = shared.find(";", end) + 1       # past the IIFE's `)();`
    # `WD` is a local inside `wd-shared.js`'s own IIFE, so the slice refers to
    # a name this page does not have. Aliasing it is the whole difference
    # between lifting the real dispatcher and rewriting it.
    return ("var WD = window.WD;\n" + shared[start:end]
            + "\nWD.actions.mount();")


#: The four renderers, lifted from the shipped files rather than retyped.
def _renderers() -> str:
    rename = (JS / "rename.js").read_text(encoding="utf-8")
    walls = (JS / "walls.js").read_text(encoding="utf-8")

    # rename.js builds the profile list inside an async function that also
    # touches the DOM and the network, so the one expression is lifted by
    # locating it rather than by running the whole function.
    #
    # **Comment lines are skipped, and that is not tidiness.** The notes
    # explaining these fixes quote the old handler, so the first match for
    # `applyRenameProfile(` is a sentence in a `/* */` block. Taking it
    # produced a renderer whose body was English prose - which threw, was
    # caught by the driver's own try/except, and reported a page where
    # nothing executed. A probe that finds the wrong line passes.
    # `data-fn` rather than `onclick` since backlog item 10 moved these onto
    # delegated attributes. One source line per button, deliberately: this
    # probe lifts a line and evaluates it, so a button split across lines
    # arrives as a fragment that either throws or - worse - concatenates
    # wrongly and renders something nobody ships.
    profile_lines = [line for _n, line in _code_lines(rename)
                     if 'data-fn="applyRenameProfile"' in line
                     or 'data-fn="deleteRenameProfile"' in line]
    if len(profile_lines) != 2:
        raise AssertionError(
            "the rename profile buttons moved (found %d) - this probe is "
            "testing nothing" % len(profile_lines))
    # Delete is the one that matters and it is the second button on the row,
    # so both are rendered rather than only the first.
    profile_expr = " + ".join(line.strip().rstrip("+").strip()
                              for line in profile_lines)

    token_line = _first_code_line(
        rename, lambda l: 'data-fn="_renameInsertFormatToken"' in l,
        "the rename token button")
    token_expr = token_line.strip().rstrip(";")

    # The two wall-audit buttons are template literals spread over two
    # lines each, with a leading `+ ` from the surrounding concatenation.
    # Stripping that and joining with ` + ` reconstitutes the expression
    # without retyping any of it.
    walls_source = list(_code_lines(walls))
    walls_lines = []
    for position, (_number, line) in enumerate(walls_source):
        if "data-fn=" not in line:
            continue
        if ("applyAuditHeight" in line or "dismissAuditFinding" in line):
            walls_lines.append(line)
            # The `title=` half sits on the next line.
            following = walls_source[position + 1][1].strip()
            if following.startswith("+ `"):
                walls_lines.append(walls_source[position + 1][1])
    if len(walls_lines) != 4:
        raise AssertionError(
            "the wall audit buttons moved (found %d fragments) - this probe "
            "is testing nothing" % len(walls_lines))

    # The first fragment opens with `(ft ? `, and the second closes with
    # `: '')`; both belong to the surrounding conditional rather than to
    # the button, so they come off.
    walls_expr = " + ".join((
        walls_lines[0].strip().split("? ", 1)[1],
        walls_lines[1].strip().lstrip("+").strip().rstrip(": '')"),
        walls_lines[2].strip().lstrip("+").strip(),
        walls_lines[3].strip().lstrip("+").strip().rstrip(";"),
    ))

    return "\n".join([
        "window.__renderProfile = function (name) { return " + profile_expr + "; };",
        # The token bar maps over a list, so the probe hands it one entry.
        "window.__renderToken = function (t) {"
        "  var tokens = [t];"
        "  var inputId = 'rnFolderFormat';"
        "  return " + token_expr + ";"
        "};",
        "window.__renderWallAudit = function (wallTypeId) {"
        "  var f = { wallTypeId: wallTypeId, wallType: 'Brick', segments: 2,"
        "            why: 'the name says so' };"
        "  var ft = 4;"
        "  return " + walls_expr + ";"
        "};",
    ])


PAGE = """<!doctype html>
<meta charset="utf-8"><title>hostile value probe</title>
<div id="host"></div>
<script>
%(escapers)s
%(dispatcher)s

/* Local aliases, exactly as cloud.js defines them at the top of the file. */
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function j(s) { return WD.escJsStr(s); }
function esc(s) { return WD.esc(s); }
function escAttr(s) { return WD.escAttr(s); }

window.__pwned = false;
window.__calls = [];
function record(which) {
  return function () { window.__calls.push([which].concat([].slice.call(arguments))); };
}
window.applyRenameProfile = record('applyRenameProfile');
window.deleteRenameProfile = record('deleteRenameProfile');
window._renameInsertFormatToken = record('_renameInsertFormatToken');
window._sharePick = record('_sharePick');
window._shareChipRemove = record('_shareChipRemove');
window._shareForget = record('_shareForget');
window.applyAuditHeight = record('applyAuditHeight');
window.dismissAuditFinding = record('dismissAuditFinding');
window.updateRenamePreview = function () {};

%(renderers)s

/* Render some markup, click every button in it, and report. */
window.__drive = function (html) {
  window.__pwned = false;
  window.__calls = [];
  var host = document.getElementById('host');
  host.innerHTML = html;
  var handlers = [];
  /* Both shapes. `[onclick]` is what these renderers used to produce and
     what the unconverted ones still do; `[data-action]` is what a converted
     one produces, and clicking it goes through the real dispatcher mounted
     above rather than through anything this file invented. */
  var buttons = host.querySelectorAll(
    '[onclick], [data-action], [data-action-input]');
  for (var i = 0; i < buttons.length; i++) {
    handlers.push(buttons[i].getAttribute('onclick')
                  || buttons[i].getAttribute('data-fn'));
    try { buttons[i].click(); } catch (err) { /* a broken handler is data */ }
    if (buttons[i].hasAttribute('data-action-input')) {
      try { buttons[i].dispatchEvent(new Event('input', { bubbles: true })); }
      catch (err) { /* not dispatchable is fine */ }
    }
  }
  /* Anything that fires on hover or on load rather than on click. */
  var hovers = host.querySelectorAll('[onmouseover],[onmouseenter],[onerror],[onload]');
  for (var k = 0; k < hovers.length; k++) {
    ['mouseover', 'mouseenter'].forEach(function (type) {
      try { hovers[k].dispatchEvent(new MouseEvent(type, { bubbles: true })); }
      catch (err) { /* not dispatchable is fine */ }
    });
  }
  return { pwned: window.__pwned, calls: window.__calls,
           handlers: handlers, extra: hovers.length,
           buttons: buttons.length, html: host.innerHTML };
};

</script>
"""


class HostileValues(unittest.TestCase):
    """One browser per subclass; the page is static and reused."""

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

        # **Every cleanup is registered at the moment the thing is made**,
        # rather than left to `tearDownClass`. `tearDownClass` does not run
        # when `setUpClass` raises, and the two lines below it can - a
        # browser that will not start raises SkipTest - so the directory and
        # the port would have leaked on exactly the machine where a browser
        # is missing. That is how 12.73 GB accumulated, one skipped run at a
        # time.
        import shutil
        import tempfile
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-hostile-"))
        cls.addClassCleanup(shutil.rmtree, str(cls.tmp), ignore_errors=True)

        (cls.tmp / "index.html").write_text(
            PAGE % {"escapers": _escapers(), "dispatcher": _dispatcher(),
                "renderers": _renderers()},
            encoding="utf-8")

        cls.port = _free_port(PORT_HINT)
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", cls.port), partial(QuietHandler, directory=str(cls.tmp)))
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

        cls.driver = _driver(cls.kind, cls.binary)
        if cls.driver is None:
            raise unittest.SkipTest("%s would not start" % cls.kind)
        cls.addClassCleanup(_browsers.shut_down, cls.driver)
        cls.driver.get("http://127.0.0.1:%d/index.html" % cls.port)

    def drive(self, js_expression, value):
        html = self.driver.execute_script(
            "return (%s)(arguments[0]);" % js_expression, value)
        return self.driver.execute_script("return window.__drive(arguments[0]);", html)

    # ── rename profiles ─────────────────────────────────────────

    def test_a_hostile_profile_name_does_not_run(self):
        r = self.drive("window.__renderProfile", HOSTILE)
        self.assertFalse(
            r["pwned"],
            "a profile name executed as code.\n  handler: %s" % (r["handlers"],))

    def test_a_hostile_profile_name_arrives_whole(self):
        """Not executed *and* not silently truncated.

        The old code passed `x` and ran the rest; a fix that passed `x` and
        merely swallowed the rest would look the same to the test above.
        """
        r = self.drive("window.__renderProfile", HOSTILE)
        received = [c[1] for c in r["calls"] if c[0] == "applyRenameProfile"]
        self.assertEqual([HOSTILE], received)

    def test_an_ordinary_profile_name_round_trips(self):
        r = self.drive("window.__renderProfile", ORDINARY)
        received = [c[1] for c in r["calls"] if c[0] == "applyRenameProfile"]
        self.assertEqual([ORDINARY], received,
                         "a name with an apostrophe, an ampersand and a "
                         "backslash was mangled by the escaping")

    def test_both_profile_buttons_are_reached(self):
        """Delete is the one that matters and it is the second on the row."""
        r = self.drive("window.__renderProfile", ORDINARY)
        self.assertEqual(
            {"applyRenameProfile", "deleteRenameProfile"},
            {c[0] for c in r["calls"]})

    # ── rename token bar (a CSV column header) ──────────────────

    def test_a_hostile_csv_column_header_does_not_run(self):
        r = self.drive("window.__renderToken", {"key": HOSTILE})
        self.assertFalse(r["pwned"],
                         "a CSV column header executed as code.\n  handler: %s"
                         % (r["handlers"],))

    def test_a_column_header_with_an_apostrophe_arrives_whole(self):
        """The exact character the text escaper leaves alone."""
        name = "Site's Code"
        r = self.drive("window.__renderToken", {"key": name})
        received = [c[2] for c in r["calls"]
                    if c[0] == "_renameInsertFormatToken"]
        self.assertEqual([name], received)

    # ── wall audit buttons (a value out of the .esx) ────────────

    def test_a_hostile_wall_type_id_does_not_run(self):
        r = self.drive("window.__renderWallAudit", HOSTILE)
        self.assertFalse(
            r["pwned"],
            "a wall type id out of the .esx executed as code.\n  handler: %s"
            % (r["handlers"],))
        received = [c[1] for c in r["calls"]]
        self.assertTrue(received, "neither audit button fired")
        self.assertTrue(all(v == HOSTILE for v in received),
                        "the wall type id was mangled: %r" % (received,))

    def test_an_ordinary_wall_type_id_round_trips(self):
        r = self.drive("window.__renderWallAudit", ORDINARY)
        self.assertEqual([ORDINARY, ORDINARY], [c[1] for c in r["calls"]])

    # ── cloud share suggestions ─────────────────────────────────

    def test_a_hostile_recipient_does_not_run_in_the_suggestion_list(self):
        r = self.driver.execute_script(
            "var matches = [{ email: arguments[0] }];"
            "var html = matches.map(function (r, i) {"
            "  return '<button type=\"button\" class=\"share-suggest-item\" data-i=\"' + i + '\"'"
            "    + ' onmousedown=\"event.preventDefault()\"'"
            "    + ' onclick=\"_sharePick(\\'' + WD.escJsStr(r.email) + '\\')\">'"
            "    + WD.esc(r.email) + '</button>';"
            "}).join('');"
            "return window.__drive(html);", HOSTILE)
        self.assertFalse(r["pwned"],
                         "a saved recipient executed as code.\n  handler: %s"
                         % (r["handlers"],))
        self.assertEqual([HOSTILE], [c[1] for c in r["calls"]])

    # ── the escapers themselves ─────────────────────────────────

    def test_the_text_escaper_still_leaves_the_quote(self):
        """The premise the whole distinction rests on.

        If `WD.esc` ever starts escaping the quote, every conclusion in this
        file changes and it should fail loudly rather than quietly stay
        true.
        """
        out = self.driver.execute_script('return WD.esc(\'a"b\');')
        self.assertEqual('a"b', out)

    def test_the_attribute_escaper_escapes_it(self):
        out = self.driver.execute_script('return WD.escAttr(\'a"b\');')
        self.assertEqual("a&quot;b", out)

    def test_the_js_escaper_escapes_the_ampersand(self):
        """The half `JSON.stringify(...).replace(/"/g, '&quot;')` missed.

        Without it, `&quot;` in the value survives to the browser's entity
        decoder and becomes a real quote.
        """
        out = self.driver.execute_script("return WD.escJsStr('a&quot;b');")
        self.assertEqual("a&amp;quot;b", out)


def _case(kind, binary):
    return type("HostileValuesIn" + kind.title(), (HostileValues,),
                {"kind": kind, "binary": binary})


HostileValuesInFirefox = _case(*BROWSERS[0])
HostileValuesInChrome = _case(*BROWSERS[1])
HostileValuesInEdge = _case(*BROWSERS[2])

del HostileValues  # the base class is not a test case

if __name__ == "__main__":
    unittest.main()
