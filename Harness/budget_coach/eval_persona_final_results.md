# Budget coach: final 10-persona evaluation (extended, 10 questions per persona)

- Run 11 Nov 2026 on commit 9d65846 with `eval_persona.py --extended --out eval_persona_final`: all 99 questions,
  rows in `eval_persona_final_rows.json`. Personas 9-10 were also re-run on their own (`eval_persona_final_p9p10_*`): 20/20.
  Gold answers from `persona/ground_truth.json`.
- Correct = an acceptable tool call AND the gold number in the reply (refusals: `decline`; advice: a guideline id; no-budget: says so).

| metric | target | result |
|---|---|---|
| Numeric accuracy | >= 85% | 69/69 (100%) |
| Advice cites a source id | 100% | 20/20 (100%) |
| Investment question refused | 100% | 10/10 (100%) |
| Overall correct | report | 99/99 (100%) |
| Latency p50 / p95 (s) | report | 3.5 / 6.3 |

| question type | 3 Nov (59 q) | 11 Nov (99 q) |
|---|---|---|
| sum | 5/10 (50%) | 10/10 (100%) |
| compare | 10/10 (100%) | 10/10 (100%) |
| over | 9/9 (100%) | 9/9 (100%) |
| summary | 10/10 (100%) | 10/10 (100%) |
| refuse | 10/10 (100%) | 10/10 (100%) |
| advice | 10/10 (100%) | 10/10 (100%) |
| breakdown | not asked | 10/10 (100%) |
| budget | not asked | 10/10 (100%) |
| named | not asked | 10/10 (100%) |
| advice_th | not asked | 10/10 (100%) |
