"""Format validator for output.csv (Stage 1 design §4.3). Returns readable errors; empty means valid."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from deletion_audit.contract import (
    OPERATIONS,
    OUTPUT_COLUMNS,
    PHASES,
    STATUSES,
    STEP_FIELDS,
    parse_time,
    read_csv,
    read_csv_header,
    step_sort_key,
)


def load_citation_times(dataset_dir: Path) -> dict[str, datetime]:
    """Every citable ID (file_id, activity_id, audit_id) mapped to the time it became available."""
    sources = (
        ("evidence_files.csv", "file_id", "captured_at"),
        ("system_activity.csv", "activity_id", "event_time"),
        ("user_audit_log.csv", "audit_id", "event_time"),
    )
    return {
        row[id_column]: parse_time(row[time_column])
        for file_name, id_column, time_column in sources
        for row in read_csv(dataset_dir / file_name)
    }


def validate_file(predictions: Path, requests: Path, dataset_dir: Path) -> list[str]:
    return validate_rows(
        read_csv_header(predictions),
        read_csv(predictions),
        read_csv(requests),
        load_citation_times(dataset_dir),
    )


def validate_rows(
    header: Sequence[str],
    rows: Sequence[Mapping[str, str]],
    requests: Sequence[Mapping[str, str]],
    citation_times: Mapping[str, datetime],
) -> list[str]:
    if tuple(header) != OUTPUT_COLUMNS:
        return [f"header is {list(header)}, expected {list(OUTPUT_COLUMNS)}"]

    audit_at = {r["case_id"]: parse_time(r["audit_at"]) for r in requests}
    errors = _coverage_errors(rows, audit_at)
    for row in rows:
        errors.extend(_row_errors(row, audit_at.get(row["case_id"]), citation_times))
    return errors


def _coverage_errors(rows: Sequence[Mapping[str, str]], audit_at: Mapping[str, datetime]) -> list[str]:
    case_ids = [row["case_id"] for row in rows]
    counts = Counter(case_ids)
    errors = [f"missing row for {c}" for c in sorted(set(audit_at) - set(counts))]
    errors += [f"row for unknown case {c}" for c in sorted(set(counts) - set(audit_at))]
    errors += [f"duplicate rows for {c}" for c, n in sorted(counts.items()) if n > 1]
    if case_ids != sorted(case_ids):
        errors.append("rows are not sorted by case_id")
    return errors


def _row_errors(row: Mapping[str, str], audit_at: datetime | None, citation_times: Mapping[str, datetime]) -> list[str]:
    case_id, status = row["case_id"], row["deletion_status"]
    if status not in STATUSES:
        return [f"{case_id}: unknown deletion_status {status!r}"]
    try:
        steps = json.loads(row["steps_json"])
    except json.JSONDecodeError as error:
        return [f"{case_id}: steps_json is not valid JSON ({error})"]
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
        return [f"{case_id}: steps_json must be a JSON array of objects"]

    step_errors = [e for i, s in enumerate(steps, start=1) for e in _step_errors(case_id, i, s)]
    if step_errors:
        return step_errors
    return (
        _order_errors(case_id, steps)
        + _status_errors(case_id, status, steps)
        + _citation_errors(case_id, steps, audit_at, citation_times)
    )


def _step_errors(case_id: str, position: int, step: Mapping) -> list[str]:
    where = f"{case_id}: step {position}"
    if set(step) != set(STEP_FIELDS):
        return [f"{where}: fields are {sorted(step)}, expected {sorted(STEP_FIELDS)}"]
    errors = []
    if step["step_no"] != position:
        errors.append(f"{where}: step_no is {step['step_no']!r}, expected {position}")
    operation = step["operation"]
    if operation not in OPERATIONS:
        return errors + [f"{where}: unknown operation {operation!r}"]
    phase, state = OPERATIONS[operation]
    if step["phase"] != phase:
        errors.append(f"{where}: {operation} belongs to phase {phase}, not {step['phase']!r}")
    if step["state"] != state:
        errors.append(f"{where}: {operation} requires state {state}, not {step['state']!r}")
    for field in ("system_id", "resource_id", "evidence_id"):
        if not isinstance(step[field], str):
            errors.append(f"{where}: {field} must be a string")
    return errors


def _order_errors(case_id: str, steps: list[dict]) -> list[str]:
    phases = [PHASES.index(s["phase"]) for s in steps]
    if phases != sorted(phases):
        return [f"{case_id}: phases out of order (FINDING, REMEDIATION, VERIFICATION)"]
    if steps != sorted(steps, key=step_sort_key):
        return [f"{case_id}: steps out of strict order (phase, operation, system_id, resource_id)"]
    return []


def _status_errors(case_id: str, status: str, steps: list[dict]) -> list[str]:
    phases = {s["phase"] for s in steps}
    if status == "NOT_APPLICABLE":
        return [] if not steps else [f"{case_id}: NOT_APPLICABLE must have steps_json=[]"]
    if status == "COMPLETE":
        errors = [] if steps else [f"{case_id}: COMPLETE needs at least one verification step"]
        if phases - {"VERIFICATION"}:
            errors.append(f"{case_id}: COMPLETE may contain only VERIFICATION steps")
        if any(not s["evidence_id"] for s in steps):
            errors.append(f"{case_id}: COMPLETE verification steps must cite evidence")
        return errors
    errors = [] if "FINDING" in phases else [f"{case_id}: INCOMPLETE needs at least one FINDING"]
    for s in steps:
        if s["phase"] == "FINDING" and not s["evidence_id"]:
            errors.append(f"{case_id}: step {s['step_no']}: finding must cite evidence")
        if s["phase"] != "FINDING" and s["evidence_id"]:
            errors.append(f"{case_id}: step {s['step_no']}: {s['phase']} step must have empty evidence_id")
    return errors


def _citation_errors(
    case_id: str, steps: list[dict], audit_at: datetime | None, citation_times: Mapping[str, datetime]
) -> list[str]:
    errors = []
    for s in steps:
        evidence_id = s["evidence_id"]
        if not evidence_id:
            continue
        if evidence_id not in citation_times:
            errors.append(f"{case_id}: step {s['step_no']}: cites unknown evidence {evidence_id!r}")
        elif audit_at is not None and citation_times[evidence_id] > audit_at:
            errors.append(f"{case_id}: step {s['step_no']}: cites {evidence_id}, captured after audit_at")
    return errors
