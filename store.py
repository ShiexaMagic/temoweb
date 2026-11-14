"""
Where the site's files live.

On Vercel nothing written to disk survives, so the GitHub repository itself
is the storage: the editor reads content.json and the image list from GitHub
and saves by committing to it.  Each commit makes Vercel redeploy the public
site.  Without a GITHUB_TOKEN (local development) plain files are used.

Both stores share one small interface:
    read(path) -> bytes | None
    list_dir(path) -> [{"name": str, "size": int}]
    put_blob(data) -> sha            (stage an upload; not visible until committed)
    commit(changes, message) -> bool (changes: path -> bytes | {"blob": sha} | None=delete)
"""
import base64
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request


class StoreError(Exception):
    pass


class GitHubStore:
    publishes = True

    def __init__(self, repo, token, branch="main", api_url="https://api.github.com"):
        self.repo, self.token, self.branch = repo, token, branch
        self.api_url = api_url.rstrip("/")

    def _api(self, method, path, body=None, raw=False, ok_missing=False):
        url = f"{self.api_url}/repos/{self.repo}/{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "portfolio-admin",
        })
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                payload = resp.read()
                return payload if raw else json.loads(payload or b"null")
        except urllib.error.HTTPError as exc:
            if ok_missing and exc.code == 404:
                return None
            detail = ""
            try:
                detail = json.loads(exc.read()).get("message", "")
            except Exception:  # noqa: BLE001
                pass
            if exc.code in (401, 403, 404):
                raise StoreError(
                    "GitHub refused the request. Check that GITHUB_TOKEN is valid and has "
                    f"read and write access to {self.repo}. ({exc.code} {detail})"
                ) from exc
            raise StoreError(f"GitHub error {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise StoreError("Could not reach GitHub. Please try again in a moment.") from exc

    def _contents(self, path):
        return f"contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(self.branch)}"

    def read(self, path):
        return self._api("GET", self._contents(path), raw=True, ok_missing=True)

    def list_dir(self, path):
        entries = self._api("GET", self._contents(path), ok_missing=True) or []
        return [{"name": e["name"], "size": e["size"]} for e in entries if e.get("type") == "file"]

    def put_blob(self, data):
        blob = self._api("POST", "git/blobs", {
            "content": base64.b64encode(data).decode(), "encoding": "base64",
        })
        return blob["sha"]

    def commit(self, changes, message, attempt=1):
        """One commit with all `changes`.  Returns False if nothing changed."""
        head = self._api("GET", f"git/ref/heads/{urllib.parse.quote(self.branch)}")["object"]["sha"]
        base_tree = self._api("GET", f"git/commits/{head}")["tree"]["sha"]

        entries = []
        for path, value in sorted(changes.items()):
            if value is None:
                # Delete — but only if the file is really there, or GitHub errors.
                if self._api("GET", self._contents(path), ok_missing=True) is None:
                    continue
                sha = None
            elif isinstance(value, dict):
                sha = value["blob"]
            else:
                sha = self.put_blob(value)
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": sha})
        if not entries:
            return False

        tree = self._api("POST", "git/trees", {"base_tree": base_tree, "tree": entries})
        if tree["sha"] == base_tree:
            return False
        commit = self._api("POST", "git/commits", {
            "message": message, "tree": tree["sha"], "parents": [head],
        })
        try:
            self._api("PATCH", f"git/refs/heads/{urllib.parse.quote(self.branch)}", {"sha": commit["sha"]})
        except StoreError:
            if attempt >= 3:
                raise
            # The branch moved while we were working — redo on the new head.
            return self.commit(changes, message, attempt + 1)
        return True


class LocalStore:
    """Plain files in the project folder.  Nothing is published."""
    publishes = False

    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.blob_dir = os.path.join(tempfile.gettempdir(), "portfolio-admin-blobs")

    def _full(self, path):
        return os.path.join(self.base_dir, *path.split("/"))

    def read(self, path):
        try:
            with open(self._full(path), "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def list_dir(self, path):
        full = self._full(path)
        if not os.path.isdir(full):
            return []
        return [
            {"name": name, "size": os.path.getsize(os.path.join(full, name))}
            for name in os.listdir(full) if os.path.isfile(os.path.join(full, name))
        ]

    def put_blob(self, data):
        sha = hashlib.sha1(data).hexdigest()
        os.makedirs(self.blob_dir, exist_ok=True)
        with open(os.path.join(self.blob_dir, sha), "wb") as f:
            f.write(data)
        return sha

    def commit(self, changes, message):
        for path, value in changes.items():
            full = self._full(path)
            if value is None:
                if os.path.isfile(full):
                    os.remove(full)
                continue
            if isinstance(value, dict):
                try:
                    with open(os.path.join(self.blob_dir, value["blob"]), "rb") as f:
                        value = f.read()
                except FileNotFoundError as exc:
                    raise StoreError("An uploaded file expired. Please upload it again.") from exc
            os.makedirs(os.path.dirname(full), exist_ok=True)
            tmp = full + ".tmp"
            with open(tmp, "wb") as f:
                f.write(value)
            os.replace(tmp, full)
        return True


def make_store(base_dir):
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return GitHubStore(
            os.environ.get("GITHUB_REPO", "ShiexaMagic/temoweb"),
            token,
            os.environ.get("GITHUB_BRANCH", "main"),
            os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        )
    return LocalStore(base_dir)
