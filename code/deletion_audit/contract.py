"""Output contract shared by the agent and the evaluation harness (AGENTS.md §6.3–6.4, PRD §5)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"

OUTPUT_COLUMNS = ("case_id", "deletion_status", "steps_json")
STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
STEP_FIELDS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")
PHASES = ("FINDING", "REMEDIATION", "VERIFICATION")

# operation -> (phase, state). Insertion order is the contract's operation order within a phase.
OPERATIONS: Mapping[str, tuple[str, str]] = {
    "REPORT_REMAINING_RECORD": ("FINDING", "PRESENT"),
    "REPORT_EXPOSED_PII": ("FINDING", "PRESENT"),
    "REPORT_ACTIVE_DATA_FLOW": ("FINDING", "ACTIVE"),
    "REPORT_RESTORE_RISK": ("FINDING", "ACTIVE"),
    "DISABLE_DATA_FLOW": ("REMEDIATION", "DISABLED"),
    "BLOCK_RESTORE": ("REMEDIATION", "BLOCKED"),
    "DELETE_RECORD": ("REMEDIATION", "ABSENT"),
    "REDACT_RECORD": ("REMEDIATION", "REDACTED"),
    "ANONYMIZE_RECORD": ("REMEDIATION", "ANONYMIZED"),
    "VERIFY_RECORD_ABSENT": ("VERIFICATION", "ABSENT"),
    "VERIFY_RECORD_PRESENT": ("VERIFICATION", "PRESENT"),
    "VERIFY_RECORD_REDACTED": ("VERIFICATION", "REDACTED"),
    "VERIFY_RECORD_ANONYMIZED": ("VERIFICATION", "ANONYMIZED"),
    "VERIFY_DATA_FLOW_DISABLED": ("VERIFICATION", "DISABLED"),
    "VERIFY_RESTORE_BLOCKED": ("VERIFICATION", "BLOCKED"),
}
_OPERATION_ORDER = {operation: index for index, operation in enumerate(OPERATIONS)}


@dataclass(frozen=True)
class Answer:
    """One case's decision: a status and its ordered steps."""

    status: str
    steps: tuple[dict, ...]


def parse_time(value: str) -> datetime:
    """Parse the dataset's ISO-8601 timestamps (with a trailing Z) into aware datetimes."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def step_sort_key(step: Mapping) -> tuple:
    """Strict step order (PRD D10): phase, operation order, system_id, resource_id."""
    return (
        PHASES.index(step["phase"]),
        _OPERATION_ORDER[step["operation"]],
        step["system_id"],
        step["resource_id"],
    )


def serialize_steps(steps: Iterable[Mapping]) -> str:
    """Deterministic JSON for steps_json: sorted keys, compact separators, UTF-8 kept."""
    return json.dumps(list(steps), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_csv_header(path: Path) -> tuple[str, ...]:
    with open(path, newline="", encoding="utf-8") as handle:
        return tuple(next(csv.reader(handle), ()))


def read_answers(path: Path) -> dict[str, Answer]:
    """Read an output-format CSV into {case_id: Answer}. Raises ValueError on unparsable JSON."""
    answers = {}
    for row in read_csv(path):
        try:
            steps = json.loads(row["steps_json"])
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}: {row['case_id']}: steps_json is not valid JSON ({error})") from error
        answers[row["case_id"]] = Answer(row["deletion_status"], tuple(steps))
    return answers


def write_answers(path: Path, answers: Mapping[str, Answer]) -> None:
    """Write answers sorted by case_id with the exact output header."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(OUTPUT_COLUMNS)
        for case_id in sorted(answers):
            answer = answers[case_id]
            writer.writerow((case_id, answer.status, serialize_steps(answer.steps)))
