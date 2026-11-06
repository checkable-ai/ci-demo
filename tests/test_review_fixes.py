"""Fixes from the buyer review: gate exit code, workflow triggers, label set-up, and the rendered wording."""
import io
import json
import os
import re
import urllib.error

import yaml

from scripts.checkable import gate, nightly
from scripts.checkable.changectx import change_context, licence_credit, show_plan
from scripts.checkable.github_api import GitHubAPI
from scripts.checkable.match import hits_for_change
from scripts.checkable.register import parse_register
from scripts.checkable.render import render
from tests.helpers import (LIC_CC, LIC_PD, REGISTER_TEXT, ROOT, FakeAPI, make_feed, register_with,
                           template_dir)

WF = os.path.join(ROOT, ".github", "workflows")
GEM = "chg_google-2026-10-26-gemini-api-storage-default"
NYT = "chg_openai-2025-05-13-nyt-preservation"


def workflow(name):
    with open(os.path.join(WF, name), encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["on"] = data.pop(True, data.get("on"))  # PyYAML reads the bare key `on` as True
    return data


# ---- finding 1: the gate job ends green once it has posted a status ----------------------------

def test_waiting_gate_posts_red_status_and_exits_zero():
    head = register_with("  - {id: claude-pro-partners, name: Claude Pro, vendor: Anthropic, product: anthropic.claude, "
                         "plan: anthropic.claude.pro, account_type: personal, used_by: Two partners}\n")
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=head, files=[("ai-vendor-register.yaml", "modified")])
    res = gate.run_pr(api, make_feed(), pr_number=4, action="opened", template_dir=template_dir())
    assert res.exit_code == 0
    assert api.statuses == [("a" * 40, "failure", gate.DESC_WAITING, gate.STATUS_CONTEXT)]


def test_fork_with_something_to_sign_still_fails_the_job():
    # no status can be posted with a read-only token, so the job result is the only red signal
    head = register_with("  - {id: x, name: X, vendor: V, product: null, plan: null}\n")
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=head, files=[("ai-vendor-register.yaml", "modified")])
    res = gate.run_pr(api, make_feed(), pr_number=5, action="opened", is_fork=True, template_dir=template_dir())
    assert res.exit_code == 1 and api.statuses == []


# ---- findings 2 and 3: triggers ---------------------------------------------------------------

def test_gate_runs_on_open_only_and_ignores_bot_record_files():
    on = workflow("checkable-gate.yml")["on"]["pull_request"]
    assert on["types"] == ["opened"]
    assert on["paths-ignore"] == ["changes/**"]
    assert "paths" not in on


def test_sign_off_runs_on_every_later_event_without_a_path_filter():
    on = workflow("checkable-sign-off.yml")["on"]["pull_request"]
    assert set(on["types"]) == {"synchronize", "reopened", "labeled", "unlabeled"}
    assert "paths" not in on and "paths-ignore" not in on
    gate_types = set(workflow("checkable-gate.yml")["on"]["pull_request"]["types"])
    assert not gate_types & set(on["types"])  # one run per event, never two


def test_gate_and_sign_off_share_one_queue_and_never_use_pull_request_target():
    g, s = workflow("checkable-gate.yml"), workflow("checkable-sign-off.yml")
    assert g["concurrency"]["group"] == s["concurrency"]["group"]
    for wf in (g, s):
        assert "pull_request_target" not in wf["on"]
        assert wf["permissions"]["issues"] == "write"


def test_tests_workflow_runs_on_every_pull_request_as_the_required_tests_check():
    wf = workflow("tests.yml")
    # no path filter: the nightly's pull requests need the required `tests` check too
    assert not wf["on"]["pull_request"] or not ({"paths", "paths-ignore"} & set(wf["on"]["pull_request"]))
    assert wf["on"]["push"]["branches"] == ["main"]
    assert wf["jobs"]["tests"]["name"] == "tests"


