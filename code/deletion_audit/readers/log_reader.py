"""Logs in eight line styles, normalised to (time, service, trace, pairs) and joined by trace id (C-LK-2)."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from deletion_audit.observations import Coverage, Observation, fields_text, is_resource_id

LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+(.*)$")
PAIR = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')
TRACE = re.compile(r"^(?:tr|rb)-[\w-]+$")
SYSLOG = re.compile(r"^<\d+>\d+ \S+ (\S+) (\S+) \S+ \S+ ?(.*)$")
BRACKETED = re.compile(r"^\[\w+\] \[([^\]]+)\] \[([^\]]+)\] ([\w.-]+):? ?(.*)$")
PIPED = re.compile(r"^\|\s*\w+\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(.*)$")


@dataclass(frozen=True)
class LogLine:
    number: int
    time: str
    service: str | None
    trace: str | None
    event: str | None
    pairs: dict
    raw: str


def _pairs(text: str) -> dict:
    pairs = {}
    for key, raw in PAIR.findall(text):
        value = json.loads(raw) if raw.startswith('"') else raw
        if key == "message" and isinstance(value, str) and "=" in value:
            pairs.update(_pairs(value))
        else:
            pairs[key] = value
    return pairs


def parse_line(number: int, line: str) -> LogLine | None:
    match = LINE.match(line.strip())
    if not match:
        return None
    time, rest = match.groups()
    service = trace = event = None
    if rest.startswith("{"):
        pairs = json.loads(rest)
    elif m := SYSLOG.match(rest):
        service, trace, pairs = m.group(1), m.group(2), _pairs(m.group(3))
    elif m := BRACKETED.match(rest):
        service, trace, event, pairs = m.group(1), m.group(2), m.group(3), _pairs(m.group(4))
    elif m := PIPED.match(rest):
        service, trace, event, pairs = m.group(1), m.group(2), m.group(3), _pairs(m.group(4))
    else:
        pairs = _pairs(rest)
    service = service or pairs.get("service") or pairs.get("logger") or pairs.get("function")
    trace = trace or pairs.get("trace_id") or pairs.get("requestId")
    return LogLine(number, time, service, trace if trace and TRACE.match(trace) else None,
                   event or pairs.get("event"), pairs, line.rstrip("\n"))


def _resources(line: LogLine) -> list[str]:
    return [v for v in line.pairs.values() if is_resource_id(v)]


def read_log(path: Path, evidence_id: str, captured_at: str) -> tuple[list[Observation], list[Coverage]]:
    lines = [p for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if (p := parse_line(n, raw))]
    traces: dict[str, list[LogLine]] = defaultdict(list)
    observations = []
    for line in lines:
        if line.trace:
            traces[line.trace].append(line)
        else:
            observations += [_observation([line], r, f"line {line.number}", evidence_id, captured_at)
                             for r in dict.fromkeys(_resources(line))]
    for trace, group in traces.items():
        resources = dict.fromkeys(r for line in group for r in _resources(line))
        observations += [_observation(group, r, f"trace {trace}", evidence_id, captured_at) for r in resources]
    return observations, []


def _observation(group: list[LogLine], resource_id: str, location: str, evidence_id: str,
                 captured_at: str) -> Observation:
    merged: dict = {}
    for line in group:
        merged.update(line.pairs)
    naming = [line for line in group if resource_id in line.pairs.values()]
    fields = {
        **merged,
        "_service": naming[-1].service,
        "_event": group[-1].event,
        "_events": [{"time": line.time, "service": line.service, "event": line.event, **line.pairs} for line in group],
    }
    return Observation(
        evidence_id=evidence_id,
        captured_at=captured_at,
        observed_at=group[-1].time,
        system_id=merged.get("system") if isinstance(merged.get("system"), str) else None,
        resource_id=resource_id,
        location=location,
        label=merged.get("record_type"),
        fields=fields,
        text="\n".join(line.raw for line in group) + "\n" + fields_text(merged),
    )
