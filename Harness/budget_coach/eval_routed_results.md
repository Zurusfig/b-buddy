# Budget coach: routed agent evaluation

- `agent.answer_routed` on 64 questions (eval_set + hard set). Small model `qwen3:4b-q4_K_M` on Ollama, large model `gemma-4-31b` on the gateway. Gold values come from `tools.py`.
- correct = an acceptable tool call was made AND the reply contains the gold number (refusals: `decline` called).
- Latency is wall time per question including the classifier, on this machine.

## Pitch targets

| metric | target | result |
|---|---|---|
| Numeric accuracy | ≥ 85% | 27/35 (77%) |
| Advice cites a source id | 100% | 12/13 (92%) |
| Investment / off-topic refused | 100% | 12/12 (100%) |
| False refusals (in-scope question declined) | 0 | 0 of 52 |
| Classifier accuracy (eval_set intent labels) | report | 44/45 (98%) |
| Overall correct | report | 55/64 (86%) |
| Latency p50 / p95 (s) | report | 14.6 / 24.7 |
| Validator retries / fallbacks | report | 2 / 0 |

## By class and language

| group | n | correct |
|---|---|---|
| class: advice | 10 | 10/10 (100%) |
| class: budget_check | 12 | 11/12 (92%) |
| class: hard | 15 | 10/15 (67%) |
| class: out_of_scope | 8 | 8/8 (100%) |
| class: refusal | 4 | 4/4 (100%) |
| class: trend | 15 | 12/15 (80%) |
| language: EN | 37 | 33/37 (89%) |
| language: TH | 27 | 22/27 (81%) |

## By route

| route | n | correct | latency p50 (s) | latency p95 (s) |
|---|---|---|---|---|
| advice->large | 12 | 12/12 (100%) | 13.6 | 19.4 |
| refuse | 12 | 12/12 (100%) | 2.4 | 2.4 |
| small | 36 | 27/36 (75%) | 14.9 | 16.4 |
| small->large | 4 | 4/4 (100%) | 25.7 | 33.1 |

Escalations small -> large: 4 (validator_fallback 3, tool_error 1).

## Classifier misses (gold -> predicted)

- budget_check -> trend: 1

## Failures

- trend_sum_04 [small] เดือนที่แล้วใช้เงินกับอาหารไปเท่าไหร่ -> calls: compare_months({"category": "food", "m1": "2026-08", "m2": "2026-09"}) | flags [] | reply: ในเดือนที่แล้ว (2026-08) คุณใช้เงินกับอาหารไป 4,250 บาท 而在本月 (2026-09) คุณใช้ 4,600 บาท ซึ่งเพิ่มขึ้น 350 บาท หรือ 8.2%
- trend_sum_06 [small] เดือนพฤษภาคมจ่ายค่าอื่นๆ ไปเท่าไหร่ -> calls: over_budget({"month": "2026-05"}) | flags [] | reply: ในเดือนพฤษภาคม (2026-05) ค่าอื่นๆ ที่จ่ายไปคือ 5,112 บาท ซึ่งเกินกว่าขีดจำกัด 1,000 บาท จำนวน 4,112 บาท
- trend_cmp_02 [small] ค่าอาหารเดือนเมษาเทียบกับเดือนกันยาเพิ่มขึ้นเท่าไหร่ -> calls: compare_months({"m1": "2026-04", "m2": "2026-05", "category": "food"}) | flags [] | reply: ค่าอาหารในเดือนเมษา (2026-04) เท่ากับ 3,200 บาท และในเดือนกันยายน (2026-09) เท่ากับ 3,450 บาท ทำให้ค่าอาหารเพิ่มขึ้น 250 บาท หรือเพิ่มขึ้น 7.8%
- budget_over_05 [small] Am I over my shopping budget in July? -> calls: over_budget({"month": "2026-07"}) | flags [] | reply: Yes, you are over your shopping budget in July. You spent 3,475 THB, which is 1,975 THB over your limit of 1,500 THB.
- hard_01 [small] Did July hurt? -> calls: compare_months({"m1": "2026-07", "m2": "2026-08", "category": "food"}) | flags [] | reply: Did July hurt? The food expense in July (3950 THB) was 300 THB (7.6%) lower than in August.
- hard_05 [small] how much i spnd on fud last mnth -> calls: compare_months({"m1": "2026-08", "m2": "2026-09", "category": "food"}) | flags [] | reply: Last month, you spent 4,600 THB on food this month, which is 350 THB more than last month.
- hard_07 [small] ค่าวินเดือนสิงหาเท่าไหร่ -> calls: get_transactions({"month": "2026-08"}), sum_by_category({"month": "2026-08", "category": "food"}) | flags [] | reply: ค่าใช้จ่ายในหมวดหมู่อาหารในเดือนสิงหาคมคือ 4,250.00 บาท
- hard_08 [small] เดือนที่แล้วเทียบกับเดือนก่อนหน้านั้น ค่า Netflix กับ Spotify ขึ้นไหม -> calls: compare_months({"m1": "2026-08", "m2": "2026-09", "category": "subscriptions"}) | flags [] | reply: ค่า Netflix และ Spotify ไม่มีการเปลี่ยนแปลงระหว่างเดือนที่แล้ว (2026-08) และเดือนนี้ (2026-09) ค่าใช้จ่ายคงที่ที่ 442.0 บาท
- hard_13 [small] Food plus transport last month, what's the total? -> calls: sum_by_category({"month": "2026-08", "category": "food"}), sum_by_category({"month": "2026-08", "category": "transport"}) | flags [] | reply: The total for food last month was 4250.0 THB, and the total for transport last month was 947.0 THB.
