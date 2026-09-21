"""The Sharing Group's six actions, executed.

These were the last untested group named in the Cloud Manager audit's A33 and
the backlog item that carried it: ``get_my_group``, ``add_group_member``,
``remove_group_member``, ``toggle_group_share``, ``refresh_group_shares`` and
``list_shares``/``remove_share`` beside them. The destructive three were closed
in v2.148.0; this is the rest, and it is breadth rather than risk - which is
why it is one file and not six.

Two of them can still take somebody's access away, though, and those get the
attention: ``remove_group_member`` and ``toggle_group_share`` with *enable*
false. A colleague who quietly loses access to a project does not find out
until they try to open it.

Everything is run against a fake standing in for Ekahau's API, shaped the way
``cloud_manager`` actually reads it - a stub that invents the contract tests the
stub. Nothing here reaches the network, and every address is invented at an
RFC 2606 documentation domain.

``CLOUD_ACTIONS`` is exercised too, and separately. It is a dictionary literal
nobody executes: a method can be perfect and unreachable, and a lambda reading
the wrong key is invisible to a test of the function it calls.
"""
from __future__ import annotations

import unittest

from tools import cloud_manager as cm

ME = "me@example.invalid"
ALICE = "alice@example.invalid"
BOB = "bob@example.invalid"
GROUP_ID = "grp-0001"
GROUP_NAME = "My Sharing Group"
PROJECT = "proj-0001"


class _GroupApi:
    """Ekahau's user-group and share surface, in the shapes actually read.

    ``get_user_group`` answers a dict with ``groupId``, ``groupName`` and a
    ``members`` list of dicts carrying ``email``; ``update_user_group`` takes
    added, deleted and the full current member list. ``toggle_project_group_share``
    answers a list whose first entry may carry ``success: False``.
    """

    #: `None` is a meaningful value here - it is what Ekahau answers when the
    #: account has never made a group - so the default cannot be `None` too.
    _DEFAULT = object()

    def __init__(self, *, group=_DEFAULT, raises=None, toggle_result=None):
        self.user_email = ME
        self._group = group if group is not _GroupApi._DEFAULT else {
            "groupId": GROUP_ID,
            "groupName": GROUP_NAME,
            "createdBy": ME,
            "members": [
                {"email": ALICE, "firstName": "Alice", "lastName": "Ant",
                 "userId": "u-1", "extra": "ignored"},
                {"email": BOB, "firstName": "", "lastName": "",
                 "userId": "u-2"},
            ],
        }
        self.raises = raises or set()
        self.toggle_result = toggle_result
        self.updates = []
        self.toggles = []
        self.removed_shares = []

    def get_user_group(self, group_name):
        if "get" in self.raises:
            raise RuntimeError("Ekahau refused the group lookup")
        return self._group

    def update_user_group(self, group_id, group_name, added, deleted,
                          current_members):
        if "update" in self.raises:
            raise RuntimeError("Ekahau refused the group update")
        self.updates.append({
            "groupId": group_id, "groupName": group_name,
            "added": list(added), "deleted": list(deleted),
            "current": list(current_members),
        })
        return {"ok": True}

    def toggle_project_group_share(self, project_id, group_id, group_name,
                                   role, enable):
        if "toggle" in self.raises:
            raise RuntimeError("Ekahau refused the toggle")
        self.toggles.append((project_id, group_id, group_name, role, enable))
        return self.toggle_result if self.toggle_result is not None else [{"success": True}]

    def list_project_shares(self, project_id):
        """Keyed on a fixed project, not on whatever was asked for.

        Echoing the argument back would make every lookup succeed, and the
        thing worth checking is what happens when the answer does not mention
        the project - which is the shape that would otherwise hand back the
        previous project's share list.
        """
        if "list" in self.raises:
            raise RuntimeError("Ekahau refused the share listing")
        return {PROJECT: [{"username": ME, "role": "OWNER"},
                          {"username": ALICE, "role": "READ_USER"}]}

    def remove_project_share(self, project_id, email):
        if "removeshare" in self.raises:
            raise RuntimeError("Ekahau refused the removal")
        self.removed_shares.append((project_id, email))
        return [{"success": True}]


