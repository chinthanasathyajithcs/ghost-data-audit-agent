# Stage 1 — Evaluation harness

| Field | Value |
|---|---|
| Status | **Done** — harness, validator, stub agent, 8 custom cases and 26 tests built; baseline recorded (§7) |
| Dates | 2026-10-25 → 2026-10-25 |
| PRD link | `code/docs/PRD.md` §7 Stage 1 (FR-1.1 – FR-1.5) |
| Depends on | Stage 0 (§3.2 coverage gaps, §8 implications) |
| Feeds | Every later stage (score after each change) · Stage 8 `evaluation_report.md` |

## How to read this document

§1 is the goal. §2 lists what we have to decide. §3 lists the inputs. **§4 is the design**: the
agent ↔ harness contract, the metric formulas, the format validator, the custom cases, the
outputs and the tests. §5 says how we will know the stage is done, §6 what it leaves out, and §7
is filled in at the end.

---

## 1. Goal

Build the measuring tool before building the agent. `code/evaluation/main.py` runs the agent on a
set of cases with known answers, compares its output step by step and prints four scores (case
status, step, field, sequence), a per-case diff showing what is missing, extra or wrong, and a
format check of `output.csv`. It covers the 32 public samples plus our own custom cases for
behaviour the samples never test (Stage 0 §3.2: `NOT_APPLICABLE`, legal hold, cache, telemetry,
marketing, email delivery log). Every later stage is judged by this tool, and its run history
becomes the "failures found and improvements made" section of `evaluation_report.md`.

## 2. Questions to answer

| # | Question | Answer in |
|---|---|---|
| Q1-1 | The grader's formulas are hidden. What exactly counts as a correct step, a correct field and a correct sequence? | §4.2 |
| Q1-2 | How does the harness call the agent: import a function or run the CLI? | §4.1 |
| Q1-3 | How do we create custom cases with trustworthy expected answers, given the samples have no `NOT_APPLICABLE` case? | §4.4 |
| Q1-4 | Which format rules can be checked mechanically (FR-1.4)? | §4.3 |
| Q1-5 | How do we stop the harness from encouraging overfitting to 32 samples (SC-4)? | §4.6 |
| Q1-6 | Where do run results live so the code judge can see them (it ignores `.csv/.json`)? | §4.5 |
| Q1-7 | How do we test the harness before the agent exists? | §4.7 |

## 3. Inputs and dependencies

| Input | Use |
|---|---|
| `dataset/sample_deletion_requests.csv` | 32 sample requests (22 INCOMPLETE, 10 COMPLETE, 193 steps, 1–14 steps per case) |
| `dataset/sample_output.csv` | Their expected outputs; read **only** by the harness, never by the agent |
| `dataset/deletion_requests.csv` | Source of real requests for hand-traced custom cases (§4.4) and the 518-row format check |
| `AGENTS.md` §6.3–6.4, PRD §5 | Output contract: columns, statuses, step fields, allowed operation→state pairs, ordering |
| PRD D10 | The strict sort (phase, operation order, `system_id`, `resource_id`) used by the order check |
| Python 3.14.4, pytest 9.1.1 | Already installed; the harness uses only the standard library |

## 4. Design

### 4.1 Agent ↔ harness contract

The harness runs the agent through its **real command line**, so every evaluation also tests the
entry point the graders will use:

```text
python code/main.py --requests <requests.csv> --output <predictions.csv> [--cases case_05,case_11]
```

- Defaults: `--requests dataset/deletion_requests.csv`, `--output output.csv` (repo root).
- `--cases` limits a run to some cases, for fast debugging loops.
- Stage 1 ships a **stub agent** that writes `INCOMPLETE` with `[]` for every case. It exists only
  so the pipeline runs end to end; Stages 2–7 replace its body.

The harness can also score a predictions file that already exists (`--predictions`), which keeps
scoring separate from running.

```text
python code/evaluation/main.py                    # run agent on samples + custom cases, score
python code/evaluation/main.py --suite samples    # samples only
python code/evaluation/main.py --cases case_05    # one case, full diff
python code/evaluation/main.py --predictions p.csv --suite samples   # score only, no run
python code/evaluation/main.py --validate output.csv                 # format check of a 518-row file
```

