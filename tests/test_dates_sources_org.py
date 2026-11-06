"""Header dates for updated changes, one Source line per page and date, and the organisation from the register."""
import os

import pytest

from scripts.checkable import gate
from scripts.checkable.changectx import FALLBACK_ORGANISATION, change_context, organisation_context, vendor_updated
from scripts.checkable.feed import load_feed
from scripts.checkable.match import hits_for_change
from scripts.checkable.register import RegisterError, parse_register
from scripts.checkable.render import render
from tests.helpers import (LIC_CC, REGISTER_TEXT, ROOT, FakeAPI, demo_feed, evidence, make_feed, register_with,
                           template_dir)

ANTH = "chg_anthropic-2025-08-28-consumer-terms"
GH = "chg_github-2026-10-26-gpt-6-1-terra-copilot"
CHANGE_TEMPLATES = ("pr-body", "change-record", "update-comment", "email-body")
URL_A = "https://example.test/a"
URL_B = "https://example.test/b"


def _tpl(name):
    with open(os.path.join(template_dir(), name + ".md"), encoding="utf-8") as f:
        return f.read()


def _render(ctx, name):
    return render(_tpl(name), dict(ctx, is_update=(name == "update-comment"), previous_version=1, pr_number=7,
                                   pr_url="https://github.com/o/r/pull/7"))


def _ctx(feed_data, cid, register_text=REGISTER_TEXT):
    feed = make_feed(feed_data)
    reg = parse_register(register_text)
    ch = next(c for c in feed.changes if c["change_id"] == cid)
    return change_context(ch, hits_for_change(ch, reg["tools"]), feed, register=reg)


def _with_change(cid, **fields):
    data = demo_feed()
    ch = next(c for c in data["changes"] if c["change_id"] == cid)
    ch.update(fields)
    return data


def _snapshot_and_register():
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        feed = load_feed(None)
    finally:
        os.chdir(cwd)
    with open(os.path.join(ROOT, "ai-vendor-register.yaml"), encoding="utf-8") as f:
        return feed, parse_register(f.read())


# ---- 1: an updated change shows the announcement date and the update date ------------------------

def test_vendor_updated_wording():
    assert vendor_updated({"vendor_date": "2025-08-28"}) == ""
    assert vendor_updated({"vendor_date": "2025-08-28", "vendor_updated_on": None}) == ""
    assert vendor_updated({"vendor_date": "2025-08-28", "vendor_updated_on": "2025-08-28"}) == ""
    assert vendor_updated({"vendor_date": "2025-05-13", "vendor_updated_on": "2025-10-09",
                           "vendor_updated_basis": "court_record"}) == "9 Oct 2025"
    assert vendor_updated({"vendor_date": "2025-08-28", "vendor_updated_on": "2025-09-30",
                           "vendor_updated_basis": "archive_first_capture"}) == "by 30 Sep 2025"


@pytest.mark.parametrize("name", CHANGE_TEMPLATES)
def test_header_names_both_dates_for_an_updated_change(name):
    data = _with_change(ANTH, vendor_updated_on="2025-09-30", vendor_updated_basis="archive_first_capture")
    out = _render(_ctx(data, ANTH), name)
    assert "28 Aug 2025, updated by 30 Sep 2025" in out
    assert "Vendor date 30 Sep" not in out and "Vendor date: 30 Sep" not in out


@pytest.mark.parametrize("name", CHANGE_TEMPLATES)
def test_header_without_an_update_has_no_updated_part(name):
    out = _render(_ctx(demo_feed(), GH), name)
    header = next(l for l in out.splitlines() if "Vendor date" in l)
    assert "26 Oct 2026" in header and "updated" not in header


def test_snapshot_header_for_anthropic_is_the_announcement_date():
    feed, reg = _snapshot_and_register()
    ch = next(c for c in feed.changes if c["change_id"] == ANTH)
    ctx = change_context(ch, hits_for_change(ch, reg["tools"]), feed, register=reg)
    assert (ctx["vendor_date"], ctx["vendor_updated"]) == ("28 Aug 2025", "by 30 Sep 2025")
    assert "**Vendor date 28 Aug 2025, updated by 30 Sep 2025.**" in _render(ctx, "pr-body")


def test_a_feed_without_the_1_1_fields_still_renders():
    data = demo_feed()
    for c in data["changes"]:
        c.pop("vendor_updated_on", None)
        c.pop("vendor_updated_basis", None)
    ctx = _ctx(data, ANTH)
    assert ctx["vendor_updated"] == ""
    assert "**Vendor date 28 Aug 2025, detected 28 Aug 2025.**" in _render(ctx, "pr-body")


# ---- 2: one Source line per page and date ---------------------------------------------------------

def _three_readings():
    ev = [evidence("ev_1", URL_A, reading="Checkable AI's reading of A: one."),
          evidence("ev_2", URL_A, reading="Checkable AI's reading of A: two."),
          evidence("ev_3", URL_B, reading="Checkable AI's reading of B: three.")]
    return _with_change(GH, evidence=ev)


@pytest.mark.parametrize("name", CHANGE_TEMPLATES)
def test_readings_on_one_page_share_one_source_line(name):
    out = _render(_ctx(_three_readings(), GH), name)
    source_lines = [l for l in out.splitlines() if "Source:" in l]
    assert len(source_lines) == 2, source_lines
    assert sum(URL_A in l for l in source_lines) == 1 and sum(URL_B in l for l in source_lines) == 1
    # every reading is still there, above the Source line of its page
    assert out.index("A: one.") < out.index("A: two.") < out.index(URL_A) < out.index("B: three.") < out.index(URL_B)


