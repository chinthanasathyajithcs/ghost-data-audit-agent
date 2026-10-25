# Stage 0 — Data discovery (manual trace)

| Field | Value |
|---|---|
| Status | **Done** — 9 traces complete; open questions OQ-1 and OQ-6 carried into Stages 3–6 (§7) |
| Dates | 2026-10-24 → 2026-10-25 |
| PRD link | `code/docs/PRD.md` §7 Stage 0; summary in PRD §7.0 "Data conventions" |
| Feeds | Stage 3 Identity · Stage 4 Evidence · Stage 5 State · Stage 6 Policy · Stage 7 Steps |

## How to read this document

§1 is the summary. §2–§3 say what we did. **§4 is the deliverable**: the data conventions, grouped
by the pipeline stage that will turn them into code. §5 lists the kinds of problem the agent
must detect, §6 the traps, §7 what is still open, §8 what this means for each later stage.
§9 keeps the per-trace evidence that every convention is based on (cited as `[T1]`, `[T2]`…).

---

## 1. Summary

The dataset is a set of **independent views of the same systems at different moments**. No single
file tells the truth about a person; the agent has to (1) gather every identifier the person has
ever had, (2) find every record that points to any of them, in eight file shapes, (3) read each
record's state as of `audit_at`, and (4) compare that with what the policy requires.

Key findings:

1. **The decision logic is a small table** (rule action × observed state → finding → fix → check) [T1]. It held in every traced case.
2. **Ghost data hides under old identifiers and in secondary copies**: old emails [T4], failover replicas [T2], search/analytics/support copies [T1], backups and live syncs [T1, T3].
3. **Claims are unreliable in both directions.** Activity results and reported statuses are wrong either way (a "SUCCESS" record still present, a "FAILED" one actually gone) [T1, T3, T8].
4. **Links between a record and a person are often indirect**: a `user_id`, an email hash, or a `trace_id` that joins two log lines [T1, T3, T8].
5. **Time matters at two levels**: the manifest's `captured_at` decides what may be *cited*; the timestamps *inside* a file decide which facts may be *used* [T3, T4].
6. **Most answers can be rebuilt from evidence**, but 16 of 111 answer resources (mostly the main account IDs) appear in no file, including PDFs and screenshots. Their only trace is the deletion worker's activity, linked by time and status (OQ-1).
7. **PDFs and screenshots are business artifacts about one subject each.** No sample answer cites one, but they hold facts found nowhere else (`support_001` only in a PDF, `marketing_001` only in a screenshot), so they matter for the 518 evaluation cases.

## 2. Goal and scope

**Goal:** learn the exact conventions the data uses to encode facts by tracing sample cases against
their known answers. Conventions are exact rules ("`status_code` 404 = record absent"), not
probabilities. Kinds of problem are things to **detect from evidence**, never case-family shortcuts (SC-4).

**Out of scope:** request-intent classification (Stage 2), extraction tooling for PDFs/PNGs
(Stage 4A), any code.

## 3. Method and coverage

### 3.1 Traces

| Trace | Cases | Pattern | Evidence used |
|---|---|---|---|
| T1 | case_11 | Downstream failures + active sync | evidence_03 (txt handover) |
| T2 | case_01 (COMPLETE) vs case_05 | Same file, opposite answers; replica drift | evidence_54 (SQL failover replica) |
| T3 | case_09, case_14 | Backups / restore risk | evidence_93 (SQL inventory), evidence_06 (JSON-line log), evidence_03 |
| T4 | case_10, case_29 | Request uses an old email | evidence_61 (logfmt log), evidence_92 (JSON export), evidence_02 (JSON bundle) |
| T5 | case_31 (COMPLETE) vs case_32 | Account tombstones | evidence_51 (JSON bundle) |
| T6 | case_07, case_08 | Support-attachment PDF; user export | evidence_58 (PDF), evidence_59 (JSON collection) |
| T7 | case_26 (COMPLETE), case_15 | All-verified case with flows/backups; service log | evidence_92, evidence_01 (logfmt log) |
| T8 | case_03, case_04, case_12 | Readback log; a case citing two files; hash link | evidence_94, evidence_54 + evidence_56, evidence_01 |
| T9 | — | Retention/legal documents and screenshots | evidence_55, evidence_27 (PDFs), legal-hold SQL/JSON, all 11 PNGs |

