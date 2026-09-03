"""
WD Cloud Manager — backend logic for the browser-based suite.

This is the pywebview app.py's proven logic, minus all the pywebview/window
machinery. It exposes a CloudManager class whose methods the Flask server
turns into JSON HTTP endpoints. Auth still uses browser_cookie3 server-side.
"""
import base64
import binascii
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

from tools.settings import get_destinations as _get_suite_destinations
from tools.settings import load_settings as _load_suite_settings
from tools.settings import update_settings as _update_suite_settings

try:
    import browser_cookie3
except ImportError:
    browser_cookie3 = None

try:
    import keyring
except ImportError:
    keyring = None

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    Fernet = None
    InvalidToken = Exception

EKAHAU_URL = "https://www.ekahau.cloud"
API_BASE = "/projectapi/v1/projects"
CONFIG_DIR = Path.home() / ".wd_wireless_tools"
CONFIG_FILE = CONFIG_DIR / "config.json"
COOKIE_FILE = CONFIG_DIR / "cookies.json"
ENCRYPTED_COOKIE_FILE = CONFIG_DIR / "cookies.enc"
KEYRING_SERVICE = "WD Wireless Tools Cloud Manager"
KEYRING_USERNAME = "session-encryption-key"
NOT_MATCH_FILE = CONFIG_DIR / "not_matches.json"
MANUAL_MATCH_FILE = CONFIG_DIR / "manual_matches.json"


def _assert_inside(path, root):
    """Raise ValueError if *path* resolves outside *root*."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        raise ValueError(f"Path is outside the allowed directory: {path}")


def load_config():
    unified = CONFIG_DIR / "settings.json"
    if unified.exists():
        s = _load_suite_settings(_path=unified)
        return {"output_dir": s.get("global", {}).get("output_dir", "")}
    cfg = {"output_dir": ""}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    unified = CONFIG_DIR / "settings.json"
    if unified.exists():
        _update_suite_settings({"global": {"output_dir": cfg.get("output_dir", "")}},
                               _path=unified)
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def _cookie_payload(raw):
    """Validate and unpack a serialized Cloud session without exposing it."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    cookies = data.get("cookies") if isinstance(data, dict) else None
    csrf = data.get("csrfToken") if isinstance(data, dict) else None
    if not isinstance(cookies, list) or not isinstance(csrf, str):
        return None
    return cookies, csrf


def _keyring_key(create=False):
    """Return the per-user encryption key, optionally creating it.

    Only this small random key goes into Credential Manager / Keychain. The
    cookie jar itself can grow without running into a system-vault size limit.
    Any backend or permission failure is treated as unavailable secure storage;
    callers must never compensate by writing a new plaintext credential file.
    """
    if keyring is None or Fernet is None:
        return None
    try:
        value = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if value:
            try:

                Fernet(value.encode("ascii"))
                return value.encode("ascii")
            except (UnicodeError, ValueError):


                if not create:
                    return None
        if not create:
            return None
        value = Fernet.generate_key().decode("ascii")
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, value)


        if keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) != value:
            return None
        return value.encode("ascii")
    except Exception:
        return None


