"""Terminal and Markdown formatting for evaluation results."""

from __future__ import annotations

from deletion_audit.contract import STATUSES
from scoring import MISSING, CaseDiff, Score

MAX_PROBLEMS_SHOWN = 10
MAX_FAILING_SHOWN = 12
HISTORY_HEADER = (
    "| Time (UTC) | Commit | Label | Suite | Cases | Status | Step P / R / F1 | Field | "
    "Seq exact | Seq partial | Fully correct | Format problems |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
)


def pct(value: float) -> str:
    return f"{value * 100:5.1f}%"


def summary(name: str, result: Score, problems: list[str]) -> str:
    lines = [
        f"== {name} ({result.cases} cases) ==",
        f"  Status accuracy     {result.status_correct}/{result.cases}  {pct(result.status_accuracy)}",
        f"  Step P / R / F1     {pct(result.step_precision)} / {pct(result.step_recall)} / {pct(result.step_f1)}"
        f"   ({result.steps_matched} matched, {result.steps_expected} expected, {result.steps_predicted} predicted)",
        f"  Field accuracy      {pct(result.field_accuracy)}   "
        + "  ".join(f"{f}={pct(v).strip()}" for f, v in result.per_field_accuracy.items()),
        f"  Sequence exact      {result.exact_sequences}/{result.cases}  {pct(result.exact_sequence_accuracy)}"
        f"   partial {pct(result.partial_sequence_accuracy)}",
        f"  Fully correct       {result.fully_correct}/{result.cases}",
        f"  Format problems     {len(problems)}",
    ]
    lines += [f"    - {p}" for p in problems[:MAX_PROBLEMS_SHOWN]]
    if len(problems) > MAX_PROBLEMS_SHOWN:
        lines.append(f"    … {len(problems) - MAX_PROBLEMS_SHOWN} more")
    return "\n".join(lines)


def confusion_table(result: Score) -> str:
    predicted = list(STATUSES) + ([MISSING] if result.missing_cases else [])
    lines = ["  Confusion (rows = expected, columns = predicted)", "    " + "".join(f"{s[:14]:>16}" for s in predicted)]
    for expected in STATUSES:
        counts = [result.confusion.get((expected, p), 0) for p in predicted]
        if any(counts):
            lines.append(f"    {expected:<16}" + "".join(f"{n:>16}" for n in counts))
    return "\n".join(lines)


def operation_table(result: Score) -> str:
    lines = [f"  {'Operation':<28}{'expected':>9}{'predicted':>10}{'matched':>9}{'recall':>9}"]
    for name, count in {**result.by_phase, **result.by_operation}.items():
        recall = pct(count.matched / count.expected) if count.expected else "    -"
        lines.append(f"  {name:<28}{count.expected:>9}{count.predicted:>10}{count.matched:>9}{recall:>9}")
    return "\n".join(lines)


def failing_cases_line(result: Score) -> str:
    failing = result.failing_cases
    if not failing:
        return "  Failing cases: none"
    parts = []
    for d in failing[:MAX_FAILING_SHOWN]:
        status = "status ok" if d.status_ok else f"status {d.expected_status}→{d.predicted_status}"
        parts.append(f"{d.case_id} ({status}, -{len(d.missing)} +{len(d.extra)} ~{len(d.wrong_fields)})")
    more = f", … {len(failing) - MAX_FAILING_SHOWN} more (use --diff)" if len(failing) > MAX_FAILING_SHOWN else ""
    return f"  Failing cases {len(failing)} (-missing +extra ~wrong fields): " + ", ".join(parts) + more


def _step_text(step: dict) -> str:
    evidence = step.get("evidence_id") or '""'
    return f"{step.get('phase')} {step.get('operation')} {step.get('system_id')}/{step.get('resource_id')} [{evidence}]"


def case_diff(diff: CaseDiff) -> str:
    verdict = "OK" if diff.fully_correct else "FAIL"
    lines = [f"--- {diff.case_id}: {verdict}  status expected {diff.expected_status}, predicted {diff.predicted_status}"]
    lines += [f"    missing  {_step_text(s)}" for s in diff.missing]
    lines += [f"    extra    {_step_text(s)}" for s in diff.extra]
    lines += [
        f"    wrong    {w.phase} {w.system_id}/{w.resource_id}: {w.field} {w.expected!r} → {w.predicted!r}"
        for w in diff.wrong_fields
    ]
    if diff.status_ok and not (diff.missing or diff.extra or diff.wrong_fields) and not diff.exact_sequence:
        lines.append("    same steps, different order or step_no")
    return "\n".join(lines)


def history_row(time: str, commit: str, label: str, suite: str, result: Score, problems: int) -> str:
    cells = (
        time,
        commit,
        label.replace("|", "/"),
        suite,
        str(result.cases),
        pct(result.status_accuracy).strip(),
        " / ".join(pct(v).strip() for v in (result.step_precision, result.step_recall, result.step_f1)),
        pct(result.field_accuracy).strip(),
        pct(result.exact_sequence_accuracy).strip(),
        pct(result.partial_sequence_accuracy).strip(),
        f"{result.fully_correct}/{result.cases}",
        str(problems),
    )
    return "| " + " | ".join(cells) + " |\n"


def intent_history_row(time: str, commit: str, label: str, result) -> str:
    """Intent suite row: Status = authorises-deletion accuracy over distinct texts; step metrics do not apply."""
    cells = (time, commit, label.replace("|", "/"), "intent", str(result.texts),
             pct(result.accuracy).strip(), "—", "—", "—", "—", "—", "—")
    return "| " + " | ".join(cells) + " |\n"


def link_history_row(time: str, commit: str, label: str, suite: str, score) -> str:
    """Link suite row: Status = resource recall, Step P/R/F1 column = resource precision / recall."""
    cells = (time, commit, label.replace("|", "/"), suite, str(score.expected),
             f"recall {pct(score.recall).strip()}", f"precision {pct(score.precision).strip()}", "—", "—", "—",
             "—", "—")
    return "| " + " | ".join(cells) + " |\n"


def metrics_dict(result: Score, problems: list[str]) -> dict:
    return {
        "cases": result.cases,
        "status_accuracy": result.status_accuracy,
        "step_precision": result.step_precision,
        "step_recall": result.step_recall,
        "step_f1": result.step_f1,
        "field_accuracy": result.field_accuracy,
        "per_field_accuracy": result.per_field_accuracy,
        "exact_sequence_accuracy": result.exact_sequence_accuracy,
        "partial_sequence_accuracy": result.partial_sequence_accuracy,
        "fully_correct": result.fully_correct,
        "confusion": {f"{e}->{p}": n for (e, p), n in sorted(result.confusion.items())},
        "by_operation": {k: vars(v) for k, v in result.by_operation.items()},
        "format_problems": problems,
        "failing_cases": [
            {
                "case_id": d.case_id,
                "expected_status": d.expected_status,
                "predicted_status": d.predicted_status,
                "missing": list(d.missing),
                "extra": list(d.extra),
                "wrong_fields": [vars(w) for w in d.wrong_fields],
            }
            for d in result.failing_cases
        ],
    }