### 4.2 Metric definitions

The grader's formulas are hidden, so we define our own, state them in `evaluation_report.md` and
keep them fixed so scores stay comparable across iterations. Definitions below are over a suite of
cases; G = expected steps, P = predicted steps for a case.

| Metric | Definition | Why |
|---|---|---|
| **Case status accuracy** | Cases whose `deletion_status` equals the expected value ÷ cases. Also shown as a 3×3 confusion matrix (COMPLETE / INCOMPLETE / NOT_APPLICABLE). | The headline decision. The matrix shows which way we fail. |
| **Step accuracy** (row-level) | A step matches when `phase, system_id, resource_id, operation, state, evidence_id` are all equal (`step_no` excluded, as position is scored by sequence). Matching is one-to-one, as multisets. Report **precision** = matched ÷ \|P\|, **recall** = matched ÷ \|G\|, **F1**, summed over all cases (micro). | Recall measures "did we find the ghost data", precision "did we invent findings". |
| **Field accuracy** | Align P and G per case by the key `(phase, system_id, resource_id)`; for each aligned pair compare all 7 fields. An unmatched G step counts as 7 wrong fields, and an unmatched P step adds 7 wrong fields too. Field accuracy = correct fields ÷ total fields; also reported **per field** (e.g. `evidence_id` 81%). | Shows *which* part is wrong: right record, wrong operation; right finding, wrong citation. |
| **Sequence accuracy** | **Exact:** cases whose full `steps_json` equals the expected array (all fields, including `step_no` and order) ÷ cases. **Partial:** mean over cases of LCS(P, G) ÷ max(\|P\|, \|G\|), where steps are compared on the six matching fields. | Exact is the strictest "whole answer right". Partial gives credit for a mostly right plan. |
| **Fully correct cases** | Status equal **and** exact sequence equal. | The number we care about most. |

Rules that apply to every metric:

- A `NOT_APPLICABLE` case with expected `[]` and predicted `[]` counts as an exact sequence match.
  It adds nothing to step or field counts.
- A missing prediction row counts as status wrong and every expected step missing.
- Breakdowns are printed for step recall/precision **by operation** and **by phase**, so a gap
  such as "we never emit `VERIFY_RESTORE_BLOCKED`" stands out.
- Samples and custom cases are reported **separately and combined**, so the custom cases cannot
  hide a sample regression and the reverse.

Reference baselines on the 32 samples (computed now, from the expected answers alone):

| Baseline | Status accuracy |
|---|---|
| Always `INCOMPLETE` | 22/32 = 69% |
| Copy `reported_status` (COMPLETE→COMPLETE, else INCOMPLETE) | 17/32 = 53% |

Status accuracy by itself is therefore weak evidence: a stub reaches 69%. Step recall and fully
correct cases are the numbers that show real progress.

### 4.3 Format validator (FR-1.4)

`validate.py` checks a predictions file and returns a list of errors (empty = valid). The agent
calls it before writing `output.csv`, and the harness runs it on every predictions file.

| Check | Rule |
|---|---|
| Header | Exactly `case_id,deletion_status,steps_json` |
| Coverage | One row per `case_id` in the requests file, no extras, no duplicates (518 for the full run) |
| Sorting | Rows sorted by `case_id` |
| Status | One of `COMPLETE`, `INCOMPLETE`, `NOT_APPLICABLE` |
| JSON | `steps_json` parses to a list of objects with exactly the 7 step fields |
| Numbering | `step_no` = 1, 2, 3, … |
| Vocabulary | Phase and operation from the allowed table; `state` equals the operation's fixed state |
| Phase order | All FINDING, then REMEDIATION, then VERIFICATION |
| Strict sort | Steps follow D10 (phase → operation order → `system_id` → `resource_id`) |
| Status ↔ steps | `NOT_APPLICABLE` ⇒ `[]`; `COMPLETE` ⇒ VERIFICATION only, non-empty, every `evidence_id` set; `INCOMPLETE` ⇒ at least one FINDING; findings cite evidence; REMEDIATION and VERIFICATION have `evidence_id = ""` |
| Citations exist | Every cited `evidence_id` is a `file_id` in `evidence_files.csv`, an `activity_id` or an `audit_id` |
| Citation time | Every cited item's time (`captured_at`, `event_time`) ≤ the case's `audit_at` |

