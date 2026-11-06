import re

from scripts.checkable import gate
from scripts.checkable.register import diff_registers, parse_register
from tests.helpers import REGISTER_TEXT, FakeAPI, make_feed, register_with, template_dir

FEED = make_feed()
TPL = template_dir()


def run(head, files=(), base=REGISTER_TEXT, **kw):
    api = FakeAPI(base_register=base, head_register=head, files=list(files))
    res = gate.run_pr(api, FEED, pr_number=5, action="opened", template_dir=TPL, **kw)
    return res, api


def test_g1_claude_pro_lookup_hit():
    head = register_with('  - {id: claude-pro-partners, name: Claude Pro, vendor: Anthropic, product: anthropic.claude, plan: anthropic.claude.pro, account_type: personal, used_by: "Two partners"}\n')
    res, api = run(head)
    assert res.exit_code == 0 and res.state == "failure" and res.description == gate.DESC_WAITING
    assert "chg_anthropic-2025-08-28-consumer-terms" in res.body
    assert "Reaches you" in res.body
    assert "`Anthropic`" in res.body
    assert "APPs" in res.body and "EU-GDPR" in res.body and "US-FTC-S5-AI" in res.body
    assert "https://example.test/terms/anthropic.claude.pro" in res.body
    assert api.statuses[-1][1:] == ("failure", gate.DESC_WAITING, gate.STATUS_CONTEXT)
    assert len(api.created) == 1


def test_g2_openai_api_two_hits():
    head = register_with("  - {id: openai-api, name: OpenAI API, vendor: OpenAI, product: openai.api, plan: openai.api.platform, account_type: business}\n")
    res, _ = run(head)
    assert res.exit_code == 0 and res.state == "failure"
    assert "chg_openai-2026-10-21-service-tier-limits" in res.body and "Reaches you" in res.body
    # the ended court order is shown as a record only, after the open changes, and never as an open change
    head, _, ended = res.body.partition("Ended vendor changes, for the record.")
    assert "chg_openai-2025-05-13-nyt-preservation" in ended
    assert "chg_openai-2025-05-13-nyt-preservation" not in head


def test_g3_plan_null_not_in_catalogue():
    head = register_with('  - {id: notes-app-ai, name: Notes App AI, vendor: Example Notes Co, product: null, plan: null}\n')
    res, _ = run(head)
    assert res.exit_code == 0 and res.state == "failure"
    assert re.search(r"Not in the (Checkable )?catalogue", res.body)
    assert "`Notes App AI`" in res.body
    assert "chg_" not in res.body


def test_g4_used_by_change_only():
    head = REGISTER_TEXT.replace("Advisory staff", "Advisory and tax staff")
    res, _ = run(head)
    assert res.exit_code == 0 and res.state == "failure"
    assert "`Claude Team`" in res.body and "https://example.test/terms/anthropic.claude.team" in res.body and "APPs" in res.body
    assert "chg_" not in res.body  # Claude Team is clear


def test_g5_readme_only_is_green():
    res, api = run(REGISTER_TEXT, files=[("README.md", "modified")])
    assert res.exit_code == 0 and res.state == "success" and res.description == gate.DESC_NOTHING
    assert "No AI tools changed." in res.body
    assert api.statuses[-1][1] == "success"


def test_removed_tool():
    head = REGISTER_TEXT.replace(
        "  - {id: m365-copilot, name: Microsoft 365 Copilot, vendor: Microsoft, product: microsoft.m365-copilot, plan: microsoft.m365-copilot.commercial}\n", "")
    res, _ = run(head)
    assert res.exit_code == 0 and res.state == "failure" and "`Microsoft 365 Copilot`" in res.body and "chg_" not in res.body


def test_deleted_register_removes_every_tool():
    res, _ = run(None)
    assert res.exit_code == 0 and res.state == "failure" and all(n in res.body for n in ("`Claude Team`", "`ChatGPT Plus`", "`Microsoft 365 Copilot`"))


def test_unparseable_register_is_red_with_error():
    res, api = run("tools: [unclosed")
    assert res.exit_code == 0 and res.state == "failure" and res.description == gate.DESC_REGISTER
    assert "Register error" in res.body or "Register problem" in res.body
    assert api.statuses[-1][1] == "failure"


def test_change_record_file_needs_sign_off():
    res, _ = run(REGISTER_TEXT, files=[("changes/chg_x.md", "added")])
    assert res.exit_code == 0 and res.state == "failure" and "changes/chg_x.md" in res.body


def test_removed_record_file_does_not_count():
    res, _ = run(REGISTER_TEXT, files=[("changes/chg_x.md", "removed")])
    assert res.exit_code == 0


def test_id_missing_falls_back_to_name():
    base = "tools:\n  - {name: Foo Tool, plan: null}\n"
    head = "tools:\n  - {name: Foo Tool, plan: null, used_by: someone}\n"
    a, c, r = diff_registers(parse_register(base), parse_register(head))
    assert not a and not r and [t["name"] for t in c] == ["Foo Tool"]


def test_duplicate_ids_are_a_register_error():
    head = register_with("  - {id: claude-team, name: Again}\n")
    res, _ = run(head)
    assert res.description == gate.DESC_REGISTER


def test_untrusted_values_are_neutralised():
    head = register_with('  - {id: evil, name: "Hi @octocat `x`\\nsecond line", vendor: "V <b>", plan: null}\n')
    res, _ = run(head)
    assert "@octocat" not in res.body and "@ octocat" in res.body
    assert "`Hi @ octocat x second line`" in res.body


def test_comment_is_sticky_and_not_duplicated():
    head = register_with('  - {id: n, name: N, plan: null}\n')
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=head)
    gate.run_pr(api, FEED, pr_number=5, action="opened", template_dir=TPL)
    gate.run_pr(api, FEED, pr_number=5, action="reopened", template_dir=TPL)
    assert len(api.comments) == 1
    assert api.comments[0]["body"].startswith(gate.MARKER_PREFIX)


def test_first_line_is_the_marker():
    res, _ = run(REGISTER_TEXT)
    assert res.body.split("\n")[0] == "<!-- checkable-gate v1 -->"
