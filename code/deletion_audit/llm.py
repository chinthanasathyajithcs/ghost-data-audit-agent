"""LLM backend: Claude Code CLI in headless mode (PRD D6), authenticated by the user's Claude plan."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

CLI_TIMEOUT_S = 180
RETRY_DELAYS_S = (2, 8, 30)


class LLMError(RuntimeError):
    """The model could not produce a usable reply."""


@dataclass(frozen=True)
class CallUsage:
    model: str
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_s: float


class Backend(Protocol):
    def is_available(self) -> bool: ...

    def complete_json(
        self, system_prompt: str, user_input: str, schema: dict, model: str, read_dirs: Sequence[Path] = ()
    ) -> tuple[dict, CallUsage]: ...


class ClaudeCliBackend:
    """Runs `claude -p` with minimal context (no MCP, settings or session) and a JSON schema.

    No tools are allowed, except the read-only `Read` tool limited to `read_dirs` when a file
    (screenshot or PDF) must be looked at.
    """

    def __init__(
        self,
        executable: str = "claude",
        timeout_s: int = CLI_TIMEOUT_S,
        retry_delays_s: Sequence[float] = RETRY_DELAYS_S,
        run: Callable = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.executable = executable
        self.timeout_s = timeout_s
        self.retry_delays_s = tuple(retry_delays_s)
        self.run = run
        self.sleep = sleep
        self.which = which

    def is_available(self) -> bool:
        return self.which(self.executable) is not None

    def command(self, system_prompt: str, schema: dict, model: str, read_dirs: Sequence[Path | str] = ()) -> list[str]:
        tools = ["--tools", "Read", "--allowed-tools", "Read"] if read_dirs else ["--tools", ""]
        directories = [arg for d in read_dirs for arg in ("--add-dir", str(d))]
        return [
            self.executable, "-p",
            "--model", model,
            "--output-format", "json",
            "--json-schema", json.dumps(schema),
            "--system-prompt", system_prompt,
            *tools,
            *directories,
            "--strict-mcp-config",
            "--setting-sources", "",
            "--disable-slash-commands",
            "--no-session-persistence",
        ]

    def complete_json(
        self, system_prompt: str, user_input: str, schema: dict, model: str, read_dirs: Sequence[Path] = ()
    ) -> tuple[dict, CallUsage]:
        command = self.command(system_prompt, schema, model, read_dirs)
        errors = []
        for attempt in range(len(self.retry_delays_s) + 1):
            if attempt:
                self.sleep(self.retry_delays_s[attempt - 1])
            started = time.monotonic()
            try:
                completed = self.run(command, input=user_input, capture_output=True, text=True,
                                     timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                errors.append(f"timed out after {self.timeout_s}s")
                continue
            if completed.returncode != 0:
                errors.append(f"exit {completed.returncode}: {(completed.stderr or completed.stdout).strip()[:300]}")
                continue
            try:
                return parse_cli_output(completed.stdout, time.monotonic() - started)
            except LLMError as error:
                errors.append(str(error))
        raise LLMError(f"Claude Code CLI failed after {len(errors)} attempts: {' | '.join(errors)}")


def parse_cli_output(stdout: str, duration_s: float) -> tuple[dict, CallUsage]:
    """Read the CLI's `--output-format json` envelope: structured reply plus per-model usage."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise LLMError(f"CLI output is not JSON ({error})") from error
    if envelope.get("is_error"):
        raise LLMError(f"model error: {str(envelope.get('result', ''))[:300]}")
    data = envelope.get("structured_output")
    if not isinstance(data, dict):
        raise LLMError("reply has no structured_output object")

    per_model = envelope.get("modelUsage") or {}
    model = ",".join(sorted(per_model)) or "unknown"
    totals = {
        key: sum(int(m.get(key, 0)) for m in per_model.values())
        for key in ("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens", "outputTokens")
    }
    cost = sum(float(m.get("costUSD", 0.0)) for m in per_model.values())
    usage = CallUsage(
        model=model,
        input_tokens=totals["inputTokens"],
        cache_creation_input_tokens=totals["cacheCreationInputTokens"],
        cache_read_input_tokens=totals["cacheReadInputTokens"],
        output_tokens=totals["outputTokens"],
        cost_usd=cost,
        duration_s=round(duration_s, 2),
    )
    return data, usage
