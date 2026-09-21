#!/usr/bin/env python3
"""Capture what every element on every page actually computes to.

This is the check that catches a CSS move going wrong, and the reason it is not
a screenshot comparison: the `ar-row` breakage that this exists for was **two
pixels** in a full-page diff and unmissable in the computed styles.

Two captures, because they answer different questions and only the pair covers
the work:

* **computed** - every element in the initial DOM, index aligned, with every
  computed property. The DOM shape does not change in a CSS move, so element
  *n* on a page is the same element before and after and the lists can be
  compared position by position.
* **rules** - for every selector, the declarations that win for it, gathered
  from all stylesheets in cascade order. This is the half that covers elements
  which are not in the initial DOM at all: a page block defines plenty of
  selectors for markup that only appears once a file is loaded, and a computed
  capture can say nothing about those.

  It is also the only thing that sees the document-order trap. An embedded
  `<style>` block beats the linked stylesheet on **document order alone** when
  specificity ties, so moving a rule into `wd-tools.css` can flip which
  declaration applies without any selector changing. Nothing about the selector
  text would show it.

Usage:
    python scripts/capture_computed_styles.py <out-dir> [--browser firefox]

Run it once on the baseline commit and once on the change, then compare with
``scripts/compare_computed_styles.py``.
"""
from __future__ import annotations

import contextlib
import json
import socket
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: Its own port range, away from 8675 (his own instance) and from the ports the
#: browser tests in tests/ use.
PORT_HINT = 8951

def all_pages():
    """Every page in web/, not just the ones being changed.

    **It was the eight pages with a `<style>` block at first, and that was
    wrong twice over.** Deriving the list from the thing under change means the
    list empties the moment the change lands - the first run after the move
    captured nothing at all, and only failed usefully because the comparison
    noticed the two sides did not line up rather than reporting no differences.

    And the narrow list was measuring the wrong thing anyway. Page CSS moved
    into the shared stylesheet now reaches *every* page that links it, so a
    selector that used to be confined to one document can quietly restyle
    another. The pages that were never touched are exactly where that shows up.
    """
    out = []
    for path in sorted(WEB.rglob("*.html")):
        if "node_modules" in path.parts:
            continue
        out.append(path.relative_to(WEB).as_posix())
    return out


#: Both widths, because the drift between Settings and Setup is in padding and
#: type size and a single width can hide a rule that only applies under a
#: media query.
WIDTHS = [(1920, 1080), (1366, 900)]

BROWSERS = {
    "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
}


def stage_web(tmp: Path) -> Path:
    """`web/` as the browser really sees it, which is not how it sits on disk.

    ``pages/landing.html`` is the exception and it matters. It links
    ``assets/wd-tools.css`` *relative to itself*, and the Pages build copies it
    to the root of the site with ``assets/`` beside it - so served from
    ``web/pages/`` that link resolves to ``web/pages/assets/…`` and 404s.

    Captured that way the page has no stylesheet at all, every element computes
    to the browser default, and a comparison of two such captures agrees
    perfectly whatever was done to the CSS. The check would be measuring
    nothing, and would say so in exactly the same words it uses when everything
    is fine.
    """
    import shutil
    staged = tmp / "web"
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(WEB, staged)
    # The landing page, at the root, the way .github/workflows/pages.yml
    # deploys it.
    shutil.copy2(WEB / "pages" / "landing.html", staged / "landing-root.html")
    return staged


def served_path(page: str) -> str:
    """Where *page* is requested from in the staged tree."""
    return "landing-root.html" if page == "pages/landing.html" else page


def _free_port(start):
    for port in range(start, start + 40):
        with contextlib.closing(socket.socket()) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port near %d" % start)


class StubApi(SimpleHTTPRequestHandler):
    """web/ as files, /api/* as JSON.

    Never ``server.py``: it opens a real browser window on his desktop that
    nobody closes.

    Answering ``settings/get`` is load-bearing rather than scaffolding. With it
    refused, a page decides it is the hosted build, ``settingsAvailable`` stays
    false, and whole branches of the markup are never rendered - so the capture
    would be of a page nobody sees, and would compare equal whatever happened
    to the CSS.
    """

    def log_message(self, *a):
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        action = self.path[len("/api/"):]
        if action == "settings/get":
            self._json({"ok": True, "settings": {"report": {}, "aprename": {},
                                                 "cloud": {}, "walls": {}}})
        else:
            self._json({"ok": True})

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._json({"ok": True, "exists": False})
            return
        super().do_GET()


