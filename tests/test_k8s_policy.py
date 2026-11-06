"""The k8s/policy check: Kubernetes AI model use must be in the AI vendor register."""
import os
import re

import pytest
import yaml

from scripts.checkable import k8s_policy as K
from scripts.checkable import services
from scripts.checkable.register import parse_register
from tests.helpers import ROOT, make_feed

FEED = make_feed()
REGISTER_PATH = os.path.join(ROOT, "ai-vendor-register.yaml")
K8S_DIR = os.path.join(ROOT, "k8s")
SERVICE_TIER = "chg_openai-2026-10-21-service-tier-limits"
GEMINI = "chg_google-2026-10-26-gemini-api-storage-default"
OPENAI_TOOL = ("  - {id: openai-api, name: OpenAI API, vendor: OpenAI, product: openai.api, "
               "plan: openai.api.platform, account_type: business, used_by: Summariser service}\n")
OLLAMA_TOOL = ("  - {id: local-llm, name: Local model server, vendor: null, product: null, plan: null, "
               "account_type: internal, used_by: Partners}\n")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def register_file(tmp_path, extra=""):
    text = read(REGISTER_PATH).replace("vendor_changes: []\n", "") + extra + "vendor_changes: []\n"
    parse_register(text)
    return write(tmp_path, "register.yaml", text)


def manifests(tmp_path, name="app.yaml", endpoint="https://generativelanguage.googleapis.com/",
              vendor="Google", product="google.gemini-api", plan="google.gemini-api.paid", model="gemini-flash",
              register_id="gemini-api-paid", image="registry.k8s.io/e2e-test-images/agnhost:2.66.1"):
    """A ConfigMap plus a Deployment that reads it, shaped like k8s/ in the repo."""
    ann = "  annotations:\n    checkable.ai/register-id: %s\n" % register_id if register_id else ""
    data = ['  MODEL_ENDPOINT: "%s"' % endpoint]
    for key, value in (("VENDOR", vendor), ("PRODUCT", product), ("PLAN", plan), ("MODEL", model)):
        if value:
            data.append('  CHECKABLE_AI_%s: "%s"' % (key, value))
    text = """\
apiVersion: v1
kind: ConfigMap
metadata: {name: summariser-model, namespace: summariser}
data:
%s
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: summariser
  namespace: summariser
%sspec:
  template:
    spec:
      containers:
        - name: summariser
          image: %s
          envFrom:
            - configMapRef: {name: summariser-model}
""" % ("\n".join(data), ann, image)
    return write(tmp_path, name, text)


def run(paths, register, feed=FEED):
    rows, warnings, _reg, _n, _f = K.check(paths if isinstance(paths, list) else [paths], register, feed)
    return rows, warnings


def blocked(rows):
    return [r for r in rows if r["fails"]]


def find(rows, kind):
    return [r for r in rows if r["kind"] == kind]


# ---- the passing case ------------------------------------------------------------------------------------------

def test_repo_manifests_pass_and_show_open_changes():
    rows, warnings = run(K8S_DIR, REGISTER_PATH)
    assert not blocked(rows) and not warnings
    ep = find(rows, "Endpoint")[0]
    assert ep["found"] == "generativelanguage.googleapis.com (MODEL_ENDPOINT)"
    assert ep["register"] == "gemini-api-paid" and ep["result"] == "In register"
    assert [c for c, _w in ep["open_changes"]] == [GEMINI]
    decl = find(rows, "Declared model")[0]
    assert decl["register"] == "gemini-api-paid" and decl["status"] == "registered"
    image = find(rows, "Image")[0]
    assert image["status"] == "info" and not image["fails"]


def test_the_config_map_is_read_through_the_deployment_once():
    rows, _ = run(K8S_DIR, REGISTER_PATH)
    assert len(rows) == 3
    assert all(r["where"] == {"Deployment/summariser"} for r in rows)


def test_gate_and_policy_agree_on_the_repo_manifests():
    """The gate reads the ConfigMap keys through services.py and finds the same register entry."""
    usages = services.k8s_file_usages("k8s/10-configmap.yaml", read(os.path.join(K8S_DIR, "10-configmap.yaml")))
    (usage,) = usages.values()
    tool, _note = services.match_register(usage, parse_register(read(REGISTER_PATH))["tools"])
    assert tool["id"] == "gemini-api-paid"


