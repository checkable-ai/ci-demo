"""Small Mustache subset renderer and the text cleaners used before rendering.

Supported: {{name}}, {{#name}}...{{/name}}, {{^name}}...{{/name}}, {{! comment }}.
An unknown placeholder raises RenderError. Nothing is HTML escaped.
"""
import re


class RenderError(Exception):
    pass


_STANDALONE = re.compile(r"^[ \t]*(\{\{[#^/!][^}]*\}\})[ \t]*(?:\r?\n|\Z)", re.M)
_TAG = re.compile(r"\{\{(.*?)\}\}", re.S)


def _parse(text):
    text = _STANDALONE.sub(r"\1", text)
    root = []
    stack = [("", root, False)]
    pos = 0
    for m in _TAG.finditer(text):
        if m.start() > pos:
            stack[-1][1].append(("text", text[pos:m.start()]))
        pos = m.end()
        raw = m.group(1).strip()
        if not raw:
            raise RenderError("empty placeholder")
        kind, name = raw[0], raw[1:].strip()
        if kind == "!":
            continue
        if kind in "#^":
            children = []
            stack[-1][1].append(("sec", name, children, kind == "^"))
            stack.append((name, children, kind == "^"))
        elif kind == "/":
            if len(stack) == 1 or stack[-1][0] != name:
                raise RenderError("unbalanced section: " + name)
            stack.pop()
        else:
            stack[-1][1].append(("var", raw))
    if len(stack) != 1:
        raise RenderError("unclosed section: " + stack[-1][0])
    if pos < len(text):
        root.append(("text", text[pos:]))
    return root


def _lookup(name, ctxs):
    for ctx in reversed(ctxs):
        if isinstance(ctx, dict) and name in ctx:
            return ctx[name]
    raise RenderError("unknown placeholder: " + name)


def _render(nodes, ctxs, out):
    for node in nodes:
        if node[0] == "text":
            out.append(node[1])
        elif node[0] == "var":
            v = _lookup(node[1], ctxs)
            if v is None:
                continue
            if isinstance(v, bool):
                out.append("true" if v else "false")
            elif isinstance(v, (list, dict)):
                raise RenderError("placeholder is a list or object: " + node[1])
            else:
                out.append(str(v))
        else:
            _, name, children, inverted = node
            v = _lookup(name, ctxs)
            if inverted:
                if not v:
                    _render(children, ctxs, out)
            elif isinstance(v, list):
                for item in v:
                    _render(children, ctxs + [item], out)
            elif v:
                _render(children, ctxs + [v] if isinstance(v, dict) else ctxs, out)


def render(template, context):
    out = []
    _render(_parse(template), [context], out)
    return "".join(out)


def placeholder_names(template):
    """All names used in a template (sections and variables)."""
    names = set()

    def walk(nodes):
        for n in nodes:
            if n[0] == "var":
                names.add(n[1])
            elif n[0] == "sec":
                names.add(n[1])
                walk(n[2])

    walk(_parse(template))
    return names


# ---- cleaners -------------------------------------------------------------

def clean_feed(value):
    """Feed text: remove angle brackets. Works through lists and dicts."""
    if isinstance(value, str):
        return value.replace("<", "").replace(">", "")
    if isinstance(value, list):
        return [clean_feed(v) for v in value]
    if isinstance(value, dict):
        return {k: clean_feed(v) for k, v in value.items()}
    return value


def plain_register(value):
    """Untrusted register text as plain text: no backticks or line breaks, no live mentions."""
    s = "" if value is None else str(value)
    s = s.replace("`", "").replace("\r", " ").replace("\n", " ")
    s = s.replace("@", "@ ")
    return " ".join(s.split())


def code_register(value):
    """Untrusted register text wrapped as inline code."""
    s = plain_register(value)
    return "`" + (s if s else "-") + "`"


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date(value):
    """'2026-10-26' or '2026-10-26T22:08:37Z' to '26 Oct 2026'. Empty for None."""
    if not value:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(value))
    if not m:
        return str(value)
    return "%d %s %s" % (int(m.group(3)), _MONTHS[int(m.group(2)) - 1], m.group(1))
