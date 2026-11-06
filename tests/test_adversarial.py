"""Cases from the adversarial pass of 6 Nov 2026: odd register shapes, stale sign-off, feed ids, nightly failures."""
import copy
import json

import pytest

from scripts.checkable import gate, nightly
from scripts.checkable.changectx import branch_for
from scripts.checkable.feed import FeedError, validate_feed
from scripts.checkable.register import RegisterError, parse_register
from tests.helpers import REGISTER_TEXT, FakeAPI, demo_feed, make_feed, register_with, template_dir
from tests.test_dedup import GEM, REG, FakeOps, feed_with_version, rec

FEED = make_feed()
TPL = template_dir()
SHA1, SHA2 = "1" * 40, "2" * 40
ROLES = {"alice": "write", "bob": "triage"}


def mk(head, labels=(), sha=SHA1):
    return FakeAPI(base_register=REGISTER_TEXT, head_register=head, labels=labels, head_sha=sha, roles=dict(ROLES))


def go(api, action, sender="alice", event_head_sha=None):
    return gate.run_pr(api, FEED, pr_number=9, action=action, sender_login=sender, sender_type="User",
                       event_label=gate.LABEL, template_dir=TPL, event_head_sha=event_head_sha)


# ---- register shapes ----------------------------------------------------------

@pytest.mark.parametrize("value", ["42", "AU", "{a: 1}", "[AU, 3]", "[AU, [EU]]"])
def test_odd_operates_in_is_a_register_error_not_a_crash(value):
    head = REGISTER_TEXT.replace("operates_in: [AU, EU, US]", "operates_in: " + value)
    api = mk(head)
    res = go(api, "synchronize")
    assert res.state == "failure" and res.description == gate.DESC_REGISTER
    assert api.statuses[-1][1] == "failure"


def test_operates_in_text_is_neutralised_from_base():
    base = REGISTER_TEXT.replace("operates_in: [AU, EU, US]", "operates_in: [\"AU @someone\", \"`x`\"]")
    api = FakeAPI(base_register=base, head_register="tools: [", roles=dict(ROLES))
    res = go(api, "synchronize")
    assert "@ someone" in res.body and "`x`" not in res.body


@pytest.mark.parametrize("field,value", [("plan", "[a, b]"), ("plan", "{x: 1}"), ("id", "[1]"), ("product", "{p: q}"),
                                         ("name", "[N]"), ("vendor", "{v: 1}")])
def test_non_text_tool_fields_are_a_register_error(field, value):
    text = register_with("  - {id: z, name: Z, %s: %s}\n" % (field, value)) if field not in ("id", "name") else \
        register_with("  - {%s: %s}\n" % (field, value))
    with pytest.raises(RegisterError):
        parse_register(text)
    api = mk(text)
    assert go(api, "synchronize").state == "failure"


def test_broken_register_cannot_be_signed_off():
    api = mk("tools: [", labels=[gate.LABEL])
    res = go(api, "labeled", event_head_sha=SHA1)
    assert not res.signed and res.state == "failure"
    assert gate.LABEL in api.removed_labels
    assert "cannot turn this check green" in res.body
    # and a later run with the label somehow back on still fails
    api.labels.append(gate.LABEL)
    assert go(api, "reopened").state == "failure"


# ---- stale sign-off -------------------------------------------------------------

def test_label_on_an_older_head_is_removed_and_not_recorded():
    head = register_with("  - {id: n, name: N, plan: null}\n")
    api = mk(head, labels=[gate.LABEL], sha=SHA2)  # branch moved to SHA2 after the label went on at SHA1
    res = go(api, "labeled", event_head_sha=SHA1)
    assert not res.signed and res.state == "failure"
    assert gate.LABEL in api.removed_labels
    assert "signed:" not in api.comments[-1]["body"].split("\n")[0]
    assert "New commits arrived" in res.body


def test_label_on_the_current_head_still_signs():
    head = register_with("  - {id: n, name: N, plan: null}\n")
    api = mk(head, labels=[gate.LABEL], sha=SHA1)
    assert go(api, "labeled", event_head_sha=SHA1).signed


def test_triage_user_cannot_sign():
    head = register_with("  - {id: n, name: N, plan: null}\n")
    api = mk(head, labels=[gate.LABEL])
    res = go(api, "labeled", sender="bob", event_head_sha=SHA1)
    assert not res.signed and gate.LABEL in api.removed_labels


