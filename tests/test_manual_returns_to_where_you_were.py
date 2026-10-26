"""The User Manual puts you back where you were after you follow a link out.

`manual.js` saves the section in view on every scroll and, on load, scrolls to
the saved one. But its first `markCurrent()` ran before the saved value was
read, and on a page that has just loaded no heading is above the reading line,
so that call saved an empty string over it. The restore then found nothing, and
following a link out of the manual and coming back always landed at the top of
a document more than a thousand lines long.

The real script runs against a small stand-in for the page. The section ids
are invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL_JS = ROOT / "web" / "assets" / "js" / "manual.js"

PROGRAM = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const mode = process.argv[2];

const store = new Map();
if (mode === 'saved') store.set('wd-manual-at', '#sec-bravo');
const sessionStorage = {
  getItem: k => store.has(k) ? store.get(k) : null,
  setItem: (k, v) => { store.set(k, String(v)); },
};

// Three sections, all below the reading line, as on a page that has just loaded.
const scrolledTo = [];
const mkSection = (id, top) => ({ id, scrollIntoView() { scrolledTo.push(id); },
                                   getBoundingClientRect: () => ({ top }) });
const sections = { 'sec-alpha': mkSection('sec-alpha', 400),
                   'sec-bravo': mkSection('sec-bravo', 1400),
                   'sec-charlie': mkSection('sec-charlie', 2400) };
const mkLink = id => ({ hidden: false, textContent: id, classList: { add() {}, remove() {} },
  getAttribute: () => '#' + id, getBoundingClientRect: () => ({ top: 0, bottom: 0 }) });
const links = Object.keys(sections).map(mkLink);
const list = { querySelectorAll: () => links, getBoundingClientRect: () => ({ top: 0, bottom: 100, height: 100 }),
               scrollTop: 0 };
const article = { closest: () => null };
const document = {
  getElementById: id => id === 'manualTocList' ? list : id === 'manualArticle' ? article
    : id === 'manualFilter' || id === 'manualTocEmpty' ? null : sections[id] || null,
};
const window = { addEventListener() {} };
const location = { hash: mode === 'hash' ? '#sec-charlie' : '' };
const requestAnimationFrame = fn => fn();

eval(src);
console.log(JSON.stringify({ scrolledTo, saved: store.get('wd-manual-at') }));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheManualReturnsToWhereYouWere(unittest.TestCase):

    def run_manual(self, mode):
        r = subprocess.run(["node", "-e", PROGRAM, str(MANUAL_JS), mode],
                           capture_output=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_saved_section_is_scrolled_to_on_load(self):
        self.assertEqual(["sec-bravo"], self.run_manual("saved")["scrolledTo"])

    def test_a_first_visit_stays_where_it_is(self):
        self.assertEqual([], self.run_manual("none")["scrolledTo"])

    def test_a_link_with_a_hash_wins_over_the_saved_place(self):
        self.assertEqual([], self.run_manual("hash")["scrolledTo"])


if __name__ == "__main__":
    unittest.main()
