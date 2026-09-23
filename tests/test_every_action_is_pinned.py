"""A tag is a pointer somebody else can move; a workflow must not follow one.

**`uses: actions/checkout@v6` is not a version, it is a name.** Whoever can
move that tag runs code inside a job that has a checkout of this repository and
a token, on every push and every release. The tag is not required to keep
pointing where it pointed yesterday, and nothing in a run tells anyone it
moved. A commit SHA cannot be moved by anybody.

Nine `uses:` across five workflows named tags until this file existed. Four of
those workflows are on the release path - `tests.yml` decides whether a release
publishes at all, `auto-release.yml` tags and publishes it, `release-assets.yml`
builds the ZIP the installers verify by checksum - so an action swapped
underneath them reaches the artifact people download.

**Pinning alone is only half of it, and the other half is why this file also
asks about Dependabot.** A tag quietly picks up the upstream security fix; a
SHA does not. An unattended pin drifts behind every advisory against that
action and nothing says so, which trades one silent exposure for another.
`.github/dependabot.yml` is what keeps the pins moving, and it understands the
`@<sha>  # vX.Y.Z` form specifically - it rewrites the comment along with the
SHA, which is why the comment is part of the convention and not decoration.

**A local reusable workflow is exempt, and deliberately so.**
`uses: ./.github/workflows/tests.yml` resolves inside this repository at the
commit being run; there is no third party to pin and a SHA would name this
repo's own history. The reader has to tell the two apart, so it is tested on
both.

The reader parses rather than searches, for the reason the rest of this suite
does: the explanatory comments in these workflows name actions and versions in
prose, so a substring assertion would pass on a comment while the step it
guards was gone.
"""
from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WORKFLOWS = ROOT / ".github" / "workflows"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"

#: A git commit SHA as Actions accepts it: full, lowercase, forty hex digits.
#: An abbreviated SHA is refused here on purpose - Actions will resolve one,
#: and a short prefix is a weaker statement about which commit is meant.
SHA = re.compile(r"^[0-9a-f]{40}$")

#: `# v6.1.0`, the version the pinned commit was released as. Dependabot reads
#: and rewrites this, and a person reading the file has nothing else to go on.
VERSION_COMMENT = re.compile(r"^v\d+\.\d+\.\d+$")


def action_refs(path: Path) -> list[dict]:
    """Every `uses:` in one workflow, as `{file, line, target, ref, version}`.

    `target` is what precedes the `@` - an action's `owner/name`, or a path
    beginning `./` for a workflow in this repository. `ref` is what follows it,
    and is `None` for a local workflow, which takes no ref. `version` is the
    trailing `# vX.Y.Z` comment where there is one.

    A line whose first non-space character is `#` is a comment and is dropped
    before anything is matched. That is the distinction a substring search
    cannot make, and these workflows are full of prose naming actions.
    """
    out: list[dict] = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if raw.lstrip().startswith("#"):
            continue
        m = re.match(r"^\s*(?:-\s+)?uses:\s*(\S+)\s*(?:#\s*(\S+))?\s*$", raw)
        if not m:
            continue
        spec, comment = m.group(1), m.group(2)
        target, _, ref = spec.partition("@")
        out.append({"file": path.name, "line": n, "target": target,
                    "ref": ref or None, "version": comment})
    return out


def every_ref() -> list[dict]:
    refs: list[dict] = []
    for f in sorted(WORKFLOWS.glob("*.yml")):
        refs += action_refs(f)
    return refs


def dependabot_ecosystems(path: Path = DEPENDABOT) -> list[str]:
    """The `package-ecosystem` values in dependabot.yml, comments dropped.

    A deliberately small reader rather than a YAML dependency, matching
    `workflow_steps` in `test_ci_runs_the_node_tests`. That file's own comment
    explains at length why `pip` is not there, so a substring search for
    "github-actions" would also match the prose about it.
    """
    if not path.exists():
        return []
    found = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.lstrip().startswith("#"):
            continue
        m = re.match(r'^\s*-?\s*package-ecosystem:\s*"?([\w-]+)"?\s*$', raw)
        if m:
            found.append(m.group(1))
    return found


