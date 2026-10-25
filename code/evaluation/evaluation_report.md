# Evaluation report

Final agent (commit `8c4efc6` + Stage 8 changes), final full run with **empty LLM caches** (see
`usage_report.md`). All numbers below were produced by `python3 code/evaluation/main.py` and its
`--suite` options; every run is recorded in [`run_history.md`](run_history.md). The grader's formulas
are hidden, so the metric definitions we used are stated in §2 and were fixed before the agent existed
(Stage 1).

## 1. Headline results

| Metric | Samples (32 public cases) | Custom (8 cases, §4) | All (40) |
|---|---|---|---|
| **Case status accuracy** | **32/32 (100%)** | **8/8 (100%)** | 40/40 (100%) |
| **Step (row) precision** | **100%** (175/175) | 100% (20/20) | 100% |
| **Step (row) recall** | **90.7%** (175/193) | 90.9% (20/22) | 90.7% |
| **Step F1** | **95.1%** | 95.2% | 95.1% |
| **Field accuracy** (all 7 fields) | **88.7%** | 89.6% | 88.8% |
| **Sequence accuracy, exact** | **18/32 (56.2%)** | 6/8 (75%) | 24/40 (60%) |
| **Sequence accuracy, partial (LCS)** | **87.4%** | 94.4% | 88.8% |
| Fully correct cases (status + every step) | 18/32 | 6/8 | 24/40 |
| Format problems | 0 | 0 | 0 |

Full evaluation set: `output.csv` has 518 rows and **0 format problems** (header, one row per case,
sorted, valid JSON, consecutive step numbers, allowed operations and states, phase order, strict step
order, findings cited, remediation and future verification uncited, no citation captured after
`audit_at`). Distribution: 351 `INCOMPLETE`, 157 `COMPLETE`, 10 `NOT_APPLICABLE`.

Confusion matrix (samples + custom, rows = expected):

| | COMPLETE | INCOMPLETE | NOT_APPLICABLE |
|---|---|---|---|
| COMPLETE | 11 | 0 | 0 |
| INCOMPLETE | 0 | 25 | 0 |
| NOT_APPLICABLE | 0 | 0 | 4 |

Field accuracy per field (samples): `phase`, `system_id`, `resource_id`, `operation`, `state`,
`evidence_id` all **90.7%**; `step_no` **76.7%**. Every field error comes from a **missing** step (no
step has a wrong value); a missing step also shifts the `step_no` of the steps after it, hence the
lower `step_no` figure.

Per operation (samples): 13 of 15 operations at **100%** recall. The misses are all verification-only
steps of records the agent cannot link (§5): `VERIFY_RECORD_ABSENT` 41/50, `VERIFY_RECORD_ANONYMIZED`
5/12, `VERIFY_RECORD_PRESENT` 22/24. Every finding and every remediation is found (`REPORT_*` 41/41,
remediation 41/41).

## 2. Metric definitions (ours, fixed in Stage 1)

| Metric | Definition |
|---|---|
| Case status accuracy | Cases whose `deletion_status` equals the expected value |
| Step precision / recall / F1 | A step matches when `phase, system_id, resource_id, operation, state, evidence_id` are all equal (`step_no` excluded; position is scored by sequence). One-to-one multiset matching, micro-averaged over all steps |
| Field accuracy | Steps aligned per case by `(phase, system_id, resource_id)`; all 7 fields compared; an unaligned step on either side counts as 7 wrong fields |
| Sequence exact | The full `steps_json` array equals the expected array (all fields, order, numbering) |
| Sequence partial | Mean over cases of LCS(predicted, expected) / max(lengths) on the six matching fields |

Harness tests (`code/tests/test_scoring.py`) check the definitions: scoring the sample answers against
themselves gives 100% everywhere; dropping, adding, swapping a step or changing one `evidence_id` moves
exactly the expected metrics.

## 3. Component suites

Each pipeline stage has its own score, built from the sample answers (used only for scoring), so a
regression points to the stage that caused it.

