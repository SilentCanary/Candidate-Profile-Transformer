"""End-to-end orchestration: CSV + resumes -> list of projected candidate profiles."""

import os
import glob

from .ingestion import load_csv, load_resume
from .normalize_records import normalize_csv_record, normalize_resume_record
from .matching import match_candidate
from .conflict import build_canonical_profile
from .projection import apply_projection, DEFAULT_CONFIG

RESUME_EXTS = (".pdf", ".docx", ".txt")


def _resolve_resume_paths(resumes_arg):
    if not resumes_arg:
        return []
    if os.path.isdir(resumes_arg):
        paths = []
        for ext in RESUME_EXTS:
            paths.extend(glob.glob(os.path.join(resumes_arg, f"*{ext}")))
        return sorted(paths)
    return [resumes_arg]


def run_pipeline(csv_path: str, resumes_arg: str, config: dict = None, include_unmatched: bool = True):
    config = config or DEFAULT_CONFIG

    raw_csv_records = load_csv(csv_path)
    csv_records_norm = [normalize_csv_record(r) for r in raw_csv_records]

    resume_paths = _resolve_resume_paths(resumes_arg)

    results = []
    for path in resume_paths:
        raw_resume = load_resume(path)
        resume_norm = normalize_resume_record(raw_resume)

        match_info = match_candidate(resume_norm, csv_records_norm)
        csv_norm = match_info["csv_record"] or normalize_csv_record({})

        if not match_info["matched"] and not include_unmatched:
            continue

        meta = {
            "source_resume": os.path.basename(path),
            "matched": match_info["matched"],
            "match_method": match_info["method"],
            "match_confidence": round(match_info["confidence"], 3),
            "match_reason": match_info["reason"],
        }
        try:
            canonical = build_canonical_profile(csv_norm, resume_norm, match_info)
            projected = apply_projection(canonical, config)
            projected["_pipeline_meta"] = meta
            results.append(projected)
        except Exception as exc:
            # A single malformed/under-specified record must not crash the batch.
            meta["error"] = str(exc)
            results.append({"candidate_id": None, "_pipeline_meta": meta})

    return results
