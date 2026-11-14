"""
Publishes saved changes to GitHub so Vercel redeploys the public site.

Everything that changed (content.json, the rebuilt index.html, uploaded or
deleted images) goes into ONE commit through the Git Data API, so each save
triggers a single deploy and never leaves the repo half-updated.

Pushes run on one background thread, in order.  If a push fails, its files
stay queued and go out with the next save (or "Retry" in the admin).
"""
import base64
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request


class PublishError(Exception):
    pass


class Publisher:
    def __init__(self, base_dir, repo, token, branch="main", api_url="https://api.github.com"):
        self.base_dir = base_dir
        self.repo = repo
        self.token = token
        self.branch = branch
        self.api_url = api_url.rstrip("/")
        self._lock = threading.Lock()
        self._pending = {}          # repo-relative path -> True
        self._messages = []
        self._running = False
        self._status = {"status": "idle", "message": ""}

    # ── Public API ──────────────────────────────────────────────
    @property
    def enabled(self):
        return bool(self.token and self.repo)

    def status(self):
        with self._lock:
            return dict(self._status, pending=len(self._pending), enabled=self.enabled)

    def enqueue(self, paths, message):
        """Queue repo-relative paths (added, changed or deleted) for publishing."""
        with self._lock:
            for path in paths:
                self._pending[path.replace(os.sep, "/")] = True
            if message and message not in self._messages:
                self._messages.append(message)
            if not self.enabled:
                self._status = {
                    "status": "local",
                    "message": "Saved on this server only — GITHUB_TOKEN is not set, so nothing was published.",
                }
                return
            self._status = {"status": "pushing", "message": "Publishing…"}
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._worker, daemon=True).start()

    def retry(self):
        with self._lock:
            has_work = bool(self._pending)
        if has_work:
            self.enqueue([], "")
        return has_work

    # ── Worker ──────────────────────────────────────────────────
    def _worker(self):
        while True:
            with self._lock:
                if not self._pending:
                    self._running = False
                    return
                paths, self._pending = sorted(self._pending), {}
                messages, self._messages = self._messages, []
                self._status = {"status": "pushing", "message": "Publishing…"}
            message = "admin: " + ("; ".join(messages) or "update site")
            try:
                changed = self._commit(paths, message)
            except Exception as exc:  # noqa: BLE001 — surface any failure to the admin
                print(f"[publish error] {exc}")
                with self._lock:
                    for path in paths:  # keep them queued for the next attempt
                        self._pending.setdefault(path, True)
                    self._messages = messages + self._messages
                    self._status = {"status": "error", "message": str(exc)}
                    self._running = False
                return
            with self._lock:
                if not self._pending:
                    self._status = {
                        "status": "ok",
                        "message": "Published — the live site updates in about a minute."
                        if changed else "Already up to date.",
                    }

    # ── GitHub ──────────────────────────────────────────────────
    def _api(self, method, path, body=None, ok_missing=False):
        url = f"{self.api_url}/repos/{self.repo}/{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "portfolio-admin",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            if ok_missing and exc.code == 404:
                return None
            detail = ""
            try:
                detail = json.loads(exc.read()).get("message", "")
            except Exception:  # noqa: BLE001
                pass
            if exc.code in (401, 403):
                hint = "GitHub rejected the token — check GITHUB_TOKEN has write access to the repository."
                raise PublishError(f"{hint} ({exc.code} {detail})") from exc
            raise PublishError(f"GitHub error {exc.code} on {method} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise PublishError(f"Could not reach GitHub: {exc.reason}") from exc

    def _commit(self, paths, message, attempt=1):
        """Create one commit containing the current state of `paths`.
        Returns False when the repo already matched."""
        head = self._api("GET", f"git/ref/heads/{self.branch}")["object"]["sha"]
        base_tree = self._api("GET", f"git/commits/{head}")["tree"]["sha"]

        entries = []
        for path in paths:
            full = os.path.join(self.base_dir, *path.split("/"))
            if os.path.isfile(full):
                with open(full, "rb") as f:
                    blob = self._api("POST", "git/blobs", {
                        "content": base64.b64encode(f.read()).decode(),
                        "encoding": "base64",
                    })
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
            else:
                # Deleted locally: remove from the repo only if it is there.
                quoted = urllib.parse.quote(path)
                exists = self._api("GET", f"contents/{quoted}?ref={self.branch}", ok_missing=True)
                if exists is not None:
                    entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
        if not entries:
            return False

        tree = self._api("POST", "git/trees", {"base_tree": base_tree, "tree": entries})
        if tree["sha"] == base_tree:
            return False
        commit = self._api("POST", "git/commits", {
            "message": message, "tree": tree["sha"], "parents": [head],
        })
        try:
            self._api("PATCH", f"git/refs/heads/{self.branch}", {"sha": commit["sha"]})
        except PublishError:
            if attempt >= 3:
                raise
            # The branch moved while we were working — rebuild on the new head.
            return self._commit(paths, message, attempt + 1)
        return True
