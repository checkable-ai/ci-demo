"""The nightly check opens pull requests with the org App token when it has one, and writes a job summary table."""
import pytest

from scripts.checkable import nightly
from tests.helpers import make_feed
from tests.test_dedup import GEM, REG, TPL, FakeOps, make_api

FEED = make_feed()


def test_app_token_is_used_for_pull_requests_when_present():
    assert nightly.pr_token({"GITHUB_TOKEN": "gh", "CHECKABLE_PR_TOKEN": "app"}) == ("app", "app")


@pytest.mark.parametrize("value", [None, "", "  "])
def test_falls_back_to_github_token(value):
    env = {"GITHUB_TOKEN": "gh"}
    if value is not None:
        env["CHECKABLE_PR_TOKEN"] = value
    assert nightly.pr_token(env) == ("gh", "github")


def test_bot_commits_are_org_owned():
    assert (nightly.BOT_NAME, nightly.BOT_EMAIL) == ("Checkable AI", "noreply@checkableai.com")


def test_run_fills_one_summary_row_per_reaching_change():
    rows = []
    nightly.run(FEED, REG, FakeOps(), make_api(), repo="checkable-ai/ci-demo", template_dir=TPL, rows=rows)
    ids = [r["change_id"] for r in rows]
    assert GEM in ids and len(ids) == len(set(ids))
    gem = rows[ids.index(GEM)]
    assert gem["version"] == 1 and "Gemini API (paid tier) (Reaches you)" in gem["tools"]
    assert gem["result"].startswith("v1: opening a pull request") and "opened #" in gem["result"]


def test_summary_markdown_has_the_table_and_the_token_note():
    rows = []
    _, lines = nightly.run(FEED, REG, FakeOps(), make_api(), repo="checkable-ai/ci-demo", template_dir=TPL,
                           dry_run=True, rows=rows)
    md = nightly.summary_markdown("Checkable nightly check (dry run)", FEED, lines, rows, "github")
    assert md.startswith("## Checkable nightly check (dry run)")
    assert "| Change | Version | Vendor date | Tools in the register | Result |" in md
    assert "| `%s` | 1 | 2026-10-26 |" % GEM in md and "would open a pull request" in md
    assert "falls back" not in md and "GITHUB_TOKEN" in md
    assert "Checkable AI GitHub App token" in nightly.summary_markdown("t", FEED, lines, rows, "app")


def test_summary_without_reaching_changes():
    md = nightly.summary_markdown("t", FEED, ["No new changes reach this register."], [], "app")
    assert "| Change |" not in md and "- No new changes reach this register." in md
