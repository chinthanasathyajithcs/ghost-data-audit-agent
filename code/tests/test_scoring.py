"""Tests for the evaluation metrics (Stage 1 design §4.2 and §4.7)."""

from conftest import REPO_ROOT

from deletion_audit.contract import read_answers
from scoring import Answer, diff_case, score

SAMPLE_OUTPUT = REPO_ROOT / "dataset" / "sample_output.csv"


def step(no, phase, system, resource, operation, state, evidence=""):
    return {
        "step_no": no,
        "phase": phase,
        "system_id": system,
        "resource_id": resource,
        "operation": operation,
        "state": state,
        "evidence_id": evidence,
    }


def incomplete_case():
    return Answer(
        "INCOMPLETE",
        (
            step(1, "FINDING", "search_service", "search_1", "REPORT_REMAINING_RECORD", "PRESENT", "evidence_01"),
            step(2, "REMEDIATION", "search_service", "search_1", "DELETE_RECORD", "ABSENT"),
            step(3, "VERIFICATION", "account_service", "account_1", "VERIFY_RECORD_ABSENT", "ABSENT"),
            step(4, "VERIFICATION", "search_service", "search_1", "VERIFY_RECORD_ABSENT", "ABSENT"),
        ),
    )


def renumber(steps):
    return tuple({**s, "step_no": i} for i, s in enumerate(steps, start=1))


def test_perfect_prediction_scores_100_percent_on_every_metric():
    expected = read_answers(SAMPLE_OUTPUT)

    result = score(expected, expected)

    assert result.status_accuracy == 1.0
    assert result.step_precision == 1.0
    assert result.step_recall == 1.0
    assert result.step_f1 == 1.0
    assert result.field_accuracy == 1.0
    assert result.exact_sequence_accuracy == 1.0
    assert result.partial_sequence_accuracy == 1.0
    assert result.fully_correct == len(expected)


def test_dropping_one_step_lowers_recall_only():
    expected = {"c1": incomplete_case()}
    predicted = {"c1": Answer("INCOMPLETE", renumber(incomplete_case().steps[:3]))}

    result = score(expected, predicted)

    assert result.step_recall == 3 / 4
    assert result.step_precision == 1.0
    assert result.exact_sequence_accuracy == 0.0
    assert result.fully_correct == 0


def test_adding_an_invented_step_lowers_precision_only():
    extra = step(5, "VERIFICATION", "support_service", "support_9", "VERIFY_RECORD_ABSENT", "ABSENT")
    expected = {"c1": incomplete_case()}
    predicted = {"c1": Answer("INCOMPLETE", incomplete_case().steps + (extra,))}

    result = score(expected, predicted)

    assert result.step_recall == 1.0
    assert result.step_precision == 4 / 5
    assert result.field_accuracy == (4 * 7) / (5 * 7)


def test_swapping_two_steps_keeps_step_scores_but_breaks_sequence():
    original = incomplete_case().steps
    swapped = renumber((original[0], original[1], original[3], original[2]))
    expected = {"c1": incomplete_case()}
    predicted = {"c1": Answer("INCOMPLETE", swapped)}

    result = score(expected, predicted)

    assert result.step_f1 == 1.0
    assert result.exact_sequence_accuracy == 0.0
    assert 0.0 < result.partial_sequence_accuracy < 1.0


def test_wrong_evidence_id_costs_one_step_match_and_one_field():
    steps = list(incomplete_case().steps)
    steps[0] = {**steps[0], "evidence_id": "evidence_99"}
    expected = {"c1": incomplete_case()}
    predicted = {"c1": Answer("INCOMPLETE", tuple(steps))}

    result = score(expected, predicted)

    assert result.step_recall == 3 / 4
    assert result.field_accuracy == (4 * 7 - 1) / (4 * 7)
    assert result.per_field_accuracy["evidence_id"] == 3 / 4
    assert result.per_field_accuracy["operation"] == 1.0


def test_wrong_status_only_changes_status_metrics():
    expected = {"c1": incomplete_case()}
    predicted = {"c1": Answer("COMPLETE", incomplete_case().steps)}

    result = score(expected, predicted)

    assert result.status_accuracy == 0.0
    assert result.confusion[("INCOMPLETE", "COMPLETE")] == 1
    assert result.step_f1 == 1.0
    assert result.fully_correct == 0


def test_not_applicable_with_empty_steps_is_an_exact_sequence_match():
    expected = {"c1": Answer("NOT_APPLICABLE", ())}
    predicted = {"c1": Answer("NOT_APPLICABLE", ())}

    result = score(expected, predicted)

    assert result.exact_sequence_accuracy == 1.0
    assert result.partial_sequence_accuracy == 1.0
    assert result.steps_expected == 0
    assert result.fully_correct == 1


def test_missing_prediction_counts_as_wrong_status_and_all_steps_missing():
    expected = {"c1": incomplete_case()}

    result = score(expected, {})

    assert result.status_accuracy == 0.0
    assert result.step_recall == 0.0
    assert result.missing_cases == ("c1",)


def test_breakdown_by_operation_shows_which_operations_are_missed():
    expected = {"c1": incomplete_case()}
    predicted = {"c1": Answer("INCOMPLETE", renumber(incomplete_case().steps[:3]))}

    result = score(expected, predicted)

    verify_absent = result.by_operation["VERIFY_RECORD_ABSENT"]
    assert verify_absent.expected == 2
    assert verify_absent.matched == 1
    assert result.by_operation["DELETE_RECORD"].matched == 1


def test_case_diff_reports_missing_extra_and_wrong_fields():
    steps = list(incomplete_case().steps)
    steps[1] = {**steps[1], "operation": "REDACT_RECORD", "state": "REDACTED"}
    del steps[2]
    steps.append(step(4, "VERIFICATION", "cache_service", "cache_1", "VERIFY_RECORD_ABSENT", "ABSENT"))

    diff = diff_case(incomplete_case(), Answer("INCOMPLETE", renumber(steps)))

    assert diff.status_ok
    assert [s["resource_id"] for s in diff.missing] == ["account_1"]
    assert [s["resource_id"] for s in diff.extra] == ["cache_1"]
    wrong = {w.field: (w.expected, w.predicted) for w in diff.wrong_fields}
    assert wrong["operation"] == ("DELETE_RECORD", "REDACT_RECORD")
    assert wrong["state"] == ("ABSENT", "REDACTED")
