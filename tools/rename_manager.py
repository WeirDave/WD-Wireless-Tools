"""
WD Rename Manager — unified backend for folder and file renaming.

Combines token-format renaming (for folders and files based on a CSV site
directory or manual token entry) with rule-based renaming (regex strip,
find/replace, case, separator, prefix/suffix).  Replaces the separate
SiteRenameManager and FolderOrganizer rename code with one module.
"""
import csv
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".wd_wireless_tools"
DIRECTORY_PATH = CONFIG_DIR / "site_directory.json"
PROFILES_PATH = CONFIG_DIR / "rename_profiles.json"
UNDO_DIR = CONFIG_DIR / "rename_undo"

# Legacy paths — checked during profile migration
_LEGACY_PROFILES_PATH = CONFIG_DIR / "site_rename_profiles.json"
_LEGACY_UNDO_DIR = CONFIG_DIR / "site_rename_undo"

BUILTIN_TOKENS = [
    {"key": "site_code",     "label": "Site code"},
    {"key": "site_name",     "label": "Site name"},
    {"key": "facility_code", "label": "Facility code"},
    {"key": "address",       "label": "Address"},
    {"key": "city",          "label": "City"},
    {"key": "state",         "label": "State"},
    {"key": "zip",           "label": "ZIP"},
    {"key": "survey_type",   "label": "Survey type"},
    {"key": "description",   "label": "Description"},
    {"key": "date",          "label": "Date (auto)",  "auto": True},
    {"key": "folder",        "label": "Folder name",  "auto": True},
    {"key": "original",      "label": "Original name", "auto": True, "file_only": True},
    {"key": "index",         "label": "File index",    "auto": True, "file_only": True},
]

BUILTIN_TOKEN_KEYS = {t["key"] for t in BUILTIN_TOKENS}

DEFAULT_FILE_RULES = {
    "strip_prefix": "",
    "strip_suffix": "",
    "regex_from": "",
    "regex_to": "",
    "separator": "",
    "case": "",
    "prefix": "",
    "suffix": "",
}

_SEPARATOR_CHARS = {
    "underscore": "_",
    "hyphen": "-",
    "space": " ",
    "spaced_hyphen": " - ",
}

_INVALID_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ── Filesystem helpers ──────────────────────────────────────────────

def _sanitize_name(name: str) -> str:
    if not name:
        return ""
    cleaned = _INVALID_NAME_RE.sub("-", name).strip().rstrip(".")
    return "" if cleaned in ("", ".", "..") else cleaned


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _split_ext(name: str) -> tuple[str, str]:
    p = Path(name)
    return p.stem, p.suffix


def _undo_path(operation_type: str) -> Path:
    UNDO_DIR.mkdir(parents=True, exist_ok=True)
    return UNDO_DIR / f"{operation_type}_last.json"


# ── Rule-based rename pipeline ──────────────────────────────────────

def _title_case(stem: str) -> str:
    return re.sub(r"[A-Za-z]+",
                  lambda m: m.group(0)[0].upper() + m.group(0)[1:], stem)


def _sentence_case(stem: str) -> str:
    lowered = stem.lower()
    m = re.search(r"[a-z]", lowered)
    if not m:
        return lowered
    i = m.start()
    return lowered[:i] + lowered[i].upper() + lowered[i + 1:]


def _expand_folder_token(text: str, folder_label: str) -> str:
    return (text or "").replace("{folder}", folder_label.strip())


