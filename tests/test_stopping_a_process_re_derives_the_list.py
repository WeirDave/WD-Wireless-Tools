"""A stop request names a process. It does not authorise killing it.

**The finding.** ``/api/dev/housekeeping_stop`` was::

    "housekeeping_stop": lambda d: {
        "ok": True,
        "stopped": [pid for pid in (d.get("pids") or [])
                    if housekeeping.stop_process(pid)]},

Every id in the request body went straight to ``taskkill /PID <n> /F``. No
check that the id was one of ours, that it was still the process the survey
had seen, or that it was a process this tool has any business stopping. Its
neighbour ``housekeeping_sweep`` does the opposite and says so in its
docstring - *"the list is re-derived, not trusted"* - so the rule already
existed here and this one action was outside it.

What that is worth, concretely: a page holding process ids from a survey taken
an hour ago can kill whatever now wears those numbers - his browser with a
day of tabs in it, Ekahau with unsaved work, a system service. Nothing about
the request has to be hostile. Windows reuses process ids, and the endpoint
never asked a second time.

So ``stop_processes`` re-derives from a fresh ``list_processes()`` and refuses
anything not on it, reporting the refusal rather than returning quietly - a
stop that silently did nothing reads as a stop that worked.

Nothing here touches a real process: the survey and the killer are both
injected, which is the same seam ``list_processes`` and ``stop_process``
already carried for the tests that came before.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import housekeeping

#: What a fresh survey reports. Shaped the way `list_processes` really
#: returns it, because that is what `stop_processes` reads.
OURS = [
    {"pid": 4242, "name": "geckodriver.exe",
     "why": "A WebDriver executable, started by a test run."},
    {"pid": 4243, "name": "firefox.exe",
     "why": "A headless browser - not a window he has open."},
]


class Recorder:
    """A killer that records instead of killing."""

    def __init__(self, fails=()):
        self.killed = []
        self.fails = set(fails)

    def __call__(self, pid):
        self.killed.append(pid)
        return pid not in self.fails


class OnlyWhatTheSurveyStillFinds(unittest.TestCase):

    def test_a_pid_the_survey_knows_is_stopped(self):
        killer = Recorder()
        out = housekeeping.stop_processes([4242], processes=OURS, killer=killer)
        self.assertEqual([4242], killer.killed)
        self.assertEqual(1, out["counts"]["stopped"])
        self.assertEqual(4242, out["stopped"][0]["pid"])

    def test_a_pid_the_survey_does_not_know_is_never_killed(self):
        """The finding itself.

        4 is `System` on Windows. Under the old endpoint this call reached
        `taskkill /F` on it.
        """
        killer = Recorder()
        out = housekeeping.stop_processes([4], processes=OURS, killer=killer)
        self.assertEqual([], killer.killed,
                         "a pid the survey never reported was passed to the killer")
        self.assertEqual(0, out["counts"]["stopped"])
        self.assertEqual(1, out["counts"]["skipped"])

    def test_the_refusal_says_why(self):
        out = housekeeping.stop_processes([4], processes=OURS, killer=Recorder())
        self.assertEqual(4, out["skipped"][0]["pid"])
        self.assertIn("not something this found",
                      out["skipped"][0]["reason"].lower())

    def test_one_bad_pid_does_not_take_the_good_ones_with_it(self):
        """A batch is not all-or-nothing, and the report says which was which."""
        killer = Recorder()
        out = housekeeping.stop_processes([4242, 4, 4243],
                                          processes=OURS, killer=killer)
        self.assertEqual([4242, 4243], killer.killed)
        self.assertEqual(2, out["counts"]["stopped"])
        self.assertEqual(1, out["counts"]["skipped"])

    def test_a_pid_that_has_gone_between_survey_and_stop_is_skipped(self):
        """The race the re-derivation exists for.

        The page offers 4242 because a survey saw it; by the time the button
        is pressed it has exited and something else may hold that number.
        """
        killer = Recorder()
        out = housekeeping.stop_processes([4242], processes=[OURS[1]],
                                          killer=killer)
        self.assertEqual([], killer.killed)
        self.assertEqual(1, out["counts"]["skipped"])

    def test_an_empty_request_stops_nothing(self):
        killer = Recorder()
        for empty in ([], None):
            out = housekeeping.stop_processes(empty, processes=OURS,
                                              killer=killer)
            self.assertEqual([], killer.killed)
            self.assertEqual(0, out["counts"]["stopped"])

    def test_a_pid_that_is_not_a_number_is_refused_rather_than_raising(self):
        """A traceback out of a dev action is a wall of red for a typo."""
        killer = Recorder()
        for junk in ("; shutdown", None, {"pid": 4242}, "4242abc"):
            with self.subTest(pid=repr(junk)):
                out = housekeeping.stop_processes([junk], processes=OURS,
                                                  killer=killer)
                self.assertEqual([], killer.killed)
                self.assertEqual(1, out["counts"]["skipped"])

    def test_a_numeric_string_naming_a_real_one_still_works(self):
        """JSON carries numbers, but a page can send "4242" and mean it."""
        killer = Recorder()
        out = housekeeping.stop_processes(["4242"], processes=OURS,
                                          killer=killer)
        self.assertEqual([4242], killer.killed)
        self.assertEqual(1, out["counts"]["stopped"])

    def test_a_kill_that_fails_is_reported_rather_than_counted_as_stopped(self):
        killer = Recorder(fails={4242})
        out = housekeeping.stop_processes([4242], processes=OURS, killer=killer)
        self.assertEqual(0, out["counts"]["stopped"])
        self.assertEqual(1, out["counts"]["failed"])
        self.assertEqual(4242, out["failed"][0]["pid"])


class TheEndpointGoesThroughIt(unittest.TestCase):
    """The route, not just the function.

    The bug was in the lambda in `server.py`, so a test of `housekeeping`
    alone would have passed either way. This drives the dispatcher the
    request really reaches.
    """

    def test_the_dev_action_calls_stop_processes(self):
        import server
        calls = {}

        def fake(pids, **kw):
            calls["pids"] = list(pids)
            return {"ok": True, "stopped": [], "skipped": [], "failed": [],
                    "counts": {"stopped": 0, "skipped": 0, "failed": 0}}

        original = server.housekeeping.stop_processes
        server.housekeeping.stop_processes = fake
        try:
            out = server.DEV_ACTIONS["housekeeping_stop"]({"pids": [1, 2, 3]})
        finally:
            server.housekeeping.stop_processes = original

        self.assertEqual([1, 2, 3], calls.get("pids"),
                         "the endpoint did not route through stop_processes")
        self.assertTrue(out["ok"])

    def test_the_endpoint_does_not_reach_stop_process_directly(self):
        """The single-process killer takes no decisions and must not be the door.

        If this ever fails, the endpoint has gone back to handing raw ids to
        `taskkill`.
        """
        import server
        reached = []
        original = server.housekeeping.stop_process
        server.housekeeping.stop_process = lambda pid, killer=None: reached.append(pid)
        survey = server.housekeeping.list_processes
        server.housekeeping.list_processes = lambda *a, **k: []
        try:
            server.DEV_ACTIONS["housekeeping_stop"]({"pids": [4, 4242]})
        finally:
            server.housekeeping.stop_process = original
            server.housekeeping.list_processes = survey

        self.assertEqual(
            [], reached,
            "the endpoint reached the killer for ids no survey reported")


if __name__ == "__main__":
    unittest.main()
