"""The last of item 12: Cloud Manager's stored state and two entry points.

Backlog item 12. What is left after the geometry, the helpers and the decision
functions:

* `load_config` / `save_config` - the output directory, which has two stores
  and a precedence between them. Getting that wrong is the two-store drift
  `CLAUDE.md` has a whole section about: a page that displays a value which is
  not in force and saves to a file nothing reads.
* `save_external_overrides` - the store behind the External badge.
* `build_projects_data` - the whole listing, assembled from two API calls.
* `try_browser_cookies` / `try_saved_cookies` - how a session is found.
* `pick_folder_dialog` - the folder picker.
* `esx_trimmer.api_trim_to` - PlanTrim's server entry point, and the second of
  the two functions a browser could reach that nothing had run.

**Nothing here touches a real browser, a real cookie jar, a real account or a
real dialog.** `browser_cookie3` is replaced with a fake, `subprocess.run` is
stubbed, and every path is redirected at a temp directory. A test that read the
signed-in user's cookie jar to see what shape it is would be the exact mistake
rule zero exists to prevent.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import cloud_manager as CM
from tools import esx_trimmer as T


# ======================================================================
class ConfigHasTwoStoresAndAPrecedenceTests(unittest.TestCase):
    """`settings.json` wins where it exists; `config.json` is the old one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-cmcfg-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, value in (("CONFIG_DIR", self.tmp),
                            ("CONFIG_FILE", self.tmp / "config.json"),
                            ("EXTERNAL_OVERRIDE_FILE",
                             self.tmp / "external_overrides.json")):
            patcher = mock.patch.object(CM, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.unified = self.tmp / "settings.json"

    def write_unified(self, output_dir):
        self.unified.write_text(
            json.dumps({"global": {"output_dir": output_dir}}), encoding="utf-8")

    # -- reading ------------------------------------------------------------

    def test_no_files_at_all_is_an_empty_output_directory(self):
        self.assertEqual({"output_dir": ""}, CM.load_config())

    def test_the_legacy_file_is_read_when_there_is_no_unified_one(self):
        (self.tmp / "config.json").write_text(
            json.dumps({"output_dir": "D:/Ekahau"}), encoding="utf-8")
        self.assertEqual("D:/Ekahau", CM.load_config()["output_dir"])

    def test_the_unified_file_wins_over_the_legacy_one(self):
        """Both existing is the ordinary state after an upgrade - the legacy
        file is left in place as an inert copy. Reading the wrong one would
        silently put the tool back on a directory nobody is using.
        """
        (self.tmp / "config.json").write_text(
            json.dumps({"output_dir": "D:/Old"}), encoding="utf-8")
        self.write_unified("E:/Current")
        self.assertEqual("E:/Current", CM.load_config()["output_dir"])

    def test_a_corrupt_legacy_file_does_not_take_the_page_down(self):
        (self.tmp / "config.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual({"output_dir": ""}, CM.load_config())

    # -- writing ------------------------------------------------------------

    def test_saving_with_no_unified_file_writes_the_legacy_one(self):
        CM.save_config({"output_dir": "F:/Surveys"})
        self.assertFalse(self.unified.exists())
        saved = json.loads((self.tmp / "config.json").read_text(encoding="utf-8"))
        self.assertEqual("F:/Surveys", saved["output_dir"])

    def test_saving_with_a_unified_file_writes_that_one_instead(self):
        """The two-store bug, pinned. Writing to the file that is not being
        read is a save that reports success and changes nothing."""
        self.write_unified("E:/Current")
        CM.save_config({"output_dir": "G:/Moved"})
        self.assertEqual("G:/Moved", CM.load_config()["output_dir"])
        self.assertFalse((self.tmp / "config.json").exists(),
                         "the legacy file was written while a unified one "
                         "existed")

    def test_what_is_saved_is_what_comes_back(self):
        for path in ("H:/One", "", "I:/Two Words/Deep"):
            with self.subTest(path=path):
                CM.save_config({"output_dir": path})
                self.assertEqual(path, CM.load_config()["output_dir"])

    def test_the_directory_is_created_if_it_is_not_there(self):
        nested = self.tmp / "does" / "not" / "exist"
        with mock.patch.object(CM, "CONFIG_DIR", nested), \
                mock.patch.object(CM, "CONFIG_FILE", nested / "config.json"):
            CM.save_config({"output_dir": "J:/x"})
            self.assertTrue((nested / "config.json").is_file())

    # -- the External override store ----------------------------------------

    def test_an_override_survives_a_round_trip(self):
        CM.save_external_overrides([{"key": "abc", "value": "external"},
                                    {"key": "def", "value": "mine"}])
        self.assertEqual({"abc": "external", "def": "mine"},
                         CM.external_overrides_map())

    def test_saving_replaces_rather_than_appends(self):
        """Marking a project back as yours has to be able to remove the entry,
        not add a second one the map then picks between."""
        CM.save_external_overrides([{"key": "abc", "value": "external"}])
        CM.save_external_overrides([{"key": "abc", "value": "mine"}])
        self.assertEqual({"abc": "mine"}, CM.external_overrides_map())

    def test_saving_none_clears_the_store(self):
        CM.save_external_overrides([{"key": "abc", "value": "external"}])
        CM.save_external_overrides([])
        self.assertEqual({}, CM.external_overrides_map())

    def test_the_file_it_writes_is_readable_json_with_an_entries_key(self):
        CM.save_external_overrides([{"key": "k", "value": "external"}])
        doc = json.loads(
            (self.tmp / "external_overrides.json").read_text(encoding="utf-8"))
        self.assertEqual([{"key": "k", "value": "external"}], doc["entries"])


# ======================================================================
class _FakeJar(list):
    """A cookie jar is iterable and that is all this code asks of it."""


class _Cookie:
    """Not a `Mock`.

    `Mock(name=...)` sets the mock's own repr rather than an attribute, so a
    cookie built that way has no readable `.name` and the code under test sees
    every cookie as unnamed. A four-line class is clearer than the keyword that
    works around it.
    """

    def __init__(self, name, value, domain=".ekahau.cloud", path="/"):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path


def _cookie(name, value, domain=".ekahau.cloud", path="/"):
    return _Cookie(name, value, domain, path)


class FindingASessionTests(unittest.TestCase):
    """How Cloud Manager comes to have a session, with nothing real involved.

    `browser_cookie3` is replaced outright. Reading the real jar to "see what
    shape it is" would put the signed-in user's session token in reach of a
    test run, which is not a thing to do on any machine.
    """

    def jar(self, *, access=True, csrf="csrf-token-value"):
        jar = _FakeJar()
        if access:
            jar.append(_cookie("AccessToken", "an-invented-token"))
        if csrf:
            jar.append(_cookie("CSRF-Token", csrf))
        return jar

    def fake_bc3(self, jar=None, raises=()):
        mod = mock.Mock()
        for browser in ("chrome", "firefox", "edge", "opera"):
            if browser in raises:
                getattr(mod, browser).side_effect = RuntimeError("deliberate failure for the test")
            else:
                getattr(mod, browser).return_value = jar if jar is not None \
                    else _FakeJar()
        return mod

    # -- browser cookies ----------------------------------------------------

    def test_no_browser_cookie_library_means_no_session(self):
        with mock.patch.object(CM, "browser_cookie3", None):
            self.assertIsNone(CM.try_browser_cookies())

    def test_a_jar_with_no_access_token_is_not_a_session(self):
        with mock.patch.object(CM, "browser_cookie3",
                               self.fake_bc3(self.jar(access=False))):
            self.assertIsNone(CM.try_browser_cookies())

    def test_a_jar_with_no_csrf_token_is_not_a_session(self):
        with mock.patch.object(CM, "browser_cookie3",
                               self.fake_bc3(self.jar(csrf=""))):
            self.assertIsNone(CM.try_browser_cookies())

    def test_a_browser_that_raises_does_not_stop_the_others_being_tried(self):
        """A locked profile is ordinary - Chrome holds its cookie database
        open. Giving up on the first exception would mean Firefox users never
        got a session."""
        mod = self.fake_bc3(raises=("chrome",))
        mod.firefox.return_value = self.jar()
        api = mock.Mock()
        api.test_connection.return_value = True
        with mock.patch.object(CM, "browser_cookie3", mod), \
                mock.patch.object(CM, "EkahauAPI", return_value=api), \
                mock.patch.object(CM, "save_cookies_to_disk") as saved:
            self.assertIs(api, CM.try_browser_cookies())
        self.assertTrue(mod.firefox.called)
        self.assertTrue(saved.called)

    def test_a_working_session_is_written_to_disk_for_next_time(self):
        api = mock.Mock()
        api.test_connection.return_value = True
        with mock.patch.object(CM, "browser_cookie3",
                               self.fake_bc3(self.jar())), \
                mock.patch.object(CM, "EkahauAPI", return_value=api), \
                mock.patch.object(CM, "save_cookies_to_disk") as saved:
            CM.try_browser_cookies()
        cookies, csrf = saved.call_args[0]
        self.assertEqual("csrf-token-value", csrf)
        self.assertIn("AccessToken", [c["name"] for c in cookies])

    def test_cookies_that_do_not_work_are_not_saved(self):
        """Writing a dead session to disk means the next start tries it first
        and fails before it reaches the browser."""
        api = mock.Mock()
        api.test_connection.return_value = False
        with mock.patch.object(CM, "browser_cookie3",
                               self.fake_bc3(self.jar())), \
                mock.patch.object(CM, "EkahauAPI", return_value=api), \
                mock.patch.object(CM, "save_cookies_to_disk") as saved:
            self.assertIsNone(CM.try_browser_cookies())
        self.assertFalse(saved.called)

    def test_only_the_ekahau_domain_is_asked_for(self):
        """Every other cookie on the machine is none of this tool's business."""
        mod = self.fake_bc3(self.jar())
        api = mock.Mock()
        api.test_connection.return_value = True
        with mock.patch.object(CM, "browser_cookie3", mod), \
                mock.patch.object(CM, "EkahauAPI", return_value=api), \
                mock.patch.object(CM, "save_cookies_to_disk"):
            CM.try_browser_cookies()
        self.assertEqual({"domain_name": ".ekahau.cloud"},
                         mod.chrome.call_args.kwargs)

    # -- saved cookies ------------------------------------------------------

    def test_nothing_saved_is_no_session(self):
        for saved in ((None, None), ([], "csrf"), (["c"], "")):
            with self.subTest(saved=saved):
                with mock.patch.object(CM, "load_cookies_from_disk",
                                       return_value=saved):
                    self.assertIsNone(CM.try_saved_cookies())

    def test_saved_cookies_that_still_work_are_a_session(self):
        api = mock.Mock()
        api.test_connection.return_value = True
        with mock.patch.object(CM, "load_cookies_from_disk",
                               return_value=([{"name": "AccessToken"}], "csrf")), \
                mock.patch.object(CM, "EkahauAPI", return_value=api):
            self.assertIs(api, CM.try_saved_cookies())

    def test_saved_cookies_that_have_expired_are_not_a_session(self):
        api = mock.Mock()
        api.test_connection.return_value = False
        with mock.patch.object(CM, "load_cookies_from_disk",
                               return_value=([{"name": "AccessToken"}], "csrf")), \
                mock.patch.object(CM, "EkahauAPI", return_value=api):
            self.assertIsNone(CM.try_saved_cookies())


# ======================================================================
class PickFolderDialogTests(unittest.TestCase):
    """The folder picker, without opening one.

    It runs a child interpreter so a Tk main loop never touches the server
    process. `subprocess.run` is stubbed throughout - a test that actually
    opened a dialog would hang a headless CI job until its timeout.
    """

    def run_with(self, result=None, **kwargs):
        completed = mock.Mock(stdout=result if result is not None else "")
        with mock.patch.object(CM.subprocess, "run",
                               return_value=completed) as run:
            value = CM.pick_folder_dialog(**kwargs)
        return value, run

    def test_the_chosen_folder_comes_back_stripped(self):
        value, _run = self.run_with("  D:/Ekahau Projects  \n")
        self.assertEqual("D:/Ekahau Projects", value)

    def test_cancelling_gives_an_empty_string(self):
        value, _run = self.run_with("\n")
        self.assertEqual("", value)

    def test_the_initial_directory_is_passed_through_safely(self):
        """It is interpolated into source with `!r`, so a path with a quote or
        a backslash in it has to survive as data rather than become code."""
        tricky = "C:\\Users\\someone\\O'Brien Projects"
        _value, run = self.run_with("", initial=tricky)
        code = run.call_args[0][0][2]
        self.assertIn(repr(tricky), code)
        compile(code, "<picker>", "exec")          # it is still valid Python

    def test_it_runs_a_child_interpreter_rather_than_importing_tk(self):
        _value, run = self.run_with("")
        argv = run.call_args[0][0]
        self.assertEqual(CM.sys.executable, argv[0])
        self.assertEqual("-c", argv[1])
        self.assertIn("askdirectory", argv[2])

    def test_it_is_bounded_rather_than_waiting_forever(self):
        _value, run = self.run_with("")
        self.assertTrue(run.call_args.kwargs.get("timeout"))

    def test_a_failure_is_an_empty_string_rather_than_an_exception(self):
        with mock.patch.object(CM.subprocess, "run",
                               side_effect=OSError("no display")):
            self.assertEqual("", CM.pick_folder_dialog())


# ======================================================================
class BuildProjectsDataTests(unittest.TestCase):
    """The listing, assembled from two API calls that fail independently."""

    def api(self, projects=None, listing=None, listing_raises=False):
        api = mock.Mock()
        api.get_projects.return_value = projects if projects is not None else []
        if listing_raises:
            api.get_dataset_listing.side_effect = RuntimeError("no listing")
        else:
            api.get_dataset_listing.return_value = listing or []
        return api

    def build(self, api, output_dir="D:/Projects"):
        with mock.patch.object(CM, "get_local_esx_files", return_value=[]), \
                mock.patch.object(CM, "manual_matches_map",
                                  return_value=({}, [])), \
                mock.patch.object(CM, "not_matches_set", return_value=set()), \
                mock.patch.object(CM.sync_state, "prune"):
            return CM.build_projects_data(api, output_dir)

    def cloud_rows(self, result):
        rows = []
        for key in ("matched", "cloudOnly"):
            for item in result.get(key) or []:
                rows.append(item.get("cloud", item))
        return rows

    PROJECT = {"id": "p-1", "name": "ACME1 Example Campus",
               "statistics": {"size": 6_500_000},
               "history": {"createdBy": "Someone@example.com",
                           "modifiedBy": "Other@example.org"}}

    def test_a_project_becomes_a_row(self):
        result = self.build(self.api(projects=[self.PROJECT]))
        row = self.cloud_rows(result)[0]
        self.assertEqual("p-1", row["id"])
        self.assertEqual("ACME1 Example Campus", row["name"])
        self.assertEqual(6_500_000, row["size"])

    def test_the_site_code_is_taken_off_the_name(self):
        row = self.cloud_rows(self.build(self.api(projects=[self.PROJECT])))[0]
        self.assertEqual("ACME1", row["code"])

    def test_a_project_with_no_name_is_untitled_rather_than_blank(self):
        row = self.cloud_rows(self.build(self.api(projects=[{"id": "p-2"}])))[0]
        self.assertEqual("Untitled", row["name"])

    def test_usernames_are_lower_cased_so_two_spellings_are_one_person(self):
        row = self.cloud_rows(self.build(self.api(projects=[self.PROJECT])))[0]
        self.assertEqual("someone@example.com", row["createdBy"])
        self.assertEqual("other@example.org", row["modifiedBy"])

    def test_the_site_and_sharing_come_off_the_dataset_listing(self):
        listing = [{"id": "p-1", "siteName": "Example Campus",
                    "type": "GREENFIELD_PLAN",
                    "datasetUsers": [
                        {"role": "OWNER", "username": "Owner@example.com"},
                        {"role": "EDITOR", "username": "Editor@example.org"},
                    ]}]
        row = self.cloud_rows(
            self.build(self.api(projects=[self.PROJECT], listing=listing)))[0]
        self.assertEqual("Example Campus", row["siteName"])
        self.assertTrue(row["hasSite"])
        self.assertEqual("owner@example.com", row["owner"])
        self.assertEqual(["editor@example.org"], row["sharedWith"])

    def test_the_owner_is_not_listed_as_somebody_it_is_shared_with(self):
        listing = [{"id": "p-1", "siteName": "S", "datasetUsers": [
            {"role": "OWNER", "username": "owner@example.com"}]}]
        row = self.cloud_rows(
            self.build(self.api(projects=[self.PROJECT], listing=listing)))[0]
        self.assertEqual([], row["sharedWith"])

    def test_a_listing_that_fails_still_produces_the_projects(self):
        """Two calls, and the listing is the optional one. Losing the site
        name is a worse row; losing the whole page is a broken tool."""
        result = self.build(
            self.api(projects=[self.PROJECT], listing_raises=True))
        rows = self.cloud_rows(result)
        self.assertEqual(1, len(rows))
        self.assertEqual("", rows[0]["siteName"])
        self.assertFalse(rows[0]["hasSite"])

    def test_the_owner_falls_back_to_who_created_it(self):
        row = self.cloud_rows(self.build(self.api(projects=[self.PROJECT])))[0]
        self.assertEqual("someone@example.com", row["owner"])

    def test_sync_points_are_pruned_against_the_whole_account(self):
        """Safe here and nowhere obvious else: this listing is every project
        the signed-in user can see. Pruning against a filtered list would
        throw away good records for projects that still exist.
        """
        with mock.patch.object(CM, "get_local_esx_files", return_value=[]), \
                mock.patch.object(CM, "manual_matches_map",
                                  return_value=({}, [])), \
                mock.patch.object(CM, "not_matches_set", return_value=set()), \
                mock.patch.object(CM.sync_state, "prune") as prune:
            CM.build_projects_data(self.api(projects=[self.PROJECT]), "D:/x")
        prune.assert_called_once_with(["p-1"])

    def test_a_failure_to_prune_does_not_break_the_listing(self):
        with mock.patch.object(CM, "get_local_esx_files", return_value=[]), \
                mock.patch.object(CM, "manual_matches_map",
                                  return_value=({}, [])), \
                mock.patch.object(CM, "not_matches_set", return_value=set()), \
                mock.patch.object(CM.sync_state, "prune",
                                  side_effect=OSError("deliberate failure for the test")):
            result = CM.build_projects_data(
                self.api(projects=[self.PROJECT]), "D:/x")
        self.assertEqual(1, len(self.cloud_rows(result)))


# ======================================================================
class ApiTrimToTests(unittest.TestCase):
    """PlanTrim's server entry point - the wrapper the browser reaches.

    Its whole job is to turn an exception into a JSON answer, because a
    traceback reaching the page reads as a fault in the tool. So the cases are
    the three exits: it worked, it was refused for a reason, and something
    unexpected happened.
    """

    def test_a_successful_trim_is_reported_as_a_result(self):
        report = {"floors": [], "skipped": []}
        with mock.patch.object(T, "trim", return_value=report) as trim, \
                mock.patch.object(T, "_report_json",
                                  return_value={"ok": True, "trimmed": 2}):
            result = T.api_trim_to("in.esx", "out.esx", margin="normal")
        self.assertEqual({"ok": True, "trimmed": 2}, result)
        self.assertEqual(Path("in.esx"), trim.call_args[0][0])
        self.assertEqual(Path("out.esx"), trim.call_args[0][1])
        self.assertEqual("normal", trim.call_args.kwargs["margin"])

    def test_the_destination_is_passed_to_the_report(self):
        with mock.patch.object(T, "trim", return_value={}), \
                mock.patch.object(T, "_report_json",
                                  return_value={"ok": True}) as rj:
            T.api_trim_to("in.esx", "D:/out/plan.esx")
        self.assertEqual(Path("D:/out/plan.esx"), rj.call_args.kwargs["dest"])

    def test_drawn_boxes_are_handed_through(self):
        boxes = {"floor-1": [10, 10, 200, 150]}
        with mock.patch.object(T, "trim", return_value={}) as trim, \
                mock.patch.object(T, "_report_json", return_value={"ok": True}):
            T.api_trim_to("in.esx", "out.esx", boxes=boxes)
        self.assertEqual(boxes, trim.call_args.kwargs["boxes"])

    def test_a_refusal_comes_back_as_its_own_wording(self):
        """A `TrimError` is something the tool decided, so its message is
        written for the person reading it and is passed through unchanged."""
        with mock.patch.object(T, "trim",
                               side_effect=T.TrimError("the crop has no area")):
            result = T.api_trim_to("in.esx", "out.esx")
        self.assertEqual({"ok": False, "error": "the crop has no area"}, result)

    def test_an_unexpected_failure_is_named_rather_than_raised(self):
        """A raw traceback in the console is the failure this wrapper exists
        to prevent, and an error with no type in it is hard to act on."""
        with mock.patch.object(T, "trim", side_effect=OSError("file is open")):
            result = T.api_trim_to("in.esx", "out.esx")
        self.assertFalse(result["ok"])
        self.assertIn("OSError", result["error"])
        self.assertIn("file is open", result["error"])

    def test_it_never_raises(self):
        for boom in (TypeError("bad argument"), MemoryError(),
                     T.TrimError("refused")):
            with self.subTest(exception=type(boom).__name__):
                with mock.patch.object(T, "trim", side_effect=boom):
                    result = T.api_trim_to("in.esx", "out.esx")
                self.assertIn("ok", result)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
