"""Which survey files an .esx should carry, and which of them it is missing.

**Why this exists.** The signal-strength and noise samples of a survey are not
in the JSON. A survey record lists its Wi-Fi tracks, each naming a
`binaryFileId`, and its spectrum sessions, each naming `chunks`; the samples
themselves are separate members of the zip - `track-<id>.bin` and
`spectrum-<id>.bin`. A copy that has the records and not the members opens as
a project with surveys on it and nothing behind them: no measurements, no
heatmaps, and no error to say so.

Cloud Manager produced exactly that for as long as it built a download from the
batch response and the floor-plan images alone. Ekahau's own download worker
also writes one `survey-<id>.json` per survey (never a merged `surveys.json`),
fetches every track and spectrum chunk from `binaryFiles/<id>`, and fetches
any Cisco radio-mapping file. This module is the shared definition of that
layout, used to build the download, to refuse one that came out short, and to
tell a local file that is already short.

**Nothing here writes.** It reads the names in an archive and the survey
records inside it.
"""
from __future__ import annotations

import json
import zipfile

SURVEY_PREFIX = "survey-"
TRACK_PREFIX = "track-"
SPECTRUM_PREFIX = "spectrum-"
WCS_PREFIX = "wcs-"

#: The members that hold measured data, as opposed to the project's design.
#: A file that has lost any of these has lost something a re-save cannot
#: recreate.
SURVEY_MEMBER_PREFIXES = (SURVEY_PREFIX, TRACK_PREFIX, SPECTRUM_PREFIX,
                          WCS_PREFIX)


def track_member(binary_file_id) -> str:
    return "%s%s.bin" % (TRACK_PREFIX, binary_file_id)


def spectrum_member(chunk_id) -> str:
    return "%s%s.bin" % (SPECTRUM_PREFIX, chunk_id)


def survey_member(survey_id) -> str:
    return "%s%s.json" % (SURVEY_PREFIX, survey_id)


def wcs_member(mapping_id) -> str:
    return "%s%s.csv" % (WCS_PREFIX, mapping_id)


def live(records) -> list:
    """The records Ekahau still counts. A deleted survey stays in the batch
    with `status: DELETED` and has no files, so expecting any for it would
    report a gap that is not one."""
    return [r for r in (records or [])
            if isinstance(r, dict) and r.get("status") != "DELETED"]


def expected_members(surveys, floor_plans=()) -> list:
    """Every member the given survey and floor-plan records say should exist,
    in a stable order and without repeats."""
    wanted = []
    for survey in live(surveys):
        if survey.get("id"):
            wanted.append(survey_member(survey["id"]))
        for track in survey.get("wifiTracks") or []:
            if isinstance(track, dict) and track.get("binaryFileId"):
                wanted.append(track_member(track["binaryFileId"]))
        for session in survey.get("spectrumSessions") or []:
            if not isinstance(session, dict):
                continue
            for chunk in session.get("chunks") or []:
                if chunk:
                    wanted.append(spectrum_member(chunk))
    for plan in live(floor_plans):
        if plan.get("ciscoWcsRadioMappingDataId"):
            wanted.append(wcs_member(plan["ciscoWcsRadioMappingDataId"]))
    return list(dict.fromkeys(wanted))


def _json_member(zf: zipfile.ZipFile, name: str):
    try:
        return json.loads(zf.read(name).decode("utf-8"))
    except (KeyError, ValueError, UnicodeDecodeError, zipfile.BadZipFile):
        return None


def surveys_in(zf: zipfile.ZipFile) -> list:
    """The survey records in an archive, whichever layout holds them: one
    `survey-<id>.json` each (what Ekahau writes) or a single merged
    `surveys.json` (what Cloud Manager used to write)."""
    names = zf.namelist()
    found = []
    for name in names:
        if name.startswith(SURVEY_PREFIX) and name.endswith(".json"):
            doc = _json_member(zf, name)
            if isinstance(doc, dict):
                found.extend(doc.get("surveys") or [])
    if "surveys.json" in names:
        doc = _json_member(zf, "surveys.json")
        if isinstance(doc, dict):
            known = {s.get("id") for s in found if isinstance(s, dict)}
            found.extend(s for s in doc.get("surveys") or []
                         if not (isinstance(s, dict) and s.get("id") in known))
    return found


def missing_members(zf: zipfile.ZipFile) -> list:
    """Names the archive's own records point at that the archive does not
    contain. Empty means the survey data is all there - including when there
    is no survey data at all, which is the ordinary state of a project that
    only predicts."""
    floor_plans = []
    if "floorPlans.json" in zf.namelist():
        doc = _json_member(zf, "floorPlans.json")
        if isinstance(doc, dict):
            floor_plans = doc.get("floorPlans") or []
    present = set(zf.namelist())
    return [name for name in expected_members(surveys_in(zf), floor_plans)
            if name not in present]


def missing_in_file(path) -> list:
    """`missing_members` for a path. An unreadable archive reports nothing:
    whether it is a valid zip is somebody else's question, and a flag that
    fires on every corrupt file would bury the one it exists to raise."""
    try:
        with zipfile.ZipFile(path) as zf:
            return missing_members(zf)
    except (OSError, zipfile.BadZipFile, ValueError):
        return []


def missing_in_bytes(data: bytes) -> list:
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return missing_members(zf)
    except (zipfile.BadZipFile, ValueError):
        return []
