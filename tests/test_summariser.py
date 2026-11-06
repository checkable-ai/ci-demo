"""The dummy summariser service: GET /health and POST /summarise, configured from model.yaml, no AI call."""
import base64
import json
import os

import pytest

from service.summariser import handler as H
from tests.helpers import ROOT

CFG = {"service": "summariser", "register_tool": "gemini-api-paid", "vendor": "Google",
       "product": "google.gemini-api", "plan": "google.gemini-api.paid", "model": "gemini-flash"}


def http(method, path, body=None, b64=False):
    ev = {"version": "2.0", "rawPath": path, "requestContext": {"http": {"method": method, "path": path}}}
    if body is not None:
        raw = body if isinstance(body, str) else json.dumps(body)
        ev["body"] = base64.b64encode(raw.encode()).decode() if b64 else raw
        ev["isBase64Encoded"] = b64
    return ev


def call(ev, cfg=CFG):
    r = H.handler(ev, None, config=cfg)
    return r["statusCode"], json.loads(r["body"])


def test_health_reports_the_configured_model():
    status, body = call(http("GET", "/health"))
    assert status == 200 and body["status"] == "ok" and body["service"] == "summariser"
    assert body["model"]["plan"] == "google.gemini-api.paid" and body["model"]["vendor"] == "Google"


def test_summarise_returns_a_dummy_summary_and_the_vendor_plan():
    text = "The partners agreed the new fee schedule. Next, the team reviews the client list."
    status, body = call(http("POST", "/summarise", {"text": text}))
    assert status == 200 and body["dummy"] is True
    assert body["summary"] == "The partners agreed the new fee schedule."
    assert body["model"] == {k: CFG[k] for k in H.CONFIG_KEYS}
    assert "No AI vendor was called" in body["note"]


def test_long_first_sentence_is_cut():
    status, body = call(http("POST", "/summarise", {"text": " ".join(["word"] * 100)}))
    assert status == 200 and body["summary"].endswith(" ...") and len(body["summary"].split()) == H.SUMMARY_WORDS + 1


def test_base64_body_and_trailing_slash():
    status, body = call(http("POST", "/summarise/", {"text": "One line."}, b64=True))
    assert status == 200 and body["summary"] == "One line."


@pytest.mark.parametrize("ev,code", [
    (http("POST", "/health"), 405),
    (http("GET", "/summarise"), 405),
    (http("GET", "/nope"), 404),
    (http("POST", "/summarise", "not json"), 400),
    (http("POST", "/summarise", {"text": "  "}), 400),
    (http("POST", "/summarise", {"text": 5}), 400),
    (http("POST", "/summarise", ["text"]), 400),
    (http("POST", "/summarise", {"text": "x" * (H.MAX_TEXT + 1)}), 413),
])
def test_bad_requests(ev, code):
    assert call(ev)[0] == code


def test_rest_api_v1_event_shape_also_works():
    status, _ = call({"httpMethod": "GET", "path": "/health"})
    assert status == 200


# Shape only for the real model.yaml, so a pull request that switches its vendor plan keeps `tests` green.

def test_real_model_yaml_loads():
    cfg = H.load_model_config()
    assert cfg["vendor"] and cfg["plan"] and cfg["model"] and cfg["register_tool"]


def test_handler_reads_model_yaml_by_default():
    r = H.handler(http("GET", "/health"))
    assert r["statusCode"] == 200 and json.loads(r["body"])["model"]["plan"] == H.load_model_config()["plan"]


def test_model_file_env_override_and_broken_config(tmp_path, monkeypatch):
    p = tmp_path / "model.yaml"
    p.write_text("vendor: OpenAI\nplan: openai.api.platform  # switched\nmodel: 'gpt-mini'\n", encoding="utf-8")
    monkeypatch.setenv("SUMMARISER_MODEL_FILE", str(p))
    body = json.loads(H.handler(http("GET", "/health"))["body"])
    assert body["model"]["plan"] == "openai.api.platform" and body["model"]["model"] == "gpt-mini"
    p.write_text("vendor: OpenAI\n", encoding="utf-8")
    r = H.handler(http("GET", "/health"))
    assert r["statusCode"] == 500 and "no plan" in json.loads(r["body"])["detail"]


def test_parser_rejects_nested_yaml():
    with pytest.raises(H.ConfigError):
        H.parse_model_config("vendor: Google\nplan:\n  id: x\nmodel: m\n")


def test_handler_is_standard_library_only():
    with open(os.path.join(ROOT, "service", "summariser", "handler.py"), encoding="utf-8") as f:
        src = f.read()
    imports = {line.split()[1].split(".")[0] for line in src.splitlines() if line.startswith(("import ", "from "))}
    assert imports <= {"base64", "json", "os", "re"}
