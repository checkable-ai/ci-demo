"""Smoke test of the deployed summariser. Standard library only.

    python infra/scripts/smoke.py <function URL> [service/summariser/model.yaml]

GET /health and POST /summarise on the function URL. Both must answer 200 with JSON whose model matches
model.yaml (read with the service's own parser), and /summarise must return a non-empty dummy summary. A new
function URL can answer 403 for a short while after it is made, so each call is retried for about a minute.
Writes a results table to the job summary and GITHUB_OUTPUT (model, vendor, plan, result). Exits 1 on any failure.
"""
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_MODEL_FILE = os.path.join(ROOT, "service", "summariser", "model.yaml")
SAMPLE = ("Risky Business Solutions met the client on Tuesday to review the quarterly cash flow. "
          "The client agreed to move two invoices to the next quarter.")
ATTEMPTS = 12
WAIT_SECONDS = 5


def load_expected(path=DEFAULT_MODEL_FILE):
    spec = importlib.util.spec_from_file_location(
        "summariser_handler", os.path.join(os.path.dirname(os.path.abspath(path)), "handler.py"))
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    return handler.load_model_config(path)


def call(url, method="GET", payload=None, opener=urllib.request.urlopen):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "content-type": "application/json", "user-agent": "Checkable AI CI demo smoke test"})
    try:
        with opener(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def with_retry(fn, attempts=ATTEMPTS, wait=WAIT_SECONDS, sleep=time.sleep):
    status, text = None, ""
    for i in range(attempts):
        try:
            status, text = fn()
        except (urllib.error.URLError, OSError) as e:
            status, text = None, str(e)
        if status == 200:
            break
        if i < attempts - 1:
            sleep(wait)
    return status, text


def check_model(got, expected):
    problems = []
    got = got if isinstance(got, dict) else {}
    for key in ("vendor", "plan", "model"):
        if got.get(key) != expected.get(key):
            problems.append("model.%s is %r, model.yaml says %r" % (key, got.get(key), expected.get(key)))
    return problems


def check_health(status, text, expected):
    if status != 200:
        return ["GET /health answered %s: %s" % (status, text[:200])]
    try:
        doc = json.loads(text)
    except ValueError:
        return ["GET /health did not return JSON"]
    problems = [] if doc.get("status") == "ok" else ["GET /health status is %r" % doc.get("status")]
    return problems + check_model(doc.get("model"), expected)


def check_summarise(status, text, expected):
    if status != 200:
        return ["POST /summarise answered %s: %s" % (status, text[:200])]
    try:
        doc = json.loads(text)
    except ValueError:
        return ["POST /summarise did not return JSON"]
    problems = []
    if not isinstance(doc.get("summary"), str) or not doc["summary"].strip():
        problems.append("POST /summarise returned no summary")
    if doc.get("dummy") is not True:
        problems.append("POST /summarise is not marked dummy")
    return problems + check_model(doc.get("model"), expected)


def run(base_url, expected, opener=urllib.request.urlopen, sleep=time.sleep):
    base = base_url.rstrip("/")
    h = with_retry(lambda: call(base + "/health", opener=opener), sleep=sleep)
    s = with_retry(lambda: call(base + "/summarise", "POST", {"text": SAMPLE}, opener=opener), sleep=sleep)
    return [
        ("GET /health", h[0], check_health(h[0], h[1], expected)),
        ("POST /summarise", s[0], check_summarise(s[0], s[1], expected)),
    ]


def summary_markdown(url, expected, results):
    ok = all(not p for _, _, p in results)
    lines = ["## Smoke test", "",
             "Model from `service/summariser/model.yaml`: **%s** (%s, plan `%s`)."
             % (expected.get("model"), expected.get("vendor"), expected.get("plan")), "",
             "| Call | HTTP | Result |", "| --- | --- | --- |"]
    for name, status, problems in results:
        lines.append("| `%s` | %s | %s |" % (name, status, "pass" if not problems else "; ".join(problems)))
    lines += ["", "URL: %s" % url, "", "**%s**" % ("Passed." if ok else "Failed.")]
    return "\n".join(lines) + "\n", ok


def _append(env_name, text):
    path = os.environ.get(env_name)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or not argv[0].startswith("https://"):
        print("::error::usage: smoke.py <https function URL> [model.yaml]")
        return 2
    url = argv[0]
    expected = load_expected(argv[1] if len(argv) > 1 else DEFAULT_MODEL_FILE)
    results = run(url, expected)
    text, ok = summary_markdown(url, expected, results)
    print(text)
    _append("GITHUB_STEP_SUMMARY", text)
    _append("GITHUB_OUTPUT", "model=%s\nvendor=%s\nplan=%s\nresult=%s\n"
            % (expected.get("model"), expected.get("vendor"), expected.get("plan"), "pass" if ok else "fail"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
