"""The k8s/policy check: every AI model a Kubernetes workload uses must be in the AI vendor register.

    python -m scripts.checkable.k8s_policy [--register FILE] [--heading TEXT] PATH...

Each PATH is a YAML file or a directory of YAML files: the manifests under k8s/, or the output of
`kubectl get ... -o yaml` for the live cluster (a `kind: List` is unpacked). The check reads, per workload:

* AI model endpoints: URLs and hosts in env entries, ConfigMap data (reached through envFrom or configMapKeyRef),
  container command and args, and Service externalName. A URL counts when its host is a known AI vendor host
  (AI_HOSTS below) or when its key looks like a model endpoint (MODEL_ENDPOINT, LLM_URL, OPENAI_API_BASE and so on).
* Declared AI use: the checkable.ai/* annotations or CHECKABLE_AI_* env and ConfigMap keys that the Checkable gate
  reads (vendor, product, plan, model), plus checkable.ai/register-id (the same as checkable.ai/register-tool),
  which names the register entry that covers the service.
* Images: AI model servers (ollama, vllm, text-generation-inference and similar) need a register entry too. Every
  other image is listed, and a missing or `latest` tag is a warning.

Each finding is matched to ai-vendor-register.yaml. A finding with no register entry, or an endpoint that
contradicts the register entry the service declares, blocks: exit 1. A finding with a register entry shows the
open vendor changes from the feed that reach it. Exit 2 means the check could not run (bad YAML, register or feed).
The job summary and the log carry the same table.
"""
import argparse
import fnmatch
import os
import re
import sys
from urllib.parse import urlsplit

import yaml

from . import match, services
from .feed import FeedError, load_feed
from .register import RegisterError, parse_register
from .render import plain_register

DEFAULT_REGISTER = "ai-vendor-register.yaml"
REGISTER_ID_ANNOTATION = "checkable.ai/register-id"
ANNOTATIONS = dict(services.ANNOTATIONS, **{REGISTER_ID_ANNOTATION: "register_tool"})

# host pattern, vendor name, product ids. The product ids follow the Checkable feed (openai.api, google.gemini-api).
# A register entry covers a host when its vendor matches and its product (or the start of its plan id) is listed.
AI_HOSTS = [
    ("api.openai.com", "OpenAI", ("openai.api",)),
    ("generativelanguage.googleapis.com", "Google", ("google.gemini-api",)),
    ("*aiplatform.googleapis.com", "Google", ("google.vertex-ai",)),
    ("api.anthropic.com", "Anthropic", ("anthropic.claude-api",)),
    ("*.openai.azure.com", "Microsoft", ("microsoft.azure-openai",)),
    ("bedrock*.amazonaws.com", "Amazon", ("aws.bedrock",)),
    ("api.githubcopilot.com", "GitHub", ("github.copilot",)),
    ("api.mistral.ai", "Mistral AI", ("mistral.api",)),
    ("api.cohere.com", "Cohere", ("cohere.api",)),
    ("api.cohere.ai", "Cohere", ("cohere.api",)),
    ("api.x.ai", "xAI", ("xai.api",)),
    ("api.groq.com", "Groq", ("groq.api",)),
    ("api.deepseek.com", "DeepSeek", ("deepseek.api",)),
    ("api.perplexity.ai", "Perplexity", ("perplexity.api",)),
    ("api.together.xyz", "Together AI", ("together.api",)),
    ("openrouter.ai", "OpenRouter", ("openrouter.api",)),
    ("*.huggingface.co", "Hugging Face", ("huggingface.inference",)),
]
# Images that serve a model. Matched against the image name without registry or tag.
AI_IMAGE_RE = re.compile(
    r"(^|/)(ollama|vllm|vllm-openai|text-generation-inference|tgi|localai|llama[-.]?cpp|llamacpp|litellm|openllm|"
    r"tritonserver|nim/[^/]+)($|[/:@-])", re.I)
