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


if __name__ == "__main__":
    unittest.main()
