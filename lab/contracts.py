"""Structured outputs and evidence checks shared by all three CLI adapters."""
import re


def obj(properties):
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": list(properties)}


def array(items):
    return {"type": "array", "items": items}


TEXT = {"type": "string"}
QUOTE = obj({"source_id": TEXT, "excerpt": TEXT})
ITEM = obj({"target": TEXT, "verdict": {"type": "string", "enum": ["supported", "contradicted", "unverified"]},
            "reason": TEXT, "evidence": array(QUOTE)})
AUDIT = obj({"summary": TEXT, "items": array(ITEM), "limitations": array(TEXT)})
REVIEW = obj({"summary": TEXT, "checked_targets": array(TEXT), "findings": array(obj({
    "id": TEXT, "target": TEXT, "kind": {"type": "string", "enum": ["contradiction", "missing_evidence", "interpretation", "scope"]},
    "severity": {"type": "string", "enum": ["major", "minor"]}, "reason": TEXT,
    "evidence": array(QUOTE), "resolution": TEXT})), "limitations": array(TEXT)})
ADJUDICATION = obj({**AUDIT["properties"], "review_resolutions": array(obj({
    "finding_id": TEXT, "disposition": {"type": "string", "enum": ["accepted", "rejected", "unresolved"]},
    "reason": TEXT, "evidence": array(QUOTE)}))})
SYNTHESIS = obj({"summary": TEXT, "recommendations": array(obj({
    "text": TEXT, "claim_refs": array(TEXT)})), "limitations": array(TEXT)})
SCHEMAS = {"audit": AUDIT, "review": REVIEW, "adjudication": ADJUDICATION, "synthesis": SYNTHESIS}
for name, schema in SCHEMAS.items():
    schema["title"] = name


def extract_sources(brief):
    matches = list(re.finditer(r"^Source ([A-Za-z][A-Za-z0-9_-]*)\b", brief, re.M))
    sources = {}
    for i, match in enumerate(matches):
        key = match.group(1)
        if key in sources:
            raise ValueError(f"Duplicate source ID: {key}")
        end = matches[i + 1].start() if i + 1 < len(matches) else len(brief)
        sources[key] = brief[match.start():end].strip()
    if not sources:
        raise ValueError("Brief must declare Source <ID> sections")
    return sources


def targets(report):
    return ["summary", *[c["id"] for c in report["claims"]], "limitations"]


def nonblank(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Empty required text")


def check_evidence(evidence, sources, required=False):
    if required and not evidence:
        raise ValueError("Supported/contradicted verdict requires source excerpts")
    for quote in evidence:
        nonblank(quote["excerpt"])
        source = sources.get(quote["source_id"])
        # Providers often unwrap source lines. Permit whitespace-only differences,
        # then store the exact original span; raw stdout/final.json remain unchanged.
        pattern = r"\s+".join(re.escape(part) for part in quote["excerpt"].split())
        match = re.search(pattern, source) if source is not None else None
        if match is None:
            raise ValueError("Evidence excerpt is absent from the locked source")
        quote["excerpt"] = match.group(0)


def exact_coverage(actual, expected):
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError("Output does not cover the assigned targets exactly once")


def validate_result(stage, result, sources, report=None, review=None, claim_refs=None):
    nonblank(result["summary"])
    for limitation in result["limitations"]:
        nonblank(limitation)
    if stage in {"audit", "adjudication"}:
        exact_coverage([i["target"] for i in result["items"]], targets(report))
        for item in result["items"]:
            nonblank(item["reason"])
            check_evidence(item["evidence"], sources, item["verdict"] != "unverified")
        if stage == "adjudication":
            findings = {f["id"]: f for f in review["findings"]}
            exact_coverage([r["finding_id"] for r in result["review_resolutions"]], findings)
            verdicts = {i["target"]: i["verdict"] for i in result["items"]}
            for resolution in result["review_resolutions"]:
                nonblank(resolution["reason"])
                check_evidence(resolution["evidence"], sources,
                               resolution["disposition"] == "rejected")
                finding = findings[resolution["finding_id"]]
                if (resolution["disposition"] == "accepted" and finding["severity"] == "major"
                        and verdicts[finding["target"]] == "supported"):
                    raise ValueError("Accepted major objection cannot leave its target supported")
    elif stage == "review":
        exact_coverage(result["checked_targets"], targets(report))
        ids = [f["id"] for f in result["findings"]]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate finding ID")
        for finding in result["findings"]:
            for key in ("id", "reason", "resolution"):
                nonblank(finding[key])
            if finding["target"] not in targets(report):
                raise ValueError("Unknown review target")
            check_evidence(finding["evidence"], sources, finding["kind"] == "contradiction")
    elif stage == "synthesis":
        for recommendation in result["recommendations"]:
            nonblank(recommendation["text"])
            refs = recommendation["claim_refs"]
            if not refs or not set(refs).issubset(claim_refs):
                raise ValueError("Recommendation cites missing claim references")
