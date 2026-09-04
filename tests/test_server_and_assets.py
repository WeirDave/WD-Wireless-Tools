from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import server
from scripts.build_release import build_release
from server import API_REQUEST_HEADER, app


ROOT = Path(__file__).resolve().parent.parent

# Cold Node startup is the slow path on the GitHub Windows runner, and the JS
# unit tests below shell out to it several times per run. A 20s cap used to
# guard these calls; it blew up on a CI runner during the v2.4.0 release, which
# failed the tests gate, skipped the release job, and left the tag published
# with no downloadable assets. 120s is loose enough that a slow cold start
# never trips it and tight enough to still catch a genuine hang.
NODE_TIMEOUT_S = 120


def run_node(args):
    """Run Node with the shared CI-safe timeout, failing clearly on a hang."""
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within the {NODE_TIMEOUT_S}s NODE_TIMEOUT_S "
            f"limit while running {args[-1]}. This is a Node startup/exec "
            f"timeout, not a failure of the code under test: a cold Node "
            f"start on a slow CI runner is the usual cause. Re-run; if it "
            f"recurs, raise NODE_TIMEOUT_S rather than treating it as a "
            f"product bug."
        ) from exc



class ServerAndAssetTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    @staticmethod
    def _api_headers(**extra):
        return {API_REQUEST_HEADER: "1", **extra}

    def test_public_routes_load(self):
        for route in ("/", "/cloud", "/walls", "/squirrel", "/scale", "/report",
                      "/rename", "/squirrel/rename",
                      "/guide", "/guide-cloud", "/guide-squirrel", "/api/version"):
            with self.subTest(route=route):
                response = self.client.get(route)
                try:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers.get("Cache-Control"),
                                     "no-store, no-cache, must-revalidate, max-age=0")
                finally:
                    response.close()

    def test_legacy_organizer_routes_redirect(self):
        for old, new in (("/organizer", "/squirrel"), ("/guide-organizer", "/guide-squirrel")):
            with self.subTest(route=old):
                response = self.client.get(old)
                try:
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.headers.get("Location", "").endswith(new))
                finally:
                    response.close()

    def test_unknown_api_actions_are_rejected(self):
        for route in ("/api/cloud/not_real", "/api/organizer/not_real", "/api/templates/not_real", "/api/rename/not_real"):
            with self.subTest(route=route):
                response = self.client.post(route, json={}, headers=self._api_headers())
                self.assertEqual(response.status_code, 404)
                self.assertIn("unknown action", response.get_json()["error"])

    def test_legitimate_local_requests_reach_argument_free_actions(self):
        cases = (
            ("/api/cloud/forget_login", server.cm, "forget_login", {"ok": True}),
            ("/api/organizer/reset_config", server.fo, "reset_config", {"ok": True}),
        )
        for route, target, method, result in cases:
            with self.subTest(route=route), patch.object(target, method, return_value=result) as action:
                response = self.client.post(
                    route,
                    json={},
                    headers=self._api_headers(Origin="http://localhost"),
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), result)
                action.assert_called_once_with()

    def test_cloud_set_folder_forwards_remembered_directory(self):
        remembered = str(ROOT)
        with patch.object(server.cm, "set_folder", return_value={"path": remembered}) as action:
            response = self.client.post(
                "/api/cloud/set_folder",
                json={"path": remembered},
                headers=self._api_headers(Origin="http://localhost"),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"path": remembered})
        action.assert_called_once_with(remembered)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_cloud_tree_side_selections_normalize_to_one_sync_pair(self):
        script = ROOT / "web" / "assets" / "js" / "cloud.js"
        node_program = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('function selectedSyncItems()');
