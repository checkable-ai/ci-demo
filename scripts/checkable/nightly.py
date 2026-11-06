"""Nightly check (design section 5).

Reads the feed, finds changes that reach the register, and opens one pull request per change id.
A new version of a change updates the open PR or comments on the closed or merged one. It never
opens a second PR for the same change id.
"""
import json
import os
import re
import subprocess
import sys

import yaml

from . import gate, match
from .changectx import branch_for, change_context, pr_title
from .feed import FeedError, load_feed
from .register import RegisterError, parse_register
from .render import placeholder_names, plain_register, render

# The bot commits that add changes/<change_id>.md. Org-owned, never a person's address.
BOT_NAME = os.environ.get("CHECKABLE_BOT_NAME") or "Checkable AI"
BOT_EMAIL = os.environ.get("CHECKABLE_BOT_EMAIL") or "noreply@checkableai.com"
PR_LABEL = gate.PR_LABEL
RECORD_DIR = "changes"
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


# ---- records ----------------------------------------------------------------

def record_path(change_id):
    return "%s/%s.md" % (RECORD_DIR, change_id)


def record_text(change, ctx, feed, tool_ids, template):
    front = "\n".join([
        "---",
        "change_id: " + change["change_id"],
        "event_id: " + change["event_id"],
        "version: %d" % change["version"],
        "vendor_date: " + change["vendor_date"],
        "feed_version: " + feed.version,
        "tools: [%s]" % ", ".join(tool_ids),
        "status: awaiting sign-off",
        "---",
        "",
    ])
    return front + render(template, ctx)


def parse_record_version(text):
    """Front matter version of a record file, or None."""
    if not text:
        return None
    m = _FRONT.match(text.replace("\r\n", "\n"))
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    v = data.get("version") if isinstance(data, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) else None


# ---- decision (design table 5.2) -------------------------------------------------

def pick_pr(prs):
    """Open PR first, otherwise the most recent."""
    if not prs:
        return None
    opens = [p for p in prs if str(p.get("state", "")).upper() == "OPEN"]
    pool = opens or prs
    return max(pool, key=lambda p: p["number"])


def decide(version, prs, main_version, branch_version):
    """Returns ('open'|'nothing'|'update_open'|'comment'|'skip', pr or None, previous_version or None)."""
    pr = pick_pr(prs)
    if pr is None:
        if main_version is None:
            return "open", None, None
        if version > main_version:
            return "skip", None, main_version  # recorded on main, no PR to comment on
        return "nothing", None, main_version
    is_open = str(pr.get("state", "")).upper() == "OPEN"
    known = [v for v in (main_version, branch_version) if v is not None]
    if is_open:
        recorded = branch_version if branch_version is not None else main_version
        if recorded is None:
            return "nothing", pr, None
        return ("update_open" if version > recorded else "nothing"), pr, recorded
    if not known:
        return "nothing", pr, None
    recorded = max(known)
    return ("comment" if version > recorded else "nothing"), pr, recorded


# ---- real git and gh operations ----------------------------------------------

class GitOps:
    def __init__(self, repo, token, workdir="."):
        self.repo = repo
        self.token = token
        self.cwd = workdir
        self.env = dict(os.environ, GH_TOKEN=token, GH_REPO=repo)

    def _run(self, *cmd, check=True, input=None):
        r = subprocess.run(cmd, cwd=self.cwd, env=self.env, capture_output=True, text=True, input=input)
        if check and r.returncode != 0:
            raise RuntimeError("%s failed: %s" % (" ".join(cmd[:3]), r.stderr.strip()[:300]))
        return r.stdout

    def _git(self, *args, check=True):
        return self._run("git", "-c", "user.name=" + BOT_NAME, "-c", "user.email=" + BOT_EMAIL, *args, check=check)

    def auth_config(self):
        """git -c option that carries the token for one command (checkout keeps no credentials)."""
        import base64
        cred = base64.b64encode(("x-access-token:" + self.token).encode()).decode()
        return "http.https://github.com/.extraheader=AUTHORIZATION: basic " + cred

    def _authed(self, *args):
        return self._run("git", "-c", self.auth_config(), *args)

    def _push(self, branch):
        self._authed("push", "--force-with-lease", "origin", "HEAD:refs/heads/" + branch)

    def fetch(self):
        self._authed("fetch", "--prune", "origin")

    def find_prs(self, branch):
        out = self._run("gh", "pr", "list", "--state", "all", "--head", branch, "--json", "number,state,url")
        return json.loads(out or "[]")

    def read_record(self, where, change_id, branch=None):
        path = record_path(change_id)
        if where == "main":
            r = self._git("show", "origin/main:" + path, check=False)
            return r or None
        r = self._git("show", "origin/%s:%s" % (branch, path), check=False)
        return r or None

    def _write_commit_push(self, branch, base_ref, change_id, text):
        self._git("checkout", "-q", "-B", branch, base_ref)
        path = os.path.join(self.cwd, record_path(change_id))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        self._git("add", record_path(change_id))
        self._git("commit", "-q", "-m", "Record vendor change " + change_id)
        self._push(branch)

    def _back_to_main(self):
        self._git("checkout", "-q", "--detach", "origin/main")

    def open_pr(self, change_id, branch, text, title, body):
        self._write_commit_push(branch, "origin/main", change_id, text)
        r = self._run("gh", "pr", "create", "--base", "main", "--head", branch, "--title", title,
                      "--body-file", "-", "--label", PR_LABEL, input=body)
        self._back_to_main()
        m = re.search(r"/pull/(\d+)", r)
        if not m:
            raise RuntimeError("could not read the pull request number from: " + r.strip()[:200])
        return int(m.group(1)), r.strip()

    def update_pr(self, change_id, branch, number, text, body):
        self._write_commit_push(branch, "origin/" + branch, change_id, text)
        self._run("gh", "pr", "edit", str(number), "--body-file", "-", input=body)
        self._back_to_main()


