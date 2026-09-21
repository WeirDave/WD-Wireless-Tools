"""The last five Cloud Manager actions no test named.

Backlog item 4, and the end of the 2026-09-18 whole-tool audit. These are the
reads and the bookkeeping - `create_local_folder`, `reveal_in_explorer`,
`open_login`, `get_duplicates`, `forget_all_recipients` - which is why the item
sat at P3 once the destructive surface was covered. None of them can lose a
project.

Two are worth more than the others and get it:

* **`create_local_folder` writes to disk**, and it takes a name typed by hand.
  It sanitises, refuses a traversal and refuses to land on something that
  already exists, and each of those is a real branch.
* **`reveal_in_explorer` takes a path from the page and hands it to the shell.**
  The containment check is the only thing between that and opening anything on
  the machine, so it is checked from outside the folder as well as inside it.

`forget_all_recipients` clears the store that holds real colleagues' email
addresses. **It is rule-zero material**, so every address here is invented at
an RFC 2606 documentation domain, and `WD_USER_DIR` - set in `tests/__init__`
before any module that reads it is imported - keeps all of this inside a
scratch directory. His own list is not reachable from here.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools import cloud_manager as cm
from tools import share_recipients

ALICE = "alice@example.invalid"
BOB = "bob@example.invalid"


class _Mgr(cm.CloudManager):
    def __init__(self, out_dir=""):
        self.api = None
        self.config = {"output_dir": str(out_dir)}

    def _ensure(self):
        return True


class _Disconnected(cm.CloudManager):
    def __init__(self, out_dir=""):
        self.api = None
        self.config = {"output_dir": str(out_dir)}

    def _ensure(self):
        return False


class MakingASiteFolderTests(unittest.TestCase):
    """It writes, and the name comes from a text box."""

    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="wd-mkfolder-")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.mgr = _Mgr(self.root)

    def test_the_folder_appears_on_disk(self):
        r = self.mgr.create_local_folder("SITE7 Harbour")
        self.assertTrue(r["ok"], r)
        made = self.root / "SITE7 Harbour"
        self.assertTrue(made.is_dir())
        self.assertEqual(str(made), r["path"])

    def test_it_comes_with_the_subfolders_the_suite_is_set_up_for(self):
        """A new site folder that arrives empty is a second job, by hand."""
        r = self.mgr.create_local_folder("SITE7 Harbour")
        for name in r["subfolders"]:
            with self.subTest(subfolder=name):
                self.assertTrue((self.root / "SITE7 Harbour" / name).is_dir())

    def test_characters_a_filesystem_will_not_take_are_replaced(self):
        r = self.mgr.create_local_folder('SITE7 <Harbour>: "north"?')
        self.assertTrue(r["ok"], r)
        made = Path(r["path"]).name
        for ch in '<>:"/\\|?*':
            self.assertNotIn(ch, made)

    def test_a_trailing_dot_is_dropped(self):
        """Windows cannot hold a folder whose name ends in a dot; it creates
        one that nothing can then open or delete."""
        r = self.mgr.create_local_folder("SITE7 Harbour.")
        self.assertTrue(r["ok"], r)
        self.assertEqual("SITE7 Harbour", Path(r["path"]).name)

    def test_a_name_that_tries_to_climb_out_is_refused(self):
        """The page sends this straight from a text box."""
        for name in ("..", "../escape", r"..\escape", "a/../b", "SITE7/../.."):
            with self.subTest(name=name):
                r = self.mgr.create_local_folder(name)
                self.assertIn("error", r)
        # And nothing was created beside the folder it was pointed at.
        self.assertEqual([], [p.name for p in self.root.parent.iterdir()
                              if p.name == "escape"])

    def test_a_name_that_sanitises_to_nothing_is_refused(self):
        for name in ("", "   ", "..."):
            with self.subTest(name=name):
                self.assertIn("error", self.mgr.create_local_folder(name))

    def test_a_name_of_nothing_but_illegal_characters_becomes_dashes(self):
        """Not refused, and that is the behaviour rather than an oversight.

        Each illegal character is replaced rather than dropped, so `<>:"|?*`
        sanitises to `-------` - a valid name, an odd one, and one he typed.
        Refusing it would mean guessing that he did not mean it; a folder he
        can see and rename is the cheaper wrong answer of the two.
        """
        r = self.mgr.create_local_folder('<>:"|?*')
        self.assertTrue(r["ok"], r)
        self.assertEqual("-------", Path(r["path"]).name)

    def test_it_will_not_land_on_a_folder_that_is_already_there(self):
        """Silently reusing one would merge two sites without saying so.

        The message is pinned exactly, not matched loosely. Without the check
        `mkdir` raises `FileExistsError`, whose text is "Cannot create a file
        when that file already exists" - so an assertion for "already exists"
        passes whether the refusal is deliberate or the operating system's
        error is leaking through the catch-all. Those read very differently on
        screen, and only one of them is this tool answering.
        """
        (self.root / "SITE7 Harbour").mkdir()
        r = self.mgr.create_local_folder("SITE7 Harbour")
        self.assertEqual("A folder with that name already exists", r.get("error"))

    def test_with_no_local_folder_set_it_says_so(self):
        r = _Mgr("").create_local_folder("SITE7 Harbour")
        self.assertIn("error", r)
        self.assertIn("pick one", r["error"])


class ShowingAFileInTheFileBrowserTests(unittest.TestCase):
    """The path comes from the page, and goes to the shell."""

    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="wd-reveal-")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.inside = self.root / "SITE7 - Design.esx"
        self.inside.write_text("x", encoding="utf-8")
        self.mgr = _Mgr(self.root)

    def test_a_file_inside_the_folder_is_handed_to_the_platform(self):
        with patch("tools.reveal.reveal", return_value={"ok": True}) as rev:
            r = self.mgr.reveal_in_explorer(str(self.inside))
        self.assertTrue(r.get("ok"), r)
        rev.assert_called_once()
        self.assertEqual(self.inside, Path(rev.call_args[0][0]))

    def test_a_path_outside_the_local_folder_is_refused(self):
        """The containment check is the whole guard here. Without it this
        opens anything on the machine that the page asks for."""
        outside = Path(self._tmp.name).parent / "not-his.esx"
        outside.write_text("x", encoding="utf-8")
        self.addCleanup(outside.unlink, True)
        with patch("tools.reveal.reveal") as rev:
            r = self.mgr.reveal_in_explorer(str(outside))
        self.assertIn("error", r)
        rev.assert_not_called()

    def test_climbing_out_with_dot_dot_is_refused(self):
        with patch("tools.reveal.reveal") as rev:
            r = self.mgr.reveal_in_explorer(str(self.root / ".." / "elsewhere.esx"))
        self.assertIn("error", r)
        rev.assert_not_called()

    def test_a_path_that_is_not_there_says_so_rather_than_opening_something(self):
        with patch("tools.reveal.reveal") as rev:
            r = self.mgr.reveal_in_explorer(str(self.root / "gone.esx"))
        self.assertIn("error", r)
        self.assertIn("not found", r["error"].lower())
        rev.assert_not_called()

    def test_with_no_local_folder_set_it_says_so(self):
        with patch("tools.reveal.reveal") as rev:
            r = _Mgr("").reveal_in_explorer(str(self.inside))
        self.assertIn("error", r)
        rev.assert_not_called()


class OpeningTheEkahauLoginTests(unittest.TestCase):
    """It opens a browser at Ekahau's sign-in page, and nothing else.

    Worth pinning that it is *that* URL: this is the one action in the tool
    that sends him somewhere to type a password, so the address it opens is
    the whole security property.
    """

    def test_it_opens_the_ekahau_url(self):
        mgr = _Mgr()
        if sys.platform == "win32":
            with patch("os.startfile", create=True) as opener:
                r = mgr.open_login()
            opener.assert_called_once_with(cm.EKAHAU_URL)
        else:  # pragma: no cover - depends on platform
            with patch("subprocess.Popen") as opener:
                r = mgr.open_login()
            self.assertIn(cm.EKAHAU_URL, opener.call_args[0][0])
        self.assertTrue(r["ok"], r)

    def test_the_url_is_ekahau_over_https(self):
        self.assertTrue(cm.EKAHAU_URL.startswith("https://"),
                        "the sign-in page must not be opened over http")
        self.assertIn("ekahau.", cm.EKAHAU_URL)

    def test_a_platform_that_refuses_reports_it_rather_than_raising(self):
        """A failure here must not take the request down - the page shows the
        address so he can open it himself."""
        mgr = _Mgr()
        target = "os.startfile" if sys.platform == "win32" else "subprocess.Popen"
        with patch(target, create=True, side_effect=OSError("no browser")):
            r = mgr.open_login()
        self.assertIn("error", r)
        self.assertIn("no browser", r["error"])


class ListingDuplicatesTests(unittest.TestCase):

    def test_it_asks_for_duplicates_in_the_local_folder(self):
        mgr = _Mgr("/some/where")
        with patch.object(cm, "build_duplicates_data",
                          return_value={"clusters": []}) as build:
            r = mgr.get_duplicates()
        self.assertEqual({"clusters": []}, r)
        self.assertEqual("/some/where", build.call_args[0][1])

    def test_being_signed_out_says_so(self):
        self.assertEqual({"error": "Not connected"}, _Disconnected().get_duplicates())

    def test_a_failure_comes_back_as_an_error_not_an_empty_list(self):
        """An empty duplicates list and a listing nobody could fetch are
        different, and showing the second as the first reads as "no duplicates
        found" - the one answer that invites doing nothing."""
        mgr = _Mgr("/some/where")
        with patch.object(cm, "build_duplicates_data",
                          side_effect=RuntimeError("Ekahau said no")):
            r = mgr.get_duplicates()
        self.assertIn("error", r)