def apply_file_rules(original_name: str, folder_label: str,
                     rules: dict | None = None) -> str:
    """Apply rule-based rename pipeline to a filename.

    Order: strip_prefix → strip_suffix → regex → separator → case → prefix/suffix.
    Extension is preserved untouched.

    `rules` is a dict with keys matching DEFAULT_FILE_RULES.  Accepts either
    a flat rules dict or a legacy dict with a nested ``"rename"`` key (so
    callers passing the full organizer config still work).
    """
    if rules is None:
        return original_name
    r = rules.get("rename", rules) if isinstance(rules, dict) else {}
    if not any((r.get("strip_prefix"), r.get("strip_suffix"), r.get("regex_from"),
                r.get("separator"), r.get("case"), r.get("prefix"), r.get("suffix"))):
        return original_name

    stem, ext = _split_ext(original_name)

    strip = r.get("strip_prefix") or ""
    if strip:
        try:
            stem = re.sub(r"^(?:" + strip + ")", "", stem)
        except re.error:
            pass

    strip_end = r.get("strip_suffix") or ""
    if strip_end:
        try:
            stem = re.sub(r"(?:" + strip_end + ")$", "", stem)
        except re.error:
            pass

    rf = r.get("regex_from") or ""
    rt = r.get("regex_to") or ""
    if rf:
        try:
            stem = re.sub(rf, rt, stem)
        except re.error:
            pass

    sep = _SEPARATOR_CHARS.get(r.get("separator") or "")
    if sep is not None:
        stem = re.sub(r"[\s_-]+", sep, stem).strip(sep)

    case = r.get("case") or ""
    if case == "lower":
        stem = stem.lower()
    elif case == "upper":
        stem = stem.upper()
    elif case == "title":
        stem = _title_case(stem)
    elif case == "sentence":
        stem = _sentence_case(stem)

    prefix = _expand_folder_token(r.get("prefix"), folder_label)
    suffix = _expand_folder_token(r.get("suffix"), folder_label)
    stem = prefix + stem + suffix

    stem = stem or _split_ext(original_name)[0]
    return stem + ext


def migrate_rename_cfg(rn: dict) -> dict:
    """Translate legacy organizer rename config keys to current equivalents."""
    if not isinstance(rn, dict):
        return dict(DEFAULT_FILE_RULES)
    rn = dict(rn)
    if "case" not in rn and rn.pop("lowercase", False):
        rn["case"] = "lower"
    rn.pop("lowercase", None)
    if "prepend_parent" not in rn and "add_site_code" in rn:
        rn["prepend_parent"] = rn.get("add_site_code", False)
    rn.pop("add_site_code", None)
    if "separator" not in rn and rn.pop("collapse_spaces", False):
        rn["separator"] = "underscore"
    rn.pop("collapse_spaces", None)
    if "prefix" not in rn and rn.pop("prepend_parent", False):
        rn["prefix"] = "{folder}_"
    rn.pop("prepend_parent", None)
    return {**DEFAULT_FILE_RULES, **rn}


def _check_collisions(renames: list) -> None:
    """Mark entries with duplicate new_name values as ``collision``."""
    counts: dict[str, int] = {}
    for r in renames:
        if r.get("status") != "rename":
            continue
        key = (r.get("folder", ""), r["new_name"])
        counts[key] = counts.get(key, 0) + 1
    for r in renames:
        if r.get("status") != "rename":
            continue
        key = (r.get("folder", ""), r["new_name"])
        if counts.get(key, 0) > 1:
            r["status"] = "collision"
            r.setdefault("warnings", []).append(
                f"Collision: multiple items would be renamed to '{r['new_name']}'")


# ── Token-format rename ─────────────────────────────────────────────

def apply_token_format(fmt: str, separator: str, values: dict) -> tuple[str, list]:
    """Apply a token format string using the given values dict.

    Replaces ``{token}`` placeholders inline, preserving all literal text in
    the format string.  The *separator* parameter is kept for API
    compatibility but is no longer used — write separators directly in your
    format string (e.g. ``{site_code} - {site_name}``).

    Returns (result_name, warnings).  Missing tokens produce a warning and
    a ``__token__`` placeholder.  Filesystem-unsafe characters are replaced.
    """
    warnings = []
    token_re = re.compile(r"\{(\w+)\}")

    def _replace(m):
        token = m.group(1)
        val = (values.get(token) or "").strip()
        if not val:
            warnings.append(f"Missing value for {{{token}}}")
            return f"__{token}__"
        return val

    result = token_re.sub(_replace, fmt)
    result = re.sub(r'[<>:"/\\|?*]', "_", result)
    return result, warnings