# ---- feed ids -------------------------------------------------------------------

@pytest.mark.parametrize("cid", ["../../etc/x", "a/b", "-x", ".hidden", "a..b", "x.lock", "", "a" * 81, "a b"])
def test_unsafe_change_ids_are_refused(cid):
    d = demo_feed()
    d["changes"][0]["change_id"] = cid
    with pytest.raises(FeedError):
        validate_feed(d)


def test_snapshot_ids_pass():
    for c in demo_feed()["changes"]:
        assert branch_for(c["change_id"]).startswith("checkable/chg_")


# ---- gate when the feed cannot be read ------------------------------------------------------

def test_gate_posts_red_when_feed_unreadable(tmp_path, monkeypatch):
    ev = {"action": "opened", "sender": {"login": "alice", "type": "User"},
          "pull_request": {"number": 9, "head": {"sha": SHA1, "repo": {"full_name": "o/r"}}}}
    p = tmp_path / "ev.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    calls = []

    class Api:
        def __init__(self, repo, token):
            pass

        def set_status(self, *a):
            calls.append(a)

        def ensure_labels(self, labels):
            return []

    import scripts.checkable.github_api as gh
    monkeypatch.setattr(gh, "GitHubAPI", Api)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("FEED_URL", "https://example.com/feed.json")  # wrong host, refused before any fetch
    assert gate.main() == 2
    assert calls == [(SHA1, "failure", gate.DESC_FEED, gate.STATUS_CONTEXT)]


# ---- nightly failures -----------------------------------------------------------------

class BrokenOps(FakeOps):
    def __init__(self, fail_on):
        super().__init__()
        self.fail_on = fail_on

    def open_pr(self, cid, branch, text, title, body):
        if cid == self.fail_on:
            raise RuntimeError("push refused")
        return super().open_pr(cid, branch, text, title, body)


def _api():
    return FakeAPI(base_register=REGISTER_TEXT, head_register=REGISTER_TEXT, files=[("changes/x.md", "added")])


def test_one_failing_change_does_not_stop_the_others():
    ops = BrokenOps(GEM)
    alerts, lines = nightly.run(FEED, REG, ops, _api(), repo="o/r", template_dir=TPL)
    assert GEM not in [a["change_id"] for a in alerts]
    assert len(alerts) == len(ops.opened) >= 1
    assert any(l.startswith(GEM + ": failed, ") for l in lines)


def test_alert_kept_when_gate_fails_after_the_pr_opened(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("status call failed")
    monkeypatch.setattr(gate, "run_pr", boom)
    ops = FakeOps()
    alerts, lines = nightly.run(FEED, REG, ops, _api(), repo="o/r", template_dir=TPL)
    assert len(alerts) == len(ops.opened) >= 1


def test_closed_pr_with_deleted_branch_still_gets_the_new_version():
    ops = FakeOps()
    ops.prs[branch_for(GEM)] = [{"number": 7, "state": "CLOSED", "url": "https://github.test/pull/7"}]
    api = _api()
    api.get_file = lambda path, ref: rec(1) if ref == "refs/pull/7/head" else None
    alerts, lines = nightly.run(feed_with_version(2), REG, ops, api, repo="o/r", template_dir=TPL)
    assert any(a["change_id"] == GEM and a["kind"] == "update" for a in alerts)
    assert any("commenting on PR #7" in l for l in lines)


def test_dependabot_event_writes_nothing(tmp_path, monkeypatch):
    # Dependabot's own events get a read-only token, so the gate treats them like a fork and posts nothing
    ev = {"action": "opened", "sender": {"login": "dependabot[bot]", "type": "Bot"},
          "pull_request": {"number": 9, "head": {"sha": SHA1, "repo": {"full_name": "o/r"}}}}
    p = tmp_path / "ev.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    calls = []

    class Api:
        def __init__(self, repo, token):
            pass

        def set_status(self, *a):
            calls.append(a)

        def ensure_labels(self, labels):
            calls.append("labels")
            return []

    import scripts.checkable.github_api as gh
    monkeypatch.setattr(gh, "GitHubAPI", Api)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("FEED_URL", "https://example.com/feed.json")
    assert gate.main() == 2
    assert calls == []
