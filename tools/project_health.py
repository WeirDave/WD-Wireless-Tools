"""One read-only health check for an Ekahau project, and where to fix each thing.

The suite already knows a good deal about what is wrong with a project, but
each piece lives in the tool that happens to need it and shows only once that
tool has the file open: Report finds access points with no model or mount
height after the whole project has been parsed in the browser, AP Labeler finds
duplicate names, Quick Walls finds a wall type whose name states a height the
data does not carry, and Cloud Manager finds survey samples missing from an
archive. Nobody sees the lot until they print a report with a hole in it.

This reads only the members it needs - the access points, their radios and
antennas, the floor plans, the wall types and segments, and the names of the
survey members - and returns a ranked list. **It never writes.**

**One definition per rule.** Wall heights and survey gaps call the functions
the other tools use (``wall_audit.audit_members``,
``esx_survey_data.missing_members``). The access-point rules are the same ones
Report's design review applies; they exist in two languages because Report
reads the project in the browser, and
``tests/test_project_health.py`` runs Report's own name rule against this one
over the same list of names so the copies cannot drift apart unnoticed.

**Only what is unambiguous.** Channel plans, power ceilings and co-channel
distance are design opinions with options, and stay in Report's design review.
Everything here is either missing or contradicted by the file itself.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

from tools import esx_guard, esx_survey_data, wall_audit

#: Report's DR_UNSET_HEIGHT_M. At or under this a mount height is Ekahau's
#: "not set" placeholder rather than a decision.
UNSET_HEIGHT_M = 0.5

SEVERITY_ORDER = {"fix": 0, "check": 1, "note": 2}

#: How many names a finding carries as examples. The count is the number; the
#: names are only so the person can find the first one.
EXAMPLES = 5

_MAC_NAME = re.compile(r"^[0-9a-f]{2}([:\-.]?[0-9a-f]{2}){5}$", re.I)
_GENERIC_NAME = re.compile(
    r"^(simulated|measured)?[\s\-_]*(ap|access[\s\-_]*point)[\s\-_#]*\d*$", re.I)

#: Where a finding is fixed. A tool here is one this suite has; anything that
#: can only be fixed in Ekahau says so rather than inventing a link.
_AP_LABELER = {"name": "AP Labeler", "href": "/aprename"}
_QUICK_WALLS = {"name": "Quick Walls", "href": "/walls"}
_CLOUD = {"name": "Cloud Manager", "href": "/cloud"}


def generic_name(name) -> str:
    """Why an access point name tells an installer nothing, or ''.

    Report's ``drGenericName``, rule for rule.
    """
    n = str(name or "").strip()
    if not n:
        return "No name"
    if _MAC_NAME.match(n):
        return "A MAC address as the name"
    if _GENERIC_NAME.match(n):
        return "Only “AP” and a number"
    return ""


def _antenna_is_directional(ant) -> bool:
    """Report's ``antennaIsDirectional``."""
    if not ant:
        return False
    if ant.get("directional") is True:
        return True
    if ant.get("directional") is False:
        return False
    return not re.search("omni", ant.get("name") or "", re.I)


def _is_live_wifi(radio) -> bool:
    """Report's ``drIsLiveWifi``: Bluetooth and the like carry no channel plan,
    and a radio switched off in the design is not on the air."""
    return (isinstance(radio, dict) and radio.get("enabled") is not False
            and (not radio.get("radioTechnology")
                 or radio.get("radioTechnology") == "IEEE802_11"))


def _members(zf: zipfile.ZipFile, names) -> dict:
    present = set(zf.namelist())
    out = {}
    for name in names:
        if name not in present:
            continue
        try:
            out[name] = json.loads(zf.read(name).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, zipfile.BadZipFile):
            continue
    return out


def _list(doc, key) -> list:
    items = doc.get(key) if isinstance(doc, dict) else None
    return [i for i in (items or []) if isinstance(i, dict)]


class _Findings:
    def __init__(self):
        self._by_id = {}

    def add(self, fid, severity, title, why, example="", tool=None, fix_in=""):
        f = self._by_id.get(fid)
        if f is None:
            f = self._by_id[fid] = {
                "id": fid, "severity": severity, "title": title, "why": why,
                "count": 0, "examples": [], "tool": tool, "fixIn": fix_in}
        f["count"] += 1
        if example and len(f["examples"]) < EXAMPLES and example not in f["examples"]:
            f["examples"].append(example)

    def ranked(self) -> list:
        return sorted(self._by_id.values(),
                      key=lambda f: (SEVERITY_ORDER[f["severity"]], -f["count"],
                                     f["title"]))


