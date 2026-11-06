"""Match feed changes to register tools (design section 5.1). Vendor names alone never match.

Only open changes reach the register: a hit that is affected or worth a check. A change that has ended
(`fixed`) or was withdrawn never opens a sign-off pull request. The gate shows ended changes as a record-only note.
"""

STATUS_WORDS = {
    "affected": "Reaches you",
    "under_investigation": "Worth a check",
    "fixed": "Ended",
    "not_affected": "Clear",
}


OPEN_STATUSES = ("affected", "under_investigation")


def is_withdrawn(change):
    return change.get("event_type") == "change.withdrawn"


def tool_hit(change, tool):
    """Return {status, plan_id, plan_name, via} for one change and one tool, or None."""
    plan = tool.get("plan")
    if plan:
        for a in change["applicability"]:
            if a["plan_id"] == plan:
                return {"status": a["status"], "plan_id": plan, "plan_name": a["plan_name"], "via": "plan"}
        return None
    product = tool.get("product")
    if product:
        for p in change["products"]:
            if p["id"] == product:
                return {"status": "under_investigation", "plan_id": None, "plan_name": p["name"], "via": "product"}
    return None


def hits_for_change(change, tools):
    out = []
    for t in tools:
        h = tool_hit(change, t)
        if h:
            h = dict(h)
            h["tool"] = t
            out.append(h)
    return out


def reaches(hits):
    """True when at least one tool is affected or worth a check. Ended and clear hits never reach."""
    return any(h["status"] in OPEN_STATUSES for h in hits)


def reaching_changes(changes, tools):
    """[(change, hits)] for changes that reach the register, sorted by vendor_date then change_id."""
    out = []
    for c in sorted(changes, key=lambda c: (c["vendor_date"], c["change_id"])):
        if is_withdrawn(c):
            continue
        hits = hits_for_change(c, tools)
        if reaches(hits):
            out.append((c, hits))
    return out


def _for_tool(changes, tool, statuses):
    out = []
    for c in sorted(changes, key=lambda c: (c["vendor_date"], c["change_id"])):
        if is_withdrawn(c):
            continue
        h = tool_hit(c, tool)
        if h and h["status"] in statuses:
            out.append((c, h))
    return out


def changes_for_tool(changes, tool):
    """[(change, hit)] that are open for this tool (affected or worth a check), in vendor_date order."""
    return _for_tool(changes, tool, OPEN_STATUSES)


def ended_changes_for_tool(changes, tool):
    """[(change, hit)] that reached this tool and have since ended. Shown as a record only."""
    return _for_tool(changes, tool, ("fixed",))
