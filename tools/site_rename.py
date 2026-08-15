"""
WD Site Rename — backend logic for renaming site folders/files
based on a user-provided CSV site directory.

Dynamic token system: every column in the CSV becomes a usable
naming token.  No hardcoded tokens or company branding.
"""
import csv
import hashlib
import io
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".wd_wireless_tools"
DIRECTORY_PATH = CONFIG_DIR / "site_directory.json"
PROFILES_PATH = CONFIG_DIR / "site_rename_profiles.json"
UNDO_DIR = CONFIG_DIR / "site_rename_undo"


def _undo_path(operation_type: str) -> Path:
    UNDO_DIR.mkdir(parents=True, exist_ok=True)
    return UNDO_DIR / f"{operation_type}_last.json"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


class SiteRenameManager:
    def __init__(self):
        self.app_version = ""

    def load_directory(self, csv_text: str, column_map: dict) -> dict:
        reader = csv.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames:
            return {"error": "CSV has no header row"}
        headers = list(reader.fieldnames)
        rows = []
        for row in reader:
            rows.append({h: (row.get(h) or "").strip() for h in headers})

        primary_col = column_map.get("primary", "")
        address_col = column_map.get("address", "")
        deprecated_col = column_map.get("deprecated", "")

        if primary_col and primary_col not in headers:
            return {"error": f"Primary column '{primary_col}' not found in CSV"}

        tokens = [h for h in headers]

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

        return {
            "ok": True,
            "site_count": len(rows),
            "tokens": tokens,
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

    def get_token_list(self) -> dict:
        d = self.get_directory()
        return {"tokens": d.get("tokens", [])}

    def _load_sites(self) -> tuple:
        if not DIRECTORY_PATH.exists():
            return [], {}, []
        with open(DIRECTORY_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("sites", []), d.get("column_map", {}), d.get("headers", [])

    def _match_folder_to_site(self, folder_name: str, sites: list, column_map: dict) -> tuple:
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
            site, method, confidence = self._match_folder_to_site(folder, sites, column_map)
            primary_col = column_map.get("primary", "")
            site_id = (site.get(primary_col, "") if site and primary_col else None)
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

    def _apply_format(self, fmt: str, separator: str, site: dict) -> tuple:
        warnings = []
        token_re = re.compile(r"\{(\w+)\}")
        tokens_used = token_re.findall(fmt)
        result_parts = []
        for token in tokens_used:
            val = (site.get(token) or "").strip()
            if not val:
                warnings.append(f"Missing value for {{{token}}}")
                result_parts.append(f"__{token}__")
            else:
                result_parts.append(val)
        result = separator.join(result_parts)
        result = re.sub(r'[<>:"/\\|?*]', "_", result)
        return result, warnings

    def preview_folder_rename(self, root: str, format_str: str,
                              separator: str = " - ") -> dict:
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
            new_name, warnings = self._apply_format(format_str, separator, m["site"])
            if new_name == m["folder"]:
                renames.append({
                    "current": m["folder"],
                    "new_name": new_name,
                    "status": "already_correct",
                    "warnings": warnings,
                })
            else:
                renames.append({
                    "current": m["folder"],
                    "new_name": new_name,
                    "status": "rename",
                    "warnings": warnings,
                })

        return {
            "ok": True,
            "renames": renames,
            "rename_count": sum(1 for r in renames if r["status"] == "rename"),
            "correct_count": sum(1 for r in renames if r["status"] == "already_correct"),
            "unmatched_count": sum(1 for r in renames if r["status"] == "unmatched"),
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
            undo_file = _undo_path("folders")
            with open(undo_file, "w", encoding="utf-8") as f:
                json.dump(undo_data, f, indent=2)

        return {
            "ok": True,
            "renamed": renamed,
            "skipped": skipped,
            "errors": errors,
        }

    def preview_file_rename(self, root: str, format_str: str,
                            separator: str = " - ") -> dict:
        root_path = Path(root)
        if not root_path.is_dir():
            return {"error": f"Not a directory: {root}"}
        sites, column_map, headers = self._load_sites()
        if not sites:
            return {"error": "No site directory loaded"}

        renames = []
        for folder_dir in sorted(root_path.iterdir()):
            if not folder_dir.is_dir():
                continue
            site, method, confidence = self._match_folder_to_site(
                folder_dir.name, sites, column_map)
            if not site:
                continue
            for fpath in sorted(folder_dir.iterdir()):
                if fpath.is_dir():
                    continue
                stem = fpath.stem
                ext = fpath.suffix
                new_stem, warnings = self._apply_format(format_str, separator, site)
                new_name = new_stem + ext
                if fpath.name == new_name:
                    renames.append({
                        "folder": folder_dir.name,
                        "current": fpath.name,
                        "new_name": new_name,
                        "status": "already_correct",
                        "warnings": warnings,
                    })
                else:
                    renames.append({
                        "folder": folder_dir.name,
                        "current": fpath.name,
                        "new_name": new_name,
                        "status": "rename",
                        "warnings": warnings,
                    })

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
                undo_log.append({"folder": folder, "old": current, "new": new_name})
                renamed += 1
            except OSError as e:
                errors.append(f"Failed: {folder}/{current}: {e}")

        if undo_log:
            undo_data = {
                "root": root,
                "renames": undo_log,
                "timestamp": datetime.now().isoformat(),
            }
            undo_file = _undo_path("files")
            with open(undo_file, "w", encoding="utf-8") as f:
                json.dump(undo_data, f, indent=2)

        return {"ok": True, "renamed": renamed, "errors": errors}

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

    def undo_last(self, operation_type: str) -> dict:
        undo_file = _undo_path(operation_type)
        if not undo_file.exists():
            return {"error": f"No undo log for {operation_type}"}
        with open(undo_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        root_path = Path(data["root"])
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
                    errors.append(f"Failed: {entry['new']} → {entry['old']}: {e}")
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

        os.remove(str(undo_file))
        return {"ok": True, "reverted": reverted, "errors": errors}

    def save_profile(self, name: str, folder_fmt: str, file_fmt: str,
                     separator: str) -> dict:
        profiles = self._load_profiles()
        profiles[name] = {
            "folder_format": folder_fmt,
            "file_format": file_fmt,
            "separator": separator,
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

    def set_manual_match(self, folder: str, site_id: str) -> dict:
        return {"ok": True, "folder": folder, "site_id": site_id}

    def pick_folder(self) -> dict:
        import subprocess, sys
        code = (
            "import tkinter as tk\n"
            "from tkinter import filedialog\n"
            "root = tk.Tk()\n"
            "root.withdraw()\n"
            "root.wm_attributes('-topmost', True)\n"
            "p = filedialog.askdirectory(title='Select site projects root folder')\n"
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
