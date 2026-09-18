"""What our own tooling has left lying around, and what is safe to remove.

**Why this exists, in his words:** "how do I know, once we've done all the
work, when to be able to clean stuff up? Because now I feel like we've got
files fucking everywhere across the board, and I don't know if you clean up
your own work or not."

He is right, and the honest answer was no. A sweep on 2026-09-17 recovered
12.73 GB of session debris - roughly 7,900 leaked temp directories and 7,000
abandoned repository clones. Twenty-seven files carrying real workplace data
were sitting in `%TEMP%`. Four worktrees outlived the sessions that reported
removing them. Screenshots were written to his Desktop. He found the worktree
folder himself, which is how the question got asked.

So this turns "I wonder if there is junk everywhere" into something he can
answer in five seconds, from the dev toolbar, without being talked through a
script.

What it looks at
----------------
Only what our tooling creates: worktrees under `C:\\wd-worktrees`, session
scratchpads and leaked temp directories, the test suite's own leftovers,
browser profiles and driver executables, downloaded release ZIPs, and stray
files left where a worktree should be.

What it will not touch
----------------------
**His files.** `REFUSED_ROOTS` is checked before anything else and covers the
Dropbox tree, `~/.wd_wireless_tools`, and the project folder Cloud Manager is
configured against. Nothing is emptied from the recycle bin. Deletion is
additionally confined to `SAFE_ROOTS` - being outside a refused root is not
enough on its own, a path has to be positively inside somewhere we own.

The Desktop is **inventoried and never deletable**. Those files are almost
certainly ours, and "almost certainly" is not the standard for deleting from
somebody's desktop - so they are listed, with a note, and left for him. That
is the general rule here: where ownership is uncertain, list it and leave it.

Live is never offered
---------------------
A worktree that `git worktree list` still registers belongs to a session that
may be mid-task, and an entry touched in the last few minutes probably does
too. Both are marked live with the reason, and `sweep` refuses them even if
asked directly.

**`sweep` re-surveys rather than trusting what it is handed.** The caller sends
a list of paths, and every one is looked up in a freshly computed survey and
must still be deletable. A path that went live between the preview and the
sweep is skipped and reported. Same rule as the realign action: the proof has
to be current at the moment of writing, not at the moment of previewing.

Real workplace data is reported first, and only ever as a count
--------------------------------------------------------------
That is the category that actually matters to him - it is not about disk
space, it is that copies of his site data should not be scattered around.
`tests/test_no_real_world_data.py` holds the authoritative detector for the
repository; this is a deliberately separate, narrower one for artifacts on
disk, and it errs toward flagging. **Nothing here ever returns the values it
matched on**, only how many - a report that quoted them would be one more copy
of the thing being reported.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

#: An entry touched more recently than this is assumed to belong to a session
#: that is still working. Deliberately generous: a wrongly-kept directory
#: costs a few megabytes, a wrongly-deleted one costs somebody's afternoon.
LIVE_WINDOW_MINUTES = 20

#: Stop walking a single entry after this many files. A pathological tree
#: should make the size approximate, not make the survey hang.
WALK_FILE_BUDGET = 20000

#: A whole-survey ceiling on time spent reading files for the data scan.
#: Sizing is stat-only and stays cheap; reading is what can run away. When
#: this is spent the survey still completes - sizes, liveness and counts are
#: unaffected - and reports `dataScanComplete: False`, so the number is shown
#: as a floor rather than a total. A survey that hangs is a survey nobody
#: runs, and then he is back to not knowing.
DATA_SCAN_SECONDS = 20.0

#: Text worth scanning for workplace data. Anything else is sized and skipped.
_TEXT_SUFFIXES = {".txt", ".json", ".md", ".log", ".py", ".js", ".html",
                  ".css", ".csv", ".yml", ".yaml", ".xml", ".ps1", ".sh"}

#: A file this big is not a note somebody left; reading it to grep is not
#: worth the time.
_TEXT_SCAN_MAX_BYTES = 2_000_000

#: Vendored third-party bundles, skipped for the same reason
#: `tests/test_no_real_world_data.py` skips them: minified code throws off
#: every heuristic here - an AWS key prefix once turned up in that repo's scan
#: as a mangled variable name inside pdf.js. Confirmed again on 2026-09-18,
#: where `jszip.min.js` and `mammoth.browser.min.js` were between them
#: producing six of the eighteen "signals" reported against a worktree that is
#: rule-zero clean by construction. They are not ours to edit and not his data.
_SKIP_PATH_PARTS = ("web/assets/lib/", "node_modules/")

_PROJECT_SUFFIXES = {".esx"}

#: Below this, an unreadable `.esx` is a stub the suite wrote rather than a
#: truncated project of his. The smallest real project seen here is well over
#: a megabyte; the fixtures are a few hundred bytes.
_REAL_PROJECT_MIN_BYTES = 100_000

CODE_TOKEN = re.compile(r"\b[A-Z]{3,5}[0-9]{1,2}\b")
#: Every quantifier here is bounded, and that is not tidiness.
#:
#: The obvious spelling - `[A-Za-z0-9._%+-]+@...` - backtracks quadratically
#: on text with long runs of those characters and no `@`, which is exactly
#: what a log file is. Measured on 2026-09-18: a 393 KB log holding two
#: files took **163 seconds** to scan, and the first full survey of this
#: machine ran past ten minutes without finishing because of two such files.
#: The bounded form does the same job on the same input in 0.005 s and
#: matches the same addresses - 64 and 63 are the RFC 5321 limits for a
#: local part and a label, so nothing valid is lost by pinning them.
EMAIL = re.compile(
    r"[A-Za-z0-9._%+-]{1,64}@"
    r"([A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,8}\.[A-Za-z]{2,24})")

#: Documentation domains, per RFC 2606, plus the generic stand-in the repo uses.
_ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net",
                          "example.invalid", "company.com",
                          "users.noreply.github.com"}

#: Prefixes the repository's invented placeholders use. This is **noise
#: reduction only** - the authoritative allowlist lives in
#: `tests/test_no_real_world_data.py` and is not importable from here on
#: purpose, because that file's support code is deliberately kept out of
#: `tools/`, which ships. Erring toward flagging is the right direction: a
#: false flag makes him look, a missed one leaves his site data on disk.
_INVENTED_PREFIXES = ("SITE", "TEST", "ACME", "FLR", "BLDG", "MPL", "UTF")


def _norm(p):
    try:
        return os.path.normcase(os.path.abspath(str(p)))
    except (OSError, ValueError):
        return os.path.normcase(str(p))


def _within(path, root):
    """Is `path` at or inside `root`? Compared on normalised absolute paths so
    a different spelling of the same folder cannot slip past."""
    p, r = _norm(path), _norm(root)
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def default_roots():
    """Where to look, and where his own things live.

    Returned as a dict so a test can point every one of them at a fixture
    tree and never touch the real machine.
    """
    home = Path.home()
    temp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp")
    return {
        "worktrees": Path("C:/wd-worktrees"),
        "temp": temp,
        "scratch": temp / "claude",
        "desktop": home / "Desktop",
        "downloads": home / "Downloads",
    }


def refused_roots(roots=None, extra=None):
    """Places this must never scan and never delete from.

    `extra` carries the project folder Cloud Manager is pointed at, which is
    not knowable from here - the caller passes it in. If that lookup ever
    fails, the caller passes nothing and the Dropbox and user-data guards
    still stand; `SAFE_ROOTS` is what actually bounds deletion.
    """
    home = Path.home()
    out = [home / ".wd_wireless_tools", home / "Dropbox"]
    out.extend(Path(p) for p in (extra or []) if p)
    return [p for p in out if str(p).strip()]


def _safe_roots(roots):
    """The only places a delete may happen. The Desktop and Downloads are
    deliberately absent - they are inventoried, never swept."""
    return [roots["worktrees"], roots["temp"], roots["scratch"]]


# ── sizing and scanning ──────────────────────────────────────────

class _Budget:
    """How much time is left for reading files, shared across the whole survey.

    Sizing is never budgeted - it is stat-only and stays cheap, and a size
    that silently stopped counting would be a lie about how much is out
    there. Only the data scan gives up, and it says so.
    """

    def __init__(self, seconds=None):
        self.deadline = time.monotonic() + (
            DATA_SCAN_SECONDS if seconds is None else seconds)
        self.complete = True

    def spent(self):
        if not self.complete:
            return True
        if time.monotonic() >= self.deadline:
            self.complete = False
            return True
        return False


def _measure(path, refused, budget=None):
    """(bytes, file count, truncated, data-finding count) for one entry.

    One walk does all four: walking a tree twice to answer two questions
    about it is the kind of thing that makes a survey too slow to run, and a
    survey too slow to run does not get run.
    """
    total = files = findings = 0
    truncated = False
    p = Path(path)

    if p.is_file():
        try:
            total = p.stat().st_size
        except OSError:
            total = 0
        return total, 1, False, _scan_file(p, budget)

    for dirpath, dirnames, filenames in os.walk(str(p), onerror=lambda e: None):
        if any(_within(dirpath, r) for r in refused):
            dirnames[:] = []
            continue
        for name in filenames:
            if files >= WALK_FILE_BUDGET:
                truncated = True
                return total, files, truncated, findings
            fp = Path(dirpath) / name
            files += 1
            try:
                total += fp.stat().st_size
            except OSError:
                pass
            findings += _scan_file(fp, budget)
    return total, files, truncated, findings


def _scan_file(fp, budget=None):
    """How many workplace-data signals this one file carries. Never what they
    were - see the module docstring."""
    suffix = fp.suffix.lower()
    if suffix in _PROJECT_SUFFIXES:
        return _scan_esx(fp)
    if suffix not in _TEXT_SUFFIXES:
        return 0
    # Compared with forward slashes so one spelling covers both
    # platforms - see the constant above for why not literals.
    if any(part in fp.as_posix() for part in _SKIP_PATH_PARTS):
        return 0
    if budget is not None and budget.spent():
        return 0
    try:
        if fp.stat().st_size > _TEXT_SCAN_MAX_BYTES:
            return 0
        text = fp.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return scan_text(text)


def _scan_esx(fp):
    """Is this `.esx` one of his, or one the suite invented?

    **The extension is not the answer, and assuming it was made the whole
    feature useless.** The first run of this against the real machine flagged
    2,226 entries - every one of them a synthetic fixture the test suite had
    written, because `wd-cloud-pull-*` and friends are full of them. A flag
    that fires on everything is a flag he learns to scroll past, and this is
    the one category he actually cares about.

    So it reads `project.json` out of the archive and runs the same detector
    over the metadata. A fixture is named something invented and authored at
    a documentation domain, and scores zero. One of his carries a real
    project name and his work address, and does not. Cheap, because
    `project.json` is a few hundred bytes and nothing else in the archive is
    read.

    **A file that is not a ZIP is not one of his projects**, and that
    distinction is worth its own branch. The tests write dummy bytes to
    `.esx` paths to exercise error handling, and 683 of those were being
    flagged on the second run of this - the same "flag fires on everything"
    failure as before, one layer down. An Ekahau project is always a valid
    ZIP archive.

    The size floor is the hedge against the one case that reasoning misses: a
    real project truncated by an interrupted copy is also not a valid ZIP,
    and a real project is never a few kilobytes. Small and unreadable is a
    stub; large and unreadable goes on the list, because "I could not tell"
    belongs where he looks rather than where he does not.
    """
    import json
    import zipfile
    try:
        size = fp.stat().st_size
    except OSError:
        return 1
    try:
        with zipfile.ZipFile(fp) as z:
            if "project.json" not in z.namelist():
                return 1
            with z.open("project.json") as pj:
                raw = pj.read(_TEXT_SCAN_MAX_BYTES)
        doc = json.loads(raw.decode("utf-8", "ignore"))
    except zipfile.BadZipFile:
        return 1 if size >= _REAL_PROJECT_MIN_BYTES else 0
    except (OSError, ValueError, KeyError):
        return 1
    proj = (doc or {}).get("project") or {}
    history = proj.get("history") or {}
    # Only the fields that carry identity. Serialising the whole document
    # would drag in ids and timestamps and tell us nothing.
    fields = " ".join(str(v) for v in (
        proj.get("name"), proj.get("title"), proj.get("location"),
        history.get("createdBy"), history.get("modifiedBy")) if v)
    return 1 if scan_text(fields) else 0


def scan_text(text):
    """Count workplace-data signals in a piece of text. Returns an int.

    Separate and public so the tests can exercise the detector directly
    without building a file tree for every case.
    """
    hits = 0
    for token in CODE_TOKEN.findall(text):
        if not token.upper().startswith(_INVENTED_PREFIXES):
            hits += 1
    for domain in EMAIL.findall(text):
        if domain.lower() not in _ALLOWED_EMAIL_DOMAINS:
            hits += 1
    return hits


# ── what counts as ours ──────────────────────────────────────────

#: Each family: (group key, title, matcher, what it is).
#:
#: Adding one is a line here. The matcher takes a directory entry's name and
#: says whether it is ours - nothing is ever matched by "it looks like junk",
#: because a rule that loose would eventually match one of his folders.
FAMILIES = [
    ("tests", "Test suite leftovers",
     lambda n: n.startswith(("wd-tests-userdir-", "wd-cloud-pull-",
                             "wd-prep-", "wd-walls-", "wd-report-")),
     "A temp directory the suite made and did not remove."),
    ("tests", "Test suite leftovers",
     lambda n: bool(re.fullmatch(r"wd\d+\.log", n)),
     "A log from a test server that ran on that port."),
    ("drivers", "Browser drivers and profiles",
     lambda n: n.startswith(("rust_mozprofile", "scoped_dir",
                             ".com.google.Chrome", ".com.microsoft.Edge",
                             "geckodriver", "chromedriver", "msedgedriver"))
     or n == "se-metadata.json",
     "A browser profile or driver left by an automated browser run."),
    ("releases", "Downloaded release archives",
     lambda n: bool(re.fullmatch(r"WD-Wireless-Tools-v[\d.]+\.zip(\.sha256)?", n)),
     "A release ZIP a session downloaded to check its contents."),
    ("temp", "Leaked temp directories",
     lambda n: bool(re.fullmatch(r"tmp[0-9a-z_]{6,10}", n)),
     "A Python temp directory whose owner exited without removing it."),
]


def _family_for(name):
    for key, title, matcher, note in FAMILIES:
        try:
            if matcher(name):
                return key, title, note
        except (TypeError, ValueError):
            continue
    return None


# ── liveness ─────────────────────────────────────────────────────

def registered_worktrees(repo=None):
    """Paths `git worktree list` knows about, normalised.

    A worktree git still registers belongs to a session that may be mid-task.
    This is the check the old convention was missing: `git worktree prune`
    only clears registrations whose directory has already gone, so it walks
    straight past an abandoned one, exits 0 and prints nothing. Verified
    again on 2026-09-18 - prune clean, `worktree list` still listing it, the
    folder still on disk. Registration is the signal; prune's exit code
    never was.
    """
    # **Default to this repository, not the process's working directory.**
    # The server is started from wherever the launcher happens to be, and
    # `git worktree list` run outside a repository exits non-zero and returns
    # nothing - so every worktree, including live ones, was labelled "the
    # session that made it never tore it down". Caught by driving the real
    # action against the real machine on 2026-09-18, where only the
    # recently-touched guard stopped this session's own worktree being
    # offered for deletion. A silent empty answer is the dangerous shape
    # here, because the failure direction is toward deleting more.
    cwd = str(repo) if repo else str(Path(__file__).resolve().parent.parent)
    try:
        out = subprocess.run(["git", "worktree", "list", "--porcelain"],
                             capture_output=True, text=True, timeout=30,
                             cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode != 0:
        return set()
    return {_norm(line[len("worktree "):].strip())
            for line in out.stdout.splitlines()
            if line.startswith("worktree ")}


def _liveness(path, name, mtime, now, registered, own_paths):
    """(live, reason). The reason is shown to him, so it says why in words."""
    if any(_within(path, p) for p in own_paths):
        return True, "This session is using it."
    if _norm(path) in registered:
        return True, "Registered as a worktree - a session may be using it."
    idle_min = (now - mtime) / 60.0
    if idle_min < LIVE_WINDOW_MINUTES:
        return True, ("Changed %d minutes ago - assumed to be in use."
                      % max(0, int(idle_min)))
    return False, ""


# ── processes ────────────────────────────────────────────────────

#: Executables an automated run starts and sometimes fails to stop. Firefox
#: is **not** on this list by name: his own browser is in that process table
#: and `taskkill /IM firefox.exe` would take it down. A headless one is
#: identified by its command line instead.
OUR_PROCESSES = ("geckodriver.exe", "chromedriver.exe", "msedgedriver.exe")

_HEADLESS_MARKERS = ("-headless", "--headless", "rust_mozprofile",
                     "--remote-debugging-port")


def list_processes(runner=None):
    """Driver and headless-browser processes that look like ours.

    `runner` is injectable so the tests never depend on what happens to be
    running on the machine.
    """
    if runner is None:
        runner = _powershell_processes
    try:
        rows = runner()
    except Exception:
        return []
    out = []
    for row in rows or []:
        name = (row.get("name") or "").lower()
        cmd = row.get("cmd") or ""
        pid = row.get("pid")
        if not pid:
            continue
        if name in OUR_PROCESSES:
            out.append({"pid": int(pid), "name": name,
                        "why": "A WebDriver executable, started by a test run."})
            continue
        if name in ("firefox.exe", "chrome.exe", "msedge.exe") and \
                any(m in cmd for m in _HEADLESS_MARKERS):
            out.append({"pid": int(pid), "name": name,
                        "why": "A headless browser - not a window he has open."})
    return out


def _powershell_processes():
    script = ("Get-CimInstance Win32_Process | "
              "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Depth 2")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                          "-Command", script],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0 or not out.stdout.strip():
        return []
    import json as _json
    data = _json.loads(out.stdout)
    if isinstance(data, dict):
        data = [data]
    return [{"pid": r.get("ProcessId"), "name": r.get("Name"),
             "cmd": r.get("CommandLine") or ""} for r in data]


def stop_process(pid, killer=None):
    """Stop one process by id. Injectable, for the same reason as above."""
    if killer is not None:
        return killer(pid)
    out = subprocess.run(["taskkill", "/PID", str(int(pid)), "/F"],
                         capture_output=True, text=True, timeout=30)
    return out.returncode == 0


# ── the survey ───────────────────────────────────────────────────

def survey(roots=None, now=None, registered=None, own_paths=None,
           project_folders=None, processes=None):
    """Everything our tooling has left, newest first, grouped.

    Every input is injectable so the whole thing can be exercised against a
    fixture tree - a test for this must never be able to reach his machine,
    which is the same reason `WD_USER_DIR` exists.
    """
    roots = roots or default_roots()
    now = time.time() if now is None else now
    registered = registered_worktrees() if registered is None else set(registered)
    own = [Path(p) for p in (own_paths or []) if p]
    refused = refused_roots(roots, project_folders)
    safe = _safe_roots(roots)

    budget = _Budget()
    groups = {}

    def add(key, title, note, path, name, kind, deletable_ok=True):
        try:
            st = Path(path).stat()
        except OSError:
            return
        mtime = st.st_mtime
        size, files, truncated, findings = _measure(path, refused, budget)
        live, reason = _liveness(path, name, mtime, now, registered, own)
        inside_safe = any(_within(path, r) for r in safe)
        entry = {
            "path": str(path), "name": name, "kind": kind,
            "sizeBytes": size, "files": files, "truncated": truncated,
            "modified": int(mtime),
            "idleHours": round(max(0.0, (now - mtime) / 3600.0), 1),
            "live": live, "liveReason": reason,
            "dataFindings": findings,
            "deletable": bool(deletable_ok and inside_safe and not live),
            "note": note,
        }
        if not entry["deletable"] and not live:
            entry["liveReason"] = entry["liveReason"] or (
                "Listed only - outside the folders this is allowed to delete from."
                if not inside_safe else "")
        g = groups.setdefault(key, {"key": key, "title": title, "entries": []})
        g["entries"].append(entry)

    _survey_worktrees(roots, add, registered)
    _survey_temp(roots, add, refused)
    _survey_scratch(roots, add, own)
    _survey_listed_only(roots, add)

    ordered = []
    for key in ("worktrees", "scratch", "tests", "temp", "drivers",
                "releases", "listed"):
        g = groups.get(key)
        if not g:
            continue
        g["entries"].sort(key=lambda e: e["modified"], reverse=True)
        g["totals"] = _totals(g["entries"])
        ordered.append(g)

    every = [e for g in ordered for e in g["entries"]]
    return {"ok": True, "groups": ordered, "totals": _totals(every),
            "processes": list_processes() if processes is None else processes,
            "liveWindowMinutes": LIVE_WINDOW_MINUTES,
            "dataScanComplete": budget.complete}


def _totals(entries):
    return {
        "count": len(entries),
        "sizeBytes": sum(e["sizeBytes"] for e in entries),
        "deletable": sum(1 for e in entries if e["deletable"]),
        "deletableBytes": sum(e["sizeBytes"] for e in entries if e["deletable"]),
        "live": sum(1 for e in entries if e["live"]),
        "withData": sum(1 for e in entries if e["dataFindings"]),
        "dataFindings": sum(e["dataFindings"] for e in entries),
    }


def _survey_worktrees(roots, add, registered):
    """`C:\\wd-worktrees` holds worktrees and nothing else.

    Three outcomes, and the third is the one nothing else catches: a folder
    that is not a worktree at all. `git worktree list` never shows it,
    `git worktree remove` does not apply to it and prune has nothing to
    prune - two of those sat invisible in the middle of this convention on
    2026-09-18, holding screenshots and a draft commit message.
    """
    root = Path(roots["worktrees"])
    if not root.is_dir():
        return
    for entry in _iterdir(root):
        is_worktree = (entry / ".git").exists()
        if entry.is_dir() and is_worktree:
            if _norm(entry) in registered:
                note = "A registered worktree."
            else:
                note = ("A worktree git no longer registers - the session that "
                        "made it never tore it down.")
            add("worktrees", "Worktrees", note, entry, entry.name, "worktree")
        else:
            add("worktrees", "Worktrees",
                "Not a worktree. No git command will ever clean this up.",
                entry, entry.name,
                "stray-dir" if entry.is_dir() else "stray-file")


def _survey_temp(roots, add, refused):
    root = Path(roots["temp"])
    if not root.is_dir():
        return
    scratch = _norm(roots["scratch"])
    for entry in _iterdir(root):
        if _norm(entry) == scratch:
            continue
        fam = _family_for(entry.name)
        if not fam:
            continue
        key, title, note = fam
        add(key, title, note, entry, entry.name,
            "dir" if entry.is_dir() else "file")


def _survey_scratch(roots, add, own):
    """Session scratchpads. One per session, and the current one is live."""
    root = Path(roots["scratch"])
    if not root.is_dir():
        return
    for entry in _iterdir(root):
        add("scratch", "Session scratchpads",
            "A session's scratch directory.", entry, entry.name,
            "dir" if entry.is_dir() else "file")


def _survey_listed_only(roots, add):
    """Inventoried, never deletable.

    Screenshots on his Desktop are the named example: a session wrote them
    there, they are almost certainly ours, and "almost certainly" is not the
    standard for deleting from somebody's desktop. He gets told they are
    there and decides himself.
    """
    for which, note in (
        ("desktop", "On your Desktop - listed only, never deleted from here."),
        ("downloads", "In Downloads - listed only, never deleted from here."),
    ):
        root = Path(roots.get(which) or "")
        if not str(root).strip() or not root.is_dir():
            continue
        for entry in _iterdir(root):
            if not _looks_like_our_output(entry):
                continue
            add("listed", "Ours, but somewhere we will not delete from",
                note, entry, entry.name,
                "dir" if entry.is_dir() else "file", deletable_ok=False)


#: Session output shapes. Narrow on purpose - this decides what gets named in
#: a report about his Desktop, and a loose rule there is noise he will learn
#: to ignore.
_OUR_OUTPUT = re.compile(
    r"^(cloud|walls|report|scale|prep|plantrim|organizer|capacity|aprename"
    r"|rename|settings|home|manual|guide|squirrel|dev|toolbar)[-_].*"
    r"\.(png|jpg|jpeg|gif|webp|pdf|html|json|txt|md)$", re.I)


def _looks_like_our_output(entry):
    name = entry.name
    if _OUR_OUTPUT.match(name):
        return True
    if re.fullmatch(r"WD-Wireless-Tools-v[\d.]+\.zip(\.sha256)?", name):
        return True
    # A folder named after one of our pages, holding only images, is a
    # screenshot set - that is the `cloud-chips` / `cloud-pro-pass` shape.
    if entry.is_dir() and re.match(
            r"^(cloud|walls|report|scale|prep|plantrim|dev|toolbar)[-_]", name, re.I):
        return True
    return False


def _iterdir(root):
    try:
        return sorted(Path(root).iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []


# ── the sweep ────────────────────────────────────────────────────

def sweep(paths, roots=None, now=None, registered=None, own_paths=None,
          project_folders=None, remover=None, processes=None):
    """Remove what the caller asked for, after checking it again.

    **The list is re-derived, not trusted.** Every path is looked up in a
    fresh survey and must still be marked deletable there. A path that went
    live in between, or that was never ours, is skipped and reported with the
    reason. That is the same rule the realign action follows: the proof has
    to be current at the moment of writing.
    """
    current = survey(roots=roots, now=now, registered=registered,
                     own_paths=own_paths, project_folders=project_folders,
                     processes=processes or [])
    allowed = {}
    for group in current["groups"]:
        for entry in group["entries"]:
            allowed[_norm(entry["path"])] = entry

    removed, skipped, failed = [], [], []
    for raw in paths or []:
        entry = allowed.get(_norm(raw))
        if entry is None:
            skipped.append({"path": str(raw), "name": Path(str(raw)).name,
                            "reason": "Not something this found, so not "
                                      "something it will delete."})
            continue
        if not entry["deletable"]:
            skipped.append({**entry,
                            "reason": entry["liveReason"] or
                            "No longer safe to remove."})
            continue
        ok, err = _remove(entry["path"], remover)
        if ok:
            removed.append(entry)
        else:
            failed.append({**entry, "error": err})

    return {"ok": True, "removed": removed, "skipped": skipped,
            "failed": failed,
            "counts": {"removed": len(removed), "skipped": len(skipped),
                       "failed": len(failed)},
            "freedBytes": sum(e["sizeBytes"] for e in removed)}


def _remove(path, remover=None):
    if remover is not None:
        try:
            remover(path)
            return True, ""
        except Exception as e:
            return False, str(e)
    import shutil
    p = Path(path)
    try:
        if p.is_dir():
            shutil.rmtree(p, onerror=_force_remove)
        else:
            p.unlink()
        return True, ""
    except OSError as e:
        return False, str(e)


def _force_remove(func, path, exc_info):
    """A read-only file inside a temp tree is still ours to delete. Same
    handler shape `cloud_manager` uses for the same reason."""
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass
