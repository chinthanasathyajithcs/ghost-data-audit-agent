"""Shift-handover text: `time | system_id | resource_id | CATEGORY | STATE | identifier` per line."""

from __future__ import annotations

from pathlib import Path

from deletion_audit.observations import Coverage, Observation, is_resource_id

COLUMNS = ("time", "system_id", "resource_id", "category", "state", "identifier")


def read_handover(path: Path, evidence_id: str, captured_at: str) -> tuple[list[Observation], list[Coverage]]:
    observations = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        parts = [p.strip() for p in line.lstrip("-* ").split("|")]  # lines are bullets: "- time | ..."
        if len(parts) != len(COLUMNS) or not is_resource_id(parts[2]):
            continue
        row = dict(zip(COLUMNS, parts))
        fields = {"category": row["category"], "state": row["state"], "identifier": row["identifier"]}
        observations.append(Observation(
            evidence_id=evidence_id,
            captured_at=captured_at,
            observed_at=row["time"],
            system_id=row["system_id"],
            resource_id=row["resource_id"],
            location=f"line {number}",
            label=row["category"],
            fields=fields,
            text=line,
        ))
    return observations, []