class _Mgr(cm.CloudManager):
    """A manager with a session already in hand and no __init__ side effects."""

    def __init__(self, api):
        self.api = api
        self.config = {"output_dir": ""}

    def _ensure(self):
        return True


class _Disconnected(cm.CloudManager):
    def __init__(self):
        self.api = None
        self.config = {}

    def _ensure(self):
        return False


class ReadingTheGroupTests(unittest.TestCase):

    def test_the_members_come_back_named(self):
        api = _GroupApi()
        r = _Mgr(api).get_my_group()
        self.assertTrue(r["ok"], r)
        self.assertEqual(GROUP_ID, r["group"]["groupId"])
        self.assertEqual([ALICE, BOB], [m["email"] for m in r["group"]["members"]])
        self.assertEqual("Alice", r["group"]["members"][0]["firstName"])

    def test_only_the_four_fields_the_page_uses_are_passed_on(self):
        """A member record from Ekahau carries more than the page needs, and
        this list ends up on screen. Copying it wholesale would put whatever
        else the API decides to include in front of him."""
        r = _Mgr(_GroupApi()).get_my_group()
        self.assertEqual({"email", "firstName", "lastName", "userId"},
                         set(r["group"]["members"][0]))

    def test_a_member_with_no_email_is_dropped(self):
        """It cannot be shared with, removed or displayed."""
        api = _GroupApi(group={
            "groupId": GROUP_ID, "groupName": GROUP_NAME, "createdBy": ME,
            "members": [{"email": ALICE}, {"firstName": "Nameless"}],
        })
        r = _Mgr(api).get_my_group()
        self.assertEqual([ALICE], [m["email"] for m in r["group"]["members"]])

    def test_no_group_is_a_state_rather_than_an_error(self):
        """Most accounts have never made one. Reporting that as a failure
        would put an error on the screen of everybody who has not."""
        r = _Mgr(_GroupApi(group=None)).get_my_group()
        self.assertTrue(r["ok"])
        self.assertIsNone(r["group"])
        self.assertIn(GROUP_NAME, r["message"])

    def test_a_refusal_comes_back_as_an_error_not_an_empty_group(self):
        """An empty group and a group nobody could read are different, and
        showing the second as the first invites him to re-add everyone."""
        r = _Mgr(_GroupApi(raises={"get"})).get_my_group()
        self.assertIn("error", r)
        self.assertNotIn("group", r)

    def test_being_signed_out_says_so(self):
        self.assertEqual({"error": "Not connected"}, _Disconnected().get_my_group())


class AddingAMemberTests(unittest.TestCase):

    def test_the_email_reaches_ekahau(self):
        api = _GroupApi()
        r = _Mgr(api).add_group_member("  Carol@Example.Invalid  ")
        self.assertTrue(r["ok"], r)
        self.assertEqual(1, len(api.updates))
        self.assertEqual(["carol@example.invalid"], api.updates[0]["added"])
        self.assertEqual(GROUP_ID, api.updates[0]["groupId"])

    def test_an_address_is_trimmed_and_lower_cased(self):
        """So the same person typed two ways is one member."""
        r = _Mgr(_GroupApi()).add_group_member(" Carol@Example.Invalid ")
        self.assertEqual("carol@example.invalid", r["email"])

    def test_somebody_already_in_the_group_is_not_added_twice(self):
        api = _GroupApi()
        r = _Mgr(api).add_group_member(ALICE.upper())
        self.assertTrue(r["ok"])
        self.assertTrue(r["already"])
        self.assertEqual([], api.updates, "it called Ekahau anyway")

    def test_something_that_is_not_an_address_is_refused_before_any_call(self):
        api = _GroupApi()
        for bad in ("", None, "carol", "carol at example"):
            with self.subTest(value=bad):
                r = _Mgr(api).add_group_member(bad)
                self.assertIn("error", r)
        self.assertEqual([], api.updates)

    def test_no_group_to_add_to_is_an_error_that_names_the_group(self):
        r = _Mgr(_GroupApi(group=None)).add_group_member(BOB)
        self.assertIn("error", r)
        self.assertIn(GROUP_NAME, r["error"])

    def test_a_refusal_is_reported_rather_than_swallowed(self):
        r = _Mgr(_GroupApi(raises={"update"})).add_group_member("carol@example.invalid")
        self.assertIn("error", r)

    def test_being_signed_out_says_so(self):
        self.assertEqual({"error": "Not connected"},
                         _Disconnected().add_group_member(BOB))


