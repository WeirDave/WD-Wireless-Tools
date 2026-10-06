"""CI runs the browser tests once, and runs the rest of the suite in parallel.

Both changes shorten the wait for a release, and each can break something
worth more than the minutes saved. So every test here runs the real thing:
the workflow's switch is evaluated for every matrix combination,
`tests.browsers` is asked about a browser that really is on `PATH`, and
`scripts/run_tests.py` is run against modules written here.

* **The browser tests still run, each browser exactly once.** They are the
  suite's standard of proof, and they have already been silently absent from
  CI once, for four releases. The suite jobs switch them off, which is only
  safe while the browser jobs, taken together, drive each browser once.
* **A parallel run still isolates the user directory.** Under `discover`,
  `test_0_user_dir_isolation.py` does that by sorting first. A module run on
  its own gets no such ordering, so the runner has to supply it, and a lapse
  would point the suite at his real `~/.wd_wireless_tools`.
* **A failing, crashing or hung module fails the run.** A runner that
  reported green over a module it never finished would be worse than the
  slow one it replaced.
* **Browser modules go first; the first runs alone**, then no more than the
  limit run at once, and everything else runs alongside them.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_tests as run_tests  # noqa: E402
from tests import browsers  # noqa: E402
from tests.test_ci_runs_the_node_tests import workflow_steps  # noqa: E402
from tools import user_dir as ud  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


def _jobs(text: str) -> dict[str, list[str]]:
    """Each job in the workflow, as its lines with comments dropped."""
    lines = [l for l in text.splitlines() if not l.lstrip().startswith("#")]
    at = lines.index("jobs:")
    jobs: dict[str, list[str]] = {}
    name = None
    for line in lines[at + 1:]:
        m = re.match(r"^  ([\w-]+):\s*$", line)
        if m:
            name = m.group(1)
            jobs[name] = []
        elif name and line.strip():
            jobs[name].append(line)
    return jobs


def _value(block: list[str], key: str) -> str | None:
    for line in block:
        m = re.match(rf"^\s+{re.escape(key)}:\s*(.*?)\s*$", line)
        if m:
            return m.group(1).strip("'\"")
    return None


def _matrix(block: list[str]) -> dict[str, list[str]]:
    out, inside = {}, False
    for line in block:
        if re.match(r"^\s+matrix:\s*$", line):
            inside = True
            continue
        if inside:
            m = re.match(r"^\s{8}([\w-]+):\s*\[(.*)\]\s*$", line)
            if not m:
                break
            out[m.group(1)] = [v.strip().strip("'\"")
                               for v in m.group(2).split(",")]
    return out


def _resolve(value: str | None, combo: dict) -> str | None:
    """A literal, or `${{ matrix.x }}` - the only two shapes allowed here."""
    if value is None:
        return None
    m = re.fullmatch(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}", value)
    if m:
        return combo[m.group(1)]
    if "${{" in value:
        raise AssertionError(f"cannot evaluate {value!r}")
    return value


def _runs(text: str) -> list[dict]:
    """One entry per job the workflow will start: its name, the runner it
    lands on, the browser switch, and which browsers it may drive."""
    out = []
    for name, block in _jobs(text).items():
        matrix = _matrix(block)
        combos = [{}]
        for key, values in matrix.items():
            combos = [dict(c, **{key: v}) for c in combos for v in values]
        for combo in combos:
            switch = _resolve(_value(block, "WD_BROWSER_TESTS"), combo)
            only = _resolve(_value(block, "WD_BROWSERS"), combo)
            browsers_ = ({b.strip() for b in only.split(",")} if only
                         else {"firefox", "chrome", "edge"})
            out.append({"job": name, "combo": combo,
                        "runs_on": _resolve(_value(block, "runs-on"), combo),
                        "switch": switch, "browsers": browsers_})
    return out


class EachBrowserIsTestedExactlyOnce(unittest.TestCase):
    """The workflow, expanded job by job and combination by combination."""

    def setUp(self):
        self.runs = _runs(WORKFLOW.read_text(encoding="utf-8"))

    def test_the_jobs_were_read(self):
        """Every assertion below is vacuous over an empty list."""
        jobs = {r["job"] for r in self.runs}
        self.assertEqual(jobs, {"test", "browsers", "safari"}, self.runs)
        self.assertEqual(sum(r["job"] == "test" for r in self.runs), 4)

    def test_every_job_says_on_or_off(self):
        """An empty value reads as "on" to `tests.browsers`, so a missing
        switch would quietly put the browsers back in every suite job."""
        for r in self.runs:
            self.assertIn(r["switch"], ("on", "off"), r)

    def test_the_suite_jobs_drive_no_browser(self):
        for r in self.runs:
            if r["job"] == "test":
                self.assertEqual(r["switch"], "off", r)

    def test_each_browser_is_driven_by_exactly_one_job(self):
        driven = [b for r in self.runs if r["switch"] == "on"
                  for b in r["browsers"]]
        self.assertEqual(sorted(driven), ["chrome", "edge", "firefox", "safari"],
                         self.runs)

    def test_every_job_that_drives_a_browser_is_on_windows_but_safari(self):
        """What he runs, and where a browser difference would matter to him.
        Safari exists only on macOS, so its job is the one exception."""
        for r in self.runs:
            if r["switch"] != "on":
                continue
            want = "macos-latest" if r["browsers"] == {"safari"} else "windows-latest"
            self.assertEqual(r["runs_on"], want, r)


class TheSafariJobCannotPassByDrivingNothing(unittest.TestCase):
    """Safari is opt-in, so a job that asks for it has to be able to fail.

    Safari is not in `triple()`: every test module builds its drivers from
    that list and falls through to Edge for a name it does not know, so
    listing it there would start Edge under Safari's name. It is requested by
    `WD_BROWSERS` instead, and the job names the modules that handle it.
    """

    def setUp(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.block = _jobs(text)["safari"]
        self.script = "\n".join(self.block)

    def test_the_job_asks_for_safari_and_for_nothing_else(self):
        self.assertEqual(_value(self.block, "WD_BROWSERS"), "safari")
        self.assertEqual(_value(self.block, "WD_BROWSER_TESTS"), "on")

    def test_it_enables_safaris_webdriver_before_it_runs_anything(self):
        enable = self.script.index("safaridriver --enable")
        self.assertLess(enable, self.script.index("scripts/run_tests.py"))

    def test_it_names_modules_that_exist_and_know_how_to_drive_safari(self):
        run = re.search(r"python scripts/run_tests\.py ([\w \-]+)$", self.script, re.M)
        self.assertIsNotNone(run, self.script)
        names = [n for n in run.group(1).split() if not n.startswith("-")]
        self.assertTrue(names, "the Safari job names no module, so it runs everything and skips most")
        for name in names:
            f = ROOT / "tests" / f"{name}.py"
            self.assertTrue(f.is_file(), name)
            self.assertIn("safari_available", f.read_text(encoding="utf-8"), name)

    def test_safari_is_never_part_of_the_default_list(self):
        self.assertEqual([k for k, _ in browsers.triple()],
                         ["firefox", "chrome", "edge"])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(browsers.ONLY, None)
            self.assertFalse(browsers.safari_requested())
            self.assertFalse(browsers.safari_available())
            self.assertNotIn("safari", browsers.available())

    def test_asking_for_it_is_what_requests_it(self):
        with mock.patch.dict(os.environ, {browsers.SWITCH: "on",
                                          browsers.ONLY: "safari"}):
            self.assertTrue(browsers.safari_requested())
        with mock.patch.dict(os.environ, {browsers.SWITCH: "on",
                                          browsers.ONLY: "firefox,chrome"}):
            self.assertFalse(browsers.safari_requested())
        with mock.patch.dict(os.environ, {browsers.SWITCH: "off",
                                          browsers.ONLY: "safari"}):
            self.assertFalse(browsers.safari_requested())

    def test_it_is_available_only_on_a_mac_with_the_driver_present(self):
        env = {browsers.SWITCH: "on", browsers.ONLY: "safari"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(Path, "is_file", return_value=True):
            with mock.patch.object(sys, "platform", "darwin"):
                self.assertTrue(browsers.safari_available())
            with mock.patch.object(sys, "platform", "win32"):
                self.assertFalse(browsers.safari_available())
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(Path, "is_file", return_value=False):
            self.assertFalse(browsers.safari_available())
            self.assertIn(browsers.SAFARIDRIVER, browsers.why_missing())

    def test_a_run_that_asked_for_safari_and_cannot_drive_it_fails(self):
        """The thing the whole job exists to prevent: green with Safari never
        started. Run the real test class with Safari asked for and absent."""
        import importlib.util
        if importlib.util.find_spec("selenium") is None:
            self.skipTest("selenium is not installed")
        from tests import test_ap_labeler_spacing_browser as mod
        with mock.patch.dict(os.environ, {browsers.SWITCH: "on",
                                          browsers.ONLY: "safari"}), \
                mock.patch.object(sys, "platform", "linux"):
            suite = unittest.TestSuite([mod.TypingIntoLineSpacingInSafariTests(
                "test_auto_draws_the_breaks_between_rows")])
            result = unittest.TestResult()
            suite.run(result)
        self.assertEqual(len(result.failures), 1, (result.failures, result.skipped, result.errors))
        self.assertEqual(result.skipped, [])


class TheSwitchReachesEveryBrowserTest(unittest.TestCase):
    """Driven with a browser that really is on `PATH`, so a switch that
    did nothing would be seen finding it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bindir = Path(tmp.name)
        for name in ("firefox", "firefox.bat"):
            f = bindir / name
            f.write_text("#!/bin/sh\n", encoding="utf-8")
            f.chmod(f.stat().st_mode | stat.S_IXUSR)
        self.path = str(bindir) + os.pathsep + os.environ.get("PATH", "")

    def test_with_the_switch_unset_the_browser_is_found(self):
        env = {k: v for k, v in os.environ.items() if k != browsers.SWITCH}
        env["PATH"] = self.path
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(browsers.installed("firefox"))

    def test_switched_off_no_browser_is_found(self):
        with mock.patch.dict(os.environ, {"PATH": self.path,
                                          browsers.SWITCH: "off"}):
            self.assertEqual(browsers.available(), [])
            for kind, binary in browsers.triple():
                self.assertFalse(Path(binary).exists(), kind)
            self.assertIn(browsers.SWITCH, browsers.why_missing())

    def test_a_browser_left_out_of_the_list_is_not_found(self):
        with mock.patch.dict(os.environ, {"PATH": self.path,
                                          browsers.SWITCH: "on",
                                          browsers.ONLY: "chrome"}):
            self.assertFalse(browsers.installed("firefox"))
            self.assertIn(browsers.ONLY, browsers.why_missing())

    def test_a_browser_in_the_list_is_found(self):
        with mock.patch.dict(os.environ, {"PATH": self.path,
                                          browsers.SWITCH: "on",
                                          browsers.ONLY: "firefox"}):
            self.assertTrue(browsers.installed("firefox"))

    def test_on_means_on(self):
        with mock.patch.dict(os.environ, {"PATH": self.path,
                                          browsers.SWITCH: "on"}):
            self.assertTrue(browsers.installed("firefox"))


