"""Evaluation harness — runs the agent on cases with known answers and scores it.

    python code/evaluation/main.py                        # run agent on samples + custom cases, score
    python code/evaluation/main.py --suite samples        # one suite
    python code/evaluation/main.py --cases case_05 --diff # one case with its full diff
    python code/evaluation/main.py --predictions p.csv --suite samples   # score an existing file
    python code/evaluation/main.py --validate output.csv  # format check of a full output file
    python code/evaluation/main.py --label "stage 3 identity"            # name the run in run_history.md
    python code/evaluation/main.py --suite intent                        # Stage 2 classifier on all distinct texts
    python code/evaluation/main.py --suite links                         # Stage 4 case files vs expected resources

Metric definitions: scoring.py and code/docs/stages/stage_1_evaluation_harness.md §4.2.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
CODE_DIR = EVAL_DIR.parent
sys.path.insert(0, str(CODE_DIR))

from deletion_audit.contract import DATASET_DIR, Answer, read_csv, read_csv_header  # noqa: E402
from deletion_audit.validate import load_citation_times, validate_file, validate_rows  # noqa: E402

import report  # noqa: E402
from intent_suite import format_intent_score, run_intent_suite  # noqa: E402
from link_suite import format_link_scores, run_link_suite  # noqa: E402
from scoring import score  # noqa: E402

SUITES = {
    "samples": (DATASET_DIR / "sample_deletion_requests.csv", DATASET_DIR / "sample_output.csv"),
    "custom": (EVAL_DIR / "custom_cases" / "requests.csv", EVAL_DIR / "custom_cases" / "expected.csv"),
}
RUNS_DIR = EVAL_DIR / "runs"
HISTORY_FILE = EVAL_DIR / "run_history.md"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score the deletion audit agent against known answers.")
    parser.add_argument("--suite", choices=("all", *SUITES, "intent", "links"), default="all",
                        help="all = samples + custom; intent = Stage 2 classifier on every distinct text; "
                             "links = Stage 4 case files")
    parser.add_argument("--cases", default="", help="comma-separated case_ids (no history row is written)")
    parser.add_argument("--predictions", type=Path, help="score this file instead of running the agent")
    parser.add_argument("--diff", action="store_true", help="print the diff of every failing case")
    parser.add_argument("--label", default="", help="short name for this run in run_history.md")
    parser.add_argument("--no-history", action="store_true", help="do not append to run_history.md")
    parser.add_argument("--refresh-intent", action="store_true", help="intent suite: ignore cached answers")
    parser.add_argument("--validate", type=Path, help="only run the format check on this output file")
    parser.add_argument("--requests", type=Path, default=DATASET_DIR / "deletion_requests.csv",
                        help="requests file used by --validate")
    return parser.parse_args(argv)


def load_predictions(path: Path) -> dict[str, Answer]:
    """Lenient reader: rows whose steps_json is not a JSON array of objects are left out
    (scored as missing; the validator reports them)."""
    answers = {}
    for row in read_csv(path):
        try:
            steps = json.loads(row["steps_json"])
        except (json.JSONDecodeError, KeyError):
            continue
        if isinstance(steps, list) and all(isinstance(s, dict) for s in steps):
            answers[row["case_id"]] = Answer(row["deletion_status"], tuple(steps))
    return answers


def run_agent(requests: Path, output: Path, cases: list[str]) -> None:
    command = [sys.executable, str(CODE_DIR / "main.py"), "--requests", str(requests), "--output", str(output)]
    if cases:
        command += ["--cases", ",".join(cases)]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(f"agent failed (exit {completed.returncode}):\n{completed.stderr}")


def evaluate_suite(name: str, args: argparse.Namespace, wanted: set[str], workdir: Path, citation_times: dict):
    requests_path, expected_path = SUITES[name]
    requests = [r for r in read_csv(requests_path) if not wanted or r["case_id"] in wanted]
    if not requests:
        return None
    case_ids = [r["case_id"] for r in requests]
    expected = {k: v for k, v in load_predictions(expected_path).items() if k in case_ids}

    predictions_path = args.predictions
    if predictions_path is None:
        predictions_path = workdir / f"{name}_predictions.csv"
        run_agent(requests_path, predictions_path, case_ids if wanted else [])

    rows = [r for r in read_csv(predictions_path) if r["case_id"] in case_ids]
    problems = validate_rows(read_csv_header(predictions_path), rows, requests, citation_times)
    predicted = {k: v for k, v in load_predictions(predictions_path).items() if k in case_ids}
    return expected, predicted, problems


def git_commit() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return head.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")


def append_history(rows: list[str]) -> None:
    if not HISTORY_FILE.exists():
        HISTORY_FILE.write_text("# Evaluation run history\n\nOne row per full-suite run of "
                                "`code/evaluation/main.py`. Metric definitions: "
                                "`code/docs/stages/stage_1_evaluation_harness.md` §4.2.\n\n"
                                + report.HISTORY_HEADER, encoding="utf-8")
    with open(HISTORY_FILE, "a", encoding="utf-8") as handle:
        handle.writelines(rows)


def record_run(results: dict, label: str) -> Path:
    now = datetime.now(timezone.utc)
    stamp, commit = now.strftime("%Y-%m-%d %H:%M"), git_commit()
    append_history([report.history_row(stamp, commit, label, suite, result, len(problems))
                    for suite, (result, problems) in results.items()])

    RUNS_DIR.mkdir(exist_ok=True)
    run_file = RUNS_DIR / f"{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    payload = {"time": now.isoformat(), "commit": commit, "label": label,
               "suites": {s: report.metrics_dict(r, p) for s, (r, p) in results.items()}}
    run_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return run_file


def run_intent(args: argparse.Namespace) -> int:
    try:
        result, usage, cache_hits = run_intent_suite(refresh=args.refresh_intent)
    except RuntimeError as error:
        raise SystemExit(f"intent suite failed: {error}")
    print(format_intent_score(result))
    print(usage.format_summary(cache_hits))
    if not args.no_history:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        append_history([report.intent_history_row(stamp, git_commit(), args.label, result)])
        print(f"\nRecorded in {HISTORY_FILE.relative_to(CODE_DIR.parent)}")
    return 0 if result.correct == result.texts else 1


def run_links(args: argparse.Namespace) -> int:
    from deletion_audit.cache import JsonCache
    from deletion_audit.config import EXTRACTION_CACHE_FILE, EXTRACTION_MODEL
    from deletion_audit.evidence import EvidenceStore
    from deletion_audit.extraction import DocumentExtractor
    from deletion_audit.identity import IdentityIndex
    from deletion_audit.llm import ClaudeCliBackend
    from deletion_audit.readers import document_reader

    identity = IdentityIndex.from_dataset(DATASET_DIR)
    extractor = DocumentExtractor(ClaudeCliBackend(), JsonCache(EXTRACTION_CACHE_FILE), EXTRACTION_MODEL)
    store = EvidenceStore.load(DATASET_DIR, identity, document_reader(extractor))
    scores = run_link_suite(SUITES, store, identity, load_predictions)
    print(format_link_scores(scores, store.skipped))
    if not args.no_history:
        stamp, commit = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), git_commit()
        append_history([report.link_history_row(stamp, commit, args.label, f"links:{name}", s)
                        for name, s in scores.items()])
        print(f"\nRecorded in {HISTORY_FILE.relative_to(CODE_DIR.parent)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.validate:
        problems = validate_file(args.validate, args.requests, DATASET_DIR)
        print(f"{args.validate}: {len(problems)} format problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1 if problems else 0

    if args.suite == "intent":
        return run_intent(args)
    if args.suite == "links":
        return run_links(args)

    wanted = {c.strip() for c in args.cases.split(",") if c.strip()}
    suites = list(SUITES) if args.suite == "all" else [args.suite]
    citation_times = load_citation_times(DATASET_DIR)
    results, combined_expected, combined_predicted, combined_problems = {}, {}, {}, []

    with tempfile.TemporaryDirectory() as workdir:
        for name in suites:
            outcome = evaluate_suite(name, args, wanted, Path(workdir), citation_times)
            if outcome is None:
                continue
            expected, predicted, problems = outcome
            results[name] = (score(expected, predicted), problems)
            combined_expected |= expected
            combined_predicted |= predicted
            combined_problems += problems

    if not results:
        raise SystemExit("no cases selected")
    if len(results) > 1:
        results["all"] = (score(combined_expected, combined_predicted), combined_problems)

    for name, (result, problems) in results.items():
        print(report.summary(name, result, problems))
        print(report.failing_cases_line(result))
        print()
    headline = results.get("all") or next(iter(results.values()))
    print(report.confusion_table(headline[0]))
    print(report.operation_table(headline[0]))

    if args.diff or wanted:
        diffs = [d for name, (r, _) in results.items() if name != "all" for d in r.case_diffs]
        for diff in diffs:
            if wanted or not diff.fully_correct:
                print(report.case_diff(diff))

    if not wanted and not args.no_history:
        run_file = record_run(results, args.label)
        print(f"\nRecorded in {HISTORY_FILE.relative_to(CODE_DIR.parent)} and {run_file.relative_to(CODE_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
