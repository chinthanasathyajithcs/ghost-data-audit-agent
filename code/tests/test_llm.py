"""Tests for the Claude Code CLI backend (Stage 2 design §4.6). The CLI is never actually run."""

import json
import subprocess

import pytest

from deletion_audit.llm import ClaudeCliBackend, LLMError

SCHEMA = {"type": "object"}


def cli_reply(structured=None, is_error=False, result=""):
    return json.dumps({
        "is_error": is_error,
        "result": result,
        "structured_output": structured,
        "total_cost_usd": 0.0004,
        "modelUsage": {
            "claude-haiku-5-5": {"inputTokens": 2, "outputTokens": 205, "cacheReadInputTokens": 10,
                                 "cacheCreationInputTokens": 1528, "costUSD": 0.0004},
        },
    })


class FakeRun:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        code, stdout = outcome
        return subprocess.CompletedProcess(command, code, stdout=stdout, stderr="boom" if code else "")


def backend(outcomes, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    return ClaudeCliBackend(run=FakeRun(outcomes), sleep=sleeps.append, which=lambda name: "/usr/bin/claude")


def test_returns_structured_output_and_usage():
    cli = backend([(0, cli_reply({"results": []}))])

    data, usage = cli.complete_json("system", "input", SCHEMA, "claude-haiku-5-5")

    assert data == {"results": []}
    assert usage.model == "claude-haiku-5-5"
    assert (usage.input_tokens, usage.output_tokens) == (2, 205)
    assert (usage.cache_creation_input_tokens, usage.cache_read_input_tokens) == (1528, 10)
    assert usage.cost_usd == pytest.approx(0.0004)


def test_command_uses_minimal_flags_schema_and_stdin():
    cli = backend([(0, cli_reply({"results": []}))])

    cli.complete_json("system prompt", "user input", SCHEMA, "claude-haiku-5-5")

    command, kwargs = cli.run.commands[0]
    assert command[:2] == ["claude", "-p"]
    for flag in ("--json-schema", "--no-session-persistence", "--strict-mcp-config", "--system-prompt"):
        assert flag in command
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--model") + 1] == "claude-haiku-5-5"
    assert kwargs["input"] == "user input"


def test_error_reply_is_retried_then_raised():
    sleeps = []
    cli = backend([(0, cli_reply(is_error=True, result="rate limited"))] * 4, sleeps)

    with pytest.raises(LLMError, match="rate limited"):
        cli.complete_json("s", "i", SCHEMA, "m")
    assert len(sleeps) == 3


def test_transient_failure_then_success():
    cli = backend([(1, ""), subprocess.TimeoutExpired("claude", 1), (0, cli_reply({"ok": True}))])

    data, _ = cli.complete_json("s", "i", SCHEMA, "m")

    assert data == {"ok": True}


def test_unparsable_output_is_an_error():
    cli = backend([(0, "not json")] * 4)

    with pytest.raises(LLMError):
        cli.complete_json("s", "i", SCHEMA, "m")


def test_availability_depends_on_the_executable_being_found():
    assert ClaudeCliBackend(which=lambda name: None).is_available() is False
    assert ClaudeCliBackend(which=lambda name: "/usr/bin/claude").is_available() is True
