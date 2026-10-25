"""Tests for state reconstruction at audit_at (Stage 5 design §4)."""

from datetime import datetime

import pytest

from deletion_audit.linking import LinkedResource
from deletion_audit.observations import Coverage, Observation, fields_text
from deletion_audit.state import read_signals, resolve_state

AUDIT_AT = datetime.fromisoformat("2026-09-15T12:00:00+00:00")


def obs(fields, observed="2026-09-15T10:00:00Z", captured="2026-09-15T12:00:00Z", evidence="evidence_1",
        location="table", label=None, resource="res_1"):
    return Observation(evidence, captured, observed, "sys", resource, location, label, fields, fields_text(fields))


@pytest.mark.parametrize("fields, label, expected", [
    ({"state": "FOUND"}, "SEARCH_INDEX_ENTRY", {"existence": "present"}),
    ({"state": "NOT_FOUND"}, "USER_PROFILE", {"existence": "absent"}),
    ({"state": "IDENTIFIABLE"}, "SUPPORT_MESSAGE", {"existence": "present", "identity": "identifiable"}),
    ({"state": "ANONYMIZED"}, "ANALYTICS_PROFILE", {"existence": "present", "identity": "anonymized"}),
    ({"state": "ACTIVE"}, "DATA_FLOW", {"flow": "active", "existence": "present"}),
    ({"state": "ACTIVE"}, "BACKUP_ARCHIVE", {"restore": "open", "existence": "present"}),
    ({"result": "NOT_FOUND"}, "USER_PROFILE", {"existence": "absent"}),
    ({"rows": "0", "http_status": "404"}, None, {"existence": "absent"}),
    ({"status_code": 404, "profile": None}, None, {"existence": "absent"}),
    ({"rows": "1", "subject_reference": "user_43"}, None, {"existence": "present"}),
    ({"result": "hit", "total_hits": "1"}, None, {"existence": "present"}),
    ({"download_available": True, "owner_email": "a@b.c"}, None, {"existence": "present", "identity": "identifiable"}),
    ({"enabled": "true", "scheduler_registered": "true"}, None, {"flow": "active", "existence": "present"}),
    ({"enabled": False}, None, {"flow": "disabled", "existence": "present"}),
    ({"restore_allowed": 1}, None, {"restore": "open", "existence": "present"}),
    ({"restore_allowed": "false"}, None, {"restore": "blocked", "existence": "present"}),
    ({"eligible": "true", "deletion_block": "false"}, None, {"restore": "open", "existence": "present"}),
    ({"decision": "deny"}, None, {"restore": "blocked", "existence": "present"}),
    ({"direct_identifiers": "0"}, None, {"identity": "anonymized", "existence": "present"}),
    ({"event": "message_pii_scan", "matched_value": "a@b.c"}, None, {"identity": "identifiable", "existence": "present"}),
    ({"message_text": "[REDACTED]"}, None, {"identity": "redacted", "existence": "present"}),
])
def test_signals(fields, label, expected):
    o = obs(fields, location="line 1", label=label)
    assert read_signals(o) == expected


def test_identity_from_identifier_fields_in_a_snapshot_row():
    identifiable = obs({"email": "a@b.c", "customer_reference": "user_1"})
    redacted = obs({"email": None, "phone": "null", "customer_reference": "user_1"})
    anonymized = obs({"user_id": None, "email": None, "phone": None, "email_hash": None})
    message = obs({"customer_reference": None, "message_text": "Send the update to a@b.c please"})

    assert read_signals(identifiable) == {"existence": "present", "identity": "identifiable"}
    assert read_signals(redacted) == {"existence": "present", "identity": "redacted"}
    assert read_signals(anonymized) == {"existence": "present", "identity": "anonymized"}
    assert read_signals(message)["identity"] == "identifiable"


def test_nested_document_fields_count():
    o = obs({"index_name": "x", "document": {"display_name": "Ann", "email": "a@b.c"}})
    assert read_signals(o)["identity"] == "identifiable"


def resource(*observations):
    return LinkedResource("sys", "res_1", frozenset({"identifier"}), tuple(observations))


def test_latest_observation_up_to_audit_wins_and_is_cited():
    state = resolve_state(resource(
        obs({"rows": "1"}, observed="2026-09-01T00:00:00Z", evidence="evidence_1", captured="2026-09-01T00:00:00Z"),
        obs({"rows": "0"}, observed="2026-09-14T00:00:00Z", evidence="evidence_2", captured="2026-09-14T00:00:00Z"),
    ), [], AUDIT_AT, {})

    assert (state.existence.value, state.existence.proof) == ("absent", "evidence_2")


def test_any_copy_present_means_present():
    state = resolve_state(resource(
        obs({"email": "a@b.c"}, location="customer_profiles_failover_replica", evidence="evidence_54"),
    ), [Coverage("evidence_54", "2026-09-15T12:00:00Z", "customer_profiles_primary", "customer_profiles", "sys")],
        AUDIT_AT, {"res_1": {"evidence_54"}})

    assert state.existence.value == "present"


def test_silence_in_a_covering_snapshot_proves_absence_when_nothing_else_speaks():
    coverage = [Coverage("evidence_7", "2026-09-10T00:00:00Z", "t", "customer_profiles", "sys"),
                Coverage("evidence_8", "2026-09-14T00:00:00Z", "t", "customer_profiles", "sys"),
                Coverage("evidence_9", "2026-09-20T00:00:00Z", "t", "customer_profiles", "sys")]

    state = resolve_state(resource(), coverage, AUDIT_AT, {})

    assert (state.existence.value, state.existence.proof, state.existence.basis) == ("absent", "evidence_8", "coverage")