# Config keys that mean "the endpoint of an AI model": a model-ish word plus an endpoint-ish ending.
ENDPOINT_KEY_RE = re.compile(
    r"(^|_)(MODEL|LLM|AI|INFERENCE|COMPLETIONS?|EMBEDDINGS?|GEMINI|OPENAI|ANTHROPIC|CLAUDE|GPT[0-9]*|BEDROCK|VERTEX)"
    r"(_[A-Z0-9_]+)?_(ENDPOINT|URL|URI|HOST|BASE)$")
URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>]+")
BARE_HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*(:\d+)?(/\S*)?")
WORKLOAD_SKIP_KEYS = ("status", "managedFields")

FAIL = ("unregistered", "mismatch")
RESULT_WORDS = {
    "unregistered": "Not in register",
    "mismatch": "Does not match register",
    "warning": "Warning",
    "registered": "In register",
    "info": "Not an AI model server",
}
KIND_ORDER = {"Declared model": 0, "Endpoint": 1, "Image": 2}
STATUS_ORDER = {"unregistered": 0, "mismatch": 0, "warning": 1, "registered": 2, "info": 3}


class PolicyError(Exception):
    pass


# ---- reading manifests ---------------------------------------------------------------------------------------

def _yaml_files(path):
    if os.path.isdir(path):
        out = []
        for root, _dirs, files in os.walk(path):
            out += [os.path.join(root, f) for f in files if f.lower().endswith((".yaml", ".yml"))]
        return sorted(out)
    if os.path.isfile(path):
        return [path]
    raise PolicyError("%s does not exist" % path)


def _unpack(doc, out):
    if not isinstance(doc, dict):
        return
    if isinstance(doc.get("items"), list) and str(doc.get("kind", "")).endswith("List"):
        for item in doc["items"]:
            _unpack(item, out)
    else:
        out.append(doc)


def load_docs(paths):
    """([doc], [file]) from files and directories. A List is unpacked. A bad YAML file raises PolicyError."""
    docs, files = [], []
    for p in paths:
        for f in _yaml_files(p):
            files.append(f)
            try:
                with open(f, encoding="utf-8") as fh:
                    for d in yaml.safe_load_all(fh):
                        _unpack(d, docs)
            except yaml.YAMLError as e:
                raise PolicyError("%s is not valid YAML: %s" % (f, " ".join(str(e).split())[:200]))
            except OSError as e:
                raise PolicyError("cannot read %s: %s" % (f, e))
    return docs, files


# ---- extracting what a resource declares -----------------------------------------------------------------------

def _meta(doc):
    m = doc.get("metadata")
    return m if isinstance(m, dict) else {}


def _name(doc):
    return str(_meta(doc).get("name") or "?")


def _ns(doc):
    return str(_meta(doc).get("namespace") or "default")


def _label(doc):
    return "%s/%s" % (doc.get("kind") or "resource", _name(doc))


