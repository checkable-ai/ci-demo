"""PR gate (design section 6).

Runs from the base commit. The head register, every changed service/**/model.yaml and every changed k8s/**
manifest are read through the API, so no pull request code runs. Sign-off is the label `checkable-signed-off`,
applied by a person with write, maintain or admin permission, recorded against the head SHA in the one sticky
comment's marker.
"""
import datetime
import json
import os
import re
import sys

from . import match, services
from .changectx import DEFAULT_REPO, organisation_context
from .feed import FeedError, load_feed
from .register import RegisterError, diff_registers, parse_register, tool_key
from .render import clean_feed, code_register, plain_register, placeholder_names, render

REGISTER_PATH = "ai-vendor-register.yaml"
LABEL = "checkable-signed-off"
PR_LABEL = "ai-governance"
# Created when missing, by the nightly check and the gate, so a new repository needs no manual label setup.
LABELS = (
    (PR_LABEL, "0e8a16", "A vendor change from the Checkable feed"),
    (LABEL, "1d76db", "A person read the Checkable gate comment and signed this off"),
)
STATUS_CONTEXT = "checkable/sign-off"
MARKER_PREFIX = "<!-- checkable-gate v1"
BOT_LOGIN = "github-actions[bot]"
# The sticky comment may also come from the org's GitHub App ("Checkable AI"). Its bot login, for example
# checkable-ai[bot], is passed in CHECKABLE_BOT_LOGINS (comma separated) by the workflows.
BOT_LOGINS_ENV = "CHECKABLE_BOT_LOGINS"
SIGNER_ROLES = {"admin", "maintain", "write"}
# Files the gate runs from or checks against. A change to any of them needs the same sign-off.
GATE_PATH_PREFIXES = ("feed-snapshot/", "scripts/", "templates/", "tests/", ".github/")
GATE_FILES_HEADLINE = "Gate files changed. A person signs this off."
# Files that reach production through deploy.yml. A pull request that changes only these, and no AI tool or model
# config, still needs a person to sign it off, because the deploy job runs only after a sign-off. k8s/ is checked on
# a throwaway kind cluster and never deployed, so it is not on this list.
DEPLOY_PATH_PREFIXES = ("infra/", "service/")
DEPLOY_FILES_HEADLINE = "Service or infrastructure files changed. A person signs this off before they deploy."
_MARKER_RE = re.compile(
    r"^<!-- checkable-gate v1(?: signed:([0-9a-f]{7,40}) by:(\S+) at:(\S+))? -->")

DESC_SIGNED = "Signed off by %s"
DESC_WAITING = "Waiting for a person to sign off"
DESC_NOTHING = "No AI tools changed"
DESC_REGISTER = "The register does not parse"
DESC_FEED = "The Checkable feed could not be read"
DESC_GATE_FILES = GATE_FILES_HEADLINE
DESC_FORK = "A maintainer must bring this change onto a branch in this repo"
DESC_UNREGISTERED = "A service uses an AI plan the register does not list"
DESC_SERVICE_CONFIG = "A service AI config does not parse"


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_marker(record=None):
    if record:
        return "%s signed:%s by:%s at:%s -->" % (MARKER_PREFIX, record["sha"], record["by"], record["at"])
    return MARKER_PREFIX + " -->"


def parse_marker(body):
    """Return (is_marker, record or None) for the first line of a comment body."""
    first = (body or "").split("\n", 1)[0].strip()
    m = _MARKER_RE.match(first)
    if not m:
        return False, None
    if m.group(1):
        return True, {"sha": m.group(1), "by": m.group(2), "at": m.group(3)}
    return True, None


def bot_logins(env=None):
    env = os.environ if env is None else env
    extra = [s.strip() for s in (env.get(BOT_LOGINS_ENV) or "").split(",")]
    return {BOT_LOGIN} | {s for s in extra if s.endswith("[bot]")}


def find_sticky(comments, logins=None):
    """The one gate comment: starts with the marker prefix and is written by the Actions bot or the org's App."""
    logins = logins or bot_logins()
    for c in comments:
        user = c.get("user") or {}
        if user.get("login") in logins and (c.get("body") or "").startswith(MARKER_PREFIX):
            return c
    return None


