"""Build the template context for one feed change (design section 3.2)."""
import re

from .match import STATUS_WORDS
from .render import clean_feed, fmt_date, plain_register

# Used when the register names no organisation.
FALLBACK_ORGANISATION = "your organisation"
DEFAULT_REPO = "checkable-ai/ci-demo"
REPLAY_CLASSES = {"replayed_vendor_change", "retrospective_reconstruction"}


def branch_for(change_id):
    """Same rule as the hosted integration: odd characters to '-', cut to 80."""
    return "checkable/" + re.sub(r"[^A-Za-z0-9._-]", "-", change_id)[:80]


def pr_title(change, tool_names):
    names = ", ".join(plain_register(n) for n in tool_names)
    title = clean_feed(change["title"])
    full = "%s [%s]" % (title, names) if names else title
    return full if len(full) <= 240 else full[:239].rstrip() + "."


def _norm(name):
    """Lower case letters and digits only, so 'Gemini API (paid tier)' and 'Gemini API, paid tier' compare equal."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def show_plan(tool_name, plan_name):
    """Show the plan name beside the tool name only when it says something the tool name does not."""
    return bool(plan_name) and _norm(plan_name) != _norm(tool_name)


def licence_credit(lic):
    """The text after the source link on a quote: the attribution, with the licence named once.

    The source line already starts with 'Source:', so a leading 'Source:' in the attribution is dropped.
    """
    lic = lic or {}
    credit = re.sub(r"^\s*Source:\s*", "", lic.get("attribution") or "").strip()
    name = (lic.get("name") or "").strip()
    if name and name.lower() not in credit.lower():
        credit = (credit + " " if credit else "") + name.rstrip(".") + "."
    return credit


def organisation_context(register):
    """company_name and is_fictional from the register, so a buyer edits only ai-vendor-register.yaml.

    The name is register text, so it is made plain. ', a fictional sample company' is printed only when the
    register says fictional: true.
    """
    reg = register if isinstance(register, dict) else {}
    name = plain_register(reg.get("organisation")) if isinstance(reg.get("organisation"), str) else ""
    return {"company_name": name or FALLBACK_ORGANISATION, "is_fictional": reg.get("fictional") is True}


def vendor_updated(change):
    """'30 Sep 2025', 'by 30 Sep 2025' for a date known only from archive captures, or empty."""
    on = change.get("vendor_updated_on")
    if not on or on == change.get("vendor_date"):
        return ""
    prefix = "by " if change.get("vendor_updated_basis") == "archive_first_capture" else ""
    return prefix + fmt_date(on)


def source_groups(items, key_fields=("source_url", "source_date")):
    """Group quotes or readings that cite the same page on the same date, keeping first-seen order.

    Each group carries the source fields once and an 'items' list, so the templates print one Source line
    per page and date instead of one after every reading.
    """
    groups, index = [], {}
    for it in items:
        key = tuple(it[k] for k in key_fields)
        if key not in index:
            index[key] = len(groups)
            groups.append({k: v for k, v in it.items() if k not in ("quote", "our_reading")} | {"items": []})
        groups[index[key]]["items"].append({k: it[k] for k in ("quote", "our_reading") if k in it})
    return groups


def change_context(change, hits, feed, repo=DEFAULT_REPO, register=None, extra=None):
    """Context for pr-body, change-record, update-comment, email-subject, email-body.

    Register values (organisation, tool names) come from the main branch register and are made plain text.
    Feed values lose angle brackets.
    """
    c = clean_feed(change)
    plans = []
    for h in hits:
        tool_name = plain_register(h["tool"].get("name") or h["tool"].get("id"))
        plan_name = clean_feed(h["plan_name"] or "")
        plans.append({
            "tool_name": tool_name,
            "plan_name": plan_name,
            "show_plan": show_plan(tool_name, plan_name),
            "status_word": STATUS_WORDS[h["status"]],
        })
    quotes, readings = [], []
    for e in c["evidence"]:
        lic = e.get("licence") or {}
        if e.get("quote"):
            quotes.append({
                "quote": e["quote"],
                "source_url": e["url"],
                "source_title": e["title"],
                "source_date": fmt_date(e.get("published_on")),
                "attribution": lic.get("attribution") or "",
                "credit": licence_credit(lic),
            })
        elif e.get("our_reading"):
            readings.append({
                "our_reading": e["our_reading"],
                "source_url": e["url"],
                "source_title": e["title"],
                "source_date": fmt_date(e.get("published_on")),
            })
    review = c.get("review") or {}
    # A quote's credit is part of its source line, so quotes group by credit too.
    quote_groups = source_groups(quotes, ("source_url", "source_date", "credit"))
    reading_groups = source_groups(readings)
    updated = vendor_updated(c)
    ctx = {
        **organisation_context(register),
        "repo": repo,
        "change_id": c["change_id"],
        "event_id": c["event_id"],
        "version": c["version"],
        "title": c["title"],
        "summary": c["summary"],
        "action": c["action"],
        "vendor_name": c["vendor"]["name"],
        "products": ", ".join(p["name"] for p in c["products"]),
        "vendor_date": fmt_date(c["vendor_date"]),
        "vendor_updated": updated,
        "detected_on": fmt_date(c.get("detected_at")),
        "feed_source": feed.source_label,
        "feed_version": feed.version,
        "feed_generated_on": fmt_date(feed.generated_at),
        "is_replay": c["record_class"] in REPLAY_CLASSES,
        "is_person_confirmed": review.get("status") == "person_confirmed",
        "reviewed_on": fmt_date(review.get("reviewed_at")),
        "plans": plans,
        "quotes": quotes,
        "readings": readings,
        "quote_sources": quote_groups,
        "reading_sources": reading_groups,
        "has_quotes": bool(quotes),
        "has_readings": bool(readings),
        "pr_number": "",
        "pr_url": "",
        "previous_version": "",
        "is_update": False,
    }
    if extra:
        ctx.update(extra)
    return ctx
