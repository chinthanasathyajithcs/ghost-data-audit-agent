# Stage 4 — Evidence ingestion and linking

| Field | Value |
|---|---|
| Status | **Agreed** — proposals P1–P7 accepted 2026-10-25; building |
| Dates | 2026-10-25 → |
| PRD link | `code/docs/PRD.md` §7 Stage 4 (FR-4.x) and §4A bake-off; open questions Q9, Q10; decision D8 |
| Depends on | Stage 0 (format field maps §4.2, linking C-LK-1…6), Stage 2 (LLM backend, cache, usage), Stage 3 (`IdentityIndex`, owner lookup) |
| Feeds | Stage 5 (state at `audit_at`), Stage 7 (which file to cite) |

## How to read this document

§1 is the goal, §2 the questions, §3 the inputs. **§4 is the design**: what the evidence looks like
(measured), the record model, the readers, system IDs, linking, the two open questions, image and PDF
extraction, the case file and how we measure it. §5 is how we know it works, §6 what it leaves out,
§7 the results.

---

## 1. Goal

Read all 94 evidence files, in every format, into **one record model**, then build a **case file**
for each deletion request: every resource that belongs to the subject, each with the observations
(what a file said about it, and when) that later stages need. Records that belong to other people
are rejected, and nothing is linked on a guess.

Stage 4 gathers; it does not judge. Whether a record is present, gone or exposed at `audit_at` is
Stage 5. What the policy requires is Stage 6.

## 2. Questions to answer

| # | Question | Answer in |
|---|---|---|
| Q4-1 | Can a few generic readers cover 94 files, or do we need one parser per family? | §4.1, §4.3 |
| Q4-2 | What does one "observation" contain, and how do we record that a file proves **absence**? | §4.2 |
| Q4-3 | Where does `system_id` come from when a file does not state it? | §4.4 |
| Q4-4 | How is a resource linked to the subject, and how are other people's records rejected? | §4.5 |
| Q4-5 | **Q9** — cleaned records carry no identifier. How are they linked? | §4.6 |
| Q4-6 | **Q10** — data-catalog activity links a resource to a person. When do we trust it? | §4.7 |
| Q4-7 | **D8** — Docling or Claude vision for screenshots and PDFs? | §4.8 |
| Q4-8 | How do we measure linking before any steps exist? | §4.10 |

## 3. Inputs and dependencies

| Input | Use |
|---|---|
| `evidence_files.csv` | 94 files: `file_id`, path, origin, `captured_at` |
| `dataset/evidence/` | 24 SQL, 28 JSON, 26 logs, 1 text, 4 PDF, 11 PNG |
| `system_activity.csv` | 4,011 events: the leads for Q9 and the catalog claims for Q10 (never proof of state) |
| Stage 3 `IdentityIndex` | Who owns any identifier; `owners_in_text` scans a record's text in one pass |
| Stage 2 backend, cache, usage | Reused for image and PDF extraction |

## 4. Design

### 4.1 What the evidence looks like (measured)

| Container | Files | Shapes | Where the facts are |
|---|---|---|---|
| SQL (SQLite-compatible) | 24 | **Generic pair** (16): tables like `customer_data_primary` + `customer_data_read_replica` / `_reporting_replica` / `_failover_replica` / `_replica_<region>`, columns `resource_id, origin_system, collection_name, record_json, updated_at`. **Inventory** (11): one typed table per category plus `snapshot_scope(origin_system, captured_at)`. **Typed pair** (2): `customer_profiles_primary` / `_failover_replica`, `search_documents_primary` | Header comment gives `Captured at` and topology; each row is a record; JSON column holds fields |
| JSON | 28 | **Snapshot bundle** (12): `snapshots[]` each with `captured_at`, `data_store`, `collection`, `records[]`. **Service export** (11): `service_exports.<system>.<collection>[]` with `observed_at`. **Ledger** (3): `records[]` of `{recorded_at, system, resource_id, record_type, result, subject_reference}`. **Single collection** (2): top-level `captured_at`, `collection`, `records[]` | Every object holding a `resource_id` is a record; system, collection and time come from the object or its ancestors |
| Logs | 26 | 8 line styles: logfmt, JSON-line, syslog, bracketed trace, pipe-separated stream, cloud runtime (escaped nested `message`), record-lookup lines, readback traces | Each line → time, service, `trace_id`, key-value pairs; lines sharing a `trace_id` form one event (subject on one line, resource and result on another: C-LK-2) |
| Text | 1 | Shift handover: `time \| system_id \| resource_id \| CATEGORY \| STATE \| identifier` | One line per record |
| PDF | 4 | Real text layer; key-value tables | Extraction (§4.8) |
| PNG | 11 | Admin-console screenshots: header IDs, tables, detail panel | Extraction (§4.8) |

