"""The gate also reads AI model use in service/**/model.yaml and k8s/** and matches it to the register."""
import os

import pytest

from scripts.checkable import feed as F
from scripts.checkable import gate, services
from scripts.checkable.register import parse_register
from tests.helpers import REGISTER_TEXT, ROOT, FakeAPI, make_feed, register_with, template_dir

FEED = make_feed()
TPL = template_dir()
REAL_TPL = os.path.join(ROOT, "templates")
MODEL = "service/summariser/model.yaml"
SERVICE_TIER = "chg_openai-2026-10-21-service-tier-limits"
GEMINI = "chg_google-2026-10-26-gemini-api-storage-default"
NYT = "chg_openai-2025-05-13-nyt-preservation"

GEMINI_MODEL = """\
service: summariser
register_tool: gemini-api-paid
vendor: Google
product: google.gemini-api
plan: google.gemini-api.paid
model: gemini-flash
"""
OPENAI_MODEL = GEMINI_MODEL.replace("vendor: Google", "vendor: OpenAI").replace(
    "product: google.gemini-api", "product: openai.api").replace(
    "plan: google.gemini-api.paid", "plan: openai.api.platform").replace("model: gemini-flash", "model: gpt-mini")
OPENAI_TOOL = ("  - {id: openai-api, name: OpenAI API, vendor: OpenAI, product: openai.api, "
               "plan: openai.api.platform, used_by: Summariser service}\n")
ROLES = {"alice": "write"}


def run(file_map, files, head_register=REGISTER_TEXT, labels=(), action="opened", sender=None, tpl=TPL, api=None,
        feed=FEED):
    api = api or FakeAPI(base_register=REGISTER_TEXT, head_register=head_register, files=files, labels=labels,
                         roles=dict(ROLES), file_map=file_map)
    res = gate.run_pr(api, feed, pr_number=12, action=action, sender_login=sender, sender_type="User",
                      event_label=gate.LABEL if action == "labeled" else None, template_dir=tpl)
    return res, api


# ---- paths -------------------------------------------------------------------------------------

@pytest.mark.parametrize("path,ok", [
    ("service/summariser/model.yaml", True), ("service/a/b/model.yml", True), ("service/summariser/handler.py", False),
    ("services/x/model.yaml", False), ("k8s/summariser/deployment.yaml", True), ("k8s/base.yml", True),
    ("k8s/README.md", False), ("ai-vendor-register.yaml", False), (None, False),
])
def test_service_paths(path, ok):
    assert services.is_service_path(path) is ok


# ---- model.yaml --------------------------------------------------------------------------------

def test_switch_to_a_plan_the_register_does_not_list_is_red_and_cannot_be_signed():
    files = [(MODEL, "modified")]
    res, api = run({MODEL: (GEMINI_MODEL, OPENAI_MODEL)}, files)
    assert res.state == "failure" and res.description == gate.DESC_UNREGISTERED
    assert "Not in the register" in res.body and "openai.api.platform" in res.body
    assert SERVICE_TIER in res.body  # the open vendor change on the new plan
    assert NYT in res.body  # the ended change, for the record
    assert "Before: vendor `Google`, plan `google.gemini-api.paid`, model `gemini-flash`" in res.body
    assert "The config still names register entry `gemini-api-paid`" in res.body
    # a writer's label cannot turn it green
    api.labels.append(gate.LABEL)
    res2, _ = run(None, files, action="labeled", sender="alice", api=api)
    assert not res2.signed and res2.state == "failure" and gate.LABEL in api.removed_labels
    assert "Only someone with write" not in res2.body


def test_switch_with_the_register_entry_added_waits_then_signs_off():
    files = [(MODEL, "modified"), ("ai-vendor-register.yaml", "modified")]
    head = register_with(OPENAI_TOOL)
    fm = {MODEL: (GEMINI_MODEL, OPENAI_MODEL)}
    res, api = run(fm, files, head_register=head)
    assert res.state == "failure" and res.description == gate.DESC_WAITING
    assert "Register entry: `OpenAI API (openai-api)`" in res.body
    api.labels.append(gate.LABEL)
    res2, _ = run(fm, files, head_register=head, action="labeled", sender="alice", api=api)
    assert res2.signed and res2.state == "success"


