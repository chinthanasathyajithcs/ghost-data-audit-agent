# PRD — Ghost Data Still Exists: Deletion Audit Agent

| Field | Value |
|---|---|
| Challenge | HackerRank Orchestrate, October 2026 — *Ghost Data Still Exists* |
| Document status | Draft v0.10 — living document, updated at every major step |
| Last updated | 2026-10-25 |
| Sources of truth | `problem_statement.md`, `AGENTS.md` §6, `dataset/deletion_rules.csv`, `README.md` |

> How this document is used: this PRD holds the **big picture** — goal, contract, stage outline,
> decisions and risks. Detail is written **when a stage starts**: before any code for a stage, we
> go deep on it and write a stage design doc (`code/docs/stages/`, template in §7) covering what
> exactly we will do, the questions it must answer and how we will know it worked. The stage
> section below then links to that doc and is updated with the outcome. Decisions are made
> together and recorded in the Decision Log (§11). Nothing is marked "Decided" until it is agreed.

---

## 1. Problem

Northstar Shop (fictional) marks customer deletion requests as **"Complete"** when personal data
still survives in secondary databases, replicas, search indexes, support attachments, analytics,
exports, logs, archives and backups — sometimes under the customer's **old** email or phone. Sync
jobs and backup restores can also **recreate** data that was deleted. Some data must legally be
**kept**, redacted or anonymized rather than deleted. The company cannot prove which deletions are
truly complete; one ghost customer cost it $2.4M.

## 2. Goal

Build an **AI-powered deletion audit agent** that, for every request in
`dataset/deletion_requests.csv`, decides the true deletion state at `audit_at` and outputs an
evidence-backed, ordered plan:

- `NOT_APPLICABLE` — the request does not authorize deletion → `[]`
- `COMPLETE` — verification steps only, each citing evidence that proves the state
- `INCOMPLETE` — findings (with evidence) → remediation plan → post-remediation verification

### 2.1 Success criteria

| ID | Criterion | Target |
|---|---|---|
| SC-1 | Valid `output.csv`: 518 rows, sorted, exact header, valid JSON, consecutive step numbers | 100% |
| SC-2 | Case-level status accuracy on the 32 samples | Maximise (target ≥ 90%) |
| SC-3 | Step-level, field-level and sequence accuracy on the samples | Maximise, tracked per iteration |
| SC-4 | No hardcoded labels, case IDs, file-specific answers or case-family shortcuts | 0 violations |
| SC-5 | Required reports present and complete (`evaluation_report.md`, `usage_report.md`) | 100% |
| SC-6 | Clean terminal run processes all 518 cases deterministically | Pass |

### 2.2 Non-goals

- Training or fine-tuning a model (the 32 samples are an answer key for evaluation, not training data).
- A general-purpose RAG system (the evidence is ~3 MB and highly structured; exact identifier
  matching beats semantic retrieval).
- A UI or web service — a terminal program is sufficient.

## 3. Users & Stakeholders

| Who | Need |
|---|---|
| Northstar privacy / compliance team (story) | Proof of what is truly deleted and an ordered fix plan |
| HackerRank auto-grader | `output.csv` matching hidden canonical answers |
| Automated code judge | Runnable, non-hardcoded code + evaluation and usage reports (reads `.md`/source, ignores `.csv/.json/.log/.sql`) |
| AI Judge interviewer | Clear architecture, decisions, evaluation and AI-usage story (via `log.txt`) |

## 4. Inputs

All inputs are under `dataset/`.

| File | Rows | Role |
|---|---|---|
| `deletion_requests.csv` | 518 | Cases to audit: `case_id,email,requested_at,reported_status,reported_at,audit_at,request_text` |
| `sample_deletion_requests.csv` / `sample_output.csv` | 32 | Public cases + correct answers (evaluation only) |
| `user_identities.csv` | 850 | Current identity snapshot per `user_id` |
| `user_audit_log.csv` | 306 | Historical identity changes (old → new values) |
| `system_activity.csv` | 4,011 | Global event stream (all users, includes decoys); results are claims |
| `deletion_rules.csv` | 15 | Policy: data category + condition → required action |
| `evidence_files.csv` | 94 | Manifest: `file_id` → path, origin, `captured_at` |
| `evidence/` | ~3 MB | SQL dumps, JSON records, logs, text, 4 PDFs, 11 PNG screenshots |

