# Budget Buddy project guide

Read [README.md](README.md) before changing setup or running the app integration. This repository holds the Python coach; the NgernTong web app and API live in the separate `../finance-tracker/` Git repository. Check each working tree independently.

## Where to work

- `Harness/budget_coach/`: routed coach, data tools, validator, local HTTP server, and read-only app database reader.
- `Harness/harness/`: reusable course harness. Keep coach-specific behavior in `budget_coach/`.
- `Harness/tests/`: offline tests. `Harness/data/test_set.jsonl` and `scripts/grade.py`: the 11 UAT tasks and grader.
- `persona/`: synthetic data and `ground_truth.json`. The UAT personas are Henry, Diana, and Grace.

## UAT invariants

- The app database path uses October 2026 as the reference month: “this month” is `2026-10`, “last month” is `2026-09`. Do not use the computer clock or `Harness/budget_coach/transactions.csv` for app answers.
- Keep database reads scoped to the authenticated user ID. The coach's database role reads only its views; the model cannot select another user. Keep financial tools read-only.
- Code computes amounts. The model selects tools and phrases answers. Advice cites a tip ID from the tip store; investment and off-topic questions are declined.
- App UAT runs write JSONL records to `Harness/logs/coach_calls.jsonl` (gitignored). Join question, tool, and HTTP records by `run_id`. The UAT fields are round, tester number, task ID, persona, chat ID, and attempt; the coach also records its Git commit and config name.

## Change and verify

1. Check `git status` before edits. Preserve existing `.env` files, credentials, logs, and committed evaluation snapshots. `dev.py eval*` overwrites saved evaluation reports; use `scripts/grade.py` for UAT checks.
2. Make focused changes with a test, then commit each step. Keep `agent.py` changes small. Ask before deleting files or changing tool signatures.
3. Run offline tests with `python3.11 dev.py test` or `./.venv/bin/python -m unittest discover -s Harness/tests`. Live grading needs Ollama and, for advice or escalation, the course gateway.
4. Restart `python3.11 dev.py serve` after coach changes. Confirm live app behavior through the authenticated finance app; an offline test alone does not establish Supabase or browser behavior.

See [CHANGELOG.md](CHANGELOG.md) for recent changes and remaining UAT verification.
