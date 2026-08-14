"""
WD Wireless Tools — local suite server.

Serves a WD-branded home page plus both tools (Cloud Manager, Quick Walls) as
browser pages, and exposes Cloud Manager's operations as JSON endpoints. Runs a
tiny local Flask server and opens your default browser to it.

    python server.py      (or just double-click run.bat)

No pywebview, no WebView2 — so none of the desktop-window headaches.
"""
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, redirect

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
sys.path.insert(0, str(HERE))
from tools.cloud_manager import CloudManager
from tools.folder_organizer import FolderOrganizer
from tools.template_store import TemplateStore

app = Flask(__name__, static_folder=None)
cm = CloudManager()
fo = FolderOrganizer()
ts = TemplateStore()
PORT = int(os.environ.get("PORT") or 8675)
API_REQUEST_HEADER = "X-WD-Wireless-Tools"
_LOCAL_API_HOSTS = {"localhost", "127.0.0.1"}


def _load_startup_versions():
    try:
        with (WEB / "assets" / "versions.json").open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_STARTUP_VERSIONS = _load_startup_versions()
_STARTED_AT = datetime.now(timezone.utc).isoformat()
fo.app_version = _STARTUP_VERSIONS.get("squirrel", "")


_progress_lock = threading.Lock()
_progress = {}


@app.before_request
def _protect_local_api():
    """Keep browser pages outside this local server from calling its API.

    A custom request header makes cross-site form submissions fail and forces
    cross-origin JavaScript through a CORS preflight, which this server never
    authorizes. The Host and Origin checks also close the DNS-rebinding route
    and reject forged cross-origin requests before an action is dispatched.
    """
    if not request.path.startswith("/api/"):
        return None

    hostname = request.host.partition(":")[0].lower().rstrip(".")
    if hostname not in _LOCAL_API_HOSTS:
        return jsonify({"error": "local API request rejected"}), 403

    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
        return jsonify({"error": "cross-origin API request rejected"}), 403

    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get(API_REQUEST_HEADER) != "1":
            return jsonify({"error": "missing local API request header"}), 403

    return None


def _progress_setter(op_id):
    """Return a progress_cb bound to op_id. Empty op_id → no-op (backward compat)."""
    if not op_id:
        return None

    def _cb(stage=None, current=None, total=None, message=None):
        with _progress_lock:
            slot = _progress.setdefault(op_id, {})
            if stage is not None: slot["stage"] = stage
            if current is not None: slot["current"] = current
            if total is not None: slot["total"] = total
            if message is not None: slot["message"] = message
    return _cb


@app.after_request
def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"


    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    return resp


@app.route("/")
def home():
    return send_from_directory(WEB, "home.html")


@app.route("/cloud")
def cloud():
    if (WEB / "cloud.html").exists():
        return send_from_directory(WEB, "cloud.html")
    return "Cloud Manager UI is being set up…", 200


@app.route("/walls")
def walls():
    return send_from_directory(WEB, "walls.html")


@app.route("/squirrel")
def organizer():
    return send_from_directory(WEB, "organizer.html")


@app.route("/organizer")
def organizer_legacy_redirect():
    return redirect("/squirrel", code=302)


@app.route("/scale")
def scale():
    return send_from_directory(WEB, "scale.html")


@app.route("/report")
def report():
    return send_from_directory(WEB, "report.html")


@app.route("/guide")
def guide():
    return send_from_directory(WEB, "guide.html")


@app.route("/guide-cloud")
def guide_cloud():
    return send_from_directory(WEB, "guide-cloud.html")


@app.route("/guide-squirrel")
def guide_organizer():
    return send_from_directory(WEB, "guide-organizer.html")


@app.route("/guide-organizer")
def guide_organizer_legacy_redirect():
    return redirect("/guide-squirrel", code=302)


@app.route("/guide-report")
def guide_report():
    return send_from_directory(WEB, "guide-report.html")


@app.route("/assets/<path:fn>")
def assets(fn):
    return send_from_directory(WEB / "assets", fn)


@app.route("/favicon.ico")
def favicon():


    return send_from_directory(WEB, "favicon.ico", mimetype="image/vnd.microsoft.icon")


