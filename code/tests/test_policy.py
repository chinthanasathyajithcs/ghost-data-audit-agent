"""Tests for categories and the policy decision table (Stage 6 design §4)."""

import json
from datetime import datetime

import pytest
from conftest import REPO_ROOT

from deletion_audit.cache import JsonCache
from deletion_audit.category import CategoryClassifier, explicit_category, signature
from deletion_audit.llm import CallUsage
from deletion_audit.observations import Observation, fields_text
from deletion_audit.policy import decide, load_rules
from deletion_audit.state import Facet, ResourceState

AUDIT_AT = datetime.fromisoformat("2026-09-15T12:00:00+00:00")
RULES = load_rules(REPO_ROOT / "dataset")


def obs(fields, label=None, location="table", system="support_platform", resource="support_1"):
    return Observation("evidence_1", "2026-09-15T00:00:00Z", "2026-09-15T00:00:00Z", system, resource, location,
                       label, fields, fields_text(fields))


def test_rules_are_read_from_the_csv():
    assert RULES["SUPPORT_MESSAGE"].action == "REDACT"
    assert RULES["ACCOUNT_TOMBSTONE"].rule_id == "rule_15"
    assert len(RULES) == 15


def test_an_explicit_category_label_decides():
    assert explicit_category([obs({"state": "FOUND"}, label="SUPPORT_ATTACHMENT")], RULES) == "SUPPORT_ATTACHMENT"
    assert explicit_category([obs({"state": "ACTIVE"}, label="DATA_FLOW")], RULES) == "DATA_FLOW"
    assert explicit_category([obs({}, label="support_conversations")], RULES) is None


def test_signature_keeps_structure_and_drops_identifiers():
    sig = signature([obs({"requester_email": "ann@example.com", "phone": "+1 555 0101", "customer_reference": "user_7",
                          "message_text": "Order arrived late", "source": "legacy_contact_index",
                          "email_hash": "a" * 64, "trace_id": "tr-1"}, label="support_conversations")])

    text = json.dumps(sig)
    assert sig["system"] == "support_platform" and sig["labels"] == ["support_conversations"]
    assert {"requester_email", "message_text", "source"} <= set(sig["fields"])
    assert "legacy_contact_index" in sig["values"] and "Order arrived late" in sig["values"]
    for secret in ("ann@example.com", "555 0101", "user_7", "a" * 64, "tr-1"):
        assert secret not in text


class FakeBackend:
    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    def complete_json(self, system_prompt, user_input, schema, model, read_dirs=()):
        self.calls += 1
        items = json.loads(user_input)["records"]
        return {"results": [{"id": i["id"], "category": "SUPPORT_MESSAGE", "reason": "ticket"} for i in items]}, \
            CallUsage(model, 1, 0, 0, 5, 0.001, 1.0)


def test_classifier_uses_explicit_labels_first_and_caches_signatures(tmp_path):
    backend = FakeBackend()
    classifier = CategoryClassifier(backend, JsonCache(tmp_path / "c.json"), "m", RULES, prompt="Classify.")
    resources = {"support_1": [obs({"message_text": "hi"}, label="support_conversations")],
                 "support_2": [obs({"message_text": "hi"}, label="support_conversations", resource="support_2")],
                 "support_3": [obs({"state": "FOUND"}, label="SUPPORT_ATTACHMENT", resource="support_3")]}

    first = classifier.classify(resources)
    second = CategoryClassifier(backend, JsonCache(tmp_path / "c.json"), "m", RULES, prompt="Classify.").classify(resources)

    assert first == second == {"support_1": ("SUPPORT_MESSAGE", "llm"), "support_2": ("SUPPORT_MESSAGE", "llm"),
                               "support_3": ("SUPPORT_ATTACHMENT", "label")}
    assert backend.calls == 3  # one batch, answered three times for the majority vote


def facet(value, proof="evidence_9"):
    return Facet(value, "2026-09-15T00:00:00Z", proof, "observation")


def state(existence=None, identity=None, flow=None, restore=None):
    f = lambda v: facet(v) if v else None
    return ResourceState("sys", "res_1", f(existence), f(identity), f(flow), f(restore))


