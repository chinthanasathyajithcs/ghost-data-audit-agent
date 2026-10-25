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