class TheReaderTellsAPinFromAComment(unittest.TestCase):
    """The reader is load-bearing, so it is tested before it is trusted."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="wd-pin-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _write(self, text: str) -> Path:
        f = self.dir / "w.yml"
        f.write_text(text, encoding="utf-8")
        return f

    def test_a_commented_out_uses_is_not_a_uses(self):
        f = self._write(
            "jobs:\n"
            "  a:\n"
            "    steps:\n"
            "      # uses: actions/checkout@v1\n"
            "      - uses: actions/checkout@" + "a" * 40 + "  # v9.9.9\n")
        refs = action_refs(f)
        self.assertEqual([r["ref"] for r in refs], ["a" * 40],
                         "the commented line was read as a step: %r" % (refs,))

    def test_the_version_comment_is_read_and_not_swallowed(self):
        f = self._write("      - uses: actions/setup-node@" + "b" * 40
                        + "  # v4.4.0\n")
        self.assertEqual(action_refs(f)[0]["version"], "v4.4.0")

    def test_a_local_workflow_has_no_ref(self):
        f = self._write("    uses: ./.github/workflows/tests.yml\n")
        got = action_refs(f)[0]
        self.assertEqual(got["target"], "./.github/workflows/tests.yml")
        self.assertIsNone(got["ref"])

    def test_a_tag_is_read_as_the_tag_it_is(self):
        """The reader must not normalise away the thing the next class
        rejects."""
        f = self._write("      - uses: actions/checkout@v6\n")
        self.assertEqual(action_refs(f)[0]["ref"], "v6")


class TheWorkflowsAreActuallyBeingRead(unittest.TestCase):
    """Liveness. Every assertion below is vacuous on an empty list, and a
    renamed directory or a changed `uses:` spelling empties it silently."""

    def test_the_workflow_directory_holds_the_release_path(self):
        names = {f.name for f in WORKFLOWS.glob("*.yml")}
        for expected in ("tests.yml", "auto-release.yml",
                         "release-assets.yml", "pages.yml"):
            self.assertIn(expected, names)

    def test_both_kinds_of_uses_are_present(self):
        refs = every_ref()
        external = [r for r in refs if not r["target"].startswith("./")]
        local = [r for r in refs if r["target"].startswith("./")]
        self.assertGreaterEqual(len(external), 9,
                                "found %d external actions; the reader has "
                                "stopped seeing them" % len(external))
        self.assertTrue(local, "no local reusable-workflow call was found, so "
                               "the exemption below is being tested against "
                               "nothing")


class EveryExternalActionNamesACommit(unittest.TestCase):

    def test_no_uses_follows_a_tag_or_a_branch(self):
        bad = ["%s:%d %s@%s" % (r["file"], r["line"], r["target"], r["ref"])
               for r in every_ref()
               if not r["target"].startswith("./")
               and not SHA.match(r["ref"] or "")]
        self.assertEqual(
            bad, [],
            "these follow a pointer somebody else can move; pin each to the "
            "commit SHA the tag points at today, with the version beside it "
            "as a comment:\n  " + "\n  ".join(bad))

    def test_every_pin_says_which_version_it_is(self):
        bare = ["%s:%d %s@%s" % (r["file"], r["line"], r["target"],
                                 (r["ref"] or "")[:8])
                for r in every_ref()
                if SHA.match(r["ref"] or "")
                and not VERSION_COMMENT.match(r["version"] or "")]
        self.assertEqual(
            bare, [],
            "a forty-character SHA tells a reader nothing about what it is, "
            "and Dependabot rewrites this comment along with the SHA:\n  "
            + "\n  ".join(bare))

    def test_a_local_reusable_workflow_is_left_alone(self):
        """The exemption, asserted rather than assumed. A future rule that
        pinned everything would have to name this repository's own commit in
        its own workflow, which pins a file to a version of itself."""
        for r in every_ref():
            if r["target"].startswith("./"):
                self.assertIsNone(
                    r["ref"],
                    "%s:%d pins a workflow that lives in this repository"
                    % (r["file"], r["line"]))


class SomethingKeepsThePinsMoving(unittest.TestCase):
    """A pin nobody updates is a pin behind every later security fix."""

    def test_dependabot_watches_the_actions(self):
        self.assertTrue(DEPENDABOT.exists(),
                        "the actions are pinned and nothing updates them: "
                        "%s is missing" % DEPENDABOT.relative_to(ROOT))
        self.assertIn("github-actions", dependabot_ecosystems(),
                      "dependabot.yml exists but does not watch the actions")

    def test_the_reader_would_notice_an_empty_config(self):
        d = Path(tempfile.mkdtemp(prefix="wd-dep-"))
        self.addCleanup(shutil.rmtree, d, True)
        f = d / "dependabot.yml"
        f.write_text('# package-ecosystem: "github-actions"\nversion: 2\n',
                     encoding="utf-8")
        self.assertEqual(dependabot_ecosystems(f), [],
                         "a commented-out ecosystem was read as a live one")


if __name__ == "__main__":
    unittest.main()
