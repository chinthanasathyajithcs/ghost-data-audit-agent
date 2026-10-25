"""Tests for the evidence store and case-file linking (Stage 4 design §4.4–4.7)."""

from datetime import datetime

from deletion_audit.evidence import EvidenceStore
from deletion_audit.identity import IdentityIndex
from deletion_audit.linking import build_case_file
from deletion_audit.observations import Coverage, Observation, fields_text


def at(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


IDENTITY = IdentityIndex(
    [
        {"user_id": "user_1", "name": "Ann", "email": "ann@example.com", "phone": "+1 555 0101",
         "email_hash": "a" * 64, "updated_at": "2026-01-01T00:00:00Z"},
        {"user_id": "user_2", "name": "Bob", "email": "bob@example.com", "phone": "+1 555 0102",
         "email_hash": "b" * 64, "updated_at": "2026-01-01T00:00:00Z"},
    ],
    [],
)
AUDIT_AT = at("2026-09-20T00:00:00Z")
REQUESTED_AT = at("2026-08-01T00:00:00Z")


def obs(resource, fields, system=None, observed="2026-09-10T00:00:00Z", evidence="evidence_1", label=None,
        captured="2026-09-15T00:00:00Z", service=None):
    if service:
        fields = {**fields, "_service": service}
    return Observation(evidence, captured, observed, system, resource, "table", label, fields, fields_text(fields))


def store(observations, coverage=(), activity=()):
    return EvidenceStore.build(list(observations), list(coverage), IDENTITY, list(activity))


def activity(aid, time, event, target, resource, result="SUCCESS", source="deletion_worker", details=""):
    return {"activity_id": aid, "event_time": time, "event_type": event, "source_system": source,
            "target_system": target, "resource_id": resource, "reported_result": result, "details": details}


def test_system_ids_are_learned_from_records_that_state_them():
    s = store([
        obs("account_10", {"email": "x@y.z"}, system="account_service"),
        obs("account_11", {"email": "q@y.z"}, system="account_service"),
        obs("account_12", {}, system=None),
        obs("support_7", {}, service="support_replica"),
        obs("support_8", {}, system="support_platform"),
    ])

    assert s.resource("account_12")[0].system_id == "account_service"
    assert s.resource("support_7")[0].system_id == "support_platform"


def test_coverage_without_a_system_takes_it_from_its_label():
    s = store([obs("account_10", {}, system="account_service", label="customer_profiles")],
              [Coverage("evidence_9", "2026-09-15T00:00:00Z", "customer_profiles", "customer_profiles", None)])

    assert s.coverage[0].system_id == "account_service"


def test_owners_are_found_for_each_observation():
    s = store([obs("search_1", {"email": "ANN@example.com"}, system="search_service")])

    assert s.owners(s.resource("search_1")[0]) == {"user_1"}


def subject(email="ann@example.com"):
    return IDENTITY.resolve(email, AUDIT_AT)


def test_case_file_links_the_subjects_records_and_rejects_others():
    s = store([
        obs("search_1", {"email": "ann@example.com"}, system="search_service"),
        obs("search_2", {"email": "bob@example.com"}, system="search_service"),
        obs("support_3", {"customer_reference": "user_1"}, system="support_platform"),
    ])

    case = build_case_file("c1", subject(), REQUESTED_AT, AUDIT_AT, at("2026-09-01T00:00:00Z"), "COMPLETE", s)

    assert {r.resource_id for r in case.resources} == {"search_1", "support_3"}
    assert case.rejected == 1


def test_link_carries_over_to_a_later_cleaned_copy_but_not_from_facts_after_audit_at():
    s = store([
        obs("analytics_5", {"email": "ann@example.com"}, system="analytics_platform", observed="2026-08-01T00:00:00Z"),
        obs("analytics_5", {"email": None}, system="analytics_platform", observed="2026-09-12T00:00:00Z"),
        obs("analytics_6", {"email": "ann@example.com"}, system="analytics_platform", observed="2026-09-25T00:00:00Z"),
    ])

    case = build_case_file("c1", subject(), REQUESTED_AT, AUDIT_AT, at("2026-09-01T00:00:00Z"), "COMPLETE", s)

    linked = {r.resource_id: r for r in case.resources}
    assert set(linked) == {"analytics_5"}
    assert len(linked["analytics_5"].observations) == 2
    assert linked["analytics_5"].methods == {"identifier", "propagated"}


def test_activity_links_unowned_resources_in_the_request_window_only():
    reported = at("2026-09-01T12:00:00Z")
    s = store(
        [obs("analytics_9", {"email": None}, system="analytics_platform"),
         obs("search_4", {"email": "bob@example.com"}, system="search_service")],
        activity=[
            activity("a1", "2026-09-01T12:30:00Z", "ANONYMIZE_RECORD", "analytics_platform", "analytics_9"),
            activity("a2", "2026-09-01T12:40:00Z", "DELETE_RECORD", "search_service", "search_4"),
            activity("a3", "2026-09-01T20:00:00Z", "DELETE_RECORD", "search_service", "search_99"),
        ],
    )

    case = build_case_file("c1", subject(), REQUESTED_AT, AUDIT_AT, reported, "COMPLETE", s, activity_mode="all")

    linked = {r.resource_id: r for r in case.resources}
    assert set(linked) == {"analytics_9"}
    assert linked["analytics_9"].methods == {"activity"}


def test_competing_account_deletes_are_settled_by_the_reported_status():
    reported = at("2026-09-01T12:00:00Z")
    rows = [
        activity("a1", "2026-09-01T11:00:00Z", "DELETE_RECORD", "account_service", "account_1", result="PARTIAL",
                 details="Deletion worker completed some internal work. Target resource: account_1."),
        activity("a2", "2026-09-01T11:10:00Z", "DELETE_RECORD", "account_service", "account_2", result="SUCCESS",
                 details="Deletion worker submitted primary profile account_2 to account_service."),
    ]
    s = store([], activity=rows)

    complete = build_case_file("c1", subject(), REQUESTED_AT, AUDIT_AT, reported, "COMPLETE", s)
    partial = build_case_file("c2", subject(), REQUESTED_AT, AUDIT_AT, reported, "PARTIALLY_COMPLETE", s)

    assert {r.resource_id for r in complete.resources} == {"account_2"}
    assert {r.resource_id for r in partial.resources} == {"account_1"}


def test_activity_adds_no_second_account_and_only_accounts_by_default():
    reported = at("2026-09-01T12:00:00Z")
    s = store(
        [obs("account_7", {"email": "ann@example.com"}, system="account_service")],
        activity=[activity("a1", "2026-09-01T11:00:00Z", "DELETE_RECORD", "account_service", "account_8"),
                  activity("a2", "2026-09-01T12:30:00Z", "ANONYMIZE_RECORD", "analytics_platform", "analytics_9")],
    )

    case = build_case_file("c1", subject(), REQUESTED_AT, AUDIT_AT, reported, "COMPLETE", s)

    assert {r.resource_id for r in case.resources} == {"account_7"}


def test_resources_last_seen_before_the_request_are_out_of_scope():
    s = store([
        obs("account_6", {"lookup_key": "ann@example.com"}, system="account_service", observed="2026-03-10T00:00:00Z"),
        obs("search_6", {"email": "ann@example.com"}, system="search_service", observed="2026-03-10T00:00:00Z"),
        obs("search_6", {"email": "ann@example.com"}, system="search_service", observed="2026-08-15T00:00:00Z"),
    ])

    case = build_case_file("c1", subject(), REQUESTED_AT, AUDIT_AT, at("2026-09-01T00:00:00Z"), "COMPLETE", s)

    assert {r.resource_id for r in case.resources} == {"search_6"}


def test_catalog_link_is_accepted_unless_the_evidence_names_someone_else():
    s = store(
        [obs("export_7", {"Owner": "ann@example.com"}, system="export_service"),
         obs("marketing_1", {"title": "Soo-jin Park", "email": "sj.park@naver.com"}, system="marketing_platform"),
         obs("tombstone_3", {"subject_reference": None}, system="identity_service")],
        activity=[
            activity("c1", "2026-09-05T00:00:00Z", "LINK_RESOURCE_IDENTITY", "marketing_platform", "marketing_1",
                     source="data_catalog", details="Data catalog linked marketing_1 to ann@example.com and user_1."),
            activity("c2", "2026-09-05T00:00:00Z", "LINK_RESOURCE_IDENTITY", "identity_service", "tombstone_3",
                     source="data_catalog", details="Data catalog linked tombstone_3 to ann@example.com and user_1."),
        ],
    )

    case = build_case_file("c1", subject(), at("2026-05-01T00:00:00Z"), AUDIT_AT, at("2026-06-01T00:00:00Z"), "COMPLETE", s)

    linked = {r.resource_id: r for r in case.resources}
    assert set(linked) == {"export_7", "tombstone_3"}
    assert linked["tombstone_3"].methods == {"catalog"}
    assert case.conflicts == ("marketing_1",)


def test_activity_supplies_the_system_only_when_no_evidence_states_it():
    s = store(
        [obs("marketing_1", {}), obs("account_10", {}, system="account_service")],
        activity=[activity("a1", "2026-09-01T00:00:00Z", "LINK_RESOURCE_IDENTITY", "marketing_platform", "marketing_1",
                           source="data_catalog"),
                  activity("a2", "2026-09-01T00:00:00Z", "SYNC_RECORD", "account_failover_replica", "account_10",
                           source="account_service")],
    )

    assert s.resource("marketing_1")[0].system_id == "marketing_platform"
    assert s.resource("account_10")[0].system_id == "account_service"


def test_catalog_alias_turns_documents_showing_the_display_reference_into_observations():
    statement = Observation("evidence_18", "2026-09-10T00:00:00Z", "2026-09-10T00:00:00Z", None, "user_1",
                            "report.pdf", "account_history_report",
                            {"statement": "NST-2026-0718-1842", "email": "ann@example.com"},
                            fields_text({"statement": "NST-2026-0718-1842", "email": "ann@example.com"}))
    s = store(
        [statement],
        activity=[activity("c1", "2026-09-10T00:00:00Z", "LINK_RESOURCE_IDENTITY", "export_service", "export_42",
                           source="data_catalog",
                           details="Data catalog linked export_42 (NST-2026-0718-1842) to ann@example.com and user_1."),
                  activity("c2", "2026-09-10T00:00:00Z", "LINK_RESOURCE_IDENTITY", "identity_service", "tombstone_3",
                           source="data_catalog",
                           details="Data catalog linked tombstone_3 (user_1) to ann@example.com and user_1.")],
    )

    (alias_obs,) = s.resource("export_42")
    assert (alias_obs.evidence_id, alias_obs.system_id) == ("evidence_18", "export_service")
    assert s.resource("tombstone_3") == []  # user IDs are never aliases
    assert s.resource("user_1") == []  # records without a resource ID are not resources

    case = build_case_file("c1", subject(), REQUESTED_AT, AUDIT_AT, at("2026-09-01T00:00:00Z"), "COMPLETE", s)
    assert "export_42" in {r.resource_id for r in case.resources}
