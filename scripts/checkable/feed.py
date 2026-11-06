"""Load the Checkable feed from FEED_URL (checkableai.com only) or the snapshot in the repo."""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

SCHEMA_PREFIX = "urn:checkable:feed:demo-changes:"
SUPPORTED_MAJOR = 1
ALLOWED_HOST = "checkableai.com"
USER_AGENT = "Checkable AI CI demo (https://checkableai.com/)"
SNAPSHOT_PATH = os.path.join("feed-snapshot", "changes.json")
SNAPSHOT_LABEL = "the feed snapshot in this repo (feed-snapshot/changes.json)"

TOP_KEYS = ["schema", "feed_id", "feed_version", "generated_at", "publisher", "terms", "notice", "plans", "changes"]
PLAN_KEYS = ["id", "vendor", "product", "name", "terms", "rules", "rules_reading", "review"]
CHANGE_KEYS = ["change_id", "event_id", "event_type", "version", "supersedes", "record_class", "vendor", "products",
               "title", "summary", "vendor_date", "detected_at", "published_at", "action", "applicability",
               "evidence", "licence", "review"]
APPLIC_KEYS = ["plan_id", "plan_name", "status", "reason"]
EVIDENCE_KEYS = ["id", "url", "title", "published_on", "quote", "quote_policy", "our_reading", "licence"]
STATUSES = {"affected", "not_affected", "under_investigation", "fixed"}
# The change id becomes a branch name and a file path (changes/<id>.md), so no slashes, no leading dot or dash.
CHANGE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,79}")


class FeedError(Exception):
    pass


class Feed:
    def __init__(self, data, source_label):
        self.data = data
        self.source_label = source_label

    @property
    def plans(self):
        return self.data["plans"]

    @property
    def changes(self):
        return self.data["changes"]

    @property
    def version(self):
        return self.data["feed_version"]

    @property
    def generated_at(self):
        return self.data["generated_at"]


def schema_version(schema):
    if not isinstance(schema, str) or not schema.startswith(SCHEMA_PREFIX):
        raise FeedError("unknown feed schema: %r" % (schema,))
    ver = schema[len(SCHEMA_PREFIX):]
    try:
        major, minor, patch = ver.split(".")
        return int(major), int(minor), int(patch)
    except ValueError:
        raise FeedError("bad feed schema version: %r" % (schema,))


def _need(obj, keys, where):
    if not isinstance(obj, dict):
        raise FeedError("%s is not an object" % where)
    for k in keys:
        if k not in obj:
            raise FeedError("%s is missing %s" % (where, k))


def validate_feed(data):
    _need(data, TOP_KEYS, "feed")
    if schema_version(data["schema"])[0] != SUPPORTED_MAJOR:
        raise FeedError("unsupported feed schema major: %s" % data["schema"])
    if not isinstance(data["plans"], list) or not isinstance(data["changes"], list):
        raise FeedError("plans and changes must be lists")
    for i, p in enumerate(data["plans"]):
        _need(p, PLAN_KEYS, "plans[%d]" % i)
    for i, c in enumerate(data["changes"]):
        where = "changes[%d]" % i
        _need(c, CHANGE_KEYS, where)
        if (not isinstance(c["change_id"], str) or not CHANGE_ID_RE.fullmatch(c["change_id"])
                or ".." in c["change_id"] or c["change_id"].endswith(".lock")):
            raise FeedError("%s.change_id must be letters, digits, '.', '_' or '-', up to 80" % where)
        if not isinstance(c["version"], int) or isinstance(c["version"], bool) or c["version"] < 1:
            raise FeedError("%s.version must be an integer of at least 1" % where)
        for j, a in enumerate(c["applicability"]):
            _need(a, APPLIC_KEYS, "%s.applicability[%d]" % (where, j))
            if a["status"] not in STATUSES:
                raise FeedError("%s.applicability[%d].status is unknown" % (where, j))
        if not c["evidence"]:
            raise FeedError("%s has no evidence" % where)
        for j, e in enumerate(c["evidence"]):
            _need(e, EVIDENCE_KEYS, "%s.evidence[%d]" % (where, j))
    return data


def check_feed_url(url):
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or p.hostname != ALLOWED_HOST or p.username or p.password:
        raise FeedError("FEED_URL must be an https URL on %s" % ALLOWED_HOST)
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            if r.status != 200:
                raise FeedError("feed fetch returned HTTP %s" % r.status)
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise FeedError("feed fetch returned HTTP %s" % e.code)
    except urllib.error.URLError as e:
        raise FeedError("feed fetch failed: %s" % e.reason)


def load_feed(feed_url=None, snapshot_path=SNAPSHOT_PATH, fetch=_fetch):
    """FEED_URL (when non-empty) wins, otherwise the snapshot file."""
    feed_url = (feed_url or "").strip()
    if feed_url:
        check_feed_url(feed_url)
        text = fetch(feed_url)
        label = "the Checkable feed at " + feed_url
    else:
        try:
            with open(snapshot_path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            raise FeedError("cannot read the feed snapshot: %s" % e)
        label = SNAPSHOT_LABEL
    try:
        data = json.loads(text)
    except ValueError as e:
        raise FeedError("feed is not valid JSON: %s" % e)
    validate_feed(data)
    return Feed(data, label)