def test_switch_back_to_a_registered_plan_shows_its_open_change_and_waits_for_a_person():
    # The recorded scenario in docs/demo-script.md: after the OpenAI switch merged, a developer moves the
    # summariser back to the Gemini API paid tier, which the register already lists.
    reg = register_with(OPENAI_TOOL)
    files = [(MODEL, "modified")]
    api = FakeAPI(base_register=reg, head_register=reg, files=files, roles=dict(ROLES),
                  file_map={MODEL: (OPENAI_MODEL, GEMINI_MODEL)})
    res, api = run(None, files, api=api)
    assert res.state == "failure" and res.description == gate.DESC_WAITING
    assert "Before: vendor `OpenAI`, plan `openai.api.platform`, model `gpt-mini`" in res.body
    assert "Register entry: `Gemini API (paid tier) (gemini-api-paid)`" in res.body
    assert GEMINI in res.body and SERVICE_TIER not in res.body and "Not in the register" not in res.body
    assert gate.DEPLOY_FILES_HEADLINE not in res.body  # the AI section carries the sign-off, not the deploy note
    assert "Service or infrastructure files changed: `%s`" % MODEL in gate.summary_markdown(res, "opened")
    api.labels.append(gate.LABEL)
    res2, _ = run(None, files, action="labeled", sender="alice", api=api)
    assert res2.signed and res2.state == "success" and res2.description == gate.DESC_SIGNED % "alice"


def test_demo_script_scenario_on_the_real_register_snapshot_and_templates():
    # Guards the gate output that docs/demo-script.md promises, against the files in this repo.
    with open(os.path.join(ROOT, "ai-vendor-register.yaml"), encoding="utf-8") as f:
        reg = f.read()
    feed = F.load_feed(None, os.path.join(ROOT, "feed-snapshot", "changes.json"))
    files = [(MODEL, "modified")]
    api = FakeAPI(base_register=reg, head_register=reg, files=files, roles={"checkable-reviewer": "write"},
                  file_map={MODEL: (OPENAI_MODEL, GEMINI_MODEL)})
    res = gate.run_pr(api, feed, pr_number=6, action="opened", template_dir=REAL_TPL)
    assert res.state == "failure" and res.description == gate.DESC_WAITING
    assert "Register entry: `Gemini API (paid tier) (gemini-api-paid)`" in res.body
    # Loose on version and title wording, so a feed snapshot refresh does not break the required tests check.
    section = res.body[res.body.index("**Open vendor changes affecting this plan**"):]
    assert GEMINI in section and "Reaches you" in section
    assert SERVICE_TIER not in res.body
    api.labels.append(gate.LABEL)
    res2 = gate.run_pr(api, feed, pr_number=6, action="labeled", sender_login="checkable-reviewer",
                       sender_type="User", event_label=gate.LABEL, template_dir=REAL_TPL)
    assert res2.state == "success" and res2.description == "Signed off by checkable-reviewer"


def test_model_label_change_on_the_same_plan_needs_sign_off():
    head = GEMINI_MODEL.replace("model: gemini-flash", "model: gemini-pro")
    res, _ = run({MODEL: (GEMINI_MODEL, head)}, [(MODEL, "modified")])
    assert res.description == gate.DESC_WAITING
    assert "Register entry: `Gemini API (paid tier) (gemini-api-paid)`" in res.body
    assert GEMINI in res.body


def test_comment_only_edit_to_model_yaml_still_needs_a_person():
    # No AI use changed, but service/ deploys to production, so a person signs it off (deploy_gate.py needs it).
    head = "# a new comment\n" + GEMINI_MODEL
    res, api = run({MODEL: (GEMINI_MODEL, head)}, [(MODEL, "modified")])
    assert res.state == "failure" and res.description == gate.DESC_WAITING
    assert gate.DEPLOY_FILES_HEADLINE in res.body and "`service/summariser/model.yaml`" in res.body


