"""Export and import everything the suite remembers about how he works.

Written after a night of testing overwrote his live settings: his Quick Walls
defaults went, his wall-type colours went, and his keyboard shortcuts survived
only because he had typed them into OneNote. This is the file that makes that
recoverable, and it is also how a setting gets from the machine at home to the
machine at work, which is a thing he asked for separately.

**Keyboard shortcuts are not their own store.** `keybindNumber` is a field on
each wall type *inside a wall template*, so the thing that saves his shortcuts
is including `templates/`. That is the single most important payload here and
the reason `templates/` is not optional.

**What is never exported.** `cookies.enc` is the encrypted Ekahau session - a
credential, and a backup file is exactly the wrong place for one. `acorn_state/`
is per-project state keyed by a path hash, 1800-odd files of where he was up to
rather than how he likes things. `organizer_undo/` is an undo journal. None of
those are preferences and the first is a hazard.

**Machine-specific values travel but are flagged.** A folder path from the home
machine is wrong on the work one, so anything path-shaped is marked, and the
preview says whether that path exists here before he agrees to it.
"""
from __future__ import annotations

import base64
import copy
import datetime as _dt
import json
import shutil
from pathlib import Path

from tools import backups as _backups
from tools import settings as _settings

SCHEMA_VERSION = 1
APP_NAME = "WD Wireless Tools"

#: Files and folders under the user-data directory that are part of "how he
#: works" rather than "where this machine got to".
EXPORT_FILES = (
    "organizer_config.json",
    "plantrim-boxes.json",
    "not_matches.json",
    "manual_matches.json",
    "config.json",
)
EXPORT_DIRS = ("templates", "capacity", "report")

#: Never, under any circumstances. `cookies.enc` is a credential; the other two
#: are machine state and would make the bundle enormous for no benefit.
NEVER_EXPORT = ("cookies.enc", "cookies.json", "acorn_state", "organizer_undo")

#: Settings whose value is a path, so it means something different on another
#: machine. Exported, flagged, and checked against the disk in the preview.
MACHINE_SPECIFIC_SETTINGS = ("global.output_dir",)
MACHINE_SPECIFIC_BROWSER = ("wd-project-directory", "wd-rename-root")

#: The only localStorage keys a restore puts back.
#:
#: The registry's own rule: ui-state "deliberately stays in localStorage:
#: syncing a collapsed panel between machines would be a regression, not a
#: feature". So panel widths, folded sections and dismissed tips are exported
#: - a backup that quietly omits things is not a backup, and he should be able
#: to read the file and see everything - but they are never written back.
#: Restoring them would carry the work machine's layout onto the laptop, which
#: is the regression that rule exists to prevent.
#:
#: These two are the exceptions because they follow the person rather than the
#: window: which theme he reads in, and which Ekahau sharing group he works
#: with. Both are filed as ui-state today and behave like preferences; they are
#: restored here rather than reclassified, because moving a key between stores
#: needs a migration and is not this feature's job.
RESTORABLE_BROWSER_KEYS = ("wd-theme", "wd-sharing-group")

#: Text-ish payloads are embedded as JSON so he can open the bundle and read
#: his own values. Anything else (a report cover image) goes in as base64 and
#: says so.
_TEXT_SUFFIXES = {".json", ".csv", ".txt", ".md"}


def _user_dir() -> Path:
    # Read through the settings module rather than recomputing, so a test that
    # patches the config directory patches this too.
    return Path(_settings.SETTINGS_FILE).parent


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _app_version() -> str:
    try:
        from tools import updater
        return updater.local_version()
    except Exception:
        return ""


