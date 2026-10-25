"""Tests for identity resolution (Stage 3 design §4)."""

import hashlib
from datetime import datetime, timezone

import pytest
from conftest import REPO_ROOT

from deletion_audit.contract import read_csv
from deletion_audit.identity import IdentityIndex

DATASET = REPO_ROOT / "dataset"


def sha(email):
    return hashlib.sha256(email.lower().encode()).hexdigest()


def at(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


IDENTITIES = [
    {"user_id": "user_10", "name": "Nadia Petrescu", "email": "n.petrescu@yahoo.com", "phone": "+40 723 481 638",
     "email_hash": sha("n.petrescu@yahoo.com"), "updated_at": "2026-04-12T14:38:26Z"},
    {"user_id": "user_25", "name": "Soo-jin Yoon", "email": "s.yoon04@gmail.com", "phone": "+82 10 0616 2075",
     "email_hash": sha("s.yoon04@gmail.com"), "updated_at": "2026-03-29T05:51:04Z"},
    {"user_id": "user_259", "name": "Yu-na Park", "email": "y.park50@yahoo.com", "phone": "+1 (312) 555-0129",
     "email_hash": sha("y.park50@yahoo.com"), "updated_at": "2026-01-01T00:00:00Z"},
]
AUDIT = [
    {"audit_id": "audit_121", "user_id": "user_10", "event_time": "2025-12-13T08:17:43Z", "field_name": "email",
     "old_value": "nadia.ionescu@yahoo.com", "new_value": "nadia.petrescu@yahoo.com"},
    {"audit_id": "audit_122", "user_id": "user_10", "event_time": "2025-12-13T08:17:43Z", "field_name": "email_hash",
     "old_value": sha("nadia.ionescu@yahoo.com"), "new_value": sha("nadia.petrescu@yahoo.com")},
    {"audit_id": "audit_238", "user_id": "user_10", "event_time": "2026-04-12T14:38:26Z", "field_name": "email",
     "old_value": "nadia.petrescu@yahoo.com", "new_value": "n.petrescu@yahoo.com"},
    {"audit_id": "audit_239", "user_id": "user_10", "event_time": "2026-04-12T14:38:26Z", "field_name": "email_hash",
     "old_value": sha("nadia.petrescu@yahoo.com"), "new_value": sha("n.petrescu@yahoo.com")},
    {"audit_id": "audit_300", "user_id": "user_10", "event_time": "2026-01-05T10:00:00Z", "field_name": "phone",
     "old_value": "+40 700 000 111", "new_value": "+40 723 481 638"},
]
LATER = at("2026-09-18T12:25:00Z")


@pytest.fixture()
def index():
    return IdentityIndex(IDENTITIES, AUDIT)


def test_resolves_a_current_email(index):
    subject = index.resolve("n.petrescu@yahoo.com", LATER)

    assert subject.user_id == "user_10"
    assert subject.matched_via == "current"


def test_resolves_the_oldest_email_in_a_chain_and_collects_every_identifier(index):
    subject = index.resolve("nadia.ionescu@yahoo.com", LATER)

    assert subject.user_id == "user_10"
    assert subject.matched_via == "historical"
    assert subject.values("email") == {"n.petrescu@yahoo.com", "nadia.petrescu@yahoo.com", "nadia.ionescu@yahoo.com"}
    assert subject.values("email_hash") == {sha("n.petrescu@yahoo.com"), sha("nadia.petrescu@yahoo.com"),
                                            sha("nadia.ionescu@yahoo.com")}
    assert subject.values("phone") == {"+40723481638", "+40700000111"}
    assert subject.values("user_id") == {"user_10"}


def test_email_lookup_ignores_case_and_surrounding_spaces(index):
    assert index.resolve("  NADIA.Ionescu@YAHOO.com ", LATER).user_id == "user_10"


def test_unknown_email_resolves_to_no_one(index):
    assert index.resolve("karim.elmasri@gmail.com", LATER) is None


def test_identifiers_first_held_after_audit_at_are_left_out(index):
    subject = index.resolve("nadia.ionescu@yahoo.com", at("2026-02-01T00:00:00Z"))

    assert "n.petrescu@yahoo.com" not in subject.values("email")
    assert {"nadia.petrescu@yahoo.com", "nadia.ionescu@yahoo.com"} <= subject.values("email")


def test_identifier_validity_window_is_recorded(index):
    subject = index.resolve("nadia.ionescu@yahoo.com", LATER)
    middle = next(i for i in subject.identifiers if i.value == "nadia.petrescu@yahoo.com")

    assert (middle.valid_from, middle.valid_to, middle.current) == ("2025-12-13T08:17:43Z", "2026-04-12T14:38:26Z", False)


def test_finds_the_subjects_identifiers_in_free_text(index):
    subject = index.resolve("n.petrescu@yahoo.com", LATER)
    text = ("lookup_key=NADIA.IONESCU@YAHOO.COM ref=user_10 phone=+40 723 481 638 "
            f"correlation_key={sha('nadia.petrescu@yahoo.com')}")

    found = subject.find_in_text(text)

    assert {(i.kind, i.value) for i in found} == {
        ("email", "nadia.ionescu@yahoo.com"), ("user_id", "user_10"), ("phone", "+40723481638"),
        ("email_hash", sha("nadia.petrescu@yahoo.com")),
    }


def test_look_alikes_and_substrings_do_not_match(index):
    subject = index.resolve("s.yoon04@gmail.com", LATER)
    text = "s.yoon04.jr@gmail.com xs.yoon04@gmail.com subject_reference=user_259 seal=" + "a" * 64

    assert subject.find_in_text(text) == set()


def test_phone_matches_identity_format_and_compact_digits_but_not_inside_longer_numbers(index):
    subject = index.resolve("y.park50@yahoo.com", LATER)

    assert subject.find_in_text("phone: +1 (312) 555-0129.")
    assert subject.find_in_text('"phone":"+13125550129"')
    assert not subject.find_in_text("order 9+13125550129 7")


def test_owner_lookup_names_the_user_behind_any_identifier(index):
    assert index.owner_of("email", "NADIA.PETRESCU@yahoo.com") == "user_10"
    assert index.owner_of("email_hash", sha("nadia.ionescu@yahoo.com")) == "user_10"
    assert index.owner_of("user_id", "user_259") == "user_259"
    assert index.owner_of("phone", "+82 10 0616 2075") == "user_25"
    assert index.owner_of("email", "karim.elmasri@gmail.com") is None


def test_owners_in_text_lists_everyone_named(index):
    owners = index.owners_in_text("to=s.yoon04@gmail.com cc=karim.elmasri@gmail.com ref=user_259")

    assert set(owners) == {"user_25", "user_259"}


def test_owners_in_text_finds_phones_in_both_spellings(index):
    assert set(index.owners_in_text("call +82 10 0616 2075")) == {"user_25"}
    assert set(index.owners_in_text("tel=+821006162075;")) == {"user_25"}


def test_every_real_deletion_request_resolves_to_exactly_one_user():
    index = IdentityIndex.from_dataset(DATASET)
    requests = read_csv(DATASET / "deletion_requests.csv") + read_csv(DATASET / "sample_deletion_requests.csv")

    subjects = [index.resolve(r["email"], at(r["audit_at"])) for r in requests]

    assert all(s is not None for s in subjects)
    assert sum(s.matched_via == "historical" for s in subjects) == 103


def test_custom_variants_resolve_to_the_same_users_as_their_sources():
    index = IdentityIndex.from_dataset(DATASET)
    samples = {r["case_id"]: r for r in read_csv(DATASET / "sample_deletion_requests.csv")}
    custom = {r["case_id"]: r for r in read_csv(REPO_ROOT / "code/evaluation/custom_cases/requests.csv")}

    def user(row):
        return index.resolve(row["email"], at(row["audit_at"])).user_id

    assert user(custom["custom_04"]) == user(samples["case_12"])
    assert user(custom["custom_08"]) == user(samples["case_31"])