ORGANIZER_ACTIONS = {
    "pick_folder":  lambda d: fo.pick_folder(),
    "set_folder":   lambda d: fo.set_folder(d["path"]),
    "scan":         lambda d: fo.scan(d.get("root")),
    "execute":      lambda d: fo.execute(d.get("root"), d.get("excluded"), d.get("overrides")),
    "undo":         lambda d: fo.undo(d.get("root")),
    "has_undo":     lambda d: fo.has_undo(d.get("root")),
    "suggest_groups": lambda d: fo.suggest_groups(d.get("root")),
    "apply_grouping": lambda d: fo.apply_grouping(d.get("root"), d.get("groups")),
    "migrate_subfolders": lambda d: fo.migrate_subfolders(d.get("root"), d.get("renames")),
    "detect_rename_style": lambda d: fo.detect_rename_style(d.get("root")),
    "preview_bulk_rename": lambda d: fo.preview_bulk_rename(d.get("root"), d.get("rename")),
    "execute_bulk_rename": lambda d: fo.execute_bulk_rename(d.get("items")),
    "get_config":   lambda d: fo.get_config(),
    "set_config":   lambda d: fo.set_config(d.get("config", {})),
    "reset_config": lambda d: fo.reset_config(),
    "create_project_folder": lambda d: fo.create_project_folder(d["name"], d.get("root"), d.get("subfolders")),
    "list_root_folders": lambda d: fo.list_root_folders(d.get("root")),
    "pick_esx_file": lambda d: fo.pick_esx_file(),
    "pick_output_folder": lambda d: fo.pick_output_folder(d.get("default")),
    "list_floorplans": lambda d: fo.list_floorplans(d["path"]),
    "extract_floorplans": lambda d: fo.extract_floorplans(d["path"], d.get("selections"), d.get("out_dir"), d.get("floor_ids")),
    "save_esx_info": lambda d: fo.save_esx_info(d["path"]),
}


