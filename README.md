# b-buddy

A Python budget coach with spending tools and model evaluations, plus a reusable
LLM harness for structured output and tool calling. There is no web UI; run the
Python scripts from a terminal. Sample budget data is included.

## First-time setup

Install Python 3.10 or newer and Git, then clone this repository:

```sh
git clone https://github.com/Zurusfig/b-buddy.git
cd b-buddy
python -m venv .venv
```

Activate the environment on macOS / Linux:

```sh
source .venv/bin/activate
```

Or on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Use `python3` in place of `python` if that is your Python command. Once activated:

```sh
python -m pip install -r requirements.txt
cd Harness
python -m unittest discover -s tests -v
```

The tests run offline without credentials or downloaded models. Choose either
of the following ways to run live model calls.

## Budget coach (department gateway)

This agent uses the department gateway and requires your own authorized API key.
It does not need a local Ollama installation.

From `Harness`, copy the environment template:

```sh
cp .env.example .env
```

On PowerShell use `Copy-Item .env.example .env` instead. Edit `.env` and replace
`sk-your-key-here` with your key. Never commit this file or share your key.
Alternatively, set `GATEWAY_KEY` in your shell environment.

```sh
cd budget_coach
python agent.py "How much did I spend on food in July?"
```

The command compares `qwen3.5` and `gemma-4-31b` using automatic escalation to
thinking mode. Your key must have access to those gateway models. For one call:

```sh
python -c 'from agent import answer; print(answer("How much did I spend on food in July?", model="qwen3.5")["answer"])'
```

`transactions.csv`, `budget.csv`, `persona.json`, and `guidelines.json` supply
the included sample data. The reference month comes from `persona.json`, rather
than the computer's current date. To run the full evaluation from this folder:

```sh
python eval_agent.py
```

Evaluations make many gateway requests and overwrite the corresponding result
files. Existing reports in this repository are snapshots from earlier runs.
A missing key, HTTP 401/403, or unavailable model requires checking your gateway
credentials/access. Gateway availability is separate from the offline tests.

## Local harness (Ollama)

Install Ollama separately and start it (open its app or run `ollama serve`).
From `Harness`, pull the models used by the default configuration:

```sh
ollama pull qwen3:4b-q4_K_M
ollama pull qwen3:8b-q4_K_M
ollama pull gemma3:12b-it-q4_K_M
python scripts/check_setup.py
python scripts/demo_structured.py
python scripts/demo_tool_call.py
```

Models require substantial disk space and RAM; the 12B fallback can be slow on
8 GB hardware. For a smaller setup, edit `Harness/config.yaml` so all three
profiles use an installed model, such as `qwen3:4b-q4_K_M`. The setup checker
requires every configured model. Gateway credentials are unnecessary here.

See [the harness guide](Harness/README.md) for the module map, demos, and labs.
The gateway budget coach has its own model settings in
`Harness/budget_coach/agent.py`; `config.yaml` configures the local harness only.

## Other scripts

- `download_models.py`: bulk-downloads the benchmark model list. Optional; review
  the list before running because it can consume substantial disk space.
- `benchmark_all.py`: benchmarks local Ollama models and writes
  `ollama_benchmark_results.csv`.
- `Harness/probe*.py`: local and gateway model experiments. Read each script's
  docstring before running; some make many calls and replace saved reports.

## Getting updates

From the repository root, save or commit your local work, then run `git pull`.
Activate your virtual environment and rerun `python -m pip install -r requirements.txt`
if dependencies changed. Each collaborator creates their own `.venv` and `.env`.
