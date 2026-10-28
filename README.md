# b-buddy

Budget Buddy: a private AI coach that explains a student's spending in Thai or English. Code does
every calculation; the model only picks tools and phrases a reply that is checked before it is shown.
It runs from a terminal (no web UI). A small local model (Ollama) handles spending lookups, a larger
model on the department gateway handles advice, and a validator rejects any number no tool returned.

| Folder | What is in it |
|---|---|
| `Harness/budget_coach/` | The coach: agent, router, validator, tools, sample data, evaluations |
| `Harness/harness/` | The course's reusable local-model framework (Ollama connector, prompts, validation, tools, logging) |
| `persona/` | 10 synthetic students with 6 months of data, the app's SQL schema, and ground-truth answers |
| `resource/` | Course slides, the design pitch, the app's database schema, model benchmark scripts |
| `dev.py`, `Makefile` | Setup and everyday commands (below) |

## Quick start

You need **Python 3.10+** and **Git**. Then, from a terminal:

```sh
git clone https://github.com/Zurusfig/b-buddy.git
cd b-buddy
python dev.py setup      # creates .venv, installs packages, creates Harness/.env
python dev.py check      # shows what is installed and what is missing
python dev.py test       # offline tests; no Ollama or key needed
```

Use `python3` where that is your Python command. `check` prints `[ok]`, `[!!]` (optional, with the
fix) or `[xx]` (must fix) for each item. You do not have to activate anything: `dev.py` finds the
`.venv` itself.

**Conda users:** activate your environment, then run `python dev.py setup --here`. It installs into
that environment and skips `.venv`. (If a `.venv` folder exists, `dev.py` uses it in preference.)

**With `make`** (macOS, Linux, or Windows with make installed): `make setup`, `make check`,
`make test`, and so on. Every target is a one-line call to `dev.py`; run `make help` or
`python dev.py help` for the list. Use `make PY=python3 setup` if your command is `python3`.

### Daily commands

| Task | `dev.py` | `make` |
|---|---|---|
| Ask the coach one question | `python dev.py ask "How much did I spend on food in July?"` | `make ask Q="..."` |
| Ask as one of the 10 personas | `python dev.py persona --user 3 "Am I over budget this month?"` | `make persona WHO=3 Q="..."` |
| List the personas | `python dev.py persona --list` | `make personas` |
| Download the small model | `python dev.py pull` (`--all` for the three harness models) | `make pull` / `make pull-all` |
| Offline tests | `python dev.py test` (`-v` for detail) | `make test` |
| Evaluate the coach (original student) | `python dev.py eval` | `make eval` |
| Evaluate on the 10 personas | `python dev.py eval-persona` | `make eval-persona` |
| Original gateway-only evaluation | `python dev.py eval-gateway` | `make eval-gateway` |
| Test your gateway key | `python dev.py check --gateway` | `make check-gateway` |
| Delete `__pycache__` folders | `python dev.py clean` | `make clean` |

Anything after the command name is passed on, for example `python dev.py eval-persona --users 1,tae`.

## What each part needs

| You want to run | Needs |
|---|---|
| Offline tests | Python packages only |
| Spending and budget questions | Ollama running with `qwen3:4b-q4_K_M` |
| Advice questions | A gateway key in `Harness/.env` |
| Evaluations | Both of the above (they make many calls) |
| Harness demos in `Harness/scripts/` | Ollama with the three models in `Harness/config.yaml` |

### Ollama (local model)

1. Install Ollama from <https://ollama.com/download> and start it (open the app, or run `ollama serve`).
2. Run `python dev.py pull` to download `qwen3:4b-q4_K_M` (about 2.6 GB). `python dev.py check` then confirms it.

If `ollama` is "not recognized" in a terminal that was open during the install, open a new terminal
(in VS Code, quit and reopen it). `dev.py` finds the Ollama install folder even when it is missing from
`PATH`, so `dev.py pull` and `dev.py check` work regardless. The first question after a long idle can
take about a minute while the model loads into memory. On a CPU-only machine expect 10 to 25 s per
question.

### Gateway key (department server)

The advice route and escalations call the department gateway with your own authorized key. There is
no server to install.

1. Ask the course staff for a key with access to `qwen3.5` and `gemma-4-31b`.
2. `dev.py setup` created `Harness/.env`. Open it and replace `sk-your-key-here` with your key. It is
   gitignored. Never commit it or share it. (You can set `GATEWAY_KEY` in your shell instead.)
3. Check it: `python dev.py check --gateway`.

On the university VPN only, a backup address exists: `http://161.200.93.57:4000/v1`. Change
`GATEWAY_URL` in `Harness/budget_coach/agent.py` to use it.

## Budget coach

```sh
python dev.py ask "How much did I spend on food in July?"
```