**Answer to Q4-1:** five readers (SQL, JSON walker, log normaliser, text handover, extracted
documents) cover all 94 files. Per-family code is limited to small field maps, not separate parsers.

Other measured facts that shape the design:

- **843 of 850 users** are named somewhere in the text evidence; most files mix many people.
- Decoys exist inside files: e.g. `account_8741` for "Karim El-Masri" / `user_8741`, a user who is
  not in the identity data, next to the real Amina El-Masri.
- One log (`evidence_53`, 300 lines) is bulk noise: `profile_service` with 5-digit account IDs.
- The 12 `LINK_RESOURCE_IDENTITY` activity rows (data catalog) name exactly the subjects of the
  screenshots and PDFs (`account_5762` → user_11, `search_428` → user_13, `object_19` → Priya
  Raman "belongs only to" her, …). 11 agree with what the image shows; `marketing_001` does not.

### 4.2 Record model

```text
Observation                                   # one thing one file says about one resource
  evidence_id      evidence_54                # manifest file_id (what Stage 7 cites)
  captured_at      2026-09-02T23:00Z          # manifest time: decides whether it may be cited
  observed_at      2026-09-02T22:45Z          # the record's own time (row updated_at, observed_at,
                                              # log line, bundle snapshot): decides whether it may be used
  system_id        account_service
  resource_id      account_005
  location         customer_profiles_failover_replica   # table / replica / collection / log trace
  label            customer_profiles                    # collection, table or record_type as written
  fields           {...}                                 # raw values, nothing interpreted yet
  owners           {user_05: {email, user_id}}           # from IdentityIndex.owners_in_text

Coverage                                      # what a file looked at, so silence can mean absence
  evidence_id, captured_at, system_id or label, location
```

`Coverage` comes from a snapshot's declared scope (`snapshot_scope`, a bundle snapshot with empty
`records[]`, a replica table). Stage 5 uses it for C-SP-4: "absence is proven by a snapshot that
covers the system and has no record for the subject". Stage 4 only records what was covered.

### 4.3 Readers

| Reader | Approach |
|---|---|
| SQL | Execute the file into an in-memory SQLite database (standard library). Each row of each table → observation; `record_json` parsed into fields; `location` = table name; header comment → topology. `snapshot_scope` and every table → coverage |
| JSON | One generic walk: every object with a `resource_id` becomes an observation, inheriting `system`/`data_store`/service key, `collection`/collection key, and the nearest `observed_at`/`recorded_at`/`captured_at` from itself or its ancestors. Search hits keep their parent's `hits.total` and query fields |
| Logs | Line normaliser for the 8 styles → `(time, service, trace_id, pairs)`, unescaping nested `message="…"`. Lines are grouped by `trace_id`; each resource in a trace becomes one observation whose fields merge the trace's lines (so `lookup_key=` on the start line links the `resource_id` on the completion line). Lines without a trace stand alone |
| Text handover | Split each record line on `\|` |
| Documents | Extracted once by the 4A winner (§4.8) into the same record shape, cached |

### 4.4 Where `system_id` comes from

1. Stated in the record: `origin_system`, `system`, `data_store`, the service key in exports, the
   handover column, or the log's `service`.