def test_nightly_opens_pull_requests_with_the_app_token_and_falls_back():
    sync = workflow("checkable-nightly.yml")["jobs"]["sync"]
    steps = {s.get("id"): s for s in sync["steps"] if s.get("id")}
    assert steps["app-token"]["uses"].startswith("actions/create-github-app-token@")
    assert steps["app-token"]["with"]["app-id"] == "${{ secrets.CHECKABLE_APP_ID }}"
    assert steps["app-token"]["with"]["private-key"] == "${{ secrets.CHECKABLE_APP_PRIVATE_KEY }}"
    assert steps["app-token"]["if"] == "steps.app.outputs.present == 'true'"
    env = steps["nightly"]["env"]
    assert env["CHECKABLE_PR_TOKEN"] == "${{ steps.app-token.outputs.token }}"
    assert env["GITHUB_TOKEN"] == "${{ github.token }}"


def test_nightly_email_settings():
    alert = workflow("checkable-nightly.yml")["jobs"]["alert"]
    assert alert["permissions"] == {"contents": "read", "id-token": "write"}
    assert "hello+feed-test@checkableai.com" in alert["env"]["ALERT_TO"]
    assert "arn:aws:iam::726495711127:role/checkable-ci-demo-ses" in alert["env"]["AWS_ROLE_ARN"]
    assert "github.repository == 'checkable-ai/ci-demo'" in alert["env"]["AWS_ROLE_ARN"]


def test_nightly_sync_job_can_create_labels():
    perms = workflow("checkable-nightly.yml")["jobs"]["sync"]["permissions"]
    assert perms["issues"] == "write"


# ---- labels created when missing --------------------------------------------------------------

class FakeOpener:
    def __init__(self, existing=(), post_status=201):
        self.existing = set(existing)
        self.post_status = post_status
        self.calls = []

    def __call__(self, req, timeout=None):
        self.calls.append((req.get_method(), req.full_url))
        name = req.full_url.rsplit("/labels/", 1)[-1] if "/labels/" in req.full_url else None
        if req.get_method() == "GET":
            if name in self.existing:
                return io.BytesIO(b"{}")
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))
        if self.post_status >= 400:
            raise urllib.error.HTTPError(req.full_url, self.post_status, "x", {}, io.BytesIO(b"{}"))
        self.existing.add(json.loads(req.data)["name"])
        return io.BytesIO(b"{}")


def test_missing_labels_are_created():
    op = FakeOpener(existing={"ai-governance"})
    api = GitHubAPI("o/r", "t", opener=op)
    assert api.ensure_labels(gate.LABELS) == []
    assert [c for c in op.calls if c[0] == "POST"] == [("POST", "https://api.github.com/repos/o/r/labels")]
    assert op.existing == {"ai-governance", "checkable-signed-off"}


def test_existing_labels_are_left_alone():
    op = FakeOpener(existing={"ai-governance", "checkable-signed-off"})
    assert GitHubAPI("o/r", "t", opener=op).ensure_labels(gate.LABELS) == []
    assert all(m == "GET" for m, _ in op.calls)


def test_label_race_is_fine_and_a_refusal_is_reported_not_raised():
    assert GitHubAPI("o/r", "t", opener=FakeOpener(post_status=422)).ensure_labels(gate.LABELS) == []
    problems = GitHubAPI("o/r", "t", opener=FakeOpener(post_status=403)).ensure_labels(gate.LABELS)
    assert len(problems) == 2 and all("could not create" in p for p in problems)


def test_nightly_and_gate_use_the_same_label_names():
    assert nightly.PR_LABEL == "ai-governance" and gate.LABEL == "checkable-signed-off"
    assert {n for n, _, _ in gate.LABELS} == {"ai-governance", "checkable-signed-off"}


# ---- finding 5: wording --------------------------------------------------------------------------

def _ctx(cid):
    feed = make_feed()
    reg = parse_register(REGISTER_TEXT)
    ch = next(c for c in feed.changes if c["change_id"] == cid)
    return change_context(ch, hits_for_change(ch, reg["tools"]), feed, register=reg)


