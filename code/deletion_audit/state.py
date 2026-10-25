"""Stage 5 — the state of each linked resource at audit_at, judged from evidence (never from claims).

Four facets, each decided by the latest observation up to audit_at that speaks to it (design §4):
existence (present/absent), identity (identifiable/redacted/anonymized), flow (active/disabled),
restore (open/blocked). Each facet keeps the citable file that proves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping

from deletion_audit.contract import parse_time
from deletion_audit.identity import EMAIL_TOKEN
from deletion_audit.linking import LinkedResource
from deletion_audit.observations import Coverage, Observation

FACETS = ("existence", "identity", "flow", "restore")
STATE_FIELDS = ("state", "result")  # explicit states in handovers, record-lookup logs and ledgers
DIRECT_IDENTIFIERS = {"email", "phone", "full_name", "display_name", "name", "email_hash", "requester_email",
                      "requester_name", "requester_phone", "owner_email", "owner_phone", "customer_email"}
REFERENCES = {"customer_reference", "subject_reference", "user_id"}
NESTED = ("document", "profile")
FREE_TEXT = ("message_text", "message_excerpt")
EMPTY = {"", "null", "none", "[redacted]"}
# When copies observed at the same time disagree, the more exposed value wins (C-ST-4).
EXPOSURE = {"existence": ("present", "absent"), "identity": ("identifiable", "redacted", "anonymized"),
            "flow": ("active", "disabled"), "restore": ("open", "blocked")}


@dataclass(frozen=True)
class Facet:
    value: str
    as_of: str  # time of the deciding observation or snapshot
    proof: str | None  # citable evidence_id (captured at or before audit_at), if any
    basis: str  # "observation" or "coverage"


@dataclass(frozen=True)
class ResourceState:
    system_id: str | None
    resource_id: str
    existence: Facet | None
    identity: Facet | None
    flow: Facet | None
    restore: Facet | None


def _text(value: object) -> str:
    return str(value).strip().lower()


def _empty(value: object) -> bool:
    return value is None or _text(value) in EMPTY


def _truth(value: object) -> bool | None:
    text = _text(value)
    return True if text in ("true", "1", "yes") else False if text in ("false", "0", "no") else None


def _explicit_state(word: str, label: str | None) -> dict[str, str]:
    is_backup = "backup" in (label or "").lower()
    return {
        "found": {"existence": "present"},
        "not_found": {"existence": "absent"},
        "identifiable": {"existence": "present", "identity": "identifiable"},
        "anonymized": {"existence": "present", "identity": "anonymized"},
        "redacted": {"existence": "present", "identity": "redacted"},
        "active": {"restore": "open"} if is_backup else {"flow": "active"},
        "disabled": {"restore": "blocked"} if is_backup else {"flow": "disabled"},
        "blocked": {"restore": "blocked"},
    }.get(word, {})


def _identity(fields: Mapping) -> str | None:
    flat = dict(fields)
    for key in NESTED:
        if isinstance(fields.get(key), dict):
            flat.update(fields[key])
    if any(not _empty(fields.get(k)) and EMAIL_TOKEN.search(str(fields[k])) for k in FREE_TEXT):
        return "identifiable"
    direct = [flat[k] for k in DIRECT_IDENTIFIERS if k in flat]
    if not direct:
        return None
    if any(not _empty(v) for v in direct):
        return "identifiable"
    return "redacted" if any(not _empty(flat.get(k)) for k in REFERENCES) else "anonymized"


def read_signals(o: Observation) -> dict[str, str]:
    """What one observation says, facet by facet. Explicit states win over inferred ones."""
    events = o.fields.get("_events")
    if events:  # a log trace: merge its lines, leaving out cache lookups (a cache miss is not a missing record)
        f = {k: v for e in events if "cache" not in _text(e.get("event", "")) for k, v in e.items()}
    else:
        f = {k: v for k, v in o.fields.items() if not k.startswith("_")}
    parent = o.fields.get("_parent") or {}
    signals: dict[str, str] = {}

    def put(facet: str, value: str) -> None:
        signals.setdefault(facet, value)

    for key in STATE_FIELDS:
        for facet, value in _explicit_state(_text(f.get(key, "")), o.label).items():
            put(facet, value)
    if _text(f.get("rows", "")).isdigit():
        put("existence", "present" if int(_text(f["rows"])) > 0 else "absent")
    for key in ("http_status", "status_code"):
        if _text(f.get(key, "")) in ("200", "404"):
            put("existence", "present" if _text(f[key]) == "200" else "absent")
    if _text(f.get("result", "")) in ("hit", "miss"):
        put("existence", "present" if _text(f["result"]) == "hit" else "absent")
    hits = f.get("total_hits", (parent.get("hits") or {}).get("total"))
    if _text(hits).isdigit():
        put("existence", "present" if int(_text(hits)) > 0 else "absent")
    for key in ("available", "download_available"):
        if _truth(f.get(key)) is not None:
            put("existence", "present" if _truth(f[key]) else "absent")

    for key in ("enabled", "scheduler_registered"):
        if _truth(f.get(key)) is not None:
            put("flow", "active" if _truth(f[key]) else "disabled")
    if _truth(f.get("restore_allowed")) is not None:
        put("restore", "open" if _truth(f["restore_allowed"]) else "blocked")
    if _truth(f.get("deletion_block")) is True or _text(f.get("decision", "")) == "deny":
        put("restore", "blocked")
    if _truth(f.get("eligible")) is True and _truth(f.get("deletion_block")) is False:
        put("restore", "open")

    if _text(f.get("direct_identifiers", "")) in ("0", "1"):
        put("identity", "identifiable" if _text(f["direct_identifiers"]) == "1" else "anonymized")
    if "pii_scan" in _text(f.get("event", "")) and not _empty(f.get("matched_value")):
        put("identity", "identifiable")
    if _text(f.get("message_text", "")) == "[redacted]":
        put("identity", "redacted")
    if "state" not in f:  # handover lines name the lookup identifier, not the record's contents
        identity = _identity(f)
        if identity:
            put("identity", identity)

    if not o.location.startswith(("trace ", "line ")) or ({"identity", "flow", "restore"} & signals.keys()):
        put("existence", "present")  # a row exists, and so does anything whose contents or settings were read
    return signals


def _citable(o: Observation, audit_at: datetime) -> bool:
    return parse_time(o.captured_at) <= audit_at


def _decide(facet: str, observations: Iterable[Observation], audit_at: datetime) -> Facet | None:
    speaking = [(o, read_signals(o)[facet]) for o in observations if facet in read_signals(o)]
    if not speaking:
        return None
    latest = max(o.observed_at for o, _ in speaking)
    group = [(o, v) for o, v in speaking if o.observed_at == latest]
    value = min((v for _, v in group), key=EXPOSURE[facet].index)
    agreeing = sorted((o for o, v in speaking if v == value and _citable(o, audit_at)),
                      key=lambda o: (o.observed_at, o.evidence_id), reverse=True)
    in_group = [o for o in agreeing if o.observed_at == latest]
    proof = (in_group or agreeing or [None])[0]
    return Facet(value, latest, proof.evidence_id if proof else None, "observation")


def _absence_from_coverage(resource: LinkedResource, coverage: list[Coverage], audit_at: datetime,
                           present_in: Mapping[str, set[str]]) -> Facet | None:
    """A covering snapshot (captured by audit_at) with no row for the resource proves it absent."""
    seen = present_in.get(resource.resource_id, set())
    covering = [c for c in coverage if c.system_id == resource.system_id and c.evidence_id not in seen
                and parse_time(c.captured_at) <= audit_at]
    if not covering:
        return None
    latest = max(covering, key=lambda c: (c.captured_at, c.evidence_id))
    return Facet("absent", latest.captured_at, latest.evidence_id, "coverage")


def resolve_state(resource: LinkedResource, coverage: list[Coverage], audit_at: datetime,
                  present_in: Mapping[str, set[str]]) -> ResourceState:
    """`resource.observations` are already limited to observed_at <= audit_at (Stage 4)."""
    facets = {facet: _decide(facet, resource.observations, audit_at) for facet in FACETS}
    existence = facets["existence"]
    if existence is None:
        facets["existence"] = _absence_from_coverage(resource, coverage, audit_at, present_in)
    elif existence.value == "absent" and existence.proof is None:
        covered = _absence_from_coverage(resource, coverage, audit_at, present_in)
        if covered is not None:  # the fact stands; a covering snapshot from before the audit can prove it
            facets["existence"] = Facet("absent", existence.as_of, covered.proof, existence.basis)
    if facets["existence"] is not None and facets["existence"].value == "absent":
        facets["identity"] = None  # a record that no longer exists exposes nothing
    return ResourceState(resource.system_id, resource.resource_id, **facets)