class ClearingTheRecentRecipientsTests(unittest.TestCase):
    """The store holds real colleagues' addresses, so this is rule-zero
    material: every address below is invented at a documentation domain, and
    `WD_USER_DIR` keeps the file in a scratch directory.
    """

    def setUp(self):
        share_recipients.forget_all()
        self.addCleanup(share_recipients.forget_all)

    def test_it_empties_a_list_that_had_something_in_it(self):
        share_recipients.remember([ALICE, BOB])
        self.assertEqual(2, len(share_recipients.recent()))
        r = share_recipients.forget_all()
        self.assertTrue(r["ok"], r)
        self.assertEqual([], r["recipients"])
        self.assertEqual([], share_recipients.recent())

    def test_it_is_written_through_to_disk(self):
        share_recipients.remember([ALICE])
        share_recipients.forget_all()
        # Read back through a fresh load, not from anything held in memory.
        self.assertEqual([], share_recipients.recent())
        self.assertTrue(share_recipients.store_path().exists())

    def test_clearing_an_empty_list_is_not_an_error(self):
        r = share_recipients.forget_all()
        self.assertTrue(r["ok"])
        self.assertEqual([], r["recipients"])

    def test_the_store_stays_inside_the_user_directory(self):
        """It is the one file in the user directory worse than the rest, and
        it must never be written anywhere a backup or a release could pick it
        up."""
        from tools.user_dir import user_dir
        self.assertTrue(str(share_recipients.store_path()).startswith(str(user_dir())))

    def test_it_reaches_no_further_than_that_one_file(self):
        """Clearing recipients must not clear anything else in the directory.

        They live side by side, and a broad write here would take the manual
        matches or the settings with it.
        """
        from tools.user_dir import user_dir
        neighbour = user_dir() / "not-the-recipients.json"
        neighbour.parent.mkdir(parents=True, exist_ok=True)
        neighbour.write_text('{"keep": true}', encoding="utf-8")
        self.addCleanup(neighbour.unlink, True)
        share_recipients.remember([ALICE])
        share_recipients.forget_all()
        self.assertEqual('{"keep": true}', neighbour.read_text(encoding="utf-8"))


class TheFiveAreReachableFromThePageTests(unittest.TestCase):
    """A method nothing routes cannot be called, and the route table is a dict
    literal that nothing else in the suite executes."""

    ACTIONS = ("create_local_folder", "reveal_in_explorer", "open_login",
               "get_duplicates", "forget_all_recipients")

    def test_every_one_of_them_is_routed(self):
        import server
        for action in self.ACTIONS:
            with self.subTest(action=action):
                self.assertIn(action, server.CLOUD_ACTIONS)

    def test_each_route_hands_over_what_the_page_sends(self):
        import server
        seen = {}

        class FakeCm:
            def create_local_folder(self, name):
                seen["create"] = name
                return {"ok": True}

            def reveal_in_explorer(self, path):
                seen["reveal"] = path
                return {"ok": True}

            def open_login(self):
                seen["login"] = True
                return {"ok": True}

            def get_duplicates(self):
                seen["dupes"] = True
                return {"ok": True}

        real_cm, real_sr = server.cm, server.share_recipients

        class FakeSr:
            def forget_all(self):
                seen["forget"] = True
                return {"ok": True}

        server.cm = FakeCm()
        server.share_recipients = FakeSr()
        try:
            server.CLOUD_ACTIONS["create_local_folder"]({"name": "SITE7 Harbour"})
            server.CLOUD_ACTIONS["reveal_in_explorer"]({"path": r"C:\a\b.esx"})
            server.CLOUD_ACTIONS["open_login"]({})
            server.CLOUD_ACTIONS["get_duplicates"]({})
            server.CLOUD_ACTIONS["forget_all_recipients"]({})
        finally:
            server.cm, server.share_recipients = real_cm, real_sr

        self.assertEqual("SITE7 Harbour", seen["create"])
        self.assertEqual(r"C:\a\b.esx", seen["reveal"])
        self.assertTrue(seen["login"])
        self.assertTrue(seen["dupes"])
        self.assertTrue(seen["forget"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
