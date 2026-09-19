"""Nothing traceable to a real workplace, person or site may be committed.

This exists because it went wrong. A real site code sat in the shipped UI as
the worked example for Cloud Manager's site-code match - readable on screen by
every person who installed the tool, and packaged into every release ZIP. A
real building and city, a real Ekahau Cloud project name and a second site code
sat in release notes. The repository is public, so all of it was published.

**The rule is in CLAUDE.md. This file is what makes the rule hold.**

The design point worth keeping: the first audit searched a *list of known
names* and missed every one of those, because they were not on the list. What
found them was enumerating every token of the shape and reading all of them.
So that is what these tests do - they assert that the set of identifier-shaped
strings in the repository is a subset of an allowlist of obviously invented
ones, and fail on anything new.

That has two consequences, both deliberate:

* The tests name no real site, person or company. Listing what to look for
  would put the very thing being protected into a public file.
* A genuinely new placeholder makes a test fail. That is not friction to route
  around - it is the check working. Add it to the allowlist below *after*
  confirming it is invented, and the failure has done its job.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Test support, kept beside the test rather than in tools/, which ships.
sys.path.insert(0, str(ROOT / "tests"))
import history_scan  # noqa: E402

#: Vendored third-party bundles. Minified code throws off every heuristic here
#: - an AWS key prefix once turned up as a mangled variable name in pdf.js -
#: and it is not ours to edit anyway.
SKIP_DIRS = ("web/assets/lib/",)
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp",
                 ".tif", ".tiff", ".pdf", ".zip", ".esx", ".woff", ".woff2",
                 ".ttf", ".otf", ".mo", ".pyc")

#: Placeholder site/building codes. Every one is invented. **Do not add a real
#: one to make a test pass** - that is the failure this file exists to catch.
ALLOWED_CODE_TOKENS = {
    "SITE1", "SITE2", "SITE3", "SITE4", "SITE5", "SITE9", "SITE42",
    "TEST1", "TEST2", "TEST3", "TEST4", "TEST5",
    "ACME1", "ACME2",
    "FLR1", "FLR2", "FLR3",
    "BLDG01",        # invented, and deliberately generic: it is the building
                     # part of the AP names in the synthetic report-sweep
                     # fixture, quoted in the comments that explain what the
                     # aim table used to print on top of itself.
    "ABCD1", "ABCD7", "WXYZ9",  # invented, and deliberately unmistakable:
                     # they are consecutive letters of the alphabet. The
                     # housekeeping scanner's fixtures need tokens of the
                     # site-code *shape* to prove it flags them, so these
                     # exist precisely to be matched by a detector.
                     # `ABCD1` names the fixture site in the long-path and
                     # detail-band tests, where the whole point is a
                     # project named after its site and long enough to cross
                     # Windows' 260-character limit.
}

#: Published names of standards and formats. They are the shape of a site
#: code and they are not one, and prose about the software uses them - the
#: release-note audit found one in a sentence about drag events.
#:
#: **Only a published name of a standard or format goes in here.** Anything
#: that is merely "probably fine" is a finding, and a real site code added to
#: make a test pass is the failure this file exists to catch.
#:
#: Kept as its own set rather than mixed in above, because the list of
#: invented placeholders and the list of real technical terms answer
#: different questions and only one of them is ours to invent. It is unioned
#: into ALLOWED_CODE_TOKENS below, so both the tree scan and
#: scripts/audit_release_notes.py clear them from one place.
ALLOWED_TECHNICAL_TERMS = {
    "UTF8",          # an encoding, not a site
    "IPV4",          # a protocol, not a site - and it is this file's own
                     # regex constant, so the scan reads its own source and
                     # flags it. Allowlisting beats exempting this file:
                     # a checker that skips itself is a checker with a hole.
    "HTML5",         # a markup standard, in a note about drag events
}

ALLOWED_CODE_TOKENS |= ALLOWED_TECHNICAL_TERMS

#: Reserved-for-documentation domains (RFC 2606) plus the generic stand-in.
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net",
                         "example.invalid", "company.com"}

#: RFC 2606 reserves these top-level domains as well, and they can never be
#: registered - so an address at one cannot be traceable to a real employer,
#: which is the only question this file asks. `.test` was added when the
#: housekeeping scanner needed a fixture domain that is plainly a stand-in and
#: is *not* on its own documentation-domain list, so that it would flag it.
#: Widening this set is only ever safe for a name nobody can own.
ALLOWED_EMAIL_TLDS = (".test", ".example", ".invalid", ".localhost")

CODE_TOKEN = re.compile(r"\b[A-Z]{3,5}[0-9]{1,2}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
IPV4 = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
CREDENTIAL = re.compile(
    r"AKIA[0-9A-Z]{16}"                      # AWS access key id
    r"|gh[pousr]_[A-Za-z0-9]{36}"            # GitHub token
    r"|xox[bpsar]-[0-9A-Za-z-]{10,}"         # Slack token
    r"|AIza[0-9A-Za-z_-]{35}"                # Google API key
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"   # any PEM private key
)

#: Loopback and the unspecified address are not infrastructure.
ALLOWED_IPS = {"127.0.0.1", "0.0.0.0", "255.255.255.255"}


#: Where the already-published findings are recorded. See TheHistoryIsCheckedToo
#: for why the history guard is a ratchet rather than a gate, and
#: scripts/refresh_history_baseline.py for how to regenerate it.
BASELINE_PATH = ROOT / "tests" / "no_real_world_data_baseline.json"

_ALLOWED_CODE_UPPER = {t.upper() for t in ALLOWED_CODE_TOKENS}


def detect_findings(text):
    """{category: {offending values}} for one piece of text.

    The same rules the working-tree tests apply, in one callable, so the
    history scan cannot drift away from them. It returns the values rather
    than a count so a caller can count distinct ones - and it is the caller's
    job never to print them.
    """
    hits = {}

    def add(category, value):
        hits.setdefault(category, set()).add(value)

    for token in CODE_TOKEN.findall(text):
        if token.upper() not in _ALLOWED_CODE_UPPER:
            add("site-code-shaped token", token)
    for domain in EMAIL.findall(text):
        low = domain.lower()
        if low in ALLOWED_EMAIL_DOMAINS or low.endswith(ALLOWED_EMAIL_TLDS):
            continue
        add("email at a non-documentation domain", domain)
    for addr in IPV4.findall(text):
        if addr not in ALLOWED_IPS:
            add("infrastructure address", addr)
    if CREDENTIAL.search(text):
        add("credential shape", "<not recorded>")
    return hits


def _candidate_paths():
    """Tracked files when git can say, every file on disk when it cannot.

    The release ZIP is extracted without a `.git`, and so is anything else that
    unpacks a tarball to run the suite. Erroring there would turn a
    confidentiality check into a broken test in exactly the place the check is
    most worth having - the packaged artefact. Falling back to a filesystem
    walk keeps it running.
    """
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout
        rels = out.splitlines()
        if rels:
            return rels
    except (OSError, subprocess.SubprocessError):
        pass
    skip = {".git", "__pycache__", "node_modules", "venv", ".venv", "tmp", ".claude"}
    rels = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip for part in path.relative_to(ROOT).parts):
            continue
        rels.append(path.relative_to(ROOT).as_posix())
    return rels


def tracked_text_files():
    """Every file we can read as text, minus vendored bundles."""
    for rel in _candidate_paths():
        if not rel or rel.endswith(SKIP_SUFFIXES) or rel.startswith(SKIP_DIRS):
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            yield rel, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


class NothingTraceableToARealPlace(unittest.TestCase):
    def setUp(self):
        self.files = list(tracked_text_files())
        self.assertGreater(len(self.files), 50,
                           "the file walk found almost nothing - it is broken, "
                           "and a broken search reports clean")

    def test_every_site_code_shaped_token_is_an_invented_one(self):
        """The check that actually caught the real ones.

        A site code looks like four letters and a digit. So does a placeholder.
        The difference is only that somebody confirmed which is which, so the
        confirmed set is written down and anything else fails here.
        """
        found = {}
        for rel, text in self.files:
            for tok in CODE_TOKEN.findall(text):
                if tok not in ALLOWED_CODE_TOKENS:
                    found.setdefault(tok, []).append(rel)
        self.assertEqual(
            found, {},
            "Unrecognised site-code-shaped token(s) in tracked files: "
            + "; ".join(f"{t} in {', '.join(sorted(set(f))[:3])}"
                        for t, f in sorted(found.items()))
            + ". If it is invented, add it to ALLOWED_CODE_TOKENS. If it came "
              "from a real site, it must not be committed - see CLAUDE.md.")

    def test_every_email_address_uses_a_documentation_domain(self):
        found = {}
        for rel, text in self.files:
            for domain in EMAIL.findall(text):
                low = domain.lower()
                if low in ALLOWED_EMAIL_DOMAINS:
                    continue
                if low.endswith(ALLOWED_EMAIL_TLDS):
                    continue
                found.setdefault(domain, []).append(rel)
        self.assertEqual(
            found, {},
            "Real-looking email domain(s): "
            + "; ".join(f"{d} in {', '.join(sorted(set(f))[:3])}"
                        for d, f in sorted(found.items()))
            + ". Use an example.* address.")

    def test_no_infrastructure_addresses(self):
        """An internal IP names a network somebody runs."""
        found = {}
        for rel, text in self.files:
            for ip in IPV4.findall(text):
                if ip in ALLOWED_IPS:
                    continue
                # Version strings and dotted decimals are not addresses.
                if any(int(p) > 255 for p in ip.split(".")):
                    continue
                found.setdefault(ip, []).append(rel)
        self.assertEqual(found, {}, f"IP addresses in tracked files: {found}")

    def test_no_credentials_of_any_recognised_shape(self):
        found = {}
        for rel, text in self.files:
            m = CREDENTIAL.search(text)
            if m:
                found.setdefault(rel, m.group(0)[:12] + "...")
        self.assertEqual(found, {}, f"Credential-shaped strings: {found}")


class TheTwoScansAgree(unittest.TestCase):
    """`detect_findings` says it applies "the same rules the working-tree
    tests apply ... so the history scan cannot drift away from them". That is
    a claim two copies of the logic have to keep making true, and it was
    already broken once: widening the working-tree email rule to accept
    RFC 2606 reserved TLDs left `detect_findings` rejecting them, so a value
    the tree blessed would have failed the history ratchet on the next commit
    that added one - red CI for something deliberately allowed.

    So the agreement is checked rather than asserted in a docstring.
    """

    #: The "must be flagged" fixtures are assembled at runtime rather than
    #: written out. A literal would be a token in a tracked file, so the
    #: working-tree test would flag it and the only way to go green would be
    #: to allowlist it - which would make the fixture clean and the test
    #: meaningless. This is not evading the checker: both values are invented
    #: and meaningless, and the whole point is that they are *not* on the
    #: allowlist. Compare the `IPV4` entry in ALLOWED_CODE_TOKENS, which is
    #: the opposite case and is correctly allowlisted rather than exempted.
    NOT_RESERVED = "not-a-" + "reserved-name" + ".com"
    NOT_ALLOWLISTED = "QQ" + "RS4"

    @property
    def cases(self):
        return [
            ("engineer@example.com", True),
            ("engineer@a-stand-in.test", True),
            ("engineer@a-stand-in.invalid", True),
            ("engineer@" + self.NOT_RESERVED, False),
        ]

    def test_both_paths_agree_about_email_domains(self):
        for address, expected_clean in self.cases:
            with self.subTest(address=address):
                tree_clean = self._tree_clean(address)
                scan_clean = "email at a non-documentation domain" not in                     detect_findings(address)
                self.assertEqual(tree_clean, expected_clean)
                self.assertEqual(scan_clean, expected_clean)

    @staticmethod
    def _tree_clean(text):
        """The working-tree test's own rule, run on one string."""
        for domain in EMAIL.findall(text):
            low = domain.lower()
            if low in ALLOWED_EMAIL_DOMAINS or low.endswith(ALLOWED_EMAIL_TLDS):
                continue
            return False
        return True

    def test_both_paths_agree_about_site_code_tokens(self):
        for token, expected_clean in (("SITE1", True), ("ABCD7", True),
                                      (self.NOT_ALLOWLISTED, False)):
            with self.subTest(token=token):
                tree_clean = token.upper() in _ALLOWED_CODE_UPPER
                scan_clean = "site-code-shaped token" not in detect_findings(token)
                self.assertEqual(tree_clean, expected_clean)
                self.assertEqual(scan_clean, expected_clean)


