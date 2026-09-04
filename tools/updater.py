"""
Self-updater — portable across the WD app family.

Everything app-specific lives in the AppConfig block at the top.  Porting this
to another repo (LensLedger, Subscription Wizard) is meant to be: copy this
file plus the front-end module, edit CONFIG, done.  Nothing below CONFIG names
WD Wireless Tools.

Three mechanisms, auto-detected, because installs genuinely differ:

  git install   .git present.  Update is a fetch + checkout of the newest
                release tag.  Fast, incremental, and its own rollback (the
                previous tag stays in the object store).  Primary path.

  ZIP install   No .git.  Update downloads the release asset, verifies its
                SHA-256, and replaces the shipped payload in place after
                copying the tree to a dated sibling backup.

  convert       A ZIP install opting into git, in place, without reinstalling.

Callers should treat `detect_install()` as the source of truth for which single
action to offer, rather than asking the user to choose a mechanism.

Why replace-in-place rather than renaming the folder: the server runs out of
this directory, so on Windows it is locked against rename while it is any
process's working directory.  Files inside it are not locked — Python closes
each module file after import — so overwriting them under the running server is
safe, and a restart picks up the new code.

Nothing here writes user data.  Everything the user creates lives under
CONFIG.user_data_dir, outside the install tree, which is what makes the whole
tree disposable.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ============================================================== app config ==

@dataclass(frozen=True)
class AppConfig:
    """Everything that differs between apps in the family."""
    name: str
    repo: str                       # "owner/name" on GitHub
    install_root: Path
    version_path: str               # relative path to the version JSON
    version_key: str                # key inside it holding the app version
    asset_template: str             # {tag} -> release asset filename
    payload_files: tuple            # replaceable top-level files
    payload_dirs: tuple             # replaceable top-level directories
    user_data_dir: Path             # never touched by an update
    launcher_win: str = ""
    launcher_mac: str = ""
    # Files the user can edit that are ALSO tracked in the repo.  These are the
    # only paths that can make a pull abort; each is rescued into user_data_dir
    # before the update rather than blocking it forever.  Glob syntax.
    rescuable_globs: tuple = ()

    @property
    def api_latest(self) -> str:
        return f"https://api.github.com/repos/{self.repo}/releases/latest"

    @property
    def releases_url(self) -> str:
        return f"https://github.com/{self.repo}/releases"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.repo}.git"

    def asset_name(self, tag: str) -> str:
        return self.asset_template.format(tag=tag, version=tag.lstrip("v"))


_ROOT = Path(__file__).resolve().parent.parent

CONFIG = AppConfig(
    name="WD Wireless Tools",
    repo="WeirDave/WD-Wireless-Tools",
    install_root=_ROOT,
    version_path="web/assets/versions.json",
    version_key="suite",
    asset_template="WD-Wireless-Tools-{tag}.zip",
    payload_files=(
        "server.py",
        "Start WD Wireless Tools.bat",
        "Start WD Wireless Tools.command",
        "requirements.txt",
        "README.md",
        "LICENSE",
        "install.ps1",
        "install.sh",
    ),
    payload_dirs=("tools", "web", "templates", "docs"),
    user_data_dir=Path.home() / ".wd_wireless_tools",
    launcher_win="Start WD Wireless Tools.bat",
    launcher_mac="Start WD Wireless Tools.command",
    rescuable_globs=("templates/*_walltemplate.json",),
)

# Back-compat aliases — existing callers and tests import these directly.
ROOT = CONFIG.install_root
GITHUB_REPO = CONFIG.repo
GITHUB_API_LATEST = CONFIG.api_latest
GITHUB_RELEASES_URL = CONFIG.releases_url
CLONE_URL = CONFIG.clone_url
PAYLOAD_FILES = CONFIG.payload_files
PAYLOAD_DIRS = CONFIG.payload_dirs

TAG_RE = re.compile(r"^v[0-9]+(?:\.[0-9]+)+$")
GIT_TIMEOUT = 120
NET_TIMEOUT = 60
WINGET_TIMEOUT = 600


class UpdateError(Exception):
    """Anything the user needs to read in plain language."""


# ================================================================ versions ==

def parse_version(text: str):
    return tuple(int(p) for p in re.findall(r"\d+", str(text or "")))


def cmp_version(a: str, b: str) -> int:
    pa, pb = parse_version(a), parse_version(b)
    length = max(len(pa), len(pb))
    pa += (0,) * (length - len(pa))
    pb += (0,) * (length - len(pb))
    return (pa > pb) - (pa < pb)


def local_version(root: Path | None = None, cfg: AppConfig = CONFIG) -> str:
    path = (root or cfg.install_root) / cfg.version_path
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(cfg.version_key, "")
    except Exception:
        return ""


# ===================================================================== git ==

# Raw git output is written for people who use git. "You are not currently on
# a branch. See git-pull(1) for details." tells an installer nothing and looks
# like the app is broken, so known failures are translated and anything
# unrecognised is reported as a plain sentence with the git text kept out of
# the headline.
_GIT_HINTS = (
    ("not currently on a branch",
     "This install sits on a specific release rather than following a branch, "
     "which is normal. Use the Update button in About rather than git directly."),
    ("could not resolve host",
     "No connection to GitHub. Check the network and try again."),
    ("unable to access",
     "Could not reach GitHub. Check the network, or a proxy or firewall, and try again."),
    ("would be overwritten",
     "Some files in the install folder have been edited and an update would "
     "overwrite them. Move or revert them, then update again."),
    ("permission denied",
     "The install folder is not writable. Close anything using it and try again."),
    ("index.lock",
     "Another git operation is still running in the install folder. "
     "Wait a moment and try again."),
    ("authentication failed",
     "GitHub refused the connection. If this install came from a private copy, "
     "sign in to git first."),
    ("not a git repository",
     "This folder is not a git install any more. Reinstall, or use the ZIP update."),
)


def _friendly_git_error(args, proc) -> str:
    text = ((proc.stderr or "") + "\n" + (proc.stdout or "")).lower()
    for needle, message in _GIT_HINTS:
        if needle in text:
            return message
    verb = args[0] if args else "git"
    return (f"The update could not finish (git {verb} failed). "
            "Try again, and if it keeps failing use Copy Diagnostics from the menu.")


def _run_git(args, cwd: Path, check: bool = True):
    try:
        proc = subprocess.run(
            ["git"] + args, cwd=str(cwd), capture_output=True, text=True,
            timeout=GIT_TIMEOUT,
        )
    except FileNotFoundError:
        raise UpdateError("Git is not installed or not on PATH.")
    except subprocess.TimeoutExpired:
        raise UpdateError("The update timed out talking to GitHub. Check the network and try again.")
    if check and proc.returncode != 0:
        raise UpdateError(_friendly_git_error(args, proc))
    return proc


def git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


def is_git_install(root: Path | None = None, cfg: AppConfig = CONFIG) -> bool:
    return ((root or cfg.install_root) / ".git").exists()


# --------------------------------------------------------- installing git --

def winget_available() -> bool:
    if os.name != "nt":
        return False
    try:
        proc = subprocess.run(["winget", "--version"], capture_output=True, timeout=20)
        return proc.returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


def git_install_plan() -> dict:
    """How (or whether) git can be installed on this machine.

    Windows is the primary target and `winget install Git.Git` is quick, so a
    missing git is offered as a step in the flow rather than a dead end.
    """
    if git_available():
        return {"needed": False, "possible": True, "method": None,
                "message": "Git is already installed."}
    if os.name == "nt":
        if winget_available():
            return {
                "needed": True, "possible": True, "method": "winget",
                "message": "Git isn't installed. It can be installed now with "
                           "winget — usually under a minute.",
            }
        return {
            "needed": True, "possible": False, "method": None,
            "message": "Git isn't installed, and winget isn't available on this "
                       "machine to install it automatically (it ships with newer "
                       "Windows 10 and 11). Install Git from git-scm.com, or use "
                       "the ZIP method instead.",
        }
    # macOS/Linux: the repo supports macOS, but the install routes there
    # (Xcode command line tools, Homebrew) are slower and more intrusive, so
    # they are described rather than run.
    hint = ("Install it with `xcode-select --install` or `brew install git`."
            if sys.platform == "darwin"
            else "Install it with your package manager.")
    return {"needed": True, "possible": False, "method": None,
            "message": f"Git isn't installed. {hint} Or use the ZIP method instead."}


def install_git(log=None) -> dict:
    """Install git via winget.  Windows only, and only when winget exists."""
    say = log or (lambda m: None)
    plan = git_install_plan()
    if not plan["needed"]:
        return {"ok": True, "installed": False, "reason": "already present"}
    if not plan["possible"]:
        raise UpdateError(plan["message"])

    say("Installing Git… this usually takes under a minute.")
    args = [
        "winget", "install", "--id", "Git.Git", "-e",
        "--accept-source-agreements", "--accept-package-agreements",
        "--disable-interactivity",
    ]
    try:
        # User scope avoids the admin prompt where the package allows it; some
        # Git.Git versions are machine-scope only, so fall back rather than fail.
        proc = subprocess.run(args + ["--scope", "user"],
                              capture_output=True, text=True, timeout=WINGET_TIMEOUT)
        if proc.returncode != 0:
            say("Per-user install unavailable; trying the standard installer…")
            proc = subprocess.run(args, capture_output=True, text=True,
                                  timeout=WINGET_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise UpdateError("The Git installer timed out. Install Git from "
                          "git-scm.com, or use the ZIP method instead.")
    except OSError as e:
        raise UpdateError(f"Could not start the Git installer: {e}")

    if proc.returncode != 0:
        detail = (proc.stdout or "") + (proc.stderr or "")
        lowered = detail.lower()
        if "policy" in lowered or "blocked" in lowered or "0x8a15005e" in lowered:
            raise UpdateError(
                "Installing Git was blocked by a policy on this machine. "
                "Use the ZIP method instead, or ask IT to install Git."
            )
        if "network" in lowered or "internet" in lowered or "0x80072ee7" in lowered:
            raise UpdateError(
                "Couldn't reach the package source to install Git. "
                "Check your connection, or use the ZIP method instead."
            )
        raise UpdateError(
            "The Git install did not complete. Install Git from git-scm.com, "
            "or use the ZIP method instead."
        )

    # winget updates PATH for new processes; this one still has the old copy.
    if not git_available():
        _refresh_path_from_registry()
    if not git_available():
        raise UpdateError(
            "Git was installed, but this app can't see it until it restarts. "
            "Restart the app, then try again."
        )
    say("Git installed.")
    return {"ok": True, "installed": True}


def _refresh_path_from_registry() -> None:
    """Pick up a PATH change made by an installer in this already-running process."""
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return
    parts = []
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE,
                       r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(hive, key) as k:
                value, _ = winreg.QueryValueEx(k, "Path")
                parts.append(os.path.expandvars(value))
        except OSError:
            continue
    if parts:
        os.environ["PATH"] = os.pathsep.join(parts + [os.environ.get("PATH", "")])


# ------------------------------------------------------------- git updates --

def _latest_release_tag(root: Path):
    """Newest release tag known locally, by version order (not commit date)."""
    proc = _run_git(["tag", "--list", "v*"], root)
    tags = [t.strip() for t in proc.stdout.splitlines() if TAG_RE.match(t.strip())]
    return max(tags, key=parse_version) if tags else None


def _tag_exists(root: Path, tag: str) -> bool:
    proc = _run_git(["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
                    root, check=False)
    return proc.returncode == 0


def _dirty_paths(root: Path):
    proc = _run_git(["status", "--porcelain"], root)
    out = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        status, path = line[:2], line[3:]
        if status.strip() == "??":
            continue  # untracked files never block a checkout
        out.append(path.strip().strip('"'))
    return out


def is_dev_checkout(root: Path | None = None, cfg: AppConfig = CONFIG) -> bool:
    """True for a maintainer's working copy with work in progress.

    Deliberately NOT based on the presence of tests/ or .github/: a user who
    installs by cloning gets those too, so a file-marker test would block the
    primary update path for everyone.

    The signal is git state instead.  Installing leaves HEAD detached at a
    release tag, so a detached HEAD is always a normal install.  An attached
    branch only counts as a dev checkout when there is something to protect —
    commits not yet pushed, or modified tracked files.
    """
    root = root or cfg.install_root
    if not is_git_install(root, cfg):
        return False

    head = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root, check=False)
    ref = (head.stdout or "").strip()
    if head.returncode != 0 or not ref or ref == "HEAD":
        return False

    ahead = _run_git(["rev-list", "--count", "@{u}..HEAD"], root, check=False)
    count = (ahead.stdout or "").strip()
    if ahead.returncode == 0 and count.isdigit() and int(count) > 0:
        return True

    try:
        return bool(_dirty_paths(root))
    except UpdateError:
        return False


def rescue_dirty_templates(root: Path, cfg: AppConfig = CONFIG):
    """Save in-place edits to tracked, user-editable files, then clean the tree.

    A user who customized one of cfg.rescuable_globs would otherwise hit
    'Your local changes would be overwritten' and be permanently stuck.  Their
    edit is copied into user_data_dir — where the app reads it in preference to
    the shipped copy — and the tree copy is reverted so the update proceeds.
    """
    if not cfg.rescuable_globs:
        return []
    from fnmatch import fnmatch
    from tools import template_store

    rescued = []
    for path in _dirty_paths(root):
        posix = path.replace("\\", "/")
        if not any(fnmatch(posix, g) for g in cfg.rescuable_globs):
            continue
        name = posix.rsplit("/", 1)[-1]
        result = template_store.rescue_dirty_builtin(name)
        if result.get("ok"):
            _run_git(["checkout", "--", path], root, check=False)
            if result.get("rescued"):
                rescued.append(name)
    return rescued


def _ensure_origin(root: Path, cfg: AppConfig = CONFIG):
    """A git install with no usable origin cannot update at all.

    An install converted from a ZIP, or one whose remote was renamed, would
    otherwise fail with git's own wording deep inside a fetch.
    """
    proc = _run_git(["remote", "get-url", "origin"], root, check=False)
    if proc.returncode == 0 and (proc.stdout or "").strip():
        return
    _run_git(["remote", "add", "origin", cfg.clone_url], root, check=False)


def git_update(root: Path | None = None, channel: str = "release", log=None,
               cfg: AppConfig = CONFIG):
    """Fetch and move to the newest release tag (or main on the dev channel)."""
    root = root or cfg.install_root
    say = log or (lambda m: None)
    before = local_version(root, cfg)

    if not is_git_install(root, cfg):
        raise UpdateError("This install has no .git folder.")

    say("Preserving any customized files…")
    rescued = rescue_dirty_templates(root, cfg)
    if rescued:
        say(f"Kept your edits to {', '.join(rescued)} as personal copies.")

    dirty = _dirty_paths(root)
    if dirty:
        listed = ", ".join(dirty[:5]) + ("…" if len(dirty) > 5 else "")
        raise UpdateError(
            "This install has local edits that an update would overwrite: "
            f"{listed}. Revert or move them, then try again."
        )

    # Repair the remote before reaching for it, not after.
    _ensure_origin(root, cfg)
    say("Fetching from GitHub…")
    _run_git(["fetch", "--tags", "--prune", "origin"], root)

    if channel == "main":
        target = label = "origin/main"
        label = "main"
    else:
        tag = _latest_release_tag(root)
        if not tag:
            raise UpdateError("No release tags found on the remote.")
        target = label = tag
        # Nothing newer: return without checking anything out. Skipping this
        # would detach HEAD from a branch to land on the commit it already
        # points at — no change, but alarming in an otherwise healthy clone.
        if cmp_version(tag, before) <= 0:
            say(f"Already on the newest release (v{before}).")
            return {
                "ok": True, "mode": "git", "channel": channel,
                "previousVersion": before, "newVersion": before,
                "target": label, "rescuedTemplates": rescued, "changed": False,
            }

    say(f"Checking out {label}…")
    _run_git(["-c", "advice.detachedHead=false", "checkout", "--force", target], root)

    after = local_version(root, cfg)
    say(f"Now on v{after}." if after else f"Now on {label}.")
    return {
        "ok": True, "mode": "git", "channel": channel,
        "previousVersion": before, "newVersion": after,
        "target": label, "rescuedTemplates": rescued,
        "changed": cmp_version(after, before) != 0,
    }


def convert_to_git(root: Path | None = None, log=None, install_git_if_missing: bool = False,
                   cfg: AppConfig = CONFIG):
    """Adopt an existing ZIP install into git, in place.

    Deliberately checks out the tag matching the version already installed, not
    the newest one.  Converting and updating are separate decisions; doing both
    at once would mean a user who clicked "switch to git updates" silently got
    new code as well.  After converting, the normal Update button handles the
    rest.

    Safety: the tree is copied to a dated sibling backup first; user data lives
    outside the tree; and untracked files (stray .esx, notes) are left alone —
    a checkout only overwrites paths the release actually ships.
    """
    root = root or cfg.install_root
    say = log or (lambda m: None)
    if is_git_install(root, cfg):
        raise UpdateError("This install is already tracked by git.")

    if not git_available():
        if not install_git_if_missing:
            raise UpdateError(git_install_plan()["message"])
        install_git(log=say)

    current = local_version(root, cfg)
    if not current:
        raise UpdateError("Can't read the installed version, so there's no safe "
                          "point to convert to. Reinstall instead.")

    say("Backing up the current install…")
    backup = _backup_install(root, current, cfg)
    say(f"Backup: {backup}")

    say("Setting up git in this folder…")
    _run_git(["init"], root)
    _run_git(["remote", "add", "origin", cfg.clone_url], root)
    say("Fetching release history…")
    _run_git(["fetch", "--tags", "--prune", "origin"], root)

    tag = f"v{current}"
    if not _tag_exists(root, tag):
        latest = _latest_release_tag(root)
        if not latest:
            raise UpdateError("No release tags found on the remote.")
        say(f"No release tag matches v{current}; adopting {latest} instead.")
        tag = latest

    say(f"Adopting {tag}…")
    _run_git(["-c", "advice.detachedHead=false", "checkout", "--force", tag], root)

    after = local_version(root, cfg)
    say("This install now updates through git.")
    return {"ok": True, "mode": "convert", "changed": cmp_version(after, current) != 0,
            "previousVersion": current, "newVersion": after,
            "target": tag, "backup": str(backup)}


# ================================================================== github ==

def fetch_latest_release(cfg: AppConfig = CONFIG):
    import requests
    try:
        r = requests.get(cfg.api_latest,
                         headers={"Accept": "application/vnd.github+json"},
                         timeout=NET_TIMEOUT)
    except Exception as e:
        raise UpdateError(f"Could not reach GitHub: {e}")
    if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
        raise UpdateError("GitHub's API is rate-limited right now. Try again shortly.")
    if not r.ok:
        raise UpdateError(f"GitHub returned HTTP {r.status_code}.")
    data = r.json()
    tag = str(data.get("tag_name") or "")
    if not TAG_RE.match(tag):
        raise UpdateError(f"GitHub returned an unexpected release tag: {tag or '(none)'}")
    return {
        "tag": tag,
        "version": tag.lstrip("v"),
        "url": data.get("html_url") or cfg.releases_url,
        "notes": data.get("body") or "",
        "assets": {a.get("name"): a.get("browser_download_url")
                   for a in (data.get("assets") or [])},
    }


# ===================================================================== zip ==

def _download(url: str, dest: Path):
    import requests
    try:
        with requests.get(url, stream=True, timeout=NET_TIMEOUT) as r:
            if not r.ok:
                raise UpdateError(f"Download failed (HTTP {r.status_code}): {url}")
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(f"Download failed: {e}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_payload(tree: Path, expected_version: str, cfg: AppConfig = CONFIG):
    for name in cfg.payload_files:
        if not (tree / name).is_file():
            raise UpdateError(f"Downloaded release is missing {name}.")
    for name in cfg.payload_dirs:
        if not (tree / name).is_dir():
            raise UpdateError(f"Downloaded release is missing the {name}/ folder.")
    found = local_version(tree, cfg)
    if not found:
        raise UpdateError("Downloaded release has no readable version file.")
    if expected_version and found != expected_version:
        raise UpdateError(
            f"Downloaded release says v{found} but the tag says v{expected_version}."
        )
    return found


def _backup_install(root: Path, version: str, cfg: AppConfig = CONFIG) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root.parent / f"{root.name}.previous-v{version or 'unknown'}-{stamp}"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "tmp", "venv", ".venv")
    shutil.copytree(root, backup, ignore=ignore)
    return backup


def zip_update(root: Path | None = None, log=None, cfg: AppConfig = CONFIG):
    """Download, verify, and replace the shipped payload in place."""
    root = root or cfg.install_root
    say = log or (lambda m: None)
    before = local_version(root, cfg)

    say("Checking GitHub for a newer release…")
    release = fetch_latest_release(cfg)
    if cmp_version(release["version"], before) <= 0:
        say(f"Already on the newest release (v{before}).")
        return {"ok": True, "mode": "zip", "changed": False,
                "previousVersion": before, "newVersion": before,
                "target": release["tag"]}

    asset_name = cfg.asset_name(release["tag"])
    asset_url = release["assets"].get(asset_name)
    if not asset_url:
        raise UpdateError(
            f"Release {release['tag']} has no {asset_name} asset. "
            "Download it manually from the releases page."
        )

    staging = Path(tempfile.mkdtemp(prefix="app-update-"))
    try:
        zip_path = staging / "release.zip"
        say(f"Downloading {release['tag']}…")
        _download(asset_url, zip_path)

        checksum_url = release["assets"].get(f"{asset_name}.sha256")
        if checksum_url:
            say("Verifying checksum…")
            checksum_path = staging / "release.sha256"
            _download(checksum_url, checksum_path)
            text = checksum_path.read_text(encoding="utf-8").strip()
            match = re.match(r"^([A-Fa-f0-9]{64})\b", text)
            if not match:
                raise UpdateError("The release checksum file is malformed.")
            expected = match.group(1).lower()
            actual = _sha256(zip_path)
            if actual != expected:
                raise UpdateError(
                    f"Checksum mismatch — expected {expected}, got {actual}. "
                    "The download was not used."
                )
            say("Checksum verified.")
        else:
            say("No checksum published for this release; skipping verification.")

        say("Extracting…")
        extract = staging / "extracted"
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for member in zf.namelist():
                    target = (extract / member).resolve()
                    if not str(target).startswith(str(extract.resolve())):
                        raise UpdateError("Release archive contains an unsafe path.")
                zf.extractall(extract)
        except zipfile.BadZipFile:
            raise UpdateError("The downloaded release is not a valid ZIP.")

        tree = extract
        entries = list(extract.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            tree = entries[0]  # some archives wrap everything in one folder

        say("Verifying contents…")
        new_version = _validate_payload(tree, release["version"], cfg)

        say("Backing up the current install…")
        backup = _backup_install(root, before, cfg)

        say("Installing…")
        try:
            for name in cfg.payload_files:
                shutil.copy2(tree / name, root / name)
            for name in cfg.payload_dirs:
                dest = root / name
                if dest.is_dir():
                    shutil.rmtree(dest)
                shutil.move(str(tree / name), str(dest))
        except Exception as e:
            raise UpdateError(
                f"Install failed partway through: {e}. "
                f"Your previous copy is intact at {backup}."
            )

        say(f"Updated to v{new_version}.")
        return {"ok": True, "mode": "zip", "changed": True,
                "previousVersion": before, "newVersion": new_version,
                "target": release["tag"], "backup": str(backup)}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


# =============================================================== detection ==

def detect_install(root: Path | None = None, cfg: AppConfig = CONFIG) -> dict:
    """What kind of install this is, and therefore how it should update."""
    root = root or cfg.install_root
    git_repo = is_git_install(root, cfg)
    has_git = git_available()

    base = {
        "app": cfg.name,
        "isGitInstall": git_repo,
        "gitAvailable": has_git,
        "isDevCheckout": False,
        "canConvertToGit": False,
        "root": str(root),
        "currentVersion": local_version(root, cfg),
        "writable": os.access(root, os.W_OK),
        "releasesUrl": cfg.releases_url,
        "userDataDir": str(cfg.user_data_dir),
        "gitInstall": git_install_plan(),
    }

    if git_repo and is_dev_checkout(root, cfg):
        base.update(method="dev", isDevCheckout=True,
                    reason="This is a development checkout — update it with git, "
                           "not from the app.")
        return base

    if git_repo and has_git:
        base.update(method="git", reason="Tracked by git — updates pull from GitHub.")
        proc = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root, check=False)
        base["ref"] = (proc.stdout or "").strip() or "detached"
        return base

    if git_repo and not has_git:
        base.update(method="manual",
                    reason="This folder is a git checkout, but git is not installed.")
        return base

    # ZIP install. Conversion is offered whether or not git is present — on
    # Windows a missing git can be installed as part of the same flow.
    base.update(
        method="zip",
        canConvertToGit=has_git or git_install_plan()["possible"],
        reason=("Installed from a ZIP. Switching to git updates makes future "
                "updates incremental instead of a full re-download."),
    )
    return base


def perform_update(mode: str | None = None, channel: str = "release", log=None,
                   install_git_if_missing: bool = False, cfg: AppConfig = CONFIG):
    """Run the correct update for this install.  `mode` forces a path."""
    info = detect_install(cfg=cfg)
    if info.get("isDevCheckout"):
        raise UpdateError(
            "This is a development checkout of the suite. Updating it from the "
            "app would check out a release tag over your work. Use git directly."
        )
    chosen = mode or info["method"]

    if chosen == "git":
        if not info["isGitInstall"]:
            raise UpdateError("This install is not tracked by git.")
        if not info["gitAvailable"]:
            raise UpdateError("Git is not installed or not on PATH.")
        return git_update(channel=channel, log=log, cfg=cfg)
    if chosen == "convert":
        return convert_to_git(log=log, install_git_if_missing=install_git_if_missing, cfg=cfg)
    if chosen == "zip":
        return zip_update(log=log, cfg=cfg)
    raise UpdateError(
        "This install can't update itself automatically. "
        f"Download the latest release from {cfg.releases_url}."
    )
