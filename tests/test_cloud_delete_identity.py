"""A delete confirmation has to say what it is about to destroy.

His report: "when we're deleting a permanent file from the ekahau cloud we get
a pop-up that says we're going to delete it but it greys the background out so
you can't remember what it is you're deleting to double check."

The dialog was right that it needed confirming and wrong about where the
answer lived. Stage one named the project; stage two - the last thing seen
before the irreversible act, and the one that asks you to type DELETE - said
only "this project", over a list the overlay had just made unreadable.

Naming it in the dialog is the fix rather than lightening the backdrop. A
backdrop only helps when the row happens to be on screen, not scrolled away
and not behind the dialog itself, and none of that is something a
confirmation for an irreversible action should depend on.

**What goes in, and one thing that deliberately does not.** Name, the site it
is in, when it was last modified, and whether anyone else has access. Not
size: `_row_meta` in `tools/cloud_manager.py` already excludes it because
cloud projects are stored uncompressed and local `.esx` are ZIP-deflated, so
the same project reads 5-10x different. In a dialog whose only job is "is this
the one I mean?", a number that disagrees with the local file by a factor of
eight is worse than no number at all.

Every project, site and address here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CLOUD_HTML = ROOT / "web" / "cloud.html"

NODE_TIMEOUT_S = 120

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block = slice('function _cloudDetailsById(id)',
                    '\nfunction _setDeleteWhat');

globalThis.e = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
globalThis.data = JSON.parse(process.argv[3]);
globalThis.currentTab = 'projects';
eval(block);
"""

ME = "me@example.com"
THEM = "colleague@example.org"


def _node(script: str, data: dict):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "probe.js"
        path.write_text(NODE_PRELUDE + script, encoding="utf-8")
        out = subprocess.run(
            [node, str(path), str(CLOUD_JS), json.dumps(data)],
            capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
        if out.returncode != 0:
            raise AssertionError(out.stderr[-2000:])
        return json.loads(out.stdout)


#: Two projects whose names differ only in a revision suffix, in two different
#: sites - the case he described, where the list is the only way to tell them
#: apart and the list is exactly what the overlay hides.
LEDGER = {
    "currentUser": ME,
    "matched": [],
    "cloudOnly": [
        {"id": "site-north", "name": "North Campus", "children": {
            "matched": [], "localOnly": [],
            "cloudOnly": [
                {"id": "p-a", "name": "Riverside Block A", "owner": ME,
                 "sharedWith": [], "meta": "12 Aug 2026", "size": 4096},
            ]}},
        {"id": "site-south", "name": "South Campus", "children": {
            "matched": [], "localOnly": [],
            "cloudOnly": [
                {"id": "p-b", "name": "Riverside Block A", "owner": ME,
                 "sharedWith": [THEM, "third@example.net"],
                 "meta": "3 Sep 2026", "size": 8192},
            ]}},
    ],
    "localOnly": [],
}


class TheDialogNamesWhatItWillDestroyTests(unittest.TestCase):

    def _html(self, ids_and_names):
        entries = ", ".join(
            "_cloudDeleteEntry(%s, %s, false)" % (json.dumps(i), json.dumps(n))
            for i, n in ids_and_names)
        return _node(
            "console.log(JSON.stringify({h: _deleteWhatHtml([%s])}));" % entries,
            LEDGER)["h"]

    def test_the_name_is_there_at_all(self):
        """The whole complaint, in one assertion."""
        html = self._html([("p-a", "Riverside Block A")])
        self.assertIn("Riverside Block A", html)

    def test_two_projects_with_the_same_name_are_told_apart(self):
        """The actual failure case: near-identical names in different sites.

        Neither the name alone nor a count can answer "which one is this?".
        The site and the modified date can, and they are what is shown.
        """
        a = self._html([("p-a", "Riverside Block A")])
        b = self._html([("p-b", "Riverside Block A")])
        self.assertNotEqual(a, b, "the two dialogs are indistinguishable")
        self.assertIn("North Campus", a)
        self.assertIn("12 Aug 2026", a)
        self.assertIn("South Campus", b)
        self.assertIn("3 Sep 2026", b)

    def test_it_says_when_other_people_will_lose_access(self):
        """Deleting something others use is a different decision."""
        html = self._html([("p-b", "Riverside Block A")])
        self.assertIn("lose access", html)
        self.assertIn(THEM, html)

    def test_it_names_every_person_who_loses_access(self):
        """Not three and a count - who loses access *is* the decision."""
        data = json.loads(json.dumps(LEDGER))
        five = ["a@example.com", "b@example.org", "c@example.net",
                "d@example.com", "e@example.org"]
        data["cloudOnly"][1]["children"]["cloudOnly"][0]["sharedWith"] = five
        html = _node(
            "console.log(JSON.stringify({h: _deleteWhatHtml("
            "[_cloudDeleteEntry('p-b', 'Riverside Block A', false)])}));", data)["h"]
        for address in five:
            self.assertIn(address, html)
        self.assertNotIn("more", html)

    def test_nothing_is_claimed_about_sharing_when_nobody_else_has_it(self):
        html = self._html([("p-a", "Riverside Block A")])
        self.assertNotIn("lose access", html)

    def test_your_own_address_is_not_counted_as_someone_else(self):
        """Shared "with yourself" must not read as other people losing access."""
        data = json.loads(json.dumps(LEDGER))
        data["cloudOnly"][0]["children"]["cloudOnly"][0]["sharedWith"] = [ME]
        html = _node(
            "console.log(JSON.stringify({h: _deleteWhatHtml("
            "[_cloudDeleteEntry('p-a', 'Riverside Block A', false)])}));", data)["h"]
        self.assertNotIn("lose access", html)

    def test_size_is_deliberately_absent(self):
        """Cloud is uncompressed, local is deflated - the number misleads.

        `_row_meta` excluded it from the row for this reason; a delete dialog
        is the last place to reintroduce a figure that disagrees with the
        local file by a factor of eight.
        """
        html = self._html([("p-a", "Riverside Block A")])
        for misleading in ("4096", "4 KB", "4.0 KB", "bytes"):
            self.assertNotIn(misleading, html)

    def test_a_bulk_delete_lists_them_rather_than_counting_them(self):
        html = self._html([("p-a", "Riverside Block A"),
                           ("p-b", "Riverside Block A")])
        self.assertIn("2 items", html)
        self.assertIn("North Campus", html)
        self.assertIn("South Campus", html)

    def test_a_long_selection_lists_every_item(self):
        """Reversed deliberately: it used to show eight and "and 12 more".

        "it would be better if it was easily readable and lengthy than if it's
        brief in order to save screen real estate." Hiding twelve of the things
        about to be destroyed is the compression he objected to; the block
        scrolls instead.
        """
        many = [("p-a", "Riverside Block A")] * 20
        html = self._html(many)
        self.assertEqual(20, html.count("delete-what-item"))
        self.assertNotIn("more</div>", html)

    def test_a_name_that_looks_like_markup_is_escaped(self):
        data = json.loads(json.dumps(LEDGER))
        data["cloudOnly"][0]["children"]["cloudOnly"][0]["name"] = "<img src=x>"
        html = _node(
            "console.log(JSON.stringify({h: _deleteWhatHtml("
            "[_cloudDeleteEntry('p-a', 'fallback', false)])}));", data)["h"]
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)

    def test_an_unknown_id_still_names_what_it_was_given(self):
        """A row that has scrolled out of the data must not produce a blank."""
        html = self._html([("not-in-the-list", "Riverside Block A")])
        self.assertIn("Riverside Block A", html)