Run against `dataset/sample_output.csv`, the validator must report **zero** errors. If it does
not, the rule is wrong, not the sample.

### 4.4 Custom evaluation cases (FR-1.5)

The brief requires at least three. We plan **eight**, of two kinds:

**A. Metamorphic cases.** Take a sample whose answer we know and change one input in a way whose
effect on the answer is certain. The expected answer then follows from the sample with no
guesswork.

| ID | Built from | Change | Expected | Tests |
|---|---|---|---|---|
| CC-1 | a sample case | `request_text` → a data **access** request ("send me a copy of my data") | `NOT_APPLICABLE`, `[]` | Intent (Stage 2) |
| CC-2 | a sample case | `request_text` → a **marketing opt-out** in Japanese ("stop sending promotional emails") | `NOT_APPLICABLE`, `[]` | Intent, non-English, deletion-like wording |
| CC-3 | a sample case | `request_text` → an **email correction** in Portuguese | `NOT_APPLICABLE`, `[]` | Intent, non-English |
| CC-4 | case_12 (user_12) | `email` → the user's **old** address `minjun.kim90@gmail.com` (from `user_audit_log.csv`) | Same as case_12 | Historical identity (Stage 3) |
| CC-5 | a COMPLETE sample | `audit_at` → a time **before** its cited file was captured | Must not cite that file; expected answer derived by hand trace | Time cutoff (Stage 5) |

**B. Hand-traced cases.** Pick real requests from `deletion_requests.csv` that touch rules no
sample covers, and work out the answer by hand with the Stage 0 conventions, writing down the
reasoning.

| ID | Covers | Tests |
|---|---|---|
| CC-6 | `LEGAL_HOLD_RECORD` (rule_13) | Retain + `VERIFY_RECORD_PRESENT` |
| CC-7 | `CACHE_ENTRY` or `PRODUCT_TELEMETRY` (rule_04 / rule_08) | Unseen categories |
| CC-8 | `EMAIL_DELIVERY_LOG` or `MARKETING_PROFILE` (rule_11 / rule_10; marketing exists only in a screenshot) | Unseen categories, image evidence |

Exact source cases for CC-1–3, CC-5 and CC-6–8 are chosen while building. Rules for custom cases:

- Stored in `code/evaluation/custom_cases/requests.csv` and `expected.csv` (same formats as the
  samples), with a `custom_` prefix on `case_id` so they never collide with real IDs.
- Every case is also written up in `code/evaluation/custom_cases/README.md`: source, change,
  expected answer and the reasoning behind it. The code judge ignores CSV files, so the Markdown
  is what it reads.
- Hand-traced answers are our own labels, used **only** for scoring. The agent never reads
  `code/evaluation/`.
- Because the stub cannot trace evidence, CC-5–8 expected answers are traced by hand now and
  re-checked once the agent produces them. A disagreement is investigated rather than resolved
  automatically in either direction.

### 4.5 Outputs and run history

| Output | Content | Visible to code judge |
|---|---|---|
| Terminal | Summary table, per-operation breakdown, list of failing cases | — |
| `--cases` view | Per-case diff: expected vs predicted status, steps marked `missing` / `extra` / `wrong field (x→y)` | — |
| `code/evaluation/runs/<timestamp>.json` | Full metrics and diffs for one run (git-ignored, regenerable) | No |
| `code/evaluation/run_history.md` | One appended row per run: time, git commit, label (`--label "stage 3 identity"`), the headline scores | **Yes** |

`run_history.md` is the raw material for the "failures found and improvements made" section of
`evaluation_report.md` in Stage 8.

### 4.6 Overfitting guard (SC-4)

- The agent never imports from `code/evaluation/` and never reads `sample_output.csv` or the
  custom expected files. A test in §4.7 checks this by scanning the agent's source.
- A fix that raises the score must be stated as a general rule (a convention ID from Stage 0 or a
  new one). The run label names that rule.
