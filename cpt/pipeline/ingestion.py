"""
Step 1 -- Ingestion.

Structured source: recruiter CSV, read via pandas, one row -> one source record.
Unstructured source: resume file (PDF/DOCX/TXT) -> plain text -> heuristically
parsed into name/email/phone/links/skills/education/certs/experience/roles.
"""

import os
import re
import pandas as pd

from .skills_alias import SKILL_ALIASES, SOFT_SKILLS

CSV_EXPECTED_COLUMNS = [
    "name", "email", "phone", "current_company", "title", "job_role", "resume_text",
]


# ---------------------------------------------------------------------------
# Structured CSV ingestion
# ---------------------------------------------------------------------------

SENSITIVE_COLUMNS = {"age", "gender", "race", "ethnicity", "sex", "marital_status", "religion", "disability"}


def split_sensitive_metadata(raw_row: dict):
    """Sensitive attributes (if a CSV happens to include them) are pulled out as
    protected metadata: never used for matching/scoring/conflict resolution and
    excluded from default output. Returned separately for audit-only use."""
    sensitive = {k: v for k, v in raw_row.items() if k in SENSITIVE_COLUMNS and v not in (None, "")}
    return sensitive


def load_csv(path: str):
    """Read recruiter CSV via pandas -> list of raw row dicts. Missing file/
    malformed rows must not crash the run."""
    if not path or not os.path.exists(path):
        return []
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return []

    df.columns = [c.strip().lower() for c in df.columns]
    records = []
    for i, row in df.iterrows():
        rec = {col: (row[col].strip() if col in row and isinstance(row[col], str) else None)
               for col in df.columns}
        rec = {k: (v if v not in ("", None) else None) for k, v in rec.items()}
        rec["_row_index"] = int(i)
        rec["_source"] = "csv"
        rec["_protected_metadata"] = split_sensitive_metadata(rec)
        records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Unstructured resume ingestion
# ---------------------------------------------------------------------------

def extract_text(path: str) -> str:
    """Convert a PDF/DOCX/TXT file to plain text. Returns '' on any failure
    (missing/corrupt file) rather than raising -- a bad source must not crash
    the run."""
    if not path or not os.path.exists(path):
        return ""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".txt":
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        elif ext == ".docx":
            import docx
            d = docx.Document(path)
            return "\n".join(p.text for p in d.paragraphs)
        elif ext == ".pdf":
            import pdfplumber
            text_parts = []
            link_uris = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
                    for link in (getattr(page, "hyperlinks", None) or []):
                        uri = link.get("uri")
                        if uri:
                            link_uris.append(uri)
            full_text = "\n".join(text_parts)
            if link_uris:
                # Hyperlinked text like "LinkedIn"/"GitHub" often has no visible
                # URL -- pdfplumber's extract_text() won't surface it, only the
                # annotation does. Append so the existing link regexes still find it.
                full_text += "\n" + "\n".join(link_uris)
            return full_text
    except Exception:
        return ""
    return ""


EMAIL_FIND_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_FIND_RE = re.compile(r"(\+?\d[\d\-\s().]{7,}\d)")
LINKEDIN_RE = re.compile(r"(https?://)?(www\.)?linkedin\.com/\S+", re.I)
GITHUB_RE = re.compile(r"(https?://)?(www\.)?github\.com/\S+", re.I)
URL_RE = re.compile(r"https?://\S+")

DEGREE_KEYWORDS = [
    "b.tech", "btech", "bachelor", "b.sc", "bsc", "b.e", "be ", "m.tech", "mtech",
    "master", "m.sc", "msc", "mba", "phd", "ph.d", "associate degree", "diploma",
]

EDU_LINE_RE = re.compile(
    r"(?P<degree>b\.?\s?tech|bachelor[^,\n]*|b\.?\s?sc|m\.?\s?tech|master[^,\n]*|"
    r"m\.?\s?sc|mba|phd|ph\.?d|diploma)[^\n,]*?(?:in\s+(?P<field>[A-Za-z &]+))?"
    r"(?:,?\s*(?P<inst>[A-Z][A-Za-z .&]+(?:University|Institute|College|IIT|NIT)[A-Za-z .&]*))?",
    re.I,
)


