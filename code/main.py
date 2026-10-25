"""Deletion audit agent — command-line entry point.

    python code/main.py [--requests dataset/deletion_requests.csv] [--output output.csv] [--cases id1,id2]

Stage 1: the decision logic is a stub (every case INCOMPLETE with no steps) so the evaluation
harness can run end to end. Stages 2–7 replace `audit_case`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deletion_audit.contract import DATASET_DIR, REPO_ROOT, Answer, read_csv, read_csv_header, write_answers
from deletion_audit.validate import load_citation_times, validate_rows

MAX_PROBLEMS_SHOWN = 10


def audit_case(request: dict) -> Answer:
    """Decide one case. Stage 1 stub."""
    return Answer("INCOMPLETE", ())


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit deletion requests and write output.csv.")
    parser.add_argument("--requests", type=Path, default=DATASET_DIR / "deletion_requests.csv")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "output.csv")
    parser.add_argument("--cases", default="", help="comma-separated case_ids to audit (default: all)")
    return parser.parse_args(argv)


def select_requests(requests: list[dict], cases: str) -> list[dict]:
    if not cases:
        return requests
    wanted = {c.strip() for c in cases.split(",") if c.strip()}
    unknown = wanted - {r["case_id"] for r in requests}
    if unknown:
        raise SystemExit(f"unknown case_ids: {', '.join(sorted(unknown))}")
    return [r for r in requests if r["case_id"] in wanted]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    requests = select_requests(read_csv(args.requests), args.cases)
    answers = {r["case_id"]: audit_case(r) for r in requests}
    write_answers(args.output, answers)

    problems = validate_rows(
        read_csv_header(args.output), read_csv(args.output), requests, load_citation_times(DATASET_DIR)
    )
    print(f"wrote {len(answers)} rows to {args.output}; format check: {len(problems)} problem(s)", file=sys.stderr)
    for problem in problems[:MAX_PROBLEMS_SHOWN]:
        print(f"  - {problem}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
