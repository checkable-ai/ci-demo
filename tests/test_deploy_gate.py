"""Deploy gate (deploy.yml, job checkable/deploy-gate): fail closed unless the merged pull request passed the gate."""
import pytest

from scripts.checkable import deploy_gate
from scripts.checkable.gate import DESC_NOTHING, DESC_SIGNED, DESC_WAITING, STATUS_CONTEXT, make_marker
from scripts.checkable.github_api import GitHubError

MERGE = "m" * 40
HEAD = "a" * 40
BOT = {"login": "github-actions[bot]"}


class Fake:
    repo = "checkable-ai/ci-demo"

    def __init__(self, pulls=None, statuses=None, comments=None, fail=None):
        self.pulls = pulls if pulls is not None else [pr()]
        self.statuses = statuses if statuses is not None else []
        self.comments = comments if comments is not None else []
        self.fail = fail

    def request(self, method, path, body=None, params=None):
        assert method == "GET"
        if self.fail:
            raise GitHubError(502, self.fail)
        if path.endswith("/commits/%s/pulls" % MERGE):
            return self.pulls
        if path.endswith("/commits/%s/statuses" % HEAD):
            return self.statuses
        return []

    def list_comments(self, number):
        return self.comments


def pr(number=7, merged=True, merge_sha=MERGE, base="main", head=HEAD):
    return {"number": number, "title": "Switch the summariser", "merged_at": "2026-11-06T01:00:00Z" if merged else None,
            "merge_commit_sha": merge_sha, "base": {"ref": base}, "head": {"sha": head}}


def status(state="success", desc=DESC_SIGNED % "checkable-reviewer", creator=BOT, context=STATUS_CONTEXT):
    return {"context": context, "state": state, "description": desc, "creator": creator}


def sticky(sha=HEAD, user=BOT):
    rec = {"sha": sha, "by": "checkable-reviewer", "at": "2026-11-06T00:50:00Z"}
    return {"user": user, "body": make_marker(rec) + "\n\n## Checkable gate"}


def test_signed_pull_request_passes():
    res = deploy_gate.check(Fake(statuses=[status()], comments=[sticky()]), MERGE)
    assert res["mode"] == "signed" and res["pr_number"] == 7 and res["signed_by"] == "checkable-reviewer"


def test_no_ai_change_passes_without_sign_off():
    res = deploy_gate.check(Fake(statuses=[status(desc=DESC_NOTHING)]), MERGE)
    assert res["mode"] == "no-ai-change"


@pytest.mark.parametrize("pulls", [[], [pr(merged=False)], [pr(merge_sha="b" * 40)], [pr(base="dev")],
                                   [pr(), pr(number=8)]])
def test_no_single_merged_pull_request_blocks(pulls):
    with pytest.raises(deploy_gate.Blocked):
        deploy_gate.check(Fake(pulls=pulls, statuses=[status()], comments=[sticky()]), MERGE)


@pytest.mark.parametrize("statuses", [
    [],
    [status(context="other")],
    [status(state="failure", desc=DESC_WAITING)],
    [status(state="pending")],
    [status(creator={"login": "someone"})],
    [status(creator=None)],
    # newest first: a later failure wins over an earlier success
    [status(state="failure", desc=DESC_WAITING), status()],
    [status(desc="Something new")],
])
def test_status_problems_block(statuses):
    with pytest.raises(deploy_gate.Blocked):
        deploy_gate.check(Fake(statuses=statuses, comments=[sticky()]), MERGE)


@pytest.mark.parametrize("comments", [[], [sticky(sha="c" * 40)], [sticky(user={"login": "someone"})],
                                      [{"user": BOT, "body": make_marker() + "\n"}]])
def test_signed_status_needs_matching_sticky_record(comments):
    with pytest.raises(deploy_gate.Blocked):
        deploy_gate.check(Fake(statuses=[status()], comments=comments), MERGE)


def test_app_bot_counts_when_configured():
    app = {"login": "checkable-ai[bot]"}
    res = deploy_gate.check(Fake(statuses=[status(creator=app)], comments=[sticky(user=app)]), MERGE,
                            logins={"github-actions[bot]", "checkable-ai[bot]"})
    assert res["mode"] == "signed"


def test_main_fails_closed_on_api_error(monkeypatch, tmp_path):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_SHA", MERGE)
    monkeypatch.setenv("GITHUB_REPOSITORY", "checkable-ai/ci-demo")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.delenv("DEPLOY_SHA", raising=False)
    from scripts.checkable import github_api
    monkeypatch.setattr(github_api, "GitHubAPI", lambda repo, token: Fake(fail="bad gateway"))
    assert deploy_gate.main() == 1
    assert "Blocked" in summary.read_text(encoding="utf-8")


def test_main_writes_outputs(monkeypatch, tmp_path):
    out = tmp_path / "out.txt"
    monkeypatch.setenv("DEPLOY_SHA", MERGE)
    monkeypatch.setenv("GITHUB_REPOSITORY", "checkable-ai/ci-demo")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    from scripts.checkable import github_api
    monkeypatch.setattr(github_api, "GitHubAPI",
                        lambda repo, token: Fake(statuses=[status()], comments=[sticky()]))
    assert deploy_gate.main() == 0
    text = out.read_text(encoding="utf-8")
    assert "pr_number=7\n" in text and "mode=signed\n" in text