| Suite | What is scored | Samples | Custom |
|---|---|---|---|
| `--suite intent` | Does the request authorise deletion? All 402 distinct request texts, hand-labelled (`intent_labels.md`) | **402/402**, intent label 402/402 | (included) |
| `--suite links` | Linked records vs the records in the expected answers | recall 93/111, **precision 93/93**, citations available 74/75 | recall 12/14, precision 12/12 |
| `--suite states` | Each linked record's state at `audit_at` vs the state its expected steps imply; proof file | **93/93** states, **65/65** proofs | 12/12, 6/6 |
| `--suite decisions` | Finding / remediation / verification per linked record | **93/93** exact, finding citations 41/41 | 12/12, 4/4 |
| Extraction bake-off | Screenshot/PDF facts vs hand-written truth (70 facts, 4 screenshots + 2 PDFs) | Haiku vision **70/70**, 0 row mix-ups | — |
| Unit tests | `pytest code/tests` | **163 passed** | |

The component scores explain the end-to-end score: intent, states and decisions are perfect on every
record that is linked; the only loss is linking recall (§5).

## 4. Custom evaluation cases

Eight cases we created (inputs in `custom_cases/requests.csv`, answers in `custom_cases/expected.csv`,
reasoning in [`custom_cases/README.md`](custom_cases/README.md)), covering what the 32 samples never
test — there is no `NOT_APPLICABLE` sample at all.

| Case | Built from | What it tests | Expected | Result |
|---|---|---|---|---|
| custom_01 | case_01, request → "send me a copy of my data" (English) | Access request is not deletion | `NOT_APPLICABLE` | ✅ |
| custom_02 | case_11, request → "stop promotional emails" (Japanese) | Marketing opt-out, non-English | `NOT_APPLICABLE` | ✅ |
| custom_03 | case_26, request → "correct my email" (Portuguese) | Correction, non-English | `NOT_APPLICABLE` | ✅ |
| custom_04 | case_12, email → the user's **old** address | Historical identity | Same as case_12 | ✅ |
| custom_05 | case_09, request rewritten in Korean | Deletion in another language | Same as case_09 | ✅ |
| custom_06 | Real eval case_261, traced by hand | Legal hold retained, replica drift, Korean text, workflow claimed `COMPLETE` | `INCOMPLETE`, 9 steps | Status ✅; 8/9 steps (misses the anonymized `analytics_5053`, linked only by activity — §5) |
| custom_07 | Real eval case_540 ("copy of last year's invoices") | Real non-deletion request | `NOT_APPLICABLE` | ✅ |
| custom_08 | case_31, email in capitals | Case-insensitive identity | Same as case_31 | Status ✅; 2/3 steps (misses cleaned `account_4857`, same limit as case_31) |

Metamorphic cases (custom_01–05, 08) have answers that follow with certainty from a published sample;
hand-traced cases (06, 07) document their trace. Three planned cases were dropped because no certain
answer exists in the data (`audit_at` before the cited file; cache/telemetry/email-log records, which
do not exist as personal records; the marketing screenshot whose catalog claim conflicts with its
content) — see the custom cases README.

## 5. Remaining errors and why they are not guessed

All 18 missed sample steps (and the 2 custom misses) are **verification-only steps** for records the
agent deliberately does not link:

| Kind | Sample misses | Why |
|---|---|---|
| Anonymized analytics records with every identifier blank and no earlier copy naming the person | 7 (case_03, 04, 21, 25, 26, 27, 28) | Nothing in the evidence ties them to the person. Linking them by deletion-worker activity windows was measured: 7 right vs 18 wrong, or 6 vs 14 when restricted to shared files — worse than missing them |
| Cleaned primary accounts competing in the same deletion batch | 8 (case_10, 18, 20, 23, 28, 29, 31, 32) | Several unowned accounts with the matching result remain in the deletion worker's window, and nothing available by `audit_at` says which is the subject's. In case_18, 31 and 32 (checked) the competitors are known to belong to other people **only through `evidence_03`, captured after those audits**; using it would change the answer with post-audit evidence (AGENTS.md §6.2), so the agent leaves the accounts unlinked |
| Records with no evidence and no activity at all | 3: `account_004` (case_04), `audit_record_6645` (case_18), `audit_record_5569` (case_20) | No trace exists |