#: Every element, in document order, with every computed property.
#:
#: `cssText` is deliberately not used - it is not stable between engines or
#: between runs. The properties are enumerated and read one at a time, which is
#: slower and gives a list that means the same thing everywhere.
CAPTURE_COMPUTED = r"""
const out = [];
/* `<style>` is an element, and removing one is the entire point of this
   change - so counting it makes every changed page differ by exactly one and
   the index-aligned comparison refuses before it looks at a single property.
   It draws nothing, and neither do the others here. */
const SKIP = { STYLE: 1, LINK: 1, SCRIPT: 1, META: 1, TITLE: 1, HEAD: 1 };
const all = document.querySelectorAll('*');
const els = [];
for (let k = 0; k < all.length; k++) {
  if (!SKIP[all[k].tagName]) els.push(all[k]);
}
for (let i = 0; i < els.length; i++) {
  const el = els[i];
  const cs = getComputedStyle(el);
  const props = {};
  for (let j = 0; j < cs.length; j++) {
    const name = cs[j];
    props[name] = cs.getPropertyValue(name);
  }
  out.push({
    i: i,
    tag: el.tagName.toLowerCase(),
    id: el.id || '',
    cls: el.getAttribute('class') || '',
    props: props,
  });
}
return JSON.stringify(out);
"""

#: For every selector in every stylesheet, the declarations it carries and
#: where it sits in the cascade.
#:
#: Sheet index and rule index are kept because they are the document order that
#: decides a tie, which is the whole point of this half of the capture.
CAPTURE_RULES = r"""
function walk(rules, sheetIdx, out, media) {
  for (let i = 0; i < rules.length; i++) {
    const r = rules[i];
    if (r.type === CSSRule.STYLE_RULE) {
      const decls = {};
      for (let j = 0; j < r.style.length; j++) {
        const p = r.style[j];
        decls[p] = r.style.getPropertyValue(p)
                 + (r.style.getPropertyPriority(p) ? ' !important' : '');
      }
      out.push({ sheet: sheetIdx, order: out.length, media: media,
                 selector: r.selectorText, decls: decls });
    } else if (r.type === CSSRule.MEDIA_RULE) {
      walk(r.cssRules, sheetIdx, out, media + '@media ' + r.conditionText + ' ');
    } else if (r.type === CSSRule.SUPPORTS_RULE) {
      walk(r.cssRules, sheetIdx, out, media + '@supports ' + r.conditionText + ' ');
    }
  }
}
const out = [];
for (let s = 0; s < document.styleSheets.length; s++) {
  let rules = null;
  try { rules = document.styleSheets[s].cssRules; } catch (e) { continue; }
  if (rules) walk(rules, s, out, '');
}
return JSON.stringify(out);
"""


def make_driver(kind: str):
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    binary = BROWSERS[kind]
    if not Path(binary).exists():
        raise RuntimeError("%s is not installed at %s" % (kind, binary))
    try:
        if kind == "firefox":
            o = webdriver.FirefoxOptions()
            o.binary_location = binary
            o.add_argument("-headless")
            return webdriver.Firefox(options=o)
        if kind == "chrome":
            o = webdriver.ChromeOptions()
            o.binary_location = binary
            o.add_argument("--headless=new")
            o.add_argument("--no-sandbox")
            o.add_argument("--hide-scrollbars")
            return webdriver.Chrome(options=o)
        o = webdriver.EdgeOptions()
        o.binary_location = binary
        o.add_argument("--headless=new")
        o.add_argument("--hide-scrollbars")
        return webdriver.Edge(options=o)
    except (WebDriverException, OSError) as exc:
        raise RuntimeError("could not start %s: %s" % (kind, exc))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    kind = "firefox"
    if "--browser" in sys.argv:
        kind = sys.argv[sys.argv.index("--browser") + 1]

    import tempfile
    pages = all_pages()
    tmp = Path(tempfile.mkdtemp(prefix="wd-cssroot-"))
    staged = stage_web(tmp)
    port = _free_port(PORT_HINT)
    httpd = ThreadingHTTPServer(("127.0.0.1", port),
                                partial(StubApi, directory=str(staged)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    driver = make_driver(kind)
    written = 0
    try:
        for page in pages:
            for (w, h) in WIDTHS:
                driver.set_window_size(w, h)
                driver.get("http://127.0.0.1:%d/%s" % (port, served_path(page)))
                # Fonts and any load-time script that writes markup.
                time.sleep(1.1)
                computed = json.loads(driver.execute_script(CAPTURE_COMPUTED))
                rules = json.loads(driver.execute_script(CAPTURE_RULES))
                name = page.replace("/", "_").replace(".html", "")
                blob = {"page": page, "width": w, "browser": kind,
                        "computed": computed, "rules": rules}
                (out_dir / ("%s__%s__%d.json" % (kind, name, w))).write_text(
                    json.dumps(blob), encoding="utf-8")
                written += 1
                print("  captured %-26s %4dpx  %4d elements  %4d rules"
                      % (page, w, len(computed), len(rules)))
    finally:
        with contextlib.suppress(Exception):
            driver.quit()
        httpd.shutdown()
        httpd.server_close()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("%d captures written to %s" % (written, out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
