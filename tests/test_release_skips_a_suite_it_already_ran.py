"""A release does not re-run a suite that already passed on the same tree.

Every version bump used to run the full four-job suite inside
`auto-release.yml`, after the pull request carrying it had already run the
same suite on the same code. That second run was about 27 minutes and was the
whole of the wait between a merge and a release.

Skipping it is only safe while two things stay true, and these tests execute
both rather than read them:

* `scripts/tested_head.py` names a commit only when the tree being released is
  provably the tree a pull request tested - it is run against real git
  histories built here;
* the `publish` job still refuses a red suite. Its `if:` is evaluated against
  every combination of test result and "already tested", because an `if:` is
  the whole guard and a wrong `||` in it would publish a failing build.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tested_head import candidate  # noqa: E402

FLOW = ROOT / ".github" / "workflows" / "auto-release.yml"


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ("git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main",
         *args),
        cwd=cwd, capture_output=True, encoding="utf-8")
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return r.stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class TheCandidateIsOnlyATreeThatWasTestedTests(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        _git(self.repo, "init", "-q")
        self._commit("a.txt", "base\n", "base")

    def _commit(self, name: str, text: str, msg: str) -> str:
        (self.repo / name).write_text(text, encoding="utf-8")
        _git(self.repo, "add", name)
        _git(self.repo, "commit", "-q", "-m", msg)
        return _git(self.repo, "rev-parse", "HEAD")

    def test_a_merge_of_a_branch_that_already_contained_main_names_the_branch(self):
        """The ordinary shape here: the session merged main into its PR, CI
        went green on that head, and the merge added nothing."""
        _git(self.repo, "checkout", "-q", "-b", "pr")
        head = self._commit("b.txt", "feature\n", "feature")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "merge", "-q", "--no-ff", "-m", "Merge PR", "pr")
        merge = _git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(candidate(merge, cwd=self.repo), head)

    def test_a_merge_after_main_moved_names_nothing(self):
        """Main moved after the PR's run, so the merged tree was never
        tested as a whole - the suite has to run."""
        _git(self.repo, "checkout", "-q", "-b", "pr")
        self._commit("b.txt", "feature\n", "feature")
        _git(self.repo, "checkout", "-q", "main")
        self._commit("c.txt", "someone else\n", "other work")
        _git(self.repo, "merge", "-q", "--no-ff", "-m", "Merge PR", "pr")
        merge = _git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(candidate(merge, cwd=self.repo), "")

    def test_the_same_tree_without_main_in_its_history_names_nothing(self):
        """A merge whose tree happens to equal the branch's while the branch
        never contained main - an `-s ours`-style merge. The PR's run tested
        merge(main, head), not head, so equal trees are not enough."""
        _git(self.repo, "checkout", "-q", "-b", "pr")
        head = self._commit("b.txt", "feature\n", "feature")
        _git(self.repo, "checkout", "-q", "main")
        main = self._commit("c.txt", "someone else\n", "other work")
        tree = _git(self.repo, "rev-parse", f"{head}^{{tree}}")
        forged = _git(self.repo, "commit-tree", tree, "-p", main, "-p", head,
                      "-m", "merge keeping the branch's tree")
        self.assertEqual(candidate(forged, cwd=self.repo), "")

    def test_a_merge_that_changed_something_itself_names_nothing(self):
        """The branch contained main, but the merge commit carries an edit
        of its own - a conflict resolution, say. That edit was never tested."""
        base = _git(self.repo, "rev-parse", "HEAD")
        _git(self.repo, "checkout", "-q", "-b", "pr")
        head = self._commit("b.txt", "feature\n", "feature")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "merge", "-q", "--no-ff", "--no-commit", "pr")
        (self.repo / "b.txt").write_text("edited in the merge\n",
                                         encoding="utf-8")
        _git(self.repo, "add", "b.txt")
        _git(self.repo, "commit", "-q", "-m", "Merge PR with an edit")
        merge = _git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(_git(self.repo, "rev-parse", f"{merge}^1"), base)
        self.assertEqual(candidate(merge, cwd=self.repo), "")

    def test_a_single_parent_commit_is_its_own_candidate(self):
        """A fast-forward or a direct push. Only a PR run recorded against
        this exact commit can vouch for it, which the workflow then asks."""
        sha = self._commit("b.txt", "direct\n", "direct push")
        self.assertEqual(candidate(sha, cwd=self.repo), sha)

    def test_an_unknown_commit_names_nothing(self):
        self.assertEqual(candidate("0" * 40, cwd=self.repo), "")


def _job_block(text: str, job: str) -> str:
    m = re.search(rf"(?m)^  {job}:\n(.*?)(?=^  \S|\Z)", text, re.S)
    if not m:
        raise AssertionError(f"job {job!r} not found in auto-release.yml")
    return m.group(1)


def _if_expression(block: str) -> str:
    m = re.search(r"(?ms)^    if: (?:>-\n)?\s*(.*?)(?=^    \S)", block)
    if not m:
        raise AssertionError("job has no if:")
    expr = " ".join(m.group(1).split())
    inner = re.fullmatch(r"\$\{\{(.*)\}\}", expr)
    return (inner.group(1) if inner else expr).strip()


def _evaluate(expr: str, needs: dict) -> bool:
    """Evaluate a GitHub `if:` over `needs` - just the grammar these use."""
    def lookup(m):
        job, rest = m.group(1), m.group(2)
        if rest == "result":
            return repr(needs[job]["result"])
        return repr(needs[job]["outputs"].get(rest.split(".", 1)[1], ""))
    py = re.sub(r"needs\.(\w+)\.(result|outputs\.\w+)", lookup, expr)
    py = py.replace("!cancelled()", "True").replace("&&", " and ") \
           .replace("||", " or ")
    if re.search(r"!(?!=)|\$|\bneeds\b", py):
        raise AssertionError(f"cannot evaluate {expr!r}")
    return bool(eval(py, {"__builtins__": {}}, {}))


class ARedSuiteStillPublishesNothingTests(unittest.TestCase):

    def setUp(self):
        text = FLOW.read_text(encoding="utf-8")
        self.tests_if = _if_expression(_job_block(text, "tests"))
        self.publish_if = _if_expression(_job_block(text, "publish"))
        self.assets_if = _if_expression(_job_block(text, "assets"))

    @staticmethod
    def _needs(tests: str, tested: str) -> dict:
        return {"decide": {"result": "success",
                           "outputs": {"needed": "true", "tested": tested}},
                "tests": {"result": tests, "outputs": {}}}

    def test_the_suite_runs_unless_the_tree_was_already_tested(self):
        runs = lambda tested: _evaluate(self.tests_if, self._needs("", tested))
        self.assertTrue(runs("false"))
        self.assertTrue(runs(""))
        self.assertFalse(runs("true"))

    def test_publishing_follows_a_green_suite_or_a_proven_earlier_one(self):
        for tests in ("success", "failure", "cancelled", "skipped"):
            for tested in ("true", "false"):
                with self.subTest(tests=tests, tested=tested):
                    want = tests == "success" or (
                        tests == "skipped" and tested == "true")
                    self.assertEqual(
                        _evaluate(self.publish_if, self._needs(tests, tested)),
                        want)

    def test_nothing_publishes_when_no_release_is_needed(self):
        needs = self._needs("skipped", "true")
        needs["decide"]["outputs"]["needed"] = "false"
        self.assertFalse(_evaluate(self.publish_if, needs))

    def test_the_assets_follow_the_release_whether_or_not_the_suite_ran(self):
        for publish in ("success", "failure", "skipped"):
            with self.subTest(publish=publish):
                self.assertEqual(
                    _evaluate(self.assets_if,
                              {"publish": {"result": publish, "outputs": {}}}),
                    publish == "success")


def _step_script(text: str, name: str) -> str:
    start = text.index(f"- name: {name}")
    run = text.index("run: |\n", start) + len("run: |\n")
    lines = []
    for line in text[run:].splitlines():
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line[10:])
    return "\n".join(lines) + "\n"


@unittest.skipIf(os.name == "nt", "`bash` on a Windows runner can be WSL's")
@unittest.skipUnless(shutil.which("bash"), "bash is not installed")
class TheDecisionFallsTowardTestingTests(unittest.TestCase):
    """Runs the real step, with `python` and `gh` standing in as functions."""

    def _decide(self, head: str, gh: str) -> str:
        script = _step_script(FLOW.read_text(encoding="utf-8"),
                              "Was this exact tree already tested on its pull request?")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.write_text("", encoding="utf-8")
            prelude = (f"python() {{ printf '%s' '{head}'; }}\n"
                       f"gh() {{ {gh}; }}\n")
            r = subprocess.run(
                ["bash", "-c", "set -eo pipefail\n" + prelude + script],
                env={**os.environ, "GITHUB_OUTPUT": str(out),
                     "SHA": "a" * 40, "REPO": "example/repo",
                     "GH_TOKEN": "unused"},
                capture_output=True, encoding="utf-8")
            if r.returncode != 0:
                raise AssertionError((r.stdout + r.stderr).strip())
            return out.read_text(encoding="utf-8").strip()

    def test_a_successful_pull_request_run_skips_the_suite(self):
        self.assertEqual(self._decide("b" * 40, "echo 1"), "tested=true")

    def test_no_successful_run_means_the_suite_runs(self):
        self.assertEqual(self._decide("b" * 40, "echo 0"), "tested=false")

    def test_no_candidate_means_the_suite_runs_without_asking(self):
        self.assertEqual(self._decide("", "echo 1"), "tested=false")

    def test_an_api_failure_means_the_suite_runs(self):
        self.assertEqual(self._decide("b" * 40, "return 1"), "tested=false")

    def test_an_answer_that_is_not_a_count_means_the_suite_runs(self):
        self.assertEqual(self._decide("b" * 40, "echo '{\"message\":\"x\"}'"),
                         "tested=false")


if __name__ == "__main__":
    unittest.main()
