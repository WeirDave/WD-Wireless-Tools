"""The update panel's "what changed since your version" list.

`/api/update/status` adds `latest.changes`: every published release newer than
the installed one, newest first, as {version, title, notes, url} - the shape the
shared `release-changelog.js` draws above the Update button. The list is
optional data in the same way the release notes are: it comes from
api.github.com, so it waits a short time, fails quietly, and is never asked for
when the API has just shown itself unreachable.

Every release body, title and version below is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tools import updater

ROOT = Path(__file__).resolve().parent.parent

GIT_INSTALL = {"isGitInstall": True, "currentVersion": "2.5.0",
               "releasesUrl": "https://github.com/o/r/releases", "method": "git"}
ZIP_INSTALL = {"isGitInstall": False, "currentVersion": "2.5.0",
               "releasesUrl": "https://github.com/o/r/releases", "method": "zip"}


def release(tag, title="A change", body=None, **extra):
    if body is None:
        body = (f"# {title}\n\nSuite **{tag.lstrip('v')}**: Example Tool **1.0.0**.\n\n"
                "## What changed\n\n### Example Tool\n\n"
                "- **A thing** now does `x`.\n\n"
                "## Verified\n\n- The suite passes.\n\n"
                "## Files changed\n\n- `tools/example.py`\n")
    out = {"tag_name": tag, "name": f"Example {tag}", "body": body,
           "html_url": f"https://github.com/o/r/releases/tag/{tag}",
           "draft": False, "prerelease": False}
    out.update(extra)
    return out


class _Resp:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _fresh():
    updater._RELEASE_CACHE.update(
        {"at": 0.0, "data": None, "etag": None, "blocked_until": 0.0})
    updater._RECENT_CACHE.update({"at": 0.0, "data": None, "etag": None})


class SplitReleaseBodyTests(unittest.TestCase):
    def test_the_title_is_lifted_out_of_the_notes(self):
        title, notes = updater.split_release_body("# One line\n\n## What changed\n- a\n")
        self.assertEqual(title, "One line")
        self.assertEqual(notes, "## What changed\n- a")

    def test_verified_and_files_changed_are_dropped_with_everything_after(self):
        body = "# T\n\n## What changed\n- a\n\n## Verified\n- v\n\n## Files changed\n- `f`\n"
        self.assertEqual(updater.split_release_body(body)[1], "## What changed\n- a")

    def test_files_changed_alone_is_dropped(self):
        body = "# T\n\n## What changed\n- a\n\n## Files changed\n- `f`\n"
        self.assertEqual(updater.split_release_body(body)[1], "## What changed\n- a")

    def test_verification_ends_the_notes_too_in_any_case(self):
        for heading in ("## Verification", "## VERIFIED", "## files changed"):
            with self.subTest(heading=heading):
                body = "# T\n\n- a\n\n" + heading + "\n- v\n"
                self.assertEqual(updater.split_release_body(body)[1], "- a")

    def test_only_a_two_hash_heading_on_a_word_boundary_ends_the_notes(self):
        for body in ("# T\n- a\n### Verified\n- v\n",
                     "# T\n- a\n# Verified\n- v\n",
                     "# T\n- a\n## Verifiedly\n- v\n",
                     "# T\n- a\nVerified by hand\n- v\n"):
            with self.subTest(body=body):
                self.assertIn("- v", updater.split_release_body(body)[1])

    def test_a_heading_at_the_very_top_of_the_notes_leaves_nothing(self):
        self.assertEqual(updater.split_release_body("# T\n## Verified\n- v\n"), ("T", ""))

    def test_windows_line_endings(self):
        title, notes = updater.split_release_body("# T\r\n\r\n- a\r\n- b\r\n")
        self.assertEqual((title, notes), ("T", "- a\n- b"))

    def test_no_title_and_no_body(self):
        self.assertEqual(updater.split_release_body("- just a bullet"), ("", "- just a bullet"))
        self.assertEqual(updater.split_release_body(None), ("", ""))
        self.assertEqual(updater.split_release_body(""), ("", ""))

    def test_only_a_leading_h1_is_a_title(self):
        title, notes = updater.split_release_body("Intro\n\n# Later\n- a")
        self.assertEqual(title, "")
        self.assertIn("# Later", notes, "a mid-body H1 is neither a title nor removed")

    def test_blank_lines_before_the_title_do_not_stop_it_being_one(self):
        self.assertEqual(updater.split_release_body("\n\n  # T\n- a"), ("T", "- a"))

    def test_a_second_level_heading_is_not_a_title(self):
        title, notes = updater.split_release_body("## What changed\n- a")
        self.assertEqual((title, notes), ("", "## What changed\n- a"))


class ReleasesSinceTests(unittest.TestCase):
    def setUp(self):
        _fresh()
        self.addCleanup(_fresh)

    def since(self, raw, current="2.5.0"):
        with mock.patch.object(updater, "fetch_recent_releases", return_value=raw):
            return updater.releases_since(current)

    def test_only_releases_newer_than_the_install_newest_first(self):
        raw = [release("v2.4.0"), release("v2.7.0"), release("v2.5.0"),
               release("v2.6.0"), release("v2.10.0")]
        out = self.since(raw)["changes"]
        self.assertEqual([c["version"] for c in out], ["2.10.0", "2.7.0", "2.6.0"],
                         "numeric, not text, ordering; nothing at or below 2.5.0")

    def test_the_shared_shape(self):
        out = self.since([release("v2.6.0", title="Better thing")])["changes"]
        self.assertEqual(set(out[0]), {"version", "title", "notes", "url"})
        self.assertEqual(out[0]["version"], "2.6.0")
        self.assertEqual(out[0]["title"], "Better thing")
        self.assertEqual(out[0]["url"], "https://github.com/o/r/releases/tag/v2.6.0")

    def test_files_changed_and_verified_never_reach_the_notes(self):
        notes = self.since([release("v2.6.0")])["changes"][0]["notes"]
        self.assertIn("A thing", notes)
        self.assertNotIn("Files changed", notes)
        self.assertNotIn("tools/example.py", notes)
        self.assertNotIn("Verified", notes)
        self.assertFalse(notes.startswith("# "), "the title is not repeated in the notes")

    def test_drafts_and_prereleases_are_skipped(self):
        raw = [release("v2.6.0", draft=True), release("v2.7.0", prerelease=True),
               release("v2.8.0")]
        self.assertEqual([c["version"] for c in self.since(raw)["changes"]], ["2.8.0"])

    def test_tags_that_are_not_versions_and_junk_entries_are_skipped(self):
        raw = [release("nightly"), release("v2.9"), {"tag_name": None}, "text", None,
               release("v2.6.0")]
        self.assertEqual([c["version"] for c in self.since(raw)["changes"]], ["2.9", "2.6.0"])

    def test_a_link_that_is_not_github_is_replaced_by_the_release_page(self):
        raw = [release("v2.6.0", html_url="javascript:alert(1)")]
        url = self.since(raw)["changes"][0]["url"]
        self.assertEqual(url, "https://github.com/WeirDave/WD-Wireless-Tools/releases/tag/v2.6.0")

    def test_up_to_date_is_an_empty_list(self):
        out = self.since([release("v2.5.0"), release("v2.4.0")])
        self.assertEqual(out, {"changes": [], "more": False})

    def test_each_release_is_capped_on_a_line_boundary(self):
        long_body = "# T\n" + "\n".join(f"- line {i} " + "x" * 50 for i in range(200))
        notes = self.since([release("v2.6.0", body=long_body)])["changes"][0]["notes"]
        self.assertLessEqual(len(notes), updater.CHANGE_NOTES_MAX + 2)
        self.assertTrue(notes.endswith("…"))
        self.assertTrue(notes.splitlines()[-2].endswith("x"), "cut between lines, not mid-line")

    def test_the_whole_answer_is_bounded_and_older_releases_keep_their_names(self):
        body = "# T\n" + "\n".join(f"- line {i} " + "y" * 60 for i in range(80))
        raw = [release(f"v2.{n}.0", body=body) for n in range(6, 36)]
        out = self.since(raw)["changes"]
        self.assertEqual(len(out), 30)
        self.assertLessEqual(sum(len(c["notes"]) for c in out),
                             updater.CHANGES_TOTAL_MAX + 2 * len(out))
        self.assertEqual(out[0]["version"], "2.35.0")
        self.assertTrue(out[0]["notes"], "the newest release keeps its notes")
        self.assertEqual(out[-1]["notes"], "", "the budget ran out before the oldest")
        self.assertEqual(out[-1]["version"], "2.6.0", "but it is still listed")

    def test_a_full_page_of_newer_releases_may_have_more_behind_it(self):
        raw = [release(f"v3.{n}.0") for n in range(updater.CHANGES_PAGE_SIZE)]
        self.assertTrue(self.since(raw)["more"])

    def test_a_full_page_that_reaches_the_install_has_nothing_behind_it(self):
        raw = [release(f"v3.{n}.0") for n in range(updater.CHANGES_PAGE_SIZE - 1)]
        raw.append(release("v2.5.0"))
        self.assertFalse(self.since(raw)["more"])

    def test_a_short_page_never_says_more(self):
        self.assertFalse(self.since([release("v3.0.0"), release("v3.1.0")])["more"])


class FetchRecentReleasesTests(unittest.TestCase):
    def setUp(self):
        _fresh()
        self.addCleanup(_fresh)

    def test_it_asks_for_thirty_releases_with_the_short_wait(self):
        seen = {}

        def fake_get(url, headers=None, params=None, timeout=None):
            seen.update(url=url, params=params, timeout=timeout, headers=headers)
            return _Resp([release("v2.6.0")])

        with mock.patch("requests.get", fake_get):
            updater.fetch_recent_releases(timeout=updater.NOTES_TIMEOUT)
        self.assertTrue(seen["url"].endswith("/repos/WeirDave/WD-Wireless-Tools/releases"))
        self.assertEqual(seen["params"], {"per_page": 30})
        self.assertEqual(seen["timeout"], updater.NOTES_TIMEOUT)
        self.assertEqual(seen["headers"]["Accept"], "application/vnd.github+json")

    def test_repeated_calls_cost_one_request_and_a_recheck_is_conditional(self):
        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            calls.append(dict(headers))
            if "If-None-Match" in headers:
                return _Resp(None, status=304)
            return _Resp([release("v2.6.0")], headers={"ETag": 'W/"abc"'})

        with mock.patch("requests.get", fake_get):
            first = updater.fetch_recent_releases()
            self.assertEqual(updater.fetch_recent_releases(), first)
            self.assertEqual(len(calls), 1)
            updater._RECENT_CACHE["at"] = 0.0
            self.assertEqual(updater.fetch_recent_releases(), first)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["If-None-Match"], 'W/"abc"')

    def test_a_network_failure_is_an_update_error_naming_github(self):
        with mock.patch("requests.get", side_effect=OSError("timed out")):
            with self.assertRaises(updater.UpdateError) as cm:
                updater.fetch_recent_releases()
        self.assertIn("Could not reach GitHub", str(cm.exception))

    def test_a_failure_does_not_hide_a_list_already_known(self):
        with mock.patch("requests.get", lambda *a, **k: _Resp([release("v2.6.0")])):
            known = updater.fetch_recent_releases()
        updater._RECENT_CACHE["at"] = 0.0
        with mock.patch("requests.get", side_effect=OSError("offline")):
            self.assertEqual(updater.fetch_recent_releases(), known)

    def test_http_errors_and_odd_bodies_are_update_errors(self):
        for resp in (_Resp(None, status=500), _Resp({"message": "no"}),
                     _Resp(None), _Resp(ValueError("not json"))):
            _fresh()
            with self.subTest(status=resp.status_code):
                with mock.patch("requests.get", lambda *a, r=resp, **k: r):
                    with self.assertRaises(updater.UpdateError):
                        updater.fetch_recent_releases()

    def test_a_rate_limit_is_shared_with_the_latest_release_lookup(self):
        limited = _Resp(None, status=403, headers={"X-RateLimit-Remaining": "0"})
        with mock.patch("requests.get", lambda *a, **k: limited):
            with self.assertRaises(updater.UpdateError):
                updater.fetch_recent_releases()
        self.assertGreater(updater._RELEASE_CACHE["blocked_until"], 0)
        asked = []
        with mock.patch("requests.get", lambda *a, **k: asked.append(1)):
            with self.assertRaises(updater.UpdateError):
                updater.fetch_recent_releases()
            with self.assertRaises(updater.UpdateError):
                updater.fetch_latest_release()
        self.assertEqual(asked, [], "no request is spent while limited")


class StatusEndpointChangesTests(unittest.TestCase):
    CHANGES = {"changes": [
        {"version": "2.9.0", "title": "New", "notes": "- b", "url": "u9"},
        {"version": "2.6.0", "title": "Older", "notes": "- a", "url": "u6"}],
        "more": True}

    def setUp(self):
        from server import app
        _fresh()
        self.addCleanup(_fresh)
        self.client = app.test_client()
        patcher = mock.patch.object(updater, "remote_branch_state", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def status(self, install, tag="v2.9.0", latest=None, since=None):
        latest = latest if latest is not None else {
            "tag": "v2.9.0", "version": "2.9.0", "notes": "n",
            "url": "https://github.com/o/r/releases/tag/v2.9.0", "assets": {}}
        since = since if since is not None else mock.Mock(
            return_value={"changes": [], "more": False})
        kw = ({"side_effect": latest} if isinstance(latest, Exception)
              else {"return_value": latest})
        with mock.patch.object(updater, "detect_install", return_value=install), \
             mock.patch.object(updater, "remote_release_tag", return_value=tag), \
             mock.patch.object(updater, "fetch_latest_release", **kw), \
             mock.patch.object(updater, "releases_since", since):
            out = json.loads(self.client.get("/api/update/status").data)
        return out, since

    def test_a_git_install_gets_the_changes_and_keeps_its_notes(self):
        out, since = self.status(GIT_INSTALL, since=mock.Mock(return_value=self.CHANGES))
        self.assertEqual(out["latest"]["changes"], self.CHANGES["changes"])
        self.assertTrue(out["latest"]["changesTruncated"])
        self.assertEqual(out["latest"]["notes"], "n", "latest.notes still works")
        self.assertEqual(out["latestSource"], "git")
        self.assertNotIn("changesError", out)
        args, kwargs = since.call_args
        self.assertEqual(args, ("2.5.0",), "asked relative to the installed version")
        self.assertEqual(kwargs["timeout"], updater.NOTES_TIMEOUT)

    def test_a_zip_install_gets_them_too(self):
        out, since = self.status(ZIP_INSTALL, tag=None,
                                 since=mock.Mock(return_value=self.CHANGES))
        self.assertEqual(out["latestSource"], "api")
        self.assertEqual(len(out["latest"]["changes"]), 2)
        self.assertEqual(since.call_args.kwargs["timeout"], updater.NOTES_TIMEOUT)

    def test_a_failure_stays_quiet(self):
        boom = mock.Mock(side_effect=updater.UpdateError("Could not reach GitHub: timed out"))
        out, _ = self.status(GIT_INSTALL, since=boom)
        self.assertTrue(out["updateAvailable"])
        self.assertEqual(out["latest"]["version"], "2.9.0")
        self.assertEqual(out["latest"]["notes"], "n")
        self.assertNotIn("changes", out["latest"])
        self.assertIn("timed out", out["changesError"])

    def test_even_an_unexpected_error_cannot_fail_the_check(self):
        boom = mock.Mock(side_effect=RuntimeError("surprise"))
        for install, tag in ((GIT_INSTALL, "v2.9.0"), (ZIP_INSTALL, None)):
            with self.subTest(method=install["method"]):
                resp, _ = self.status(install, tag=tag, since=boom)
                self.assertTrue(resp["updateAvailable"])
                self.assertIn("changesError", resp)

    def test_a_blocked_api_is_not_asked_twice(self):
        """The notes lookup already showed the API unreachable; the list would
        be a second wait for the same answer."""
        out, since = self.status(GIT_INSTALL,
                                 latest=updater.UpdateError("Could not reach GitHub"),
                                 since=mock.Mock(return_value=self.CHANGES))
        self.assertTrue(out["updateAvailable"], "git still decides")
        self.assertIn("notesError", out)
        self.assertNotIn("changes", out["latest"])
        since.assert_not_called()

    def test_nothing_is_asked_when_there_is_nothing_newer(self):
        out, since = self.status(dict(GIT_INSTALL, currentVersion="2.9.0"))
        self.assertFalse(out["updateAvailable"])
        since.assert_not_called()
        out, since = self.status(dict(ZIP_INSTALL, currentVersion="2.9.0"), tag=None)
        self.assertFalse(out["updateAvailable"])
        since.assert_not_called()

    def test_a_real_lookup_against_a_blocked_api_leaves_the_check_whole(self):
        """No stand-in for the new function: the real one, with requests
        failing the way a blocking proxy makes it fail."""
        with mock.patch.object(updater, "detect_install", return_value=GIT_INSTALL), \
             mock.patch.object(updater, "remote_release_tag", return_value="v2.9.0"), \
             mock.patch("requests.get", side_effect=OSError("blocked")):
            out = json.loads(self.client.get("/api/update/status").data)
        self.assertTrue(out["updateAvailable"])
        self.assertEqual(out["latest"]["version"], "2.9.0")
        self.assertIn("notesError", out)
        self.assertNotIn("changes", out["latest"])

    def test_the_real_lookup_end_to_end(self):
        raw = [release("v2.9.0", title="Newest"), release("v2.7.0", title="Middle"),
               release("v2.5.0", title="Installed")]

        def fake_get(url, headers=None, params=None, timeout=None):
            if url.endswith("/releases/latest"):
                return _Resp(raw[0])
            return _Resp(raw)

        with mock.patch.object(updater, "detect_install", return_value=GIT_INSTALL), \
             mock.patch.object(updater, "remote_release_tag", return_value="v2.9.0"), \
             mock.patch("requests.get", fake_get):
            out = json.loads(self.client.get("/api/update/status").data)
        self.assertEqual([c["version"] for c in out["latest"]["changes"]], ["2.9.0", "2.7.0"])
        self.assertEqual(out["latest"]["changes"][1]["title"], "Middle")
        self.assertFalse(out["latest"]["changesTruncated"])


class TheServerAgreesWithTheSharedChangelogCodeTests(unittest.TestCase):
    """The panel draws what the server sends with `release-changelog.js`, which
    is the same file in every product and has its own parser for GitHub's list.
    Both parsers read the same releases here - the shipped JavaScript, run under
    Node - and have to agree on which releases, in what order, with which title,
    notes and link - including where the notes end and what counts as a title."""

    SHARED_JS = ROOT / "web" / "assets" / "js" / "release-changelog.js"

    def js_parse(self, raw, current):
        program = (
            "const fs=require('fs'),vm=require('vm');"
            "const s={document:{}};s.window=s;vm.createContext(s);"
            "vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),s);"
            "const raw=JSON.parse(process.argv[2]);"
            "const out=s.ReleaseChangelog.newerThan(s.ReleaseChangelog.parseApiList(raw),process.argv[3]);"
            "process.stdout.write(JSON.stringify(out));")
        r = subprocess.run(["node", "-e", program, str(self.SHARED_JS),
                            json.dumps(raw), current],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node is not installed here")
    def test_same_releases_same_order_same_fields(self):
        plain = "\n".join([
            "# {t}", "", "Suite **{v}**.", "", "## What changed", "",
            "### Example Tool", "", "- **A thing** now does `x`.", "- Another.",
            "", "## Files changed", "", "- `f.py`", ""])
        raw = [release("v2.4.0"), release("v2.7.0", body=plain.format(t="Seven", v="2.7.0")),
               release("v2.10.0", body=plain.format(t="Ten", v="2.10.0")),
               release("v2.8.0", draft=True), release("v2.9.0", prerelease=True),
               release("v2.6.0", body="No heading, one line."),
               release("v2.11.0", body="\n\n# Padded\n\n- a\n\n## Verification\n- v\n"),
               release("v2.12.0", body="Intro\n\n# Later heading\n- a\n### Verified\n- kept\n"),
               release("v2.13.0", body="# Win\r\n\r\n- a\r\n\r\n## VERIFIED\r\n- v\r\n"),
               release("v2.14.0", body="# T\n- a\n## Verifiedly\n- kept\n"),
               release("v2.15.0", body="# Only a title\n## Verified\n- v\n"),
               release("v2.5.0", body=plain.format(t="Installed", v="2.5.0"))]
        with mock.patch.object(updater, "fetch_recent_releases", return_value=raw):
            ours = updater.releases_since("2.5.0")["changes"]
        theirs = self.js_parse(raw, "2.5.0")
        self.assertEqual([c["version"] for c in ours], ["2.15.0", "2.14.0", "2.13.0", "2.12.0", "2.11.0", "2.10.0", "2.7.0", "2.6.0"])
        self.assertEqual(ours, theirs)

    def test_the_shared_files_ship_beside_the_page_script(self):
        self.assertTrue(self.SHARED_JS.is_file())
        self.assertTrue(self.SHARED_JS.with_suffix(".css").is_file())


if __name__ == "__main__":
    unittest.main()