class RemovingAMemberTests(unittest.TestCase):
    """This one takes somebody's access away, so it gets the closer look."""

    def test_the_email_is_sent_as_a_deletion(self):
        api = _GroupApi()
        r = _Mgr(api).remove_group_member(ALICE)
        self.assertTrue(r["ok"], r)
        self.assertEqual([ALICE], api.updates[0]["deleted"])
        self.assertEqual([], api.updates[0]["added"])

    def test_the_whole_current_member_list_is_echoed_back(self):
        """Ekahau's captured remove payload carries the pre-delete state, and
        the docstring on the method says why: the server checks it against what
        it holds. Sending an empty list is the shape that silently removes the
        wrong person.
        """
        api = _GroupApi()
        _Mgr(api).remove_group_member(ALICE)
        sent = [m.get("email") for m in api.updates[0]["current"]]
        self.assertEqual([ALICE, BOB], sent)

    def test_exactly_one_person_is_ever_deleted_in_a_call(self):
        api = _GroupApi()
        _Mgr(api).remove_group_member(ALICE)
        self.assertEqual(1, len(api.updates[0]["deleted"]))

    def test_an_empty_email_is_refused_before_anything_is_sent(self):
        api = _GroupApi()
        for bad in ("", None):
            with self.subTest(value=bad):
                self.assertIn("error", _Mgr(api).remove_group_member(bad))
        self.assertEqual([], api.updates)

    def test_a_refusal_is_reported_rather_than_reported_as_done(self):
        """Saying somebody was removed when they were not is the worse of the
        two wrong answers here: nobody goes back to check."""
        r = _Mgr(_GroupApi(raises={"update"})).remove_group_member(ALICE)
        self.assertIn("error", r)
        self.assertNotIn("ok", r)

    def test_no_group_is_an_error_that_names_it(self):
        r = _Mgr(_GroupApi(group=None)).remove_group_member(ALICE)
        self.assertIn("error", r)
        self.assertIn(GROUP_NAME, r["error"])

    def test_being_signed_out_says_so(self):
        self.assertEqual({"error": "Not connected"},
                         _Disconnected().remove_group_member(ALICE))


class TogglingTheGroupOnAProjectTests(unittest.TestCase):

    def test_turning_it_on_passes_every_argument_through_in_order(self):
        """The argument order is pinned because one of them decides whether
        access is being given or taken away."""
        api = _GroupApi()
        r = _Mgr(api).toggle_group_share(PROJECT, GROUP_ID, GROUP_NAME,
                                         "WRITE_USER", True)
        self.assertTrue(r["ok"], r)
        self.assertEqual([(PROJECT, GROUP_ID, GROUP_NAME, "WRITE_USER", True)],
                         api.toggles)
        self.assertTrue(r["enabled"])

    def test_turning_it_off_is_carried_through_as_off(self):
        """An `enable` that arrived as truthy when the page meant off would
        share a project rather than unshare it."""
        api = _GroupApi()
        r = _Mgr(api).toggle_group_share(PROJECT, GROUP_ID, GROUP_NAME,
                                         "READ_USER", False)
        self.assertFalse(api.toggles[0][4])
        self.assertFalse(r["enabled"])

    def test_the_role_defaults_to_read_rather_than_write(self):
        """A missing role must not quietly hand out write access."""
        api = _GroupApi()
        _Mgr(api).toggle_group_share(PROJECT, GROUP_ID, GROUP_NAME, "", True)
        self.assertEqual("READ_USER", api.toggles[0][3])

    def test_a_missing_project_or_group_is_refused_before_the_call(self):
        api = _GroupApi()
        for pid, gid in ((None, GROUP_ID), (PROJECT, None), ("", "")):
            with self.subTest(projectId=pid, groupId=gid):
                r = _Mgr(api).toggle_group_share(pid, gid, GROUP_NAME, "READ_USER", True)
                self.assertIn("error", r)
        self.assertEqual([], api.toggles)

    def test_ekahau_saying_no_is_reported_as_no(self):
        """`success: False` in the body, not an exception. Reading only the
        exception path is how a refused write gets announced as done."""
        api = _GroupApi(toggle_result=[{"success": False,
                                        "message": "Not the project owner"}])
        r = _Mgr(api).toggle_group_share(PROJECT, GROUP_ID, GROUP_NAME,
                                         "READ_USER", True)
        self.assertEqual("Not the project owner", r["error"])

    def test_a_refusal_with_no_message_still_reads_as_a_failure(self):
        api = _GroupApi(toggle_result=[{"success": False}])
        r = _Mgr(api).toggle_group_share(PROJECT, GROUP_ID, GROUP_NAME,
                                         "READ_USER", True)
        self.assertIn("error", r)
        self.assertTrue(r["error"].strip(), "an empty reason is not a reason")

    def test_an_empty_body_is_not_read_as_a_refusal(self):
        """Ekahau answers some writes with nothing at all, and every other
        write helper in this file already has that fallback."""
        api = _GroupApi(toggle_result=[])
        r = _Mgr(api).toggle_group_share(PROJECT, GROUP_ID, GROUP_NAME,
                                         "READ_USER", True)
        self.assertTrue(r["ok"], r)

    def test_being_signed_out_says_so(self):
        self.assertEqual({"error": "Not connected"},
                         _Disconnected().toggle_group_share(
                             PROJECT, GROUP_ID, GROUP_NAME, "READ_USER", True))


