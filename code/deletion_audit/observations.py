"""The common record model every evidence reader produces (Stage 4 design §4.2)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# A resource identifier: lowercase words joined by underscores, then _digits (user_N is a person, not a resource).
RESOURCE_ID = re.compile(r"^(?!user_)[a-z]+(?:_[a-z]+)*_\d+$")


@dataclass(frozen=True)
class Observation:
    """One thing one evidence file says about one resource. Raw values only; Stage 5 interprets them."""

    evidence_id: str
    captured_at: str  # manifest time: decides whether the file may be cited
    observed_at: str  # the record's own time: decides whether the fact may be used
    system_id: str | None
    resource_id: str
    location: str  # table, replica, collection path, log trace or document
    label: str | None  # collection, table or record type as written
    fields: dict
    text: str  # everything searchable for identifiers (fields, plus every line of a log trace)


@dataclass(frozen=True)
class Coverage:
    """What a snapshot looked at, so a missing record can later count as proof of absence."""

    evidence_id: str
    captured_at: str
    location: str
    label: str | None
    system_id: str | None
    file_captured_at: str = ""  # manifest time of the file: decides whether the snapshot may be cited


def is_resource_id(value: object) -> bool:
    return isinstance(value, str) and bool(RESOURCE_ID.match(value))


def resource_prefix(resource_id: str) -> str:
    return resource_id.rsplit("_", 1)[0]


def fields_text(fields: dict) -> str:
    return json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
