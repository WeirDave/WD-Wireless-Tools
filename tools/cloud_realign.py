"""Realign local .esx files whose cloud counterpart was renamed.

**The problem this exists for is one we caused.** A batch of cloud projects
was renamed. Ekahau stamps `history.modifiedAt` on a rename, so every one of
those projects came back newer than the local copy that had not moved - and
Cloud Manager, which compares those two timestamps, duly reported around
ninety pairs as "cloud newer". The designs are identical. The dates are not.

Pulling all ninety to fix a date would be a lot of downloading to change
nothing, and it is the kind of bulk operation that goes wrong quietly. So
this does the smaller, checkable thing instead.

**What "proven identical" means here, and why it is not the rename
heuristic.** `build_matches` already separates "renamed" from "content" by
comparing the name inside the .esx with the cloud's name, and its own
docstring is careful to say that **it does not prove the content is
unchanged** - a project renamed *and* edited still reads as "renamed". That
is a triage signal. It is not a licence to write to his files. So every pair
here is settled by `esx_compare.compare_esx`, which unzips both sides and
compares every JSON member after normalisation plus every floor plan image by
SHA-256. A pair is only touched when that comparison reports no design
difference. Anything else is skipped and listed.

**The timestamp that matters is the one inside the file, not the one on
disk.** This is the trap in the obvious implementation. `get_local_esx_files`
reports `mtime` as `internalMtime or fs_mtime` - the `history.modifiedAt`
recorded inside `project.json` - precisely because a filesystem mtime resets
on copy, sync or a OneDrive touch and the internal one does not. So `os.utime`
alone changes nothing a row displays, and all ninety would still read "cloud
newer" afterwards. Both are set: the internal one because it is what is
compared and shown, the filesystem one so the file on disk agrees with what
is inside it.

**Nothing is forged.** The value written is the cloud project's own
`history.modifiedAt`, taken verbatim from the project record where the API
gives us the string, and otherwise reconstructed as UTC ISO-8601 from the same
instant. It is never "now", and it is never invented.

**Nothing leaves the machine and nothing is deleted.** The only cloud call is
`download_project`, which reads. There is no upload path here, no rename call,
no delete call - `tests/test_cloud_realign.py` asserts that against a
recording API stub rather than trusting this paragraph.

**Dry run is the default and is the real work.** `dry_run=True` performs every
download and every comparison and then writes nothing, so the preview is not a
guess about what would happen - it is the same decision, reported instead of
applied. The live run re-verifies rather than trusting the preview, because a
file can change between the two and the proof has to be current at the moment
of writing.

**Idempotent.** A pair is a candidate only while the cloud reads newer than
the local copy, so an aligned pair drops out of the candidate set on the next
run. `_rewrite_project_json` writes nothing when the mutation changes nothing,
so a re-run after an interruption finishes the remainder without touching what
is already done and without stacking a second backup.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from tools import esx_compare
from tools.cloud_manager import (
    _parse_cloud_mtime,
    _rewrite_project_json,
    build_projects_data,
)

#: Matches `_STALE_TOLERANCE_S` in `build_matches`. A pair inside this window
#: is not reported as stale in the first place, so writing to it would be
#: churn: the row already says what he wants it to say.
TOLERANCE_S = 60


def _iso_utc(unix_seconds):
    """The cloud's own format: `2026-09-18T07:21:14.000Z`.

    Used only when the project record did not carry a usable string of its
    own. Same instant, written the way Ekahau writes it, so the value round
    trips through `_esx_meta`'s parser unchanged.
    """
    dt = datetime.fromtimestamp(int(unix_seconds), tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _cloud_modified_strings(api):
    """`{project_id: raw history.modifiedAt}` straight off the project records.

    Taken verbatim so the value written into the local file is the cloud's own
    string rather than one of ours that happens to mean the same thing. When
    a record has no usable value the id is simply absent and the caller falls
    back to `_iso_utc`.
    """
    out = {}
    try:
        for pr in api.get_projects():
            pid = pr.get("id")
            iso = ((pr.get("history") or {}).get("modifiedAt") or "").strip()
            if pid and iso:
                out[pid] = iso
    except Exception:
        pass
    return out


def find_candidates(data):
    """The pairs worth examining: matched, and the cloud side reads newer.

    Deliberately *not* filtered by `difference == "renamed"`. That field is
    the name-based heuristic, and using it to choose what to write to would
    make a guess load-bearing. Every candidate is settled by content below;
    a pair the heuristic calls "content" and the comparison finds identical
    is exactly the case this was built for.
    """
    return [m for m in (data.get("matched") or [])
            if m.get("staleness") == "cloud_newer"]


def _entry(pair):
    """The identity of a row, for the report. Local stem and site folder are
    what he recognises; the path is what he would open."""
    local, cloud = pair["local"], pair["cloud"]
    return {"name": local.get("name") or "", "folder": local.get("folder") or "",
            "path": local.get("path") or "", "cloudId": cloud.get("id") or ""}


def realign(cm, dry_run=True, progress_cb=None, limit=None):
    """Align every pair that is provably identical. Returns a report.

    `cm` is a `CloudManager`. `dry_run=True` (the default) decides everything
    and writes nothing.

    The report is three lists plus counts:

    * `aligned` - what was changed, or would be, with the specific actions
    * `skipped` - and the reason, in words, for each one
    * `failed`  - and the error

    Every candidate lands in exactly one of them, so the three add up to
    `examined` and nothing goes missing between the preview and the run.
    """
    if not cm._ensure():
        return {"error": "Not connected"}
    output_dir = cm.config.get("output_dir", "")
    if not output_dir:
        return {"error": "No local folder is set"}

    keep_backups = cm.config.get("keep_local_backups")
    keep_backups = True if keep_backups is None else bool(keep_backups)

    def _say(**kw):
        if progress_cb:
            progress_cb(**kw)

    _say(stage="scan", current=2, total=100, message="Reading both sides…")
    try:
        data = build_projects_data(cm.api, output_dir)
    except Exception as e:
        return {"error": "Could not list projects: %s" % e}

    candidates = find_candidates(data)
    if limit:
        candidates = candidates[:int(limit)]

    cloud_iso = _cloud_modified_strings(cm.api)

    aligned, skipped, failed = [], [], []
    total = len(candidates) or 1

    for i, pair in enumerate(candidates):
        entry = _entry(pair)
        _say(stage="compare", current=int(5 + 90 * i / total), total=100,
             message="Checking %d of %d…" % (i + 1, len(candidates)))

        src = cm._local_esx(entry["path"])
        if isinstance(src, dict):
            failed.append({**entry, "error": src.get("error", "Unusable path")})
            continue

        cloud_unix = int(pair["cloud"].get("mtime") or 0) or \
            _parse_cloud_mtime(pair["cloud"])
        if not cloud_unix:
            skipped.append({**entry,
                            "reason": "The cloud project has no usable "
                                      "modified date to copy."})
            continue

        try:
            local_bytes = src.read_bytes()
        except OSError as e:
            failed.append({**entry, "error": "Could not read the local file: %s" % e})
            continue

        try:
            got = cm.api.download_project(entry["cloudId"])
        except Exception as e:
            failed.append({**entry, "error": "Could not fetch the cloud copy: %s" % e})
            continue
        if isinstance(got, dict) and got.get("error"):
            failed.append({**entry, "error": str(got.get("error"))})
            continue

        result = esx_compare.compare_esx(local_bytes, got.get("esx") or b"",
                                         local_file_stem=src.stem)
        if result.get("error"):
            failed.append({**entry, "error": str(result["error"])})
            continue
        if result.get("designDiffers"):
            # The case this must not touch. Name it in his words and carry the
            # comparison's own sentence, which says which members moved.
            skipped.append({**entry,
                            "reason": "The designs genuinely differ - %s"
                                      % (result.get("summary")
                                         or "the contents are not the same."),
                            "differences": result.get("differences") or []})
            continue

        cloud_name = (pair["cloud"].get("name") or "").strip()
        internal_name = (pair["local"].get("projectName") or "").strip()
        wants_name = bool(cloud_name) and \
            internal_name.casefold() != cloud_name.casefold()
        local_unix = int(pair["local"].get("mtime") or 0)
        wants_date = abs(cloud_unix - local_unix) > TOLERANCE_S

        actions = []
        if wants_name:
            actions.append("Set the name inside the file to match the cloud")
        if wants_date:
            actions.append("Set the modified date to the cloud's")
        if not actions:
            skipped.append({**entry,
                            "reason": "Already aligned - nothing to change."})
            continue

        planned = {**entry, "actions": actions,
                   "newDate": _iso_utc(cloud_unix),
                   "identical": True}

        if dry_run:
            aligned.append(planned)
            continue

        iso = cloud_iso.get(entry["cloudId"]) or _iso_utc(cloud_unix)

        def _fix(proj, doc, _name=cloud_name, _iso=iso,
                 _do_name=wants_name, _do_date=wants_date):
            changed = False
            if _do_name:
                proj["name"] = _name
                if "title" in proj:
                    proj["title"] = _name
                changed = True
            if _do_date:
                history = proj.get("history")
                if not isinstance(history, dict):
                    history = {}
                    proj["history"] = history
                history["modifiedAt"] = _iso
                changed = True
            return changed

        out = _rewrite_project_json(src, _fix, output_dir,
                                    keep_backups=keep_backups)
        if out.get("error"):
            failed.append({**entry, "error": out["error"]})
            continue

        try:
            os.utime(src, (cloud_unix, cloud_unix))
        except OSError as e:
            # The file itself is correct; only the disk timestamp is not, and
            # that is the one the tool does not read. Say so rather than
            # reporting a failure for work that succeeded.
            planned["warning"] = "Contents updated, but the file's date on " \
                                 "disk could not be set: %s" % e

        planned["backup"] = out.get("backup")
        aligned.append(planned)

    _say(stage="done", current=100, total=100, message="Done.")
    return {"ok": True, "dryRun": bool(dry_run),
            "examined": len(candidates),
            "aligned": aligned, "skipped": skipped, "failed": failed,
            "counts": {"aligned": len(aligned), "skipped": len(skipped),
                       "failed": len(failed)}}
