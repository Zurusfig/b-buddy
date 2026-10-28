#!/usr/bin/env python3
"""Setup and everyday commands for b-buddy. Standard library only; works on Windows, macOS and Linux.

    python dev.py setup            create .venv, install packages, create Harness/.env
    python dev.py setup --here     install into the Python you are running (conda users)
    python dev.py check            what is installed and what is missing (add --gateway to test the key)
    python dev.py test             the offline tests (no Ollama, no key)
    python dev.py pull             download the small model (--all for the three harness models)
    python dev.py ask "How much did I spend on food in July?"
    python dev.py persona --user 3 "Am I over budget this month?"      (also: persona --list)
    python dev.py eval | eval-persona | eval-gateway                   (extra arguments are passed on)
    python dev.py clean            delete __pycache__ folders

Commands run with the repo's .venv if it exists, otherwise with the Python that runs this file.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HARNESS = ROOT / "Harness"
COACH = HARNESS / "budget_coach"
VENV = ROOT / ".venv"
ENV_FILE = HARNESS / ".env"
ENV_EXAMPLE = HARNESS / ".env.example"
REQUIREMENTS = ROOT / "requirements.txt"

MIN_PYTHON = (3, 10)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
SMALL_MODEL = os.environ.get("COACH_SMALL_MODEL", "qwen3:4b-q4_K_M")
HARNESS_MODELS = ("qwen3:4b-q4_K_M", "qwen3:8b-q4_K_M", "gemma3:12b-it-q4_K_M")
GATEWAY_URL = "https://llm.nattee.net/v1"  # kept equal to agent.GATEWAY_URL by a test
PLACEHOLDER_KEY = "sk-your-key-here"
OLLAMA_DOWNLOAD = "https://ollama.com/download"

OK, WARN, FAIL = "[ok]", "[!!]", "[xx]"


# ----------------------------------------------------------------------------- helpers
def venv_python(venv: Path = VENV) -> Path | None:
    """The interpreter inside a virtual environment, or None if there is no such environment."""
    for rel in ("Scripts/python.exe", "bin/python"):
        p = venv / rel
        if p.exists():
            return p
    return None


def project_python() -> str:
    found = venv_python()
    return str(found) if found else sys.executable


def run(cmd: list[str], cwd: Path = ROOT) -> int:
    """Run a command with the console attached; UTF-8 so Thai text prints on Windows."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        return subprocess.call(cmd, cwd=cwd, env=env)
    except FileNotFoundError:
        print(f"{FAIL} cannot run {cmd[0]!r}")
        return 127


def read_key(env_file: Path = ENV_FILE) -> str | None:
    """GATEWAY_KEY from an env file, or None. The key is never printed by this tool."""
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "GATEWAY_KEY":
            return v.strip().strip('"').strip("'") or None
    return None


def key_status(env_file: Path = ENV_FILE, environ=os.environ) -> str:
    """'environment', 'file', 'placeholder' or 'missing'."""
    if environ.get("GATEWAY_KEY", "").strip():
        return "environment"
    key = read_key(env_file)
    if key is None:
        return "missing"
    return "placeholder" if key == PLACEHOLDER_KEY else "file"


def ensure_env(env_file: Path = ENV_FILE, example: Path = ENV_EXAMPLE) -> str:
    """Create .env from the template if it is absent; never overwrite an existing one."""
    if env_file.exists():
        return "exists"
    shutil.copyfile(example, env_file)
    return "created"


def find_ollama() -> str | None:
    """The ollama executable, including the install folders that are often missing from PATH."""
    found = shutil.which("ollama")
    if found:
        return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path("/Applications/Ollama.app/Contents/Resources/ollama"),
        Path("/usr/local/bin/ollama"),
        Path("/usr/bin/ollama"),
    ]
    return next((str(c) for c in candidates if c.name and c.exists()), None)


def ollama_models(url: str = OLLAMA_URL, opener=urllib.request.urlopen) -> list[str] | None:
    """Names of pulled models, or None when the Ollama server is not reachable."""
    try:
        with opener(url + "/api/tags", timeout=3) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return None


def gateway_status(key: str, url: str = GATEWAY_URL, opener=urllib.request.urlopen) -> tuple[str, str]:
    """('ok'|'rejected'|'unreachable'|'unknown', detail). The key goes only to the gateway."""
    req = urllib.request.Request(url + "/models", headers={
        "Authorization": "Bearer " + key, "User-Agent": "week12-budget-coach/1.0"})
    try:
        with opener(req, timeout=10) as r:
            return "ok", f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "rejected", f"HTTP {e.code}: the key was refused or lacks access"
        return "unknown", f"HTTP {e.code} (the server answered, so it is reachable)"
    except Exception as e:
        return "unreachable", f"{type(e).__name__}: {e}"


