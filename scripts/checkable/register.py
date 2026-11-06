"""Load and diff the AI vendor register."""
import yaml


class RegisterError(Exception):
    pass


def tool_key(tool):
    return str(tool.get("id") or tool.get("name") or "")


def parse_register(text):
    """Return the register dict. Raises RegisterError on bad YAML or shape."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise RegisterError("register is not valid YAML: " + " ".join(str(e).split()))
    if not isinstance(data, dict):
        raise RegisterError("register must be a YAML mapping")
    tools = data.get("tools")
    if tools is None:
        tools = []
    if not isinstance(tools, list):
        raise RegisterError("tools must be a list")
    seen = set()
    for i, t in enumerate(tools):
        if not isinstance(t, dict):
            raise RegisterError("tools[%d] must be a mapping" % i)
        for field in ("id", "name", "vendor", "product", "plan"):
            if not isinstance(t.get(field), (str, type(None))):
                raise RegisterError("tools[%d].%s must be text or null" % (i, field))
        k = tool_key(t)
        if not k:
            raise RegisterError("tools[%d] has neither id nor name" % i)
        if k in seen:
            raise RegisterError("duplicate tool: " + k)
        seen.add(k)
    if not isinstance(data.get("organisation"), (str, type(None))):
        raise RegisterError("organisation must be text or null")
    if not isinstance(data.get("fictional"), (bool, type(None))):
        raise RegisterError("fictional must be true or false")
    where = data.get("operates_in")
    if where is not None and not (isinstance(where, list) and all(isinstance(x, str) for x in where)):
        raise RegisterError("operates_in must be a list of region codes")
    data["tools"] = tools
    return data


def diff_registers(base, head):
    """base and head are parsed registers or None (missing). Returns (added, changed, removed) tool lists."""
    bt = {tool_key(t): t for t in (base or {}).get("tools", [])}
    ht = {tool_key(t): t for t in (head or {}).get("tools", [])}
    added = [ht[k] for k in ht if k not in bt]
    removed = [bt[k] for k in bt if k not in ht]
    changed = [ht[k] for k in ht if k in bt and ht[k] != bt[k]]
    return added, changed, removed
