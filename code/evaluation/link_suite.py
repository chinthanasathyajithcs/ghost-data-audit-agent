"""Link suite (Stage 4 design §4.10): does each case file hold the resources the answer expects?

Expected resources = every (system_id, resource_id) in a case's expected steps. Used only for scoring.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from deletion_audit.contract import Answer, parse_time, read_csv
from deletion_audit.evidence import EvidenceStore
from deletion_audit.identity import IdentityIndex
from deletion_audit.linking import CaseFile, build_case_file


@dataclass
class LinkScore:
    expected: int = 0
    found: int = 0
    linked: int = 0
    linked_expected: int = 0
    citations: int = 0
    citations_observed: int = 0
    citations_covered: int = 0
    by_method: Counter = field(default_factory=Counter)
    wrong_by_method: Counter = field(default_factory=Counter)
    misses: list = field(default_factory=list)
    extras: list = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.found / self.expected if self.expected else 1.0

    @property
    def precision(self) -> float:
        return self.linked_expected / self.linked if self.linked else 1.0


def score_case(case: CaseFile, expected: Answer, audit_at, store: EvidenceStore, result: LinkScore) -> None:
    wanted = {(s["system_id"], s["resource_id"]) for s in expected.steps}
    linked = {r.resource_id: r for r in case.resources}
    result.expected += len(wanted)
    for system, rid in sorted(wanted):
        if rid in linked:
            result.found += 1
        else:
            result.misses.append(f"{case.case_id} {system}/{rid}")
    wanted_ids = {rid for _, rid in wanted}
    for rid, resource in linked.items():
        result.linked += 1
        method = "+".join(sorted(resource.methods))
        result.by_method[method] += 1
        if rid in wanted_ids:
            result.linked_expected += 1
        else:
            result.wrong_by_method[method] += 1
            result.extras.append(f"{case.case_id} {resource.system_id}/{rid} [{method}]")
    for step in expected.steps:
        if not step["evidence_id"]:
            continue
        result.citations += 1
        resource = linked.get(step["resource_id"])
        if resource and any(o.evidence_id == step["evidence_id"] for o in resource.observations):
            result.citations_observed += 1
        elif any(c.evidence_id == step["evidence_id"] and c.system_id == step["system_id"]
                 and parse_time(c.captured_at) <= audit_at for c in store.coverage):
            result.citations_covered += 1


def run_link_suite(suites: dict, store: EvidenceStore, identity: IdentityIndex, load_answers) -> dict[str, LinkScore]:
    scores = {}
    for name, (requests_path, expected_path) in suites.items():
        expected = load_answers(expected_path)
        result = LinkScore()
        for request in read_csv(requests_path):
            answer = expected.get(request["case_id"])
            if answer is None or not answer.steps:
                continue
            audit_at = parse_time(request["audit_at"])
            subject = identity.resolve(request["email"], audit_at)
            case = build_case_file(request["case_id"], subject, parse_time(request["requested_at"]), audit_at,
                                   parse_time(request["reported_at"]), request["reported_status"], store)
            score_case(case, answer, audit_at, store, result)
        scores[name] = result
    return scores


def format_link_scores(scores: dict[str, LinkScore], skipped: list[str]) -> str:
    lines = []
    for name, s in scores.items():
        lines += [
            f"== links: {name} ==",
            f"  Resource recall     {s.found}/{s.expected}  {s.recall * 100:5.1f}%",
            f"  Resource precision  {s.linked_expected}/{s.linked}  {s.precision * 100:5.1f}%",
            f"  Citations           {s.citations_observed} in observations + {s.citations_covered} via coverage"
            f" of {s.citations}",
            "  Linked by method    " + ", ".join(f"{m}={n} (wrong {s.wrong_by_method[m]})"
                                              for m, n in s.by_method.most_common()),
            f"  Misses ({len(s.misses)}): " + ", ".join(s.misses[:25]) + (" …" if len(s.misses) > 25 else ""),
            f"  Extras ({len(s.extras)}): " + ", ".join(s.extras[:25]) + (" …" if len(s.extras) > 25 else ""),
        ]
    if skipped:
        lines.append(f"  Evidence files not read: {', '.join(skipped)}")
    return "\n".join(lines)
