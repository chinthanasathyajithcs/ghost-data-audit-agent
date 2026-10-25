"""Tests for turning policy decisions into the case answer (Stage 7)."""

from deletion_audit.policy import Decision
from deletion_audit.steps import build_answer


def decision(system, resource, finding=None, finding_evidence=None, remediation=None, verification=None,
             verification_evidence=None, review=None):
    return Decision(system, resource, "CAT", "rule_x", finding, finding_evidence, remediation, verification,
                    verification_evidence, review)


SEARCH_REMAINING = decision("search_service", "search_052", "REPORT_REMAINING_RECORD", "evidence_03",
                            "DELETE_RECORD", "VERIFY_RECORD_ABSENT", "evidence_03")
FLOW_ACTIVE = decision("integration_service", "data_flow_9522", "REPORT_ACTIVE_DATA_FLOW", "evidence_03",
                       "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED", "evidence_03")
ACCOUNT_ABSENT = decision("account_service", "account_4248", verification="VERIFY_RECORD_ABSENT",
                          verification_evidence="evidence_03")
AUDIT_PRESENT = decision("security_service", "audit_record_9394", verification="VERIFY_RECORD_PRESENT",
                         verification_evidence="evidence_03")


def test_incomplete_case_has_cited_findings_then_uncited_remediation_and_verification_in_strict_order():
    answer = build_answer([AUDIT_PRESENT, SEARCH_REMAINING, ACCOUNT_ABSENT, FLOW_ACTIVE])

    assert answer.status == "INCOMPLETE"
    assert [(s["step_no"], s["operation"], s["resource_id"], s["evidence_id"]) for s in answer.steps] == [
        (1, "REPORT_REMAINING_RECORD", "search_052", "evidence_03"),
        (2, "REPORT_ACTIVE_DATA_FLOW", "data_flow_9522", "evidence_03"),
        (3, "DISABLE_DATA_FLOW", "data_flow_9522", ""),
        (4, "DELETE_RECORD", "search_052", ""),
        (5, "VERIFY_RECORD_ABSENT", "account_4248", ""),
        (6, "VERIFY_RECORD_ABSENT", "search_052", ""),
        (7, "VERIFY_RECORD_PRESENT", "audit_record_9394", ""),
        (8, "VERIFY_DATA_FLOW_DISABLED", "data_flow_9522", ""),
    ]
    assert {s["state"] for s in answer.steps if s["operation"] == "DELETE_RECORD"} == {"ABSENT"}


def test_complete_case_has_only_verifications_each_citing_its_proof():
    answer = build_answer([AUDIT_PRESENT, ACCOUNT_ABSENT])

    assert answer.status == "COMPLETE"
    assert [(s["phase"], s["operation"], s["evidence_id"]) for s in answer.steps] == [
        ("VERIFICATION", "VERIFY_RECORD_ABSENT", "evidence_03"),
        ("VERIFICATION", "VERIFY_RECORD_PRESENT", "evidence_03")]


def test_case_with_nothing_found_is_complete_with_no_steps():
    assert build_answer([]).status == "COMPLETE"
    assert build_answer([]).steps == ()


def test_finding_without_citable_evidence_keeps_its_remediation_and_verification_only():
    uncited = decision("account_service", "account_8819", "REPORT_REMAINING_RECORD", None, "DELETE_RECORD",
                       "VERIFY_RECORD_ABSENT", None)

    answer = build_answer([uncited, SEARCH_REMAINING])

    assert [s["operation"] for s in answer.steps if s["resource_id"] == "account_8819"] == [
        "DELETE_RECORD", "VERIFY_RECORD_ABSENT"]
    assert answer.status == "INCOMPLETE"


def test_decisions_needing_review_produce_no_steps():
    review = decision("support_platform", "support_1", review="identity unknown")

    assert build_answer([review, ACCOUNT_ABSENT]).steps == build_answer([ACCOUNT_ABSENT]).steps
