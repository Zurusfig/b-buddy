# Changelog

Recent Budget Buddy changes for the 4 November 2026 UAT. Commit IDs refer to this repository; the finance app's `?uat=1` panel and authenticated API checks are committed separately in `../finance-tracker/`.

## 2026-11-04

- `e7cd552` — Log the complete serialized result of each coach tool call. The previous 300-character limit could cut off transaction lists and guideline details. Updated the focused test to check both tools.
- `5198d64` — Carry `chat_id` and `attempt` through the app coach endpoint into question and HTTP logs. Record the coach Git commit and model configuration name on each app run.
- `93c3a44` — Add `AGENTS.md` with project boundaries, UAT invariants, and verification steps.

## 2026-11-03

- `4d26359` — Fix the app database reader's reference month to October 2026. “Last month” therefore means September 2026 on the app path.
- `2d0641e` — Log round, tester number, task ID, and persona on app coach runs so UAT forms can be matched to answers.
- `df0d53c` — Add `Harness/data/test_set.jsonl` with T01–T11 and validate its ground-truth references, including `Henry.2026-10.over_budget_categories` for T02.
- `6e46cb2` — Add `scripts/grade.py` to report pass or fail for each UAT task without overwriting saved evaluation reports.
- `d9e6ea8`, `0bcb1f7` — Detect Chinese characters in Thai replies. The coach retries once and uses a verified Thai tool-result fallback if the reply still mixes scripts.
- `632552a` — Guide single-month Thai spending questions toward `sum_by_category`. A live T04/T05 rerun reported 2/2 passes after this change; three repeats per task through the app remain unverified.
- `5670d47` — Add a targeted password reset command for the Henry, Diana, and Grace demo accounts. It preserves their transactions and budgets and writes ignored, owner-only credentials.

## UAT verification still needed

- Confirm the app and Supabase path for Henry, Diana, and Grace, including a fresh account ID → persona check. The earlier read-only Supabase check reported the five requested ground-truth comparisons matching, but the ID mapping was not recorded.
- Run T04 and T05 three times each through the live app and inspect the tool calls.
- Inspect a fresh Thai app reply for Chinese characters and confirm that new UAT log records include `chat_id`, `attempt`, `git_commit`, `config_name`, and full tool results. Restart the coach after pulling changes so the process logs the current commit.
