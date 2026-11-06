"""Deploy gate: no Checkable sign-off, no deploy.

Runs in deploy.yml (job `checkable/deploy-gate`) before the production deploy, for the commit on main being
deployed. It finds the merged pull request that made that commit and reads what the Checkable gate recorded on the
pull request's head commit, with the same constants and helpers the gate uses (gate.py):

1. Exactly one merged pull request into main whose merge commit is this commit. A direct push has none.
2. The newest `checkable/sign-off` status on its head commit is `success`, posted by the Actions bot or the org's
   App (CHECKABLE_BOT_LOGINS). A status from anyone else, or a newer status in any other state, stops the deploy.
3. A "Signed off by" status also needs the gate's sticky comment, from the same bots, to record a sign-off of that
   exact head commit. "No AI tools changed" needs no sign-off, as in the gate, which gives that status only
   when a pull request leaves service/ and infra/ (everything this workflow deploys) alone.

Anything else, an API error included, fails closed.
"""
import json
import os
import sys

from .gate import DESC_NOTHING, DESC_SIGNED, STATUS_CONTEXT, bot_logins, find_sticky, parse_marker

SIGNED_PREFIX = DESC_SIGNED.split("%s")[0]
BASE_BRANCH = "main"


class Blocked(Exception):
    pass


def merged_pr_for_commit(api, sha, base=BASE_BRANCH):
    pulls = api.request("GET", "/repos/%s/commits/%s/pulls" % (api.repo, sha), params={"per_page": 100}) or []
    hits = [p for p in pulls
            if p.get("merged_at") and p.get("merge_commit_sha") == sha
            and ((p.get("base") or {}).get("ref") == base)]
    if not hits:
        raise Blocked("commit %s is not the merge commit of a pull request into %s" % (sha[:7], base))
    if len(hits) > 1:
        raise Blocked("commit %s matches %d merged pull requests" % (sha[:7], len(hits)))
    return hits[0]


def latest_signoff_status(api, head_sha):
    """The newest checkable/sign-off status on a commit, or None. The API lists newest first."""
    statuses = api.request("GET", "/repos/%s/commits/%s/statuses" % (api.repo, head_sha),
                           params={"per_page": 100}) or []
    for s in statuses:
        if s.get("context") == STATUS_CONTEXT:
            return s
    return None


def check(api, sha, logins=None):
    """Returns a dict describing the sign-off, or raises Blocked."""
    logins = logins or bot_logins()
    pr = merged_pr_for_commit(api, sha)
    number = pr["number"]
    head = (pr.get("head") or {}).get("sha") or ""
    if not head:
        raise Blocked("pull request #%s has no head commit" % number)

    status = latest_signoff_status(api, head)
    if status is None:
        raise Blocked("pull request #%s has no %s status on %s" % (number, STATUS_CONTEXT, head[:7]))
    creator = (status.get("creator") or {}).get("login")
    if creator not in logins:
        raise Blocked("the newest %s status on #%s was posted by %s, not the Checkable gate"
                      % (STATUS_CONTEXT, number, creator or "nobody"))
    state, desc = status.get("state"), status.get("description") or ""
    if state != "success":
        raise Blocked("pull request #%s was merged with %s %s: %s" % (number, STATUS_CONTEXT, state, desc))

    result = {"pr_number": number, "head_sha": head, "merge_sha": sha, "description": desc,
              "pr_title": pr.get("title") or "", "signed_by": "", "signed_at": ""}
    if desc == DESC_NOTHING:
        result["mode"] = "no-ai-change"
        return result
    if not desc.startswith(SIGNED_PREFIX):
        raise Blocked("pull request #%s has an unknown %s description: %s" % (number, STATUS_CONTEXT, desc))

    sticky = find_sticky(api.list_comments(number), logins)
    if sticky is None:
        raise Blocked("pull request #%s says signed off but has no Checkable gate comment" % number)
    _, record = parse_marker(sticky.get("body"))
    if not record or record["sha"] != head:
        raise Blocked("the Checkable gate comment on #%s records no sign-off of %s" % (number, head[:7]))
    result.update(mode="signed", signed_by=record["by"], signed_at=record["at"])
    return result


def summary_markdown(sha, result=None, error=None):
    lines = ["## Checkable deploy gate", ""]
    if error:
        lines += ["**Blocked**: %s." % error, "",
                  "No sign-off, no deploy. Merge through a pull request that the Checkable gate passed."]
        return "\n".join(lines) + "\n"
    who = ("Signed off by %s on %s" % (result["signed_by"], result["signed_at"][:10])
           if result["mode"] == "signed" else DESC_NOTHING + ", no sign-off needed")
    lines += [
        "| | |", "| --- | --- |",
        "| Commit | `%s` |" % sha[:7],
        "| Pull request | #%s %s |" % (result["pr_number"], result["pr_title"].replace("|", "\\|")),
        "| Head commit | `%s` |" % result["head_sha"][:7],
        "| `%s` | %s |" % (STATUS_CONTEXT, who),
        "", "**Passed.** The deploy job may run.",
    ]
    return "\n".join(lines) + "\n"


def _append(env_name, text):
    path = os.environ.get(env_name)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def main(argv=None):
    from .github_api import GitHubAPI, GitHubError
    sha = os.environ.get("DEPLOY_SHA") or os.environ["GITHUB_SHA"]
    api = GitHubAPI(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    try:
        result = check(api, sha)
    except (Blocked, GitHubError) as e:
        print("::error::Deploy blocked: %s" % e)
        _append("GITHUB_STEP_SUMMARY", summary_markdown(sha, error=str(e)))
        return 1
    print("Deploy gate passed: %s" % json.dumps(result))
    _append("GITHUB_STEP_SUMMARY", summary_markdown(sha, result))
    _append("GITHUB_OUTPUT", "".join("%s=%s\n" % (k, str(result[k]).replace("\n", " "))
                                     for k in ("pr_number", "head_sha", "mode", "signed_by", "signed_at")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
