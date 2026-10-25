"""JSON evidence: one generic walk. Every object with a resource_id is a record; context comes from ancestors."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from deletion_audit.observations import Coverage, Observation, fields_text

SYSTEM_KEYS = ("system", "data_store", "origin_system")
LABEL_KEYS = ("collection", "collection_name", "record_type")
TIME_KEYS = ("observed_at", "recorded_at", "captured_at", "updated_at")
FILE_TIME_KEYS = ("exported_at",)
SYSTEM_CONTAINER = "service_exports"  # {"service_exports": {<system_id>: {<collection>: [records]}}}


@dataclass(frozen=True)
class _Context:
    system: str | None
    label: str | None
    time: str
    path: str
    parent: dict | None


def read_json(path: Path, evidence_id: str, captured_at: str) -> tuple[list[Observation], list[Coverage]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    file_time = next((data[k] for k in FILE_TIME_KEYS if isinstance(data, dict) and data.get(k)), captured_at)
    observations: list[Observation] = []
    coverage: list[Coverage] = []
    _walk(data, _Context(None, None, file_time, "", None), evidence_id, captured_at, observations, coverage)
    return observations, coverage


def _scalars(node: dict) -> dict:
    """A record's surroundings without its lists: scalars and nested objects only."""
    return {k: (_scalars(v) if isinstance(v, dict) else v) for k, v in node.items() if not isinstance(v, list)}


def _with_node(ctx: _Context, node: dict) -> _Context:
    system = next((node[k] for k in SYSTEM_KEYS if isinstance(node.get(k), str)), ctx.system)
    label = next((node[k] for k in LABEL_KEYS if isinstance(node.get(k), str)), ctx.label)
    time = next((node[k] for k in TIME_KEYS if isinstance(node.get(k), str)), ctx.time)
    return replace(ctx, system=system, label=label, time=time)


def _walk(node, ctx: _Context, evidence_id: str, captured_at: str, out: list, coverage: list) -> None:
    if isinstance(node, list):
        for index, item in enumerate(node):
            parent = _scalars(item) if isinstance(item, dict) and "resource_id" not in item else ctx.parent
            _walk(item, replace(ctx, path=f"{ctx.path}[{index}]", parent=parent), evidence_id, captured_at, out,
                  coverage)
        return
    if not isinstance(node, dict):
        return
    ctx = _with_node(ctx, node)
    if isinstance(node.get("resource_id"), str):
        out.append(_observation(node, ctx, evidence_id, captured_at))
        return
    if isinstance(node.get("records"), list) and (ctx.system or ctx.label):
        coverage.append(Coverage(evidence_id, ctx.time, f"{ctx.system or ''}/{ctx.label or ''}", ctx.label,
                                 ctx.system, captured_at))
    for key, value in node.items():
        if key == SYSTEM_CONTAINER and isinstance(value, dict):
            _walk_systems(value, ctx, evidence_id, captured_at, out, coverage)
        elif isinstance(value, (dict, list)):
            _walk(value, replace(ctx, path=f"{ctx.path}.{key}"), evidence_id, captured_at, out, coverage)


def _walk_systems(systems: dict, ctx: _Context, evidence_id: str, captured_at: str, out: list, coverage: list) -> None:
    for system, collections in systems.items():
        if not isinstance(collections, dict):
            continue
        for collection, items in collections.items():
            inner = replace(ctx, system=system, label=collection, path=f"{SYSTEM_CONTAINER}.{system}.{collection}")
            coverage.append(Coverage(evidence_id, ctx.time, f"{system}/{collection}", collection, system, captured_at))
            _walk(items, inner, evidence_id, captured_at, out, coverage)


def _observation(node: dict, ctx: _Context, evidence_id: str, captured_at: str) -> Observation:
    fields = {k: v for k, v in node.items() if k != "resource_id"}
    if ctx.parent:
        fields["_parent"] = ctx.parent
    return Observation(
        evidence_id=evidence_id,
        captured_at=captured_at,
        observed_at=ctx.time,
        system_id=ctx.system,
        resource_id=node["resource_id"],
        location=ctx.path.lstrip(".") or "records",
        label=ctx.label,
        fields=fields,
        text=fields_text(fields),
    )
