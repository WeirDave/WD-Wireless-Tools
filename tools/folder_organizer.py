"""
WD Folder Organizer — backend logic for organizing Ekahau site folders.

Ported from Organize-EkahauFolders.ps1. For each site folder under a root,
creates images/, floorplans/, reports/ subfolders and sorts loose files by
type.  .esx project files stay in the root.

Exposes a FolderOrganizer class whose methods the Flask server turns into
JSON HTTP endpoints.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".wd_wireless_tools"
ORGANIZER_CONFIG = CONFIG_DIR / "organizer_config.json"
UNDO_DIR = CONFIG_DIR / "organizer_undo"
ACORN_STATE_DIR = CONFIG_DIR / "acorn_state"


def _tk_dialog(code: str, timeout: int = 180) -> str:
    """Run a Tk file/folder dialog in its own subprocess and return stdout.

    The server (waitress) handles requests on a pool of worker threads, but
    Tkinter's Tcl interpreter is not thread-safe — creating a Tk() root
    in-process here can crash with a "main thread is not in main loop"
    error if a second dialog request lands on a different worker thread
    while the first is still open. Running each dialog in its own process
    sidesteps that entirely, matching the pattern cloud_manager.py already
    uses for its folder picker.
    """
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, timeout=timeout, **kwargs)
        return out.stdout.strip()
    except Exception:
        return ""


def _undo_path(root: Path) -> Path:
    """One rollback log per organize root (path hash keeps filenames sane)."""
    key = hashlib.sha1(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    return UNDO_DIR / f"{key}.json"


def _acorn_state_path(esx_path: Path) -> Path:
    """Where the last-known floor/summary snapshot for a given .esx is kept,
    separate from the human-readable Acorn.txt, so re-saving the note never
    depends on parsing our own pretty-printed report back out."""
    key = hashlib.sha1(str(esx_path.resolve()).encode("utf-8")).hexdigest()[:16]
    return ACORN_STATE_DIR / f"{key}.json"


def _read_acorn_state(esx_path: Path) -> dict | None:
    try:
        with open(_acorn_state_path(esx_path)) as f:
            return json.load(f)
    except Exception:
        return None


def _write_acorn_state(esx_path: Path, state: dict) -> None:
    try:
        ACORN_STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_acorn_state_path(esx_path), "w") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass


def _acorn_diff(prev: dict | None, floors: list[str], summary: dict | None) -> tuple[str, list[str]]:
    """Compare the current .esx state against the last time Acorn Notes ran
    for this file. Returns (status, detail_lines) where status is
    'first' (no prior note to compare against), 'unchanged', or 'changed'."""
    if not prev:
        return "first", []

    prev_floors = prev.get("floors") or []
    added = [n for n in floors if n not in prev_floors]
    removed = [n for n in prev_floors if n not in floors]

    prev_summary = prev.get("summary") or {}
    deltas = []
    if summary:
        for key, label in (("floors", "Floor plans"), ("aps", "Access points"),
                            ("measurements", "Measurements"), ("surveys", "Surveys")):
            old_v, new_v = prev_summary.get(key), summary.get(key)
            if old_v is not None and new_v is not None and old_v != new_v:
                sign = "+" if new_v > old_v else ""
                deltas.append(f"  {label}: {old_v} -> {new_v} ({sign}{new_v - old_v})")

    detail = ([f"  + Added floor plan: {n}" for n in added]
              + [f"  - Removed floor plan: {n}" for n in removed]
              + deltas)
    return ("changed" if detail else "unchanged"), detail


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


    "subfolders": ["images", "floorplans", "reports"],


    "subfolder_names": {
        "images": "images",
        "floorplans": "floorplans",
        "reports": "reports",
    },


    "custom_destinations": [],


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
}


_SEPARATOR_CHARS = {"underscore": "_", "hyphen": "-", "space": " ", "spaced_hyphen": " - "}


def _migrate_rename_cfg(rn: dict) -> dict:
    """Translate rename keys from older releases to their current equivalents
    so configs saved by earlier versions still work:
      pre-v1.34: lowercase / add_site_code / collapse_spaces
      v1.34:     prepend_parent (bool prefix of the parent folder's name)
    """
    if not isinstance(rn, dict):
        return dict(DEFAULT_CONFIG["rename"])
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

    return {**DEFAULT_CONFIG["rename"], **rn}


def _title_case(stem: str) -> str:
    """Capitalize the first letter of each word, leaving the rest of each
    word's casing untouched (so acronyms like 'SITE1' aren't mangled)."""
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0)[0].upper() + m.group(0)[1:], stem)


def _sentence_case(stem: str) -> str:
    """Lowercase the whole stem, then capitalize its first letter."""
    lowered = stem.lower()
    m = re.search(r"[a-z]", lowered)
    if not m:
        return lowered
    i = m.start()
    return lowered[:i] + lowered[i].upper() + lowered[i + 1:]


def _expand_folder_token(text: str, folder_label: str) -> str:
    """Replace the {folder} placeholder in a prefix/suffix field with the
    file's containing folder name."""
    return (text or "").replace("{folder}", folder_label.strip())


def _apply_rename(original_name: str, folder_label: str, cfg: dict) -> str:
    """Compute the target filename after applying the configured rename rules.

    Order: strip_prefix -> strip_suffix -> regex -> separator -> case -> prefix/suffix.
    Prefix/suffix are literal text (with an optional {folder} token) wrapped
    around the transformed stem last, so free-typed text like "PD v1.0" is
    never mangled by the case/separator rules meant for the original name.
    Extension is preserved untouched (only the stem is transformed).
    """
    r = (cfg.get("rename") or {})
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


def _split_ext(name: str) -> tuple[str, str]:
    """Split a filename into (stem, ext). Handles hidden files ('.esx' → ('.esx', ''))."""
    p = Path(name)
    return p.stem, p.suffix


_ESX_SUMMARY_CACHE: dict[tuple[str, int, float], dict] = {}
_ESX_IMAGE_NAMES_CACHE: dict[tuple[str, int, float], set[str]] = {}


def _esx_image_names(path: Path) -> set[str]:
    """Return the set of `imageName` values from an .esx's images.json,
    lowercased with extensions stripped. Empty set on any failure.
    Cached identically to _esx_summary."""
    try:
        st = path.stat()
    except OSError:
        return set()
    key = (str(path), st.st_size, st.st_mtime)
    cached = _ESX_IMAGE_NAMES_CACHE.get(key)
    if cached is not None:
        return cached
    names: set[str] = set()
    try:
        with zipfile.ZipFile(path, "r") as z:
            if "images.json" in z.namelist():
                try:
                    body = json.loads(z.read("images.json"))
                    for img in (body.get("images") or []):
                        n = img.get("imageName") or ""
                        if n:
                            names.add(_stem_lower(n))
                except Exception:
                    pass
    except (zipfile.BadZipFile, OSError):
        pass
    _ESX_IMAGE_NAMES_CACHE[key] = names
    return names


