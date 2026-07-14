"""
WD Folder Organizer — backend logic for organizing Ekahau site folders.

Ported from Organize-EkahauFolders.ps1. For each site folder under a root,
creates images/, floorplans/, reports/ subfolders and sorts loose files by
type.  .esx project files stay in the root.

Exposes a FolderOrganizer class whose methods the Flask server turns into
JSON HTTP endpoints.
"""
import json
import shutil
from pathlib import Path

CONFIG_DIR = Path.home() / ".wd_wireless_tools"
ORGANIZER_CONFIG = CONFIG_DIR / "organizer_config.json"

# ── Default type mapping (editable via UI) ───────────────────────────

DEFAULT_CONFIG = {
    "image_ext": [
        ".png", ".jpg", ".jpeg", ".gif", ".bmp",
        ".tif", ".tiff", ".svg", ".webp", ".heic",
    ],
    "plan_ext": [".dwg", ".dxf", ".vsd", ".vsdx", ".pcp"],
    "report_ext": [
        ".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".csv",
        ".pptx", ".ppt", ".html", ".htm", ".txt", ".rtf",
    ],
    # PDFs whose name contains any of these → reports; else → floorplans
    "report_keywords": [
        "report", "audit", "coverage", "validation",
        "bom", "as-built", "asbuilt", "summary",
    ],
    # .json files matching these → reports; other .json left alone
    "json_report_keywords": [
        "waxframe", "checkpoint", "assessment", "report",
    ],
    # Folders to skip entirely (case-insensitive)
    "skip_dirs": [
        "backups", "backup", "output", "outputs",
        "archive", "archives", ".git",
        "images", "floorplans", "reports",
    ],
    # Managed subfolders created inside each site folder
    "subfolders": ["images", "floorplans", "reports"],
}


# ── Helpers ──────────────────────────────────────────────────────────

def _load_config():
    """Load saved organizer config, falling back to defaults."""
    cfg = dict(DEFAULT_CONFIG)
    if ORGANIZER_CONFIG.exists():
        try:
            with open(ORGANIZER_CONFIG) as f:
                saved = json.load(f)
            cfg.update(saved)
        except Exception:
            pass
    return cfg


def _save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(ORGANIZER_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)


def _unique_path(dest: Path) -> Path:
    """Return *dest* if it doesn't exist, else append (1), (2), … to stem."""
    if not dest.exists():
        return dest
    stem, ext = dest.stem, dest.suffix
    parent = dest.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){ext}"
        if not candidate.exists():
            return candidate
        i += 1


def _classify(file: Path, cfg: dict) -> str | None:
    """Return target subfolder name or None (= leave in place)."""
    ext = file.suffix.lower()
    name_lower = file.stem.lower()

    if ext == ".esx":
        return None  # stays in root

    if ext in cfg["image_ext"]:
        return "images"
    if ext in cfg["plan_ext"]:
        return "floorplans"
    if ext in cfg["report_ext"]:
        return "reports"

    if ext == ".pdf":
        for kw in cfg["report_keywords"]:
            if kw in name_lower:
                return "reports"
        return "floorplans"

    if ext == ".json":
        for kw in cfg["json_report_keywords"]:
            if kw in name_lower:
                return "reports"
        return None  # non-report json → leave alone

    return None  # unknown → leave alone


# ── Main class ───────────────────────────────────────────────────────