# ── RenameManager class ─────────────────────────────────────────────

class RenameManager:
    def __init__(self):
        self.app_version = ""
        self._migrate_legacy_paths()

    def _migrate_legacy_paths(self):
        """One-time migration from old site_rename paths to new rename paths."""
        if _LEGACY_PROFILES_PATH.exists() and not PROFILES_PATH.exists():
            try:
                _LEGACY_PROFILES_PATH.rename(PROFILES_PATH)
            except OSError:
                pass
        if _LEGACY_UNDO_DIR.exists() and not UNDO_DIR.exists():
            try:
                _LEGACY_UNDO_DIR.rename(UNDO_DIR)
            except OSError:
                pass

    # ── Tokens ──

    def get_tokens(self) -> dict:
        """Return the full token list: builtins + any CSV-derived columns."""
        d = self.get_directory()
        csv_tokens = d.get("tokens", [])
        combined = list(BUILTIN_TOKENS)
        seen = set(BUILTIN_TOKEN_KEYS)
        for tok in csv_tokens:
            key = tok if isinstance(tok, str) else tok.get("key", "")
            if key and key not in seen:
                combined.append({"key": key, "label": key, "csv": True})
                seen.add(key)
        return {"ok": True, "tokens": combined}

    # ── CSV / Directory ──

    def load_directory(self, csv_text: str, column_map: dict) -> dict:
        reader = csv.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames:
            return {"error": "CSV has no header row"}
        headers = list(reader.fieldnames)
        rows = []
        for row in reader:
            rows.append({h: (row.get(h) or "").strip() for h in headers})

        primary_col = column_map.get("primary", "")
        if primary_col and primary_col not in headers:
            return {"error": f"Primary column '{primary_col}' not found in CSV"}

        tokens = list(headers)
        directory = {
            "headers": headers,
            "column_map": column_map,
            "tokens": tokens,
            "sites": rows,
            "loaded_at": datetime.now().isoformat(),
        }

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(DIRECTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(directory, f, indent=2)

        all_tokens = self.get_tokens()["tokens"]
        return {
            "ok": True,
            "site_count": len(rows),
            "tokens": all_tokens,
            "headers": headers,
        }

    def get_directory(self) -> dict:
        if not DIRECTORY_PATH.exists():
            return {"loaded": False, "sites": [], "tokens": [], "headers": []}
        try:
            with open(DIRECTORY_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
            return {
                "loaded": True,
                "site_count": len(d.get("sites", [])),
                "tokens": d.get("tokens", []),
                "headers": d.get("headers", []),
                "column_map": d.get("column_map", {}),
                "sites": d.get("sites", []),
            }
        except Exception as e:
            return {"loaded": False, "error": str(e)}

    def _load_sites(self) -> tuple:
        if not DIRECTORY_PATH.exists():
            return [], {}, []
        with open(DIRECTORY_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("sites", []), d.get("column_map", {}), d.get("headers", [])

    # ── Matching ──

    def _match_folder_to_site(self, folder_name: str, sites: list,
                              column_map: dict) -> tuple:
        primary_col = column_map.get("primary", "")
        address_col = column_map.get("address", "")
        deprecated_col = column_map.get("deprecated", "")
        fn_lower = folder_name.lower().strip()

        if primary_col:
            for site in sites:
                val = (site.get(primary_col) or "").strip()
                if val and val.lower() == fn_lower:
                    return site, "exact", 1.0

        if primary_col:
            for site in sites:
                val = (site.get(primary_col) or "").strip()
                if val and val.lower() in fn_lower:
                    return site, "contains-id", 0.8
                if val and fn_lower in val.lower():
                    return site, "id-contains", 0.7

        if address_col:
            for site in sites:
                addr = (site.get(address_col) or "").strip().lower()
                if addr and addr in fn_lower:
                    return site, "address", 0.6
                if addr:
                    addr_parts = addr.split()
                    if len(addr_parts) >= 2:
                        matched = sum(1 for p in addr_parts if p in fn_lower)
                        if matched >= len(addr_parts) * 0.5:
                            return site, "address-partial", 0.4

        if deprecated_col:
            for site in sites:
                dep = (site.get(deprecated_col) or "").strip()
                if not dep:
                    continue
                for old_name in dep.split(";"):
                    old_name = old_name.strip()
                    if old_name and old_name.lower() == fn_lower:
                        return site, "deprecated", 0.9

        return None, "unmatched", 0.0

    def match_folders(self, root: str) -> dict:
        root_path = Path(root)
        if not root_path.is_dir():
            return {"error": f"Not a directory: {root}"}
        sites, column_map, headers = self._load_sites()
        if not sites:
            return {"error": "No site directory loaded"}

        folders = sorted(
            [d.name for d in root_path.iterdir() if d.is_dir()],
            key=str.lower,
        )

        matches = []
        used_sites = set()
        for folder in folders:
            site, method, confidence = self._match_folder_to_site(
                folder, sites, column_map)
            primary_col = column_map.get("primary", "")
            site_id = (site.get(primary_col, "")
                       if site and primary_col else None)
            matches.append({
                "folder": folder,
                "site": site,
                "site_id": site_id,
                "method": method,
                "confidence": confidence,
            })
            if site_id:
                used_sites.add(site_id)

        primary_col = column_map.get("primary", "")
        unmatched_sites = []
        if primary_col:
            for site in sites:
                sid = site.get(primary_col, "")
                if sid and sid not in used_sites:
                    unmatched_sites.append(site)

        return {
            "ok": True,
            "matches": matches,
            "unmatched_sites": unmatched_sites,
            "total_folders": len(folders),
            "matched_count": sum(1 for m in matches if m["site"]),
        }

    # ── Folder rename (token-based) ──

    def preview_folder_rename(self, root: str, format_str: str,
                              separator: str = " - ",
                              manual_values: dict | None = None) -> dict:
        """Preview folder renames.

        If a CSV is loaded, matches folders to CSV rows and uses row values
        for token expansion.  If ``manual_values`` is provided (no CSV mode),
        applies that single set of values to each folder.
        """
        if manual_values:
            return self._preview_folder_rename_manual(
                root, format_str, separator, manual_values)

        match_result = self.match_folders(root)
        if "error" in match_result:
            return match_result

        renames = []
        for m in match_result["matches"]:
            if not m["site"]:
                renames.append({
                    "current": m["folder"],
                    "new_name": None,
                    "status": "unmatched",
                    "warnings": [],
                })
                continue
            new_name, warnings = apply_token_format(
                format_str, separator, m["site"])
            status = ("already_correct" if new_name == m["folder"]
                      else "rename")
            renames.append({
                "current": m["folder"],
                "new_name": new_name,
                "status": status,
                "warnings": warnings,
            })

        _check_collisions(renames)
        return {
            "ok": True,
            "renames": renames,
            "rename_count": sum(1 for r in renames if r["status"] == "rename"),
            "correct_count": sum(
                1 for r in renames if r["status"] == "already_correct"),
            "unmatched_count": sum(
                1 for r in renames if r["status"] == "unmatched"),
        }

    def _preview_folder_rename_manual(self, root: str, format_str: str,
                                      separator: str,
                                      values: dict) -> dict:
        root_path = Path(root)
        if not root_path.is_dir():
            return {"error": f"Not a directory: {root}"}

        folders = sorted(
            [d.name for d in root_path.iterdir() if d.is_dir()],
            key=str.lower,
        )
        renames = []
        for folder in folders:
            auto_values = dict(values)
            auto_values.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
            auto_values["folder"] = folder
            new_name, warnings = apply_token_format(
                format_str, separator, auto_values)
            renames.append({
                "current": folder,
                "new_name": new_name,
                "status": "rename" if new_name != folder else "already_correct",
                "warnings": warnings,
            })
        _check_collisions(renames)
        return {
            "ok": True,
            "renames": renames,
            "rename_count": sum(1 for r in renames if r["status"] == "rename"),
        }

    def execute_folder_rename(self, root: str, renames: list) -> dict:
        root_path = Path(root)
        undo_log = []
        renamed = 0
        skipped = 0
        errors = []

        for item in renames:
            current = item.get("current", "")
            new_name = item.get("new_name", "")
            if not current or not new_name or current == new_name:
                skipped += 1
                continue
            src = root_path / current
            dst = root_path / new_name
            if not src.is_dir():
                errors.append(f"Folder not found: {current}")
                continue
            if dst.exists():
                errors.append(f"Target already exists: {new_name}")
                continue
            try:
                os.rename(str(src), str(dst))
                undo_log.append({"old": current, "new": new_name})
                renamed += 1
            except OSError as e:
                errors.append(f"Failed to rename {current}: {e}")

        if undo_log:
            undo_data = {
                "root": root,
                "renames": undo_log,
                "timestamp": datetime.now().isoformat(),
            }
            with open(_undo_path("folders"), "w", encoding="utf-8") as f:
                json.dump(undo_data, f, indent=2)

        return {
            "ok": True,
            "renamed": renamed,
            "skipped": skipped,
            "errors": errors,
        }

    # ── File rename (token-based) ──

    def preview_file_rename(self, root: str, format_str: str,
                            separator: str = " - ") -> dict:
        root_path = Path(root)
        if not root_path.is_dir():
            return {"error": f"Not a directory: {root}"}
        sites, column_map, headers = self._load_sites()
        if not sites:
            return {"error": "No site directory loaded"}

        has_original = "{original}" in format_str
        has_index = "{index}" in format_str

        renames = []
        for folder_dir in sorted(root_path.iterdir()):
            if not folder_dir.is_dir():
                continue
            site, method, confidence = self._match_folder_to_site(
                folder_dir.name, sites, column_map)
            if not site:
                continue
            files = sorted(
                [f for f in folder_dir.iterdir() if not f.is_dir()],
                key=lambda p: p.name.lower(),
            )
            for idx, fpath in enumerate(files, 1):
                ext = fpath.suffix
                stem = _split_ext(fpath.name)[0]
                values = dict(site)
                values["original"] = stem
                values["index"] = str(idx)
                new_stem, warnings = apply_token_format(
                    format_str, separator, values)
                new_name = new_stem + ext
                status = ("already_correct" if fpath.name == new_name
                          else "rename")
                renames.append({
                    "folder": folder_dir.name,
                    "current": fpath.name,
                    "new_name": new_name,
                    "status": status,
                    "warnings": warnings,
                })

        _check_collisions(renames)
        return {
            "ok": True,
            "renames": renames,
            "rename_count": sum(1 for r in renames if r["status"] == "rename"),
        }

    def execute_file_rename(self, root: str, renames: list) -> dict:
        root_path = Path(root)
        undo_log = []
        renamed = 0
        errors = []

        for item in renames:
            folder = item.get("folder", "")
            current = item.get("current", "")
            new_name = item.get("new_name", "")
            if not folder or not current or not new_name or current == new_name:
                continue
            src = root_path / folder / current
            dst = root_path / folder / new_name
            if not src.is_file():
                errors.append(f"File not found: {folder}/{current}")
                continue
            if dst.exists():
                errors.append(f"Target exists: {folder}/{new_name}")
                continue
            try:
                os.rename(str(src), str(dst))
                undo_log.append({"folder": folder, "old": current,
                                 "new": new_name})
                renamed += 1
            except OSError as e:
                errors.append(f"Failed: {folder}/{current}: {e}")

        if undo_log:
            undo_data = {
                "root": root,
                "renames": undo_log,
                "timestamp": datetime.now().isoformat(),
            }
            with open(_undo_path("files"), "w", encoding="utf-8") as f:
                json.dump(undo_data, f, indent=2)

        return {"ok": True, "renamed": renamed, "errors": errors}

    # ── Rule-based bulk rename (files in place) ──

    def detect_rename_style(self, root: str | None = None,
                            skip: set | None = None,
                            subfolder_names: list | None = None) -> dict:
        root_path = Path(root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set"}

        skip = skip or set()
        subfolder_names = subfolder_names or []
        votes = {"spaced_hyphen": 0, "underscore": 0,
                 "hyphen": 0, "space": 0}

        def tally(d: Path):
            if not d.is_dir():
                return
            for f in d.iterdir():
                if (not f.is_file() or f.name.startswith(".")
                        or f.suffix.lower() == ".esx"):
                    continue
                stem = _split_ext(f.name)[0]
                if " - " in stem:
                    votes["spaced_hyphen"] += 1
                elif "_" in stem:
                    votes["underscore"] += 1
                elif "-" in stem:
                    votes["hyphen"] += 1
                elif " " in stem:
                    votes["space"] += 1

        site_dirs = [
            d for d in sorted(root_path.iterdir())
            if d.is_dir() and d.name.lower() not in skip
            and not d.name.startswith(".")
        ]
        for site_dir in (site_dirs or [root_path]):
            tally(site_dir)
            for sf in subfolder_names:
                tally(site_dir / sf)

        best = max(votes, key=votes.get)
        runner_up = max(
            (v for k, v in votes.items() if k != best), default=0)
        separator = (best if votes[best] > 0 and votes[best] > runner_up
                     else "")
        return {"ok": True, "separator": separator, "votes": votes}

    def preview_bulk_rename(self, root: str | None = None,
                            rules: dict | None = None,
                            skip: set | None = None,
                            subfolder_names: list | None = None) -> dict:
        """Dry-run rule-based rename across files under root."""
        root_path = Path(root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set"}

        skip = skip or set()
        subfolder_names = subfolder_names or []
        cfg = {"rename": rules} if rules else {"rename": DEFAULT_FILE_RULES}

        def scan_site(site_dir: Path) -> list:
            found = []
            candidate_dirs = ([site_dir]
                              + [site_dir / sf for sf in subfolder_names])
            for d in candidate_dirs:
                if not d.is_dir():
                    continue
                for f in sorted(d.iterdir()):
                    if (not f.is_file() or f.name.startswith(".")
                            or f.suffix.lower() == ".esx"):
                        continue
                    new_name = apply_file_rules(f.name, site_dir.name, cfg)
                    if new_name == f.name:
                        continue
                    found.append({
                        "site": site_dir.name,
                        "dir": str(d),
                        "path": str(f),
                        "old_name": f.name,
                        "new_name": new_name,
                    })
            return found

        site_dirs = [
            d for d in sorted(root_path.iterdir())
            if d.is_dir() and d.name.lower() not in skip
            and not d.name.startswith(".")
        ]
        items = []
        for site_dir in site_dirs:
            items.extend(scan_site(site_dir))
        if not site_dirs:
            items.extend(scan_site(root_path))
        return {"ok": True, "items": items, "count": len(items)}

    def execute_bulk_rename(self, items: list | None = None) -> dict:
        if not items:
            return {"ok": False, "error": "Nothing to rename"}
        renamed = 0
        skipped = 0
        undo_log = []
        details = []
        for it in items:
            src = Path(it.get("path") or "")
            new_name = _sanitize_name(it.get("new_name") or "")
            if not src.is_file() or not new_name:
                skipped += 1
                details.append({"old_name": src.name,
                                "new_name": it.get("new_name"),
                                "status": "error",
                                "reason": "invalid path or name"})
                continue
            dst = src.parent / new_name
            if not _is_inside(dst, src.parent):
                skipped += 1
                details.append({"old_name": src.name, "new_name": new_name,
                                "status": "error",
                                "reason": "invalid target name"})
                continue
            if dst.exists():
                skipped += 1
                details.append({"old_name": src.name, "new_name": new_name,
                                "status": "skipped",
                                "reason": "target exists"})
                continue
            try:
                src.rename(dst)
                renamed += 1
                undo_log.append({"path": str(dst), "old_name": src.name,
                                 "new_name": new_name})
                details.append({"old_name": src.name, "new_name": new_name,
                                "status": "renamed"})
            except Exception as e:
                skipped += 1
                details.append({"old_name": src.name, "new_name": new_name,
                                "status": "error", "reason": str(e)})

        if undo_log:
            undo_data = {
                "renames": undo_log,
                "timestamp": datetime.now().isoformat(),
            }
            with open(_undo_path("bulk"), "w", encoding="utf-8") as f:
                json.dump(undo_data, f, indent=2)

        return {"ok": True, "renamed": renamed, "skipped": skipped,
                "details": details}

    # ── Gap report ──

    def gap_report(self, root: str) -> dict:
        root_path = Path(root)
        if not root_path.is_dir():
            return {"error": f"Not a directory: {root}"}
        sites, column_map, headers = self._load_sites()
        if not sites:
            return {"error": "No site directory loaded"}

        primary_col = column_map.get("primary", "")
        has_data = []
        empty = []
        orphans = []
        matched_ids = set()

        for folder_dir in sorted(root_path.iterdir()):
            if not folder_dir.is_dir():
                continue
            site, method, conf = self._match_folder_to_site(
                folder_dir.name, sites, column_map)
            files = [f.name for f in folder_dir.iterdir() if f.is_file()]
            project_files = [f for f in files if f.lower().endswith(".esx")]

            if site and primary_col:
                matched_ids.add(site.get(primary_col, ""))

            entry = {"folder": folder_dir.name, "file_count": len(files),
                     "project_files": project_files}
            if not site:
                orphans.append(entry)
            elif project_files:
                has_data.append(entry)
            else:
                empty.append(entry)

        not_started = []
        if primary_col:
            for site in sites:
                sid = site.get(primary_col, "")
                if sid and sid not in matched_ids:
                    not_started.append({"site_id": sid, "site": site})

        return {
            "ok": True,
            "has_data": has_data,
            "empty": empty,
            "not_started": not_started,
            "orphans": orphans,
        }

    # ── Undo ──

    def undo_last(self, operation_type: str) -> dict:
        undo_file = _undo_path(operation_type)
        if not undo_file.exists():
            return {"error": f"No undo log for {operation_type}"}
        with open(undo_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        root_path = Path(data["root"]) if "root" in data else None
        reverted = 0
        errors = []

        if operation_type == "folders":
            for entry in reversed(data.get("renames", [])):
                src = root_path / entry["new"]
                dst = root_path / entry["old"]
                if not src.exists():
                    errors.append(f"Not found: {entry['new']}")
                    continue
                try:
                    os.rename(str(src), str(dst))
                    reverted += 1
                except OSError as e:
                    errors.append(
                        f"Failed: {entry['new']} → {entry['old']}: {e}")
        elif operation_type == "files":
            for entry in reversed(data.get("renames", [])):
                folder = entry.get("folder", "")
                src = root_path / folder / entry["new"]
                dst = root_path / folder / entry["old"]
                if not src.exists():
                    errors.append(f"Not found: {folder}/{entry['new']}")
                    continue
                try:
                    os.rename(str(src), str(dst))
                    reverted += 1
                except OSError as e:
                    errors.append(str(e))
        elif operation_type == "bulk":
            for entry in reversed(data.get("renames", [])):
                dst_path = Path(entry["path"])
                src = dst_path
                dst = dst_path.parent / entry["old_name"]
                if not src.exists():
                    errors.append(f"Not found: {entry['path']}")
                    continue
                try:
                    os.rename(str(src), str(dst))
                    reverted += 1
                except OSError as e:
                    errors.append(str(e))

        os.remove(str(undo_file))
        return {"ok": True, "reverted": reverted, "errors": errors}

    # ── Profiles ──

    def save_profile(self, name: str, folder_fmt: str = "",
                     file_fmt: str = "", separator: str = " - ",
                     file_rules: dict | None = None) -> dict:
        profiles = self._load_profiles()
        profiles[name] = {
            "folder_format": folder_fmt,
            "file_format": file_fmt,
            "separator": separator,
            "file_rules": file_rules or {},
            "saved_at": datetime.now().isoformat(),
        }
        self._save_profiles(profiles)
        return {"ok": True}

    def delete_profile(self, name: str) -> dict:
        profiles = self._load_profiles()
        if name in profiles:
            del profiles[name]
            self._save_profiles(profiles)
        return {"ok": True}

    def list_profiles(self) -> dict:
        return {"profiles": self._load_profiles()}

    def _load_profiles(self) -> dict:
        if not PROFILES_PATH.exists():
            return {}
        try:
            with open(PROFILES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_profiles(self, profiles: dict):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(PROFILES_PATH, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2)

    # ── CSV Helper ──

    def generate_csv_template(self, format_str: str = "") -> dict:
        """Generate a CSV template with columns matching the tokens in the
        given format string, plus any useful built-in columns.  Returns the
        CSV text and column list."""
        token_re = re.compile(r"\{(\w+)\}")
        format_tokens = token_re.findall(format_str) if format_str else []
        columns = []
        seen = set()
        for tok in format_tokens:
            if tok not in seen and tok not in ("date", "folder"):
                columns.append(tok)
                seen.add(tok)
        for bt in BUILTIN_TOKENS:
            key = bt["key"]
            if key not in seen and not bt.get("auto"):
                columns.append(key)
                seen.add(key)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        return {
            "ok": True,
            "csv_text": output.getvalue(),
            "columns": columns,
        }

    def prefill_from_folders(self, root: str,
                             format_str: str = "") -> dict:
        """Scan existing folders and generate a partially-filled CSV.  Each
        folder becomes a row.  If the format string has tokens, attempts to
        reverse-parse folder names; otherwise just places the folder name in
        the first column."""
        root_path = Path(root)
        if not root_path.is_dir():
            return {"error": f"Not a directory: {root}"}

        template_result = self.generate_csv_template(format_str)
        columns = template_result["columns"]
        if not columns:
            columns = ["site_name"]

        folders = sorted(
            [d.name for d in root_path.iterdir() if d.is_dir()],
            key=str.lower,
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        for folder in folders:
            row = [""] * len(columns)
            row[0] = folder
            writer.writerow(row)

        return {
            "ok": True,
            "csv_text": output.getvalue(),
            "columns": columns,
            "folder_count": len(folders),
        }

    # ── Folder picker (Tk dialog) ──

    def pick_folder(self) -> dict:
        code = (
            "import tkinter as tk\n"
            "from tkinter import filedialog\n"
            "root = tk.Tk()\n"
            "root.withdraw()\n"
            "root.wm_attributes('-topmost', True)\n"
            "p = filedialog.askdirectory("
            "title='Select site projects root folder')\n"
            "print(p or '')\n"
        )
        try:
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = 0x08000000
            out = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=180, **kwargs,
            )
            path = out.stdout.strip()
            return {"path": path} if path else {"path": ""}
        except Exception:
            return {"path": ""}

    @staticmethod
    def get_default_root() -> dict:
        """Return the Ekahau AI Pro default projects folder."""
        return {"path": str(Path.home() / "Documents" / "Ekahau Ai Pro" / "Projects")}