def _annotation_dicts(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in WORKLOAD_SKIP_KEYS:
                continue
            if k == "annotations" and isinstance(v, dict):
                out.append(v)
            else:
                _annotation_dicts(v, out)
    elif isinstance(node, list):
        for v in node:
            _annotation_dicts(v, out)


def _pod_specs(node, out):
    if isinstance(node, dict):
        if isinstance(node.get("containers"), list):
            out.append(node)
        for k, v in node.items():
            if k not in WORKLOAD_SKIP_KEYS:
                _pod_specs(v, out)
    elif isinstance(node, list):
        for v in node:
            _pod_specs(v, out)


def _as_text(v):
    if v is None or isinstance(v, (dict, list, bool)):
        return None
    s = str(v).strip()
    return s or None


def _declared(annotation_dicts, pairs):
    """{vendor, product, plan, model, register_tool} from checkable.ai/* annotations, then CHECKABLE_AI_* keys."""
    out = {}
    for ann in annotation_dicts:
        for key, field in ANNOTATIONS.items():
            if key in ann and not out.get(field) and _as_text(ann[key]):
                out[field] = _as_text(ann[key])
    for key, value in pairs:
        field = services.ENV_NAMES.get(key)
        if field and not out.get(field) and _as_text(value):
            out[field] = _as_text(value)
    return out


def _endpoint_hosts(key, value):
    """Hosts in one config value. A key with a model-endpoint name also accepts a bare host."""
    text = _as_text(value)
    if not text:
        return []
    hosts = [urlsplit(u).hostname for u in URL_RE.findall(text)]
    if not hosts and key and ENDPOINT_KEY_RE.search(key.upper()) and BARE_HOST_RE.fullmatch(text):
        hosts = [urlsplit("//" + text).hostname]
    return [h.lower() for h in hosts if h]


def _container_pairs(container, configmaps, consumed, ns, warnings, owner):
    """[(key, value)] for one container: env, envFrom and configMapKeyRef values, then command and args as text."""
    pairs = []

    def cm_data(name, optional):
        cm = configmaps.get((ns, name))
        if cm is None:
            if not optional:
                warnings.append("%s reads ConfigMap `%s`, which is not in what was read, so its AI settings were "
                                "not checked." % (owner, plain_register(name)))
            return {}
        consumed.add((ns, name))
        return cm

    for ef in container.get("envFrom") or []:
        ref = ef.get("configMapRef") if isinstance(ef, dict) else None
        if isinstance(ref, dict) and ref.get("name"):
            prefix = str(ef.get("prefix") or "")
            for k, v in cm_data(str(ref["name"]), bool(ref.get("optional"))).items():
                pairs.append((prefix + str(k), v))
    for e in container.get("env") or []:
        if not isinstance(e, dict) or not e.get("name"):
            continue
        if "value" in e:
            pairs.append((str(e["name"]), e["value"]))
        ref = (e.get("valueFrom") or {}).get("configMapKeyRef") if isinstance(e.get("valueFrom"), dict) else None
        if isinstance(ref, dict) and ref.get("name") and ref.get("key") is not None:
            data = cm_data(str(ref["name"]), bool(ref.get("optional")))
            if str(ref["key"]) in data:
                pairs.append((str(e["name"]), data[str(ref["key"])]))
    for part in list(container.get("command") or []) + list(container.get("args") or []):
        if isinstance(part, str):
            pairs.append((None, part))
    return pairs


# ---- matching to the register ----------------------------------------------------------------------------------

def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold())


def host_info(host):
    """(vendor, products) for a known AI vendor host, else None."""
    for pattern, vendor, products in AI_HOSTS:
        if fnmatch.fnmatchcase(host, pattern):
            return vendor, products
    return None


def tool_covers_host(tool, info):
    vendor, products = info
    if _norm(tool.get("vendor")) != _norm(vendor):
        return False
    product, plan = tool.get("product") or "", tool.get("plan") or ""
    return any(product == p or plan.startswith(p + ".") for p in products)


def tool_has_known_hosts(tool):
    return any(_norm(tool.get("vendor")) == _norm(v) for _p, v, _prods in AI_HOSTS)


def resolve_declared(usage, tools):
    """(tool or None, note) for the declared vendor, plan, model and register id."""
    plan, vendor, rt = usage.get("plan"), usage.get("vendor"), usage.get("register_tool")
    if not plan and not vendor and rt:
        tool = next((t for t in tools if str(t.get("id")) == rt), None)
        if tool:
            return tool, ""
        return None, "The service names register entry `%s`, which the register does not have." % plain_register(rt)
    if not plan and not vendor:
        return None, "A model is declared without a vendor, a plan or a register entry, so it cannot be matched."
    tool, note = services.match_register(usage, tools)
    if not tool and not note:
        what = plain_register(plan or vendor)
        note = "The register has no entry for `%s`. Add one in this pull request." % what
    return tool, note


