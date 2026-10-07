"""Run the suite across several processes, one test module at a time.

`python -m unittest discover -s tests` runs ~3,400 tests in one process, one
after another. On a CI runner that was 16-26 minutes per job, and the longest
job was the whole of the wait between a merge and a release. The runners have
three or four cores and used one.

**Each module runs in its own `python -m unittest` process**, and up to
`--jobs` of those run at once, taken longest-first from a queue so the slow
modules start early and the short ones fill the gaps. A module in its own
process cannot inherit state from whichever module happened to run before it,
which is stricter than the single-process run rather than looser: a test that
passed only because an earlier one had reloaded a module fails here, and
`test_capacity_profiles` was one.

**Every worker gets `WD_USER_DIR` from this script.** Under `discover`, the
isolation comes from `test_0_user_dir_isolation.py` sorting first - a module
run on its own has no such ordering, so relying on it here would put a run
one import away from his real `~/.wd_wireless_tools`. The directory is a
fresh one per module, under a root this script removes when it finishes.

**Browser modules go first, and the first one runs alone.** They are the long
pole - about 1,000 seconds between them on a Windows runner against under two
minutes for everything else - and with local timings, where they skip, they
had sorted last and run one at a time: a 19-minute job. Selenium Manager
fetches a driver on first use, and two fetches racing for one cache is a
failure nobody could reproduce, so nothing else that drives a browser starts
until the first browser module has finished. After that up to
`--browser-jobs` run at once (default: one fewer than `--jobs`, leaving a core
for the rest).

Usage::

    python scripts/run_tests.py                 # all modules, one per core
    python scripts/run_tests.py --jobs 1        # serially, same isolation
    python scripts/run_tests.py test_updater test_esx_trimmer
    python scripts/run_tests.py --record tests/durations.json
    python scripts/run_tests.py --browsers-only  # what each browser job runs

`tests/durations.json` only orders the queue. A module missing from it is
treated as slow and started early, so a stale file costs balance, never a
test.
"""
from __future__ import annotations

import argparse
import ast
import functools
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DURATIONS = ROOT / "tests" / "durations.json"

#: Seconds before a single module is stopped and reported as a failure. A
#: hung browser or server would otherwise hold the job until the CI cap
#: cancels it, and a cancelled run says nothing about which module hung.
MODULE_TIMEOUT = 20 * 60

#: Where an unmeasured module goes in the queue: first, with the slow ones.
UNKNOWN = float("inf")


def discover(names: list[str] | None = None, root: Path = ROOT) -> list[str]:
    """Test module names, `test_*` in `tests/`, as `discover` would find."""
    found = sorted(p.stem for p in (root / "tests").glob("test_*.py"))
    if not names:
        return found
    wanted = [n.removeprefix("tests.").removesuffix(".py") for n in names]
    missing = [n for n in wanted if n not in found]
    if missing:
        raise SystemExit("no such test module: " + ", ".join(missing))
    return wanted


#: Imports selenium itself, or runs through a harness that did and says so
#: with `HAVE_SELENIUM` - test_combined_sections_browser is the second kind.
#: Kept for a file that will not parse; `uses_a_browser` reads the syntax tree.
_IMPORTS_SELENIUM = re.compile(
    r"^\s*(?:from|import)\s+selenium\b"
    r"|^\s*HAVE_SELENIUM\s*="
    r"|\.HAVE_SELENIUM\b", re.M)


def _drives_a_browser(tree: ast.AST) -> bool:
    """Whether the syntax tree imports selenium, borrows `HAVE_SELENIUM` from
    another test module, assigns it, or reads it off a harness.

    Read from the tree rather than searched for. The text search matched
    `from selenium import ...` and `HAVE_SELENIUM =` and nothing else, so a
    module that did `from tests.x import HAVE_SELENIUM, _driver` - four of
    them - was not a browser module: the suite jobs switch browsers off, the
    browser jobs run only the modules this returns, and those four ran in no
    job at all, skipping silently on every runner.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] == "selenium" for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "selenium":
                return True
            if any(a.name == "HAVE_SELENIUM" for a in node.names):
                return True
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "HAVE_SELENIUM"
                   for t in targets):
                return True
        elif isinstance(node, ast.Attribute) and node.attr == "HAVE_SELENIUM":
            return True
        elif isinstance(node, ast.Call):
            # A module that gets its browser from `tests/browsers.py` need not
            # import selenium itself. The two that were Firefox-only moved to
            # `browsers.make_driver` and stopped importing it, which would have
            # taken them out of every browser job the same way.
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in _DRIVER_CALLS:
                return True
    return False


#: Calls into `tests/browsers.py` that start a browser.
_DRIVER_CALLS = {"make_driver", "safari_driver"}


@functools.lru_cache(maxsize=None)
def uses_a_browser(module: str, root: Path = ROOT) -> bool:
    """True for a module that drives a browser - not one that merely says
    the word, which a test about this runner has to."""
    text = (root / "tests" / f"{module}.py").read_text(encoding="utf-8",
                                                       errors="replace")
    try:
        return _drives_a_browser(ast.parse(text))
    except SyntaxError:
        return bool(_IMPORTS_SELENIUM.search(text))


def load_durations(path: Path = DURATIONS) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: float(v) for k, v in data.items()
            if isinstance(v, (int, float))}


def order(modules: list[str], durations: dict[str, float],
          browser=lambda m: False) -> list[str]:
    """Browser modules first, then longest first; unmeasured before
    measured; name breaks ties."""
    return sorted(modules, key=lambda m: (not browser(m),
                                          -durations.get(m, UNKNOWN), m))


#: `test_name (tests.module.Class.test_name) ... ok` from `unittest -v`.
_PASSED = re.compile(r"(?:\.\.\. |^)ok\s*$", re.M)
_RAN = re.compile(r"^Ran (\d+) tests? in", re.M)
_SKIPPED = re.compile(r"skipped=(\d+)")


def summarise(output: str) -> tuple[int, int]:
    """(tests run, tests skipped) out of unittest's closing lines."""
    ran = _RAN.findall(output)
    tail = output[output.rfind("\nRan "):] if ran else ""
    skipped = _SKIPPED.search(tail)
    return (int(ran[-1]) if ran else 0,
            int(skipped.group(1)) if skipped else 0)


