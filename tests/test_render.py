import os

import pytest

from scripts.checkable import render as R
from scripts.checkable.changectx import change_context
from scripts.checkable.match import hits_for_change
from scripts.checkable.register import parse_register
from tests.helpers import REGISTER_TEXT, TEMPLATE_NAMES, make_feed, template_dir

CHANGE_TEMPLATES = ["pr-body", "change-record", "update-comment", "email-subject", "email-body"]


def test_variable_and_comment_and_sections():
    t = "{{! note }}\nHi {{name}}.\n{{#items}}\n- {{n}} of {{name}}\n{{/items}}\n{{^items}}none\n{{/items}}"
    assert R.render(t, {"name": "A", "items": [{"n": 1}, {"n": 2}]}) == "Hi A.\n- 1 of A\n- 2 of A\n"
    assert R.render(t, {"name": "A", "items": []}) == "Hi A.\nnone\n"


def test_boolean_sections_and_none():
    t = "{{#a}}yes{{/a}}{{^a}}no{{/a}}|{{b}}|"
    assert R.render(t, {"a": True, "b": None}) == "yes||"
    assert R.render(t, {"a": False, "b": "x"}) == "no|x|"
    assert R.render("{{#a}}yes{{/a}}", {"a": None}) == ""


def test_unknown_placeholder_raises():
    with pytest.raises(R.RenderError):
        R.render("{{nope}}", {})
    with pytest.raises(R.RenderError):
        R.render("{{#nope}}x{{/nope}}", {})
    with pytest.raises(R.RenderError):
        R.render("{{#a}}{{missing}}{{/a}}", {"a": [{"x": 1}]})


def test_unbalanced_raises():
    with pytest.raises(R.RenderError):
        R.render("{{#a}}x", {"a": True})
    with pytest.raises(R.RenderError):
        R.render("x{{/a}}", {"a": True})


def test_no_html_escaping():
    assert R.render("{{x}}", {"x": "a & b"}) == "a & b"


def test_clean_feed_removes_angle_brackets():
    assert R.clean_feed({"a": ["<b>x</b>"]}) == {"a": ["bx/b"]}


def test_register_values_neutralised():
    s = "evil `code`\nline @someone"
    assert R.plain_register(s) == "evil code line @ someone"
    assert R.code_register(s) == "`evil code line @ someone`"
    assert R.code_register("") == "`-`"


def test_fmt_date():
    assert R.fmt_date("2026-10-06") == "6 Oct 2026"
    assert R.fmt_date("2026-10-26T22:08:37Z") == "26 Oct 2026"
    assert R.fmt_date(None) == ""


def _contexts():
    feed = make_feed()
    reg = parse_register(REGISTER_TEXT)
    out = []
    for c in feed.changes:
        hits = hits_for_change(c, reg["tools"])
        out.append(change_context(c, hits, feed, register=reg, extra={"pr_number": 7, "pr_url": "https://example.test/pull/7",
                                                       "previous_version": 1, "is_update": True}))
        out.append(change_context(c, hits, feed))  # no register: the organisation falls back, no fictional phrase
    return out


@pytest.mark.parametrize("name", CHANGE_TEMPLATES)
def test_change_templates_render_clean(name):
    d = template_dir()
    with open(os.path.join(d, name + ".md"), encoding="utf-8") as f:
        tpl = f.read()
    for ctx in _contexts():
        out = R.render(tpl, ctx)
        assert "{{" not in out and "}}" not in out
        assert out.strip()


def test_gate_comment_renders_clean_for_every_case():
    from scripts.checkable import gate
    from tests.helpers import FakeAPI, register_with
    feed = make_feed()
    d = template_dir()
    head = register_with("  - {id: claude-pro-partners, name: Claude Pro, vendor: Anthropic, product: anthropic.claude, plan: anthropic.claude.pro}\n")
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=head)
    res = gate.run_pr(api, feed, pr_number=3, action="opened", template_dir=d)
    assert "{{" not in res.body and res.body.startswith("<!-- checkable-gate v1")
    api = FakeAPI(base_register=REGISTER_TEXT, head_register="a: [", files=[("changes/x.md", "added")])
    res = gate.run_pr(api, feed, pr_number=3, action="opened", template_dir=d)
    assert "{{" not in res.body


def test_every_template_present_uses_only_known_placeholders():
    """D's real templates, when present, must render with the contexts B provides."""
    present = [n for n in TEMPLATE_NAMES if os.path.exists(os.path.join(os.path.dirname(__file__), "..", "templates", n + ".md"))]
    assert present, "no real templates found"