@pytest.mark.parametrize("path", ["service/summariser/handler.py", "infra/service/main.tf", "infra/scripts/smoke.py"])
def test_deploy_only_change_needs_a_person_and_the_label_signs_it(path):
    res, api = run({}, [(path, "modified")], tpl=REAL_TPL)
    assert res.state == "failure" and res.description == gate.DESC_WAITING
    assert "**Service or infrastructure files changed. A person signs this off before they deploy.**" in res.body
    assert "`%s`" % path in res.body and "No AI tools changed" not in res.body
    summary = gate.summary_markdown(res, "opened")
    assert "Service or infrastructure files changed: `%s`" % path in summary
    assert "Nothing the gate guards changed." not in summary
    api.labels.append(gate.LABEL)
    res2, _ = run(None, [(path, "modified")], tpl=REAL_TPL, action="labeled", sender="alice", api=api)
    assert res2.state == "success" and res2.description == gate.DESC_SIGNED % "alice"


def test_deploy_headline_is_not_added_when_ai_use_changed():
    res, _ = run({MODEL: (GEMINI_MODEL, OPENAI_MODEL)}, [(MODEL, "modified")], tpl=REAL_TPL)
    assert res.description == gate.DESC_UNREGISTERED and gate.DEPLOY_FILES_HEADLINE not in res.body


def test_docs_only_change_is_still_green():
    res, _ = run({}, [("README.md", "modified")], tpl=REAL_TPL)
    assert res.state == "success" and res.description == gate.DESC_NOTHING


def test_new_model_yaml_is_added_usage():
    res, _ = run({MODEL: (None, GEMINI_MODEL)}, [(MODEL, "added")])
    assert res.description == gate.DESC_WAITING and "(added)" in res.body


def test_removed_model_yaml_needs_sign_off():
    res, _ = run({MODEL: (GEMINI_MODEL, None)}, [(MODEL, "removed")])
    assert res.description == gate.DESC_WAITING
    assert "AI model config removed: `service/summariser/model.yaml`" in res.body


def test_broken_model_yaml_is_red_and_cannot_be_signed():
    res, api = run({MODEL: (GEMINI_MODEL, "vendor: [")}, [(MODEL, "modified")])
    assert res.description == gate.DESC_SERVICE_CONFIG and "does not parse" in res.body
    api.labels.append(gate.LABEL)
    res2, _ = run(None, [(MODEL, "modified")], action="labeled", sender="alice", api=api)
    assert not res2.signed


def test_vendor_only_config_matches_by_vendor_with_a_note():
    head = "vendor: Google\nproduct: google.gemini-api\nmodel: gemini-flash\n"
    res, _ = run({MODEL: (None, head)}, [(MODEL, "added")])
    assert res.description == gate.DESC_WAITING
    assert "Matched by vendor only" in res.body


def test_register_text_in_model_yaml_is_made_plain():
    head = GEMINI_MODEL.replace("model: gemini-flash", "model: \"@everyone `x`\"")
    res, _ = run({MODEL: (GEMINI_MODEL, head)}, [(MODEL, "modified")])
    assert "@everyone" not in res.body and "@ everyone" in res.body


def test_a_template_without_the_service_placeholders_gets_fallback_lines(tmp_path):
    # tests/fixtures/templates/gate-comment.md predates the service checks
    with open(os.path.join(ROOT, "tests", "fixtures", "templates", "gate-comment.md"), encoding="utf-8") as f:
        (tmp_path / "gate-comment.md").write_text(f.read(), encoding="utf-8")
    res, _ = run({MODEL: (GEMINI_MODEL, OPENAI_MODEL)}, [(MODEL, "modified")], tpl=str(tmp_path))
    assert "Not in the register: `openai.api.platform`" in res.body
    res2, _ = run({MODEL: (GEMINI_MODEL, "vendor: [")}, [(MODEL, "modified")], tpl=str(tmp_path))
    assert "Service AI config problem: service/summariser/model.yaml" in res2.body


# ---- Kubernetes --------------------------------------------------------------------------------

