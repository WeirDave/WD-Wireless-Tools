"""Live notices a project that was saved again, and says when it is holding.

He saved a new version of a project from Ekahau, watched Live count down to
zero, and nothing happened until F5. Two things could do that, and both are
covered:

* **The poll compared ids, not rows.** A project saved again keeps its cloud id
  and gains a newer date and a new size, so the "has anything changed" check
  called it identical, raised no "Ekahau Cloud has changed" bar, and the list
  stayed as drawn. F5 worked because it draws without comparing.
* **A busy tick skipped the poll silently.** Something ticked or a dialog open
  holds the poll, and the button went on counting as if it were running.

Driven through the real cloud.js. Every name is invented.
"""
from __future__ import annotations

import json
import unittest

from tests import cloud_vm


def _cloud(mtime, size=100, name="Dock A Survey"):
    return {"id": "p1", "name": name, "mtime": mtime, "size": size,
            "owner": "pat@example.invalid"}


def _local(mtime=1000):
    return {"path": "/o/Dock A Survey.esx", "name": "Dock A Survey",
            "mtime": mtime, "size": 90}


def _cloud_only(c):
    return {"matched": [], "cloudOnly": [c], "localOnly": [],
            "orphans": {"cloudOnly": []}, "currentUser": "pat@example.invalid"}


def _pair(c, l, staleness=None):
    return {"matched": [{"cloud": c, "local": l, "matchType": "exact",
                         "namesDiffer": False, "staleness": staleness}],
            "cloudOnly": [], "localOnly": [], "orphans": {"cloudOnly": []},
            "currentUser": "pat@example.invalid"}


# The payloads go in as JSON text, as refreshData hands them to onData.
POLL = r"""
s.__set('currentTab', 'projects');
const A = %s, B = %s;
s.onData('projects', A, { background: false });
s.onData('projects', B, { background: true });
out({ pending: s.__get('_pendingData') !== null,
      barShown: document.getElementById('staleDataBar').hidden === false });
"""


def _poll(first, second):
    probe = POLL % (json.dumps(json.dumps(first)), json.dumps(json.dumps(second)))
    return cloud_vm.run(probe)


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class APollSeesAProjectSavedAgainTests(unittest.TestCase):
    def test_a_cloud_only_project_with_a_newer_date_raises_the_bar(self):
        r = _poll(_cloud_only(_cloud(1000)), _cloud_only(_cloud(2000, 150)))
        self.assertTrue(r["barShown"], "a re-saved project left Live silent")
        self.assertTrue(r["pending"])

    def test_a_matched_pair_whose_cloud_side_moved_raises_the_bar(self):
        # Staleness is "cloud_newer" before and after, so only the dates differ.
        r = _poll(_pair(_cloud(1000), _local(500), "cloud_newer"),
                  _pair(_cloud(2000, 150), _local(500), "cloud_newer"))
        self.assertTrue(r["barShown"])

    def test_a_rename_in_the_cloud_raises_the_bar(self):
        r = _poll(_cloud_only(_cloud(1000)),
                  _cloud_only(_cloud(1000, name="Dock A Survey v2")))
        self.assertTrue(r["barShown"])

    def test_nothing_changing_still_raises_nothing(self):
        # The other half: comparing more must not turn every poll into a bar.
        r = _poll(_pair(_cloud(1000), _local()), _pair(_cloud(1000), _local()))
        self.assertFalse(r["barShown"])
        self.assertFalse(r["pending"])


HOLD = r"""
const btn = document.getElementById('liveBtn');
s.startLive();
const running = btn.textContent;
s.__get('selected').add('p:p1');
s.applyLiveUI();
const held = btn.textContent;
s.__get('selected').clear();
s.applyLiveUI();
out({ running, held, released: btn.textContent });
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class LiveSaysWhenItIsHoldingTests(unittest.TestCase):
    def test_a_selection_holds_the_poll_and_the_button_says_so(self):
        r = cloud_vm.run(HOLD)
        self.assertRegex(r["running"], r"^Live ● \d+s$")
        self.assertIn("paused", r["held"])
        self.assertRegex(r["released"], r"^Live ● \d+s$")


if __name__ == "__main__":
    unittest.main()
