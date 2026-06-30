"""
Step 3 -- Candidate matching.

Order: exact normalized email -> exact normalized phone -> fuzzy full-name
match, backed by resume-similarity overlap (skills / company / role
keywords) to disambiguate same-name rows. Uses difflib instead of
`rapidfuzz` (no network access to install it here); swap in
`rapidfuzz.fuzz.token_sort_ratio` for production -- the rest of the
pipeline only depends on getting a 0..1 similarity score back.
"""

from difflib import SequenceMatcher


def _name_similarity(a, b) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _token_overlap(a_tokens, b_tokens) -> float:
    a = {t.lower() for t in a_tokens if t}
    b = {t.lower() for t in b_tokens if t}
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _resume_similarity_to_csv(resume_norm: dict, csv_norm: dict) -> float:
    """CSV rows only carry company/title/job_role/resume_text -- compare what's there."""
    skill_names = [s["name"] for s in resume_norm.get("skills", [])]
    csv_text_tokens = " ".join(filter(None, [
        csv_norm.get("current_company"), csv_norm.get("title"),
        csv_norm.get("job_role"), csv_norm.get("resume_text"),
    ])).split()

    company_overlap = _token_overlap(
        [e.get("company") for e in resume_norm.get("experience", [])] + [csv_norm.get("current_company")],
        [csv_norm.get("current_company")],
    )
    role_overlap = _token_overlap(resume_norm.get("roles", []) + skill_names, csv_text_tokens)
    return max(company_overlap, role_overlap)


NAME_FUZZY_THRESHOLD = 0.6  # below this on name alone -> ambiguous, do not merge


def match_candidate(resume_norm: dict, csv_records_norm: list):
    """
    Returns a dict: {matched: bool, csv_record, confidence, method, reason}
    method in {"email", "phone", "name_unique", "name_fuzzy+similarity", "none"}
    """
    # 1) Email match (high confidence)
    if resume_norm.get("email"):
        for csv_rec in csv_records_norm:
            if csv_rec.get("email") and csv_rec["email"] == resume_norm["email"]:
                return {"matched": True, "csv_record": csv_rec, "confidence": 0.97,
                        "method": "email", "reason": "exact normalized email match"}

    # 2) Phone match (high confidence)
    if resume_norm.get("phone"):
        for csv_rec in csv_records_norm:
            if csv_rec.get("phone") and csv_rec["phone"] == resume_norm["phone"]:
                return {"matched": True, "csv_record": csv_rec, "confidence": 0.95,
                        "method": "phone", "reason": "exact normalized phone match"}

    # 3) Name-based matching
    resume_name = resume_norm.get("full_name")
    if not resume_name:
        return {"matched": False, "csv_record": None, "confidence": 0.0,
                "method": "none", "reason": "no email/phone/name available on resume"}

    same_name_rows = [c for c in csv_records_norm
                       if c.get("full_name") and c["full_name"].lower() == resume_name.lower()]

    if len(same_name_rows) == 1:
        return {"matched": True, "csv_record": same_name_rows[0], "confidence": 0.70,
                "method": "name_unique", "reason": "unique exact name match in CSV"}

    if len(same_name_rows) > 1:
        # Disambiguate with resume similarity (skills/company/role overlap).
        best, best_score = None, -1.0
        for c in same_name_rows:
            score = _resume_similarity_to_csv(resume_norm, c)
            if score > best_score:
                best, best_score = c, score
        if best is not None and best_score > 0:
            conf = min(0.65 + best_score * 0.2, 0.85)
            return {"matched": True, "csv_record": best, "confidence": conf,
                    "method": "name_fuzzy+similarity",
                    "reason": f"multiple same-name rows, resolved via similarity={best_score:.2f}"}
        return {"matched": False, "csv_record": None, "confidence": 0.4,
                "method": "name_ambiguous",
                "reason": "multiple same-name rows, no distinguishing similarity"}

    # 4) Fuzzy name (no exact name match at all)
    best, best_score = None, 0.0
    for c in csv_records_norm:
        if not c.get("full_name"):
            continue
        sim = _name_similarity(resume_name, c["full_name"])
        if sim > best_score:
            best, best_score = c, sim

    if best is not None and best_score >= NAME_FUZZY_THRESHOLD:
        sim_boost = _resume_similarity_to_csv(resume_norm, best)
        conf = min(0.45 + best_score * 0.25 + sim_boost * 0.15, 0.84)
        return {"matched": True, "csv_record": best, "confidence": conf,
                "method": "name_fuzzy+similarity",
                "reason": f"fuzzy name sim={best_score:.2f}"}

    return {"matched": False, "csv_record": None, "confidence": best_score,
            "method": "name_fuzzy_below_threshold",
            "reason": f"best fuzzy name sim={best_score:.2f} < {NAME_FUZZY_THRESHOLD}"}