def _stem_lower(name: str) -> str:
    """Filename → lowercase stem, no extension. Ekahau imageName often includes
    the original extension so we normalize before comparing."""
    return Path(name).stem.lower()


def _esx_floor_plan_names(path: Path) -> list[str] | None:
    """Return the ordered list of floor-plan names stored in an .esx's
    floorPlans.json, or None if the file can't be read as a valid .esx."""
    try:
        with zipfile.ZipFile(path, "r") as z:
            if "floorPlans.json" not in z.namelist():
                return None
            body = json.loads(z.read("floorPlans.json"))
    except (zipfile.BadZipFile, OSError, json.JSONDecodeError):
        return None
    return [fp.get("name") or "Unnamed" for fp in (body.get("floorPlans") or [])]


def _acorn_path(esx_path: Path) -> Path:
    """Where Squirrel stashes its info note for a given .esx — same folder,
    named after the project so multiple .esx files in one site don't collide."""
    return esx_path.parent / f"{esx_path.stem} - Acorn.txt"


_ACORN_WIDTH = 64


def _acorn_rule(char: str = "=") -> str:
    return char * _ACORN_WIDTH


def _acorn_section(title: str, body_lines: list[str]) -> list[str]:
    """A titled block: UPPERCASE heading, a rule underneath, then its lines."""
    return [title.upper(), _acorn_rule("-"), *body_lines, ""]


def _dest_name(cfg: dict, key: str) -> str:
    """Canonical destination key → on-disk folder name, honoring both
    builtin subfolder_names overrides and custom destinations' own name."""
    for d in _get_destinations(cfg):
        if d["key"] == key:
            return d["name"]
    return key


_INVALID_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_folder_name(name: str) -> str:
    """Strip characters that Windows/POSIX filesystems reject.
    Returns '' if the result is empty or all-dots."""
    if not name:
        return ""
    cleaned = _INVALID_NAME_RE.sub("-", name).strip().rstrip(".")
    return "" if cleaned in ("", ".", "..") else cleaned


def _is_inside(path: Path, root: Path) -> bool:
    """True if *path* resolves to somewhere inside *root* — guards against a
    '..' segment or (on Windows) an absolute-path override in a name/target
    field escaping the intended site/root directory."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _esx_summary(path: Path) -> dict | None:
    """Open an .esx as a ZIP and count floors/APs/measurements/surveys.

    Returns None on any error (unreadable, not a valid zip, missing JSON).
    Results are cached in-process by (path, size, mtime) so re-scans are fast.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    cache_key = (str(path), st.st_size, st.st_mtime)
    cached = _ESX_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        with zipfile.ZipFile(path, "r") as z:
            names = set(z.namelist())

            def _list_len(fname: str, key: str) -> int:
                if fname not in names:
                    return 0
                try:
                    body = json.loads(z.read(fname))
                except Exception:
                    return 0
                lst = body.get(key)
                return len(lst) if isinstance(lst, list) else 0

            floors = _list_len("floorPlans.json", "floorPlans")
            aps = _list_len("accessPoints.json", "accessPoints")
            apms = _list_len("accessPointMeasurements.json",
                             "accessPointMeasurements")


            surveys = _list_len("surveys.json", "surveys")
            survey_re = re.compile(r"^survey-[a-f0-9\-]+\.json$")
            for n in names:
                if survey_re.match(n):
                    try:
                        body = json.loads(z.read(n))
                        lst = body.get("surveys")
                        if isinstance(lst, list):
                            surveys += len(lst)
                    except Exception:
                        pass

            summary = {
                "floors": floors,
                "aps": aps,
                "measurements": apms,
                "surveys": surveys,
            }
    except (zipfile.BadZipFile, OSError, KeyError):
        summary = None

    _ESX_SUMMARY_CACHE[cache_key] = summary
    return summary


_IMAGE_EXTS = {
    "png": ".png", "jpeg": ".jpg", "gif": ".gif",
    "webp": ".webp", "bmp": ".bmp", "tiff": ".tif",
}


def _sniff_image_format(head: bytes) -> str:
    """Best-effort format sniff from a file's first bytes. Ekahau stores
    floorplan images as `image-<uuid>` with no extension, so we detect the
    real format to name extracts correctly."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return ""


def _image_ext_from_bytes(data: bytes) -> str:
    """Return a filename extension (with dot) for an image blob, or .png
    as a safe fallback — Ekahau raster imports are overwhelmingly PNG."""
    return _IMAGE_EXTS.get(_sniff_image_format(data[:16]), ".png")


def _human_size(n: int) -> str:
    """Human-readable bytes: 512 B, 1.4 KB, 12.6 MB."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


_GLOBAL_KEYS = {"subfolders", "subfolder_names", "custom_destinations"}


def _load_config():
    """Load saved organizer config, falling back to defaults.

    Prefers the unified settings.json when it exists, assembling the
    same flat dict shape callers have always expected.  Uses CONFIG_DIR
    (not an imported constant) so test patches are honored.
    """
    unified = CONFIG_DIR / "settings.json"
    if unified.exists():
        from tools.settings import load_settings
        s = load_settings(_path=unified)
        cfg = dict(DEFAULT_CONFIG)
        g = s.get("global", {})
        o = s.get("organizer", {})
        cfg.update(o)
        for key in _GLOBAL_KEYS:
            if key in g:
                cfg[key] = g[key]
        cfg["rename"] = _migrate_rename_cfg(cfg.get("rename"))
        return cfg

    cfg = dict(DEFAULT_CONFIG)
    if ORGANIZER_CONFIG.exists():
        try:
            with open(ORGANIZER_CONFIG) as f:
                saved = json.load(f)
            cfg.update(saved)
        except Exception:
            pass
    cfg["rename"] = _migrate_rename_cfg(cfg.get("rename"))
    return cfg


def _save_config(cfg):
    """Save organizer config.

    Routes through unified settings.json when it exists, splitting keys
    into global vs organizer sections.  Falls back to the legacy file.
    """
    unified = CONFIG_DIR / "settings.json"
    if unified.exists():
        from tools.settings import update_settings
        global_patch = {}
        org_patch = {}
        for key, val in cfg.items():
            if key in _GLOBAL_KEYS:
                global_patch[key] = val
            elif key in DEFAULT_CONFIG:
                org_patch[key] = val
        update_settings({"global": global_patch, "organizer": org_patch},
                        _path=unified)
        return

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