None of these misses changes a case's status (status accuracy 100%), and no step is invented or wrong
(precision 100%).

## 6. Failures found and improvements made

Every stage was built test-first and scored before moving on; these are the failures the measurements
exposed and what changed (details in `code/docs/stages/`).

| Stage | Failure found | Improvement |
|---|---|---|
| 1 Harness | The stub answering `INCOMPLETE` for everything scored 68.8% status accuracy | Made step F1 and fully-correct cases the progress metrics; status alone is not evidence of quality |
| 2 Intent | v1 prompt 400/402: follow-ups ("verify my account was deleted", "audit the deletion") read as non-deletion | Rule: confirming one's own deletion keeps it in scope |
| 2 Intent | v2 401/402: "remove that search result too" read as a search-engine request | Rule: removing leftover copies of one's own data is deletion → **402/402** |
| 3 Identity | Phones in the identity file's own format not matched; compact phones silently never matched (generator read twice) | Keep original spelling; read input once; tests for both |
| 4 Linking | Activity-window linking of all unowned records: 57 wrong of 75 | Only one missing primary account per case → 0 wrong |
| 4 Linking | A March readback (404) linked an account to a September request | Scope rule: a record must be seen at or after the request → precision 100% with no expected record lost |
| 4 Linking | `account_00N` deletions worded differently from "primary profile" | Recognise accounts by system, not wording |
| 4 Linking | Ingrid's export visible only as a statement number in a PDF | Catalog display aliases pull in records showing the alias |
| 4A Extraction | Docling could not be installed within the 30-minute timebox | Claude vision (Haiku) chosen by the bake-off: 63/63, later 70/70 |
| 5 State | Backups with `restore_allowed` read as absent; absent records kept old identity; content-only reads fell to coverage absence | Rows always exist; absent records have no identity; any content signal implies existence |
| 5 State | A **cache miss** in the same log trace read as "record not found" | Cache-lookup lines ignored |
| 6 Policy | Cleaned accounts classified `OTHER`; audit lookup keys and infrastructure log lines misled the classifier | Signature gains the resource kind; lookup keys and other records' log lines removed → 93/93 |
| 6 Policy | Screen fields ("Mode: Continuous", capitalised "Email") unread; configured mode overrode `enabled: false` | Screen signals added; the enabled flag wins → 0 reviews on 1,542 eval records |
| 6 Policy | Display names could reach the LLM in signatures (privacy) | Identity and person field values never sent; test added |
| 7 Steps | A bundle snapshot dated before the audit but exported after it was cited | Coverage is citable only by its file's capture time |
| 7 Steps | case_126 reported an account present from a post-audit bundle | A later capture of the subject's data without the record proves absence (changes 1 record in 540 cases) |
| 8 Cold run | Fresh extraction varied: a screen header omitted (wrong catalog claim accepted), a panel reference turned into a record | Prompt requires header identity fields and keeps references as fields; marketing screen added to the truth set (70/70) |
| 8 Cold run | Category answer for one thin support-ticket signature varied between runs, flipping 7 tickets | Majority vote of three answers per batch; sharper secondary-identifier rule; final cold run reproduces the validated output exactly |

## 7. Reproducibility

- The final cold run produced exactly the same `output.csv` as the validated pre-cold version (0 differing
  cases).
- With the shipped caches, `python3 code/main.py` makes 0 LLM calls and reproduces `output.csv` byte for
  byte, also with Claude Code absent from `PATH`; the agent itself needs only the Python standard
  library.
- No organizer-only data, hard-coded case IDs or answers are used: the agent never reads the sample
  answers, custom answers or intent labels (`code/tests/test_no_leak.py` scans the agent source for
  answer files, case and evidence ID literals and evaluation imports).