class ListingAndRemovingASingleShareTests(unittest.TestCase):

    def test_the_share_list_comes_back_for_the_project_asked_about(self):
        r = _Mgr(_GroupApi()).list_shares(PROJECT)
        self.assertTrue(r["ok"], r)
        self.assertEqual([ME, ALICE], [u["username"] for u in r["users"]])

    def test_a_project_with_no_entry_in_the_answer_is_an_empty_list(self):
        """Not a crash, and not the previous project's list."""
        r = _Mgr(_GroupApi()).list_shares("some-other-project")
        self.assertTrue(r["ok"])
        self.assertEqual([], r["users"])

    def test_a_missing_project_id_is_refused(self):
        self.assertIn("error", _Mgr(_GroupApi()).list_shares(""))

    def test_removing_a_share_sends_the_address_lower_cased(self):
        api = _GroupApi()
        r = _Mgr(api).remove_share(PROJECT, "  Alice@Example.Invalid ")
        self.assertTrue(r["ok"], r)
        self.assertEqual([(PROJECT, ALICE)], api.removed_shares)

    def test_removing_needs_both_a_project_and_an_address(self):
        api = _GroupApi()
        for pid, email in ((None, ALICE), (PROJECT, ""), ("", "")):
            with self.subTest(projectId=pid, email=email):
                self.assertIn("error", _Mgr(api).remove_share(pid, email))
        self.assertEqual([], api.removed_shares)

    def test_a_refused_removal_is_reported_rather_than_reported_as_done(self):
        r = _Mgr(_GroupApi(raises={"removeshare"})).remove_share(PROJECT, ALICE)
        self.assertIn("error", r)

    def test_being_signed_out_says_so(self):
        self.assertEqual({"error": "Not connected"},
                         _Disconnected().list_shares(PROJECT))
        self.assertEqual({"error": "Not connected"},
                         _Disconnected().remove_share(PROJECT, ALICE))


class NoneOfThemTouchRecentRecipientsTests(unittest.TestCase):
    """``share_recipients.json`` holds real colleagues' addresses.

    It is rule zero material - gitignored, absent from the release payload, no
    network imports - and the group actions have no business writing to it.
    ``add_share`` deliberately does; these six do not.
    """

    def test_the_group_actions_do_not_write_the_recipient_store(self):
        import inspect
        for name in ("get_my_group", "add_group_member", "remove_group_member",
                     "toggle_group_share", "list_shares", "remove_share"):
            src = inspect.getsource(getattr(cm.CloudManager, name))
            with self.subTest(method=name):
                self.assertNotIn("share_recipients", src)
                self.assertNotIn("remember_recipients", src)


