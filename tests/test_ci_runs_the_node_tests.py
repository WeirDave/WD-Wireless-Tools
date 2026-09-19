"""Half the suite is gated on node, so CI has to prove node was there.

**1,069 of 2,173 test methods sit behind
`@unittest.skipUnless(shutil.which("node"), ...)`** - 57 files that slice the
real render functions out of `cloud.js` and `report.js` and execute them,
which is the pattern the whole "a test that would pass with the feature
deleted is not a test" section asks for. That guard is right on a developer's
machine: no node, no probe, and the rest of the suite still means something.

It is a hole in CI, and it was an open one. Nothing in `tests.yml` installed
node; those tests ran because `windows-latest` and `macos-latest` happen to
ship it. A runner image change would have skipped **half the suite** and
reported green - the same shape as a test that cannot fail, one level up, and
with nothing to read in the transcript but a slightly smaller number. The
audit on 2026-09-18 recorded it as a systemic finding and it stayed open.

Two halves, because either alone is insufficient:

* **`test_ci_has_node` runs only on a runner** and is the one that would
  actually have caught it. A skip is an acceptable answer on a laptop and
  never on the build everybody trusts.
* **The workflow checks run everywhere**, including on a machine with no node,
  because reading the pipeline is the only way to check it off a runner.

**Those workflow checks parse the steps rather than searching the text**, and
that is not ceremony. `assertIn("actions/setup-node", yaml)` passes on the
*comment* in `tests.yml` that explains why the step is there - so the
substring form would have survived deleting the very step it exists to
protect. `workflow_steps()` returns what the runner will actually execute.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

#: GitHub Actions sets this on every runner. It is the only signal that
#: separates "a developer without node" from "the build everyone trusts".
IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"


def workflow_steps(path: Path = WORKFLOW) -> list[dict]:
    """The steps the runner will execute, in order, as `{name, uses, with}`.

    A deliberately small reader rather than a YAML dependency - the suite has
    none, and the shape needed here is one flat list. What it has to get right
    is the thing a substring search gets wrong: **a `#` comment is not a
    step**, so the key/value lines are taken only from inside a `- ` item and
    every comment line is dropped first.
    """
    steps: list[dict] = []
    cur: dict | None = None
    in_steps = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.lstrip().startswith("#"):
            continue
        if re.match(r"^\s*steps:\s*$", raw):
            in_steps = True
            continue
        if not in_steps:
            continue
        # A new step, or the end of the steps block.
        item = re.match(r"^(\s*)-\s+(\w[\w-]*):\s*(.*)$", raw)
        if item:
            cur = {item.group(2): item.group(3).strip()}
            steps.append(cur)
            continue
        kv = re.match(r"^\s+(\w[\w-]*):\s*(.*)$", raw)
        if kv and cur is not None:
            cur.setdefault(kv.group(1), kv.group(2).strip())
    return steps


class TheReaderTellsAStepFromAComment(unittest.TestCase):
    """The parser is load-bearing, so it is tested before it is trusted."""

    def test_a_commented_out_step_is_not_a_step(self):
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="wd-yaml-"))
        self.addCleanup(__import__("shutil").rmtree, d, True)
        f = d / "w.yml"
        f.write_text(
            "jobs:\n  test:\n    steps:\n"
            "      # uses: actions/setup-node@v4 - explaining, not doing\n"
            "      - name: Real step\n        uses: actions/checkout@v6\n",
            encoding="utf-8")
        steps = workflow_steps(f)
        self.assertEqual(1, len(steps), steps)
        self.assertEqual("actions/checkout@v6", steps[0]["uses"])


class NodeIsPresentWhereItIsExpected(unittest.TestCase):

    @unittest.skipUnless(IN_CI, "only CI is expected to have node")
    def test_ci_has_node(self):
        """The one that would have caught it.

        If this fails, roughly half the suite around it did not run and said
        nothing about it.
        """
        self.assertIsNotNone(
            shutil.which("node"),
            "node is missing on a CI runner, so every node-gated test skipped "
            "silently and this run proves far less than it appears to. Check "
            "the 'Set up Node.js' step in .github/workflows/tests.yml.")


class TheWorkflowInstallsNode(unittest.TestCase):

    def setUp(self):
        self.steps = workflow_steps()
        self.node = [s for s in self.steps
                     if s.get("uses", "").startswith("actions/setup-node")]

    def test_a_step_installs_node(self):
        self.assertTrue(
            self.node,
            "tests.yml has no setup-node step. Every node-gated test will "
            "skip on any runner image that stops shipping node, and the suite "
            "will stay green while proving half as much. Steps found: "
            + ", ".join(s.get("name", "?") for s in self.steps))

    def test_a_node_version_is_pinned(self):
        """`setup-node` with no version resolves to whatever the image has,
        which is the thing being fixed rather than a fix for it."""
        self.assertTrue(self.node, "no setup-node step at all")
        self.assertRegex(
            str(self.node[0].get("node-version", "")), r"^['\"]?\d+",
            "setup-node pins no version, so the runner image still decides "
            "which node runs.")

    def test_node_is_installed_before_the_suite_runs(self):
        """Order is the whole point: a setup step after the test step is a
        step that did nothing for this run."""
        names = [s.get("name", "") for s in self.steps]
        self.assertIn("Run safety suite", names, names)
        self.assertTrue(self.node, "no setup-node step at all")
        node_at = self.steps.index(self.node[0])
        self.assertLess(
            node_at, names.index("Run safety suite"),
            "node is installed after the suite runs, so the suite ran "
            "without it.")


class EveryNodeTestSkipsRatherThanCrashing(unittest.TestCase):
    """The guard has to stay a *skip* locally, or this fix trades one problem
    for a worse one: a developer with no node getting 57 files of errors."""

    def test_every_file_that_shells_out_to_node_guards_the_call(self):
        gated, ungated = [], []
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            if path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if not re.search(r"""["']node["']|node -e""", text):
                continue
            (gated if 'which("node")' in text else ungated).append(path.name)

        self.assertEqual(
            [], ungated,
            "these files run node without checking it exists, so a developer "
            "without node gets errors instead of skips: " + ", ".join(ungated))
        self.assertGreater(len(gated), 40,
                           "far fewer node-driven test files than expected - "
                           "has the detection above drifted?")


if __name__ == "__main__":
    unittest.main()