const end = source.indexOf('\nasync function bulkSync', start);
if (start < 0 || end < 0) throw new Error('selectedSyncItems not found');
let selected = new Set(['ct-c:cloud-1', 'ct-l:C:/sites/one.esx']);
let rowData = {
  'ct:cloud-1': {kind:'pair', cloudId:'cloud-1', localPath:'C:/sites/one.esx'},
  'ct-c:cloud-1': {kind:'cloud', id:'cloud-1'},
  'ct-l:C:/sites/one.esx': {kind:'local', path:'C:/sites/one.esx', isDir:false}
};
eval(source.slice(start, end));
const result = selectedSyncItems();
if (result.length !== 1 || result[0].kind !== 'pair') process.exit(1);
"""
        result = run_node(["node", "-e", node_program, str(script)])
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_cloud_tree_top_level_site_side_selections_normalize_to_one_sync_pair(self):
        # Same as test_cloud_tree_side_selections_normalize_to_one_sync_pair,
        # but for a top-level matched SITE row's independent s-c:/s-l:
        # checkboxes rather than a nested project row's ct-c:/ct-l: ones —
        # selecting either side of a matched site must resolve back to the
        # single p:<cloudId> pair record so a bulk Sync push renames the
        # whole site, not just files inside it.
        script = ROOT / "web" / "assets" / "js" / "cloud.js"
        node_program = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('function selectedSyncItems()');
const end = source.indexOf('\nasync function bulkSync', start);
if (start < 0 || end < 0) throw new Error('selectedSyncItems not found');
let selected = new Set(['s-c:cloud-1', 's-l:C:/sites/one']);
let rowData = {
  'p:cloud-1': {kind:'pair', cloudId:'cloud-1', localPath:'C:/sites/one'},
  's-c:cloud-1': {kind:'cloud', id:'cloud-1'},
  's-l:C:/sites/one': {kind:'local', path:'C:/sites/one', isDir:true}
};
eval(source.slice(start, end));
const result = selectedSyncItems();
if (result.length !== 1 || result[0].kind !== 'pair') process.exit(1);
"""
        result = run_node(["node", "-e", node_program, str(script)])
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_cloud_tree_select_all_reaches_top_level_site_rows(self):
        # toggleSelectAll() used to explicitly skip every non-"ct"-prefixed
        # checkbox on the Sites tab, which meant "Select All" silently only
        # grabbed nested project files and never the site rows themselves.
        script = ROOT / "web" / "assets" / "js" / "cloud.js"
        node_program = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
if (source.includes(`!k.startsWith('ct')`)) process.exit(1);
if (!source.includes('function selectAllSide(side)')) process.exit(2);
"""
        result = run_node(["node", "-e", node_program, str(script)])
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_cloud_tree_orphans_are_eligible_for_bulk_transfer(self):
        script = ROOT / "web" / "assets" / "js" / "cloud.js"
        node_program = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const indexStart = source.indexOf('function indexRowData');
const indexEnd = source.indexOf('\nfunction _passOwnerForCounts', indexStart);
const syncStart = source.indexOf('function isProjectSyncItem');
const syncEnd = source.indexOf('\nfunction bulkDelete', syncStart);
if ([indexStart, indexEnd, syncStart, syncEnd].some(i => i < 0)) throw new Error('sync helpers not found');
let data = {
  matched: [],
  localOnly: [],
  cloudOnly: [{
    id:'site-1', name:'Sydney',
    children:{matched:[], localOnly:[], cloudOnly:[{id:'cloud-1', name:'Baseline Survey'}]}
  }]
};
let rowData = {};
let currentTab = 'sites';
let selected = new Set(['ct:cloud-1']);
let enqueued = [];
let apiCall = null;
function showConfirmModal() { return Promise.resolve(true); }
function clearSelection() { selected.clear(); }
function opEnqueue(spec) { enqueued.push(spec); }
async function pyApi(...args) { apiCall = args; return {}; }
function toast() {}
function _scheduleOpRefresh() {}
eval(source.slice(indexStart, indexEnd));
eval(source.slice(syncStart, syncEnd));
indexRowData();
if (rowData['ct:cloud-1'].entityKind !== 'projects') process.exit(1);
bulkSync('to-local').then(async () => {
  if (enqueued.length !== 1 || enqueued[0].type !== 'download') process.exit(2);
  await enqueued[0].run('op-1');
  if (JSON.stringify(apiCall) !== JSON.stringify(['download_project', 'cloud-1', 'Sydney', 'op-1'])) process.exit(3);
}).catch(err => { console.error(err); process.exit(4); });
"""
        result = run_node(["node", "-e", node_program, str(script)])
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_bulk_sync_creates_missing_cloud_site_and_uploads_its_files(self):
        # A local-only site folder ("select local" + Sync <-) used to be
        # silently dropped by bulk Sync -- no cloud site existed for it, and
        # bulk Sync only ever renamed matched pairs or moved individual
        # project files. It should instead create the missing cloud site
        # and upload every .esx already in the folder to it in one action.
        script = ROOT / "web" / "assets" / "js" / "cloud.js"
        node_program = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const indexStart = source.indexOf('function indexRowData');