class TheActionsAreReachableFromThePageTests(unittest.TestCase):
    """A method that is not routed is unreachable, and the route table is a
    dictionary literal that nothing else in the suite executes.

    ``delete_cloud`` spent the whole audit period appearing in exactly one test
    docstring, which is what this shape of gap looks like from outside.
    """

    ACTIONS = ("get_my_group", "add_group_member", "remove_group_member",
               "toggle_group_share", "refresh_group_shares", "list_shares",
               "remove_share")

    def test_every_action_is_in_the_route_table(self):
        import server
        for action in self.ACTIONS:
            with self.subTest(action=action):
                self.assertIn(action, server.CLOUD_ACTIONS)

    def test_the_page_can_call_every_one_of_them(self):
        """The name the browser sends, read out of the built API_MAP.

        The map is evaluated rather than searched: a name that happens to
        appear in a comment or a tooltip satisfies a substring check while the
        action is routed nowhere, which is the shape this whole audit item was
        about.
        """
        import json
        import shutil
        import subprocess
        from pathlib import Path
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        cloud_js = (Path(__file__).resolve().parent.parent
                    / "web" / "assets" / "js" / "cloud.js")
        program = (
            "const fs=require('fs');"
            "const s=fs.readFileSync(process.argv[1],'utf8');"
            "const a=s.indexOf('const API_MAP = {');"
            "const b=s.indexOf('\\nasync function pyApi(', a);"
            "eval(s.slice(a,b)+';globalThis.API_MAP=API_MAP;');"
            "console.log(JSON.stringify(Object.values(API_MAP).map(v=>v[0])));")
        proc = subprocess.run(["node", "-e", program, str(cloud_js)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=120)
        self.assertEqual(0, proc.returncode, proc.stderr)
        routed = set(json.loads(proc.stdout))
        for action in self.ACTIONS:
            with self.subTest(action=action):
                self.assertIn(action, routed)

    def test_each_route_hands_over_the_arguments_the_page_sends(self):
        """A lambda reading the wrong key is invisible to a test of the method
        it calls: the method is correct, and it is handed None."""
        import server

        seen = {}

        class FakeCm:
            def get_my_group(self, group_name="My Sharing Group"):
                seen["group"] = group_name
                return {"ok": True}

            def add_group_member(self, email, group_name="My Sharing Group"):
                seen["add"] = (email, group_name)
                return {"ok": True}

            def remove_group_member(self, email, group_name="My Sharing Group"):
                seen["remove"] = (email, group_name)
                return {"ok": True}

            def toggle_group_share(self, project_id, group_id, group_name,
                                   role, enable):
                seen["toggle"] = (project_id, group_id, group_name, role, enable)
                return {"ok": True}

            def list_shares(self, project_id):
                seen["list"] = project_id
                return {"ok": True}

            def remove_share(self, project_id, email):
                seen["removeshare"] = (project_id, email)
                return {"ok": True}

        real = server.cm
        server.cm = FakeCm()
        try:
            server.CLOUD_ACTIONS["add_group_member"]({"email": BOB})
            server.CLOUD_ACTIONS["remove_group_member"]({"email": ALICE})
            server.CLOUD_ACTIONS["toggle_group_share"]({
                "projectId": PROJECT, "groupId": GROUP_ID,
                "groupName": GROUP_NAME, "role": "READ_USER", "enable": False})
            server.CLOUD_ACTIONS["list_shares"]({"projectId": PROJECT})
            server.CLOUD_ACTIONS["remove_share"]({"projectId": PROJECT,
                                                  "email": ALICE})
        finally:
            server.cm = real

        self.assertEqual(BOB, seen["add"][0])
        self.assertEqual(ALICE, seen["remove"][0])
        # The one that decides whether access is given or taken away.
        self.assertEqual((PROJECT, GROUP_ID, GROUP_NAME, "READ_USER", False),
                         seen["toggle"])
        self.assertEqual(PROJECT, seen["list"])
        self.assertEqual((PROJECT, ALICE), seen["removeshare"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