def test_fact_from_a_file_captured_after_audit_is_used_but_not_cited():
    state = resolve_state(resource(
        obs({"rows": "0"}, observed="2026-09-15T09:00:00Z", captured="2026-09-18T00:00:00Z", evidence="evidence_6"),
    ), [], AUDIT_AT, {})

    assert (state.existence.value, state.existence.proof) == ("absent", None)


def test_no_evidence_and_no_coverage_leaves_existence_unknown():
    assert resolve_state(resource(), [], AUDIT_AT, {}).existence is None


def test_a_backup_or_connector_row_exists_whatever_its_restore_or_flow_state():
    backup = obs({"customer_email": "a@b.c", "restore_allowed": 1}, label="backup_restore_entries")
    connector = obs({"customer_email": "a@b.c", "enabled": 0}, label="connector_subscriptions")

    assert read_signals(backup)["existence"] == "present"
    assert read_signals(connector)["existence"] == "present"


def test_an_absent_record_has_no_identity():
    state = resolve_state(resource(
        obs({"email": "a@b.c"}, observed="2026-09-01T00:00:00Z"),
        obs({"status_code": 404}, observed="2026-09-14T00:00:00Z", location="line 3"),
    ), [], AUDIT_AT, {})

    assert state.existence.value == "absent"
    assert state.identity is None


def test_absence_decided_by_an_uncitable_file_borrows_proof_from_an_earlier_covering_snapshot():
    state = resolve_state(
        resource(obs({"rows": "0"}, observed="2026-09-15T09:00:00Z", captured="2026-09-18T00:00:00Z",
                     evidence="evidence_6", location="trace tr-1")),
        [Coverage("evidence_8", "2026-09-14T00:00:00Z", "t", "customer_profiles", "sys")], AUDIT_AT, {})

    assert (state.existence.value, state.existence.proof) == ("absent", "evidence_8")


def test_any_content_flow_or_restore_signal_means_the_record_exists():
    scan = obs({"event": "message_pii_scan", "matched_value": "a@b.c"}, location="trace tr-1")
    read = obs({"event": "analytics_profile_read_completed", "email": "a@b.c"}, location="trace tr-2")
    restore = obs({"eligible": "true", "deletion_block": "false"}, location="trace tr-3")

    for o in (scan, read, restore):
        assert read_signals(o)["existence"] == "present"


def test_a_cache_miss_in_the_same_trace_is_not_a_missing_record():
    events = [
        {"time": "t1", "event": "connector_heartbeat", "resource_id": "data_flow_1", "enabled": "true",
         "scheduler_registered": "true"},
        {"time": "t2", "event": "cache_lookup", "result": "miss", "cache": "integration_service_lookup_v2"},
    ]
    merged = {k: v for e in events for k, v in e.items()}
    o = obs({**merged, "_events": events}, location="trace tr-9")

    assert read_signals(o) == {"flow": "active", "existence": "present"}


def test_screen_and_log_signals_found_in_the_eval_set():
    connector_screen = obs({"Connector": "data_flow_1", "Mode": "Continuous", "Sync mode": "Continuous sync",
                            "Status": "Healthy"}, location="connector_management_console.png")
    paused_screen = obs({"Mode": "Paused"}, location="connector_management_console.png")
    ticket_screen = obs({"Customer": "Kofi Agyeman", "Email": "k@x.com", "Order": "ORD-1"}, location="ticket.png")
    loaded = obs({"event": "retained_order_loaded", "access": "allowed"}, location="trace tr-5")

    assert read_signals(connector_screen)["flow"] == "active"
    assert read_signals(paused_screen)["flow"] == "disabled"
    assert read_signals(ticket_screen)["identity"] == "identifiable"
    assert read_signals(loaded)["existence"] == "present"


def test_configured_mode_never_overrides_the_enabled_flag():
    disabled = obs({"customer_email": "a@b.c", "mode": "continuous_sync", "enabled": False})

    assert read_signals(disabled)["flow"] == "disabled"


def test_a_later_capture_of_the_subjects_data_without_the_record_overrides_an_earlier_present():
    earlier = obs({"email": "a@b.c"}, observed="2026-08-11T10:00:00Z", captured="2026-08-11T10:00:00Z",
                  evidence="evidence_5")
    later = Coverage("evidence_87", "2026-08-17T09:42:50Z", "customer_profiles", "customer_profiles", "sys",
                     "2026-08-17T09:42:50Z")
    random_slice = Coverage("evidence_70", "2026-08-16T00:00:00Z", "customer_profiles", "customer_profiles", "sys",
                            "2026-08-16T00:00:00Z")

    about_subject = resolve_state(resource(earlier), [later], AUDIT_AT, {}, subject_files={"evidence_87"})
    unrelated = resolve_state(resource(earlier), [random_slice], AUDIT_AT, {}, subject_files={"evidence_87"})

    assert (about_subject.existence.value, about_subject.existence.proof) == ("absent", "evidence_87")
    assert unrelated.existence.value == "present"


def test_coverage_is_cited_only_when_its_file_was_captured_by_audit_at():
    inner_time_ok_file_late = Coverage("evidence_17", "2026-09-10T00:00:00Z", "t", "customer_profiles", "sys",
                                       "2026-09-20T00:00:00Z")

    state = resolve_state(resource(), [inner_time_ok_file_late], AUDIT_AT, {})

    assert state.existence is None