Key input facts (from `AGENTS.md` §6.2):
- The request `email` may be a **current or historical** address.
- `request_text` may be in **different languages**.
- `reported_status` is a claim, not proof.
- Only information **at or before `audit_at`** may be used.

## 5. Output

`output.csv` at the **repository root**, header `case_id,deletion_status,steps_json`, 518 rows
sorted by `case_id`. Each step has exactly:
`step_no, phase, system_id, resource_id, operation, state, evidence_id`.

Allowed operations (no others may be invented):

| Phase | Operation → State |
|---|---|
| FINDING | `REPORT_REMAINING_RECORD`→PRESENT, `REPORT_EXPOSED_PII`→PRESENT, `REPORT_ACTIVE_DATA_FLOW`→ACTIVE, `REPORT_RESTORE_RISK`→ACTIVE |
| REMEDIATION | `DISABLE_DATA_FLOW`→DISABLED, `BLOCK_RESTORE`→BLOCKED, `DELETE_RECORD`→ABSENT, `REDACT_RECORD`→REDACTED, `ANONYMIZE_RECORD`→ANONYMIZED |
| VERIFICATION | `VERIFY_RECORD_ABSENT`→ABSENT, `VERIFY_RECORD_PRESENT`→PRESENT, `VERIFY_RECORD_REDACTED`→REDACTED, `VERIFY_RECORD_ANONYMIZED`→ANONYMIZED, `VERIFY_DATA_FLOW_DISABLED`→DISABLED, `VERIFY_RESTORE_BLOCKED`→BLOCKED |

Ordering: phase (FINDING → REMEDIATION → VERIFICATION), then operation order as in the table,
then `system_id` ascending, then `resource_id` ascending.

Evidence citation: findings and `COMPLETE` verification steps cite a `file_id`, `activity_id` or
`audit_id` captured at or before `audit_at`; remediation and post-remediation verification steps
for `INCOMPLETE` cases use `""`.

## 6. Policy (from `deletion_rules.csv`)

| Rule | Category | Condition | Action |
|---|---|---|---|
| rule_01 | USER_PROFILE | Always | DELETE |
| rule_02 | SECONDARY_IDENTIFIER | Always | DELETE |
| rule_03 | SEARCH_INDEX_ENTRY | Always | DELETE |
| rule_04 | CACHE_ENTRY | Always | DELETE |
| rule_05 | SUPPORT_MESSAGE | Conversation has shared customer/agent/order context to retain | REDACT |
| rule_06 | SUPPORT_ATTACHMENT | Attachment belongs only to the deletion subject | DELETE |
| rule_07 | ANALYTICS_PROFILE | Record still attributable to a user | ANONYMIZE |
| rule_08 | PRODUCT_TELEMETRY | Record still attributable to a user | ANONYMIZE |
| rule_09 | USER_EXPORT | Always | DELETE |
| rule_10 | MARKETING_PROFILE | Always | DELETE |
| rule_11 | EMAIL_DELIVERY_LOG | Log contains a user email address | REDACT |
| rule_12 | SECURITY_AUDIT_LOG | Within the supplied retention period | RETAIN |
| rule_13 | LEGAL_HOLD_RECORD | A supplied legal hold is active | RETAIN |
| rule_14 | BACKUP_ARCHIVE | Restore access can be blocked | RETAIN (+ block restore) |
| rule_15 | ACCOUNT_TOMBSTONE | Account deleted; only stable `user_id` needed for references | REDACT (keep `user_id`, remove name/email/phone/hash) |

The agent must read these rules from the CSV at runtime, not copy them into code.

## 7. Functional Requirements (by stage)

Each stage below is built and verified against the 32 samples before moving on.