class TheOneDialogCarriesItTests(unittest.TestCase):
    """There is one dialog now, and it has to hold everything."""

    def setUp(self):
        self.js = CLOUD_JS.read_text(encoding="utf-8")
        self.html = CLOUD_HTML.read_text(encoding="utf-8")

    def test_the_markup_exists(self):
        self.assertIn('id="deleteWhat"', self.html)
        self.assertNotIn('id="cloudDeleteWhat"', self.html)

    def test_both_the_single_and_bulk_paths_fill_it(self):
        self.assertGreaterEqual(
            self.js.count("_setDeleteWhat('deleteWhat',"), 2,
            "the single and bulk paths should both fill the block")
        self.assertIn("_cloudDeleteEntry(idOrPath, name, kind === 'sites')", self.js)

    def test_the_single_delete_carries_its_name(self):
        self.assertIn("deleteTarget = { side, idOrPath, kind, name }", self.js)

    def test_the_backdrop_was_not_lightened_instead(self):
        """The fix is naming it, not making the greyed list readable again.

        A backdrop cannot be relied on: the row may be scrolled away or behind
        the dialog. If someone later "fixes" this by lightening the overlay,
        this is the test that should make them explain why.
        """
        self.assertIn(".delete-what", (ROOT / "web" / "assets" / "wd-tools.css")
                      .read_text(encoding="utf-8"))

    def test_it_says_plainly_that_nothing_can_be_recovered(self):
        """Permanence, stated rather than implied.

        Checked before writing it rather than assumed: the endpoint is
        `PUT .../batch-delete`, and there is no restore, trash, recycle,
        undelete or `deletedAt` anywhere in the API wrapper or in the captured
        request logs under `docs/reverse-engineering/`. CLAUDE.md records the
        same conclusion. So the wording claims permanence, and claims no
        safety net that does not exist.
        """
        # The wording moved into the one dialog's own copy when the second
        # gate went, so it is asserted where it now lives.
        self.assertIn("no trash to recover it from", self.js)
        self.assertIn("will not exist on Ekahau Cloud anymore", self.js)

    def test_it_does_not_pretend_local_copies_are_at_risk(self):
        """Being clear about what is *not* destroyed is part of the decision."""
        self.assertIn("is not touched", self.js)

    def test_there_is_no_type_to_confirm_step_at_all(self):
        """Removed, not softened.

        "another thing that I can't stand is the fact that you're forcing me
        to type 'delete'... even Ekahau doesn't do that, they just put up a
        nice modal that has a red delete button."

        It added no information. It could not tell him *which* project he had
        picked - the thing that actually protects him - and he deletes
        routinely. Friction that conveys nothing teaches people to click
        through the dialogs that do convey something.
        """
        for gone in ("cloudDeleteConfirmInput", "Type <b>DELETE</b>",
                     "Type DELETE to confirm", "cloudDeleteConfirmModal"):
            self.assertNotIn(gone, self.html, gone)
        for gone in ("_updateCloudDeleteConfirmBtn", "_requireCloudDeleteConfirm",
                     "cloudDeleteConfirmInput"):
            self.assertNotIn(gone, self.js, gone)

    def test_one_dialog_rather_than_two(self):
        """With the typing gone, a second dialog asks the same question twice.

        That is the same defect in another form: more effort, no more
        information.
        """
        self.assertEqual(1, self.html.count('id="deleteModal"'))
        self.assertNotIn("Stage2", self.js)

    def test_the_action_is_a_red_button_that_says_what_it_does(self):
        block = self.html[self.html.index('id="deleteModal"'):]
        block = block[:block.index("modal-overlay", 10)]
        self.assertIn("btn-red", block)
        self.assertIn('id="deleteBtn"', block)
        self.assertIn("_setDeleteBtn", self.js)
        self.assertIn("Delete from cloud", self.js)


if __name__ == "__main__":
    unittest.main()
