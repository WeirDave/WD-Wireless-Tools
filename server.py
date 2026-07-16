"""
WD Wireless Tools — local suite server.

Serves a WD-branded home page plus both tools (Cloud Manager, Quick Walls) as
browser pages, and exposes Cloud Manager's operations as JSON endpoints. Runs a
tiny local Flask server and opens your default browser to it.

    python server.py      (or just double-click run.bat)

No pywebview, no WebView2 — so none of the desktop-window headaches.
"""
import sys
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
sys.path.insert(0, str(HERE))
from tools.cloud_manager import CloudManager  # noqa: E402
from tools.folder_organizer import FolderOrganizer  # noqa: E402
from tools.template_store import TemplateStore  # noqa: E402

app = Flask(__name__, static_folder=None)
cm = CloudManager()
fo = FolderOrganizer()
ts = TemplateStore()
PORT = 8765


# Local dev tool — never let the browser cache pages/assets, so edits always
# show up on a plain refresh instead of serving a stale copy.
@app.after_request
def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ── pages ─────────────────────────────────────────────────────────────
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


@app.route("/organizer")
def organizer():
    return send_from_directory(WEB, "organizer.html")


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


@app.route("/guide-organizer")
def guide_organizer():
    return send_from_directory(WEB, "guide-organizer.html")


@app.route("/assets/<path:fn>")
def assets(fn):
    return send_from_directory(WEB / "assets", fn)


# ── Folder Organizer API ─────────────────────────────────────────────
ORGANIZER_ACTIONS = {
    "pick_folder":  lambda d: fo.pick_folder(),
    "set_folder":   lambda d: fo.set_folder(d["path"]),
    "scan":         lambda d: fo.scan(d.get("root")),
    "execute":      lambda d: fo.execute(d.get("root"), d.get("excluded"), d.get("overrides")),
    "get_config":   lambda d: fo.get_config(),
    "set_config":   lambda d: fo.set_config(d.get("config", {})),
    "reset_config": lambda d: fo.reset_config(),
    "create_project_folder": lambda d: fo.create_project_folder(d["name"], d.get("root")),
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


# ── Quick Walls Template API ──────────────────────────────────────────
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


# ── Cloud Manager API ─────────────────────────────────────────────────
CLOUD_ACTIONS = {
    "status": lambda d: cm.status(),
    "open_login": lambda d: cm.open_login(),
    "get_data": lambda d: cm.get_data(d.get("kind", "sites")),
    "rename_cloud": lambda d: cm.rename_cloud(d["kind"], d["id"], d["name"]),
    "delete_cloud": lambda d: cm.delete_cloud(d["kind"], d["id"]),
    "create_site": lambda d: cm.create_site(d["name"]),
    "upload_project": lambda d: cm.upload_project(d["path"], d.get("siteId")),
    "assign_to_site": lambda d: cm.assign_to_site(d["siteId"], d["datasetId"]),
    "rename_local": lambda d: cm.rename_local(d["path"], d["name"]),
    "delete_local": lambda d: cm.delete_local(d["path"]),
    "create_local_folder": lambda d: cm.create_local_folder(d["name"]),
    "merge_preview": lambda d: cm.merge_preview(d["src"], d["dst"]),
    "merge_execute": lambda d: cm.merge_execute(d["src"], d["dst"], d.get("ops", [])),
    "pick_folder": lambda d: cm.pick_folder(),
    "reveal_in_explorer": lambda d: cm.reveal_in_explorer(d["path"]),
    "get_duplicates": lambda d: cm.get_duplicates(),
    "mark_not_match": lambda d: cm.mark_not_match(d.get("cloudId"), d.get("localPath"),
                                                    d.get("cloudName", ""), d.get("localName", "")),
    "unmark_not_match": lambda d: cm.unmark_not_match(d.get("cloudId"), d.get("localPath")),
    "list_not_matches": lambda d: cm.list_not_matches(),
}


@app.route("/api/cloud/<action>", methods=["POST"])
def api_cloud(action):
    fn = CLOUD_ACTIONS.get(action)
    if not fn:
        return jsonify({"error": f"unknown action: {action}"}), 404
    try:
        data = request.get_json(silent=True) or {}
        return jsonify(fn(data))
    except KeyError as e:
        return jsonify({"error": f"missing field: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── launch ────────────────────────────────────────────────────────────
def _open_browser():
    time.sleep(1.0)
    webbrowser.open(f"http://localhost:{PORT}/")


def main():
    print(f"\n  WD Wireless Tools  →  http://localhost:{PORT}/\n")
    threading.Thread(target=_open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
