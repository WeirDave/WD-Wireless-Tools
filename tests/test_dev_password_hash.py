"""The dev gate uses WaxFrame Professional's hash, and only the hash.

He asked for one dev password across both products: *"The password should use
the same hash I currently use on WaxFrame Pro."* An earlier build here
generated its own, on the reasoning that a password should not be shared
between two things. That was his call to make and he made it.

So two properties, and neither of them needs the plaintext:

* the constant in `wd-dev.js` is **the same value** as WaxFrame's
  `DEV_PW_HASH` - checked by reading both files, skipped when WaxFrame is not
  on this machine, because CI has no reason to have it;
* **no plaintext anywhere** - not in the source, not in a test, not in a
  fixture. A password that only exists as a digest cannot be leaked by this
  repository, which is the whole point of moving only the hash.

**Both repositories are public**, so this value now appears in two public
places. That is no more exposed than it already was - it is the same hash
either way - but one recovered password opens both products' dev modes rather
than one. The gate is obfuscation, not security: it keeps a curious user out
of a maintenance surface on a localhost-bound server, and anyone with a
console can set the flag directly.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WD_DEV_JS = ROOT / "web" / "assets" / "js" / "wd-dev.js"

#: WaxFrame Professional's checkout, where it sits on his machine. Absent on
#: CI and on anybody else's, hence the skip rather than a failure.
WAXFRAME_APP_JS = (ROOT.parent.parent /
                   "Dropbox" / "Websites" / "02 - Tools and Apps" /
                   "GitHub Projects" / "WaxFrame-Professional" / "js" / "app.js")

HASH_RE = re.compile(r"DEV_PW_HASH\s*=\s*\n?\s*'([0-9a-f]{64})'")


def hash_in(path):
    m = HASH_RE.search(path.read_text(encoding="utf-8", errors="ignore"))
    return m.group(1) if m else None


class TheGateUsesHisSharedHash(unittest.TestCase):

    def test_this_repository_has_one_and_it_is_a_sha256(self):
        found = hash_in(WD_DEV_JS)
        self.assertIsNotNone(found, "no DEV_PW_HASH in wd-dev.js")
        self.assertEqual(len(found), 64)

    @unittest.skipUnless(WAXFRAME_APP_JS.exists(),
                         "WaxFrame Professional is not on this machine")
    def test_it_is_the_same_hash_waxframe_uses(self):
        """The property he asked for. If someone regenerates one of them, the
        two products stop sharing a password and this says so."""
        self.assertEqual(hash_in(WD_DEV_JS), hash_in(WAXFRAME_APP_JS),
                         "the dev password hash has diverged from WaxFrame's")


class ThePlaintextIsNowhere(unittest.TestCase):
    """A hash is safe to publish. The thing it is a hash of is not, and the
    only way to be sure it is not here is to look."""

    #: Where a password would plausibly have been left: the gate itself, the
    #: tests that drive it, and the notes that describe it.
    CANDIDATES = [
        ROOT / "web" / "assets" / "js" / "wd-dev.js",
        ROOT / "web" / "assets" / "js" / "wd-dev-actions.js",
        ROOT / "tests" / "test_dev_toolbar_browser.py",
        ROOT / "tests" / "test_dev_nav_on_every_page.py",
        ROOT / "tests" / "test_dev_password_hash.py",
        ROOT / "CLAUDE.md",
    ]

    def test_no_file_carries_a_password_shaped_assignment(self):
        """Anything that reads as a password being written down. The pattern
        is deliberately broad - a false positive here costs one look, and a
        missed one costs a published secret."""
        pattern = re.compile(
            r"(?i)\b(dev[_ -]?password|devpw|dev[_ -]?pass|password)\s*[=:]\s*"
            r"['\"][^'\"]{3,}['\"]")
        offenders = []
        for path in self.CANDIDATES:
            if not path.exists():
                continue
            for i, line in enumerate(
                    path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if "DEV_PW_HASH" in line:
                    continue          # the hash is the thing that is allowed
                if pattern.search(line):
                    # Name the place, never the value - a CI transcript is as
                    # public as the thing it would be quoting.
                    offenders.append("%s:%d" % (path.name, i))
        self.assertEqual(offenders, [],
                         "these look like a password written down in a public "
                         "repository")

    def test_the_browser_test_still_covers_the_unlock_path(self):
        """Removing the plaintext must not have quietly removed the test that
        needed it. Checked by importing the module and looking at the real
        objects rather than at its text - the ratchet in
        `test_a_test_must_be_able_to_fail.py` is right that a grep over source
        proves only that a string exists."""
        from tests import test_dev_toolbar_browser as browser_tests
        case = browser_tests.ToolbarInABrowser
        for name in ("arm_with_a_known_phrase",
                     "test_a_matching_password_unlocks_it",
                     "test_the_input_is_hashed_rather_than_compared_as_text"):
            self.assertTrue(callable(getattr(case, name, None)),
                            "the browser suite lost %s" % name)
        # And what it types is an invented string, not a recovered secret.
        self.assertIn("invented", browser_tests.TEST_PASSPHRASE)


if __name__ == "__main__":
    unittest.main()