@pytest.mark.parametrize("category, st, expected", [
    ("USER_PROFILE", state("present", "identifiable"),
     ("REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT")),
    ("USER_PROFILE", state("absent"), (None, None, "VERIFY_RECORD_ABSENT")),
    ("SUPPORT_MESSAGE", state("present", "identifiable"), ("REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED")),
    ("SUPPORT_MESSAGE", state("present", "redacted"), (None, None, "VERIFY_RECORD_REDACTED")),
    ("ACCOUNT_TOMBSTONE", state("present", "identifiable"), ("REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED")),
    ("ANALYTICS_PROFILE", state("present", "identifiable"),
     ("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED")),
    ("ANALYTICS_PROFILE", state("present", "anonymized"), (None, None, "VERIFY_RECORD_ANONYMIZED")),
    ("BACKUP_ARCHIVE", state("present", "identifiable", restore="open"),
     ("REPORT_RESTORE_RISK", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED")),
    ("BACKUP_ARCHIVE", state("present", restore="blocked"), (None, None, "VERIFY_RESTORE_BLOCKED")),
    ("SECURITY_AUDIT_LOG", state("present"), (None, None, "VERIFY_RECORD_PRESENT")),
    ("DATA_FLOW", state("present", flow="active"), ("REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED")),
    ("DATA_FLOW", state("present", flow="disabled"), (None, None, "VERIFY_DATA_FLOW_DISABLED")),
])
def test_decision_table(category, st, expected):
    d = decide(st, category, RULES, AUDIT_AT, [])

    assert (d.finding, d.remediation, d.verification) == expected
    assert d.needs_review is None
    assert d.compliant == (expected[0] is None)
    if expected[0]:
        assert d.finding_evidence == "evidence_9"


@pytest.mark.parametrize("category, st, reason", [
    ("SECURITY_AUDIT_LOG", state("absent"), "retained record"),
    ("SUPPORT_MESSAGE", state("present"), "identity"),
    ("OTHER", state("present"), "category"),
])
def test_cases_outside_the_table_are_flagged_not_guessed(category, st, reason):
    d = decide(st, category, RULES, AUDIT_AT, [])

    assert d.finding is None and d.verification is None
    assert reason in d.needs_review


def test_expired_retention_fails_the_condition():
    expired = obs({"retention_until": "2026-01-01T00:00:00Z"}, system="security_service")

    d = decide(state("present"), "SECURITY_AUDIT_LOG", RULES, AUDIT_AT, [expired])

    assert d.verification is None and "condition" in d.needs_review


def test_signature_never_sends_names_or_other_identity_field_values():
    sig = signature([obs({"display_name": "Jonas Berg", "full_name": "Ann Lee", "requester_name": "Kofi Agyeman",
                          "Customer": "Priya Raman", "index_name": "customer_directory_v3"}, label="search_documents")])

    text = json.dumps(sig)
    for name in ("Jonas Berg", "Ann Lee", "Kofi Agyeman"):
        assert name not in text
    assert "customer_directory_v3" in sig["values"]


def test_log_signature_uses_only_the_lines_that_name_the_resource():
    events = [{"event": "connection_acquired", "pool": "replica"},
              {"event": "dependency_retry", "reason": "read_timeout"},
              {"event": "message_pii_scan", "resource_id": "support_1", "detector": "direct_identifier",
               "matched_value": "ann@example.com"}]
    merged = {k: v for e in events for k, v in e.items()}
    sig = signature([obs({**merged, "_events": events}, location="trace tr-1")], resource_id="support_1")

    assert sig["events"] == ["message_pii_scan"]
    assert "pool" not in sig["fields"] and "reason" not in sig["fields"]
    assert sig["resource_kind"] == "support"


class WobblyBackend(FakeBackend):
    """Answers SUPPORT_MESSAGE, then SECONDARY_IDENTIFIER, then SUPPORT_MESSAGE: one wobble out of three."""

    def complete_json(self, system_prompt, user_input, schema, model, read_dirs=()):
        self.calls += 1
        category = "SECONDARY_IDENTIFIER" if self.calls == 2 else "SUPPORT_MESSAGE"
        items = json.loads(user_input)["records"]
        return {"results": [{"id": i["id"], "category": category, "reason": "r"} for i in items]}, \
            CallUsage(model, 1, 0, 0, 5, 0.001, 1.0)


def test_categories_are_decided_by_a_majority_of_three_answers(tmp_path):
    backend = WobblyBackend()
    cache = JsonCache(tmp_path / "c.json")
    classifier = CategoryClassifier(backend, cache, "m", RULES, prompt="Classify.")

    result = classifier.classify({"support_1": [obs({"requester_email": "a@b.c"})]})

    assert result == {"support_1": ("SUPPORT_MESSAGE", "llm")}
    assert backend.calls == 3
    (entry,) = json.loads((tmp_path / "c.json").read_text()).values()
    assert entry["votes"] == {"SUPPORT_MESSAGE": 2, "SECONDARY_IDENTIFIER": 1}
