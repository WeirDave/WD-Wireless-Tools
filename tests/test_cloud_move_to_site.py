"""Moving projects into a cloud site — the control has to be where the rows are.

Everything needed for this already existed. `assign_to_site` reassigns a
project directly, the picker lists real cloud sites, a destination can be
stamped on every row at once, and a partial failure is reported per item. What
did not exist was any way to reach it from the **Sites** tab.

"Move to site…" was shown only when `currentTab === 'projects'`. The Sites tab
is the tree, and the tree is where the nested `.esx` rows live — so selecting a
handful of project files there and looking for a Move found nothing, and the
feature read as missing.

The tab was standing in for a different question. A site row and a nested
project row are **both** `kind: 'cloud'`; what separates them is
`entityKind`. `isProjectSyncItem()` asks that directly, and is what both the
button and the action use now — so a site can never be handed to
`assign_to_site` as though it were a project, which is the reason the crude
tab check was there in the first place.

Driven through the real selection code in Node.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CLOUD_PY = ROOT / "tools" / "cloud_manager.py"

NODE_TIMEOUT_S = 120

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function cut(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
eval(cut('function isProjectSyncItem(d) {', '/* What a Sync in this direction'));

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}

// The four row shapes indexRowData builds, reduced to what this decides on.
const siteCloud    = { kind: 'cloud', id: 'site-1', name: 'Sydney', entityKind: 'sites' };
const siteLocal    = { kind: 'local', path: '/l/Sydney', name: 'Sydney', isDir: true,
                       entityKind: 'sites' };
const projectCloud = { kind: 'cloud', id: 'proj-1', name: 'SITE4-A', entityKind: 'projects' };
const projectLocal = { kind: 'local', path: '/l/SITE4-A.esx', name: 'SITE4-A',
                       isDir: false, entityKind: 'projects' };

// A matched project on the Projects tab: one row, two sides.
const projectPair  = { kind: 'pair', cloudId: 'proj-1', cloudName: 'SITE4-A',
                       localName: 'SITE4-A', localPath: '/l/SITE4-A.esx',
                       matchType: 'exact', entityKind: 'projects' };
const sitePair     = { kind: 'pair', cloudId: 'site-1', cloudName: 'Sydney',
                       localName: 'Sydney', localPath: '/l/Sydney',
                       matchType: 'exact', entityKind: 'sites' };

// What the bulk bar counts and what the action takes are the same function.
function movable(d) { return movableSidesOf(d).length > 0; }
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
class ProjectsAreMovableFromEitherTab(unittest.TestCase):

    def run_block(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_nested_project_rows_are_movable_from_the_sites_tab(self):
        """The reported case: select some .esx files in the tree and move them.
        These rows only appear on the Sites tab."""
        self.run_block("""
          currentTab = 'sites';
          check('a cloud project in the tree is movable', movable(projectCloud));
          check('a local .esx in the tree is movable', movable(projectLocal));
          done();
        """)

    def test_a_site_is_never_movable_into_a_site(self):
        """A site row is also kind 'cloud'. Handing one to assign_to_site would
        file a site inside a site - which is why the tab check existed, and is
        the thing that still has to hold now the tab check is gone."""
        self.run_block("""
          currentTab = 'sites';
          check('a cloud site row is not a movable project', !movable(siteCloud));
          check('a local site folder is not a movable project', !movable(siteLocal));
          done();
        """)

    def test_the_projects_tab_still_works_as_before(self):
        """On that tab every row is a project, whatever entityKind says."""
        self.run_block("""
          currentTab = 'projects';
          check('cloud project movable', movable(projectCloud));
          check('local .esx movable', movable(projectLocal));
          check('a local folder is still not a file', !movable(
            { kind: 'local', path: '/l/f', name: 'f', isDir: true }));
          done();
        """)


class TheButtonAndTheActionAgree(unittest.TestCase):
    """The last faults in this file were a control disagreeing with the thing
    behind it - a badge with no handler, and a Sync that dropped what the bar
    said it would take. The button and the action ask the same question."""

    def setUp(self):
        self.source = CLOUD_JS.read_text(encoding="utf-8")

    def test_the_button_is_no_longer_hidden_on_the_sites_tab(self):
        self.assertIn("setBtn('bulkMoveBtn', true, movableCount > 0", self.source)
        self.assertNotIn("setBtn('bulkMoveBtn', currentTab === 'projects'", self.source)

    def test_the_count_asks_the_shared_question(self):
        self.assertIn("if (movableSidesOf(d).length) movableCount++;", self.source)

    def test_the_action_applies_the_same_test(self):
        block = self.source[self.source.index("async function bulkMoveToSite()"):]
        block = block[:block.index("_openMoveToSitePicker")]
        self.assertIn("movableSidesOf(rowData[k])", block)

    def test_there_is_only_one_answer_to_what_can_move(self):
        """The old shape - `d.kind === 'cloud' || (d.kind === 'local' &&
        !d.isDir)` - was written out twice, and both copies were wrong in the
        same way. One function now, or the next fix lands in one of them."""
        code = re.sub(r"/\*.*?\*/", "", self.source, flags=re.S)
        code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
        self.assertNotIn("d.kind === 'cloud' || (d.kind === 'local' && !d.isDir)", code,
                         "the old two-copy rule is back in live code")


class MovingIsAReassignmentNotARewrite(unittest.TestCase):
    """The upload direction is blocked precisely because it would mean
    delete-and-reupload. Moving is not: the API reassigns a dataset to a site
    in one call, so nothing is deleted and the project keeps its id, its
    shares and its history."""

    def test_the_api_call_is_a_direct_assignment(self):
        src = CLOUD_PY.read_text(encoding="utf-8")
        block = src[src.index("def assign_to_site"):]
        block = block[:block.index("\n    def ", 1)]
        self.assertIn("/site-management-api/v1/sites/", block)
        self.assertIn("datasets", block)
        for destructive in ("delete_project", "upload_project", "batch-delete"):
            with self.subTest(not_used=destructive):
                self.assertNotIn(destructive, block)

    def test_a_partial_failure_names_what_happened(self):
        """Three of five moving and the fourth failing must not leave him
        counting cards to work out which."""
        src = CLOUD_JS.read_text(encoding="utf-8")
        block = src[src.index("function _reportMoveOutcome"):]
        block = block[:block.index("function _wireIconTipDelegation")]
        self.assertIn("results.failed", block)
        self.assertIn("results.skipped", block)
        self.assertIn("results.firstErr", block)
        self.assertIn("Moved ${results.ok}", block)


class MovesGoThroughTheQueueLikeEverythingElse(unittest.TestCase):
    """He asked for this directly: "you can queue the move just like we
    currently queue moves."

    Auto-assign already queued `assign_to_site` through opEnqueue, with a card,
    a stage, a retry and a cancel. The bulk move ran its own blocking
    for-await loop with a private tally - a second implementation of "assign a
    project to a site" sitting right next to the queued one, and the only
    operation in the tool with no card to look at when one of fifteen failed.
    """

    def setUp(self):
        self.source = CLOUD_JS.read_text(encoding="utf-8")
        start = self.source.index("  closeModal('moveToSiteModal');")
        self.body = self.source[start:self.source.index("function _reportMoveOutcome")]

    def test_each_move_is_queued(self):
        self.assertIn("opEnqueue({", self.body)
        self.assertIn("pyApi('assign_to_site', siteId, t.id)", self.body)
        self.assertIn("pyApi('move_local_to_site', t.path, folder)", self.body)

    def test_a_single_failed_move_can_be_retried(self):
        """The point of the deck. A blocking loop gave him no way to retry
        one of fifteen without redoing the selection."""
        self.assertIn("retryFn:", self.body)

    def test_the_blocking_loop_is_gone(self):
        self.assertNotIn("let ok = 0, fail = 0, firstErr = ''", self.source)

    def test_creating_a_destination_site_is_resolved_before_the_moves(self):
        """A move needs the new site's id, so that one op is awaited. Queueing
        it alongside the moves would race the id it hands them."""
        create_at = self.body.index("Creating cloud site")
        move_at = self.body.index("Moving \"${label}\"")
        self.assertLess(create_at, move_at)
        self.assertIn("await promise;", self.body[:move_at])

    def test_two_rows_bound_for_one_new_site_create_it_once(self):
        self.assertIn("const needNew = new Set();", self.body)
        self.assertIn("newSiteByName.get(key)", self.body)

    def test_a_move_whose_site_could_not_be_created_is_skipped_not_lost(self):
        """Queueing it anyway would fail with a confusing error; dropping it
        silently would leave him believing it moved."""
        self.assertIn("createFailed", self.body)
        self.assertIn("results.skipped++", self.body)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class AMatchedProjectCanBeMovedTo(unittest.TestCase):
    """The everyday case, and the one that did not work.

    His workflow ends with the local .esx and the cloud project matched. On the
    **Projects** tab that is a single row of `kind: 'pair'` - which is the one
    row shape neither the count nor the action accepted, so "Move to site..."
    stayed greyed out for precisely the files he would be moving. It worked on
    the Sites tab only because the tree gives each side of a nested pair its own
    checkbox key, and those rows are plain cloud/local.
    """

    def run_block(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_a_matched_project_is_movable_from_the_projects_tab(self):
        self.run_block("""
          currentTab = 'projects';
          check('a matched project row is movable', movable(projectPair));
          done();
        """)

    def test_both_sides_of_the_pair_move(self):
        """Filing the cloud project under one site and leaving the .esx in
        another folder would break the pair that the move is meant to keep."""
        self.run_block("""
          currentTab = 'projects';
          const sides = movableSidesOf(projectPair);
          check('two sides', sides.length === 2);
          check('cloud side carries the cloud id',
                sides.some(s => s.kind === 'cloud' && s.id === 'proj-1'));
          check('local side carries the local path',
                sides.some(s => s.kind === 'local' && s.path === '/l/SITE4-A.esx'));
          done();
        """)

    def test_a_matched_site_is_still_not_movable(self):
        """A site pair's local side is a folder. assign_to_site must never be
        handed one, which is what the .esx test is for."""
        self.run_block("""
          currentTab = 'sites';
          check('a matched site is not movable', !movable(sitePair));
          currentTab = 'projects';
          check('nor on the projects tab', !movable(sitePair));
          done();
        """)

    def test_selecting_a_pair_and_one_of_its_sides_moves_each_side_once(self):
        """Both are reachable on the Sites tab, and a doubled move would queue
        assign_to_site twice for one project."""
        self.run_block("""
          currentTab = 'projects';
          const rows = [projectPair, projectCloud];
          const seen = new Set();
          const sides = rows.flatMap(movableSidesOf).filter(sd => {
            const k = sd.kind + ':' + (sd.id || sd.path);
            if (seen.has(k)) return false;
            seen.add(k); return true;
          });
          check('three moves, not four', sides.length === 2 + 0 + 1 - 1);
          check('the cloud project is queued once',
                sides.filter(s => s.kind === 'cloud' && s.id === 'proj-1').length === 1);
          done();
        """)


if __name__ == "__main__":
    unittest.main()