2. Otherwise **learned from the data**: build a `resource-ID prefix → system_id` map from every
   observation where both appear (e.g. `account_*` → `account_service`, `audit_record_*` →
   `security_service`), by majority vote, and report any prefix with conflicting votes. Nothing is
   hard-coded: the map is rebuilt from the evidence on every run.

### 4.5 Linking resources to the subject

1. **Observation owners.** Scan each observation's fields (and, for logs, every line of its
   trace) with `IdentityIndex.owners_in_text`.
2. **Resource owners.** A resource ID names one resource, so the owners of a resource are the union
   over all its observations whose `observed_at ≤ audit_at`. A record anonymized at audit time is
   still linked if an earlier observation named the subject. This covers part of Q9 without any
   activity data.
3. **Classes.** For each case: **subject** (the subject's identifiers name it), **other** (only
   other people's identifiers name it: rejected and counted), **unlinked** (no owner at all: input
   to §4.6). A resource naming the subject *and* someone else stays linked and is flagged for review.

### 4.6 Q9 — cleaned records with no identifier

Stage 0 found that 16 of the 111 resources in the sample answers appear with no identifier (mostly
primary `account_*` IDs), and that the deletion worker's activity is their only trace. Candidate
rule, evaluated on the samples before it is adopted:

- Leads are `deletion_worker` activity rows within a window of the request's `reported_at`
  (Stage 0: ±2 h covers 30 of 32 samples).
- A lead becomes a link only if the resource is **unlinked** after §4.5. Resources owned by someone
  else are never taken (this is the "exclusion" option the Stage 3 owner index makes possible).
- When several primary-account deletes remain, prefer the one whose result matches
  `reported_status` (H-LK-6: 29/32), and record the link method as `activity` so it is visible in
  every report.

We measure this rule's precision and recall separately (§4.10). If it links wrong resources more
than it helps, it is dropped and those resources are accepted as misses (verification steps only).

### 4.7 Q10 — data-catalog link claims

`LINK_RESOURCE_IDENTITY` rows are claims like any other activity. Rule: **accept the catalog link
unless evidence about that resource names a different person**, meaning any email, phone or hash in
its observations that is not the linked person's, whether owned by another user or by no one. For
`marketing_001` the screenshot shows "Soo-jin Park, sj.park@naver.com", not Kwame Mensah, so the
link is rejected and the conflict is reported. The other 11 agree with their evidence and are
accepted. `object_19`'s "belongs only to" wording is kept as a fact for Stage 6 (rule_06 condition).

### 4.8 Stage 4A — screenshots and PDFs (decides D8)

**Feasibility test (done at kickoff).** `claude -p --model sonnet` with only the `Read` tool
allowed (limited to `dataset/evidence/images/`) and a JSON schema read
`backup_restore_console.png` in 9.7 s for $0.028 and returned all four table rows plus the detail
panel with **row associations intact** (`backup_9287` ↔ `areed1433@gmail.com`, matching the catalog
claim).

**Environment found:** Python 3.14, no pip and no PDF or OCR library installed (no pypdf, PyMuPDF,
Docling, pdftotext or tesseract), 7 GB RAM, RTX 4050 (6 GB). Any library therefore needs a project
virtual environment (`.venv/` at the repo root, outside `code/`, so it never enters `code.zip`)
and a `requirements.txt`.

Bake-off as planned in PRD §4A, with a timebox:

| Candidate | For | Notes |
|---|---|---|
| E0 `pypdf` text layer | PDFs | Small pure-Python dependency |
| E1 Docling | PDFs + PNGs | Install timeboxed to 30 minutes; Python 3.14 support and RAM are the risks. If it does not install, the result is recorded as "not viable here" |
| E3 Claude vision (Sonnet, CLI `Read` tool) | PNGs (+ PDFs if E0 loses facts) | Working now; about $0.03 per image, about $0.35 for all 11 images once |

Test set, ground truth and decision rule stay as in PRD §4A: hand-written truth for 3 screenshots
and 2 PDFs in `code/evaluation/extraction_truth/`, scored on field recall, row association and
exact values. Docling wins only with ≥ 99% exactness and 100% row association. Whatever wins, the
extraction runs **once per file**, is validated against its schema, and is cached in
`code/deletion_audit/cache/extraction_cache.json` keyed by file hash + prompt version + model, then
shipped like the intent cache (offline reruns, usage logged).

