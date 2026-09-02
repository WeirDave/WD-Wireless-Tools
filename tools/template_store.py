"""
WD Quick Walls — Template Store

Manages wall-type templates stored as JSON files on disk.

Two locations, deliberately:

  Built-in   {project_root}/templates/       — shipped with the app, read-only.
  User       ~/.wd_wireless_tools/templates/ — everything you create or edit.

User templates used to live in the install folder alongside the built-ins.
That made the install tree un-updatable: `git pull` refuses to overwrite a
locally-edited tracked file, so a user who had customized "WD Template" could
never update.  Keeping writes out of the install tree is what lets the in-app
updater replace the whole folder without touching your work.

A user file shadows a built-in of the same filename (edit a built-in and your
copy wins, the shipped one stays underneath).  Deleting a built-in records a
tombstone rather than removing a shipped file.
"""
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

BUILTIN_DIR = PROJECT_ROOT / "templates"
USER_DIR = Path.home() / ".wd_wireless_tools" / "templates"

TPL_SUFFIX = "_walltemplate.json"
DEFAULTS_FILE = BUILTIN_DIR / "ekahau_defaults.json"
HIDDEN_NAME = "hidden.json"
MIGRATED_NAME = ".migrated"

# Back-compat alias — older code referenced the single combined directory.
TPL_DIR = USER_DIR


# Derived paths are computed per call, not frozen at import, so patching
# USER_DIR (tests, or a relocated home) redirects everything with it.
def _hidden_file() -> Path:
    return USER_DIR / HIDDEN_NAME


def _migrated_marker() -> Path:
    return USER_DIR / MIGRATED_NAME


def _load_hidden() -> set:
    """Filenames of built-in templates the user has deleted."""
    try:
        with open(_hidden_file()) as f:
            return set(json.load(f).get("hidden", []))
    except Exception:
        return set()


def _save_hidden(hidden: set) -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    with open(_hidden_file(), "w") as f:
        json.dump({"hidden": sorted(hidden)}, f, indent=2)


def builtin_names() -> set:
    """Filenames the app ships.  In a clean checkout these are exactly the
    tracked files in templates/, so anything else found there is user work."""
    if not BUILTIN_DIR.is_dir():
        return set()
    return {p.name for p in BUILTIN_DIR.iterdir()
            if p.is_file() and p.name.lower().endswith(TPL_SUFFIX)}


def migrate_legacy_templates() -> dict:
    """Move user-created templates out of the install folder, once.

    Only files that are NOT shipped names get copied.  Those are untracked, so
    they were never at risk from a pull — this just relocates them so the whole
    install tree becomes disposable.

    Shipped names are deliberately left alone.  Copying them would freeze a
    private duplicate of every built-in and cut users off from upstream
    template improvements.  The one case that genuinely needs rescuing — a
    user who edited a *shipped* template in place, making a tracked file dirty
    — is handled by the updater instead (see rescue_dirty_builtin), which runs
    at the only moment the pristine version is still available to compare
    against.
    """
    if _migrated_marker().exists():
        return {"migrated": [], "already": True}

    USER_DIR.mkdir(parents=True, exist_ok=True)
    shipped = builtin_names()
    copied = []
    if BUILTIN_DIR.is_dir():
        for src in sorted(BUILTIN_DIR.iterdir()):
            if not src.is_file() or not src.name.lower().endswith(TPL_SUFFIX):
                continue
            if src.name in shipped:
                continue
            dest = USER_DIR / src.name
            if dest.exists():
                continue
            try:
                shutil.copy2(src, dest)
                copied.append(src.name)
            except OSError:
                continue

    _migrated_marker().write_text("", encoding="utf-8")
    return {"migrated": copied, "already": False}


def rescue_dirty_builtin(filename: str) -> dict:
    """Preserve a locally-edited shipped template as a user copy.

    Called by the updater when `git status` reports a tracked template as
    modified.  The edit becomes a user-level shadow, which lets the updater
    then discard the tree change and pull cleanly.  Without this, the pull
    aborts and the user can never update.
    """
    src = BUILTIN_DIR / filename
    if not src.is_file():
        return {"ok": False, "error": f"No such template: {filename}"}
    USER_DIR.mkdir(parents=True, exist_ok=True)
    dest = USER_DIR / filename
    if dest.exists():
        return {"ok": True, "rescued": False, "reason": "user copy already exists"}
    try:
        shutil.copy2(src, dest)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "rescued": True, "file": filename}


