"""Short checks over the feed snapshot: quotes need an allowed licence, paraphrase needs a reading, URLs are safe.

Written for this demo. Runs over feed-snapshot/changes.json when it exists, and always over the
built-in sample feed so a planted bad quote is shown to fail.
"""
import copy
import json
import os
import re

import pytest

from tests.helpers import ROOT, demo_feed

AT = chr(64)
SNAPSHOT = os.path.join(ROOT, "feed-snapshot", "changes.json")
QUOTE_OK = {"confirmed_reusable", "public_domain"}
BAD_WORDS = [chr(0x2014), chr(0x2013), "coming soon", "on the way", "planned for"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def problems(feed):
    out = []
    for ci, c in enumerate(feed["changes"]):
        for ei, e in enumerate(c["evidence"]):
            where = "changes[%d].evidence[%d]" % (ci, ei)
            lic = e["licence"]
            if e["quote"] is not None:  # L1
                if lic["status"] not in QUOTE_OK:
                    out.append(where + ": quote without an allowed licence")
                if not lic.get("name") or not lic.get("read_on"):
                    out.append(where + ": quote licence lacks a name or read date")
                if lic["status"] == "confirmed_reusable" and not lic.get("attribution"):
                    out.append(where + ": reusable quote without attribution")
                if len(e["quote"]) > 320:
                    out.append(where + ": quote too long")
            if e["quote_policy"] == "link_and_paraphrase":  # L3
                if e["quote"] is not None or not str(e.get("our_reading") or "").startswith("Checkable AI's reading of "):
                    out.append(where + ": paraphrase item needs null quote and a reading")
    text = json.dumps(feed, ensure_ascii=False)  # L6
    for u in re.findall(r'"(https?://[^"]+)"', text):
        if not u.startswith("https://"):
            out.append("non-https URL " + u)
    if EMAIL.search(text):
        out.append("email address in feed")
    low = text.lower()
    for w in BAD_WORDS:
        if w in low:
            out.append("banned text: " + w)
    return out


def test_sample_feed_is_clean():
    assert problems(demo_feed()) == []


def test_planted_quote_without_licence_fails():
    d = demo_feed()
    ev = d["changes"][2]["evidence"][0]  # a no_reuse_licence item
    ev["quote"] = "A quote we may not carry."
    assert any("without an allowed licence" in p for p in problems(d))


def test_planted_email_and_dash_fail():
    d = demo_feed()
    d["changes"][0]["summary"] = "Write to someone" + AT + "example.test " + chr(0x2014) + " now"
    p = problems(d)
    assert any("email" in x for x in p) and any("banned text" in x for x in p)


def test_planted_paraphrase_without_reading_fails():
    d = demo_feed()
    d["changes"][2]["evidence"][0]["our_reading"] = "Some other start"
    assert any("needs null quote" in p for p in problems(d))


@pytest.mark.skipif(not os.path.exists(SNAPSHOT), reason="feed-snapshot/changes.json not copied in yet")
def test_snapshot_is_clean():
    with open(SNAPSHOT, encoding="utf-8") as f:
        assert problems(json.load(f)) == []
