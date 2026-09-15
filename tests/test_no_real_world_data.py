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

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
    "UTF8",          # an encoding, not a site
    "IPV4",          # a protocol, not a site - and it is this file's own
                     # regex constant, so the scan reads its own source and
                     # flags it. Allowlisting beats exempting this file:
                     # a checker that skips itself is a checker with a hole.
}

#: Reserved-for-documentation domains (RFC 2606) plus the generic stand-in.
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net",
                         "example.invalid", "company.com"}

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
                if domain.lower() not in ALLOWED_EMAIL_DOMAINS:
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