class GateResult:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __repr__(self):
        return "GateResult(%r)" % self.__dict__


def _tool_ctx(tool, kind, feed, plans_by_id):
    plan_id = tool.get("plan")
    plan = plans_by_id.get(plan_id) if plan_id else None
    opens = []
    for c, h in match.changes_for_tool(feed.changes, tool):
        opens.append({
            "change_id": c["change_id"],
            "title": clean_feed(c["title"]),
            "status_word": match.STATUS_WORDS[h["status"]],
            "action": clean_feed(c["action"]),
            "source_url": c["evidence"][0]["url"],
            "version": c["version"],
        })
    ended = [{
        "change_id": c["change_id"],
        "title": clean_feed(c["title"]),
        "source_url": c["evidence"][0]["url"],
        "version": c["version"],
    } for c, _ in match.ended_changes_for_tool(feed.changes, tool)]
    rules = (plan or {}).get("rules") or {}
    return {
        "tool_name": code_register(tool.get("name") or tool.get("id")),
        "change_kind": kind,
        "plan_id": plain_register(plan_id) if plan_id else "",
        "plan_name": clean_feed(plan["name"]) if plan else "",
        "vendor_name": code_register(tool.get("vendor")) if tool.get("vendor") else "",
        "in_catalogue": plan is not None,
        "terms": clean_feed((plan or {}).get("terms") or []),
        "rules_au": clean_feed(rules.get("au") or []),
        "rules_eu": clean_feed(rules.get("eu") or []),
        "rules_us": clean_feed(rules.get("us") or []),
        "has_open_changes": bool(opens),
        "open_changes": opens,
        "has_ended_changes": bool(ended),
        "ended_changes": ended,
        "is_service": False,
    }


def _describe_usage(u):
    """One line for a usage, every value as inline code."""
    if not u:
        return ""
    parts = []
    for field in ("vendor", "plan", "model"):
        if u.get(field):
            parts.append("%s %s" % (field, code_register(u[field])))
    return ", ".join(parts)


def _read_pair(api, f, base_sha, head_sha, pr_number, is_fork):
    """(base_path, base_text, head_path, head_text) for one changed file, None where it does not exist."""
    status = f.get("status")
    head_path = f.get("filename")
    base_path = f.get("previous_filename") or head_path
    base_text = None if status == "added" else api.get_file(base_path, base_sha)
    head_text = None
    if status != "removed":
        head_text = api.get_file(head_path, head_sha)
        if head_text is None and is_fork:
            head_text = api.get_file(head_path, "refs/pull/%d/head" % pr_number)
    return base_path, base_text, head_path, head_text


def _row(kind, item, plan, register, open_changes):
    return {"kind": kind, "item": item, "plan": plan, "register": register, "open_changes": open_changes}


def service_changes(api, files, *, base_sha, head_sha, pr_number, is_fork, feed, plans_by_id, register_tools):
    """Tool contexts for AI use declared in service/**/model.yaml and k8s/** that this pull request changes.

    Returns (service_tools, removed_services, unregistered, errors, rows).
    """
    base_u, head_u, errors = {}, {}, []
    for f in files:
        names = (f.get("filename"), f.get("previous_filename"))
        if not any(services.is_service_path(n) for n in names):
            continue
        base_path, base_text, head_path, head_text = _read_pair(api, f, base_sha, head_sha, pr_number, is_fork)
        for path, text, into in ((base_path, base_text, base_u), (head_path, head_text, head_u)):
            try:
                into.update(services.usages_for(path, text))
            except services.ServiceConfigError as e:
                if into is head_u:  # a broken base is main's problem, a broken head blocks this pull request
                    errors.append({"path": plain_register(path), "error": plain_register(str(e))})
    added, changed, removed = services.diff_usages(base_u, head_u)
    out, unregistered, rows = [], [], []
    for kind, items in (("added", added), ("changed", changed)):
        for key, before, after in items:
            tool, note = services.match_register(after, register_tools)
            pseudo = {"name": key, "vendor": after.get("vendor"), "product": after.get("product"),
                      "plan": after.get("plan")}
            ctx = _tool_ctx(pseudo, kind, feed, plans_by_id)
            label = "%s (%s)" % (tool.get("name") or tool.get("id"), tool.get("id")) if tool else ""
            ctx.update({
                "is_service": True,
                "source_path": plain_register(key),
                "has_before": bool(before),
                "before": _describe_usage(before),
                "after": _describe_usage(after),
                "in_register": tool is not None,
                "register_tool": code_register(label) if tool else "",
                "register_note": note,
                "after_plan": code_register(after.get("plan") or after.get("vendor")),
            })
            out.append(ctx)
            if tool is None:
                unregistered.append({"source_path": plain_register(key), "after_plan": ctx["after_plan"]})
            rows.append(_row(kind, plain_register(key), plain_register(after.get("plan") or after.get("vendor")),
                             plain_register(tool.get("id")) if tool else "not in the register",
                             len(ctx["open_changes"])))
    removed_services = [{"source_path": plain_register(k), "before": _describe_usage(b)} for k, b, _ in removed]
    for k, b, _ in removed:
        rows.append(_row("removed", plain_register(k), plain_register(b.get("plan") or b.get("vendor")), "", 0))
    return out, removed_services, unregistered, errors, rows


