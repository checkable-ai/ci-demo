"""A pull request that changes the gate's own files stays red until a person signs it off."""
import pytest

from scripts.checkable import gate
from tests.helpers import REGISTER_TEXT, FakeAPI, make_feed, register_with, template_dir

FEED = make_feed()
TPL = template_dir()
REAL_TPL = "templates"


def run(files, labels=(), comments=None, action="opened", tpl=TPL, **kw):
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=REGISTER_TEXT, files=list(files),
                  labels=labels, roles={"owner": "admin"}, comments=comments)
    res = gate.run_pr(api, FEED, pr_number=9, action=action, template_dir=tpl, **kw)
    return res, api


@pytest.mark.parametrize("path", [
    "feed-snapshot/changes.json",
    "feed-snapshot/changes.schema.json",
    "scripts/checkable/gate.py",
    "scripts/requirements.txt",
    "templates/gate-comment.md",
    "tests/test_gate_diff.py",
    ".github/workflows/checkable-gate.yml",
    ".github/dependabot.yml",
])
@pytest.mark.parametrize("status", ["added", "modified", "removed"])
def test_gate_path_needs_sign_off(path, status):
    res, api = run([(path, status)])
    assert res.exit_code == 0 and res.state == "failure"
    assert res.description == gate.DESC_GATE_FILES == "Gate files changed. A person signs this off."
    assert "Gate files changed. A person signs this off." in res.body
    assert path in res.body
    assert "No AI tools changed" not in res.body
    assert api.statuses[-1][1:] == ("failure", gate.DESC_GATE_FILES, gate.STATUS_CONTEXT)


@pytest.mark.parametrize("path", ["README.md", "docs/notes.md", "scriptsx/a.py", "my-tests/a.py", "github/x.yml"])
def test_other_paths_stay_green(path):
    res, _ = run([(path, "modified")])
    assert res.exit_code == 0 and res.description == gate.DESC_NOTHING


def test_rename_out_of_a_gate_path_counts():
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=REGISTER_TEXT)
    api.list_pr_files = lambda n: [{"filename": "docs/gate.py", "status": "renamed",
                                    "previous_filename": "scripts/checkable/gate.py"}]
    res = gate.run_pr(api, FEED, pr_number=9, action="opened", template_dir=TPL)
    assert res.exit_code == 0 and res.state == "failure" and "scripts/checkable/gate.py" in res.body


def test_real_template_shows_headline_and_files():
    res, _ = run([("scripts/checkable/gate.py", "modified"), (".github/workflows/tests.yml", "modified")], tpl=REAL_TPL)
    assert "**Gate files changed. A person signs this off.**" in res.body
    assert "- `.github/workflows/tests.yml`" in res.body and "- `scripts/checkable/gate.py`" in res.body
    assert "Waiting for a person to sign off." in res.body


def test_label_signs_off_gate_files():
    res, api = run([("scripts/checkable/gate.py", "modified")], labels=[gate.LABEL], action="labeled",
                   sender_login="owner", sender_type="User", event_label=gate.LABEL)
    assert res.exit_code == 0 and res.state == "success" and res.description == gate.DESC_SIGNED % "owner"


def test_new_commit_clears_gate_file_sign_off():
    _, api = run([("tests/test_feed.py", "modified")], labels=[gate.LABEL], action="labeled",
                 sender_login="owner", sender_type="User", event_label=gate.LABEL)
    api.head_sha = "c" * 40
    res = gate.run_pr(api, FEED, pr_number=9, action="synchronize", template_dir=TPL)
    assert res.exit_code == 0 and res.state == "failure" and res.cleared and gate.LABEL in api.removed_labels


def test_gate_files_and_tool_change_together():
    head = register_with('  - {id: openai-api, name: OpenAI API, vendor: OpenAI, product: openai.api, plan: openai.api.platform, account_type: business}\n')
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=head, files=[("templates/pr-body.md", "modified")])
    res = gate.run_pr(api, FEED, pr_number=9, action="opened", template_dir=REAL_TPL)
    assert res.exit_code == 0 and res.state == "failure"
    assert "Gate files changed. A person signs this off." in res.body and "`OpenAI API`" in res.body


def test_fork_with_gate_files_stays_red_without_status():
    res, api = run([("scripts/checkable/gate.py", "modified")], is_fork=True)
    assert res.exit_code == 1 and api.statuses == [] and res.description == gate.DESC_FORK
