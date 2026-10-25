"""Tests for the evidence readers (Stage 4 design §4.1–4.3), on small fixtures copying each real shape."""

import json

import pytest

from deletion_audit.readers import read_handover, read_json, read_log, read_sql

CAPTURED = "2026-09-20T12:00:00Z"


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


GENERIC_SQL = """-- Ghost Data Still Exists: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-06-13T11:00:00Z
-- Database topology: read_replica
BEGIN TRANSACTION;
CREATE TABLE customer_data_primary (resource_id TEXT PRIMARY KEY, origin_system TEXT NOT NULL,
  collection_name TEXT NOT NULL, record_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE customer_data_read_replica (resource_id TEXT PRIMARY KEY, origin_system TEXT NOT NULL,
  collection_name TEXT NOT NULL, record_json TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO "customer_data_primary" VALUES('search_6781','search_service','customer_search_documents',
  '{"resource_id":"search_6781","document":{"email":"y.park50@yahoo.com","customer_reference":"user_259"}}','2026-06-13T11:00:00Z');
INSERT INTO "customer_data_read_replica" VALUES('account_3150','account_service','customer_profiles',
  '{"resource_id":"account_3150","customer_reference":"user_259","email":"y.park50@yahoo.com"}','2026-06-13T11:00:00Z');
COMMIT;
"""

INVENTORY_SQL = """BEGIN TRANSACTION;
CREATE TABLE snapshot_scope (origin_system TEXT, captured_at TEXT);
INSERT INTO snapshot_scope VALUES('account_service','2026-02-13T07:43:27Z');
CREATE TABLE customer_profiles (resource_id TEXT, customer_reference TEXT, email TEXT, account_status TEXT, updated_at TEXT);
INSERT INTO customer_profiles VALUES('account_3626',NULL,'daniel.m47291@outlook.com','DELETION_PENDING','2026-02-13T07:43:27Z');
CREATE TABLE customer_exports (resource_id TEXT, owner_email TEXT, updated_at TEXT);
COMMIT;
"""


def test_sql_generic_pair_gives_one_observation_per_row_with_json_fields(tmp_path):
    observations, coverage = read_sql(write(tmp_path, "a.sql", GENERIC_SQL), "evidence_24", CAPTURED)

    by_id = {o.resource_id: o for o in observations}
    assert set(by_id) == {"search_6781", "account_3150"}
    account = by_id["account_3150"]
    assert (account.system_id, account.location, account.label) == ("account_service", "customer_data_read_replica",
                                                                     "customer_profiles")
    assert account.fields["email"] == "y.park50@yahoo.com"
    assert account.observed_at == "2026-06-13T11:00:00Z"
    assert by_id["search_6781"].fields["document"]["customer_reference"] == "user_259"
    assert {c.location for c in coverage} == {"customer_data_primary", "customer_data_read_replica"}
    assert all(c.captured_at == "2026-06-13T11:00:00Z" for c in coverage)


def test_sql_inventory_records_scope_and_empty_tables_as_coverage(tmp_path):
    observations, coverage = read_sql(write(tmp_path, "b.sql", INVENTORY_SQL), "evidence_63", CAPTURED)

    assert [o.resource_id for o in observations] == ["account_3626"]
    assert observations[0].system_id is None  # resolved later from the learned prefix map
    assert observations[0].label == "customer_profiles"
    assert {c.location for c in coverage} >= {"customer_profiles", "customer_exports"}
    assert any(c.system_id == "account_service" for c in coverage)


BUNDLE = {
    "exported_at": "2026-09-17T12:00:00Z",
    "snapshots": [
        {"captured_at": "2026-09-15T12:00:00Z", "data_store": "identity_service",
         "collection": "deleted_customer_references",
         "records": [{"resource_id": "tombstone_440", "subject_reference": "user_541", "email": None}]},
        {"captured_at": "2026-09-15T12:00:00Z", "data_store": "account_service", "collection": "customer_profiles",
         "records": []},
    ],
}

