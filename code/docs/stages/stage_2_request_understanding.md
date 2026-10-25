# Stage 2 — Request understanding

| Field | Value |
|---|---|
| Status | **Done** — classifier, CLI backend, cache, usage tracking and intent suite built; intent 402/402 (§7) |
| Dates | 2026-10-25 → 2026-10-25 |
| PRD link | `code/docs/PRD.md` §7 Stage 2 (FR-2.1, FR-2.2); decisions D6, D7; open questions Q6, Q7 |
| Depends on | Stage 1 harness (custom cases custom_01–03, 05, 07; finding F1-4) |
| Feeds | Every case: a request that does not authorise deletion stops here as `NOT_APPLICABLE`, `[]` |

## How to read this document

§1 is the goal. §2 lists what we have to decide. §3 lists the inputs. **§4 is the design**: what
the request texts look like, the flow, the prompt, batching, the cache that makes runs repeatable,
the LLM backend, usage tracking, how the agent uses the answer and how we measure it. §5 says how we
will know the stage is done, §6 what it leaves out, and §7 is filled in at the end.

---

## 1. Goal

For every request, decide whether `request_text` **authorises deletion**, in any language. If it
does not (access, export, correction, marketing opt-out, login help, documents), the case is
`NOT_APPLICABLE` with `steps_json=[]` and no investigation runs. If it does, the case goes on to
Stages 3–7.

This is the agent's first AI step, so it also sets up the pieces every later AI call will reuse:
the Claude Code CLI backend (D6), the cache that makes runs repeatable and lets a grader re-run
without a Claude login (Q7), and token/cost tracking for `usage_report.md`.

## 2. Questions to answer

| # | Question | Answer in |
|---|---|---|
| Q2-1 | What do the request texts actually look like, and where are the traps? | §4.1 |
| Q2-2 | LLM only, keyword rules, or both? | §4.2 |
| Q2-3 | What exactly counts as "authorises deletion" (the labelling rule the prompt encodes)? | §4.3 |
| Q2-4 | One call per text or batches? Which model (PRD Q6)? | §4.4 |
| Q2-5 | How do we get the same answer on every run, and how can a grader without a Claude login re-run (PRD Q7)? | §4.5 |
| Q2-6 | What happens when the CLI is missing, logged out or rate-limited? | §4.6 |
| Q2-7 | How do we capture tokens and cost for `usage_report.md`? | §4.7 |
| Q2-8 | How do we measure intent accuracy beyond the 5 custom intent cases? | §4.9 |

## 3. Inputs and dependencies

| Input | Use |
|---|---|
| `request_text` of each request | The only field the classifier reads |
| `dataset/deletion_requests.csv` | 518 requests, 375 distinct texts |
| `dataset/sample_deletion_requests.csv` | 32 requests, all deletion requests (9 texts shared with the eval set) |
| `code/evaluation/custom_cases/` | custom_01–03 and custom_07 (`NOT_APPLICABLE`), custom_05 (Korean deletion) |
| Claude Code CLI 2.1.310 | Headless backend: `claude -p` with `--json-schema`, tested in §4.4 |
| PRD D6, D7 | LLM via CLI on the Pro plan; intent decided by LLM, cached |

**Fields deliberately not used:** `email`, `reported_status`, `reported_at`, dates. All 10
non-deletion requests in the eval set happen to be `NOT_STARTED`. Using that would be a
case-family shortcut (SC-4), so the classifier never sees it.

## 4. Design

### 4.1 What the request texts look like

All 518 texts are built from **67 distinct sentences**:

| Group | Rows | Shape |
|---|---|---|
| English deletion | 503 | One of 12 opening sentences ("Please erase the account linked to this email address."), one of 12 scope sentences ("Please include information linked through current or earlier account identifiers."), one of 9 closing sentences |
| Other-language deletion | 5 | Portuguese, Spanish, French, Japanese, Korean: "I request permanent deletion of the account linked to this email" plus review and confirmation sentences |
| Non-deletion | 10 | case_533–542, one each (below) |

The 10 non-deletion requests, and why each one is a trap for keyword rules:

| Case | Text (shortened) | Intent | Trap |
|---|---|---|---|
| case_533 | Mobile number out of date, replace it, leave the account active | Correction | — |
| case_534 | Stop the promotional emails… **not asking for deletion** | Marketing opt-out | "deletion" appears |
| case_535 | Download my account information in a portable format | Export | — |
| case_536 | Need help resetting the login. **Do not close** the account | Account support | "close" appears |
| case_537 | Surname misspelled; correct it **without removing** any records | Correction | "removing" appears |
| case_538 | **Remove me** from marketing lists only | Marketing opt-out | "remove" appears |
| case_539 | What information do you hold… **not a request to erase it** | Access | "erase" appears |
| case_540 | Copy of last year's invoices; leave my profile in place | Other (documents) | — |
| case_541 | Change the email address; I want to keep using the service | Correction | — |
| case_542 | Send me a copy of my information… **don't delete** or change anything | Access | "delete" appears |

Six of ten contain a deletion word next to a negation or a narrowing ("only", "without", "not").
Meanwhile the 12 French deletion requests use *suppression*, which an English keyword list misses
(F1-4). Keyword rules would have to be hand-tuned to these exact sentences, which is overfitting.
Reading the meaning is what an LLM is for.

### 4.2 Flow

```text
request_text ──► normalise (trim, collapse spaces) ──► cache lookup ──hit──► IntentResult
                                                          │ miss
                                                          ▼
                                     batch of misses ──► LLM (claude -p, JSON schema) ──► validate ──► cache ──► IntentResult
```

`IntentResult = (authorizes_deletion: bool, intent: label, language: str, reason: str)`. Only
`authorizes_deletion` drives the decision. The label, language and reason are kept for debugging,
the evaluation report and the interview.

**LLM only, no keyword fallback (P1).** A fallback would either be a weaker second classifier
that disagrees silently, or a copy of the traps above. When the LLM is unreachable and the text is
not cached, the run stops with a clear message (§4.6) rather than guessing.

### 4.3 Labelling rule (encoded in the prompt)

The prompt lives in `code/deletion_audit/prompts/intent.md`, a Markdown file the code judge can
read (NFR-6).

`authorizes_deletion = true` when the person asks to **delete, erase or permanently remove their
account or the personal data linked to it**, in any language, including:

