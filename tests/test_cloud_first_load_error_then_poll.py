"""A first-load error followed by a good background poll leaves a list to draw.

`onData` keeps drawing what the reader is looking at when an unrequested poll
brings something different: `data = _drawnData`. After a failed first load
nothing has ever been drawn, so `_drawnData` is null, and the next successful
poll set `data` to null. Typing in the search box then threw inside the
renderers, which read `data.matched`.

Driven through the real cloud.js (`tests/cloud_vm.py`). Every name is invented.
"""
from __future__ import annotations

import unittest

from tests import cloud_vm


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class AGoodPollAfterAFailedFirstLoadIsDrawn(unittest.TestCase):

    PROBE = r"""
s.__set('currentTab', 'projects');
const good = JSON.stringify({ currentUser: 'pat@example.invalid',
  matched: [], cloudOnly: [{ id: 'uuid-n', name: 'Invented November' }],
  localOnly: [], orphans: { cloudOnly: [] } });

// The first load fails: nothing has ever been drawn.
s.onData('projects', JSON.stringify({ error: 'the account could not be read' }), {});
const afterError = s.__get('data');

// Then a poll he did not ask for succeeds.
s.onData('projects', good, { background: true });
const afterPoll = s.__get('data');

// Typing in the search box re-renders from `data`.
let threw = null;
try { s.renderRows(); } catch (err) { threw = String(err && err.message || err); }

out({ errorShapeIsSafe: !!(afterError && Array.isArray(afterError.matched)),
      dataIsNull: afterPoll === null,
      drewThePoll: !!(afterPoll && (afterPoll.cloudOnly || []).length === 1),
      threw });
"""

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(cls.PROBE)

    def test_the_error_leaves_a_shape_the_renderers_can_read(self):
        self.assertTrue(self.r["errorShapeIsSafe"], self.r)

    def test_the_poll_is_drawn_rather_than_discarded(self):
        self.assertFalse(self.r["dataIsNull"], self.r)
        self.assertTrue(self.r["drewThePoll"], self.r)

    def test_a_re_render_afterwards_does_not_throw(self):
        self.assertIsNone(self.r["threw"], self.r)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
