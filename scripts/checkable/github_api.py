"""Thin GitHub REST client on urllib."""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"


class GitHubError(Exception):
    def __init__(self, status, message):
        super().__init__("GitHub API %s: %s" % (status, message))
        self.status = status


class GitHubAPI:
    def __init__(self, repo, token, opener=None):
        self.repo = repo
        self.token = token
        self._open = opener or urllib.request.urlopen

    def request(self, method, path, body=None, params=None):
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Checkable AI CI demo (https://checkableai.com/)",
            "Content-Type": "application/json",
        })
        try:
            with self._open(req, timeout=30) as r:
                raw = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise GitHubError(e.code, e.read().decode("utf-8", "replace")[:300])
        return json.loads(raw) if raw else None

    def _paged(self, path, params=None, limit=3000):
        out, page = [], 1
        while len(out) < limit:
            p = dict(params or {})
            p.update({"per_page": 100, "page": page})
            batch = self.request("GET", path, params=p) or []
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return out

    # reads
    def get_pr(self, number):
        return self.request("GET", "/repos/%s/pulls/%d" % (self.repo, number))

    def list_pr_files(self, number):
        return self._paged("/repos/%s/pulls/%d/files" % (self.repo, number))

    def get_file(self, path, ref):
        """Decoded text of a file at a ref, or None for a 404."""
        try:
            r = self.request("GET", "/repos/%s/contents/%s" % (self.repo, urllib.parse.quote(path)),
                             params={"ref": ref})
        except GitHubError as e:
            if e.status == 404:
                return None
            raise
        if not isinstance(r, dict) or r.get("encoding") != "base64":
            raise GitHubError(0, "unexpected contents response for " + path)
        return base64.b64decode(r["content"]).decode("utf-8")

    def permission_role(self, login):
        """role_name of a user on this repo (admin, maintain, write, triage, read), or 'none'."""
        try:
            r = self.request("GET", "/repos/%s/collaborators/%s/permission" % (self.repo, urllib.parse.quote(login)))
        except GitHubError as e:
            if e.status in (403, 404):
                return "none"
            raise
        return (r or {}).get("role_name") or "none"

    def list_comments(self, number):
        return self._paged("/repos/%s/issues/%d/comments" % (self.repo, number))

    # writes
    def create_comment(self, number, body):
        return self.request("POST", "/repos/%s/issues/%d/comments" % (self.repo, number), {"body": body})

    def update_comment(self, comment_id, body):
        return self.request("PATCH", "/repos/%s/issues/comments/%d" % (self.repo, comment_id), {"body": body})

    def remove_label(self, number, label):
        try:
            self.request("DELETE", "/repos/%s/issues/%d/labels/%s" % (self.repo, number, urllib.parse.quote(label)))
        except GitHubError as e:
            if e.status != 404:
                raise

    def set_status(self, sha, state, description, context):
        return self.request("POST", "/repos/%s/statuses/%s" % (self.repo, sha),
                            {"state": state, "description": description[:140], "context": context})

    def ensure_labels(self, labels):
        """Create each (name, colour, description) label that is missing. Returns a list of problems, never raises."""
        problems = []
        for name, color, description in labels:
            try:
                self.request("GET", "/repos/%s/labels/%s" % (self.repo, urllib.parse.quote(name)))
                continue
            except GitHubError as e:
                if e.status != 404:
                    problems.append("could not read label %s: %s" % (name, e))
                    continue
            try:
                self.request("POST", "/repos/%s/labels" % self.repo,
                             {"name": name, "color": color, "description": description})
            except GitHubError as e:
                if e.status != 422:  # 422: created meanwhile by another run
                    problems.append("could not create label %s: %s" % (name, e))
        return problems
