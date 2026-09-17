"""Compare a local .esx against the cloud copy of the same project, in memory.

**Why this exists.** Staleness was decided by two `history.modifiedAt` values,
one from inside the local file and one from the cloud's project record. A
rename moves that timestamp, so renaming a project read exactly like somebody
redesigning it, and the honest answer to "is it safe to pull these sixty" was
that the tool could not tell. That is an inference problem, and the fix is to
stop inferring: unzip both sides and look.

**Why hashing the archives does not work, and why that does not matter.** Cloud
projects are stored uncompressed at rest and a local .esx is ZIP-deflated, so
the same project hashes differently on each side. Worse, the cloud does not
serve a stored ZIP at all - `download_project` assembles one from the batch
document plus per-image S3 fetches, so two downloads of an unchanged project
need not be byte-identical either. Both facts rule out hashing the *archive*.
Neither says anything about the *contents*, which is what this compares.

**Nothing is written to disk.** The cloud copy arrives as bytes and `zipfile`
reads a `BytesIO`, so there are no extracted copies of live projects to clean
up afterwards - and therefore none to leak if this raises halfway through.
That is deliberate: twenty-seven extracted copies of real projects were found
sitting in a temp folder earlier today.

**It is read-only.** This is a diagnostic. It opens two archives and returns a
description; it never writes to either side.

**What it can and cannot see.** Every JSON member is compared after
normalisation, and every floor plan image by SHA-256 of its bytes - so a
re-cropped plan from PlanTrim is detected, which a document-only comparison
would miss. What it cannot do is tell you *who* changed something or merge two
sets of changes; it reports that both sides differ from their common ancestor
only in the sense that they differ from each other.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

#: Fields that move when nothing about the design does. Stripped everywhere
#: they appear, at any depth.
#:
#: `modifiedAt` / `modifiedBy` are the whole reason this module exists - they
#: are what a rename moves. `status` is set to "UPDATED" by the rename call
#: itself. The rest are server bookkeeping that varies between a stored copy
#: and an assembled one.
VOLATILE_KEYS = frozenset({
    "modifiedAt", "modifiedBy", "lastModifiedAt", "updatedAt",
    "status", "etag", "eTag",
})

#: Members that are metadata about the project rather than the design in it.
#: They are compared and reported, but separately: a difference here is not a
#: reason to think somebody has moved an access point.
METADATA_MEMBERS = frozenset({
    "project.json", "projectHistorys.json", "version",
})

#: Inside `project.json`, the name is the thing a rename changes. Comparing it
#: is the point - it is how "renamed" is told apart from "redesigned" - but it
#: is reported as a rename rather than as a design difference.
NAME_KEYS = ("name", "title")

MAX_REPORTED_MEMBERS = 40


def _strip_volatile(value):
    """Recursively drop volatile keys and put mappings in a stable order."""
    if isinstance(value, dict):
        return {k: _strip_volatile(v) for k, v in sorted(value.items())
                if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    return value


def _canonical(value) -> str:
    return json.dumps(_strip_volatile(value), sort_keys=True,
                      ensure_ascii=False, separators=(",", ":"))


def _members(zf: zipfile.ZipFile) -> dict:
    return {name: zf.read(name) for name in zf.namelist()
            if not name.endswith("/")}


def _as_json(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def _collection(doc):
    """If the document is `{key: [items with ids]}`, return (key, {id: item}).

    Ekahau's members are almost all of this shape - `accessPoints.json` holds
    `{"accessPoints": [...]}` - and diffing by id is what turns "this file
    differs" into "three access points differ", which is the difference between
    a label he distrusts and a fact he can act on.
    """
    if not isinstance(doc, dict) or len(doc) != 1:
        return None, None
    key, items = next(iter(doc.items()))
    if not isinstance(items, list) or not items:
        return None, None
    by_id = {}
    for item in items:
        if not isinstance(item, dict) or "id" not in item:
            return None, None
        by_id[item["id"]] = item
    return key, by_id


def _describe_collection(local_doc, cloud_doc):
    """{'added': n, 'removed': n, 'changed': n} or None if not a collection."""
    lkey, litems = _collection(local_doc)
    ckey, citems = _collection(cloud_doc)
    if litems is None or citems is None or lkey != ckey:
        return None
    added = [i for i in citems if i not in litems]
    removed = [i for i in litems if i not in citems]
    changed = [i for i in litems if i in citems
               and _canonical(litems[i]) != _canonical(citems[i])]
    if not (added or removed or changed):
        return None
    return {"noun": lkey, "added": len(added),
            "removed": len(removed), "changed": len(changed)}


def _names(doc):
    project = (doc or {}).get("project") if isinstance(doc, dict) else None
    if not isinstance(project, dict):
        return ""
    for key in NAME_KEYS:
        value = project.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def compare_esx(local_bytes: bytes, cloud_bytes: bytes) -> dict:
    """Describe how two .esx archives differ. Pure; no I/O, no disk.

    Returns a dict with:

    * `identical`      - nothing differs at all, including the name
    * `designDiffers`  - something other than metadata differs
    * `renamedOnly`    - the only difference is the project's name
    * `differences`    - per-member detail, ids and counts, never values
    * `summary`        - one sentence for the row
    """
    out = {"identical": False, "designDiffers": False, "renamedOnly": False,
           "differences": [], "imagesCompared": 0, "summary": ""}

    try:
        lz = zipfile.ZipFile(io.BytesIO(local_bytes))
        cz = zipfile.ZipFile(io.BytesIO(cloud_bytes))
    except zipfile.BadZipFile as exc:
        return {**out, "error": "Could not read one of the archives: %s" % exc}

    with lz, cz:
        local = _members(lz)
        cloud = _members(cz)

    local_name = _names(_as_json(local.get("project.json", b"")))
    cloud_name = _names(_as_json(cloud.get("project.json", b"")))
    renamed = bool(local_name and cloud_name and local_name != cloud_name)

    design_diffs = []
    meta_diffs = []

    for member in sorted(set(local) | set(cloud)):
        in_local, in_cloud = member in local, member in cloud
        is_meta = member in METADATA_MEMBERS
        is_image = member.startswith("image-")

        if in_local != in_cloud:
            entry = {"member": member,
                     "state": "only in local" if in_local else "only in cloud"}
            (meta_diffs if is_meta else design_diffs).append(entry)
            continue

        if is_image:
            out["imagesCompared"] += 1
            # Images are opaque bytes, so the hash *is* the comparison. This is
            # what catches a re-cropped floor plan, which every JSON document
            # would report as unchanged.
            if hashlib.sha256(local[member]).hexdigest() != \
                    hashlib.sha256(cloud[member]).hexdigest():
                design_diffs.append({"member": member, "state": "differs",
                                     "kind": "floor plan image"})
            continue

        ldoc, cdoc = _as_json(local[member]), _as_json(cloud[member])
        if ldoc is None or cdoc is None:
            if local[member] != cloud[member]:
                (meta_diffs if is_meta else design_diffs).append(
                    {"member": member, "state": "differs"})
            continue

        if _canonical(ldoc) == _canonical(cdoc):
            continue

        if member == "project.json":
            # Strip the name too and see whether anything else moved. This is
            # the line that separates "renamed" from "redesigned".
            l2 = _strip_volatile(ldoc)
            c2 = _strip_volatile(cdoc)
            for doc in (l2, c2):
                if isinstance(doc.get("project"), dict):
                    for key in NAME_KEYS:
                        doc["project"].pop(key, None)
            if json.dumps(l2, sort_keys=True) == json.dumps(c2, sort_keys=True):
                continue
            meta_diffs.append({"member": member, "state": "differs"})
            continue

        detail = _describe_collection(ldoc, cdoc)
        entry = {"member": member, "state": "differs"}
        if detail:
            entry.update(detail)
        (meta_diffs if is_meta else design_diffs).append(entry)

    out["differences"] = (design_diffs + meta_diffs)[:MAX_REPORTED_MEMBERS]
    out["designDiffers"] = bool(design_diffs)
    out["renamedOnly"] = bool(renamed and not design_diffs)
    out["identical"] = not design_diffs and not meta_diffs and not renamed
    out["renamed"] = renamed
    out["summary"] = _summarise(out, design_diffs, renamed)
    return out


def _summarise(out, design_diffs, renamed) -> str:
    if out["identical"]:
        return "Identical - the cloud copy matches your local file."
    if out["renamedOnly"]:
        return ("Renamed only - the design is identical, the project just has "
                "a different name on each side.")
    if not design_diffs:
        return ("No design change - only bookkeeping differs (dates, revision "
                "history).")

    parts = []
    for d in design_diffs[:4]:
        if d.get("kind") == "floor plan image":
            parts.append("a floor plan image")
            continue
        noun = d.get("noun")
        if noun:
            bits = []
            for label in ("added", "removed", "changed"):
                if d.get(label):
                    bits.append("%d %s" % (d[label], label))
            parts.append("%s (%s)" % (noun, ", ".join(bits)) if bits else noun)
        else:
            parts.append(d["member"].replace(".json", ""))
    more = len(design_diffs) - len(parts)
    text = ", ".join(parts) + (" and %d more" % more if more > 0 else "")
    return "Real changes: " + text + ("; also renamed." if renamed else ".")