@app.route("/api/organizer/<action>", methods=["POST"])
def api_organizer(action):
    fn = ORGANIZER_ACTIONS.get(action)
    if not fn:
        return jsonify({"error": f"unknown action: {action}"}), 404
    try:
        data = request.get_json(silent=True) or {}
        return jsonify(fn(data))
    except KeyError as e:
        return jsonify({"error": f"missing field: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


TEMPLATE_ACTIONS = {
    "get_folder":   lambda d: ts.get_folder(),
    "scan":         lambda d: ts.scan(),
    "save":         lambda d: ts.save(d["name"], d["wallTypes"]),
    "delete":       lambda d: ts.delete(d["filename"]),
    "defaults":     lambda d: ts.get_defaults(),
}


@app.route("/api/templates/<action>", methods=["POST"])
def api_templates(action):
    fn = TEMPLATE_ACTIONS.get(action)
    if not fn:
        return jsonify({"error": f"unknown action: {action}"}), 404
    try:
        data = request.get_json(silent=True) or {}
        return jsonify(fn(data))
    except KeyError as e:
        return jsonify({"error": f"missing field: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


CLOUD_ACTIONS = {
    "status": lambda d: cm.status(),
    "open_login": lambda d: cm.open_login(),
    "forget_login": lambda d: cm.forget_login(),
    "get_data": lambda d: cm.get_data(d.get("kind", "sites")),
    "rename_cloud": lambda d: cm.rename_cloud(d["kind"], d["id"], d["name"]),
    "delete_cloud": lambda d: cm.delete_cloud(d["kind"], d["id"]),
    "create_site": lambda d: cm.create_site(d["name"]),
    "upload_project": lambda d: cm.upload_project(d["path"], d.get("siteId"),
                                                     progress_cb=_progress_setter(d.get("opId"))),
    "download_project": lambda d: cm.download_project(d["projectId"], d["folder"],
                                                        progress_cb=_progress_setter(d.get("opId"))),
    "assign_to_site": lambda d: cm.assign_to_site(d["siteId"], d["datasetId"]),
    "rename_local": lambda d: cm.rename_local(d["path"], d["name"]),
    "delete_local": lambda d: cm.delete_local(d["path"]),
    "create_local_folder": lambda d: cm.create_local_folder(d["name"]),
    "move_local_to_site": lambda d: cm.move_local_to_site(d["path"], d["folder"]),
    "merge_preview": lambda d: cm.merge_preview(d["src"], d["dst"]),
    "merge_execute": lambda d: cm.merge_execute(d["src"], d["dst"], d.get("ops", [])),
    "pick_folder": lambda d: cm.pick_folder(),
    "set_folder": lambda d: cm.set_folder(d["path"]),
    "reveal_in_explorer": lambda d: cm.reveal_in_explorer(d["path"]),
    "get_duplicates": lambda d: cm.get_duplicates(),
    "mark_not_match": lambda d: cm.mark_not_match(d.get("cloudId"), d.get("localPath"),
                                                    d.get("cloudName", ""), d.get("localName", "")),
    "unmark_not_match": lambda d: cm.unmark_not_match(d.get("cloudId"), d.get("localPath")),
    "list_not_matches": lambda d: cm.list_not_matches(),
    "mark_manual_match": lambda d: cm.mark_manual_match(d.get("cloudId"), d.get("localPath"),
                                                        d.get("cloudName", ""), d.get("localName", "")),
    "unmark_manual_match": lambda d: cm.unmark_manual_match(d.get("cloudId"), d.get("localPath")),
    "list_manual_matches": lambda d: cm.list_manual_matches(),
    "verify_replace_local": lambda d: cm.verify_replace_local(d.get("cloudId"), d.get("localPath")),
    "list_shares": lambda d: cm.list_shares(d.get("projectId")),
    "add_share": lambda d: cm.add_share(d.get("projectId"), d.get("email"), d.get("role", "READ_USER")),
    "remove_share": lambda d: cm.remove_share(d.get("projectId"), d.get("email")),
    "change_share_role": lambda d: cm.change_share_role(d.get("projectId"), d.get("email"), d.get("role")),
    "toggle_group_share": lambda d: cm.toggle_group_share(d.get("projectId"), d.get("groupId"),
                                                          d.get("groupName", ""), d.get("role", "READ_USER"),
                                                          d.get("enable", False)),
    "transfer_ownership": lambda d: cm.transfer_ownership(d.get("projectId"), d.get("newOwnerEmail")),
    "bulk_share": lambda d: cm.bulk_share(
        d.get("projectIds") or [],
        d.get("emails") or [],
        d.get("role") or "READ_USER",
        bool(d.get("shareWithGroup")),
        d.get("groupId"),
        d.get("groupName") or "",
        d.get("groupRole") or "READ_USER"),
    "get_my_group": lambda d: cm.get_my_group(d.get("groupName") or "My Sharing Group"),
    "add_group_member": lambda d: cm.add_group_member(d.get("email"), d.get("groupName") or "My Sharing Group"),
    "remove_group_member": lambda d: cm.remove_group_member(d.get("email"), d.get("groupName") or "My Sharing Group"),
    "refresh_group_shares": lambda d: cm.refresh_group_shares(
        d.get("groupName") or "My Sharing Group",
        bool(d.get("dryRun")),
        d.get("projectIds")),
}


@app.route("/api/cloud/<action>", methods=["POST"])
def api_cloud(action):
    fn = CLOUD_ACTIONS.get(action)
    if not fn:
        return jsonify({"error": f"unknown action: {action}"}), 404
    try:
        data = request.get_json(silent=True) or {}
        op_id = data.get("opId")
        try:
            return jsonify(fn(data))
        finally:


            if op_id:
                with _progress_lock:
                    _progress.pop(op_id, None)
    except KeyError as e:
        return jsonify({"error": f"missing field: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/version", methods=["GET"])
def api_version():
    """Startup snapshot of versions.json + process metadata. The frontend
    compares this to a fresh fetch of /assets/versions.json and shows a
    banner if they diverge (meaning the user pulled new code but the
    Python process is still running the old build)."""
    return jsonify({
        "versions": _STARTUP_VERSIONS,
        "startedAt": _STARTED_AT,
        "pid": os.getpid(),
    })


RESTART_MARKER = HERE / ".restart_requested"


def _restart_after_response():
    """Drop the sentinel file the launcher watches, then exit hard so the
    launcher's loop relaunches us. Runs in a background thread so the
    /api/restart HTTP response has a moment to flush to the browser
    before Waitress gets torn down. os._exit skips atexit handlers —
    deliberate, we want the socket released fast so the next process
    can bind the same port without a TIME_WAIT gap."""
    try:
        RESTART_MARKER.write_text("1", encoding="ascii")
    except Exception:


        pass
    time.sleep(0.3)
    os._exit(0)


@app.route("/api/restart", methods=["POST"])
def api_restart():
    """Restart the server in place. The stale-server banner uses this so a
    pinned browser tab can recover from a code/build mismatch without the
    user hunting for the terminal window. Same URL, same port — relies on
    the launcher's loop, which is why closing the launcher's console (or
    starting the server via an unwrapped `python server.py`) means the
    restart hits an exit with no relaunch. That's intentional: the ONLY
    path we support for restart is through the launcher."""
    threading.Thread(target=_restart_after_response, daemon=True).start()
    return jsonify({"ok": True, "message": "restarting"})


@app.route("/api/cloud/progress", methods=["GET"])
def api_cloud_progress():
    op_id = request.args.get("id", "")
    if not op_id:
        return jsonify({"error": "missing id"}), 400
    with _progress_lock:
        snap = dict(_progress.get(op_id) or {})

    return jsonify(snap)


def _open_browser():
    time.sleep(1.0)
    webbrowser.open(f"http://localhost:{PORT}/")


def _print_banner():


    logo = [
        " __          __  _____ ",
        " \\ \\        / / |  __ \\",
        "  \\ \\  /\\  / /  | |  | |",
        "   \\ \\/  \\/ /   | |  | |",
        "    \\  /\\  /    | |__| |",
        "     \\/  \\/     |_____/ ",
    ]
    version = _STARTUP_VERSIONS.get("suite")
    title = "WIRELESS TOOLS" + (f"  v{version}" if version else "")
    lines = [
        title,
        "A suite of Ekahau workflow tools.",
        "",
        f"Local suite: http://localhost:{PORT}/",
        "Press CTRL+C in this window to stop WD Wireless Tools.",
    ]
    width = max([len(line) for line in lines] + [len(l) for l in logo]) + 4
    border = "=" * width
    print("\n" + border)
    for l in logo:
        print("  " + l)
    print()
    for line in lines:
        print("  " + line if line else "")


    print(border + "\n", flush=True)


def main():
    _print_banner()
    threading.Thread(target=_open_browser, daemon=True).start()


    try:
        from waitress import serve
        serve(app, host="127.0.0.1", port=PORT, threads=8, _quiet=True)
    except ImportError:

        print("  (waitress not installed — falling back to Flask dev server)\n")
        app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
