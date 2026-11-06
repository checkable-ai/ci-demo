"""Build SES v2 messages from alerts.json and check the recipients before anything is sent."""
import json
import os
import re
import sys

from .render import render

ALLOWED_TO = ("hello+feed-test@checkableai.com", "hello+feed-demo@checkableai.com")
ALLOWED_FROM = "feed@checkableai.com"


class AlertError(Exception):
    pass


def check_addresses(to, frm):
    if to not in ALLOWED_TO:
        raise AlertError("ALERT_TO is not one of the two allowed demo recipients")
    if frm != ALLOWED_FROM:
        raise AlertError("ALERT_FROM is not the allowed demo sender")


def build_message(subject, body):
    """The --content JSON for `aws sesv2 send-email`."""
    return {"Simple": {
        "Subject": {"Data": subject, "Charset": "UTF-8"},
        "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
    }}


SUBJECT_MAX = 160
_PR_SUFFIX = re.compile(r" \(PR #\d+\)$")


def one_line_subject(text, limit=SUBJECT_MAX):
    """Fold the subject onto one line and cut it to `limit`, keeping a trailing " (PR #n)".

    The PR number makes each subject unique, so Gmail does not thread alerts for different pull requests.
    A long title is cut, never the PR number.
    """
    subject = " ".join(text.split())
    if len(subject) <= limit:
        return subject
    m = _PR_SUFFIX.search(subject)
    if not m:
        return subject[:limit]
    tail = m.group(0)
    return subject[:m.start()][:limit - len(tail)].rstrip() + tail


def render_alert(alert, template_dir="templates"):
    ctx = alert["context"]
    with open(os.path.join(template_dir, "email-subject.md"), encoding="utf-8") as f:
        subject = one_line_subject(render(f.read(), ctx))
    with open(os.path.join(template_dir, "email-body.md"), encoding="utf-8") as f:
        body = render(f.read(), ctx).strip() + "\n"
    return subject, body


def should_send(env):
    return bool((env.get("AWS_ROLE_ARN") or "").strip())


def prepare(alerts, env, out_dir=".", template_dir="templates"):
    """Check the addresses, write alert-<n>.json files, return (files, rendered, send)."""
    check_addresses(env.get("ALERT_TO", ""), env.get("ALERT_FROM", ""))
    files, rendered = [], []
    for i, a in enumerate(alerts, 1):
        subject, body = render_alert(a, template_dir)
        path = os.path.join(out_dir, "alert-%d.json" % i)
        send = should_send(env)
        if send:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(build_message(subject, body), f, indent=2)
            files.append(path)
        rendered.append((subject, body))
    return files, rendered, should_send(env)


def main(argv=None):
    try:
        with open("alerts.json", encoding="utf-8") as f:
            alerts = json.load(f)
        files, rendered, send = prepare(alerts, os.environ, ".", os.environ.get("TEMPLATE_DIR", "templates"))
    except AlertError as e:
        print("::error::" + str(e))
        return 2
    lines = ["## Checkable alert emails", ""]
    lines.append("Sending %d email(s)." % len(files) if send else
                 "AWS_ROLE_ARN is not set, so nothing is sent. The rendered emails follow.")
    if not send:
        for subject, body in rendered:
            lines += ["", "**Subject:** " + subject, "", "```", body.rstrip(), "```"]
    text = "\n".join(lines) + "\n"
    print(text)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as f:
            f.write(text)
    op = os.environ.get("GITHUB_OUTPUT")
    if op:
        with open(op, "a", encoding="utf-8") as f:
            f.write("send=%s\n" % ("true" if send and files else "false"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