### 4.9 The case file

```text
CaseFile(case_id, subject, resources[], rejected_count, coverage[])
  LinkedResource(system_id, resource_id, link_methods {identifier | trace | propagated | activity | catalog},
                 observations[] sorted by observed_at)
```

`python code/main.py --cases case_11 --explain` prints the case file, so every link can be checked
by eye during development and shown in the interview.

### 4.10 Measuring it

A new **link suite** in the harness, using the sample answers (expected `(system_id, resource_id)`
pairs, 111 in total) only for scoring:

| Metric | Meaning |
|---|---|
| Resource recall | Expected resources found in the case file, split by link method |
| Resource precision | Linked resources that the answer expects. Already-compliant resources also get verification steps (C-SP-2), so an unexpected link usually means a wrong link |
| Citation coverage | For expected steps that cite a file: that file is among the resource's observations with `captured_at ≤ audit_at` (what Stage 7 will need) |
| Rejections | Count of other people's records rejected per case (sanity check) |

Targets: 100% recall on the resources that appear in text or image evidence (95 of 111), precision
≥ 95%, citation coverage ≥ 95%. Q9's activity-linked resources are reported on their own line.

### 4.11 Proposals to agree before coding

| # | Proposal | Alternative |
|---|---|---|
| P1 | One `Observation` + `Coverage` model; readers keep raw fields, all interpretation in Stage 5 | Interpret state while parsing: fewer objects, but mixes stages and hides why a decision was made |
| P2 | Five generic readers with small field maps (SQL via in-memory SQLite, JSON walker, log normaliser + `trace_id` join, handover, extracted documents) | One parser per file family (~45): brittle and repetitive |
| P3 | `system_id` from the record, else a prefix map learned from the evidence on every run | Hand-written prefix table: simpler, but hard-coded |
| P4 | Linking = identifier owners + resource-level propagation (observations ≤ `audit_at`); other people's records rejected; mixed records flagged | Link per observation only: misses records cleaned before audit time |
| P5 | Q9 activity linking only for unlinked resources, `reported_status` tie-break, measured separately and dropped if it hurts precision | Skip Q9: certain misses on ~14 sample resources (verification steps) |
| P6 | Q10: accept catalog links unless the resource's evidence names a different person (`marketing_001` rejected) | Always trust the catalog / never use it |
| P7 | Stage 4A bake-off with a 30-minute Docling install timebox; project `.venv` + `requirements.txt`; winner's output cached and shipped | Skip the bake-off and use Claude vision: faster, but D8 stays untested |

### 4.12 Behaviour across case conditions

Checked at kickoff: across **2,037 resources** named on single-resource lines in the text evidence
(463 of them in two or more files), **no resource ID is ever tied to two different people**. That is
what makes resource-level propagation (P4) safe.

| Condition | Handled by | Example |
|---|---|---|
| Record deleted before `audit_at` | Coverage proves absence (C-SP-4); P5 links it through deletion-worker activity when no file names it | case_01 `account_001` (evidence_54 covers both account tables, no row) |
| Record cleaned (anonymized or redacted) but present | P4 propagation from an earlier naming observation, else P5 activity | case_26, custom_06 analytics records |
| Deleted, then recreated by a sync or restore | All observations kept in time order; Stage 5 takes the latest ≤ `audit_at` | case_11, case_15 active syncs |
| Deleted in one copy, alive in another | One observation per table or replica (`location`); Stage 5 compares copies | case_05, custom_06 replica drift |
| File captured after `audit_at` | Cite only if `captured_at` ≤ `audit_at`; use facts with own time ≤ `audit_at`; later facts never create links | case_09 evidence_06 |
| Changes during the audit period | Dated identifiers (Stage 3) and dated observations; nothing collapsed to "latest only" in Stage 4 | — |
| Record under an old identifier | Stage 3 full history feeds owner lookup | case_10, case_29 |
| Any `reported_status` | Never decides state; only a measured tie-break inside P5 | H-LK-6 (29/32) |
| Interleaved runs of several people | Owner index rejects other people's records; P5 takes only unowned resources | case_09 |