def _read_payload(path: Path) -> dict | None:
    """One file, in the most readable form it can honestly take."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if path.suffix.lower() in _TEXT_SUFFIXES:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            if path.suffix.lower() == ".json":
                try:
                    return {"json": json.loads(text)}
                except json.JSONDecodeError:
                    # Keep it rather than drop it. A file he can still read is
                    # worth more than a clean bundle.
                    return {"text": text, "note": "not valid JSON when exported"}
            return {"text": text}
    return {"base64": base64.b64encode(raw).decode("ascii"),
            "bytes": len(raw)}


def _write_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if "json" in payload:
        path.write_text(json.dumps(payload["json"], indent=2), encoding="utf-8")
    elif "text" in payload:
        path.write_text(payload["text"], encoding="utf-8")
    elif "base64" in payload:
        path.write_bytes(base64.b64decode(payload["base64"]))


def _collect_files(root: Path) -> dict:
    out = {}
    for name in EXPORT_FILES:
        p = root / name
        if p.is_file():
            payload = _read_payload(p)
            if payload is not None:
                out[name] = payload
    for folder in EXPORT_DIRS:
        d = root / folder
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if any(part in NEVER_EXPORT for part in p.parts):
                continue
            # Dot-files are markers, not choices - `templates/.migrated` says a
            # one-time migration already ran here. Restoring that onto a
            # machine whose legacy templates have NOT been moved yet would skip
            # the migration and lose them, so a marker never travels.
            if p.name.startswith("."):
                continue
            payload = _read_payload(p)
            if payload is not None:
                out[rel] = payload
    return out


def export_bundle(browser: dict | None = None, root: Path | None = None) -> dict:
    """Everything user-configured, in one readable document."""
    root = Path(root) if root else _user_dir()
    bundle = {
        "schema": SCHEMA_VERSION,
        "app": APP_NAME,
        "appVersion": _app_version(),
        "exportedAt": _now_iso(),
        "settings": _settings.load_settings(),
        "files": _collect_files(root),
        "browser": dict(browser or {}),
        "notes": {
            "excluded": list(NEVER_EXPORT),
            "why": ("cookies.enc is a saved login and is never exported; "
                    "acorn_state and organizer_undo are per-project machine "
                    "state, not preferences."),
            "keyboardShortcuts": ("Quick Walls shortcuts are the keybindNumber "
                                  "field on each wall type inside "
                                  "templates/, so they are in this file."),
        },
    }
    return bundle


def suggested_filename(bundle: dict | None = None) -> str:
    when = _dt.datetime.now().strftime("%Y-%m-%d")
    return f"wd-wireless-tools-settings-{when}.json"


def note_export_taken() -> str:
    """Record that an export just happened, so the page can say how old it is.

    A backup nobody can date is one he has to trust rather than check. Recorded
    only for an export he asked for - an automatic dump before an update is the
    suite protecting itself and would make the figure read as reassurance he
    did not earn.
    """
    when = _now_iso()
    try:
        _settings.update_settings({"global": {"last_settings_export": when}})
    except Exception:
        return ""
    return when


# ── comparing a bundle with what is here now ──────────────────────────────

def _flatten(obj, prefix=""):
    """Dotted leaf keys, so a diff can be read a line at a time.

    A dict that REPLACE_NOT_MERGE treats as one value is a leaf here too -
    splitting a keyed store into dotted paths would report a rename as one
    addition and one deletion rather than as the single change it is.
    """
    out = {}
    # REPLACE_NOT_MERGE holds tuples of path segments, not dotted strings.
    replace_whole = {".".join(p) for p in
                     (getattr(_settings, "REPLACE_NOT_MERGE", ()) or ())}
    for key, value in (obj or {}).items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and path not in replace_whole:
            out.update(_flatten(value, path + "."))
        else:
            out[path] = value
    return out


def _diff_map(incoming: dict, current: dict, known: set | None = None) -> dict:
    add, change, same, unknown = [], [], [], []
    for key in sorted(incoming):
        new = incoming[key]
        if key not in current:
            entry = {"key": key, "new": new}
            (unknown if known is not None and key not in known else add).append(entry)
        elif current[key] != new:
            change.append({"key": key, "old": current[key], "new": new})
        else:
            same.append({"key": key, "new": new})
    return {"add": add, "change": change, "same": same, "unknown": unknown}


def preview_import(bundle: dict, browser: dict | None = None,
                   root: Path | None = None) -> dict:
    """What importing this would change, before anything is written.

    He has had settings change underneath him twice in one night. Nothing here
    writes; the caller shows this and asks.
    """
    root = Path(root) if root else _user_dir()
    if not isinstance(bundle, dict):
        return {"ok": False, "error": "That file is not a settings export."}

    schema = bundle.get("schema")
    if not isinstance(schema, int):
        return {"ok": False,
                "error": "That file has no schema version, so it is not a "
                         "settings export this can read."}

    result = {
        "ok": True,
        "from": {
            "appVersion": bundle.get("appVersion") or "unknown",
            "exportedAt": bundle.get("exportedAt") or "unknown",
            "schema": schema,
        },
        "schemaNewer": schema > SCHEMA_VERSION,
        "schemaNotes": [],
    }
    if schema > SCHEMA_VERSION:
        result["schemaNotes"].append(
            f"This export came from a newer version (schema {schema}; this "
            f"install understands {SCHEMA_VERSION}). Everything recognised is "
            f"listed below and anything unrecognised is listed as well, so "
            f"nothing is dropped without being named.")

    incoming_settings = _flatten(bundle.get("settings") or {})
    current_settings = _flatten(_settings.load_settings())
    known = set(_flatten(copy.deepcopy(_settings.DEFAULTS)))
    result["settings"] = _diff_map(incoming_settings, current_settings, known)

    incoming_files = bundle.get("files") or {}
    file_diff = {"add": [], "change": [], "same": []}
    for rel in sorted(incoming_files):
        here = root / rel
        payload = incoming_files[rel]
        if not here.is_file():
            file_diff["add"].append({"key": rel, "new": _describe(payload)})
            continue
        mine = _read_payload(here)
        if mine == payload:
            file_diff["same"].append({"key": rel, "new": _describe(payload)})
        else:
            file_diff["change"].append({"key": rel, "old": _describe(mine),
                                        "new": _describe(payload)})
    result["files"] = file_diff

    # Only what would actually be written is diffed. Listing panel widths as
    # "will change" and then not changing them is the kind of preview that
    # teaches him to stop reading previews.
    incoming_browser = bundle.get("browser") or {}
    restorable = {k: v for k, v in incoming_browser.items()
                  if k in RESTORABLE_BROWSER_KEYS}
    result["browser"] = _diff_map(restorable, dict(browser or {}))
    result["browserNotRestored"] = sorted(set(incoming_browser)
                                          - set(RESTORABLE_BROWSER_KEYS))

    # Paths mean something different on another machine, so each one is
    # checked against this disk rather than assumed.
    flagged = []
    for key in MACHINE_SPECIFIC_SETTINGS:
        if key in incoming_settings:
            value = incoming_settings[key]
            flagged.append({"key": key, "new": value, "where": "settings",
                            "existsHere": bool(value) and Path(str(value)).exists()})
    for key in MACHINE_SPECIFIC_BROWSER:
        if key in incoming_browser:
            value = incoming_browser[key]
            flagged.append({"key": key, "new": value, "where": "browser",
                            "existsHere": bool(value) and Path(str(value)).exists()})
    result["machineSpecific"] = flagged

    counts = {}
    for section in ("settings", "files", "browser"):
        block = result[section]
        counts[section] = {k: len(block.get(k, [])) for k in
                           ("add", "change", "same", "unknown")}
    result["counts"] = counts
    result["willChangeAnything"] = any(
        counts[s]["add"] or counts[s]["change"] for s in counts)
    return result


def _describe(payload: dict | None) -> str:
    """A file, in a few words, without dumping it into the UI."""
    if payload is None:
        return "missing"
    if "json" in payload:
        body = payload["json"]
        if isinstance(body, dict):
            wall_types = body.get("wallTypes")
            if isinstance(wall_types, list):
                binds = sum(1 for w in wall_types
                            if isinstance(w, dict) and w.get("keybindNumber"))
                extra = f", {binds} with a keyboard shortcut" if binds else ""
                return f"{len(wall_types)} wall types{extra}"
            return f"{len(body)} keys"
        if isinstance(body, list):
            return f"{len(body)} entries"
        return "a value"
    if "text" in payload:
        return f"{len(payload['text'])} characters"
    if "base64" in payload:
        return f"{payload.get('bytes', 0)} bytes"
    return "unknown"


# ── writing it back ───────────────────────────────────────────────────────

def backup_current(root: Path | None = None, keep: int | None = None) -> dict:
    """Copy settings.json aside before anything overwrites it.

    Uses the same `.backup-<stamp>` convention and the same retention code as
    every other backup in the suite, so one purge screen covers them all.

    Retention here is `max(1, backup_keep)` on purpose. Turning backups off is
    about routine ones accumulating; an import is a deliberate destructive
    action and its one step back is part of the action rather than clutter.
    """
    root = Path(root) if root else _user_dir()
    live = root / "settings.json"
    if not live.is_file():
        return {"ok": True, "backup": None, "note": "nothing to back up yet"}

    if keep is None:
        try:
            keep = int((_settings.load_settings().get("global") or {})
                       .get("backup_keep", _backups.DEFAULT_KEEP))
        except Exception:
            keep = _backups.DEFAULT_KEEP
    keep = max(1, int(keep or 0))

    # `settings.backup-<stamp>.json`, not `settings.json.backup-<stamp>`.
    # tools/backups.py matches on `path.stem`, so the stamp has to sit before
    # the extension or classify() returns None - and a backup it cannot
    # classify is one the purge screen never sees and retention never prunes,
    # which is precisely the accumulation he asked for a switch against.
    dest = live.with_name(f"{live.stem}.backup-{_stamp()}{live.suffix}")
    shutil.copy2(live, dest)
    # prune_for takes one path to protect, not a list - the backup just made.
    pruned = _backups.prune_for(live, keep=keep, protect=dest)
    return {"ok": True, "backup": str(dest), "keep": keep,
            "pruned": pruned.get("deleted") if isinstance(pruned, dict) else None}


#: Where automatic dumps go. Their own folder so a directory listing reads as
#: "these are my settings backups" rather than as clutter beside settings.json.
AUTO_DIR_NAME = "settings-backups"


def auto_dump(reason: str, root: Path | None = None, keep: int | None = None,
              browser: dict | None = None) -> dict:
    """A full export taken before something that could lose settings.

    Triggered by the operations that have actually cost him settings or could:
    an update, and an import. Roughly 5 KB, so the cheapest insurance in the
    suite.

    Retention is his `backup_keep`, and **0 genuinely means off here** - these
    are the accumulating kind, which is what that switch is for. The one
    exception is the dump taken immediately before an import, which is the undo
    for an action he just asked for rather than a copy piling up, and is kept
    by `backup_current` regardless.

    Pruned per reason, so a run of updates cannot evict the dump taken before
    the last import - the same "five backups of one file do not hide a single
    backup of another" rule `tools/backups.py` already applies.
    """
    root = Path(root) if root else _user_dir()
    if keep is None:
        try:
            keep = int((_settings.load_settings().get("global") or {})
                       .get("backup_keep", _backups.DEFAULT_KEEP))
        except Exception:
            keep = _backups.DEFAULT_KEEP
    keep = int(keep or 0)
    if keep <= 0:
        return {"ok": True, "written": None, "reason": reason,
                "note": "automatic settings backups are switched off "
                        '("Backup copies to keep" is set to Off)'}

    safe = "".join(c for c in str(reason) if c.isalnum() or c in "-_") or "auto"
    folder = root / AUTO_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    # `settings-<reason>.backup-<stamp>.json` - the stamp before the extension,
    # so tools/backups.py classify() recognises it and the Clean up button on
    # the Settings page can see and prune these too.
    owner = folder / f"settings-{safe}.json"
    dest = folder / f"settings-{safe}.backup-{_stamp()}.json"
    try:
        bundle = export_bundle(browser=browser, root=root)
        bundle["takenBecause"] = reason
        dest.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    except Exception as exc:
        # Never fail the operation this was protecting. A missing safety net is
        # bad; an update that refuses to run because of one is worse.
        return {"ok": False, "written": None, "reason": reason,
                "error": f"{type(exc).__name__}: {exc}"}

    pruned = _backups.prune_for(owner, keep=keep, protect=dest)
    return {"ok": True, "written": str(dest), "reason": reason, "keep": keep,
            "pruned": (pruned or {}).get("deleted")}


def apply_import(bundle: dict, sections=("settings", "files"),
                 root: Path | None = None, keep: int | None = None) -> dict:
    """Write the bundle in. Backs up first, always.

    `browser` is never written here - localStorage belongs to the page, so the
    caller hands those keys back to the browser itself.
    """
    root = Path(root) if root else _user_dir()
    want = set(sections or ())
    backup = backup_current(root=root, keep=keep)

    applied = {"settings": 0, "files": []}
    if "settings" in want:
        incoming = bundle.get("settings") or {}
        if incoming:
            _settings.update_settings(incoming)
            applied["settings"] = len(_flatten(incoming))

    if "files" in want:
        for rel, payload in sorted((bundle.get("files") or {}).items()):
            # Refuse anything that would climb out of the user-data directory.
            target = (root / rel).resolve()
            if not str(target).startswith(str(root.resolve())):
                applied.setdefault("refused", []).append(rel)
                continue
            if any(part in NEVER_EXPORT for part in Path(rel).parts):
                applied.setdefault("refused", []).append(rel)
                continue
            _write_payload(target, payload)
            applied["files"].append(rel)

    browser_back = {}
    if "browser" in want:
        incoming = bundle.get("browser") or {}
        browser_back = {k: incoming[k] for k in RESTORABLE_BROWSER_KEYS
                        if k in incoming}

    return {"ok": True, "backup": backup.get("backup"),
            "keep": backup.get("keep"), "applied": applied,
            "browser": browser_back,
            "browserSkipped": sorted(set(bundle.get("browser") or {})
                                     - set(RESTORABLE_BROWSER_KEYS))}