const indexEnd = source.indexOf('\nfunction _passOwnerForCounts', indexStart);
const syncStart = source.indexOf('function isProjectSyncItem');
const syncEnd = source.indexOf('\nfunction bulkDelete', syncStart);
if ([indexStart, indexEnd, syncStart, syncEnd].some(i => i < 0)) throw new Error('sync helpers not found');
let data = {
  matched: [], cloudOnly: [],
  localOnly: [{
    path: 'C:/sites/NewSite', name: 'NewSite', isDir: true,
    children: { matched: [], cloudOnly: [], localOnly: [
      {path: 'C:/sites/NewSite/a.esx', name: 'a', isDir: false},
      {path: 'C:/sites/NewSite/b.esx', name: 'b', isDir: false},
    ] }
  }]
};
let rowData = {};
let currentTab = 'sites';
let selected = new Set(['l:C:/sites/NewSite']);
let enqueued = [];
let apiCalls = [];
function showConfirmModal() { return Promise.resolve(true); }
function clearSelection() { selected.clear(); }
// Mirrors the real opEnqueue's contract: it fires spec.run() immediately
// and returns {id, promise} -- bulkSync now awaits that promise for the
// site-create step to learn the new site's id before queuing its uploads.
function opEnqueue(spec) {
  enqueued.push(spec);
  return { id: 'op-x', promise: spec.run('op-x', { aborted: false }) };
}
async function pyApi(...args) { apiCalls.push(args); if (args[0] === 'create_site') return {id: 'new-site-1'}; return {}; }
function toast() {}
function _scheduleOpRefresh() {}
eval(source.slice(indexStart, indexEnd));
eval(source.slice(syncStart, syncEnd));
indexRowData();
bulkSync('to-cloud').then(async () => {
  if (apiCalls[0][0] !== 'create_site' || apiCalls[0][1] !== 'NewSite') process.exit(1);
  // 1 create-site op + 2 upload ops, each now enqueued as its own progress
  // card instead of running silently.
  if (enqueued.length !== 3) process.exit(2);
  if (apiCalls[1][0] !== 'upload_project' || apiCalls[1][1] !== 'C:/sites/NewSite/a.esx' || apiCalls[1][2] !== 'new-site-1') process.exit(3);
}).catch(err => { console.error(err); process.exit(4); });
"""
        result = run_node(["node", "-e", node_program, str(script)])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_restart_accepts_a_legitimate_local_request(self):
        with patch.object(server.threading, "Thread") as thread:
            response = self.client.post(
                "/api/restart",
                headers=self._api_headers(Origin="http://localhost"),
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        thread.assert_called_once_with(target=server._restart_in_new_console, daemon=True)
        thread.return_value.start.assert_called_once_with()

    def test_cross_origin_posts_are_rejected_before_actions_run(self):
        routes = (
            ("/api/cloud/forget_login", server.cm, "forget_login"),
            ("/api/organizer/reset_config", server.fo, "reset_config"),
            ("/api/restart", server, "_restart_in_new_console"),
        )
        forged_headers = (
            {"Origin": "https://malicious.example"},
            self._api_headers(Origin="https://malicious.example"),
        )
        for route, target, method in routes:
            for headers in forged_headers:
                with self.subTest(route=route, headers=headers), patch.object(target, method) as action:
                    response = self.client.post(route, json={}, headers=headers)
                    self.assertEqual(response.status_code, 403)
                    action.assert_not_called()

    def test_non_loopback_host_is_rejected(self):
        response = self.client.post(
            "/api/cloud/forget_login",
            base_url="http://attacker.example:8675",
            json={},
            headers=self._api_headers(Origin="http://attacker.example:8675"),
        )
        self.assertEqual(response.status_code, 403)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_wall_swap_undo_round_trips_type_changes_and_deletes(self):
        # Visual Wall Swap edits walls in bulk, so an accidental swap has to be
        # reversible. The pure history core is kept free of DOM/state so it can
        # be exercised directly here.
        script = ROOT / "web" / "assets" / "js" / "walls-swap.js"
        node_program = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('  // --- pure history core');
const end = source.indexOf('  // --- end pure history core ---');
if (start < 0 || end < 0) throw new Error('pure history core markers not found');
eval(source.slice(start, end));

function assert(cond, msg) { if (!cond) { console.error('FAIL: ' + msg); process.exit(1); } }

// --- a swap, then its undo, must restore the exact original types ---
const segments = [
  {id: 'a', wallTypeId: 'wood'},
  {id: 'b', wallTypeId: 'wood'},
  {id: 'c', wallTypeId: 'concrete'},
];
const original = JSON.stringify(segments);
const changes = [
  {id: 'a', from: 'wood', to: 'rollup'},
  {id: 'b', from: 'wood', to: 'rollup'},
];
assert(applyTypeChanges(segments, changes) === 2, 'swap should touch two segments');
assert(segments[0].wallTypeId === 'rollup', 'a swapped');
assert(segments[1].wallTypeId === 'rollup', 'b swapped');
assert(segments[2].wallTypeId === 'concrete', 'c untouched by a targeted swap');

applyTypeChanges(segments, invertTypeChanges(changes));
assert(JSON.stringify(segments) === original, 'undo must restore the original types exactly');

// redo, then undo again - the round trip has to be stable
applyTypeChanges(segments, changes);
applyTypeChanges(segments, invertTypeChanges(changes));
assert(JSON.stringify(segments) === original, 'undo after redo must still restore the original');

// --- segments that use the alternate `wallType` key ---
const alt = [{id: 'x', wallType: 'wood'}];
applyTypeChanges(alt, [{id: 'x', from: 'wood', to: 'rollup'}]);
assert(alt[0].wallType === 'rollup', 'alternate wallType key is written');
assert(alt[0].wallTypeId === undefined, 'alternate key must not gain a wallTypeId');

// --- an id that no longer exists must not throw or invent a segment ---
assert(applyTypeChanges(segments, [{id: 'gone', from: 'x', to: 'y'}]) === 0, 'missing id is skipped');
assert(segments.length === 3, 'no segment invented');

// --- undoing a delete restores position, not just presence ---
const full = [{id:'a'},{id:'b'},{id:'c'},{id:'d'}];
const before = JSON.stringify(full);
const removed = [{index: 1, seg: full[1]}, {index: 3, seg: full[3]}];
const afterDelete = full.filter(s => s.id !== 'b' && s.id !== 'd');
assert(afterDelete.length === 2, 'two removed');
const restored = restoreRemoved(afterDelete, removed);
assert(JSON.stringify(restored) === before, 'undo of a delete must restore original order');

// out-of-order removal records must still restore correctly
const restored2 = restoreRemoved(afterDelete, [removed[1], removed[0]]);
assert(JSON.stringify(restored2) === before, 'restore is independent of record order');
"""
        result = run_node(["node", "-e", node_program, str(script)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wall_swap_keeps_the_selection_after_applying_a_swap(self):
        # Regression guard. Getting a wall type wrong and immediately
        # re-swapping the same segments to the right one is the recovery path
        # the user relies on, so applySelectionSwap must not clear the
        # selection. See the note above the function body.
        source = (ROOT / "web" / "assets" / "js" / "walls-swap.js").read_text(encoding="utf-8")
        start = source.index("window.applySelectionSwap = function ()")
        end = source.index("window.applyQuickSwap = function ()", start)
        body = source[start:end]
        self.assertNotIn("clearSelectionState()", body)
        self.assertNotIn("state.selected.clear()", body)
        # and it must record an undo entry
        self.assertIn("pushHistory(", body)

    def test_wall_swap_records_undo_history_for_every_destructive_action(self):
        source = (ROOT / "web" / "assets" / "js" / "walls-swap.js").read_text(encoding="utf-8")
        for fn, nxt in (
            ("window.applySelectionSwap = function ()", "window.applyQuickSwap = function ()"),
            ("window.applyQuickSwap = function ()", "window.deleteSelectedWalls = function ()"),
            ("window.deleteSelectedWalls = function ()", "function writeSegmentsBack()"),
        ):
            with self.subTest(operation=fn):
                start = source.index(fn)
                body = source[start:source.index(nxt, start)]
                self.assertIn("pushHistory(", body)

    def test_every_navigation_menu_lists_every_tool(self):
        # The drop-zone menus were kept current as tools were added but the
        # menus shown after a project loads were not, so PlanTrim and the AP
        # Labeler disappeared the moment you opened a file. Menus are generated
        # from one list now; this keeps them from drifting apart again.
        tools = {
            "/cloud": "Cloud Manager",
            "/walls": "Quick Walls",
            "/report": "Report",
            "/scale": "Scale",
            "/plantrim": "PlanTrim",
            "/aprename": "AP Labeler",
            "/squirrel": "Squirrel",
        }
        pages = sorted((ROOT / "web").glob("*.html"))
        checked = 0
        for page in pages:
            html = page.read_text(encoding="utf-8")
            menus = re.findall(
                r'<div class="menu-section">[^<]*Navigation</div>(.*?)'
                r'(?:<div class="(?:help-menu-sep|menu-sep)")',
                html, re.S)
            for index, block in enumerate(menus):
                hrefs = set(re.findall(r'href="(/[a-z0-9\-/]*)"', block))
                for route, name in tools.items():
                    with self.subTest(page=page.name, menu=index, tool=name):
                        self.assertIn(route, hrefs)
                checked += 1
        self.assertGreaterEqual(checked, 10, "expected to find the suite nav menus")

    def test_home_page_offers_every_tool(self):
        home = (ROOT / "web" / "home.html").read_text(encoding="utf-8")
        cards = set(re.findall(r'<a class="card[^"]*" href="(/[a-z0-9\-]*)"', home))
        for route in ("/cloud", "/walls", "/report", "/scale",
                      "/plantrim", "/aprename", "/squirrel"):
            with self.subTest(tool=route):
                self.assertIn(route, cards)

    def test_versions_manifest_has_every_tool(self):
        versions = json.loads((ROOT / "web" / "assets" / "versions.json").read_text(encoding="utf-8"))
        self.assertEqual(set(versions), {"suite", "cloud", "walls", "report", "scale", "squirrel", "plantrim", "aprename"})
        for key, value in versions.items():
            with self.subTest(tool=key):
                self.assertRegex(value, r"^\d+(?:\.\d+)+$")

    def test_public_documentation_uses_current_versions_and_report_status(self):
        versions = json.loads((ROOT / "web" / "assets" / "versions.json").read_text(encoding="utf-8"))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"WIRELESS TOOLS  v{versions['suite']}", readme)
        for tool in ("cloud", "walls", "report", "scale", "squirrel", "plantrim", "aprename"):
            with self.subTest(tool=tool):
                self.assertIn(f"v{versions[tool]}", readme)
        self.assertIn("Seven report formats are available today", readme)
        self.assertIn("Change / Audit Report (coming soon)", readme)
        self.assertIn("[User Manual](docs/USER_MANUAL.md)", readme)
        self.assertIn("reverse-engineered upload/download flows", readme)
        self.assertIn("development-tool configuration", readme)
        for documented_path in (
            "versions.json", "walls-swap.js", "make_test_projects.py", "tests/",
        ):
            with self.subTest(documented_path=documented_path):
                self.assertIn(documented_path, readme)

        cloud_stub = (ROOT / "web" / "pages" / "hosted-cloud-stub.html").read_text(encoding="utf-8")
        squirrel_stub = (ROOT / "web" / "pages" / "hosted-organizer-stub.html").read_text(encoding="utf-8")
        self.assertIn(f"v{versions['cloud']} · desktop suite", cloud_stub)
        self.assertIn(f"v{versions['squirrel']} · desktop suite", squirrel_stub)

    def test_backlog_contains_only_current_unfinished_work(self):
        backlog = (ROOT / "BACKLOG.md").read_text(encoding="utf-8")
        self.assertIn("bulk merge many folders into one", backlog)
        self.assertIn("manual External override", backlog)
        self.assertIn("Change / Audit report", backlog)
        self.assertNotIn("Recently shipped", backlog)
        self.assertNotIn("Process reminders", backlog)
        self.assertNotIn("PROJECT_MEMORY", backlog)

    def test_html_references_existing_local_assets(self):
        asset_pattern = re.compile(r'''(?:src|href)=["'](/assets/[^"'?#]+)''')
        pages = list((ROOT / "web").glob("*.html"))
        pages.extend((ROOT / "web" / "pages").glob("*.html"))
        self.assertTrue(pages)
        for page in pages:
            html = page.read_text(encoding="utf-8")
            for asset_path in asset_pattern.findall(html):
                with self.subTest(page=page.name, asset=asset_path):
                    self.assertTrue((ROOT / "web" / asset_path.lstrip("/")).is_file())

    def test_ap_labeler_offers_every_ordering_it_implements(self):
        """Every ordering in the dropdown has to be handled, and vice versa.

        A mode listed but not implemented falls through sortAPs and silently
        leaves the APs in file order, which reads as "the tool ignored me".
        A mode implemented but not listed is unreachable. Both have happened
        here before, so the two lists are compared rather than trusted.
        """
        html = (ROOT / "web" / "ap-rename.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "assets" / "js" / "ap-rename.js").read_text(encoding="utf-8")

        select = re.search(r'<select id="arOrder">(.*?)</select>', html, re.S)
        self.assertIsNotNone(select, "the spatial ordering dropdown is gone")
        offered = set(re.findall(r'<option value="([^"]+)"', select.group(1)))

        body = re.search(r"function sortAPs\(aps, method\) \{(.*?)\n  \}", js, re.S)
        self.assertIsNotNone(body, "sortAPs is gone or has been reshaped")
        handled = set(re.findall(r"case '([^']+)':", body.group(1)))

        self.assertTrue(offered, "no orderings at all")
        self.assertEqual(offered, handled)

    def test_ap_labeler_preselects_exactly_one_ordering(self):
        html = (ROOT / "web" / "ap-rename.html").read_text(encoding="utf-8")
        select = re.search(r'<select id="arOrder">(.*?)</select>', html, re.S)
        selected = re.findall(r'<option value="([^"]+)"[^>]*selected', select.group(1))
        self.assertEqual(len(selected), 1, "exactly one ordering may be preselected")

    def test_ap_labeler_marker_number_comes_from_the_preview_row(self):
        """The number on the plan and the number in the table must be one value.

        They were computed separately: the table carried a running count across
        floors while the marker drew its position within the current floor. With
        "restart numbering each floor" turned off, floor two restarted at 1 on
        the plan while its names continued, and a start number other than 1 was
        ignored on the plan entirely. The fix was to record the number once, in
        the pass that builds the names, and have every surface read it - so this
        checks the marker still reads rather than recomputes.
        """
        js = (ROOT / "web" / "assets" / "js" / "ap-rename.js").read_text(encoding="utf-8")
        body = re.search(r"function renderMarkers\(\) \{(.*?)\n  \}\n", js, re.S)
        self.assertIsNotNone(body, "renderMarkers is gone or has been reshaped")
        markers = body.group(1)

        self.assertIn("S.byId[ap.id]", markers,
                      "the marker should read the preview row, not rebuild the number")
        self.assertNotIn("idx + 1", markers,
                         "the marker is numbering by its position on the floor again")
        self.assertNotRegex(markers, r"offset\s*\+=",
                            "the running offset is being recomputed here again")

        # and the number the names are built from is the one that gets recorded
        preview = re.search(r"function generatePreview\(\) \{(.*?)\n  \}\n", js, re.S)
        self.assertIsNotNone(preview)
        self.assertIn("num: num", preview.group(1))

    def test_powershell_scripts_are_readable_by_windows_powershell(self):
        """A .ps1 with non-ASCII in it needs a UTF-8 BOM to survive PS 5.1.

        Windows PowerShell 5.1 - still the default shell on a new Windows box -
        reads a BOM-less file as the system ANSI codepage. install.ps1 is full
        of em-dashes and ellipses, so without a BOM every one of them became
        mojibake and the file stopped parsing: nine syntax errors, and
        "right-click -> Run with PowerShell" did nothing at all. The bootstrap
        one-liner was unaffected, because Invoke-RestMethod decodes UTF-8 from
        the response header, which is why this hid for so long - the path that
        broke was the copy shipped inside the ZIP.
        """
        scripts = sorted(ROOT.glob("*.ps1"))
        self.assertTrue(scripts, "no PowerShell scripts found")
        for script in scripts:
            with self.subTest(script=script.name):
                raw = script.read_bytes()
                body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
                try:
                    body.decode("ascii")
                except UnicodeDecodeError:
                    self.assertTrue(
                        raw.startswith(b"\xef\xbb\xbf"),
                        f"{script.name} has non-ASCII characters but no UTF-8 BOM, "
                        "so Windows PowerShell 5.1 will fail to parse it",
                    )

    # Fixed elements that may stay out of the print rules, and why. Anything
    # position:fixed that is not here has to be hidden in print.
    PRINT_CHROME_ALLOWED = {
        ".toast": "lives inside .toasts / .toast-container, both hidden",
        ".dz-topbar": "hidden by id, as #dzTopbar",
        ".scale-copy-buffer": "Scale has nothing to print",
        ".hotkey-sidebar": "Quick Walls has nothing to print",
    }

    def test_fixed_elements_do_not_print(self):
        """Anything position:fixed repeats on every sheet in Chrome.

        A fixed element is not simply visible on the printed page - the engine
        paints it again on every sheet. That put a red "Server is running old
        code" strip across every page of a report, and printing with Report
        settings open put the dialog and its grey scrim over every map. Neither
        shows on screen, and both land on a document that goes to a client.

        So every fixed thing must be hidden in print or listed above with a
        reason. Sticky is left out: it degrades to static when paginating.
        """
        css = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")
        lines = css.split("\n")
        start = next(i for i, l in enumerate(lines) if l.startswith("@media print"))
        depth, end = 0, len(lines) - 1
        for i in range(start, len(lines)):
            depth += lines[i].count("{") - lines[i].count("}")
            if depth == 0 and i > start:
                end = i
                break
        print_block = "\n".join(lines[start:end + 1])

        hidden = set()
        for m in re.finditer(r"([^{}]+)\{[^{}]*display:\s*none[^{}]*\}", print_block):
            for sel in m.group(1).split(","):
                sel = sel.strip().split()[-1] if sel.strip() else ""
                if sel:
                    hidden.add(sel)

        offenders = []
        for i, line in enumerate(lines[:start]):
            if not re.search(r"position:\s*fixed", line):
                continue
            for j in range(i, -1, -1):
                if "{" in lines[j]:
                    for sel in lines[j].split("{")[0].split(","):
                        sel = sel.strip()
                        if not sel or sel.startswith("@"):
                            continue
                        if sel not in hidden and sel not in self.PRINT_CHROME_ALLOWED:
                            offenders.append((sel, i + 1))
                    break

        self.assertEqual(
            offenders, [],
            "position:fixed and not hidden in print - Chrome repeats these on "
            "every sheet of a printed report: " + repr(offenders),
        )

    def test_javascript_files_have_no_nul_bytes(self):
        scripts = list((ROOT / "web" / "assets" / "js").glob("*.js"))
        self.assertTrue(scripts)
        for script in scripts:
            with self.subTest(script=script.name):
                self.assertNotIn(b"\x00", script.read_bytes())

    def test_current_branding_lives_only_with_runtime_assets(self):
        self.assertFalse((ROOT / "images").exists())
        deployed = list((ROOT / "web" / "assets").glob("*v8.0*"))
        self.assertTrue(deployed)
        self.assertTrue(any(path.name == "wd-wireless-tools-v8.0-720x720.png" for path in deployed))

    def test_report_template_cards_have_distinct_accent_colors(self):
        css = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")
        accents = re.findall(
            r"\.rep-template-card\.tpl-([\w-]+)\s*\{[^}]*"
            r"--card-accent:\s*([^;]+);",
            css,
        )
        self.assertEqual(len(accents), 9)
        values = [value.strip().lower() for _, value in accents]
        self.assertEqual(len(values), len(set(values)), accents)

    def test_release_builder_includes_required_files_and_launcher_permissions(self):
        version = json.loads(
            (ROOT / "web" / "assets" / "versions.json").read_text(encoding="utf-8")
        )["suite"]
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / f"WD-Wireless-Tools-v{version}.zip"
            build_release(version, archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertIn("LICENSE", names)
                self.assertIn("docs/USER_MANUAL.md", names)
                self.assertIn("web/assets/lib/jszip.min.js", names)
                self.assertNotIn("PROJECT_MEMORY.md", names)
                self.assertFalse(any(name.startswith("docs/releases/") for name in names))
                self.assertFalse(any(name.startswith("images/") for name in names))
                self.assertFalse(any("__pycache__" in name for name in names))
                mode = archive.getinfo("Start WD Wireless Tools.command").external_attr >> 16
                self.assertTrue(mode & stat.S_IXUSR)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_javascript_files_parse(self):
        scripts = sorted((ROOT / "web" / "assets" / "js").glob("*.js"))
        self.assertTrue(scripts)
        for script in scripts:
            with self.subTest(script=script.name):
                result = run_node(["node", "--check", str(script)])
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
