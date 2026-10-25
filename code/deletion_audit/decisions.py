"""Stages 5–6 together: for each case file, every resource's state, category and policy decision."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from deletion_audit.category import CategoryClassifier
from deletion_audit.evidence import EvidenceStore
from deletion_audit.linking import CaseFile
from deletion_audit.policy import Decision, Rule, decide
from deletion_audit.state import resolve_state


def classify_cases(case_files: Mapping[str, CaseFile | None], classifier: CategoryClassifier) -> dict[str, tuple[str, str]]:
    """One batched classification for every resource of every case, keyed "case_id/resource_id"."""
    resources, systems = {}, {}
    for case_id, case_file in case_files.items():
        for r in case_file.resources if case_file else ():
            resources[f"{case_id}/{r.resource_id}"] = list(r.observations)
            systems[f"{case_id}/{r.resource_id}"] = r.system_id
    return classifier.classify(resources, systems)


def case_decisions(case_file: CaseFile, store: EvidenceStore, audit_at: datetime,
                   categories: Mapping[str, tuple[str, str]], rules: Mapping[str, Rule]) -> list[Decision]:
    decisions = []
    subject_files = {o.evidence_id for r in case_file.resources for o in r.observations}
    for r in case_file.resources:
        state = resolve_state(r, store.coverage, audit_at, store.files_by_resource, subject_files)
        category, _ = categories[f"{case_file.case_id}/{r.resource_id}"]
        decisions.append(decide(state, category, rules, audit_at, r.observations))
    return decisions