- Custom cases are reported apart from samples, so a gain on samples that breaks a custom case
  shows up.
- A grep check for case IDs (`case_\d+`) and evidence file IDs (`evidence_\d+`) in the agent's
  source runs with the tests. Any hit fails the run.

### 4.7 Testing the harness

The harness has to be right before it can judge anything. Tests in `code/tests/`, run with pytest:

| Test | Expectation |
|---|---|
| Perfect prediction (expected scored against itself) | Every metric 100%, validator 0 errors |
| Drop one step | Recall falls by exactly 1/\|G\|; precision stays 100%; that case's exact sequence fails |
| Add one invented step | Precision falls; recall stays 100% |
| Swap two steps | Step and field scores unchanged; exact sequence fails; partial sequence < 1; validator flags the sort |
| Change one `evidence_id` | Step match lost for that step; field accuracy loses one field; per-field `evidence_id` drops |
| Wrong status only | Status accuracy and the confusion matrix change; step metrics unchanged |
| Missing row / duplicate row / bad JSON / unknown operation / wrong state / citation after `audit_at` | Each one detected by the validator with a clear message |
| `NOT_APPLICABLE` with `[]` | Counted as exact sequence match, no step counts |
| No-leak scan | Agent source contains no import from `evaluation`, no read of `sample_output.csv`, no `case_NN` / `evidence_NN` literals |

Then an end-to-end run: stub agent on samples → baseline row in `run_history.md` (expected status
accuracy 69%, step recall 0%).

### 4.8 Proposals to agree before coding

| # | Proposal | Alternative |
|---|---|---|
| P1 | Metric formulas as in §4.2 (multiset step match without `step_no`; key-aligned field accuracy; exact + LCS sequence) | Position-by-position comparison: simpler, but one missing step shifts every later step and makes them all wrong |
| P2 | Harness runs the agent through its CLI as a subprocess (§4.1) | Import a function: faster, but does not test the real entry point |
| P3 | Eight custom cases: five metamorphic and three hand-traced (§4.4) | Only the three required, all metamorphic: quicker, but no coverage of unseen policy rules |
| P4 | Validator shared by the harness and the agent (the agent checks its own output before writing) | Harness-only validation |
| P5 | `run_history.md` committed; per-run JSON git-ignored | Commit everything; or keep no history |

## 5. Acceptance checks

| Check | Pass condition |
|---|---|
| Harness tests | All §4.7 tests pass |
| Sample self-check | Scoring `sample_output.csv` against itself gives 100% everywhere; validator gives 0 errors |
| Stub run | `python code/evaluation/main.py` runs the stub end to end on samples + custom cases and appends a baseline row to `run_history.md` |
| Full-file check | Stub on `deletion_requests.csv` produces a 518-row `output.csv` that passes the structural validator checks (header, coverage, sort, JSON) |
| Custom cases | ≥ 3 cases (target 8) in CSV, each documented in `custom_cases/README.md` with its reasoning |
| No leak | Agent source does not touch `code/evaluation/`, sample answers or ID literals |

## 6. Out of scope

- Any real agent logic: intent (Stage 2), identity (3), evidence (4), state (5), policy (6), steps (7).
- Writing `evaluation_report.md` and `usage_report.md` (Stage 8); Stage 1 only produces the data for them.
- Token and cost tracking (added with the LLM backend in Stage 2).
- Guessing the grader's real weighting; we report our metrics and say they are our own definitions.

## 7. Results

### 7.1 What was built

| File | Role |
|---|---|
| `code/deletion_audit/contract.py` | Output contract shared by agent and harness: columns, statuses, operation→phase/state table, strict sort key, deterministic JSON, CSV read/write |
| `code/deletion_audit/validate.py` | Format validator (§4.3), returns readable errors |
| `code/main.py` | Agent CLI (`--requests`, `--output`, `--cases`); `audit_case` is a stub; validates its own output and prints problems |
| `code/evaluation/scoring.py` | Metrics (§4.2) and per-case diffs |
| `code/evaluation/report.py` | Terminal tables, case diffs, history rows, run JSON |
| `code/evaluation/main.py` | Harness CLI: run agent → validate → score → print → record |
| `code/evaluation/custom_cases/` | `requests.csv`, `expected.csv`, `README.md` (8 cases with reasoning) |
| `code/evaluation/run_history.md` | One row per full run (committed); per-run JSON in `runs/` (git-ignored) |
| `code/tests/` | 26 pytest tests: scoring (10), validator (14), no-leak guard (2) |

