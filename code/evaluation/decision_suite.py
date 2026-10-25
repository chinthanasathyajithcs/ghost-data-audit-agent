"""Decision suite (Stage 6 design §4.4): does each linked expected resource get exactly the expected
finding / remediation / verification? Used only for scoring."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from deletion_audit.contract import parse_time, read_csv
from deletion_audit.decisions import case_decisions, classify_cases
from deletion_audit.linking import build_case_file

FINDINGS = {"REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"}
REMEDIATIONS = {"DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD"}


def expected_ops(steps) -> dict[str, tuple]:
    grouped: dict[str, dict] = {}
    for s in steps:
        slot = "finding" if s["operation"] in FINDINGS else "remediation" if s["operation"] in REMEDIATIONS \
            else "verification"
        grouped.setdefault(s["resource_id"], {})[slot] = (s["operation"], s["evidence_id"])
    return {rid: (g.get("finding"), g.get("remediation", (None, ""))[0], g.get("verification", (None, ""))) for rid, g
            in grouped.items()}


@dataclass
class DecisionScore:
    scored: int = 0
    correct: int = 0
    finding_cites: int = 0
    finding_cites_correct: int = 0
    by_source: Counter = field(default_factory=Counter)
    wrong_by_source: Counter = field(default_factory=Counter)
    reviews: int = 0
    misses: list = field(default_factory=list)


def run_decision_suite(suites: dict, store, identity, classifier, rules, load_answers) -> dict[str, DecisionScore]:
    scores = {}
    for name, (requests_path, expected_path) in suites.items():
        answers = load_answers(expected_path)
        requests = [r for r in read_csv(requests_path) if answers.get(r["case_id"]) and answers[r["case_id"]].steps]
        case_files, audit = {}, {}
        for r in requests:
            audit[r["case_id"]] = parse_time(r["audit_at"])
            case_files[r["case_id"]] = build_case_file(
                r["case_id"], identity.resolve(r["email"], audit[r["case_id"]]), parse_time(r["requested_at"]),
                audit[r["case_id"]], parse_time(r["reported_at"]), r["reported_status"], store)
        categories = classify_cases(case_files, classifier)
        score = DecisionScore()
        for case_id, case_file in case_files.items():
            want = expected_ops(answers[case_id].steps)
            for d in case_decisions(case_file, store, audit[case_id], categories, rules):
                if d.resource_id not in want:
                    continue
                source = categories[f"{case_id}/{d.resource_id}"][1]
                finding, remediation, (verification, _) = want[d.resource_id]
                got = (d.finding, d.remediation, d.verification)
                score.scored += 1
                score.by_source[source] += 1
                score.reviews += d.needs_review is not None
                if got == ((finding or (None,))[0], remediation, verification):
                    score.correct += 1
                else:
                    score.wrong_by_source[source] += 1
                    score.misses.append(f"{case_id} {d.resource_id} [{d.category}/{source}]: expected "
                                        f"{(finding or (None,))[0]}/{remediation}/{verification}, got "
                                        f"{d.finding}/{d.remediation}/{d.verification}"
                                        + (f" (review: {d.needs_review})" if d.needs_review else ""))
                if finding and finding[1]:
                    score.finding_cites += 1
                    score.finding_cites_correct += d.finding_evidence == finding[1]
        scores[name] = score
    return scores


def format_decision_scores(scores: dict[str, DecisionScore]) -> str:
    lines = []
    for name, s in scores.items():
        lines += [f"== decisions: {name} ==",
                  f"  Exact decision   {s.correct}/{s.scored}  {100 * s.correct / max(s.scored, 1):5.1f}%   "
                  + ", ".join(f"{src} {n - s.wrong_by_source[src]}/{n}" for src, n in sorted(s.by_source.items())),
                  f"  Finding cites    {s.finding_cites_correct}/{s.finding_cites}",
                  f"  Needs review     {s.reviews}",
                  f"  Misses ({len(s.misses)}): " + "; ".join(s.misses[:20])]
    return "\n".join(lines)
