"""Advice that always carries a source. Code picks the tip and writes the source; the model only phrases the advice.

    pick("How can I make sure I save each month?", facts)  -> "G04"
    footer(guideline, "th")  -> "แหล่งอ้างอิง: ... / อ่านเพิ่มเติม: https://..."

Why code and not the model: the same situation must always give the same tip and the same link, and a model
can invent a URL. The catalog (guidelines.json) is the cache: a vetted snapshot, read offline. Run
`python dev.py sources-check` to see which links still open.

`facts` come from the student's own numbers (see persona_agent.advice_facts):
    {"over_budget": ["entertainment", ...], "has_budget": bool, "net": float, "subscriptions_over": bool}
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = {g["id"]: g for g in json.loads((HERE / "guidelines.json").read_text("utf-8"))}

# First match wins, so more specific topics come first. Thai and English in one pattern.
KEYWORDS = (
    ("G08", r"credit card|บัตรเครดิต|ขั้นต่ำ|minimum payment"),
    ("G11", r"chargeback|still (?:being )?(?:charged|billed)|ยกเลิกแล้ว"),
    ("G03", r"subscription|netflix|spotify|youtube premium|สมาชิก|รายเดือน"),
    ("G02", r"emergency|ฉุกเฉิน"),
    ("G07", r"repair|irregular|unexpected|ซ่อม|ไม่คาดคิด|ไม่แน่นอน"),
    ("G05", r"track|ติดตาม|จดบันทึก|บันทึกรายจ่าย|ทำบัญชี"),
    ("G01", r"split|50/30/20|ratio|แบ่ง(?:เงิน)?เดือน|สัดส่วน"),
    ("G04", r"save something|how .*save|เก็บเงินก่อน|ออมก่อน|ออมเงิน|เก็บเงิน"),
    ("G09", r"saving goal|goal|เป้าหมาย"),
    ("G06", r"running out|run out|runs out|before the end|last (?:until|till|through)|(?:until|till|by) (?:the )?end of "
           r"(?:the |this )?month|หมดก่อน|ไม่พอใช้|หมดเร็ว|ให้พอ(?:ใช้)?(?:ถึง|จน)|ถึงสิ้นเดือน|จนสิ้นเดือน|ก่อนสิ้นเดือน"),
)
DEFAULT_GID = "G04"


def pick_match(question: str, facts: dict | None = None) -> tuple[str, bool]:
    """(guideline id, whether the question's topic matched a tip). Deterministic: same input, same result.

    Built-in KEYWORDS come first, then any `match` pattern a guideline carries in guidelines.json (this is how
    tips approved through `dev.py sources-approve` become findable). With no topic match the id comes from
    the student's numbers and the second value is False, so the reply can say it is a general tip.
    """
    q = (question or "").lower()
    for gid, pattern in KEYWORDS:
        if re.search(pattern, q):
            return gid, True
    for gid, g in CATALOG.items():
        if g.get("match") and re.search(g["match"], q):
            return gid, True
    f = facts or {}
    if f.get("over_budget"):
        return ("G03" if "subscriptions" in f["over_budget"] else "G06"), False
    if f.get("has_budget") is False:
        return "G05", False
    if (f.get("net") or 0) < 0:
        return "G01", False
    return DEFAULT_GID, False


def menu() -> str:
    """One line per tip (id and title), for the large model to choose from when no keyword matched."""
    return "\n".join(f"{gid}: {g['title']}" for gid, g in CATALOG.items())


def pick(question: str, facts: dict | None = None) -> str:
    return pick_match(question, facts)[0]


# Questions with no topic match are queued here so a person can add a tip for them (dev.py sources-misses).
MISSES_PATH = HERE.parent / "data" / "tip_misses.jsonl"


def log_miss(question: str, gid: str, lang: str) -> None:
    """Append one line; never raises (advice must not fail because a log file is unwritable)."""
    try:
        MISSES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MISSES_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                "question": question, "lang": lang, "served": gid}, ensure_ascii=False) + "\n")
    except OSError:
        pass


LABELS = {"en": ("Source", "Read more", "Also"), "th": ("แหล่งอ้างอิง", "อ่านเพิ่มเติม", "ดูเพิ่ม")}


def tip_text(g: dict, lang: str) -> str:
    return g.get("tip_th") if lang == "th" and g.get("tip_th") else g["tip"]


def source_info(gid: str) -> dict:
    g = CATALOG[gid]
    return {"id": gid, "title": g["title"], "source": g["source"], "url": g.get("url"),
            "read_more": g.get("read_more"), "read_more_title": g.get("read_more_title")}


def footer(gid: str, lang: str) -> str:
    """The source lines, built from the catalog only, in the question's language."""
    g = CATALOG[gid]
    src_label, more_label, also_label = LABELS.get(lang, LABELS["en"])
    lines = [f"{src_label}: {g['source']} [{gid}]"]
    if g.get("url"):
        lines.append(f"{more_label}: {g['url']}")
    if g.get("read_more"):
        label = also_label if g.get("url") else more_label
        title = f" ({g['read_more_title']})" if g.get("read_more_title") else ""
        lines.append(f"{label}{title}: {g['read_more']}")
    return "\n".join(lines)


GID = re.compile(r"\[G\d{2}\]")


NO_MATCH_NOTE = {
    "en": "I don't have a tip for this exact topic yet, so this is a general one.",
    "th": "ยังไม่มีคำแนะนำเฉพาะสำหรับหัวข้อนี้ นี่เป็นคำแนะนำทั่วไป",
}


def attach_source(answer: str, gid: str, lang: str, fetched: list[str],
                  matched: bool = True) -> tuple[str, list[str]]:
    """Reply with the chosen tip's source attached. Returns (text, flags).

    - ids in the model's text that are not the chosen one are removed, so the reply names one tip
    - if the model never fetched the chosen tip, the catalog's tip text is added in the question's language
    """
    flags = []
    text = GID.sub(lambda m: m.group(0) if m.group(0) == f"[{gid}]" else "", answer).strip()
    if gid not in fetched:
        flags.append("source_added")
        text = f"{text}\n\n{tip_text(CATALOG[gid], lang)}".strip()
    if fetched and any(f != gid for f in fetched):
        flags.append("source_overridden")
    if not matched:
        flags.append("no_topic_match")
        text = f"{text}\n\n{NO_MATCH_NOTE.get(lang, NO_MATCH_NOTE['en'])}"
    return f"{text}\n\n{footer(gid, lang)}", flags
