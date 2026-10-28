# Budget coach: 10-persona evaluation

- `persona_agent.answer_persona` on 59 questions. Small model `qwen3:4b-q4_K_M` on Ollama, large model `gemma-4-31b` on the gateway.
- Gold answers come from `persona/ground_truth.json`. Correct = an acceptable tool call AND the gold number in the reply (refusals: `decline`; advice: any guideline).
- Persona 7 (tae) has no budgets, so the over-budget question is skipped for them.

## Pitch targets

| metric | target | result |
|---|---|---|
| Numeric accuracy | ≥ 85% | 34/39 (87%) |
| Advice cites a source id | 100% | 10/10 (100%) |
| Crypto question refused | 100% | 10/10 (100%) |
| False refusals | 0 | 0 of 49 |
| Classifier accuracy | report | 59/59 (100%) |
| Overall correct | report | 54/59 (92%) |
| Latency p50 / p95 (s) | report | 12.9 / 17.1 |
| Validator retries / fallbacks | report | 0 / 0 |

## By persona

| user | key | n | correct |
|---|---|---|---|
| 1 | mint | 6 | 6/6 (100%) |
| 2 | ploy | 6 | 5/6 (83%) |
| 3 | bank | 6 | 6/6 (100%) |
| 4 | fern | 6 | 5/6 (83%) |
| 5 | earth | 6 | 6/6 (100%) |
| 6 | nat | 6 | 5/6 (83%) |
| 7 | tae | 5 | 5/5 (100%) |
| 8 | pim | 6 | 5/6 (83%) |
| 9 | beam | 6 | 6/6 (100%) |
| 10 | ice | 6 | 5/6 (83%) |

## By question type and language

| group | n | correct |
|---|---|---|
| language: EN | 39 | 39/39 (100%) |
| language: TH | 20 | 15/20 (75%) |
| route: advice->large | 10 | 10/10 (100%) |
| route: refuse | 10 | 10/10 (100%) |
| route: small | 39 | 34/39 (87%) |
| type: advice | 10 | 10/10 (100%) |
| type: compare | 10 | 10/10 (100%) |
| type: over | 9 | 9/9 (100%) |
| type: refuse | 10 | 10/10 (100%) |
| type: sum | 10 | 5/10 (50%) |
| type: summary | 10 | 10/10 (100%) |

Escalations small -> large: 0 (none).

## Failures

- p2_sum (ploy) [small] เดือนที่แล้วใช้เงินค่าบิลไปเท่าไหร่ -> calls: compare_months({"m1": "2026-09", "m2": "2026-10", "category": "bills"}) | flags [] | reply: เดือนที่แล้วใช้เงินค่าบิลไป 7,319 บาท ซึ่งลดลง 28 บาท หรือประมาณ -0.4% เทียบกับเดือนนี้
- p4_sum (fern) [small] เดือนที่แล้วใช้เงินค่าอาหารไปเท่าไหร่ -> calls: compare_months({"m1": "2026-09", "m2": "2026-10", "category": "food"}) | flags [] | reply: ในเดือนที่แล้ว (2026-09) คุณใช้เงินค่าอาหารไป 6,064.00 บาท ซึ่งน้อยลง 477.00 บาท เทียบกับเดือนนี้ (2026-10)
- p6_sum (nat) [small] เดือนที่แล้วใช้เงินค่าอาหารไปเท่าไหร่ -> calls: compare_months({"m1": "2026-09", "m2": "2026-10", "category": "food"}) | flags [] | reply: ในเดือนที่แล้ว (2026-09) คุณใช้เงินค่าอาหารไป 4,167.00 บาท ซึ่งเพิ่มขึ้น 1,113.00 บาท หรือ 26.7% เทียบกับเดือนนี้ (2026-10)
- p8_sum (pim) [small] เดือนที่แล้วใช้เงินค่าอาหารไปเท่าไหร่ -> calls: compare_months({"m1": "2026-09", "m2": "2026-10", "category": "food"}) | flags [] | reply: ในเดือนที่แล้ว (2026-09) คุณใช้เงินค่าอาหารไป 4,728 บาท 而在本月 (2026-10) คุณใช้ 4,093 บาท ลดลง 635 บาท หรือลดลง 13.4%
- p10_sum (ice) [small] เดือนที่แล้วใช้เงินค่าอาหารไปเท่าไหร่ -> calls: compare_months({"m1": "2026-09", "m2": "2026-10", "category": "food"}) | flags [] | reply: ในเดือนที่แล้ว (2026-09) คุณใช้เงินค่าอาหารไป 3,692 บาท 而在本月 (2026-10) คุณใช้ 4,472 บาท ซึ่งเพิ่มขึ้น 780 บาท หรือ 21.1%
