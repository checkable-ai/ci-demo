import copy
import json

from scripts.checkable import gate, nightly
from scripts.checkable.changectx import branch_for
from scripts.checkable.register import parse_register
from tests.helpers import REGISTER_TEXT, FakeAPI, demo_feed, make_feed, template_dir

TPL = template_dir()
REG = parse_register(REGISTER_TEXT)
GEM = "chg_google-2026-10-26-gemini-api-storage-default"


def rec(version):
    return "---\nchange_id: x\nversion: %d\n---\nbody\n" % version


class FakeOps:
    def __init__(self):
        self.prs = {}       # branch -> list of {number,state,url}
        self.main = {}      # change_id -> record text
        self.branch = {}    # change_id -> record text
        self.opened, self.updated = [], []
        self.next = 100

    def find_prs(self, branch):
        return list(self.prs.get(branch, []))

    def read_record(self, where, cid, branch=None):
        return (self.main if where == "main" else self.branch).get(cid)

    def open_pr(self, cid, branch, text, title, body):
        self.next += 1
        url = "https://github.test/pull/%d" % self.next
        self.prs.setdefault(branch, []).append({"number": self.next, "state": "OPEN", "url": url})
        self.branch[cid] = text
        self.opened.append((cid, title, body))
        return self.next, url

    def update_pr(self, cid, branch, number, text, body):
        self.branch[cid] = text
        self.updated.append((cid, number, body))


def make_api():
    return FakeAPI(base_register=REGISTER_TEXT, head_register=REGISTER_TEXT, files=[("changes/x.md", "added")])


def run(feed, ops, api=None, dry=False):
    return nightly.run(feed, REG, ops, api or make_api(), repo="checkable-ai/ci-demo", template_dir=TPL, dry_run=dry)


def feed_with_version(v):
    d = demo_feed()
    for c in d["changes"]:
        if c["change_id"] == GEM:
            c["version"] = v
    return make_feed(d)


def test_decide_table():
    D = nightly.decide
    open_pr = [{"number": 1, "state": "OPEN", "url": "u"}]
    closed = [{"number": 1, "state": "CLOSED", "url": "u"}]
    merged = [{"number": 1, "state": "MERGED", "url": "u"}]
    assert D(1, [], None, None)[0] == "open"
    assert D(1, open_pr, None, 1)[0] == "nothing"
    assert D(2, open_pr, None, 1)[0] == "update_open"
    assert D(1, closed, None, 1)[0] == "nothing"
    assert D(2, closed, None, 1)[0] == "comment"
    assert D(1, merged, 1, None)[0] == "nothing"
    assert D(2, merged, 1, None)[0] == "comment"
    assert D(1, [], 1, None)[0] == "nothing"
    assert D(2, [], 1, None)[0] == "skip"
    assert D(2, closed, None, None)[0] == "nothing"  # cannot tell, never open a second PR


def test_first_run_opens_one_pr_per_open_change():
    ops, api = FakeOps(), make_api()
    alerts, lines = run(make_feed(), ops, api)
    assert len(ops.opened) == 2 and len(alerts) == 2
    assert {a["kind"] for a in alerts} == {"new"}
    # the ended court order is on record in the feed but opens no sign-off pull request
    assert sorted(o[0] for o in ops.opened) == sorted([GEM, "chg_github-2026-10-26-gpt-6-1-terra-copilot"])
    # every PR got a gate comment and a failing status
    assert len(api.created) == 2
    assert all(s[1] == "failure" and s[3] == gate.STATUS_CONTEXT for s in api.statuses)
    assert all("[" in o[1] for o in ops.opened)  # tool names in the title
    assert all(a["context"]["pr_number"] for a in alerts)


def test_second_run_opens_nothing():
    ops, api = FakeOps(), make_api()
    run(make_feed(), ops, api)
    for cid, branch_prs in list(ops.prs.items()):
        pass
    before = len(ops.opened)
    alerts, lines = run(make_feed(), ops, api)
    assert len(ops.opened) == before and alerts == []
    assert lines[0] == "No new changes reach this register."


