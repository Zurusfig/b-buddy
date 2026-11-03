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
MIN_LETTERS = 15      # shorter replies (a bare number, "ok") are not judged
THAI_MIN_SHARE = 0.2  # a Thai reply must be at least this much Thai letters
EN_MAX_SHARE = 0.5    # an English reply may be at most this much Thai letters (quoted merchant names)

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


def reply_matches(lang: str, reply: str) -> bool:
    letters = len(THAI.findall(reply)) + len(LATIN.findall(reply))
    if letters < MIN_LETTERS:
        return True
    share = thai_share(reply)
    return share >= THAI_MIN_SHARE if lang == "th" else share <= EN_MAX_SHARE
