"""The dev gate was entirely in the browser. Now the writing half is not.

**What it was.** Dev mode is `localStorage['wd_dev'] === '1'`, set by a
SHA-256 password modal. `wd-dev.js` is honest about what that is worth -
*"obfuscation, not security ... anyone with a browser console can set the flag
directly"* - and the hash it checks against is published in two public
repositories, because the same password opens WaxFrame Professional's toolbar.
The server agreed with none of it: `/api/dev/<action>` ran whatever arrived.

**What that was actually worth**, because the size of the hole decides the
size of the fix:

* A local process running as him can already delete a temp directory or kill
  a process without asking this server. A gate changes nothing there.
* Cross-site is already closed by `_protect_local_api` - foreign Host,
  foreign Origin, and no state-changing request without the custom header.
* What is left is **script inside a page this server served**: the crafted
  `.esx` XSS class that v2.146.1 was about. That script is same-origin and
  passes everything above.

So the gate stands in front of the two actions that *write* - the sweep that
deletes and the stop that kills a process - and not in front of the survey,
which is a read that returns counts rather than values and is the whole point
of the toolbar being a five-second answer.

It is **not** claimed to make the API authenticated. `/api/cloud/delete_cloud`
and `/api/update` are not behind it and would be theatre if they were; what
holds for those is that every destructive action re-derives its target
server-side, which is what `sweep` and `stop_processes` do.

Nothing here knows the password. The hash is read from `wd-dev.js` at call
time, so these tests point the reader at a digest of a string they invented -
the same seam `Dev._expectedHash` gives the browser tests, and for the same
reason: the plaintext is in neither repository.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server

INVENTED = "a password this test made up"
INVENTED_HASH = hashlib.sha256(INVENTED.encode("utf-8")).hexdigest()


class DevGateHarness(unittest.TestCase):

    def setUp(self):
        server._dev_relock()
        self.addCleanup(server._dev_relock)
        self.client = server.app.test_client()
        # The reader is patched rather than the file edited: the constant in
        # wd-dev.js is the shipped one and must stay the shipped one.
        self.hash_patch = mock.patch.object(
            server, "_dev_password_hash", return_value=INVENTED_HASH)
        self.hash_patch.start()
        self.addCleanup(self.hash_patch.stop)

    def post(self, action, body=None):
        return self.client.post(
            "/api/dev/" + action,
            data=json.dumps(body or {}),
            content_type="application/json",
            headers={server.API_REQUEST_HEADER: "1"})


class LockedIsTheDefault(DevGateHarness):

    def test_a_fresh_server_is_locked(self):
        """Every run starts locked. An unlock is not persisted anywhere."""
        self.assertFalse(server.dev_is_unlocked())
        self.assertFalse(self.post("state").get_json()["unlocked"])

    def test_the_sweep_is_refused_while_locked(self):
        r = self.post("housekeeping_sweep", {"paths": ["/anything"]})
        self.assertEqual(403, r.status_code)
        self.assertEqual("dev_locked", r.get_json()["code"])

    def test_the_stop_is_refused_while_locked(self):
        r = self.post("housekeeping_stop", {"pids": [4]})
        self.assertEqual(403, r.status_code)
        self.assertEqual("dev_locked", r.get_json()["code"])

    def test_nothing_is_deleted_by_a_refused_sweep(self):
        """A 403 that still ran the action would be the worst of both."""
        with mock.patch.object(server.housekeeping, "sweep") as swept:
            self.post("housekeeping_sweep", {"paths": ["/anything"]})
        swept.assert_not_called()

    def test_nothing_is_killed_by_a_refused_stop(self):
        with mock.patch.object(server.housekeeping, "stop_processes") as stopped:
            self.post("housekeeping_stop", {"pids": [4]})
        stopped.assert_not_called()

    def test_the_refusal_says_how_to_proceed(self):
        """A control that refuses without saying how is a wall, not a guard."""
        body = self.post("housekeeping_sweep", {"paths": []}).get_json()
        self.assertIn("password", body["error"].lower())


class TheReadIsNotBehindIt(DevGateHarness):
    """Charging a password for a read is the guard firing on the normal case.

    The survey is the toolbar's reason to exist - "is there junk everywhere",
    answered in five seconds - and it returns counts, never the values it
    matched on.
    """

    def test_the_survey_runs_while_locked(self):
        self.assertFalse(server.dev_is_unlocked())
        with mock.patch.object(server.housekeeping, "survey",
                               return_value={"ok": True, "groups": []}) as sur:
            r = self.post("housekeeping_survey")
        self.assertEqual(200, r.status_code)
        sur.assert_called_once()


class UnlockingWithThePassword(DevGateHarness):

    def test_the_right_password_unlocks(self):
        r = self.post("unlock", {"password": INVENTED})
        self.assertTrue(r.get_json()["ok"])
        self.assertTrue(server.dev_is_unlocked())

    def test_the_wrong_password_does_not(self):
        r = self.post("unlock", {"password": "not it"})
        self.assertFalse(r.get_json()["ok"])
        self.assertFalse(server.dev_is_unlocked())

    def test_no_password_at_all_does_not(self):
        for body in ({}, {"password": ""}, {"password": None}):
            with self.subTest(body=body):
                server._dev_relock()
                self.assertFalse(self.post("unlock", body).get_json()["ok"])
                self.assertFalse(server.dev_is_unlocked())

    def test_the_hash_is_not_the_password(self):
        """Sending the published digest must not work.

        The hash is readable in `wd-dev.js` in a public repository, so a
        server that accepted it would be accepting something anybody has.
        """
        self.assertFalse(
            self.post("unlock", {"password": INVENTED_HASH}).get_json()["ok"])
        self.assertFalse(server.dev_is_unlocked())

    def test_after_unlocking_the_sweep_runs(self):
        self.post("unlock", {"password": INVENTED})
        with mock.patch.object(
                server.housekeeping, "sweep",
                return_value={"ok": True, "removed": [], "skipped": [],
                              "failed": [], "counts": {}}) as swept:
            r = self.post("housekeeping_sweep", {"paths": ["/x"]})
        self.assertEqual(200, r.status_code)
        swept.assert_called_once()

    def test_after_unlocking_the_stop_runs(self):
        self.post("unlock", {"password": INVENTED})
        with mock.patch.object(
                server.housekeeping, "stop_processes",
                return_value={"ok": True, "stopped": [], "skipped": [],
                              "failed": [], "counts": {}}) as stopped:
            r = self.post("housekeeping_stop", {"pids": [4242]})
        self.assertEqual(200, r.status_code)
        stopped.assert_called_once()

    def test_locking_again_closes_it(self):
        self.post("unlock", {"password": INVENTED})
        self.assertTrue(server.dev_is_unlocked())
        self.post("lock")
        self.assertFalse(server.dev_is_unlocked())
        self.assertEqual(
            403, self.post("housekeeping_sweep", {"paths": []}).status_code)

    def test_the_unlock_expires(self):
        """An unlocked server left running overnight re-locks itself."""
        self.post("unlock", {"password": INVENTED})
        self.assertTrue(server.dev_is_unlocked())
        with mock.patch.object(
                server.time, "time",
                return_value=server._dev_unlocked_until + 1):
            self.assertFalse(server.dev_is_unlocked())


class TheComparisonIsNotNaive(DevGateHarness):

    def test_it_uses_a_constant_time_comparison(self):
        """Timing a `==` on digests leaks how much of one matched.

        Asserted by watching the call rather than by reading the source: a
        comparison that stopped going through `hmac.compare_digest` would
        pass a substring check on the file just as well.
        """
        with mock.patch.object(server.hmac, "compare_digest",
                               wraps=server.hmac.compare_digest) as cd:
            self.post("unlock", {"password": INVENTED})
        cd.assert_called()

    def test_a_wrong_password_costs_time(self):
        """A local script can try thousands a second against a public hash.

        A speed bump, not a lockout - and capped, so it cannot be used to
        hold the server's threads.
        """
        with mock.patch.object(server.time, "sleep") as slept:
            self.post("unlock", {"password": "no"})
            self.post("unlock", {"password": "no"})
        self.assertEqual(2, slept.call_count)
        self.assertTrue(all(0 < c.args[0] <= 2.0 for c in slept.call_args_list),
                        slept.call_args_list)

    def test_a_correct_password_costs_nothing(self):
        with mock.patch.object(server.time, "sleep") as slept:
            self.post("unlock", {"password": INVENTED})
        slept.assert_not_called()

    def test_the_delay_resets_after_a_success(self):
        with mock.patch.object(server.time, "sleep"):
            self.post("unlock", {"password": "no"})
            self.post("unlock", {"password": "no"})
        self.post("unlock", {"password": INVENTED})
        self.assertEqual(0, server._dev_failed_attempts)


class AnUnreadableHashFailsClosed(DevGateHarness):
    """A gate that fails open is not a gate."""

    def test_no_hash_means_locked(self):
        self.hash_patch.stop()
        with mock.patch.object(server, "_dev_password_hash", return_value=None):
            r = self.post("unlock", {"password": INVENTED})
            self.assertFalse(r.get_json()["ok"])
            self.assertFalse(server.dev_is_unlocked())
        self.hash_patch.start()

    def test_the_hash_is_read_from_the_shipped_file(self):
        """One copy, and it stays in the portable file.

        `wd-dev.js` is copied to his other products unchanged and the hash is
        deliberately the same in both. A second copy in `server.py` could
        drift from the one the modal checks, and
        `tests/test_dev_password_hash.py` - which compares this repository's
        copy with WaxFrame's - would not see the drift.
        """
        self.hash_patch.stop()
        try:
            found = server._dev_password_hash()
        finally:
            self.hash_patch.start()
        self.assertIsNotNone(found, "server.py cannot read DEV_PW_HASH")
        self.assertRegex(found, r"^[0-9a-f]{64}$")

        js = (ROOT / "web" / "assets" / "js" / "wd-dev.js").read_text(
            encoding="utf-8")
        self.assertIn(found, js.lower())

        py = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertNotIn(found, py.lower(),
                         "server.py carries its own copy of the hash - it "
                         "must read the one in wd-dev.js instead")


class TheCrossOriginGuardStillCoversAllOfThis(DevGateHarness):
    """The gate is added to the existing protection, not in place of it."""

    def test_the_unlock_needs_the_local_api_header(self):
        r = self.client.post("/api/dev/unlock",
                             data=json.dumps({"password": INVENTED}),
                             content_type="application/json")
        self.assertEqual(403, r.status_code)
        self.assertFalse(server.dev_is_unlocked())

    def test_the_unlock_rejects_a_foreign_origin(self):
        r = self.client.post("/api/dev/unlock",
                             data=json.dumps({"password": INVENTED}),
                             content_type="application/json",
                             headers={server.API_REQUEST_HEADER: "1",
                                      "Origin": "https://evil.example"})
        self.assertEqual(403, r.status_code)
        self.assertFalse(server.dev_is_unlocked())


if __name__ == "__main__":
    unittest.main()
