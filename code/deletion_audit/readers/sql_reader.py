"""SQL snapshots (SQLite-compatible): generic pairs, typed pairs and inventories."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from deletion_audit.observations import Coverage, Observation, fields_text

CAPTURED_AT = re.compile(r"--\s*Captured at:\s*(\S+)")
COPY_SUFFIX = re.compile(r"_(?:primary|(?:[a-z]+_)?replica(?:_[a-z_]+)?)$")
SCOPE_TABLE = "snapshot_scope"


def table_label(table: str) -> str:
    """customer_profiles_failover_replica -> customer_profiles; search_documents_primary -> search_documents."""
    return COPY_SUFFIX.sub("", table)


def read_sql(path: Path, evidence_id: str, captured_at: str) -> tuple[list[Observation], list[Coverage]]:
    script = path.read_text(encoding="utf-8")
    header = CAPTURED_AT.search(script)
    snapshot_time = header.group(1) if header else captured_at
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(script)
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        rows = {t: [dict(r) for r in connection.execute(f'SELECT * FROM "{t}"')] for t in tables}
    finally:
        connection.close()

    coverage = [Coverage(evidence_id, r["captured_at"], SCOPE_TABLE, None, r["origin_system"], captured_at)
                for r in rows.pop(SCOPE_TABLE, [])]
    observations = []
    for table, table_rows in rows.items():
        coverage += _table_coverage(evidence_id, snapshot_time, table, table_rows, captured_at)
        observations += [_observation(evidence_id, captured_at, snapshot_time, table, row)
                         for row in table_rows if row.get("resource_id")]
    return observations, coverage


def _table_coverage(evidence_id: str, time: str, table: str, rows: list[dict], file_time: str) -> list[Coverage]:
    pairs = {(r.get("origin_system"), r.get("collection_name")) for r in rows if r.get("origin_system")}
    if pairs:
        return [Coverage(evidence_id, time, table, label, system, file_time) for system, label in sorted(pairs)]
    return [Coverage(evidence_id, time, table, table_label(table), None, file_time)]


def _observation(evidence_id: str, captured_at: str, snapshot_time: str, table: str, row: dict) -> Observation:
    fields = {k: v for k, v in row.items() if k not in ("resource_id", "record_json")}
    if row.get("record_json"):
        record = json.loads(row["record_json"])
        fields = {**fields, **{k: v for k, v in record.items() if k != "resource_id"}}
    return Observation(
        evidence_id=evidence_id,
        captured_at=captured_at,
        observed_at=row.get("updated_at") or snapshot_time,
        system_id=row.get("origin_system"),
        resource_id=row["resource_id"],
        location=table,
        label=row.get("collection_name") or table_label(table),
        fields=fields,
        text=fields_text(fields),
    )