**Stage kickoff (applies to every stage).** Before starting a stage we write
`code/docs/stages/stage_<n>_<name>.md` with these sections:

| Section | Content |
|---|---|
| Goal | What this stage must deliver, in one paragraph |
| Questions to answer | What we do not know yet and must find out (starting from the stage's carry-in notes below) |
| Inputs & dependencies | Files, earlier stages and decisions it relies on |
| Design | The detailed approach: data structures, algorithms, prompts, edge cases |
| Acceptance checks | How we know it works (sample metrics, unit tests, manual checks) |
| Out of scope | What this stage deliberately does not do |
| Results | Filled at the end: what happened, scores, failures and fixes, decisions taken |

The stage section in this PRD keeps only the big picture, a link to the stage doc and the status.
"Carry-in notes" are facts and questions found earlier that the kickoff must address.

### Stage 0 — Data discovery (manual trace)
- **Goal:** learn how the data encodes facts (sync flows, tombstones, failed deletes, replicas, retention, legal holds) by tracing sample cases by hand.
- **Output:** a "Data conventions" section appended to this PRD (§7.0 findings).
- **Carry-in notes** (from the PRD analysis):
  - How does each evidence record map to a policy category (rule_01–15)? Find the fields that carry it (system type, table name, record kind) so the mapping is derived from data, not a hand-written list.
  - Which `evidence_id` is cited for a step when several items could prove it? Samples cite only `evidence_xx` file IDs (never `activity_id`/`audit_id`); case_01 and case_02 both cite `evidence_54`, which looks like a shared snapshot.
  - How do `system_id` and `resource_id` values appear in each evidence format?
- **Stage doc:** [`stages/stage_0_data_discovery.md`](stages/stage_0_data_discovery.md)
- **Status:** **Done** (2026-10-25) — 9 traces over 17 sample cases, all evidence formats. Results in §7.0; open items OQ-1 (unlinked account IDs) and OQ-6 (unlabelled categories) carried into Stages 3–6.

### 7.0 Data conventions (from Stage 0)

Full detail, IDs and evidence: [`stages/stage_0_data_discovery.md`](stages/stage_0_data_discovery.md) §4.

| Area | Convention (short) | Stage |
|---|---|---|
| Identity | Subject = current snapshot + **full** identifier history (emails, phones, hashes); request email may be any old value; match exact identifiers only, never names or substrings | 3 |
| Formats | 12 shapes across txt, SQL (replica pair, inventory, generic), JSON (service export, snapshot bundle, single collection), logs (JSON-line, logfmt, readback), PDF, PNG — all normalised to one record model | 4 |
| Linking | Direct identifier · `user_id` reference · email hash · `trace_id` join across log lines. Cleaned records (deleted accounts, anonymized analytics) carry no identifier; only the deletion worker's activity links them (OQ-1) | 3–4 |
| Time | Cite only files with manifest `captured_at` ≤ `audit_at`; use facts whose own timestamp ≤ `audit_at`; latest observation wins | 5 |
| Claims | Activity results and `reported_status` are leads, never proof; wrong in both directions; `SUCCESS` ≠ good outcome | 5 |
| State | One vocabulary across formats (present / absent / identifiable / redacted / anonymized / flow active / restore open); replica copies compared individually | 5 |
| Policy | Category read from evidence (label, table, collection, content); policy beats request text; backups and security logs retained; tombstone keeps `subject_reference` only | 6 |
| Steps | Decision table (finding → fix → check); compliant resources get verification only; per-step citation of the snapshot showing the state; strict sort | 7 |

Kinds of problem to detect (from evidence, never assumed): downstream copies left behind, primary
account still present, replica drift, active syncs, restorable backups, data under old emails,
exposed tombstones, leftover attachments/exports.

Not covered by any sample (custom eval cases needed): `NOT_APPLICABLE`, legal holds, cache,
telemetry, marketing profiles, email delivery logs.

### Stage 1 — Evaluation harness (`code/evaluation/main.py`)
- FR-1.1 Run the agent on `sample_deletion_requests.csv` and compare with `sample_output.csv`.
- FR-1.2 Report case-level status accuracy, step-level accuracy, field-level accuracy, sequence accuracy.
- FR-1.3 Show per-case diffs (missing / extra / wrong steps) to drive fixes.
- FR-1.4 Validate output format (header, 518 rows, sorting, JSON validity, step numbering, allowed ops).
- FR-1.5 Support ≥ 3 custom evaluation cases created by us.
- **Carry-in notes:**
  - Define our own metric formulas (the grader's are hidden): what counts as a matching step, field-level accuracy over aligned steps, sequence accuracy (exact array match vs. longest common subsequence).
  - The 32 samples contain **no `NOT_APPLICABLE` cases** (22 INCOMPLETE, 10 COMPLETE), so custom cases must cover non-deletion requests, plus rules the samples barely test (historical email, evidence after `audit_at`).
  - Overfitting guard: every fix that raises the sample score must be a general rule (see SC-4).
- **Stage doc:** [`stages/stage_1_evaluation_harness.md`](stages/stage_1_evaluation_harness.md)
- **Status:** **Done** (2026-10-25) — harness (`code/evaluation/main.py`), validator, stub agent CLI, 8 custom cases, 26 tests. Baseline: samples 68.8% status, 0% steps (stub). Findings F1-1…F1-4 carried forward (stage doc §7.5).

### Stage 2 — Request understanding
- FR-2.1 Classify whether `request_text` authorizes deletion, in any language.
- FR-2.2 Access, correction, export, marketing opt-out and other non-deletion intents → `NOT_APPLICABLE`, `[]`.
- **Carry-in notes:** the 518 eval requests use only 375 distinct texts; 62 are non-English (Portuguese, Spanish, French, Japanese, Korean); only about 5 look like non-deletion requests (invoice copy, phone update, export, login reset, email change). Cache by text, not by case, and batch calls.
- **Stage doc:** [`stages/stage_2_request_understanding.md`](stages/stage_2_request_understanding.md)
- **Status:** **Done** (2026-10-25) — LLM classifier (Haiku via `claude -p`, JSON schema, batches of 25), shipped cache, usage tracking, intent suite. Intent 402/402 after two general prompt fixes; 10 eval cases → `NOT_APPLICABLE`; reruns byte-identical with 0 calls, also offline.

### Stage 3 — Identity resolution
- FR-3.1 Map the request email (current **or historical**) to a `user_id`.
- FR-3.2 Collect all current and historical emails, phones, names and email hashes from `user_identities.csv` + `user_audit_log.csv`.
- FR-3.3 Respect time: identifiers are valid relative to `audit_at`.
- FR-3.4 Avoid decoys (similar names/emails belonging to other users).
- **Status:** Not started.

### Stage 4 — Evidence ingestion & search
- FR-4.1 Parse every evidence format into a common record model: SQL (via SQLite), JSON, logs, text, PDFs, images.
- FR-4.2 Link records to the subject via identifiers, hashes, `customer_reference`/`user_id`, resource IDs and other grounded links — never via filename or manifest alone.
- FR-4.3 Extract facts from images/PDFs once and cache them.
- FR-4.4 Exclude evidence captured after `audit_at`.
- **Status:** Not started.

#### 4A — Extraction bake-off: Docling vs Claude vision (run at the start of Stage 4)

**Timebox:** about one hour. Images and PDFs are only 15 of 94 evidence files and Claude vision
over all of them is a one-off cached cost, so the bake-off must not hold up the pipeline.

**Why:** decide D8 with evidence instead of opinion. The screenshots' value is in *row/field
associations* (e.g. `backup_9287 → areed1433@gmail.com`, `data_flow_1121 → selector
jain.aditi@gmail.com, Continuous sync`); an extractor that reads every word but scrambles rows is
worse than useless because it links the wrong person to a backup or sync flow.

**Candidates**

| ID | Extractor | Notes |
|---|---|---|
| E1 | Docling (default pipeline: layout + TableFormer + OCR), output Markdown/JSON | Local, free, deterministic. Needs Python 3.12 venv (system Python is 3.14) |
| E2 | Docling with an alternative OCR engine (e.g. RapidOCR / Tesseract) | Only if E1 misreads text |
| E3 | Claude vision via `claude -p` (Sonnet or Haiku), prompt asks for structured JSON | Costs tokens; cached after first run |
| E0 | Plain PDF text library (e.g. `pypdf`) — PDFs only | Baseline: PDFs already have a text layer |

**Test set** (small, chosen to cover the hard layouts)

- 3 screenshots: `backup_restore_console_20260429.png` (table + detail panel + activity),
  `connector_management_console_20260807.png` (data flows + selectors + sync mode),
  plus one support/search screenshot chosen during the bake-off.
- 2 PDFs: `legal_retention_register_20260529.pdf` (pipe-delimited table rows),
  `security_retention_extract.pdf`.

**Ground truth:** we hand-write the expected facts for each test file once (resource IDs, linked
emails / user refs, statuses, dates) in `code/evaluation/extraction_truth/` — used only to score
extractors, never by the agent.

**Metrics**

| Metric | Meaning |
|---|---|
| Field recall | % of expected facts (IDs, emails, dates, statuses) found verbatim |
| Row-association accuracy | % of expected (resource_id → identifier/status) pairs kept together |
| Exactness | Emails/IDs reproduced character-exact (no OCR drift like `0`↔`O`, `l`↔`1`) |
| Determinism | Same output on two runs |
| Runtime per file / tokens per file | Cost of the extractor |

**Decision rule**

- Use **Docling for everything** if it scores ≥ 99% exactness and 100% row association on the
  screenshot set.
- Otherwise use **Docling (or E0) for PDFs + Claude vision for screenshots**, cached once.
- Any extractor output is normalised into the same evidence record model before matching (FR-4.1).

**Record results** in this section (table of scores per extractor) and summarise them in
`evaluation_report.md` as a model/tool comparison. Then mark D8 as Agreed with the winner.

| Extractor | Field recall | Row association | Exactness | Deterministic | Time / tokens per file | Verdict |
|---|---|---|---|---|---|---|
| E1 Docling | – | – | – | – | – | pending |
| E3 Claude vision | – | – | – | – | – | pending |
| E0 pypdf (PDFs) | – | – | – | – | – | pending |

### Stage 5 — State reconstruction at `audit_at`
- FR-5.1 For each subject resource, determine its true state at `audit_at` from evidence; treat `reported_result` and workflow statuses as claims.
- FR-5.2 Detect recreation (a sync/import re-creating deleted data after the delete).
- FR-5.3 Compare replicas (primary, read, regional, reporting, failover) for drift.
- FR-5.4 Detect active data flows and restorable backups.
- **Status:** Not started.

### Stage 6 — Policy engine
- FR-6.1 Map each resource to a data category and apply the matching rule and condition.
- FR-6.2 Retain required records (security audit logs in retention, legal holds, backups) and verify they remain present.
- FR-6.3 Account tombstone: keep the stable `user_id`, require removal of direct identifiers.
- FR-6.4 Decide `COMPLETE` only when every copy has the required treatment, retained records remain available, and no active sync/import/restore path exists.
- **Carry-in notes:** the resource → category mapping (FR-6.1) is the core of the agent and the likeliest place for a hardcoding violation; it must use what Stage 0 finds about category-bearing fields.
- **Status:** Not started.

### Stage 7 — Step builder & output writer
- FR-7.1 `INCOMPLETE`: findings (cited) → remediation → verification (empty evidence).
- FR-7.2 `COMPLETE`: verification steps only, each citing proving evidence.
- FR-7.3 Ordering is one strict sort: phase, operation order (§5), `system_id`, `resource_id` (D10). This already places disable/block before record changes; no separate dependency ordering.
- FR-7.4 Verification covers every remediated record/process and every retained record.
- FR-7.5 Deterministic ordering and JSON serialization; write `output.csv` at repo root.
- **Carry-in notes** (observed in all 32 samples):
  - Each finding has exactly one remediation and one verification (41 findings, 41 remediations):

    | Finding | Remediation | Verification |
    |---|---|---|
    | `REPORT_REMAINING_RECORD` | `DELETE_RECORD` | `VERIFY_RECORD_ABSENT` |
    | `REPORT_EXPOSED_PII` | `REDACT_RECORD` / `ANONYMIZE_RECORD` (by rule) | `VERIFY_RECORD_REDACTED` / `VERIFY_RECORD_ANONYMIZED` |
    | `REPORT_ACTIVE_DATA_FLOW` | `DISABLE_DATA_FLOW` | `VERIFY_DATA_FLOW_DISABLED` |
    | `REPORT_RESTORE_RISK` | `BLOCK_RESTORE` | `VERIFY_RESTORE_BLOCKED` |

  - Records retained by policy appear **only** as `VERIFY_RECORD_PRESENT` (24 in the samples), with no finding or remediation.
  - Already-compliant resources in an INCOMPLETE case still get a verification step (77 verifications vs. 41 remediations) — confirm the exact rule at kickoff.
- **Status:** Not started.

### Stage 8 — Iterate, full run, reports, package
- FR-8.1 Iterate on failures until sample scores plateau; record each failure and fix.
- FR-8.2 Full 518-case run with token/cost tracking.
- FR-8.3 Write `code/evaluation/evaluation_report.md` and `code/evaluation/usage_report.md`.
- FR-8.4 Replace the **root** `README.md` with our setup + run instructions (the official zip command packs the root `README.md` and `code/`, not `code/README.md`), package `code.zip`, final checklist.
- FR-8.5 Submission is an upload of `code.zip`, `output.csv` and `log.txt` (chat_transcript) on the challenge page; the git remote is the organizers' repo, so commits stay local and are never pushed.
- **Status:** Not started.

## 8. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | Runnable from the terminal with one command; clear setup in `README.md` |
| NFR-2 | Deterministic where possible (ordering, JSON serialization, cached AI outputs). `claude -p` appears to expose no temperature flag (to verify), so LLM determinism comes from caching every result |
| NFR-3 | No hardcoded case IDs, labels, file-specific answers or case-family shortcuts; policy read from CSV |
| NFR-4 | Secrets only from environment variables / uncommitted `.env`; none in code, logs or `log.txt` |
| NFR-5 | Token-efficient: AI only where understanding is required; cache and batch calls |
| NFR-6 | Prompts kept in source or Markdown files (visible to the code judge) |
| NFR-7 | Every turn logged to root `log.txt` per `AGENTS.md` §5 |

## 9. Proposed Architecture (to be confirmed)

Hybrid pipeline: deterministic code for investigation and output; AI only where understanding is
needed.

```
dataset/ ──► Loaders ──► Identity resolver ──► Evidence index ──► State @ audit_at
                │                                   ▲                   │
                │            AI (cached): images/PDFs                   ▼
                └──► AI: request intent ──────────────────────► Policy engine
                                                                        │
                                                                        ▼
                                                   Step builder ──► output.csv
evaluation/main.py ──► runs agent on samples ──► metrics + diffs
```

| Component | Approach | Why |
|---|---|---|
| Request intent | LLM (proposed) | Multilingual natural language |
| Images / PDFs | VLM or PDF text extraction, once, cached | Screenshots and documents hold facts |
| Identity, search, state, policy, steps | Plain Python | Exact, repeatable, cheap, explainable |

## 10. Open Questions

| # | Question | Options | Status |
|---|---|---|---|
| Q1 | Language | Python / TypeScript | **Decided: Python** (D4) |
| Q2 | LLM provider & model | Anthropic API key / Claude Code CLI on Pro plan / local model | **Decided: Claude via Claude Code CLI** (D6) |
| Q3 | Request intent | LLM / keyword rules / rules with LLM fallback | **Decided: LLM, cached** (D7) |
| Q4 | Images & PDFs | Docling (local OCR + layout) / Claude vision / plain PDF text library | **Proposed: Docling for PDFs + screenshots; Claude vision as fallback — confirm with a bake-off on 2–3 screenshots** (D8, revised) |
| Q5 | Fully agentic vs hybrid pipeline | Hybrid / fully agentic | **Decided: Hybrid** (D5) |
| Q6 | Model tier per task | Haiku for intent, Sonnet for image extraction, … | **Intent: Haiku** (`claude-haiku-5-5`, 402/402, D12); image extraction open — Stage 4A |
| Q7 | How can a grader without a Claude Code login re-run the agent? | Ship the LLM cache in `code.zip` / offline fallback backend / both | **Decided: ship the cache** (keyed by prompt version + model + text); verified offline run (D12) |
| Q8 | Which `evidence_id` to cite when several items prove a step | Determined from sample patterns in Stage 0 | **Answered (Stage 0, C-SP-4):** per step, the file captured ≤ `audit_at` that shows that resource's state; activity rows are not cited |
| Q9 | How to link cleaned records that carry no identifier (OQ-1: 16 of 111 sample resources) | Deletion-worker window + result matching `reported_status` (29/32) / exclusion of other people's resources / accept misses | Open — Stage 3–4 |
| Q10 | How to treat `LINK_RESOURCE_IDENTITY` activity (data-catalog claims linking a resource to a person) when evidence disagrees, e.g. `marketing_001` (F1-1) | Trust evidence identifiers only / accept the link when evidence does not contradict it | Open — Stage 3–4 |

## 11. Decision Log

| # | Date | Decision | Reason | Decided by |
|---|---|---|---|---|
| D1 | 2026-10-24 | No model training and no RAG | Samples are an answer key; evidence is small and structured | Agreed |
| D2 | 2026-10-24 | Build stage by stage, evaluate after each stage | Measurable progress; feeds `evaluation_report.md` | Agreed |
| D3 | 2026-10-24 | Document everything in this PRD | Shared plan; source for reports and interview | Agreed |
| D4 | 2026-10-24 | Language: Python | Built-in `sqlite3`/`csv`/`json`, good PDF libraries | Agreed |
| D5 | 2026-10-24 | Hybrid pipeline (code investigates, AI interprets) | Accuracy, determinism, cost, explainability | Agreed |
| D6 | 2026-10-24 | LLM backend: Claude Code CLI in headless mode (`claude -p`), authenticated by the user's Claude Pro plan; no API key. Pluggable backend interface so an `ANTHROPIC_API_KEY` backend can be added later | No API key available; tested working. Minimal flags cut per-call overhead from ~43k to ~0.6k tokens | Agreed |
| D7 | 2026-10-24 | Request intent via LLM, results cached per request | Multilingual natural language | Agreed |
| D8 | 2026-10-24 | ~~PDFs via text library; screenshots via Claude vision~~ → **Revised (user suggestion): Docling for PDFs and screenshots, Claude vision only if Docling misreads; decided by the Stage 4A bake-off.** Extract once and cache | Inspection: PDFs have a real text layer; screenshots are clean admin-console UIs whose facts are all text (tables + detail panel, no colour-only states). Docling is local, free and deterministic; risk is losing row/column links in UI tables. Stage 0: some facts exist **only** in PDFs/PNGs (`support_001`, `marketing_001`), so extraction is required, not optional | Pending bake-off |
| D9 | 2026-10-24 | PRD stays big picture; each stage starts with a deep-dive design doc in `code/docs/stages/` (template in §7), written before coding and closed with results | Detail is decided when we know most; keeps the PRD readable | Agreed |
| D11 | 2026-10-25 | Evaluation harness as designed in Stage 1 (P1–P5): own metric formulas, agent run via CLI, 8 custom cases, validator shared with the agent (placed in the agent package), committed `run_history.md` | Measurable, reproducible progress; visible to the code judge | Agreed |
| D12 | 2026-10-25 | Stage 2 as designed (P1–P6): LLM-only intent, Haiku, batches of 25 with id checks, committed cache answering Q7, per-call usage log, hand-labelled intent suite | 402/402 intent accuracy; byte-identical offline reruns; $0.025 per cold run | Agreed |
| D10 | 2026-10-24 | Step order is one strict sort (phase, operation order, `system_id`, `resource_id`); FR-7.3's separate dependency ordering dropped | Verified: all 32 sample outputs follow this sort exactly | Agreed |

### 11.1 LLM backend notes (D6)

Verified on 2026-10-24 with Claude Code 2.1.310:

```bash
claude -p "<prompt>" --model haiku --output-format json --max-turns 1 \
  --tools "" --strict-mcp-config --setting-sources "" \
  --disable-slash-commands --no-session-persistence \
  --system-prompt "<task system prompt>"
```

- Returns JSON with `result`, `total_cost_usd` and per-model `modelUsage`
  (input/output/cache tokens, list-price cost) → feeds `usage_report.md` directly.
- Without the minimal flags each call carries ~43k tokens of Claude Code context (tools, plugins,
  CLAUDE.md); with them ~0.6k. The flags are mandatory.
- Constraints: Pro plan has usage limits → batch several requests per call and cache every result
  on disk so re-runs cost nothing. Anyone re-running the code needs Claude Code installed and
  logged in (documented in `README.md`).

## 12. Risks

| Risk | Mitigation |
|---|---|
| Hidden data conventions misunderstood | Stage 0 manual trace before building |
| Overfitting to 32 samples / hardcoding | Generic logic only; custom eval cases; code review for case/file literals |
| Evidence after `audit_at` leaks into answers | Central time filter on every evidence item |
| Wrong step order loses sequence score | Single sort function implementing §5 ordering + unit tests |
| AI non-determinism or cost | Temperature 0, caching, AI only where needed |
| Decoy records matched to the wrong user | Match on multiple identifiers + `user_id` links |

## 13. Deliverables

| Item | Location |
|---|---|
| Agent | `code/main.py` (+ modules in `code/`) |
| Evaluation harness | `code/evaluation/main.py` |
| Evaluation report | `code/evaluation/evaluation_report.md` |
| Usage report | `code/evaluation/usage_report.md` |
| Setup / run guide | `code/README.md` |
| Predictions | `output.csv` (repo root) |
| Chat transcript | `log.txt` (repo root) |
| Code archive | `code.zip` (excludes `dataset/`, venvs, caches, nested archives) |

## 14. Change Log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-10-24 | Initial draft from problem statement, `AGENTS.md` §6 and dataset inspection |
| 0.2 | 2026-10-24 | Resolved Q1–Q5 (Python, hybrid, Claude Code CLI backend, LLM intent, PDF text + vision); D1 agreed; added D4–D8 and LLM backend notes |
| 0.3 | 2026-10-24 | D8 revised: Docling proposed for PDFs/screenshots pending bake-off vs Claude vision |
| 0.4 | 2026-10-24 | Added Stage 4A extraction bake-off plan (Docling vs Claude vision): candidates, test set, ground truth, metrics, decision rule, results table |
| 0.6 | 2026-10-25 | Stage 0 done: §7.0 Data conventions added; Q8 answered; Q9 (unlinked cleaned records) added |
| 0.7 | 2026-10-25 | Stage 1 kickoff doc written; Stage 1 status → Kickoff |
| 0.8 | 2026-10-25 | Stage 1 done (D11); Q10 added (identity-link claims) |
| 0.9 | 2026-10-25 | Stage 2 kickoff doc written |
| 0.10 | 2026-10-25 | Stage 2 done (D12); Q6 answered for intent; Q7 decided |
| 0.5 | 2026-10-24 | PRD analysis folded in: stage kickoff template (D9); carry-in notes for Stages 0, 1, 2, 6, 7; FR-7.3 replaced by strict sort (D10); step-chain table; NFR-2 corrected (no CLI temperature); Q7 reproducibility, Q8 citation rule; 4A timebox; change log reordered |