def deps_ok(python: str) -> bool:
    code = "import requests, pydantic, yaml"
    return subprocess.call([python, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


# ---------------------------------------------------------------------------- commands
def cmd_setup(args: list[str]) -> int:
    p = argparse.ArgumentParser(prog="dev.py setup")
    p.add_argument("--here", action="store_true", help="install into the current Python, no .venv (conda)")
    a = p.parse_args(args)
    if sys.version_info < MIN_PYTHON:
        print(f"{FAIL} Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required; this is {sys.version.split()[0]}.")
        return 1
    if a.here:
        python = sys.executable
        print(f"Installing into {python}")
    else:
        if venv_python() is None:
            print(f"Creating {VENV} ...")
            import venv
            try:
                venv.EnvBuilder(with_pip=True).create(VENV)
            except Exception as e:
                print(f"{FAIL} could not create a virtual environment: {e}\n"
                      "     On Debian/Ubuntu run: sudo apt install python3-venv. Or use: python dev.py setup --here")
                return 1
        python = str(venv_python())
    print("Installing packages ...")
    if run([python, "-m", "pip", "install", "-q", "-r", str(REQUIREMENTS)]) != 0:
        print(f"{FAIL} pip install failed; read the message above.")
        return 1
    state = ensure_env()
    print(f"{OK} packages installed")
    print(f"{OK} Harness/.env {state}" + (" (add your key to it)" if state == "created" else ""))
    print("\nNext: python dev.py check")
    return 0


def cmd_check(args: list[str]) -> int:
    p = argparse.ArgumentParser(prog="dev.py check")
    p.add_argument("--gateway", action="store_true", help="also test the key against the gateway")
    a = p.parse_args(args)
    required_ok = True
    python = project_python()

    py_ok = sys.version_info >= MIN_PYTHON
    required_ok &= py_ok
    print(f"{OK if py_ok else FAIL} Python {sys.version.split()[0]} (need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)"
          f"  using {'.venv' if venv_python() else 'the current interpreter'}")
    have = deps_ok(python)
    required_ok &= have
    print(f"{OK if have else FAIL} packages (requests, pydantic, pyyaml)"
          + ("" if have else "  -> run: python dev.py setup"))

    ks = key_status()
    print({"environment": f"{OK} GATEWAY_KEY found in your environment",
           "file": f"{OK} GATEWAY_KEY found in Harness/.env",
           "placeholder": f"{WARN} Harness/.env still has the placeholder key; edit it (needed for advice questions)",
           "missing": f"{WARN} no GATEWAY_KEY; run setup, then edit Harness/.env (needed for advice questions)"}[ks])

    exe = find_ollama()
    if exe:
        on_path = shutil.which("ollama") is not None
        print(f"{OK} Ollama installed at {exe}" + ("" if on_path else "  (not on PATH; dev.py finds it anyway)"))
    else:
        print(f"{WARN} Ollama not found. Install it from {OLLAMA_DOWNLOAD} (needed for local questions)")
    models = ollama_models()
    if models is None:
        print(f"{WARN} Ollama server not reachable at {OLLAMA_URL}. Open the Ollama app or run: ollama serve")
    else:
        has_small = any(m == SMALL_MODEL or m.startswith(SMALL_MODEL) for m in models)
        print(f"{OK if has_small else WARN} small model {SMALL_MODEL} "
              + ("is pulled" if has_small else "is missing; run: python dev.py pull"))
        extra = [m for m in HARNESS_MODELS if m != SMALL_MODEL and m not in models]
        if extra:
            print(f"{WARN} harness demos also use: {', '.join(extra)} (python dev.py pull --all; optional)")

    persona = (ROOT / "persona" / "csv" / "Transaction.csv").exists()
    print(f"{OK if persona else WARN} persona data " + ("found" if persona else
          "missing: persona/ is not in this checkout (only the persona commands need it)"))

    if a.gateway:
        key = os.environ.get("GATEWAY_KEY", "").strip() or read_key()
        if not key or key == PLACEHOLDER_KEY:
            print(f"{WARN} gateway not tested: no real key")
        else:
            status, detail = gateway_status(key)
            print(f"{OK if status in ('ok', 'unknown') else FAIL} gateway {GATEWAY_URL}: {status} ({detail})")
    print("\n" + ("Ready." if required_ok else "Fix the [xx] items above first."))
    return 0 if required_ok else 1


def cmd_test(args: list[str]) -> int:
    verbose = ["-v"] if "-v" in args or "--verbose" in args else []
    return run([project_python(), "-m", "unittest", "discover", "-s", "tests", *verbose], cwd=HARNESS)


def cmd_pull(args: list[str]) -> int:
    p = argparse.ArgumentParser(prog="dev.py pull")
    p.add_argument("--all", action="store_true", help="pull the three models the harness demos use")
    a = p.parse_args(args)
    exe = find_ollama()
    if not exe:
        print(f"{FAIL} Ollama is not installed. Get it from {OLLAMA_DOWNLOAD}, then run this again.")
        return 1
    if ollama_models() is None:
        print(f"{WARN} the Ollama server is not running; open the Ollama app or run `ollama serve` first.")
        return 1
    for model in (HARNESS_MODELS if a.all else (SMALL_MODEL,)):
        print(f"Pulling {model} ...")
        code = run([exe, "pull", model])
        if code != 0:
            return code
    return 0


def cmd_ask(args: list[str]) -> int:
    flags = [a for a in args if a.startswith("--")]
    question = " ".join(a for a in args if not a.startswith("--"))
    return run([project_python(), "agent.py", question, *flags] if question
               else [project_python(), "agent.py", *flags], cwd=COACH)


def cmd_persona(args: list[str]) -> int:
    return run([project_python(), "persona_agent.py", *args], cwd=COACH)


def _script(name: str):
    return lambda args: run([project_python(), name, *args], cwd=COACH)


def cmd_clean(args: list[str]) -> int:
    n = 0
    for d in ROOT.rglob("__pycache__"):
        if VENV in d.parents or ".git" in d.parts:
            continue
        shutil.rmtree(d, ignore_errors=True)
        n += 1
    print(f"removed {n} __pycache__ folders")
    return 0


COMMANDS = {
    "setup": cmd_setup, "check": cmd_check, "test": cmd_test, "pull": cmd_pull, "ask": cmd_ask,
    "persona": cmd_persona, "eval": _script("eval_routed.py"), "eval-persona": _script("eval_persona.py"),
    "eval-gateway": _script("eval_agent.py"), "clean": cmd_clean,
}


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if argv[0] not in COMMANDS:
        print(f"unknown command {argv[0]!r}. Commands: {', '.join(COMMANDS)}")
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
