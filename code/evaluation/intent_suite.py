"""Intent suite: scores the Stage 2 classifier on every distinct request text (labels: intent_labels.md)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from deletion_audit.cache import JsonCache
from deletion_audit.config import INTENT_CACHE_FILE, USAGE_LOG_FILE
from deletion_audit.contract import read_csv
from deletion_audit.intent import IntentClassifier, IntentResult
from deletion_audit.llm import ClaudeCliBackend
from deletion_audit.usage import UsageRecorder

LABELS_FILE = Path(__file__).resolve().parent / "intent_labels.csv"


@dataclass(frozen=True)
class IntentScore:
    texts: int
    correct: int
    label_correct: int
    confusion: Counter
    disagreements: tuple[tuple[dict, IntentResult], ...]

    @property
    def accuracy(self) -> float:
        return self.correct / self.texts if self.texts else 1.0

    @property
    def label_accuracy(self) -> float:
        return self.label_correct / self.texts if self.texts else 1.0


def score_intents(labels: list[dict], predicted: dict[str, IntentResult]) -> IntentScore:
    confusion: Counter = Counter()
    correct = label_correct = 0
    disagreements = []
    for row in labels:
        expected = row["authorizes_deletion"] == "true"
        result = predicted[row["request_text"]]
        confusion[(expected, result.authorizes_deletion)] += 1
        correct += expected == result.authorizes_deletion
        label_correct += row["intent"] == result.intent
        if expected != result.authorizes_deletion or row["intent"] != result.intent:
            disagreements.append((row, result))
    return IntentScore(len(labels), correct, label_correct, confusion, tuple(disagreements))


def run_intent_suite(refresh: bool = False) -> tuple[IntentScore, UsageRecorder, int]:
    labels = read_csv(LABELS_FILE)
    usage = UsageRecorder(USAGE_LOG_FILE)
    classifier = IntentClassifier(ClaudeCliBackend(), JsonCache(INTENT_CACHE_FILE), usage=usage)
    predicted = classifier.classify_all([row["request_text"] for row in labels], refresh=refresh)
    return score_intents(labels, predicted), usage, classifier.cache_hits


def format_intent_score(result: IntentScore) -> str:
    def cell(expected: bool, predicted: bool) -> int:
        return result.confusion.get((expected, predicted), 0)

    lines = [
        f"== intent ({result.texts} distinct request texts) ==",
        f"  Authorises deletion  {result.correct}/{result.texts}  {result.accuracy * 100:5.1f}%",
        f"  Intent label         {result.label_correct}/{result.texts}  {result.label_accuracy * 100:5.1f}%",
        "  Confusion (rows = expected, columns = predicted)   deletion   not deletion",
        f"    deletion                                        {cell(True, True):>8}   {cell(True, False):>12}",
        f"    not deletion                                    {cell(False, True):>8}   {cell(False, False):>12}",
    ]
    for row, predicted in result.disagreements:
        lines.append(f"  - expected {row['intent']}, predicted {predicted.intent} ({predicted.reason}): "
                     f"{row['request_text'][:120]}")
    return "\n".join(lines)
