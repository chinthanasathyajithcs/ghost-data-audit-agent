"""Stage 3 — identity resolution: who is the subject, under every identifier they have ever held?

Exact lookups only (C-ID-4): emails case-insensitive, whole tokens, never names or substrings.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from deletion_audit.contract import parse_time, read_csv

IDENTITY_FIELDS = ("email", "phone", "email_hash")

EMAIL_TOKEN = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
HASH_TOKEN = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
USER_ID_TOKEN = re.compile(r"\buser_\d+\b")


def normalise(kind: str, value: str) -> str:
    value = value.strip()
    if kind in ("email", "email_hash"):
        return value.lower()
    if kind == "phone":
        return "+" + re.sub(r"\D", "", value)
    return value


def _phone_pattern(phones: Iterable[str]) -> re.Pattern | None:
    """Known phones as written in the identity files, or compactly as +digits; no digit may touch them."""
    written = [p.strip() for p in phones]
    variants = set(written) | {normalise("phone", p) for p in written}
    if not variants:
        return None
    alternation = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    return re.compile(rf"(?<![\d+])(?:{alternation})(?!\d)")


@dataclass(frozen=True)
class Identifier:
    kind: str
    value: str  # normalised
    written: str  # as spelled in the identity files
    current: bool
    valid_from: str | None  # None: held since before the audit log starts
    valid_to: str | None  # None: still held


@dataclass(frozen=True)
class Subject:
    user_id: str
    name: str
    request_email: str
    matched_via: str  # "current" or "historical"
    identifiers: tuple[Identifier, ...]

    def values(self, kind: str) -> set[str]:
        return {i.value for i in self.identifiers if i.kind == kind}

    def find_in_text(self, text: str) -> set[Identifier]:
        """The subject's identifiers that appear in `text` as whole tokens."""
        by_key = {(i.kind, i.value): i for i in self.identifiers}
        phones = [i.written for i in self.identifiers if i.kind == "phone"]
        return {by_key[key] for key in _tokens(text, _phone_pattern(phones)) if key in by_key}


def _tokens(text: str, phone_pattern: re.Pattern | None) -> set[tuple[str, str]]:
    found = {("email", m.lower()) for m in EMAIL_TOKEN.findall(text)}
    found |= {("email_hash", m.lower()) for m in HASH_TOKEN.findall(text)}
    found |= {("user_id", m) for m in USER_ID_TOKEN.findall(text)}
    if phone_pattern is not None:
        found |= {("phone", normalise("phone", m)) for m in phone_pattern.findall(text)}
    return found


def _identifier(kind: str, written: str, current: bool, valid_from: str | None, valid_to: str | None) -> Identifier:
    return Identifier(kind, normalise(kind, written), written.strip(), current, valid_from, valid_to)


def _timeline(user: Mapping[str, str], events: list[Mapping[str, str]], kind: str) -> list[Identifier]:
    """Replay one field's history: every value held, with the window it was held in."""
    changes = sorted((e for e in events if e["field_name"] == kind), key=lambda e: e["event_time"])
    if not changes:
        return [_identifier(kind, user[kind], True, None, None)]
    held = [_identifier(kind, changes[0]["old_value"], False, None, changes[0]["event_time"])]
    for change, following in zip(changes, changes[1:] + [None]):
        held.append(_identifier(kind, change["new_value"], following is None,
                                change["event_time"], following["event_time"] if following else None))
    return held


class IdentityIndex:
    """All users' identifier timelines, plus a reverse index from any identifier to its owner."""

    def __init__(self, identities: Iterable[Mapping[str, str]], audit_log: Iterable[Mapping[str, str]]) -> None:
        events = defaultdict(list)
        for event in audit_log:
            events[event["user_id"]].append(event)
        self._users: dict[str, Mapping[str, str]] = {}
        self._timelines: dict[str, tuple[Identifier, ...]] = {}
        self._owners: dict[tuple[str, str], str] = {}
        for user in identities:
            user_id = user["user_id"]
            timeline = [_identifier("user_id", user_id, True, None, None)]
            for kind in IDENTITY_FIELDS:
                timeline += _timeline(user, events[user_id], kind)
            self._users[user_id] = user
            self._timelines[user_id] = tuple(timeline)
            for identifier in timeline:
                self._owners[(identifier.kind, identifier.value)] = user_id
        self._phone_pattern = _phone_pattern(
            i.written for timeline in self._timelines.values() for i in timeline if i.kind == "phone"
        )

    @classmethod
    def from_dataset(cls, dataset_dir: Path) -> IdentityIndex:
        return cls(read_csv(dataset_dir / "user_identities.csv"), read_csv(dataset_dir / "user_audit_log.csv"))

    def owner_of(self, kind: str, value: str) -> str | None:
        return self._owners.get((kind, normalise(kind, value)))

    def resolve(self, email: str, audit_at: datetime) -> Subject | None:
        """The person behind a request email (current or historical), with identifiers held up to audit_at."""
        user_id = self.owner_of("email", email)
        if user_id is None:
            return None
        user = self._users[user_id]
        identifiers = tuple(
            i for i in self._timelines[user_id] if i.valid_from is None or parse_time(i.valid_from) <= audit_at
        )
        matched_via = "current" if normalise("email", email) == normalise("email", user["email"]) else "historical"
        return Subject(user_id, user["name"], normalise("email", email), matched_via, identifiers)

    def owners_in_text(self, text: str) -> dict[str, set[tuple[str, str]]]:
        """Every user named in `text`, with the identifiers that name them."""
        owners: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for key in _tokens(text, self._phone_pattern):
            user_id = self._owners.get(key)
            if user_id is not None:
                owners[user_id].add(key)
        return dict(owners)
