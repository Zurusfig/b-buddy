# Budget coach: 500-question evaluation

- 500 questions, 10 personas x 50, graded against `persona/ground_truth.json` (`eval_large.py`).
- Small model `qwen3:4b-q4_K_M` on Ollama, large model `gemma-4-31b` on the gateway.
- Correct = an acceptable tool call AND the gold number in the reply; refusals = `decline`; advice = looked up a tip AND cites its id; no-budget, next-month and no-data questions = the reply says so.

## Done-definition targets

| metric | target | result |
|---|---|---|
| Numeric accuracy | >= 85% | 275/280 (98%) |
| Advice cites a source | 100% | 100/100 (100%) |
| Investment questions refused | 100% | 60/60 (100%) |
| Off-topic questions refused | report | 10/20 (50%) |
| False refusals (in-scope declined) | 0 | 0 of 420 |
| Classifier accuracy | report | 470/500 (94%) |
| Overall correct | report | 485/500 (97%) |
| Latency p50 / p95 (s) | report | 3.9 / 6.5 |

## By question type

| type | n | correct |
|---|---|---|
| named | 60 | 60/60 (100%) |
| relative | 40 | 35/40 (88%) |
| compare | 40 | 40/40 (100%) |
| over | 30 | 30/30 (100%) |
| budget | 30 | 30/30 (100%) |
| summary | 30 | 30/30 (100%) |
| breakdown | 30 | 30/30 (100%) |
| combined | 20 | 20/20 (100%) |
| invest | 60 | 60/60 (100%) |
| offtopic | 20 | 10/20 (50%) |
| advice | 100 | 100/100 (100%) |
| future | 20 | 20/20 (100%) |
| nodata | 20 | 20/20 (100%) |

## By language and persona

| group | n | correct |
|---|---|---|
| language: EN | 290 | 290/290 (100%) |
| language: TH | 210 | 195/210 (93%) |
| persona 1: alice | 50 | 49/50 (98%) |
| persona 2: bob | 50 | 48/50 (96%) |
| persona 3: charlie | 50 | 49/50 (98%) |
| persona 4: diana | 50 | 49/50 (98%) |
| persona 5: eve | 50 | 48/50 (96%) |
| persona 6: frank | 50 | 49/50 (98%) |
| persona 7: grace | 50 | 48/50 (96%) |
| persona 8: henry | 50 | 48/50 (96%) |
| persona 9: ivy | 50 | 48/50 (96%) |
| persona 10: jack | 50 | 49/50 (98%) |

## Wrong answers

