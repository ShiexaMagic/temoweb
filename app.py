"""
Admin app for the portfolio site.

  /            live preview of the public page (rendered from content.json)
  /admin       the editor — every text, image, link and section on the page

Saving in the admin writes content.json, rebuilds the static index.html and
commits both (plus any uploaded images) to GitHub, which redeploys the
public site on Vercel.
"""
import hashlib
import io
import json
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
from publisher import Publisher

# ── Configuration ───────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "admin_config.json")
IMAGES_DIR = site_content.IMAGES_DIR

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
FILE_EXTENSIONS = {"pdf"}
MAX_IMAGE_SIDE = 2400          # px — larger uploads are scaled down
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Hosting env vars (set these in the Railway dashboard)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "ShiexaMagic/temoweb")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

app = Flask(__name__, template_folder="templates")
publisher = Publisher(
    BASE, GITHUB_REPO, GITHUB_TOKEN, GITHUB_BRANCH,
    api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
)


def _load_admin_config():
    # ── Hosted mode: credentials from environment variables ──────
    if os.environ.get("ADMIN_PASSWORD_HASH"):
        return {
            "username": os.environ.get("ADMIN_USERNAME", "admin"),
            "password_hash": os.environ["ADMIN_PASSWORD_HASH"],
            "hosted": True,
        }
    # ── Local mode: credentials from admin_config.json ───────────
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


HOSTED = bool(os.environ.get("ADMIN_PASSWORD_HASH"))
app.secret_key = (
    os.environ.get("SECRET_KEY")
    or _load_admin_config().get("secret_key")
    or secrets.token_hex(32)
)
app.config.update(
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=HOSTED,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


# ── Helpers ─────────────────────────────────────────────────────
def _ext(filename):
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def _safe_name(filename):
    """Only plain filenames inside Images/ — no paths."""
    name = os.path.basename(filename or "")
    if not name or name.startswith(".") or name != filename:
        return None
    return name


def _list_uploads():
    used = site_content.referenced_images(site_content.load_content())
    files = []
    for name in sorted(os.listdir(IMAGES_DIR), key=str.lower):
        ext = _ext(name)
        if ext in IMAGE_EXTENSIONS or ext in FILE_EXTENSIONS:
            files.append({
                "name": name,
                "kind": "image" if ext in IMAGE_EXTENSIONS else "file",
                "size": os.path.getsize(os.path.join(IMAGES_DIR, name)),
                "used": name in used,
            })
    return files


def _process_image(data, ext):
    """Fix phone-camera rotation and scale huge photos down.  Returns
    (bytes, extension).  Falls back to the original bytes if anything fails."""
    if ext == "gif":
        return data, ext
    try:
        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        if max(img.size) <= MAX_IMAGE_SIDE and len(data) < 1_500_000:
            return data, ext
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        out = io.BytesIO()
        if ext == "png" and img.mode in ("RGBA", "LA", "P"):
            img.save(out, "PNG", optimize=True)
        elif ext == "webp":
            img.save(out, "WEBP", quality=86)
        else:
            img.convert("RGB").save(out, "JPEG", quality=86, optimize=True, progressive=True)
            ext = "jpg"
        return out.getvalue(), ext
    except Exception as exc:  # noqa: BLE001 — never block an upload on this
        print(f"[image processing skipped] {exc}")
        return data, ext


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Your session expired — please sign in again."}), 401
            return redirect(url_for("admin_login"))
        # Changes must come from the admin page itself, not a foreign form.
        if request.method != "GET" and request.path.startswith("/api/"):
            if request.headers.get("X-Requested-With") != "admin":
                return jsonify({"error": "Bad request"}), 400
        return f(*args, **kwargs)

    return decorated


# ── Public routes ────────────────────────────────────────────────
@app.route("/")
def index():
    return Response(site_content.render_site(), mimetype="text/html")


@app.route("/styles.css")
def styles():
    return send_from_directory(BASE, "styles.css")


@app.route("/script.js")
def scriptjs():
    return send_from_directory(BASE, "script.js")


@app.route("/Images/<path:filename>")
def images(filename):
    return send_from_directory(IMAGES_DIR, filename)


# ── Admin auth ───────────────────────────────────────────────────
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


# ── Content API ──────────────────────────────────────────────────
@app.route("/api/content", methods=["GET"])
@login_required
def api_get_content():
    return jsonify({
        "content": site_content.load_content(),
        "uploads": _list_uploads(),
        "publish": publisher.status(),
        "hosted": HOSTED,
    })


@app.route("/api/content", methods=["PUT"])
@login_required
def api_save_content():
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid data"}), 400
    saved = site_content.save_content(data)
    try:
        site_content.build()
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Saved, but the page could not be rebuilt: {exc}"}), 500
    publisher.enqueue(["content.json", "index.html"], _s(data.get("_note")) or "update content")
    return jsonify({"ok": True, "content": saved, "uploads": _list_uploads(),
                    "publish": publisher.status()})


def _s(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:80]


# ── Uploads API ──────────────────────────────────────────────────
@app.route("/api/images", methods=["GET"])
@login_required
def api_list_images():
    return jsonify(_list_uploads())


@app.route("/api/upload", methods=["POST"])
@login_required
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file provided"}), 400
    ext = _ext(f.filename)
    if ext not in IMAGE_EXTENSIONS and ext not in FILE_EXTENSIONS:
        return jsonify({"error": "Unsupported file type. Use JPG, PNG, WebP, GIF or PDF."}), 400
    data = f.read()
    if ext in IMAGE_EXTENSIONS:
        data, ext = _process_image(data, ext)
    # Content-hashed name: the public site caches images for a year, so a
    # changed image must always get a new name.
    stem = site_content._slug(os.path.basename(f.filename).rsplit(".", 1)[0]) or "file"
    filename = f"{stem}-{hashlib.sha1(data).hexdigest()[:8]}.{ext}"
    with open(os.path.join(IMAGES_DIR, filename), "wb") as out:
        out.write(data)
    publisher.enqueue([f"Images/{filename}"], "upload file")
    return jsonify({"filename": filename, "uploads": _list_uploads()})


@app.route("/api/images/<path:filename>", methods=["DELETE"])
@login_required
def api_delete_image(filename):
    name = _safe_name(filename)
    path = os.path.join(IMAGES_DIR, name) if name else None
    if not path or not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404
    if name in site_content.referenced_images(site_content.load_content()):
        return jsonify({"error": "This image is used on the site. Replace it there first."}), 409
    os.remove(path)
    publisher.enqueue([f"Images/{name}"], "delete file")
    return jsonify({"ok": True, "uploads": _list_uploads()})


# ── Publishing / settings API ────────────────────────────────────
@app.route("/api/publish-status", methods=["GET"])
@login_required
def api_publish_status():
    return jsonify(publisher.status())


@app.route("/api/publish-retry", methods=["POST"])
@login_required
def api_publish_retry():
    publisher.retry()
    return jsonify(publisher.status())


@app.route("/api/change-password", methods=["POST"])
@login_required
def api_change_password():
    if HOSTED:
        return jsonify({
            "error": "On the hosted site the password is set by the ADMIN_PASSWORD_HASH "
                     "environment variable in the Railway dashboard."
        }), 400
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


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "File is too large (25 MB maximum)."}), 413


if __name__ == "__main__":
    app.run(debug=True, port=5000)
