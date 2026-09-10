"""One button that grabs everything the cloud has that is newer.

Bulk Sync can already do this, but only over rows you have selected - which
means finding every stale pair yourself, across sites and nested files, and
knowing you found all of them. Same capability, different job.

"All the cloud stuff" is two things, and splitting them across two controls
would leave the work half done with no way to tell which half:

  - matched pairs where the cloud copy is newer  -> content comes down
  - cloud-only projects                          -> downloaded fresh

One-directional on purpose. Nothing newer locally is touched and nothing
already in sync is re-fetched, which is what makes it safe as a single button
rather than a bulk overwrite of everything.

Driven through the real everythingFromCloud in Node.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CLOUD_HTML = ROOT / "web" / "cloud.html"

NODE_TIMEOUT_S = 120

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const a = source.indexOf('function everythingFromCloud() {');
const b = source.indexOf('async function pullEverythingFromCloud()');
if (a < 0 || b < 0) throw new Error('the collector moved');
eval(source.slice(a, b));

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
// A matched file pair. Local side is an .esx; a site's would be a folder.
function pair(name, staleness) {
  return {
    cloud: { id: 'c-' + name, name: name, mtime: 200 },
    local: { name: name, path: '/local/' + name + '.esx', mtime: 100 },
    staleness: staleness || null,
  };
}
function cloudOnly(id) { return { id: id, name: id, mtime: 200 }; }
function names(list, key) { return list.map(x => x[key]).sort().join(','); }
"""


