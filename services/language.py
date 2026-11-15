"""Tell Azerbaijani, Russian and English apart, cheaply and offline.

Rules, in order:
1. Mostly Cyrillic letters -> Russian.
2. Any Azerbaijani-only Latin letter (ə, ğ, ı, ö, ü, ş, ç) -> Azerbaijani.
3. Otherwise count common Azerbaijani vs English words, because many people
   type Azerbaijani without special letters ("salam, qiymet nece?").
4. Too little signal (a number, "ok") -> keep the language we already had.
"""

from __future__ import annotations

import re

from services.models import DEFAULT_LANGUAGE

_AZ_LETTERS = frozenset("əƏğĞıİöÖüÜşŞçÇ")

_AZ_WORDS = frozenset(
    """
    salam salamlar necə nece neçə neçəyə neceye qiymət qiymet qiymətlər qiymetler harada harda haradasınız
    haradasiniz ünvan unvan yox var sabah bugün bugun saat növbə novbe istəyirəm isteyirem zəhmət zehmet
    təşəkkür tesekkur sağol sagol olar mən siz sizin nə qədər qeder saç sac kəsim kesim bərbər berber açıq
    aciq bağlı bagli lazımdır lazimdir edirsiniz xahiş xahis ilə ile üçün ucun və nədir nedir işləyirsiniz
    isleyirsiniz kişi kisi uşaq usaq saqqal yazılmaq yazilmaq yazmaq gün gun hansı hansi
    """.split()
)

_EN_WORDS = frozenset(
    """
    hi hello hey the a an is are do does you your i my me we can could would how what when where which
    much price prices cost open close closed hours address book booking appointment haircut beard
    please thanks thank want need have there time today tomorrow for to and of in on at it this that
    """.split()
)

_WORD_RE = re.compile(r"[^\W\d_]+")


def detect_language(text: str, fallback: str = DEFAULT_LANGUAGE) -> str:
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 2:
        return fallback

    cyrillic = sum("Ѐ" <= ch <= "ӿ" for ch in letters)
    if cyrillic * 2 >= len(letters):
        return "ru"
    if any(ch in _AZ_LETTERS for ch in text):
        return "az"

    words = _WORD_RE.findall(text.casefold())
    az_hits = sum(w in _AZ_WORDS for w in words)
    en_hits = sum(w in _EN_WORDS for w in words)
    if az_hits > en_hits:
        return "az"
    if en_hits > 0:
        return "en"
    # Unknown Latin words: only switch to English if there is a real sentence, not "ok" or a name.
    return "en" if len(words) >= 3 else fallback