LOCATION_LABEL_RE = re.compile(r"^(location|based in|address)\s*[:\-]\s*(?P<loc>.+)$", re.I)
# "City, Region" or "City, Country" near the top of the resume (header block).
LOCATION_LINE_RE = re.compile(r"^([A-Z][a-zA-Z .]+),\s*([A-Z][a-zA-Z .]+)$")


def _extract_location(lines: list):
    """Best-effort location extraction: an explicit 'Location:'/'Based in:'
    line anywhere, else a 'City, Region' style line in the header (first 6
    lines), skipping lines that are clearly links/emails/phones."""
    for line in lines:
        m = LOCATION_LABEL_RE.match(line.strip())
        if m:
            parts = [p.strip() for p in m.group("loc").split(",")]
            if len(parts) >= 2:
                return {"city": parts[0], "region": parts[1] if len(parts) > 2 else None,
                        "country": parts[-1]}
            return {"city": parts[0], "region": None, "country": None}

    for line in lines[:6]:
        if EMAIL_FIND_RE.search(line) or URL_RE.search(line) or PHONE_FIND_RE.search(line):
            continue
        m = LOCATION_LINE_RE.match(line.strip())
        if m:
            return {"city": m.group(1).strip(), "region": None, "country": m.group(2).strip()}
    return {"city": None, "region": None, "country": None}


def _first(pattern, text):
    m = pattern.search(text)
    return m.group(0).strip() if m else None


SECTION_HEADER_RE = re.compile(
    r"^(PROFESSIONAL SUMMARY|SUMMARY|OBJECTIVE|EDUCATION|SKILLS|TECHNICAL SKILLS|"
    r"CORE SKILLS|EXPERIENCE|WORK EXPERIENCE|PROFESSIONAL EXPERIENCE|PROJECTS|"
    r"CERTIFICATIONS?|CERTIFICATES|AWARDS|PUBLICATIONS|LANGUAGES|INTERESTS)\s*:?\s*$",
    re.I,
)


def _split_sections(lines: list) -> dict:
    """Split resume lines into {SECTION_NAME: [lines]} using recognizable
    ALL-CAPS-style header lines as boundaries, rather than assuming blank
    lines separate sections (many PDF text extractions -- including
    ReportLab/pdfplumber output -- have no blank lines between visually
    distinct sections at all)."""
    sections = {"_header": []}
    current = "_header"
    for line in lines:
        m = SECTION_HEADER_RE.match(line.strip())
        if m:
            current = m.group(1).upper()
            sections.setdefault(current, [])
        else:
            sections[current].append(line)
    return sections


def _section_text(sections: dict, *name_fragments: str) -> str:
    """Returns the joined text of the first section whose header contains any
    of the given fragments (e.g. 'SKILL' matches 'SKILLS'/'TECHNICAL SKILLS')."""
    for header, lines in sections.items():
        if any(frag in header for frag in name_fragments):
            return "\n".join(lines)
    return ""


