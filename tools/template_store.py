"""
WD Quick Walls — Template Store

Manages wall-type templates stored as JSON files on disk.
Location: {project_root}/Templates/
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent          # tools/
PROJECT_ROOT = HERE.parent                       # WD Wireless Tools/
TPL_DIR = PROJECT_ROOT / "templates"
TPL_SUFFIX = "_walltemplate.json"
DEFAULTS_FILE = TPL_DIR / "ekahau_defaults.json"


class TemplateStore:

    def get_folder(self) -> dict:
        """Return the template folder path."""
        return {"ok": True, "folder": str(TPL_DIR), "exists": TPL_DIR.is_dir()}

    def scan(self) -> dict:
        """
        Scan the Templates folder for *_walltemplate.json files.
        Returns a list of templates with their contents.
        """
        if not TPL_DIR.is_dir():
            TPL_DIR.mkdir(parents=True, exist_ok=True)
            return {"ok": True, "folder": str(TPL_DIR), "templates": []}

        templates = []
        for f in sorted(TPL_DIR.iterdir()):
            if not f.is_file():
                continue
            # Skip the bundled defaults file — it's not a user template
            if f.name == "ekahau_defaults.json":
                continue
            if not f.name.lower().endswith(TPL_SUFFIX):
                # Also accept plain .json files that look like templates
                if f.suffix.lower() != ".json":
                    continue
            try:
                with open(f) as fh:
                    data = json.load(fh)
                # Validate it looks like a wall template
                if "wallTypes" not in data and "name" not in data:
                    continue
                templates.append({
                    "name": data.get("name", f.stem),
                    "file": f.name,
                    "path": str(f),
                    "created": data.get("created", ""),
                    "wallTypes": data.get("wallTypes", []),
                })
            except Exception:
                continue

        return {"ok": True, "folder": str(TPL_DIR), "templates": templates}

    def save(self, name: str, wall_types: list) -> dict:
        """Save a template to disk."""
        TPL_DIR.mkdir(parents=True, exist_ok=True)

        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        filename = f"{safe_name}{TPL_SUFFIX}"
        filepath = TPL_DIR / filename

        tpl = {
            "name": name,
            "created": __import__("datetime").datetime.now().isoformat(),
            "wallTypes": wall_types,
        }

        with open(filepath, "w") as f:
            json.dump(tpl, f, indent=2)

        return {"ok": True, "file": filename, "path": str(filepath)}

    def get_defaults(self) -> dict:
        """Return the Ekahau factory-default wall types."""
        if not DEFAULTS_FILE.is_file():
            return {"ok": False, "error": "ekahau_defaults.json not found"}
        try:
            with open(DEFAULTS_FILE) as f:
                data = json.load(f)
            return {"ok": True, "wallTypes": data.get("wallTypes", [])}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def delete(self, filename: str) -> dict:
        """Delete a template file from disk."""
        if '..' in filename or '/' in filename or '\\' in filename:
            return {"ok": False, "error": "Invalid filename"}
        filepath = TPL_DIR / filename
        try:
            filepath.resolve().relative_to(TPL_DIR.resolve())
        except ValueError:
            return {"ok": False, "error": "Invalid filename"}
        if not filepath.is_file():
            return {"ok": False, "error": f"File not found: {filename}"}
        filepath.unlink()
        return {"ok": True, "deleted": filename}
