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

from tools.user_dir import user_dir
from tools import sync_state
from tools.settings import get_destinations as _get_suite_destinations
from tools import share_recipients
from tools import applog
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
CONFIG_DIR = user_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
COOKIE_FILE = CONFIG_DIR / "cookies.json"
ENCRYPTED_COOKIE_FILE = CONFIG_DIR / "cookies.enc"
KEYRING_SERVICE = "WD Wireless Tools Cloud Manager"
KEYRING_USERNAME = "session-encryption-key"
NOT_MATCH_FILE = CONFIG_DIR / "not_matches.json"
MANUAL_MATCH_FILE = CONFIG_DIR / "manual_matches.json"
EXTERNAL_OVERRIDE_FILE = CONFIG_DIR / "external_overrides.json"


def _assert_inside(path, root):
    """Raise ValueError if *path* is outside *root*.

    Asked two ways, because one of them refused his own project folder.

    `Path.resolve()` goes to the filesystem: it opens the path to follow
    reparse points, and a cloud-synced folder is full of them. When the file
    resolves through one and the root does not - or when the path is long
    enough that resolving it fails and it silently falls back to something
    else - the two come back rooted differently and `relative_to` says a file
    sitting inside the configured folder is outside it. "Could not confirm the
    result: Local path is outside the configured folder", on the folder the
    tool itself is configured with.

    So the resolved comparison is tried first, because following links is the
    stricter question and the right one when it works; and a purely textual
    comparison of the absolute, case-folded paths is accepted as well. This is
    a sanity check on a path this app's own page supplied, not a boundary
    against an attacker, and a guard that refuses his normal case is worse than
    no guard - he stops believing the ones that matter.
    """
    def _inside(a, b):
        try:
            Path(a).relative_to(Path(b))
            return True
        except ValueError:
            return False

    try:
        if _inside(Path(path).resolve(), Path(root).resolve()):
            return
    except OSError:
        pass
    #: No filesystem access, so a reparse point cannot move one side and not
    #: the other. `normcase` folds case and separators on Windows.
    a = os.path.normcase(os.path.abspath(str(path)))
    b = os.path.normcase(os.path.abspath(str(root)))
    if _inside(a, b):
        return
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


def _ov_key(cloud_id, local_path):
    """One key for a project however it is reachable.

    Ekahau's cloud id where there is one, because it survives a rename on
    either side; the normalised local path otherwise, which is all a
    local-only file has. The same shape ``_nm_pair_key`` uses, and for the
    same reason.
    """
    if cloud_id:
        return "c:" + str(cloud_id)
    return "l:" + str(local_path or "").replace(chr(92), "/").lower()


def load_external_overrides():
    """Projects he has said are External, or are his, whatever the file says.

    Ownership metadata answers "whose account is this in", and that is not
    always the same question as "is this somebody else's work". A project can
    come back with no owner at all - and when the account reports no current
    user, *nothing* looks external, which is a confident empty answer rather
    than an unknown one. This is the override for both.
    """
    if EXTERNAL_OVERRIDE_FILE.exists():
        try:
            with open(EXTERNAL_OVERRIDE_FILE) as f:
                data = json.load(f) or {}
            entries = data.get("entries", []) or []
            return [e for e in entries
                    if e.get("key") and e.get("value") in ("external", "mine")]
        except Exception:
            pass
    return []


def save_external_overrides(entries):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(EXTERNAL_OVERRIDE_FILE, "w") as f:
        json.dump({"entries": entries}, f, indent=2)


def external_overrides_map():
    """key -> "external" | "mine"."""
    return {e["key"]: e["value"] for e in load_external_overrides()}


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
            # Lead with what it means, not with the status and the path.
            #
            # "I got the failures that are listed there and I don't know what
            # those failures are all about." What he was shown was
            # `403 Forbidden on POST /site-management-api/v1/...` - which
            # reads like a fault in this tool, and is not one: Ekahau
            # understood the request and refused it. The plain sentence goes
            # first and the endpoint stays afterwards, because it is still
            # what makes a report diagnosable.
            plain = {
                401: "Ekahau did not accept the sign-in. Reconnect and try again.",
                403: ("Ekahau refused this. The usual reason is that the "
                      "project belongs to someone else - only its owner can "
                      "change a project."),
                404: "Ekahau no longer has that item. Refresh the list.",
                409: "Ekahau says that conflicts with something already there.",
                429: "Ekahau is rate-limiting; wait a moment and try again.",
            }.get(r.status_code)
            lead = (plain + " ") if plain else ""
            raise requests.HTTPError(
                f"{lead}[{r.status_code} {r.reason} on {method} {path} — {snippet}]",
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


#: **The word boundary after the keyword is load-bearing, and so is the
#: unbounded digit run.** This was `(?:bldg|bld|building)\.?\s*(\d{1,2}|[A-Za-z])`.
#: On "Bldg 100" the two-digit cap made the digit branch fail its lookahead,
#: the engine backtracked into the `bld` alternative, and `[A-Za-z]` then
#: matched the **g** of "Bldg". Every three-digit building therefore read as
#: "G", two different buildings at one address produced the same token, the
#: guard saw no conflict, and they auto-paired - which is the one case the
#: guard exists for. "Building 100" came back as nothing at all by the same
#: route. "Bldg 3" against "Bldg 5" was unaffected, which is why it looked
#: correct.
_BUILDING_RE = re.compile(
    r'\b(?:building|bldg|bld)\b\.?\s*(\d+|[A-Za-z])(?![A-Za-z0-9])', re.I)


def _building_token(name):
    m = _BUILDING_RE.search(name)
    return m.group(1).upper() if m else None


#: A year is not a street number. The first run of 3-6 digits was taken as
#: one, so "Survey 2025" and "Survey 2026" - two ordinary survey names a year
#: apart - were held back with "Street numbers don't match", a refusal he then
#: has to overrule by hand on a pair that was never in doubt.
_YEARISH = re.compile(r'^(?:19|20)\d{2}$')


def _street_number(name):
    stripped = re.sub(r'^\s*[A-Za-z]{2,}\d+', '', name.strip())
    for m in re.finditer(r'\b(\d{3,6})\b', stripped):
        if not _YEARISH.match(m.group(1)):
            return m.group(1)
    return None


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


#: `backups` stays in `_SKIP_DIRS` below even though nothing writes one any
#: more. The folder still exists on every install that ran a sync before
#: v2.141.0, full of real projects, and a scan that suddenly descended into it
#: would report every one of them as a local-only project needing attention.
#: It is his folder to delete when he is ready, not ours to start reading.


def _lp():
    """`tools.longpath`, imported where it is used.

    Module-level would be fine now - it reads no settings and touches no user
    directory - but the lazy form is what the rest of this file does, and one
    habit is easier to follow than two.
    """
    from tools import longpath as _l
    return _l


def _remap_progress(cb, lo, hi):
    """Report a sub-step's 0-100 as a slice of the whole operation."""
    if not cb:
        return None

    def inner(**kw):
        if "current" in kw:
            frac = kw["current"] / max(kw.get("total", 100), 1)
            kw["current"] = int(lo + frac * (hi - lo))
            kw["total"] = 100
        cb(**kw)
    return inner


_SKIP_DIRS = {"backups", "backup", "output", "outputs", "archive", "archives", ".git"}


_FLOORPLAN_EXT = {".pdf", ".dwg", ".dxf"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".svg", ".webp", ".heic"}


def folder_inventory(folder):
    """Inventory a site folder's contents so the UI can preview any folder,
    badge the ones holding precious non-.esx "source" files (floor plans,
    images, CAD — none of which live on Ekahau Cloud), and guard deletes.
    Skips backup/output subfolders."""
    esx_files, plans, images, other = [], [], [], []
    #: What the listing deliberately leaves out, counted rather than ignored.
    #: The skip is right for the peek and the badge - he does not want a year
    #: of archived surveys listed every time he looks at a site folder - but
    #: this inventory also feeds the delete confirmation, whose whole job is
    #: to say what is about to be destroyed. Counting zero for a folder full
    #: of archived work made that sentence wrong in the one direction that
    #: matters, and since v2.141.0 nothing copies a file aside first.
    tucked_n, tucked_bytes = 0, 0
    try:
        for f in folder.rglob("*"):
            if not f.is_file():
                continue
            rel_parts = [p.lower() for p in f.relative_to(folder).parts[:-1]]
            if any(part in _SKIP_DIRS for part in rel_parts):
                tucked_n += 1
                try:
                    tucked_bytes += f.stat().st_size
                except OSError:
                    pass
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
        "tuckedCount": tucked_n, "tuckedSizeH": human_size(tucked_bytes),
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
                            "projectName": em["projectName"],
                            "projectType": _esx_project_type(f, mtime)})
        except OSError:
            continue
    out.sort(key=lambda x: x["name"].lower())
    return out