def _atomic_private_write(path, data):
    """Atomically write bytes with owner-only POSIX permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass


def _decrypt_cookie_data(key, token):
    """Decrypt only a canonical Fernet token.

    Python 3.10's Base64 decoder accepts trailing characters that newer
    Python versions reject. Fernet still authenticates the decoded payload,
    but accepting a byte-modified cache on one supported runtime and rejecting
    it on another is surprising. A strict decode + round trip makes tamper
    behavior identical across every supported Python version.
    """
    try:
        decoded = base64.b64decode(token, altchars=b"-_", validate=True)
    except (binascii.Error, TypeError, ValueError) as exc:
        raise InvalidToken from exc
    if base64.urlsafe_b64encode(decoded) != token:
        raise InvalidToken
    return Fernet(key).decrypt(token)


def save_cookies_to_disk(cookies, csrf):
    """Encrypt and persist a Cloud session; return whether it was saved.

    Failure intentionally leaves the session memory-only. In particular, this
    function never recreates the legacy plaintext ``cookies.json`` file.
    """
    key = _keyring_key(create=True)
    if key is None:
        return False
    try:
        raw = json.dumps({"cookies": cookies, "csrfToken": csrf},
                         separators=(",", ":")).encode("utf-8")
        encrypted = Fernet(key).encrypt(raw)
        _atomic_private_write(ENCRYPTED_COOKIE_FILE, encrypted)


        verified = _decrypt_cookie_data(key, ENCRYPTED_COOKIE_FILE.read_bytes())
        return _cookie_payload(verified.decode("utf-8")) == (cookies, csrf)
    except Exception:
        return False


def _load_encrypted_cookies():
    if not ENCRYPTED_COOKIE_FILE.exists():
        return None
    key = _keyring_key(create=False)
    if key is None:
        return None
    try:
        raw = _decrypt_cookie_data(key, ENCRYPTED_COOKIE_FILE.read_bytes())
        return _cookie_payload(raw.decode("utf-8"))
    except (OSError, UnicodeError, InvalidToken, ValueError):
        return None


def load_cookies_from_disk():
    encrypted = _load_encrypted_cookies()
    if encrypted is not None:


        if COOKIE_FILE.exists():
            try:
                legacy = _cookie_payload(COOKIE_FILE.read_text(encoding="utf-8"))
                if legacy == encrypted:
                    COOKIE_FILE.unlink()
            except Exception:
                pass
        return encrypted


    if COOKIE_FILE.exists():
        try:
            payload = _cookie_payload(COOKIE_FILE.read_text(encoding="utf-8"))
            if payload is not None:
                if save_cookies_to_disk(*payload):
                    COOKIE_FILE.unlink()
                return payload
        except Exception:
            pass
    return None, None


def clear_saved_cookies():
    """Forget both current and legacy saved Cloud credentials."""
    errors = []
    for path in (ENCRYPTED_COOKIE_FILE, COOKIE_FILE):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(str(exc))
    if keyring is not None:
        try:
            if keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) is not None:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception as exc:
            errors.append(str(exc))
    return not errors


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


def load_manual_matches():
    if MANUAL_MATCH_FILE.exists():
        try:
            with open(MANUAL_MATCH_FILE) as f:
                data = json.load(f) or {}
            pairs = data.get("pairs", []) or []
            return [p for p in pairs if p.get("cloudId") and p.get("localPath")]
        except Exception:
            pass
    return []


def save_manual_matches(pairs):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANUAL_MATCH_FILE, "w") as f:
        json.dump({"pairs": pairs}, f, indent=2)


def manual_matches_map():
    """cloud_id → normalized local_path. Reverse-lookup by local_path is also
    needed (to skip that local file when other passes consider it), so we
    return the raw list too."""
    pairs = load_manual_matches()
    by_cloud = {p["cloudId"]: (p["localPath"] or "").replace(chr(92), "/").lower()
                for p in pairs}
    return by_cloud, pairs


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

        return r.json() if (r.text or "").strip() else {"ok": True}

    def get_dataset(self, dataset_id):
        return self.get(f"/site-management-api/v1/datasets/{dataset_id}").json()

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


    def list_project_shares(self, project_id):
        """Returns {project_id: [user_dict, ...]}. Each user has username
        (email), role, firstName, lastName, startTime, optional groupId."""
        r = self._write("POST", "/shareapi/v1/projects/users/list", [project_id])
        return r.json() if (r.text or "").strip() else {}

    def add_project_share(self, project_id, email, role="READ_USER"):
        """Add a user to a project's share list. Role choices in the
        Ekahau UI: READ_USER, WRITE_USER, WRITE_SHARE_USER. External emails
        will land as READ_USER regardless of what's requested."""
        r = self._write("POST", "/shareapi/v1/projects/users", {
            "projectIds": [project_id],
            "emailAddresses": [email],
            "userGroupIds": [],
            "role": role,
        })
        return r.json() if (r.text or "").strip() else [{"projectId": project_id, "success": True}]

    def remove_project_share(self, project_id, email):
        """Remove a single user from a project's share list. Owner cannot
        be removed via this endpoint (would 4xx)."""
        r = self._write("POST", "/shareapi/v1/projects/users/delete", {
            "projectIds": [project_id],
            "email": email,
        })
        return r.json() if (r.text or "").strip() else [{"projectId": project_id, "success": True}]


    def transfer_ownership(self, project_id, current_owner_email, new_owner_email):
        body = {
            "projectOwnershipTransferDetails": [{
                "projectIds": [project_id],
                "currentOwnerEmailAddress": current_owner_email,
            }],
            "newOwnerEmailAddress": new_owner_email,
        }
        r = self._write("POST", "/shareapi/v1/projects/users/transfer-ownership", body)
        try:
            data = r.json() if (r.text or "").strip() else {}
        except Exception:
            data = {}
        return {"status": r.status_code, "result": data}


    def get_user_group(self, group_name="My Sharing Group"):
        """GET /userapi/v1/userGroups?groupName=<name>. Response is an array
        of group objects — usually just one for the standard 'My Sharing
        Group' every user has. Returns the FIRST match or None."""
        from urllib.parse import quote
        r = self.get(f"/userapi/v1/userGroups?groupName={quote(group_name)}")
        try:
            data = r.json() if (r.text or "").strip() else []
        except Exception:
            data = []
        if isinstance(data, list) and data:
            return data[0]
        return None

    def update_user_group(self, group_id, group_name, added=None, deleted=None, current_members=None):
        """PUT /userapi/v1/userGroups. Body shape captured from the manage
        page: addedMemberList for adds, deletedMemberList + full current
        members for removes. We normalize the two forms so callers just pass
        `added=[emails]` or `deleted=[emails]`.

        The `members` field in the payload is echoed back to Ekahau's server
        so it knows the pre-update state. Empty for pure adds, full for
        deletes, per the captured pattern."""
        body = {
            "addedMemberList": list(added or []),
            "createdBy": "",
            "deletedMemberList": list(deleted or []),
            "groupId": group_id,
            "groupName": group_name,
            "members": list(current_members or []),
        }
        r = self._write("PUT", "/userapi/v1/userGroups", body)

        return {"ok": True, "status": r.status_code}

    def bulk_add_shares(self, project_ids, emails, role="READ_USER"):
        """Add M emails to N projects in a single request. Ekahau's endpoint
        takes both projectIds AND emailAddresses as arrays — every project
        gets every email at the specified role. External emails silently
        downgrade to READ_USER (same as the single-project version)."""
        r = self._write("POST", "/shareapi/v1/projects/users", {
            "projectIds": list(project_ids),
            "emailAddresses": list(emails),
            "userGroupIds": [],
            "role": role,
        })
        try:
            return r.json() if (r.text or "").strip() else []
        except Exception:
            return []

    def toggle_project_group_share(self, project_id, group_id, group_name, role, enable):
        """Add or remove the entire "My Sharing Group" from a project's shares.
        toggleGroupShare=True adds the group + gives every group member the
        specified role; False removes the group.

        We captured this endpoint from Ekahau's web UI's "Share with My Group"
        toggle. The role sticks to every group member; individual per-user
        role changes for group members would require removing them from the
        group entirely (a manage-page action, not per-project)."""
        r = self._write("PUT", "/shareapi/v1/projects/users/toggle-userGroup", {
            "projectIds": [project_id],
            "projectUserGroupDto": {
                "userGroupId": group_id,
                "userGroupName": group_name,
                "role": role,
                "toggleGroupShare": bool(enable),
            },
        })
        return r.json() if (r.text or "").strip() else [{"projectId": project_id, "success": True}]

    def download_project(self, project_id, progress_cb=None):
        """Download a cloud project as .esx bytes.

        Ekahau's web UI builds the .esx client-side in a worker; there's no
        server endpoint that hands out a finished file. We reproduce that
        flow: batch → per-image S3 fetch → ZIP assembly. Verified byte-equal
        to a reference .esx from their UI.

        progress_cb(stage=..., current=..., total=..., message=...) is called
        at stage boundaries. Downloads spend most of their time in the image
        loop, so we emit per-image progress there with a real N-of-N total.

        Returns {"esx": bytes, "name": str} or {"error": str}.
        """
        import io as _io
        import zipfile as _zip

        if progress_cb:
            progress_cb(stage="batch", current=5, total=100,
                        message="Fetching project data from Ekahau…")
        try:
            batch = self.get(f"{API_BASE}/{project_id}/batch").json()
        except Exception as e:
            return {"error": f"Could not fetch project data: {e}"}

        proj_name = ((batch.get("project") or {}).get("name")
                     or (batch.get("project") or {}).get("title")
                     or f"project-{project_id}")

        images = batch.get("images") or []
        n_images = sum(1 for img in images if img.get("id"))


        base_pct = 10

        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w", _zip.ZIP_DEFLATED) as zf:
            zf.writestr("version", "2.0")
            for key, value in batch.items():
                zf.writestr(f"{key}.json", json.dumps({key: value}, ensure_ascii=False))
            if progress_cb:
                progress_cb(stage="images", current=base_pct, total=100,
                            message=f"Downloading {n_images} floor plan image{'s' if n_images != 1 else ''}…")
            done_images = 0
            for img in images:
                image_id = img.get("id")
                if not image_id:
                    continue
                try:
                    r = self.http.get(
                        f"{EKAHAU_URL}{API_BASE}/{project_id}/imageFiles/{image_id}?redirect=true",
                        allow_redirects=True, timeout=180,
                    )
                    r.raise_for_status()
                    zf.writestr(f"image-{image_id}", r.content)
                except Exception as e:
                    return {"error": f"Failed fetching image {image_id}: {e}"}
                done_images += 1
                if progress_cb and n_images > 0:
                    pct = base_pct + int(85 * done_images / n_images)
                    progress_cb(current=pct,
                                message=f"Downloading floor plan {done_images} of {n_images}…")

            if progress_cb:
                progress_cb(stage="assemble", current=95, total=100,
                            message="Assembling .esx…")

        return {"esx": buf.getvalue(), "name": proj_name}

    def upload_project(self, esx_path, progress_cb=None):
        """Upload a local .esx file to Ekahau Cloud (3-step presigned flow).

        1. POST /esxfileapi/v1/projects/upload/initiate  →  presigned S3 URL + id
        2. PUT  the raw bytes to S3
        3. POST /esxfileapi/v1/projects/upload/commit?fileUploadId=…

        progress_cb(stage=..., current=..., total=..., message=...) is called
        at stage boundaries. The S3 PUT is a single blocking call inside
        requests, so we can only report before/after — not per-byte.
        """
        p = Path(esx_path)
        if not p.is_file():
            return {"error": f"File not found: {esx_path}"}
        file_name = p.name
        file_size = p.stat().st_size


        if progress_cb:
            progress_cb(stage="initiate", current=5, total=100,
                        message="Requesting upload slot from Ekahau…")
        init_r = self._write("POST", "/esxfileapi/v1/projects/upload/initiate",
                             {"fileName": file_name, "fileExtension": "esx"})
        init_data = init_r.json()


        upload_url = (init_data.get("url")
                      or init_data.get("uploadUrl")
                      or init_data.get("presignedUrl"))
        file_upload_id = (init_data.get("fileUploadId")
                          or init_data.get("id")
                          or init_data.get("uploadId"))

        if not upload_url or not file_upload_id:

            return {"error": "Could not parse initiate response — check raw fields",
                    "raw_initiate_response": init_data}


        if progress_cb:
            size_mb = file_size / (1024 * 1024)
            progress_cb(stage="upload", current=15, total=100,
                        message=f"Uploading {size_mb:.1f} MB to Ekahau…")
        with open(p, "rb") as f:
            file_bytes = f.read()

        s3_r = self.http.put(upload_url, data=file_bytes,
                             headers={"Content-Type": "application/esx"},
                             timeout=max(300, file_size // 50000))
        s3_r.raise_for_status()
        if progress_cb:
            progress_cb(current=85, message="Upload complete — finalizing…")


        if progress_cb:
            progress_cb(stage="commit", current=90, total=100,
                        message="Committing upload to Ekahau…")
        commit_r = self._write("POST",
                               f"/esxfileapi/v1/projects/upload/commit"
                               f"?fileUploadId={file_upload_id}", {})
        if progress_cb:
            progress_cb(stage="done", current=95, total=100,
                        message="Waiting for cloud listing to update…")

        try:
            return commit_r.json()
        except Exception:
            return {"ok": True, "status": commit_r.status_code}


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


    m = re.search(r'\b(?:bldg|bld|building)\.?\s*(\d{1,2}|[A-Za-z])(?![A-Za-z0-9])', name, re.I)
    return m.group(1).upper() if m else None


def _street_number(name):
    stripped = re.sub(r'^\s*[A-Za-z]{2,}\d+', '', name.strip())
    m = re.search(r'\b(\d{3,6})\b', stripped)
    return m.group(1) if m else None


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


def discriminators_reason(a, b):
    """Checks building/street/survey-phase discriminators for a conflict and
    returns a plain-English reason string (or None if no conflict). Fuels the
    "Held back" UI section so users see WHY a pair was auto-rejected."""
    ba, bb = _building_token(a), _building_token(b)
    if ba and bb and ba != bb:
        return f"Building numbers don't match ({ba} vs {bb})"
    sa, sb = _street_number(a), _street_number(b)
    if sa and sb and sa != sb:
        return f"Street numbers don't match ({sa} vs {sb})"
    pa, pb = _survey_phase(a), _survey_phase(b)
    if pa and pb and pa != pb:
        return f"Survey phases don't match ({pa} vs {pb})"
    return None


def human_size(b):
    if not b:
        return "0 B"
    if b < 1024:
        return f"{b} B"
    if b < 1048576:
        return f"{b / 1024:.0f} KB"
    return f"{b / 1048576:.1f} MB"


def _fmt_short_datetime(ts):
    """Compact absolute date+time for row meta:
    · same year   → 'Jul 24, 5:53 PM'
    · older year  → 'Jul 24, 2025, 5:53 PM'

    Time-of-day is included because two files with the SAME internal
    modifiedAt (down to the minute) are the same snapshot — that's a strong
    at-a-glance signal that "these two are identical copies." Windows-safe
    (no %-d / %-I format codes)."""
    if not ts:
        return ""
    from datetime import datetime as _dt
    try:
        d = _dt.fromtimestamp(int(ts))
    except (ValueError, OSError, OverflowError):
        return ""
    day = str(d.day)
    month = d.strftime("%b")

    hour12 = d.hour % 12 or 12
    time_str = f"{hour12}:{d.minute:02d} {'PM' if d.hour >= 12 else 'AM'}"
    if d.year == _dt.now().year:
        return f"{month} {day}, {time_str}"
    return f"{month} {day}, {d.year}, {time_str}"


def _row_meta(size, mtime, tail=None):
    """Build a row meta string: 'DATE [· TAIL]'. Size is deliberately EXCLUDED.

    Why no size: cloud files are stored uncompressed at rest; local .esx are
    ZIP-deflated. Same project shows up as 5-10× different in size — a signal
    that misleads far more than it informs. Size still lives on the row's
    underlying data (for folder-peek and Duplicates tab), but not in the meta
    line where users scan for "same or different?".

    If mtime is missing (very old .esx without history.modifiedAt), we fall
    back to just the tail (or empty) rather than showing 'size unknown' —
    saying nothing is honest; saying "size unknown" implies size matters."""
    parts = []
    dt = _fmt_short_datetime(mtime)
    if dt:
        parts.append(dt)
    if tail:
        parts.append(tail)
    return " · ".join(parts)


_SKIP_DIRS = {"backups", "backup", "output", "outputs", "archive", "archives", ".git"}


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
    source = plans + images + other
    allfiles = esx_files + source
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
                em = _esx_meta(f, mtime)


                effective_mtime = em["internalMtime"] or mtime
                out.append({"name": f.stem, "folder": d.name,
                            "size": _esx_size(f), "path": str(f),
                            "mtime": effective_mtime,
                            "fsMtime": mtime,
                            "owner": em["author"],
                            "projectId": em["projectId"],
                            "projectType": _esx_project_type(f, mtime)})
        except OSError:
            continue
    out.sort(key=lambda x: x["name"].lower())
    return out


_ESX_META_CACHE = {}


def _esx_meta(path, mtime):
    """One-shot read of project.json fields we care about — author, internal
    UUID, and internal modifiedAt. Returns a dict; cached by mtime so a re-saved
    .esx (mtime bump) is re-parsed automatically. Missing fields are empty
    strings / 0 rather than None so callers don't need per-field None guards.

    Why we extract these together: opening a .esx is a ZIP inflate + JSON
    parse, and we used to do it 2× per file (author, then again for other
    fields). This helper reads project.json once and pulls everything.

    Notes:
    · `projectId` — Ekahau's internal UUID for the project record. Same value
      whether the file is compressed, downloaded, renamed, or re-saved locally.
      This is the primary "same project" signal in build_matches (Pass 0).
    · `internalMtime` — Unix seconds parsed from `history.modifiedAt`. This is
      "when Ekahau last saved the project," not "when this file was last
      written to disk." Filesystem mtime resets on copy/sync/OneDrive touch;
      the internal one doesn't, so it's the truthful date to compare across
      cloud (server) and local (disk)."""
    key = str(path)
    hit = _ESX_META_CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    meta = {"author": "", "projectId": "", "internalMtime": 0}
    try:
        import zipfile
        with zipfile.ZipFile(path) as z:
            if "project.json" in z.namelist():
                with z.open("project.json") as pj:
                    data = json.load(pj)
                proj = (data or {}).get("project") or {}
                history = proj.get("history") or {}
                meta["author"] = (history.get("createdBy") or "").strip().lower()
                meta["projectId"] = (proj.get("id") or "").strip().lower()


                iso = (history.get("modifiedAt") or "").strip()
                if iso:
                    try:
                        from datetime import datetime as _dt


                        clean = iso.replace("Z", "+00:00")
                        meta["internalMtime"] = int(_dt.fromisoformat(clean).timestamp())
                    except (ValueError, TypeError):
                        pass
    except Exception:
        pass
    _ESX_META_CACHE[key] = (mtime, meta)
    return meta


def _esx_author(path, mtime):
    """Back-compat shim — old call sites still ask for just the author.
    New code should use _esx_meta and pluck the field it wants."""
    return _esx_meta(path, mtime)["author"]


_ESX_TYPE_CACHE = {}


def _esx_project_type(path, mtime):
    """Detect whether a local .esx is a Design, Measured, or Hybrid project,
    matching the labels the cloud side surfaces from Ekahau's dataset API.

    Heuristic: look at which radio-tables the file contains.
    · `simulatedRadios.json`  →  planned/simulated APs exist  → design side
    · `measuredRadios.json`   →  survey measurements exist    → measured side
    · both                    →  Hybrid
    · neither                 →  None (empty project, template, or older format
                                  we don't recognize — pill just doesn't render
                                  rather than displaying a wrong guess)

    Cached by mtime. Returns None on any read error rather than raising —
    a badge that fails to appear is a much better UX than a scan that
    breaks the whole local ledger."""
    key = str(path)
    hit = _ESX_TYPE_CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    ptype = None
    try:
        import zipfile
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
        has_measured = "measuredRadios.json" in names
        has_simulated = "simulatedRadios.json" in names
        if has_measured and has_simulated:
            ptype = "Hybrid"
        elif has_measured:
            ptype = "Measured"
        elif has_simulated:
            ptype = "Design"
    except Exception:
        ptype = None
    _ESX_TYPE_CACHE[key] = (mtime, ptype)
    return ptype


def build_matches(cloud_items, local_items, excluded=None, manual_map=None):
    """Five ordered passes, strongest-evidence-first, so no weak match can
    steal a local .esx from a stronger claimant later in the pipeline.

    Pass -1 · MANUAL   — user said "these two ARE the same." Final answer,
                         overrides every guard and every heuristic below.
    Pass  0 · ID       — same `project.json.id` UUID on both sides. Ekahau
                         stamps this at project creation and it survives every
                         edit / rename / upload / download / copy. Two files
                         with the same id ARE the same project record.
                         Overrides discriminator guards (a rename that changes
                         the building token doesn't change the id).
    Pass  1 · NAME     — exact name equality (case + whitespace normalized).
                         High confidence with no id link.
    Pass  2 · CODE     — same site code (e.g. "CLMB2") plus fuzzy name score,
                         with discriminator guard (Bldg 3 vs Bldg 5 rejected).
    Pass  3 · FUZZY    — fuzzy name overlap only, with discriminator guard.
                         The weakest auto-pass — surface confidence in the UI.

    Discriminator rejections (Passes 2 and 3) are collected into `heldBack`
    with a plain-English reason so the UI can offer "match anyway" — this
    replaces the old silent-drop behavior that had users confused about why
    obviously-related files weren't paired.
    """
    excluded = excluded or set()
    manual_map = manual_map or {}

    def _blocked(c, l):
        cid = c.get("id") or ""
        lp = l.get("path") or ""
        return _nm_pair_key(cid, lp) in excluded

    matched = []
    held_back = []
    unmatched_local = list(local_items)

    _STALE_TOLERANCE_S = 60

    def _staleness(c, l):
        cm = c.get("mtime") or 0
        lm = l.get("mtime") or 0
        if not cm or not lm:
            return None
        if cm > lm + _STALE_TOLERANCE_S:
            return "cloud_newer"
        if lm > cm + _STALE_TOLERANCE_S:
            return "local_newer"
        return None

    def _take(c, idx, mtype, score=1.0):
        l = unmatched_local.pop(idx)
        disp = score - 2.0 if mtype == "code" else score
        matched.append({"cloud": c, "local": l, "matchType": mtype,
                        "score": round(min(disp, 1.0), 2),
                        "namesDiffer": c["name"].strip() != l["name"].strip(),
                        "staleness": _staleness(c, l)})

    def _norm_path(p):
        return (p or "").replace(chr(92), "/").lower()


    pending = []
    for c in cloud_items:
        cid = c.get("id") or ""
        target_path = manual_map.get(cid)
        if target_path:
            hit = next((i for i, l in enumerate(unmatched_local)
                        if _norm_path(l.get("path")) == target_path
                        and not _blocked(c, l)), None)
            if hit is not None:
                _take(c, hit, "manual")
                continue
        pending.append(c)


    still_after_id = []
    for c in pending:
        cid = (c.get("id") or "").strip().lower()
        if cid:
            hit = next((i for i, l in enumerate(unmatched_local)
                        if (l.get("projectId") or "").strip().lower() == cid
                        and not _blocked(c, l)), None)
            if hit is not None:
                _take(c, hit, "id")
                continue
        still_after_id.append(c)


    pending = []
    for c in still_after_id:
        cn = c["name"].strip()
        hit = next((i for i, l in enumerate(unmatched_local)
                    if cn == l["name"].strip() and not _blocked(c, l)), None)
        if hit is not None:
            _take(c, hit, "exact", 3.0)
        else:
            pending.append(c)


    still = []
    for c in pending:
        cloud_code = c.get("code") or extract_site_code(c["name"])
        best, best_score = None, 0
        best_conflict = None
        best_conflict_score = 0
        if cloud_code:
            for i, l in enumerate(unmatched_local):
                if _blocked(c, l):
                    continue
                lcode = l.get("code") or extract_site_code(l["name"])
                if not (lcode and lcode == cloud_code):
                    continue
                reason = discriminators_reason(c["name"], l["name"])
                score = 2.0 + fuzzy_similarity(c["name"], l["name"])
                if reason:


                    if score > best_conflict_score:
                        best_conflict = (i, reason)
                        best_conflict_score = score
                    continue
                if score > best_score:
                    best, best_score = i, score
        if best is not None:
            _take(c, best, "code", best_score)
        else:
            if best_conflict is not None:
                l = unmatched_local[best_conflict[0]]
                held_back.append({"cloud": c, "local": l,
                                  "reason": best_conflict[1],
                                  "via": "code"})
            still.append(c)


    unmatched_cloud = []
    for c in still:
        best, best_score = None, 0
        best_conflict = None
        best_conflict_score = 0
        for i, l in enumerate(unmatched_local):
            if _blocked(c, l):
                continue
            sim = fuzzy_similarity(c["name"], l["name"])
            if sim <= 0.5:
                continue
            reason = discriminators_reason(c["name"], l["name"])
            if reason:
                if sim > best_conflict_score:
                    best_conflict = (i, reason)
                    best_conflict_score = sim
                continue
            if sim > best_score:
                best, best_score = i, sim
        if best is not None:
            _take(c, best, "fuzzy", best_score)
        else:
            if best_conflict is not None:
                l = unmatched_local[best_conflict[0]]

                already = any(h["cloud"].get("id") == c.get("id")
                              and h["local"].get("path") == l.get("path")
                              for h in held_back)
                if not already:
                    held_back.append({"cloud": c, "local": l,
                                      "reason": best_conflict[1],
                                      "via": "fuzzy"})
            unmatched_cloud.append(c)


    matched.sort(key=lambda e: e["cloud"]["name"].lower())
    unmatched_cloud.sort(key=lambda c: c["name"].lower())
    unmatched_local.sort(key=lambda l: l["name"].lower())
    held_back.sort(key=lambda h: h["cloud"]["name"].lower())
    mismatches = [e for e in matched if e["namesDiffer"]]
    return {
        "matched": matched, "mismatches": mismatches,
        "cloudOnly": unmatched_cloud, "localOnly": unmatched_local,
        "heldBack": held_back,
        "summary": {"matched": len(matched), "mismatches": len(mismatches),
                    "cloudOnly": len(unmatched_cloud), "localOnly": len(unmatched_local),
                    "heldBack": len(held_back)},
    }


def build_sites_data(api, output_dir):
    sites = api.get_sites()


    site_id_by_name = {}
    for s in sites:
        sid = s.get("siteId") or s.get("id")
        if sid:
            site_id_by_name[s.get("name", "")] = sid


    dataset_to_site = {}
    dataset_meta = {}


    plan_by_name = {}
    try:
        for entry in api.get_dataset_listing():
            eid = entry.get("id")
            sid = entry.get("siteId") or site_id_by_name.get(entry.get("siteName") or "")
            if eid and sid:
                dataset_to_site[eid] = sid
            if eid:
                users = entry.get("datasetUsers") or []
                shared_with = sorted({
                    (u.get("username") or "").strip().lower()
                    for u in users
                    if u.get("role") != "OWNER" and u.get("username")
                })


                current_owner = next(
                    ((u.get("username") or "").strip().lower()
                     for u in users if u.get("role") == "OWNER"), "")
                dataset_meta[eid] = {
                    "projectType": _PROJECT_TYPE_LABELS.get(entry.get("type")),
                    "sharedWith": shared_with,
                    "currentOwner": current_owner,
                }
            etype = entry.get("type")
            if etype in ("GREENFIELD_PLAN", "BROWNFIELD_PLAN"):
                ename = (entry.get("name") or "").strip().lower()
                if ename:
                    plan_by_name[ename] = _PROJECT_TYPE_LABELS.get(etype)
    except Exception:
        pass

    all_projects = []
    try:
        all_projects = api.get_projects()
    except Exception:
        pass


    site_datasets = {}
    for pr in all_projects:
        pid = pr.get("id")
        if not pid:
            continue
        sid = dataset_to_site.get(pid)
        if not sid:
            continue
        history = pr.get("history") or {}
        size = int((pr.get("statistics") or {}).get("size", 0) or 0)
        name = pr.get("name") or pr.get("title") or "Untitled"
        dm = dataset_meta.get(pid) or {}
        created_by = (history.get("createdBy") or "").strip().lower()
        proj = {
            "id": pid, "name": name, "code": extract_site_code(name),
            "size": size, "mtime": _parse_cloud_mtime(pr),


            "owner": dm.get("currentOwner") or created_by,
            "createdBy": created_by,
            "modifiedBy": (history.get("modifiedBy") or "").strip().lower(),


            "meta": _row_meta(size, _parse_cloud_mtime(pr)),
            "projectType": dm.get("projectType"),
            "sharedWith": dm.get("sharedWith") or [],
            "planType": plan_by_name.get(name.strip().lower()),
        }
        site_datasets.setdefault(sid, []).append(proj)

    cloud = []
    for s in sites:
        sid = s.get("siteId") or s.get("id")
        datasets = site_datasets.get(sid, [])
        pc = len(datasets)
        total_size = sum(d["size"] for d in datasets)


        if pc:
            meta = f"{pc} esx · {human_size(total_size)}" if total_size else f"{pc} esx"
        else:
            meta = "empty"
        cloud.append({"id": sid, "name": s["name"],
                      "code": extract_site_code(s["name"]), "meta": meta,
                      "datasets": [{"name": d["name"], "id": d["id"], "size": d["size"]} for d in datasets],
                      "_childCloud": datasets})


    esx_by_folder = {}
    for f in get_local_esx_files(output_dir):
        item = {"path": f["path"], "name": f["name"], "code": extract_site_code(f["name"]),
                 "isDir": False, "folder": f["folder"], "size": int(f.get("size") or 0),
                 "mtime": int(f.get("mtime") or 0), "owner": f.get("owner") or "",


                 "projectId": f.get("projectId") or "",
                 "projectType": f.get("projectType"),
                 "meta": _row_meta(int(f.get("size") or 0), int(f.get("mtime") or 0))}
        esx_by_folder.setdefault(f["folder"], []).append(item)

    local = []
    for f in get_local_folders(output_dir):
        inv = folder_inventory(Path(f["path"]))
        local.append({"path": f["path"], "name": f["name"], "code": f["code"], "isDir": True,
                      "meta": f'{f["esxCount"]} esx · {human_size(f["totalSize"])}',
                      "hasSource": inv["srcCount"] > 0, "src": inv,
                      "_childLocal": esx_by_folder.get(f["name"], [])})

    nm = not_matches_set()
    mm_map, _ = manual_matches_map()
    result = build_matches(cloud, local, nm, mm_map)


    def attach_children(site, folder):
        cchild = site.pop("_childCloud", []) if site else []
        lchild = folder.pop("_childLocal", []) if folder else []
        target = site if site is not None else folder
        target["children"] = build_matches(cchild, lchild, nm, mm_map)

    for pair in result["matched"]:
        attach_children(pair["cloud"], pair["local"])
    for s in result["cloudOnly"]:
        attach_children(s, None)
    for f in result["localOnly"]:
        attach_children(None, f)


    claimed = set(dataset_to_site.keys())
    orphan_cloud = []
    for pr in all_projects:
        pid = pr.get("id")
        if not pid or pid in claimed:
            continue
        history = pr.get("history") or {}
        size = int((pr.get("statistics") or {}).get("size", 0) or 0)
        name = pr.get("name") or pr.get("title") or "Untitled"
        dm = dataset_meta.get(pid) or {}
        created_by = (history.get("createdBy") or "").strip().lower()
        orphan_cloud.append({
            "id": pid, "name": name, "code": extract_site_code(name),
            "size": size, "mtime": _parse_cloud_mtime(pr),

            "owner": dm.get("currentOwner") or created_by,
            "createdBy": created_by,
            "modifiedBy": (history.get("modifiedBy") or "").strip().lower(),
            "meta": _row_meta(size, _parse_cloud_mtime(pr)), "hasSite": False,
            "projectType": dm.get("projectType"),
            "sharedWith": dm.get("sharedWith") or [],
            "planType": plan_by_name.get(name.strip().lower()),
        })
    orphan_cloud.sort(key=lambda c: c["name"].lower())


    if orphan_cloud:
        local_index = {}
        def _index_site(container):
            children = container.get("children") if container else None
            if not children:
                return
            for l in children.get("localOnly", []):
                local_index[l["path"]] = (children, l)
        for pair in result["matched"]:
            _index_site(pair.get("cloud") or pair.get("local"))
        for f in result["localOnly"]:
            _index_site(f)

        if local_index:
            pool = [l for (_, l) in local_index.values()]
            cross = build_matches(orphan_cloud, pool, nm, mm_map)
            moved_ids = set()
            for pair in cross["matched"]:
                c = pair["cloud"]
                l_hit = pair["local"]
                entry = local_index.get(l_hit["path"])
                if not entry:
                    continue
                children, l_item = entry
                try:
                    children["localOnly"].remove(l_item)
                except ValueError:
                    continue
                c["unassigned"] = True
                children["matched"].append({
                    "cloud": c, "local": l_item,
                    "matchType": pair.get("matchType"),
                    "score": pair.get("score"),
                    "namesDiffer": pair.get("namesDiffer"),
                })


                children["mismatches"] = [e for e in children["matched"] if e.get("namesDiffer")]
                children["summary"]["matched"] = len(children["matched"])
                children["summary"]["mismatches"] = len(children["mismatches"])
                children["summary"]["localOnly"] = len(children["localOnly"])
                moved_ids.add(c["id"])
            orphan_cloud = [c for c in orphan_cloud if c["id"] not in moved_ids]

    result["orphans"] = build_matches(orphan_cloud, [], nm, mm_map)
    return result


def build_projects_data(api, output_dir):

    dataset_site = {}
    dataset_meta = {}
    plan_by_name = {}
    try:
        for entry in api.get_dataset_listing():
            eid = entry.get("id")
            sname = entry.get("siteName")
            if eid and sname:
                dataset_site[eid] = sname
            if eid:
                users = entry.get("datasetUsers") or []
                shared_with = sorted({
                    (u.get("username") or "").strip().lower()
                    for u in users
                    if u.get("role") != "OWNER" and u.get("username")
                })


                current_owner = next(
                    ((u.get("username") or "").strip().lower()
                     for u in users if u.get("role") == "OWNER"), "")
                dataset_meta[eid] = {
                    "projectType": _PROJECT_TYPE_LABELS.get(entry.get("type")),
                    "sharedWith": shared_with,
                    "currentOwner": current_owner,
                }
            etype = entry.get("type")
            if etype in ("GREENFIELD_PLAN", "BROWNFIELD_PLAN"):
                ename = (entry.get("name") or "").strip().lower()
                if ename:
                    plan_by_name[ename] = _PROJECT_TYPE_LABELS.get(etype)
    except Exception:
        pass

    cloud = []
    for pr in api.get_projects():
        name = pr.get("name") or pr.get("title") or "Untitled"
        pid = pr.get("id")

        size = int((pr.get("statistics") or {}).get("size", 0) or 0)
        size_str = human_size(size) if size else ""

        mtime = _parse_cloud_mtime(pr)


        history = pr.get("history") or {}
        created_by = (history.get("createdBy") or "").strip().lower()
        modified_by = (history.get("modifiedBy") or "").strip().lower()

        site_name = dataset_site.get(pid, "")
        dm = dataset_meta.get(pid) or {}
        owner = dm.get("currentOwner") or created_by

        meta = _row_meta(size, mtime, tail=site_name or None)
        cloud.append({"id": pid, "name": name,
                      "code": extract_site_code(name), "meta": meta,
                      "size": size, "mtime": mtime,
                      "owner": owner, "createdBy": created_by,
                                "modifiedBy": modified_by,
                      "hasSite": bool(site_name),
                      "projectType": dm.get("projectType"),
                      "sharedWith": dm.get("sharedWith") or [],
                      "planType": plan_by_name.get(name.strip().lower()),


                      "siteName": site_name})
    local = [{"path": f["path"], "name": f["name"], "code": extract_site_code(f["name"]),
              "isDir": False, "folder": f["folder"],
              "size": int(f.get("size") or 0), "mtime": int(f.get("mtime") or 0),
              "owner": f.get("owner") or "",
              "projectId": f.get("projectId") or "",
              "projectType": f.get("projectType"),
              "meta": _row_meta(int(f.get("size") or 0), int(f.get("mtime") or 0),
                                tail=f["folder"])}
             for f in get_local_esx_files(output_dir)]
    mm_map, _ = manual_matches_map()
    return build_matches(cloud, local, not_matches_set(), mm_map)


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
    Returns unix seconds (int) or 0. Ekahau nests the real dates inside
    pr["history"]{modifiedAt, createdAt}; older/other endpoints may return
    them flat. Try both."""
    from datetime import datetime
    history = pr.get("history") or {}
    candidates = [
        history.get("modifiedAt"), history.get("createdAt"),
        pr.get("modifiedAt"), pr.get("updatedAt"),
        pr.get("lastModifiedAt"), pr.get("modified"), pr.get("createdAt"),
    ]
    for v in candidates:
        if not v:
            continue
        try:
            s = str(v).replace("Z", "+00:00")
            return int(datetime.fromisoformat(s).timestamp())
        except (ValueError, TypeError):
            continue
    return 0


_PROJECT_TYPE_LABELS = {
    "SIMULATED_PROJECT": "Design",
    "MEASURED_PROJECT": "Measured",
    "HYBRID_PROJECT": "Hybrid",
    "GREENFIELD_PLAN": "Greenfield Plan",
    "BROWNFIELD_PLAN": "Brownfield Plan",
}


def build_duplicates_data(api, output_dir):
    """Cluster cloud projects + local .esx files by normalized name.
    Only clusters with 2+ items are returned. Each item carries side, size,
    mtime, location, and a `matched` flag (true if it's currently paired in
    the Sites/Projects view — helps identify the "canonical" copy)."""


    dataset_site = {}
    dataset_owner = {}
    try:
        for entry in api.get_dataset_listing():
            eid = entry.get("id")
            sname = entry.get("siteName")
            if eid and sname:
                dataset_site[eid] = sname
            if eid:
                users = entry.get("datasetUsers") or []
                dataset_owner[eid] = next(
                    ((u.get("username") or "").strip().lower()
                     for u in users if u.get("role") == "OWNER"), "")
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
            history = pr.get("history") or {}
            created_by = (history.get("createdBy") or "").strip().lower()
            owner = dataset_owner.get(pid) or created_by
            cloud_items.append({
                "side": "cloud",
                "id": pid,
                "name": name,
                "size": size,
                "mtime": _parse_cloud_mtime(pr),
                "location": dataset_site.get(pid, ""),
                "hasSite": bool(dataset_site.get(pid)),
                "owner": owner,
            })
    except Exception:
        pass


    local_items = []
    for f in get_local_esx_files(output_dir):
        local_items.append({
            "side": "local",
            "path": f["path"],
            "name": f["name"],
            "size": int(f.get("size", 0) or 0),
            "mtime": int(f.get("mtime", 0) or 0),
            "location": f["folder"],
            "owner": f.get("owner") or "",
        })


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


        if cloud_count == 1 and local_count == 1 and all(i.get("matched") for i in items):
            continue
        shape = "mixed" if cloud_count and local_count else (
            "cloud-only" if cloud_count else "local-only")
        newest = max(items, key=lambda i: i["mtime"])
        largest = max(items, key=lambda i: i["size"])

        def _iid(i):
            return i.get("id") or i.get("path") or ""
        clusters.append({
            "key": key,
            "displayName": items[0]["name"],
            "items": items,
            "sides": {"cloud": cloud_count, "local": local_count},
            "shape": shape,
            "newestId": _iid(newest),
            "largestId": _iid(largest),
        })


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


class CloudManager:
    def __init__(self):
        self.api = None
        self.config = load_config()

    def _ensure(self):
        if self.api:
            return True
        self.api = try_saved_cookies() or try_browser_cookies()
        return self.api is not None

    def _handle_api_error(self, e):
        """A saved session can go stale between calls (signed out of Ekahau
        Cloud elsewhere, cookie expiry). requests then follows the app's
        login redirect in a loop until it hits its 30-redirect cap, raising
        TooManyRedirects with a raw "Exceeded 30 redirects" message instead
        of anything a user can act on. Treat that as a dead session: drop
        it so the next call re-validates via try_saved_cookies()/
        try_browser_cookies() instead of trusting a stale self.api forever."""
        if isinstance(e, (requests.exceptions.TooManyRedirects, requests.exceptions.ConnectionError)):
            self.api = None
            return "Your Ekahau Cloud session has expired. Reconnect (Settings → Forget login, then sign back in)."
        return str(e)

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

    def forget_login(self):
        """Disconnect this process and remove every persisted Cloud session."""
        self.api = None
        if not clear_saved_cookies():
            return {"error": "The saved Cloud login could not be completely removed."}
        return {"ok": True}

    def reveal_in_explorer(self, path):
        try:
            od = self.config.get("output_dir", "")
            if not od:
                return {"error": "No local folder is set — pick one first"}
            _assert_inside(path, od)
            p = Path(path)
            if not p.exists():
                return {"error": "Path not found"}
            # One implementation, in tools/reveal.py - it also carries the
            # fix for Explorer needing /select,<path> as a single argument.
            from tools.reveal import reveal as _reveal
            return _reveal(p)
        except Exception as e:
            return {"error": str(e)}

    def get_data(self, kind):
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            od = self.config.get("output_dir", "")
            data = build_projects_data(self.api, od) if kind == "projects" else build_sites_data(self.api, od)


            data["currentUser"] = (self.api.user_email or "").strip().lower()
            return data
        except Exception as e:
            return {"error": self._handle_api_error(e)}

    def get_duplicates(self):
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            od = self.config.get("output_dir", "")
            return build_duplicates_data(self.api, od)
        except Exception as e:
            return {"error": self._handle_api_error(e)}

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
            if not od:
                return {"error": "No local folder is set — pick one first"}
            _assert_inside(path, od)


            if not new_name or new_name in (".", ".."):
                return {"error": "Invalid name"}
            if "/" in new_name or "\\" in new_name or ".." in Path(new_name).parts:
                return {"error": "Name cannot contain path separators or '..'"}
            old = Path(path)
            if old.is_dir():
                new = old.parent / new_name
            else:
                nn = new_name if new_name.lower().endswith(".esx") else new_name + ".esx"
                new = old.parent / nn

            _assert_inside(new, old.parent)
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
            if not od:
                return {"error": "No local folder is set — pick one first"}
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

    def upload_project(self, esx_path, site_id=None, progress_cb=None):
        """Upload .esx to cloud. If site_id given, auto-assign to that site.

        Waits (poll-until-visible, up to ~6s) for Ekahau's project-listing API
        to reflect the new upload before returning. This lets callers refresh
        the UI immediately on success without racing the cloud's propagation.

        IMPORTANT: after the new project appears in the listing, we check
        whether Ekahau's assigned name matches the local filename (minus
        `.esx`). If it doesn't, we rename the cloud project to match.

        Why: Ekahau derives the cloud project's name from `project.json`
        inside the `.esx` (the file's internal `project.name` metadata),
        not from the filename you uploaded. If you copy `Site-A.esx` and
        upload it as `MyNewSurvey.esx`, the cloud project shows up as
        `Site-A` — surprising, and if you upload N copies of the same
        source file with different filenames they all become duplicates
        of the source's name. This rename step makes the cloud reflect
        what the user actually named the file locally.
        """
        if not self._ensure():
            return {"error": "Not connected"}
        od = self.config.get("output_dir", "")
        if not od:
            return {"error": "No local folder is set — pick one first"}
        try:
            _assert_inside(esx_path, od)
        except ValueError as e:
            return {"error": str(e)}
        try:

            before_ids = {p["id"] for p in self.api.get_projects()}

            result = self.api.upload_project(esx_path, progress_cb=progress_cb)
            if isinstance(result, dict) and result.get("error"):
                return result


            new_id = None
            new_project = None
            for i in range(12):
                time.sleep(0.5)
                after = self.api.get_projects()
                new_ones = [p for p in after if p["id"] not in before_ids]
                if new_ones:
                    new_project = new_ones[0]
                    new_id = new_project["id"]
                    break
                if progress_cb:


                    progress_cb(current=95 + i // 3,
                                message=f"Waiting for cloud listing to update ({(i + 1) // 2}s)…")


            renamed_to = None
            if new_id and new_project:
                desired_name = Path(esx_path).stem
                cloud_name = (new_project.get("name") or "").strip()
                if desired_name and cloud_name and cloud_name != desired_name:
                    try:
                        if progress_cb:
                            progress_cb(message=f"Renaming cloud project → \"{desired_name}\"…")
                        self.api.rename_project(new_id, desired_name)
                        renamed_to = desired_name
                    except Exception as e:


                        renamed_to = None

            if progress_cb:
                progress_cb(current=100, message="Done.")


            if site_id and new_id:
                try:
                    self.api.assign_to_site(site_id, new_id)
                    ret = {"ok": True, "assigned": True, "siteId": site_id,
                           "datasetId": new_id}
                    if renamed_to:
                        ret["renamedTo"] = renamed_to
                    return ret
                except Exception as e:
                    return {"ok": True, "uploaded": True, "datasetId": new_id,
                            "assignError": str(e),
                            "renamedTo": renamed_to,
                            "warning": f"Uploaded but couldn't assign to site: {e}"}

            if not new_id:


                return {"ok": True, "uploaded": True,
                        "warning": "Uploaded but not yet visible in cloud listing — may take another moment to appear."}

            ret = {"ok": True, "uploaded": True, "datasetId": new_id}
            if renamed_to:
                ret["renamedTo"] = renamed_to
            return ret
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


            destinations = _get_suite_destinations()
            subfolder_names = [d["name"] for d in destinations]
            for name in subfolder_names:
                (target / name).mkdir(exist_ok=True)
            return {"ok": True, "path": str(target), "subfolders": subfolder_names}
        except Exception as e:
            return {"error": str(e)}

    def download_project(self, project_id, dest_folder_name, progress_cb=None):
        """Download a cloud project as an .esx file into a site folder.

        Uses the reverse-engineered batch + imageFiles flow from EkahauAPI
        (see capture_download.js). Refuses to overwrite an existing file
        of the same name — the caller can rename the cloud project first.

        progress_cb forwards through to the API-level download; we tack on
        a final "save to disk" stage after the bytes are in hand.
        """
        base = self.config.get("output_dir", "")
        if not base:
            return {"error": "No local folder is set — pick one first"}
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            safe_folder = re.sub(r'[<>:"/\\|?*]', '-', dest_folder_name or '').strip().rstrip('.')
            if not safe_folder or '..' in safe_folder or '/' in safe_folder or '\\' in safe_folder:
                return {"error": "Invalid site folder name"}
            dest_dir = Path(base) / safe_folder
            is_new_folder = not dest_dir.exists()
            if is_new_folder:
                dest_dir.mkdir(parents=True)
            elif not dest_dir.is_dir():
                return {"error": "Destination is not a folder"}
            _assert_inside(dest_dir, base)
            if is_new_folder:


                for d in _get_suite_destinations():
                    (dest_dir / d["name"]).mkdir(exist_ok=True)

            result = self.api.download_project(project_id, progress_cb=progress_cb)
            if isinstance(result, dict) and result.get("error"):
                return result
            esx_bytes = result["esx"]
            proj_name = result["name"]

            safe_name = re.sub(r'[<>:"/\\|?*]', '-', proj_name).strip().rstrip('.')
            if not safe_name.lower().endswith(".esx"):
                safe_name += ".esx"
            target = dest_dir / safe_name
            if target.exists():
                return {"error": f"'{safe_name}' already exists in {safe_folder}"}
            _assert_inside(target, dest_dir)
            if progress_cb:
                progress_cb(stage="save", current=97, total=100,
                            message=f"Saving {safe_name} to disk…")
            with open(target, "wb") as f:
                f.write(esx_bytes)
            if progress_cb:
                progress_cb(stage="done", current=100, total=100,
                            message="Done.")
            return {"ok": True, "path": str(target), "name": proj_name}
        except Exception as e:
            return {"error": str(e)}

    def verify_replace_local(self, project_id, local_path, progress_cb=None):
        """Download the cloud project's current content and overwrite the
        local .esx. Used by the Verify button on blue "Name matches" rows —
        after replacement, both files share the same internal project.json.id
        so the pair upgrades to green "Same file" on the next refresh.

        Safe direction only: refuses if local's internal modifiedAt is
        meaningfully newer than cloud's — that case needs a destructive
        delete+reupload flow that would also lose sharing/tags/versions,
        and we haven't shipped that direction yet.

        Returns {"ok": True, "path": ..., "newProjectId": ...} on success,
        {"error": "local_newer", ...} when the safe direction doesn't apply,
        or {"error": <msg>} on other failures."""
        if not self._ensure():
            return {"error": "Not connected"}
        base = self.config.get("output_dir", "")
        if not base:
            return {"error": "No local folder is set"}
        try:
            _assert_inside(local_path, base)
        except ValueError:
            return {"error": "Local path is outside the configured folder"}

        src = Path(local_path)
        if not src.exists() or not src.is_file():
            return {"error": f"Local file not found: {local_path}"}


        try:
            fs_mtime = int(src.stat().st_mtime)
        except OSError:
            fs_mtime = 0
        local_meta = _esx_meta(src, fs_mtime)
        local_internal_mtime = local_meta.get("internalMtime") or fs_mtime


        try:
            proj = self.api.get(f"{API_BASE}/{project_id}").json()
        except Exception as e:
            return {"error": f"Cloud project lookup failed: {e}"}
        cloud_mtime = _parse_cloud_mtime(proj)


        _NEWER_TOLERANCE_S = 60
        if local_internal_mtime and cloud_mtime and (local_internal_mtime > cloud_mtime + _NEWER_TOLERANCE_S):
            return {
                "error": "local_newer",
                "message": ("Local file is newer than cloud — overwriting would "
                            "lose local changes. Upload local to cloud first, or "
                            "skip this pair."),
                "localMtime": local_internal_mtime,
                "cloudMtime": cloud_mtime,
            }


        if progress_cb:
            progress_cb(stage="download", current=5, total=100,
                        message="Downloading cloud copy…")
        try:
            result = self.api.download_project(project_id, progress_cb=progress_cb)
        except Exception as e:
            return {"error": f"Download failed: {e}"}
        if isinstance(result, dict) and result.get("error"):
            return result
        esx_bytes = result["esx"]


        tmp = src.with_suffix(src.suffix + ".wd-verify.tmp")
        try:
            if progress_cb:
                progress_cb(stage="save", current=95, total=100,
                            message="Replacing local file…")
            with open(tmp, "wb") as f:
                f.write(esx_bytes)
            os.replace(tmp, src)
        except OSError as e:
            try:
                tmp.unlink()
            except OSError:
                pass
            return {"error": f"Write failed: {e}"}


        _ESX_META_CACHE.pop(str(src), None)
        _ESX_TYPE_CACHE.pop(str(src), None)


        new_fs_mtime = int(src.stat().st_mtime)
        new_meta = _esx_meta(src, new_fs_mtime)
        if progress_cb:
            progress_cb(stage="done", current=100, total=100, message="Done.")
        return {
            "ok": True,
            "path": str(src),
            "newProjectId": new_meta.get("projectId"),
            "cloudProjectId": project_id,
        }


    def list_shares(self, project_id):
        if not self._ensure():
            return {"error": "Not connected"}
        if not project_id:
            return {"error": "projectId required"}
        try:
            result = self.api.list_project_shares(project_id)
            users = (result or {}).get(project_id, [])
            return {"ok": True, "users": users}
        except Exception as e:
            return {"error": str(e)}

    def add_share(self, project_id, email, role="READ_USER"):
        if not self._ensure():
            return {"error": "Not connected"}
        if not project_id or not email:
            return {"error": "projectId and email are required"}


        email = email.strip().lower()
        try:
            r = self.api.add_project_share(project_id, email, role)

            per_email = ((r or [{}])[0] or {}).get("responsePerEmailAddress", {})
            msg = per_email.get(email, "")
            return {"ok": True, "email": email, "message": msg}
        except Exception as e:
            return {"error": str(e)}

    def remove_share(self, project_id, email):
        if not self._ensure():
            return {"error": "Not connected"}
        if not project_id or not email:
            return {"error": "projectId and email are required"}
        try:
            r = self.api.remove_project_share(project_id, email.strip().lower())

            first = (r or [{}])[0] or {}
            if first.get("success") is False:
                return {"error": first.get("message") or "Remove failed"}
            return {"ok": True, "email": email}
        except Exception as e:
            return {"error": str(e)}


    def bulk_share(self, project_ids, emails, role="READ_USER",
                   share_with_group=False, group_id=None,
                   group_name="", group_role="READ_USER"):
        """Batch-share a set of projects with a set of emails and/or the
        user's sharing group. Returns per-project results so the frontend
        can surface partial failures without pretending everything worked.

        Guards non-owned projects out (Ekahau would reject anyway, but a
        pre-check gives clearer messaging than a 403 aggregate)."""
        if not self._ensure():
            return {"error": "Not connected"}
        project_ids = [p for p in (project_ids or []) if p]
        if not project_ids:
            return {"error": "No projects selected"}
        emails = [e.strip().lower() for e in (emails or []) if e and "@" in e]
        if not emails and not share_with_group:
            return {"error": "Provide at least one email or enable group share"}
        my_email = (self.api.user_email or "").strip().lower()


        owned_ids, skipped = [], []
        for pid in project_ids:
            try:
                raw = self.api.list_project_shares(pid) or {}
                shares = raw.get(pid, []) if isinstance(raw, dict) else []
                owner = next((u for u in shares
                              if (u.get("role") or "").upper() == "OWNER"), None)
                owner_email = ((owner or {}).get("username") or "").strip().lower()
                if my_email and owner_email and my_email == owner_email:
                    owned_ids.append(pid)
                else:
                    skipped.append({"projectId": pid, "reason":
                        f"Not owner (owned by {owner_email or 'unknown'})"})
            except Exception as e:
                skipped.append({"projectId": pid, "reason": str(e)})

        results = {"skipped": skipped, "ownedCount": len(owned_ids)}
        if not owned_ids:
            return {"error": "None of the selected projects are yours to share",
                    **results}


        if emails:
            try:
                self.api.bulk_add_shares(owned_ids, emails, role)
                results["emailsAdded"] = emails
                results["role"] = role
            except Exception as e:
                results["emailError"] = str(e)


        if share_with_group and group_id:
            try:
                group_dto = {
                    "userGroupId": group_id,
                    "userGroupName": group_name or "My Sharing Group",
                    "role": group_role,
                }
                self.api._write(
                    "PUT", "/shareapi/v1/projects/users/toggle-userGroup", {
                    "projectIds": owned_ids,
                    "projectUserGroupDto": {**group_dto, "toggleGroupShare": False},
                })
                r = self.api._write(
                    "PUT", "/shareapi/v1/projects/users/toggle-userGroup", {
                    "projectIds": owned_ids,
                    "projectUserGroupDto": {**group_dto, "toggleGroupShare": True},
                })
                results["groupShared"] = True
                results["groupRole"] = group_role
                results["groupStatus"] = r.status_code
            except Exception as e:
                results["groupError"] = str(e)

        results["ok"] = True
        return results


    def transfer_ownership(self, project_id, new_owner_email):
        if not self._ensure():
            return {"error": "Not connected"}
        if not project_id:
            return {"error": "projectId required"}
        if not new_owner_email or "@" not in new_owner_email:
            return {"error": "Valid new-owner email required"}
        new_owner_email = new_owner_email.strip().lower()
        try:


            raw = self.api.list_project_shares(project_id) or {}
            shares = raw.get(project_id, []) if isinstance(raw, dict) else []
            owner = next((u for u in shares if (u.get("role") or "").upper() == "OWNER"), None)
            if not owner:
                return {"error": "Could not determine current owner"}
            current_owner_email = (owner.get("username") or "").strip().lower()
            if not current_owner_email:
                return {"error": "Current owner has no email on record"}
            if current_owner_email == new_owner_email:
                return {"error": f"{new_owner_email} is already the owner"}


            my_email = (self.api.user_email or "").strip().lower()
            if my_email and my_email != current_owner_email:
                return {"error": f"Only the owner ({current_owner_email}) can transfer this project"}
            result = self.api.transfer_ownership(project_id, current_owner_email, new_owner_email)
            status = result.get("result", {}).get(project_id)
            if status == "SUCCESS":
                return {"ok": True,
                        "message": f"Ownership transferred to {new_owner_email}",
                        "previousOwner": current_owner_email,
                        "newOwner": new_owner_email}


            return {"error": f"Transfer failed: {status or result}"}
        except Exception as e:
            return {"error": str(e)}


    def get_my_group(self, group_name="My Sharing Group"):
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            group = self.api.get_user_group(group_name)
            if not group:
                return {"ok": True, "group": None,
                        "message": f"No group named '{group_name}' found."}


            trimmed = [{
                "email": m.get("email"),
                "firstName": m.get("firstName") or "",
                "lastName": m.get("lastName") or "",
                "userId": m.get("userId"),
            } for m in (group.get("members") or []) if m.get("email")]
            return {"ok": True, "group": {
                "groupId": group.get("groupId"),
                "groupName": group.get("groupName"),
                "createdBy": group.get("createdBy"),
                "members": trimmed,
            }}
        except Exception as e:
            return {"error": str(e)}

    def add_group_member(self, email, group_name="My Sharing Group"):
        """Fetch the current group so we have the member list to echo back,
        then PUT with the new email in addedMemberList."""
        if not self._ensure():
            return {"error": "Not connected"}
        if not email or "@" not in email:
            return {"error": "Valid email required"}
        email = email.strip().lower()
        try:
            group = self.api.get_user_group(group_name)
            if not group:
                return {"error": f"Group '{group_name}' not found"}


            existing_emails = {(m.get("email") or "").lower()
                               for m in (group.get("members") or [])}
            if email in existing_emails:
                return {"ok": True, "already": True, "email": email}


            self.api.update_user_group(
                group["groupId"], group["groupName"],
                added=[email], deleted=[], current_members=[])
            return {"ok": True, "email": email}
        except Exception as e:
            return {"error": str(e)}

    def refresh_group_shares(self, group_name="My Sharing Group", dry_run=False,
                             project_ids=None):
        """Force-refresh the user's Sharing Group membership on every owned
        project where the group is currently shared. Fixes the "stale group"
        problem: when you add someone to your group AFTER already sharing
        projects with it, existing shares don't auto-update — Ekahau doesn't
        propagate. This action finds every affected project and does
        OFF-then-ON in a single batch, pushing the current member list.

        Detection is authoritative, not heuristic: for each candidate, we
        call list_project_shares and confirm at least one shared user has
        the matching groupId. Skips projects the user doesn't own (Ekahau
        would 403 anyway).

        dry_run=True skips the actual refresh — just returns which project
        IDs would be affected. Useful for the frontend to show a "N will
        be refreshed" pre-flight.

        project_ids: optional explicit subset. When provided, skips auto-
        discovery and refreshes only those IDs (still ownership-validated
        per project). Used by the picker modal to let the user uncheck
        specific projects before committing."""
        if not self._ensure():
            return {"error": "Not connected"}
        try:
            g = self.api.get_user_group(group_name)
            if not g:
                return {"error": f"Group '{group_name}' not found"}
            group_id = g.get("groupId")
            group_name_actual = g.get("groupName") or group_name
            if not group_id:
                return {"error": "Group has no id — cannot refresh"}
            my_email = (self.api.user_email or "").strip().lower()

            group_member_emails = set()
            for m in (g.get("members") or []):
                em = (m.get("email") or "").strip().lower()
                if em:
                    group_member_emails.add(em)


            confirmed_ids = []
            if project_ids is not None:
                for pid in project_ids:
                    if not pid:
                        continue
                    try:
                        raw = self.api.list_project_shares(pid) or {}
                        shares = raw.get(pid, []) if isinstance(raw, dict) else []
                        owner = next((u for u in shares
                                      if (u.get("role") or "").upper() == "OWNER"), None)
                        if not owner or (owner.get("username") or "").strip().lower() != my_email:
                            continue
                        confirmed_ids.append(pid)
                    except Exception:
                        continue
            else:
                try:
                    dsl = self.api.get_dataset_listing() or []
                except Exception:
                    dsl = []
                candidates = set()
                for entry in dsl:
                    eid = entry.get("id")
                    if not eid:
                        continue
                    users = entry.get("datasetUsers") or []
                    shared_emails = {(u.get("username") or "").strip().lower()
                                     for u in users if u.get("role") != "OWNER"}
                    if shared_emails.isdisjoint(group_member_emails):
                        continue
                    owner = next((u for u in users if u.get("role") == "OWNER"), None)
                    owner_email = ((owner or {}).get("username") or "").strip().lower()
                    if my_email and owner_email and owner_email != my_email:
                        continue
                    candidates.add(eid)

                for pid in candidates:
                    try:
                        raw = self.api.list_project_shares(pid) or {}
                        shares = raw.get(pid, []) if isinstance(raw, dict) else []
                        owner = next((u for u in shares
                                      if (u.get("role") or "").upper() == "OWNER"), None)
                        if not owner or (owner.get("username") or "").strip().lower() != my_email:
                            continue
                        if any(u.get("groupId") == group_id for u in shares):
                            confirmed_ids.append(pid)
                    except Exception:
                        continue

            if dry_run:
                return {"ok": True, "dryRun": True, "projectIds": confirmed_ids,
                        "count": len(confirmed_ids),
                        "groupId": group_id, "groupName": group_name_actual}

            if not confirmed_ids:
                msg = ("None of the selected projects are eligible."
                       if project_ids is not None
                       else "No projects need refreshing — nothing currently uses this group.")
                return {"ok": True, "count": 0, "message": msg}


            role = "WRITE_USER"
            try:

                raw = self.api.list_project_shares(confirmed_ids[0]) or {}
                shares = raw.get(confirmed_ids[0], []) if isinstance(raw, dict) else []
                first_gu = next((u for u in shares if u.get("groupId") == group_id), None)
                if first_gu and first_gu.get("role"):
                    role = first_gu["role"]
            except Exception:
                pass

            group_dto = {
                "userGroupId": group_id,
                "userGroupName": group_name_actual,
                "role": role,
            }
            self.api._write(
                "PUT", "/shareapi/v1/projects/users/toggle-userGroup", {
                "projectIds": confirmed_ids,
                "projectUserGroupDto": {**group_dto, "toggleGroupShare": False},
            })
            self.api._write(
                "PUT", "/shareapi/v1/projects/users/toggle-userGroup", {
                "projectIds": confirmed_ids,
                "projectUserGroupDto": {**group_dto, "toggleGroupShare": True},
            })
            return {"ok": True, "count": len(confirmed_ids),
                    "projectIds": confirmed_ids, "role": role,
                    "groupId": group_id, "groupName": group_name_actual,
                    "message": f"Refreshed group membership on {len(confirmed_ids)} project{'s' if len(confirmed_ids) != 1 else ''}."}
        except Exception as e:
            return {"error": str(e)}

    def remove_group_member(self, email, group_name="My Sharing Group"):
        """Same pattern as add, but the captured remove payload includes
        the FULL current member list in `members`. We fetch first so the
        server sees the pre-delete state matches what it holds."""
        if not self._ensure():
            return {"error": "Not connected"}
        if not email:
            return {"error": "email required"}
        email = email.strip().lower()
        try:
            group = self.api.get_user_group(group_name)
            if not group:
                return {"error": f"Group '{group_name}' not found"}
            members_raw = group.get("members") or []
            self.api.update_user_group(
                group["groupId"], group["groupName"],
                added=[], deleted=[email], current_members=members_raw)
            return {"ok": True, "email": email}
        except Exception as e:
            return {"error": str(e)}

    def toggle_group_share(self, project_id, group_id, group_name, role, enable):
        """Enable or disable the user's "My Sharing Group" on a project.
        Wraps EkahauAPI.toggle_project_group_share with error normalization
        so the frontend gets {ok:True} or {error:msg}."""
        if not self._ensure():
            return {"error": "Not connected"}
        if not project_id or not group_id:
            return {"error": "projectId and groupId are required"}
        try:
            r = self.api.toggle_project_group_share(
                project_id, group_id, group_name or "My Sharing Group",
                role or "READ_USER", bool(enable))
            first = (r or [{}])[0] or {}
            if first.get("success") is False:
                return {"error": first.get("message") or "Group toggle failed"}
            return {"ok": True, "enabled": bool(enable), "role": role,
                    "groupName": group_name}
        except Exception as e:
            return {"error": str(e)}

    def change_share_role(self, project_id, email, new_role):
        """Ekahau's API has no per-user role update — the toggle-userGroup
        endpoint changes an entire named user-group. To change ONE user's
        role, remove them and re-add with the new role. Not atomic (a
        crash between the two calls leaves the user unshared) but the
        caller can retry."""
        if not self._ensure():
            return {"error": "Not connected"}
        if not project_id or not email or not new_role:
            return {"error": "projectId, email, and new_role are required"}
        email = email.strip().lower()
        try:
            rm = self.api.remove_project_share(project_id, email)
            first = (rm or [{}])[0] or {}
            if first.get("success") is False:
                return {"error": "Remove step failed: " + (first.get("message") or "unknown")}
            add = self.api.add_project_share(project_id, email, new_role)
            per_email = ((add or [{}])[0] or {}).get("responsePerEmailAddress", {})
            return {"ok": True, "email": email, "role": new_role,
                    "message": per_email.get(email, "")}
        except Exception as e:
            return {"error": str(e)}

    def move_local_to_site(self, esx_path, dest_folder_name):
        """Move a local .esx file into a site folder under output_dir.

        Creates the destination folder if it doesn't exist. Refuses if a file
        with the same name is already there (caller can rename first).
        """
        base = self.config.get("output_dir", "")
        if not base:
            return {"error": "No local folder is set — pick one first"}
        try:
            _assert_inside(esx_path, base)
            safe = re.sub(r'[<>:"/\\|?*]', '-', dest_folder_name or '').strip().rstrip('.')
            if not safe or '..' in safe or '/' in safe or '\\' in safe:
                return {"error": "Invalid site folder name"}
            src = Path(esx_path)
            if not src.exists() or not src.is_file():
                return {"error": "Source .esx not found"}
            dest_dir = Path(base) / safe
            if not dest_dir.exists():
                dest_dir.mkdir(parents=True)
            elif not dest_dir.is_dir():
                return {"error": "Destination is not a folder"}
            _assert_inside(dest_dir, base)
            target = dest_dir / src.name
            if target.exists():
                if target.resolve() == src.resolve():
                    return {"ok": True, "newPath": str(target), "unchanged": True}
                return {"error": f"'{src.name}' already exists in {safe}"}
            shutil.move(str(src), str(target))
            return {"ok": True, "newPath": str(target)}
        except Exception as e:
            return {"error": str(e)}

    def merge_preview(self, src_path, dst_path):
        """Dry run: what would move from src into dst, and which files collide."""
        try:
            od = self.config.get("output_dir", "")
            if not od:
                return {"error": "No local folder is set — pick one first"}
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
            if not od:
                return {"error": "No local folder is set — pick one first"}
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
                    _assert_inside(s, src)
                    _assert_inside(d, dst)
                except ValueError as e:
                    errors.append(f"{rel}: {e}")
                    continue
                try:
                    d.parent.mkdir(parents=True, exist_ok=True)
                    if not d.exists():
                        shutil.move(str(s), str(d)); moved += 1
                    elif action == "overwrite":
                        d.unlink(); shutil.move(str(s), str(d)); overwritten += 1
                    elif action == "keepboth":


                        s_m, d_m = s.stat().st_mtime, d.stat().st_mtime
                        if s_m >= d_m:

                            d.rename(_timestamped_path(d, d_m))
                            shutil.move(str(s), str(d))
                        else:

                            shutil.move(str(s), str(_timestamped_path(d, s_m)))
                        keptboth += 1
                    else:
                        skipped += 1
                except Exception as e:
                    errors.append(f"{rel}: {e}")
            try:
                src_empty = not any(True for _ in _walk_files(src))
            except OSError:
                src_empty = False
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

    def set_folder(self, path):
        """Restore a previously selected project directory without a picker."""
        target = Path(path)
        if not target.is_dir():
            return {"error": f"Not a directory: {path}"}
        resolved = str(target.resolve())
        self.config["output_dir"] = resolved
        save_config(self.config)
        return {"path": resolved}

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


    def mark_manual_match(self, cloud_id, local_path, cloud_name="", local_name=""):
        if not cloud_id or not local_path:
            return {"error": "cloudId and localPath are required"}
        pairs = load_manual_matches()
        target = _nm_pair_key(cloud_id, local_path)
        if any(_nm_pair_key(p["cloudId"], p["localPath"]) == target for p in pairs):
            return {"ok": True, "already": True}
        pairs.append({
            "cloudId": cloud_id, "localPath": local_path,
            "cloudName": cloud_name, "localName": local_name,
            "addedAt": int(time.time()),
        })
        save_manual_matches(pairs)

        nm = load_not_matches()
        nm_kept = [p for p in nm if _nm_pair_key(p["cloudId"], p["localPath"]) != target]
        if len(nm_kept) != len(nm):
            save_not_matches(nm_kept)
        return {"ok": True, "count": len(pairs)}

    def unmark_manual_match(self, cloud_id, local_path):
        if not cloud_id or not local_path:
            return {"error": "cloudId and localPath are required"}
        pairs = load_manual_matches()
        target = _nm_pair_key(cloud_id, local_path)
        kept = [p for p in pairs if _nm_pair_key(p["cloudId"], p["localPath"]) != target]
        save_manual_matches(kept)
        return {"ok": True, "count": len(kept), "removed": len(pairs) - len(kept)}

    def list_manual_matches(self):
        return {"ok": True, "pairs": load_manual_matches(),
                "file": str(MANUAL_MATCH_FILE)}
