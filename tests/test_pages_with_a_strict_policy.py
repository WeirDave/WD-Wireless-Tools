"""A page on the strict list has no inline script, and really gets the header.

Backlog item 10. A Content-Security-Policy without `'unsafe-inline'` is the
second line of defence behind this suite's 264 `innerHTML` assignments: nine of
the fourteen findings in the 2026-09-21 sweep were a value reaching markup
without the right escaper, and with a real policy an injected `<script>` does
not run even when an escaper is missed.

**What makes it a project rather than a fix** is that every control in the
suite was an inline `onclick`, which is exactly what such a policy forbids. So
the rollout is page by page - the header is per response - and `server.py`
carries `CSP_STRICT_PAGES`, the list of pages whose controls have all been
converted to the delegated dispatcher in `wd-shared.js`.

**The failure this guards against is invisible in development.** An inline
`onclick` added back to a converted page works perfectly in the browser of
whoever wrote it, because they are looking at a page that renders. It stops
working for the user, silently, the moment the header is applied - the control
is there, it is named, and clicking it does nothing. That is the defect class
this repository has shipped four times, and this is the only check that sees
it.

So, for every page on the list:

* no inline event attribute anywhere in its markup, **and none produced by the
  JavaScript it loads** - a handler written into `innerHTML` is blocked by the
  same policy as one in the file;
* no inline `<script>` block;
* every `data-fn` names something that exists;
* and the response really carries the header, which is asked of the running
  app rather than of the source, because `/manual` is rendered rather than
  served from disk and does not go through `_page`.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

EVENTS = ("click", "change", "input", "submit", "keyup", "keydown",
          "dblclick", "blur", "focus", "contextmenu", "wheel",
          "mouseover", "mouseout", "dragover", "dragleave", "drop",
          "load", "error")

INLINE_ATTR = re.compile(r'\son(' + "|".join(EVENTS) + r')\s*=\s*["\']', re.I)
INLINE_SCRIPT = re.compile(r'<script\b(?![^>]*\bsrc=)[^>]*>', re.I)
#: `onclick="` built by JavaScript - the same defect wearing a template
#: literal. Deliberately loose: any `on<event>=` next to a quote in a JS file.
JS_INLINE_ATTR = re.compile(r'\son(' + "|".join(EVENTS) + r')\s*=\s*[\\"\'`]', re.I)
SCRIPT_SRC = re.compile(r'<script[^>]*\bsrc="([^"]+)"', re.I)
DATA_FN = re.compile(r'data-fn="([^"]+)"')

#: Names the browser provides, which no script in this repository defines.
#: Deliberately tiny and explicit: the point of the check is that a control
#: names something real, and "it is probably a global" would let every typo
#: through. A name goes here only when the page is genuinely calling a
#: browser builtin.
BROWSER_BUILTINS = {"location.reload", "history.back", "window.print"}


def strict_pages():
    import server
    return set(server.CSP_STRICT_PAGES)


def page_text(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def scripts_for(name: str):
    """The local JS files a page loads, as paths."""
    out = []
    for src in SCRIPT_SRC.findall(page_text(name)):
        if src.startswith("http"):
            continue
        path = WEB / src.lstrip("/")
        if path.is_file():
            out.append(path)
    return out


class TheListIsRealTests(unittest.TestCase):

    def test_every_page_on_the_list_exists(self):
        for name in strict_pages():
            with self.subTest(page=name):
                self.assertTrue((WEB / name).is_file(),
                                "%s is on CSP_STRICT_PAGES and is not a page"
                                % name)

    def test_the_list_is_not_empty(self):
        """Otherwise every assertion below passes on nothing."""
        self.assertTrue(strict_pages())


class AStrictPageHasNoInlineScriptTests(unittest.TestCase):

    def test_no_inline_event_attribute_in_the_markup(self):
        found = {}
        for name in sorted(strict_pages()):
            hits = INLINE_ATTR.findall(page_text(name))
            if hits:
                found[name] = sorted(set(hits))
        self.assertEqual(
            {}, found,
            "these pages carry a policy that forbids inline handlers and "
            "have some:\n  %r\n\nConvert them with "
            "scripts/convert_inline_handlers.py, or take the page off "
            "server.CSP_STRICT_PAGES." % (found,))

    def test_no_inline_script_block(self):
        found = [name for name in sorted(strict_pages())
                 if INLINE_SCRIPT.search(page_text(name))]
        self.assertEqual(
            [], found,
            "inline <script> is blocked by the policy these pages carry: %r. "
            "The theme setter moved to /assets/js/wd-theme-boot.js for exactly "
            "this reason." % (found,))

    def test_the_javascript_a_strict_page_loads_writes_no_inline_handlers(self):
        """The half a markup-only check would miss.

        `innerHTML` with an `onclick` in it is the same defect and the same
        policy blocks it, but it lives in a `.js` file where no scan of the
        HTML would ever look.
        """
        found = {}
        for name in sorted(strict_pages()):
            for script in scripts_for(name):
                hits = JS_INLINE_ATTR.findall(
                    script.read_text(encoding="utf-8", errors="ignore"))
                if hits:
                    found.setdefault(name, []).append(
                        "%s (%d)" % (script.name, len(hits)))
        self.assertEqual(
            {}, found,
            "these pages load JavaScript that writes inline handlers into "
            "markup, which the page's own policy blocks:\n  %r" % (found,))


class EveryDelegatedNameResolvesTests(unittest.TestCase):
    """`data-fn` is a string until something looks it up.

    The same reasoning as `TheAppOnlyPointsAtControlsThatExist`: a name that
    resolves to nothing is a control that renders and does nothing, and the
    dispatcher deliberately warns rather than throwing, so nothing else would
    ever say so.
    """

    def defined_names(self, name):
        """Every function name the page's own scripts define."""
        names = set()
        for script in scripts_for(name):
            text = script.read_text(encoding="utf-8", errors="ignore")
            names |= set(re.findall(r'\bfunction\s+([A-Za-z_$][\w$]*)', text))
            names |= set(re.findall(r'\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)'
                                    r'\s*=\s*(?:function|\()', text))
            # Any `Thing.method = function` - `SP.addCustomDest`,
            # `WD.toggleMenu`. Matching only `WD.` and `window.` missed a
            # whole page's worth of handlers on an object built as
            # `window.SP = {}` and filled in afterwards.
            names |= set(re.findall(
                r'\b[A-Za-z_$][\w$]*\.([A-Za-z_$][\w$]*)\s*=\s*function', text))
            names |= set(re.findall(r'\bwindow\.([A-Za-z_$][\w$]*)\s*=', text))
            # `WD.x = { y: function ... }` and object-literal members.
            names |= set(re.findall(r'^\s*([A-Za-z_$][\w$]*)\s*:\s*function',
                                    text, re.M))
        return names

    def test_every_data_fn_names_something_the_page_defines(self):
        missing = {}
        for name in sorted(strict_pages()):
            defined = self.defined_names(name)
            for fn in sorted(set(DATA_FN.findall(page_text(name)))):
                if fn in BROWSER_BUILTINS:
                    continue
                leaf = fn.split(".")[-1]
                if leaf not in defined:
                    missing.setdefault(name, []).append(fn)
        self.assertEqual(
            {}, missing,
            "these delegated controls name a handler nothing defines - they "
            "would render and do nothing:\n  %r" % (missing,))

    def test_every_data_action_is_one_the_dispatcher_knows(self):
        shared = (WEB / "assets" / "js" / "wd-shared.js").read_text(
            encoding="utf-8")
        block = shared[shared.index("var HANDLERS = {"):]
        known = set(re.findall(r"^\s*'([a-z-]+)':", block[:2000], re.M))
        self.assertTrue(known, "could not read the dispatcher's action names")

        used = set()
        for name in sorted(strict_pages()):
            used |= set(re.findall(r'data-action(?:-[a-z]+)?="([^"]+)"',
                                   page_text(name)))
        self.assertEqual(
            set(), used - known,
            "these markup actions have no handler in WD.actions: %r "
            "(known: %r)" % (sorted(used - known), sorted(known)))


