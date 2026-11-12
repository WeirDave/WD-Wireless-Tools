"""The browser tab says which version of the page is open.

Two tabs of one tool, or a tab left open across an update, are otherwise
indistinguishable. A tool's tab names the tool's number and the suite it
shipped in; Home and the other suite pages name the suite.

The Report is the exception that matters: its document.title is the saved
PDF's file name, so a title the page has replaced must never be extended.
Driven through the real functions in Node, with the real versions.json.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SHARED_JS = WEB / "assets" / "js" / "wd-shared.js"
VERSIONS = json.loads((WEB / "assets" / "versions.json").read_text(encoding="utf-8"))
TOOLS = frozenset(VERSIONS)  # parsed data, not source text

NODE = r"""
const fs = require('fs');
const shared = fs.readFileSync(process.argv[1], 'utf8');
function cut(from, to) {
  const a = shared.indexOf(from);
  const b = shared.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return shared.slice(a, b);
}
const input = JSON.parse(process.argv[2]);
const out = [];
for (const c of input.cases) {
  global.document = {
    title: c.title,
    querySelector: (s) => s === 'title' ? { getAttribute: () => c.tool } : null,
  };
  // The slice is evaluated per case so each page starts from its own title,
  // exactly as the module reads it when the script loads.
  const WD = {};
  eval(cut('  WD.titleWithVersions = ', '  WD.applyVersions = '));
  (c.steps || []).forEach(step => {
    if (step.set !== undefined) global.document.title = step.set;
    if (step.apply) WD.applyTitleVersion(input.versions);
  });
  out.push(global.document.title);
}
console.log(JSON.stringify(out));
"""


def run(cases):
    r = subprocess.run(["node", "-e", NODE, str(SHARED_JS),
                        json.dumps({"cases": cases, "versions": VERSIONS})],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TabTitleTests(unittest.TestCase):
    def test_suite_page_names_the_suite(self):
        (t,) = run([{"title": "WD Wireless Tools", "tool": None, "steps": [{"apply": True}]}])
        self.assertEqual(t, f"WD Wireless Tools v{VERSIONS['suite']}")

    def test_tool_page_names_the_tool_and_the_suite(self):
        (t,) = run([{"title": "WD Cloud Manager", "tool": "cloud", "steps": [{"apply": True}]}])
        self.assertEqual(t, f"WD Cloud Manager v{VERSIONS['cloud']} (suite v{VERSIONS['suite']})")

    def test_applying_twice_does_not_stack_the_number(self):
        (t,) = run([{"title": "WD Prep", "tool": "prep",
                     "steps": [{"apply": True}, {"apply": True}, {"apply": True}]}])
        self.assertEqual(t.count("v" + VERSIONS["prep"]), 1, t)

    def test_a_title_the_page_replaced_is_left_alone(self):
        (t,) = run([{"title": "WD Report", "tool": "report",
                     "steps": [{"set": "Site A - Installation - Rev 1"}, {"apply": True}]}])
        self.assertEqual(t, "Site A - Installation - Rev 1")


class _TitleReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attrs = None

    def handle_starttag(self, tag, attrs):
        if tag == "title" and self.attrs is None:
            self.attrs = dict(attrs)


def _title_attrs(page: Path) -> dict:
    reader = _TitleReader()
    reader.feed(page.read_text(encoding="utf-8"))
    return reader.attrs


class EveryPageDeclaresItsTool(unittest.TestCase):
    def test_a_tool_page_names_a_tool_that_has_a_version(self):
        for page in WEB.glob("*.html"):
            attrs = _title_attrs(page)
            self.assertIsNotNone(attrs, page.name)
            tool = attrs.get("data-tool")
            if tool:
                self.assertIn(tool, TOOLS, page.name)

    def test_every_tool_page_declares_its_tool(self):
        for name in ("ap-rename", "capacity", "cloud", "organizer", "plantrim",
                     "prep", "rename", "report", "scale", "walls"):
            attrs = _title_attrs(WEB / f"{name}.html")
            self.assertIn(attrs.get("data-tool"), TOOLS, name)


if __name__ == "__main__":
    unittest.main()
