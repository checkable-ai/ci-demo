from scripts.checkable import match
from scripts.checkable.register import parse_register
from tests.helpers import REGISTER_TEXT, demo_feed

REG = parse_register(REGISTER_TEXT)
CHANGES = demo_feed()["changes"]
BY_ID = {c["change_id"]: c for c in CHANGES}


def tool(**kw):
    return dict(kw)


def test_plan_hit_takes_status():
    c = BY_ID["chg_google-2026-10-26-gemini-api-storage-default"]
    h = match.tool_hit(c, tool(id="g", plan="google.gemini-api.paid", product="google.gemini-api"))
    assert h["status"] == "affected" and h["via"] == "plan"


def test_product_only_gives_worth_a_check():
    c = BY_ID["chg_google-2026-10-26-gemini-api-storage-default"]
    h = match.tool_hit(c, tool(id="g", plan=None, product="google.gemini-api"))
    assert h["status"] == "under_investigation"
    assert match.STATUS_WORDS[h["status"]] == "Worth a check"


def test_plan_set_but_not_named_is_no_hit_even_if_product_matches():
    c = BY_ID["chg_google-2026-10-26-gemini-api-storage-default"]
    assert match.tool_hit(c, tool(id="g", plan="google.gemini-api.enterprise", product="google.gemini-api")) is None


def test_not_affected_is_clear_and_does_not_reach():
    c = BY_ID["chg_anthropic-2025-08-28-consumer-terms"]
    hits = match.hits_for_change(c, REG["tools"])
    assert [h["status"] for h in hits] == ["not_affected"]
    assert not match.reaches(hits)
    assert match.STATUS_WORDS["not_affected"] == "Clear"


def test_ended_change_does_not_reach():
    # An ended change never opens a sign-off pull request. The gate shows it as a record only.
    c = BY_ID["chg_openai-2025-05-13-nyt-preservation"]
    hits = match.hits_for_change(c, REG["tools"])
    assert [h["status"] for h in hits] == ["fixed"]
    assert not match.reaches(hits)
    assert match.STATUS_WORDS["fixed"] == "Ended"
    t = {"id": "chatgpt-plus-research", "plan": "openai.chatgpt.plus"}
    assert match.changes_for_tool(CHANGES, t) == []
    assert [c["change_id"] for c, _ in match.ended_changes_for_tool(CHANGES, t)] == [
        "chg_openai-2025-05-13-nyt-preservation"]


def test_withdrawn_change_never_reaches_or_shows():
    import copy
    changes = copy.deepcopy(CHANGES)
    for c in changes:
        if c["change_id"] == "chg_google-2026-10-26-gemini-api-storage-default":
            c["event_type"] = "change.withdrawn"
    ids = [c["change_id"] for c, _ in match.reaching_changes(changes, REG["tools"])]
    assert "chg_google-2026-10-26-gemini-api-storage-default" not in ids
    t = {"id": "gemini-api-paid", "plan": "google.gemini-api.paid"}
    assert match.changes_for_tool(changes, t) == [] and match.ended_changes_for_tool(changes, t) == []


def test_worth_a_check_reaches():
    assert match.reaches([{"status": "under_investigation"}])
    assert not match.reaches([{"status": "not_affected"}, {"status": "fixed"}])


def test_vendor_name_alone_never_matches():
    c = BY_ID["chg_openai-2026-10-21-service-tier-limits"]
    t = tool(id="x", name="Azure OpenAI", vendor="OpenAI", product="microsoft.azure-openai", plan="microsoft.azure-openai.standard")
    assert match.tool_hit(c, t) is None
    assert match.tool_hit(c, tool(id="y", vendor="OpenAI", plan=None, product=None)) is None


def test_inhouse_tool_matches_nothing():
    for c in CHANGES:
        assert match.tool_hit(c, tool(id="inhouse", plan=None, product=None, vendor=None)) is None


def test_first_run_is_exactly_two_changes():
    r = match.reaching_changes(CHANGES, REG["tools"])
    ids = [c["change_id"] for c, _ in r]
    assert ids == [
        "chg_github-2026-10-26-gpt-6-1-terra-copilot",
        "chg_google-2026-10-26-gemini-api-storage-default",
    ]


def test_changes_for_tool_skips_clear():
    t = {"id": "claude-team", "plan": "anthropic.claude.team"}
    assert match.changes_for_tool(CHANGES, t) == []
    t = {"id": "claude-pro", "plan": "anthropic.claude.pro"}
    assert [c["change_id"] for c, _ in match.changes_for_tool(CHANGES, t)] == ["chg_anthropic-2025-08-28-consumer-terms"]
