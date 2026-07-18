"""
WD Cloud Manager — backend logic for the browser-based suite.

This is the pywebview app.py's proven logic, minus all the pywebview/window
machinery. It exposes a CloudManager class whose methods the Flask server
turns into JSON HTTP endpoints. Auth still uses browser_cookie3 server-side.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import requests

try:
    import browser_cookie3
except ImportError:
    browser_cookie3 = None

EKAHAU_URL = "https://www.ekahau.cloud"
API_BASE = "/projectapi/v1/projects"
CONFIG_DIR = Path.home() / ".wd_wireless_tools"
CONFIG_FILE = CONFIG_DIR / "config.json"
COOKIE_FILE = CONFIG_DIR / "cookies.json"
NOT_MATCH_FILE = CONFIG_DIR / "not_matches.json"


def _assert_inside(path, root):
    """Raise ValueError if *path* resolves outside *root*."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        raise ValueError(f"Path is outside the allowed directory: {path}")


# ── config / cookie persistence ───────────────────────────────────────
def load_config():
    cfg = {"output_dir": ""}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def save_cookies_to_disk(cookies, csrf):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = json.dumps({"cookies": cookies, "csrfToken": csrf})
    if sys.platform != "win32":
        fd = os.open(str(COOKIE_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(data)
    else:
        with open(COOKIE_FILE, "w") as f:
            f.write(data)


def load_cookies_from_disk():
    if COOKIE_FILE.exists():
        try:
            with open(COOKIE_FILE) as f:
                data = json.load(f)
            return data.get("cookies", []), data.get("csrfToken", "")
        except Exception:
            pass
    return None, None


# ── not-a-match persistence ───────────────────────────────────────────
# User-declared "these two are NOT the same project." Stored per-user so
# decisions carry across sessions and folder rescans. Pair identity is the
# stable (cloud_id, local_path) tuple — cloud ids are Ekahau UUIDs that
# survive renames, and local paths are stable until the user moves the file.
def _nm_pair_key(cloud_id, local_path):
    return f"{cloud_id or ''}||{(local_path or '').replace(chr(92), '/').lower()}"


def load_not_matches():
    if NOT_MATCH_FILE.exists():
        try:
            with open(NOT_MATCH_FILE) as f:
                data = json.load(f) or {}
            pairs = data.get("pairs", []) or []
            return [p for p in pairs if p.get("cloudId") and p.get("localPath")]
        except Exception:
            pass
    return []


def save_not_matches(pairs):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(NOT_MATCH_FILE, "w") as f:
        json.dump({"pairs": pairs}, f, indent=2)


def not_matches_set():
    return {_nm_pair_key(p["cloudId"], p["localPath"]) for p in load_not_matches()}


# ── Ekahau Cloud API client ───────────────────────────────────────────
class EkahauAPI:
    def __init__(self, cookies, csrf_token):
        self.http = requests.Session()
        self.csrf_token = csrf_token
        self.user_email = ""
        if isinstance(cookies, list):
            for c in cookies:
                self.http.cookies.set(c["name"], c["value"],
                                      domain=c.get("domain", ".ekahau.cloud"),
                                      path=c.get("path", "/"))
        else:
            self.http.cookies = cookies
        self.http.headers.update({
            "csrfToken": csrf_token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101",
            "Referer": "https://www.ekahau.cloud/",
            "Accept": "*/*",
        })

    def test_connection(self):
        try:
            r = self.http.get(f"{EKAHAU_URL}/site-management-api/v1/sites",
                              allow_redirects=False, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    self.user_email = data[0].get("ownerEmail", "")
                return True
        except Exception:
            pass
        return False

    def get(self, path):
        r = self.http.get(f"{EKAHAU_URL}{path}", allow_redirects=True, timeout=120)
        r.raise_for_status()
        return r

    def _write(self, method, path, json_body=None):
        r = self.http.request(method, f"{EKAHAU_URL}{path}", json=json_body,
                              headers={"csrftoken": self.csrf_token,
                                       "Accept": "application/json, text/plain, */*",
                                       "Content-Type": "application/json"}, timeout=30)
        if not r.ok:
            # Include a snippet of the server's response body so the caller can
            # see what Ekahau actually complained about (500s often carry a
            # useful message that raise_for_status() would otherwise hide).
            body = (r.text or "").strip()
            snippet = body[:300] + ("…" if len(body) > 300 else "") if body else "no response body"
            raise requests.HTTPError(
                f"{r.status_code} {r.reason} on {method} {path} — {snippet}",
                response=r,
            )
        return r

    def get_sites(self):     return self.get("/site-management-api/v1/sites").json()
    def get_projects(self):  return self.get(API_BASE).json()
    def get_dataset_listing(self):  return self.get("/site-management-api/v1/datasetListing").json()

    def rename_site(self, sid, name):
        r = self._write("PUT", f"/site-management-api/v1/sites/{sid}", {"name": name})
        return r.json() if (r.text or "").strip() else {"ok": True}

    def create_site(self, name):
        r = self._write("POST", "/site-management-api/v1/sites", {"name": name})
        return r.json() if (r.text or "").strip() else {"ok": True}

    def delete_sites(self, ids):
        r = self._write("DELETE", "/site-management-api/v1/sites", ids)
        return r.json() if (r.text or "").strip() else {"ok": True}

    def rename_project(self, pid, name):
        proj = self.get(f"{API_BASE}/{pid}").json()
        proj["name"] = name
        proj["title"] = name
        proj["status"] = "UPDATED"
        r = self._write("PUT", f"{API_BASE}/{pid}/batch/update", {"project": proj})
        # batch/update sometimes returns 204 No Content or an empty body on success
        return r.json() if (r.text or "").strip() else {"ok": True}

    def get_dataset(self, dataset_id):
        return self.get(f"/site-management-api/v1/datasets/{dataset_id}").json()

    def delete_dataset(self, dataset_id, dtype):
        r = self._write("DELETE", "/site-management-api/v1/datasets",
                        [{"datasetId": dataset_id, "type": dtype}])
        try:
            return r.json()
        except Exception:
            return {"ok": True}

    def delete_project(self, project_id):
        """Delete a cloud project via the batch-delete endpoint."""
        r = self._write("PUT", f"{API_BASE}/batch-delete",
                         {"projects": [project_id]})
        try:
            return r.json()
        except Exception:
            return {"ok": True, "status": r.status_code}

    def assign_to_site(self, site_id, dataset_id, dtype=None):
        """Move/assign a project (dataset) into a site."""
        if not dtype:
            try:
                dtype = self.get_dataset(dataset_id).get("type", "SIMULATED_PROJECT")
            except Exception:
                dtype = "SIMULATED_PROJECT"
        r = self._write("POST", f"/site-management-api/v1/sites/{site_id}/datasets",
                         [{"datasetId": dataset_id, "type": dtype}])
        try:
            return r.json()
        except Exception:
            return {"ok": True, "status": r.status_code}

    def upload_project(self, esx_path, progress_cb=None):
        """Upload a local .esx file to Ekahau Cloud (3-step presigned flow).

        1. POST /esxfileapi/v1/projects/upload/initiate  →  presigned S3 URL + id
        2. PUT  the raw bytes to S3
        3. POST /esxfileapi/v1/projects/upload/commit?fileUploadId=…

        progress_cb(stage, detail) is called if provided:
            ("initiate", None) → ("upload", pct) → ("commit", None) → ("done", resp)
        """
        p = Path(esx_path)
        if not p.is_file():
            return {"error": f"File not found: {esx_path}"}
        file_name = p.name
        file_size = p.stat().st_size

        # ── step 1: initiate ─────────────────────────────────────────
        if progress_cb:
            progress_cb("initiate", None)
        init_r = self._write("POST", "/esxfileapi/v1/projects/upload/initiate",
                             {"fileName": file_name, "fileExtension": "esx"})
        init_data = init_r.json()

        # Field names confirmed from API capture
        upload_url = (init_data.get("url")
                      or init_data.get("uploadUrl")
                      or init_data.get("presignedUrl"))
        file_upload_id = (init_data.get("fileUploadId")
                          or init_data.get("id")
                          or init_data.get("uploadId"))

        if not upload_url or not file_upload_id:
            # Return the raw response so we can see the actual field names
            return {"error": "Could not parse initiate response — check raw fields",
                    "raw_initiate_response": init_data}

        # ── step 2: PUT bytes to S3 ──────────────────────────────────
        if progress_cb:
            progress_cb("upload", 0)
        with open(p, "rb") as f:
            file_bytes = f.read()

        s3_r = self.http.put(upload_url, data=file_bytes,
                             headers={"Content-Type": "application/esx"},
                             timeout=max(300, file_size // 50000))  # scale timeout w/ size
        s3_r.raise_for_status()
        if progress_cb:
            progress_cb("upload", 100)

        # ── step 3: commit ───────────────────────────────────────────
        if progress_cb:
            progress_cb("commit", None)
        commit_r = self._write("POST",
                               f"/esxfileapi/v1/projects/upload/commit"
                               f"?fileUploadId={file_upload_id}", {})
        if progress_cb:
            progress_cb("done", None)

        try:
            return commit_r.json()
        except Exception:
            return {"ok": True, "status": commit_r.status_code}


# ── cookie discovery ──────────────────────────────────────────────────
def try_browser_cookies():
    if browser_cookie3 is None:
        return None
    browsers = [("Chrome", browser_cookie3.chrome), ("Firefox", browser_cookie3.firefox),
                ("Edge", browser_cookie3.edge), ("Opera", browser_cookie3.opera)]
    for _name, func in browsers:
        try:
            jar = func(domain_name=".ekahau.cloud")
            names = [c.name for c in jar]
            csrf = next((c.value for c in jar if c.name == "CSRF-Token"), "")
            if "AccessToken" in names and csrf:
                api = EkahauAPI(jar, csrf)
                if api.test_connection():
                    cookie_list = [{"name": c.name, "value": c.value,
                                    "domain": c.domain, "path": c.path} for c in jar]
                    save_cookies_to_disk(cookie_list, csrf)
                    return api
        except Exception:
            continue
    return None


def try_saved_cookies():
    cookies, csrf = load_cookies_from_disk()
    if not cookies or not csrf:
        return None
    api = EkahauAPI(cookies, csrf)
    return api if api.test_connection() else None


# ── matching helpers ──────────────────────────────────────────────────
def extract_site_code(name):
    m = re.match(r"([A-Z]{2,}[0-9]+)", name.strip())
    return m.group(1) if m else None


def fuzzy_similarity(a, b):
    aw = set(re.findall(r'\w+', a.lower()))
    bw = set(re.findall(r'\w+', b.lower()))
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / len(aw | bw)


def _building_token(name):
    m = re.search(r'\b(?:bld|bldg|building)\.?\s*(\d{1,2}|[A-Za-z])(?![A-Za-z0-9])', name, re.I)
    return m.group(1).upper() if m else None


def _street_number(name):
    stripped = re.sub(r'^\s*[A-Za-z]{2,}\d+', '', name.strip())
    m = re.search(r'\b(\d{3,6})\b', stripped)
    return m.group(1) if m else None


# Survey-phase tokens. When both names carry a phase token AND the phases
# differ, the two projects can't be the same file — a Baseline can never be a
# Cleanroom-PD, etc. Order matters: the first matching token wins, so put more
# specific tokens (e.g. "cleanroom") before generic ones. "PD" is intentionally
# excluded — it's ambiguous ("Predictive Design" as a phase, but also appears as
# a suffix on room-scoped surveys like "Cleanroom - PD").
_SURVEY_PHASE_TOKENS = [
    ("baseline",     "baseline"),
    ("remediation",  "remediation"),
    ("cleanroom",    "cleanroom"),
    ("predictive",   "predictive"),
    ("post-install", "postinstall"),
    ("postinstall",  "postinstall"),
    ("post_install", "postinstall"),
    ("pre-install",  "preinstall"),
    ("preinstall",   "preinstall"),
    ("as-built",     "asbuilt"),
    ("asbuilt",      "asbuilt"),
    ("as-ran",       "asran"),
    ("asran",        "asran"),
    ("validation",   "validation"),
    ("tvr",          "validation"),
]


def _survey_phase(name):
    n = name.lower()
    for token, phase in _SURVEY_PHASE_TOKENS:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])", n):
            return phase
    return None


def discriminators_conflict(a, b):
    ba, bb = _building_token(a), _building_token(b)
    if ba and bb and ba != bb:
        return True
    sa, sb = _street_number(a), _street_number(b)
    if sa and sb and sa != sb:
        return True
    pa, pb = _survey_phase(a), _survey_phase(b)
    if pa and pb and pa != pb:
        return True
    return False


# Size threshold for the metadata discriminator. Below this both sides are
# treated as "too small to compare" (Ekahau template stubs are ~500KB).
_SIZE_FLOOR_BYTES = 500_000
# Ratio above which two .esx files can't be the same project. A same-project
# cloud/local pair usually stays within ~2x (edits, versioning). 5x is the
# threshold where "clearly different content" starts.
_SIZE_RATIO_CUTOFF = 5.0
# Date-gap threshold. Same-project mtimes can legitimately drift by months
# (old cloud snapshot, recent local edit). Only very large gaps — >5 years —
# suggest two different projects that happened to share names or codes.
_MTIME_GAP_SECS = 5 * 365 * 24 * 3600  # ≈ 5 years


def _size_conflict(cloud_item, local_item):
    """True when both sides have a measurable size AND they differ by more
    than _SIZE_RATIO_CUTOFF. Works regardless of file-naming convention —
    the universal signal for users whose files aren't tagged with survey phases."""
    cs = int(cloud_item.get("size") or 0)
    ls = int(local_item.get("size") or 0)
    if cs < _SIZE_FLOOR_BYTES or ls < _SIZE_FLOOR_BYTES:
        return False
    hi, lo = (cs, ls) if cs >= ls else (ls, cs)
    return (hi / lo) > _SIZE_RATIO_CUTOFF


def _mtime_conflict(cloud_item, local_item):
    """True when both sides have a modification timestamp AND they're more
    than _MTIME_GAP_SECS apart. Complements size — a small template file that
    survives the size floor can still be caught here when the timestamps
    diverge by years."""
    cm = int(cloud_item.get("mtime") or 0)
    lm = int(local_item.get("mtime") or 0)
    if cm <= 0 or lm <= 0:
        return False
    return abs(cm - lm) > _MTIME_GAP_SECS


def pair_conflicts(c, l):
    """A cloud item and a local item can't be the same project when ANY of:
    (name) building/street/phase discriminators disagree,
    (size) file sizes differ by more than an order of magnitude, or
    (date) modification times are years apart.
    Name-based checks are convention-specific; size + date are universal and
    work on generic names like 'Building 1' where heuristics have nothing to grip."""
    if discriminators_conflict(c["name"], l["name"]):
        return True
    if _size_conflict(c, l):
        return True
    if _mtime_conflict(c, l):
        return True
    return False


def human_size(b):
    if not b:
        return "0 B"
    if b < 1024:
        return f"{b} B"
    if b < 1048576:
        return f"{b / 1024:.0f} KB"
    return f"{b / 1048576:.1f} MB"


# Subfolders that hold backup/output copies — skip so they don't flood the list.
_SKIP_DIRS = {"backups", "backup", "output", "outputs", "archive", "archives", ".git"}


def _esx_in_folder(folder):
    """Every .esx under a site folder at ANY depth, minus backup/output subfolders."""
    files = []
    for f in folder.rglob("*.esx"):
        rel = [p.lower() for p in f.relative_to(folder).parts[:-1]]
        if any(part in _SKIP_DIRS for part in rel):
            continue
        files.append(f)
    return files


# Non-.esx file types worth flagging: Ekahau Cloud stores ONLY the .esx, so
# anything else in a local folder (floor plans, installer images, CAD) exists
# nowhere else and must never be deleted without the user seeing it first.
_FLOORPLAN_EXT = {".pdf", ".dwg", ".dxf"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".svg", ".webp", ".heic"}


def folder_inventory(folder):
    """Inventory a site folder's contents so the UI can preview any folder,
    badge the ones holding precious non-.esx "source" files (floor plans,
    images, CAD — none of which live on Ekahau Cloud), and guard deletes.
    Skips backup/output subfolders."""
    esx_files, plans, images, other = [], [], [], []
    try:
        for f in folder.rglob("*"):
            if not f.is_file():
                continue
            rel_parts = [p.lower() for p in f.relative_to(folder).parts[:-1]]
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            ext = f.suffix.lower()
            try:
                st = f.stat()
                size, mtime = st.st_size, int(st.st_mtime)
            except OSError:
                size, mtime = 0, 0
            rec = {"name": f.name, "size": size, "sizeH": human_size(size),
                   "mtime": mtime, "rel": str(f.relative_to(folder)), "type": "other"}
            if ext == ".esx":
                rec["type"] = "esx"; esx_files.append(rec)
            elif ext in _FLOORPLAN_EXT:
                rec["type"] = "plan"; plans.append(rec)
            elif ext in _IMAGE_EXT:
                rec["type"] = "image"; images.append(rec)
            else:
                other.append(rec)
    except OSError:
        pass
    source = plans + images + other              # non-.esx = precious, cloud-less
    allfiles = esx_files + source                 # .esx listed first in the peek
    slim = [{"name": r["name"], "sizeH": r["sizeH"], "mtime": r["mtime"],
             "rel": r["rel"], "type": r["type"]} for r in allfiles[:400]]
    return {
        "esx": len(esx_files), "plans": len(plans), "images": len(images), "other": len(other),
        "srcCount": len(source), "srcSizeH": human_size(sum(r["size"] for r in source)),
        "total": len(allfiles), "files": slim,
    }


def _walk_files(root):
    """Every file under root at any depth, skipping backup/output subfolders."""
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        rel_parts = [p.lower() for p in f.relative_to(root).parts[:-1]]
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        yield f


def _unique_path(p):
    """A non-colliding sibling path: 'name.pdf' -> 'name (1).pdf', etc."""
    if not p.exists():
        return p
    i = 1
    while True:
        cand = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not cand.exists():
            return cand
        i += 1


def _force_remove(func, path, exc_info):
    """rmtree onerror hook: Windows/OneDrive read-only files raise Access
    denied on delete — clear the read-only bit and retry the operation once."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _timestamped_path(p, mtime):
    """A dated sibling name from a file's modified time, e.g.
    'notes.txt' -> 'notes 2026-07-09_143205.txt'. Used to archive the OLDER of
    two same-named files so the newer one keeps the clean name."""
    ts = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(mtime))
    return _unique_path(p.with_name(f"{p.stem} {ts}{p.suffix}"))


def _safe_iterdir(p):
    """Top-level entries, tolerant of a locked/syncing item (e.g. OneDrive)."""
    try:
        return sorted(p.iterdir(), key=lambda x: x.name.lower())
    except OSError:
        return []


def _esx_size(f):
    try:
        return f.stat().st_size
    except OSError:
        return 0


def get_local_folders(output_dir):
    # Single level: each top-level folder is a "site"; its .esx are direct
    # children. (Ekahau Cloud can't nest sites, so we don't recurse deeper.)
    # Every per-item access is guarded so one locked/syncing folder (OneDrive
    # loves to lock a folder right after a move) can't blow up the whole scan.
    p = Path(output_dir)
    if not p.exists():
        return []
    folders = []
    for d in _safe_iterdir(p):
        try:
            if not d.is_dir() or d.name.startswith(".") or d.name.lower() in _SKIP_DIRS:
                continue
            files = sorted(d.glob("*.esx"), key=lambda x: x.name.lower())
            folders.append({
                "name": d.name, "code": extract_site_code(d.name),
                "esxCount": len(files), "totalSize": sum(_esx_size(f) for f in files),
                "path": str(d),
            })
        except OSError:
            continue
    return folders


def get_local_esx_files(output_dir):
    p = Path(output_dir)
    if not p.exists():
        return []
    out = []
    for d in _safe_iterdir(p):
        try:
            if not d.is_dir() or d.name.startswith(".") or d.name.lower() in _SKIP_DIRS:
                continue
            for f in sorted(d.glob("*.esx"), key=lambda x: x.name.lower()):
                try:
                    mtime = int(f.stat().st_mtime)
                except OSError:
                    mtime = 0
                out.append({"name": f.stem, "folder": d.name,
                            "size": _esx_size(f), "path": str(f), "mtime": mtime,
                            "owner": _esx_author(f, mtime)})
        except OSError:
            continue
    out.sort(key=lambda x: x["name"].lower())
    return out


# In-memory cache: {path: (mtime, author_str)}. Keyed by mtime so a .esx that
# gets re-saved (mtime changes) is re-parsed the next time we look. A cold
# scan of ~150 files is ~9s; the warm scan drops to <100ms.
_ESX_AUTHOR_CACHE = {}


def _esx_author(path, mtime):
    """Read project.history.createdBy from a .esx's project.json.
    Returns the raw value (email or display-name, whichever the .esx has),
    lowercased and stripped. Empty string on any error. Cached by mtime."""
    key = str(path)
    hit = _ESX_AUTHOR_CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    author = ""
    try:
        import zipfile
        with zipfile.ZipFile(path) as z:
            if "project.json" in z.namelist():
                with z.open("project.json") as pj:
                    data = json.load(pj)
                proj = (data or {}).get("project") or {}
                history = proj.get("history") or {}
                author = (history.get("createdBy") or "").strip().lower()
    except Exception:
        author = ""
    _ESX_AUTHOR_CACHE[key] = (mtime, author)
    return author


def build_matches(cloud_items, local_items, excluded=None):
    # Three global passes so stronger evidence always wins: every cloud project
    # gets first crack at an EXACT-name local file, then a site-CODE match, then
    # a fuzzy match on the leftovers. This prevents an early cloud project from
    # greedily "stealing" a local .esx (via a weak fuzzy hit) that another cloud
    # project matches exactly or by code — the old single-pass bug that could
    # push a code-matched project (e.g. BALB01) into "cloud only".
    excluded = excluded or set()

    def _blocked(c, l):
        cid = c.get("id") or ""
        lp = l.get("path") or ""
        return _nm_pair_key(cid, lp) in excluded

    matched = []
    unmatched_local = list(local_items)

    def _take(c, idx, mtype, score):
        l = unmatched_local.pop(idx)
        disp = score - 2.0 if mtype == "code" else score
        matched.append({"cloud": c, "local": l, "matchType": mtype,
                        "score": round(min(disp, 1.0), 2),
                        "namesDiffer": c["name"].strip() != l["name"].strip()})

    # Pass 1 — exact name (case/space-normalized equality).
    pending = []
    for c in cloud_items:
        cn = c["name"].strip()
        hit = next((i for i, l in enumerate(unmatched_local)
                    if cn == l["name"].strip() and not _blocked(c, l)), None)
        if hit is not None:
            _take(c, hit, "exact", 3.0)
        else:
            pending.append(c)

    # Pass 2 — same site code, best fuzzy tie-break, respecting discriminators.
    still = []
    for c in pending:
        cloud_code = c.get("code") or extract_site_code(c["name"])
        best, best_score = None, 0
        if cloud_code:
            for i, l in enumerate(unmatched_local):
                if _blocked(c, l):
                    continue
                if pair_conflicts(c, l):
                    continue
                lcode = l.get("code") or extract_site_code(l["name"])
                if lcode and lcode == cloud_code:
                    score = 2.0 + fuzzy_similarity(c["name"], l["name"])
                    if score > best_score:
                        best, best_score = i, score
        if best is not None:
            _take(c, best, "code", best_score)
        else:
            still.append(c)

    # Pass 3 — fuzzy match on whatever remains.
    unmatched_cloud = []
    for c in still:
        best, best_score = None, 0
        for i, l in enumerate(unmatched_local):
            if _blocked(c, l):
                continue
            if pair_conflicts(c, l):
                continue
            sim = fuzzy_similarity(c["name"], l["name"])
            if sim > 0.5 and sim > best_score:
                best, best_score = i, sim
        if best is not None:
            _take(c, best, "fuzzy", best_score)
        else:
            unmatched_cloud.append(c)

    # Alpha-sort everything by name.
    matched.sort(key=lambda e: e["cloud"]["name"].lower())
    unmatched_cloud.sort(key=lambda c: c["name"].lower())
    unmatched_local.sort(key=lambda l: l["name"].lower())
    mismatches = [e for e in matched if e["namesDiffer"]]
    return {
        "matched": matched, "mismatches": mismatches,
        "cloudOnly": unmatched_cloud, "localOnly": unmatched_local,
        "summary": {"matched": len(matched), "mismatches": len(mismatches),
                    "cloudOnly": len(unmatched_cloud), "localOnly": len(unmatched_local)},
    }


def build_sites_data(api, output_dir):
    sites = api.get_sites()

    # Build a name→id map from sites (some Ekahau responses only give us
    # siteName on dataset listings, so we need a fallback).
    site_id_by_name = {}
    for s in sites:
        sid = s.get("siteId") or s.get("id")
        if sid:
            site_id_by_name[s.get("name", "")] = sid

    # Map dataset id → site id via the dataset listing endpoint.
    dataset_to_site = {}
    try:
        for entry in api.get_dataset_listing():
            eid = entry.get("id")
            sid = entry.get("siteId") or site_id_by_name.get(entry.get("siteName") or "")
            if eid and sid:
                dataset_to_site[eid] = sid
    except Exception:
        pass

    # Group projects by site id, with real name + size for each dataset.
    site_datasets = {}
    try:
        for pr in api.get_projects():
            pid = pr.get("id")
            if not pid:
                continue
            sid = dataset_to_site.get(pid)
            if not sid:
                continue
            proj = {
                "id": pid,
                "name": pr.get("name") or pr.get("title") or "Untitled",
                "size": int((pr.get("statistics") or {}).get("size", 0) or 0),
            }
            site_datasets.setdefault(sid, []).append(proj)
    except Exception:
        pass

    cloud = []
    for s in sites:
        sid = s.get("siteId") or s.get("id")
        datasets = site_datasets.get(sid, [])
        pc = len(datasets)
        total_size = sum(d["size"] for d in datasets)
        # Real cloud meta — showing the true cloud count/size next to the local
        # count/size is what lets users spot content-level mismatches (same
        # code prefix, different files).
        if pc:
            meta = f"{pc} esx · {human_size(total_size)}" if total_size else f"{pc} esx"
        else:
            meta = "empty"
        cloud.append({"id": sid, "name": s["name"],
                      "code": extract_site_code(s["name"]), "meta": meta,
                      "datasets": [{"name": d["name"], "id": d["id"], "size": d["size"]} for d in datasets]})

    local = []
    for f in get_local_folders(output_dir):
        inv = folder_inventory(Path(f["path"]))
        local.append({"path": f["path"], "name": f["name"], "code": f["code"], "isDir": True,
                      "meta": f'{f["esxCount"]} esx · {human_size(f["totalSize"])}',
                      "hasSource": inv["srcCount"] > 0, "src": inv})
    return build_matches(cloud, local, not_matches_set())


def build_projects_data(api, output_dir):
    # Build dataset→site mapping via the datasetListing endpoint (single call)
    dataset_site = {}
    try:
        for entry in api.get_dataset_listing():
            eid = entry.get("id")
            sname = entry.get("siteName")
            if eid and sname:
                dataset_site[eid] = sname
    except Exception:
        pass

    cloud = []
    for pr in api.get_projects():
        name = pr.get("name") or pr.get("title") or "Untitled"
        pid = pr.get("id")
        # File size — nested under statistics.size (confirmed from API)
        size = int((pr.get("statistics") or {}).get("size", 0) or 0)
        size_str = human_size(size) if size else ""
        # Modification time — ISO string on one of several keys.
        mtime = _parse_cloud_mtime(pr)
        # Owner / last editor — nested under history.createdBy / history.modifiedBy.
        # This is the same "Owner" surfaced in the Ekahau Cloud Share dialog.
        history = pr.get("history") or {}
        owner = (history.get("createdBy") or "").strip().lower()
        modified_by = (history.get("modifiedBy") or "").strip().lower()
        # Site name from our mapping
        site_name = dataset_site.get(pid, "")
        # Build meta to match local side: "size · site"
        parts = [p for p in [size_str, site_name] if p]
        meta = " · ".join(parts) if parts else "project"
        cloud.append({"id": pid, "name": name,
                      "code": extract_site_code(name), "meta": meta,
                      "size": size, "mtime": mtime,
                      "owner": owner, "modifiedBy": modified_by,
                      "hasSite": bool(site_name)})
    local = [{"path": f["path"], "name": f["name"], "code": extract_site_code(f["name"]),
              "isDir": False, "folder": f["folder"],
              "size": int(f.get("size") or 0), "mtime": int(f.get("mtime") or 0),
              "owner": f.get("owner") or "",
              "meta": f'{human_size(f["size"])} · {f["folder"]}'}
             for f in get_local_esx_files(output_dir)]
    return build_matches(cloud, local, not_matches_set())


# ── Duplicate detection ────────────────────────────────────────────────
def _dup_key(name):
    """Normalize a project/file name so near-duplicates cluster together.
    Strips .esx, lowercases, replaces punctuation with spaces, collapses runs.
    Deterministic — no fuzzy matching. Used only to group like-named files."""
    stem = (name or "").lower()
    if stem.endswith(".esx"):
        stem = stem[:-4]
    stem = re.sub(r"[-_.,;:!?/\\()\[\]{}]+", " ", stem)
    return re.sub(r"\s+", " ", stem).strip()


def _parse_cloud_mtime(pr):
    """Best-effort extraction of a modification timestamp from a project dict.
    Returns unix seconds (int) or 0. Ekahau uses ISO strings on various keys."""
    from datetime import datetime
    for key in ("modifiedAt", "updatedAt", "lastModifiedAt", "modified", "createdAt"):
        v = pr.get(key)
        if not v:
            continue
        try:
            # Handle trailing Z (UTC) and fractional seconds.
            s = str(v).replace("Z", "+00:00")
            return int(datetime.fromisoformat(s).timestamp())
        except (ValueError, TypeError):
            continue
    return 0


def build_duplicates_data(api, output_dir):
    """Cluster cloud projects + local .esx files by normalized name.
    Only clusters with 2+ items are returned. Each item carries side, size,
    mtime, location, and a `matched` flag (true if it's currently paired in
    the Sites/Projects view — helps identify the "canonical" copy)."""
    # Cloud side — join projects with dataset listing for site name context.
    dataset_site = {}
    try:
        for entry in api.get_dataset_listing():
            eid = entry.get("id")
            sname = entry.get("siteName")
            if eid and sname:
                dataset_site[eid] = sname
    except Exception:
        pass

    cloud_items = []
    try:
        for pr in api.get_projects():
            pid = pr.get("id")
            if not pid:
                continue
            name = pr.get("name") or pr.get("title") or "Untitled"
            size = int((pr.get("statistics") or {}).get("size", 0) or 0)
            cloud_items.append({
                "side": "cloud",
                "id": pid,
                "name": name,
                "size": size,
                "mtime": _parse_cloud_mtime(pr),
                "location": dataset_site.get(pid, ""),
                "hasSite": bool(dataset_site.get(pid)),
            })
    except Exception:
        pass

    # Local side.
    local_items = []
    for f in get_local_esx_files(output_dir):
        local_items.append({
            "side": "local",
            "path": f["path"],
            "name": f["name"],
            "size": int(f.get("size", 0) or 0),
            "mtime": int(f.get("mtime", 0) or 0),
            "location": f["folder"],
        })

    # Determine which items are currently "matched" in the Projects view so we
    # can flag them. Uses the same matcher the main UI uses.
    matched_cloud_ids = set()
    matched_local_paths = set()
    try:
        cloud_for_match = [{"id": c["id"], "name": c["name"],
                            "code": extract_site_code(c["name"]),
                            "hasSite": c["hasSite"]}
                           for c in cloud_items]
        local_for_match = [{"path": l["path"], "name": l["name"],
                            "code": extract_site_code(l["name"]),
                            "isDir": False, "folder": l["location"]}
                           for l in local_items]
        m = build_matches(cloud_for_match, local_for_match)
        for entry in m["matched"]:
            if entry["cloud"].get("id"):
                matched_cloud_ids.add(entry["cloud"]["id"])
            if entry["local"].get("path"):
                matched_local_paths.add(entry["local"]["path"])
    except Exception:
        pass

    for c in cloud_items:
        c["matched"] = c["id"] in matched_cloud_ids
    for l in local_items:
        l["matched"] = l["path"] in matched_local_paths

    # Group into clusters by normalized key.
    clusters_by_key = {}
    for item in cloud_items + local_items:
        key = _dup_key(item["name"])
        if not key:
            continue
        clusters_by_key.setdefault(key, []).append(item)

    clusters = []
    for key, items in clusters_by_key.items():
        if len(items) < 2:
            continue
        cloud_count = sum(1 for i in items if i["side"] == "cloud")
        local_count = sum(1 for i in items if i["side"] == "local")
        # A 1-cloud + 1-local cluster where BOTH sides are matched is just a
        # normal pair (already visible on Projects tab). Hide it so the
        # Duplicates view only surfaces clusters with actual duplicates —
        # unmatched extras or multiple copies on the same side.
        if cloud_count == 1 and local_count == 1 and all(i.get("matched") for i in items):
            continue
        shape = "mixed" if cloud_count and local_count else (
            "cloud-only" if cloud_count else "local-only")
        newest = max(items, key=lambda i: i["mtime"])
        largest = max(items, key=lambda i: i["size"])
        # Stable id per item for UI cross-reference
        def _iid(i):
            return i.get("id") or i.get("path") or ""
        clusters.append({
            "key": key,
            "displayName": items[0]["name"],  # sample; UI shows all names
            "items": items,
            "sides": {"cloud": cloud_count, "local": local_count},
            "shape": shape,
            "newestId": _iid(newest),
            "largestId": _iid(largest),
        })

    # Sort clusters: mixed first (most actionable), then by size desc.
    shape_rank = {"mixed": 0, "local-only": 1, "cloud-only": 2}
    clusters.sort(key=lambda c: (shape_rank.get(c["shape"], 9),
                                  -sum(i["size"] for i in c["items"])))

    return {
        "clusters": clusters,
        "summary": {
            "total": len(clusters),
            "mixed": sum(1 for c in clusters if c["shape"] == "mixed"),
            "localOnly": sum(1 for c in clusters if c["shape"] == "local-only"),
            "cloudOnly": sum(1 for c in clusters if c["shape"] == "cloud-only"),
        },
    }


# ── folder picker (native dialog via a short-lived subprocess) ─────────
def pick_folder_dialog(initial=""):
    code = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        f"p = filedialog.askdirectory(initialdir={initial!r})\n"
        "print(p or '')\n"
    )
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, timeout=180, **kwargs)
        return out.stdout.strip()
    except Exception:
        return ""


# ── CloudManager: the operations the server exposes ───────────────────
class CloudManager:
    def __init__(self):
        self.api = None
        self.config = load_config()

    def _ensure(self):
        if self.api:
            return True
        self.api = try_saved_cookies() or try_browser_cookies()
        return self.api is not None

    def status(self):
        connected = self._ensure()
        return {"connected": connected,
                "email": self.api.user_email if self.api else "",
                "outputDir": self.config.get("output_dir", "")}

    def open_login(self):
        try:
            if sys.platform == "win32":
                os.startfile(EKAHAU_URL)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", EKAHAU_URL])
            else:
                subprocess.Popen(["xdg-open", EKAHAU_URL])
        except Exception as e:
            return {"error": str(e)}
        return {"ok": True}

    def reveal_in_explorer(self, path):
        try:
            od = self.config.get("output_dir", "")
            if od:
                _assert_inside(path, od)
            p = Path(path)
            if not p.exists():
                return {"error": "Path not found"}
            if sys.platform == "win32":
                if p.is_dir():
                    os.startfile(str(p))
                else:
                    subprocess.Popen(["explorer", "/select,", str(p)])
            elif sys.platform == "darwin":
                if p.is_dir():
                    subprocess.Popen(["open", str(p)])
                else:
                    subprocess.Popen(["open", "-R", str(p)])
            else:
                target = str(p) if p.is_dir() else str(p.parent)
                subprocess.Popen(["xdg-open", target])
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def get_data(self, kind):
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            od = self.config.get("output_dir", "")
            data = build_projects_data(self.api, od) if kind == "projects" else build_sites_data(self.api, od)
            # Stamp the current user's email so the frontend can split
            # "mine" from "someone else's" cloud projects.
            data["currentUser"] = (self.api.user_email or "").strip().lower()
            return data
        except Exception as e:
            return {"error": str(e)}

    def get_duplicates(self):
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            od = self.config.get("output_dir", "")
            return build_duplicates_data(self.api, od)
        except Exception as e:
            return {"error": str(e)}

    def rename_cloud(self, kind, cloud_id, name):
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            return self.api.rename_project(cloud_id, name) if kind == "projects" else self.api.rename_site(cloud_id, name)
        except Exception as e:
            return {"error": str(e)}

    def delete_cloud(self, kind, cloud_id):
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            return self.api.delete_project(cloud_id) if kind == "projects" else self.api.delete_sites([cloud_id])
        except Exception as e:
            return {"error": str(e)}

    def create_site(self, name):
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            return self.api.create_site(name)
        except Exception as e:
            return {"error": str(e)}

    def assign_to_site(self, site_id, dataset_id):
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            return self.api.assign_to_site(site_id, dataset_id)
        except Exception as e:
            return {"error": str(e)}

    def rename_local(self, path, new_name):
        try:
            od = self.config.get("output_dir", "")
            if od:
                _assert_inside(path, od)
            old = Path(path)
            if old.is_dir():
                new = old.parent / new_name
            else:
                nn = new_name if new_name.lower().endswith(".esx") else new_name + ".esx"
                new = old.parent / nn
            same = new.exists() and old.exists() and (
                str(old) == str(new) or os.path.samefile(str(old), str(new)))
            if new.exists() and not same:
                return {"error": "A file/folder with that name already exists"}
            old.rename(new)
            return {"ok": True, "newPath": str(new)}
        except Exception as e:
            return {"error": str(e)}

    def delete_local(self, path):
        try:
            od = self.config.get("output_dir", "")
            if od:
                _assert_inside(path, od)
            p = Path(path)
            if p.is_dir():
                shutil.rmtree(p, onerror=_force_remove)
            else:
                try:
                    p.unlink()
                except PermissionError:
                    os.chmod(p, stat.S_IWRITE)
                    p.unlink()
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def upload_project(self, esx_path, site_id=None):
        """Upload .esx to cloud. If site_id given, auto-assign to that site."""
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            # Snapshot project IDs before upload so we can find the new one
            before_ids = {p["id"] for p in self.api.get_projects()} if site_id else set()

            result = self.api.upload_project(esx_path)
            if isinstance(result, dict) and result.get("error"):
                return result

            # Auto-assign to site if requested
            if site_id:
                # Brief pause — cloud may take a moment to register the new project
                time.sleep(1.5)
                after = self.api.get_projects()
                new_ids = [p["id"] for p in after if p["id"] not in before_ids]
                if new_ids:
                    assign_r = self.api.assign_to_site(site_id, new_ids[0])
                    return {"ok": True, "assigned": True, "siteId": site_id,
                            "datasetId": new_ids[0]}
                else:
                    return {"ok": True, "uploaded": True,
                            "warning": "Uploaded but could not find new project to assign"}

            return {"ok": True, "uploaded": True}
        except Exception as e:
            return {"error": str(e)}

    def create_local_folder(self, name):
        base = self.config.get("output_dir", "")
        if not base:
            return {"error": "No local folder is set — pick one first"}
        try:
            safe = re.sub(r'[<>:"/\\|?*]', '-', name).strip().rstrip('.')
            if '..' in safe or '/' in safe or '\\' in safe:
                return {"error": "Invalid folder name"}
            if not safe:
                return {"error": "Invalid folder name"}
            target = Path(base) / safe
            if target.exists():
                return {"error": "A folder with that name already exists"}
            target.mkdir(parents=True)
            return {"ok": True, "path": str(target)}
        except Exception as e:
            return {"error": str(e)}

    def merge_preview(self, src_path, dst_path):
        """Dry run: what would move from src into dst, and which files collide."""
        try:
            od = self.config.get("output_dir", "")
            if od:
                _assert_inside(src_path, od)
                _assert_inside(dst_path, od)
            src, dst = Path(src_path), Path(dst_path)
            if not src.is_dir():
                return {"error": "Source folder not found"}
            if not dst.is_dir():
                return {"error": "Destination folder not found"}
            if src.resolve() == dst.resolve():
                return {"error": "Source and destination are the same folder"}
            try:
                dst.resolve().relative_to(src.resolve())
                return {"error": "Destination is inside the source folder"}
            except ValueError:
                pass
            files, nconf = [], 0
            for f in _walk_files(src):
                rel = f.relative_to(src)
                st = f.stat()
                rec = {"rel": str(rel), "srcSizeH": human_size(st.st_size),
                       "srcMtime": int(st.st_mtime)}
                target = dst / rel
                if target.exists():
                    ts = target.stat()
                    rec.update(conflict=True, dstSizeH=human_size(ts.st_size),
                               dstMtime=int(ts.st_mtime),
                               newer=("src" if st.st_mtime > ts.st_mtime + 1
                                      else "dst" if ts.st_mtime > st.st_mtime + 1 else "same"))
                    nconf += 1
                else:
                    rec["conflict"] = False
                files.append(rec)
            return {"srcName": src.name, "dstName": dst.name,
                    "nClean": len(files) - nconf, "nConflicts": nconf, "files": files}
        except Exception as e:
            return {"error": str(e)}

    def merge_execute(self, src_path, dst_path, ops):
        """Apply per-file operations. ops: [{rel, action}] where action is
        move | overwrite | keepboth | skip. Never deletes the source folder."""
        try:
            od = self.config.get("output_dir", "")
            if od:
                _assert_inside(src_path, od)
                _assert_inside(dst_path, od)
            src, dst = Path(src_path), Path(dst_path)
            if not src.is_dir() or not dst.is_dir():
                return {"error": "Folder not found"}
            if src.resolve() == dst.resolve():
                return {"error": "Source and destination are the same folder"}
            moved = overwritten = keptboth = skipped = 0
            errors = []
            for op in ops or []:
                rel = op.get("rel")
                action = op.get("action", "move")
                if not rel:
                    continue
                if action == "skip":
                    skipped += 1
                    continue
                s = src / rel
                if not s.is_file():
                    continue
                d = dst / rel
                try:
                    d.parent.mkdir(parents=True, exist_ok=True)
                    if not d.exists():
                        shutil.move(str(s), str(d)); moved += 1
                    elif action == "overwrite":
                        d.unlink(); shutil.move(str(s), str(d)); overwritten += 1
                    elif action == "keepboth":
                        # Keep both, but the NEWER file takes the clean name and
                        # the OLDER one is archived with its own date stamp.
                        s_m, d_m = s.stat().st_mtime, d.stat().st_mtime
                        if s_m >= d_m:
                            # incoming is newer (or same): archive the existing, move src in
                            d.rename(_timestamped_path(d, d_m))
                            shutil.move(str(s), str(d))
                        else:
                            # existing is newer: bring the older incoming in under a dated name
                            shutil.move(str(s), str(_timestamped_path(d, s_m)))
                        keptboth += 1
                    else:
                        skipped += 1
                except Exception as e:
                    errors.append(f"{rel}: {e}")
            try:
                src_empty = not any(True for _ in _walk_files(src))
            except OSError:
                src_empty = False   # can't tell (locked) — don't offer to delete
            return {"ok": True, "moved": moved, "overwritten": overwritten,
                    "keptboth": keptboth, "skipped": skipped, "errors": errors[:20],
                    "srcEmpty": src_empty, "srcPath": str(src), "srcName": src.name}
        except Exception as e:
            return {"error": str(e)}

    def pick_folder(self):
        path = pick_folder_dialog(self.config.get("output_dir", ""))
        if path:
            self.config["output_dir"] = path
            save_config(self.config)
            return {"path": path}
        return {"path": None}

    def mark_not_match(self, cloud_id, local_path, cloud_name="", local_name=""):
        if not cloud_id or not local_path:
            return {"error": "cloudId and localPath are required"}
        pairs = load_not_matches()
        target = _nm_pair_key(cloud_id, local_path)
        if any(_nm_pair_key(p["cloudId"], p["localPath"]) == target for p in pairs):
            return {"ok": True, "already": True}
        pairs.append({
            "cloudId": cloud_id, "localPath": local_path,
            "cloudName": cloud_name, "localName": local_name,
            "addedAt": int(time.time()),
        })
        save_not_matches(pairs)
        return {"ok": True, "count": len(pairs)}

    def unmark_not_match(self, cloud_id, local_path):
        if not cloud_id or not local_path:
            return {"error": "cloudId and localPath are required"}
        pairs = load_not_matches()
        target = _nm_pair_key(cloud_id, local_path)
        kept = [p for p in pairs if _nm_pair_key(p["cloudId"], p["localPath"]) != target]
        save_not_matches(kept)
        return {"ok": True, "count": len(kept), "removed": len(pairs) - len(kept)}

    def list_not_matches(self):
        return {"ok": True, "pairs": load_not_matches(),
                "file": str(NOT_MATCH_FILE)}