_ESX_META_CACHE = {}
#: Generous enough that a full scan of a large project folder never evicts
#: mid-pass, small enough that it cannot grow without limit.
_ESX_CACHE_MAX = 5000


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
    #: **Size as well as the second.** The key was the path and a whole-second
    #: mtime, so a rewrite landing in the same second as the previous scan -
    #: or arriving from a sync client that preserves the original timestamp,
    #: which is the ordinary way this happens here - was served from the
    #: cache. What came back was the *previous* project id, name and internal
    #: date, which is what the id pass matches on and what the row's date is
    #: drawn from. A size that has not changed either is a file that has
    #: almost certainly not changed.
    key = str(path)
    try:
        size = os.path.getsize(path)
    except OSError:
        size = -1
    stamp = (mtime, size)
    hit = _ESX_META_CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    meta = {"author": "", "projectId": "", "projectName": "",
            "internalMtime": 0}
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
                # The project's own name, as Ekahau stored it. A local
                # copy records whatever the cloud called it at download
                # time, which is what makes a later rename detectable
                # without asking the server anything.
                meta["projectName"] = (proj.get("name")
                                       or proj.get("title") or "").strip()


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
    #: Bounded, because it is keyed per path and a long-running server walking
    #: a large project folder would otherwise hold every file it ever read.
    if len(_ESX_META_CACHE) > _ESX_CACHE_MAX:
        _ESX_META_CACHE.clear()
    _ESX_META_CACHE[key] = (stamp, meta)
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
    Pass  2 · CODE     — same site code (e.g. "SITE1") plus fuzzy name score,
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

    #: Read once for the whole build rather than per pair - this runs over
    #: every project in the account.
    _sync_points = sync_state.load()

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

    def _difference(c, l, staleness):
        """What kind of difference is this - a rename, or real work?

        `_staleness` compares two `history.modifiedAt` values, and a rename
        moves one of them. That is why renaming a cloud project used to read
        exactly like somebody redesigning it, and why "is it safe to pull
        these" had no answer.

        The discriminator is the name **inside** the .esx. `project.json`
        carries `project.name`, and `download_project` writes the cloud's own
        documents verbatim - so immediately after a download the internal name
        and the cloud name are identical. If they have since diverged, one side
        was renamed, and the staleness direction says which:

        · cloud is newer and the names diverged  -> the cloud was renamed
        · local is newer and the names diverged  -> it was renamed in Ekahau

        Returns "renamed", "content", or None when there is nothing to say.

        **It does not prove the content is unchanged.** A project renamed *and*
        edited still reports "renamed", because the rename is all this can see.
        It separates the rename you performed from everything else, which is
        the triage that was missing - not a content hash.
        """
        if not staleness:
            return None
        internal = (l.get("projectName") or "").strip()
        if not internal:
            # Older file, or one we could not read. Say nothing rather than
            # guess - an unknown reported as "content" would be a false alarm
            # and as "renamed" would be a false reassurance.
            return None
        return "renamed" if internal.casefold() != c["name"].strip().casefold() \
            else "content"

    def _take(c, idx, mtype, score=1.0):
        l = unmatched_local.pop(idx)
        disp = score - 2.0 if mtype == "code" else score
        stale = _staleness(c, l)
        #: The fourth state, which two timestamps cannot produce. `unknown`
        #: on a pair this machine has never synced, which is most of them
        #: the first time and is why `staleness` stays exactly as it was -
        #: this is an extra fact on the row, not a replacement for one.
        divergence = sync_state.verdict_for(
            _sync_points, c.get("id"), l.get("path"),
            c.get("mtime"), l.get("mtime"))
        #: What a content comparison last found about these two, if it still
        #: describes them. This is what stops him being asked the same
        #: question after every reload: the answer is on the row when the
        #: list is built, rather than only in the page that asked for it.
        comparison = sync_state.comparison_for(
            _sync_points, c.get("id"), l.get("path"),
            c.get("mtime"), l.get("mtime"))
        matched.append({"cloud": c, "local": l, "matchType": mtype,
                        "score": round(min(disp, 1.0), 2),
                        "namesDiffer": c["name"].strip() != l["name"].strip(),
                        "staleness": stale,
                        "divergence": divergence,
                        "comparison": comparison,
                        "differenceKind": _difference(c, l, stale)})

    def _resolve_pass(cands, conflicts, mtype, base):
        """Take the strongest candidates first, whoever Ekahau listed first.

        Each pass used to walk the cloud projects in listing order and let
        every one take its own best local file as it was reached. There is no
        global view in that: a weaker claimant considered earlier took a file
        a later one matched far better. And `get_projects` returns the listing
        unsorted, so the order moves whenever any project is saved - same data,
        different pairing, with nothing on screen to explain the change.

        Scoring every candidate and taking them strongest-first makes the
        answer a property of the names. Ties break on the two names, so it is
        stable rather than merely better.
        """
        taken_cloud, taken_local = set(), set()
        cands.sort(key=lambda t: (-t[0], str(t[1].get("name") or ""),
                                  str(t[2].get("name") or "")))
        for sim, c, l in cands:
            if id(c) in taken_cloud or id(l) in taken_local:
                continue
            idx = next((i for i, x in enumerate(unmatched_local) if x is l), None)
            if idx is None:
                continue
            taken_cloud.add(id(c))
            taken_local.add(id(l))
            _take(c, idx, mtype, base + sim)

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
            #: **The id outranks a not-a-match, deliberately.** A not-a-match
            #: is his statement about two particular files, keyed on cloud id
            #: and local path, and nothing prunes it when the file at that path
            #: goes. Delete a local .esx and download the cloud project into
            #: the same folder and the new file carries Ekahau's own project
            #: id - which is proof that these are one project record, not a
            #: heuristic - and the entry went on refusing the pair with
            #: nothing on screen saying why. Every weaker pass still honours
            #: it; there is nothing stronger than the id to overrule it with.
            hit = next((i for i, l in enumerate(unmatched_local)
                        if (l.get("projectId") or "").strip().lower() == cid),
                       None)
            if hit is not None:
                _take(c, hit, "id")
                continue
        still_after_id.append(c)


    #: Case and run-of-spaces folded, which is what this pass has always
    #: claimed to do - "exact name equality (case + whitespace normalized)".
    #: It compared the raw strings, so a pair differing only in capitals fell
    #: through to `fuzzy`, and `fuzzy` is excluded from both PUSHABLE and
    #: PULLABLE - so Local -> Cloud was greyed out for two names that read the
    #: same word for word. `namesDiffer` still reports the real spelling
    #: difference, so the rename is still offered.
    def _norm_name(s):
        return re.sub(r'\s+', ' ', str(s or '')).strip().casefold()

    pending = []
    for c in still_after_id:
        cn = _norm_name(c["name"])
        hit = next((i for i, l in enumerate(unmatched_local)
                    if cn == _norm_name(l["name"]) and not _blocked(c, l)), None)
        if hit is not None:
            _take(c, hit, "exact", 3.0)
        else:
            pending.append(c)


    #: A shared site code says these two are at the same place. It does not
    #: say they are the same project, and nothing checked the second half -
    #: so "SITE2 Rooftop Antenna Replacement" paired with "SITE2 Basement
    #: Parking Garage" at a name similarity of 0.14, while the badge told him
    #: "the site codes match and the names are close". Those pairs carry
    #: `namesDiffer`, so Sync then offered to rename one to the other.
    #:
    #: The floor is well under the fuzzy pass's 0.5, because the shared code
    #: is real evidence and this pass should stay more generous than matching
    #: on wording alone - it only has to exclude the pairs with nothing in
    #: common at all.
    _CODE_SIM_FLOOR = 0.3

    still = []
    code_cands, code_conflicts = [], {}
    for c in pending:
        cloud_code = c.get("code") or extract_site_code(c["name"])
        if not cloud_code:
            continue
        for l in unmatched_local:
            if _blocked(c, l):
                continue
            lcode = l.get("code") or extract_site_code(l["name"])
            if not (lcode and lcode == cloud_code):
                continue
            sim = fuzzy_similarity(c["name"], l["name"])
            reason = discriminators_reason(c["name"], l["name"])
            if not reason and sim < _CODE_SIM_FLOOR:
                reason = ("Same site code, but the names have nothing else in "
                          "common")
            if reason:
                prev = code_conflicts.get(id(c))
                if not prev or sim > prev[2]:
                    code_conflicts[id(c)] = (c, l, sim, reason)
                continue
            code_cands.append((sim, c, l))

    _resolve_pass(code_cands, code_conflicts, "code", 2.0)

    for c in pending:
        if any(m["cloud"] is c for m in matched):
            continue
        held = code_conflicts.get(id(c))
        if held and held[1] in unmatched_local:
            held_back.append({"cloud": c, "local": held[1],
                              "reason": held[3], "via": "code"})
        still.append(c)


    unmatched_cloud = []
    fuzzy_cands, fuzzy_conflicts = [], {}
    for c in still:
        for l in unmatched_local:
            if _blocked(c, l):
                continue
            sim = fuzzy_similarity(c["name"], l["name"])
            if sim <= 0.5:
                continue
            reason = discriminators_reason(c["name"], l["name"])
            if reason:
                prev = fuzzy_conflicts.get(id(c))
                if not prev or sim > prev[2]:
                    fuzzy_conflicts[id(c)] = (c, l, sim, reason)
                continue
            fuzzy_cands.append((sim, c, l))

    #: Strongest-first, so the answer does not depend on Ekahau's listing
    #: order - see `_resolve_pass`.
    _resolve_pass(fuzzy_cands, fuzzy_conflicts, "fuzzy", 0.0)

    for c in still:
        if any(m["cloud"] is c for m in matched):
            continue
        held = fuzzy_conflicts.get(id(c))
        if held and held[1] in unmatched_local:
            l = held[1]
            already = any(h["cloud"].get("id") == c.get("id")
                          and h["local"].get("path") == l.get("path")
                          for h in held_back)
            if not already:
                held_back.append({"cloud": c, "local": l,
                                  "reason": held[3], "via": "fuzzy"})
        unmatched_cloud.append(c)


    #: Say when "nothing on disk" is really "you said these are not the
    #: same project".
    #:
    #: A rejected pairing is honoured by every pass, so the cloud project
    #: falls through to `cloudOnly` and the row states, as a fact about the
    #: disk, something that is actually a record of his own decision. When
    #: the two names agree the download then refuses with "already exists",
    #: and the list and the downloader are flatly contradicting each other
    #: on the one question he is acting on.
    #:
    #: The matcher already knows; it was not saying. `_blocked` is re-asked
    #: rather than a note being carried out of the passes, because a pair can
    #: be vetoed in any of them and a flag threaded through four loops is a
    #: flag one of them will forget to set.
    if excluded:
        for c in unmatched_cloud:
            for l in unmatched_local:
                if _blocked(c, l):
                    c["rejectedPairing"] = True
                    c["rejectedLocalPath"] = l.get("path") or ""
                    c["rejectedLocalName"] = l.get("name") or ""
                    break

    #: And the more general case, which needs no decision from him at all.
    #:
    #: A rejected pairing is one way a cloud project ends up unpaired next to
    #: a file of its own name. The other is that **the file is already
    #: somebody else's**: two cloud projects sharing a name, the first taking
    #: the local file by id, the second correctly landing here. Downloading
    #: the second then refuses, and the row has just said nothing is on disk.
    #:
    #: Measured rather than assumed - it reproduces with no entry in
    #: `not_matches.json`, which makes it the likelier of the two after a
    #: bulk cloud rename.
    #:
    #: This is the downloader's question - "is there a file of this name" -
    #: answered by the half of the tool that has already scanned the disk, so
    #: the two stop disagreeing. It does not claim the download *will*
    #: collide: that also depends on the folder, and saying "a file of this
    #: name is on disk, here" is both true and the thing he needs to see.
    _by_stem = {}
    for l in local_items:
        _by_stem.setdefault(_norm_name(l.get("name") or ""), l)
    for c in unmatched_cloud:
        if c.get("rejectedPairing"):
            continue
        hit = _by_stem.get(_norm_name(c.get("name") or ""))
        if hit:
            c["nameCollision"] = True
            c["collidingLocalPath"] = hit.get("path") or ""
            c["collidingLocalName"] = hit.get("name") or ""

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
                 #: Same reasoning as the cloud side above - no size.
              "meta": _row_meta(0, int(f.get("mtime") or 0))}
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

        # The site is rendered as its own thing on the row - see `locationHtml`
        # in cloud.js. Repeating it here put the site name on the row three
        # times over: in the project's name, on the cloud meta and on the local
        # meta, which is what wrapped the name onto a second line.
        # No size: it is the same number on both sides of every row and is
        # not what he decides with. The name, where it lives and when it was
        # saved are the row; the rest is in the menu.
        meta = _row_meta(0, mtime)
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
              #: Same reasoning as the cloud side above.
              "meta": _row_meta(int(f.get("size") or 0), int(f.get("mtime") or 0))}
             for f in get_local_esx_files(output_dir)]
    mm_map, _ = manual_matches_map()

    #: Drop sync points for projects that are no longer in the account.
    #:
    #: Safe *here* and nowhere obvious else: this listing is the whole
    #: account. The owner filter is applied in the browser, so `cloud` holds
    #: every project the signed-in user can see - pruning against a filtered
    #: list would throw away good records for projects that still exist.
    #: `prune` writes only when something actually goes, so the ordinary
    #: refresh touches no file.
    try:
        sync_state.prune([c.get("id") for c in cloud if c.get("id")])
    except Exception as e:
        applog.note_failure("pruning sync points", e)

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


