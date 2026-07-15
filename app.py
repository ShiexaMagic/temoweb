import json
import os
import secrets
import subprocess
import sys
import threading
from functools import wraps

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# ── Configuration ───────────────────────────────────────────────
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}

BASE = os.path.dirname(os.path.abspath(__file__))
CONTENT_FILE = os.path.join(BASE, "content.json")
CONFIG_FILE = os.path.join(BASE, "admin_config.json")
IMAGES_DIR = os.path.join(BASE, "Images")

# Git / hosting env vars (set these in Railway dashboard)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "ShiexaMagic/temoweb")

# Ensure build.py is importable from the background thread
if BASE not in sys.path:
    sys.path.insert(0, BASE)

app = Flask(__name__, template_folder="templates")


def _load_secret_key():
    # Env var takes priority (Railway / production)
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    cfg = _load_admin_config()
    return cfg.get("secret_key", secrets.token_hex(32))


def _load_admin_config():
    # ── Hosted mode: credentials from environment variables ──────
    if os.environ.get("ADMIN_PASSWORD_HASH"):
        return {
            "username": os.environ.get("ADMIN_USERNAME", "admin"),
            "password_hash": os.environ["ADMIN_PASSWORD_HASH"],
            "secret_key": os.environ.get("SECRET_KEY", secrets.token_hex(32)),
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


app.secret_key = _load_secret_key()


def _configure_git():
    """Set git identity and token-authenticated remote URL (for Railway)."""
    try:
        if GITHUB_TOKEN:
            remote_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
            subprocess.run(["git", "remote", "set-url", "origin", remote_url],
                           cwd=BASE, capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "admin@temorekhviashvili.com"],
                       cwd=BASE, capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.name", "Temo Rekhviashvili"],
                       cwd=BASE, capture_output=True, timeout=10)
    except Exception as exc:  # git not in PATH or other OS error — non-fatal
        print(f"[git config] skipped: {exc}")


_configure_git()


# ── Helpers ─────────────────────────────────────────────────────
def load_content():
    with open(CONTENT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_content(data):
    with open(CONTENT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Git auto-push ────────────────────────────────────────────────
_push_status = {"status": "idle", "message": ""}


def git_auto_push(section):
    """Commit content.json and push to remote in a background thread."""
    def _push():
        global _push_status
        _push_status = {"status": "pushing", "message": "Building & pushing…"}
        try:
            # 1. Regenerate static index.html for Vercel
            import build as _build
            _build.build()

            # 2. Ensure on main branch (Railway deploys detached HEAD)
            subprocess.run(["git", "checkout", "-B", "main"],
                           cwd=BASE, capture_output=True, timeout=10)

            # 3. Stage both data file and built HTML
            subprocess.run(
                ["git", "add", "content.json", "index.html"],
                cwd=BASE, capture_output=True, timeout=10
            )
            commit = subprocess.run(
                ["git", "commit", "-m", f"admin: update {section}"],
                cwd=BASE, capture_output=True, timeout=10, text=True
            )
            # nothing new to commit — that’s fine
            if commit.returncode not in (0, 1):
                _push_status = {"status": "error", "message": commit.stderr.strip()}
                return
            push = subprocess.run(
                ["git", "push", "origin", "HEAD:main"],
                cwd=BASE, capture_output=True, timeout=30, text=True
            )
            if push.returncode == 0:
                _push_status = {"status": "ok", "message": "Built & pushed → Vercel deploying"}
            else:
                _push_status = {"status": "error", "message": push.stderr.strip() or push.stdout.strip()}
                print(f"[git push error] {_push_status['message']}")
        except Exception as exc:
            _push_status = {"status": "error", "message": str(exc)}

    threading.Thread(target=_push, daemon=True).start()


def load_admin_config():
    return _load_admin_config()


def save_admin_config(cfg):
    if _load_admin_config().get("hosted"):
        # In hosted mode credentials live in Railway env vars — cannot be
        # written to a file that survives restarts.  Return silently; the
        # /api/change-password route will surface an appropriate message.
        return
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)

    return decorated


# ── Public routes ────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", content=load_content())


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
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        cfg = load_admin_config()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == cfg["username"] and check_password_hash(
            cfg["password_hash"], password
        ):
            session["logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        error = "Invalid credentials."
    return render_template("admin/login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# ── Admin dashboard ──────────────────────────────────────────────
@app.route("/admin")
@app.route("/admin/")
@login_required
def admin_dashboard():
    return render_template("admin/dashboard.html")


# ── Content API ──────────────────────────────────────────────────
@app.route("/api/content", methods=["GET"])
@login_required
def api_get_content():
    return jsonify(load_content())


VALID_SECTIONS = {
    "hero",
    "books",
    "theatre_plays",
    "theatre_credits",
    "cinema_featured",
    "cinema_credits",
    "press",
    "about",
    "contact",
    "rights_note",
}


@app.route("/api/content/<section>", methods=["PUT"])
@login_required
def api_update_section(section):
    if section not in VALID_SECTIONS:
        return jsonify({"error": "Section not found"}), 404
    data = request.get_json(force=True, silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400
    content = load_content()
    content[section] = data
    save_content(content)
    git_auto_push(section)
    return jsonify({"ok": True})


# ── Image API ────────────────────────────────────────────────────
@app.route("/api/images", methods=["GET"])
@login_required
def api_list_images():
    files = sorted(
        f for f in os.listdir(IMAGES_DIR) if allowed_file(f)
    )
    return jsonify(files)


@app.route("/api/upload", methods=["POST"])
@login_required
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename or not allowed_file(f.filename):
        return jsonify({"error": "Invalid or unsupported file type"}), 400
    filename = secure_filename(f.filename)
    f.save(os.path.join(IMAGES_DIR, filename))
    return jsonify({"filename": filename})


@app.route("/api/images/<filename>", methods=["DELETE"])
@login_required
def api_delete_image(filename):
    safe = secure_filename(filename)
    path = os.path.join(IMAGES_DIR, safe)
    if not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404
    os.remove(path)
    return jsonify({"ok": True})


# ── Settings API ─────────────────────────────────────────────────
@app.route("/api/git-status", methods=["GET"])
@login_required
def api_git_status():
    return jsonify(_push_status)


@app.route("/api/change-password", methods=["POST"])
@login_required
def api_change_password():
    if _load_admin_config().get("hosted"):
        return jsonify({
            "error": "Running in hosted mode. Update the ADMIN_PASSWORD_HASH "
                     "environment variable in your Railway dashboard instead."
        }), 400
    data = request.get_json(force=True, silent=True) or {}
    current = data.get("current", "")
    new_pw = data.get("new", "")
    cfg = load_admin_config()
    if not check_password_hash(cfg["password_hash"], current):
        return jsonify({"error": "Current password is incorrect"}), 403
    if len(new_pw) < 6:
        return jsonify({"error": "New password must be at least 6 characters"}), 400
    cfg["password_hash"] = generate_password_hash(new_pw)
    save_admin_config(cfg)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