All proposals P1–P5 were agreed and built as written.

### 7.2 Acceptance checks

| Check | Result |
|---|---|
| Harness tests | **Pass** — 26/26 |
| Sample self-check | **Pass** — `sample_output.csv` scored against itself: 100% on every metric, 0 format problems. The same holds for the custom expected file (8/8, 0 problems) |
| Stub run | **Pass** — baseline row recorded in `run_history.md` |
| Full-file check | **Pass** — stub writes 518 rows; header, coverage, sort and JSON checks pass. The only problems are the 518 expected "INCOMPLETE needs at least one FINDING" flags, which go away once the agent produces steps |
| Custom cases | **Pass** — 8 cases, documented in `custom_cases/README.md` |
| No leak | **Pass** — the guard caught a real hit during development (a comment in `contract.py` naming the sample answer file), which was reworded |

### 7.3 Baseline (stub: always INCOMPLETE, no steps)

| Suite | Status | Step F1 | Field | Seq exact | Fully correct |
|---|---|---|---|---|---|
| samples (32) | 68.8% | 0% | 0% | 0% | 0/32 |
| custom (8) | 37.5% | 0% | 0% | 50% | 0/8 |

As predicted in §4.2, a stub reaches 69% status accuracy on the samples, so step F1 and fully
correct cases are the progress numbers. The custom suite's 50% exact sequence comes from the four
`NOT_APPLICABLE` cases, where an empty prediction equals the empty expected list even though the
status is wrong. This is why "fully correct" requires the status as well.

### 7.4 Changes from the plan

| Planned | What happened | Why |
|---|---|---|
| Validator in `code/evaluation/`, shared with the agent (P4) | Placed in the agent package (`deletion_audit/validate.py`); the harness imports it from there | The no-leak rule (§4.6) forbids the agent importing from `code/evaluation/`; the harness may import agent code |
| CC-5: `audit_at` moved before the cited file | Replaced by a Korean rewrite of case_09 (same answer) | Without the cited file the expected answer would be a guess |
| CC-7: cache / telemetry case | Replaced by real non-deletion request case_540 | No personal cache, telemetry or email-delivery records exist in the evidence (only log noise such as `dns_cache`, `telemetry_flushed`) |
| CC-8: marketing profile from a screenshot | Replaced by an upper-case email variant of case_31 | The screenshot and a data-catalog activity disagree about who `marketing_001` belongs to (below) |

### 7.5 Findings carried forward

| # | Finding | Carried to |
|---|---|---|
| F1-1 | `LINK_RESOURCE_IDENTITY` activity (12 rows) is a **claim** linking a resource to an email and `user_id`. `activity_4008` links `marketing_001` to user_09 (case_63), while the screenshot of `marketing_001` shows a different, unknown person (Soo-jin Park, `sj.park@naver.com`) and the activity is dated after the screenshot. Decide how such links are used | Stages 3–4 (PRD Q10) |
| F1-2 | Rules rule_04 (cache), rule_08 (telemetry) and rule_11 (email delivery log) have no matching records in the evidence. The policy engine must still read them from the CSV, but they cannot be tested on real data | Stage 6 |
| F1-3 | Legal holds exist for four users with real requests (case_261, case_460, case_505, case_511), as `legal_service/legal_hold_*` records in SQL snapshots captured at those cases' `audit_at`. Decoys appear in the same snapshots (e.g. `backup_1140` in case_460's window belongs to `d.romero12@gmail.com`) | Stages 3–6 |
| F1-4 | Eval requests not caught by a simple deletion-keyword check: 12 French requests (`suppression` with an accent) plus four real non-deletion requests (case_533 phone update, case_535 data download, case_540 invoices, case_541 email change). Keyword rules alone are not enough, which supports the LLM decision (D7) | Stage 2 |