# ---- run ----------------------------------------------------------------------

def _read(template_dir, name):
    with open(os.path.join(template_dir, name), encoding="utf-8") as f:
        return f.read()


def _subject(text):
    return " ".join(text.split())[:160]


def run(feed, register, ops, api, *, repo, template_dir="templates", dry_run=False, rows=None):
    """Returns (alerts, summary_lines). ops and api are real or fake.

    rows, when given, is a list that gets one dict per reaching change for the job summary table.
    """
    tools = register["tools"]
    tpl = {n: _read(template_dir, n + ".md") for n in
           ("pr-body", "change-record", "update-comment", "email-subject", "email-body")}
    alerts, lines, errors = [], [], []
    reaching = match.reaching_changes(feed.changes, tools)
    if not reaching:
        return alerts, ["No new changes reach this register."]

    for change, hits in reaching:
        cid = change["change_id"]
        branch = branch_for(cid)
        shown = [h for h in hits]
        tool_ids = [str(h["tool"].get("id") or h["tool"].get("name")) for h in shown]
        reach_names = [h["tool"].get("name") or h["tool"].get("id") for h in shown if h["status"] != "not_affected"]
        start = len(lines)
        try:
            _one(change, shown, cid, branch, tool_ids, reach_names, feed, ops, api, tpl, repo, template_dir,
                 dry_run, alerts, lines, register)
        except Exception as e:  # one bad change never stops the rest, or the email for PRs already opened
            errors.append(cid)
            lines.append("%s: failed, %s" % (cid, " ".join(str(e).split())[:300]))
        if rows is not None:
            rows.append({
                "change_id": cid,
                "version": change["version"],
                "vendor_date": change["vendor_date"],
                "tools": ", ".join("%s (%s)" % (n, match.STATUS_WORDS[h["status"]])
                                   for n, h in zip((h["tool"].get("name") or h["tool"].get("id") for h in shown), shown)),
                "result": " ".join(l.strip() for l in lines[start:]).replace(cid + " ", "", 1).replace(cid + ": ", "", 1),
            })
    if not alerts and not errors and not any(("opening" in l or "would" in l or "updating" in l) for l in lines):
        lines.insert(0, "No new changes reach this register.")
    return alerts, lines


def _record_on_pr(api, pr, cid):
    """The record file at a pull request's head ref. Works after its branch is deleted."""
    try:
        return api.get_file(record_path(cid), "refs/pull/%d/head" % pr["number"])
    except Exception:
        return None


def _one(change, shown, cid, branch, tool_ids, reach_names, feed, ops, api, tpl, repo, template_dir, dry_run,
         alerts, lines, register=None):
    prs = ops.find_prs(branch)
    pr = pick_pr(prs)
    main_v = parse_record_version(ops.read_record("main", cid))
    branch_v = parse_record_version(ops.read_record("branch", cid, branch)) if pr else None
    if pr and branch_v is None:
        branch_v = parse_record_version(_record_on_pr(api, pr, cid))
    action, pr, previous = decide(change["version"], prs, main_v, branch_v)
    ctx = change_context(change, shown, feed, repo=repo, register=register)

    if action == "open":
        lines.append("%s v%d: %s" % (cid, change["version"], "would open a pull request" if dry_run else "opening a pull request"))
        if dry_run:
            return
        body = render(tpl["pr-body"], ctx)
        text = record_text(change, ctx, feed, tool_ids, tpl["change-record"])
        number, url = ops.open_pr(cid, branch, text, pr_title(change, reach_names), body)
        alerts.append(_alert("new", cid, ctx, tpl, number, url, None))
        lines.append("  opened #%d %s" % (number, url))
        gate.run_pr(api, feed, repo=repo, pr_number=number, action="bot-opened", template_dir=template_dir)
    elif action == "update_open":
        lines.append("%s: version %d is newer than %d, %s PR #%d" % (
            cid, change["version"], previous, "would update" if dry_run else "updating", pr["number"]))
        if dry_run:
            return
        uctx = dict(ctx, is_update=True, previous_version=previous, pr_number=pr["number"], pr_url=pr["url"])
        text = record_text(change, uctx, feed, tool_ids, tpl["change-record"])
        ops.update_pr(cid, branch, pr["number"], text, render(tpl["pr-body"], uctx))
        alerts.append(_alert("update", cid, ctx, tpl, pr["number"], pr["url"], previous))
        _post_update_comment(api, pr, change, uctx, tpl)
        gate.run_pr(api, feed, repo=repo, pr_number=pr["number"], action="bot-updated", template_dir=template_dir)
    elif action == "comment":
        uctx = dict(ctx, is_update=True, previous_version=previous, pr_number=pr["number"], pr_url=pr["url"])
        lines.append("%s: version %d is newer than %d, %s on PR #%d" % (
            cid, change["version"], previous, "would comment" if dry_run else "commenting", pr["number"]))
        if dry_run:
            return
        if _post_update_comment(api, pr, change, uctx, tpl):
            alerts.append(_alert("update", cid, ctx, tpl, pr["number"], pr["url"], previous))
    elif action == "skip":
        lines.append("%s: version %d is newer than the record on main but no PR exists to comment on" % (
            cid, change["version"]))
    else:
        lines.append("%s v%d: already recorded" % (cid, change["version"]))