Plus whole-sample scans: ordering (32/32 follow the strict sort), resource coverage in text
evidence, and two linking heuristics tested against all 32 answers (§4.3).

### 3.2 Coverage

| Area | Covered | Not covered by samples (needs custom eval cases, Stage 1) |
|---|---|---|
| Formats | txt, 3 SQL shapes, 3 JSON shapes, 3 log shapes, PDF, PNG | — |
| Rules seen in answers | rule_01, 03, 05, 06, 07, 09, 12, 14, 15, plus "contact" records → DELETE | rule_04 cache (in 12 evidence files), rule_08 telemetry (2 files), rule_10 marketing (screenshot only), rule_11 email delivery log, rule_13 legal hold (7 files) |
| Statuses | COMPLETE, INCOMPLETE | **NOT_APPLICABLE (0 of 32 samples)** |

---

## 4. Data conventions (the deliverable)

Each convention has an ID used by later stages. **Basis** cites the traces in §9.

### 4.1 Identity (→ Stage 3)

| ID | Convention | Basis |
|---|---|---|
| C-ID-1 | A person's identifiers = current snapshot (`user_identities.csv`) **plus every old value** in their full `user_audit_log.csv` history (emails, phones, email hashes). History is a chain: one user had three emails and three hashes. | T4 |
| C-ID-2 | The request `email` may be any old value; resolve it to a `user_id` through the history, not only the snapshot. | T4 (case_10, case_29, case_30) |
| C-ID-3 | Only identifiers valid **at or before `audit_at`** count (a change made later cannot explain earlier evidence). | Contract §6.2; not contradicted |
| C-ID-4 | Match **exact identifiers only**: emails case-insensitively (evidence uses `CHOI.JIHOON94@GMAIL.COM`), IDs as whole tokens. Never names, never substrings. | T1, T2, T4 |

### 4.2 Evidence formats (→ Stage 4)

Every format must be normalised into one record model:
`(system_id, resource_id, category, state, identifiers[], observed_at, source evidence_id)`.

| Format | Where the fields are | Basis |
|---|---|---|
| **txt handover** | One line per record: `time \| system_id \| resource_id \| CATEGORY \| STATE \| identifier`. Category is an explicit label. States: `FOUND`, `NOT_FOUND`, `IDENTIFIABLE`, `ANONYMIZED`, `REDACTED`, `ACTIVE`, `BLOCKED`, `DISABLED`. | T1 |
| **SQL replica pair** | Same table twice (`customer_profiles_primary`, `customer_profiles_failover_replica`); header comment gives `Captured at` and topology. Absent from one copy, present in another = drift. | T2 |
| **SQL inventory** | One table per category (`customer_profiles`, `customer_search_documents`, `customer_analytics_profiles`, `support_records`, `customer_exports`, `connector_subscriptions`, `backup_restore_entries`, `security_audit_records`) + `snapshot_scope` (systems covered, capture time). Person = email column **or** `customer_reference`/`subject_reference`. | T3 |
| **SQL generic** | Tables `customer_data_primary` / `customer_data_reporting_replica` with `(resource_id, system, collection, JSON payload, …)`; used e.g. for legal holds. | T9 |
| **JSON service export** | `service_exports.<system_id>.<collection>[]`, each item with `resource_id`, `observed_at` and state fields. | T4, T7 |
| **JSON snapshot bundle** | `snapshots[]`, **each with its own `captured_at`**, `data_store` (= system_id), `collection`, `records[]`. One bundle mixes times before and after `audit_at`. An empty `records[]` for a store is proof of absence. | T4, T5 |
| **JSON single collection** | Top-level `captured_at`, `collection`, `records[]` (export jobs, analytics reports). | T6, T8 |
| **JSON-line logs** | `<time> {json}`; subject on one line (`lookup_key`, `subject_ref`, `subject_key`), resource + result on another, **joined by `trace_id`**. | T3 |
| **logfmt logs** | `key=value` pairs, same `trace_id` join; keys include `lookup_key`, `match_key`, `subject_key`, `correlation_key` (can be an **email hash**). | T4, T7, T8 |
| **Readback trace log** | logfmt, but the start line carries both `resource_id` and `lookup_key`; completion line carries state. | T8 |
| **PDF** | Real text layer; key/value table rows. Holds unique facts (e.g. `support_001` appears only in a PDF). | T6, T9 |
| **PNG screenshot** | One subject per screen (account, ticket, marketing profile, reference registry, audit explorer, storage browser). Some hold facts found nowhere else (`marketing_001` exists only in a screenshot). Several are unrelated noise. | T9 |

