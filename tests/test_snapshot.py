"""The real snapshot copied from the exporter: it loads, validates against its schema, and gives the section 2 first run."""
import json
import os

import pytest

from scripts.checkable import feed as F
from scripts.checkable import match, nightly
from scripts.checkable.register import parse_register
from tests.helpers import ROOT, FakeAPI, template_dir
from tests.test_dedup import FakeOps

SNAP = os.path.join(ROOT, "feed-snapshot", "changes.json")
SCHEMA = os.path.join(ROOT, "feed-snapshot", "changes.schema.json")
# A frozen copy of the register as first published, so adding a tool in a PR does not break this test.
REGISTER = os.path.join(ROOT, "tests", "fixtures", "register-first-run.yaml")

pytestmark = pytest.mark.skipif(not os.path.exists(SNAP), reason="snapshot not copied in yet")


def load():
    return F.load_feed("", snapshot_path=SNAP)


def test_snapshot_validates_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    if not os.path.exists(SCHEMA):
        pytest.skip("schema not copied in yet")
    with open(SCHEMA, encoding="utf-8") as f:
        schema = json.load(f)
    with open(SNAP, encoding="utf-8") as f:
        jsonschema.Draft202012Validator(schema).validate(json.load(f))


def test_real_register_first_run_is_one_pr_per_open_change():
    feed = load()
    with open(REGISTER, encoding="utf-8") as f:
        reg = parse_register(f.read())
    r = match.reaching_changes(feed.changes, reg["tools"])
    assert [c["change_id"] for c, _ in r] == [
        "chg_github-2026-10-26-gpt-6-1-terra-copilot",
        "chg_google-2026-10-26-gemini-api-storage-default",
    ]
    api = FakeAPI(base_register=open(REGISTER, encoding="utf-8").read(),
                  head_register=open(REGISTER, encoding="utf-8").read(), files=[("changes/x.md", "added")])
    ops = FakeOps()
    alerts, _ = nightly.run(feed, reg, ops, api, repo="checkable-ai/ci-demo", template_dir=template_dir())
    assert len(ops.opened) == 2 and len(alerts) == 2
    again, lines = nightly.run(feed, reg, ops, api, repo="checkable-ai/ci-demo", template_dir=template_dir())
    assert again == [] and len(ops.opened) == 2
