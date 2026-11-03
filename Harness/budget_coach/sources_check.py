"""Check that every link in guidelines.json still opens, and keep a dated snapshot of the result.

    python dev.py sources-check

Writes Harness/data/sources_check.json (status, page title, date checked per link). The coach itself never
fetches the web: this is the only place that does, and a person runs it before a demo or a release.
Exit code 1 if any link fails. Standard library only.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data" / "sources_check.json"
UA = {"User-Agent": "Mozilla/5.0 (budget-buddy sources-check)"}
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def links(catalog: list[dict]) -> dict[str, list[str]]:
    """url -> the guideline ids that use it."""
    out: dict[str, list[str]] = {}
    for g in catalog:
        for field in ("url", "read_more"):
            if g.get(field):
                out.setdefault(g[field], []).append(g["id"])
    return out


def quote(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, urllib.parse.quote(parts.path, safe="/%()"),
                                    parts.query, parts.fragment))


def check(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(quote(url), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(200_000) if "html" in (resp.headers.get("Content-Type") or "") else b""
            m = TITLE.search(body.decode("utf-8", "replace"))
            return {"status": resp.status, "ok": 200 <= resp.status < 300,
                    "title": re.sub(r"\s+", " ", m.group(1)).strip() if m else None,
                    "final_url": resp.geturl()}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "ok": False, "title": None, "final_url": url}
    except Exception as e:  # DNS, timeout, TLS
        return {"status": None, "ok": False, "title": None, "final_url": url, "error": type(e).__name__}


def main(argv: list[str]) -> int:
    catalog = json.loads((HERE / "guidelines.json").read_text("utf-8"))
    today = datetime.date.today().isoformat()
    by_id = {g["id"]: g for g in catalog}
    results, failed = {}, 0
    for url, ids in links(catalog).items():
        r = check(url)
        by_hand = all(by_id[i].get("checked_by_hand") for i in ids)
        # some sites answer scripts with 403/404 while opening fine in a browser; a person checks those
        verdict = "ok" if r["ok"] else ("hand" if by_hand and r["status"] in (403, 404, 429) else "FAIL")
        results[url] = {**r, "verdict": verdict, "used_by": ids, "checked": today}
        failed += verdict == "FAIL"
        note = f"  (script blocked; hand-checked {by_id[ids[0]]['checked_by_hand']})" if verdict == "hand" else ""
        print(f"{verdict:<4} {r['status']} {','.join(ids):<12} {url}{note}")
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n{len(results) - failed} of {len(results)} links ok or hand-checked. Snapshot: {OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
