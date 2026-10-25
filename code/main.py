"""Deletion audit agent — command-line entry point.

    python code/main.py [--requests dataset/deletion_requests.csv] [--output output.csv]
                        [--cases id1,id2] [--refresh-intent]

Stage 2: requests that do not authorise deletion become NOT_APPLICABLE (LLM, cached). Deletion
requests still get a stub decision (INCOMPLETE, no steps) until Stages 3–7 replace it.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from deletion_audit.cache import CacheError, JsonCache
from deletion_audit.config import INTENT_CACHE_FILE, LAST_RUN_USAGE_FILE, USAGE_LOG_FILE
from deletion_audit.contract import DATASET_DIR, REPO_ROOT, Answer, read_csv, read_csv_header, write_answers
from deletion_audit.intent import IntentClassifier, IntentError, IntentResult
from deletion_audit.llm import ClaudeCliBackend
from deletion_audit.usage import UsageRecorder
from deletion_audit.validate import load_citation_times, validate_rows

MAX_PROBLEMS_SHOWN = 10


def audit_case(request: dict, intent: IntentResult) -> Answer:
    """Decide one case."""
    if not intent.authorizes_deletion:
        return Answer("NOT_APPLICABLE", ())
    return Answer("INCOMPLETE", ())  # Stages 3–7 replace this stub


def audit_all(requests: list[dict], classifier: IntentClassifier, refresh_intent: bool = False) -> dict[str, Answer]:
    """Classify every request text in one batched pass, then decide each case."""
    intents = classifier.classify_all([r["request_text"] for r in requests], refresh=refresh_intent)
    return {r["case_id"]: audit_case(r, intents[r["request_text"]]) for r in requests}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit deletion requests and write output.csv.")
    parser.add_argument("--requests", type=Path, default=DATASET_DIR / "deletion_requests.csv")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "output.csv")
    parser.add_argument("--cases", default="", help="comma-separated case_ids to audit (default: all)")
    parser.add_argument("--refresh-intent", action="store_true", help="ignore cached intent answers and re-ask the model")
    return parser.parse_args(argv)


def select_requests(requests: list[dict], cases: str) -> list[dict]:
    if not cases:
        return requests
    wanted = {c.strip() for c in cases.split(",") if c.strip()}
    unknown = wanted - {r["case_id"] for r in requests}
    if unknown:
        raise SystemExit(f"unknown case_ids: {', '.join(sorted(unknown))}")
    return [r for r in requests if r["case_id"] in wanted]


def write_usage_summary(usage: UsageRecorder, requests: int, cache_hits: int) -> None:
    LAST_RUN_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "requests": requests,
               "intent_cache_hits": cache_hits, "models": usage.summary()}
    LAST_RUN_USAGE_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    requests = select_requests(read_csv(args.requests), args.cases)
    usage = UsageRecorder(USAGE_LOG_FILE)
    try:
        classifier = IntentClassifier(ClaudeCliBackend(), JsonCache(INTENT_CACHE_FILE), usage=usage)
        answers = audit_all(requests, classifier, refresh_intent=args.refresh_intent)
    except (IntentError, CacheError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    write_answers(args.output, answers)

    problems = validate_rows(
        read_csv_header(args.output), read_csv(args.output), requests, load_citation_times(DATASET_DIR)
    )
    print(f"wrote {len(answers)} rows to {args.output}; format check: {len(problems)} problem(s)", file=sys.stderr)
    for problem in problems[:MAX_PROBLEMS_SHOWN]:
        print(f"  - {problem}", file=sys.stderr)
    print(usage.format_summary(classifier.cache_hits), file=sys.stderr)
    write_usage_summary(usage, len(requests), classifier.cache_hits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