SERVICE_EXPORT = {
    "exported_at": "2026-01-29T12:00:00Z",
    "service_exports": {
        "search_service": {"index_queries": [
            {"observed_at": "2026-01-29T11:40:30Z", "query": "jonas-lund@proton.me",
             "hits": {"total": 1, "documents": [{"resource_id": "search_1091", "email": "jonas-lund@proton.me"}]}}]},
        "backup_service": {"restore_entries": [
            {"observed_at": "2026-01-29T11:39:19Z", "resource_id": "backup_3382", "restore_allowed": True}]},
    },
}

LEDGER = {"exported_at": "2026-08-12T12:00:00Z", "records": [
    {"recorded_at": "2026-08-12T09:00:00Z", "system": "account_service", "resource_id": "account_1084",
     "record_type": "USER_PROFILE", "result": "NOT_FOUND", "subject_reference": "mateo.alvarez@gmail.com"}]}


def test_json_bundle_uses_each_snapshots_own_time_and_records_empty_snapshots(tmp_path):
    observations, coverage = read_json(write(tmp_path, "c.json", json.dumps(BUNDLE)), "evidence_51", CAPTURED)

    assert [(o.resource_id, o.system_id, o.label, o.observed_at) for o in observations] == [
        ("tombstone_440", "identity_service", "deleted_customer_references", "2026-09-15T12:00:00Z")]
    assert ("account_service", "customer_profiles", "2026-09-15T12:00:00Z") in {
        (c.system_id, c.label, c.captured_at) for c in coverage}


def test_json_service_export_takes_system_and_collection_from_keys_and_keeps_parent_context(tmp_path):
    observations, _ = read_json(write(tmp_path, "d.json", json.dumps(SERVICE_EXPORT)), "evidence_62", CAPTURED)

    by_id = {o.resource_id: o for o in observations}
    assert (by_id["search_1091"].system_id, by_id["search_1091"].label) == ("search_service", "index_queries")
    assert by_id["search_1091"].fields["_parent"]["hits"]["total"] == 1
    assert by_id["search_1091"].observed_at == "2026-01-29T11:40:30Z"
    assert by_id["backup_3382"].fields["restore_allowed"] is True


def test_json_ledger_record_keeps_system_label_and_time(tmp_path):
    observations, _ = read_json(write(tmp_path, "e.json", json.dumps(LEDGER)), "evidence_13", CAPTURED)

    (o,) = observations
    assert (o.system_id, o.label, o.observed_at) == ("account_service", "USER_PROFILE", "2026-08-12T09:00:00Z")
    assert o.fields["result"] == "NOT_FOUND"


LOGFMT = """2026-09-15T08:51:43Z level=DEBUG service=log_router instance=collector-3 event=export_started
2026-09-15T09:30:01Z level=DEBUG service=account_service trace_id=tr-1 event=profile_lookup_started lookup_key=k.appiah88@gmail.com
2026-09-15T09:30:02Z level=INFO service=account_service trace_id=tr-1 resource_id=account_3960 event=profile_lookup_completed rows=0 http_status=404
2026-09-15T09:31:00Z level=WARN service=support_platform trace_id=tr-2 resource_id=support_9553 event=message_pii_scan matched_value="e.varga90@yahoo.com"
"""
JSON_LINES = '2026-09-10T08:56:20Z {"severity":"DEBUG","service":"account_service","trace_id":"tr-9","resource_id":"account_6633","event":"profile_lookup_completed","rows":"1"}\n'
SYSLOG = ('2026-08-22T10:51:11Z <15>1 node-1 account_service tr-4973247 - - level=DEBUG event="profile_lookup_started" lookup_key="nana.b9576@outlook.com"\n'
          '2026-08-22T10:51:17Z <15>1 node-1 account_service tr-4973247 - - level=DEBUG resource_id="account_1785" event="profile_lookup_completed" rows="1"\n')
BRACKET = '2026-07-28T05:51:21Z [INFO] [account_service] [tr-6074163] profile_lookup_completed: resource_id="account_7947" rows="0" http_status="404"\n'
PIPE = '2026-07-03T07:51:32Z | DEBUG | security_service | tr-5156005 | audit_record_read_completed | resource_id="audit_record_4413" rows="1"\n'
CLOUD = ('2026-06-08T06:52:09Z requestId=tr-1108860 level=INFO function=search_service '
         'message="instance=\\"search-3\\" resource_id=\\"search_021\\" event=\\"index_query_completed\\" result=\\"hit\\""\n')
