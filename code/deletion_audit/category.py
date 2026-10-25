"""Stage 6 — each resource's data category (design §4.1).

An explicit category label in the evidence decides; otherwise the LLM classifies the resource's
evidence signature (structure and descriptive values, identifiers removed) against the policy read from
deletion_rules.csv. Answers are cached by signature, so resources that look alike share one answer.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Mapping

from deletion_audit.cache import JsonCache
from deletion_audit.config import PROMPTS_DIR
from deletion_audit.identity import EMAIL_TOKEN, HASH_TOKEN, USER_ID_TOKEN
from deletion_audit.llm import Backend, LLMError
from deletion_audit.observations import RESOURCE_ID, Observation, resource_prefix
from deletion_audit.policy import DATA_FLOW, Rule
from deletion_audit.state import DIRECT_IDENTIFIERS, REFERENCES
from deletion_audit.usage import UsageRecorder

OTHER = "OTHER"
BATCH_SIZE = 25
VOTES = 3  # each batch is answered three times; the majority category wins (borderline signatures wobble)
MAX_VALUES = 25
MAX_VALUE_LENGTH = 80
TECHNICAL_KEYS = {"level", "severity", "logger", "instance", "pod", "region", "trace_id", "requestId", "attempt",
                  "duration_ms", "took_ms", "latency_ms", "wait_ms", "retry_in_ms", "shard", "node", "seq", "service",
                  "function", "resource_id", "time", "observed_at", "recorded_at", "captured_at", "updated_at",
                  # how the audit searched, not what the record is
                  "lookup_key", "subject_key", "subject_ref", "match_key", "correlation_key", "query"}
PERSON_FIELDS = {"customer", "owner", "account", "subject", "selector", "assigned", "assigned_agent", "user"}
OBJECT_NAMES = {"index_name", "connector_name", "file_name", "event_name", "collection_name"}
LOOKS_IDENTIFYING = re.compile(r"\d[\d\s().+-]{5,}\d|^\d{4}-\d{2}-\d{2}|tr-|rb-")


class CategoryError(RuntimeError):
    """A resource's category could not be determined."""


def explicit_category(observations: Iterable[Observation], rules: Mapping[str, Rule]) -> str | None:
    labels = Counter(o.label for o in observations if o.label in rules or o.label == DATA_FLOW)
    return labels.most_common(1)[0][0] if labels else None


def _descriptive(value: object) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_VALUE_LENGTH:
        return False
    if EMAIL_TOKEN.search(value) or HASH_TOKEN.search(value) or USER_ID_TOKEN.search(value):
        return False
    return not RESOURCE_ID.match(value) and not LOOKS_IDENTIFYING.search(value) and value.lower() != "null"


def _identity_field(key: str) -> bool:
    """Identity fields' values (names, contacts, references) are never sent, whatever they look like."""
    lowered = key.lower().replace(" ", "_")
    return (lowered in DIRECT_IDENTIFIERS | REFERENCES | PERSON_FIELDS
            or lowered.endswith(("_email", "_phone")) or lowered.endswith("_name") and lowered not in OBJECT_NAMES)


def signature(observations: Iterable[Observation], system_id: str | None = None,
              resource_id: str | None = None) -> dict:
    """What a resource looks like in the evidence, without any personal data."""
    observations = list(observations)
    systems = Counter(o.system_id for o in observations if o.system_id) or Counter([system_id] if system_id else [])
    fields, values, events = set(), set(), set()
    for o in observations:
        own = [e for e in o.fields.get("_events", []) if o.resource_id in e.values()]
        # a log trace also holds infrastructure lines (retries, pools): keep only the lines about this record
        sources = own if own else [o.fields]
        for source in sources:
            for key, value in source.items():
                if key.startswith("_") or key in TECHNICAL_KEYS:
                    continue
                fields.add(key)
                nested = value.items() if isinstance(value, dict) else [(key, value)]
                values.update(v for k, v in nested if not _identity_field(k) and _descriptive(v))
        events.update(e.get("event") for e in own if e.get("event"))
    return {
        "system": systems.most_common(1)[0][0] if systems else None,
        "resource_kind": resource_prefix(resource_id) if resource_id else None,
        "labels": sorted({o.label for o in observations if o.label}),
        "events": sorted(e for e in events if "cache" not in e),
        "fields": sorted(fields),
        "values": sorted(values)[:MAX_VALUES],
    }


def load_prompt() -> str:
    return (PROMPTS_DIR / "category.md").read_text(encoding="utf-8")


