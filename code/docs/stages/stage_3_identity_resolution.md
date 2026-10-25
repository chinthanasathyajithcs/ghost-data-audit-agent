# Stage 3 — Identity resolution

| Field | Value |
|---|---|
| Status | **Done** — identity index, subject profiles and matching rules built; 508/508 eval deletion requests resolve (§7) |
| Dates | 2026-10-25 → 2026-10-25 |
| PRD link | `code/docs/PRD.md` §7 Stage 3 (FR-3.x); conventions C-ID-1…4, C-LK-1, C-LK-3 |
| Depends on | Stage 0 (identity conventions), Stage 2 (only deletion requests reach this stage) |
| Feeds | Stage 4 (which records belong to the subject, and which belong to someone else) |

## How to read this document

§1 is the goal, §2 the questions, §3 the inputs. **§4 is the design**: what the identity data
looks like (measured), the subject profile, the matching rules and the special cases. §5 is how we
know it works, §6 what it leaves out, §7 the results.

---

## 1. Goal

Turn each deletion request's `email` into **one person and every identifier they have ever had**:
current and old emails, phones and email hashes, plus the stable `user_id` that many records use
instead of an email. Also provide the **matching rules** Stage 4 uses to decide whether a piece of
evidence names this person, someone else, or no one. Plain Python, no AI: exact lookups in two CSV
files are deterministic, free and easy to explain.

## 2. Questions to answer

| # | Question | Answer in |
|---|---|---|
| Q3-1 | How often does a request use an old email, and is any identifier shared between people? | §4.1 |
| Q3-2 | Is `email_hash` derivable from the email, so hashes of old emails can be trusted? | §4.1 |
| Q3-3 | How are identifiers written in the evidence (case, formats, decoys)? | §4.1 |
| Q3-4 | Which identifiers count at `audit_at` (C-ID-3)? | §4.3 |
| Q3-5 | How do we find identifiers inside free text without substring mistakes? | §4.4 |
| Q3-6 | Who owns an identifier that is *not* the subject's (needed to reject other people's records)? | §4.5 |
| Q3-7 | Where does Q9 (cleaned records with no identifier) belong? | §6 |

## 3. Inputs and dependencies

| Input | Use |
|---|---|
| `user_identities.csv` | 850 users: current name, email, phone, email hash, `updated_at` |
| `user_audit_log.csv` | 306 changes: 107 email, 107 email hash, 92 phone (196 users) |
| Request `email`, `audit_at` | Lookup key and time cutoff |
| Text evidence (read-only scan, design check only) | How identifiers appear in practice (§4.1) |

## 4. Design

### 4.1 What the data looks like (measured)

| Check | Result | Consequence |
|---|---|---|
| Requests using an **old** email | **100 of 518** eval requests (103 incl. samples) | Lookup must search history, not only the snapshot (C-ID-2) |
| Request emails not in lowercase | 20 | Emails compared case-insensitively |
| `email_hash` = SHA-256 of the lowercased email | **850/850** current, **107/107** historical pairs | Hashes are trustworthy identifiers; email and hash always change together |
| Snapshot equals the latest change for every field | Yes (0 mismatches, no change after `updated_at`) | History can be replayed from the snapshot backwards |
| Change chains unbroken (each old value = previous new value) | Yes (0 breaks) | One clean timeline per field |
| Identifier owned by more than one user (ever) | **0** | Any identifier points to exactly one person |
| Subject changes after `requested_at` or `audit_at` | 0 | The time rule (§4.3) never changes an answer in this data, but the contract requires it |
| Emails in text evidence not belonging to any user | **22 look-alikes**, e.g. `karim.elmasri@…` (real: `amina.elmasri@…`), `g.silva76.jr@…` (real: `g.silva76@…`) | Exact whole-token match only |
| Emails written in capitals in evidence | 49 occurrences | Case-insensitive |
| 64-hex strings in evidence | 59 real email hashes, **358 others** (integrity seals and similar) | A hex string counts only if it is a known hash |
| Phones in evidence | Always written exactly as in the identity files (formats differ by country: `+1 (312) 555-0129`, `+40 723 481 638`) | Match known phone strings; also accept the same digits written compactly |
| `user_id` references | 1,302 occurrences, always `user_N` | Whole-token match (`user_25` ≠ `user_259`) |

### 4.2 The subject profile

```text
Subject
  user_id        user_10
  name           Nadia Petrescu            (for reports only; never used to match)
  request_email  nadia.ionescu@yahoo.com
  matched_via    historical                (or current)
  identifiers    kind        value                      current  valid_from   valid_to
                 user_id     user_10                    yes      —            —
                 email       n.petrescu@yahoo.com       yes      2026-04-12   —
                 email       nadia.petrescu@yahoo.com   no       2025-12-13   2026-04-12
                 email       nadia.ionescu@yahoo.com    no       —            2025-12-13
                 email_hash  (one per email above)      …
                 phone       +40 723 481 638            yes      —            —
```

Built by replaying each field's history: the snapshot holds the latest value; each change event
closes the new value's start and the old value's end.

### 4.3 Time rule (C-ID-3)

An identifier belongs to the subject's profile for a case if it was held **at any moment up to
`audit_at`**, so `valid_from ≤ audit_at`. Values that only appear after `audit_at` are left out:
evidence before the cutoff cannot contain them. Old values stay in, because old systems keep them
after the person moves on.

