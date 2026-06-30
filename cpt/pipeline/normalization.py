"""
Field normalization, applied independently to each source (CSV row / resume
record) before any matching or merging happens.

NOTE on phone numbers: the original design calls for the `phonenumbers`
library for true E.164 validation/formatting. This sandbox has no network
access to install it, so a regex-based approximation is used instead
(`normalize_phone`). It supports the common shapes (+countrycode, leading 0,
10-digit local) and defaults the region to IN when no country code is
present -- swap in `phonenumbers.parse(...)` / `format_number(...,
PhoneNumberFormat.E164)` for production use; the rest of the pipeline is
agnostic to which implementation produces the E.164 string.
"""

import re

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

DEFAULT_REGION_CALLING_CODE = "91"  # India, matches sample data / user context


def normalize_name(raw: str):
    if not raw or not str(raw).strip():
        return None
    cleaned = re.sub(r"\s+", " ", str(raw).strip())
    # Title-case but keep already-capitalized acronyms (e.g. "PV" in names) intact-ish.
    parts = [p[:1].upper() + p[1:].lower() if p.isalpha() else p for p in cleaned.split(" ")]
    return " ".join(parts)


def normalize_email(raw: str):
    """Returns (email_or_None, is_valid)."""
    if not raw or not str(raw).strip():
        return None, False
    email = str(raw).strip().lower()
    is_valid = bool(EMAIL_RE.match(email))
    return email, is_valid


def normalize_phone(raw: str, default_calling_code: str = DEFAULT_REGION_CALLING_CODE):
    """
    Best-effort E.164 normalization without the `phonenumbers` lib.
    Returns (e164_or_None, is_valid, region_inferred: bool)
    """
    if not raw or not str(raw).strip():
        return None, False, False

    digits = re.sub(r"[^\d+]", "", str(raw).strip())
    region_inferred = False

    if digits.startswith("+"):
        national = digits[1:]
    elif digits.startswith("00"):
        national = digits[2:]
    else:
        # No explicit country code present -> infer default region.
        national = digits.lstrip("0")
        digits = "+" + default_calling_code + national
        region_inferred = True
        national = default_calling_code + national

    candidate = "+" + national if not digits.startswith("+") else digits
    digit_count = len(re.sub(r"\D", "", candidate))
    is_valid = 8 <= digit_count <= 15
    if not is_valid:
        return None, False, region_inferred
    return candidate, True, region_inferred


def normalize_date(raw: str):
    """Standardize to YYYY-MM. Partial dates (year only) fill MM=01."""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()

    m = re.match(r"^(\d{4})-(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"

    m = re.match(r"^(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"

    m = re.match(r"^(\d{4})$", s)
    if m:
        return f"{m.group(1)}-01"

    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    m = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{4})$", s)
    if m:
        mon = months.get(m.group(1)[:3].lower())
        if mon:
            return f"{m.group(2)}-{mon:02d}"

    if s.lower() in ("present", "current", "now", "ongoing"):
        return "present"

    return None  # ambiguous / unparseable -> honestly-empty


def is_present(date_str: str) -> bool:
    return date_str == "present"
