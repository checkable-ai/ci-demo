"""AI model use declared outside the register: service/**/model.yaml and Kubernetes manifests under k8s/.

The gate reads these files at the base and head commits through the API, as it does the register, so no pull
request code runs. Each file yields zero or more usages, one per model.yaml and one per Kubernetes resource that
declares an AI vendor, plan or model. A usage is matched to the register by plan id, or by vendor (and product,
when given) when it names no plan.

Kubernetes convention, on any resource (Deployment, CronJob, ConfigMap and so on):

    metadata.annotations or spec.template.metadata.annotations:
        checkable.ai/vendor, checkable.ai/product, checkable.ai/plan, checkable.ai/model, checkable.ai/register-tool
    container env entries or ConfigMap data keys:
        CHECKABLE_AI_VENDOR, CHECKABLE_AI_PRODUCT, CHECKABLE_AI_PLAN, CHECKABLE_AI_MODEL, CHECKABLE_AI_REGISTER_TOOL
"""
import re

import yaml

from .render import code_register

FIELDS = ("vendor", "product", "plan", "model", "register_tool")
# A usage needs at least one of these to count as AI model use.
SIGNAL_FIELDS = ("vendor", "plan", "model")
ANNOTATIONS = {
    "checkable.ai/vendor": "vendor",
    "checkable.ai/product": "product",
    "checkable.ai/plan": "plan",
    "checkable.ai/model": "model",
    "checkable.ai/register-tool": "register_tool",
}
ENV_NAMES = {
    "CHECKABLE_AI_VENDOR": "vendor",
    "CHECKABLE_AI_PRODUCT": "product",
    "CHECKABLE_AI_PLAN": "plan",
    "CHECKABLE_AI_MODEL": "model",
    "CHECKABLE_AI_REGISTER_TOOL": "register_tool",
}
MODEL_FILE_RE = re.compile(r"service/(?:[^/]+/)*model\.ya?ml")
K8S_FILE_RE = re.compile(r"k8s/(?:[^/]+/)*[^/]+\.ya?ml")


class ServiceConfigError(Exception):
    pass


def is_model_file(name):
    return isinstance(name, str) and bool(MODEL_FILE_RE.fullmatch(name))


def is_k8s_file(name):
    return isinstance(name, str) and bool(K8S_FILE_RE.fullmatch(name))


def is_service_path(name):
    return is_model_file(name) or is_k8s_file(name)


def _text(value, where):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ServiceConfigError("%s must be text" % where)
    s = str(value).strip()
    return s or None


def _usage(values):
    u = {f: values.get(f) for f in FIELDS}
    return u if any(u[f] for f in SIGNAL_FIELDS) else None


def _load(path, text, many=False):
    try:
        if many:
            return [d for d in yaml.safe_load_all(text) if d is not None]
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ServiceConfigError("%s is not valid YAML: %s" % (path, " ".join(str(e).split())[:200]))


def model_file_usages(path, text):
    """{key: usage} for one model.yaml. A file without vendor, plan or model declares no AI use."""
    data = _load(path, text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ServiceConfigError("%s must be a YAML mapping" % path)
    values = {f: _text(data.get(f), "%s %s" % (path, f)) for f in FIELDS}
    u = _usage(values)
    return {path: dict(u, source=path)} if u else {}


def _collect(node, values, where):
    """Walk one manifest and fill values from annotations, env entries and ConfigMap-style data keys."""
    if isinstance(node, dict):
        for key, field in list(ANNOTATIONS.items()) + list(ENV_NAMES.items()):
            if key in node and not values.get(field):
                values[field] = _text(node[key], "%s %s" % (where, key))
        name = node.get("name")
        if isinstance(name, str) and name in ENV_NAMES and "value" in node and not values.get(ENV_NAMES[name]):
            values[ENV_NAMES[name]] = _text(node["value"], "%s env %s" % (where, name))
        for v in node.values():
            _collect(v, values, where)
    elif isinstance(node, list):
        for v in node:
            _collect(v, values, where)


def k8s_file_usages(path, text):
    """{key: usage} for one manifest file, one usage per resource that declares AI model use."""
    out = {}
    for i, doc in enumerate(_load(path, text, many=True)):
        if not isinstance(doc, dict):
            continue
        meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        kind = str(doc.get("kind") or "resource")
        name = str(meta.get("name") or i)
        key = "%s %s/%s" % (path, kind, name)
        values = {}
        _collect(doc, values, key)
        u = _usage(values)
        if u:
            out[key] = dict(u, source=key)
    return out


def usages_for(path, text):
    if text is None:
        return {}
    if is_model_file(path):
        return model_file_usages(path, text)
    if is_k8s_file(path):
        return k8s_file_usages(path, text)
    return {}


def diff_usages(base, head):
    """Returns (added, changed, removed) as lists of (key, base_usage, head_usage), sorted by key."""
    added = [(k, None, head[k]) for k in sorted(head) if k not in base]
    removed = [(k, base[k], None) for k in sorted(base) if k not in head]
    changed = [(k, base[k], head[k]) for k in sorted(head)
               if k in base and {f: base[k].get(f) for f in FIELDS} != {f: head[k].get(f) for f in FIELDS}]
    return added, changed, removed


def match_register(usage, tools):
    """(tool or None, note). By plan id first. With no plan, by vendor and, when given, product."""
    plan, vendor, product = usage.get("plan"), usage.get("vendor"), usage.get("product")
    rt = usage.get("register_tool")
    tool = None
    note = ""
    if plan:
        tool = next((t for t in tools if t.get("plan") == plan), None)
    elif vendor:
        tool = next((t for t in tools if (t.get("vendor") or "").casefold() == vendor.casefold()
                     and (not product or t.get("product") == product)), None)
        if tool:
            note = "Matched by vendor only. Name the plan id in the config so the gate can check the exact plan."
    if rt:
        named = next((t for t in tools if str(t.get("id")) == rt), None)
        if tool and str(tool.get("id")) != rt:
            note = ("The config names register entry %s, but its plan matches %s. Update `register_tool`."
                    % (code_register(rt), code_register(tool.get("id"))))
        elif not tool and named:
            note = ("The config still names register entry %s, which is on plan %s."
                    % (code_register(rt), code_register(named.get("plan") or "none")))
        elif not tool and not named:
            note = "The config names register entry %s, which the register does not have." % code_register(rt)
    return tool, note
