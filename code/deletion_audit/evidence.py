"""All evidence in one place: observations with resolved system IDs, coverage, owners and activity."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterable

from deletion_audit.contract import read_csv
from deletion_audit.identity import IdentityIndex
from deletion_audit.observations import Coverage, Observation, is_resource_id, resource_prefix
from deletion_audit.readers import read_handover, read_json, read_log, read_sql

READERS = {".sql": read_sql, ".json": read_json, ".log": read_log, ".txt": read_handover}
DOCUMENT_SUFFIXES = (".pdf", ".png")
ACTIVITY_SYSTEM_SOURCES = ("deletion_worker", "data_catalog")
CATALOG_ALIAS = re.compile(r"linked (\S+) \(([^)]+)\) (?:to|belongs)")
NOT_AN_ALIAS = re.compile(r"^user_\d+$|@")  # person references are never document aliases

DocumentReader = Callable[[Path, str, str], tuple[list[Observation], list[Coverage]]]


def learn_map(pairs: Iterable[tuple[str, str]]) -> tuple[dict[str, str], dict[str, Counter]]:
    """Majority vote key -> value; keys with more than one value are returned as conflicts."""
    votes: dict[str, Counter] = defaultdict(Counter)
    for key, value in pairs:
        votes[key][value] += 1
    mapping = {key: counter.most_common(1)[0][0] for key, counter in votes.items()}
    conflicts = {key: counter for key, counter in votes.items() if len(counter) > 1}
    return mapping, conflicts


class EvidenceStore:
    def __init__(self, observations: list[Observation], coverage: list[Coverage], owners: list[frozenset],
                 activity: list[dict], system_conflicts: dict[str, Counter], skipped: list[str],
                 unkeyed: list[Observation]) -> None:
        self.observations = observations
        self.unkeyed = unkeyed  # document records with no resource ID (kept so catalog aliases can find them)
        self.coverage = coverage
        self.activity = activity
        self.system_conflicts = system_conflicts
        self.skipped = skipped
        self._owners = {id(o): owner for o, owner in zip(observations, owners)}
        self.files_by_resource: dict[str, set[str]] = defaultdict(set)  # evidence files that show each resource
        for o in observations:
            self.files_by_resource[o.resource_id].add(o.evidence_id)
        self._by_resource: dict[str, list[Observation]] = defaultdict(list)
        for o in sorted(observations, key=lambda o: (o.observed_at, o.evidence_id, o.location)):
            self._by_resource[o.resource_id].append(o)

    @classmethod
    def build(cls, observations: list[Observation], coverage: list[Coverage], identity: IdentityIndex,
              activity: list[dict], skipped: list[str] | None = None) -> EvidenceStore:
        unkeyed = [o for o in observations if not is_resource_id(o.resource_id)]
        observations = [o for o in observations if is_resource_id(o.resource_id)]
        prefixes, conflicts = learn_map((resource_prefix(o.resource_id), o.system_id)
                                        for o in observations if o.system_id)
        # Fallback for prefixes no evidence file states: the system the deletion worker or catalog targeted.
        targeted, _ = learn_map((resource_prefix(a["resource_id"]), a["target_system"]) for a in activity
                                if a["source_system"] in ACTIVITY_SYSTEM_SOURCES)
        prefixes = {**targeted, **prefixes}
        known_systems = set(prefixes.values())
        resolved = [replace(o, system_id=_system_for(o, prefixes, known_systems)) for o in observations]
        resolved += _alias_observations(activity, resolved + unkeyed)
        labels, _ = learn_map((o.label, o.system_id) for o in resolved if o.label and o.system_id)
        coverage = [c if c.system_id else replace(c, system_id=labels.get(c.label)) for c in coverage]
        owners = [frozenset(identity.owners_in_text(o.text)) for o in resolved]
        return cls(resolved, coverage, owners, activity, conflicts, skipped or [], unkeyed)

    @classmethod
    def load(cls, dataset_dir: Path, identity: IdentityIndex,
             document_reader: DocumentReader | None = None) -> EvidenceStore:
        observations: list[Observation] = []
        coverage: list[Coverage] = []
        skipped = []
        for entry in read_csv(dataset_dir / "evidence_files.csv"):
            path = dataset_dir / entry["file_path"]
            reader = READERS.get(path.suffix)
            if reader is None and path.suffix in DOCUMENT_SUFFIXES and document_reader is not None:
                reader = document_reader
            if reader is None:
                skipped.append(entry["file_id"])
                continue
            found, covered = reader(path, entry["file_id"], entry["captured_at"])
            observations += found
            coverage += covered
        activity = read_csv(dataset_dir / "system_activity.csv")
        return cls.build(observations, coverage, identity, activity, skipped)

    def resource_ids(self) -> list[str]:
        return sorted(self._by_resource)

    def resource(self, resource_id: str) -> list[Observation]:
        """Observations of one resource, oldest first."""
        return list(self._by_resource.get(resource_id, []))

    def owners(self, observation: Observation) -> frozenset:
        return self._owners[id(observation)]


def _system_for(o: Observation, prefixes: dict[str, str], known: set[str]) -> str | None:
    """Stated system, else the system learned for the resource prefix, else a known log service."""
    if o.system_id:
        return o.system_id
    learned = prefixes.get(resource_prefix(o.resource_id))
    if learned:
        return learned
    service = o.fields.get("_service")
    return service if service in known else None


def _alias_observations(activity: list[dict], observations: list[Observation]) -> list[Observation]:
    """A catalog claim "linked export_1842 (NST-2026-0718-1842) ..." makes any record showing that display
    reference an observation of the resource. The claim is still checked against evidence in linking (Q10)."""
    aliases = {}
    for row in activity:
        match = CATALOG_ALIAS.search(row["details"]) if row["source_system"] == "data_catalog" else None
        if match and match.group(1) == row["resource_id"] and match.group(2) != row["resource_id"]:
            if not NOT_AN_ALIAS.search(match.group(2)):
                aliases[row["resource_id"]] = (match.group(2), row["target_system"])
    found = []
    for resource_id, (alias, system) in sorted(aliases.items()):
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])")
        found += [replace(o, resource_id=resource_id, system_id=system, location=f"{o.location} (shows {alias})")
                  for o in observations if o.resource_id != resource_id and pattern.search(o.text)]
    return found