Known limits: P5 can pick the wrong account when two runs overlap and both leave unowned records
(measured, dropped if harmful); a resource with no file and no activity (e.g. `account_004`) cannot
be found; a link that only appears after `audit_at` is deliberately not used.

## 5. Acceptance checks

| Check | Pass condition |
|---|---|
| Resource uniqueness | Over all observations (not only single-resource lines), no resource is owned by two different users; any exception is reported |
| Unit tests | Each reader on small fixtures (every SQL shape, JSON shape and log style), `trace_id` joins, prefix-map learning and conflicts, linking classes, propagation time rule, Q9 rule, Q10 rule, extraction cache |
| Coverage of files | All 94 files read without error; observation and coverage counts per file reported |
| Link suite | Targets in §4.10 met, or each miss explained |
| Bake-off | Results table in PRD §4A filled; D8 decided |
| Reproducibility | Offline rerun with shipped caches gives identical case files and `output.csv` |
| No regressions | Harness, intent suite and tests unchanged |

## 6. Out of scope

- Deciding state at `audit_at`, replica drift, active flows and restore risk (Stage 5).
- Mapping labels to policy categories and choosing actions (Stage 6).
- Choosing which observation to cite (Stage 7). Stage 4 makes sure the candidates are there.

## 7. Results

### 7.1 What was built

