from scripts.checkable import gate
from tests.helpers import REGISTER_TEXT, FakeAPI, make_feed, register_with, template_dir

FEED = make_feed()
TPL = template_dir()
HEAD = register_with("  - {id: n, name: N, plan: null}\n")
SHA1, SHA2 = "1" * 40, "2" * 40


def mk(labels=(), comments=None, sha=SHA1, roles=None):
    return FakeAPI(base_register=REGISTER_TEXT, head_register=HEAD, labels=labels, head_sha=sha,
                   roles=roles if roles is not None else {"alice": "write", "bob": "read", "carol": "maintain", "dan": "admin"},
                   comments=comments)


def go(api, action, sender="alice", sender_type="User", label=gate.LABEL, fork=False):
    return gate.run_pr(api, FEED, pr_number=9, action=action, sender_login=sender, sender_type=sender_type,
                       event_label=label, is_fork=fork, template_dir=TPL)


def bot_comment(body, cid=1):
    return {"id": cid, "body": body, "user": {"login": "github-actions[bot]"}}


def test_writer_label_passes_and_records_sha():
    api = mk()
    go(api, "opened")
    api.labels.append(gate.LABEL)
    res = go(api, "labeled")
    assert res.exit_code == 0 and res.signed and res.state == "success"
    first = api.comments[0]["body"].split("\n")[0]
    assert first.startswith("<!-- checkable-gate v1 signed:%s by:alice at:" % SHA1)
    assert "Signed off" in res.body and "alice" in res.body
    assert api.statuses[-1][1:3] == ("success", "Signed off by alice")


def test_maintain_and_admin_may_sign_off():
    for who in ("carol", "dan"):
        api = mk(labels=[gate.LABEL])
        assert go(api, "labeled", sender=who).signed


def test_read_only_user_label_removed():
    api = mk(labels=[gate.LABEL])
    res = go(api, "labeled", sender="bob")
    assert not res.signed and res.exit_code == 0 and res.state == "failure"
    assert gate.LABEL in api.removed_labels and gate.LABEL not in api.labels
    assert "label was removed" in res.body
    assert api.comments[0]["body"].startswith("<!-- checkable-gate v1 -->")


def test_bot_sender_cannot_sign_off():
    api = mk(labels=[gate.LABEL], roles={"github-actions[bot]": "write"})
    res = go(api, "labeled", sender="github-actions[bot]", sender_type="Bot")
    assert not res.signed and gate.LABEL in api.removed_labels


def test_label_with_old_sha_fails():
    old = bot_comment("<!-- checkable-gate v1 signed:%s by:alice at:2026-11-06T01:00:00Z -->\nold" % SHA1)
    api = mk(labels=[gate.LABEL], comments=[old], sha=SHA2)
    res = go(api, "reopened")
    assert not res.signed and res.exit_code == 0 and res.state == "failure"
    assert api.comments[0]["body"].startswith("<!-- checkable-gate v1 -->")


def test_matching_sha_and_label_stays_green_on_later_run():
    c = bot_comment("<!-- checkable-gate v1 signed:%s by:alice at:2026-11-06T01:00:00Z -->\nold" % SHA1)
    api = mk(labels=[gate.LABEL], comments=[c])
    res = go(api, "reopened")
    assert res.signed and res.exit_code == 0 and "alice" in res.body


def test_record_without_label_is_not_signed():
    c = bot_comment("<!-- checkable-gate v1 signed:%s by:alice at:2026-11-06T01:00:00Z -->\nold" % SHA1)
    api = mk(labels=[], comments=[c])
    assert not go(api, "labeled", label="other").signed


def test_synchronize_clears_label_and_record():
    c = bot_comment("<!-- checkable-gate v1 signed:%s by:alice at:2026-11-06T01:00:00Z -->\nold" % SHA1)
    api = mk(labels=[gate.LABEL], comments=[c], sha=SHA2)
    res = go(api, "synchronize")
    assert not res.signed and res.cleared and res.exit_code == 0 and res.state == "failure"
    assert gate.LABEL in api.removed_labels
    assert "A new commit cleared" in res.body
    assert api.comments[0]["body"].startswith("<!-- checkable-gate v1 -->")


def test_bot_updated_clears_like_synchronize():
    c = bot_comment("<!-- checkable-gate v1 signed:%s by:alice at:2026-11-06T01:00:00Z -->\nold" % SHA1)
    api = mk(labels=[gate.LABEL], comments=[c], sha=SHA2)
    res = go(api, "bot-updated", sender=None, sender_type=None, label=None)
    assert res.cleared and not res.signed and res.state == "failure"


def test_unlabeled_clears_record():
    c = bot_comment("<!-- checkable-gate v1 signed:%s by:alice at:2026-11-06T01:00:00Z -->\nold" % SHA1)
    api = mk(labels=[], comments=[c])
    res = go(api, "unlabeled")
    assert not res.signed and res.exit_code == 0 and res.state == "failure"
    assert api.comments[0]["body"].startswith("<!-- checkable-gate v1 -->")


def test_forged_marker_by_non_bot_is_ignored():
    forged = {"id": 1, "body": "<!-- checkable-gate v1 signed:%s by:mallory at:2026-11-06T01:00:00Z -->\nx" % SHA1,
              "user": {"login": "mallory"}}
    api = mk(labels=[gate.LABEL], comments=[forged])
    res = go(api, "reopened")
    assert not res.signed and res.exit_code == 0 and res.state == "failure"
    # the gate wrote its own comment and left the forged one alone
    assert len(api.comments) == 2 and api.comments[0]["user"]["login"] == "mallory"


def test_fork_pr_fails_closed_and_writes_nothing():
    api = mk(labels=[gate.LABEL], comments=[])
    res = go(api, "labeled", fork=True)
    assert not res.signed and res.exit_code == 1
    assert api.created == [] and api.statuses == [] and api.removed_labels == []
    assert res.body


def test_fork_pr_with_nothing_to_check_is_green():
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=REGISTER_TEXT, files=[("README.md", "modified")])
    res = go(api, "opened", fork=True)
    assert res.exit_code == 0 and api.statuses == []


def test_nothing_to_check_ignores_label():
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=REGISTER_TEXT, labels=[gate.LABEL])
    res = go(api, "labeled", sender="alice")
    assert res.exit_code == 0 and res.description == gate.DESC_NOTHING


def test_self_sign_off_allowed():
    api = mk(labels=[gate.LABEL])
    assert go(api, "labeled", sender="alice").signed
