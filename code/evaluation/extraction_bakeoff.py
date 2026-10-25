"""Stage 4A bake-off: which tool (or combination) extracts screenshots and PDFs best?

    .venv/bin/python code/evaluation/extraction_bakeoff.py [--skip-docling]

Scores every candidate against hand-written truth (extraction_truth/truth.json, 63 facts in
3 screenshots and 2 PDFs). A fact counts only if it appears in the extracted record with the right
resource_id (row association). Raw-text candidates (no records) get a text-recall score only.
Results are printed and written to extraction_bakeoff.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parent))

from deletion_audit.cache import JsonCache  # noqa: E402
from deletion_audit.contract import DATASET_DIR  # noqa: E402
from deletion_audit.extraction import DocumentExtractor  # noqa: E402
from deletion_audit.llm import ClaudeCliBackend  # noqa: E402
from deletion_audit.usage import UsageRecorder  # noqa: E402

TRUTH = json.loads((EVAL_DIR / "extraction_truth" / "truth.json").read_text(encoding="utf-8"))
FILES = {k: v for k, v in TRUTH.items() if not k.startswith("_")}
CACHE = EVAL_DIR / "runs" / "bakeoff_cache.json"
REPORT = EVAL_DIR / "extraction_bakeoff.md"
MODELS = {"sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}


def norm(text: str) -> str:
    """Lowercase; punctuation other than @ . _ + - / becomes a space (so 04:03 == 04 03, 1,284 == 1 284)."""
    return " ".join(re.sub(r"[^a-z0-9@._+\-/]+", " ", text.lower()).split())


def contains(haystack: str, needle: str) -> bool:
    return f" {norm(needle)} " in f" {norm(haystack)} "


def record_text(record: dict) -> str:
    return " | ".join(f"{k} {v}" for k, v in record["fields"].items()) + f" | {record['resource_id']}"


def score_records(file_id: str, records: tuple[dict, ...]) -> dict:
    facts = FILES[file_id]["facts"]
    by_id = {}
    for r in records:
        by_id.setdefault(r["resource_id"], []).append(record_text(r))
    found = misplaced = total = 0
    missing = []
    for resource_id, values in facts.items():
        own = " | ".join(by_id.get(resource_id, []))
        others = " | ".join(t for rid, ts in by_id.items() if rid != resource_id for t in ts)
        for value in values:
            total += 1
            if contains(own, value):
                found += 1
            elif contains(others, value):
                misplaced += 1
                missing.append(f"{resource_id}: {value!r} (under another resource)")
            else:
                missing.append(f"{resource_id}: {value!r}")
    invented = sorted({r["resource_id"] for r in records} - set(facts))
    return {"found": found, "misplaced": misplaced, "total": total, "missing": missing, "extra_ids": invented}


def score_text(file_id: str, text: str) -> dict:
    facts = [(rid, v) for rid, vs in FILES[file_id]["facts"].items() for v in vs]
    missing = [f"{rid}: {v!r}" for rid, v in facts if not contains(text, v)]
    return {"found": len(facts) - len(missing), "total": len(facts), "missing": missing}


def pypdf_text(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def docling_text(path: Path, converter) -> str:
    return converter.convert(str(path)).document.export_to_markdown()


def run(skip_docling: bool) -> dict:
    usage = UsageRecorder()
    cache = JsonCache(CACHE)
    backend = ClaudeCliBackend()
    extractors = {name: DocumentExtractor(backend, cache, model, usage=usage) for name, model in MODELS.items()}
    converter = None
    if not skip_docling:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()

    results: dict[str, dict] = {}
    texts: dict[str, dict] = {"pypdf": {}, "docling": {}}
    timings: dict[str, float] = {}

    def timed(name, fn):
        start = time.monotonic()
        value = fn()
        timings[name] = timings.get(name, 0.0) + time.monotonic() - start
        return value

    for file_id, meta in FILES.items():
        path = DATASET_DIR / meta["path"]
        is_pdf = path.suffix == ".pdf"
        if is_pdf:
            texts["pypdf"][file_id] = timed("E0 pypdf text", lambda: pypdf_text(path))
            results.setdefault("E0 pypdf text", {})[file_id] = score_text(file_id, texts["pypdf"][file_id])
            records = timed("E0+L pypdf → Claude Haiku",
                            lambda: extractors["haiku"].extract_text(path, texts["pypdf"][file_id], "pypdf"))
            results.setdefault("E0+L pypdf → Claude Haiku", {})[file_id] = score_records(file_id, records)
        if converter is not None:
            texts["docling"][file_id] = timed("E1 Docling text", lambda: docling_text(path, converter))
            results.setdefault("E1 Docling text", {})[file_id] = score_text(file_id, texts["docling"][file_id])
            records = timed("E1+L Docling → Claude Haiku",
                            lambda: extractors["haiku"].extract_text(path, texts["docling"][file_id], "docling"))
            results.setdefault("E1+L Docling → Claude Haiku", {})[file_id] = score_records(file_id, records)
        for name in ("sonnet", "haiku"):
            label = f"E3 Claude vision {name.title()}"
            records = timed(label, lambda: extractors[name].extract_file(path))
            results.setdefault(label, {})[file_id] = score_records(file_id, records)
            if converter is not None and name == "sonnet":
                results.setdefault("E3+E1 vision checked by Docling text", {})[file_id] = cross_check(
                    file_id, records, texts["docling"][file_id])

    return {"results": results, "timings": timings, "usage": usage.summary()}


def cross_check(file_id: str, records: tuple[dict, ...], ocr_text: str) -> dict:
    """Keep only vision values that Docling's OCR text also contains; report what the check removed."""
    checked = tuple({"resource_id": r["resource_id"],
                     "fields": {k: v for k, v in r["fields"].items() if contains(ocr_text, v)}} for r in records)
    score = score_records(file_id, checked)
    removed = sum(len(r["fields"]) for r in records) - sum(len(r["fields"]) for r in checked)
    return {**score, "removed_values": removed}