def parse_resume(text: str) -> dict:
    """Heuristic resume parser -> raw source record (same shape family as the
    CSV record, with resume-specific extras)."""
    if not text or not text.strip():
        return {
            "_source": "resume", "name": None, "email": None, "phone": None,
            "links": {}, "location": {"city": None, "region": None, "country": None},
            "skills": [], "education": [], "certs": [],
            "experience": [], "roles": [], "raw_text": "",
        }

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    name = lines[0] if lines and len(lines[0].split()) <= 5 and not EMAIL_FIND_RE.search(lines[0]) else None

    email = _first(EMAIL_FIND_RE, text)
    phone_match = PHONE_FIND_RE.search(text)
    phone = phone_match.group(0).strip() if phone_match else None

    linkedin = _first(LINKEDIN_RE, text)
    github = _first(GITHUB_RE, text)
    other_links = [u for u in URL_RE.findall(text) if "linkedin.com" not in u and "github.com" not in u]
    location = _extract_location(lines)

    sections = _split_sections(lines)

    # Skills: prefer a dedicated section; fall back to scanning the whole
    # document for known aliases if no section header was found at all.
    skills_found = set()
    skills_text = _section_text(sections, "SKILL")
    if not skills_text:
        inline = re.search(r"^skills?\s*:\s*(.+)$", text, re.I | re.M)
        if inline:
            skills_text = inline.group(1)
    if skills_text:
        for raw_line in skills_text.splitlines():
            # Strip a leading "Label:" or "Label<2+ spaces>" prefix (common in
            # tabular skill blocks, e.g. "Languages: Python, C++, Java") so the
            # category label itself doesn't get mistaken for a skill. PDF text
            # extraction can collapse multi-space gaps to a single space, so
            # the colon form is the more reliable signal; both are handled.
            cleaned_line = re.sub(r"^[A-Za-z /&]{2,25}:\s*", "", raw_line)
            cleaned_line = re.sub(r"^[A-Za-z /&]{2,25}?\s{2,}", "", cleaned_line)
            for tok in re.split(r"[,/|•;]+", cleaned_line):
                tok = tok.strip(" .-")
                if not tok or len(tok) > 40 or tok.lower() in SOFT_SKILLS:
                    continue
                skills_found.add(tok)
    else:
        lowered = text.lower()
        for alias in SKILL_ALIASES:
            if re.search(r"\b" + re.escape(alias) + r"\b", lowered):
                skills_found.add(alias)

    # Education: search within an EDUCATION section if present, else whole text.
    education = []
    edu_text = _section_text(sections, "EDUCATION") or text
    for m in EDU_LINE_RE.finditer(edu_text):
        education.append({
            "degree": (m.group("degree") or "").strip().title() or None,
            "field": (m.group("field") or "").strip() or None,
            "institution": (m.group("inst") or "").strip() or None,
            "end": None,
            "raw": m.group(0).strip(),
        })

    # Certifications: a dedicated section's lines, each treated as one entry.
    certs = []
    cert_text = _section_text(sections, "CERTIF", "CERTIFICATE")
    for line in cert_text.splitlines():
        line = line.strip(" -•\t")
        if line:
            # A single line may list multiple certs separated by | or ;
            certs.extend(c.strip() for c in re.split(r"\s*\|\s*|;", line) if c.strip())

    # Experience: restrict the "Company — Title (start - end)" scan to an
    # EXPERIENCE section if one was found, so it can't swallow unrelated
    # sections when there are no blank-line separators in the extracted text.
    experience = []
    exp_text = _section_text(sections, "EXPERIENCE") or text
    exp_line_re = re.compile(
        r"(?P<title>[A-Za-z .]+?)\s*(?:@|-|–|—|,|at)\s*(?P<company>[A-Z][A-Za-z0-9 .&]+?)"
        r"\s*\(?(?P<start>[A-Za-z]{3,9}\.?\s*\d{4}|\d{4})\s*[-–—to]+\s*"
        r"(?P<end>[A-Za-z]{3,9}\.?\s*\d{4}|\d{4}|[Pp]resent)\)?"
    )
    for m in exp_line_re.finditer(exp_text):
        experience.append({
            "title": m.group("title").strip(),
            "company": m.group("company").strip(),
            "start": m.group("start").strip(),
            "end": m.group("end").strip(),
            "summary": None,
        })

    return {
        "_source": "resume",
        "name": name,
        "email": email,
        "phone": phone,
        "links": {"linkedin": linkedin, "github": github, "other": other_links[:5]},
        "location": location,
        "skills": sorted(skills_found),
        "education": education,
        "certs": certs,
        "experience": experience,
        "roles": [e["title"] for e in experience],
        "raw_text": text,
    }


def load_resume(path: str) -> dict:
    text = extract_text(path)
    record = parse_resume(text)
    record["_path"] = path
    return record