class TheSuiteStepUsesTheRunner(unittest.TestCase):

    def test_the_safety_suite_step_runs_the_parallel_runner(self):
        steps = {s.get("name"): s for s in workflow_steps(WORKFLOW)}
        self.assertIn("Run safety suite", steps)
        self.assertEqual(steps["Run safety suite"].get("run"),
                         "python scripts/run_tests.py")

    def test_the_browser_jobs_run_only_the_browser_modules(self):
        steps = {s.get("name"): s for s in workflow_steps(WORKFLOW)}
        self.assertEqual(steps["Run browser tests"].get("run"),
                         "python scripts/run_tests.py --browsers-only")

    def test_browsers_only_selects_exactly_the_browser_modules(self):
        """Run through `main`, so the flag is proved to reach the queue."""
        seen = []
        with mock.patch.object(run_tests, "run_all",
                               lambda mods, *a, **k: seen.extend(mods) or []), \
                contextlib.redirect_stdout(io.StringIO()):
            run_tests.main(["--browsers-only"])
        self.assertTrue(seen)
        self.assertEqual(sorted(seen), sorted(
            m for m in run_tests.discover() if run_tests.uses_a_browser(m)))

    def test_the_runner_finds_every_test_file(self):
        """`discover` runs every `test_*.py`; a runner that found fewer
        would drop them without failing."""
        self.assertEqual(run_tests.discover(),
                         sorted(p.stem for p in (ROOT / "tests").glob("test_*.py")))