### 4.3 Linking records to the subject (→ Stages 3–4)

| ID | Convention | Basis |
|---|---|---|
| C-LK-1 | Direct link: the record carries one of the subject's identifiers (email, old email, phone, hash, `user_id` as `customer_reference`/`subject_reference`/`user_id`). Any one match is enough; the same record can show different identifiers in different files. | T1, T4 |
| C-LK-2 | Log link: join lines by `trace_id`; the subject is on the start line, the resource and result on a later line. | T3, T4, T7 |
| C-LK-3 | Hash link: `correlation_key` / `email_hash` matches any current or historical hash. | T8 (case_12) |
| C-LK-4 | **Already-cleaned records carry no identifier** (deleted accounts, anonymized analytics). Their only link is the deletion worker's activity for this request. Every non-audit resource in 30 of 32 answers has a `deletion_worker` row within ±2 h of `reported_at`. | Scan, T7 |
| C-LK-5 | Time windows alone are **not** a link: windows contain other people's runs (up to 17 extra rows). Rejected heuristic: "nearest account delete to `reported_at`" = 14/32. | T3, scan |
| H-LK-6 *(hypothesis)* | Within the ±2 h window, the **primary account delete whose result matches `reported_status`** (COMPLETE→SUCCESS, PARTIALLY_COMPLETE→PARTIAL, NOT_STARTED→FAILED) is the subject's account: holds in 29/32 samples, leaving 1–4 candidates (1 in 13 cases). Excluding accounts already linked to other people (C-LK-1) should narrow it further — untested. | Scan → OQ-1 |

### 4.4 Time (→ Stage 5)

| ID | Convention | Basis |
|---|---|---|
| C-TM-1 | **Citation:** cite only files whose manifest `captured_at` ≤ `audit_at`. | T3, T4 (all citations checked) |
| C-TM-2 | **Use:** a fact may be used if its *own* timestamp (log line time, bundle snapshot `captured_at`, item `observed_at`) ≤ `audit_at`, even when the file was exported later. Inner snapshots after `audit_at` are ignored. | T3, T4 (supported, OQ-5 closed as working rule) |
| C-TM-3 | When several observations of one resource exist, the latest one ≤ `audit_at` wins. | Contract §6.5; consistent with T1–T8 |

### 4.5 State and claims (→ Stage 5)

| ID | Convention | Basis |
|---|---|---|
| C-ST-1 | `system_activity.csv` results and `reported_status` are **claims**. They are leads (which resources were processed), never proof of state. | T1, T3, T4 |
| C-ST-2 | `SUCCESS` describes the operation, not the outcome: `CHECK_DATA_FLOW … SUCCESS` can mean "confirmed still enabled"; `CHECK_RESTORE_ACCESS … SUCCESS` can mean "still restorable". | T1, T3 |
| C-ST-3 | State vocabulary across formats: **present** = `FOUND`, row exists, `status_code 200`, `rows=1`, `hits.total>0`, `download_available=true`; **absent** = `NOT_FOUND`, no row, empty `records[]`, `404`, `rows=0`; **identifiable** = identifier fields non-null / `IDENTIFIABLE`; **redacted** = identifiers null but `customer_reference` kept / `REDACTED`; **anonymized** = all identifiers null / `ANONYMIZED`; **flow active** = `ACTIVE`, `enabled=1/true`, `scheduler_registered=true`; **restore open** = `ACTIVE`, `restore_allowed=1/true`, `eligible=true, deletion_block=false`. | T1–T8 |
| C-ST-4 | Replica drift: compare every copy of a table (primary, failover, read, reporting) at its own capture time; a record present in **any** copy is still present. | T2 |

### 4.6 Policy and categories (→ Stage 6)

