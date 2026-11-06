"""Test helpers: a small demo feed, a fake GitHub API, a fake git/gh layer and template lookup."""
import copy
import os
import shutil
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_TEMPLATES = os.path.join(ROOT, "templates")
STAND_INS = os.path.join(ROOT, "tests", "fixtures", "templates")
TEMPLATE_NAMES = ["pr-body", "change-record", "update-comment", "gate-comment", "email-subject", "email-body"]

LIC_NONE = {"status": "no_reuse_licence", "name": None, "url": None, "attribution": None,
            "read_on": "2026-11-06", "basis": "Page shows a copyright notice and no reuse licence"}
LIC_CC = {"status": "confirmed_reusable", "name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
          "attribution": "Source: Google for Developers, Gemini API changelog, licensed under CC BY 4.0.",
          "read_on": "2026-11-06", "basis": "Page footer licence statement"}
LIC_PD = {"status": "public_domain", "name": "Public domain (US court order)", "url": None,
          "attribution": "Order of the US District Court, via CourtListener.", "read_on": "2026-11-06",
          "basis": "US federal court order"}


def template_dir():
    """A temp dir holding D's real templates where they exist, stand-ins otherwise."""
    d = tempfile.mkdtemp(prefix="tpl-")
    for n in TEMPLATE_NAMES:
        real = os.path.join(REAL_TEMPLATES, n + ".md")
        src = real if os.path.exists(real) else os.path.join(STAND_INS, n + ".md")
        shutil.copy(src, os.path.join(d, n + ".md"))
    return d


def real_templates_present():
    return [n for n in TEMPLATE_NAMES if os.path.exists(os.path.join(REAL_TEMPLATES, n + ".md"))]


def plan(pid, name, vendor="V", product=None):
    product = product or ".".join(pid.split(".")[:2])
    return {
        "id": pid, "vendor": {"id": pid.split(".")[0], "name": vendor},
        "product": {"id": product, "name": product}, "name": name,
        "terms": [{"title": name + " terms", "url": "https://example.test/terms/" + pid}],
        "rules": {"au": [{"code": "APPs", "name": "Australian Privacy Principles", "why": "Client data is personal information."}],
                  "eu": [{"code": "EU-GDPR", "name": "General Data Protection Regulation", "why": "EU clients."}],
                  "us": [{"code": "US-FTC-S5-AI", "name": "FTC Act section 5 and AI", "why": "Claims must be true."}]},
        "rules_reading": "Checkable AI's reading of how these rules reach a business using this plan.",
        "review": {"status": "auto_needs_review", "reviewed_at": None},
    }


def evidence(eid, url, quote=None, lic=None, reading=None):
    lic = lic or LIC_NONE
    return {"id": eid, "url": url, "title": "Source " + eid, "published_on": "2026-10-26", "quote": quote,
            "quote_policy": "verbatim" if quote else "link_and_paraphrase",
            "our_reading": None if quote else (reading or "Checkable AI's reading of the page: a change."),
            "licence": lic}


def change(cid, title, vendor, products, vendor_date, applic, ev, version=1, record_class="observed_vendor_change",
           quotes="paraphrase_only"):
    return {
        "change_id": cid, "event_id": "evt_" + "0" * 26, "event_type": "change.published", "version": version,
        "supersedes": None, "record_class": record_class, "vendor": {"id": vendor.lower(), "name": vendor},
        "products": [{"id": p, "name": p.split(".")[-1]} for p in products], "title": title,
        "summary": "Summary of " + title, "vendor_date": vendor_date, "detected_at": vendor_date + "T01:00:00Z",
        "published_at": vendor_date + "T06:00:00Z", "action": "Do the thing for " + title,
        "applicability": [{"plan_id": p, "plan_name": n, "status": s, "reason": None} for p, n, s in applic],
        "evidence": ev, "licence": {"quotes": quotes}, "review": {"status": "auto_needs_review", "reviewed_at": None},
    }


