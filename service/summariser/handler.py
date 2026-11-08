"""Summariser service of Risky Business Solutions, a fictional sample company. AWS Lambda, Python 3.12.

A dummy internal service for the Checkable AI CI demo. It answers two routes behind an API Gateway HTTP API
(payload format 2.0) or a Lambda function URL:

    GET  /health     {"status": "ok", ...configured model}
    POST /summarise  {"text": "..."} -> a dummy summary plus the configured model and vendor plan

It never calls an AI vendor. The vendor, plan and model come from model.yaml beside this file, the same file the
Checkable gate reads, so a pull request that switches the vendor plan is visible to the gate before it ships.
Standard library only, so the deployment package is this folder and nothing else.
"""
import base64
import json
import os
import re

MODEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.yaml")
CONFIG_KEYS = ("service", "register_tool", "vendor", "product", "plan", "model")
MAX_TEXT = 20000
SUMMARY_WORDS = 40


class ConfigError(Exception):
    pass


def _scalar(raw):
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    v = re.sub(r"\s+#.*$", "", v).strip()
    return None if v in ("", "null", "~") else v


def parse_model_config(text):
    """model.yaml is flat `key: value` lines. Comments and blank lines are skipped. Unknown keys are kept."""
    out = {}
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if line[:1].isspace() or ":" not in s:
            raise ConfigError("model.yaml line %d is not a flat `key: value` line" % n)
        key, _, value = s.partition(":")
        out[key.strip()] = _scalar(value)
    for key in ("vendor", "plan", "model"):
        if not out.get(key):
            raise ConfigError("model.yaml has no %s" % key)
    return out


def load_model_config(path=None):
    with open(path or os.environ.get("SUMMARISER_MODEL_FILE") or MODEL_FILE, encoding="utf-8") as f:
        return parse_model_config(f.read())


def dummy_summary(text, words=SUMMARY_WORDS):
    """The first sentence, cut to a word limit. Stands in for the model call."""
    flat = " ".join(text.split())
    first = re.split(r"(?<=[.!?])\s", flat, maxsplit=1)[0]
    parts = first.split()
    return " ".join(parts[:words]) + (" ..." if len(parts) > words else "")


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(body),
    }


def _model_view(cfg):
    return {k: cfg.get(k) for k in CONFIG_KEYS}


def _route(event):
    http = (event.get("requestContext") or {}).get("http") or {}
    method = (http.get("method") or event.get("httpMethod") or "GET").upper()
    path = event.get("rawPath") or event.get("path") or "/"
    return method, "/" + path.strip("/")


def _body(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw) if raw else {}


def handler(event, context=None, config=None):
    """Lambda entry point. `config` is for tests, otherwise model.yaml is read on each call (it is tiny)."""
    event = event or {}
    try:
        cfg = config if config is not None else load_model_config()
    except (OSError, ConfigError) as e:
        return _response(500, {"error": "model configuration unreadable", "detail": str(e)})
    method, path = _route(event)

    if path == "/health":
        if method != "GET":
            return _response(405, {"error": "use GET"})
        return _response(200, {"status": "ok", "service": cfg.get("service") or "summariser", "model": _model_view(cfg)})

    if path == "/summarise":
        if method != "POST":
            return _response(405, {"error": "use POST"})
        try:
            body = _body(event)
        except (ValueError, UnicodeDecodeError):
            return _response(400, {"error": "body must be JSON"})
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str) or not text.strip():
            return _response(400, {"error": "text is required"})
        if len(text) > MAX_TEXT:
            return _response(413, {"error": "text is longer than %d characters" % MAX_TEXT})
        return _response(200, {
            "summary": dummy_summary(text),
            "dummy": True,
            "note": "Demo service. No AI vendor was called.",
            "model": _model_view(cfg),
        })

    return _response(404, {"error": "not found"})
