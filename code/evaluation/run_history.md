# Evaluation run history

One row per full-suite run of `code/evaluation/main.py`. Metric definitions: `code/docs/stages/stage_1_evaluation_harness.md` §4.2.

| Time (UTC) | Commit | Label | Suite | Cases | Status | Step P / R / F1 | Field | Seq exact | Seq partial | Fully correct | Format problems |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-25 07:01 | acb3dfc+dirty | stage 1 stub baseline (always INCOMPLETE, no steps) | samples | 32 | 68.8% | 0.0% / 0.0% / 0.0% | 0.0% | 0.0% | 0.0% | 0/32 | 32 |
| 2026-10-25 07:01 | acb3dfc+dirty | stage 1 stub baseline (always INCOMPLETE, no steps) | custom | 8 | 37.5% | 0.0% / 0.0% / 0.0% | 0.0% | 50.0% | 50.0% | 0/8 | 8 |
| 2026-10-25 07:01 | acb3dfc+dirty | stage 1 stub baseline (always INCOMPLETE, no steps) | all | 40 | 62.5% | 0.0% / 0.0% / 0.0% | 0.0% | 10.0% | 10.0% | 0/40 | 40 |
| 2026-10-25 08:09 | 49a9642+dirty | stage 2 intent, haiku, prompt v1 | intent | 402 | 99.5% | — | — | — | — | — | — |
| 2026-10-25 08:12 | 49a9642+dirty | stage 2 intent, haiku, prompt v2 (deletion follow-ups) | intent | 402 | 99.8% | — | — | — | — | — | — |
| 2026-10-25 08:16 | 49a9642+dirty | stage 2 intent, haiku, prompt v3 (leftover copies) | intent | 402 | 100.0% | — | — | — | — | — | — |
| 2026-10-25 08:16 | 49a9642+dirty | stage 2: intent -> NOT_APPLICABLE (deletion cases still stub) | samples | 32 | 68.8% | 0.0% / 0.0% / 0.0% | 0.0% | 0.0% | 0.0% | 0/32 | 32 |
| 2026-10-25 08:16 | 49a9642+dirty | stage 2: intent -> NOT_APPLICABLE (deletion cases still stub) | custom | 8 | 87.5% | 0.0% / 0.0% / 0.0% | 0.0% | 50.0% | 50.0% | 4/8 | 4 |
| 2026-10-25 08:16 | 49a9642+dirty | stage 2: intent -> NOT_APPLICABLE (deletion cases still stub) | all | 40 | 72.5% | 0.0% / 0.0% / 0.0% | 0.0% | 10.0% | 10.0% | 4/40 | 36 |
| 2026-10-25 09:20 | 1b596a5+dirty | stage 3: identity resolution (no score change expected) | samples | 32 | 68.8% | 0.0% / 0.0% / 0.0% | 0.0% | 0.0% | 0.0% | 0/32 | 32 |
| 2026-10-25 09:20 | 1b596a5+dirty | stage 3: identity resolution (no score change expected) | custom | 8 | 87.5% | 0.0% / 0.0% / 0.0% | 0.0% | 50.0% | 50.0% | 4/8 | 4 |
| 2026-10-25 09:20 | 1b596a5+dirty | stage 3: identity resolution (no score change expected) | all | 40 | 72.5% | 0.0% / 0.0% / 0.0% | 0.0% | 10.0% | 10.0% | 4/40 | 36 |
| 2026-10-25 10:34 | 9f4d33a+dirty | stage 4: identifier + scope rule + account activity, documents via haiku vision | links:samples | 111 | recall 83.8% | precision 100.0% | — | — | — | — | — |
| 2026-10-25 10:34 | 9f4d33a+dirty | stage 4: identifier + scope rule + account activity, documents via haiku vision | links:custom | 14 | recall 85.7% | precision 100.0% | — | — | — | — | — |
| 2026-10-25 11:22 | e041266+dirty | stage 5: state at audit_at (signals, latest-wins, any-copy, coverage absence, cache-noise filter) | states:samples | 93 | state 100.0% | proof 100.0% | — | — | — | — | — |
| 2026-10-25 11:22 | e041266+dirty | stage 5: state at audit_at (signals, latest-wins, any-copy, coverage absence, cache-noise filter) | states:custom | 12 | state 100.0% | proof 100.0% | — | — | — | — | — |
| 2026-10-25 12:00 | c28c0ad+dirty | stage 6: categories (labels + Haiku over de-identified signatures) + decision table | decisions:samples | 93 | exact 100.0% | finding cites 100.0% | — | — | — | — | 0 review(s) |
| 2026-10-25 12:00 | c28c0ad+dirty | stage 6: categories (labels + Haiku over de-identified signatures) + decision table | decisions:custom | 12 | exact 100.0% | finding cites 100.0% | — | — | — | — | 0 review(s) |
| 2026-10-25 12:08 | e4b2344+dirty | stage 7: first full agent (decisions -> steps) | samples | 32 | 100.0% | 100.0% / 90.7% / 95.1% | 88.7% | 56.2% | 87.4% | 18/32 | 0 |
| 2026-10-25 12:08 | e4b2344+dirty | stage 7: first full agent (decisions -> steps) | custom | 8 | 100.0% | 100.0% / 90.9% / 95.2% | 89.6% | 75.0% | 94.4% | 6/8 | 0 |
| 2026-10-25 12:08 | e4b2344+dirty | stage 7: first full agent (decisions -> steps) | all | 40 | 100.0% | 100.0% / 90.7% / 95.1% | 88.8% | 60.0% | 88.8% | 24/40 | 0 |
