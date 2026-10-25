"""Tests for document and screenshot extraction (Stage 4A). No real LLM calls."""

import json

import pytest

from deletion_audit.cache import JsonCache
from deletion_audit.extraction import DocumentExtractor, ExtractionError
from deletion_audit.llm import CallUsage, ClaudeCliBackend


class FakeBackend:
    def __init__(self, reply=None, available=True):
        self.available = available
        self.reply = reply or {"records": [{"resource_id": "backup_1", "fields": {"Account": "a@b.com"}}]}
        self.calls = []

    def is_available(self):
        return self.available

    def complete_json(self, system_prompt, user_input, schema, model, read_dirs=()):
        self.calls.append({"input": user_input, "read_dirs": tuple(read_dirs), "model": model})
        return self.reply, CallUsage(model, 1, 0, 0, 10, 0.01, 2.0)


@pytest.fixture()
def image(tmp_path):
    path = tmp_path / "console.png"
    path.write_bytes(b"fake png bytes")
    return path


def make(tmp_path, backend):
    return DocumentExtractor(backend, JsonCache(tmp_path / "cache.json"), model="vision-model", prompt="Extract.")


def test_vision_mode_lets_the_model_read_only_the_files_folder(tmp_path, image):
    backend = FakeBackend()

    records = make(tmp_path, backend).extract_file(image)

    assert records == ({"resource_id": "backup_1", "fields": {"Account": "a@b.com"}},)
    assert backend.calls[0]["read_dirs"] == (image.parent,)
    assert str(image) in backend.calls[0]["input"]


def test_text_mode_sends_text_and_allows_no_file_access(tmp_path, image):
    backend = FakeBackend()

    make(tmp_path, backend).extract_text(image, "Archive ID backup_1 Account a@b.com", source="pypdf")

    assert backend.calls[0]["read_dirs"] == ()
    assert "backup_1" in backend.calls[0]["input"]


def test_results_are_cached_by_file_content(tmp_path, image):
    backend = FakeBackend()
    make(tmp_path, backend).extract_file(image)

    make(tmp_path, backend).extract_file(image)
    image.write_bytes(b"changed bytes")
    make(tmp_path, backend).extract_file(image)

    assert len(backend.calls) == 2


def test_records_without_a_resource_id_or_with_non_text_fields_are_dropped(tmp_path, image):
    reply = {"records": [{"resource_id": "", "fields": {"a": "b"}},
                         {"resource_id": "export_9", "fields": {"Owner": "x@y.com", "Size": 18}},
                         {"resource_id": "export_10", "fields": {"Owner": "z@y.com"}}]}

    records = make(tmp_path, FakeBackend(reply)).extract_file(image)

    assert [r["resource_id"] for r in records] == ["export_9", "export_10"]
    assert records[0]["fields"] == {"Owner": "x@y.com", "Size": "18"}


def test_reply_without_records_is_an_error(tmp_path, image):
    with pytest.raises(ExtractionError):
        make(tmp_path, FakeBackend({"rows": []})).extract_file(image)


def test_cli_command_grants_read_access_only_when_asked():
    cli = ClaudeCliBackend(which=lambda name: "/usr/bin/claude")

    plain = cli.command("s", {}, "m")
    reading = cli.command("s", {}, "m", read_dirs=["/data/images"])

    assert plain[plain.index("--tools") + 1] == ""
    assert reading[reading.index("--tools") + 1] == "Read"
    assert reading[reading.index("--add-dir") + 1] == "/data/images"
    assert json.loads(reading[reading.index("--json-schema") + 1]) == {}


def test_uncached_file_without_the_cli_is_a_clear_error(tmp_path, image):
    with pytest.raises(ExtractionError, match="not in the extraction cache"):
        make(tmp_path, FakeBackend(available=False)).extract_file(image)