class TheHeaderReallyArrivesTests(unittest.TestCase):
    """Asked of the running app, not of the source.

    A list in `server.py` that nothing applies is the shape of every "two
    stores" bug in this repository: the value is configured, it reads
    correctly, and it is not in force. `/manual` is the case that proves it -
    it is rendered rather than served from disk and never goes through
    `_page`, so it needs the header applied on its own route.
    """

    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        server.app.config["TESTING"] = True
        cls.client = server.app.test_client()

    def routes(self):
        """Which URL serves each page on the strict list."""
        return {"home.html": "/", "scale.html": "/scale",
                "manual.html": "/manual", "plantrim.html": "/plantrim",
                "ap-rename.html": "/aprename", "capacity.html": "/capacity",
                "prep.html": "/prep", "rename.html": "/squirrel/rename",
                "settings.html": "/settings", "setup.html": "/setup"}

    def test_every_strict_page_has_a_route_in_this_test(self):
        """Adding a page to the list without adding it here would leave it
        unchecked while the suite still went green."""
        self.assertEqual(set(self.server.CSP_STRICT_PAGES),
                         set(self.routes()),
                         "CSP_STRICT_PAGES and this test's route map disagree")

    def get(self, url):
        """A response whose file handle is closed.

        `send_from_directory` hands back an open reader, and leaving it to the
        garbage collector fills the suite's output with ResourceWarnings that
        bury anything real.
        """
        resp = self.client.get(url)
        self.addCleanup(resp.close)
        return resp

    def test_a_strict_page_gets_the_strict_policy(self):
        for page, url in sorted(self.routes().items()):
            with self.subTest(page=page):
                resp = self.get(url)
                self.assertEqual(200, resp.status_code)
                policy = resp.headers.get("Content-Security-Policy", "")
                self.assertEqual(self.server.STRICT_CSP, policy,
                                 "%s did not get the strict policy" % page)

    def test_the_policy_actually_forbids_inline_script(self):
        """The one property the whole item is for.

        A policy with `'unsafe-inline'` in `script-src` is a policy that
        changes nothing, and it is an easy thing to add while chasing a
        console warning.
        """
        policy = self.server.STRICT_CSP
        script_src = next(part.strip() for part in policy.split(";")
                          if part.strip().startswith("script-src"))
        self.assertNotIn("unsafe-inline", script_src)
        self.assertNotIn("unsafe-eval", script_src)
        self.assertIn("'self'", script_src)

    def test_an_unconverted_page_keeps_the_permissive_default(self):
        """A page that still needs inline script must not get a policy that
        breaks it. Half a rollout is worse than none."""
        resp = self.get("/walls")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("frame-ancestors 'none'",
                         resp.headers.get("Content-Security-Policy"))

    def test_the_default_policy_is_still_set_everywhere(self):
        for url in ("/walls", "/report", "/squirrel"):
            with self.subTest(url=url):
                self.assertIn(
                    "frame-ancestors 'none'",
                    self.get(url).headers.get("Content-Security-Policy", ""))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
