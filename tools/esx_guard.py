"""Is this uploaded archive a project, or a way to take the server down?

Three drop zones - PlanTrim, Capacity and Prep - accept an `.esx` posted as
the raw request body and hand it straight to a tool that reads members out of
it. Every one of those reads a whole member into memory with `ZipFile.read`,
which is correct for a project and is the wrong end of a zip bomb: a few
hundred kilobytes of deflate can carry gigabytes of zeroes, and the first
thing that happens is `json.loads` on all of them.

An `.esx` is an untrusted archive by nature. It arrives by email, from a
colleague, out of a shared folder or down from Ekahau Cloud, and the audit
that preceded this already proved a crafted one could run script in the
browser. So the archive is looked at before it is read.

**What this is not.** It is not a validity check - `plan_detect`,
`esx_trimmer` and `capacity_profiles` each decide for themselves whether the
members they need are present, and saying "not an Ekahau project" is their
job. This only answers "is reading this going to be sane", and it answers
from the central directory, which is metadata: nothing is decompressed to
find out.

**The numbers are deliberately far above a real project**, for the same
reason the request-size ceiling is: his projects run to a couple of hundred
megabytes with hundreds of floor-plan images in them, and a guard that fires
on a Monday morning is worse than no guard, because he stops believing the
ones that matter. The largest project measured here is comfortably inside
every limit below with an order of magnitude to spare.

Declared sizes are what a zip bomb lies about, so the ratio is checked
against the declared total as well - a member claiming to be small and
inflating past its own declaration is caught by the per-member ceiling when
it is actually read, which is the tool's business, not this one's.
"""
from __future__ import annotations

import zipfile

#: Everything in the archive, uncompressed, added up. Five times the largest
#: project seen here.
MAX_TOTAL_UNCOMPRESSED = 4 * 1024 * 1024 * 1024

#: One member. A floor-plan image is the big one and is measured in tens of
#: megabytes; a gigabyte is not a plan.
MAX_MEMBER_UNCOMPRESSED = 1024 * 1024 * 1024

#: How many entries. A project with a few hundred floors would be
#: extraordinary and this allows fifty thousand.
MAX_MEMBERS = 50_000

#: Compressed to uncompressed, over the whole archive. Ordinary JSON and PNG
#: land between 1 and 5; text of one repeated byte reaches several thousand.
MAX_RATIO = 500


class HostileArchive(Exception):
    """Reported to the page in plain language, like any other refusal."""


def check(path) -> None:
    """Raise `HostileArchive` if reading this archive would be unreasonable.

    Silent on anything that is merely *invalid* - a truncated file, a file
    that is not a ZIP at all. Those are the tools' own error messages and
    saying it twice, in different words, is how a user ends up with two
    explanations for one problem.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return

    if len(infos) > MAX_MEMBERS:
        raise HostileArchive(
            f"That archive holds {len(infos):,} entries, which is not an "
            "Ekahau project. Nothing was read from it.")

    total = 0
    for info in infos:
        if info.file_size > MAX_MEMBER_UNCOMPRESSED:
            raise HostileArchive(
                "That archive claims to contain a single file of "
                f"{info.file_size / (1024 ** 3):.1f} GB. Nothing was read "
                "from it.")
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise HostileArchive(
                "That archive unpacks to more than "
                f"{MAX_TOTAL_UNCOMPRESSED // (1024 ** 3)} GB. Nothing was "
                "read from it.")

    compressed = sum(i.compress_size for i in infos)
    # A small archive with a high ratio is ordinary - an empty file, a short
    # JSON document of repeated whitespace - and refusing it would fire on
    # real projects. The ratio only means something once there is enough
    # data for it to mean something.
    if total > 64 * 1024 * 1024 and compressed > 0:
        ratio = total / compressed
        if ratio > MAX_RATIO:
            raise HostileArchive(
                f"That archive expands {int(ratio):,} times over, which no "
                "Ekahau project does. Nothing was read from it.")
