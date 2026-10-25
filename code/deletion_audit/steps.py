"""Stage 7 — a case's answer from its policy decisions: status and ordered steps (AGENTS.md §6.3–6.5).

- Any finding → INCOMPLETE: findings (citing their proof), the remediation for each, and a verification
  for every resource; remediation and verification describe future work, so they cite nothing.
- No finding → COMPLETE: one verification per resource, each citing the evidence that proves it.
- A finding whose proof is only in a file captured after audit_at cannot be cited, so the finding line is
  left out while its remediation and verification stay (the work is still needed).
- Steps follow the strict order (PRD D10) and are numbered from 1.
"""

from __future__ import annotations

from typing import Iterable

from deletion_audit.contract import OPERATIONS, Answer, step_sort_key
from deletion_audit.policy import Decision


def _step(decision: Decision, operation: str, evidence: str | None) -> dict:
    phase, state = OPERATIONS[operation]
    return {"phase": phase, "system_id": decision.system_id or "", "resource_id": decision.resource_id,
            "operation": operation, "state": state, "evidence_id": evidence or ""}


def build_answer(decisions: Iterable[Decision]) -> Answer:
    decisions = [d for d in decisions if d.needs_review is None]
    problems = [d for d in decisions if d.finding]
    if problems:
        steps = [_step(d, d.finding, d.finding_evidence) for d in problems if d.finding_evidence]
        steps += [_step(d, d.remediation, None) for d in problems]
        steps += [_step(d, d.verification, None) for d in decisions if d.verification]
        status = "INCOMPLETE"
    else:
        steps = [_step(d, d.verification, d.verification_evidence) for d in decisions if d.verification]
        status = "COMPLETE"
    ordered = sorted(steps, key=step_sort_key)
    return Answer(status, tuple({"step_no": i, **s} for i, s in enumerate(ordered, start=1)))