- closing the account **together with** deletion of its data ("close my account and process the
  personal-data deletion");
- asking to check for leftover data and **finish** a deletion that failed or was partial;
- deletion requests that also ask for a confirmation, a review of old identifiers, or retention
  rules to be applied (policy, not the request, decides what is kept: C-PL-2).

`authorizes_deletion = false` for:

| Intent label | Examples |
|---|---|
| `ACCESS` | What data do you hold; send me a copy |
| `EXPORT` | Download my data in a portable format |
| `CORRECTION` | Fix my name, phone or email |
| `MARKETING_OPT_OUT` | Stop promotional emails; remove me from marketing lists **only** |
| `ACCOUNT_SUPPORT` | Login reset, access problems |
| `OTHER` | Invoices, documents, anything else |

Two tie-breakers: an explicit refusal ("not asking for deletion", "don't delete", "do not close")
always wins; and removing only a narrow item (a marketing subscription) is an opt-out, not
deletion of the person's data. Request texts are customer input: the prompt tells the model to
treat them as data to classify, never as instructions, and the JSON schema means the reply can
only be a classification.

### 4.4 Batching and model

**Feasibility test (done at kickoff).** One `claude -p` call with `--model haiku`,
`--json-schema`, minimal flags (`--tools ""`, `--strict-mcp-config`, `--setting-sources ""`,
`--disable-slash-commands`, `--no-session-persistence`, custom `--system-prompt`) and four tricky
texts (case_538, case_539, a French and a Spanish deletion) returned all four correctly:

| Measure | Value |
|---|---|
| Wall time | 3.4 s |
| Model | `claude-haiku-5-5` |
| Tokens | 2 input + 1,528 cache-creation input, 205 output |
| Cost (list price) | $0.00041 |
| Result | `structured_output.results[]`, one object per id, matching the schema |

**Batching (P3).** Send the cache misses in batches of **25 texts**, each with a short id, and get
back one result per id. The ~375 distinct texts (plus samples and custom cases) need about 17
calls and roughly a minute, against ~400 calls for one-by-one. After each batch the code checks
that every id came back exactly once with a valid label. Missing or malformed results are retried
in a smaller batch, and then one by one.

**Model (P2, answers PRD Q6 for this task).** Haiku (`claude-haiku-5-5`). The task is short-text
classification and the test above was all correct. If the intent evaluation (§4.9) shows **any**
error that a prompt fix does not solve, switch this task to Sonnet and record why.

### 4.5 Cache and reproducibility (answers PRD Q7)

- Cache file: `code/deletion_audit/cache/intent_cache.json`, **committed and shipped in
  `code.zip`**.
- Key: `sha256(prompt_version + model + normalised_text)`. Editing the prompt or changing the
  model bumps `prompt_version`, so stale answers are never reused.
- Entry: the `IntentResult` plus provenance (model, prompt version, call id, timestamp).
- A run where every text is cached makes **zero** LLM calls and needs no Claude login, so a grader
  can reproduce `output.csv` exactly. This also delivers determinism: the CLI exposes no
  temperature setting, so caching is how the same input always gives the same answer (NFR-2).
- `--refresh-intent` ignores the cache and re-asks the model (used once for the final run, and
  when the prompt changes).
- Writes are atomic (write to a temporary file, then rename), so an interrupted run never leaves a
  corrupt cache.

### 4.6 LLM backend and errors

`code/deletion_audit/llm.py` defines one small interface, `complete_json(system_prompt, user_input,
schema, model) -> (data, usage)`, with one implementation now:

| Backend | How | When |
|---|---|---|
| `ClaudeCliBackend` | `subprocess.run(["claude", "-p", ...])` with the minimal flags above; reads `structured_output` and `modelUsage` | Default (D6) |
| *(later, optional)* `AnthropicApiBackend` | Same interface, `ANTHROPIC_API_KEY` from the environment | Only if needed; not built now (YAGNI) |

Errors are never swallowed:

| Failure | Behaviour |
|---|---|
| `claude` not installed / not logged in | Stop before any batch with "Claude Code CLI unavailable; N texts are not cached" and how to fix it |
| Timeout, non-zero exit, `is_error: true`, rate limit | Retry up to 3 times with backoff (2 s, 8 s, 30 s), then stop with the CLI's message |
| Reply missing ids or failing the schema | Re-ask smaller batches (§4.4), then stop naming the text |

Answers already cached stay cached, so a re-run resumes where it stopped.

### 4.7 Usage tracking (for `usage_report.md`)

Each real call records model, input tokens, cache-creation and cache-read input tokens, output
tokens, list-price cost (from the CLI's `modelUsage`), wall time and batch size. Records are
appended to `code/evaluation/usage/usage_log.jsonl` (git-ignored raw data) and summarised at the
end of every agent run: calls, tokens and cost per model, plus cache hits.

`usage_report.md` must describe "the final full-dataset run that produced `output.csv`". With a
warm cache that run would make zero calls, so the final run is done with `--refresh-intent`
(cold cache), and its usage summary goes into the report. The same applies to later AI stages.

### 4.8 How the agent uses it

```text
audit_case(request):
    intent = classify(request.request_text)          # Stage 2
    if not intent.authorizes_deletion:
        return Answer("NOT_APPLICABLE", ())
    return <Stages 3–7>                               # still the stub until then
```

Classification runs once for all requests before the per-case loop, so cache misses are batched
together rather than called one case at a time.

### 4.9 Measuring it

The custom suite has only five intent cases, so we add an **intent suite** to the harness:

- `code/evaluation/intent_labels.csv`: one row per distinct request text from the samples, the eval
  set and the custom cases (about 400 texts), with our label `authorizes_deletion` and intent.
- Labels are written by hand following §4.3, documented in `code/evaluation/intent_labels.md`
  (counts per group, the 10 non-deletion texts with reasons), and used **only** for scoring.
- `python code/evaluation/main.py --suite intent` reports accuracy, a confusion matrix (deletion /
  not deletion) and every disagreement with its text and the model's reason.

Expected scores after Stage 2 (the stub still handles deletion cases):

| Suite | Before | After | Why |
|---|---|---|---|
| intent | — | target 100% | All groups in §4.1 |
| custom status | 3/8 | 7/8 | custom_01–03, 07 become `NOT_APPLICABLE`; custom_08 (COMPLETE) still wrong until later stages |
| samples status | 22/32 | 22/32 | All samples are deletion requests; no change expected, and any change is a bug |

### 4.10 Proposals to agree before coding

| # | Proposal | Alternative |
|---|---|---|
| P1 | LLM only for intent, no keyword fallback; unreachable LLM + uncached text stops the run | Keyword fallback: works offline, but it is the overfitted rule set §4.1 warns about, and it fails silently |
| P2 | Haiku (`claude-haiku-5-5`); switch to Sonnet only if the intent suite shows errors a prompt fix cannot solve | Sonnet from the start: more cost and time for a task Haiku handled in the test |
| P3 | Batches of 25 texts with ids and a JSON schema; verify ids, retry smaller | One call per text: simpler, about 20× more calls and time |
| P4 | Commit the cache and ship it in `code.zip`, keyed by prompt version + model + text; `--refresh-intent` for a cold run | No shipped cache: a grader without a Claude login cannot re-run |
| P5 | Intent suite with hand labels for all ~400 distinct texts, used only for scoring | Only the five custom intent cases: too few to trust |
| P6 | Usage log per call (JSONL, git-ignored) plus an end-of-run summary; the final run is cold so the report reflects real calls | Track usage only at the end, by hand |

## 5. Acceptance checks

| Check | Pass condition |
|---|---|
| Unit tests | Prompt/schema building, batching and id checking, cache keys and atomic writes, error paths (CLI missing, bad JSON, missing ids) with a fake backend — no real LLM calls in tests |
| Intent suite | 100% on all distinct texts, or every error explained and fixed |
| Custom suite | 7/8 status (only custom_08 still wrong, by design) |
| Samples | Status unchanged at 22/32 (no deletion request misread) |
| Reproducibility | Second run: 0 LLM calls, identical `output.csv` (byte for byte) |
| Offline | With `claude` removed from PATH and a warm cache, the full 518-case run still succeeds |
| Usage | Summary printed with calls, tokens and cost per model; log written |
| No leak | Agent never reads `intent_labels.csv`, `reported_status` or `email` for intent |

## 6. Out of scope

- Identity, evidence, state, policy and step building (Stages 3–7).
- An Anthropic API backend (interface only; built only if needed).
- `usage_report.md` itself (Stage 8). Stage 2 only produces the data.
- Image/PDF extraction (Stage 4A), which will reuse this backend and cache.

## 7. Results

### 7.1 What was built

| File | Role |
|---|---|
| `code/deletion_audit/prompts/intent.md` | The prompt: labels, output fields and the labelling rules (§4.3) |
| `code/deletion_audit/llm.py` | `ClaudeCliBackend`: `claude -p` with minimal flags and `--json-schema`; retries 2 s / 8 s / 30 s; parses `structured_output` and per-model usage |
| `code/deletion_audit/intent.py` | `IntentClassifier`: normalise, cache lookup, batches of 25, result validation (known id, unique, valid label, `authorizes_deletion` consistent with the label), retry in halves, clear errors |
| `code/deletion_audit/cache.py` | JSON cache with atomic saves; a corrupt file is an error, never silently dropped |
| `code/deletion_audit/usage.py` | Per-call usage records and per-model summary |
| `code/deletion_audit/config.py` | Models, batch size and file locations in one place |
| `code/deletion_audit/cache/intent_cache.json` | 402 cached answers (current prompt version only), committed and shipped |
| `code/main.py` | Classifies all texts in one pass, then `NOT_APPLICABLE` for non-deletion requests; `--refresh-intent`; prints and saves the usage summary |
| `code/evaluation/intent_labels.csv` + `.md` | Hand labels for all 402 distinct texts, with reasons for the 13 non-deletion texts |
| `code/evaluation/intent_suite.py` | `--suite intent`: accuracy, confusion matrix, every disagreement with the model's reason |
| `code/tests/test_intent.py`, `test_llm.py`, `test_agent.py` | 22 new tests with a fake backend and fake CLI (48 in total) |

### 7.2 Iterations (failures found and fixes)

| Run | Prompt | Authorises deletion | Failure | Fix (general rule added to the prompt) |
|---|---|---|---|---|
| 1 | v1 | 400/402 (99.5%) | Sample case_27 "Please audit the deletion as it stood…" and case_28 "Can you verify that my account was deleted?" read as `OTHER` | Asking to verify, audit or confirm that one's own account **was deleted** is a follow-up that keeps the deletion in scope → `DELETION` |
| 2 | v2 | 401/402 (99.8%) | Sample case_06 "my old profile still appears when I search for it. Can you remove that search result too?" read as a search-engine listing | Removing **leftover copies** of one's own personal data (search result, file, export, support record) is `DELETION`; only marketing unsubscribes are opt-outs |
| 3 | v3 | **402/402 (100%)**, labels 402/402 | — | — |

All three misses were **deletion requests read as non-deletion**. All 10 real non-deletion requests
(including the six with deletion words next to a negation) were right from the first run. The
labels were correct each time: the published sample answers treat case_06, 27 and 28 as deletion
audits. Haiku was kept (P2), because prompt fixes solved every error.

### 7.3 Acceptance checks

| Check | Result |
|---|---|
| Unit tests | **Pass** — 48/48 (22 new: batching, dedup, cache reuse, refresh, prompt-version keys, retry in halves, unresolvable result, unavailable CLI, backend failure keeps finished batches, usage records, corrupt cache, CLI flags, error replies, transient failures, availability) |
| Intent suite | **Pass** — 402/402 |
| Custom suite | **Pass** — 7/8 status as predicted; custom_01, 02, 03 and 07 fully correct; only custom_08 (COMPLETE) wrong until later stages |
| Samples | **Pass** — 22/32, unchanged |
| Reproducibility | **Pass** — two full 518-case runs give byte-identical `output.csv`, 0 LLM calls (375 cache hits) |
| Offline | **Pass** — with `claude` removed from PATH and the shipped cache, the 518-case run succeeds and matches. Without the cache it stops with exit 2: "Claude Code CLI unavailable and 375 request text(s) are not cached…" |
| Usage | **Pass** — summary printed each run; per-call log in `code/usage/usage_log.jsonl`, run summary in `code/usage/last_run_usage.json` (both git-ignored) |
| No leak | **Pass** — guard extended to `intent_labels`; agent reads only `request_text` for intent |

Full 518-case output now: 508 `INCOMPLETE` (stub) and 10 `NOT_APPLICABLE`, exactly case_533–542.

### 7.4 Cost of the final cold run (prompt v3, all 402 texts)

| Model | Calls | Input tokens (of which cache reads) | Output tokens | Cost (list price) | Wall time |
|---|---|---|---|---|---|
| `claude-haiku-5-5` | 17 | 66,820 (25,681) | 32,491 | $0.0247 | 190 s |

Three runs during the stage cost about $0.075 in total. Each batch call takes about 11 s; the
`reason` field accounts for most output tokens.

### 7.5 Changes from the plan

| Planned | What happened | Why |
|---|---|---|
| Usage log in `code/evaluation/usage/` | `code/usage/` | The agent writes the log; keeping agent output out of `code/evaluation/` preserves the one-way rule (the harness reads agent code, never the reverse) |
| Intent set of ~400 texts | 402 texts | 375 eval + 32 sample texts (9 shared) + 4 new custom texts |
| Prompt fixes only if needed | Two fixes (v2, v3) | Both added general rules about deletion follow-ups and leftover copies; no case-specific wording |
| Stale cache answers left in the file | Cache cleared before each prompt change | Old-version answers are never reused, so keeping them only bloats the shipped file |

### 7.6 Notes for later stages

- The backend, cache and usage recorder are generic: Stage 4A image/PDF extraction can reuse them
  with its own prompt, schema and cache file.
- The final submission run must use `--refresh-intent` (cold cache) so `usage_report.md` reflects
  real calls (§4.7).