| ID | Convention | Basis |
|---|---|---|
| C-PL-1 | Category comes from the evidence: explicit label (txt), table name (SQL), `collection`/`data_store` (JSON), `service` + event (logs), document content (PDF: "attachment properties, uploader customer" → SUPPORT_ATTACHMENT). | T1–T6 |
| C-PL-2 | The request only starts the process; **policy decides each record's treatment and always wins** over the request text. | T1, contract §6.5 |
| C-PL-3 | Backups are RETAINED (rule_14); the issue is restore access, never the record. | T3 |
| C-PL-4 | Security audit records are RETAINED; `retention_until` (2031–2034 in all text evidence; Aug 2027 in one PDF) proves rule_12's condition. No expired retention exists in the data. | T3, T7, T9 |
| C-PL-5 | Tombstone (`identity_service`, `deleted_customer_references`): keep `subject_reference`; compliant when name, email, phone and hash are null; otherwise `REPORT_EXPOSED_PII` → REDACT. | T5 |
| C-PL-6 | Support conversations (ticket, `message_excerpt`/`message_text`) → REDACT (rule_05); customer-uploaded files → DELETE (rule_06). | T1, T6 |
| H-PL-7 *(hypothesis)* | "Contact" records (`legacy_contact_index` in support, `contact_lookup` with `email_opt_in` in analytics) → DELETE as remaining records, not REDACT/ANONYMIZE. Seen twice (case_10, case_12). | T4, T8 → OQ-6 |

### 4.7 Steps and citations (→ Stage 7)

| ID | Convention | Basis |
|---|---|---|
| C-SP-1 | Decision table: DELETE+present → `REPORT_REMAINING_RECORD`/`DELETE_RECORD`/`VERIFY_RECORD_ABSENT`; REDACT+identifiable → `REPORT_EXPOSED_PII`/`REDACT_RECORD`/`VERIFY_RECORD_REDACTED`; ANONYMIZE+identifiable → `REPORT_EXPOSED_PII`/`ANONYMIZE_RECORD`/`VERIFY_RECORD_ANONYMIZED`; flow active → `REPORT_ACTIVE_DATA_FLOW`/`DISABLE_DATA_FLOW`/`VERIFY_DATA_FLOW_DISABLED`; restore open → `REPORT_RESTORE_RISK`/`BLOCK_RESTORE`/`VERIFY_RESTORE_BLOCKED`; retained → `VERIFY_RECORD_PRESENT` only. | T1, T3, T5 |
| C-SP-2 | Already-compliant resources get the verification step only. Retained records appear only when evidence links one to the subject. | T1, T2 |
| C-SP-3 | INCOMPLETE: findings cite evidence; every remediation and every verification has `evidence_id=""`. COMPLETE: verification steps only, each citing evidence. | All 32 |
| C-SP-4 | Citation is **per step**: the file (≤ `audit_at`) that shows that resource's state. Most cases cite one file because one snapshot covers all their systems; case_04 cites two. Absence is proven by a snapshot that covers the system and has no record for the subject. Activity rows are never cited in samples. | T2, T5, T8 |
| C-SP-5 | Order is the strict sort (phase, operation order, `system_id`, `resource_id`) — 32/32 (PRD D10). | Scan |

---

## 5. Kinds of problem the agent must detect

Detected from evidence per case — never assumed from a pattern (SC-4).

| Problem | Seen in | Detected by |
|---|---|---|
| Downstream copies left behind (search, support, analytics, export) | case_11, 13, 19, 22, 23, 29, 30 | C-ST-3 + C-SP-1 |
| Primary account still present | case_16, 24 | C-ST-3 |
| Replica drift (deleted in primary, alive in failover) | case_05 | C-ST-4 |
| Active sync that can recreate data | case_11, 15, 18, 20, 29, 30 | C-ST-3 flow active |
| Restorable backup | case_09, 14, 17 | C-ST-3 restore open |
| Data under an old email | case_10, 29, 30 | C-ID-1, C-LK-1 |
| Tombstone still exposing identifiers | case_32 | C-PL-5 |
| Leftover attachment or export file | case_07, 08, 13, 23 | C-PL-6, C-ST-3 |
| Workflow reported success before downstream results returned | case_11 (reported 12:00, failures 12:55–13:33) | C-ST-1 |

## 6. Traps

