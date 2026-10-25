# Stage 5 — State reconstruction at `audit_at`

| Field | Value |
|---|---|
| Status | **Done** — state at audit_at per facet with proof; 93/93 states, 65/65 proofs on samples (§7) |
| Dates | 2026-10-25 → 2026-10-25 |
| PRD link | `code/docs/PRD.md` §7 Stage 5 (FR-5.1 – FR-5.4); conventions C-TM-1…3, C-ST-1…4, C-SP-4 |
| Depends on | Stage 4 case files (linked resources with raw observations, coverage) |
| Feeds | Stage 6 (policy compares required vs actual state), Stage 7 (which file proves each state) |

## 1. Goal

For every resource in a case file, decide its **state at `audit_at`** from evidence, never from
claims, and keep the **file that proves it**. Stage 4 stored raw values without judging them; Stage 5
judges them.

## 2. Questions

| # | Question | Answer in |
|---|---|---|
| Q5-1 | Which raw values mean present, absent, identifiable, redacted, anonymized, flow active/disabled, restore open/blocked? | §4.2 |
| Q5-2 | Which observation decides when there are several? | §4.3 |
| Q5-3 | When does a snapshot's silence prove absence, given snapshots are slices of ~30 people? | §4.4 |
| Q5-4 | Which file is cited as proof? | §4.5 |
| Q5-5 | How do we measure state before any steps exist? | §4.6 |

## 3. Inputs

Case files from Stage 4 (observations with `observed_at`, `captured_at`, `location`, raw `fields`),
the store's `Coverage` entries, `audit_at`. Activity results are not inputs: they are claims (C-ST-1).

## 4. Design

### 4.1 State model

A resource's state has up to four independent facets; each comes with its own proof:

| Facet | Values | Typical resources |
|---|---|---|
| existence | present / absent | every record |
| identity | identifiable / redacted / anonymized | profiles, analytics, support, tombstones, search, exports |
| flow | active / disabled | data flows (sync connectors) |
| restore | open / blocked | backups |

Stage 6 decides which facet matters for a resource (a backup is retained, so only *restore* is a
problem; a tombstone must exist and be redacted).

### 4.2 Reading raw values (measured inventory of every signal in the evidence)

| Signal (format) | Facet → value |
|---|---|
| Explicit state `FOUND` / `NOT_FOUND` / `IDENTIFIABLE` / `ANONYMIZED` / `REDACTED` / `ACTIVE` / `DISABLED` / `BLOCKED` (handover, record-lookup logs, ledgers) | existence / identity; `ACTIVE` → restore open for backup labels, else flow active |
| `rows` 0 / ≥1, `http_status` or `status_code` 404 / 200 | existence absent / present |
| Search `result=hit`, `total_hits` or parent `hits.total` > 0 | present |
| `available`, `download_available` true / false | present / absent |
| A row in a snapshot table or collection | present (unless its own fields say otherwise) |
| `enabled`, `scheduler_registered` true / false | flow active / disabled |
| `restore_allowed` true / false; `eligible`=true with `deletion_block`=false; `decision=deny` | restore open / blocked |
| `direct_identifiers` 1 / 0 | identifiable / anonymized |
| PII scan with `matched_value` | identifiable |
| `message_text` = `[REDACTED]` | redacted |
| Identifier fields (email, phone, names, hash, requester/owner/customer contact, nested `document`/`profile`) and reference fields (`customer_reference`, `subject_reference`, `user_id`) | any direct identifier filled → identifiable; all direct identifiers empty but a reference kept → redacted; everything empty → anonymized. Free text (message excerpts) naming an identifier → identifiable. The string `"null"` counts as empty |

### 4.3 Which observation decides (C-TM-2, C-TM-3, C-ST-4)

Per facet: among observations with `observed_at ≤ audit_at`, the **latest** one that speaks to that
facet decides. Copies observed at the same time are combined: present in **any** copy means present
(replica drift); identifiable in any copy means identifiable.

### 4.4 Absence from silence (coverage)

A record with no existence observation at all can still be proven absent: a snapshot that covers its
system, captured at or before `audit_at`, without a row for it. Because snapshots are slices, silence
is used **only** when no observation speaks to existence. Whether a later covering snapshot may
override an earlier "present" is measured on the samples (§7), not assumed.

### 4.5 Proof