LOOKUP = '2026-08-31T07:00:00Z INFO service=search_index_service event=record_lookup seq=1 system="account_service" resource_id="account_8473" record_type="USER_PROFILE" result="FOUND" subject_reference="marek.zielinski@gmail.com"\n'


def test_logfmt_trace_join_puts_the_subject_line_into_the_resources_observation(tmp_path):
    observations, coverage = read_log(write(tmp_path, "f.log", LOGFMT), "evidence_06", CAPTURED)

    by_id = {o.resource_id: o for o in observations}
    assert set(by_id) == {"account_3960", "support_9553"}
    account = by_id["account_3960"]
    assert account.location == "trace tr-1"
    assert account.observed_at == "2026-09-15T09:30:02Z"
    assert "k.appiah88@gmail.com" in account.text
    assert account.fields["http_status"] == "404"
    assert coverage == []


@pytest.mark.parametrize("text, resource, service", [
    (JSON_LINES, "account_6633", "account_service"),
    (SYSLOG, "account_1785", "account_service"),
    (BRACKET, "account_7947", "account_service"),
    (PIPE, "audit_record_4413", "security_service"),
    (CLOUD, "search_021", "search_service"),
])
def test_every_log_style_yields_resource_service_and_fields(tmp_path, text, resource, service):
    observations, _ = read_log(write(tmp_path, "g.log", text), "evidence_x", CAPTURED)

    (o,) = observations
    assert (o.resource_id, o.fields["_service"]) == (resource, service)
    assert o.fields.get("event") or o.fields.get("_event")


def test_syslog_trace_join_links_lookup_key_to_resource(tmp_path):
    (o,) = read_log(write(tmp_path, "h.log", SYSLOG), "evidence_11", CAPTURED)[0]

    assert "nana.b9576@outlook.com" in o.text


def test_record_lookup_line_takes_its_explicit_system(tmp_path):
    (o,) = read_log(write(tmp_path, "i.log", LOOKUP), "evidence_08", CAPTURED)[0]

    assert (o.system_id, o.label, o.fields["result"]) == ("account_service", "USER_PROFILE", "FOUND")


HANDOVER = """CUSTOMER PLATFORM - SHIFT HANDOVER
Snapshot: 2026-10-01T12:00:00Z

Account and downstream checks completed during the shift:
- 2026-09-29T10:00:00Z | search_service | search_052 | SEARCH_INDEX_ENTRY | FOUND | novak.tomasz@icloud.com
- 2026-09-29T10:05:00Z | security_service | audit_record_9394 | SECURITY_AUDIT_LOG | FOUND | user_32
"""


def test_handover_lines_become_observations_with_label_and_state(tmp_path):
    observations, _ = read_handover(write(tmp_path, "j.txt", HANDOVER), "evidence_03", CAPTURED)

    assert [(o.system_id, o.resource_id, o.label, o.fields["state"]) for o in observations] == [
        ("search_service", "search_052", "SEARCH_INDEX_ENTRY", "FOUND"),
        ("security_service", "audit_record_9394", "SECURITY_AUDIT_LOG", "FOUND")]
    assert observations[1].observed_at == "2026-09-29T10:05:00Z"


class FakeExtractor:
    def __init__(self, records):
        self.records = records

    def extract_file(self, path):
        return self.records


def test_document_records_become_observations_at_the_capture_time(tmp_path):
    from deletion_audit.readers import document_reader

    path = write(tmp_path, "backup_restore_console_20260429.png", "png")
    reader = document_reader(FakeExtractor(({"resource_id": "backup_9287", "fields": {"Account": "areed1433@gmail.com"}},)))

    observations, coverage = reader(path, "evidence_32", "2026-04-29T09:00:00Z")

    (o,) = observations
    assert (o.resource_id, o.observed_at, o.location, o.label) == (
        "backup_9287", "2026-04-29T09:00:00Z", "backup_restore_console_20260429.png", "backup_restore_console")
    assert "areed1433@gmail.com" in o.text
    assert coverage == []