def _read_template(path: Path, builtin: bool):
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception:
        return None
    if "wallTypes" not in data and "name" not in data:
        return None
    return {
        "name": data.get("name", path.stem),
        "file": path.name,
        "path": str(path),
        "created": data.get("created", ""),
        "builtin": builtin,
        "wallTypes": data.get("wallTypes", []),
    }


class TemplateStore:

    def get_folder(self) -> dict:
        """Return the folder templates are saved to."""
        return {"ok": True, "folder": str(USER_DIR), "exists": USER_DIR.is_dir(),
                "builtinFolder": str(BUILTIN_DIR)}

    def scan(self) -> dict:
        """Built-in templates overlaid by user templates of the same filename."""
        migrate_legacy_templates()
        USER_DIR.mkdir(parents=True, exist_ok=True)
        hidden = _load_hidden()

        found = {}
        if BUILTIN_DIR.is_dir():
            for f in sorted(BUILTIN_DIR.iterdir()):
                if not f.is_file() or f.name == "ekahau_defaults.json":
                    continue
                if not f.name.lower().endswith(TPL_SUFFIX):
                    continue
                if f.name in hidden:
                    continue
                tpl = _read_template(f, builtin=True)
                if tpl:
                    found[f.name] = tpl

        for f in sorted(USER_DIR.iterdir()):
            if not f.is_file() or f.name in (HIDDEN_NAME, MIGRATED_NAME):
                continue
            if not f.name.lower().endswith(TPL_SUFFIX):
                if f.suffix.lower() != ".json":
                    continue
            tpl = _read_template(f, builtin=False)
            if tpl:
                found[f.name] = tpl

        return {"ok": True, "folder": str(USER_DIR),
                "templates": [found[k] for k in sorted(found)]}

    def save(self, name: str, wall_types: list) -> dict:
        """Save a template to the user folder."""
        USER_DIR.mkdir(parents=True, exist_ok=True)

        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        filename = f"{safe_name}{TPL_SUFFIX}"
        filepath = USER_DIR / filename

        tpl = {
            "name": name,
            "created": __import__("datetime").datetime.now().isoformat(),
            "wallTypes": wall_types,
        }

        with open(filepath, "w") as f:
            json.dump(tpl, f, indent=2)

        hidden = _load_hidden()
        if filename in hidden:
            hidden.discard(filename)
            _save_hidden(hidden)

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

    def reset(self, filename: str) -> dict:
        """Drop the user's copy so the shipped built-in shows through again."""
        if '..' in filename or '/' in filename or '\\' in filename:
            return {"ok": False, "error": "Invalid filename"}
        if not (BUILTIN_DIR / filename).is_file():
            return {"ok": False, "error": f"No built-in template named {filename}"}
        user_copy = USER_DIR / filename
        if user_copy.is_file():
            user_copy.unlink()
        hidden = _load_hidden()
        if filename in hidden:
            hidden.discard(filename)
            _save_hidden(hidden)
        return {"ok": True, "reset": filename}

    def delete(self, filename: str) -> dict:
        """Delete a user template.  Built-ins are tombstoned, not removed."""
        if '..' in filename or '/' in filename or '\\' in filename:
            return {"ok": False, "error": "Invalid filename"}

        filepath = USER_DIR / filename
        try:
            filepath.resolve().relative_to(USER_DIR.resolve())
        except ValueError:
            return {"ok": False, "error": "Invalid filename"}

        had_user_copy = filepath.is_file()
        if had_user_copy:
            filepath.unlink()

        if (BUILTIN_DIR / filename).is_file():
            hidden = _load_hidden()
            hidden.add(filename)
            _save_hidden(hidden)
        elif not had_user_copy:
            return {"ok": False, "error": f"File not found: {filename}"}

        return {"ok": True, "deleted": filename}
