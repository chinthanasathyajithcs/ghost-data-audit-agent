"""Deletion audit agent — command-line entry point.

    python code/main.py [--requests dataset/deletion_requests.csv] [--output output.csv]
                        [--cases id1,id2] [--refresh-intent] [--explain]

Stage 2: requests that do not authorise deletion become NOT_APPLICABLE (LLM, cached).
Stage 3: each deletion request is resolved to its subject (every current and old identifier).
Stage 4: all evidence is read (screenshots and PDFs through the cached extractor) and each deletion
request gets a case file of the subject's resources.
Stage 5: each resource's state at audit_at (existence, identity, flow, restore) with the file proving it.
Stage 6: each resource's data category (evidence label, else LLM over a de-identified signature) and the
policy decision (finding / remediation / verification). Deletion requests still get a stub decision
(INCOMPLETE, no steps) until Stage 7 turns decisions into steps.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from deletion_audit.cache import CacheError, JsonCache
from deletion_audit.category import CategoryClassifier, CategoryError
from deletion_audit.config import (
    CATEGORY_CACHE_FILE,
    CATEGORY_MODEL,
    EXTRACTION_CACHE_FILE,
    EXTRACTION_MODEL,
    INTENT_CACHE_FILE,
    LAST_RUN_USAGE_FILE,
    USAGE_LOG_FILE,
)
from deletion_audit.contract import (
    DATASET_DIR,
    REPO_ROOT,
    Answer,
    parse_time,
    read_csv,
    read_csv_header,
    write_answers,
)
from deletion_audit.decisions import case_decisions, classify_cases
from deletion_audit.evidence import EvidenceStore
from deletion_audit.extraction import DocumentExtractor, ExtractionError
from deletion_audit.identity import IdentityIndex
from deletion_audit.intent import IntentClassifier, IntentError, IntentResult
from deletion_audit.linking import CaseFile, build_case_file
from deletion_audit.llm import ClaudeCliBackend
from deletion_audit.policy import Rule, load_rules
from deletion_audit.readers import document_reader
from deletion_audit.state import resolve_state
from deletion_audit.usage import UsageRecorder
from deletion_audit.validate import load_citation_times, validate_rows

MAX_PROBLEMS_SHOWN = 10


@dataclass(frozen=True)
class IdentityStats:
    resolved: int = 0
    via_old_email: int = 0
    unresolved: list[str] = field(default_factory=list)

    def describe(self) -> str:
        text = f"identity: {self.resolved} deletion request(s) resolved ({self.via_old_email} via an old email)"
        return text + (f"; unresolved: {', '.join(self.unresolved)}" if self.unresolved else "; 0 unresolved")


def audit_case(request: dict, intent: IntentResult, case_file: CaseFile | None) -> Answer:
    """Decide one case."""
    if not intent.authorizes_deletion:
        return Answer("NOT_APPLICABLE", ())
    return Answer("INCOMPLETE", ())  # Stages 5–7 replace this stub; no case file means no linked records


def audit_all(
    requests: list[dict],
    classifier: IntentClassifier,
    identity: IdentityIndex,
    store: EvidenceStore,
    refresh_intent: bool = False,
) -> tuple[dict[str, Answer], IdentityStats, dict[str, CaseFile | None]]:
    """Classify every request in one batched pass, then resolve the subject, build the case file, decide."""
    intents = classifier.classify_all([r["request_text"] for r in requests], refresh=refresh_intent)
    answers, case_files = {}, {}
    for r in requests:
        intent = intents[r["request_text"]]
        case_file = None
        if intent.authorizes_deletion:
            audit_at = parse_time(r["audit_at"])
            subject = identity.resolve(r["email"], audit_at)
            if subject is not None:
                case_file = build_case_file(r["case_id"], subject, parse_time(r["requested_at"]), audit_at,
                                            parse_time(r["reported_at"]), r["reported_status"], store)
            case_files[r["case_id"]] = case_file
        answers[r["case_id"]] = audit_case(r, intent, case_file)
    resolved = [c.subject for c in case_files.values() if c is not None]
    stats = IdentityStats(
        resolved=len(resolved),
        via_old_email=sum(s.matched_via == "historical" for s in resolved),
        unresolved=sorted(c for c, f in case_files.items() if f is None),
    )
    return answers, stats, case_files


def explain(case_file: CaseFile, store: EvidenceStore, audit_at: datetime, categories: dict,
            rules: dict[str, Rule]) -> str:
    s = case_file.subject
    lines = [f"--- {case_file.case_id}: {s.user_id} ({s.name}), request email {s.request_email} ({s.matched_via})",
             f"    {len(case_file.resources)} resource(s); {case_file.rejected} other people's resource(s) rejected"]
    decisions = {d.resource_id: d for d in case_decisions(case_file, store, audit_at, categories, rules)}
    for r in case_file.resources:
        cited = sorted({o.evidence_id for o in r.observations})
        state = resolve_state(r, store.coverage, audit_at, store.files_by_resource)
        facets = ", ".join(f"{name}={facet.value}@{facet.proof or '-'}" for name in ("existence", "identity", "flow",
                                                                                   "restore")
                           if (facet := getattr(state, name)) is not None)
        lines.append(f"    {r.system_id or '?'}/{r.resource_id}  [{'+'.join(sorted(r.methods))}]  "
                     f"{len(r.observations)} observation(s) in {', '.join(cited) or 'activity only'}  → {facets}")
        d = decisions[r.resource_id]
        ops = " → ".join(op for op in (d.finding, d.remediation, d.verification) if op)
        lines.append(f"        {d.category} ({d.rule_id or 'no rule'}): {ops or 'review: ' + str(d.needs_review)}")
    if case_file.conflicts:
        lines.append(f"    catalog links contradicted by evidence: {', '.join(case_file.conflicts)}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit deletion requests and write output.csv.")
    parser.add_argument("--requests", type=Path, default=DATASET_DIR / "deletion_requests.csv")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "output.csv")
    parser.add_argument("--cases", default="", help="comma-separated case_ids to audit (default: all)")
    parser.add_argument("--refresh-intent", action="store_true", help="ignore cached intent answers and re-ask the model")
    parser.add_argument("--explain", action="store_true", help="print each deletion case's case file")
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
        backend = ClaudeCliBackend()
        classifier = IntentClassifier(backend, JsonCache(INTENT_CACHE_FILE), usage=usage)
        extractor = DocumentExtractor(backend, JsonCache(EXTRACTION_CACHE_FILE), EXTRACTION_MODEL, usage=usage)
        identity = IdentityIndex.from_dataset(DATASET_DIR)
        store = EvidenceStore.load(DATASET_DIR, identity, document_reader(extractor))
        answers, identity_stats, case_files = audit_all(requests, classifier, identity, store,
                                                        refresh_intent=args.refresh_intent)
        rules = load_rules(DATASET_DIR)
        categorizer = CategoryClassifier(backend, JsonCache(CATEGORY_CACHE_FILE), CATEGORY_MODEL, rules, usage=usage)
        categories = classify_cases(case_files, categorizer)
    except (IntentError, ExtractionError, CategoryError, CacheError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    write_answers(args.output, answers)

    problems = validate_rows(
        read_csv_header(args.output), read_csv(args.output), requests, load_citation_times(DATASET_DIR)
    )
    print(f"wrote {len(answers)} rows to {args.output}; format check: {len(problems)} problem(s)", file=sys.stderr)
    for problem in problems[:MAX_PROBLEMS_SHOWN]:
        print(f"  - {problem}", file=sys.stderr)
    print(f"evidence: {len(store.observations)} observations, {len(store.coverage)} coverage entries, "
          f"{len(store.skipped)} file(s) skipped", file=sys.stderr)
    print(identity_stats.describe(), file=sys.stderr)
    print(usage.format_summary(classifier.cache_hits + extractor.cache_hits + categorizer.cache_hits), file=sys.stderr)
    write_usage_summary(usage, len(requests), classifier.cache_hits)
    if args.explain:
        audit_times = {r["case_id"]: parse_time(r["audit_at"]) for r in requests}
        for case_id, case_file in case_files.items():
            if case_file is not None:
                print(explain(case_file, store, audit_times[case_id], categories, rules))
    return 0


if __name__ == "__main__":
    sys.exit(main())
