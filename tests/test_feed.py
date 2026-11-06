import copy
import json

import pytest

from scripts.checkable import feed as F
from tests.helpers import demo_feed


def write(tmp_path, data):
    p = tmp_path / "changes.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_snapshot_loads_when_url_empty(tmp_path):
    f = F.load_feed("", snapshot_path=write(tmp_path, demo_feed()))
    assert f.source_label == F.SNAPSHOT_LABEL
    assert len(f.changes) == 5 and len(f.plans) == 7


def test_none_url_uses_snapshot(tmp_path):
    f = F.load_feed(None, snapshot_path=write(tmp_path, demo_feed()))
    assert f.version == "2026-11-06.1"


def test_unknown_major_refused(tmp_path):
    d = demo_feed()
    d["schema"] = "urn:checkable:feed:demo-changes:2.0.0"
    with pytest.raises(F.FeedError):
        F.load_feed("", snapshot_path=write(tmp_path, d))


def test_any_1x_accepted(tmp_path):
    d = demo_feed()
    d["schema"] = "urn:checkable:feed:demo-changes:1.4.2"
    assert F.load_feed("", snapshot_path=write(tmp_path, d))


def test_unknown_schema_urn_refused(tmp_path):
    d = demo_feed()
    d["schema"] = "urn:other:feed:1.0.0"
    with pytest.raises(F.FeedError):
        F.load_feed("", snapshot_path=write(tmp_path, d))


@pytest.mark.parametrize("url", [
    "https://example.com/feed/demo/changes.json",
    "https://checkableai.com.evil.test/feed/demo/changes.json",
    "https://www.checkableai.com/feed/demo/changes.json",
    "http://checkableai.com/feed/demo/changes.json",
    "https://user:pw" + chr(64) + "checkableai.com/feed/demo/changes.json",
])
def test_feed_url_host_other_than_checkableai_refused(url):
    called = []
    with pytest.raises(F.FeedError):
        F.load_feed(url, fetch=lambda u: called.append(u))
    assert not called


def test_feed_url_fetched(tmp_path):
    seen = []

    def fetch(u):
        seen.append(u)
        return json.dumps(demo_feed())

    f = F.load_feed("https://checkableai.com/feed/demo/changes.json", fetch=fetch)
    assert seen == ["https://checkableai.com/feed/demo/changes.json"]
    assert f.source_label == "the Checkable feed at https://checkableai.com/feed/demo/changes.json"


def test_missing_required_key(tmp_path):
    d = demo_feed()
    del d["changes"][0]["action"]
    with pytest.raises(F.FeedError):
        F.load_feed("", snapshot_path=write(tmp_path, d))


def test_bad_status_and_version(tmp_path):
    d = demo_feed()
    d["changes"][0]["applicability"][0]["status"] = "maybe"
    with pytest.raises(F.FeedError):
        F.load_feed("", snapshot_path=write(tmp_path, d))
    d = demo_feed()
    d["changes"][0]["version"] = 0
    with pytest.raises(F.FeedError):
        F.load_feed("", snapshot_path=write(tmp_path, d))


def test_missing_snapshot_and_bad_json(tmp_path):
    with pytest.raises(F.FeedError):
        F.load_feed("", snapshot_path=str(tmp_path / "nope.json"))
    p = tmp_path / "x.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(F.FeedError):
        F.load_feed("", snapshot_path=str(p))


def test_fetch_failure_propagates():
    def boom(u):
        raise F.FeedError("feed fetch returned HTTP 404")

    with pytest.raises(F.FeedError):
        F.load_feed("https://checkableai.com/x.json", fetch=boom)