def _evaluate_signoff(*, action, label_present, record, head_sha, sender_login, sender_type, event_label,
                      api, pr_number, is_fork, event_head_sha=None, can_sign=True):
    """Returns (record_to_store, signed, cleared, denied_login, stale).

    event_head_sha is the head commit in the labeled event. When the branch has moved on since the label went on,
    the label is taken off and nothing is recorded, so a sign-off never lands on a commit the person did not see.
    can_sign is False when the head register does not parse, so a broken register can never go green.
    """
    cleared = False
    denied = None
    stale = False
    removing = False
    if action in ("synchronize", "bot-updated"):
        cleared = bool(label_present or record)
        record = None
        removing = label_present
    elif action == "unlabeled" and event_label == LABEL:
        record = None
    elif action == "labeled" and event_label == LABEL and label_present:
        role = api.permission_role(sender_login) if sender_login else "none"
        if event_head_sha and event_head_sha != head_sha:
            record = None
            stale = True
            removing = True
        elif (not is_fork) and sender_type == "User" and role in SIGNER_ROLES and can_sign:
            record = {"sha": head_sha, "by": sender_login, "at": now_utc()}
        else:
            record = None
            denied = sender_login or "unknown"
            removing = True
    if removing and not is_fork:
        try:
            api.remove_label(pr_number, LABEL)
        except Exception:  # the token may not allow it, the record is cleared anyway
            pass
        label_present = False
    if removing:
        label_present = False
    signed = bool(not is_fork and can_sign and label_present and record and record["sha"] == head_sha)
    return record, signed, cleared, denied, stale


def is_gate_path(name):
    return isinstance(name, str) and name.startswith(GATE_PATH_PREFIXES)


def gate_files_changed(files):
    """Every gate path a pull request adds, edits, renames or removes, sorted, renames counted on both sides."""
    out = set()
    for f in files:
        for name in (f.get("filename"), f.get("previous_filename")):
            if is_gate_path(name):
                out.add(name)
    return sorted(out)


def deploy_files_changed(files):
    """Every service or infra path a pull request adds, edits, renames or removes, sorted."""
    out = set()
    for f in files:
        for name in (f.get("filename"), f.get("previous_filename")):
            if isinstance(name, str) and name.startswith(DEPLOY_PATH_PREFIXES):
                out.add(name)
    return sorted(out)


