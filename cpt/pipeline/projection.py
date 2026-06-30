"""
Step 5 -- Projection (runtime config) + final validation.

Same canonical profile, zero code changes needed to reshape output: the
config selects fields, renames via `from` paths, applies per-field
normalization, toggles confidence/provenance, and decides how to handle
missing values (null | omit | error).
"""

import re

DEFAULT_CONFIG = {
    "fields": [
        {"path": "candidate_id", "from": "candidate_id", "type": "string", "required": True},
        {"path": "full_name", "from": "full_name", "type": "string", "required": True},
        {"path": "emails", "from": "emails[].value", "type": "string[]"},
        {"path": "phones", "from": "phones[].value", "type": "string[]"},
        {"path": "location", "from": "location", "type": "object"},
        {"path": "links", "from": "links", "type": "object"},
        {"path": "headline", "from": "headline", "type": "string"},
        {"path": "years_experience", "from": "years_experience", "type": "number"},
        {"path": "skills", "from": "skills", "type": "object[]"},
        {"path": "experience", "from": "experience", "type": "object[]"},
        {"path": "education", "from": "education", "type": "object[]"},
        {"path": "certifications", "from": "certifications", "type": "string[]"},
        {"path": "current_company", "from": "current_company", "type": "string"},
        {"path": "title", "from": "title", "type": "string"},
        {"path": "overall_confidence", "from": "confidence", "type": "number"},
    ],
    "include_confidence": True,
    "include_provenance": False,
    "on_missing": "null",
}


def _is_evidence(node):
    return isinstance(node, dict) and "value" in node and "confidence" in node and "field" in node


def _strip_evidence(node, include_confidence, include_provenance):
    """Recursively unwrap evidence objects -> plain values, optionally keeping
    confidence/provenance alongside."""
    if _is_evidence(node):
        value = _strip_evidence(node["value"], include_confidence, include_provenance)
        if not include_confidence and not include_provenance:
            return value
        out = {"value": value}
        if include_confidence:
            out["confidence"] = node["confidence"]
        if include_provenance:
            out["provenance"] = node.get("provenance", [])
        return out
    if isinstance(node, list):
        return [_strip_evidence(n, include_confidence, include_provenance) for n in node]
    if isinstance(node, dict):
        return {k: _strip_evidence(v, include_confidence, include_provenance)
                for k, v in node.items() if not k.startswith("_")}
    return node


def _get_path(profile, path):
    """Resolve dotted/bracketed paths like 'emails[0].value', 'skills[].name',
    'links.linkedin', 'full_name.value'."""
    tokens = re.findall(r"[^.\[\]]+|\[\]|\[\d+\]", path)
    current = [profile]
    saw_wildcard = False
    for tok in tokens:
        nxt = []
        if tok == "[]":
            saw_wildcard = True
            for c in current:
                if isinstance(c, list):
                    nxt.extend(c)
        elif re.match(r"^\[\d+\]$", tok):
            idx = int(tok[1:-1])
            for c in current:
                if isinstance(c, list) and len(c) > idx:
                    nxt.append(c[idx])
        else:
            for c in current:
                if isinstance(c, dict) and tok in c:
                    nxt.append(c[tok])
        current = nxt
        if not current:
            return [] if saw_wildcard else None
    if saw_wildcard:
        return current  # always a list when a [] wildcard was used in the path
    if len(current) == 1:
        return current[0]
    return current


def _normalize_value(value, kind):
    if value is None:
        return value
    if kind == "E164":
        return value if isinstance(value, str) and value.startswith("+") else value
    if kind == "canonical":
        return value  # already canonicalized upstream (skills_alias)
    return value


def apply_projection(canonical_profile: dict, config: dict = None) -> dict:
    config = config or DEFAULT_CONFIG
    include_confidence = config.get("include_confidence", False)
    include_provenance = config.get("include_provenance", False)
    on_missing = config.get("on_missing", "null")

    plain = _strip_evidence(canonical_profile, include_confidence=True, include_provenance=True)

    output = {}
    errors = []
    for field_cfg in config.get("fields", []):
        out_path = field_cfg["path"]
        from_path = field_cfg.get("from", out_path)
        required = field_cfg.get("required", False)
        normalize_kind = field_cfg.get("normalize")

        raw = _get_path(plain, from_path)

        # Unwrap {value, confidence, provenance} wrapper produced by _strip_evidence,
        # respecting this field's own confidence/provenance toggle if specified,
        # else falling back to the global config.
        field_include_conf = field_cfg.get("include_confidence", include_confidence)
        field_include_prov = field_cfg.get("include_provenance", include_provenance)

        def unwrap(node):
            if isinstance(node, dict) and set(node.keys()) <= {"value", "confidence", "provenance"} and "value" in node:
                val = node["value"]
                if not field_include_conf and not field_include_prov:
                    return val
                out = {"value": val}
                if field_include_conf and "confidence" in node:
                    out["confidence"] = node["confidence"]
                if field_include_prov and "provenance" in node:
                    out["provenance"] = node["provenance"]
                return out
            if isinstance(node, list):
                return [unwrap(n) for n in node]
            return node

        value = unwrap(raw)
        if normalize_kind and value is not None:
            if isinstance(value, list):
                value = [_normalize_value(v, normalize_kind) for v in value]
            else:
                value = _normalize_value(value, normalize_kind)

        is_missing = value is None or value == [] or value == {}
        if is_missing:
            if required and on_missing == "error":
                errors.append(f"required field '{out_path}' is missing")
                continue
            if on_missing == "omit":
                continue
            output[out_path] = None
        else:
            output[out_path] = value

    if errors:
        raise ValueError("Projection validation failed: " + "; ".join(errors))

    return output


def validate_output(output: dict, config: dict = None) -> list:
    """Returns a list of validation error strings (empty list == valid)."""
    config = config or DEFAULT_CONFIG
    errors = []
    field_paths = {f["path"] for f in config.get("fields", [])}
    for f in config.get("fields", []):
        if f.get("required") and f["path"] not in output:
            errors.append(f"missing required field: {f['path']}")
    for k in output:
        if k not in field_paths:
            errors.append(f"unexpected field in output: {k}")
    return errors
