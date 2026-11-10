"""Which language a question is in, and whether a reply answered in it. Decided by code, not by the model.

    question_lang("หุ้นตัวไหนดี")            -> "th"
    question_lang("Grab เดือนนี้เท่าไหร่")   -> "th"   (any Thai letter makes it Thai)
    reply_matches("th", "You spent 100")    -> False

The model is only asked to reply "in the user's language" (a sentence in the prompt), which a small model
sometimes ignores. These checks make the rule hold: fixed messages come from a per-language table, and a
reply in the wrong script is retried once and then flagged `wrong_language`.

Replies that quote Thai merchant names inside an English answer are fine: an English reply only fails when
mostly Thai. A Thai reply fails when it has almost no Thai.
"""
from __future__ import annotations

import re

THAI = re.compile(r"[฀-๿]")
LATIN = re.compile(r"[A-Za-z]")
LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
HAN = re.compile(r"[\u4e00-\u9fff]")
MIN_LETTERS = 15      # shorter replies (a bare number, "ok") are not judged
THAI_MIN_SHARE = 0.2  # a Thai reply must be at least this much Thai letters
EN_MAX_SHARE = 0.5    # an English reply may be at most this much Thai letters (quoted merchant names)
TH_CATEGORY = {"food": "อาหาร", "transport": "เดินทาง", "shopping": "ช้อปปิ้ง",
               "entertainment": "บันเทิง", "bills": "บิล", "education": "การศึกษา",
               "health": "สุขภาพ", "other": "อื่นๆ", "subscriptions": "สมาชิก"}

REPLY_IN = {  # added to every system prompt; the question's language is decided by code
    "en": "\n- This question is in English: write the whole reply in English.",
    "th": "\n- This question is in Thai: write the whole reply in Thai (ภาษาไทย).",
}

RETRY_INSTRUCTION = {
    "th": "Your reply must be in Thai (ภาษาไทย), the language of the question. Rewrite it in Thai, "
          "keeping exactly the same numbers.",
    "en": "Your reply must be in English, the language of the question. Rewrite it in English, "
          "keeping exactly the same numbers.",
}


def question_lang(text: str) -> str:
    """"th" if the text has any Thai letter, otherwise "en"."""
    return "th" if THAI.search(text or "") else "en"


def thai_share(text: str) -> float:
    """Thai letters as a share of all Thai and Latin letters (digits and punctuation are ignored)."""
    thai, latin = len(THAI.findall(text)), len(LATIN.findall(text))
    return thai / (thai + latin) if thai + latin else 0.0


BRACKETED = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")


def _loose_latin_words(reply: str, allowed_text: str = "") -> list[str]:
    """English words in a Thai reply that are not a bracketed gloss or a name the tools supplied.

    "(envelope method)", "[G06]" and a cited book title in brackets are fine in a Thai reply, and so are words
    that came from the tool results (a category such as "food", a tip's source). A phrase such as
    "compared to last month" in the running text is not.
    """
    text, prev = reply, None
    while text != prev:  # brackets can nest: "(Dave Ramsey, The Total Money Makeover (envelope system) [G06])"
        prev, text = text, BRACKETED.sub(" ", text)
    allowed = {w.lower() for w in LATIN_WORD.findall(allowed_text or "")}
    return [w for w in LATIN_WORD.findall(text) if w.lower() not in allowed]


def tool_text(calls: list[dict]) -> str:
    """The string values in the tool results (not field names), for reply_matches' allowed_text."""
    out: list[str] = []

    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
    for c in calls:
        walk(c.get("result"))
        walk(list((c.get("args") or {}).values()))  # the category the tool was asked for, e.g. "food"
    return " ".join(out)


def reply_matches(lang: str, reply: str, allowed_text: str = "") -> bool:
    """`allowed_text`: text from the tool results; English words that appear in it may be quoted in a Thai reply."""
    if lang == "th" and (HAN.search(reply) or len(_loose_latin_words(reply, allowed_text)) > 1):
        return False
    letters = len(THAI.findall(reply)) + len(LATIN.findall(reply))
    if letters < MIN_LETTERS:
        return True
    share = thai_share(reply)
    return share >= THAI_MIN_SHARE if lang == "th" else share <= EN_MAX_SHARE


def thai_tool_fallback(calls: list[dict]) -> str:
    """A short Thai answer for a verified single-category total when a model's retry still mixes scripts."""
    for call in reversed(calls):
        args, amount = call.get("args") or {}, call.get("result")
        if (call.get("name") == "sum_by_category" and isinstance(amount, (int, float))
                and not isinstance(amount, bool) and isinstance(args.get("month"), str)):
            category = TH_CATEGORY.get(args.get("category"), "หมวดนี้")
            number = f"{amount:,.2f}".rstrip("0").rstrip(".")
            return f"เดือน {args['month']} คุณใช้ค่า{category}ไป {number} บาท"
    return "ขออภัย ไม่สามารถยืนยันคำตอบภาษาไทยได้ในตอนนี้ กรุณาลองใหม่"