_BUILTIN_KEYS = ("images", "floorplans", "reports")


def _sanitize_custom_key(key: str) -> str:
    """Custom-destination keys must be safe filesystem tokens and must not
    collide with builtin keys."""
    if not isinstance(key, str):
        return ""
    k = re.sub(r"[^A-Za-z0-9_\-]", "", key).strip("-_").lower()
    if not k or k in _BUILTIN_KEYS:
        return ""
    return k


def _normalize_exts(exts) -> list:
    """Accept a list of strings, return lowercase dotted extensions.
    Strips whitespace, prepends a dot if missing, drops empty entries."""
    out = []
    if not isinstance(exts, list):
        return out
    for e in exts:
        if not isinstance(e, str):
            continue
        s = e.strip().lower()
        if not s:
            continue
        if not s.startswith("."):
            s = "." + s
        out.append(s)
    return out


def _get_destinations(cfg: dict) -> list:
    """Return the effective destination list: three builtins (derived from
    legacy config fields) followed by any user-added custom destinations.

    Each entry: {key, name, exts, pdf_keywords, json_keywords, builtin}.
    """
    names = cfg.get("subfolder_names") or {}
    builtins = [
        {
            "key": "images",
            "name": names.get("images", "images") or "images",
            "exts": [e.lower() for e in (cfg.get("image_ext") or [])],
            "pdf_keywords": [],
            "json_keywords": [],
            "builtin": True,
        },
        {
            "key": "floorplans",
            "name": names.get("floorplans", "floorplans") or "floorplans",
            "exts": [e.lower() for e in (cfg.get("plan_ext") or [])],
            "pdf_keywords": [],
            "json_keywords": [],
            "builtin": True,
        },
        {
            "key": "reports",
            "name": names.get("reports", "reports") or "reports",
            "exts": [e.lower() for e in (cfg.get("report_ext") or [])],
            "pdf_keywords": [k.lower() for k in (cfg.get("report_keywords") or [])],
            "json_keywords": [k.lower() for k in (cfg.get("json_report_keywords") or [])],
            "builtin": True,
        },
    ]

    seen_keys = set(_BUILTIN_KEYS)
    seen_names = {d["name"].lower() for d in builtins}
    for c in (cfg.get("custom_destinations") or []):
        if not isinstance(c, dict):
            continue
        key = _sanitize_custom_key(c.get("key") or c.get("name") or "")
        if not key or key in seen_keys:
            continue
        raw_name = (c.get("name") or key).strip()
        name = _sanitize_folder_name(raw_name) or key
        if name.lower() in seen_names:
            continue
        seen_keys.add(key)
        seen_names.add(name.lower())
        builtins.append({
            "key": key,
            "name": name,
            "exts": _normalize_exts(c.get("exts")),
            "pdf_keywords": [str(k).strip().lower() for k in (c.get("pdf_keywords") or []) if str(k).strip()],
            "json_keywords": [str(k).strip().lower() for k in (c.get("json_keywords") or []) if str(k).strip()],
            "builtin": False,
        })
    return builtins


def _effective_skip(cfg: dict) -> set:
    """Directory names to skip during scan/execute. Always includes every
    destination's on-disk name so we never recurse into a managed subfolder."""
    skip = {str(s).lower() for s in (cfg.get("skip_dirs") or [])}
    for d in _get_destinations(cfg):
        if d.get("name"):
            skip.add(d["name"].lower())
        if d.get("key"):
            skip.add(d["key"].lower())
    return skip


def _classify(file: Path, cfg: dict) -> str | None:
    """Return canonical destination key or None (= leave in place).

    Ordering: (1) exact extension match walks destinations in list order —
    custom destinations come after builtins, so a custom destination only
    wins for extensions the builtins don't already claim. (2) PDFs use
    pdf_keywords across all destinations, falling back to 'floorplans'.
    (3) JSONs use json_keywords, falling back to None.
    """
    ext = file.suffix.lower()
    if ext == ".esx":
        return None
    name_lower = file.stem.lower()
    dests = _get_destinations(cfg)


    ordered = [d for d in dests if not d["builtin"]] + [d for d in dests if d["builtin"]]
    for d in ordered:
        if ext in d["exts"]:
            return d["key"]

    if ext == ".pdf":
        for d in dests:
            for kw in d["pdf_keywords"]:
                if kw in name_lower:
                    return d["key"]
        return "floorplans"

    if ext == ".json":
        for d in dests:
            for kw in d["json_keywords"]:
                if kw in name_lower:
                    return d["key"]
        return None

    return None


