"""Stage 6 — what the policy requires for a resource, compared with its state (design §4.2–4.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from deletion_audit.contract import parse_time, read_csv
from deletion_audit.observations import Observation
from deletion_audit.state import Facet, ResourceState

DATA_FLOW = "DATA_FLOW"  # a sync/connector process: no rule, but an active one can recreate data
RETENTION_KEYS = ("retention_until", "retained_until", "retain_until", "retain until", "Retention end")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str
    condition: str
    action: str  # DELETE, REDACT, ANONYMIZE, RETAIN


@dataclass(frozen=True)
class Decision:
    system_id: str | None
    resource_id: str
    category: str
    rule_id: str | None
    finding: str | None
    finding_evidence: str | None
    remediation: str | None
    verification: str | None
    verification_evidence: str | None
    needs_review: str | None = None

    @property
    def compliant(self) -> bool:
        return self.finding is None and self.needs_review is None


def load_rules(dataset_dir: Path) -> dict[str, Rule]:
    return {r["data_category"]: Rule(r["rule_id"], r["data_category"], r["condition"], r["required_action"])
            for r in read_csv(dataset_dir / "deletion_rules.csv")}


def _retention_expired(observations: Iterable[Observation], audit_at: datetime) -> str | None:
    for o in observations:
        for key in RETENTION_KEYS:
            value = o.fields.get(key)
            if isinstance(value, str) and ISO_DATE.fullmatch(value) and parse_time(value) < audit_at:
                return f"{key} {value} is before audit_at"
    return None


def _decision(state: ResourceState, category: str, rule: Rule | None, finding: str | None, remediation: str | None,
              verification: str | None, facet: Facet | None, review: str | None = None) -> Decision:
    proof = facet.proof if facet else None
    return Decision(state.system_id, state.resource_id, category, rule.rule_id if rule else None,
                    finding, proof if finding else None, remediation, verification, proof, review)


def decide(state: ResourceState, category: str, rules: Mapping[str, Rule], audit_at: datetime,
           observations: Iterable[Observation]) -> Decision:
    """Apply the decision table (design §4.3). Anything outside it is flagged for review, never guessed."""
    rule = rules.get(category)
    existence, identity, flow, restore = state.existence, state.identity, state.flow, state.restore

    def review(reason: str) -> Decision:
        return _decision(state, category, rule, None, None, None, None, reason)

    if category == DATA_FLOW:
        if flow is None:
            return review("data flow without a flow state")
        if flow.value == "active":
            return _decision(state, category, None, "REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW",
                             "VERIFY_DATA_FLOW_DISABLED", flow)
        return _decision(state, category, None, None, None, "VERIFY_DATA_FLOW_DISABLED", flow)
    if rule is None:
        return review(f"no rule for category {category}")
    expired = _retention_expired(observations, audit_at) if rule.action == "RETAIN" else None
    if expired:
        return review(f"rule condition not met: {expired}")

    if rule.action == "RETAIN":
        if restore is not None:
            if restore.value == "open":
                return _decision(state, category, rule, "REPORT_RESTORE_RISK", "BLOCK_RESTORE",
                                 "VERIFY_RESTORE_BLOCKED", restore)
            return _decision(state, category, rule, None, None, "VERIFY_RESTORE_BLOCKED", restore)
        if existence is not None and existence.value == "present":
            return _decision(state, category, rule, None, None, "VERIFY_RECORD_PRESENT", existence)
        return review("retained record is not present")

    if existence is None:
        return review("existence unknown")
    if rule.action == "DELETE":
        if existence.value == "present":
            return _decision(state, category, rule, "REPORT_REMAINING_RECORD", "DELETE_RECORD",
                             "VERIFY_RECORD_ABSENT", existence)
        return _decision(state, category, rule, None, None, "VERIFY_RECORD_ABSENT", existence)

    if existence.value == "absent":
        return review(f"record to {rule.action.lower()} is absent")
    if identity is None:
        return review("identity unknown for a record to " + rule.action.lower())
    remediation, verification = (("REDACT_RECORD", "VERIFY_RECORD_REDACTED") if rule.action == "REDACT"
                                 else ("ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED"))
    if identity.value == "identifiable":
        return _decision(state, category, rule, "REPORT_EXPOSED_PII", remediation, verification, identity)
    return _decision(state, category, rule, None, None, verification, identity)
