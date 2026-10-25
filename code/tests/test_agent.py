"""Tests for the agent's case loop (code/main.py)."""

import importlib.util
import sys

from conftest import CODE_DIR

from deletion_audit.evidence import EvidenceStore
from deletion_audit.identity import IdentityIndex
from deletion_audit.intent import IntentResult

# Load code/main.py by path: code/evaluation/main.py shares the module name "main".
_spec = importlib.util.spec_from_file_location("agent_main", CODE_DIR / "main.py")
agent = importlib.util.module_from_spec(_spec)
sys.modules["agent_main"] = agent  # dataclasses need their module registered
_spec.loader.exec_module(agent)

DELETION = IntentResult(True, "DELETION", "en", "asks to delete the account")
ACCESS = IntentResult(False, "ACCESS", "en", "asks for a copy of data")


class FakeClassifier:
    def __init__(self, answers):
        self.answers = answers
        self.batches = []

    def classify_all(self, texts, refresh=False):
        texts = list(texts)
        self.batches.append(texts)
        return {t: self.answers[t] for t in texts}


IDENTITY = IdentityIndex(
    [{"user_id": "user_1", "name": "X", "email": "x@example.com", "phone": "+1 555 0100",
      "email_hash": "0" * 64, "updated_at": "2026-01-01T00:00:00Z"}],
    [{"audit_id": "audit_1", "user_id": "user_1", "event_time": "2025-06-01T00:00:00Z", "field_name": "email",
      "old_value": "old.x@example.com", "new_value": "x@example.com"}],
)
STORE = EvidenceStore.build([], [], IDENTITY, [])


def request(case_id, text, email="x@example.com"):
    return {"case_id": case_id, "email": email, "request_text": text, "requested_at": "2026-08-01T00:00:00Z",
            "reported_status": "NOT_STARTED", "reported_at": "2026-08-02T00:00:00Z", "audit_at": "2026-09-01T00:00:00Z"}


def test_non_deletion_request_is_not_applicable_with_no_steps():
    classifier = FakeClassifier({"copy please": ACCESS, "delete please": DELETION})

    answers, _, _ = agent.audit_all([request("c1", "copy please"), request("c2", "delete please")], classifier, IDENTITY, STORE)

    assert answers["c1"].status == "NOT_APPLICABLE"
    assert answers["c1"].steps == ()
    assert answers["c2"].status != "NOT_APPLICABLE"


def test_all_texts_are_classified_in_one_pass_before_the_case_loop():
    classifier = FakeClassifier({"a": DELETION, "b": ACCESS})

    agent.audit_all([request("c1", "a"), request("c2", "b"), request("c3", "a")], classifier, IDENTITY, STORE)

    assert len(classifier.batches) == 1


def test_deletion_requests_are_resolved_to_subjects_and_counted():
    classifier = FakeClassifier({"delete": DELETION, "copy": ACCESS})
    requests = [request("c1", "delete"), request("c2", "delete", "OLD.X@example.com"),
                request("c3", "delete", "nobody@example.com"), request("c4", "copy")]

    _, stats, case_files = agent.audit_all(requests, classifier, IDENTITY, STORE)

    assert (stats.resolved, stats.via_old_email, stats.unresolved) == (2, 1, ["c3"])
    assert set(case_files) == {"c1", "c2", "c3"}
    assert case_files["c3"] is None
