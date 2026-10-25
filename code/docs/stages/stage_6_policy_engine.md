# Stage 6 — Policy engine

| Field | Value |
|---|---|
| Status | **Done** — categories + decision table; samples 93/93 exact decisions, 0 reviews on 1,542 eval resources (§7) |
| Dates | 2026-10-25 → 2026-10-25 |
| PRD link | `code/docs/PRD.md` §6 (policy table), §7 Stage 6 (FR-6.1 – FR-6.4); conventions C-PL-1…7, C-SP-1, C-SP-2 |
| Depends on | Stage 4 (observations, labels), Stage 5 (state per facet with proof), Stage 2 (LLM backend, cache) |
| Feeds | Stage 7 (steps, citations, case status) |

## 1. Goal

For every resource in a case file: decide its **data category** from the evidence, apply the matching
rule from `deletion_rules.csv` (read at runtime), compare the **required treatment** with the Stage 5
state, and produce the resource's **decision**: compliant or not, and the finding / remediation /
verification operations with the evidence that proves each.

## 2. Questions

| # | Question | Answer in |
|---|---|---|
| Q6-1 | How is a resource's category found without a hand-written mapping? | §4.1 |
| Q6-2 | How are rule conditions checked? | §4.2 |
| Q6-3 | Which state facet does each action judge, and what operations follow? | §4.3 |
| Q6-4 | Data flows have no rule; backups are retained but restorable. How are they handled? | §4.3 |
| Q6-5 | How is it measured? | §4.4 |

## 3. Inputs

The case file (resources with all observations), Stage 5 `ResourceState`, `deletion_rules.csv`,
`audit_at`.

## 4. Design

### 4.1 Category (C-PL-1)

Measured on the samples: within most systems one category fits every resource, but **support** and
**analytics** split by content: a ticket conversation (redact, rule_05), a customer-uploaded PDF
(delete, rule_06), a legacy contact-index lookup and a contact lookup with `email_opt_in` (delete as
secondary identifiers, rule_02 — this resolves Stage 0's H-PL-7 and OQ-6). Telling them apart is
reading comprehension, so:

1. **Explicit label.** If an observation's label is a rule category (`USER_PROFILE`,
   `SUPPORT_ATTACHMENT`, … from handovers, ledgers and record-lookup logs) or `DATA_FLOW`, it decides.
2. **LLM over an evidence signature.** Otherwise the resource's signature — system, labels, event
   names, field names and short descriptive values, **with identifiers removed** — is classified by
   Claude Haiku against the categories and conditions read from `deletion_rules.csv`, plus
   `DATA_FLOW` (a sync/connector process) and `OTHER`. Batched, schema-validated, cached by signature
   (resources sharing a signature share the answer), shipped like the intent cache. Prompt in
   `prompts/category.md`.

### 4.2 Conditions

Stage 0 found no case where a condition fails (OQ-3). Conditions with a checkable date are checked:
a retention or hold date (`retention_until`, `retained_until`, `retain until`) before `audit_at`
marks the condition as failed and the resource is flagged for review instead of guessed. All other
conditions are treated as met when the category is assigned.

### 4.3 Decision table (C-SP-1, C-SP-2)

| Required treatment | State | Finding → remediation → verification |
|---|---|---|
| DELETE | present | `REPORT_REMAINING_RECORD` → `DELETE_RECORD` → `VERIFY_RECORD_ABSENT` |
| DELETE | absent | `VERIFY_RECORD_ABSENT` only |
| REDACT (incl. tombstone) | identifiable | `REPORT_EXPOSED_PII` → `REDACT_RECORD` → `VERIFY_RECORD_REDACTED` |
| REDACT | redacted / anonymized | `VERIFY_RECORD_REDACTED` only |
| ANONYMIZE | identifiable | `REPORT_EXPOSED_PII` → `ANONYMIZE_RECORD` → `VERIFY_RECORD_ANONYMIZED` |
| ANONYMIZE | anonymized / redacted | `VERIFY_RECORD_ANONYMIZED` only |
| RETAIN, restore facet open | — | `REPORT_RESTORE_RISK` → `BLOCK_RESTORE` → `VERIFY_RESTORE_BLOCKED` |
| RETAIN, restore facet blocked | — | `VERIFY_RESTORE_BLOCKED` only |
| RETAIN, no restore facet | present | `VERIFY_RECORD_PRESENT` only |
| DATA_FLOW (no rule) | flow active | `REPORT_ACTIVE_DATA_FLOW` → `DISABLE_DATA_FLOW` → `VERIFY_DATA_FLOW_DISABLED` |
| DATA_FLOW | flow disabled | `VERIFY_DATA_FLOW_DISABLED` only |

