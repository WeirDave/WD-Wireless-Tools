"""
Unified settings for WD Wireless Tools.

Single source of truth at ~/.wd_wireless_tools/settings.json.
Replaces the per-module config files (organizer_config.json, config.json)
while leaving data stores (cookies, matches, undo logs) untouched.
"""
import copy
import json
import os
import re
import tempfile
from pathlib import Path

SETTINGS_DIR = Path.home() / ".wd_wireless_tools"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
LEGACY_ORGANIZER_CONFIG = SETTINGS_DIR / "organizer_config.json"
LEGACY_CLOUD_CONFIG = SETTINGS_DIR / "config.json"

_BUILTIN_KEYS = ("images", "floorplans", "reports")

DEFAULTS = {
    "_version": 1,
    "setup_complete": False,
    "global": {
        "output_dir": "",
        "subfolders": ["images", "floorplans", "reports"],
        "subfolder_names": {
            "images": "images",
            "floorplans": "floorplans",
            "reports": "reports",
        },
        "custom_destinations": [],
    },
    "organizer": {
        "image_ext": [
            ".png", ".jpg", ".jpeg", ".gif", ".bmp",
            ".tif", ".tiff", ".svg", ".webp", ".heic",
        ],
        "plan_ext": [".dwg", ".dxf", ".vsd", ".vsdx", ".pcp"],
        "report_ext": [
            ".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".csv",
            ".pptx", ".ppt", ".html", ".htm", ".txt", ".rtf",
        ],
        "report_keywords": [
            "report", "audit", "coverage", "validation",
            "bom", "as-built", "asbuilt", "summary",
        ],
        "json_report_keywords": [
            "waxframe", "checkpoint", "assessment", "report",
        ],
        "skip_dirs": [
            "backups", "backup", "output", "outputs",
            "archive", "archives", ".git",
            "images", "floorplans", "reports",
        ],
        "create_folder_template": "",
        "rename": {
            "strip_prefix": "",
            "strip_suffix": "",
            "regex_from": "",
            "regex_to": "",
            "separator": "",
            "case": "",
            "prefix": "",
            "suffix": "",
        },
    },
    "cloud": {
        "merge_rule": "ask",
        "live_interval_ms": 30000,
    },
    "rename": {
        "folder_format": "",
        "file_format": "",
        "separator": " - ",
        "file_rules": {
            "strip_prefix": "",
            "strip_suffix": "",
            "regex_from": "",
            "regex_to": "",
            "separator": "",
            "case": "",
            "prefix": "",
            "suffix": "",
        },
    },
    "report": {
        # Defaults every report starts from. An individual report may diverge
        # from these without changing them.
        "client_name": "",
        "prepared_by": "",
        "project_ref": "",
        "revision": "",
        # The revision is a version number, so it earns a place in the saved
        # filename -- but not everyone names files that way, hence the switch.
        "include_revision_in_filename": True,
    },
    "walls": {},
}


def _deep_merge(base, override):
    """Recursively merge *override* into *base*, returning a new dict."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


_CREATE_TOKEN_MIGRATION = {
    "{code}": "{site_code}",
    "{name}": "{site_name}",
}


def _migrate_settings(settings):
    """In-place migration of legacy keys to current schema."""
    org = settings.get("organizer", {})
    rn_section = settings.setdefault("rename", copy.deepcopy(DEFAULTS["rename"]))

    old_rename = org.get("rename")
    if old_rename and isinstance(old_rename, dict):
        has_rules = any(old_rename.get(k) for k in (
            "strip_prefix", "strip_suffix", "regex_from",
            "separator", "case", "prefix", "suffix"))
        current_rules = rn_section.get("file_rules", {})
        current_has = any(current_rules.get(k) for k in (
            "strip_prefix", "strip_suffix", "regex_from",
            "separator", "case", "prefix", "suffix"))
        if has_rules and not current_has:
            rn_section["file_rules"] = {
                **DEFAULTS["rename"]["file_rules"], **old_rename}

    tmpl = org.get("create_folder_template", "")
    if tmpl:
        for old_tok, new_tok in _CREATE_TOKEN_MIGRATION.items():
            tmpl = tmpl.replace(old_tok, new_tok)
        org["create_folder_template"] = tmpl

    return settings


def load_settings(_path=None):
    """Load settings.json, filling in defaults for any missing keys.

    *_path* overrides SETTINGS_FILE so callers with a patched config
    directory can pass their own location.
    """
    path = Path(_path) if _path else SETTINGS_FILE
    settings = copy.deepcopy(DEFAULTS)
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            settings = _deep_merge(settings, saved)
        except Exception:
            pass
    return _migrate_settings(settings)


def save_settings(settings, _path=None):
    """Write settings.json atomically."""
    path = Path(_path) if _path else SETTINGS_FILE
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(parent), suffix=".tmp", prefix="settings_"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        tmp = Path(tmp_path)
        tmp.replace(path)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise


def update_settings(patch, _path=None):
    """Deep-merge *patch* into current settings, save, and return the result."""
    current = load_settings(_path=_path)
    merged = _deep_merge(current, patch)
    save_settings(merged, _path=_path)
    return merged


def needs_setup():
    """True when the first-run wizard should be shown."""
    if not SETTINGS_DIR.exists() or not SETTINGS_FILE.exists():
        return True
    settings = load_settings()
    return not settings.get("setup_complete", False)


def migrate_legacy():
    """One-time migration from per-module config files to unified settings.

    Reads organizer_config.json and config.json, splits keys into the
    unified schema, writes settings.json with setup_complete=True
    (existing user has already been using the app).  Legacy files are
    left in place as inert backups.

    Returns the new settings dict.  If settings.json already exists,
    returns it unchanged (idempotent).
    """
    if SETTINGS_FILE.exists():
        return load_settings()

    settings = copy.deepcopy(DEFAULTS)
    settings["setup_complete"] = True

    _GLOBAL_KEYS = {"subfolders", "subfolder_names", "custom_destinations"}

    if LEGACY_ORGANIZER_CONFIG.exists():
        try:
            with open(LEGACY_ORGANIZER_CONFIG, encoding="utf-8") as f:
                org = json.load(f)
            for key in _GLOBAL_KEYS:
                if key in org:
                    settings["global"][key] = org[key]
            for key, val in org.items():
                if key in _GLOBAL_KEYS:
                    continue
                if key in settings["organizer"]:
                    settings["organizer"][key] = val
        except Exception:
            pass

    if LEGACY_CLOUD_CONFIG.exists():
        try:
            with open(LEGACY_CLOUD_CONFIG, encoding="utf-8") as f:
                cloud = json.load(f)
            if cloud.get("output_dir"):
                settings["global"]["output_dir"] = cloud["output_dir"]
        except Exception:
            pass

    save_settings(settings)
    return settings


def get_destinations():
    """Canonical subfolder resolver — returns the effective destination list.

    Delegates to folder_organizer._get_destinations() with a cfg dict
    assembled from the unified settings, so the resolution logic stays
    in one place.
    """
    from tools.folder_organizer import _get_destinations

    settings = load_settings()
    g = settings.get("global", {})
    o = settings.get("organizer", {})

    cfg = dict(o)
    cfg["subfolders"] = g.get("subfolders", DEFAULTS["global"]["subfolders"])
    cfg["subfolder_names"] = g.get("subfolder_names", DEFAULTS["global"]["subfolder_names"])
    cfg["custom_destinations"] = g.get("custom_destinations", [])
    return _get_destinations(cfg)
