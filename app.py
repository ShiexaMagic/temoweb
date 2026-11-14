"""
The editor for the portfolio site.

  /admin       every text, image, link and section of the page
  /api/*       what the editor page talks to

The public site is the static index.html.  Saving in the editor rebuilds
that file from content.json + templates/index.html and commits it — with
content.json and any new images — to GitHub in one commit; Vercel then
redeploys.  Runs as a Vercel serverless function (api/index.py) or locally
with `python app.py`.
"""
import hashlib
import json
import mimetypes
import os
import re
import secrets
import time
from datetime import timedelta
from functools import wraps

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import site_content
from store import StoreError, make_store

# ── Configuration ───────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "admin_config.json")

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
FILE_EXTENSIONS = {"pdf"}
# Vercel rejects request bodies over 4.5 MB; the editor shrinks photos in
# the browser before sending them.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
UPLOAD_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*-[0-9a-f]{8}\.(jpg|jpeg|png|webp|gif|pdf)$")
BLOB_SHA = re.compile(r"^[0-9a-f]{40}$")

# Hosted mode: the login comes from environment variables (Vercel settings).
HOSTED = bool(os.environ.get("ADMIN_PASSWORD_HASH"))

app = Flask(__name__, template_folder="templates")
store = make_store(BASE)


def _load_admin_config():
    if HOSTED:
        return {
            "username": os.environ.get("ADMIN_USERNAME", "admin"),
            "password_hash": os.environ["ADMIN_PASSWORD_HASH"],
        }
    # Local mode: credentials in admin_config.json (never committed).
    if not os.path.exists(CONFIG_FILE):
        cfg = {
            "username": "admin",
            "password_hash": generate_password_hash("admin"),
            "secret_key": secrets.token_hex(32),
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        print("\n⚠  First run: admin credentials set to  admin / admin")
        print("   Go to /admin and change the password immediately.\n")
        return cfg
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    if HOSTED:
        # Must be identical on every serverless instance, so derive it from
        # another secret rather than generating a random one.
        seed = os.environ["ADMIN_PASSWORD_HASH"] + os.environ.get("GITHUB_TOKEN", "")
        return hashlib.sha256(("session:" + seed).encode()).hexdigest()
    return _load_admin_config().get("secret_key") or secrets.token_hex(32)


app.secret_key = _secret_key()
app.config.update(
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES + 64 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=HOSTED,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


# ── Helpers ─────────────────────────────────────────────────────
def _ext(filename):
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def _load_content():
    return site_content.parse(store.read("content.json"))


def _uploads(content, extra_names=()):
    """Files in Images/ (plus not-yet-saved uploads), for the editor."""
    used = site_content.referenced_images(content)
    files = []
    for entry in store.list_dir("Images"):
        ext = _ext(entry["name"])
        if ext in IMAGE_EXTENSIONS or ext in FILE_EXTENSIONS:
            files.append({
                "name": entry["name"],
                "kind": "image" if ext in IMAGE_EXTENSIONS else "file",
                "size": entry["size"],
                "used": entry["name"] in used,
            })
    known = {f["name"] for f in files}
    for name in extra_names:
        if name not in known:
            files.append({"name": name, "kind": "image" if _ext(name) in IMAGE_EXTENSIONS else "file",
                          "size": 0, "used": name in used})
    return sorted(files, key=lambda f: f["name"].lower())


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Your session expired — please sign in again."}), 401
            return redirect(url_for("admin_login"))
        # Changes must come from the editor page itself, not a foreign form.
        if request.method != "GET" and request.headers.get("X-Requested-With") != "admin":
            return jsonify({"error": "Bad request"}), 400
        return f(*args, **kwargs)

    return decorated


@app.after_request
def no_cache(resp):
    if request.path.startswith(("/admin", "/api/")) and "Cache-Control" not in resp.headers:
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(StoreError)
def store_error(exc):
    return jsonify({"error": str(exc)}), 502


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "File is too large (4 MB maximum)."}), 413


# ── Local development only: on Vercel these paths are static files ──
@app.route("/")
def index():
    content = _load_content()
    names = [e["name"] for e in store.list_dir("Images")]
    return Response(site_content.render_site(content, names), mimetype="text/html")


@app.route("/styles.css")
def styles():
    return send_from_directory(BASE, "styles.css")


@app.route("/script.js")
def scriptjs():
    return send_from_directory(BASE, "script.js")


@app.route("/Images/<path:filename>")
def images(filename):
    return send_from_directory(os.path.join(BASE, "Images"), filename)


# ── Sign in ──────────────────────────────────────────────────────
_failed_logins = {}   # ip -> [timestamps]
LOGIN_WINDOW, LOGIN_MAX = 300, 8