def _fallback_lines(body, template_names, ctx):
    """Add one fixed line only when the template has no place for a case it must be able to show."""
    extra = []
    if ctx.get("has_gate_files") and "has_gate_files" not in template_names:
        extra.append(GATE_FILES_HEADLINE + " Changed: "
                     + ", ".join("`%s`" % g["path"] for g in ctx["gate_files"]) + ".")
    if ctx.get("has_deploy_only") and "has_deploy_only" not in template_names:
        extra.append(DEPLOY_FILES_HEADLINE + " Changed: "
                     + ", ".join("`%s`" % g["path"] for g in ctx["deploy_files"]) + ".")
    if ctx.get("register_error") and "register_error" not in template_names:
        extra.append("Register problem: " + code_register(ctx["register_error"])
                     + ". Fix the register first. The label cannot turn this check green while it does not parse.")
    if ctx.get("has_unregistered") and "has_unregistered" not in template_names:
        extra.append("Not in the register: " + ", ".join(u["after_plan"] for u in ctx["unregistered"])
                     + ". Add it to `ai-vendor-register.yaml` in this pull request. The label cannot turn this check "
                     "green until the register lists it.")
    if ctx.get("has_service_errors") and "has_service_errors" not in template_names:
        extra.append("Service AI config problem: " + ", ".join(
            "%s (%s)" % (e["path"], e["error"]) for e in ctx["service_errors"])
            + ". Fix it first. The label cannot turn this check green while it does not parse.")
    if ctx.get("sign_off_stale") and "sign_off_stale" not in template_names:
        extra.append("The label was removed. New commits arrived after it was added, so a person reads this comment "
                     "against commit `%s` and adds the label again." % ctx["head_sha_short"])
    if ctx.get("sign_off_denied") and not ctx.get("register_error") and "sign_off_denied" not in template_names:
        extra.append("The label was removed. Only someone with write, maintain or admin access to %s can sign off."
                     % ctx["repo"])
    if extra:
        body = body.rstrip("\n") + "\n\n" + "\n".join(extra) + "\n"
    return body


def _operates_in(reg):
    """Register text, so plain text, and never a crash on an odd shape."""
    v = (reg or {}).get("operates_in")
    if v is None:
        return ""
    if not isinstance(v, list):
        v = [v]
    return ", ".join(plain_register(x) for x in v)


