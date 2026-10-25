"""A small JSON key-value cache for LLM answers, saved atomically so a crash never corrupts it."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class CacheError(RuntimeError):
    """The cache file exists but cannot be read."""


class JsonCache:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._entries: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise CacheError(f"{self.path} is not valid JSON ({error}); fix or delete it") from error
        if not isinstance(data, dict):
            raise CacheError(f"{self.path} must contain a JSON object")
        return data

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> dict | None:
        return self._entries.get(key)

    def put(self, key: str, value: dict) -> None:
        self._entries[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._entries, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                file.write(text)
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