def _js(text: str) -> str:
    return json.dumps(text)


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = NODE_PRELUDE + "eval(" + _js(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                              capture_output=True, text=True,
                              timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s. That is a Node "
            f"startup timeout, not a failure of the code under test."
        ) from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ItFindsEverythingWithoutBeingTold(unittest.TestCase):

    def run_block(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_it_takes_both_halves_of_what_the_cloud_has(self):
        self.run_block("""
          data = { summary: {}, matched: [pair('a','cloud_newer')],
                   cloudOnly: [cloudOnly('fresh-1')] };
          var p = everythingFromCloud();
          check('the stale pair comes down', p.pulls.length === 1);
          check('the cloud-only project is downloaded', p.fresh.length === 1);
          done();
        """)

    def test_it_reaches_files_nested_inside_sites(self):
        """The stale ones are usually inside a site, which is exactly what
        makes assembling this by hand tedious enough to get wrong."""
        self.run_block("""
          data = { summary: {}, matched: [{
            cloud: { id: 'site-1', name: 'Sydney', children: {
              matched: [pair('inner','cloud_newer'), pair('ok', null)],
              cloudOnly: [cloudOnly('inner-fresh')]
            }},
            local: { name: 'Sydney', path: '/local/Sydney' },
            staleness: null
          }] };
          var p = everythingFromCloud();
          check('the nested stale file is found: ' + names(p.pulls, 'cloudName'),
                names(p.pulls, 'cloudName') === 'inner');
          check('so is the nested cloud-only one: ' + names(p.fresh, 'id'),
                names(p.fresh, 'id') === 'inner-fresh');
          check('the in-sync one is counted, not pulled', p.inSync === 1);
          done();
        """)

    def test_a_site_is_never_treated_as_a_file(self):
        """A matched site is the same shape as a matched pair, but its local
        side is a folder - handing that to a download-and-replace would point
        it at a directory."""
        self.run_block("""
          data = { summary: {}, matched: [{
            cloud: { id: 'site-1', name: 'Sydney' },
            local: { name: 'Sydney', path: '/local/Sydney' },
            staleness: 'cloud_newer'
          }] };
          var p = everythingFromCloud();
          check('the folder is not pulled', p.pulls.length === 0);
          done();
        """)

    def test_nothing_newer_locally_is_ever_swept_along(self):
        """The whole reason this can be one button."""
        self.run_block("""
          data = { summary: {}, matched: [
            pair('down','cloud_newer'), pair('mine','local_newer'),
            pair('same', null)] };
          var p = everythingFromCloud();
          check('only the cloud-newer one moves: ' + names(p.pulls, 'cloudName'),
                names(p.pulls, 'cloudName') === 'down');
          check('the locally-newer one is reported, not touched: ' +
                names(p.blocked, 'cloudName'),
                names(p.blocked, 'cloudName') === 'mine');
          check('and the matching one is left alone', p.inSync === 1);
          done();
        """)

    def test_the_same_project_is_not_queued_twice(self):
        """A project can appear both nested under its site and in the orphan
        list. Downloading it twice would race two writes at one path."""
        self.run_block("""
          data = { summary: {},
            matched: [{
              cloud: { id: 'site-1', name: 'Sydney', children: {
                matched: [pair('dup','cloud_newer')],
                cloudOnly: [cloudOnly('fresh-1')]
              }},
              local: { name: 'Sydney', path: '/local/Sydney' }, staleness: null
            }],
            cloudOnly: [cloudOnly('fresh-1')],
            orphans: { cloudOnly: [cloudOnly('fresh-1')] } };
          var p = everythingFromCloud();
          check('one download, not three: ' + p.fresh.length, p.fresh.length === 1);
          check('one pull', p.pulls.length === 1);
          done();
        """)

    def test_an_up_to_date_listing_yields_nothing_to_do(self):
        self.run_block("""
          data = { summary: {}, matched: [pair('a', null), pair('b', null)] };
          var p = everythingFromCloud();
          check('nothing to pull', p.pulls.length === 0);
          check('nothing to download', p.fresh.length === 0);
          check('both counted as in sync', p.inSync === 2);
          done();
        """)

    def test_a_download_carries_the_site_it_belongs_in(self):
        """Downloaded into the wrong folder is a different bug that looks like
        this one."""
        self.run_block("""
          data = { summary: {}, matched: [{
            cloud: { id: 'site-1', name: 'Sydney', children: {
              matched: [], cloudOnly: [cloudOnly('inner')] }},
            local: { name: 'Sydney', path: '/local/Sydney' }, staleness: null
          }] };
          var p = everythingFromCloud();
          check('site name travels with it: ' + p.fresh[0].siteName,
                p.fresh[0].siteName === 'Sydney');
          done();
        """)


class ItSaysWhatItWillDoBeforeItDoesIt(unittest.TestCase):

    def setUp(self):
        self.source = CLOUD_JS.read_text(encoding="utf-8")
        start = self.source.index("async function pullEverythingFromCloud()")
        self.body = self.source[start:self.source.index("clearSelection();", start)]

    def test_every_file_it_will_overwrite_is_named_with_both_dates(self):
        self.assertIn("sync-plan", self.body)
        self.assertIn("fmtRelDate(d.cloudMtime)", self.body)
        self.assertIn("fmtRelDate(d.localMtime)", self.body)

    def test_the_backup_is_promised_where_the_overwrite_is_confirmed(self):
        self.assertIn(".previous-", self.body)

    def test_the_divergence_caveat_travels_with_it(self):
        """Two timestamps cannot separate "cloud is newer" from "we both
        changed it", and this action overwrites more files at once than any
        other, so the person clicking it is the one who needs telling."""
        self.assertIn("Two dates cannot tell you whether both sides", self.body)

    def test_what_it_leaves_alone_is_counted_too(self):
        self.assertIn("plan.blocked.length", self.body)
        self.assertIn("plan.inSync", self.body)

    def test_it_says_so_rather_than_opening_an_empty_confirm(self):
        self.assertIn("already up to date", self.body)


class ThereIsStillOneDownloadImplementation(unittest.TestCase):

    def test_it_reuses_verify_replace_local(self):
        source = CLOUD_JS.read_text(encoding="utf-8")
        start = source.index("async function pullEverythingFromCloud()")
        block = source[start:source.index("window.pullEverythingFromCloud", start)]
        self.assertIn("pyApi('verify_replace_local'", block)
        self.assertIn("pyApi('download_project'", block)


class TheButtonDoesNotNeedASelection(unittest.TestCase):
    """Asking him to select the stale rows first is the thing he asked not to
    have to do, so it must not carry the class that hides it until something
    is ticked."""

    def test_it_is_not_gated_behind_bulk_selection(self):
        html = CLOUD_HTML.read_text(encoding="utf-8")
        line = next(l for l in html.splitlines() if 'id="pullAllBtn"' in l)
        self.assertNotIn("bulk-btn", line)
        self.assertIn("pullEverythingFromCloud()", line)


if __name__ == "__main__":
    unittest.main()