def run_pr(api, feed, *, repo=DEFAULT_REPO, pr_number, action, sender_login=None, sender_type=None,
           event_label=None, is_fork=False, template_dir="templates", event_head_sha=None):
    """Evaluate one pull request and (unless a fork) post the sticky comment and the status."""
    pr = api.get_pr(pr_number)
    head_sha = pr["head"]["sha"]
    base_sha = pr["base"]["sha"]
    labels = {l["name"] for l in pr.get("labels", [])}
    label_present = LABEL in labels

    # registers
    register_error = None
    try:
        base_text = api.get_file(REGISTER_PATH, base_sha)
        base_reg = parse_register(base_text) if base_text is not None else None
    except RegisterError:
        base_reg = None
    head_text = api.get_file(REGISTER_PATH, head_sha)
    if head_text is None and is_fork:
        head_text = api.get_file(REGISTER_PATH, "refs/pull/%d/head" % pr_number)
    head_reg = None
    if head_text is not None:
        try:
            head_reg = parse_register(head_text)
        except RegisterError as e:
            register_error = str(e)

    files = api.list_pr_files(pr_number)
    record_ids = []
    for f in files:
        name = f.get("filename", "")
        if f.get("status") != "removed" and re.fullmatch(r"changes/[^/]+\.md", name):
            record_ids.append(name[len("changes/"):-3])

    gate_files = [{"path": plain_register(n)} for n in gate_files_changed(files)]
    deploy_files = [{"path": plain_register(n)} for n in deploy_files_changed(files)]

    plans_by_id = {p["id"]: p for p in feed.plans}
    titles = {c["change_id"]: clean_feed(c["title"]) for c in feed.changes}

    if register_error:
        added = changed = removed = []
    else:
        added, changed, removed = diff_registers(base_reg, head_reg)

    tools, rows = [], []
    for kind, items in (("added", added), ("changed", changed)):
        for t in items:
            c = _tool_ctx(t, kind, feed, plans_by_id)
            tools.append(c)
            rows.append(_row(kind, plain_register(t.get("name") or t.get("id")),
                             plain_register(t.get("plan") or "none"), "register entry", len(c["open_changes"])))
    removed_tools = [{"tool_name": code_register(t.get("name") or t.get("id"))} for t in removed]
    for t in removed:
        rows.append(_row("removed", plain_register(t.get("name") or t.get("id")),
                         plain_register(t.get("plan") or "none"), "register entry", 0))
    change_records = [{"change_id": cid, "title": titles.get(cid, plain_register(cid))} for cid in record_ids]

    # AI use declared in service/**/model.yaml and k8s/**, matched against the head register
    register_tools = (head_reg or base_reg or {}).get("tools", [])
    svc_tools, removed_services, unregistered, service_errors, svc_rows = service_changes(
        api, files, base_sha=base_sha, head_sha=head_sha, pr_number=pr_number, is_fork=is_fork, feed=feed,
        plans_by_id=plans_by_id, register_tools=register_tools)
    tools += svc_tools
    rows += svc_rows

    other_reasons = bool(tools or removed_tools or change_records or register_error or gate_files
                         or removed_services or service_errors)
    nothing = not (other_reasons or deploy_files)
    needs = not nothing
    can_sign = not (register_error or unregistered or service_errors)

    # sticky comment and sign-off
    sticky = None if is_fork else find_sticky(api.list_comments(pr_number))
    record = parse_marker(sticky["body"])[1] if sticky else None
    stored, signed, cleared, denied, stale = _evaluate_signoff(
        action=action, label_present=label_present, record=record, head_sha=head_sha,
        sender_login=sender_login, sender_type=sender_type, event_label=event_label,
        api=api, pr_number=pr_number, is_fork=is_fork, event_head_sha=event_head_sha,
        can_sign=can_sign)
    # a stored record only counts when it matches the head commit
    if stored and stored["sha"] != head_sha:
        stored = None
    if not needs:
        signed = False

    marker = make_marker(stored)
    ctx = {
        "gate_marker": marker,
        # The organisation comes from the base register (main), the head register only when main has none.
        **organisation_context(base_reg if (base_reg or {}).get("organisation") else head_reg),
        "repo": repo,
        "feed_source": feed.source_label,
        "feed_version": feed.version,
        "pr_number": pr_number,
        "head_sha_short": head_sha[:7],
        "register_path": REGISTER_PATH,
        "operates_in": _operates_in(head_reg or base_reg),
        "tools": tools,
        "removed_tools": removed_tools,
        "change_records": change_records,
        "removed_services": removed_services,
        "has_unregistered": bool(unregistered),
        "unregistered": unregistered,
        "has_service_errors": bool(service_errors),
        "sign_off_blocked": bool(unregistered or service_errors),
        "service_errors": service_errors,
        "has_gate_files": bool(gate_files),
        "gate_files": gate_files,
        "has_deploy_only": bool(deploy_files) and not other_reasons,
        "deploy_files": deploy_files,
        "nothing_to_check": nothing,
        "needs_sign_off": needs and not signed,
        "signed_off": signed,
        "signed_by": stored["by"] if signed else "",
        "signed_on": stored["at"][:10] if signed else "",
        "signed_sha_short": stored["sha"][:7] if signed else "",
        "label_name": LABEL,
        "sign_off_cleared": cleared,
        "is_fork": is_fork,
        # extras for cases the design list does not name
        "register_error": register_error or "",
        "sign_off_denied": bool(denied) and can_sign,
        "sign_off_stale": stale,
        "denied_login": plain_register(denied) if denied else "",
    }
    with open(os.path.join(template_dir, "gate-comment.md"), encoding="utf-8") as f:
        tpl = f.read()
    body = render(tpl, ctx)
    body = _fallback_lines(body, placeholder_names(tpl), ctx)
    if not body.startswith(MARKER_PREFIX):
        body = marker + "\n" + body

    if nothing:
        state, desc = "success", DESC_NOTHING
    elif signed:
        state, desc = "success", DESC_SIGNED % plain_register(stored["by"])
    elif register_error:
        state, desc = "failure", DESC_REGISTER
    elif service_errors:
        state, desc = "failure", DESC_SERVICE_CONFIG
    elif unregistered:
        state, desc = "failure", DESC_UNREGISTERED
    elif gate_files:
        state, desc = "failure", DESC_GATE_FILES
    else:
        state, desc = "failure", DESC_WAITING
    if is_fork and needs:
        desc = DESC_FORK

    if not is_fork:
        if sticky:
            if sticky["body"] != body:
                api.update_comment(sticky["id"], body)
        else:
            api.create_comment(pr_number, body)
        api.set_status(head_sha, state, desc, STATUS_CONTEXT)

    # The commit status carries red and green. Once it is posted the job has done its work and ends green, so a
    # waiting pull request shows one red check, not a failed workflow run as well. A fork pull request gets no
    # status (its token is read-only), so there the job result is the only signal and it fails closed.
    return GateResult(state=state, description=desc, body=body, needs_sign_off=needs, signed=signed,
                      exit_code=1 if (is_fork and needs) else 0, head_sha=head_sha, cleared=cleared,
                      rows=rows, gate_files=[g["path"] for g in gate_files], record_ids=record_ids,
                      deploy_files=[g["path"] for g in deploy_files],
                      service_errors=service_errors, pr_number=pr_number, feed_version=feed.version,
                      feed_source=feed.source_label)