class TheRunnerTests(unittest.TestCase):
    """`scripts/run_tests.py` against modules written here."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "tests").mkdir()
        (self.root / "tests" / "__init__.py").write_text("", encoding="utf-8")
        self.log = self.root / "log"
        self.log.mkdir()

    def _module(self, name: str, body: str) -> str:
        (self.root / "tests" / f"{name}.py").write_text(
            textwrap.dedent(body), encoding="utf-8")
        return name

    def _run(self, modules, jobs=4, timeout=run_tests.MODULE_TIMEOUT,
             browser_jobs=None):
        out = io.StringIO()
        results = run_tests.run_all(modules, jobs, False, {}, out=out,
                                    root=self.root, timeout=timeout,
                                    browser_jobs=browser_jobs)
        return {r.module: r for r in results}, out.getvalue()

    def _recorder(self, name: str, sleep: float, browser: bool) -> str:
        marker = "HAVE_SELENIUM = False  # stands in for a browser test" \
            if browser else ""
        return self._module(name, f"""
            {marker}
            import os, time, unittest
            from pathlib import Path

            class T(unittest.TestCase):
                def test_it(self):
                    log = Path({str(self.log)!r})
                    (log / "{name}.start").write_text(repr(time.time()))
                    time.sleep({sleep})
                    (log / "{name}.end").write_text(repr(time.time()))
                    (log / "{name}.dir").write_text(os.environ["WD_USER_DIR"])
            """)

    def _span(self, name: str) -> tuple[float, float]:
        return (float((self.log / f"{name}.start").read_text()),
                float((self.log / f"{name}.end").read_text()))

    def test_every_module_gets_its_own_user_directory(self):
        mods = [self._recorder(f"test_m{i}", 0, False) for i in range(3)]
        results, _ = self._run(mods)
        self.assertTrue(all(r.ok for r in results.values()), results)
        dirs = [Path((self.log / f"{m}.dir").read_text()) for m in mods]
        self.assertEqual(len(set(dirs)), 3, dirs)
        for d in dirs:
            self.assertNotEqual(d, ud.DEFAULT)
            self.assertNotEqual(d.parent, ud.DEFAULT)
            self.assertFalse(d.exists(), "the run left %s behind" % d)

    def test_a_directory_set_by_the_caller_is_not_the_one_used(self):
        """Even with `WD_USER_DIR` already pointing somewhere, each module
        gets a fresh one - two modules sharing a directory can see each
        other's writes."""
        mod = self._recorder("test_given", 0, False)
        with mock.patch.dict(os.environ, {"WD_USER_DIR": str(self.root)}):
            self._run([mod])
        self.assertNotEqual(
            Path((self.log / "test_given.dir").read_text()), self.root)

    def test_modules_run_at_the_same_time(self):
        mods = [self._recorder(f"test_p{i}", 1.0, False) for i in range(2)]
        self._run(mods)
        (a0, a1), (b0, b1) = self._span(mods[0]), self._span(mods[1])
        self.assertLess(max(a0, b0), min(a1, b1),
                        "the two modules ran one after the other")

    @staticmethod
    def _overlap(a, b) -> bool:
        return max(a[0], b[0]) < min(a[1], b[1])

    def test_with_one_browser_job_no_two_browser_modules_overlap(self):
        mods = [self._recorder(f"test_b{i}", 0.7, True) for i in range(3)]
        mods.append(self._recorder("test_plain", 0.7, False))
        results, _ = self._run(mods, browser_jobs=1)
        self.assertTrue(all(r.ok for r in results.values()), results)
        spans = sorted(self._span(m) for m in mods[:3])
        for (_, end), (start, _) in zip(spans, spans[1:]):
            self.assertLessEqual(end, start, spans)
        plain = self._span("test_plain")
        self.assertTrue(any(self._overlap(plain, s) for s in spans),
                        "a plain module waited for the browser modules")

    def test_the_first_browser_module_runs_alone(self):
        """Selenium Manager fetches drivers on first use; nothing else that
        drives a browser may start until that first one is done."""
        mods = [self._recorder(f"test_b{i}", 0.7, True) for i in range(3)]
        results, _ = self._run(mods, browser_jobs=3)
        self.assertTrue(all(r.ok for r in results.values()), results)
        spans = sorted(self._span(m) for m in mods)
        first_end = spans[0][1]
        for start, _ in spans[1:]:
            self.assertGreaterEqual(start, first_end, spans)

    def test_after_the_first_they_share_the_runner(self):
        mods = [self._recorder(f"test_b{i}", 1.0, True) for i in range(3)]
        self._run(mods, jobs=4, browser_jobs=2)
        spans = sorted(self._span(m) for m in mods)
        self.assertTrue(self._overlap(spans[1], spans[2]),
                        "browser modules still ran one at a time: %s" % spans)

    def test_never_more_browser_modules_than_the_limit(self):
        mods = [self._recorder(f"test_b{i}", 0.8, True) for i in range(5)]
        self._run(mods, jobs=4, browser_jobs=2)
        spans = [self._span(m) for m in mods]
        for t in sorted({s for s, _ in spans}):
            running = sum(1 for s, e in spans if s <= t < e)
            self.assertLessEqual(running, 2, spans)

    def test_browser_modules_are_queued_first(self):
        got = run_tests.order(["test_a", "test_b_browser", "test_c"],
                              {"test_a": 90.0, "test_b_browser": 1.0},
                              lambda m: m.endswith("browser"))
        self.assertEqual(got[0], "test_b_browser")

    def test_saying_the_word_is_not_driving_a_browser(self):
        """This file names selenium in prose; it must not be queued, and
        serialised, as though it opened one."""
        self.assertFalse(run_tests.uses_a_browser(Path(__file__).stem))
        self.assertTrue(run_tests.uses_a_browser("test_dev_toolbar_browser"))
        self.assertTrue(run_tests.uses_a_browser(
            "test_combined_sections_browser"))

    def test_a_failing_module_fails_and_its_output_is_printed(self):
        mod = self._module("test_red", """
            import unittest
            class T(unittest.TestCase):
                def test_it(self):
                    self.assertEqual(1, 2, "the deliberate failure")
            """)
        results, out = self._run([mod])
        self.assertFalse(results[mod].ok)
        self.assertIn("the deliberate failure", out)

    def test_a_module_that_cannot_import_fails(self):
        mod = self._module("test_broken", "import no_such_module_anywhere\n")
        results, _ = self._run([mod])
        self.assertFalse(results[mod].ok)

    def test_a_hung_module_is_stopped_and_fails(self):
        mod = self._module("test_hung", """
            import time, unittest
            class T(unittest.TestCase):
                def test_it(self):
                    time.sleep(30)
            """)
        results, out = self._run([mod], timeout=2)
        self.assertFalse(results[mod].ok)
        self.assertIn("did not finish", out)

    def test_counts_come_from_the_module_output(self):
        mod = self._module("test_counted", """
            import unittest
            class T(unittest.TestCase):
                def test_a(self): pass
                def test_b(self): pass
                @unittest.skip("x")
                def test_c(self): pass
            """)
        results, _ = self._run([mod])
        self.assertEqual((results[mod].ran, results[mod].skipped), (3, 1))


class TheQueueOrderTests(unittest.TestCase):

    def test_longest_first_and_unmeasured_before_measured(self):
        got = run_tests.order(["a", "b", "c", "new"],
                              {"a": 1.0, "b": 9.0, "c": 5.0})
        self.assertEqual(got, ["new", "b", "c", "a"])

    def test_a_missing_or_broken_durations_file_is_no_durations(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bad = Path(tmp.name) / "d.json"
        bad.write_text("{not json", encoding="utf-8")
        self.assertEqual(run_tests.load_durations(bad), {})
        self.assertEqual(run_tests.load_durations(Path(tmp.name) / "no"), {})


if __name__ == "__main__":
    unittest.main()
