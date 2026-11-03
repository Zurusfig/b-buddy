"""The review queue for new advice tips: see what students asked that no tip covered, and approve new tips.

    python dev.py sources-misses          questions with no matching tip, grouped (data/tip_misses.jsonl)
    python dev.py sources-pending         candidate tips waiting for a person (data/tips_pending.json)
    python dev.py sources-approve          show each candidate, check its link, ask y/n, then save it
    python dev.py sources-approve --ids P01,P03 --yes       approve named candidates without prompts

Candidates are written to tips_pending.json after someone has searched for an official source and read the page
(the coach itself never searches the web). Nothing reaches students until it is approved here, and approval
sets `checked_by_hand` in guidelines.json. Standard library only.

A candidate looks like:
    {"pending_id": "P01", "topic": "food delivery", "match": "delivery|grab ?food|เดลิเวอรี่",
     "title": "...", "tip": "...", "tip_th": "...", "source": "Organisation: page title", "url": "https://...",
     "evidence": "a short quote from the page that the tip is based on", "found": "2026-11-02"}
"""
from __future__ import annotations

import collections
import datetime
import json
import re
import sys
from pathlib import Path

import sources_check

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
CATALOG_PATH = HERE / "guidelines.json"
PENDING_PATH = DATA / "tips_pending.json"
MISSES_PATH = DATA / "tip_misses.jsonl"
REQUIRED = ("pending_id", "match", "title", "tip", "tip_th", "source", "url", "evidence")
THAI = re.compile(r"[฀-๿]")


def load_json(path: Path, default):
    return json.loads(path.read_text("utf-8")) if path.exists() else default


def problems(c: dict) -> list[str]:
    """Why a candidate cannot be approved yet (empty list means it can)."""
    out = [f"missing {k}" for k in REQUIRED if not str(c.get(k) or "").strip()]
    if c.get("url") and not str(c["url"]).startswith("https://"):
        out.append("url must start with https://")
    if c.get("tip_th") and not THAI.search(c["tip_th"]):
        out.append("tip_th has no Thai letters")
    try:
        re.compile(c.get("match") or "")
    except re.error as e:
        out.append(f"match is not a valid pattern: {e}")
    return out


def next_id(catalog: list[dict]) -> str:
    return f"G{max(int(g['id'][1:]) for g in catalog) + 1:02d}"


def approve(candidate: dict, catalog: list[dict], today: str | None = None) -> dict:
    """The catalog entry for an approved candidate (not yet saved)."""
    bad = problems(candidate)
    if bad:
        raise ValueError(f"{candidate.get('pending_id')}: " + "; ".join(bad))
    entry = {"id": next_id(catalog)}
    for k in ("title", "tip", "tip_th", "source", "url", "match"):
        entry[k] = candidate[k]
    entry["checked_by_hand"] = today or datetime.date.today().isoformat()
    return entry


def save_catalog(catalog: list[dict]) -> None:
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_misses() -> int:
    rows = [json.loads(x) for x in MISSES_PATH.read_text("utf-8").splitlines() if x.strip()] if MISSES_PATH.exists() else []
    if not rows:
        print("No unmatched questions yet.")
        return 0
    seen = collections.Counter(r["question"].strip().lower() for r in rows)
    print(f"{len(rows)} unmatched questions ({len(seen)} different):\n")
    for q, n in seen.most_common():
        print(f"  {n:>3}x  {q}")
    print("\nSearch for an official source for the common topics, put candidates in "
          f"{PENDING_PATH.name}, then run: python dev.py sources-approve")
    return 0


def cmd_pending() -> int:
    pending = load_json(PENDING_PATH, [])
    if not pending:
        print("Nothing waiting for review.")
        return 0
    for c in pending:
        bad = problems(c)
        print(f"{c.get('pending_id')}  {c.get('topic', '')}: {c.get('title')}\n    {c.get('source')}\n    {c.get('url')}"
              + (f"\n    NOT READY: {'; '.join(bad)}" if bad else ""))
    return 0


def ask_yes(prompt: str) -> bool:
    try:
        return input(prompt + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def cmd_approve(ids: set[str] | None, assume_yes: bool) -> int:
    pending = load_json(PENDING_PATH, [])
    catalog = load_json(CATALOG_PATH, [])
    if not pending:
        print("Nothing waiting for review.")
        return 0
    keep, added = [], []
    for c in pending:
        if ids is not None and c.get("pending_id") not in ids:
            keep.append(c)
            continue
        bad = problems(c)
        if bad:
            print(f"{c.get('pending_id')} skipped: {'; '.join(bad)}")
            keep.append(c)
            continue
        r = sources_check.check(c["url"])
        link = "opens" if r["ok"] else f"did not open from a script (status {r['status']}); open it in a browser first"
        print(f"\n{c['pending_id']}  {c.get('topic', '')}\n  tip:  {c['tip']}\n  thai: {c['tip_th']}\n  source: {c['source']}\n"
              f"  link: {c['url']} ({link})\n  based on: \"{c['evidence']}\"\n  matches questions like: {c['match']}")
        if assume_yes or ask_yes("Approve (you opened the link and the tip matches the page)?"):
            entry = approve(c, catalog)
            catalog.append(entry)
            added.append(entry["id"])
            print(f"  saved as {entry['id']}")
        else:
            keep.append(c)
    if added:
        save_catalog(catalog)
    PENDING_PATH.write_text(json.dumps(keep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nApproved: {', '.join(added) or 'none'}. Still waiting: {len(keep)}.")
    return 0


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    cmd = argv[0] if argv else "pending"
    if cmd == "misses":
        return cmd_misses()
    if cmd == "pending":
        return cmd_pending()
    if cmd == "approve":
        ids = None
        if "--ids" in argv:
            ids = set(argv[argv.index("--ids") + 1].split(","))
        return cmd_approve(ids, "--yes" in argv)
    print("usage: tips_review.py misses|pending|approve [--ids P01,P02] [--yes]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
