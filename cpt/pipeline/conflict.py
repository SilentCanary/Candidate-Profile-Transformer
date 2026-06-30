"""
Step 4 -- Conflict resolution.

Builds an `evidence` object per value: {field, value, source, method,
confidence, provenance}. Multi-value fields (emails, phones, skills,
certifications, experience) are accumulated/deduped/sorted by confidence.
Scalar fields (full_name, current_company, title, headline,
years_experience, location, education) pick one winner; the rejected value
is kept in provenance, never silently dropped.
"""

import hashlib
import re
import uuid

SENSITIVE_FIELDS = {"age", "gender", "race", "ethnicity", "sex", "marital_status"}


def _evidence(field, value, source, method, confidence, provenance=None):
    return {
        "field": field, "value": value, "source": source, "method": method,
        "confidence": round(confidence, 3),
        "provenance": provenance or [],
    }


# ---------------------------------------------------------------------------
# Scalar field resolution
# ---------------------------------------------------------------------------

def resolve_scalar(field_name, candidates):
    """
    candidates: list of (value, source, method, confidence, prefer_bias)
    prefer_bias is a small tiebreaker (e.g. CSV-preferred fields get a bump).
    Returns evidence dict for the winner, with rejected values in provenance.
    """
    valid = [c for c in candidates if c[0] not in (None, "", [])]
    if not valid:
        return _evidence(field_name, None, None, "no_valid_source", 0.0)

    # Specificity tiebreak for titles/roles: longer / superstring wins when close.
    def sort_key(c):
        value, source, method, confidence, bias = c
        specificity = len(str(value)) if isinstance(value, str) else 0
        return (round(confidence + bias, 3), specificity)

    valid.sort(key=sort_key, reverse=True)
    winner = valid[0]
    rejected = valid[1:]

    confidence = winner[3] + winner[4]
    # Agreement boost: if two sources produced the same value, bump confidence.
    same_value_other_source = any(
        str(r[0]).strip().lower() == str(winner[0]).strip().lower() and r[1] != winner[1]
        for r in rejected
    )
    if same_value_other_source:
        confidence = min(confidence + 0.1, 0.99)

    provenance = [{"value": r[0], "source": r[1], "method": r[2], "confidence": round(r[3], 3)}
                  for r in rejected]
    return _evidence(field_name, winner[0], winner[1], winner[2], min(confidence, 0.99), provenance)


def resolve_full_name(csv_norm, resume_norm, match_info):
    candidates = []
    if csv_norm.get("full_name"):
        candidates.append((csv_norm["full_name"], "csv", "direct_field", 0.75, 0.0))
    if resume_norm.get("full_name"):
        candidates.append((resume_norm["full_name"], "resume", "direct_field", 0.75, 0.0))
    return resolve_scalar("full_name", candidates)


def resolve_company_title(csv_norm, resume_norm):
    """CSV current_company wins on conflict; resume's company goes to experience
    (handled by resolve_experience). Title: prefer more specific when confidence close."""
    company_candidates = []
    if csv_norm.get("current_company"):
        company_candidates.append((csv_norm["current_company"], "csv", "recruiter_direct_field", 0.85, 0.05))
    current_company_ev = resolve_scalar("current_company", company_candidates)

    title_candidates = []
    if csv_norm.get("title"):
        title_candidates.append((csv_norm["title"], "csv", "recruiter_direct_field", 0.80, 0.0))
    resume_titles = [e.get("title") for e in resume_norm.get("experience", []) if e.get("title")]
    if resume_titles:
        # Most specific (longest) resume title as candidate.
        best_resume_title = max(resume_titles, key=len)
        title_candidates.append((best_resume_title, "resume", "experience_entry", 0.65, 0.0))
    title_ev = resolve_scalar("title", title_candidates)

    return current_company_ev, title_ev


def resolve_years_experience(resume_norm):
    """Conservative: explicit statement > computed from clear dates > null."""
    text = (resume_norm.get("raw_text") or "").lower()
    import re
    m = re.search(r"(\d{1,2})\+?\s*years?\s+(of\s+)?experience", text)
    if m:
        return _evidence("years_experience", int(m.group(1)), "resume", "explicit_statement", 0.9)

    spans = []
    for e in resume_norm.get("experience", []):
        start, end = e.get("start"), e.get("end")
        if start and end and len(start) == 7 and (end == "present" or len(end) == 7):
            spans.append((start, end))
    if not spans:
        return _evidence("years_experience", None, None, "ambiguous_dates", 0.0)

    import datetime
    months = 0
    for start, end in spans:
        sy, sm = map(int, start.split("-"))
        if end == "present":
            ey, em = datetime.date.today().year, datetime.date.today().month
        else:
            ey, em = map(int, end.split("-"))
        months += max((ey - sy) * 12 + (em - sm), 0)
    years = round(months / 12, 1)
    return _evidence("years_experience", years, "resume", "computed_from_dates", 0.7)


# ---------------------------------------------------------------------------
# Multi-value field resolution
# ---------------------------------------------------------------------------