def test_open_pr_higher_version_updates_and_comments():
    ops, api = FakeOps(), make_api()
    run(make_feed(), ops, api)
    api.labels.append(gate.LABEL)
    api.comments.clear()
    alerts, _ = run(feed_with_version(2), ops, api)
    assert len(ops.opened) == 2 and len(ops.updated) == 1
    assert [a["kind"] for a in alerts] == ["update"]
    assert alerts[0]["context"]["previous_version"] == 1 and alerts[0]["context"]["is_update"]
    assert gate.LABEL in api.removed_labels
    assert any(b.startswith("<!-- checkable-update %s v2 -->" % GEM) for _, b in api.created)
    assert parse_ver(ops.branch[GEM]) == 2
    assert api.statuses[-1][1] == "failure"


def parse_ver(text):
    return nightly.parse_record_version(text)


def test_closed_pr_higher_version_comments_and_never_opens():
    ops, api = FakeOps(), make_api()
    ops.prs[branch_for(GEM)] = [{"number": 7, "state": "CLOSED", "url": "https://github.test/pull/7"}]
    ops.branch[GEM] = rec(1)
    feed = feed_with_version(2)
    alerts, _ = run(feed, ops, api)
    assert GEM not in [o[0] for o in ops.opened]
    assert ops.updated == []
    assert [(n, b.split("\n")[0]) for n, b in api.created if n == 7] == [(7, "<!-- checkable-update %s v2 -->" % GEM)]
    assert any(a["kind"] == "update" and a["change_id"] == GEM for a in alerts)
    # second night: no repeat comment, no repeat alert
    n_before = len([1 for n, _ in api.created if n == 7])
    alerts2, _ = run(feed, ops, api)
    assert len([1 for n, _ in api.created if n == 7]) == n_before
    assert not any(a["change_id"] == GEM for a in alerts2)


def test_merged_pr_with_record_on_main_same_version_does_nothing():
    ops, api = FakeOps(), make_api()
    ops.prs[branch_for(GEM)] = [{"number": 8, "state": "MERGED", "url": "u"}]
    ops.main[GEM] = rec(1)
    run(make_feed(), ops, api)
    assert GEM not in [o[0] for o in ops.opened] and not ops.updated


def test_record_on_main_without_pr_never_opens():
    ops, api = FakeOps(), make_api()
    ops.main[GEM] = rec(1)
    run(make_feed(), ops, api)
    assert GEM not in [o[0] for o in ops.opened]
    alerts, lines = run(feed_with_version(2), ops, api)
    assert GEM not in [o[0] for o in ops.opened]
    assert any("no PR exists" in l for l in lines)


def test_dry_run_changes_nothing():
    ops, api = FakeOps(), make_api()
    alerts, lines = run(make_feed(), ops, api, dry=True)
    assert ops.opened == [] and api.created == [] and api.statuses == [] and alerts == []
    assert len([l for l in lines if "would open" in l]) == 2


def test_no_reaching_changes_message():
    d = demo_feed()
    d["changes"] = [c for c in d["changes"] if c["change_id"] == "chg_anthropic-2025-08-28-consumer-terms"]
    alerts, lines = run(make_feed(d), FakeOps())
    assert alerts == [] and lines == ["No new changes reach this register."]


def test_branch_name_rule():
    assert branch_for("chg_a b/c") == "checkable/chg_a-b-c"
    assert len(branch_for("x" * 200)) == len("checkable/") + 80


def test_record_front_matter_round_trip():
    feed = make_feed()
    from scripts.checkable.changectx import change_context
    c = feed.changes[0]
    ctx = change_context(c, [], feed)
    with open(TPL + "/change-record.md", encoding="utf-8") as f:
        tpl = f.read()
    text = nightly.record_text(c, ctx, feed, ["gemini-api-paid"], tpl)
    assert text.startswith("---\nchange_id: %s\n" % c["change_id"])
    assert nightly.parse_record_version(text) == c["version"]
    assert "status: awaiting sign-off" in text.split("---")[1]


def test_gitops_fetch_and_push_carry_the_same_auth(monkeypatch):
    import subprocess
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops = nightly.GitOps("checkable-ai/ci-demo", "tok", workdir=".")
    ops.fetch()
    ops._push("checkable/x")
    fetch, push = calls
    assert fetch[1] == push[1] == "-c" and fetch[2] == push[2] == ops.auth_config()
    assert "fetch" in fetch and "push" in push
    assert "tok" not in " ".join(fetch + push)  # only the encoded form is passed