@pytest.mark.parametrize("name", CHANGE_TEMPLATES)
def test_same_page_on_two_dates_keeps_two_source_lines(name):
    data = _three_readings()
    ch = next(c for c in data["changes"] if c["change_id"] == GH)
    ch["evidence"][1]["published_on"] = "2026-10-28"
    out = _render(_ctx(data, GH), name)
    assert sum(URL_A in l for l in out.splitlines() if "Source:" in l) == 2


@pytest.mark.parametrize("name", CHANGE_TEMPLATES)
def test_quotes_on_one_page_share_one_source_line_with_one_credit(name):
    ev = [evidence("ev_q1", URL_A, quote="First quoted line.", lic=LIC_CC),
          evidence("ev_q2", URL_A, quote="Second quoted line.", lic=LIC_CC)]
    out = _render(_ctx(_with_change(GH, evidence=ev, licence={"quotes": "verbatim"}), GH), name)
    source_lines = [l for l in out.splitlines() if "Source:" in l]
    assert len(source_lines) == 1 and source_lines[0].count("CC BY 4.0") == 1
    assert "First quoted line." in out and "Second quoted line." in out


@pytest.mark.parametrize("name", CHANGE_TEMPLATES)
def test_snapshot_renders_have_no_repeated_source_line(name):
    feed, reg = _snapshot_and_register()
    for ch in feed.changes:
        ctx = change_context(ch, hits_for_change(ch, reg["tools"]), feed, register=reg)
        lines = [l.strip() for l in _render(ctx, name).splitlines() if "Source:" in l]
        assert len(lines) == len(set(lines)), (ch["change_id"], lines)


# ---- 4: organisation and the fictional phrase come from the register ------------------------------

def test_organisation_context():
    assert organisation_context({"organisation": "Example Bay Advisory", "fictional": True}) == \
        {"company_name": "Example Bay Advisory", "is_fictional": True}
    assert organisation_context({"organisation": "Acme Legal"}) == {"company_name": "Acme Legal", "is_fictional": False}
    assert organisation_context({"organisation": "Acme", "fictional": "yes"})["is_fictional"] is False
    assert organisation_context({}) == {"company_name": FALLBACK_ORGANISATION, "is_fictional": False}
    assert organisation_context(None)["company_name"] == FALLBACK_ORGANISATION
    assert organisation_context({"organisation": "@team `x`\nY"})["company_name"] == "@ team x Y"


REAL_REGISTER = register_with(replace={"organisation: Example Bay Advisory\nfictional: true\n":
                                       "organisation: Acme Legal\nfictional: false\n"})
NO_FLAG_REGISTER = register_with(replace={"fictional: true\n": ""})


@pytest.mark.parametrize("name", CHANGE_TEMPLATES)
@pytest.mark.parametrize("which", ["fictional_false", "flag_missing"])
def test_fictional_phrase_only_when_the_register_says_so(name, which):
    register_text = REAL_REGISTER if which == "fictional_false" else NO_FLAG_REGISTER
    out = _render(_ctx(demo_feed(), GH, register_text), name)
    assert "fictional" not in out and "made up" not in out
    if name != "update-comment":
        assert ("Acme Legal" if which == "fictional_false" else "Example Bay Advisory") in out


@pytest.mark.parametrize("name", CHANGE_TEMPLATES)
def test_fictional_phrase_kept_for_the_demo_register(name):
    out = _render(_ctx(demo_feed(), GH), name)
    if name != "update-comment":
        assert "Example Bay Advisory, a fictional sample company" in out


def test_pr_body_sentence_reads_cleanly_for_a_real_register():
    out = _render(_ctx(demo_feed(), GH, REAL_REGISTER), "pr-body")
    assert "The register belongs to Acme Legal.\n" in out


def test_gate_comment_takes_the_organisation_from_the_base_register():
    extra = "  - {id: claude-pro-partners, name: Claude Pro, vendor: Anthropic, product: anthropic.claude, plan: anthropic.claude.pro}\n"
    files = [("ai-vendor-register.yaml", "modified")]
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=register_with(extra), files=files)
    body = gate.run_pr(api, make_feed(), pr_number=4, action="opened", template_dir=template_dir()).body
    assert "of Example Bay Advisory, a fictional sample company operating in AU, EU, US." in body

    api = FakeAPI(base_register=REAL_REGISTER, head_register=REAL_REGISTER + extra, files=files)
    body = gate.run_pr(api, make_feed(), pr_number=4, action="opened", template_dir=template_dir()).body
    assert "of Acme Legal, operating in AU, EU, US." in body and "fictional" not in body

    # a pull request cannot rename the organisation in the gate comment while main names one
    renamed = register_with(extra, replace={"organisation: Example Bay Advisory": "organisation: Someone Else"})
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=renamed, files=files)
    body = gate.run_pr(api, make_feed(), pr_number=4, action="opened", template_dir=template_dir()).body
    assert "Someone Else" not in body and "Example Bay Advisory" in body


def test_register_rejects_odd_organisation_or_fictional_values():
    with pytest.raises(RegisterError):
        parse_register(register_with(replace={"organisation: Example Bay Advisory": "organisation: [a, b]"}))
    with pytest.raises(RegisterError):
        parse_register(register_with(replace={"fictional: true": "fictional: maybe"}))


def test_demo_register_is_marked_fictional():
    _, reg = _snapshot_and_register()
    assert reg["organisation"] == "Example Bay Advisory" and reg["fictional"] is True


def test_no_template_or_module_hardcodes_the_company():
    for name in CHANGE_TEMPLATES + ("gate-comment",):
        stripped = _tpl(name).replace("{{#is_fictional}}, a fictional sample company", "")
        assert "fictional sample company" not in stripped and "Example Bay" not in stripped, name
    import scripts.checkable.changectx as cc
    assert not hasattr(cc, "COMPANY_NAME")
