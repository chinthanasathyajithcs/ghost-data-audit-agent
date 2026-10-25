"""Tests for the agent's case loop (code/main.py)."""

import importlib.util

from conftest import CODE_DIR

from deletion_audit.intent import IntentResult

# Load code/main.py by path: code/evaluation/main.py shares the module name "main".
_spec = importlib.util.spec_from_file_location("agent_main", CODE_DIR / "main.py")
agent = importlib.util.module_from_spec(_spec)
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


def request(case_id, text):
    return {"case_id": case_id, "email": "x@example.com", "request_text": text,
            "requested_at": "", "reported_status": "NOT_STARTED", "reported_at": "", "audit_at": ""}


def test_non_deletion_request_is_not_applicable_with_no_steps():
    classifier = FakeClassifier({"copy please": ACCESS, "delete please": DELETION})

    answers = agent.audit_all([request("c1", "copy please"), request("c2", "delete please")], classifier)

    assert answers["c1"].status == "NOT_APPLICABLE"
    assert answers["c1"].steps == ()
    assert answers["c2"].status != "NOT_APPLICABLE"


def test_all_texts_are_classified_in_one_pass_before_the_case_loop():
    classifier = FakeClassifier({"a": DELETION, "b": ACCESS})

    agent.audit_all([request("c1", "a"), request("c2", "b"), request("c3", "a")], classifier)

    assert len(classifier.batches) == 1