class FolderOrganizer:
    """Stateless-ish organizer.  All state lives in the config file."""

    def __init__(self):
        self._root: str | None = None

    # -- config -----------------------------------------------------------

    def get_config(self) -> dict:
        return {"ok": True, "config": _load_config()}

    def set_config(self, updates: dict) -> dict:
        cfg = _load_config()
        # Only allow updating known keys
        for key in DEFAULT_CONFIG:
            if key in updates:
                cfg[key] = updates[key]
        _save_config(cfg)
        return {"ok": True, "config": cfg}

    def reset_config(self) -> dict:
        _save_config(dict(DEFAULT_CONFIG))
        return {"ok": True, "config": dict(DEFAULT_CONFIG)}

    # -- create project folder --------------------------------------------

    def create_project_folder(self, name: str, root: str | None = None) -> dict:
        """Create a new project folder with images/, floorplans/, reports/ subfolders."""
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set — pick one first"}
        name = name.strip()
        if not name:
            return {"ok": False, "error": "Folder name cannot be empty"}
        # Sanitize: remove chars illegal on Windows/macOS
        import re
        safe_name = re.sub(r'[<>:"/\\|?*]', '-', name).rstrip('.')
        if not safe_name:
            return {"ok": False, "error": "Invalid folder name"}
        target = root_path / safe_name
        if target.exists():
            return {"ok": False, "error": f"Folder '{safe_name}' already exists"}
        cfg = _load_config()
        subfolders = cfg.get("subfolders", ["images", "floorplans", "reports"])
        try:
            target.mkdir(parents=True)
            for sf in subfolders:
                (target / sf).mkdir(exist_ok=True)
            return {"ok": True, "path": str(target), "name": safe_name,
                    "subfolders": subfolders}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # -- folder picker ----------------------------------------------------

    def pick_folder(self) -> dict:
        """Open a native folder picker (Tk) and return the chosen path."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder = filedialog.askdirectory(
                title="Select the folder containing your Ekahau site folders"
            )
            root.destroy()
            if not folder:
                return {"ok": False, "error": "No folder selected"}
            self._root = folder
            return {"ok": True, "path": folder}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_folder(self, path: str) -> dict:
        """Set root folder without opening a picker."""
        p = Path(path)
        if not p.is_dir():
            return {"ok": False, "error": f"Not a directory: {path}"}
        self._root = path
        return {"ok": True, "path": path}

    # -- scan (dry run) ---------------------------------------------------

    def _scan_dir(self, site_dir: Path, cfg: dict, totals: dict) -> dict | None:
        """Scan a single directory for loose files, return a site entry or None."""
        subfolders = cfg["subfolders"]
        existing_subs = [sf for sf in subfolders if (site_dir / sf).is_dir()]
        missing_subs = [sf for sf in subfolders if sf not in existing_subs]

        moves = []
        staying = []
        for f in sorted(site_dir.iterdir()):
            if not f.is_file():
                continue
            target = _classify(f, cfg)
            if target is None:
                staying.append({
                    "name": f.name,
                    "ext": f.suffix.lower(),
                    "size": f.stat().st_size,
                    "reason": "esx" if f.suffix.lower() == ".esx" else "unknown",
                })
                totals["skipped"] += 1
            else:
                dest = site_dir / target / f.name
                final = _unique_path(dest)
                renamed = (final.name != f.name)
                moves.append({
                    "name": f.name,
                    "ext": f.suffix.lower(),
                    "size": f.stat().st_size,
                    "target": target,
                    "renamed_to": final.name if renamed else None,
                })
                totals[target] += 1

        if moves or staying:
            return {
                "folder": site_dir.name,
                "path": str(site_dir),
                "existing_subs": existing_subs,
                "missing_subs": missing_subs,
                "moves": moves,
                "staying": staying,
            }
        return None

    def scan(self, root: str | None = None) -> dict:
        """
        Scan the root folder and return a dry-run preview.
        Returns a list of site folders, each with their proposed moves.
        If the root folder itself has loose organizable files (no site
        subfolders), it is treated as a single site.
        """
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set"}

        cfg = _load_config()
        skip = {s.lower() for s in cfg["skip_dirs"]}

        sites = []
        totals = {"images": 0, "floorplans": 0, "reports": 0, "skipped": 0}

        # Scan subdirectories as site folders
        for site_dir in sorted(root_path.iterdir()):
            if not site_dir.is_dir():
                continue
            if site_dir.name.lower() in skip or site_dir.name.startswith("."):
                continue
            entry = self._scan_dir(site_dir, cfg, totals)
            if entry:
                sites.append(entry)

        # If no site subfolders found, check the root itself for loose files
        if not sites:
            entry = self._scan_dir(root_path, cfg, totals)
            if entry:
                entry["folder"] = root_path.name + "  (root folder)"
                entry["is_root"] = True
                sites.append(entry)

        return {
            "ok": True,
            "root": str(root_path),
            "site_count": len(sites),
            "totals": totals,
            "sites": sites,
        }

    # -- execute (apply moves) --------------------------------------------

    def _execute_dir(self, site_dir: Path, cfg: dict, excl: set,
                     overrides: dict, totals: dict,
                     folder_label: str) -> dict | None:
        """Move loose files in a single directory. Returns a result entry or None."""
        subfolders = cfg["subfolders"]
        for sf in subfolders:
            (site_dir / sf).mkdir(exist_ok=True)

        site_moves = []
        for f in sorted(site_dir.iterdir()):
            if not f.is_file():
                continue
            target = _classify(f, cfg)
            if target is None:
                continue

            if (folder_label, f.name) in excl:
                totals["skipped"] += 1
                site_moves.append({
                    "name": f.name,
                    "target": target,
                    "status": "skipped",
                })
                continue

            # Apply user override if present
            override_key = (folder_label, f.name)
            if override_key in overrides:
                target = overrides[override_key]

            dest = site_dir / target / f.name
            final = _unique_path(dest)
            try:
                shutil.move(str(f), str(final))
                site_moves.append({
                    "name": f.name,
                    "target": target,
                    "renamed_to": final.name if final.name != f.name else None,
                    "status": "moved",
                })
                totals[target] += 1
            except Exception as e:
                site_moves.append({
                    "name": f.name,
                    "target": target,
                    "status": "error",
                    "error": str(e),
                })
                totals["errors"] += 1

        if site_moves:
            return {"folder": folder_label, "moves": site_moves}
        return None

    def execute(self, root: str | None = None, excluded: list | None = None,
                overrides: list | None = None) -> dict:
        """
        Actually move the files.  *excluded* is a list of
        {"folder": "SiteName", "name": "file.png"} dicts for files the user
        unchecked in the review UI — those are skipped.
        *overrides* is a list of {"folder": "...", "name": "...", "target": "reports"}
        dicts for files the user reassigned to a different destination.
        """
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set"}

        cfg = _load_config()
        skip = {s.lower() for s in cfg["skip_dirs"]}

        excl = set()
        for item in (excluded or []):
            excl.add((item["folder"], item["name"]))

        # Build overrides lookup: (folder, filename) -> new target
        ovr = {}
        for item in (overrides or []):
            ovr[(item["folder"], item["name"])] = item["target"]

        results = []
        totals = {"images": 0, "floorplans": 0, "reports": 0, "errors": 0, "skipped": 0}

        # Process site subdirectories
        found_sites = False
        for site_dir in sorted(root_path.iterdir()):
            if not site_dir.is_dir():
                continue
            if site_dir.name.lower() in skip or site_dir.name.startswith("."):
                continue
            found_sites = True
            entry = self._execute_dir(site_dir, cfg, excl, ovr, totals, site_dir.name)
            if entry:
                results.append(entry)

        # If no site subfolders, process the root folder itself
        if not found_sites:
            label = root_path.name + "  (root folder)"
            entry = self._execute_dir(root_path, cfg, excl, ovr, totals, label)
            if entry:
                results.append(entry)

        return {
            "ok": True,
            "root": str(root_path),
            "totals": totals,
            "sites": results,
        }
