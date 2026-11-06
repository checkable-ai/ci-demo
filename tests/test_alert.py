import json

import pytest

from scripts.checkable import alert
from scripts.checkable.changectx import change_context
from scripts.checkable.match import hits_for_change
from scripts.checkable.register import parse_register
from tests.helpers import REGISTER_TEXT, make_feed, template_dir

TPL = template_dir()
AT = chr(64)
GOOD = {"ALERT_TO": alert.ALLOWED_TO[0], "ALERT_FROM": alert.ALLOWED_FROM}


def sample_alerts():
    feed = make_feed()
    reg = parse_register(REGISTER_TEXT)
    c = feed.changes[0]
    ctx = change_context(c, hits_for_change(c, reg["tools"]), feed, register=reg,
                         extra={"pr_number": 4, "pr_url": "https://github.test/pull/4"})
    return [{"kind": "new", "change_id": c["change_id"], "context": ctx}]


@pytest.mark.parametrize("to", [
    "someone" + AT + "example.test", "nobody" + AT + "checkableai.com", "", "hello+feed-test" + AT + "checkableai.com,other" + AT + "example.test",
    "HELLO+feed-test" + AT + "checkableai.com"])
def test_recipient_outside_the_two_is_refused(to):
    with pytest.raises(alert.AlertError):
        alert.check_addresses(to, alert.ALLOWED_FROM)


def test_both_allowed_recipients_pass():
    for to in alert.ALLOWED_TO:
        alert.check_addresses(to, alert.ALLOWED_FROM)


def test_sender_other_than_feed_is_refused():
    with pytest.raises(alert.AlertError):
        alert.check_addresses(alert.ALLOWED_TO[0], "nobody" + AT + "checkableai.com")


def test_ses_json_shape():
    m = alert.build_message("Subject here", "Body here\n")
    assert m == {"Simple": {"Subject": {"Data": "Subject here", "Charset": "UTF-8"},
                            "Body": {"Text": {"Data": "Body here\n", "Charset": "UTF-8"}}}}


def test_no_send_without_role_arn(tmp_path):
    files, rendered, send = alert.prepare(sample_alerts(), dict(GOOD), str(tmp_path), TPL)
    assert send is False and files == [] and len(rendered) == 1
    assert list(tmp_path.iterdir()) == []


def test_blank_role_arn_is_not_set(tmp_path):
    assert alert.should_send({"AWS_ROLE_ARN": "  "}) is False


def test_send_writes_one_file_per_alert(tmp_path):
    env = dict(GOOD, AWS_ROLE_ARN="arn:aws:iam::123456789012:role/x")
    alerts = sample_alerts() * 2
    files, rendered, send = alert.prepare(alerts, env, str(tmp_path), TPL)
    assert send and len(files) == 2
    data = json.loads(open(files[0], encoding="utf-8").read())
    assert "Simple" in data and data["Simple"]["Subject"]["Data"]


def test_prepare_refuses_before_writing(tmp_path):
    env = dict(GOOD, ALERT_TO="x" + AT + "example.test", AWS_ROLE_ARN="arn:aws:iam::1:role/x")
    with pytest.raises(alert.AlertError):
        alert.prepare(sample_alerts(), env, str(tmp_path), TPL)
    assert list(tmp_path.iterdir()) == []


def test_subject_is_one_line_and_short():
    a = sample_alerts()
    a[0]["context"]["title"] = "Line one\nline two " + "x" * 400
    subject, body = alert.render_alert(a[0], TPL)
    assert "\n" not in subject and len(subject) <= 160
    # a long title is cut, never the PR number
    assert subject.endswith(" (PR #4)")


def _alert_for_pr(number, kind="new"):
    a = sample_alerts()[0]
    ctx = dict(a["context"], pr_number=number, pr_url="https://github.test/pull/%d" % number,
               is_update=(kind == "update"), previous_version=1 if kind == "update" else "")
    return dict(a, kind=kind, context=ctx)


def test_subject_names_the_pull_request_so_gmail_does_not_thread_alerts():
    # Gmail threads mail with the same subject. Two alerts for two pull requests must never share one.
    s3, _ = alert.render_alert(_alert_for_pr(3), TPL)
    s4, _ = alert.render_alert(_alert_for_pr(4), TPL)
    title = sample_alerts()[0]["context"]["title"]
    assert s3 == "Checkable: %s (PR #3)" % title
    assert s4 == "Checkable: %s (PR #4)" % title
    su, _ = alert.render_alert(_alert_for_pr(4, "update"), TPL)
    assert su == "Checkable update: %s (PR #4)" % title
    assert len({s3, s4, su}) == 3


def test_nightly_alerts_carry_the_pr_number_into_the_subject():
    from scripts.checkable import nightly
    ctx = sample_alerts()[0]["context"]
    for kind, n in (("new", 3), ("update", 12)):
        a = nightly._alert(kind, "chg_x", ctx, None, n, "https://github.test/pull/%d" % n, 1)
        subject, body = alert.render_alert(a, TPL)
        assert subject.endswith(" (PR #%d)" % n) and ("pull request #%d" % n) in body


def test_subject_without_a_pr_number_has_no_empty_suffix():
    a = sample_alerts()[0]
    a = dict(a, context=dict(a["context"], pr_number=""))
    subject, _ = alert.render_alert(a, TPL)
    assert "PR #" not in subject


def test_one_line_subject_keeps_the_suffix_at_the_limit():
    s = alert.one_line_subject("Checkable: " + "y" * 300 + " (PR #123)")
    assert len(s) == alert.SUBJECT_MAX and s.endswith("y (PR #123)")
    assert alert.one_line_subject("short (PR #1)") == "short (PR #1)"
    assert alert.one_line_subject("z" * 200) == "z" * 160