| File | Role |
|---|---|
| `code/deletion_audit/observations.py` | `Observation`, `Coverage`, resource-ID pattern |
| `code/deletion_audit/readers/` | `sql_reader` (in-memory SQLite), `json_reader` (generic walk), `log_reader` (8 line styles + `trace_id` join), `handover_reader`, `document_reader` (extracted records) |
| `code/deletion_audit/extraction.py` + `prompts/extraction.md` | Stage 4A extractor: vision mode (CLI `Read` tool limited to the file's folder) and text mode; cached by file hash + prompt version + model |
| `code/deletion_audit/llm.py` | Optional read-only file access for the CLI backend |
| `code/deletion_audit/evidence.py` | `EvidenceStore`: loads all 94 files, learns `prefix → system` from the evidence (activity as fallback), resolves coverage systems by label, catalog aliases, owners per observation |
| `code/deletion_audit/linking.py` | `build_case_file`: identifier links, propagation, scope rule, Q10 catalog rule, Q9 activity rule |
| `code/main.py` | Loads evidence, builds a case file per deletion request, `--explain` |
| `code/evaluation/link_suite.py` | `--suite links`: resource recall/precision by method, citation coverage |
| `code/evaluation/extraction_bakeoff.py` + `extraction_truth/truth.json` + `extraction_bakeoff.md` | Stage 4A bake-off: 63 hand-written facts, every candidate scored |
| `code/requirements.txt`, `.venv/` (uv, Python 3.12) | Test and bake-off dependencies only; the agent itself is standard library |
| Tests | 34 new (97 in total): readers on every shape, extraction, evidence store, linking rules |

### 7.2 Stage 4A bake-off (decides D8)

| Candidate | Files | Facts found | Row mix-ups | Invented IDs | Cost |
|---|---|---|---|---|---|
| E3 Claude vision, Sonnet | 5 | 63/63 | 0 | 0 | $0.130 (5 calls) |
| **E3 Claude vision, Haiku** | 5 | **63/63** | **0** | **0** | **≈ $0.01 (5 calls)** |
| E0 pypdf text | 2 PDFs | 16/16 (text only, no records) | — | — | free |
| E0+L pypdf → Claude Haiku | 2 PDFs | 16/16 | 0 | 0 | ≈ $0.002 |
| E1 Docling, E1+L Docling → Haiku, E3+E1 cross-check | — | see §7.2.1 | | | |

**Decision (D8):** Claude vision with Haiku for every screenshot and PDF: perfect on the truth set,
row associations intact, cheapest model, one code path for both file types. Full extraction of all
15 documents: 15 calls, $0.0205, cached and shipped.

### 7.3 Link suite

| Suite | Resource recall | Resource precision | Citations available |
|---|---|---|---|
| samples (111 expected resources) | 93/111 (83.8%) | **93/93 (100%)** | 74/75 (63 in observations, 11 via coverage) |
| custom | 12/14 | 12/12 | 7/7 |

Every one of the 19 missed resources either appears in no evidence file (accounts `account_004`,
`account_010`, `account_5521`, …; audit records `audit_record_6645`, `audit_record_5569`) or appears
**only with every identifier blanked** (8 anonymized analytics records, `account_5482` as a bare
404). **Recall on resources the evidence ties to the subject is 93/93.**

### 7.4 Iterations and decisions

| Run | Change | Recall | Precision | Finding |
|---|---|---|---|---|
| 1 | Identifier links + Q9 activity on all unowned resources in ±2 h | 100/111 | 100/160 | Activity: 75 links, **57 wrong**. Runs of several people are interleaved in batches; cleaned records carry no name |
| 2 | Activity for one primary account only, and only when the case has no account yet | 87/111 | 87/90 | 0 wrong activity links; remaining wrong: 2 catalog, 1 identifier |
| 3 | **Scope rule:** a resource must be seen at or after `requested_at` (else it belongs to an earlier deletion) | 92/111 | **92/92** | Removed case_17's `account_6523` (a March readback, 404, five months before the request) and old catalog claims (`tombstone_17`, `object_19`); no expected resource lost |
| 3 | Accounts recognised by system (`account_service`), not by the wording "primary profile" | — | — | `account_00N` deletes use different wording |
| 4 | Documents read (Haiku vision) | 93/111 | 93/93 | `support_001` (PDF-only) found |
| 5 | Catalog aliases (`export_1842 (NST-2026-0718-1842)`) | 93/111 | 93/93 | Eval case_33 gains `export_1842` from `evidence_18`; no sample change |

Measured and rejected for non-account cleaned records: "appears in some evidence file"
(7 right / 18 wrong) and "shares an evidence file with the subject's records" (6 right / 14 wrong).

**Ambiguous accounts stay unlinked on purpose.** In case_18, 20, 23, 28, 29, 31, 32 the competing
cleaned accounts are known to belong to other people **only through `evidence_03`, captured on
2026-10-01, after those audits**. Using it would recover about five accounts, but evidence created
after `audit_at` must not change the answer (AGENTS.md §6.2), so the agent leaves them unlinked.

### 7.5 Acceptance checks

| Check | Result |
|---|---|
| Unit tests | **Pass** — 97/97 |
| Coverage of files | **Pass** — 94/94 files read, 0 errors: 2,921 observations (28 from documents), 549 coverage entries; system conflicts: none; 5 object-storage file names left without a system (they are files, not resources) |
| Resource uniqueness | **Pass** — 2,059 resources, none owned by two users |
| Link suite | Precision **100%** (target ≥ 95%); citations 98.7% (target ≥ 95%); recall 100% of identifier-bearing resources (target 100% of resources "in evidence": met for every resource whose evidence names the subject; cleaned no-identifier records are the documented exception) |
| Bake-off | Done; D8 decided |
| Reproducibility | **Pass** — online and offline (`claude` removed from PATH) runs give identical `output.csv` and identical case files for all 508 deletion cases (390 cached answers, 0 calls); system Python 3.14 without the venv gives the same output |
| No regressions | **Pass** — harness unchanged (answers still the stub), intent 402/402 |

### 7.6 Carried forward

- **Stage 5** reads states from `fields` (status codes, `rows`, `restore_allowed`, `enabled`,
  null identifiers, handover `state`) and decides absence through `Coverage` (C-SP-4).
- **Stage 7** cites the observation's `evidence_id`; 11 sample citations are absence proofs
  through coverage, not through an observation.
- The extraction prompt says records without a resource ID are left out, but the model keyed such
  documents by a reference (`user_18`), which the catalog-alias rule relies on. Worth making explicit
  if the prompt is revised.
