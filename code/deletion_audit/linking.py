"""Stage 4 — the case file: every resource that belongs to the subject, and why (design §4.5–4.7)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from deletion_audit.contract import parse_time
from deletion_audit.evidence import EvidenceStore
from deletion_audit.identity import EMAIL_TOKEN, Subject
from deletion_audit.observations import Observation

ACTIVITY_WINDOW = timedelta(hours=2)  # Stage 0: covers the deletion runs of 30 of 32 samples
DELETION_WORKER = "deletion_worker"
CATALOG_EVENT = "LINK_RESOURCE_IDENTITY"
EXPECTED_RESULT = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}  # H-LK-6
CATALOG_USER = re.compile(r"\b(user_\d+)\b")
ACCOUNT_SYSTEM = "account_service"
# Q9 activity linking: "off", "account" (one primary account, only if none is linked yet) or "all".
ACTIVITY_MODE = "account"


@dataclass(frozen=True)
class LinkedResource:
    system_id: str | None
    resource_id: str
    methods: frozenset[str]  # identifier | propagated | activity | catalog
    observations: tuple[Observation, ...]  # usable ones (observed_at <= audit_at), oldest first


@dataclass(frozen=True)
class CaseFile:
    case_id: str
    subject: Subject
    resources: tuple[LinkedResource, ...]
    rejected: int  # other people's resources in the same evidence files
    conflicts: tuple[str, ...]  # catalog links contradicted by evidence (Q10)


def build_case_file(case_id: str, subject: Subject, requested_at: datetime, audit_at: datetime,
                    reported_at: datetime, reported_status: str, store: EvidenceStore,
                    activity_mode: str = ACTIVITY_MODE) -> CaseFile:
    """Resources in scope belong to the subject and are seen at or after the request (a record already gone
    before the request belongs to an earlier deletion), or were touched by this request's deletion run."""
    usable = {rid: [o for o in store.resource(rid) if parse_time(o.observed_at) <= audit_at]
              for rid in store.resource_ids()}
    owners = {rid: frozenset().union(*(store.owners(o) for o in obs)) for rid, obs in usable.items()}

    linked: dict[str, set[str]] = {}
    for rid, obs in usable.items():
        if subject.user_id in owners[rid]:
            naming = [subject.user_id in store.owners(o) for o in obs]
            linked[rid] = {"identifier"} | ({"propagated"} if not all(naming) else set())
    owned_by_others = {rid for rid, who in owners.items() if who and subject.user_id not in who}

    conflicts = []
    for rid in _catalog_claims(subject, audit_at, store):
        if rid in linked:
            continue
        if _contradicts(subject, usable.get(rid, []), store):
            conflicts.append(rid)
        else:
            linked[rid] = {"catalog"}

    linked = {rid: methods for rid, methods in linked.items()
              if any(parse_time(o.observed_at) >= requested_at for o in usable.get(rid, []))}

    if activity_mode != "off":
        has_account = any(_system_of(rid, usable, store) == ACCOUNT_SYSTEM for rid in linked)
        owned = {rid for rid, who in owners.items() if who}  # incl. the subject's out-of-scope resources
        leads = _activity_leads(reported_at, reported_status, audit_at, store, set(linked) | owned)
        for rid, is_account in leads:
            if activity_mode == "all" or (is_account and not has_account):
                linked[rid] = {"activity"}

    subject_files = {o.evidence_id for rid in linked for o in usable.get(rid, [])}
    rejected = sum(1 for rid in owned_by_others if any(o.evidence_id in subject_files for o in usable[rid]))
    resources = tuple(sorted((_linked(rid, methods, usable.get(rid, []), store) for rid, methods in linked.items()),
                             key=lambda r: (r.system_id or "", r.resource_id)))
    return CaseFile(case_id, subject, resources, rejected, tuple(sorted(conflicts)))


def _system_of(rid: str, usable: dict[str, list[Observation]], store: EvidenceStore) -> str | None:
    system = next((o.system_id for o in reversed(usable.get(rid, [])) if o.system_id), None)
    return system or next((a["target_system"] for a in store.activity if a["resource_id"] == rid), None)


def _linked(rid: str, methods: set[str], observations: list[Observation], store: EvidenceStore) -> LinkedResource:
    system = _system_of(rid, {rid: observations}, store)
    return LinkedResource(system, rid, frozenset(methods), tuple(observations))


def _catalog_claims(subject: Subject, audit_at: datetime, store: EvidenceStore) -> list[str]:
    claims = []
    for row in store.activity:
        if row["event_type"] != CATALOG_EVENT or parse_time(row["event_time"]) > audit_at:
            continue
        users = set(CATALOG_USER.findall(row["details"]))
        emails = {e.lower() for e in EMAIL_TOKEN.findall(row["details"])}
        if subject.user_id in users or emails & subject.values("email"):
            claims.append(row["resource_id"])
    return claims


def _contradicts(subject: Subject, observations: list[Observation], store: EvidenceStore) -> bool:
    """Evidence names someone else: another user's identifier, or an email that is not the subject's."""
    for o in observations:
        if store.owners(o) - {subject.user_id}:
            return True
        if {e.lower() for e in EMAIL_TOKEN.findall(o.text)} - subject.values("email"):
            return True
    return False


def _activity_leads(reported_at: datetime, reported_status: str, audit_at: datetime, store: EvidenceStore,
                    excluded: set[str]) -> list[tuple[str, bool]]:
    """Q9: deletion-worker work on unowned resources near the reported time, as (resource, is_primary_account);
    at most one primary account, settled by the reported status when several compete (H-LK-6)."""
    rows = [r for r in store.activity
            if r["source_system"] == DELETION_WORKER
            and abs(parse_time(r["event_time"]) - reported_at) <= ACTIVITY_WINDOW
            and parse_time(r["event_time"]) <= audit_at
            and r["resource_id"] not in excluded]
    accounts = [r for r in rows if r["target_system"] == ACCOUNT_SYSTEM and r["event_type"] == "DELETE_RECORD"]
    leads = [(rid, False) for rid in dict.fromkeys(r["resource_id"] for r in rows if r not in accounts)]
    if len(accounts) > 1:
        accounts = [r for r in accounts if r["reported_result"] == EXPECTED_RESULT.get(reported_status)]
    if len(accounts) == 1:
        leads.append((accounts[0]["resource_id"], True))
    return leads
