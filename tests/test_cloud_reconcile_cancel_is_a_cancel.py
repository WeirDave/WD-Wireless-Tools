"""Removing a queued reconcile says it was cancelled.

An operation removed from the queue before it ran settles as
`{cancelled: true}`. `reconcilePairs` read that as a result with nothing in
it and reported "Nothing needed changing" about pairs nobody had compared.

Driven through the real cloud.js, with the queue settling the way a removed
card does. Every name is invented.
"""
from __future__ import annotations

import unittest

from tests import cloud_vm

PROBE = r"""
s.opEnqueue = () => ({ id: 'op-1', promise: Promise.resolve({ cancelled: true }) });
await s.reconcilePairs([{ cloudId: 'p-1', name: 'Invented Quay' },
                        { cloudId: 'p-2', name: 'Invented Pier' }]);
const bulk = s.toasts.map(t => t[1]).join(' | ');
s.toasts.length = 0;
await s.reconcileNow({ cloudId: 'p-1', name: 'Invented Quay' });
const row = s.toasts.map(t => t[1]).join(' | ');
out({ bulk, row, asked: s.confirms.length });
"""


@unittest.skipUnless(cloud_vm.HAVE_NODE, "node is not installed")
class ACancelIsReportedAsACancelTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = cloud_vm.run(PROBE)

    def test_the_bulk_check_says_cancelled(self):
        self.assertIn("ancelled", self.r["bulk"])
        self.assertNotIn("Nothing needed changing", self.r["bulk"])
        self.assertEqual(0, self.r["asked"], "a cancelled check went on to ask")

    def test_the_row_says_cancelled(self):
        self.assertIn("ancelled", self.r["row"])
        self.assertNotIn("Nothing needed changing", self.r["row"])


if __name__ == "__main__":
    unittest.main()
