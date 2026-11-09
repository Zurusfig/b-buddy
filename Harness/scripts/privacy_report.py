"""Check what left this computer: every request the coach sent to the course gateway, read from the log.

    python Harness/scripts/privacy_report.py                    # whole log
    python Harness/scripts/privacy_report.py --since 2026-11-09  # only requests on or after a date
    python Harness/scripts/privacy_report.py --log path/to/coach_calls.jsonl

The design promises that the large model on the gateway sees computed totals only: no transaction rows,
no purchase descriptions, no dates of single purchases, no user id or email. agent.py logs each gateway
request as a `coach_gateway_request` line with its exact messages; this script scans them and prints
one summary. Exit code 1 means at least one request carried raw data.

What is checked:
  - tools offered:   get_transactions (the only raw-row tool) must not be offered to the gateway
  - tool results:    no row with both a date and a description, no full date (2026-10-14), and no
                     purchase description known from the persona data or from local get_transactions results
                     (the tip text from lookup_guideline is the curated tip store, not user data, and is skipped)
  - every message:   no email address and no userId / user_id field
The question text is the user's own words and goes to the gateway on the advice route (the design says so);
it is counted, not scanned.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = ROOT / "Harness" / "logs" / "coach_calls.jsonl"
PERSONA_TRANSACTIONS = ROOT / "persona" / "csv" / "Transaction.csv"
RAW_TOOLS = {"get_transactions"}
CURATED_TOOLS = {"lookup_guideline"}

FULL_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
USER_FIELD = re.compile(r"\"?\b(?:userId|user_id)\b\"?\s*:", re.I)
MIN_DESCRIPTION_CHARS = 3


def load_log(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text("utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def known_descriptions(rows: list[dict], persona_csv: Path | None = PERSONA_TRANSACTIONS) -> set[str]:
    """Purchase descriptions that count as raw data: the persona rows plus anything get_transactions returned."""
    found: set[str] = set()
    if persona_csv and persona_csv.exists():
        with open(persona_csv, encoding="utf-8", newline="") as f:
            found |= {r["description"] for r in csv.DictReader(f) if r.get("description")}
    for r in rows:
        if r.get("event") == "coach_tool_call" and r.get("tool") in RAW_TOOLS and r.get("result"):
            try:
                result = json.loads(r["result"])
            except (TypeError, ValueError):
                continue
            if isinstance(result, list):
                found |= {x.get("description") or x.get("merchant") for x in result if isinstance(x, dict)}
    return {d.strip() for d in found if d and len(d.strip()) >= MIN_DESCRIPTION_CHARS}


def tool_results(messages: list[dict]) -> list[tuple[str, object]]:
    """(tool name, result) for every tool result inside one request, in either message format agent.py uses."""
    names, out = {}, []
    for m in messages:
        for c in m.get("tool_calls") or []:
            names[c.get("id")] = c.get("function", {}).get("name", "")
        content = m.get("content")
        if m.get("role") == "tool":
            try:
                out.append((names.get(m.get("tool_call_id"), ""), json.loads(content)))
            except (TypeError, ValueError):
                out.append((names.get(m.get("tool_call_id"), ""), content))
        elif m.get("role") == "user" and isinstance(content, str) and content.startswith("<tool_results>"):
            body = content.split("\n", 1)[1].rsplit("</tool_results>", 1)[0] if "\n" in content else ""
            try:
                out.extend((x.get("tool", ""), x.get("result")) for x in json.loads(body))
            except (TypeError, ValueError, AttributeError):
                out.append(("", body))
    return out


def _is_row(value) -> bool:
    return isinstance(value, dict) and "date" in value and ("description" in value or "merchant" in value)


def _has_rows(value) -> bool:
    if _is_row(value):
        return True
    if isinstance(value, dict):
        return any(_has_rows(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_rows(v) for v in value)
    return False


def check_request(req: dict, question: str | None, descriptions: set[str]) -> list[str]:
    """Problems found in one gateway request ([] = totals only)."""
    problems = []
    messages = req.get("messages") or []
    offered = set(req.get("tools") or [])
    if offered & RAW_TOOLS:
        problems.append("raw-row tool offered: " + ", ".join(sorted(offered & RAW_TOOLS)))
    for name, result in tool_results(messages):
        if name in CURATED_TOOLS:
            continue
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        if _has_rows(result):
            problems.append(f"{name or 'tool'} result contains transaction rows")
        if m := FULL_DATE.search(text):
            problems.append(f"{name or 'tool'} result contains a full date {m.group(0)}")
        hits = sorted(d for d in descriptions if d in text)
        if hits:
            problems.append(f"{name or 'tool'} result contains purchase descriptions: " + ", ".join(hits[:5]))
    for m in messages:
        content = m.get("content")
        if not isinstance(content, str) or content == question:
            continue
        if e := EMAIL.search(content):
            problems.append(f"{m.get('role')} message contains an email address {e.group(0)}")
        if USER_FIELD.search(content):
            problems.append(f"{m.get('role')} message contains a user id field")
    return problems


def report(rows: list[dict], since: str = "", descriptions: set[str] | None = None) -> tuple[str, int]:
    """(printable report, number of requests with a problem)."""
    descriptions = known_descriptions(rows) if descriptions is None else descriptions
    questions = {r.get("run_id"): r for r in rows if r.get("event") == "coach_question"}
    requests_ = [r for r in rows if r.get("event") == "coach_gateway_request" and (r.get("ts") or "") >= since]
    bad, lines, runs, with_question = 0, [], set(), 0
    for req in requests_:
        q = questions.get(req.get("run_id"), {}).get("question")
        runs.add(req.get("run_id"))
        if q and any(m.get("content") == q for m in req.get("messages") or []):
            with_question += 1
        problems = check_request(req, q, descriptions)
        if problems:
            bad += 1
            lines.append(f"  [xx] {req.get('ts')} run {req.get('run_id')} ({req.get('model')}):")
            lines.extend(f"       - {p}" for p in problems)
    head = [
        "Gateway privacy report" + (f" (since {since})" if since else ""),
        f"  gateway requests:            {len(requests_)} in {len(runs)} questions",
        f"  requests with raw data:      {bad}",
        f"  requests carrying the user's question text: {with_question} (expected on the advice route)",
        f"  purchase descriptions known: {len(descriptions)}",
    ]
    if not requests_:
        head.append("  No gateway requests logged yet. Ask an advice question, or run scripts/grade.py, then rerun.")
    elif not bad:
        head.append("  [ok] Every request held computed totals and tips only.")
    return "\n".join(head + lines), bad


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--log", type=Path, default=DEFAULT_LOG)
    p.add_argument("--since", default="", help="only requests logged on or after this date/time (YYYY-MM-DD)")
    a = p.parse_args(argv)
    if not a.log.exists():
        print(f"No log at {a.log}")
        return 1
    text, bad = report(load_log(a.log), a.since)
    print(text)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
