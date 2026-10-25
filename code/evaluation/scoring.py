"""Evaluation metrics (Stage 1 design §4.2).

The grader's formulas are hidden; these are our own fixed definitions:
- step match: all fields except step_no equal, one-to-one (multiset), micro precision/recall/F1;
- field accuracy: steps aligned per case by (phase, system_id, resource_id), all 7 fields compared,
  unaligned steps on either side count as 7 wrong fields;
- sequence: exact array equality, plus LCS / max(len) as partial credit.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from deletion_audit.contract import OPERATIONS, STEP_FIELDS, Answer

MATCH_FIELDS = tuple(f for f in STEP_FIELDS if f != "step_no")
ALIGN_FIELDS = ("phase", "system_id", "resource_id")
MISSING = "MISSING"

__all__ = ["Answer", "CaseDiff", "FieldDiff", "OperationCount", "Score", "diff_case", "score"]


@dataclass(frozen=True)
class OperationCount:
    expected: int = 0
    predicted: int = 0
    matched: int = 0


@dataclass(frozen=True)
class FieldDiff:
    phase: str
    system_id: str
    resource_id: str
    field: str
    expected: object
    predicted: object


@dataclass(frozen=True)
class CaseDiff:
    case_id: str
    expected_status: str
    predicted_status: str
    missing: tuple[dict, ...]
    extra: tuple[dict, ...]
    wrong_fields: tuple[FieldDiff, ...]
    exact_sequence: bool

    @property
    def status_ok(self) -> bool:
        return self.expected_status == self.predicted_status

    @property
    def fully_correct(self) -> bool:
        return self.status_ok and self.exact_sequence


@dataclass(frozen=True)
class Score:
    cases: int
    status_correct: int
    confusion: Counter
    steps_expected: int
    steps_predicted: int
    steps_matched: int
    field_correct: int
    field_total: int
    per_field_correct: Mapping[str, int]
    exact_sequences: int
    partial_sequence_sum: float
    fully_correct: int
    missing_cases: tuple[str, ...]
    by_operation: Mapping[str, OperationCount]
    by_phase: Mapping[str, OperationCount]
    case_diffs: tuple[CaseDiff, ...] = field(repr=False)

    @property
    def status_accuracy(self) -> float:
        return _ratio(self.status_correct, self.cases)

    @property
    def step_precision(self) -> float:
        if self.steps_predicted == 0:
            return 1.0 if self.steps_expected == 0 else 0.0
        return self.steps_matched / self.steps_predicted

    @property
    def step_recall(self) -> float:
        return _ratio(self.steps_matched, self.steps_expected)

    @property
    def step_f1(self) -> float:
        p, r = self.step_precision, self.step_recall
        return 0.0 if p + r == 0 else 2 * p * r / (p + r)

    @property
    def field_accuracy(self) -> float:
        return _ratio(self.field_correct, self.field_total)

    @property
    def per_field_accuracy(self) -> dict[str, float]:
        slots = self.field_total // len(STEP_FIELDS)
        return {f: _ratio(self.per_field_correct[f], slots) for f in STEP_FIELDS}

    @property
    def exact_sequence_accuracy(self) -> float:
        return _ratio(self.exact_sequences, self.cases)

    @property
    def partial_sequence_accuracy(self) -> float:
        return self.partial_sequence_sum / self.cases if self.cases else 1.0

    @property
    def failing_cases(self) -> tuple[CaseDiff, ...]:
        return tuple(d for d in self.case_diffs if not d.fully_correct)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _match_key(step: Mapping) -> tuple:
    return tuple(step.get(f) for f in MATCH_FIELDS)


def _align_key(step: Mapping) -> tuple:
    return tuple(step.get(f) for f in ALIGN_FIELDS)


def _lcs_length(a: Sequence, b: Sequence) -> int:
    previous = [0] * (len(b) + 1)
    for x in a:
        current = [0]
        for j, y in enumerate(b, start=1):
            current.append(previous[j - 1] + 1 if x == y else max(previous[j], current[j - 1]))
        previous = current
    return previous[-1]


def _align(expected: Sequence[dict], predicted: Sequence[dict]) -> tuple[list, list, list]:
    """Pair steps sharing (phase, system_id, resource_id); prefer the pair with most equal fields."""
    pool = defaultdict(list)
    for step in expected:
        pool[_align_key(step)].append(step)
    pairs, extra = [], []
    for step in predicted:
        candidates = pool.get(_align_key(step))
        if not candidates:
            extra.append(step)
            continue
        best = max(candidates, key=lambda e: sum(e.get(f) == step.get(f) for f in STEP_FIELDS))
        candidates.remove(best)
        pairs.append((best, step))
    missing = [s for group in pool.values() for s in group]
    return pairs, missing, extra


def diff_case(expected: Answer, predicted: Answer, case_id: str = "") -> CaseDiff:
    """What is missing, extra or wrong in one case's prediction."""
    pairs, missing, extra = _align(expected.steps, predicted.steps)
    wrong = tuple(
        FieldDiff(e["phase"], e["system_id"], e["resource_id"], f, e.get(f), p.get(f))
        for e, p in pairs
        for f in MATCH_FIELDS
        if e.get(f) != p.get(f)
    )
    return CaseDiff(
        case_id=case_id,
        expected_status=expected.status,
        predicted_status=predicted.status,
        missing=tuple(missing),
        extra=tuple(extra),
        wrong_fields=wrong,
        exact_sequence=list(expected.steps) == list(predicted.steps),
    )