def _rewrite_project_json(src, mutate):
    """Rewrite `project.json` inside a .esx, copying every other member across
    byte for byte, in its original order.

    `mutate(proj, doc)` edits the `project` record in place and returns True
    when it changed something. **Returning False writes nothing at all** - no
    temp file, no replace - which is what lets every caller be re-run after an
    interruption without doing a second round of work on a file that is
    already correct.

    Nothing is copied aside first. The rebuild goes to a temp file and is
    renamed over the top, so the `.esx` is either entirely the old one or
    entirely the new one, and the only field being changed is the project's
    name - which the cloud also holds.

    Extracted from `set_internal_project_name` when a second caller needed the
    same careful part: rebuild preserving every entry's own metadata, replace
    atomically, drop the caches.
    """
    import zipfile

    src = Path(src)
    try:
        with zipfile.ZipFile(_lp().write_path(src)) as zf:
            if "project.json" not in zf.namelist():
                return {"error": "That .esx has no project.json"}
            members = [(i, zf.read(i.filename)) for i in zf.infolist()]
    except (OSError, zipfile.BadZipFile) as e:
        return {"error": "Could not read the .esx: %s" % e}

    changed = False
    rebuilt = []
    for info, raw in members:
        if info.filename == "project.json":
            try:
                doc = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                return {"error": "project.json could not be read: %s" % e}
            proj = doc.get("project")
            if not isinstance(proj, dict):
                return {"error": "project.json has no project record"}
            try:
                changed = bool(mutate(proj, doc))
            except ValueError as e:
                return {"error": str(e)}
            if changed:
                raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        rebuilt.append((info, raw))

    if not changed:
        return {"ok": True, "unchanged": True, "path": str(src)}

    #: Written to a temp file and renamed over the top, so the .esx is either
    #: the old one or the new one and never half of either. That atomicity is
    #: what a copy-aside used to be insurance against, and it is the better
    #: half of the two: a copy aside protects a write that already went
    #: wrong; this stops it going wrong.
    tmp = src.with_suffix(src.suffix + ".wd-rename.tmp")
    #: The temp file is the .esx path plus 14 characters, so on the projects
    #: whose names are longest it is the thing that crosses MAX_PATH even when
    #: the .esx itself did not. See `longpath.write_path`.
    _bm = _lp()
    tmp_w, src_w = _bm.write_path(tmp), _bm.write_path(src)
    try:
        with zipfile.ZipFile(tmp_w, "w", zipfile.ZIP_DEFLATED) as out:
            for info, raw in rebuilt:
                # Carry the original entry across rather than letting
                # zipfile invent one: same name, same date, same compression.
                keep_info = zipfile.ZipInfo(info.filename, info.date_time)
                keep_info.compress_type = info.compress_type
                keep_info.external_attr = info.external_attr
                out.writestr(keep_info, raw)
        os.replace(tmp_w, src_w)
    except OSError as e:
        try:
            os.unlink(tmp_w)
        except OSError:
            pass
        #: `describe_failure` rather than `%s` - see its own docstring. This
        #: was the message that reached him as
        #: "[Errno 2] No such file or directory: 'C:\Users\...'".
        return {"error": "Write failed, the file is untouched. "
                         + _bm.describe_failure(e, tmp)}

    _ESX_META_CACHE.pop(str(src), None)
    _ESX_TYPE_CACHE.pop(str(src), None)
    return {"ok": True, "unchanged": False, "path": str(src)}


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


#: Ekahau answers per address with free text. There is no status code in
#: there, so "did it work" is read off the wording - and the default has to be
#: success, because the common case is an empty string and treating that as a
#: failure would report every working share as broken.
_SHARE_FAILURE_WORDS = ("not found", "invalid", "error", "failed", "cannot",
                        "could not", "unable", "does not exist", "denied")

#: Ekahau's own wording when it has done the thing. "Invitation sent" is how it
#: answers a share with somebody outside the account - a success whose text
#: also contains "not found", which is why success is looked for first.
_SHARE_SUCCESS_WORDS = ("invitation sent", "invite sent", "added", "shared",
                        "success")


