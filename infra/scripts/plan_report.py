"""Terraform plan report for the terraform/plan check and the deploy job. Standard library only.

    python infra/scripts/plan_report.py --plan-json plan.json --plan-text plan.txt --title "..." [--comment PR]

Counts the resource changes in `terraform show -json` output, writes the job summary and GITHUB_OUTPUT
(add, change, destroy, counts), and with --comment keeps one sticky comment on the pull request up to date (it
finds its own comment by the marker on the first line, written by the Actions bot or the org's App).
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MARKER = "<!-- checkable-terraform-plan v1 -->"
MAX_PLAN_CHARS = 50000


def counts(plan):
    """add, change, destroy as terraform plan prints them (a replace counts once in add and once in destroy)."""
    c = {"add": 0, "change": 0, "destroy": 0}
    for rc in (plan or {}).get("resource_changes") or []:
        actions = set((rc.get("change") or {}).get("actions") or [])
        if "create" in actions:
            c["add"] += 1
        if "delete" in actions:
            c["destroy"] += 1
        if actions == {"update"}:
            c["change"] += 1
    return c


def counts_line(c):
    return "%(add)d to add, %(change)d to change, %(destroy)d to destroy" % c


def body(title, plan_text, c=None, failed=False, run_url=None):
    text = plan_text or ""
    cut = len(text) > MAX_PLAN_CHARS
    if cut:
        text = text[:MAX_PLAN_CHARS]
    head = "**Plan failed.** The output is below." if failed else "**Plan:** %s." % counts_line(c)
    lines = [MARKER, "## %s" % title, "", head, ""]
    if run_url:
        lines += ["Run: %s" % run_url, ""]
    lines += ["<details%s><summary>terraform plan</summary>" % ("" if not failed else " open"), "", "```",
              text.replace("```", "'''").rstrip(), "```", ""]
    if cut:
        lines += ["The plan is longer than %d characters. The full plan is in the run log." % MAX_PLAN_CHARS, ""]
    lines += ["</details>", ""]
    return "\n".join(lines)


def bot_logins(env=None):
    """The Actions bot plus the org App's bot login from CHECKABLE_BOT_LOGINS, the same rule as gate.bot_logins.
    Kept here so this script runs on the runner's own Python with no packages installed."""
    env = os.environ if env is None else env
    extra = [s.strip() for s in (env.get("CHECKABLE_BOT_LOGINS") or "").split(",")]
    return {"github-actions[bot]"} | {s for s in extra if s.endswith("[bot]")}


def upsert_comment(api, number, text, logins):
    for c in api.list_comments(number):
        if (c.get("user") or {}).get("login") in logins and (c.get("body") or "").startswith(MARKER):
            api.update_comment(c["id"], text)
            return "updated"
    api.create_comment(number, text)
    return "created"


def _read(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    return ""


def _append(env_name, text):
    path = os.environ.get(env_name)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-json")
    ap.add_argument("--plan-text", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--comment", type=int, help="pull request number for the sticky comment")
    ap.add_argument("--failed", action="store_true")
    args = ap.parse_args(argv)

    failed = args.failed
    c = None
    if not failed:
        try:
            c = counts(json.loads(_read(args.plan_json)))
        except ValueError:
            failed = True
    run_url = None
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = "%s/%s/actions/runs/%s" % (os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
                                             os.environ.get("GITHUB_REPOSITORY", ""), os.environ["GITHUB_RUN_ID"])
    text = body(args.title, _read(args.plan_text), c, failed, run_url)
    _append("GITHUB_STEP_SUMMARY", text.split("\n", 1)[1] + "\n")
    if c:
        _append("GITHUB_OUTPUT", "add=%(add)d\nchange=%(change)d\ndestroy=%(destroy)d\n" % c
                + "counts=%s\n" % counts_line(c))
        print("Plan: " + counts_line(c))
    if args.comment:
        from scripts.checkable.github_api import GitHubAPI  # standard library only, like this script
        api = GitHubAPI(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
        print("Plan comment %s" % upsert_comment(api, args.comment, text, bot_logins()))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