def check_zip(zf: zipfile.ZipFile) -> dict:
    """The findings for an open archive."""
    docs = _members(zf, ("accessPoints.json", "simulatedRadios.json",
                         "antennaTypes.json", "floorPlans.json",
                         "wallTypes.json", "wallSegments.json"))
    aps = _list(docs.get("accessPoints.json"), "accessPoints")
    radios = _list(docs.get("simulatedRadios.json"), "simulatedRadios")
    antennas = {a.get("id"): a
                for a in _list(docs.get("antennaTypes.json"), "antennaTypes")}
    floors = {f.get("id") for f in _list(docs.get("floorPlans.json"), "floorPlans")
              if f.get("id")}

    radios_by_ap = {}
    for r in radios:
        if r.get("accessPointId"):
            radios_by_ap.setdefault(r["accessPointId"], []).append(r)

    found = _Findings()

    # Names. Case and surrounding space do not make two names different.
    by_name = {}
    for ap in aps:
        key = str(ap.get("name") or "").strip().lower()
        if key:
            by_name.setdefault(key, []).append(ap)
    for group in by_name.values():
        if len(group) > 1:
            for ap in group:
                found.add("dupName", "fix", "Access points sharing a name",
                          "The name is what goes on the label, in the controller "
                          "and in the ticket. Two APs with one name are one AP to "
                          "everyone after the designer.",
                          example=str(ap.get("name") or "").strip(),
                          tool=_AP_LABELER)

    for ap in aps:
        name = str(ap.get("name") or "").strip()
        label = name or "(no name)"
        if generic_name(name):
            found.add("genericName", "check", "Access points without a real name",
                      "An installer cannot tell these apart on site, and the "
                      "controller will learn them by MAC address.",
                      example=label, tool=_AP_LABELER)
        loc = ap.get("location") if isinstance(ap.get("location"), dict) else {}
        if loc.get("floorPlanId") not in floors:
            found.add("noFloor", "check", "Access points on no floor plan",
                      "Nothing here says where these go. Every placement sheet "
                      "leaves them out.", example=label,
                      fix_in="Ekahau: place the AP on a floor plan, or delete it")
        if not str(ap.get("model") or "").strip():
            found.add("noModel", "check", "Access points with no model",
                      "The Bill of Materials counts them as \"Unknown\", and the "
                      "prediction used a generic radio.", example=label,
                      fix_in="Ekahau: choose the AP model")

        live = [r for r in radios_by_ap.get(ap.get("id"), []) if _is_live_wifi(r)]
        if live:
            primary = live[0]
            h = primary.get("antennaHeight")
            h = h if isinstance(h, (int, float)) and not isinstance(h, bool) else None
            if h is None or h <= UNSET_HEIGHT_M:
                found.add("noHeight", "check", "Access points with no mount height",
                          "The prediction assumed a height nobody chose, and the "
                          "installer has nothing to hang it at.", example=label,
                          fix_in="Ekahau: set the antenna height")
            for r in live:
                bearing = r.get("antennaDirection")
                aimless = (bearing is None or isinstance(bearing, bool)
                           or not isinstance(bearing, (int, float)))
                if aimless and _antenna_is_directional(antennas.get(r.get("antennaTypeId"))):
                    found.add("noAzimuth", "fix", "Directional antennas with no azimuth",
                              "A directional antenna with no bearing cannot be "
                              "aimed, and the prediction pointed it somewhere by "
                              "default.", example=label,
                              fix_in="Ekahau: set the antenna direction")
                    break

    # Walls: the rule the Quick Walls audit applies, over the same two lists.
    wall_types = _list(docs.get("wallTypes.json"), "wallTypes")
    segments = _list(docs.get("wallSegments.json"), "wallSegments")
    for w in wall_audit.audit_members(wall_types, segments):
        found.add("wallHeight", "check", "Wall types whose name states a height the file does not",
                  "The name says how tall the wall is and the type has none, so "
                  "the prediction treats it as reaching the ceiling.",
                  example=w.wall_type, tool=_QUICK_WALLS)

    # Survey samples the records point at and the archive does not hold.
    try:
        missing = esx_survey_data.missing_members(zf)
    except (zipfile.BadZipFile, ValueError, KeyError):
        missing = []
    for _ in missing:
        found.add("surveyGaps", "fix", "Survey data missing from the file",
                  "The survey records name signal and noise samples that are not "
                  "in the archive, so heat maps and survey reports built from "
                  "them are short. Downloading the project again from Ekahau "
                  "Cloud, or re-saving it in Ekahau, restores them.",
                  tool=_CLOUD)

    findings = found.ranked()
    summary = {"fix": 0, "check": 0, "note": 0}
    for f in findings:
        summary[f["severity"]] += 1
    return {"ok": True, "findings": findings, "summary": summary,
            "accessPoints": len(aps), "floors": len(floors),
            "clean": not findings}


def check_path(path) -> dict:
    """The findings for a project on disk, or why it could not be read."""
    try:
        with esx_guard.open_zip(Path(path)) as zf:
            return check_zip(zf)
    except esx_guard.HostileArchive as e:
        return {"ok": False, "error": str(e)}
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        return {"ok": False, "error": f"That project could not be read: {e}"}


def check_bytes(data: bytes) -> dict:
    """The findings for a project that arrived as bytes."""
    try:
        with esx_guard.open_zip(io.BytesIO(data)) as zf:
            return check_zip(zf)
    except esx_guard.HostileArchive as e:
        return {"ok": False, "error": str(e)}
    except (zipfile.BadZipFile, ValueError) as e:
        return {"ok": False, "error": f"That is not a readable .esx project: {e}"}
