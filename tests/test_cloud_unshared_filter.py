"""Cloud Manager's "Not Shared" card: projects nobody else can see.

This is an oversight filter rather than a browsing convenience. It answers one
question - "what did I finish and never send?" - and the value of the answer
depends entirely on the definition being the right one, so the definition is
what is pinned here.

**Not shared means: you own it, and nobody other than you has access.**

Three cases the obvious version gets wrong, each with a test below:

* A project *someone else* owns and shared **with you** has `sharedWith ==
  [you]`. Subtracting yourself would empty it and report it as unshared, which
  is backwards - being shared is how you can see it at all. It is also not
  something you could have failed to share.
* A project of yours shared **only with yourself** has nobody else on it, so it
  counts as unshared. That is the question being asked.
* A **local-only** file is not unshared, it is un-uploaded. The Local-Only card
  already answers that, and counting it here would make one number mean two
  things.

The functions are executed in Node, sliced out of the real `cloud.js`, so this
tests what the page runs rather than a copy of it. Every project name, site and
address below is invented.
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
const block = slice('function _isUnshared(cloudObj)',
                    '\nfunction _siteHasExternal');

globalThis.data = JSON.parse(process.argv[3]);
eval(block);
"""


def _node(script: str, data: dict) -> dict:
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


ME = "me@example.com"


def _cloud(owner=ME, shared=(), **extra):
    row = {"id": "p1", "name": "Example Project", "owner": owner,
           "sharedWith": list(shared)}
    row.update(extra)
    return row


class WhatNotSharedMeansTests(unittest.TestCase):
    """The definition, case by case. Each of these was a way to get it wrong."""

    def _is_unshared(self, cloud, current_user=ME):
        script = ("globalThis.probe = data.probe;\n"
                  "console.log(JSON.stringify({v: _isUnshared(data.probe)}));")
        return _node(script, {"currentUser": current_user, "probe": cloud})["v"]

    def test_yours_with_nobody_on_it_is_unshared(self):
        self.assertTrue(self._is_unshared(_cloud(shared=[])))

    def test_yours_shared_with_someone_is_not(self):
        self.assertFalse(self._is_unshared(_cloud(shared=["colleague@example.org"])))

    def test_yours_shared_only_with_yourself_still_counts_as_unshared(self):
        """Nobody other than you has access, which is the question."""
        self.assertTrue(self._is_unshared(_cloud(shared=[ME])))

    def test_theirs_shared_with_you_is_shared_not_unshared(self):
        """The case that makes "subtract yourself" wrong.

        `sharedWith` is `[you]`, so removing yourself empties it - and calling
        it unshared would be exactly backwards. Being shared is how you can
        see it.
        """
        self.assertFalse(self._is_unshared(
            _cloud(owner="someone@example.org", shared=[ME])))

    def test_theirs_shared_widely_is_not_unshared_either(self):
        self.assertFalse(self._is_unshared(
            _cloud(owner="someone@example.org", shared=[ME, "third@example.net"])))

    def test_a_local_only_file_is_not_counted(self):
        """Un-uploaded is a different problem, and Local-Only already shows it."""
        self.assertFalse(self._is_unshared(None))

    def test_a_group_share_counts_as_shared(self):
        """Toggling the sharing group adds each member as a dataset user.

        So they arrive in `sharedWith` like anyone else and need no special
        handling - which is the reason to assert it rather than assume it.
        """
        self.assertFalse(self._is_unshared(
            _cloud(shared=["one@example.org", "two@example.net"])))

    def test_case_and_padding_in_addresses_do_not_change_the_answer(self):
        self.assertTrue(self._is_unshared(_cloud(owner="ME@Example.com",
                                                 shared=["Me@EXAMPLE.com"])))

    def test_without_a_current_user_it_answers_no_rather_than_guessing(self):
        """Unknown identity cannot answer "yours", so nothing is claimed.

        The card hides itself in that state too - see the card test below.
        Silently meaning something else would be the worst option.
        """
        self.assertFalse(self._is_unshared(_cloud(shared=[]), current_user=""))