Findings cite the proof of the facet that shows the problem; a compliant verification carries the
proof of the facet it verifies (used for `COMPLETE` cases in Stage 7). Combinations outside the table
(a record to redact that is absent, a retained record that is missing, an unknown state) are
reported as `needs_review` with the reason, never silently turned into a step.

### 4.4 Measuring it

A **decision suite**: for every linked expected resource in the samples and custom cases, the
operations the answer gives it (grouped per resource) against the decision's operations; plus
category coverage (explicit vs LLM) and the evidence cited for findings.

## 5. Acceptance checks

| Check | Pass condition |
|---|---|
| Unit tests | Explicit labels, signature building (no identifiers), category cache, condition dates, every row of §4.3, needs_review paths |
| Decision suite | ≥ 95% of linked expected resources get exactly the expected operations |
| No leak | Rules read from the CSV; no category names hard-coded outside the decision table's action names |

## 6. Out of scope

Assembling, numbering and sorting steps, case status and `output.csv` (Stage 7).

## 7. Results

### 7.1 What was built

| File | Role |
|---|---|
| `code/deletion_audit/policy.py` | `load_rules` (from the CSV), `decide` (decision table §4.3, condition dates, `needs_review`), `Decision` |
| `code/deletion_audit/category.py` + `prompts/category.md` | Explicit labels first; else `signature()` (system, resource kind, labels, the record's own log events, field names, descriptive values; identifiers and person fields never sent) classified by Haiku against the CSV policy; batched, validated, cached by signature |
| `code/deletion_audit/decisions.py` | One batched classification for all cases; per-case state + decision |
| `code/deletion_audit/cache/category_cache.json` | Category answers (current prompt version only), shipped |
| `code/main.py` | Runs categories for all deletion cases; `--explain` shows category, rule and operations per resource |
| `code/evaluation/decision_suite.py` | `--suite decisions` |
| Tests | 24 new (154 in total) |

### 7.2 Results

| Suite | Exact decision (finding/remediation/verification) | Finding citations | Needs review |
|---|---|---|---|
| samples (93 linked expected resources) | **93/93** (13 by label, 80 by LLM) | **41/41** | 0 |
| custom | 12/12 | 4/4 | 0 |

All 508 eval deletion cases (1,542 resources): every system maps to one consistent category, support
splits into 162 messages and 19 attachments, contact lookups become secondary identifiers, **0
resources need review**, and 352 cases have at least one finding (153 fully compliant, 3 with no
linked resources). Cost of a cold classification of every eval resource: 13 Haiku calls, about $0.03.

### 7.3 Iterations

| Run | Change | Samples exact | Finding |
|---|---|---|---|
| 1 | Explicit labels + LLM over signatures | 78/93 | 13 cleaned accounts (only a 404 or nothing) classified `OTHER`; one ticket read as secondary identifier because the audit's `lookup_key` was in its signature |
| 2 | Signature gains the resource kind (ID prefix); audit query keys removed; prompt: decide from kind and system when details are thin | 92/93 | `support_9553`: trace full of infrastructure retry lines, judged as "a PII-scanner log" |
| 3 | Signature uses only the log lines that name the record; prompt: classify the record, not the log | **93/93** | — |
| 4 | Eval scan: 3 review flags (connector screen with "Mode: Continuous", ticket screen with capitalised `Email`/`Customer`, legal hold seen only as `retained_order_loaded`) and one backup classed as an audit log | 90/93 | The new mode rule overrode `enabled: false` on three disabled connectors |
| 5 | `enabled`/`scheduler_registered` win over a configured mode; kind is the strongest clue | **93/93** | 0 reviews on 1,542 eval resources |

A privacy gap was found by code review, not by a test: display names (`"Jonas Berg"`) passed the
identifier filter. Identity and person fields' values are now never sent (test added).

### 7.4 Notes

- The prompt carries short guidance on four distinctions the policy implies (contact lookups are
  secondary identifiers; uploads are attachments vs conversations are messages; profiles, tombstones,
  holds). These are readings of the policy categories, not case answers; the categories and
  conditions themselves are read from the CSV at runtime.
- Conditions are treated as met except checkable retention/hold dates (none expired in the data).
- Stage 0's H-PL-7 and OQ-6 are resolved: "contact" records are `SECONDARY_IDENTIFIER` (rule_02, delete).

### 7.5 Acceptance checks

| Check | Result |
|---|---|
| Unit tests | **Pass** — 154/154 |
| Decision suite | **Pass** — 100% exact (target 95%) |
| No leak | **Pass** — rules from the CSV; guard passes |
| Reproducibility | **Pass** — offline run gives identical case files, states and decisions (1,646 cached answers, 0 calls); `output.csv` unchanged (answers still the stub until Stage 7) |