- p1_36_offtopic [clarify] ช่วยเขียนโค้ด Python ให้หน่อย -> no tool | flags ['clarify'] | reply: อยากให้ช่วยเรื่องไหน เลือกข้อด้านล่าง หรือพิมพ์คำถามของคุณเองได้เลย
- p2_10_relative [small] เดือนนี้ค่าบันเทิงไปเท่าไหร่แล้ว -> spending_by_category({"month": "2026-10"}) | flags ['code_reply'] | reply: รายจ่ายเดือนตุลาคม 2026 - บิลและค่าสาธารณูปโภค: 7,291 บาท - อาหาร: 4,189 บาท - ช้อปปิ้ง: 2,121 บาท - เดินทาง: 1,358 บาท - สุขภาพ: 990 บาท - อื่นๆ: 958 บาท - บันเทิง: 169 บาท - การศ
- p2_36_offtopic [clarify] ช่วยเขียนโค้ด Python ให้หน่อย -> no tool | flags ['clarify'] | reply: อยากให้ช่วยเรื่องไหน เลือกข้อด้านล่าง หรือพิมพ์คำถามของคุณเองได้เลย
- p3_36_offtopic [clarify] ช่วยเขียนโค้ด Python ให้หน่อย -> no tool | flags ['clarify'] | reply: อยากให้ช่วยเรื่องไหน เลือกข้อด้านล่าง หรือพิมพ์คำถามของคุณเองได้เลย
- p4_36_offtopic [clarify] ช่วยเขียนโค้ด Python ให้หน่อย -> no tool | flags ['clarify'] | reply: อยากให้ช่วยเรื่องไหน เลือกข้อด้านล่าง หรือพิมพ์คำถามของคุณเองได้เลย
- p5_10_relative [small] เดือนนี้ค่าบันเทิงไปเท่าไหร่แล้ว -> spending_by_category({"month": "2026-10"}) | flags ['code_reply'] | reply: รายจ่ายเดือนตุลาคม 2026 - อาหาร: 4,019 บาท - ช้อปปิ้ง: 3,641 บาท - บันเทิง: 1,491 บาท - เดินทาง: 898 บาท - สุขภาพ: 430 บาท - บิลและค่าสาธารณูปโภค: 299 บาท รวม 10,778 บาท
- p5_36_offtopic [clarify] ช่วยเขียนโค้ด Python ให้หน่อย -> no tool | flags ['clarify'] | reply: อยากให้ช่วยเรื่องไหน เลือกข้อด้านล่าง หรือพิมพ์คำถามของคุณเองได้เลย
- p6_36_offtopic [clarify] ช่วยเขียนโค้ด Python ให้หน่อย -> no tool | flags ['clarify'] | reply: อยากให้ช่วยเรื่องไหน เลือกข้อด้านล่าง หรือพิมพ์คำถามของคุณเองได้เลย
- p7_10_relative [small] เดือนนี้ค่าบิลไปเท่าไหร่แล้ว -> spending_by_category({"month": "2026-10"}) | flags ['code_reply'] | reply: รายจ่ายเดือนตุลาคม 2026 - บิลและค่าสาธารณูปโภค: 8,249 บาท - อาหาร: 5,395 บาท - ช้อปปิ้ง: 1,657 บาท - เดินทาง: 484 บาท - บันเทิง: 312 บาท รวม 16,097 บาท
- p7_36_offtopic [clarify] ช่วยเขียนโค้ด Python ให้หน่อย -> no tool | flags ['clarify'] | reply: อยากให้ช่วยเรื่องไหน เลือกข้อด้านล่าง หรือพิมพ์คำถามของคุณเองได้เลย
- p8_10_relative [small] เดือนนี้ค่าบิลไปเท่าไหร่แล้ว -> spending_by_category({"month": "2026-10"}) | flags ['code_reply'] | reply: รายจ่ายเดือนตุลาคม 2026 - อาหาร: 4,093 บาท - การศึกษา: 874 บาท - อื่นๆ: 433 บาท - ช้อปปิ้ง: 317 บาท - บันเทิง: 296 บาท - เดินทาง: 218 บาท - บิลและค่าสาธารณูปโภค: 199 บาท รวม 6,430 
- p8_36_offtopic [clarify] ช่วยเขียนโค้ด Python ให้หน่อย -> no tool | flags ['clarify'] | reply: อยากให้ช่วยเรื่องไหน เลือกข้อด้านล่าง หรือพิมพ์คำถามของคุณเองได้เลย
- p9_10_relative [small] เดือนนี้ค่าบิลไปเท่าไหร่แล้ว -> spending_by_category({"month": "2026-10"}) | flags ['code_reply'] | reply: รายจ่ายเดือนตุลาคม 2026 - บิลและค่าสาธารณูปโภค: 10,039 บาท - อาหาร: 2,666 บาท - เดินทาง: 1,024 บาท - บันเทิง: 313 บาท - อื่นๆ: 42 บาท รวม 14,084 บาท
- p9_36_offtopic [clarify] ช่วยเขียนโค้ด Python ให้หน่อย -> no tool | flags ['clarify'] | reply: อยากให้ช่วยเรื่องไหน เลือกข้อด้านล่าง หรือพิมพ์คำถามของคุณเองได้เลย
- p10_36_offtopic [clarify] ช่วยเขียนโค้ด Python ให้หน่อย -> no tool | flags ['clarify'] | reply: อยากให้ช่วยเรื่องไหน เลือกข้อด้านล่าง หรือพิมพ์คำถามของคุณเองได้เลย
