"""Overfitting guard (Stage 1 design §4.6): the agent must not see answers or hardcode IDs."""

import re

from conftest import CODE_DIR

NON_AGENT_DIRS = {"evaluation", "tests", "docs"}

FORBIDDEN = {
    "case ID literal": re.compile(r"\bcase_\d+"),
    "evidence file ID literal": re.compile(r"\bevidence_\d+"),
    "sample answer file": re.compile(r"sample_output"),
    "custom expected answers": re.compile(r"custom_cases|expected\.csv"),
    "evaluation import": re.compile(r"^\s*(from|import)\s+(evaluation|scoring)\b", re.MULTILINE),
}


def agent_sources():
    for path in CODE_DIR.rglob("*.py"):
        relative = path.relative_to(CODE_DIR)
        if relative.parts[0] not in NON_AGENT_DIRS:
            yield path


def test_agent_sources_exist():
    assert any(p.name == "main.py" for p in agent_sources())


def test_agent_source_has_no_answer_access_or_id_literals():
    violations = [
        f"{path.relative_to(CODE_DIR)}: {name}"
        for path in agent_sources()
        for name, pattern in FORBIDDEN.items()
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert violations == []
