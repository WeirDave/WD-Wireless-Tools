"""A browser that disappears mid-run is run again once; a finding never is.

Firefox gates a release, and on a shared Windows runner its window sometimes
goes away under the driver: the test raises `NoSuchWindowError`, the module
fails, and a finished version stays unpublished until someone re-runs the job
by hand. Nothing in that says our code is wrong.

`scripts/run_tests.py` therefore runs a **browser** module again, once, when
every failure in it is an error carrying a driver-went-away signature. The
other half matters as much: one assertion failure, one error of any other
kind, or a module that simply timed out is a result, and is reported as it is.
These tests run the real runner on a throwaway project rather than reading its
source.
"""
from __future__ import annotations

import io
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.run_tests as run_tests  # noqa: E402

BAR = "=" * 70
RULE = "-" * 70


def failure(kind: str, test: str, tail: str) -> str:
    return (f"{BAR}\n{kind}: {test} (tests.x.Y.{test})\n{RULE}\n"
            f"Traceback (most recent call last):\n  File \"x.py\", line 1, in t\n{tail}\n")


WINDOW_GONE = failure("ERROR", "test_a", "selenium.common.exceptions.NoSuchWindowException: "
                      "Message: Browsing context has been discarded")
FIREFOX_STACK = failure("ERROR", "test_b", "selenium.common.exceptions.WebDriverException: "
                        "RemoteError@chrome://remote/content/shared/RemoteError.sys.mjs:8:8\n"
                        "NoSuchWindowError@chrome://remote/content/shared/webdriver/Errors.sys.mjs:781:5")
WRONG = failure("FAIL", "test_c", "AssertionError: 'a' != 'b'")
OTHER_ERROR = failure("ERROR", "test_d", "KeyError: 'floorPlans'")
TAIL = f"{RULE}\nRan 3 tests in 1.0s\n\nFAILED (errors=1)\n"


class WhatCountsAsALostBrowser(unittest.TestCase):

    def test_a_window_that_went_away_does_(self):
        self.assertTrue(run_tests.browser_went_away(WINDOW_GONE + TAIL))

    def test_firefoxs_own_stack_does_(self):
        self.assertTrue(run_tests.browser_went_away(FIREFOX_STACK + TAIL))

    def test_several_lost_windows_together_do_(self):
        self.assertTrue(run_tests.browser_went_away(WINDOW_GONE + FIREFOX_STACK + TAIL))

    def test_one_wrong_answer_among_them_does_not(self):
        self.assertFalse(run_tests.browser_went_away(WINDOW_GONE + WRONG + TAIL))

    def test_one_error_of_another_kind_among_them_does_not(self):
        self.assertFalse(run_tests.browser_went_away(WINDOW_GONE + OTHER_ERROR + TAIL))

    def test_an_assertion_alone_does_not(self):
        self.assertFalse(run_tests.browser_went_away(WRONG + TAIL))

    def test_output_with_no_failure_in_it_does_not(self):
        """A module stopped for taking too long prints no failure block."""
        self.assertFalse(run_tests.browser_went_away(
            "tests.x did not finish within 1200s and was stopped.\n"))


def project(tmp: Path, body: str) -> Path:
    """A throwaway project whose one browser module has the given tests."""
    (tmp / "tests").mkdir()
    (tmp / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (tmp / "tests" / "test_fake_browser.py").write_text(
        "import unittest\nHAVE_SELENIUM = True\n" + textwrap.dedent(body), encoding="utf-8")
    return tmp


class TheRunnerRetriesOnlyThat(unittest.TestCase):

    def run_it(self, body: str):
        run_tests.uses_a_browser.cache_clear()
        with tempfile.TemporaryDirectory(prefix="wd-retry-") as t:
            root = project(Path(t), body)
            out = io.StringIO()
            results = run_tests.run_all(["test_fake_browser"], 1, False, {}, out=out,
                                        root=root, timeout=120)
            return results, out.getvalue()

    def test_a_window_lost_on_the_first_attempt_is_run_again_and_passes(self):
        results, said = self.run_it("""
            from pathlib import Path
            MARK = Path(__file__).with_name("seen")

            class T(unittest.TestCase):
                def test_it(self):
                    if not MARK.exists():
                        MARK.write_text("x")
                        raise Exception("NoSuchWindowError: the window was closed")
        """)
        self.assertEqual([r.ok for r in results], [True], said)
        self.assertIn("RETRY test_fake_browser", said, "the retry has to be visible in the log")
        self.assertIn("NoSuchWindowError", said, "the first attempt's evidence is kept")
        self.assertIn("passed on its second attempt", said)

    def test_a_lost_window_both_times_is_still_a_failure(self):
        results, said = self.run_it("""
            class T(unittest.TestCase):
                def test_it(self):
                    raise Exception("NoSuchWindowError: the window was closed")
        """)
        self.assertEqual([r.ok for r in results], [False], said)
        self.assertEqual(said.count("RETRY test_fake_browser"), 1, "once, not until it passes")

    def test_a_wrong_answer_is_never_run_again(self):
        results, said = self.run_it("""
            class T(unittest.TestCase):
                def test_it(self):
                    self.assertEqual(1, 2)
        """)
        self.assertEqual([r.ok for r in results], [False], said)
        self.assertNotIn("RETRY", said)

    def test_a_module_that_is_not_a_browser_module_is_never_run_again(self):
        run_tests.uses_a_browser.cache_clear()
        with tempfile.TemporaryDirectory(prefix="wd-retry-") as t:
            root = Path(t)
            (root / "tests").mkdir()
            (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (root / "tests" / "test_plain.py").write_text(textwrap.dedent("""
                import unittest

                class T(unittest.TestCase):
                    def test_it(self):
                        raise Exception("NoSuchWindowError: mentioned, not a browser")
            """), encoding="utf-8")
            out = io.StringIO()
            results = run_tests.run_all(["test_plain"], 1, False, {}, out=out,
                                        root=root, timeout=120)
        self.assertEqual([r.ok for r in results], [False])
        self.assertNotIn("RETRY", out.getvalue())


if __name__ == "__main__":
    unittest.main()