class TheCardBehavesLikeTheOthersTests(unittest.TestCase):

    def setUp(self):
        self.html = CLOUD_HTML.read_text(encoding="utf-8")
        self.js = CLOUD_JS.read_text(encoding="utf-8")

    def test_it_is_a_dashboard_card_like_every_other_filter(self):
        """Not a one-off control in its own style."""
        self.assertIn('data-filter="unshared"', self.html)
        self.assertIn('data-fn="setFilter" data-arg="unshared"', self.html)
        # It is found by what it filters now, not by the id of the box round
        # it - see the note on the hiding test below.
        self.assertIn('data-filter="unshared"', self.html)

    def test_it_shows_a_count(self):
        self.assertIn('id="dUnshared"', self.html)
        self.assertIn("dUnshared", self.js)

    def test_the_count_is_taken_through_the_owner_filter(self):
        """Otherwise the number on the control and the rows in the list
        disagree, which is the same lie in a smaller place."""
        window = self.js[self.js.index("let unsharedCount = 0;"):]
        window = window[:window.index("_setCount('dUnshared'")]
        self.assertIn("_passOwnerForCounts", window)

    def test_it_hides_itself_when_it_cannot_answer(self):
        """This read a local variable, `dUnsCard`, which was the id of the box
        the old design drew round this filter. The box is gone and the
        behaviour is not, so the assertion moved to the behaviour: it is
        *driven* in test_cloud_dashboard_reaches_the_page.py, which runs
        updateDashboard against the real cloud.html and checks the control is
        actually hidden when there is no current user.

        What stays here is that the hiding is keyed on knowing who he is - an
        unshared filter with no answer to "yours" would silently mean something
        else.
        """
        window = self.js[self.js.index("let unsharedCount = 0;"):]
        window = window[:window.index("_setCount('dTypeDesign'")]
        self.assertIn("_showFilter('unshared'", window)
        self.assertIn("currentUser", window)

    def test_the_filter_turns_itself_off_without_a_current_user(self):
        self.assertIn("if (activeFilter === 'unshared' && !((data && data.currentUser)",
                      self.js)

    def test_an_empty_list_says_what_emptied_it(self):
        self.assertIn("Everything you own has been shared", self.js)

    def _site_has_unshared(self, kids):
        """Run the real predicate rather than read it.

        This used to assert that the source of `_siteHasUnshared` contained
        the strings `kids.matched` and `kids.cloudOnly`, which pinned one
        implementation of the walk and would have passed with the answer
        inverted. It executes now. The owner test the real one applies is
        stubbed open, so this file keeps asking only its own question.
        """
        script = (
            "globalThis._passOwnerForCounts = () => true;\n"
            "eval(slice('function _siteHoldsVisible', "
            "'\\nfunction _siteHasUnassigned'));\n"
            "eval(slice('function _siteHasUnshared', "
            "'\\n/* And a site is not external'));\n"
            "console.log(JSON.stringify({v: "
            "_siteHasUnshared({children: data.probe}, null)}));"
        )
        return _node(script, {"currentUser": ME, "probe": kids})["v"]

    def test_a_site_holding_an_unshared_project_matches(self):
        """A site row is shown when a project inside it is unshared."""
        self.assertTrue(self._site_has_unshared(
            {"matched": [{"cloud": _cloud(shared=[]), "local": None}],
             "cloudOnly": [], "localOnly": []}))
        self.assertTrue(self._site_has_unshared(
            {"matched": [], "cloudOnly": [_cloud(shared=[])],
             "localOnly": []}))

    def test_a_site_whose_projects_are_all_shared_does_not(self):
        them = ["colleague@example.org"]
        self.assertFalse(self._site_has_unshared(
            {"matched": [{"cloud": _cloud(shared=them), "local": None}],
             "cloudOnly": [_cloud(shared=them)], "localOnly": []}))

    def test_a_site_is_never_unshared_on_its_own_account(self):
        """"you don't actually share sites on Ekahau." Sharing belongs to a
        project, so a site with nothing in it answers this with no."""
        self.assertFalse(self._site_has_unshared(
            {"matched": [], "cloudOnly": [], "localOnly": []}))


if __name__ == "__main__":
    unittest.main()