def score(expected: Mapping[str, Answer], predicted: Mapping[str, Answer]) -> Score:
    """Score predictions against expected answers over the cases in `expected`."""
    confusion: Counter = Counter()
    per_field = Counter({f: 0 for f in STEP_FIELDS})
    op_expected, op_predicted, op_matched = Counter(), Counter(), Counter()
    totals = Counter()
    partial_sum = 0.0
    diffs, missing_cases = [], []

    for case_id in sorted(expected):
        exp = expected[case_id]
        pred = predicted.get(case_id)
        if pred is None:
            missing_cases.append(case_id)
            pred = Answer(MISSING, ())
        confusion[(exp.status, pred.status)] += 1

        matched = Counter(map(_match_key, exp.steps)) & Counter(map(_match_key, pred.steps))
        op_expected.update(s.get("operation") for s in exp.steps)
        op_predicted.update(s.get("operation") for s in pred.steps)
        for key, n in matched.items():
            op_matched[key[MATCH_FIELDS.index("operation")]] += n

        pairs, unaligned_exp, unaligned_pred = _align(exp.steps, pred.steps)
        for e, p in pairs:
            per_field.update(f for f in STEP_FIELDS if e.get(f) == p.get(f))
        slots = len(pairs) + len(unaligned_exp) + len(unaligned_pred)

        exp_keys, pred_keys = list(map(_match_key, exp.steps)), list(map(_match_key, pred.steps))
        longest = max(len(exp_keys), len(pred_keys))
        partial_sum += _lcs_length(exp_keys, pred_keys) / longest if longest else 1.0

        diff = diff_case(exp, pred, case_id)
        diffs.append(diff)
        totals.update(
            status_correct=int(diff.status_ok),
            steps_expected=len(exp.steps),
            steps_predicted=len(pred.steps),
            steps_matched=sum(matched.values()),
            field_total=slots * len(STEP_FIELDS),
            exact_sequences=int(diff.exact_sequence),
            fully_correct=int(diff.fully_correct),
        )

    return Score(
        cases=len(expected),
        status_correct=totals["status_correct"],
        confusion=confusion,
        steps_expected=totals["steps_expected"],
        steps_predicted=totals["steps_predicted"],
        steps_matched=totals["steps_matched"],
        field_correct=sum(per_field.values()),
        field_total=totals["field_total"],
        per_field_correct=dict(per_field),
        exact_sequences=totals["exact_sequences"],
        partial_sequence_sum=partial_sum,
        fully_correct=totals["fully_correct"],
        missing_cases=tuple(missing_cases),
        by_operation=_counts(op_expected, op_predicted, op_matched),
        by_phase=_phase_counts(op_expected, op_predicted, op_matched),
        case_diffs=tuple(diffs),
    )


def _counts(expected: Counter, predicted: Counter, matched: Counter) -> dict[str, OperationCount]:
    keys = sorted(set(expected) | set(predicted), key=str)
    return {k: OperationCount(expected[k], predicted[k], matched[k]) for k in keys}


def _phase_counts(expected: Counter, predicted: Counter, matched: Counter) -> dict[str, OperationCount]:
    def by_phase(counter: Counter) -> Counter:
        result = Counter()
        for operation, n in counter.items():
            result[OPERATIONS.get(operation, ("UNKNOWN",))[0]] += n
        return result

    return _counts(by_phase(expected), by_phase(predicted), by_phase(matched))