def _render_all(ctx):
    d = template_dir()
    out = {}
    for n in ("pr-body", "change-record", "update-comment", "email-body", "email-subject"):
        with open(os.path.join(d, n + ".md"), encoding="utf-8") as f:
            out[n] = render(f.read(), dict(ctx, is_update=(n == "update-comment"), previous_version=1,
                                           pr_number=7, pr_url="https://github.com/o/r/pull/7"))
    return out


def test_no_internal_event_id_in_anything_a_reader_sees():
    for cid in (GEM, NYT):
        for name, text in _render_all(_ctx(cid)).items():
            assert "evt_" not in text, name
            if name != "email-subject":
                assert cid in text, name


def test_each_quote_has_one_source_line_and_names_its_licence_once():
    out = _render_all(_ctx(GEM))
    for name in ("pr-body", "change-record", "update-comment", "email-body"):
        lines = [l for l in out[name].splitlines() if "Source:" in l]
        assert lines, name
        for l in lines:
            assert l.count("Source:") == 1, (name, l)
            if "CC BY 4.0" in l:
                assert l.count("CC BY 4.0") == 1, (name, l)


def test_licence_credit():
    assert licence_credit({"name": "CC BY 4.0", "attribution": "Source: Google for Developers, licensed under CC BY 4.0 (u)."}) \
        == "Google for Developers, licensed under CC BY 4.0 (u)."
    assert licence_credit(LIC_PD) == "Order of the US District Court, via CourtListener. Public domain (US court order)."
    assert licence_credit(LIC_CC).count("CC BY 4.0") == 1
    assert licence_credit({"name": None, "attribution": None}) == ""


def test_plan_name_shown_only_when_it_differs_from_the_tool_name():
    assert not show_plan("Gemini API (paid tier)", "Gemini API, paid tier")
    assert not show_plan("ChatGPT Plus", "ChatGPT Plus")
    assert show_plan("Research seat", "ChatGPT Plus")
    assert not show_plan("Anything", "")
    out = _render_all(_ctx(GEM))
    assert "Gemini API (paid tier): Reaches you" in out["pr-body"]
    assert "(Gemini API, paid tier)" not in out["pr-body"]
    assert "Gemini API (paid tier): Reaches you" in out["email-body"]


def test_no_detected_date_when_the_feed_has_none():
    ctx = _ctx(GEM)
    ctx["detected_on"] = ""
    for name in ("pr-body", "change-record", "update-comment", "email-body"):
        assert "detected" not in _render_all(ctx)[name], name


def test_snapshot_dates_match_the_primary_sources():
    with open(os.path.join(ROOT, "feed-snapshot", "changes.json"), encoding="utf-8") as f:
        feed = json.load(f)
    by_id = {c["change_id"]: c for c in feed["changes"]}
    nyt = by_id[NYT]
    # a retrospective KB entry is not a detection
    assert nyt["detected_at"] is None
    ev = {e["id"]: e for e in nyt["evidence"]}
    assert ev["ev_oai-q11"]["published_on"] == "2025-10-22"  # OpenAI's update of 22 October 2025
    assert ev["ev_oai-q4"]["published_on"] == "2025-06-05"
    assert ev["ev_oai-q15"]["published_on"] == "2025-10-09"
    for c in feed["changes"]:
        for e in c["evidence"]:
            assert not (e["licence"].get("attribution") or "").startswith("Source:"), e["id"]


def test_nightly_opens_no_pull_request_for_an_ended_change():
    from tests.test_dedup import FakeOps
    reg = parse_register(REGISTER_TEXT)
    ops = FakeOps()
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=REGISTER_TEXT, files=[("changes/x.md", "added")])
    nightly.run(make_feed(), reg, ops, api, repo="o/r", template_dir=template_dir())
    assert NYT not in [o[0] for o in ops.opened]
    assert ops.opened and not any(re.search(r"\bEnded\b", body) for _, _, body in ops.opened)
