"""Step 2 -- apply field normalization to each raw source record, independently."""

from .normalization import normalize_name, normalize_email, normalize_phone, normalize_date
from .skills_alias import canonicalize_skill
from .geo import country_to_alpha2, CALLING_CODE_TO_ALPHA2


def normalize_csv_record(raw: dict) -> dict:
    name = normalize_name(raw.get("name"))
    email, email_valid = normalize_email(raw.get("email"))
    phone, phone_valid, region_inferred = normalize_phone(raw.get("phone"))

    return {
        "_source": "csv",
        "_row_index": raw.get("_row_index"),
        "full_name": name,
        "email": email if email_valid else None,
        "email_valid": email_valid,
        "email_raw": raw.get("email"),
        "phone": phone if phone_valid else None,
        "phone_valid": phone_valid,
        "phone_region_inferred": region_inferred,
        "phone_raw": raw.get("phone"),
        "current_company": (raw.get("current_company") or "").strip() or None,
        "title": (raw.get("title") or "").strip() or None,
        "job_role": (raw.get("job_role") or "").strip() or None,
        "resume_text": raw.get("resume_text"),
        "location": {
            "city": (raw.get("city") or "").strip() or None,
            "region": (raw.get("region") or raw.get("state") or "").strip() or None,
            "country": country_to_alpha2(raw.get("country")) if raw.get("country") else None,
        },
    }


def _normalize_skills(skill_list):
    out = []
    seen = set()
    for s in skill_list or []:
        canon, is_known, is_soft = canonicalize_skill(s)
        if is_soft or canon is None:
            continue
        if canon.lower() in seen:
            continue
        seen.add(canon.lower())
        out.append({"name": canon, "is_known_alias": is_known})
    return out


def _normalize_experience(exp_list):
    out = []
    for e in exp_list or []:
        out.append({
            "company": (e.get("company") or "").strip() or None,
            "title": (e.get("title") or "").strip() or None,
            "start": normalize_date(e.get("start")),
            "end": normalize_date(e.get("end")),
            "summary": e.get("summary"),
        })
    return out


def _normalize_education(edu_list):
    out = []
    for e in edu_list or []:
        out.append({
            "institution": e.get("institution"),
            "degree": e.get("degree"),
            "field": e.get("field"),
            "end": normalize_date(e.get("end")) if e.get("end") else None,
        })
    return out


def normalize_resume_record(raw: dict) -> dict:
    name = normalize_name(raw.get("name"))
    email, email_valid = normalize_email(raw.get("email"))
    phone, phone_valid, region_inferred = normalize_phone(raw.get("phone"))

    links = raw.get("links") or {}
    raw_location = raw.get("location") or {}
    location = {
        "city": raw_location.get("city"),
        "region": raw_location.get("region"),
        "country": country_to_alpha2(raw_location.get("country")) if raw_location.get("country") else None,
    }

    return {
        "_source": "resume",
        "_path": raw.get("_path"),
        "full_name": name,
        "email": email if email_valid else None,
        "email_valid": email_valid,
        "email_raw": raw.get("email"),
        "phone": phone if phone_valid else None,
        "phone_valid": phone_valid,
        "phone_region_inferred": region_inferred,
        "phone_raw": raw.get("phone"),
        "links": {
            "linkedin": links.get("linkedin"),
            "github": links.get("github"),
            "other": links.get("other") or [],
        },
        "location": location,
        "skills": _normalize_skills(raw.get("skills")),
        "education": _normalize_education(raw.get("education")),
        "certs": raw.get("certs") or [],
        "experience": _normalize_experience(raw.get("experience")),
        "roles": raw.get("roles") or [],
        "raw_text": raw.get("raw_text", ""),
    }