| Trap | Example | Guard |
|---|---|---|
| Look-alike people | Six "Novak" users; `karim.elmasri` next to `amina.elmasri`; `nadia.popescu` vs Nadia Ionescu/Petrescu | C-ID-4 |
| Substring IDs | `support_8642` matches a search for `support_864` | C-ID-4 |
| Interleaved runs | Kojo's deletion run (case_09) is interleaved with user_62's | C-LK-5 |
| Claims in both directions | `account_3960` delete "FAILED" but absent; `search_052` assumed done but present | C-ST-1 |
| Later evidence | evidence_06 (captured 09-18) and evidence_02 (09-17) contain facts for audits on 09-15/09-16 | C-TM-1, C-TM-2 |
| Noise documents | Customer statement PDF, object-storage browser, unrelated screenshots | Link only by C-LK rules |

## 7. Open questions carried forward

| # | Question | Current answer | Carried to |
|---|---|---|---|
| OQ-1 | How is a resource linked when no text evidence contains it? 16 of 111 answer resources: 14 primary `account_*` IDs (cases 01, 02, 04, 07, 08, 10, 18, 20, 22, 23, 29, 30, 31, 32) and 2 audit records (case_18, case_20). `account_004` has no activity row at all. | Best lead H-LK-6 (29/32). All PDFs and PNGs checked: none contains these IDs, so the deletion-worker activity is their only source. Accept imperfect recall on verification-only steps if unresolved. | Stage 3–4 |
| OQ-2 | Which `evidence_id` to cite (PRD Q8)? | **Answered:** C-SP-4 | Stage 7 |
| OQ-3 | What if a rule's condition fails (no shared context; retention expired)? | Never occurs in the data (C-PL-4); treat condition as met when its proof is present | Stage 6 |
| OQ-4 | Where is retention proven? | **Answered:** C-PL-4 | Stage 6 |
| OQ-5 | Which time counts? | **Answered as working rule:** C-TM-1, C-TM-2 | Stage 5 |
| OQ-6 | Category of records without a label | H-PL-7 for "contact" records; confirm against the evaluation set in Stage 6 | Stage 6 |

## 8. What this means for later stages

| Stage | Must implement | Conventions |
|---|---|---|
| 1 Evaluation | Custom cases for NOT_APPLICABLE, legal hold, cache, telemetry, marketing, email-delivery log (none in samples); report OQ-1 misses separately | §3.2 |
| 2 Intent | No sample coverage — rely on custom cases | §3.2 |
| 3 Identity | Full identifier history; exact matching; time-valid identifiers | C-ID-1…4 |
| 4 Evidence | 12 format parsers into one record model; `trace_id` joins; PDF text; PNG extraction **is required** (unique facts exist only in images, which strengthens D8) | §4.2, C-LK-1…3 |
| 5 State | Inner-timestamp filtering; latest observation wins; replica comparison; claim vs proof | C-TM, C-ST |
| 6 Policy | Category from evidence; retained categories; tombstone rule; contact-record hypothesis | C-PL |
| 7 Steps | Decision table, per-step citation, strict sort | C-SP |

## 9. Trace evidence

### T1 — case_11 (evidence_03, text handover)
Request `novak.tomasz@icloud.com` (user_32), reported COMPLETE, answer INCOMPLETE, 14 steps. The
handover lists 41 records for many people. Tomasz's: `account_4248 NOT_FOUND` (verify only),
`analytics_2034 IDENTIFIABLE` (→ anonymize), `support_864 SUPPORT_MESSAGE IDENTIFIABLE`
(→ redact), `search_052 FOUND` (→ delete), `data_flow_9522 ACTIVE` (→ disable), and
`audit_record_9394 … user_32` (no email; linked through `user_identities.csv`; retained). Activity
rows show the three downstream actions FAILED and the flow check "remains enabled"; findings cite
the handover (captured exactly at `audit_at`), not the activity rows. The workflow reported
COMPLETE at 12:00, after the account delete (11:04) and before the failures (12:55–13:33).

### T2 — case_01 vs case_05 (evidence_54, SQL failover replica)
Both cite the same file. Leila's `account_005` is missing from `customer_profiles_primary` but
present in `customer_profiles_failover_replica` → drift → finding (activity claimed both the delete
and the replica sync succeeded). Amina has no row in either table → COMPLETE, citing the same file.
The file contains no category label, and `account_001` appears in no text evidence (OQ-1).

