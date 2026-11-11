# Budget coach: 10-persona evaluation

- `persona_agent.answer_persona` on 20 questions. Small model `qwen3:4b-q4_K_M` on Ollama, large model `gemma-4-31b` on the gateway.
- Gold answers come from `persona/ground_truth.json`. Correct = an acceptable tool call AND the gold number in the reply (refusals: `decline`; advice: any guideline).
- Persona 7 (grace) has no budgets, so the over-budget question is skipped for them.

## Pitch targets

| metric | target | result |
|---|---|---|
| Numeric accuracy | ≥ 85% | 14/14 (100%) |
| Advice cites a source id | 100% | 4/4 (100%) |
| Crypto question refused | 100% | 2/2 (100%) |
| False refusals | 0 | 0 of 18 |
| Classifier accuracy | report | 20/20 (100%) |
| Overall correct | report | 20/20 (100%) |
| Latency p50 / p95 (s) | report | 1.8 / 5.8 |
| Validator retries / fallbacks | report | 0 / 0 |

## By persona

| user | key | n | correct |
|---|---|---|---|
| 9 | ivy | 10 | 10/10 (100%) |
| 10 | jack | 10 | 10/10 (100%) |

## By question type and language

| group | n | correct |
|---|---|---|
| language: EN | 10 | 10/10 (100%) |
| language: TH | 10 | 10/10 (100%) |
| route: advice->large | 4 | 4/4 (100%) |
| route: refuse | 2 | 2/2 (100%) |
| route: small | 14 | 14/14 (100%) |
| type: advice | 2 | 2/2 (100%) |
| type: advice_th | 2 | 2/2 (100%) |
| type: breakdown | 2 | 2/2 (100%) |
| type: budget | 2 | 2/2 (100%) |
| type: compare | 2 | 2/2 (100%) |
| type: named | 2 | 2/2 (100%) |
| type: over | 2 | 2/2 (100%) |
| type: refuse | 2 | 2/2 (100%) |
| type: sum | 2 | 2/2 (100%) |
| type: summary | 2 | 2/2 (100%) |

Escalations small -> large: 0 (none).

## Failures