DEPLOY = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: summariser
spec:
  template:
    metadata:
      annotations:
        checkable.ai/vendor: Google
        checkable.ai/plan: google.gemini-api.paid
        checkable.ai/model: gemini-flash
    spec:
      containers:
        - name: app
          image: example/summariser:1
---
apiVersion: v1
kind: Service
metadata:
  name: summariser
spec:
  ports: [{port: 80}]
"""
ENV_DEPLOY = """\
apiVersion: apps/v1
kind: Deployment
metadata: {name: summariser}
spec:
  template:
    spec:
      containers:
        - name: app
          env:
            - {name: CHECKABLE_AI_VENDOR, value: OpenAI}
            - {name: CHECKABLE_AI_PLAN, value: openai.api.platform}
            - {name: CHECKABLE_AI_MODEL, value: gpt-mini}
"""
CONFIGMAP = """\
apiVersion: v1
kind: ConfigMap
metadata: {name: summariser-model}
data:
  CHECKABLE_AI_VENDOR: Google
  CHECKABLE_AI_PLAN: google.gemini-api.paid
  CHECKABLE_AI_MODEL: gemini-flash
"""


def test_k8s_annotations_are_one_usage_per_resource():
    u = services.k8s_file_usages("k8s/summariser.yaml", DEPLOY)
    assert list(u) == ["k8s/summariser.yaml Deployment/summariser"]
    assert u["k8s/summariser.yaml Deployment/summariser"]["plan"] == "google.gemini-api.paid"


def test_k8s_env_and_configmap_conventions():
    assert services.k8s_file_usages("k8s/a.yaml", ENV_DEPLOY)["k8s/a.yaml Deployment/summariser"]["vendor"] == "OpenAI"
    assert services.k8s_file_usages("k8s/c.yaml", CONFIGMAP)["k8s/c.yaml ConfigMap/summariser-model"]["model"] == "gemini-flash"


def test_k8s_switch_to_an_unregistered_plan_is_red():
    path = "k8s/summariser/deployment.yaml"
    res, _ = run({path: (DEPLOY, ENV_DEPLOY)}, [(path, "modified")])
    assert res.description == gate.DESC_UNREGISTERED and SERVICE_TIER in res.body
    assert "k8s/summariser/deployment.yaml Deployment/summariser" in res.body


def test_k8s_change_without_ai_use_is_green():
    path = "k8s/summariser/service.yaml"
    plain = "apiVersion: v1\nkind: Service\nmetadata: {name: s}\nspec: {ports: [{port: 80}]}\n"
    res, _ = run({path: (plain, plain.replace("80", "8080"))}, [(path, "modified")])
    assert res.description == gate.DESC_NOTHING


def test_k8s_unchanged_ai_use_with_other_edits_is_green():
    path = "k8s/summariser.yaml"
    res, _ = run({path: (DEPLOY, DEPLOY.replace("summariser:1", "summariser:2"))}, [(path, "modified")])
    assert res.description == gate.DESC_NOTHING


# ---- the sticky comment and the job summary -------------------------------------------------

def test_sticky_from_the_org_app_is_found_not_duplicated(monkeypatch):
    monkeypatch.setenv(gate.BOT_LOGINS_ENV, "checkable-ai[bot]")
    api = FakeAPI(base_register=REGISTER_TEXT, head_register=REGISTER_TEXT, files=[(MODEL, "modified")],
                  file_map={MODEL: (GEMINI_MODEL, OPENAI_MODEL)}, bot_login="checkable-ai[bot]")
    run(None, None, api=api)
    run(None, None, api=api, action="synchronize")
    assert len(api.comments) == 1 and len(api.created) == 1


def test_sticky_from_another_bot_is_ignored(monkeypatch):
    monkeypatch.delenv(gate.BOT_LOGINS_ENV, raising=False)
    assert gate.bot_logins({}) == {"github-actions[bot]"}
    assert gate.bot_logins({gate.BOT_LOGINS_ENV: "checkable-ai[bot], someone"}) == {"github-actions[bot]", "checkable-ai[bot]"}
    fake = {"id": 1, "body": gate.MARKER_PREFIX + " -->", "user": {"login": "other[bot]"}}
    assert gate.find_sticky([fake], {"github-actions[bot]"}) is None


def test_gate_summary_lists_each_change():
    files = [(MODEL, "modified"), ("ai-vendor-register.yaml", "modified")]
    res, _ = run({MODEL: (GEMINI_MODEL, OPENAI_MODEL)}, files, head_register=register_with(OPENAI_TOOL))
    md = gate.summary_markdown(res, "opened")
    assert md.startswith("## Checkable gate, pull request #12")
    assert "| added | OpenAI API | openai.api.platform | register entry | 1 |" in md
    assert "| changed | service/summariser/model.yaml | openai.api.platform | openai-api | 1 |" in md
    assert "`checkable/sign-off`" in md


def test_gate_summary_when_nothing_changed():
    res, _ = run({}, [("README.md", "modified")])
    assert "Nothing the gate guards changed." in gate.summary_markdown(res, "opened")


# ---- the real files: the demo switch in docs/demo-script.md ---------------------------------
# These tests check shape only, never which vendor the real model.yaml names, so the demo's own switch
# pull request (Gemini API to OpenAI API) keeps the required `tests` check green at every step.
# Whether the register lists the plan is the gate's job, not a unit test's.

def test_real_model_yaml_is_well_formed_and_its_plan_is_in_the_catalogue():
    with open(os.path.join(ROOT, MODEL), encoding="utf-8") as f:
        usage = services.model_file_usages(MODEL, f.read())[MODEL]
    assert usage["vendor"] and usage["plan"] and usage["model"] and usage["register_tool"]
    snap = F.load_feed("", snapshot_path=os.path.join(ROOT, "feed-snapshot", "changes.json"))
    assert usage["plan"] in {p["id"] for p in snap.plans}


def test_demo_switch_against_the_real_snapshot_shows_open_changes():
    snap = F.load_feed("", snapshot_path=os.path.join(ROOT, "feed-snapshot", "changes.json"))
    base = GEMINI_MODEL  # the starting state in docs/demo-script.md
    # the register as first published, frozen, so this test holds before and after the demo pull requests
    with open(os.path.join(ROOT, "tests", "fixtures", "register-first-run.yaml"), encoding="utf-8") as f:
        reg = f.read()
    head = OPENAI_MODEL.replace("register_tool: gemini-api-paid", "register_tool: openai-api")
    api = FakeAPI(base_register=reg, head_register=reg, files=[(MODEL, "modified")], file_map={MODEL: (base, head)})
    res = gate.run_pr(api, snap, pr_number=5, action="opened", template_dir=REAL_TPL)
    assert res.description == gate.DESC_UNREGISTERED
    assert SERVICE_TIER in res.body and "Reaches you" in res.body
    head_reg = reg.replace("vendor_changes: []", OPENAI_TOOL + "vendor_changes: []")
    api2 = FakeAPI(base_register=reg, head_register=head_reg,
                   files=[(MODEL, "modified"), ("ai-vendor-register.yaml", "modified")], file_map={MODEL: (base, head)})
    res2 = gate.run_pr(api2, snap, pr_number=5, action="opened", template_dir=REAL_TPL)
    assert res2.description == gate.DESC_WAITING and "Register entry: `OpenAI API (openai-api)`" in res2.body


def test_blocked_comment_says_so_instead_of_waiting():
    res, _ = run({MODEL: (GEMINI_MODEL, OPENAI_MODEL)}, [(MODEL, "modified")], tpl=REAL_TPL)
    assert "**Sign-off is blocked.**" in res.body and "Waiting for a person to sign off" not in res.body
    res2, _ = run({MODEL: (GEMINI_MODEL, OPENAI_MODEL)}, [(MODEL, "modified"), ("ai-vendor-register.yaml", "modified")],
                  head_register=register_with(OPENAI_TOOL), tpl=REAL_TPL)
    assert "Sign-off is blocked" not in res2.body and "Waiting for a person to sign off" in res2.body
