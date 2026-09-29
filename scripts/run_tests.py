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

`tests/durations.json` only orders the queue. A module missing from it is
treated as slow and started early, so a stale file costs balance, never a
test.
"""
from __future__ import annotations

import argparse
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
_IMPORTS_SELENIUM = re.compile(
    r"^\s*(?:from|import)\s+selenium\b"
    r"|^\s*HAVE_SELENIUM\s*="
    r"|\.HAVE_SELENIUM\b", re.M)


@functools.lru_cache(maxsize=None)
def uses_a_browser(module: str, root: Path = ROOT) -> bool:
    """True for a module that drives a browser - not one that merely says
    the word, which a test about this runner has to."""
    text = (root / "tests" / f"{module}.py").read_text(encoding="utf-8",
                                                       errors="replace")
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

    def __repr__(self) -> str:
        return (f"<{self.module}: exit {self.code}, {self.ran} ran>\n"
                + self.output[-2000:])

    @property
    def ok(self) -> bool:
        return self.code == 0


def run_module(module: str, user_root: Path, verbose: bool,
               timeout: float = MODULE_TIMEOUT, root: Path = ROOT) -> Result:
    user_dir = user_root / module
    user_dir.mkdir()
    env = {**os.environ, "WD_USER_DIR": str(user_dir),
           "PYTHONIOENCODING": "utf-8"}
    cmd = [sys.executable, "-m", "unittest", f"tests.{module}"]
    if verbose:
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


def run_all(modules: list[str], jobs: int, verbose: bool,
            durations: dict[str, float], out=sys.stdout,
            root: Path = ROOT, timeout: float = MODULE_TIMEOUT,
            browser_jobs: int | None = None) -> list[Result]:
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
                print(res.output.rstrip(), file=out, flush=True)

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
                    report(run_module(m, Path(users), verbose, timeout, root))
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("modules", nargs="*",
                    help="test modules to run (default: all)")
    ap.add_argument("--jobs", "-j", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--browser-jobs", type=int, default=None,
                    help="browser modules at once after the first "
                         "(default: --jobs minus one)")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="print every module's full output, not only "
                         "the failing ones")
    ap.add_argument("--record", metavar="PATH",
                    help="write each module's duration here as JSON")
    a = ap.parse_args(argv)

    modules = discover(a.modules)
    if not modules:
        print("no test modules found", file=sys.stderr)
        return 1

    started = time.monotonic()
    print(f"Running {len(modules)} modules on {a.jobs} worker(s)", flush=True)
    results = run_all(modules, a.jobs, a.verbose, load_durations(),
                      browser_jobs=a.browser_jobs)
    elapsed = time.monotonic() - started

    if a.record:
        Path(a.record).write_text(json.dumps(
            {r.module: round(r.seconds, 2)
             for r in sorted(results, key=lambda r: r.module)},
            indent=1) + "\n", encoding="utf-8")

    failed = sorted(r.module for r in results if not r.ok)
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
