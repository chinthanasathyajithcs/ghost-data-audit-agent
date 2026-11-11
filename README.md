# Ghost Data Audit Agent

![The workflow said “Complete.” The data was still there.](code/docs/images/hero.svg)

> **Built in about 24 hours** for [HackerRank Orchestrate](https://github.com/interviewstreet/hackerrank-orchestrate-october26)
> (October 2026), challenge *Ghost Data Still Exists*: from first look at the data to the final
> 518-case run, with a design doc and an evaluation for every stage.

When someone asks a company to delete their data, a workflow runs and reports **Complete**. But
copies often survive in replicas, backups, logs, exports, search indexes, screenshots and PDFs, and
a sync or a backup restore can quietly bring deleted data back.

This agent audits those claims. For each deletion request it works out whether the person really
asked for deletion, finds every record of them under every identifier they ever used, decides what
was actually true on the audit date, applies the company's deletion policy, and returns a verdict:
`COMPLETE`, `INCOMPLETE` or `NOT_APPLICABLE`. An incomplete case also gets an ordered plan of
findings (each citing the file that proves it), fixes, and the checks that must pass afterwards.


## Results

| Metric (32 public sample cases) | Score |
|---|---|
| Verdict accuracy | **32/32 (100%)** |
| Step precision / recall / F1 | **100% / 90.7% / 95.1%** |
| Fully correct cases (verdict and every step) | 18/32 |
| Format problems in the 518-row output | 0 |

Full metrics, custom test cases, failures and fixes: [`code/evaluation/evaluation_report.md`](code/evaluation/evaluation_report.md).
Token use and cost of the final run: [`code/evaluation/usage_report.md`](code/evaluation/usage_report.md).

## How it works

![Seven steps from one request to a verdict](code/docs/images/pipeline.svg)

Deterministic Python does the investigating. A Claude model is used only where reading needs
judgment (understanding a request, reading a screenshot or PDF, naming a record's type), always
through a JSON schema and a cache, so runs are repeatable.

![Step 1: did they really ask for deletion?](code/docs/images/step-1-intent.svg)

Some requests look like deletions but aren't: asking for a copy of your data, or to stop marketing
emails. A Claude model reads each request, in any language, and only real deletion requests go on.
The rest are answered `NOT_APPLICABLE` with no steps.

![Step 2: who are they, then and now?](code/docs/images/step-2-identity.svg)

Requests often come from an email the person no longer uses, and old copies of their data still
carry old emails and phones. The agent rebuilds every identifier from the identity snapshot and its
change history, including the stable `user_id` that many records use instead of an email.
Plain lookups, no AI.

![Step 3: reading 94 files in 6 formats](code/docs/images/step-3-evidence.svg)

Evidence arrives as SQL snapshots, JSON exports, eight styles of log, a text record, screenshots and
PDFs. Five readers turn them into one list of observations; screenshots and PDFs are read with Claude
vision. Every observation keeps its file ID and capture time, so any finding can cite its proof.

![Step 4: which records are theirs?](code/docs/images/step-4-linking.svg)

A record joins the person's case file only through an exact identifier: a current or old email,
phone, email hash, user ID, or a `trace_id` join. A matching name or a similar-looking email is never
enough, because a wrong link would delete someone else's data.

![Step 5: what was true on audit day?](code/docs/images/step-5-state.svg)

Logs and workflow statuses are claims, not proof. For each record the agent asks four questions
(is it there, does it still identify the person, is a sync still copying it, can a backup restore
it) and answers each from the latest evidence captured before `audit_at`. Anything later can't
change the answer.

![Step 6: what does the policy say?](code/docs/images/step-6-policy.svg)

The policy file decides each record's treatment: delete, redact, anonymize, retain, or keep an
account tombstone with only the stable reference. A record's category comes from its evidence label,
or from Claude when the file doesn't say. The agent compares what the rule requires with what was
true on audit day.

![Step 7: the verdict and the fix-it plan](code/docs/images/step-7-plan.svg)

Any violation makes the case `INCOMPLETE`: findings first (each citing its evidence), then a
remediation plan that stops data flows and blocks restores before touching records, then the checks
that must pass afterwards. A clean case is `COMPLETE`, with verification steps backed by evidence.

### Under the hood

| Step | What it does | Code |
|---|---|---|
| 1 Intent | Does the request authorise deletion? (any language; negations such as "remove me from marketing lists only") | `deletion_audit/intent.py`, `prompts/intent.md` |
| 2 Identity | The subject and every email, phone, email hash and `user_id` they ever had, valid at `audit_at`; owner of any identifier | `deletion_audit/identity.py` |
| 3 Evidence | Five readers turn all 94 evidence files (SQL via SQLite, JSON, 8 log styles with `trace_id` joins, handover text, screenshots/PDFs via Claude vision) into one observation model | `deletion_audit/readers/`, `evidence.py`, `extraction.py` |
| 4 Linking | The case file of the subject's records; other people's records rejected | `deletion_audit/linking.py` |
| 5 State | Each record at `audit_at`: present/absent, identifiable/redacted/anonymized, sync active/disabled, restore open/blocked. Latest evidence wins, any copy present means present, claims never decide | `deletion_audit/state.py` |
| 6 Policy | Data category (evidence label, else Claude over a de-identified signature) and the rule from the policy CSV → finding / remediation / verification | `deletion_audit/category.py`, `policy.py`, `prompts/category.md` |
| 7 Answer | Verdict and strictly ordered, numbered, cited steps → `output.csv`, checked by the format validator | `deletion_audit/steps.py`, `validate.py`, `main.py` |

The design, decisions and results of every stage are written up in
[`code/docs/PRD.md`](code/docs/PRD.md) and [`code/docs/stages/`](code/docs/stages/).

## Run it

Requirements:

- **Python 3.12+**. The agent and the evaluation harness use only the standard library.
- **The challenge dataset**, which is not included in this repository (see below).
- **Optional:** [Claude Code](https://claude.com/claude-code) (`claude` on `PATH`, logged in). It is only
  needed when an answer is not already in the shipped caches (see *Offline runs*). No API key is used
  or read.

```bash
git clone https://github.com/chinthanasathyajithcs/ghost-data-audit-agent.git
cd ghost-data-audit-agent

# The dataset belongs to the challenge organisers; fetch it from the public challenge repo
git clone --depth 1 https://github.com/interviewstreet/hackerrank-orchestrate-october26.git /tmp/challenge
cp -r /tmp/challenge/dataset ./dataset

python3 code/main.py                       # all 518 requests -> ./output.csv
python3 code/main.py --cases case_33,case_261 --explain --output /tmp/check.csv   # inspect cases
```

`--explain` prints, for each deletion case, the subject, every linked record with its observations,
its state at `audit_at` with the proving file, its data category and rule, and the resulting steps.
The run ends with a format check of the written file and a usage summary.

### Offline runs

Every LLM answer (request intent, screenshot/PDF extraction, data categories) is cached in
`code/deletion_audit/cache/` and shipped. With these caches the agent makes **zero** LLM calls and
reproduces its output byte for byte, without Claude Code installed or logged in. Cache keys include
the prompt version and model, so editing a prompt re-asks the model. `--refresh-intent` re-asks the
intent model; deleting a cache file re-creates it on the next run.

## Evaluate

For the tests and the extraction bake-off:

```bash
uv venv .venv --python 3.12          # or: python3.12 -m venv .venv
uv pip install --python .venv/bin/python -r code/requirements.txt
```

```bash
python3 code/evaluation/main.py                    # agent on 32 samples + 8 custom cases: status, step,
                                                   # field and sequence accuracy, per-case diffs
python3 code/evaluation/main.py --cases case_05 --diff
python3 code/evaluation/main.py --suite intent     # request intent on all 402 distinct texts
python3 code/evaluation/main.py --suite links      # linked records vs records in the expected answers
python3 code/evaluation/main.py --suite states     # state at audit_at vs states the answers imply
python3 code/evaluation/main.py --suite decisions  # policy decisions vs expected operations
python3 code/evaluation/main.py --validate output.csv
.venv/bin/python -m pytest code/tests -q           # unit tests
```

Every full run appends a row to `code/evaluation/run_history.md`.

## Repository layout

```text
code/
  main.py                    agent entry point
  deletion_audit/            agent package (pipeline stages, prompts/, cache/)
  evaluation/                harness, suites, custom cases, bake-off, reports, run history
  tests/                     pytest suite
  docs/                      PRD, stage design documents, README illustrations (docs/images/)
  requirements.txt           test and bake-off dependencies (the agent needs none)
  package.py                 builds the challenge's code.zip
dataset/                     challenge data: not included, fetch it as shown above
```

The illustrations are hand-written SVG. Their sources are in `code/docs/images/src/`; rebuild them
with `python code/docs/images/src/build.py` (needs `fonttools` and `brotli`).

## Credits and license

- Challenge, problem statement and dataset: [HackerRank Orchestrate, October 2026](https://github.com/interviewstreet/hackerrank-orchestrate-october26).
  They are not redistributed here.
- Fonts in the illustrations: Fraunces, Atkinson Hyperlegible and Caveat, under the
  [SIL Open Font License 1.1](code/docs/images/src/fonts/OFL.txt).
- Code: [MIT License](LICENSE).
