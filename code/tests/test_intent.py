"""Tests for request-intent classification (Stage 2 design §4.2–4.7). No real LLM calls."""

import json

import pytest

from deletion_audit.cache import CacheError, JsonCache
from deletion_audit.intent import IntentClassifier, IntentError, normalise, prompt_version
from deletion_audit.llm import CallUsage, LLMError
from deletion_audit.usage import UsageRecorder

NOT_DELETION = {
    "Please stop the promotional emails.": "MARKETING_OPT_OUT",
    "Send me a copy of my data.": "ACCESS",
}


class FakeBackend:
    """Answers like a model would; can drop or corrupt results to exercise the retry path."""

    def __init__(self, available=True, drop_ids_once=(), inconsistent_texts=(), fail_with=None):
        self.available = available
        self.drop_ids_once = set(drop_ids_once)
        self.inconsistent_texts = set(inconsistent_texts)
        self.fail_with = fail_with
        self.calls = []

    def is_available(self):
        return self.available

    def complete_json(self, system_prompt, user_input, schema, model):
        if self.fail_with:
            raise self.fail_with
        requests = json.loads(user_input)["requests"]
        self.calls.append([r["text"] for r in requests])
        results = []
        for r in requests:
            if r["id"] in self.drop_ids_once:
                self.drop_ids_once.discard(r["id"])
                continue
            intent = NOT_DELETION.get(r["text"], "DELETION")
            authorizes = intent == "DELETION"
            if r["text"] in self.inconsistent_texts:
                authorizes = not authorizes
            results.append({"id": r["id"], "intent": intent, "authorizes_deletion": authorizes,
                            "language": "en", "reason": "test"})
        usage = CallUsage(model, 2, 1500, 0, 50 * len(requests), 0.0004, 3.0)
        return {"results": results}, usage


def make_classifier(tmp_path, backend, batch_size=25, usage=None, prompt="Classify requests."):
    cache = JsonCache(tmp_path / "intent_cache.json")
    return IntentClassifier(backend, cache, model="test-model", batch_size=batch_size, prompt=prompt, usage=usage)


def deletion_texts(n):
    return [f"Please delete account number {i}." for i in range(n)]


def test_normalise_trims_and_collapses_whitespace():
    assert normalise("  Please   delete\n my account. ") == "Please delete my account."


def test_classifies_deletion_and_non_deletion_requests(tmp_path):
    classifier = make_classifier(tmp_path, FakeBackend())
    texts = ["Please delete my account.", *NOT_DELETION]

    results = classifier.classify_all(texts)

    assert results["Please delete my account."].authorizes_deletion is True
    assert results["Please stop the promotional emails."].authorizes_deletion is False
    assert results["Please stop the promotional emails."].intent == "MARKETING_OPT_OUT"


def test_sends_misses_in_batches(tmp_path):
    backend = FakeBackend()
    classifier = make_classifier(tmp_path, backend, batch_size=25)

    classifier.classify_all(deletion_texts(30))

    assert [len(c) for c in backend.calls] == [25, 5]


def test_duplicate_and_whitespace_variants_are_classified_once(tmp_path):
    backend = FakeBackend()
    classifier = make_classifier(tmp_path, backend)

    results = classifier.classify_all(["Please delete my account.", "Please  delete my account. "])

    assert sum(len(c) for c in backend.calls) == 1
    assert len(results) == 2


def test_second_run_uses_the_cache_and_makes_no_calls(tmp_path):
    make_classifier(tmp_path, FakeBackend()).classify_all(deletion_texts(5))
    backend = FakeBackend(available=False)

    results = make_classifier(tmp_path, backend).classify_all(deletion_texts(5))

    assert backend.calls == []
    assert all(r.authorizes_deletion for r in results.values())


def test_refresh_ignores_the_cache(tmp_path):
    make_classifier(tmp_path, FakeBackend()).classify_all(deletion_texts(3))
    backend = FakeBackend()

    make_classifier(tmp_path, backend).classify_all(deletion_texts(3), refresh=True)

    assert sum(len(c) for c in backend.calls) == 3


def test_changing_the_prompt_or_model_changes_the_cache_key():
    assert prompt_version("prompt A") != prompt_version("prompt B")


def test_cached_answers_for_another_prompt_are_not_reused(tmp_path):
    make_classifier(tmp_path, FakeBackend(), prompt="Old prompt.").classify_all(deletion_texts(2))
    backend = FakeBackend()

    make_classifier(tmp_path, backend, prompt="New prompt.").classify_all(deletion_texts(2))

    assert sum(len(c) for c in backend.calls) == 2


def test_missing_result_is_retried_in_a_smaller_batch(tmp_path):
    backend = FakeBackend(drop_ids_once={"r2"})
    classifier = make_classifier(tmp_path, backend)

    results = classifier.classify_all(deletion_texts(4))

    assert len(results) == 4
    assert len(backend.calls) > 1


def test_inconsistent_result_that_never_resolves_raises(tmp_path):
    bad = "Please delete account number 1."
    classifier = make_classifier(tmp_path, FakeBackend(inconsistent_texts={bad}))

    with pytest.raises(IntentError, match="account number 1"):
        classifier.classify_all(deletion_texts(3))


def test_unavailable_backend_with_uncached_texts_stops_with_a_clear_message(tmp_path):
    classifier = make_classifier(tmp_path, FakeBackend(available=False))

    with pytest.raises(IntentError, match="3 request text"):
        classifier.classify_all(deletion_texts(3))


def test_backend_failure_is_reported_and_finished_batches_stay_cached(tmp_path):
    texts = deletion_texts(30)
    make_classifier(tmp_path, FakeBackend(), batch_size=25).classify_all(texts[:25])
    classifier = make_classifier(tmp_path, FakeBackend(fail_with=LLMError("rate limited")), batch_size=25)

    with pytest.raises(IntentError, match="rate limited"):
        classifier.classify_all(texts)

    cache = JsonCache(tmp_path / "intent_cache.json")
    assert len(cache) == 25


def test_usage_is_recorded_per_call(tmp_path):
    recorder = UsageRecorder(tmp_path / "usage.jsonl")
    classifier = make_classifier(tmp_path, FakeBackend(), batch_size=25, usage=recorder)

    classifier.classify_all(deletion_texts(30))

    summary = recorder.summary()
    assert summary["test-model"]["calls"] == 2
    assert summary["test-model"]["output_tokens"] == 50 * 30
    assert len((tmp_path / "usage.jsonl").read_text().splitlines()) == 2


def test_cache_survives_reload_and_rejects_a_corrupt_file(tmp_path):
    path = tmp_path / "cache.json"
    cache = JsonCache(path)
    cache.put("k", {"v": 1})
    cache.save()
    assert JsonCache(path).get("k") == {"v": 1}

    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CacheError):
        JsonCache(path)


def test_usage_can_be_summarised_per_task():
    recorder = UsageRecorder()
    recorder.record("intent", CallUsage("m", 1, 0, 0, 10, 0.01, 1.0), 25)
    recorder.record("extraction:vision", CallUsage("m", 2, 0, 0, 20, 0.02, 1.0), 1)

    tasks = recorder.summary(by="task")

    assert set(tasks) == {"intent", "extraction"}
    assert tasks["extraction"]["output_tokens"] == 20
