"""Tests for the output format validator (Stage 1 design §4.3)."""

import json

import pytest
from conftest import REPO_ROOT

from deletion_audit.contract import OUTPUT_COLUMNS, read_csv
from deletion_audit.validate import load_citation_times, validate_rows

DATASET = REPO_ROOT / "dataset"


@pytest.fixture(scope="module")
def citation_times():
    return load_citation_times(DATASET)


@pytest.fixture(scope="module")
def sample_requests():
    return read_csv(DATASET / "sample_deletion_requests.csv")


@pytest.fixture()
def sample_rows():
    return read_csv(DATASET / "sample_output.csv")


def errors_for(rows, requests, citation_times, header=OUTPUT_COLUMNS):
    return validate_rows(header, rows, requests, citation_times)


def edit_steps(row, edit):
    steps = json.loads(row["steps_json"])
    return {**row, "steps_json": json.dumps(edit(steps))}


def test_sample_output_passes_every_check(sample_rows, sample_requests, citation_times):
    assert errors_for(sample_rows, sample_requests, citation_times) == []


def test_wrong_header_is_reported(sample_rows, sample_requests, citation_times):
    errors = errors_for(sample_rows, sample_requests, citation_times, header=("case_id", "status", "steps_json"))
    assert any("header" in e for e in errors)


def test_missing_and_duplicate_rows_are_reported(sample_rows, sample_requests, citation_times):
    rows = sample_rows[1:] + [sample_rows[5]]
    errors = errors_for(rows, sample_requests, citation_times)
    assert any("missing" in e and "case_01" in e for e in errors)
    assert any("duplicate" in e and "case_06" in e for e in errors)


def test_unsorted_rows_are_reported(sample_rows, sample_requests, citation_times):
    rows = [sample_rows[1], sample_rows[0]] + sample_rows[2:]
    assert any("sorted" in e for e in errors_for(rows, sample_requests, citation_times))


def test_bad_json_is_reported(sample_rows, sample_requests, citation_times):
    rows = [{**sample_rows[0], "steps_json": "[{not json"}] + sample_rows[1:]
    assert any("case_01" in e and "JSON" in e for e in errors_for(rows, sample_requests, citation_times))


def test_unknown_operation_and_wrong_state_are_reported(sample_rows, sample_requests, citation_times):
    rows = list(sample_rows)
    rows[4] = edit_steps(rows[4], lambda s: [{**s[0], "operation": "PURGE_RECORD"}] + s[1:])
    rows[5] = edit_steps(rows[5], lambda s: [{**s[0], "state": "ABSENT"}] + s[1:])
    errors = errors_for(rows, sample_requests, citation_times)
    assert any("case_05" in e and "operation" in e for e in errors)
    assert any("case_06" in e and "state" in e for e in errors)


def test_extra_step_field_is_reported(sample_rows, sample_requests, citation_times):
    rows = [edit_steps(sample_rows[0], lambda s: [{**s[0], "note": "x"}])] + sample_rows[1:]
    assert any("case_01" in e and "fields" in e for e in errors_for(rows, sample_requests, citation_times))


def test_bad_step_numbering_is_reported(sample_rows, sample_requests, citation_times):
    rows = list(sample_rows)
    rows[4] = edit_steps(rows[4], lambda s: [{**x, "step_no": x["step_no"] + 1} for x in s])
    assert any("case_05" in e and "step_no" in e for e in errors_for(rows, sample_requests, citation_times))


def test_steps_out_of_strict_order_are_reported(sample_rows, sample_requests, citation_times):
    def swap_last_two(steps):
        swapped = steps[:-2] + [steps[-1], steps[-2]]
        return [{**x, "step_no": i} for i, x in enumerate(swapped, start=1)]

    rows = list(sample_rows)
    rows[10] = edit_steps(rows[10], swap_last_two)
    assert any("case_11" in e and "order" in e for e in errors_for(rows, sample_requests, citation_times))


def test_not_applicable_with_steps_is_reported(sample_rows, sample_requests, citation_times):
    rows = [{**sample_rows[0], "deletion_status": "NOT_APPLICABLE"}] + sample_rows[1:]
    assert any("case_01" in e and "NOT_APPLICABLE" in e for e in errors_for(rows, sample_requests, citation_times))


def test_complete_case_with_uncited_verification_is_reported(sample_rows, sample_requests, citation_times):
    rows = [edit_steps(sample_rows[0], lambda s: [{**s[0], "evidence_id": ""}])] + sample_rows[1:]
    assert any("case_01" in e and "evidence" in e for e in errors_for(rows, sample_requests, citation_times))


def test_incomplete_remediation_with_evidence_is_reported(sample_rows, sample_requests, citation_times):
    def cite_remediation(steps):
        return [{**x, "evidence_id": "evidence_03"} if x["phase"] == "REMEDIATION" else x for x in steps]

    rows = list(sample_rows)
    rows[10] = edit_steps(rows[10], cite_remediation)
    assert any("case_11" in e and "evidence" in e for e in errors_for(rows, sample_requests, citation_times))


def test_unknown_citation_is_reported(sample_rows, sample_requests, citation_times):
    rows = [edit_steps(sample_rows[0], lambda s: [{**s[0], "evidence_id": "evidence_999"}])] + sample_rows[1:]
    assert any("case_01" in e and "evidence_999" in e for e in errors_for(rows, sample_requests, citation_times))


def test_citation_captured_after_audit_at_is_reported(sample_rows, sample_requests, citation_times):
    # evidence_02 was captured on 2026-09-17, after case_01's audit_at (2026-09-03).
    rows = [edit_steps(sample_rows[0], lambda s: [{**s[0], "evidence_id": "evidence_02"}])] + sample_rows[1:]
    assert any("case_01" in e and "after audit_at" in e for e in errors_for(rows, sample_requests, citation_times))
