"""
CLI:
    python -m pipeline.cli --csv recruiters.csv --resumes ./resumes --config config.json --out out.json
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.orchestrator import run_pipeline
from pipeline.projection import DEFAULT_CONFIG


def main():
    parser = argparse.ArgumentParser(description="Candidate Profile Transformer")
    parser.add_argument("--csv", required=True, help="Path to recruiter CSV")
    parser.add_argument("--resumes", required=True, help="Path to a resume file or a directory of resumes")
    parser.add_argument("--config", help="Path to runtime projection config JSON (defaults to built-in schema)")
    parser.add_argument("--out", default="-", help="Output JSON path, or '-' for stdout (default)")
    parser.add_argument("--no-unmatched", action="store_true",
                         help="Drop resumes that could not be matched to a CSV row")
    args = parser.parse_args()

    config = DEFAULT_CONFIG
    if args.config:
        with open(args.config, "r") as f:
            config = json.load(f)

    results = run_pipeline(args.csv, args.resumes, config=config,
                            include_unmatched=not args.no_unmatched)

    output_text = json.dumps(results, indent=2, default=str)
    if args.out == "-":
        print(output_text)
    else:
        with open(args.out, "w") as f:
            f.write(output_text)
        print(f"Wrote {len(results)} profile(s) to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
