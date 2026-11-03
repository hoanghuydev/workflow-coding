"""Persona roster and risk policy: runtime (layer 1), model/effort (layer 2) and
persona/scope/permissions (layer 3) are configured independently."""
from .. import runtime
from .contracts import RISKS

GATES = {"prd", "techspec", "release"}
PROTOCOLS = {"code-review", "qa"}


def persona_cfg(persona, agents):
    """CLI config for one persona: the runtime's executable plus persona overrides."""
    base = agents[persona["runtime"]]
    return {"prefix": base["prefix"], "model": persona.get("model") or base["model"],
            "effort": persona["effort"] if "effort" in persona else base.get("effort")}


def check_roster(flow, personas, agents):
    """Reject a roster that breaks independence or gives write access to an unverified runtime."""
    def persona(name, where):
        if name not in personas:
            raise ValueError(f"Unknown persona {name!r} in {where}")
        entry = personas[name]
        if entry.get("runtime") not in agents:
            raise ValueError(f"Persona {name} uses an unconfigured runtime")
        if entry.get("effort") is not None and entry["effort"] not in runtime.EFFORTS:
            raise ValueError(f"Invalid effort for persona {name}")
        if entry.get("model") is not None and (not isinstance(entry["model"], str) or not entry["model"].strip()):
            raise ValueError(f"Invalid model for persona {name}")
        for key in ("role", "mindset", "scope", "escalation"):
            if not entry.get(key):
                raise ValueError(f"Persona {name} needs {key}")
        return entry["runtime"]

    roles = flow["roles"]
    persona(roles["triage"], "roles.triage")
    if flow.get("default_risk") not in RISKS:
        raise ValueError("default_risk must be one of P0..P3")
    for doc in ("prd", "techspec"):
        author = persona(roles[doc]["author"], f"roles.{doc}.author")
        if not roles[doc]["reviewers"]:
            raise ValueError(f"roles.{doc}.reviewers is empty")
        for reviewer in roles[doc]["reviewers"]:
            if persona(reviewer, f"roles.{doc}.reviewers") == author:
                raise ValueError(f"{doc} reviewer {reviewer} must use a different runtime from the author")
    for risk in RISKS:
        implementer = persona(roles["implement"][risk], f"roles.implement.{risk}")
        if implementer == "antigravity":
            raise ValueError("Write roles must use codex or claude; Antigravity write mode is unverified")
        reviewers = roles["code_review"][risk]
        if not reviewers:
            raise ValueError(f"roles.code_review.{risk} is empty")
        for reviewer in reviewers:
            if persona(reviewer, f"roles.code_review.{risk}") == implementer:
                raise ValueError(f"Code reviewer {reviewer} must use a different runtime from implementer for {risk}")
            if personas[reviewer].get("protocol", "code-review") not in PROTOCOLS:
                raise ValueError(f"Persona {reviewer} has an unknown review protocol")
        gates = flow["gates"][risk]
        if not set(gates) <= GATES or "release" not in gates:
            raise ValueError(f"gates.{risk} must be a subset of {sorted(GATES)} and include release")
        if not isinstance(flow["docs"][risk], bool):
            raise ValueError(f"docs.{risk} must be true or false")
    for key in ("max_calls", "max_doc_rounds", "max_fix_rounds", "diff_limit_bytes", "test_timeout"):
        if not isinstance(flow.get(key), int) or flow[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    return flow
