"""Persona roster and risk policy: runtime (layer 1), model/effort (layer 2) and
persona/scope/permissions (layer 3) are configured independently."""
from .. import runtime
from .contracts import RISKS

GATES = {"prd", "uxspec", "techspec", "release"}
PROTOCOLS = {"code-review", "qa", "docs-review", "content-review", "ui-review"}  # review protocols
DOC_STAGES = ("prd", "uxspec", "techspec")
WRITE_PROTOCOLS = {"implement", "write-docs", "write-content"}
ROLE_KEYS = {"triage", *DOC_STAGES, "implement", "code_review"}
# A kind (code, design, docs, content) picks which documents run, extra gates, the writing
# protocol and role overrides; anything it leaves out falls back to the code flow.
DEFAULT_KIND = {"docs": ["prd", "techspec"], "gates": [], "implement_protocol": "implement", "roles": {}}


BINDING_KEYS = {"persona", "model", "effort"}


def binding(ref):
    """A roles entry: a persona id, or {"persona": id, "model": ..., "effort": ...} to tune one
    stage without a second persona. Overrides never change the runtime."""
    if isinstance(ref, str):
        return ref, {}
    return ref["persona"], {key: ref[key] for key in ("model", "effort") if key in ref}


def kind_config(flow, kind):
    kinds = flow.get("kinds", {"code": {}})
    if kind not in kinds:
        raise ValueError(f"Unknown kind {kind!r}; config/flow.json defines: {', '.join(kinds)}")
    return {**DEFAULT_KIND, **kinds[kind]}


def role(flow, kind, key, risk=None):
    """The roles entry for a stage: the kind's override, else the code flow's; per-risk maps resolve to the tier."""
    value = kind_config(flow, kind)["roles"].get(key, flow["roles"].get(key))
    if risk is not None and isinstance(value, dict) and "persona" not in value:
        value = value[risk]
    return value


def persona_cfg(persona, agents, override=None):
    """CLI config: the runtime's executable, then persona defaults, then the stage override."""
    base = agents[persona["runtime"]]
    merged = {**persona, **(override or {})}
    return {"prefix": base["prefix"], "model": merged.get("model") or base["model"],
            "effort": merged["effort"] if "effort" in merged else base.get("effort")}


def check_roster(flow, personas, agents):
    """Reject a roster that breaks independence or gives write access to an unverified runtime."""
    def settings(values, where):
        if values.get("effort") is not None and values["effort"] not in runtime.EFFORTS:
            raise ValueError(f"Invalid effort in {where}")
        if values.get("model") is not None and (not isinstance(values["model"], str) or not values["model"].strip()):
            raise ValueError(f"Invalid model in {where}")

    def persona(ref, where):
        if not isinstance(ref, str) and (not isinstance(ref, dict) or "persona" not in ref
                                         or set(ref) - BINDING_KEYS):
            raise ValueError(f"{where} must be a persona id or {{persona, model, effort}}")
        name, override = binding(ref)
        if name not in personas:
            raise ValueError(f"Unknown persona {name!r} in {where}")
        entry = personas[name]
        if entry.get("runtime") not in agents:
            raise ValueError(f"Persona {name} uses an unconfigured runtime")
        settings(entry, f"persona {name}")
        settings(override, where)
        for key in ("role", "mindset", "scope", "escalation"):
            if not entry.get(key):
                raise ValueError(f"Persona {name} needs {key}")
        return entry["runtime"]

    if flow.get("default_risk") not in RISKS:
        raise ValueError("default_risk must be one of P0..P3")
    kinds = flow.get("kinds", {"code": {}})
    if "code" not in kinds:
        raise ValueError("config/flow.json kinds must include code")
    for kind in kinds:
        cfg = kind_config(flow, kind)
        where = f"kinds.{kind}"
        if set(cfg) - set(DEFAULT_KIND) or set(cfg["roles"]) - ROLE_KEYS:
            raise ValueError(f"{where} has unknown keys")
        docs = cfg["docs"]
        if docs and (docs[0] != "prd" or len(set(docs)) != len(docs) or not set(docs) <= set(DOC_STAGES)):
            raise ValueError(f"{where}.docs must start with prd and use {', '.join(DOC_STAGES)} once each")
        if not set(cfg["gates"]) <= GATES or cfg["implement_protocol"] not in WRITE_PROTOCOLS:
            raise ValueError(f"{where} has an unknown gate or implement_protocol")
        persona(role(flow, kind, "triage"), f"{where} triage")
        for doc in docs:
            entry = role(flow, kind, doc)
            if not entry or not entry.get("reviewers"):
                raise ValueError(f"{where} needs an author and reviewers for {doc}")
            author = persona(entry["author"], f"{where} {doc}.author")
            for reviewer in entry["reviewers"]:
                if persona(reviewer, f"{where} {doc}.reviewers") == author:
                    raise ValueError(f"{doc} reviewer {binding(reviewer)[0]} must use a different runtime "
                                     f"from the author")
        for risk in RISKS:
            implementer = persona(role(flow, kind, "implement", risk), f"{where} implement.{risk}")
            if implementer == "antigravity":
                raise ValueError("Write roles must use codex or claude; Antigravity write mode is unverified")
            reviewers = role(flow, kind, "code_review", risk)
            if not reviewers:
                raise ValueError(f"{where} code_review.{risk} is empty")
            for reviewer in reviewers:
                name = binding(reviewer)[0]
                if persona(reviewer, f"{where} code_review.{risk}") == implementer:
                    raise ValueError(f"Code reviewer {name} must use a different runtime from implementer for {risk}")
                if personas[name].get("protocol", "code-review") not in PROTOCOLS:
                    raise ValueError(f"Persona {name} has an unknown review protocol")
    for risk in RISKS:
        gates = flow["gates"][risk]
        if not set(gates) <= GATES or "release" not in gates:
            raise ValueError(f"gates.{risk} must be a subset of {sorted(GATES)} and include release")
        if not isinstance(flow["docs"][risk], bool):
            raise ValueError(f"docs.{risk} must be true or false")
    for key in ("max_calls", "max_doc_rounds", "max_fix_rounds", "diff_limit_bytes", "test_timeout"):
        if not isinstance(flow.get(key), int) or flow[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    return flow
