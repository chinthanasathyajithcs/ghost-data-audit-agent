# Stage 7 — Steps, case status and `output.csv`

| Field | Value |
|---|---|
| Status | **Done** — the full agent writes a valid 518-row `output.csv`; samples 32/32 status, step F1 95.1% (§4) |
| Dates | 2026-10-25 → 2026-10-25 |
| PRD link | `code/docs/PRD.md` §5 (output contract), §7 Stage 7 (FR-7.1 – FR-7.5); D10; C-SP-1…5 |
| Depends on | Stage 6 decisions (finding / remediation / verification with proofs), Stage 2 intent |
| Feeds | Stage 8 (full cold run, reports, packaging) |

## 1. Goal

Turn each case's decisions into the answer the grader reads: a status and an ordered, numbered, cited
list of steps, for every one of the 518 requests, in a file that passes the format checker.

## 2. Design (`code/deletion_audit/steps.py`)

| Situation | Answer |
|---|---|
| Request does not authorise deletion (Stage 2) | `NOT_APPLICABLE`, `[]` |
| Any decision has a finding | `INCOMPLETE`: every finding (citing its proof) → the remediation for each → a verification for every resource; remediation and verification cite nothing (AGENTS.md §6.6) |
| No finding | `COMPLETE`: one verification per resource, each citing the evidence that proves it |
| No linked resources (nothing remaining was found) | `COMPLETE`, `[]` |
| A finding whose only proof is in a file captured after `audit_at` | The finding line is left out (it cannot be cited); its remediation and verification stay. Safety net — occurs 0 times after §3 |
| A decision flagged `needs_review` | No steps (0 occurrences) |

Steps are sorted by the strict order (PRD D10: phase, operation order, `system_id`, `resource_id`) and
numbered from 1. Measured edge cases before choosing the rules: 3 eval cases and sample case_04 have no
linked resources (case_04's expected answer is `COMPLETE`); the format checker's "COMPLETE needs a
step" rule was ours, not the contract's, so it was removed.

## 3. Problems found by the first full run

The first 518-case run had two format problems, both real:

| Problem | Cause | Fix |
|---|---|---|
| case_178 cited `evidence_17`, captured after its audit | Absence-from-silence compared the **snapshot's inner date**, not the **file's** manifest date (a bundle exported after the audit can hold a snapshot dated before it) | `Coverage` carries the file's capture time; a snapshot is citable only if its file was captured by `audit_at` (C-TM-1) |
| case_126 was `INCOMPLETE` with no citable finding | `account_8819` was "present" on 08-11 in a bundle exported on 08-19, after the audit; `evidence_87`, an inventory captured at the audit **holding the subject's audit record**, covers the account system with **no row** for it | Stage 5 rule: a later citable snapshot that covers the resource's system, holds other records of the same subject and has no row for the resource proves it was gone by then. It changes exactly one resource in 540 cases (this one); all samples unchanged |

## 4. Results

| Suite | Status | Step P / R / F1 | Field | Seq exact | Fully correct | Format |
|---|---|---|---|---|---|---|
| samples (32) | **32/32** | **100% / 90.7% / 95.1%** | 88.7% | 18/32 | 18/32 | 0 |
| custom (8) | 8/8 | 100% / 90.9% / 95.2% | 89.6% | 6/8 | 6/8 | 0 |
| all (40) | 40/40 | 100% / 90.7% / 95.1% | 88.8% | 24/40 | 24/40 | 0 |

Baseline (stub) was 68.8% status and 0% steps. Every remaining sample failure is a **missing** step,
never an extra or wrong one: the 18 resources Stage 4 cannot link (cleaned accounts and anonymized
analytics records with no identifier, where linking would require guessing or evidence captured after
the audit). Missing a step also shifts later `step_no` values, which is why field accuracy for
`step_no` (76.7%) is below the other fields (90.7%).

Full eval run: 518 rows, 0 format problems: 351 `INCOMPLETE`, 157 `COMPLETE`, 10 `NOT_APPLICABLE`; the split comes from
the evidence (not from `reported_status`). Offline rerun with all caches: identical output, 0 LLM calls.

## 5. Acceptance checks

| Check | Result |
|---|---|
| Unit tests | **Pass** — 161/161 (5 for the step builder, 2 for the Stage 5 fixes) |
| Format | **Pass** — 518 rows, 0 problems (sorted, valid JSON, consecutive steps, allowed operations and states, phase order, strict sort, citation rules, no citation after `audit_at`) |
| Scores | Status 100% on samples and custom cases; step precision 100% |
| Earlier suites | **Pass** — states 93/93, decisions 93/93, links unchanged, intent unchanged |