class Result:
    def __init__(self, module: str, code: int, output: str, seconds: float):
        self.module = module
        self.code = code
        self.output = output
        self.seconds = seconds
        self.ran, self.skipped = summarise(output)
        # Tests that actually passed, read off `unittest -v` lines. Only a
        # verbose run has them; a quiet one reads 0.
        self.passed = len(_PASSED.findall(output))
        # A module that ran tests, skipped none and exited 0 passed them
        # all, whatever the lines looked like: a warning printed mid-test
        # puts "ok" on a line of its own, and Safari run 4 read 18 such
        # modules as having passed nothing.
        if code == 0 and self.ran and not self.skipped:
            self.passed = self.ran

    def __repr__(self) -> str:
        return (f"<{self.module}: exit {self.code}, {self.ran} ran>\n"
                + self.output[-2000:])

    @property
    def ok(self) -> bool:
        return self.code == 0


def run_module(module: str, user_root: Path, verbose: bool,
               timeout: float = MODULE_TIMEOUT, root: Path = ROOT,
               detail: bool = False) -> Result:
    user_dir = user_root / module
    user_dir.mkdir()
    env = {**os.environ, "WD_USER_DIR": str(user_dir),
           "PYTHONIOENCODING": "utf-8"}
    cmd = [sys.executable, "-m", "unittest", f"tests.{module}"]
    if verbose or detail:       # `detail`: wanted for Result.passed, not printed
        cmd.append("-v")
    start = time.monotonic()
    try:
        r = subprocess.run(cmd, cwd=root, env=env, capture_output=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout)
        code, output = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        code = 1
        output = (out + err + f"\n{module} did not finish within "
                  f"{int(timeout)}s and was stopped.\n")
    return Result(module, code, output, time.monotonic() - start)


#: A web server's access line, which unittest's progress characters are
#: interleaved with. A failing browser module's output was 98% of these, and
#: the one assertion that mattered was lines from the end of a 3,000-line log.
_ACCESS_LOG = re.compile(r"^(?P<progress>[.FEsxu]*)\d+\.\d+\.\d+\.\d+ - - \[.*$")


def without_access_log(output: str) -> str:
    """The output with the server's access lines removed and the progress
    characters that shared a line with them kept."""
    kept = []
    for line in output.splitlines():
        m = _ACCESS_LOG.match(line)
        if m is None:
            kept.append(line)
        elif m.group("progress"):
            kept.append(m.group("progress"))
    return "\n".join(kept)


