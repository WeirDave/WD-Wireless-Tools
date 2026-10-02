"""Inside the Settings panel, a way to another page navigates the tool window.

Settings opens in a panel over the tool - an iframe - and every page but
Settings and the User Guide sends `X-Frame-Options: DENY`. So "Re-run Setup
Wizard", "Open Report" and "Home" each loaded their page *inside the panel*,
where the browser refuses it and the panel shows an error instead. They
navigate the top window now; on the Settings page on its own, the top window
is the page, so nothing changes there.

The button is held by running the real `SP.rerunSetup` in Node with a
stubbed window, embedded and standalone. The links are held against the
server's own answer: every link in the page body that leads to a page the
server will not let be framed has to leave the frame.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SETTINGS_JS = ROOT / "web" / "assets" / "js" / "settings-page.js"
SETTINGS_HTML = ROOT / "web" / "settings.html"

PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('  SP.rerunSetup = function () {');
if (a < 0) throw new Error('SP.rerunSetup moved');
let b = a, depth = 0, seen = false;
while (b < src.length && !(seen && depth === 0)) {
  if (src[b] === '{') { depth++; seen = true; }
  else if (src[b] === '}') depth--;
  b++;
}
const EMBEDDED = process.argv[2] === 'embedded';
const calls = [];
const top = { location: { href: '/capacity' } };
global.window = { location: { href: '/settings' } };
window.top = EMBEDDED ? top : window;
const API = (action, body) => { calls.push(action);
  return { then(f) { f({ ok: true }); return this; } }; };
const SP = {};
eval(src.slice(a, b));
SP.rerunSetup();
console.log(JSON.stringify({ calls, self: window.location.href, top: top.location.href }));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ReRunSetupLeavesThePanel(unittest.TestCase):
    def run_it(self, mode):
        r = subprocess.run(["node", "-e", PROBE, str(SETTINGS_JS), mode],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_in_the_panel_the_tool_window_goes_to_setup(self):
        out = self.run_it("embedded")
        self.assertEqual(out["calls"], ["settings/reset_setup"])
        self.assertEqual(out["top"], "/setup")
        self.assertEqual(out["self"], "/settings", "the panel itself is not navigated")

    def test_on_its_own_the_page_goes_to_setup(self):
        out = self.run_it("standalone")
        self.assertEqual(out["self"], "/setup")


class _Anchors(HTMLParser):
    """Anchors outside the top bar, which the panel hides."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.found = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("a", "div", "span", "details", "summary", "section", "nav", "header"):
            in_bar = "topbar" in (a.get("class") or "").split()
            self.stack.append((tag, in_bar))
        if tag == "a" and not any(bar for _t, bar in self.stack):
            self.found.append(a)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


class EveryLinkToAnUnframeablePageLeavesThePanel(unittest.TestCase):
    def test_links_in_the_body_target_the_top_window(self):
        import server
        client = server.app.test_client()
        parser = _Anchors()
        parser.feed(SETTINGS_HTML.read_text(encoding="utf-8"))
        checked = []
        for a in parser.found:
            href = a.get("href") or ""
            if not href.startswith("/") or href.startswith("//"):
                continue
            path = href.split("#")[0].split("?")[0] or "/"
            resp = client.get(path)
            refused = (resp.headers.get("X-Frame-Options", "").upper() == "DENY"
                       or "frame-ancestors 'none'" in resp.headers.get(
                           "Content-Security-Policy", ""))
            resp.close()
            if not refused:
                continue
            checked.append(href)
            self.assertIn(a.get("target"), ("_top", "_blank"),
                          f"{href} refuses to be framed, so inside the Settings "
                          f"panel this link loads a refused page")
        self.assertIn("/report", checked, "the Open Report link was not found")


if __name__ == "__main__":
    unittest.main()