# ---- findings --------------------------------------------------------------------------------------------------

def _finding(kind, found, status, tool=None, note="", where=None):
    return {"kind": kind, "found": found, "status": status, "tool": tool, "note": note, "where": set(where or [])}


def _worse(a, b):
    return STATUS_ORDER[a] <= STATUS_ORDER[b]


def _add(findings, f):
    key = (f["kind"], f["found"])
    cur = findings.get(key)
    if cur is None:
        findings[key] = f
        return
    cur["where"] |= f["where"]
    if not _worse(cur["status"], f["status"]):
        cur.update(status=f["status"], tool=f["tool"] or cur["tool"], note=f["note"] or cur["note"])
    elif f["tool"] and not cur["tool"]:
        cur["tool"] = f["tool"]


def _describe_usage(u):
    parts = [u.get(f) for f in ("vendor", "plan", "model") if u.get(f)]
    if u.get("register_tool"):
        parts.append("register-id %s" % u["register_tool"])
    return " / ".join(parts)


def _endpoint_finding(host, key, ctx_tool, tools, where):
    found = "%s (%s)" % (host, key) if key else host
    info = host_info(host)
    if info:
        vendor, products = info
        covering = [t for t in tools if tool_covers_host(t, info)]
        if ctx_tool is not None and ctx_tool in covering:
            return _finding("Endpoint", found, "registered", ctx_tool, where=where)
        if ctx_tool is not None:
            return _finding("Endpoint", found, "mismatch", ctx_tool, where=where, note=(
                "The endpoint is a %s host, but the service declares register entry `%s` (%s). Update the "
                "declaration or the endpoint so they agree." % (
                    vendor, plain_register(ctx_tool.get("id")),
                    plain_register(ctx_tool.get("vendor") or ctx_tool.get("name")))))
        if covering:
            return _finding("Endpoint", found, "registered", covering[0], where=where)
        return _finding("Endpoint", found, "unregistered", where=where, note=(
            "The register has no %s entry for %s. Add one in this pull request, or remove the endpoint." % (
                vendor, " or ".join(products))))
    if ctx_tool is not None:
        if tool_has_known_hosts(ctx_tool):
            return _finding("Endpoint", found, "warning", ctx_tool, where=where, note=(
                "This host is not a known %s host. If it is a proxy or gateway in front of the model, that is "
                "fine, but check it." % plain_register(ctx_tool.get("vendor"))))
        return _finding("Endpoint", found, "registered", ctx_tool, where=where,
                        note="The host is not on the known AI vendor list. The declared register entry covers it.")
    return _finding("Endpoint", found, "unregistered", where=where, note=(
        "This looks like an AI model endpoint, but the host is not a known vendor and the service declares no "
        "register entry. Add the checkable.ai/register-id annotation and a register entry."))


def _image_finding(image, ctx_tool, where):
    name = re.sub(r"@sha256:[0-9a-f]+$", "", image)
    last = name.rsplit("/", 1)[-1]
    tag = last.split(":", 1)[1] if ":" in last else ("" if "@" not in image else "digest")
    unpinned = tag in ("", "latest")
    if AI_IMAGE_RE.search(name):
        if ctx_tool is not None:
            f = _finding("Image", image, "registered", ctx_tool, where=where)
        else:
            f = _finding("Image", image, "unregistered", where=where, note=(
                "This image serves an AI model and the service declares no register entry. Add the "
                "checkable.ai/register-id annotation and a register entry."))
    else:
        f = _finding("Image", image, "info", where=where)
    if unpinned:
        f["note"] = (f["note"] + " " if f["note"] else "") + "The image has no version tag or digest."
        if f["status"] == "info":
            f["status"] = "warning"
    return f


