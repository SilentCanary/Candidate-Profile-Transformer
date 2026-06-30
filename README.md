# Candidate Profile Transformer

A deterministic and explainable pipeline that converts recruiter CSV data and resume files into one canonical candidate profile per candidate.

The pipeline extracts, normalizes, matches, merges, and projects candidate data while keeping confidence scores, provenance, and safe fallback behavior for uncertain values.

## Sources Implemented

This project handles one source from each required group:

- **Structured source:** Recruiter CSV  
  Fields such as `name`, `email`, `phone`, `current_company`, `title`, `job_role`, `resume_text`

- **Unstructured source:** Resume file  
  Supported formats: `PDF`, `DOCX`, `TXT`

---

## How to Run

From the project root:

```bash
cd cpt
pip install pandas python-docx pdfplumber
```

### Default canonical output

```bash
python -m pipeline.cli --csv "sample_data\recruiters_pipeline_ready.csv" --resumes "sample_resumes\daisuke_mori.pdf" --out -
```

### Custom runtime config output

```bash
python -m pipeline.cli --csv "sample_data\recruiters_pipeline_ready.csv" --resumes "sample_resumes\daisuke_mori.pdf" --config "sample_data\slim_config.json" --out -
```

### Edge-case unmatched resume

```bash
python -m pipeline.cli --csv "sample_data\recruiters_pipeline_ready.csv" --resumes "sample_resumes\ananya_iyer.txt" --out -
```

### Write output to file

```bash
python -m pipeline.cli --csv "sample_data\recruiters_pipeline_ready.csv" --resumes "sample_resumes\daisuke_mori.pdf" --out "output.json"
```

---

## Example Default Output

For `daisuke_mori.pdf`, the pipeline finds a matching CSV row using exact normalized email.

```json
{
  "candidate_id": "cd90e56b-5171-7c9c-1355-751f8dd506a6",
  "full_name": {
    "value": "Daisuke Mori",
    "confidence": 0.85
  },
  "emails": [
    "daisuke.mori.223@yahoo.com"
  ],
  "phones": [
    "+918573688180"
  ],
  "location": {
    "value": {
      "city": "Tokyo",
      "region": "Tokyo",
      "country": "JP"
    },
    "confidence": 0.8
  },
  "skills": [
    {
      "name": "Product Roadmap",
      "confidence": 0.9,
      "sources": ["csv", "resume"]
    }
  ],
  "overall_confidence": 0.737,
  "_pipeline_meta": {
    "source_resume": "daisuke_mori.pdf",
    "matched": true,
    "match_method": "email",
    "match_confidence": 0.97,
    "match_reason": "exact normalized email match"
  }
}
```

---

## Example Custom Config Output

With `sample_data/slim_config.json`, the same canonical profile is projected into a smaller schema.

```json
{
  "full_name": "Daisuke Mori",
  "primary_email": "daisuke.mori.223@yahoo.com",
  "phone": "+918573688180",
  "skills": [
    "Cross-Functional Collaboration",
    "Customer Feedback",
    "Product Roadmap",
    "Project Management",
    "SQL"
  ]
}
```

The same internal canonical profile is used. Only the final output shape changes.

---

## Edge Case Example

For `ananya_iyer.txt`, the resume is parsed but not merged because the fuzzy name match is below the threshold.

```json
{
  "_pipeline_meta": {
    "source_resume": "ananya_iyer.txt",
    "matched": false,
    "match_method": "name_fuzzy_below_threshold",
    "match_confidence": 0.583,
    "match_reason": "best fuzzy name sim=0.58 < 0.6"
  }
}
```

This is intentional. A weak match is left unmatched rather than merged incorrectly.

---

## Architecture

```text
                     INPUT SOURCES
                           │
          ┌────────────────┴────────────────┐
          │                                 │
   Recruiter CSV                     Resume File
 structured source              PDF / DOCX / TXT
          │                                 │
          └────────────────┬────────────────┘
                           │
                 Stage 1 - Ingestion
                           │
                 Stage 2 - Extraction
                           │
                 Stage 3 - Normalization
                           │
                 Stage 4 - Candidate Matching
                           │
                 Stage 5 - Conflict Resolution
                           │
                 Stage 6 - Canonical Profile
                           │
                 Stage 7 - Runtime Projection
                           │
                 Stage 8 - JSON Output
                           │
                 Final Candidate Profile
```