class CategoryClassifier:
    def __init__(self, backend: Backend, cache: JsonCache, model: str, rules: Mapping[str, Rule],
                 prompt: str | None = None, usage: UsageRecorder | None = None) -> None:
        self.backend = backend
        self.cache = cache
        self.model = model
        self.rules = rules
        self.prompt = load_prompt() if prompt is None else prompt
        self.categories = sorted(rules) + [DATA_FLOW, OTHER]
        self.policy = [{"data_category": r.category, "condition": r.condition, "required_action": r.action}
                       for r in rules.values()]
        material = self.prompt + json.dumps(self.policy, sort_keys=True) + self.model
        self.version = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
        self.usage = usage
        self.cache_hits = 0

    def _key(self, sig: dict) -> str:
        return hashlib.sha256(f"{self.version}\n{json.dumps(sig, sort_keys=True)}".encode("utf-8")).hexdigest()

    def classify(self, resources: Mapping[str, list[Observation]],
                 systems: Mapping[str, str | None] | None = None) -> dict[str, tuple[str, str]]:
        """{key: (category, source)} where source is "label" or "llm". `systems` supplies the system for
        resources known only from activity (no observations)."""
        systems = systems or {}
        result, pending = {}, {}
        for rid, observations in sorted(resources.items()):
            label = explicit_category(observations, self.rules)
            if label:
                result[rid] = (label, "label")
                continue
            sig = signature(observations, systems.get(rid), rid.rsplit("/", 1)[-1])
            cached = self.cache.get(self._key(sig))
            if cached:
                self.cache_hits += 1
                result[rid] = (cached["category"], "llm")
            else:
                pending.setdefault(self._key(sig), (sig, []))[1].append(rid)
        if pending and not self.backend.is_available():
            raise CategoryError(f"{len(pending)} record signature(s) are not in the category cache and the Claude "
                                "Code CLI is unavailable")
        items = list(pending.items())
        for start in range(0, len(items), BATCH_SIZE):
            for key, category in self._ask(items[start:start + BATCH_SIZE]).items():
                for rid in pending[key][1]:
                    result[rid] = (category, "llm")
            self.cache.save()
        return result

    def _schema(self) -> dict:
        item = {"type": "object", "additionalProperties": False, "required": ["id", "category", "reason"],
                "properties": {"id": {"type": "string"}, "category": {"type": "string", "enum": self.categories},
                               "reason": {"type": "string"}}}
        return {"type": "object", "additionalProperties": False, "required": ["results"],
                "properties": {"results": {"type": "array", "items": item}}}

    def _ask(self, batch: list[tuple[str, tuple[dict, list[str]]]]) -> dict[str, str]:
        """Majority of VOTES independent answers per signature; the votes are kept in the cache."""
        ballots = [self._ask_once(batch) for _ in range(VOTES)]
        decided = {}
        for key, (sig, _) in batch:
            votes = Counter(b[key][0] for b in ballots if key in b)
            category = votes.most_common(1)[0][0]
            reason = next(b[key][1] for b in ballots if b.get(key, ("",))[0] == category)
            decided[key] = category
            self.cache.put(key, {"category": category, "reason": reason, "votes": dict(votes), "signature": sig,
                                 "model": self.model,
                                 "classified_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        return decided

    def _ask_once(self, batch: list[tuple[str, tuple[dict, list[str]]]]) -> dict[str, tuple[str, str]]:
        """One answer per signature: {key: (category, reason)}; missing answers are re-asked in halves."""
        ids = {f"s{i}": key for i, (key, _) in enumerate(batch, start=1)}
        records = [{"id": i, "signature": batch_item[1][0]} for i, batch_item in zip(ids, batch)]
        user_input = json.dumps({"policy": self.policy, "records": records}, ensure_ascii=False)
        try:
            data, usage = self.backend.complete_json(self.prompt, user_input, self._schema(), self.model)
        except LLMError as error:
            raise CategoryError(f"category classification failed: {error}") from error
        if self.usage is not None:
            self.usage.record("category", usage, len(batch))
        answers = {}
        for item in data.get("results", []) if isinstance(data, dict) else []:
            key = ids.get(item.get("id")) if isinstance(item, dict) else None
            if key and item.get("category") in self.categories and key not in answers:
                answers[key] = (item["category"], str(item.get("reason", "")))
        missing = [k for k in ids.values() if k not in answers]
        if missing and len(batch) == 1:
            raise CategoryError(f"no valid category for signature {json.dumps(batch[0][1][0])[:200]}")
        if missing:
            middle = max(1, len(missing) // 2)
            retry = [item for item in batch if item[0] in missing]
            for part in (retry[:middle], retry[middle:]):
                if part:
                    answers.update(self._ask_once(part))
        return answers