def analyse(docs, tools):
    """({key: finding}, [warning]) for the resources in docs, matched to the register tools."""
    findings, warnings = {}, []
    live = [d for d in docs if not _meta(d).get("ownerReferences")]  # a pod or ReplicaSet is covered by its owner
    configmaps = {(_ns(d), _name(d)): (d.get("data") if isinstance(d.get("data"), dict) else {})
                  for d in live if d.get("kind") == "ConfigMap"}
    consumed = set()

    for doc in live:
        if doc.get("kind") == "ConfigMap":
            continue
        specs = []
        _pod_specs(doc, specs)
        where = [_label(doc)]
        anns = []
        _annotation_dicts(doc, anns)
        pairs, images = [], []
        for spec in specs:
            for c in list(spec.get("containers") or []) + list(spec.get("initContainers") or []):
                if not isinstance(c, dict):
                    continue
                pairs += _container_pairs(c, configmaps, consumed, _ns(doc), warnings, _label(doc))
                if isinstance(c.get("image"), str) and c["image"].strip():
                    images.append(c["image"].strip())
        if doc.get("kind") == "Service":
            ext = (doc.get("spec") or {}).get("externalName") if isinstance(doc.get("spec"), dict) else None
            if _as_text(ext):
                pairs.append(("EXTERNAL_NAME", "https://" + str(ext).strip()))
        _evaluate(findings, tools, where, anns, pairs, images, declares=bool(specs) or bool(anns))

    for key, data in configmaps.items():  # ConfigMaps no workload reads still declare AI use
        if key in consumed:
            continue
        doc = next(d for d in live if d.get("kind") == "ConfigMap" and (_ns(d), _name(d)) == key)
        anns = []
        _annotation_dicts(doc, anns)
        _evaluate(findings, tools, [_label(doc)], anns, [(str(k), v) for k, v in data.items()], [], declares=True)
    return findings, warnings


def _evaluate(findings, tools, where, anns, pairs, images, declares):
    usage = _declared(anns, pairs) if declares else {}
    ctx_tool = None
    if usage:
        ctx_tool, note = resolve_declared(usage, tools)
        status = "unregistered" if ctx_tool is None else ("warning" if note else "registered")
        _add(findings, _finding("Declared model", _describe_usage(usage), status, ctx_tool, note, where))
    seen = set()
    for key, value in pairs:
        for host in _endpoint_hosts(key, value):
            if (key, host) in seen:
                continue
            seen.add((key, host))
            if host_info(host) or (key and ENDPOINT_KEY_RE.search(key.upper())):
                _add(findings, _endpoint_finding(host, key, ctx_tool, tools, where))
    for image in images:
        _add(findings, _image_finding(image, ctx_tool, where))


# ---- report ----------------------------------------------------------------------------------------------------

def _code(s, limit=110):
    s = " ".join(str(s).replace("`", "").replace("|", "/").split())
    if len(s) > limit:
        s = s[:limit - 1] + "..."
    return "`%s`" % s if s else "-"


def _cell(s):
    return " ".join(str(s).replace("|", "/").replace("`", "'").split())


def _open_changes(tool, feed):
    if tool is None or feed is None:
        return []
    return [(c["change_id"], match.STATUS_WORDS[h["status"]]) for c, h in match.changes_for_tool(feed.changes, tool)]


def build_rows(findings, feed):
    rows = []
    for f in findings.values():
        opens = _open_changes(f["tool"], feed)
        rows.append(dict(f, result=RESULT_WORDS[f["status"]], fails=f["status"] in FAIL, open_changes=opens,
                         register=str(f["tool"].get("id")) if f["tool"] else ""))
    rows.sort(key=lambda r: (STATUS_ORDER[r["status"]], KIND_ORDER[r["kind"]], r["found"]))
    return rows


def _opens_cell(opens):
    if not opens:
        return "-"
    shown = ["`%s` (%s)" % (plain_register(i), w) for i, w in opens[:4]]
    if len(opens) > 4:
        shown.append("and %d more" % (len(opens) - 4))
    return ", ".join(shown)