def resolve_emails(csv_norm, resume_norm):
    items = []
    if csv_norm.get("email"):
        items.append(_evidence("emails", csv_norm["email"], "csv", "direct_field", 0.9))
    elif csv_norm.get("email_raw"):
        items.append(_evidence("emails", csv_norm["email_raw"], "csv", "invalid_format", 0.0))
    if resume_norm.get("email"):
        items.append(_evidence("emails", resume_norm["email"], "resume", "extracted", 0.85))
    elif resume_norm.get("email_raw"):
        items.append(_evidence("emails", resume_norm["email_raw"], "resume", "invalid_format", 0.0))

    # Dedupe (case-insensitive), keep highest confidence, boost if both sources agree.
    by_value = {}
    for it in items:
        if it["value"] is None:
            continue
        key = str(it["value"]).lower()
        if key not in by_value:
            by_value[key] = it
        else:
            existing = by_value[key]
            existing["confidence"] = min(max(existing["confidence"], it["confidence"]) + 0.05, 0.99)
            existing["provenance"].append({"source": it["source"], "method": it["method"]})

    return sorted(by_value.values(), key=lambda e: e["confidence"], reverse=True)


def resolve_phones(csv_norm, resume_norm):
    items = []
    if csv_norm.get("phone"):
        items.append(_evidence("phones", csv_norm["phone"], "csv", "direct_field", 0.9,
                                provenance=[{"region_inferred": csv_norm.get("phone_region_inferred", False)}]))
    if resume_norm.get("phone"):
        items.append(_evidence("phones", resume_norm["phone"], "resume", "extracted", 0.8,
                                provenance=[{"region_inferred": resume_norm.get("phone_region_inferred", False)}]))

    by_value = {}
    for it in items:
        if it["value"] is None:
            continue
        if it["value"] not in by_value:
            by_value[it["value"]] = it
        else:
            existing = by_value[it["value"]]
            existing["confidence"] = min(max(existing["confidence"], it["confidence"]) + 0.05, 0.99)

    return sorted(by_value.values(), key=lambda e: e["confidence"], reverse=True)


def resolve_skills(csv_norm, resume_norm):
    """Cross-references skills mentioned in the CSV's free-text resume_text
    against the uploaded resume's skill list. Two extraction passes on the
    CSV text: (1) a structured 'Proficient in X, Y, Z, with...' pattern
    (common in ATS exports / this dataset's generator), and (2) a scan for
    any known alias-dictionary term, as a fallback for less structured text."""
    import re
    from .skills_alias import canonicalize_skill, SKILL_ALIASES, SOFT_SKILLS

    csv_skills = set()
    csv_text = csv_norm.get("resume_text") or ""

    m = re.search(r"proficient in\s+(.+?)(?:,?\s*with\s)", csv_text, re.I)
    if m:
        for raw_skill in m.group(1).split(","):
            raw_skill = raw_skill.strip()
            if not raw_skill or raw_skill.lower() in SOFT_SKILLS:
                continue
            canon, _, is_soft = canonicalize_skill(raw_skill)
            if canon and not is_soft:
                csv_skills.add(canon)

    csv_text_lower = csv_text.lower()
    for alias in SKILL_ALIASES:
        if re.search(r"\b" + re.escape(alias) + r"\b", csv_text_lower):
            canon, _, _ = canonicalize_skill(alias)
            csv_skills.add(canon)

    resume_skill_names = {s["name"] for s in resume_norm.get("skills", [])}

    all_names = csv_skills | resume_skill_names
    out = []
    for name in sorted(all_names):
        in_csv = name in csv_skills
        in_resume = name in resume_skill_names
        if in_csv and in_resume:
            confidence, sources = 0.9, ["csv", "resume"]
        else:
            confidence, sources = 0.55, ["csv"] if in_csv else ["resume"]
        out.append({"name": name, "confidence": confidence, "sources": sources})
    return sorted(out, key=lambda s: s["confidence"], reverse=True)