class FolderOrganizer:
    """Stateless-ish organizer.  All state lives in the config file."""

    def __init__(self):
        self._root: str | None = None


        self.app_version: str = ""


    def get_config(self) -> dict:
        return {"ok": True, "config": _load_config()}

    def set_config(self, updates: dict) -> dict:
        cfg = _load_config()

        for key in DEFAULT_CONFIG:
            if key in updates:
                cfg[key] = updates[key]
        _save_config(cfg)
        return {"ok": True, "config": cfg}

    def reset_config(self) -> dict:
        _save_config(dict(DEFAULT_CONFIG))
        return {"ok": True, "config": dict(DEFAULT_CONFIG)}


    def create_project_folder(self, name: str, root: str | None = None,
                              subfolders: list | None = None) -> dict:
        """Create a new project folder and pre-build the given subfolders.

        `subfolders` is the literal, ordered list of subfolder names to
        create, as chosen in the Create Folder modal — this already reflects
        any inline renames plus ad-hoc "+ Add subfolder" entries the user
        typed for this one project, without touching the saved config.
        None means "every configured destination, unedited" — the historical
        behavior — so callers that don't pass it keep working.
        """
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set — pick one first"}
        name = name.strip()
        if not name:
            return {"ok": False, "error": "Folder name cannot be empty"}
        import re
        safe_name = re.sub(r'[<>:"/\\|?*]', '-', name).rstrip('.')
        if '..' in safe_name or '/' in safe_name or '\\' in safe_name:
            return {"ok": False, "error": "Invalid folder name"}
        if not safe_name:
            return {"ok": False, "error": "Invalid folder name"}
        target = root_path / safe_name
        existed = target.exists()
        if existed and not target.is_dir():
            return {"ok": False, "error": f"'{safe_name}' exists but isn't a folder"}
        if subfolders is None:
            cfg = _load_config()
            picked_names = [d["name"] for d in _get_destinations(cfg)]
        else:
            picked_names = []
            seen = set()
            for raw in subfolders:
                nm = re.sub(r'[<>:"/\\|?*]', '-', str(raw)).strip().rstrip('.')
                if not nm or '..' in nm or '/' in nm or '\\' in nm or nm in seen:
                    continue
                seen.add(nm)
                picked_names.append(nm)
        try:
            target.mkdir(parents=True, exist_ok=True)
            added = []
            for sf in picked_names:
                sub = target / sf
                if not sub.exists():
                    added.append(sf)
                sub.mkdir(exist_ok=True)
            return {"ok": True, "path": str(target), "name": safe_name,
                    "subfolders": picked_names, "existed": existed,
                    "added": added}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def list_root_folders(self, root: str | None = None) -> dict:
        """List the direct site-folder names in a root, for autocompleting
        the Create Folder dialog when a user wants to top up subfolders on
        an existing folder they moved in from elsewhere.

        Same skip rules as scan() — hides backup/output/subfolder-name
        directories and dotfiles, so the dropdown shows only real sites."""
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set"}
        cfg = _load_config()
        skip = _effective_skip(cfg)
        names = []
        try:
            for child in sorted(root_path.iterdir(), key=lambda p: p.name.lower()):
                if not child.is_dir():
                    continue
                if child.name.lower() in skip or child.name.startswith("."):
                    continue
                names.append(child.name)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "folders": names}


    def pick_folder(self) -> dict:
        """Open a native folder picker (Tk, isolated subprocess) and return the chosen path."""
        code = (
            "import tkinter as tk\n"
            "from tkinter import filedialog\n"
            "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
            "p = filedialog.askdirectory(title='Select the folder containing your Ekahau site folders')\n"
            "print(p or '')\n"
        )
        folder = _tk_dialog(code)
        if not folder:
            return {"ok": False, "error": "No folder selected"}
        self._root = folder
        return {"ok": True, "path": folder}


    def pick_esx_file(self) -> dict:
        """Native file picker limited to .esx (Tk, isolated subprocess)."""
        code = (
            "import tkinter as tk\n"
            "from tkinter import filedialog\n"
            "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
            "p = filedialog.askopenfilename(title='Select an Ekahau project (.esx)', "
            "filetypes=[('Ekahau project', '*.esx'), ('All files', '*.*')])\n"
            "print(p or '')\n"
        )
        path = _tk_dialog(code)
        if not path:
            return {"ok": False, "error": "No file selected"}
        return {"ok": True, "path": path}

    def pick_output_folder(self, default: str | None = None) -> dict:
        """Folder picker seeded with `default` when it exists (Tk, isolated subprocess)."""
        initialdir_src = ""
        if default:
            p = Path(default)
            seed = p if p.is_dir() else p.parent if p.parent.is_dir() else None
            if seed:
                initialdir_src = f", initialdir={str(seed)!r}"
        code = (
            "import tkinter as tk\n"
            "from tkinter import filedialog\n"
            "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
            f"p = filedialog.askdirectory(title='Select the folder to save floorplans into'{initialdir_src})\n"
            "print(p or '')\n"
        )
        folder = _tk_dialog(code)
        if not folder:
            return {"ok": False, "error": "No folder selected"}
        return {"ok": True, "path": folder}

    def list_floorplans(self, path: str) -> dict:
        """Read floorPlans.json from an .esx and return a floor list plus
        the default output directory (`<esx-parent>/<floorplans-name>/`)."""
        p = Path(path)
        if not p.is_file():
            return {"ok": False, "error": "File not found"}
        cfg = _load_config()
        try:
            with zipfile.ZipFile(p, "r") as z:
                names = set(z.namelist())
                if "floorPlans.json" not in names:
                    return {"ok": False, "error": "No floorPlans.json inside — not a valid .esx?"}
                body = json.loads(z.read("floorPlans.json"))
                floors = []
                for fp in (body.get("floorPlans") or []):
                    image_id = fp.get("imageId")
                    entry = f"image-{image_id}" if image_id else None
                    size = 0
                    fmt = ""
                    available = bool(entry and entry in names)
                    if available:
                        try:
                            size = z.getinfo(entry).file_size
                            with z.open(entry) as fh:
                                fmt = _sniff_image_format(fh.read(12))
                        except (KeyError, OSError):
                            available = False
                    floors.append({
                        "id": fp.get("id"),
                        "name": fp.get("name") or "Unnamed",
                        "imageId": image_id,
                        "width": fp.get("width"),
                        "height": fp.get("height"),
                        "format": fmt,
                        "size": size,
                        "size_h": _human_size(size) if size else "",
                        "available": available,
                    })
        except (zipfile.BadZipFile, OSError, json.JSONDecodeError) as e:
            return {"ok": False, "error": f"Could not read .esx: {e}"}
        default_out = str(p.parent / _dest_name(cfg, "floorplans"))
        return {"ok": True, "path": str(p), "floors": floors,
                "default_output": default_out}

    def extract_floorplans(self, path: str, selections: list | None = None,
                           out_dir: str | None = None,
                           floor_ids: list | None = None) -> dict:
        """Write selected floorplan images out as standalone image files.

        `selections` is a list of {"id": "<floor-id>", "name": "custom-stem"}
        dicts — the name is optional and, when present, overrides the floor's
        default (sanitized) name. `floor_ids` is a legacy shortcut for the
        same list without any renames.

        Extension is sniffed from the image bytes. Collisions get a numeric
        suffix."""
        p = Path(path)
        if not p.is_file():
            return {"ok": False, "error": "File not found"}
        overrides: dict[str, str] = {}
        wanted: set[str] = set()
        for item in (selections or []):
            if isinstance(item, dict) and item.get("id"):
                fid = item["id"]
                wanted.add(fid)
                name = (item.get("name") or "").strip()
                if name:
                    overrides[fid] = name
            elif isinstance(item, str):
                wanted.add(item)
        for fid in (floor_ids or []):
            if isinstance(fid, str):
                wanted.add(fid)
        if not wanted:
            return {"ok": False, "error": "No floors selected"}
        cfg = _load_config()
        out = Path(out_dir) if out_dir else (p.parent / _dest_name(cfg, "floorplans"))
        try:
            out.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return {"ok": False, "error": f"Could not create output folder: {e}"}

        written = []
        errors = []
        try:
            with zipfile.ZipFile(p, "r") as z:
                names = set(z.namelist())
                body = json.loads(z.read("floorPlans.json"))
                for fp in (body.get("floorPlans") or []):
                    if fp.get("id") not in wanted:
                        continue
                    label = fp.get("name") or f"floor-{fp.get('id')}"
                    image_id = fp.get("imageId")
                    entry = f"image-{image_id}" if image_id else None
                    if not entry or entry not in names:
                        errors.append({"name": label,
                                       "error": "image missing in .esx"})
                        continue
                    try:
                        data = z.read(entry)
                    except (KeyError, OSError) as e:
                        errors.append({"name": label, "error": str(e)})
                        continue
                    ext = _image_ext_from_bytes(data)
                    raw_stem = overrides.get(fp.get("id")) or label
                    stem = _sanitize_folder_name(raw_stem) or f"floor-{fp.get('id')}"
                    dest = _unique_path(out / f"{stem}{ext}")
                    if not _is_inside(dest, out):
                        errors.append({"name": label,
                                       "error": "Destination escapes the output folder"})
                        continue
                    try:
                        dest.write_bytes(data)
                        written.append({"name": label,
                                        "file": dest.name,
                                        "size": len(data),
                                        "size_h": _human_size(len(data))})
                    except Exception as e:
                        errors.append({"name": label, "error": str(e)})
        except (zipfile.BadZipFile, OSError, json.JSONDecodeError) as e:
            return {"ok": False, "error": f"Could not read .esx: {e}"}

        acorn = self.save_esx_info(str(p))

        return {"ok": True, "out_dir": str(out),
                "written": written, "errors": errors,
                "written_count": len(written),
                "error_count": len(errors),
                "acorn_path": acorn.get("path") if acorn.get("ok") else None,
                "acorn_error": None if acorn.get("ok") else acorn.get("error")}


    def save_esx_info(self, path: str) -> dict:
        """Write (or refresh) Squirrel's 'Acorn' — a small text note stashed
        next to the .esx recording basic facts about the project, so you can
        check what's inside an .esx (floor plans, AP/measurement/survey
        counts, and whether it's changed since you last looked) without
        opening Ekahau.

        Independent of Extract Floorplans (which calls this too, to keep the
        note in sync with whatever's actually in the .esx), so it can also
        be run on its own without extracting any images.
        """
        p = Path(path)
        if not p.is_file():
            return {"ok": False, "error": "File not found"}
        names = _esx_floor_plan_names(p)
        if names is None:
            return {"ok": False, "error": "Could not read .esx: no floorPlans.json inside"}
        summary = _esx_summary(p)

        prev = _read_acorn_state(p)
        status, detail_lines = _acorn_diff(prev, names, summary)

        out = _acorn_path(p)
        num_width = len(str(len(names))) if names else 1
        floor_lines = (
            [f"  {i:>{num_width}}. {n}" for i, n in enumerate(names, 1)]
            if names else ["  (none found)"]
        )
        try:
            esx_modified = datetime.fromtimestamp(p.stat().st_mtime)
        except OSError:
            esx_modified = None
        saved_at = f"{datetime.now():%Y-%m-%d %H:%M}"

        lines = [
            _acorn_rule(),
            f" WD Squirrel v{self.app_version}" if self.app_version else " WD Squirrel",
            f" Acorn Site Notes: {p.name} - {saved_at}",
        ]
        if esx_modified:


            lines.append(f" ESX last modified: {esx_modified:%Y-%m-%d %H:%M}")
        lines += [_acorn_rule(), ""]


        if status == "unchanged":
            lines += [f"STATUS: No changes since last note (saved {prev['saved']})", ""]
        elif status == "changed":
            lines += [f"STATUS: CHANGED since last note (saved {prev['saved']})", *detail_lines, ""]

        if summary:
            lines += _acorn_section("Summary", [
                f"  Floor plans:   {summary['floors']}",
                f"  Access points: {summary['aps']}",
                f"  Measurements:  {summary['measurements']}",
                f"  Surveys:       {summary['surveys']}",
            ])

        lines += _acorn_section(f"Floor plans ({len(names)})", floor_lines)
        lines += [_acorn_rule(), ""]

        try:
            out.write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            return {"ok": False, "error": str(e)}
        _write_acorn_state(p, {"saved": saved_at, "floors": names, "summary": summary})
        return {"ok": True, "path": str(out), "floor_count": len(names), "floors": names,
                "status": status}

    def set_folder(self, path: str) -> dict:
        """Set root folder without opening a picker."""
        p = Path(path)
        if not p.is_dir():
            return {"ok": False, "error": f"Not a directory: {path}"}
        self._root = path
        return {"ok": True, "path": path}


    def _scan_dir(self, site_dir: Path, cfg: dict, totals: dict) -> dict | None:
        """Scan a single directory for loose files, return a site entry or None."""
        destinations = _get_destinations(cfg)
        subfolder_display = [d["name"] for d in destinations]
        existing_subs = [name for name in subfolder_display if (site_dir / name).is_dir()]
        missing_subs = [name for name in subfolder_display if name not in existing_subs]


        referenced_names: set[str] = set()
        esx_count = 0
        for f in site_dir.iterdir():
            if f.is_file() and f.suffix.lower() == ".esx":
                esx_count += 1
                referenced_names |= _esx_image_names(f)

        moves = []
        staying = []
        for f in sorted(site_dir.iterdir()):
            if not f.is_file():
                continue
            target = _classify(f, cfg)
            if target is None:
                entry = {
                    "name": f.name,
                    "ext": f.suffix.lower(),
                    "size": f.stat().st_size,
                    "reason": "esx" if f.suffix.lower() == ".esx" else "unknown",
                }
                if entry["reason"] == "esx":
                    summary = _esx_summary(f)
                    if summary is not None:
                        entry["esx"] = summary
                staying.append(entry)
                totals["skipped"] += 1
            else:
                renamed_target = _apply_rename(f.name, site_dir.name, cfg)
                dest_dir_name = _dest_name(cfg, target)
                dest = site_dir / dest_dir_name / renamed_target
                final = _unique_path(dest)
                renamed = (final.name != f.name)
                moves.append({
                    "name": f.name,
                    "ext": f.suffix.lower(),
                    "size": f.stat().st_size,
                    "target": target,
                    "target_display": dest_dir_name,
                    "renamed_to": final.name if renamed else None,
                })
                totals[target] += 1


        unreferenced = []
        if esx_count > 0 and referenced_names:
            for key in ("images", "floorplans"):
                sub_name = _dest_name(cfg, key)
                sub_dir = site_dir / sub_name
                if not sub_dir.is_dir():
                    continue
                for f in sub_dir.iterdir():
                    if not f.is_file() or f.name.startswith("."):
                        continue
                    if _stem_lower(f.name) not in referenced_names:
                        try:
                            fsize = f.stat().st_size
                        except OSError:
                            continue
                        unreferenced.append({
                            "name": f.name,
                            "folder": sub_name,
                            "size": fsize,
                            "size_h": _human_size(fsize),
                        })

        if moves or staying or unreferenced:
            return {
                "folder": site_dir.name,
                "path": str(site_dir),
                "existing_subs": existing_subs,
                "missing_subs": missing_subs,
                "moves": moves,
                "staying": staying,
                "unreferenced": unreferenced,
                "referenced_count": len(referenced_names),
                "esx_count": esx_count,
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
        skip = _effective_skip(cfg)

        sites = []
        totals = {d["key"]: 0 for d in _get_destinations(cfg)}
        totals["skipped"] = 0


        site_dirs = []
        for site_dir in sorted(root_path.iterdir()):
            if not site_dir.is_dir():
                continue
            if site_dir.name.lower() in skip or site_dir.name.startswith("."):
                continue
            site_dirs.append(site_dir)
            entry = self._scan_dir(site_dir, cfg, totals)
            if entry:
                sites.append(entry)


        if not sites:
            entry = self._scan_dir(root_path, cfg, totals)
            if entry:
                entry["folder"] = root_path.name + "  (root folder)"
                entry["is_root"] = True
                sites.append(entry)

        duplicates = self._find_duplicates(site_dirs, cfg) if len(site_dirs) >= 2 else []
        unreferenced_total = sum(len(s.get("unreferenced") or []) for s in sites)

        return {
            "ok": True,
            "root": str(root_path),
            "site_count": len(sites),
            "totals": totals,
            "sites": sites,
            "duplicates": duplicates,
            "duplicate_count": len(duplicates),
            "unreferenced_count": unreferenced_total,
            "destinations": [{"key": d["key"], "name": d["name"], "builtin": d["builtin"]}
                             for d in _get_destinations(cfg)],
        }


    def _find_duplicates(self, site_dirs: list, cfg: dict) -> list:
        """Return dup groups where the same (name_lower, size) appears in >= 2
        different site folders. Each group: {name, size, copies:[{site, rel}]}.
        Only cross-site duplicates — same-site same-name files are impossible
        on filesystems anyway."""
        subfolder_names = [d["name"] for d in _get_destinations(cfg)]
        key_map: dict[tuple[str, int], list[dict]] = {}
        for site_dir in site_dirs:

            candidate_dirs = [site_dir] + [site_dir / sf for sf in subfolder_names]
            for d in candidate_dirs:
                if not d.is_dir():
                    continue
                for f in d.iterdir():
                    if not f.is_file():
                        continue
                    if f.name.startswith("."):
                        continue
                    try:
                        size = f.stat().st_size
                    except OSError:
                        continue
                    key = (f.name.lower(), size)
                    key_map.setdefault(key, []).append({
                        "site": site_dir.name,
                        "rel": str(f.relative_to(site_dir)).replace("\\", "/"),
                        "path": str(f),
                    })

        groups = []
        for (name_lower, size), copies in key_map.items():

            distinct_sites = {c["site"] for c in copies}
            if len(distinct_sites) < 2:
                continue

            display_name = Path(copies[0]["path"]).name
            groups.append({
                "name": display_name,
                "size": size,
                "size_h": _human_size(size),
                "site_count": len(distinct_sites),
                "copy_count": len(copies),
                "copies": copies,
            })

        groups.sort(key=lambda g: (-g["size"] * g["copy_count"], g["name"].lower()))
        return groups


    def _execute_dir(self, site_dir: Path, cfg: dict, excl: set,
                     overrides: dict, totals: dict,
                     folder_label: str, undo_log: dict) -> dict | None:
        """Move loose files in a single directory. Returns a result entry or None.

        Appends to `undo_log["moves"]` and `undo_log["created_dirs"]` so a later
        undo() call can walk the log in reverse.
        """
        for d in _get_destinations(cfg):
            sub_path = site_dir / d["name"]
            if not sub_path.exists():
                sub_path.mkdir()
                undo_log["created_dirs"].append(str(sub_path))

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


            override_key = (folder_label, f.name)
            if override_key in overrides:
                target = overrides[override_key]

            src_path = f
            renamed_target = _apply_rename(f.name, folder_label, cfg)
            dest_dir_name = _dest_name(cfg, target)
            dest = site_dir / dest_dir_name / renamed_target
            if not _is_inside(dest, site_dir):
                site_moves.append({
                    "name": f.name,
                    "target": target,
                    "status": "error",
                    "error": "Destination escapes the site folder",
                })
                totals["errors"] += 1
                continue
            final = _unique_path(dest)
            try:
                shutil.move(str(f), str(final))
                site_moves.append({
                    "name": f.name,
                    "target": target,
                    "renamed_to": final.name if final.name != f.name else None,
                    "status": "moved",
                })
                undo_log["moves"].append({
                    "from": str(src_path),
                    "to": str(final),
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
        skip = _effective_skip(cfg)

        excl = set()
        for item in (excluded or []):
            excl.add((item["folder"], item["name"]))


        ovr = {}
        for item in (overrides or []):
            ovr[(item["folder"], item["name"])] = item["target"]

        results = []
        totals = {d["key"]: 0 for d in _get_destinations(cfg)}
        totals["errors"] = 0
        totals["skipped"] = 0
        undo_log = {"root": str(root_path), "moves": [], "created_dirs": []}


        found_sites = False
        for site_dir in sorted(root_path.iterdir()):
            if not site_dir.is_dir():
                continue
            if site_dir.name.lower() in skip or site_dir.name.startswith("."):
                continue
            found_sites = True
            entry = self._execute_dir(site_dir, cfg, excl, ovr, totals,
                                      site_dir.name, undo_log)
            if entry:
                results.append(entry)


        if not found_sites:
            label = root_path.name + "  (root folder)"
            entry = self._execute_dir(root_path, cfg, excl, ovr, totals,
                                      label, undo_log)
            if entry:
                results.append(entry)


        undo_file = _undo_path(root_path)
        if undo_log["moves"]:
            UNDO_DIR.mkdir(parents=True, exist_ok=True)
            with open(undo_file, "w") as f:
                json.dump(undo_log, f, indent=2)
        elif undo_file.exists():
            try:
                undo_file.unlink()
            except Exception:
                pass

        return {
            "ok": True,
            "root": str(root_path),
            "totals": totals,
            "sites": results,
            "undo_available": len(undo_log["moves"]) > 0,
            "undo_count": len(undo_log["moves"]),
        }


    def has_undo(self, root: str | None = None) -> dict:
        """Return whether an undo log exists for the given root, and how big."""
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": True, "available": False, "count": 0}
        undo_file = _undo_path(root_path)
        if not undo_file.exists():
            return {"ok": True, "available": False, "count": 0}
        try:
            with open(undo_file) as f:
                log = json.load(f)
        except Exception:
            return {"ok": True, "available": False, "count": 0}
        return {
            "ok": True,
            "available": True,
            "count": len(log.get("moves", [])),
        }

    def undo(self, root: str | None = None) -> dict:
        """Reverse the last organize run for this root. Moves each file back
        to its recorded original path (skipping any where the current file no
        longer exists or the original slot is now occupied), then removes any
        subfolders it created if they are still empty. Deletes the rollback log
        on completion so it can't be undone twice."""
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set"}
        undo_file = _undo_path(root_path)
        if not undo_file.exists():
            return {"ok": False, "error": "Nothing to undo for this folder"}
        try:
            with open(undo_file) as f:
                log = json.load(f)
        except Exception as e:
            return {"ok": False, "error": f"Rollback log unreadable: {e}"}

        restored = 0
        skipped = 0
        errors = 0
        details = []


        for m in reversed(log.get("moves", [])):
            src = Path(m["to"])
            dst = Path(m["from"])
            if not src.exists():
                skipped += 1
                details.append({"name": src.name, "status": "skipped",
                                "reason": "file no longer at moved location"})
                continue
            if dst.exists():
                skipped += 1
                details.append({"name": src.name, "status": "skipped",
                                "reason": "original slot is occupied"})
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                restored += 1
                details.append({"name": src.name, "status": "restored"})
            except Exception as e:
                errors += 1
                details.append({"name": src.name, "status": "error",
                                "error": str(e)})


        removed_dirs = []
        for d in reversed(log.get("created_dirs", [])):
            p = Path(d)
            try:
                if p.is_dir() and not any(p.iterdir()):
                    p.rmdir()
                    removed_dirs.append(str(p))
            except Exception:
                pass


        try:
            undo_file.unlink()
        except Exception:
            pass

        return {
            "ok": True,
            "restored": restored,
            "skipped": skipped,
            "errors": errors,
            "removed_dirs": removed_dirs,
            "details": details,
        }


    def migrate_subfolders(self, root: str | None = None,
                           renames: dict | None = None) -> dict:
        """Rename existing on-disk subfolders across every site under `root`.
        `renames` is {old_name: new_name}. Only renames that would collide
        (target already exists) are skipped and reported."""
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set"}
        if not renames:
            return {"ok": False, "error": "No renames specified"}

        safe: dict[str, str] = {}
        for old, new in renames.items():
            if not old or not new or old == new:
                continue
            cleaned = _sanitize_folder_name(new)
            if not cleaned:
                return {"ok": False,
                        "error": f"'{new}' is not a valid folder name"}
            safe[old] = cleaned
        if not safe:
            return {"ok": True, "renamed": 0, "skipped": 0, "details": []}

        cfg = _load_config()
        skip = {s.lower() for s in cfg["skip_dirs"]}
        renamed = 0
        skipped = 0
        details = []
        for site_dir in sorted(root_path.iterdir()):
            if not site_dir.is_dir():
                continue
            if site_dir.name.lower() in skip or site_dir.name.startswith("."):
                continue
            for old, new in safe.items():
                src = site_dir / old
                dst = site_dir / new
                if not _is_inside(src, site_dir) or not _is_inside(dst, site_dir):
                    skipped += 1
                    details.append({"site": site_dir.name,
                                    "from": old, "to": new,
                                    "status": "error",
                                    "reason": "Path escapes the site folder"})
                    continue
                if not src.is_dir():
                    continue
                if dst.exists():
                    skipped += 1
                    details.append({"site": site_dir.name,
                                    "from": old, "to": new,
                                    "status": "skipped",
                                    "reason": "target exists"})
                    continue
                try:
                    src.rename(dst)
                    renamed += 1
                    details.append({"site": site_dir.name,
                                    "from": old, "to": new,
                                    "status": "renamed"})
                except Exception as e:
                    skipped += 1
                    details.append({"site": site_dir.name,
                                    "from": old, "to": new,
                                    "status": "error",
                                    "reason": str(e)})
        return {"ok": True, "renamed": renamed, "skipped": skipped,
                "details": details}


    def detect_rename_style(self, root: str | None = None) -> dict:
        """Guess which word-separator convention is already in use among the
        files under `root`, so Bulk Rename can default to matching what's
        already there instead of always starting from "Leave as-is". Each
        file casts one vote for the first separator style it contains
        (spaced-dash checked before plain hyphen so 'My - File.jpg' doesn't
        register as a hyphen file); the most-voted style wins, ties/no
        signal fall back to "" (leave as-is)."""
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set"}

        cfg = _load_config()
        skip = _effective_skip(cfg)
        subfolder_names = [d["name"] for d in _get_destinations(cfg)]
        votes = {"spaced_hyphen": 0, "underscore": 0, "hyphen": 0, "space": 0}

        def tally(d: Path):
            if not d.is_dir():
                return
            for f in d.iterdir():
                if not f.is_file() or f.name.startswith(".") or f.suffix.lower() == ".esx":
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
            if d.is_dir() and d.name.lower() not in skip and not d.name.startswith(".")
        ]
        for site_dir in (site_dirs or [root_path]):
            tally(site_dir)
            for sf in subfolder_names:
                tally(site_dir / sf)

        best = max(votes, key=votes.get)
        runner_up = max((v for k, v in votes.items() if k != best), default=0)
        separator = best if votes[best] > 0 and votes[best] > runner_up else ""
        return {"ok": True, "separator": separator, "votes": votes}

    def preview_bulk_rename(self, root: str | None = None,
                            rename: dict | None = None) -> dict:
        """Dry-run the rename rules across every file already in place under
        `root` — site root + each destination subfolder, one level deep,
        same scope as duplicate detection. Files whose computed name doesn't
        change are omitted. `rename` overrides the saved rule set for preview
        without persisting it (used for the live example in the Bulk Rename
        tool); omit to preview the saved rules."""
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set"}

        cfg = _load_config()
        if rename is not None:
            cfg = dict(cfg)
            cfg["rename"] = rename
        skip = _effective_skip(cfg)
        subfolder_names = [d["name"] for d in _get_destinations(cfg)]

        def scan_site(site_dir: Path) -> list:
            found = []
            candidate_dirs = [site_dir] + [site_dir / sf for sf in subfolder_names]
            for d in candidate_dirs:
                if not d.is_dir():
                    continue
                for f in sorted(d.iterdir()):
                    if not f.is_file() or f.name.startswith("."):
                        continue
                    if f.suffix.lower() == ".esx":
                        continue
                    new_name = _apply_rename(f.name, site_dir.name, cfg)
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
            if d.is_dir() and d.name.lower() not in skip and not d.name.startswith(".")
        ]
        items = []
        for site_dir in site_dirs:
            items.extend(scan_site(site_dir))


        if not site_dirs:
            items.extend(scan_site(root_path))
        return {"ok": True, "items": items, "count": len(items)}

    def execute_bulk_rename(self, items: list | None = None) -> dict:
        """Apply a set of {path, new_name} renames computed by
        preview_bulk_rename. Same-directory renames only; skips anything
        whose target already exists rather than overwriting."""
        if not items:
            return {"ok": False, "error": "Nothing to rename"}
        renamed = 0
        skipped = 0
        details = []
        for it in items:
            src = Path(it.get("path") or "")
            new_name = _sanitize_folder_name(it.get("new_name") or "")
            if not src.is_file() or not new_name:
                skipped += 1
                details.append({"old_name": src.name, "new_name": it.get("new_name"),
                                "status": "error", "reason": "invalid path or name"})
                continue
            dst = src.parent / new_name
            if not _is_inside(dst, src.parent):
                skipped += 1
                details.append({"old_name": src.name, "new_name": new_name,
                                "status": "error", "reason": "invalid target name"})
                continue
            if dst.exists():
                skipped += 1
                details.append({"old_name": src.name, "new_name": new_name,
                                "status": "skipped", "reason": "target exists"})
                continue
            try:
                src.rename(dst)
                renamed += 1
                details.append({"old_name": src.name, "new_name": new_name, "status": "renamed"})
            except Exception as e:
                skipped += 1
                details.append({"old_name": src.name, "new_name": new_name,
                                "status": "error", "reason": str(e)})
        return {"ok": True, "renamed": renamed, "skipped": skipped, "details": details}


    def suggest_groups(self, root: str | None = None) -> dict:
        """Detect candidate site-prefix groupings in a flat folder.

        Advisory only — no moves. Called after a scan comes back with no
        site subfolders. Groups files by the leading token in the basename
        (up to the first space/dash/underscore/dot). Returns groups where at
        least 2 files share a prefix AND the prefix has ≥ 3 chars, so we
        don't group ambiguous 1-2 char shorthand.
        """
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set"}
        cfg = _load_config()
        skip_names = _effective_skip(cfg)
        prefix_re = re.compile(r"^([A-Za-z0-9]+)")
        groups: dict[str, list[dict]] = {}
        unmatched = 0
        total = 0
        for f in sorted(root_path.iterdir()):
            if not f.is_file():
                continue
            if f.name.startswith("."):
                continue
            total += 1
            m = prefix_re.match(f.stem)
            if not m:
                unmatched += 1
                continue
            token = m.group(1)
            if len(token) < 3:
                unmatched += 1
                continue
            key = token.upper()
            groups.setdefault(key, []).append({
                "name": f.name,
                "size": f.stat().st_size,
                "ext": f.suffix.lower(),
            })

        candidates = []
        for key, files in groups.items():
            if len(files) < 2:
                unmatched += len(files)
                continue


            if key.lower() in skip_names:
                unmatched += len(files)
                continue
            candidates.append({
                "prefix": key,
                "count": len(files),
                "files": files,
            })
        candidates.sort(key=lambda c: (-c["count"], c["prefix"]))

        return {
            "ok": True,
            "root": str(root_path),
            "candidates": candidates,
            "unmatched": unmatched,
            "total_loose_files": total,
        }

    def apply_grouping(self, root: str | None = None,
                       groups: list | None = None) -> dict:
        """Create subfolders and move files into them per the user's picks.

        `groups` is a list of {"prefix": "SITE1", "folder_name": "SITE1",
        "files": ["file1.png", "file2.pdf", ...]}. Any files not listed stay
        in the root. Returns totals + writes to the same undo log as
        execute() so the user can undo grouping the same way.
        """
        root_path = Path(root or self._root or "")
        if not root_path.is_dir():
            return {"ok": False, "error": "No valid root folder set"}
        if not groups:
            return {"ok": False, "error": "No groups to apply"}

        undo_log = {"root": str(root_path), "moves": [], "created_dirs": []}
        moved = 0
        errors = 0
        details = []
        for g in groups:
            folder_name = (g.get("folder_name") or g.get("prefix") or "").strip()
            if not folder_name:
                continue
            safe = re.sub(r'[<>:"/\\|?*]', '-', folder_name).rstrip('.')
            if not safe or '..' in safe:
                continue
            target_dir = root_path / safe
            if not target_dir.exists():
                try:
                    target_dir.mkdir()
                    undo_log["created_dirs"].append(str(target_dir))
                except Exception as e:
                    errors += len(g.get("files") or [])
                    details.append({"folder": safe, "status": "error",
                                    "error": str(e)})
                    continue
            elif not target_dir.is_dir():
                errors += len(g.get("files") or [])
                details.append({"folder": safe, "status": "error",
                                "error": "target path exists but is not a directory"})
                continue

            for fname in (g.get("files") or []):
                src = root_path / fname
                dest = target_dir / fname
                if not _is_inside(src, root_path) or not _is_inside(dest, target_dir):
                    errors += 1
                    details.append({"folder": safe, "name": fname,
                                    "status": "error",
                                    "error": "Path escapes the root folder"})
                    continue
                if not src.is_file():
                    details.append({"folder": safe, "name": fname,
                                    "status": "skipped",
                                    "reason": "file not found"})
                    continue
                final = _unique_path(dest)
                try:
                    shutil.move(str(src), str(final))
                    undo_log["moves"].append({
                        "from": str(src),
                        "to": str(final),
                    })
                    moved += 1
                    details.append({"folder": safe, "name": fname,
                                    "status": "moved",
                                    "renamed_to": final.name if final.name != fname else None})
                except Exception as e:
                    errors += 1
                    details.append({"folder": safe, "name": fname,
                                    "status": "error", "error": str(e)})


        if undo_log["moves"]:
            UNDO_DIR.mkdir(parents=True, exist_ok=True)
            with open(_undo_path(root_path), "w") as f:
                json.dump(undo_log, f, indent=2)

        return {
            "ok": True,
            "root": str(root_path),
            "moved": moved,
            "errors": errors,
            "details": details,
            "undo_available": len(undo_log["moves"]) > 0,
            "undo_count": len(undo_log["moves"]),
        }