def report_markdown(rows, warnings, *, heading, register, feed, n_resources, n_files):
    fails = [r for r in rows if r["fails"]]
    lines = ["## " + heading, ""]
    if fails:
        lines.append("**Blocked: %d AI use%s not covered by the register.**" % (
            len(fails), " is" if len(fails) == 1 else "s are"))
    elif any(r["kind"] != "Image" for r in rows):
        lines.append("**Passed: every AI model the manifests use is in the register.**")
    else:
        lines.append("**Passed: no AI model use found.**")
    lines += ["", "Register: %s, %d tools. Feed: %s, version %s. Read %d resources from %d files." % (
        _code(register.get("organisation") or "register"), len(register["tools"]),
        feed.source_label, feed.version, n_resources, n_files)]
    if rows:
        lines += ["", "| Result | Kind | Found | Where | Register entry | Open vendor changes |",
                  "|---|---|---|---|---|---|"]
        for r in rows:
            lines.append("| %s | %s | %s | %s | %s | %s |" % (
                r["result"], r["kind"], _code(r["found"]), _cell(", ".join(sorted(r["where"]))),
                _code(r["register"]) if r["register"] else "-", _opens_cell(r["open_changes"])))
    notes = [r for r in rows if r["note"]]
    if notes or warnings:
        lines += ["", "### Notes", ""]
        lines += ["- %s %s: %s" % (r["result"], _code(r["found"]), _cell(r["note"])) for r in notes]
        lines += ["- " + _cell(w) for w in warnings]
    return "\n".join(lines) + "\n"


def log_lines(rows, warnings):
    out = []
    for r in rows:
        line = "%s: %s %s" % (r["result"], r["kind"].lower(), _cell(r["found"]))
        if r["status"] != "info":
            line += " -> " + (r["register"] or "no register entry")
        if r["open_changes"]:
            line += " (%d open vendor change%s)" % (len(r["open_changes"]), "" if len(r["open_changes"]) == 1 else "s")
        out.append(line)
        if r["fails"]:
            out.append("::error::%s %s: %s" % (r["kind"], _cell(r["found"]), _cell(r["note"] or r["result"])))
    out += ["::warning::" + _cell(w) for w in warnings]
    return out


def check(paths, register_path=DEFAULT_REGISTER, feed=None):
    """(rows, warnings, register, n_resources, n_files). Raises PolicyError, RegisterError."""
    try:
        with open(register_path, encoding="utf-8") as f:
            register = parse_register(f.read())
    except OSError as e:
        raise PolicyError("cannot read the register: %s" % e)
    docs, files = load_docs(paths)
    findings, warnings = analyse(docs, register["tools"])
    return build_rows(findings, feed), warnings, register, len(docs), len(files)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check Kubernetes AI model use against the AI vendor register.")
    ap.add_argument("paths", nargs="+", help="manifest files or directories, or kubectl get -o yaml output")
    ap.add_argument("--register", default=DEFAULT_REGISTER)
    ap.add_argument("--heading", default="Kubernetes policy")
    args = ap.parse_args(argv)
    try:
        feed = load_feed(os.environ.get("FEED_URL"))
        rows, warnings, register, n_res, n_files = check(args.paths, args.register, feed)
    except (FeedError, RegisterError, PolicyError) as e:
        print("::error::" + str(e))
        _summary("## %s\n\n**Could not run the check.** %s\n" % (args.heading, _cell(e)))
        return 2
    for line in log_lines(rows, warnings):
        print(line)
    _summary(report_markdown(rows, warnings, heading=args.heading, register=register, feed=feed,
                             n_resources=n_res, n_files=n_files))
    failed = [r for r in rows if r["fails"]]
    print("%s: %d finding%s, %d blocked." % ("Blocked" if failed else "Passed", len(rows),
                                             "" if len(rows) == 1 else "s", len(failed)))
    return 1 if failed else 0


def _summary(text):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    sys.exit(main())