# ---- command line -----------------------------------------------------------

def _summary(text):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def _cell(s):
    return str(s).replace("|", "/").replace("\n", " ")


def summary_markdown(res, action=None, is_fork=False):
    """The job summary: the result, then one row per tool, model config or Kubernetes resource the PR changes."""
    lines = ["## Checkable gate, pull request #%s" % res.pr_number, ""]
    where = "not posted, fork pull request" if is_fork else "status `%s` on commit `%s`" % (STATUS_CONTEXT, res.head_sha[:7])
    lines.append("**%s**: %s (%s)." % (res.state, res.description, where))
    lines.append("")
    lines.append("Event: `%s`. Feed: %s, version %s." % (action or "unknown", res.feed_source, res.feed_version))
    if res.rows:
        lines += ["", "| Change | Tool or config | Plan | Register | Open vendor changes |", "|---|---|---|---|---|"]
        for r in res.rows:
            lines.append("| %s | %s | %s | %s | %d |" % (r["kind"], _cell(r["item"]), _cell(r["plan"]),
                                                      _cell(r["register"] or "-"), r["open_changes"]))
    if res.record_ids:
        lines += ["", "Change records: " + ", ".join("`changes/%s.md`" % plain_register(c) for c in res.record_ids)]
    if res.gate_files:
        lines += ["", "Gate files changed: " + ", ".join("`%s`" % g for g in res.gate_files)]
    deploy_files = getattr(res, "deploy_files", None) or []
    if deploy_files:
        lines += ["", "Service or infrastructure files changed: " + ", ".join("`%s`" % g for g in deploy_files)]
    for e in res.service_errors:
        lines += ["", "Config problem in `%s`: %s" % (e["path"], e["error"])]
    if not (res.rows or res.record_ids or res.gate_files or deploy_files or res.service_errors):
        lines += ["", "Nothing the gate guards changed."]
    if is_fork:
        lines += ["", "### Gate comment", "", res.body]
    return "\n".join(lines) + "\n"


def main(argv=None):
    from .github_api import GitHubAPI
    repo = os.environ["GITHUB_REPOSITORY"]
    api = GitHubAPI(repo, os.environ["GITHUB_TOKEN"])
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        ev = json.load(f)
    pr = ev["pull_request"]
    head_repo = (pr.get("head") or {}).get("repo") or {}
    sender = ev.get("sender") or {}
    # Dependabot's own events run with a read-only token, like a fork: the gate reports in the job summary.
    is_fork = head_repo.get("full_name") != repo or sender.get("login") == "dependabot[bot]"
    if not is_fork:
        for problem in api.ensure_labels(LABELS):
            print("::warning::" + problem)
    try:
        feed = load_feed(os.environ.get("FEED_URL"))
    except FeedError as e:
        print("::error::" + str(e))
        if not is_fork:  # red, not missing, so the pull request never looks clear
            api.set_status(pr["head"]["sha"], "failure", DESC_FEED, STATUS_CONTEXT)
        _summary("## Checkable gate, pull request #%s\n\n**failure**: %s. %s" % (pr["number"], DESC_FEED, e))
        return 2
    res = run_pr(api, feed, repo=repo, pr_number=pr["number"], action=ev.get("action"),
                 sender_login=sender.get("login"), sender_type=sender.get("type"),
                 event_label=(ev.get("label") or {}).get("name"), is_fork=is_fork,
                 template_dir=os.environ.get("TEMPLATE_DIR", "templates"),
                 event_head_sha=(pr.get("head") or {}).get("sha"))
    print("%s: %s" % (res.state, res.description))
    _summary(summary_markdown(res, ev.get("action"), is_fork))
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
