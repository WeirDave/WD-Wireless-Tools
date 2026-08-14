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


class ServerAndAssetTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    @staticmethod
    def _api_headers(**extra):
        return {API_REQUEST_HEADER: "1", **extra}

    def test_public_routes_load(self):
        for route in ("/", "/cloud", "/walls", "/squirrel", "/scale", "/report",
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
        for route in ("/api/cloud/not_real", "/api/organizer/not_real", "/api/templates/not_real"):
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
        result = subprocess.run(
            ["node", "-e", node_program, str(script)],
            capture_output=True, text=True, timeout=20,
        )
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
const confirm = () => true;
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
        result = subprocess.run(
            ["node", "-e", node_program, str(script)],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_restart_accepts_a_legitimate_local_request(self):
        with patch.object(server.threading, "Thread") as thread:
            response = self.client.post(
                "/api/restart",
                headers=self._api_headers(Origin="http://localhost"),
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        thread.assert_called_once_with(target=server._restart_after_response, daemon=True)
        thread.return_value.start.assert_called_once_with()

    def test_cross_origin_posts_are_rejected_before_actions_run(self):
        routes = (
            ("/api/cloud/forget_login", server.cm, "forget_login"),
            ("/api/organizer/reset_config", server.fo, "reset_config"),
            ("/api/restart", server, "_restart_after_response"),
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

    def test_versions_manifest_has_every_tool(self):
        versions = json.loads((ROOT / "web" / "assets" / "versions.json").read_text(encoding="utf-8"))
        self.assertEqual(set(versions), {"suite", "cloud", "walls", "report", "scale", "squirrel"})
        for key, value in versions.items():
            with self.subTest(tool=key):
                self.assertRegex(value, r"^\d+(?:\.\d+)+$")

    def test_public_documentation_uses_current_versions_and_report_status(self):
        versions = json.loads((ROOT / "web" / "assets" / "versions.json").read_text(encoding="utf-8"))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"WIRELESS TOOLS  v{versions['suite']}", readme)
        for tool in ("cloud", "walls", "report", "scale", "squirrel"):
            with self.subTest(tool=tool):
                self.assertIn(f"v{versions[tool]}", readme)
        self.assertIn("Seven report formats are available today", readme)
        self.assertIn("Change / Audit Report (coming soon)", readme)
        self.assertIn("[User Manual](docs/USER_MANUAL.md)", readme)
        for documented_path in (
            "versions.json", "walls-swap.js", "make_test_projects.py", "tests/",
        ):
            with self.subTest(documented_path=documented_path):
                self.assertIn(documented_path, readme)

        cloud_stub = (ROOT / "web" / "pages" / "hosted-cloud-stub.html").read_text(encoding="utf-8")
        squirrel_stub = (ROOT / "web" / "pages" / "hosted-organizer-stub.html").read_text(encoding="utf-8")
        self.assertIn(f"v{versions['cloud']} · desktop suite", cloud_stub)
        self.assertIn(f"v{versions['squirrel']} · desktop suite", squirrel_stub)

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

    def test_javascript_files_have_no_nul_bytes(self):
        scripts = list((ROOT / "web" / "assets" / "js").glob("*.js"))
        self.assertTrue(scripts)
        for script in scripts:
            with self.subTest(script=script.name):
                self.assertNotIn(b"\x00", script.read_bytes())

    def test_report_template_cards_have_distinct_accent_colors(self):
        css = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")
        accents = re.findall(
            r"\.rep-template-card\.tpl-([\w-]+)\s*\{[^}]*"
            r"--card-accent:\s*([^;]+);",
            css,
        )
        self.assertEqual(len(accents), 8)
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
                self.assertFalse(any("__pycache__" in name for name in names))
                mode = archive.getinfo("run.command").external_attr >> 16
                self.assertTrue(mode & stat.S_IXUSR)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_javascript_files_parse(self):
        scripts = sorted((ROOT / "web" / "assets" / "js").glob("*.js"))
        self.assertTrue(scripts)
        for script in scripts:
            with self.subTest(script=script.name):
                result = subprocess.run(
                    ["node", "--check", str(script)],
                    capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