def test_cli_passes_on_the_repo(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("FEED_URL", raising=False)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert K.main(["--heading", "Kubernetes policy, files", "k8s"]) == 0
    out = capsys.readouterr().out
    assert "Passed: 3 findings, 0 blocked." in out
    md = summary.read_text(encoding="utf-8")
    assert md.startswith("## Kubernetes policy, files")
    assert "| In register | Endpoint | `generativelanguage.googleapis.com (MODEL_ENDPOINT)` | Deployment/summariser |" in md
    assert "`%s` (Reaches you)" % GEMINI in md


# ---- the failing cases -----------------------------------------------------------------------------------------

def test_unregistered_endpoint_blocks(tmp_path):
    m = manifests(tmp_path, endpoint="https://api.openai.com/v1", vendor="OpenAI", product="openai.api",
                  plan="openai.api.platform", model="gpt-mini", register_id="openai-api")
    rows, _ = run(m, REGISTER_PATH)
    bad = {(r["kind"], r["found"]): r for r in blocked(rows)}
    assert ("Endpoint", "api.openai.com (MODEL_ENDPOINT)") in bad
    assert "OpenAI entry" in bad[("Endpoint", "api.openai.com (MODEL_ENDPOINT)")]["note"]
    decl = [r for r in blocked(rows) if r["kind"] == "Declared model"][0]
    assert "no entry for `openai.api.platform`" in decl["note"] or "does not have" in decl["note"]


def test_cli_exits_1_and_annotates_an_unregistered_endpoint(monkeypatch, tmp_path, capsys):
    m = manifests(tmp_path, endpoint="https://api.openai.com/v1", vendor="OpenAI", product="openai.api",
                  plan="openai.api.platform", model="gpt-mini", register_id="openai-api")
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("FEED_URL", raising=False)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert K.main(["--register", REGISTER_PATH, m]) == 1
    out = capsys.readouterr().out
    assert "::error::Endpoint api.openai.com (MODEL_ENDPOINT)" in out and out.rstrip().endswith("2 blocked.")
    md = summary.read_text(encoding="utf-8")
    assert "**Blocked: 2 AI uses are not covered by the register.**" in md
    assert "| Not in register | Endpoint | `api.openai.com (MODEL_ENDPOINT)` |" in md


def test_adding_the_register_entry_clears_it_and_shows_the_open_change(tmp_path):
    m = manifests(tmp_path, endpoint="https://api.openai.com/v1", vendor="OpenAI", product="openai.api",
                  plan="openai.api.platform", model="gpt-mini", register_id="openai-api")
    rows, warnings = run(m, register_file(tmp_path, OPENAI_TOOL))
    assert not blocked(rows) and not warnings
    ep = find(rows, "Endpoint")[0]
    assert ep["register"] == "openai-api"
    assert [c for c, w in ep["open_changes"]] == [SERVICE_TIER]
    assert ep["open_changes"][0][1] == "Reaches you"


def test_changing_only_the_endpoint_is_a_mismatch(tmp_path):
    """The declaration still says Gemini, but the endpoint now points at OpenAI, which the register does list."""
    m = manifests(tmp_path, endpoint="https://api.openai.com/v1")
    rows, _ = run(m, register_file(tmp_path, OPENAI_TOOL))
    (bad,) = blocked(rows)
    assert bad["kind"] == "Endpoint" and bad["status"] == "mismatch" and bad["register"] == "gemini-api-paid"
    assert "declares register entry `gemini-api-paid`" in bad["note"]


def test_register_id_that_the_register_does_not_have_blocks(tmp_path):
    m = manifests(tmp_path, vendor=None, product=None, plan=None, model=None, register_id="no-such-tool")
    rows, _ = run(m, REGISTER_PATH)
    (bad,) = blocked(rows)
    assert bad["kind"] == "Declared model" and "no-such-tool" in bad["note"]


def test_unknown_model_endpoint_with_no_declaration_blocks(tmp_path):
    m = manifests(tmp_path, endpoint="http://llm.models.svc.cluster.local:8000/v1", vendor=None, product=None,
                  plan=None, model=None, register_id=None)
    rows, _ = run(m, REGISTER_PATH)
    (bad,) = blocked(rows)
    assert bad["found"] == "llm.models.svc.cluster.local (MODEL_ENDPOINT)" and bad["status"] == "unregistered"


def test_unknown_endpoint_is_covered_by_a_declared_register_entry(tmp_path):
    m = manifests(tmp_path, endpoint="http://llm.models.svc.cluster.local:8000/v1", vendor=None, product=None,
                  plan=None, model=None, register_id="local-llm")
    rows, _ = run(m, register_file(tmp_path, OLLAMA_TOOL))
    assert not blocked(rows)
    assert find(rows, "Endpoint")[0]["register"] == "local-llm"


def test_gateway_host_in_front_of_a_vendor_is_a_warning_not_a_block(tmp_path):
    m = manifests(tmp_path, endpoint="https://gateway.example.test/gemini")
    rows, _ = run(m, REGISTER_PATH)
    assert not blocked(rows)
    assert find(rows, "Endpoint")[0]["status"] == "warning"


@pytest.mark.parametrize("image", ["ollama/ollama:0.5.1", "vllm/vllm-openai:v0.6.0",
                                   "ghcr.io/huggingface/text-generation-inference:2.4",
                                   "nvcr.io/nim/meta/llama-3.1-8b-instruct:1.2"])
def test_model_server_image_needs_a_register_entry(tmp_path, image):
    m = manifests(tmp_path, endpoint="http://localhost:8080", vendor=None, product=None, plan=None, model=None,
                  register_id=None, image=image)
    rows, _ = run(m, REGISTER_PATH)
    assert [r["found"] for r in blocked(rows) if r["kind"] == "Image"] == [image]
    m2 = manifests(tmp_path, name="declared.yaml", endpoint="http://localhost:8080", vendor=None, product=None,
                   plan=None, model=None, register_id="local-llm", image=image)
    rows2, _ = run(m2, register_file(tmp_path, OLLAMA_TOOL))
    assert not blocked(rows2) and find(rows2, "Image")[0]["register"] == "local-llm"


@pytest.mark.parametrize("image", ["python", "python:latest"])
def test_untagged_image_is_a_warning(tmp_path, image):
    rows, _ = run(manifests(tmp_path, image=image), REGISTER_PATH)
    assert not blocked(rows)
    (img,) = find(rows, "Image")
    assert img["status"] == "warning" and "no version tag" in img["note"]


def test_digest_pinned_image_has_no_warning(tmp_path):
    rows, _ = run(manifests(tmp_path, image="python@sha256:" + "a" * 64), REGISTER_PATH)
    assert find(rows, "Image")[0]["status"] == "info"


def test_vendor_host_in_container_args_and_external_name_service(tmp_path):
    text = """\
apiVersion: apps/v1
kind: Deployment
metadata: {name: worker}
spec:
  template:
    spec:
      containers:
        - name: w
          image: python:3.12-slim
          args: ["--base", "https://api.anthropic.com/v1"]
---
apiVersion: v1
kind: Service
metadata: {name: openai-proxy}
spec: {type: ExternalName, externalName: api.openai.com}
"""
    rows, _ = run(write(tmp_path, "x.yaml", text), REGISTER_PATH)
    assert sorted(r["found"].split(" ")[0] for r in blocked(rows)) == ["api.anthropic.com", "api.openai.com"]


def test_non_ai_urls_and_keys_are_ignored(tmp_path):
    text = """\
apiVersion: v1
kind: ConfigMap
metadata: {name: plain}
data:
  DATABASE_URL: postgres://db.example.test/app
  EMAIL_URL: https://mail.example.test
  SERVICE_HOST: example.test
"""
    rows, _ = run(write(tmp_path, "x.yaml", text), REGISTER_PATH)
    assert rows == []


def test_config_map_that_no_workload_reads_is_still_checked(tmp_path):
    text = """\
apiVersion: v1
kind: ConfigMap
metadata: {name: lonely}
data:
  OPENAI_API_BASE: https://api.openai.com/v1
"""
    rows, _ = run(write(tmp_path, "x.yaml", text), REGISTER_PATH)
    assert [(r["kind"], r["where"]) for r in blocked(rows)] == [("Endpoint", {"ConfigMap/lonely"})]


def test_missing_config_map_is_a_warning(tmp_path):
    text = """\
apiVersion: apps/v1
kind: Deployment
metadata: {name: d, namespace: summariser}
spec:
  template:
    spec:
      containers:
        - {name: c, image: "python:3.12", envFrom: [{configMapRef: {name: elsewhere}}]}
"""
    rows, warnings = run(write(tmp_path, "x.yaml", text), REGISTER_PATH)
    assert not blocked(rows) and "`elsewhere`" in warnings[0]


# ---- the live cluster ------------------------------------------------------------------------------------------

LIVE = """\
apiVersion: v1
kind: List
items:
- apiVersion: apps/v1
  kind: Deployment
  metadata:
    name: summariser
    namespace: summariser
    annotations:
      checkable.ai/register-id: gemini-api-paid
      kubectl.kubernetes.io/last-applied-configuration: '{"data":{"MODEL_ENDPOINT":"https://api.openai.com/v1"}}'
    managedFields:
    - manager: kubectl
      fieldsV1: {f:data: {f:MODEL_ENDPOINT: {}}}
  spec:
    template:
      spec:
        containers:
        - name: summariser
          image: registry.k8s.io/e2e-test-images/agnhost:2.66.1
          envFrom: [{configMapRef: {name: summariser-model}}]
  status: {conditions: [{message: "see https://api.openai.com/v1"}]}
- apiVersion: v1
  kind: ConfigMap
  metadata: {name: summariser-model, namespace: summariser}
  data:
    MODEL_ENDPOINT: https://generativelanguage.googleapis.com/
    CHECKABLE_AI_VENDOR: Google
    CHECKABLE_AI_PLAN: google.gemini-api.paid
- apiVersion: v1
  kind: Pod
  metadata:
    name: summariser-6d9f
    namespace: summariser
    ownerReferences: [{kind: ReplicaSet, name: summariser-6d9f}]
  spec:
    containers:
    - {name: summariser, image: "ollama/ollama:0.5.1"}
"""


def test_live_list_is_unpacked_and_noise_is_ignored(tmp_path):
    rows, warnings = run(write(tmp_path, "live.yaml", LIVE), REGISTER_PATH)
    assert not blocked(rows) and not warnings
    assert {r["found"] for r in find(rows, "Endpoint")} == {"generativelanguage.googleapis.com (MODEL_ENDPOINT)"}
    assert [r["found"] for r in find(rows, "Image")] == ["registry.k8s.io/e2e-test-images/agnhost:2.66.1"]


def test_live_pod_with_no_owner_is_checked(tmp_path):
    live = LIVE.replace("ownerReferences: [{kind: ReplicaSet, name: summariser-6d9f}]", "labels: {run: rogue}")
    rows, _ = run(write(tmp_path, "live.yaml", live), REGISTER_PATH)
    (bad,) = blocked(rows)
    assert bad["kind"] == "Image" and bad["found"] == "ollama/ollama:0.5.1" and bad["where"] == {"Pod/summariser-6d9f"}


def test_live_deployment_drifted_to_an_unregistered_endpoint_blocks(tmp_path):
    live = LIVE.replace("https://generativelanguage.googleapis.com/", "https://api.openai.com/v1")
    rows, _ = run(write(tmp_path, "live.yaml", live), REGISTER_PATH)
    assert [r["status"] for r in blocked(rows)] == ["mismatch"]


# ---- the check could not run -----------------------------------------------------------------------------------

def test_bad_yaml_exits_2(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("FEED_URL", raising=False)
    bad = write(tmp_path, "bad.yaml", "a: [unclosed\n")
    assert K.main(["--register", REGISTER_PATH, bad]) == 2
    assert "is not valid YAML" in capsys.readouterr().out


def test_missing_path_and_missing_register_exit_2(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("FEED_URL", raising=False)
    assert K.main(["--register", REGISTER_PATH, str(tmp_path / "nope")]) == 2
    assert K.main(["--register", str(tmp_path / "none.yaml"), K8S_DIR]) == 2
    assert "cannot read the register" in capsys.readouterr().out


def test_missing_feed_exits_2(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)  # no feed-snapshot/ here
    monkeypatch.delenv("FEED_URL", raising=False)
    assert K.main(["--register", REGISTER_PATH, K8S_DIR]) == 2
    assert "cannot read the feed snapshot" in capsys.readouterr().out


def test_empty_directory_passes_with_no_findings(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("FEED_URL", raising=False)
    (tmp_path / "empty").mkdir()
    assert K.main(["--register", REGISTER_PATH, str(tmp_path / "empty")]) == 0
    assert "Passed: 0 findings" in capsys.readouterr().out


# ---- the report is safe to publish ----------------------------------------------------------------------------

def test_report_cells_cannot_break_the_table_or_inject_markdown(tmp_path):
    m = manifests(tmp_path, image="evil`|[x](https://x.test) tag:1")
    rows, _ = run(m, REGISTER_PATH)
    md = K.report_markdown(rows, [], heading="h", register=parse_register(read(REGISTER_PATH)), feed=FEED,
                           n_resources=2, n_files=1)
    (line,) = [ln for ln in md.splitlines() if "evil" in ln and ln.startswith("|")]
    assert line.count("|") == 7  # six cells, so the pipe in the image name did not add one
    assert "`evil/[x](https://x.test) tag:1`" in line  # backtick removed, pipe replaced, still inside one code span


# ---- the workflow ----------------------------------------------------------------------------------------------

def workflow():
    data = yaml.safe_load(read(os.path.join(ROOT, ".github", "workflows", "k8s-policy.yml")))
    data["on"] = data.pop(True, data.get("on"))  # PyYAML reads the bare key `on` as True
    return data


def test_workflow_is_the_required_k8s_policy_check():
    wf = workflow()
    assert set(wf["on"]) == {"pull_request", "workflow_dispatch"}
    assert "paths" not in wf["on"]["pull_request"] and "paths-ignore" not in wf["on"]["pull_request"]
    assert wf["permissions"] == {"contents": "read"}
    (job,) = wf["jobs"].values()
    assert job["name"] == "k8s/policy" and job["runs-on"].startswith("ubuntu-")
    text = read(os.path.join(ROOT, ".github", "workflows", "k8s-policy.yml"))
    assert "secrets." not in text and "pull_request_target" not in text


def test_workflow_pins_actions_and_runs_the_policy_on_files_then_the_live_cluster():
    (job,) = workflow()["jobs"].values()
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]
    kind = [s for s in job["steps"] if s.get("uses", "").startswith("helm/kind-action@")]
    assert len(kind) == 1
    runs = [s.get("run", "") for s in job["steps"]]
    files_at = next(i for i, r in enumerate(runs) if "scripts.checkable.k8s_policy" in r and r.rstrip().endswith(" k8s"))
    apply_at = next(i for i, r in enumerate(runs) if "kubectl apply -f k8s/" in r)
    live_at = next(i for i, r in enumerate(runs) if "scripts.checkable.k8s_policy" in r and "live.yaml" in r)
    assert files_at < job["steps"].index(kind[0]) < apply_at < live_at
    assert "rollout status deployment/summariser" in runs[apply_at]
    assert any("kubectl" in r and "get all,configmaps -o yaml" in r for r in runs)


def test_no_banned_strings_in_the_k8s_files():
    banned = ["Markus" + "-Doc", "Markus " + "Walker", "markus" + "walker", "17898" + "4035", "mwal" + "ker",
              "markusda" + "chroeden"]  # written in parts so this file never holds them
    paths = [os.path.join(K8S_DIR, f) for f in os.listdir(K8S_DIR)]
    paths += [os.path.join(ROOT, ".github", "workflows", "k8s-policy.yml"),
              os.path.join(ROOT, "scripts", "checkable", "k8s_policy.py")]
    for p in paths:
        text = read(p)
        assert not [b for b in banned if b in text], p
