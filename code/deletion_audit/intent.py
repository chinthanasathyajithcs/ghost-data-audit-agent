"""Stage 2 — does the request authorise deletion? LLM classification, batched and cached."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from deletion_audit.cache import JsonCache
from deletion_audit.config import INTENT_BATCH_SIZE, INTENT_MODEL, PROMPTS_DIR
from deletion_audit.llm import Backend, LLMError
from deletion_audit.usage import UsageRecorder

INTENT_LABELS = ("DELETION", "ACCESS", "EXPORT", "CORRECTION", "MARKETING_OPT_OUT", "ACCOUNT_SUPPORT", "OTHER")

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "intent": {"type": "string", "enum": list(INTENT_LABELS)},
                    "authorizes_deletion": {"type": "boolean"},
                    "language": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "intent", "authorizes_deletion", "language", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


class IntentError(RuntimeError):
    """Intent could not be determined for some request text."""


@dataclass(frozen=True)
class IntentResult:
    authorizes_deletion: bool
    intent: str
    language: str
    reason: str


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_prompt() -> str:
    return (PROMPTS_DIR / "intent.md").read_text(encoding="utf-8")


def prompt_version(prompt: str) -> str:
    """Changes whenever the prompt or the output schema changes, so stale answers are not reused."""
    material = prompt + json.dumps(RESULT_SCHEMA, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


class IntentClassifier:
    def __init__(
        self,
        backend: Backend,
        cache: JsonCache,
        model: str = INTENT_MODEL,
        batch_size: int = INTENT_BATCH_SIZE,
        prompt: str | None = None,
        usage: UsageRecorder | None = None,
    ) -> None:
        self.backend = backend
        self.cache = cache
        self.model = model
        self.batch_size = batch_size
        self.prompt = load_prompt() if prompt is None else prompt
        self.version = prompt_version(self.prompt)
        self.usage = usage
        self.cache_hits = 0

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.version}\n{self.model}\n{text}".encode("utf-8")).hexdigest()

    def classify_all(self, texts: Iterable[str], refresh: bool = False) -> dict[str, IntentResult]:
        """Classify every text; returns {original text: IntentResult}."""
        originals = list(texts)
        unique = sorted({normalise(t) for t in originals})
        known: dict[str, IntentResult] = {}
        if not refresh:
            for text in unique:
                entry = self.cache.get(self._key(text))
                if entry is not None:
                    known[text] = IntentResult(**entry["result"])
            self.cache_hits = len(known)

        misses = [t for t in unique if t not in known]
        if misses and not self.backend.is_available():
            raise IntentError(
                f"Claude Code CLI unavailable and {len(misses)} request text(s) are not cached. "
                "Install and log in to Claude Code (`claude`), or run with a complete intent cache."
            )
        for start in range(0, len(misses), self.batch_size):
            batch = misses[start:start + self.batch_size]
            for text, result in self._classify_batch(batch).items():
                known[text] = result
                self._remember(text, result)
            self.cache.save()
        return {t: known[normalise(t)] for t in originals}

    def _remember(self, text: str, result: IntentResult) -> None:
        self.cache.put(self._key(text), {
            "text": text,
            "model": self.model,
            "prompt_version": self.version,
            "classified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "result": asdict(result),
        })

    def _classify_batch(self, texts: Sequence[str]) -> dict[str, IntentResult]:
        """One call; texts without a valid result are re-asked in halves, then one by one."""
        ids = {f"r{i}": text for i, text in enumerate(texts, start=1)}
        user_input = json.dumps({"requests": [{"id": i, "text": t} for i, t in ids.items()]}, ensure_ascii=False)
        try:
            data, usage = self.backend.complete_json(self.prompt, user_input, RESULT_SCHEMA, self.model)
        except LLMError as error:
            raise IntentError(f"intent classification failed: {error}") from error
        if self.usage is not None:
            self.usage.record("intent", usage, len(texts))

        results = _valid_results(data, ids)
        missing = [t for t in texts if t not in results]
        if missing and len(texts) == 1:
            raise IntentError(f"no valid intent result for request text: {texts[0]!r}")
        if missing:
            middle = max(1, len(missing) // 2)
            for part in (missing[:middle], missing[middle:]):
                if part:
                    results.update(self._classify_batch(part))
        return results


def _valid_results(data: dict, ids: dict[str, str]) -> dict[str, IntentResult]:
    """Keep results whose id is known, unique, and whose fields are well formed and consistent."""
    raw = data.get("results") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return {}
    counts: dict[str, int] = {}
    for item in raw:
        if isinstance(item, dict):
            counts[item.get("id")] = counts.get(item.get("id"), 0) + 1
    valid = {}
    for item in raw:
        if not isinstance(item, dict) or item.get("id") not in ids or counts[item["id"]] != 1:
            continue
        intent, authorizes = item.get("intent"), item.get("authorizes_deletion")
        if intent not in INTENT_LABELS or not isinstance(authorizes, bool) or authorizes != (intent == "DELETION"):
            continue
        valid[ids[item["id"]]] = IntentResult(authorizes, intent, str(item.get("language", "")),
                                              str(item.get("reason", "")))
    return valid
