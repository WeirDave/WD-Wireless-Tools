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
    with open(COOKIE_FILE, "w") as f:
        json.dump({"cookies": cookies, "csrfToken": csrf}, f)


def load_cookies_from_disk():
    if COOKIE_FILE.exists():
        try:
            with open(COOKIE_FILE) as f:
                data = json.load(f)
            return data.get("cookies", []), data.get("csrfToken", "")
        except Exception:
            pass
    return None, None


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
        r.raise_for_status()
        return r

    def get_sites(self):     return self.get("/site-management-api/v1/sites").json()
    def get_projects(self):  return self.get(API_BASE).json()
    def get_dataset_listing(self):  return self.get("/site-management-api/v1/datasetListing").json()

    def rename_site(self, sid, name):
        return self._write("PUT", f"/site-management-api/v1/sites/{sid}", {"name": name}).json()

    def create_site(self, name):
        return self._write("POST", "/site-management-api/v1/sites", {"name": name}).json()

    def delete_sites(self, ids):
        return self._write("DELETE", "/site-management-api/v1/sites", ids).json()

    def rename_project(self, pid, name):
        proj = self.get(f"{API_BASE}/{pid}").json()
        proj["name"] = name
        proj["title"] = name
        proj["status"] = "UPDATED"
        return self._write("PUT", f"{API_BASE}/{pid}/batch/update", {"project": proj}).json()

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


def discriminators_conflict(a, b):
    ba, bb = _building_token(a), _building_token(b)
    if ba and bb and ba != bb:
        return True
    sa, sb = _street_number(a), _street_number(b)
    if sa and sb and sa != sb:
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
                out.append({"name": f.stem, "folder": d.name,
                            "size": _esx_size(f), "path": str(f)})
        except OSError:
            continue
    out.sort(key=lambda x: x["name"].lower())
    return out


def build_matches(cloud_items, local_items):
    # Three global passes so stronger evidence always wins: every cloud project
    # gets first crack at an EXACT-name local file, then a site-CODE match, then
    # a fuzzy match on the leftovers. This prevents an early cloud project from
    # greedily "stealing" a local .esx (via a weak fuzzy hit) that another cloud
    # project matches exactly or by code — the old single-pass bug that could
    # push a code-matched project (e.g. BALB01) into "cloud only".
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
                    if cn == l["name"].strip()), None)
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
                if discriminators_conflict(c["name"], l["name"]):
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
            if discriminators_conflict(c["name"], l["name"]):
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
    cloud = []
    for s in api.get_sites():
        pc = len(s.get("datasets", []))
        cloud.append({"id": s.get("siteId") or s.get("id"), "name": s["name"],
                      "code": extract_site_code(s["name"]), "meta": f"{pc} proj" if pc else ""})
    local = []
    for f in get_local_folders(output_dir):
        inv = folder_inventory(Path(f["path"]))
        local.append({"path": f["path"], "name": f["name"], "code": f["code"], "isDir": True,
                      "meta": f'{f["esxCount"]} esx · {human_size(f["totalSize"])}',
                      "hasSource": inv["srcCount"] > 0, "src": inv})
    result = build_matches(cloud, local)
    for entry in result["matched"]:
        entry["cloud"]["meta"] = entry["local"].get("meta", "")
    return result


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
        size = (pr.get("statistics") or {}).get("size", 0)
        size_str = human_size(size) if size else ""
        # Site name from our mapping
        site_name = dataset_site.get(pid, "")
        # Build meta to match local side: "size · site"
        parts = [p for p in [size_str, site_name] if p]
        meta = " · ".join(parts) if parts else "project"
        cloud.append({"id": pid, "name": name,
                      "code": extract_site_code(name), "meta": meta,
                      "hasSite": bool(site_name)})
    local = [{"path": f["path"], "name": f["name"], "code": extract_site_code(f["name"]),
              "isDir": False, "folder": f["folder"],
              "meta": f'{human_size(f["size"])} · {f["folder"]}'}
             for f in get_local_esx_files(output_dir)]
    return build_matches(cloud, local)


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
        flags = 0x08000000 if sys.platform == "win32" else 0
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, timeout=180, creationflags=flags)
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

    def get_data(self, kind):
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            od = self.config.get("output_dir", "")
            return build_projects_data(self.api, od) if kind == "projects" else build_sites_data(self.api, od)
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
                new_ids 