def share_message_verdict(message) -> str:
    """`ok`, `failed` or `unknown` for one address's reply.

    This used to answer a plain boolean by searching for the nine failure
    words above and calling everything else a success. That is wrong in both
    directions, and quietly so:

    * "Access is forbidden", "No such user", "403 Forbidden" and "Share limit
      reached" contain none of the nine, so a refused share was reported as
      done - and the address was then written into Recent Recipients, which is
      the one thing that store exists to prevent.
    * "User not found - invitation sent" contains "not found", so Ekahau's
      external-invite *success* was reported as a failure.

    The answer is not a longer word list, because there is no published list of
    what this endpoint can say. It is to stop rounding: a reply nobody
    recognises is `unknown`, the caller says so, and Ekahau's own words are
    carried through to the person who can read them. An empty reply stays the
    quiet success it has always been, which is what the ordinary case sends.
    """
    text = str(message or "").strip().lower()
    if not text:
        return "ok"
    if any(word in text for word in _SHARE_SUCCESS_WORDS):
        return "ok"
    if any(word in text for word in _SHARE_FAILURE_WORDS):
        return "failed"
    return "unknown"


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
            # The overrides travel with the listing rather than being fetched
            # separately: the row styling, the dashboard counts and the owner
            # filter all read them, and a second round trip means a window
            # where the page has the projects and not the answer to "is this
            # one mine", which is when it would draw the list wrong once.
            data["externalOverrides"] = external_overrides_map()
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

    def replace_cloud_project(self, esx_path, cloud_project_id, progress_cb=None):
        """Put a local .esx up over an existing cloud project.

        "why can't we just automatically delete that first and then upload the
        new one? I mean why do we have to consider that we can only do one
        step at a time?"

        Composing the calls is the answer. **The order is inverted from the way
        he said it, on purpose.** Deleting first means a failed upload leaves
        nothing in the cloud - his local copy survives, but the shared copy
        other people work from is gone and he may not find out until somebody
        asks. Uploading first means a failure leaves a duplicate: visible,
        annoying, and removable in one click. The safer way round, same result.

        So: upload, **verify the new one is really there and really his file**,
        and only then delete the old. Nothing is deleted until the replacement
        is confirmed good.

        Why this is a composition rather than one call. Nothing replaces a
        project's content: `upload/initiate` takes a filename and no project
        id and `commit` takes only the upload id, so that flow can only
        create. `batch/update` does write in place - it is how renaming works -
        but it is JSON, and a project's floor plans are binary images fetched
        from S3 by id during download. A JSON document write cannot carry a
        re-cropped plan, which is exactly what his edits change.

        Returns a dict that always says what actually happened, step by step.
        """
        if not self._ensure():
            return {"error": "Not connected"}
        if not cloud_project_id:
            return {"error": "No cloud project to replace"}

        try:
            before = {p["id"]: p for p in self.api.get_projects()}
        except Exception as e:
            return {"error": "Could not read the cloud project list: %s" % e}
        old = before.get(cloud_project_id)
        if not old:
            return {"error": "That cloud project is no longer there - "
                             "refresh and try again."}
        old_name = (old.get("name") or "").strip()

        #: **Which side is newer is re-read here, not taken from the client.**
        #: The pull direction has had this since it was written, and says why:
        #: the ledger's `staleness` is a snapshot from when the list was
        #: drawn, and the server wins because it just re-read both. The push
        #: had no such check - not one reference to a date anywhere in this
        #: function - and it is the push that deletes.
        #:
        #: The gap is an ordinary morning: the ledger says local is newer at
        #: 08:55, the cloud copy is saved from Ekahau at 08:58, Local -> Cloud
        #: runs at 09:00. Nothing is kept, and a cloud delete does not come
        #: back.
        #:
        #: Refused *before* the upload, so a refusal does not also leave a
        #: duplicate behind. Both dates are returned so the row can say which
        #: is which rather than only that it declined.
        try:
            fs_mtime = int(Path(esx_path).stat().st_mtime)
        except OSError:
            fs_mtime = 0
        local_internal_mtime = (_esx_meta(Path(esx_path), fs_mtime)
                                .get("internalMtime") or fs_mtime)
        cloud_mtime = _parse_cloud_mtime(old)
        _NEWER_TOLERANCE_S = 60
        #: A missing date is Ekahau not saying, which is not Ekahau saying
        #: newer - a guard that fired on that would refuse his ordinary case.
        if (local_internal_mtime and cloud_mtime
                and cloud_mtime > local_internal_mtime + _NEWER_TOLERANCE_S):
            return {
                "error": "cloud_newer",
                "step": "direction",
                "deletedOld": False,
                "oldId": cloud_project_id,
                "message": ("The cloud copy of \"%s\" has been saved since this "
                            "list was drawn, so it is newer than your local "
                            "file. Replacing it would throw that away, and a "
                            "cloud delete cannot be undone. Nothing was "
                            "uploaded and nothing was deleted."
                            % (old_name or "that project")),
                "localMtime": local_internal_mtime,
                "cloudMtime": cloud_mtime,
            }

        site_id = None
        try:
            for entry in self.api.get_dataset_listing():
                if entry.get("id") == cloud_project_id:
                    site_id = entry.get("siteId")
                    break
        except Exception:
            site_id = None

        # ---- 1. upload, into the same site when we know it ---------------
        if progress_cb:
            progress_cb(stage="upload", current=5, total=100,
                        message="Uploading over %s..." % old_name)
        up = self.upload_project(esx_path, site_id=site_id,
                                 progress_cb=_remap_progress(progress_cb, 5, 70))
        if not isinstance(up, dict) or up.get("error"):
            return {"error": (up or {}).get("error", "Upload failed"),
                    "step": "upload", "deletedOld": False,
                    "note": "Nothing was deleted - the old cloud project is "
                            "untouched."}
        uploaded_as = up.get("renamedTo") or Path(esx_path).stem

        # The key this function reads has to be the key the upload writes.
        #
        # It read `id` / `projectId`. `upload_project` has only ever returned
        # the new project under `datasetId` - on all three of its success
        # paths - so this branch fired on every successful upload, and the
        # replace could never have completed for anybody. Not a race, not a
        # stale internal name, not the owner filter: two functions in this
        # file disagreeing about one key.
        #
        # It survived its tests because they replaced `mgr.upload_project`
        # with a stub returning `{"ok": True, "id": "new-1"}` - a shape the
        # real function does not produce. A stub that invents the contract
        # tests the stub.
        new_id = (up.get("datasetId") or up.get("id")
                  or up.get("projectId") or "")

        # And when the upload genuinely could not name it - its own listing
        # poll timed out - ask the listing again rather than giving up on one
        # read. Ekahau's project list is not instantly consistent after a
        # commit, and the cost of being early is a duplicate this tool created
        # and then could not see.
        if not new_id:
            if progress_cb:
                progress_cb(stage="verify", current=72, total=100,
                            message="Waiting for Ekahau to list the upload...")
            internal = ""
            try:
                internal = (_esx_meta(Path(esx_path),
                                      int(Path(esx_path).stat().st_mtime))
                            .get("projectName") or "")
            except Exception:
                internal = ""
            found = self._await_new_project(
                set(before), esx_path,
                expect_names=(uploaded_as, internal, old_name))
            new_id = found.get("id") or ""
            if found.get("name"):
                uploaded_as = found["name"]

        if not new_id:
            return {"error": "The upload finished, but Ekahau has not listed "
                             "the new project yet, so the old one was left "
                             "alone.",
                    "step": "verify", "deletedOld": False,
                    "uploadedAs": uploaded_as, "oldId": cloud_project_id,
                    "note": "Your local file was uploaded as \"%s\". There are "
                            "almost certainly two copies in the cloud now - "
                            "the older one, and this upload. Refresh in a "
                            "moment, check which is which, and remove the one "
                            "you do not want." % uploaded_as}

        # ---- 2. verify before destroying anything ------------------------
        if progress_cb:
            progress_cb(stage="verify", current=75, total=100,
                        message="Checking the upload landed...")
        check = self._verify_uploaded(new_id, esx_path)
        if not check.get("ok"):
            return {"error": "The upload could not be verified, so the old "
                             "project was left alone: " + check.get("why", ""),
                    "step": "verify", "deletedOld": False, "newId": new_id,
                    "uploadedAs": uploaded_as, "oldId": cloud_project_id,
                    # Name it. "Something unidentifiable exists" is the one
                    # thing he cannot act on, and it is the report he got.
                    "note": "There are now two copies. The new one is your "
                            "local file, uploaded as \"%s\"; the other is the "
                            "older cloud copy. Nothing was deleted."
                            % uploaded_as}

        # ---- 3. only now, the old one ------------------------------------
        if progress_cb:
            progress_cb(stage="delete", current=90, total=100,
                        message="Removing the old %s..." % old_name)
        try:
            self.api.delete_project(cloud_project_id)
        except Exception as e:
            # The dangerous silence. Say there are two, and say which is new.
            return {"ok": False, "step": "delete", "deletedOld": False,
                    "newId": new_id, "oldId": cloud_project_id,
                    "error": "The new copy uploaded correctly, but the old one "
                             "could not be removed: %s" % e,
                    "note": "There are now two projects named %s. The newer "
                            "one is the good copy; delete the other when you "
                            "can." % (old_name or "the same thing")}

        if progress_cb:
            progress_cb(stage="done", current=100, total=100, message="Done.")

        # A share is keyed to the project id, and this operation deliberately
        # creates a new project rather than editing the old one in place - so
        # whoever the old copy was shared with loses it, silently, at the
        # moment the replace succeeds. Nothing here re-applies them: sharing
        # people's projects on their behalf is not a side effect an upload
        # should have. It is said instead, with the names, so the loss is
        # visible at the moment it happens rather than when somebody asks
        # why they cannot open it.
        #: A replace makes the two sides identical too, so it records the
        #: same note the pull does - under the **new** id, because this
        #: creates a project rather than writing in place. The old entry is
        #: left for `prune` rather than deleted here: the delete above may
        #: have failed, and forgetting a pair that still exists would be a
        #: fact thrown away to tidy up.
        try:
            src_p = Path(esx_path)
            fs_m = int(src_p.stat().st_mtime)
            sync_state.record(new_id, str(src_p),
                              _parse_cloud_mtime(check.get("project") or {})
                              or fs_m,
                              _esx_meta(src_p, fs_m).get("internalMtime") or fs_m,
                              direction="push")
        except Exception as e:
            applog.note_failure("recording the sync point", e)

        lost = [s for s in (old.get("sharedWith") or []) if s]
        out = {"ok": True, "newId": new_id, "oldId": cloud_project_id,
               "name": check.get("name") or old_name,
               "deletedOld": True, "siteId": site_id,
               "renamedTo": up.get("renamedTo")}
        if lost:
            out["lostShares"] = lost
            out["note"] = ("The old copy was shared with %d %s. A share belongs "
                           "to the project it was made on, so the new copy does "
                           "not carry them - re-share it with %s."
                           % (len(lost), "person" if len(lost) == 1 else "people",
                              ", ".join(lost)))
        return out

    # How long to keep asking Ekahau's listing about something we know we
    # just wrote. Short, rising gaps rather than one long sleep: the usual
    # case answers on the first read and costs nothing.
    _LISTING_BACKOFF_S = (0.0, 1.0, 2.0, 3.0, 5.0)

    def _await_new_project(self, before_ids, esx_path, expect_names=(),
                           progress_cb=None):
        """The project this upload created, once the listing admits it exists.

        Only reached when the upload could not name what it made, and the
        alternative is telling him something unidentifiable is in his account.

        **It has to be the right one, because what happens next is a delete.**
        "a project that was not there a minute ago" is not good enough on an
        account other people also write to - the upload of a large file is a
        long window, and taking the first new row would eventually delete his
        old project on the strength of somebody else's new one. So a candidate
        is accepted on evidence:

        * the local file's own internal project id. `upload_project` has
          already downloaded the cloud copy back over it, so the id inside it
          now names the project that was just created. This is positive
          identification and is tried first.
        * failing that, **exactly one** new project, whose name is one we
          expect - what he called the file, or the name Ekahau would have
          taken from inside it.

        Anything else returns nothing, and the caller says so rather than
        guessing. Refusing costs him a duplicate to tidy; guessing costs him
        a project.
        """
        wanted = ""
        try:
            src = Path(esx_path)
            wanted = (_esx_meta(src, int(src.stat().st_mtime))
                      .get("projectId") or "")
        except Exception:
            wanted = ""
        names = {n.strip().lower() for n in expect_names if n and n.strip()}

        waited = 0.0
        for wait in self._LISTING_BACKOFF_S:
            if wait:
                time.sleep(wait)
                waited += wait
                if progress_cb:
                    progress_cb(message="Waiting for the cloud listing to "
                                        "show the upload (%ds)…" % int(waited))
            try:
                fresh = [p for p in self.api.get_projects()
                         if p.get("id") not in before_ids]
            except Exception:
                continue
            if not fresh:
                continue
            if wanted:
                # `_esx_meta` lowercases the id it reads out of the .esx and
                # Ekahau's listing does not, so this compares folded or it
                # silently never matches.
                for p in fresh:
                    if (p.get("id") or "").strip().lower() == wanted:
                        return {"id": p.get("id"),
                                "name": (p.get("name") or "").strip(),
                                "how": "the id inside the local file"}
            if len(fresh) == 1:
                p = fresh[0]
                if (p.get("name") or "").strip().lower() in names:
                    return {"id": p.get("id") or "",
                            "name": (p.get("name") or "").strip(),
                            "how": "the only new project, and it is named "
                                   "what we uploaded"}
            # More than one new project, or one we cannot account for: keep
            # looking until the budget runs out, then refuse.
        return {}

    def _verify_uploaded(self, new_id, esx_path):
        """Is the project the upload says it created actually in the listing?

        Scope, stated plainly because the docstring here used to claim more
        than the code does: this confirms **that id is present**. It does not
        compare contents, and it cannot compare the .esx's own internal
        project id against it, because Ekahau assigns a fresh id on upload -
        the local file only carries it after the sync-back, and that is used
        for identification in `_await_new_project`, not here.

        Asked more than once, because a listing that has not caught up yet and
        an upload that failed are the same answer on a single read - and they
        have opposite consequences. Being early used to mean refusing to
        delete a project that was perfectly replaceable, which leaves him with
        the duplicate he fears.
        """
        found = None
        why = "the new project is not in the listing"
        for wait in self._LISTING_BACKOFF_S:
            if wait:
                time.sleep(wait)
            try:
                listing = {p["id"]: p for p in self.api.get_projects()}
            except Exception as e:
                why = "could not re-read the project list (%s)" % e
                continue
            found = listing.get(new_id)
            if found:
                break
        if not found:
            return {"ok": False, "why": why}
        try:
            src = Path(esx_path)
            local_id = _esx_meta(src, int(src.stat().st_mtime)).get("projectId")
        except Exception:
            local_id = ""
        return {"ok": True, "name": (found.get("name") or "").strip(),
                "localProjectId": local_id}


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

            def _remap(cb, lo, hi):
                """Wrap progress_cb to remap 0-100 → lo-hi."""
                if not cb:
                    return None
                def inner(**kw):
                    if "current" in kw:
                        frac = kw["current"] / max(kw.get("total", 100), 1)
                        kw["current"] = int(lo + frac * (hi - lo))
                        kw["total"] = 100
                    cb(**kw)
                return inner

            result = self.api.upload_project(
                esx_path, progress_cb=_remap(progress_cb, 0, 55))
            if isinstance(result, dict) and result.get("error"):
                return result


            #: **Identified on evidence, never on "it was not there a minute
            #: ago".** `_await_new_project` states the rule and the reason it
            #: exists; this used to take `new_ones[0]` instead, which is the
            #: thing that docstring forbids in those words.
            #:
            #: The diff is taken before the upload and read after it, so the
            #: window is as long as a multi-megabyte transfer. On an account
            #: other people also write to, the first new row is as likely to
            #: be a colleague's upload as ours - and what follows renames it
            #: to his filename, files it into his site, downloads it back over
            #: his local .esx, and, when the caller is `replace_cloud_project`,
            #: deletes the project it is supposedly replacing. Refusing costs
            #: a duplicate to tidy; guessing costs a project.
            #:
            #: Both spellings of the name count, because Ekahau names the new
            #: project from `project.json` inside the .esx while the rename
            #: below moves it to the filename - so at this moment it may
            #: legitimately be called either.
            expect = [Path(esx_path).stem]
            try:
                src = Path(esx_path)
                internal = (_esx_meta(src, int(src.stat().st_mtime))
                            .get("projectName") or "")
            except Exception:
                internal = ""
            if internal:
                expect.append(internal)

            found = self._await_new_project(
                before_ids, esx_path, expect_names=expect,
                progress_cb=progress_cb) or {}
            new_id = found.get("id") or None
            new_project = ({"id": new_id, "name": found.get("name") or ""}
                           if new_id else None)


            renamed_to = None
            if new_id and new_project:
                desired_name = Path(esx_path).stem
                cloud_name = (new_project.get("name") or "").strip()
                if desired_name and cloud_name and cloud_name != desired_name:
                    try:
                        if progress_cb:
                            progress_cb(current=62,
                                        message=f"Renaming cloud project → \"{desired_name}\"…")
                        self.api.rename_project(new_id, desired_name)
                        renamed_to = desired_name
                    except Exception as e:


                        renamed_to = None


            if site_id and new_id:
                try:
                    if progress_cb:
                        progress_cb(current=65,
                                    message="Assigning project to site…")
                    self.api.assign_to_site(site_id, new_id)
                    ret = {"ok": True, "assigned": True, "siteId": site_id,
                           "datasetId": new_id}
                    if renamed_to:
                        ret["renamedTo"] = renamed_to
                except Exception as e:
                    ret = {"ok": True, "uploaded": True, "datasetId": new_id,
                           "assignError": str(e),
                           "renamedTo": renamed_to,
                           "warning": f"Uploaded but couldn't assign to site: {e}"}
            elif not new_id:


                #: The upload itself succeeded - the file is in the account.
                #: What could not be established is *which* project it is, so
                #: nothing was renamed, nothing was filed into a site, and
                #: nothing was written back over the local file. Say that,
                #: rather than "not yet visible", which invites a retry that
                #: would upload it a second time.
                return {"ok": True, "uploaded": True,
                        "identified": False,
                        "warning": "Uploaded, but the new project could not be "
                                   "identified in the cloud listing — so it has "
                                   "not been renamed, filed into a site, or "
                                   "synced back. Check Ekahau Cloud before "
                                   "uploading it again."}
            else:
                ret = {"ok": True, "uploaded": True, "datasetId": new_id}
                if renamed_to:
                    ret["renamedTo"] = renamed_to

            # ── Sync-back: download the cloud copy over the local file ──
            # The cloud assigns its own project ID and metadata to the
            # uploaded file. Downloading it back makes the local copy
            # byte-identical to the cloud, so future Cloud Manager
            # refreshes see "Same file" instead of a name-only match.
            if new_id:
                try:
                    if progress_cb:
                        progress_cb(current=68,
                                    message="Syncing cloud copy back to local…")

                    dl = self.api.download_project(
                        new_id, progress_cb=_remap(progress_cb, 68, 96))
                    if isinstance(dl, dict) and dl.get("error"):
                        ret["syncBackError"] = dl["error"]
                        ret.setdefault("warning",
                                       f"Uploaded OK, but sync-back failed: {dl['error']}")
                    else:
                        esx_bytes = dl["esx"]
                        src = Path(esx_path)
                        if progress_cb:
                            progress_cb(current=97,
                                        message="Replacing local file with cloud copy…")
                        tmp = src.with_suffix(src.suffix + ".wd-syncback.tmp")
                        with open(tmp, "wb") as f:
                            f.write(esx_bytes)
                        os.replace(tmp, src)
                        _ESX_META_CACHE.pop(str(src), None)
                        _ESX_TYPE_CACHE.pop(str(src), None)
                        ret["syncedBack"] = True
                except Exception as e:
                    ret["syncBackError"] = str(e)
                    ret.setdefault("warning",
                                   f"Uploaded OK, but sync-back failed: {e}")

            if progress_cb:
                progress_cb(current=100, message="Done.")
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

    def download_project(self, project_id, dest_folder_name, progress_cb=None,
                         on_exists="refuse"):
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
            #: A refusal he can act on.
            #:
            #: This said `'<name>' already exists in <folder>` and stopped -
            #: no path, no options, and nothing downstream able to tell it
            #: apart from a network failure. It is worse than a dead end when
            #: the list has just called the project cloud-only, which happens
            #: when he has marked the pair as not-a-match: the two halves of
            #: the tool then contradict each other and neither offers a way
            #: through.
            #:
            #: `on_exists` is explicit and defaults to refusing. An
            #: unrecognised value refuses too - a typo in a caller must never
            #: become an overwrite.
            replaced = bool(target.exists() and on_exists == "overwrite")
            if target.exists():
                if on_exists == "keepboth":
                    target = _timestamped_path(target, int(time.time()))
                elif on_exists == "overwrite":
                    pass
                elif on_exists == "refuse":
                    return {"error": f"'{safe_name}' already exists in "
                                     f"{safe_folder}",
                            "code": "exists",
                            "existingPath": str(target),
                            "existingName": safe_name,
                            "folder": safe_folder}
                else:
                    return {"error": f"Unknown choice for an existing file: "
                                     f"{on_exists!r}. Nothing was written."}
            _assert_inside(target, dest_dir)
            if progress_cb:
                progress_cb(stage="save", current=97, total=100,
                            message=f"Saving {safe_name} to disk…")
            with open(target, "wb") as f:
                f.write(esx_bytes)
            if progress_cb:
                progress_cb(stage="done", current=100, total=100,
                            message="Done.")
            #: `replaced` so the caller can say which of the two things
            #: it did - writing a new file and overwriting one are not
            #: the same event to report.
            return {"ok": True, "path": str(target), "name": proj_name,
                    "replaced": replaced}
        except Exception as e:
            return {"error": str(e)}

    def verify_replace_local(self, project_id, local_path, progress_cb=None):
        """Download the cloud project's current content over the local .esx.

        This is what "Cloud newer" means in practice: the cloud copy was edited
        after the local one, and this brings the local file up to date. After it
        runs both files carry the same internal project.json.id, so a pair that
        matched only by name upgrades to "Same file" on the next refresh.

        **No copy of the local file is kept.** The cloud copy is what replaces
        it, so the cloud is the other copy - keeping a third would be a backup
        of a backup. The safe-direction refusal below is what actually
        protects local work, and it is a refusal rather than a copy.

        Safe direction only: refuses if local's internal modifiedAt is
        meaningfully newer than cloud's. Sending local up to an existing cloud
        project is not implemented; the upload flow only creates new projects.

        Returns {"ok": True, "path", "localMtime", "cloudMtime", ...}
        on success, {"error": "local_newer", ...} when the safe direction does
        not apply, or {"error": <msg>} on other failures."""
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
            resp = self.api.get(f"{API_BASE}/{project_id}")
            if resp.status_code in (401, 403):
                return {"error": "Ekahau Cloud sign-in has expired. "
                                 "Sign in again in your browser, then reconnect."}
            if resp.status_code == 404:
                return {"error": "That project is no longer in Ekahau Cloud - "
                                 "it may have been deleted or unshared. "
                                 "Nothing was changed locally."}
            proj = resp.json()
        except Exception as e:
            return {"error": f"Could not reach Ekahau Cloud: {e}. "
                             "Nothing was changed locally."}
        cloud_mtime = _parse_cloud_mtime(proj)
        cloud_name = proj.get("name") or proj.get("title") or ""


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
            return {"error": f"Download failed: {e}. Nothing was changed locally."}
        if isinstance(result, dict) and result.get("error"):
            return result
        esx_bytes = result["esx"]


        #: **No copy is kept, and that is the decision rather than an
        #: omission.** This replaces a local `.esx` with the copy Ekahau Cloud
        #: is holding, so the cloud *is* the other copy - a backup here would
        #: be a backup of a backup. It only runs when the cloud side is the
        #: newer of the two; the direction that would overwrite newer local
        #: work is refused higher up, by name.
        tmp = src.with_suffix(src.suffix + ".wd-verify.tmp")
        #: Same length problem as the rename path - see `longpath.write_path`.
        _bm = _lp()
        tmp_w, src_w = _bm.write_path(tmp), _bm.write_path(src)
        try:
            if progress_cb:
                progress_cb(stage="save", current=95, total=100,
                            message="Replacing local file…")
            with open(tmp_w, "wb") as f:
                f.write(esx_bytes)
            os.replace(tmp_w, src_w)
        except OSError as e:
            try:
                os.unlink(_bm.write_path(tmp))
            except OSError:
                pass
            return {"error": "Write failed, local file untouched. "
                             + _bm.describe_failure(e, tmp)}


        _ESX_META_CACHE.pop(str(src), None)
        _ESX_TYPE_CACHE.pop(str(src), None)

        new_fs_mtime = int(src.stat().st_mtime)
        new_meta = _esx_meta(src, new_fs_mtime)

        #: The two sides are identical as of this moment, which is the only
        #: thing worth recording. Everything downstream that wants to say
        #: "both of you changed it" compares against this pair of numbers.
        #: A failure to write the note must not fail the download that
        #: already succeeded - the pair simply reads `unknown` next time,
        #: which is where it started.
        try:
            sync_state.record(project_id, str(src), cloud_mtime,
                              new_meta.get("internalMtime") or new_fs_mtime,
                              direction="pull")
        except Exception as e:
            applog.note_failure("recording the sync point", e)

        if progress_cb:
            progress_cb(stage="done", current=100, total=100, message="Done.")
        return {
            "ok": True,
            "path": str(src),
            "newProjectId": new_meta.get("projectId"),
            "cloudProjectId": project_id,
            "cloudName": cloud_name,
            "localMtime": local_internal_mtime,
            "cloudMtime": cloud_mtime,
            "newLocalMtime": new_meta.get("internalMtime") or new_fs_mtime,
        }


    def set_internal_project_name(self, local_path, new_name, progress_cb=None):
        """Rewrite the project name stored *inside* a local .esx.

        There are three names on a row and only two of them are visible.
        Renaming the file on disk does not touch `project.json`, so after
        renaming a fleet of projects to a new convention every one of them
        reports a difference over a field he cannot see, for ever. This is the
        fix for that, and without it the comparison just produces a permanent
        complaint.

        Only `project.name` and `project.title` change. Every other member is
        copied across byte for byte, in its original order, so the archive is
        the same project with a corrected label - not a re-save.

        Nothing is copied aside first: the rebuild is written to a temp file
        and renamed over the top, so the archive is never half-replaced, and
        the one field being corrected is the name the cloud also holds.
        """
        if not new_name or not str(new_name).strip():
            return {"error": "No name given"}
        new_name = str(new_name).strip()

        src = self._local_esx(local_path)
        if isinstance(src, dict):
            return src

        seen = {}

        def _rename(proj, doc):
            seen["old"] = (proj.get("name") or proj.get("title") or "").strip()
            if seen["old"] == new_name:
                return False
            proj["name"] = new_name
            if "title" in proj:
                proj["title"] = new_name
            return True

        out = _rewrite_project_json(src, _rename)
        if out.get("error"):
            return out
        if out.get("unchanged"):
            return {"ok": True, "unchanged": True, "name": new_name,
                    "path": str(src)}
        return {"ok": True, "path": str(src), "name": new_name,
                "previousName": seen.get("old", "")}

    def _local_esx(self, local_path):
        """Resolve a caller-supplied path to a local .esx we are allowed to
        touch, or return the error dict to hand straight back.

        The containment check is the point. `_assert_inside` is what stops a
        path from the page naming a file outside the configured folder, and
        every writer needs it - so it lives in one place rather than being
        re-typed at each one.
        """
        base = self.config.get("output_dir", "")
        if not base:
            return {"error": "No local folder is set"}
        try:
            _assert_inside(local_path, base)
        except ValueError:
            return {"error": "Local path is outside the configured folder"}
        src = Path(local_path)
        if not src.is_file():
            return {"error": "Local file not found: %s" % local_path}
        return src

    def compare_with_cloud(self, local_path, cloud_project_id,
                           progress_cb=None, cloud_mtime=None):
        """Is the cloud copy actually different, or only differently dated?

        "I don't know why we can't just compare a local file with the cloud
        file ... seems like basic engineering, man." It is, and what had been
        holding it up was aimed at the wrong target: the cloud does not serve a
        stored ZIP - `download_project` assembles one - so two downloads of an
        unchanged project need not be byte-identical, and a local .esx is
        deflated where the cloud stores uncompressed. That rules out hashing
        the *archive*. It says nothing about the *contents*.

        So this downloads the cloud copy and compares member by member, after
        normalising away the fields that move when the design does not.

        **It writes nothing, anywhere.** The cloud copy is bytes in memory and
        `zipfile` reads a `BytesIO`, so no extracted copy of a live project
        ever reaches disk - and none can be left behind if this raises. Twenty
        seven extracted copies were found sitting in a temp folder earlier
        today; that is the failure mode being designed out rather than
        cleaned up after.

        Read-only in both directions. This is a diagnostic: it never touches
        the local file and never writes to the cloud.
        """
        from tools import esx_compare

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
        if not src.is_file():
            return {"error": "Local file not found: %s" % local_path}
        if not cloud_project_id:
            return {"error": "No cloud project to compare against"}

        try:
            local_bytes = src.read_bytes()
        except OSError as e:
            return {"error": "Could not read the local file: %s" % e}

        if progress_cb:
            progress_cb(stage="download", current=5, total=100,
                        message="Fetching the cloud copy to compare\u2026")
        try:
            got = self.api.download_project(
                cloud_project_id, progress_cb=_remap_progress(progress_cb, 5, 85))
        except Exception as e:
            return {"error": "Could not fetch the cloud copy: %s" % e}
        if isinstance(got, dict) and got.get("error"):
            return got

        if progress_cb:
            progress_cb(stage="compare", current=90, total=100,
                        message="Comparing contents\u2026")
        result = esx_compare.compare_esx(local_bytes, got["esx"],
                                         local_file_stem=src.stem)
        if progress_cb:
            progress_cb(stage="done", current=100, total=100, message="Done.")
        result["cloudProjectId"] = cloud_project_id
        result["path"] = str(src)

        # Keep the answer. Without this the verdict lived in the page and
        # nowhere else, so a reload asked him the same question again and
        # discarded a comparison that had downloaded the whole cloud project
        # to reach it.
        #
        # The local date is the one the list is built from -
        # `history.modifiedAt` inside the .esx, falling back to the
        # filesystem - because a fingerprint written against a different
        # number than the list reads would never match and the memory would
        # silently never work.
        #
        # The cloud date comes from the caller: it is the value the row was
        # built with, and the question this record answers is "has either
        # side moved since then". Without one there is nothing to invalidate
        # against, so nothing is stored rather than something that cannot be
        # retired.
        try:
            fs_mtime = int(src.stat().st_mtime)
        except OSError:
            fs_mtime = 0
        local_mtime = _esx_meta(src, fs_mtime).get("internalMtime") or fs_mtime
        result["localMtime"] = local_mtime
        if cloud_mtime:
            try:
                sync_state.record_comparison(
                    cloud_project_id, str(src), cloud_mtime, local_mtime,
                    result)
                result["checkedAt"] = int(time.time())
            except Exception as exc:
                # A comparison he can read now matters more than a record of
                # it, so a store that will not write is logged and skipped.
                applog.note_failure("recording a comparison", exc)
        return result

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
        """One recipient. Kept because callers and tests use it; it delegates."""
        out = self.add_shares(project_id, [email], role)
        if out.get("error"):
            return out
        first = (out.get("results") or [{}])[0]
        return {"ok": True, "email": first.get("email", ""),
                "message": first.get("message", ""),
                "results": out.get("results", [])}

    def add_shares(self, project_id, emails, role="READ_USER"):
        """Several recipients, in one request, reported one by one.

        Ekahau's endpoint has always taken `emailAddresses` as an array - the
        one-at-a-time limit was ours, in the form. So this is a single call
        rather than a loop, and nothing here has to pretend a sequence of
        requests was atomic.

        It also answers per recipient, in `responsePerEmailAddress`, which is
        what makes honest reporting possible: "shared with two of three, and
        here is which one did not" rather than one verdict covering everybody.
        """
        if not self._ensure():
            return {"error": "Not connected"}
        if not project_id:
            return {"error": "projectId is required"}

        wanted, invalid = [], []
        for raw in (emails or []):
            for candidate in share_recipients.split_addresses(str(raw)):
                if share_recipients.looks_like_email(candidate):
                    if candidate not in wanted:
                        wanted.append(candidate)
                elif candidate not in invalid:
                    invalid.append(candidate)
        if not wanted:
            return {"error": "No valid email address to share with."}

        try:
            r = self.api.bulk_add_shares([project_id], wanted, role)
        except Exception as e:
            return {"error": str(e)}

        per_email = {}
        for row in (r or []):
            if isinstance(row, dict):
                per_email.update(row.get("responsePerEmailAddress") or {})

        results, succeeded = [], []
        for email in wanted:
            message = per_email.get(email, "")
            # Ekahau reports a per-address problem as text against that
            # address. An empty entry is the quiet success case, which is what
            # the single-recipient path has always treated it as. Anything it
            # says that we do not recognise is `unknown` - reported as not
            # shared, with its words kept, rather than rounded to yes.
            verdict = share_message_verdict(message)
            ok = verdict == "ok"
            results.append({"email": email, "ok": ok, "verdict": verdict,
                            "message": message})
            if ok:
                succeeded.append(email)
        for email in invalid:
            results.append({"email": email, "ok": False,
                            "message": "That does not look like an email address."})

        if succeeded:
            share_recipients.remember(succeeded)

        return {"ok": bool(succeeded), "results": results,
                "shared": succeeded, "invalid": invalid}


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
        # The same splitter the single-project path uses, so a list pasted
        # into the bulk form behaves identically to one pasted into the other.
        parsed = []
        for raw in (emails or []):
            for candidate in share_recipients.split_addresses(str(raw)):
                if share_recipients.looks_like_email(candidate) and candidate not in parsed:
                    parsed.append(candidate)
        emails = parsed
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
                share_recipients.remember(emails)
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

        #: **`ok` means something happened.** Every failure above is caught
        #: into `emailError` / `groupError`, and this used to set `ok: True`
        #: regardless and never set `error` - which is the only key the page
        #: tests. A rate-limited or rejected bulk share therefore toasted
        #: "Shared with A and B on 8 projects", naming everyone, having shared
        #: with nobody.
        #:
        #: Both halves asked for and both refused is a failure, and says so.
        #: One of two working is a partial, which keeps `ok` and carries the
        #: error alongside so the page can show it.
        wanted_email = bool(emails)
        wanted_group = bool(share_with_group and group_id)
        email_failed = wanted_email and "emailError" in results
        group_failed = wanted_group and "groupError" in results
        nothing_worked = ((email_failed or not wanted_email)
                          and (group_failed or not wanted_group))
        if nothing_worked:
            why = results.get("emailError") or results.get("groupError") or "unknown"
            return {"error": "Nothing was shared: %s" % why, **results}
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
            #: **An empty body on a 2xx is Ekahau agreeing.** This endpoint
            #: answers with no body, so `.get(project_id)` was `None` and a
            #: transfer that had *happened* - and that this tool cannot undo -
            #: was announced as a failure. The armed button stayed on screen,
            #: and pressing it again reported "Only the owner can transfer this
            #: project", because by then that was true. Every other write
            #: helper in this file already allows for the empty body; this one
            #: did not. The body may also be a list, which used to raise
            #: `AttributeError` and surface as one.
            status_code = result.get("status") if isinstance(result, dict) else None
            body = result.get("result") if isinstance(result, dict) else None
            per_project = body.get(project_id) if isinstance(body, dict) else None
            http_ok = not isinstance(status_code, int) or 200 <= status_code < 300
            if http_ok and (per_project == "SUCCESS" or not per_project):
                return {"ok": True,
                        "message": f"Ownership transferred to {new_owner_email}",
                        "previousOwner": current_owner_email,
                        "newOwner": new_owner_email}

            return {"error": f"Transfer failed: {per_project or result}"}
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
            #: **The add is checked too, because the remove already happened.**
            #: Only the remove step was inspected, so a refused re-add left the
            #: colleague with no access at all and reported the new role as
            #: though it had been applied. That is the worst outcome available
            #: here: the tool removed somebody's access and said it had
            #: changed it.
            try:
                add = self.api.add_project_share(project_id, email, new_role)
            except Exception as e:
                return {"error": "%s now has no access to this project. Their "
                                 "old access was removed and the new role "
                                 "could not be applied: %s. Share with them "
                                 "again to put it back." % (email, e),
                        "removed": True, "email": email}
            per_email = ((add or [{}])[0] or {}).get("responsePerEmailAddress", {})
            message = per_email.get(email, "")
            verdict = share_message_verdict(message)
            if verdict != "ok":
                return {"error": "%s now has no access to this project. Their "
                                 "old access was removed and Ekahau did not "
                                 "confirm the new role%s Share with them again "
                                 "to put it back."
                                 % (email, (": \"%s\"." % message) if message else "."),
                        "removed": True, "email": email,
                        "verdict": verdict, "message": message}
            return {"ok": True, "email": email, "role": new_role,
                    "message": message}
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

    def merge_preview_many(self, src_paths, dst_path):
        """Dry run for several source folders landing in one destination.

        **Not a loop over ``merge_preview``, and that is the whole point.** Two
        sources can each carry a ``Report.pdf``. Previewed one at a time they
        both read "no conflict", because neither file is in the destination
        *yet*; run one after the other, the first moves cleanly and the second
        lands on top of it - or is date-stamped - with nothing having warned
        him. So the preview walks the sources in the order they will run and
        carries what each one will place forward into the next. A file that
        collides with an earlier source in the same run is marked
        ``fromSource``, carrying that folder's name.

        A source that cannot be merged at all - missing, the destination
        itself, a parent of the destination - is reported by name and left out
        rather than failing the whole run. Refusing eight folders because one
        of them is wrong is the guard firing on his normal case.
        """
        try:
            od = self.config.get("output_dir", "")
            if not od:
                return {"error": "No local folder is set — pick one first"}
            paths = [p for p in (src_paths or []) if p]
            if not paths:
                return {"error": "No source folders were given"}
            _assert_inside(dst_path, od)
            dst = Path(dst_path)
            if not dst.is_dir():
                return {"error": "Destination folder not found"}

            # What the destination will hold as the run proceeds: what is there
            # now, plus whatever each earlier source will have put there.
            placed = {}          # rel -> the source folder that will place it
            sources, refused = [], []
            total_clean = total_conflicts = total_cross = 0

            for sp in paths:
                one = self.merge_preview(sp, dst_path)
                if one.get("error"):
                    refused.append({"path": sp, "name": Path(sp).name,
                                    "reason": one["error"]})
                    continue
                files = one.get("files") or []
                n_conf = n_cross = 0
                for rec in files:
                    rel = rec["rel"]
                    if not rec.get("conflict") and rel in placed:
                        # Clean against the destination as it is now, and not
                        # clean against the destination as it will be.
                        rec["conflict"] = True
                        rec["fromSource"] = placed[rel]
                        rec["newer"] = "unknown"
                        n_cross += 1
                    if rec.get("conflict"):
                        n_conf += 1
                    placed.setdefault(rel, one["srcName"])
                sources.append({
                    "srcPath": sp, "srcName": one["srcName"],
                    "nClean": len(files) - n_conf, "nConflicts": n_conf,
                    "nCrossSource": n_cross, "files": files,
                })
                total_clean += len(files) - n_conf
                total_conflicts += n_conf
                total_cross += n_cross

            if not sources:
                return {"error": "None of the selected folders can be merged: "
                                 + "; ".join(r["reason"] for r in refused)}
            return {"dstName": dst.name, "dstPath": dst_path,
                    "sources": sources, "refused": refused,
                    "nSources": len(sources),
                    "nClean": total_clean, "nConflicts": total_conflicts,
                    "nCrossSource": total_cross}
        except Exception as e:
            return {"error": str(e)}

    def merge_execute_many(self, merges, dst_path):
        """Run several merges into one destination, in the order given.

        *merges* is ``[{srcPath, ops}]``. Each goes through ``merge_execute``,
        so every guard on the single-folder path applies here too rather than
        being written a second time - the containment checks, the date-stamping
        and the refusal to remove a source folder.

        **One source failing does not stop the rest.** The ones that already
        ran have moved real files and unwinding them is not something this can
        do, so the result carries a row per source saying what happened to that
        one, and the page reports the failures by name.
        """
        try:
            od = self.config.get("output_dir", "")
            if not od:
                return {"error": "No local folder is set — pick one first"}
            items = [m for m in (merges or []) if m.get("srcPath")]
            if not items:
                return {"error": "No source folders were given"}
            results = []
            moved = overwritten = keptboth = skipped = 0
            for m in items:
                one = self.merge_execute(m["srcPath"], dst_path, m.get("ops") or [])
                row = {"srcPath": m["srcPath"], "srcName": Path(m["srcPath"]).name}
                if one.get("error"):
                    row["error"] = one["error"]
                else:
                    row.update(one)
                    moved += one.get("moved", 0)
                    overwritten += one.get("overwritten", 0)
                    keptboth += one.get("keptboth", 0)
                    skipped += one.get("skipped", 0)
                results.append(row)
            failed = [r for r in results if r.get("error")]
            return {"ok": True, "results": results,
                    "nSources": len(results), "nFailed": len(failed),
                    "moved": moved, "overwritten": overwritten,
                    "keptboth": keptboth, "skipped": skipped}
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
            #: **Every file, including the ones a scan skips.** This answer is
            #: what the page acts on: with "Delete the source folder afterward"
            #: ticked - and it ships ticked - `srcEmpty` sends the folder
            #: straight to `delete_local`, which is `shutil.rmtree` on a
            #: directory, with no dialog naming anything.
            #:
            #: `_walk_files` deliberately skips `output`, `archive` and
            #: `backups` so a scan does not report finished exports as work to
            #: do. Right for a scan, wrong for this: a folder holding nothing
            #: but `Output/` and `Archive/` answered "empty" and was then
            #: deleted whole. Since v2.141.0 nothing copies a file aside
            #: first, so there is no other copy of any of it.
            #:
            #: Deleting a folder that really is empty loses nothing, so the
            #: measurement is what changes rather than a prompt being added in
            #: front of it.
            try:
                src_empty = not any(p.is_file() for p in src.rglob("*"))
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

    def set_external_override(self, items, value):
        """Mark projects External, or mark them as his, by hand.

        *items* is a list of ``{cloudId, localPath, label}``. Nothing here
        touches either copy of the project: an override is an annotation on
        this installation's view, in the same class as a manual match, and the
        cloud does not learn about it.
        """
        if value not in ("external", "mine"):
            return {"error": "value must be 'external' or 'mine'"}
        items = [i for i in (items or []) if i.get("cloudId") or i.get("localPath")]
        if not items:
            return {"error": "nothing to mark"}
        entries = load_external_overrides()
        by_key = {e["key"]: e for e in entries}
        for item in items:
            key = _ov_key(item.get("cloudId"), item.get("localPath"))
            by_key[key] = {
                "key": key,
                "value": value,
                "cloudId": item.get("cloudId") or "",
                "localPath": item.get("localPath") or "",
                "label": item.get("label") or "",
                "addedAt": int(time.time()),
            }
        ordered = list(by_key.values())
        save_external_overrides(ordered)
        return {"ok": True, "count": len(ordered), "marked": len(items)}

    def clear_external_override(self, items):
        items = items or []
        keys = {_ov_key(i.get("cloudId"), i.get("localPath")) for i in items}
        if not keys:
            return {"error": "nothing to clear"}
        entries = load_external_overrides()
        kept = [e for e in entries if e["key"] not in keys]
        save_external_overrides(kept)
        return {"ok": True, "count": len(kept), "removed": len(entries) - len(kept)}

    def list_external_overrides(self):
        return {"ok": True, "entries": load_external_overrides(),
                "file": str(EXTERNAL_OVERRIDE_FILE)}
