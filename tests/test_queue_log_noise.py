"""The launcher window only shows things the user can act on.

waitress logs "Task queue depth is N" at warning level whenever a request
arrives with no idle worker thread. On a single-user local tool that is a
momentary burst - the browser firing parallel requests while one long one holds
a thread - so a depth of 1 means nothing is wrong and nothing can be done about
it. It was reported as a possible fault, which is the cost: the launcher window
stays open while the server runs and is watched.

`_quiet=True` on serve() suppresses only the startup banner, not the loggers,
so the message is filtered at `waitress.queue` instead. Genuine saturation
still gets through, in words.
"""
from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


def record(depth):
    """The record waitress actually emits, argument shape included."""
    return logging.LogRecord(
        name="waitress.queue", level=logging.WARNING, pathname=__file__,
        lineno=1, msg="Task queue depth is %d", args=(depth,), exc_info=None)


class QueueDepthFilter(unittest.TestCase):
    def setUp(self):
        self.filt = server._QueueDepthFilter()

    def test_a_depth_of_one_is_not_shown(self):
        """The reported case. One request waiting is not a fault."""
        self.assertFalse(self.filt.filter(record(1)))

    def test_ordinary_bursts_are_not_shown(self):
        for depth in (2, 3, 5, 9):
            with self.subTest(depth=depth):
                self.assertFalse(self.filt.filter(record(depth)))

    def test_real_saturation_still_gets_through(self):
        self.assertTrue(self.filt.filter(record(server.QUEUE_SATURATION_DEPTH)))
        self.assertTrue(self.filt.filter(record(50)))

    def test_what_gets_through_is_in_words_not_a_counter(self):
        """A number alone tells the user nothing they can act on."""
        rec = record(50)
        self.filt.filter(rec)
        text = rec.getMessage()
        self.assertNotIn("Task queue depth", text)
        self.assertIn("50", text)
        self.assertIn("waiting for a free thread", text)

    def test_a_record_with_no_arguments_is_dropped_not_crashed(self):
        """Defensive: a future waitress could change the call shape."""
        rec = logging.LogRecord(name="waitress.queue", level=logging.WARNING,
                                pathname=__file__, lineno=1,
                                msg="Task queue depth is unknown", args=(),
                                exc_info=None)
        self.assertFalse(self.filt.filter(rec))

    def test_a_non_integer_argument_is_dropped_not_crashed(self):
        rec = record("lots")
        self.assertFalse(self.filt.filter(rec))


class FilterIsActuallyInstalled(unittest.TestCase):
    def test_installing_it_attaches_to_the_waitress_queue_logger(self):
        log = logging.getLogger("waitress.queue")
        before = list(log.filters)
        try:
            server._quieten_queue_warnings()
            self.assertTrue(any(isinstance(f, server._QueueDepthFilter)
                                for f in log.filters))
        finally:
            log.filters = before

    def test_the_threshold_is_not_set_so_low_it_reintroduces_the_noise(self):
        self.assertGreaterEqual(server.QUEUE_SATURATION_DEPTH, 5)


if __name__ == "__main__":
    unittest.main()