def demo_feed():
    plans = [
        plan("anthropic.claude.team", "Claude Team"), plan("anthropic.claude.pro", "Claude Pro"),
        plan("openai.chatgpt.plus", "ChatGPT Plus"), plan("openai.api.platform", "OpenAI API"),
        plan("github.copilot.business", "GitHub Copilot Business"), plan("google.gemini-api.paid", "Gemini API, paid tier"),
        plan("microsoft.m365-copilot.commercial", "Microsoft 365 Copilot"),
    ]
    changes = [
        change("chg_google-2026-10-26-gemini-api-storage-default", "Google turns request storage on by default",
               "Google", ["google.gemini-api"], "2026-10-26",
               [("google.gemini-api.free", "Gemini API, free tier", "under_investigation"),
                ("google.gemini-api.paid", "Gemini API, paid tier", "affected")],
               [evidence("ev_g1", "https://ai.google.dev/gemini-api/docs/changelog", "New projects now store requests by default.", LIC_CC)],
               quotes="verbatim"),
        change("chg_openai-2025-05-13-nyt-preservation", "Court order on OpenAI log preservation", "OpenAI",
               ["openai.chatgpt", "openai.api"], "2025-05-13",
               [("openai.chatgpt.plus", "ChatGPT Plus", "fixed"), ("openai.api.platform", "OpenAI API", "fixed")],
               [evidence("ev_o1", "https://www.courtlistener.com/docket/68117049/551/", "The court order text.", LIC_PD),
                evidence("ev_o2", "https://openai.com/index/response-to-nyt-data-demands/")],
               version=2, record_class="replayed_vendor_change", quotes="mixed"),
        change("chg_github-2026-10-26-gpt-6-1-terra-copilot", "GPT-6.1 Terra arrives in Copilot", "GitHub",
               ["github.copilot"], "2026-10-26", [("github.copilot.business", "GitHub Copilot Business", "affected")],
               [evidence("ev_h1", "https://github.blog/changelog/2026-10-23-gpt-6-1-terra/")]),
        change("chg_anthropic-2025-08-28-consumer-terms", "Anthropic updates consumer terms", "Anthropic",
               ["anthropic.claude"], "2025-08-28",
               [("anthropic.claude.team", "Claude Team", "not_affected"), ("anthropic.claude.pro", "Claude Pro", "affected")],
               [evidence("ev_a1", "https://www.anthropic.com/news/updates-to-our-consumer-terms")], version=2),
        change("chg_openai-2026-10-21-service-tier-limits", "OpenAI changes service tier limits", "OpenAI",
               ["openai.api"], "2026-10-21", [("openai.api.platform", "OpenAI API", "affected")],
               [evidence("ev_o9", "https://developers.openai.com/api/docs/changelog")]),
    ]
    return {
        "schema": "urn:checkable:feed:demo-changes:1.0.0", "feed_id": "checkable-demo",
        "feed_version": "2026-11-06.1", "generated_at": "2026-11-06T09:00:00Z",
        "publisher": {"name": "Checkable AI", "url": "https://checkableai.com/"},
        "terms": {"url": "https://checkableai.com/terms/", "text": "Terms text."},
        "notice": "A demo feed.", "plans": plans, "changes": changes,
    }


def make_feed(data=None, label="the feed snapshot in this repo (feed-snapshot/changes.json)"):
    from scripts.checkable.feed import Feed, validate_feed
    data = copy.deepcopy(data or demo_feed())
    validate_feed(data)
    return Feed(data, label)


REGISTER_TEXT = """\
organisation: Example Bay Advisory
fictional: true
operates_in: [AU, EU, US]
tools:
  - {id: claude-team, name: Claude Team, vendor: Anthropic, product: anthropic.claude, plan: anthropic.claude.team, used_by: "Advisory staff"}
  - {id: chatgpt-plus-research, name: ChatGPT Plus, vendor: OpenAI, product: openai.chatgpt, plan: openai.chatgpt.plus, used_by: "Research lead"}
  - {id: copilot-business, name: GitHub Copilot Business, vendor: GitHub, product: github.copilot, plan: github.copilot.business}
  - {id: gemini-api-paid, name: Gemini API (paid tier), vendor: Google, product: google.gemini-api, plan: google.gemini-api.paid}
  - {id: m365-copilot, name: Microsoft 365 Copilot, vendor: Microsoft, product: microsoft.m365-copilot, plan: microsoft.m365-copilot.commercial}
  - {id: inhouse-summariser, name: In-house summariser, vendor: null, product: null, plan: null}
"""


def register_with(extra_lines="", replace=None):
    text = REGISTER_TEXT
    for old, new in (replace or {}).items():
        assert old in text
        text = text.replace(old, new)
    return text + extra_lines


class FakeAPI:
    """Fake of GitHubAPI for the gate and the nightly job."""

    def __init__(self, base_register=None, head_register=None, files=None, labels=(), roles=None, comments=None,
                 head_sha="a" * 40, base_sha="b" * 40, file_map=None, bot_login="github-actions[bot]"):
        self.base_register, self.head_register = base_register, head_register
        # {path: (base_text, head_text)} for files other than the register, such as service/*/model.yaml
        self.file_map = file_map or {}
        self.bot_login = bot_login
        self.files = files or []
        self.labels = list(labels)
        self.roles = roles or {}
        self.comments = comments if comments is not None else []
        self.head_sha, self.base_sha = head_sha, base_sha
        self.statuses, self.removed_labels, self.created, self.updated = [], [], [], []
        self.pr_comments = {}

    def get_pr(self, number):
        return {"head": {"sha": self.head_sha}, "base": {"sha": self.base_sha}, "labels": [{"name": l} for l in self.labels]}

    def get_file(self, path, ref):
        if path in self.file_map:
            base, head = self.file_map[path]
            return base if ref == self.base_sha else head
        if ref == self.base_sha:
            return self.base_register
        return self.head_register

    def list_pr_files(self, number):
        return [{"filename": f, "status": s} for f, s in self.files]

    def permission_role(self, login):
        return self.roles.get(login, "none")

    def list_comments(self, number):
        return [c for c in self.comments if c.get("pr", number) == number]

    def create_comment(self, number, body):
        c = {"id": len(self.comments) + 1, "pr": number, "body": body, "user": {"login": self.bot_login, "type": "Bot"}}
        self.comments.append(c)
        self.created.append((number, body))
        return c

    def update_comment(self, cid, body):
        for c in self.comments:
            if c["id"] == cid:
                c["body"] = body
        self.updated.append((cid, body))

    def remove_label(self, number, label):
        self.removed_labels.append(label)
        if label in self.labels:
            self.labels.remove(label)

    def set_status(self, sha, state, description, context):
        self.statuses.append((sha, state, description, context))
