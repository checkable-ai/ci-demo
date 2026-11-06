"""infra/scripts: plan counts and the sticky plan comment, and the smoke test run against the real handler."""
import importlib.util
import io
import json
import os
import urllib.error

from helpers import ROOT


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


plan_report = _load("plan_report", "infra/scripts/plan_report.py")
smoke = _load("smoke", "infra/scripts/smoke.py")
handler = _load("summariser_handler_t", "service/summariser/handler.py")
MODEL_FILE = os.path.join(ROOT, "service", "summariser", "model.yaml")


def rc(*actions):
    return {"change": {"actions": list(actions)}}


def test_counts_match_terraform_wording():
    plan = {"resource_changes": [rc("create"), rc("create"), rc("update"), rc("delete", "create"),
                                 rc("create", "delete"), rc("delete"), rc("no-op"), rc("read")]}
    c = plan_report.counts(plan)
    assert c == {"add": 4, "change": 1, "destroy": 3}
    assert plan_report.counts_line(c) == "4 to add, 1 to change, 3 to destroy"


def test_body_has_marker_and_truncates():
    text = plan_report.body("Plan", "x" * (plan_report.MAX_PLAN_CHARS + 10), {"add": 1, "change": 0, "destroy": 0})
    assert text.startswith(plan_report.MARKER + "\n")
    assert "1 to add" in text and "longer than" in text
    failed = plan_report.body("Plan", "Error: boom", failed=True)
    assert "Plan failed" in failed and "Error: boom" in failed


class FakeComments:
    def __init__(self, comments):
        self.comments = comments
        self.updated, self.created = [], []

    def list_comments(self, number):
        return self.comments

    def update_comment(self, cid, body):
        self.updated.append(cid)

    def create_comment(self, number, body):
        self.created.append(number)


def test_upsert_updates_own_comment_only():
    bots = {"github-actions[bot]"}
    api = FakeComments([{"id": 1, "user": {"login": "someone"}, "body": plan_report.MARKER},
                        {"id": 2, "user": {"login": "github-actions[bot]"}, "body": plan_report.MARKER + "\nold"}])
    assert plan_report.upsert_comment(api, 5, "new", bots) == "updated" and api.updated == [2]
    api = FakeComments([{"id": 1, "user": {"login": "someone"}, "body": plan_report.MARKER}])
    assert plan_report.upsert_comment(api, 5, "new", bots) == "created" and api.created == [5]


class _Resp(io.BytesIO):
    def __init__(self, status, body):
        super().__init__(body.encode("utf-8"))
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def lambda_opener(cfg, fail_first=0):
    """Routes smoke-test requests to the real handler, as a function URL would (payload format 2.0)."""
    calls = {"n": 0}

    def opener(req, timeout=None):
        calls["n"] += 1
        if calls["n"] <= fail_first:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b"{}"))
        path = "/" + req.full_url.split("/", 3)[3]
        event = {"rawPath": path, "requestContext": {"http": {"method": req.get_method()}},
                 "body": req.data.decode("utf-8") if req.data else None}
        out = handler.handler(event, config=cfg)
        return _Resp(out["statusCode"], out["body"])
    return opener


def test_smoke_passes_against_handler_with_model_from_yaml():
    expected = smoke.load_expected(MODEL_FILE)
    assert expected["model"] and expected["plan"]
    results = smoke.run("https://abc.lambda-url.ap-southeast-2.on.aws/", expected,
                        opener=lambda_opener(expected, fail_first=2), sleep=lambda s: None)
    assert [p for _, _, p in results] == [[], []]
    text, ok = smoke.summary_markdown("https://x/", expected, results)
    assert ok and "| `GET /health` | 200 | pass |" in text


def test_smoke_fails_when_deployed_model_differs():
    expected = smoke.load_expected(MODEL_FILE)
    deployed = dict(expected, model="some-other-model")
    results = smoke.run("https://x.on.aws", expected, opener=lambda_opener(deployed), sleep=lambda s: None)
    assert all(any("model.model" in p for p in probs) for _, _, probs in results)


def test_smoke_reports_http_failure_after_retries():
    def down(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b"no"))
    expected = smoke.load_expected(MODEL_FILE)
    results = smoke.run("https://x.on.aws", expected, opener=down, sleep=lambda s: None)
    assert results[0][1] == 403 and results[0][2]
    assert json.loads(json.dumps(smoke.summary_markdown("u", expected, results)[1])) is False


def test_plan_report_bot_logins_match_gate():
    from scripts.checkable.gate import bot_logins
    env = {"CHECKABLE_BOT_LOGINS": "checkable-ai[bot], not-a-bot"}
    assert plan_report.bot_logins(env) == bot_logins(env)
