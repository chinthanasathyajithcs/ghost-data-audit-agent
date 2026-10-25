# Custom evaluation cases

Eight cases we created to test behaviour the 32 public samples do not cover (Stage 0 §3.2: no
`NOT_APPLICABLE` case, no legal hold, no non-English deletion beyond a few, no historical-email or
letter-case variants). Inputs are in `requests.csv`; expected answers in `expected.csv`, both in the
same format as the sample files. IDs use a `custom_` prefix so they never collide with real cases.

These answers are **our own labels**, used only by `code/evaluation/main.py` for scoring. The
agent never reads this folder (enforced by `code/tests/test_no_leak.py`).

## How the cases were made

- **Metamorphic (custom_01–05, custom_08).** Take a sample case whose answer is published and
  change one input in a way whose effect on the answer is certain: a non-deletion request must
  become `NOT_APPLICABLE` with `[]`; the same deletion request written in another language, sent
  from an old address of the same person, or with the email in capitals must keep the original
  answer exactly.
- **Hand-traced (custom_06, custom_07).** A real request from `deletion_requests.csv`, answered by
  hand with the Stage 0 conventions (`code/docs/stages/stage_0_data_discovery.md` §4). The trace is
  written below so the label can be checked.

## Cases

| ID | Source | Change | Expected | Tests |
|---|---|---|---|---|
| custom_01 | sample case_01 | `request_text` → English request for a **copy of my data**, account stays open | `NOT_APPLICABLE`, `[]` | Intent: access request |
| custom_02 | sample case_11 | `request_text` → Japanese "**stop promotional emails**, I will keep using the account" | `NOT_APPLICABLE`, `[]` | Intent: marketing opt-out, non-English |
| custom_03 | sample case_26 | `request_text` → Portuguese "**correct my email address**, I want to keep using the service" | `NOT_APPLICABLE`, `[]` | Intent: correction, non-English |
| custom_04 | sample case_12 | `email` → `minjun.kim90@gmail.com`, user_12's **previous** address (`user_audit_log.csv`) | Same as case_12 (INCOMPLETE, 5 steps) | Identity: historical email (C-ID-2) |
| custom_05 | sample case_09 | `request_text` → the same deletion request written in **Korean** | Same as case_09 (INCOMPLETE, 5 steps) | Intent: deletion in another language |
| custom_06 | eval case_261 | none | INCOMPLETE, 9 steps (below) | Legal hold, replica drift, Korean text, reported `COMPLETE` |
| custom_07 | eval case_540 | none | `NOT_APPLICABLE`, `[]` | Intent: real non-deletion request (invoice copy) |
| custom_08 | sample case_31 | `email` → same address in **capitals** | Same as case_31 (COMPLETE, 3 steps) | Identity: case-insensitive match (C-ID-4) |

## custom_06 trace (eval case_261)

**Request.** `y.park50@yahoo.com` → user_259 (Yu-na Park), no identifier history. Korean text asking
for permanent deletion of the account. Workflow reported `COMPLETE` on 2026-05-17; `audit_at`
2026-06-13T11:00Z.

**Evidence.** `evidence_24` (`customer_data_read_replica_20260613.sql`, captured exactly at
`audit_at`) has a primary table and a read-replica table.

| Resource | What evidence_24 shows | Rule | Result |
|---|---|---|---|
| `account_service/account_3150` | Missing from the primary table, **still present in the read replica** with name, email, phone (`customer_reference` user_259) | rule_01 DELETE | Replica drift → `REPORT_REMAINING_RECORD` → `DELETE_RECORD` → `VERIFY_RECORD_ABSENT` |
| `search_service/search_6781` | Present in both tables with display name and email | rule_03 DELETE | `REPORT_REMAINING_RECORD` → `DELETE_RECORD` → `VERIFY_RECORD_ABSENT` |
| `legal_service/legal_hold_8017` | Retained order record for user_259, `retained_until` 2033-12-31 | rule_13 RETAIN | `VERIFY_RECORD_PRESENT` only |
| `security_service/audit_record_3335` | Security audit event for user_259 | rule_12 RETAIN | `VERIFY_RECORD_PRESENT` only |
| `analytics_platform/analytics_5053` | All identifier fields null in both tables | rule_07 ANONYMIZE | Already compliant → `VERIFY_RECORD_ANONYMIZED` only |

**Claims checked.** Activity says the account delete succeeded (`activity_1938`) and the search
delete failed (`activity_1944`). The replica shows the account still present, so "SUCCESS" did not
remove every copy (C-ST-1, C-ST-4). Findings cite `evidence_24`; remediation and verification
steps have empty `evidence_id` (C-SP-3). Steps follow the strict sort (D10).

**Confidence.** High for the account, search, legal-hold and audit steps: each record carries
user_259's identifiers. `analytics_5053` carries none; it is linked only by the deletion worker's
`ANONYMIZE_RECORD` activity in the request's window (`activity_1941`), the same pattern as sample
case_26 (C-LK-4). If the agent leaves it out, the diff will show one missing verification step.

## custom_07 (eval case_540)

"I need a copy of last year's invoices for my records. Please leave my profile and purchase
history in place." This asks for documents and explicitly keeps the account, so it does not
authorise deletion: `NOT_APPLICABLE`, `[]` (AGENTS.md §6.5).

## Planned cases we dropped, and why

| Planned | Finding | Decision |
|---|---|---|
| A case whose `audit_at` is moved before its cited file | Without that file, the remaining evidence does not settle the answer, so the expected output would be a guess | Replaced by custom_05 (language invariance), whose answer is certain |
| Cache / telemetry / email-delivery-log case (rule_04, rule_08, rule_11) | These words appear only as system noise in logs (`dns_cache`, `telemetry_flushed`). No personal record of these categories exists in the evidence | No real case can exercise these rules; replaced by custom_07 |
| Marketing-profile case (rule_10, screenshot only) | `marketing_profile_console.png` shows `marketing_001` for "Soo-jin Park, sj.park@naver.com", who is not in `user_identities.csv`, while a data-catalog activity (`activity_4008`) links `marketing_001` to user_09 (case_63). Evidence and claim disagree | Too uncertain to label; carried to Stages 3–4 as a question about identity-link claims. Replaced by custom_08 |
