"""Token and cost tracking for every real LLM call (feeds usage_report.md)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from deletion_audit.llm import CallUsage

TOKEN_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


class UsageRecorder:
    def __init__(self, log_path: Path | None = None) -> None:
        self.log_path = log_path
        self.records: list[dict] = []

    def record(self, task: str, usage: CallUsage, items: int) -> None:
        entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "task": task,
                 "items": items, **asdict(usage)}
        self.records.append(entry)
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")

    def summary(self, by: str = "model") -> dict[str, dict]:
        """Totals per model (or per task): calls, token counts, cost and wall time."""
        totals: dict[str, dict] = defaultdict(lambda: dict.fromkeys(("calls", *TOKEN_FIELDS, "cost_usd", "duration_s"), 0))
        for entry in self.records:
            model = totals[entry[by].split(":")[0]]
            model["calls"] += 1
            for field in (*TOKEN_FIELDS, "cost_usd", "duration_s"):
                model[field] += entry[field]
        return dict(totals)

    def format_summary(self, cache_hits: int) -> str:
        summary = self.summary()
        if not summary:
            return f"LLM usage: 0 calls ({cache_hits} answers from cache)"
        lines = [f"LLM usage ({cache_hits} answers from cache):"]
        for model, t in sorted(summary.items()):
            total_input = t["input_tokens"] + t["cache_creation_input_tokens"] + t["cache_read_input_tokens"]
            lines.append(f"  {model}: {t['calls']} calls, {total_input} input tokens "
                         f"({t['cache_read_input_tokens']} cache reads), {t['output_tokens']} output tokens, "
                         f"${t['cost_usd']:.4f}, {t['duration_s']:.0f}s")
        return "\n".join(lines)
