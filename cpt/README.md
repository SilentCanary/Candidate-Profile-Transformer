# Candidate Profile Transformer

A deterministic, explainable pipeline that turns a recruiter CSV + resume files
into one canonical candidate profile per person, with confidence scores and
provenance, reshaped at request time by a runtime projection config.

Sources implemented (one per required group, per the brief):
- **Structured**: recruiter CSV (`name, email, phone, current_company, title, job_role, resume_text`)
- **Unstructured**: resume file (PDF / DOCX / TXT)

## How to run

```bash
cd cpt
pip install pandas python-docx pdfplumber   # pandas already required; docx/pdf only needed for those file types

# Full default schema, all resumes in a folder, matched against the CSV:
python -m pipeline.cli --csv "sample_data\recruiters_pipeline_ready.csv" --resumes "sample_resumes\daisuke_mori.pdf" --out -

# Single resume, custom runtime config (field select/rename/normalize), to stdout:
python -m pipeline.cli --csv "sample_data\recruiters_pipeline_ready.csv" --resumes "sample_resumes\daisuke_mori.pdf" --config "sample_data\slim_config.json" --out -


# Drop resumes that couldn't be matched to any CSV row:
python -m pipeline.cli --csv "sample_data\recruiters_pipeline_ready.csv" --resumes "sample_resumes\ananya_iyer.txt" --out -
```

`sample_data/recruiters_pipeline_ready.csv` and `sample_resumes/*.txt` are included so the
whole thing runs end to end with no other inputs. Swap in your real CSV and
resume files (PDF/DOCX/TXT all supported) -- same commands.

## Pipeline stages (`pipeline/`)

1. **Ingestion** (`ingestion.py`) -- CSV read via pandas, one row -> one raw
   record. Resume converted to plain text (pdfplumber / python-docx / direct
   read) then heuristically parsed into name/email/phone/links/skills/
   education/certs/experience.
2. **Normalization** (`normalization.py`, `normalize_records.py`,
   `skills_alias.py`, `geo.py`) -- applied to both sources **independently**:
   name title-casing, email lowercase+validate, phone -> E.164-style,
   dates -> `YYYY-MM`, skill alias canonicalization, country -> ISO-3166 alpha-2
   (for both CSV `city/region/country` columns, if present, and resume-extracted
   location lines).
3. **Candidate matching** (`matching.py`) -- finds the CSV row for a resume:
   exact email -> exact phone -> unique name match -> fuzzy name +
   resume-similarity (skill/company/role overlap) for same-name disambiguation.
   Below the fuzzy threshold (0.6) the record is left **unmatched** rather than
   guessed at.
4. **Conflict resolution** (`conflict.py`) -- every value becomes an evidence
   object `{field, value, source, method, confidence, provenance}`.
   - Multi-value fields (emails, phones, skills, experience, certifications)
     are accumulated, deduplicated, and sorted by confidence.
   - Scalar fields (full_name, current_company, title, headline,
     years_experience) pick one winner; the rejected value is kept in
     `provenance`, never discarded silently.
   - `current_company`: CSV always wins on conflict; the resume's older
     company is preserved as an `experience` entry instead of being dropped.
   - `title`: more specific value wins when confidence is close
     ("Backend Developer" > "Developer").
   - Skills found in **both** CSV resume-text and the uploaded resume get
     high confidence (0.9); single-source skills get medium (0.55); repeated
     mentions from one source don't inflate confidence (no keyword-stuffing).
   - `years_experience`: explicit statement > computed from clear start/end
     dates > `null` (never guessed from partial dates).
   - Education: resume preferred, CSV only as fallback; no degree is inferred
     without explicit evidence.
   - Sensitive attributes (age/gender/race/...) are split out into
     `_protected_metadata` at ingestion and never reach matching, scoring, or
     the canonical profile / default output.
   - Every profile gets a top-level `confidence` (unweighted average of every
     field/item with real evidence behind it; fields with no source at all
     are skipped rather than dragging the average toward 0, so "no data"
     doesn't read the same as "low-confidence data"). Exposed by the default
     config as `overall_confidence`.
5. **Projection** (`projection.py`) -- the only place the runtime config is
   applied. It selects fields, renames via `from` paths (including
   `array[0]` and `array[].field` wildcards), applies per-field
   normalization, toggles confidence/provenance visibility, and resolves
   missing values as `null` / `omit` / `error`. The canonical profile itself
   never changes shape -- only the projection does, so reshaping output needs
   **zero code changes**, just a new config file (see
   `sample_data/slim_config.json` for an example matching the brief's spec).
6. **Orchestrator / CLI** (`orchestrator.py`, `cli.py`) -- wires the stages
   together per resume, isolates per-record failures (one bad file produces
   an error entry in the output, it does not crash the batch), and writes
   JSON to stdout or a file.

## Known gaps (honest list)

- Matching is O(resumes x csv_rows); fine at hundreds/thousands of rows, not
  load-tested at larger scale.
- `candidate_id` is a deterministic hash of the best available identity
  anchor (email > phone > name > file path), not a random UUID -- this
  matters because the brief requires "same inputs produce the same output."
- `location` and `links.portfolio` are populated on a best-effort basis:
  - CSV: only if the CSV has `city`/`region`/`country` (or `state`) columns.
  - Resume: an explicit `Location:` / `Based in:` line anywhere, or a bare
    `City, Country` line in the header. No geocoding/inference beyond that.
  - `portfolio`: any non-LinkedIn/GitHub URL containing "portfolio",
    "behance", "dribbble", or a `.me`/`.dev` path; otherwise lands in
    `links.other[]`.
  When the CSV and resume disagree on city, the CSV (recruiter-maintained)
  wins, same rule as `current_company`.

## Known substitutions (sandbox had no network/pip access)

- Phone normalization uses a regex-based E.164 approximation instead of the
  `phonenumbers` library (default region inferred as `+91`). Swap
  `normalization.normalize_phone` for `phonenumbers.parse(...)` +
  `format_number(..., PhoneNumberFormat.E164)` in production.
- Fuzzy name matching uses stdlib `difflib.SequenceMatcher` instead of
  `rapidfuzz`. Swap `matching._name_similarity` for
  `rapidfuzz.fuzz.token_sort_ratio(...) / 100` for production -- the rest of
  the pipeline only depends on getting a 0..1 similarity score back.
- Resume parsing (`ingestion.parse_resume`) is regex/heuristic-based, not
  ML/NLP-based (the design doc explicitly lists "ML-based skill extraction"
  and "NLP co-ref resolution" as deliberately out of scope for Phase 1).

## What's deliberately not built (matches "Deliberate Omissions" in the design)

GitHub/LinkedIn live API fetch, ML-based skill extraction, NLP co-reference
resolution, multi-language name normalization, ATS JSON ingestion (only one
structured + one unstructured source was required; adding a second
structured source is a matter of writing another `ingestion.load_x()` +
`normalize_x_record()` pair and feeding its output into the same
`matching`/`conflict`/`projection` stages -- no other changes needed).