def _marker(change):
    return "<!-- checkable-update %s v%d -->" % (change["change_id"], change["version"])


def _post_update_comment(api, pr, change, uctx, tpl):
    """Post once per change version. Returns True when a comment was posted."""
    mk = _marker(change)
    for c in api.list_comments(pr["number"]):
        if (c.get("body") or "").startswith(mk):
            return False
    api.create_comment(pr["number"], mk + "\n" + render(tpl["update-comment"], uctx))
    return True


def _alert(kind, cid, ctx, tpl, number, url, previous):
    ectx = dict(ctx, pr_number=number, pr_url=url, previous_version=previous or "", is_update=(kind == "update"))
    return {"kind": kind, "change_id": cid, "context": ectx}


def _write_output(name, value):
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s=%s\n" % (name, value))


def pr_token(env):
    """(token for git push and gh pr, source word). The org App token when the workflow minted one.

    A pull request opened with GITHUB_TOKEN starts no other workflow, so the tests check never reports on it.
    The App token opens pull requests like a person would, and their workflows run normally.
    """
    app = (env.get("CHECKABLE_PR_TOKEN") or "").strip()
    if app:
        return app, "app"
    return env["GITHUB_TOKEN"], "github"


TOKEN_NOTES = {
    "app": "Pull requests opened with the Checkable AI GitHub App token, so their workflows run.",
    "github": ("Pull requests opened with GITHUB_TOKEN, because CHECKABLE_APP_ID and CHECKABLE_APP_PRIVATE_KEY "
               "are not set. Their workflows do not start, so the tests check never reports on them."),
}


def summary_markdown(title, feed, lines, rows, token_source):
    out = ["## " + title, "", "Feed: %s, version %s." % (feed.source_label, feed.version), "",
           TOKEN_NOTES.get(token_source, ""), ""]
    if rows:
        out += ["| Change | Version | Vendor date | Tools in the register | Result |", "|---|---|---|---|---|"]
        for r in rows:
            out.append("| `%s` | %d | %s | %s | %s |" % (
                r["change_id"], r["version"], r["vendor_date"],
                plain_register(r["tools"]).replace("|", "/"), plain_register(r["result"]).replace("|", "/")))
        out.append("")
    out += ["- " + l for l in lines]
    return "\n".join(out) + "\n"


def main(argv=None):
    from .github_api import GitHubAPI
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    push_token, token_source = pr_token(os.environ)
    dry = os.environ.get("DRY_RUN", "").lower() == "true"
    template_dir = os.environ.get("TEMPLATE_DIR", "templates")
    try:
        feed = load_feed(os.environ.get("FEED_URL"))
    except FeedError as e:
        print("::error::" + str(e))
        return 2
    try:
        with open("ai-vendor-register.yaml", encoding="utf-8") as f:
            register = parse_register(f.read())
    except RegisterError as e:
        print("::error::ai-vendor-register.yaml on main does not parse: " + str(e))
        return 2
    # git push and gh pr use the App token when there is one. Comments, labels and the checkable/sign-off status
    # use GITHUB_TOKEN, the same token the gate and sign-off workflows use, so they come from one author.
    ops = GitOps(repo, push_token)
    ops.fetch()
    api = GitHubAPI(repo, token)
    if not dry:
        for problem in api.ensure_labels(gate.LABELS):
            print("::warning::" + problem)
        if token_source == "github":
            print("::warning::" + TOKEN_NOTES["github"])
    rows = []
    alerts, lines = run(feed, register, ops, api, repo=repo, template_dir=template_dir, dry_run=dry, rows=rows)
    failed = [l for l in lines if ": failed, " in l]
    title = "Checkable nightly check (dry run)" if dry else "Checkable nightly check"
    summary = summary_markdown(title, feed, lines, rows, token_source)
    print(summary)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as f:
            f.write(summary)
    with open("alerts.json", "w", encoding="utf-8") as f:
        json.dump(alerts, f, indent=2)
    _write_output("has_alerts", "true" if alerts else "false")
    for l in failed:
        print("::error::" + l)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