class TheHistoryIsCheckedToo(unittest.TestCase):
    """The working tree is not the exposure. The repository is.

    Everything above reads `git ls-files` - the files checked out right now.
    That was the whole check for a long time, and it missed two surfaces that
    are just as public: **every commit message**, and **every version of every
    file ever committed**. A survey on 2026-09-17 found site-code-shaped
    tokens in both, on `main`, long after the working tree had been cleaned.

    One of them was in the message of the commit that did the cleaning. A
    commit message naming the identifier it just removed republishes it, and
    no amount of tidying the tree takes that back.

    **This is a ratchet, not a gate.** What is already published is recorded in
    `no_real_world_data_baseline.json` by object id and skipped; anything else
    fails. Failing on the existing history would pin CI red until somebody
    rewrote published history, and that is the owner's decision to take
    deliberately - not something a test should force on a Tuesday. Meanwhile a
    new commit carrying workplace data cannot land, which is the part that was
    missing.

    Rewriting history is the only thing that clears the baseline. After that,
    run `scripts/refresh_history_baseline.py` and it gets shorter.

    **That happened on 2026-09-17 and the baseline is empty.** Every commit and
    every blob was rewritten with `git-filter-repo`, the findings went to zero,
    and the file records nothing. The ratchet is at its floor: an entry
    appearing in it again is new debt rather than inherited debt, and the right
    response is to fix the commit, not to record it.
    """

    @classmethod
    def setUpClass(cls):
        if not history_scan.git_available():
            raise unittest.SkipTest("not a git checkout (release ZIP or tarball)")
        if history_scan.is_shallow():
            # A truncated clone has no history to scan, and asserting about
            # one would be claiming a clean result that was never read.
            raise unittest.SkipTest(
                "shallow clone - history is not present to scan. CI asks for "
                "the full history in .github/workflows/tests.yml.")
        cls.baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        cls.known_messages = set(cls.baseline["commit_messages"])
        cls.known_blobs = set(cls.baseline["blobs"])
        cls.messages = history_scan.scan_commit_messages("HEAD", detect_findings)
        cls.blobs = history_scan.scan_blobs("HEAD", detect_findings)
        cls.walked = history_scan.count_commits("HEAD")

    def test_no_commit_message_carries_workplace_data(self):
        """The surface the file-content check could never see.

        Commit messages were catalogued as carrying workplace identifiers and
        nothing in the suite could tell. This is what tells.
        """
        new = {sha: cats for sha, cats in self.messages.items()
               if sha not in self.known_messages}
        self.assertEqual(
            {}, new,
            "commit message(s) contain workplace data: "
            + ", ".join("%s (%s)" % (sha, ", ".join(sorted(cats)))
                        for sha, cats in sorted(new.items()))
            + ". The values are deliberately not printed - read it with "
              "`git show -s <sha>`. A pushed message cannot be edited without "
              "rewriting history, so this has to fail before the push.")

    def test_nothing_new_is_committed_into_a_file(self):
        """Catches it in the commit even if the tree is cleaned afterwards.

        Cleaning the tree later does not unpublish the blob, which is exactly
        the shape of what already happened here.
        """
        new = {sha: info for sha, info in self.blobs.items()
               if sha not in self.known_blobs}
        self.assertEqual(
            {}, new,
            "blob(s) committed with workplace data: "
            + "; ".join("%s in %s (%s)"
                        % (sha, ", ".join(info["paths"][:3]),
                           ", ".join(sorted(info["categories"])))
                        for sha, info in sorted(new.items()))
            + ". Values deliberately not printed - `git cat-file -p <sha>`.")

    def test_the_baseline_records_object_ids_and_not_values(self):
        """A baseline quoting the values would republish them.

        The file is tracked, so anything written into it is exactly as public
        as the history it describes.
        """
        raw = BASELINE_PATH.read_text(encoding="utf-8")
        for token in CODE_TOKEN.findall(raw):
            self.assertIn(
                token.upper(), _ALLOWED_CODE_UPPER,
                "the baseline itself contains a site-code-shaped token - it "
                "must record object ids only")
        for domain in EMAIL.findall(raw):
            self.assertIn(domain.lower(), ALLOWED_EMAIL_DOMAINS)
        for entry in sorted(self.known_messages | self.known_blobs):
            self.assertRegex(entry, r"^[0-9a-f]{7,40}$",
                             "baseline entries are object ids")

    def test_the_baseline_only_lists_things_that_are_really_there(self):
        """A record of debt, not a place to silence a finding.

        An id that no longer resolves means the history moved - after a
        rewrite, most likely - and the file should be regenerated so what is
        left is honest.
        """
        stale = [e for e in sorted(self.known_messages | self.known_blobs)
                 if subprocess.run(["git", "cat-file", "-e", e], cwd=str(ROOT),
                                   capture_output=True).returncode != 0]
        self.assertEqual(
            [], stale,
            "baseline entries no longer exist in this repository: "
            + ", ".join(stale[:10])
            + ". Run scripts/refresh_history_baseline.py to re-record what is "
              "actually left.")

    def test_the_scan_really_walked_the_history(self):
        """A history check that silently scanned nothing is a comment.

        This used to assert that the scan found *something*, reasoning that the
        baseline was not empty so a nil result meant a nil run. The history was
        rewritten on 2026-09-17 and the baseline is empty now, so that proxy
        would fail for the best possible reason. Ask the direct question
        instead: how many commits did it walk.

        `setUpClass` skips when git is missing, which is right for a release
        ZIP and wrong everywhere else - and a shallow clone skips too, because
        a truncated history reporting itself clean is the exact failure this
        guards against.
        """
        self.assertGreater(
            self.walked, 100,
            "the history scan walked %d commit(s), which is not this "
            "repository - it did not run" % self.walked)


class TheRuleItselfIsStillThere(unittest.TestCase):
    """A rule that can be quietly deleted is a rule with a countdown on it."""

    def setUp(self):
        self.claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    def test_claude_md_carries_the_no_real_data_rule(self):
        for phrase in ("Never use real personal or company information",
                       "without asking him first",
                       "Assume this repository is public",
                       "Unsure is a hit"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.claude_md,
                              "the no-real-data rule has been weakened or "
                              "removed from CLAUDE.md")

    def test_the_rule_is_near_the_top_where_it_will_be_read(self):
        """Buried at the bottom it is documentation. At the top it is a rule."""
        at = self.claude_md.index("Never use real personal or company information")
        self.assertLess(at, 3000,
                        "the rule has drifted down the file; it belongs before "
                        "the release process, not after it")


if __name__ == "__main__":
    unittest.main()