The proof is the evidence file of the deciding observation (or covering snapshot) if its manifest
`captured_at ≤ audit_at` (C-TM-1). If the deciding fact sits in a file captured after `audit_at`, the
state still stands (the fact is dated before the audit), but the latest earlier citable file that
agrees is cited instead, or none.

### 4.6 Measuring it

A **state suite** derives each expected resource's state from the sample answers: a finding gives its
state (`REPORT_REMAINING_RECORD` → present, `REPORT_EXPOSED_PII` → identifiable,
`REPORT_ACTIVE_DATA_FLOW` → flow active, `REPORT_RESTORE_RISK` → restore open); otherwise the
verification gives it (`VERIFY_RECORD_ABSENT` → absent, `…_PRESENT` → present, `…_REDACTED`,
`…_ANONYMIZED`, `…_DATA_FLOW_DISABLED`, `…_RESTORE_BLOCKED`). Scored: state accuracy per facet, and
proof accuracy where the answer cites a file. Only linked resources are scored (linking is Stage 4's
metric).

## 5. Acceptance checks

| Check | Pass condition |
|---|---|
| Unit tests | Every signal in §4.2; latest-wins; replica "any copy"; coverage absence; proof rules incl. post-audit files |
| State suite | ≥ 95% state accuracy on linked sample resources; ≥ 90% proof accuracy; every miss explained |
| No regressions | All earlier suites and tests unchanged |

## 6. Out of scope

Policy categories and required actions (Stage 6); steps and final status (Stage 7).

## 7. Results

### 7.1 What was built

| File | Role |
|---|---|
| `code/deletion_audit/state.py` | `read_signals` (one observation → facets), `resolve_state` (latest-wins per facet, any-copy rule, coverage absence, proof selection), `ResourceState`, `Facet` |
| `code/deletion_audit/evidence.py` | `files_by_resource` (which files show each resource, for absence-from-silence) |
| `code/main.py` | `--explain` prints each resource's state and proof |
| `code/evaluation/state_suite.py` | `--suite states`: state accuracy per facet and proof accuracy against the states the answers imply |
| `code/tests/test_state.py` | 33 tests (130 in total) |

### 7.2 Results

| Suite | State accuracy | Proof accuracy |
|---|---|---|
| samples (93 linked expected resources) | **93/93** (existence 63, flow 9, identity 15, restore 6) | **65/65** |
| custom | 12/12 | 6/6 |

Consistency over all 508 eval deletion cases (1,542 resources): every resource has a known
existence; no resource is "absent" with a flow or restore state; 118 existence states have no
citable proof (the deciding fact is in a file captured after `audit_at` and no earlier snapshot
covers it), which matters only for `COMPLETE` cases (Stage 7).

Answers to the design's open choice (§4.4): absence from silence is used only when no observation
speaks to existence, choosing the **latest covering snapshot captured by `audit_at`**. That matched
every coverage-based citation in the samples (e.g. case_01 `account_001` → `evidence_54`). Letting a
later covering slice override an observed "present" was not needed.

### 7.3 Problems found and fixed

The first run scored 100%, but the suite only checks the one facet each answer implies, so the hard
cases were inspected by hand and across all eval cases. Four real problems were found:

| Problem | Example | Fix |
|---|---|---|
| A backup or connector row was not counted as existing when it carried a restore/flow value, so a coverage slice made it "absent" | case_09 `backup_4978` absent although listed with `restore_allowed=1` | A row always exists |
| An absent record kept an old "identifiable" | case_26 `account_5684` (404) | Absent records have no identity |
| Absence decided by a post-audit file had no proof | case_09 `account_3960` | Borrow proof from a covering snapshot captured by `audit_at` |
| Records read only through content signals (PII scan, analytics read) fell to coverage absence after the first fix | case_18 `analytics_037`, case_19 `support_9553` | Any content, flow or restore signal implies the record exists |
| A **cache** miss in the same log trace read as "record not found" | eval case_116 `data_flow_6699`, case_171 `backup_5520` | Log traces ignore cache-lookup lines |

### 7.4 Acceptance checks

| Check | Result |
|---|---|
| Unit tests | **Pass** — 130/130 |
| State suite | **Pass** — 100% state, 100% proof (targets 95% / 90%) |
| No regressions | **Pass** — `output.csv` byte-identical (answers still the stub); harness 22/32, 7/8; links unchanged |
