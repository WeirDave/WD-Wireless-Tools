"""A version bump on main is a release. Nothing ships halfway.

"why were commits created with no releases?? that should never happen."

It happened because releasing was something a session had to remember. Main
went red on a test, three sessions correctly held their tags, two were cut
afterwards and one was not; later sessions bumped the version and deliberately
did not tag, on the reasoning that pushing a tag is ceremony to perform only
when asked. Each decision was defensible. The result was three versions of
finished work he could not install while he sat at work fighting the old build.

He installs what is published, so an unreleased commit is not "nearly shipped",
it is invisible - the same problem as uncommitted work in a different hat.

`auto-release.yml` removes the remembering. These assert the properties that
make it safe, because a workflow that is wrong only says so at release time,
which is the worst moment to find out. Every one of them corresponds to
something that has already gone wrong here.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOW = ROOT / ".github" / "workflows"
AUTO = (FLOW / "auto-release.yml").read_text(encoding="utf-8")
RELEASE = (FLOW / "release.yml").read_text(encoding="utf-8")
ASSETS = (FLOW / "release-assets.yml").read_text(encoding="utf-8")


class ABumpOnMainReleasesItselfTests(unittest.TestCase):

    def test_it_runs_on_a_version_change_and_not_on_every_commit(self):
        """Releasing on every push would be its own kind of noise."""
        self.assertIn("branches: [main]", AUTO)
        self.assertIn("web/assets/versions.json", AUTO)
        self.assertIn("paths:", AUTO)

    def test_a_red_suite_produces_no_release(self):
        """The behaviour that already saved three bad tags: main went red and
        the sessions held. That must survive automation, or the automation is
        strictly worse than the habit it replaces."""
        self.assertIn("uses: ./.github/workflows/tests.yml", AUTO)
        self.assertRegex(
            AUTO, r"publish:\s*\n\s*needs: \[decide, tests\]",
            "publishing must depend on the test job, not merely follow it")

    def test_it_tags_the_commit_it_ran_for_rather_than_whatever_main_is_now(self):
        """v2.103.14 landed on another session's commit because a bare `git
        tag` took a HEAD that had moved in the seconds between."""
        self.assertIn("${{ github.sha }}", AUTO)
        self.assertRegex(AUTO, r'git tag -a "\$TAG" -m "\$TAG" "\$sha"')

    def test_it_checks_versions_json_at_the_tag_before_publishing(self):
        """The cheap check from the manual ceremony, kept: it reads what
        `build_release.py` will read, rather than what the workspace holds."""
        self.assertIn('git show "$TAG:web/assets/versions.json"', AUTO)
        self.assertIn('exit 1', AUTO)

    def test_it_does_nothing_when_the_tag_already_exists(self):
        """Idempotent, so a re-run, a revert or a manual release converge
        rather than colliding."""
        self.assertIn('git rev-parse -q --verify "refs/tags/$tag"', AUTO)
        self.assertIn("needed=false", AUTO)
        self.assertIn('gh release view "$TAG"', AUTO)

    def test_two_releases_cannot_run_at_once(self):
        self.assertIn("group: auto-release", AUTO)
        self.assertIn("cancel-in-progress: false", AUTO)


class TheReleaseAlwaysCarriesItsAssetsTests(unittest.TestCase):

    def test_the_assets_are_built_by_the_automatic_path_too(self):
        """**The trap this design exists around.** A release created with
        GITHUB_TOKEN does not fire `release: published` - GitHub suppresses it
        to stop workflows looping. An auto-tagger relying on that event would
        publish a release with no ZIP, and an asset-less release is worse than
        none: the updater and both install scripts refuse a download whose
        checksum does not match, so he ends up stuck rather than out of date.

        So the automatic path calls the packaging workflow directly."""
        self.assertIn("uses: ./.github/workflows/release-assets.yml", AUTO)
        self.assertRegex(AUTO, r"assets:\s*\n\s*needs: \[decide, publish\]")

    def test_the_checksum_ships_with_the_zip(self):
        self.assertIn(".sha256", ASSETS)
        self.assertIn("sha256sum", ASSETS)
        self.assertRegex(ASSETS, r"gh release upload")

    def test_there_is_only_one_implementation_of_the_build(self):
        """Two implementations of one operation is a failure mode this repo has
        already paid for. The build lives in the reusable workflow and both the
        manual and automatic paths call it."""
        builders = [name for name, text in
                    (("auto-release.yml", AUTO), ("release.yml", RELEASE),
                     ("release-assets.yml", ASSETS))
                    if "scripts/build_release.py" in text]
        self.assertEqual(
            ["release-assets.yml"], builders,
            "the release ZIP is built in more than one workflow")

    def test_the_manual_path_still_works_for_a_release_made_by_hand(self):
        """A release published through the GitHub UI, or a backfill, still has
        to get its assets."""
        self.assertIn("types: [published]", RELEASE)
        self.assertIn("workflow_dispatch", RELEASE)
        self.assertIn("uses: ./.github/workflows/release-assets.yml", RELEASE)


class TheAutomaticNoteDoesNotPublishTheCommitMessageTests(unittest.TestCase):
    """A commit message here is a record. A release note is a public page.

    The two documents have different jobs and CLAUDE.md sets them out side
    by side: the commit message quotes the user - *"yes, that is the point"* -
    and the release note never does. The workflow published the commit
    message as the note anyway, and the documented mitigation was to replace
    it by hand every time.

    That does not work, and the file says so: **58 of the first 60 releases
    went out as commit messages**, and an audit of the 60 published notes
    found 34 of them quoting him directly. A default that has to be
    remembered on every release is a default that publishes.

    So the automatic note is a stub. These hold the property rather than the
    wording - the phrasing is free to change, publishing his week is not.
    """

    def _note_step(self) -> str:
        start = AUTO.index("- name: Create the release")
        end = AUTO.index("\n  assets:", start)
        return AUTO[start:end]

    def _note_commands(self) -> str:
        """The step with its shell comments removed.

        The note explaining this change quotes the command it replaced -
        that is the whole point of the note - and a check that fires on its
        own explanation teaches the next session to delete the
        explanation.
        """
        return "\n".join(
            line for line in self._note_step().split("\n")
            if not line.strip().startswith("#"))

    def test_the_commit_message_is_not_written_into_the_note(self):
        self.assertNotIn("git log", self._note_commands(),
                         "the release note is being built from the commit "
                         "message again - see this class's docstring")

    def test_the_note_still_names_the_version(self):
        """A stub that says nothing is its own failure.

        He reads these to work out whether the number on his screen is newer
        or older than the release he is looking at.
        """
        step = self._note_step()
        self.assertIn("${VERSION}", step)

    def test_the_note_points_at_the_commit_for_anybody_who_wants_the_reasoning(self):
        """The reasoning is not deleted, it is left where it belongs."""
        self.assertIn("github.sha", self._note_step())

    def test_a_hand_written_note_still_replaces_it(self):
        self.assertIn("gh release edit", self._note_step())


def _job_permissions(text: str) -> dict:
    """{job name: {scope: level}} out of a workflow, including the default.

    Parsed rather than grepped. `assertIn("contents: read", source)` is true
    of a workflow where *some other* job reads, and it is the assert-on-the-
    text shape `tests/test_a_test_must_be_able_to_fail.py` exists to stop
    spreading. A dict can be asked the question that is actually meant:
    what can *this* job's token do.

    A hand-written reader rather than PyYAML, because PyYAML is not in
    requirements.txt and a test that skips in CI is a test that is not run
    where it matters most.
    """
    out, job, scope, indent = {}, None, None, None
    for raw in text.split("\n"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.strip()
        depth = len(raw) - len(raw.lstrip())

        if depth == 2 and stripped.endswith(":") and job is not None or \
           depth == 2 and stripped.endswith(":"):
            job = stripped[:-1]
            out.setdefault(job, {})
            scope = None
            continue
        if depth == 0 and stripped == "permissions:":
            job, scope, indent = "*", "permissions", 0
            out.setdefault("*", {})
            continue
        if depth == 0:
            job, scope = None, None
            continue
        if stripped == "permissions:":
            scope, indent = "permissions", depth
            continue
        if scope == "permissions":
            if depth <= indent:
                scope = None
            elif ":" in stripped:
                key, _, value = stripped.partition(":")
                target = "*" if job is None else job
                out.setdefault(target, {})[key.strip()] = value.strip()
    return out


class NoJobTakesMorePermissionThanItUsesTests(unittest.TestCase):
    """A job that inherits a write token it never uses is a job whose token
    can do more than the job can."""

    def setUp(self):
        self.auto = _job_permissions(AUTO)
        self.tests_flow = _job_permissions(
            (FLOW / "tests.yml").read_text(encoding="utf-8"))

    def test_the_reader_found_the_jobs(self):
        """A parser that returned nothing would pass every test below."""
        self.assertIn("decide", self.auto)
        self.assertIn("publish", self.auto)

    def test_the_decide_job_only_reads(self):
        """It reads one file and asks whether a tag exists."""
        self.assertEqual("read", self.auto["decide"].get("contents"))

    def test_the_publish_job_can_still_write(self):
        """It pushes a tag and creates a release, so it needs the token."""
        self.assertEqual("write", self.auto["publish"].get("contents"))

    def test_the_test_workflow_never_asks_for_write(self):
        levels = {scope: level
                  for perms in self.tests_flow.values()
                  for scope, level in perms.items()}
        self.assertEqual("read", levels.get("contents"))
        self.assertNotIn("write", levels.values())


if __name__ == "__main__":
    unittest.main()
