"""State suite (Stage 5 design §4.6): is each linked resource's judged state the one the answer implies?

The expected state comes from the answer's steps: a finding's state if there is one, else the
verification's. Only resources Stage 4 linked are scored. Used only for scoring.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from deletion_audit.contract import parse_time, read_csv
from deletion_audit.evidence import EvidenceStore
from deletion_audit.identity import IdentityIndex
from deletion_audit.linking import build_case_file
from deletion_audit.state import ResourceState, resolve_state

FINDING_STATE = {"REPORT_REMAINING_RECORD": ("existence", "present"),
                 "REPORT_EXPOSED_PII": ("identity", "identifiable"),
                 "REPORT_ACTIVE_DATA_FLOW": ("flow", "active"),
                 "REPORT_RESTORE_RISK": ("restore", "open")}
VERIFY_STATE = {"VERIFY_RECORD_ABSENT": ("existence", "absent"),
                "VERIFY_RECORD_PRESENT": ("existence", "present"),
                "VERIFY_RECORD_REDACTED": ("identity", "redacted"),
                "VERIFY_RECORD_ANONYMIZED": ("identity", "anonymized"),
                "VERIFY_DATA_FLOW_DISABLED": ("flow", "disabled"),
                "VERIFY_RESTORE_BLOCKED": ("restore", "blocked")}


def expected_states(steps) -> dict[str, tuple[str, str, str]]:
    """resource_id -> (facet, value, cited evidence_id)."""
    expected = {}
    for step in steps:
        if step["operation"] in FINDING_STATE:
            expected[step["resource_id"]] = (*FINDING_STATE[step["operation"]], step["evidence_id"])
    for step in steps:
        if step["operation"] in VERIFY_STATE and step["resource_id"] not in expected:
            expected[step["resource_id"]] = (*VERIFY_STATE[step["operation"]], step["evidence_id"])
    return expected


@dataclass
class StateScore:
    scored: int = 0
    correct: int = 0
    proofs: int = 0
    proofs_correct: int = 0
    by_facet: Counter = field(default_factory=Counter)
    wrong_by_facet: Counter = field(default_factory=Counter)
    misses: list = field(default_factory=list)
    proof_misses: list = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.scored if self.scored else 1.0

    @property
    def proof_accuracy(self) -> float:
        return self.proofs_correct / self.proofs if self.proofs else 1.0


def case_states(request: dict, store: EvidenceStore, identity: IdentityIndex,
                present_in: dict[str, set[str]]) -> tuple[datetime, dict[str, ResourceState]]:
    audit_at = parse_time(request["audit_at"])
    subject = identity.resolve(request["email"], audit_at)
    case = build_case_file(request["case_id"], subject, parse_time(request["requested_at"]), audit_at,
                           parse_time(request["reported_at"]), request["reported_status"], store)
    return audit_at, {r.resource_id: resolve_state(r, store.coverage, audit_at, present_in) for r in case.resources}


def run_state_suite(suites: dict, store: EvidenceStore, identity: IdentityIndex, load_answers) -> dict[str, StateScore]:
    present_in = store.files_by_resource
    scores = {}
    for name, (requests_path, expected_path) in suites.items():
        answers = load_answers(expected_path)
        score = StateScore()
        for request in read_csv(requests_path):
            answer = answers.get(request["case_id"])
            if answer is None or not answer.steps:
                continue
            _, states = case_states(request, store, identity, present_in)
            for rid, (facet, value, cited) in expected_states(answer.steps).items():
                if rid not in states:
                    continue
                facet_state = getattr(states[rid], facet)
                got = facet_state.value if facet_state else "unknown"
                score.scored += 1
                score.by_facet[facet] += 1
                if got == value:
                    score.correct += 1
                else:
                    score.wrong_by_facet[facet] += 1
                    score.misses.append(f"{request['case_id']} {rid}: {facet} expected {value}, got {got}")
                if cited:
                    score.proofs += 1
                    proof = facet_state.proof if facet_state else None
                    if proof == cited:
                        score.proofs_correct += 1
                    else:
                        score.proof_misses.append(f"{request['case_id']} {rid}: cite {cited}, got {proof}")
        scores[name] = score
    return scores


def format_state_scores(scores: dict[str, StateScore]) -> str:
    lines = []
    for name, s in scores.items():
        lines += [
            f"== states: {name} ==",
            f"  State accuracy  {s.correct}/{s.scored}  {s.accuracy * 100:5.1f}%   by facet: "
            + ", ".join(f"{f} {n - s.wrong_by_facet[f]}/{n}" for f, n in sorted(s.by_facet.items())),
            f"  Proof accuracy  {s.proofs_correct}/{s.proofs}  {s.proof_accuracy * 100:5.1f}%",
            f"  State misses ({len(s.misses)}): " + "; ".join(s.misses[:20]),
            f"  Proof misses ({len(s.proof_misses)}): " + "; ".join(s.proof_misses[:20]),
        ]
    return "\n".join(lines)