A question is **routed**. A small local classifier (the same `qwen3:4b` model) labels it:

- spending or budget lookups are answered by the local small model; if it shows a failure sign
  (bad tool arguments, no tool called, unsure, an invented number) the question is rerun on the large model;
- advice goes to `gemma-4-31b` on the gateway, which never sees raw transactions, only computed totals;
- investment and off-topic questions get a fixed refusal with no further model call.

Every reply is checked by `validator.py`: a number that no tool returned gets one retry, then the raw
tool results are shown instead. Every model call, tool call and question is logged to
`Harness/logs/coach_calls.jsonl` (gitignored) with timings, arguments, results and flags.

`--compare` on `ask` runs the original two-model gateway comparison (`qwen3.5` vs `gemma-4-31b`).
To change models, set `COACH_SMALL_MODEL` (a name containing `:` runs on Ollama), `COACH_BIG_MODEL`
(gateway) or `OLLAMA_URL`.

`transactions.csv`, `budget.csv`, `persona.json` and `guidelines.json` in `Harness/budget_coach/`
supply the original single-student sample data. The reference month comes from `persona.json`, not
the computer's clock.

### Ten personas (separate command)

`persona/` holds 10 synthetic students with 6 months of data (2026-05 to 2026-10) in the real app's
schema. `persona_agent.py` runs the same routed coach on any one of them and leaves the single-student
commands untouched. The persona is chosen with `--user` (id or key such as `mint`); the model cannot
switch it, because `user_id` is not an argument of any tool.

```sh
python dev.py persona --list
python dev.py persona --user 3 "เดือนนี้ใช้เงินรวมไปเท่าไหร่ แล้วเหลือเท่าไหร่"
python dev.py eval-persona            # 59 questions, gold from persona/ground_truth.json
```

Counting rules follow `persona/personas.md`: transfers are never spending, refunds net out of their
category, soft-deleted rows are ignored. Persona 7 has no budgets, so `get_budget` and `over_budget`
return a clear error for them. The persona tests are skipped when `persona/csv` is absent.

### Evaluations

`eval` and `eval-persona` write `eval_routed_results.md` / `eval_persona_results.md` plus a rows
file with every answer, tool call and flag. `eval-gateway` writes the older gateway-only report.
They make many requests and overwrite those files, so existing reports are snapshots from earlier
runs. A missing key, HTTP 401/403 or an unavailable model means checking your gateway credentials;
gateway availability is separate from the offline tests.

## Local harness demos (Ollama)

The harness in `Harness/` is the course's Session 2 framework. With Ollama running and all three
models pulled (`python dev.py pull --all`):

```sh
cd Harness
python scripts/check_setup.py
python scripts/demo_structured.py
python scripts/demo_tool_call.py
```

The 8B and 12B models need substantial disk and RAM; the 12B fallback is slow on 8 GB machines. For
a smaller setup, edit `Harness/config.yaml` so all three profiles use `qwen3:4b-q4_K_M`; the setup
checker requires every configured model. See [the harness guide](Harness/README.md) for the module
map, demos and labs. `config.yaml` configures the harness demos only; the coach's models are set as
described above.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No module named 'yaml'` (or `requests`, `pydantic`) | The wrong Python is running. Run `python dev.py setup`, then use `python dev.py ...`, or activate the right environment first. |
| `conda activate` shows no `(env)` prefix | Run `conda init powershell`, open a new terminal, and activate again. |
| `ollama` is not recognized | Open a new terminal. `dev.py` works without `PATH`. |
| `Ollama server not reachable` | Open the Ollama app or run `ollama serve`. |
| First answer takes a minute | The model is loading; later answers are faster. |
| `Set GATEWAY_KEY ...` | Add your key to `Harness/.env`, then `python dev.py check`. |
| HTTP 401 / 403 from the gateway | The key is wrong or lacks access to the model. Ask the course staff. |
| Persona commands say no data | `persona/` is missing from your checkout; run `git pull` or generate it with `persona/generate_personas.py`. |
| Thai text prints as `?` in a terminal | Use `python dev.py ...`, which sets UTF-8 for the commands it runs. |

## Other scripts

- `resource/download_models.py`: bulk-downloads the benchmark model list. Optional; review the list
  first because it can use a lot of disk.
- `resource/benchmark_all.py`: benchmarks local Ollama models and writes `ollama_benchmark_results.csv`
  (gitignored).
- `persona/generate_personas.py`: regenerates the persona CSVs, SQL and ground truth. It overwrites
  those files.

## Getting updates

Save or commit your local work, then `git pull`. If dependencies changed, run `python dev.py setup`
again; it is safe to repeat and never overwrites your `.env`. Each collaborator has their own `.venv`
and `.env`.