def run_all(modules: list[str], jobs: int, verbose: bool,
            durations: dict[str, float], out=sys.stdout,
            root: Path = ROOT, timeout: float = MODULE_TIMEOUT,
            browser_jobs: int | None = None,
            detail: bool = False) -> list[Result]:
    is_browser = functools.partial(uses_a_browser, root=root)
    queue = order(modules, durations, is_browser)
    lock = threading.RLock()
    limit = max(1, browser_jobs if browser_jobs is not None else jobs - 1)
    browsers = {"running": 0, "done": 0}
    active = {"n": 0}
    results: list[Result] = []

    def take() -> str | None:
        """The next module this worker may start. A browser module waits
        while the first browser module is still running, and after that
        while `limit` are."""
        with lock:
            allowed = 1 if browsers["done"] == 0 else limit
            for i, m in enumerate(queue):
                if not is_browser(m):
                    return queue.pop(i)
                if browsers["running"] < allowed:
                    browsers["running"] += 1
                    return queue.pop(i)
            return None

    def stalled() -> bool:
        """Modules are waiting, none is running, and none can be handed out.
        Nothing will ever change that, so the workers stop and `main`
        reports what never ran - a hang would say nothing at all."""
        with lock:
            return bool(queue) and active["n"] == 0 and take_is_blocked()

    def take_is_blocked() -> bool:
        allowed = 1 if browsers["done"] == 0 else limit
        return all(is_browser(m) for m in queue) and \
            browsers["running"] >= allowed

    def report(res: Result):
        with lock:
            results.append(res)
            state = "ok  " if res.ok else "FAIL"
            skipped = f", {res.skipped} skipped" if res.skipped else ""
            print(f"{state} {res.module}  ({res.ran} tests{skipped}, "
                  f"{res.seconds:.1f}s)", file=out, flush=True)
            if verbose or not res.ok:
                shown = res.output if verbose else without_access_log(res.output)
                print(shown.rstrip(), file=out, flush=True)

    with tempfile.TemporaryDirectory(prefix="wd-tests-userdir-") as users:
        def worker():
            while True:
                with lock:
                    if not queue:
                        return
                with lock:
                    m = take()
                    if m is not None:
                        active["n"] += 1
                if m is None:
                    if stalled():
                        return
                    time.sleep(0.2)
                    continue
                try:
                    report(run_module(m, Path(users), verbose, timeout, root, detail))
                finally:
                    with lock:
                        active["n"] -= 1
                        if is_browser(m):
                            browsers["running"] -= 1
                            browsers["done"] += 1

        threads = [threading.Thread(target=worker, daemon=True)
                   for _ in range(max(1, jobs))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    return results


def drove_nothing(results: list) -> list[str]:
    """Modules that passed without a single test passing.

    In a run that asked for Safari that is a module that never drove Safari,
    and "ok" would say it had - the failure the Safari job exists to prevent.

    It counts tests that **passed**, read from `unittest -v`, not skips against
    runs. A module that builds one class per browser skips the three it cannot
    drive at class level - three skips - however many tests the Safari class
    ran, so `skipped >= ran` flagged two modules that had run 2 and 3 Safari
    tests and passed them. And the earlier `r.ran and ...` let three modules
    through that had run nothing at all (a class skipped in `setUpClass`
    reports "0 tests, 3 skipped" and exits 0).
    """
    return sorted(r.module for r in results if r.ok and r.passed == 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("modules", nargs="*",
                    help="test modules to run (default: all)")
    ap.add_argument("--jobs", "-j", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--browsers-only", action="store_true",
                    help="run only the modules that drive a browser - "
                         "what each per-browser CI job runs")
    ap.add_argument("--browser-jobs", type=int, default=None,
                    help="browser modules at once after the first "
                         "(default: --jobs minus one)")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="print every module's full output, not only "
                         "the failing ones")
    ap.add_argument("--record", metavar="PATH",
                    help="write each module's duration here as JSON")
    a = ap.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    from tests import browsers as _browsers
    safari = _browsers.safari_requested()

    modules = discover(a.modules)
    if a.browsers_only or safari:
        modules = [m for m in modules if uses_a_browser(m)]
    if safari:
        # Safari runs one session at a time per machine and has no headless
        # mode, so the modules go one after another. A run that asked for it
        # and cannot start it is a failure here, not a skip.
        if not _browsers.safari_available():
            print(_browsers.why_missing(), file=sys.stderr)
            return 1
        a.jobs, a.browser_jobs = 1, 1
        for name, why in sorted(_browsers.SAFARI_NOT_APPLICABLE.items()):
            if name in modules:
                modules.remove(name)
                print(f"not run in Safari: {name} - {why}")
    if not modules:
        print("no test modules found", file=sys.stderr)
        return 1

    started = time.monotonic()
    print(f"Running {len(modules)} modules on {a.jobs} worker(s)", flush=True)
    results = run_all(modules, a.jobs, a.verbose, load_durations(),
                      browser_jobs=a.browser_jobs, detail=safari)
    elapsed = time.monotonic() - started

    if a.record:
        Path(a.record).write_text(json.dumps(
            {r.module: round(r.seconds, 2)
             for r in sorted(results, key=lambda r: r.module)},
            indent=1) + "\n", encoding="utf-8")

    failed = sorted(r.module for r in results if not r.ok)
    if safari:
        silent = drove_nothing(results)
        if silent:
            print("DROVE NO SAFARI TEST (every test skipped): "
                  + ", ".join(silent))
        failed = sorted(set(failed) | set(silent))
    lost = sorted(set(modules) - {r.module for r in results})
    ran = sum(r.ran for r in results)
    skipped = sum(r.skipped for r in results)
    print("-" * 70)
    print(f"Ran {ran} tests in {len(results)} modules in {elapsed:.1f}s "
          f"({skipped} skipped)")
    if lost:
        print("NEVER RAN: " + ", ".join(lost))
    if failed:
        print("FAILED: " + ", ".join(failed))
    if failed or lost:
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