---

## Project Structure

```text
.
├── README.md
│
├── pipeline/
│   ├── __init__.py
│   ├── cli.py
│   ├── orchestrator.py
│   ├── ingestion.py
│   ├── normalization.py
│   ├── normalize_records.py
│   ├── matching.py
│   ├── conflict.py
│   ├── projection.py
│   ├── geo.py
│   └── skills_alias.py
│
├── sample_data/
│   ├── recruiters.csv
│   ├── recruiters_pipeline_ready.csv
│   └── slim_config.json
│
└── sample_resumes/
    ├── daisuke_mori.pdf
    ├── daisuke_mori.txt
    ├── ananya_iyer.txt
    ├── priya_sharma.txt
    ├── rohit_kumar_analyst.txt
    └── vikram_rao.txt
```


---

## Pipeline Stages

### 1. Ingestion

Implemented in `ingestion.py`.

- Reads recruiter CSV using pandas.
- Converts resume files into plain text.
- Supports PDF, DOCX, and TXT resumes.
- Extracts fields such as name, email, phone, links, skills, experience, education, and certifications.

### 2. Normalization

Implemented in:

```text
normalization.py
normalize_records.py
skills_alias.py
geo.py
```

Normalization is applied independently to CSV records and resume records.

Examples:

```text
Emails      → lowercase + validation
Phones      → E.164-style format
Dates       → YYYY-MM
Country     → ISO-3166 alpha-2
Skills      → canonical skill names
Names       → cleaned and title-cased
```

Example:

```text
Japan        → JP
Mar 2021     → 2021-03
85736 88180  → +918573688180
```

### 3. Candidate Matching

Implemented in `matching.py`.

The matcher links a resume to the correct CSV row using:

```text
1. Exact normalized email
2. Exact normalized phone
3. Unique exact name
4. Fuzzy name + resume similarity
5. Below threshold → leave unmatched
```

The fuzzy threshold is `0.6`. If the score is lower, the pipeline does not merge the record.

### 4. Conflict Resolution

Implemented in `conflict.py`.

The pipeline resolves conflicting values using field-specific rules:

- Email and phone are strong identity signals.
- CSV is preferred for current title/current company.
- Resume is preferred for experience, education, and certifications.
- Skills are merged, deduplicated, and confidence-scored.
- Unknown values remain `null` instead of being guessed.
- Rejected scalar values are kept in provenance where applicable.

Skill confidence example:

```text
Skill in both CSV + resume → high confidence
Skill in one source only   → medium confidence
Repeated mentions          → no confidence inflation
```

### 5. Projection Layer

Implemented in `projection.py`.

The runtime config reshapes the output without changing the internal canonical profile.

It supports:

- selecting fields
- renaming fields using `from`
- paths like `emails[0]`
- array paths like `skills[].name`
- toggling confidence/provenance
- missing value behavior: `null`, `omit`, or `error`

Example config file:

```text
sample_data/slim_config.json
```


## Design Decisions

This implementation prioritizes:

- deterministic output
- explainable matching
- conservative conflict resolution
- confidence scoring
- provenance tracking
- runtime configurable output
- no unsafe guessing for missing fields

---

## Known Gaps

- Matching is currently `O(resumes × csv_rows)`.
- Phone normalization uses an E.164-style regex approximation instead of the full `phonenumbers` library.
- Fuzzy name matching uses Python standard library similarity instead of RapidFuzz.
- Resume parsing is heuristic/regex-based, not ML-based.
- Scanned PDF OCR is not implemented.
- GitHub/LinkedIn live fetching and ATS JSON ingestion are deliberately left out for this phase.

---

## Future Improvements

- OCR for scanned PDFs
- ATS JSON ingestion
- GitHub / LinkedIn profile ingestion
- LLM-assisted resume extraction
- ML-based skill extraction
- Better semantic skill canonicalization
- Configurable source weighting
- Pydantic / JSON Schema validation
- Unit and end-to-end tests

---

## Author

Advitiya Prakash  

