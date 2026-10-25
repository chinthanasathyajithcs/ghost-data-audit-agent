"""Stage 4A — structured records from screenshots and PDFs, extracted once and cached.

Two modes, both producing `{"resource_id", "fields"}` records:
- vision: the model reads the file itself (CLI `Read` tool, limited to the file's folder);
- text: the model structures text already taken from the file (pypdf, Docling), with no file access.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from deletion_audit.cache import JsonCache
from deletion_audit.config import PROMPTS_DIR
from deletion_audit.llm import Backend, LLMError
from deletion_audit.usage import UsageRecorder

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "resource_id": {"type": "string"},
                    "fields": {"type": "object", "additionalProperties": {"type": "string"}},
                },
                "required": ["resource_id", "fields"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["records"],
    "additionalProperties": False,
}


class ExtractionError(RuntimeError):
    """A file could not be turned into records."""


def load_prompt() -> str:
    return (PROMPTS_DIR / "extraction.md").read_text(encoding="utf-8")


class DocumentExtractor:
    def __init__(
        self,
        backend: Backend,
        cache: JsonCache,
        model: str,
        prompt: str | None = None,
        usage: UsageRecorder | None = None,
    ) -> None:
        self.backend = backend
        self.cache = cache
        self.model = model
        self.prompt = load_prompt() if prompt is None else prompt
        material = self.prompt + json.dumps(EXTRACTION_SCHEMA, sort_keys=True)
        self.version = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
        self.usage = usage
        self.cache_hits = 0

    def extract_file(self, path: Path) -> tuple[dict, ...]:
        """Vision mode: the model reads the screenshot or PDF directly."""
        path = Path(path).resolve()
        user_input = f"Read the file {path} and extract its records."
        return self._extract(path, "vision", user_input, read_dirs=(path.parent,))

    def extract_text(self, path: Path, text: str, source: str) -> tuple[dict, ...]:
        """Text mode: the model structures text already extracted from the file by `source`."""
        user_input = f"Text extracted from {Path(path).name} by {source}:\n\n{text}"
        return self._extract(Path(path), f"text:{source}", user_input, read_dirs=())

    def _key(self, path: Path, mode: str, user_input: str) -> str:
        content = hashlib.sha256(path.read_bytes()).hexdigest()
        material = f"{self.version}\n{self.model}\n{mode}\n{content}\n{hashlib.sha256(user_input.encode()).hexdigest()}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _extract(self, path: Path, mode: str, user_input: str, read_dirs: tuple) -> tuple[dict, ...]:
        key = self._key(path, mode, user_input if mode != "vision" else "")
        cached = self.cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return tuple(cached["records"])
        if not self.backend.is_available():
            raise ExtractionError(f"{path.name} is not in the extraction cache and the Claude Code CLI is unavailable")
        try:
            data, usage = self.backend.complete_json(self.prompt, user_input, EXTRACTION_SCHEMA, self.model,
                                                     read_dirs=read_dirs)
        except LLMError as error:
            raise ExtractionError(f"extraction failed for {path.name}: {error}") from error
        if self.usage is not None:
            self.usage.record(f"extraction:{mode}", usage, 1)
        records = _clean_records(data, path)
        self.cache.put(key, {"file": path.name, "mode": mode, "model": self.model, "prompt_version": self.version,
                             "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "records": list(records)})
        self.cache.save()
        return records


def _clean_records(data: dict, path: Path) -> tuple[dict, ...]:
    raw = data.get("records") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise ExtractionError(f"extraction reply for {path.name} has no records list")
    records = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("resource_id", "")).strip():
            continue
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        records.append({"resource_id": str(item["resource_id"]).strip(),
                        "fields": {str(k): str(v) for k, v in fields.items()}})
    return tuple(records)