def _client_ip():
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr or "?")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        ip, now = _client_ip(), time.time()
        recent = [t for t in _failed_logins.get(ip, []) if now - t < LOGIN_WINDOW]
        if len(recent) >= LOGIN_MAX:
            error = "Too many attempts. Please wait a few minutes and try again."
        else:
            cfg = _load_admin_config()
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if username == cfg["username"] and check_password_hash(cfg["password_hash"], password):
                _failed_logins.pop(ip, None)
                session.clear()
                session["logged_in"] = True
                session.permanent = True
                return redirect(url_for("admin_dashboard"))
            time.sleep(0.6)   # slow down guessing
            recent.append(now)
            error = "Wrong username or password."
        _failed_logins[ip] = recent
    return render_template("admin/login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin")
@app.route("/admin/")
@login_required
def admin_dashboard():
    return render_template("admin/dashboard.html")


@app.route("/admin/file/<path:filename>")
@login_required
def admin_file(filename):
    """An image straight from storage — for files saved moments ago that the
    public site has not finished deploying yet."""
    if "/" in filename or filename.startswith("."):
        return "", 404
    data = store.read("Images/" + filename)
    if data is None:
        return "", 404
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(data, mimetype=mime, headers={"Cache-Control": "private, max-age=86400"})


# ── Content API ──────────────────────────────────────────────────
@app.route("/api/content", methods=["GET"])
@login_required
def api_get_content():
    content = _load_content()
    return jsonify({
        "content": content,
        "uploads": _uploads(content),
        "hosted": HOSTED,
        "publishes": store.publishes,
    })


@app.route("/api/content", methods=["PUT"])
@login_required
def api_save_content():
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("content"), dict):
        return jsonify({"error": "Invalid data"}), 400
    content = site_content.normalize(body["content"])

    # Uploads made since the last save: filename -> staged blob.
    new_files = body.get("new_files") or {}
    changes = {}
    for name, sha in new_files.items():
        if not UPLOAD_NAME.match(str(name)) or not BLOB_SHA.match(str(sha)):
            return jsonify({"error": "Invalid upload. Please upload the file again."}), 400
        changes["Images/" + name] = {"blob": sha}

    existing = [e["name"] for e in store.list_dir("Images")]
    changes["content.json"] = site_content.dump(content)
    changes["index.html"] = site_content.render_site(content, existing + list(new_files)).encode("utf-8")
    store.commit(changes, "admin: update site")
    return jsonify({"ok": True, "content": content, "uploads": _uploads(content, new_files)})


# ── Uploads API ──────────────────────────────────────────────────
@app.route("/api/upload", methods=["POST"])
@login_required
def api_upload():
    """Stage a file.  It becomes part of the site at the next save."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file provided"}), 400
    ext = _ext(f.filename)
    if ext not in IMAGE_EXTENSIONS and ext not in FILE_EXTENSIONS:
        return jsonify({"error": "Unsupported file type. Use JPG, PNG, WebP, GIF or PDF."}), 400
    data = f.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return jsonify({"error": "File is too large (4 MB maximum)."}), 413
    # Content-hashed name: the public site caches images for a year, so a
    # changed image must always get a new name.
    stem = site_content._slug(os.path.basename(f.filename).rsplit(".", 1)[0]) or "file"
    filename = f"{stem}-{hashlib.sha1(data).hexdigest()[:8]}.{ext}"
    return jsonify({
        "filename": filename,
        "sha": store.put_blob(data),
        "kind": "image" if ext in IMAGE_EXTENSIONS else "file",
        "size": len(data),
    })


@app.route("/api/images/<path:filename>", methods=["DELETE"])
@login_required
def api_delete_image(filename):
    content = _load_content()
    names = {e["name"] for e in store.list_dir("Images")}
    if "/" in filename or filename not in names:
        return jsonify({"error": "File not found"}), 404
    if filename in site_content.referenced_images(content):
        return jsonify({"error": "This image is used on the site. Replace it there first."}), 409
    store.commit({"Images/" + filename: None}, "admin: delete " + filename)
    remaining = [u for u in _uploads(content) if u["name"] != filename]
    return jsonify({"ok": True, "uploads": remaining})


# ── Account ──────────────────────────────────────────────────────
@app.route("/api/change-password", methods=["POST"])
@login_required
def api_change_password():
    if HOSTED:
        return jsonify({"error": "On the hosted site the password is set by the "
                                 "ADMIN_PASSWORD_HASH variable in the Vercel project settings."}), 400
    data = request.get_json(force=True, silent=True) or {}
    cfg = _load_admin_config()
    if not check_password_hash(cfg["password_hash"], data.get("current", "")):
        return jsonify({"error": "Current password is incorrect"}), 403
    if len(data.get("new", "")) < 8:
        return jsonify({"error": "New password must be at least 8 characters"}), 400
    cfg["password_hash"] = generate_password_hash(data["new"])
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