### 4.4 Matching rules

Applied to field values and to free text (support messages, logs, documents):

| Kind | Normalised as | Found in text by |
|---|---|---|
| email | lowercased, trimmed | extracting whole email tokens, then exact lookup |
| email_hash | lowercased | extracting whole 64-hex tokens, then exact lookup |
| user_id | as written (`user_N`) | whole-token `user_\d+`, then exact lookup |
| phone | digits with leading `+` | searching for each known phone, written as in the identity file or compactly, with no digit directly before or after |

**Names are never identifiers.** Six users are called Novak; display names in evidence are for
reports only.

### 4.5 Owner index

The same index answers "**who owns this identifier?**" for all 850 users and their full history.
Stage 4 uses it to tell three situations apart:

| Evidence names… | Meaning |
|---|---|
| one of the subject's identifiers | the record belongs to the subject |
| another user's identifier | the record belongs to someone else (decoy, interleaved run): reject it |
| an identifier nobody owns (look-alike email, random hex) | not a link to anyone |

### 4.6 Unresolvable emails

No request email in the data fails to resolve. If one did, the case would carry no subject; the
agent reports it on stderr and later stages treat it as "no records can be linked". It never
guesses a person from a similar email or a name.

### 4.7 Integration

`IdentityIndex` is built once per run from the two CSV files. For every deletion request,
`resolve(email, audit_at)` returns the `Subject`, which `audit_case` passes on to later stages.
The stub decision stays until Stage 7, so **no score changes are expected in this stage**: the
proof is in the tests and the resolution statistics.

## 5. Acceptance checks

| Check | Pass condition |
|---|---|
| Unit tests | Current and historical lookup, case-insensitivity, full chain (3 emails), time rule, look-alike rejection, substring safety (`user_25` vs `user_259`, `.jr` emails), hash vs non-hash hex, phone formats, owner lookup, unknown email |
| Real data | All 508 deletion requests in the eval set resolve to exactly one user; 100 through an old email; custom_04 (old email) and custom_08 (capitals) resolve to the same users as case_12 and case_31 |
| No regressions | Harness scores unchanged; intent suite unchanged |
| No leak | Guard passes; identity code reads only participant files |

## 6. Out of scope

- Searching evidence files (Stage 4) — Stage 3 provides the profile and matching rules only.
- **Q9** (cleaned records with no identifier, linked only through deletion-worker activity) and
  **Q10** (data-catalog claims vs evidence): both need evidence and activity, so they move to
  Stage 4.
- Names, fuzzy matching, and phone numbers in formats the data never uses.

## 7. Results

### 7.1 What was built

| File | Role |
|---|---|
| `code/deletion_audit/identity.py` | `IdentityIndex` (timelines for all 850 users, reverse owner index, `resolve`, `owner_of`, `owners_in_text`), `Subject` (`values`, `find_in_text`), `Identifier` (kind, normalised value, original spelling, current, validity window) |
| `code/deletion_audit/contract.py` | `parse_time` moved here so every stage shares one timestamp parser |
| `code/main.py` | Builds the index once; resolves every deletion request; prints `identity: N resolved (M via an old email); unresolved: …` |
| `code/tests/test_identity.py`, `test_agent.py` | 16 new tests (63 in total) |

### 7.2 Acceptance checks

| Check | Result |
|---|---|
| Unit tests | **Pass** — 63/63: current and historical lookup, 3-email chain with hashes and phones, case and spaces, unknown email, time rule, validity windows, free-text matching, look-alikes and substrings, phone spellings, owner lookup, multi-person text, real-data and custom-variant checks |
| Real data | **Pass** — 508/508 eval deletion requests resolve; 100 through an old email; all 32 samples resolve (3 through an old email); custom_04 → same user as case_12, custom_08 → same user as case_31 |
| No regressions | **Pass** — samples 22/32, custom 7/8, intent 402/402; `output.csv` byte-identical to Stage 2 |
| No leak | **Pass** |
| Speed | Index built in 0.02 s; all 13,727 lines of text evidence scanned with `owners_in_text` in 0.06 s |

### 7.3 Problems found while building

| Problem | How it was caught | Fix |
|---|---|---|
| A subject's phone was stored only in compact form, so `+1 (312) 555-0129` written as in the identity file was not found | Test failed | Each identifier keeps its original spelling; phone patterns use both spellings |
| The owner index built its phone pattern from a generator that was read twice, so compact phones would silently never match in `owners_in_text` | Code reading; a new test failed before the fix | Read the input into a list once |
| Loading `code/main.py` by path in tests broke once it defined a dataclass | Test collection error | Register the module in `sys.modules` before executing it |

### 7.4 Notes for Stage 4

- **843 of 850 users** are named somewhere in the text evidence: nearly every file mixes many
  people, so "belongs to someone else" (owner index, §4.5) is as important as "belongs to the
  subject".
- For scanning many records, use `IdentityIndex.owners_in_text` (one precompiled pattern for all
  phones) rather than `Subject.find_in_text`, which compiles the subject's phone pattern per call.
- Q9 (cleaned records with no identifier) and Q10 (catalog claims vs evidence) start there.