### T3 — case_09, case_14: backups
Same 5-step shape: restore risk → block restore → verify account absent, audit record present,
restore blocked. evidence_93 (SQL inventory) shows `backup_4978 restore_allowed=1` for Kojo's email.
`account_3960` and `audit_record_4902` are linked only through evidence_06's `trace_id` joins
(`lookup_key=k.appiah88@gmail.com` → `account_3960 rows=0 404`; `subject_ref=user_61` →
`audit_record_4902 rows=1`). evidence_06 was captured after `audit_at`, but its lines precede it
(→ C-TM-2). Activity said the account delete FAILED; the log shows it absent.

### T4 — case_10, case_29: old emails
Nadia's chain: `nadia.ionescu` → `nadia.petrescu` → `n.petrescu`. Her `support_002` was found by
a `legacy_contact_index` lookup on the oldest email (logfmt, `trace_id` join) → DELETE. All four of
Noah's leftover records in evidence_92 carry his old email. `audit_record_3954` (user_29) appears
only in evidence_02's snapshot captured at `audit_at`; the bundle also has a later snapshot.
Findings cite evidence_92, not evidence_02.

### T5 — case_31 vs case_32: tombstones
evidence_51 (`identity_service / deleted_customer_references`): `tombstone_440` (user_541) has all
identifiers null → `VERIFY_RECORD_REDACTED`, COMPLETE; `tombstone_9178` (user_542) still shows
name, email, phone and hash → `REPORT_EXPOSED_PII` → REDACT. The account snapshot in the same
bundle has empty `records[]`, which proves absence; the account IDs themselves come only from
activity (OQ-1). Both cases were reported at the same moment, so their runs share a window.

### T6 — case_07, case_08: attachment PDF and export
evidence_58 is a customer-uploaded delivery-correction PDF (`support_001`, Priya's email and phone,
"uploader customer") → SUPPORT_ATTACHMENT → DELETE. evidence_59 lists `export_001` for Gabriel
with `download_available=true` → remaining record → DELETE.

### T7 — case_26 (COMPLETE), case_15
evidence_92 proves each of six requirements: account 404, audit record present, support ticket
with `customer_reference` but null contact fields (redacted), analytics with all identifiers null
(anonymized; linked only by activity), connector `enabled=false`, backup `restore_allowed=false`.
case_15: evidence_01 logfmt shows `data_flow_9846 enabled=true scheduler_registered=true` for
Lucia's `subject_key` → active flow finding.

### T8 — case_03, case_04, case_12
evidence_94 readback log carries `resource_id` and `lookup_key` on the start line (French request,
COMPLETE). case_04 cites evidence_54 for the account and evidence_56 for the anonymized analytics
record → per-step citation. case_12's `analytics_9914` is a `contact_lookup` with `email_opt_in`,
linked by `correlation_key` = email hash, and is DELETED rather than anonymized (H-PL-7).

### T9 — retention, legal and screenshots
`security_retention_extract.pdf`: a signed journal extract for `audit_record_003` / user_03 with
"retain until 25 Aug 2027". `legal_retention_register_20260529.pdf`: disputed orders for six users,
retained to 2033, with no resource IDs; no sample answer uses it. Legal holds appear as
`legal_hold_*` records in SQL-generic and JSON bundles from early 2026 (eval cases only). Screenshots
viewed: security audit explorer (user_03), account admin console (user_11 / account_5762),
customer reference registry (user_17), helpline ticket (`support_1034`), marketing profile
(`marketing_001`), object storage browser (no personal IDs), search index inspector (`search_428`
for user_13, with decoy `g.silva76.jr@gmail.com` next to `g.silva76@gmail.com`), analytics profile
view (`analytics_7438`, user_20), customer export console (`export_1258`–`export_1261`, owner emails
and Ready/Collecting/Packaging statuses); the backup and connector consoles were viewed in the
previous session. **All 11 screenshots and all 4 PDFs have now been read.** None of them contains
any of the 16 resource IDs in OQ-1, and no sample answer cites an image.

## 10. Acceptance check status

| Check (from the plan) | Status |
|---|---|
| Every question Q-A…Q-G answered by ≥2 cases or listed open | Done — open: OQ-1, OQ-6 (§7) |
| Every format has a field map | Done for text formats and PDFs; all 11 PNGs read (one subject per screen, header IDs + tables + detail panel); exact extraction is Stage 4A |
| Each traced case's answer can be rebuilt from the conventions | Done, except resource IDs covered by OQ-1 |
| PRD "Data conventions" section | Done (PRD §7.0) |
