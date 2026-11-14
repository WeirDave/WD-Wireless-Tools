"""Cloud Manager: what a signed request, a settings change and a typo can reach.

Each section is one fault found by running the real function:

* **A presigned address is a credential.** `requests` puts the whole URL into an
  exception's text, and for a presigned S3 address the query string is the
  signature. It reached the toast and the log file.
* **The project folder was read once, at import.** Settings, the setup wizard and
  an import write it without telling Cloud Manager, so every containment check
  kept the old folder until restart.
* **A drive root can never be the project folder.** Every local delete is checked
  against it, so it is the boundary.
* **`kind` was compared against "projects" and anything else meant sites**, so a
  typo in a delete meant "delete a site".
* **The upload went out on the signed-in session**, carrying the CSRF token and
  Referer to the storage host, read the whole file into memory first, and
  accepted any scheme.
* **A 404 from the cloud arrived as raw "404 Client Error ... for url ...".**
  `api.get` raises on an error status, so the status branches below it never ran.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import cloud_manager as cm
from tools import settings as suite_settings


def _response(status, url=None):
    r = requests.Response()
    r.status_code = status
    r.reason = {401: "Unauthorized", 404: "Not Found"}.get(status, "Error")
    r.url = url or cm.EKAHAU_URL + "/x"
    r._content = b"{}"
    return r


class PresignedAddressesStayOutOfMessagesTests(unittest.TestCase):

    SIGNED = ("https://bucket.s3.amazonaws.com/a/b.esx?X-Amz-Signature=abc123"
              "&X-Amz-Credential=zzz&X-Amz-Date=20260101")

    def test_the_query_string_is_removed_and_the_address_kept(self):
        text = f"403 Client Error: Forbidden for url: {self.SIGNED} (retrying)"
        out = cm.redact_urls(text)
        self.assertNotIn("abc123", out)
        self.assertNotIn("X-Amz", out)
        self.assertIn("https://bucket.s3.amazonaws.com/a/b.esx", out)
        self.assertIn("(retrying)", out)

    def test_text_without_a_query_is_untouched(self):
        s = "Could not reach https://www.ekahau.cloud/site-management-api/v1/sites now"
        self.assertEqual(s, cm.redact_urls(s))

    def test_a_failed_download_names_no_signature(self):
        m = cm.CloudManager.__new__(cm.CloudManager)
        m.config = {"output_dir": ""}
        m.api = cm.EkahauAPI([], "csrf")
        err = requests.exceptions.HTTPError("403 for url: " + self.SIGNED)
        self.assertNotIn("abc123", m._handle_api_error(err))

    def test_a_retry_that_is_logged_names_no_signature(self):
        m = cm.CloudManager.__new__(cm.CloudManager)
        calls = {"n": 0}

        def always_refused():
            calls["n"] += 1
            raise requests.exceptions.HTTPError("403 for url: " + self.SIGNED)

        with mock.patch.object(m, "_LISTING_BACKOFF_S", (0, 0)), \
                self.assertLogs(level="INFO") as logged:
            with self.assertRaises(requests.exceptions.HTTPError):
                m._with_patience(always_refused, "a step")
        joined = "\n".join(logged.output)
        self.assertEqual(2, calls["n"])
        self.assertNotIn("abc123", joined)


class TheProjectFolderIsLiveAndSaneTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-cm-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.user = self.tmp / "user"
        self.user.mkdir()
        self.settings = self.user / "settings.json"
        # Cloud Manager reads settings.json when it exists and a legacy file
        # when it does not; give it the real one from the start.
        self.settings.write_text("{}", encoding="utf-8")
        patches = [mock.patch.object(cm, "CONFIG_DIR", self.user),
                   mock.patch.object(suite_settings, "SETTINGS_FILE", self.settings)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _write_folder(self, folder):
        self.settings.write_text(json.dumps(
            {"global": {"output_dir": str(folder)}}), encoding="utf-8")

    def test_a_folder_changed_in_settings_is_the_folder_cloud_manager_uses(self):
        one, two = self.tmp / "one", self.tmp / "two"
        one.mkdir()
        two.mkdir()
        m = cm.CloudManager()
        self._write_folder(one)
        self.assertEqual(str(one), m.config["output_dir"])
        # Another part of the app writes the setting; nothing tells `m`.
        self._write_folder(two)
        self.assertEqual(str(two), m.config["output_dir"],
                         "Cloud Manager kept the folder it read at start")

    def test_assigning_a_config_still_pins_it_for_a_test(self):
        m = cm.CloudManager()
        m.config = {"output_dir": "pinned"}
        self._write_folder(self.tmp)
        self.assertEqual("pinned", m.config["output_dir"])

    def test_set_folder_saves_where_settings_reads_it_back(self):
        target = self.tmp / "projects"
        target.mkdir()
        m = cm.CloudManager()
        out = m.set_folder(str(target))
        self.assertEqual(str(target.resolve()), out["path"])
        self.assertEqual(str(target.resolve()), m.config["output_dir"])

    def test_a_drive_root_is_refused(self):
        root = Path(self.tmp.anchor or "/")
        m = cm.CloudManager()
        out = m.set_folder(str(root))
        self.assertIn("error", out)
        # The reason is asserted, not just a refusal: the user directory sits
        # inside a drive root too, so another rule would refuse it anyway and a
        # bare truthiness check could not tell the drive-root rule had gone.
        self.assertIn("top of a drive", cm.unsafe_project_folder(root))

    def test_the_home_folder_is_refused(self):
        self.assertIn("home folder", cm.unsafe_project_folder(Path.home()))

    def test_a_folder_that_holds_the_user_data_directory_is_refused(self):
        self.assertIn("own settings", cm.unsafe_project_folder(self.tmp),
                      "the user directory sits inside it")

    def test_an_ordinary_folder_is_accepted(self):
        ordinary = self.tmp / "user" / "projects-here"
        ordinary.mkdir()
        self.assertIsNone(cm.unsafe_project_folder(ordinary))

    def test_the_settings_route_refuses_the_same_folders(self):
        import server
        with self.assertRaises(ValueError):
            server._checked_patch({"global": {"output_dir": str(Path.home())}})
        ok = {"global": {"output_dir": str(self.tmp / "user" / "fine")}}
        self.assertIs(ok, server._checked_patch(ok))
        self.assertEqual({}, server._checked_patch({}))


class KindMustBeNamedTests(unittest.TestCase):

    def _manager(self):
        m = cm.CloudManager.__new__(cm.CloudManager)
        m.config = {"output_dir": ""}
        m.api = mock.Mock()
        return m

    def test_a_typo_in_a_delete_deletes_nothing(self):
        m = self._manager()
        for kind in ("project", "site", "", None, "Sites", "projects "):
            out = m.delete_cloud(kind, "abc")
            self.assertIn("error", out, kind)
        m.api.delete_project.assert_not_called()
        m.api.delete_sites.assert_not_called()

    def test_rename_and_get_data_are_checked_too(self):
        m = self._manager()
        self.assertIn("error", m.rename_cloud("proj", "abc", "x"))
        self.assertIn("error", m.get_data("nonsense"))
        m.api.rename_project.assert_not_called()
        m.api.rename_site.assert_not_called()

    def test_the_two_real_kinds_still_reach_the_api(self):
        m = self._manager()
        m.delete_cloud("projects", "p1")
        m.delete_cloud("sites", "s1")
        m.api.delete_project.assert_called_once_with("p1")
        m.api.delete_sites.assert_called_once_with(["s1"])


class AnUploadStaysOffTheSessionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-up-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.esx = self.tmp / "p.esx"
        with zipfile.ZipFile(self.esx, "w") as z:
            z.writestr("project.json", json.dumps({"project": {"name": "p"}}))

    def _manager(self, upload_url):
        m = cm.CloudManager.__new__(cm.CloudManager)
        m.config = {"output_dir": str(self.tmp)}
        m.api = mock.Mock()

        class Init:
            def json(self_inner):
                return {"url": upload_url, "fileUploadId": "u1"}

        m.api._write = mock.Mock(return_value=Init())
        return m

    def test_a_plain_http_address_is_refused_before_anything_is_sent(self):
        m = self._manager("http://storage.invalid/put?sig=1")
        with mock.patch.object(requests, "put") as put:
            out = m.api and cm.EkahauAPI.upload_project(
                self._api_for(m), str(self.esx))
        self.assertIn("error", out)
        put.assert_not_called()

    def _api_for(self, m):
        api = cm.EkahauAPI([], "csrf")
        api._write = m.api._write
        return api

    def test_the_put_is_a_bare_request_that_streams_the_file(self):
        api = cm.EkahauAPI([], "csrf")

        class Init:
            def json(self_inner):
                return {"url": "https://storage.invalid/put?sig=SECRET",
                        "fileUploadId": "u1"}

        class Commit:
            status_code = 200

            def json(self_inner):
                return {"ok": True}

        api._write = mock.Mock(side_effect=[Init(), Commit()])
        api.http.put = mock.Mock(side_effect=AssertionError(
            "the signed-in session was used for the storage upload"))
        sent = {}

        def fake_put(url, data=None, headers=None, timeout=None):
            sent.update(url=url, headers=headers or {},
                        is_file=hasattr(data, "read"))
            r = requests.Response()
            r.status_code = 200
            return r

        with mock.patch.object(requests, "put", fake_put):
            api.upload_project(str(self.esx))
        self.assertTrue(sent["url"].startswith("https://storage.invalid/put"))
        self.assertTrue(sent["is_file"], "the file was read into memory first")
        lowered = {k.lower() for k in sent["headers"]}
        self.assertEqual({"content-type"}, lowered,
                         "session headers went to the storage host")

    def test_a_failed_put_reports_without_the_signature(self):
        api = cm.EkahauAPI([], "csrf")

        class Init:
            def json(self_inner):
                return {"url": "https://storage.invalid/put?sig=SECRET",
                        "fileUploadId": "u1"}

        api._write = mock.Mock(return_value=Init())

        def refused(url, **kw):
            raise requests.exceptions.ConnectionError("refused for url: " + url)

        with mock.patch.object(requests, "put", refused):
            out = api.upload_project(str(self.esx))
        self.assertIn("error", out)
        self.assertNotIn("SECRET", json.dumps(out))


class AMissingCloudProjectIsSaidInWordsTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-vr-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.esx = self.tmp / "p.esx"
        with zipfile.ZipFile(self.esx, "w") as z:
            z.writestr("project.json", json.dumps({"project": {"name": "p"}}))

    def _manager(self, status):
        m = cm.CloudManager.__new__(cm.CloudManager)
        m.config = {"output_dir": str(self.tmp)}
        m.api = cm.EkahauAPI([], "csrf")
        m.api.http.get = mock.Mock(return_value=_response(status))
        return m

    def test_a_404_says_the_project_is_gone(self):
        out = self._manager(404).verify_replace_local("pid", str(self.esx))
        self.assertIn("no longer in Ekahau Cloud", out["error"])
        self.assertNotIn("Client Error", out["error"])

    def test_a_401_says_the_sign_in_expired_and_drops_the_session(self):
        m = self._manager(401)
        out = m.verify_replace_local("pid", str(self.esx))
        self.assertIn("sign-in has expired", out["error"])
        self.assertIsNone(m.api, "the dead session was kept")


class AShareThatSucceededIsNeverReportedAsFailedTests(unittest.TestCase):

    def test_a_damaged_recipients_file_does_not_raise_out_of_the_share(self):
        with mock.patch.object(cm.share_recipients, "remember",
                               side_effect=ValueError("bad count")):
            cm._remember_recipients(["a@example.com"])  # must not raise


class OnlyEkahausCookiesAreReadFromFirefoxTests(unittest.TestCase):
    """The query is `host like '%.ekahau.cloud%'`, so a host that merely
    contains the name matched - and its AccessToken could win."""

    def setUp(self):
        import sqlite3
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-ffc-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = self.tmp / "cookies.sqlite"
        con = sqlite3.connect(str(self.db))
        con.execute("create table moz_cookies (host text, path text, isSecure int, "
                    "expiry int, name text, value text, isHttpOnly int)")
        for host in (".ekahau.cloud", "www.ekahau.cloud",
                     ".ekahau.cloud.example.org", "www.ekahau.cloud.example.org",
                     "notekahau.cloud.example"):
            con.execute("insert into moz_cookies values (?, '/', 1, 0, 'AccessToken', 'v', 1)",
                        (host,))
        con.commit()
        con.close()

    def test_a_lookalike_host_is_not_read(self):
        db = self.db

        class Firefox:
            def __init__(self, domain_name=None):
                self.cookie_file = str(db)

        class Reader:
            pass

        Reader.Firefox = Firefox
        Reader.create_cookie = staticmethod(lambda *row: row[0])
        got = cm._firefox_cookies_including_wal(Reader, ".ekahau.cloud")
        self.assertEqual({".ekahau.cloud", "www.ekahau.cloud"}, set(got))

    def test_the_host_rule_on_its_own(self):
        within = cm._host_is_within
        self.assertTrue(within(".ekahau.cloud", ".ekahau.cloud"))
        self.assertTrue(within("www.ekahau.cloud", ".ekahau.cloud"))
        self.assertFalse(within("ekahau.cloud.example.org", ".ekahau.cloud"))
        self.assertFalse(within("notekahau.cloud", ".ekahau.cloud"))
        self.assertFalse(within("", ".ekahau.cloud"))
        self.assertFalse(within("www.ekahau.cloud", ""))


if __name__ == "__main__":
    unittest.main()