def write_report(outcome: dict) -> str:
    lines = ["# Stage 4A extraction bake-off — results", "",
             "Generated by `code/evaluation/extraction_bakeoff.py`. Truth: `extraction_truth/truth.json` "
             "(63 facts: 3 screenshots, 2 PDFs). *Found* = fact in the record with the right resource_id; "
             "*misplaced* = fact only under another resource (row-association error).", "",
             "| Candidate | Files | Found | Misplaced | Invented IDs | Time (s) |", "|---|---|---|---|---|---|"]
    for name, per_file in outcome["results"].items():
        found = sum(r["found"] for r in per_file.values())
        total = sum(r["total"] for r in per_file.values())
        misplaced = sum(r.get("misplaced", 0) for r in per_file.values())
        extra = sum(len(r.get("extra_ids", [])) for r in per_file.values())
        records_based = "misplaced" in next(iter(per_file.values()))
        lines.append(f"| {name} | {len(per_file)} | {found}/{total} ({found / total:.0%}) | "
                     f"{misplaced if records_based else '— (text only)'} | {extra if records_based else '—'} | "
                     f"{outcome['timings'].get(name, 0):.1f} |")
    lines += ["", "## Misses", ""]
    for name, per_file in outcome["results"].items():
        misses = [f"{fid} {m}" for fid, r in per_file.items() for m in r["missing"]]
        lines.append(f"- **{name}**: " + ("none" if not misses else "; ".join(misses[:15])
                                          + (f" … (+{len(misses) - 15})" if len(misses) > 15 else "")))
    lines += ["", "## LLM usage", ""]
    for model, t in outcome["usage"].items():
        lines.append(f"- {model}: {t['calls']} calls, ${t['cost_usd']:.4f}, {t['duration_s']:.0f}s")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-docling", action="store_true")
    args = parser.parse_args()
    outcome = run(args.skip_docling)
    report = write_report(outcome)
    REPORT.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