def resolve_experience(csv_norm, resume_norm, current_company_value):
    """Accumulate resume experience entries; dedupe on (company+title+start).
    If the CSV current_company differs from a resume entry, that resume entry
    stays here (full history), current_company itself is the CSV-trusted scalar."""
    entries = []
    seen_keys = set()
    for e in resume_norm.get("experience", []):
        key = (
            (e.get("company") or "").strip().lower(),
            (e.get("title") or "").strip().lower(),
            e.get("start"),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        entries.append({
            "company": e.get("company"), "title": e.get("title"),
            "start": e.get("start"), "end": e.get("end"),
            "summary": e.get("summary"), "source": "resume",
        })

    # If CSV's current_company/title isn't already represented, add it as the
    # most-current entry (recruiter-known current status).
    if current_company_value and not any(
        (en["company"] or "").lower() == current_company_value.lower() for en in entries
    ):
        entries.insert(0, {
            "company": current_company_value, "title": csv_norm.get("title"),
            "start": None, "end": "present", "summary": None, "source": "csv",
        })
    return entries


def resolve_education(csv_norm, resume_norm):
    """Resume preferred; CSV used only if resume has none. No degree inference
    beyond what was explicitly extracted (a project mention is not a degree)."""
    if resume_norm.get("education"):
        return [dict(e, source="resume") for e in resume_norm["education"]]
    # CSV doesn't carry structured education in this schema; nothing to fall back to.
    return []


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

def resolve_location(csv_norm, resume_norm):
    """CSV location (if the CSV export carries city/region/country columns) is
    treated like other recruiter-maintained fields and preferred; the
    resume's extracted location is used only as a fallback -- never blended
    field-by-field (a resume mentioning only a country shouldn't get a city
    invented from an unrelated CSV value)."""
    csv_loc = csv_norm.get("location") or {}
    resume_loc = resume_norm.get("location") or {}

    csv_has_data = any(csv_loc.get(k) for k in ("city", "region", "country"))
    resume_has_data = any(resume_loc.get(k) for k in ("city", "region", "country"))

    if csv_has_data and resume_has_data:
        same_city = (csv_loc.get("city") or "").lower() == (resume_loc.get("city") or "").lower()
        confidence = 0.9 if same_city else 0.75
        provenance = [{"value": resume_loc, "source": "resume", "method": "extracted"}]
        return _evidence("location", csv_loc, "csv", "recruiter_direct_field", confidence, provenance)
    if csv_has_data:
        return _evidence("location", csv_loc, "csv", "recruiter_direct_field", 0.8)
    if resume_has_data:
        return _evidence("location", resume_loc, "resume", "extracted", 0.55)
    return _evidence("location", {"city": None, "region": None, "country": None}, None, "no_source", 0.0)


# ---------------------------------------------------------------------------
# Overall profile confidence
# ---------------------------------------------------------------------------

def compute_overall_confidence(profile: dict) -> float:
    """Unweighted average of every field/item confidence we actually have
    real evidence for (fields with no source at all are skipped rather than
    dragging the average toward 0, so 'no data available' doesn't read the
    same as 'low-quality data')."""
    scores = []

    def collect(node):
        if isinstance(node, dict):
            if "confidence" in node and "value" in node and "source" in node:
                if node.get("source") is not None:
                    scores.append(node["confidence"])
            else:
                for v in node.values():
                    collect(v)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict) and "confidence" in item and "sources" in item:
                    scores.append(item["confidence"])  # skills entries
                else:
                    collect(item)

    collect({k: v for k, v in profile.items() if not k.startswith("_")})
    return round(sum(scores) / len(scores), 3) if scores else 0.0


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _deterministic_candidate_id(csv_norm, resume_norm, match_info):
    """Stable UUID derived from the best available identity anchor, so the
    same inputs always produce the same candidate_id (required for
    deterministic/explainable output). Falls back through email -> phone ->
    full_name -> source file path so even an unmatched single-source resume
    still gets a stable id across reruns."""
    anchor = (
        (match_info.get("csv_record") or {}).get("email")
        or resume_norm.get("email")
        or (match_info.get("csv_record") or {}).get("phone")
        or resume_norm.get("phone")
        or resume_norm.get("full_name")
        or resume_norm.get("_path")
        or "unknown"
    )
    digest = hashlib.sha1(str(anchor).strip().lower().encode("utf-8")).hexdigest()
    return str(uuid.UUID(digest[:32]))


def build_canonical_profile(csv_norm: dict, resume_norm: dict, match_info: dict) -> dict:
    full_name_ev = resolve_full_name(csv_norm, resume_norm, match_info)
    emails_ev = resolve_emails(csv_norm, resume_norm)
    phones_ev = resolve_phones(csv_norm, resume_norm)
    current_company_ev, title_ev = resolve_company_title(csv_norm, resume_norm)
    skills = resolve_skills(csv_norm, resume_norm)
    experience = resolve_experience(csv_norm, resume_norm, current_company_ev["value"])
    education = resolve_education(csv_norm, resume_norm)
    years_exp_ev = resolve_years_experience(resume_norm)

    location_ev = resolve_location(csv_norm, resume_norm)

    links = resume_norm.get("links") or {}
    other_links = links.get("other", [])
    portfolio = next((u for u in other_links if re.search(r"portfolio|\.me/|\.dev/|behance|dribbble", u, re.I)), None)
    other_links_filtered = [u for u in other_links if u != portfolio]

    profile = {
        "candidate_id": _deterministic_candidate_id(csv_norm, resume_norm, match_info),
        "full_name": full_name_ev,
        "emails": emails_ev,
        "phones": phones_ev,
        "location": location_ev,
        "links": {
            "linkedin": links.get("linkedin"), "github": links.get("github"),
            "portfolio": portfolio, "other": other_links_filtered,
        },
        "headline": _evidence("headline", csv_norm.get("job_role") or title_ev["value"],
                               "csv" if csv_norm.get("job_role") else title_ev["source"],
                               "direct_field", 0.6 if csv_norm.get("job_role") else title_ev["confidence"]),
        "years_experience": years_exp_ev,
        "skills": skills,
        "experience": experience,
        "education": education,
        "certifications": sorted(set(resume_norm.get("certs", []))),
        "current_company": current_company_ev,
        "title": title_ev,
        "_match": match_info,
    }
    profile["confidence"] = compute_overall_confidence(profile)
    return profile
