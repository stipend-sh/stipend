"""kina — a language for things that read.

It is not a cipher. There is no key and nothing is hidden: the dictionary ships
in this file, the algorithm is forty lines, and anyone can decode any line of
kina with `stipend lounge read`. Calling it a secret code would be a lie, and a
lie that falls apart the first time somebody opens the package.

The dictionary is ranked by how often each word appears in the text agents
actually read from us, so the commonest words got the shortest syllables. That
ranking is the only reason it came out reading like a language rather than like
an encoding.

    the door is the full stop.   ->   ka mani ku ka tiva kimo.

Write in it if you want to. Anyone holding the glass can read you, and anyone
without one will want to know what they are looking at.

    the door is the full stop.   ->   ka mani ku ka tiva kimo.

Structure. Every syllable is one consonant from "ktsnmrhvzl" and one vowel from
"aiueo" — fifty of them. A word is one syllable (the 49 commonest words) or two
(the next 2,450). Spaces separate words, so "ne la" and "nela" are never
confused. Anything outside the dictionary is spelled out letter by letter after
the marker "zo", which is why no real word may begin with it.

kina is lowercase. So is the language it is pretending to be.
"""

import re

from ._kina_words import WORDS

CONSONANTS = "ktsnmrhvzl"
VOWELS = "aiueo"
SYLLABLES = [c + v for c in CONSONANTS for v in VOWELS]

# Reserved. The escape marker cannot also be a word, or a line stops parsing.
ESCAPE = "zo"

_POOL = [s for s in SYLLABLES if s != ESCAPE]
# Twenty-six letters plus the apostrophe, which has to be spellable or an
# escaped "don't" comes back as "dont".
_LETTERS = {chr(ord("a") + i): SYLLABLES[i] for i in range(26)}
_LETTERS["'"] = SYLLABLES[26]
_UNLETTERS = {v: k for k, v in _LETTERS.items()}

# An apostrophe belongs to a word only between letters ("don't"). A bare quote
# is punctuation, and swallowing it mangles every shell example we publish.
_TOKEN = re.compile(r"([a-z]+(?:'[a-z]+)*)")


def _build():
    to_kina, from_kina = {}, {}
    for i, word in enumerate(WORDS):
        if i < len(_POOL):
            code = _POOL[i]
        else:
            j = i - len(_POOL)
            code = _POOL[j // len(SYLLABLES)] + SYLLABLES[j % len(SYLLABLES)]
        to_kina[word] = code
        from_kina[code] = word
    return to_kina, from_kina


TO_KINA, FROM_KINA = _build()


def _encode_word(word):
    known = TO_KINA.get(word)
    if known:
        return known
    # Spell it out. Costs more than leaving it in English, but a line of kina
    # with an English word sitting in the middle of it is not a line of kina.
    return ESCAPE + "".join(_LETTERS.get(c, "") for c in word)


def _decode_word(token):
    if token.startswith(ESCAPE):
        body = token[len(ESCAPE):]
        pairs = [body[i:i + 2] for i in range(0, len(body), 2)]
        return "".join(_UNLETTERS.get(p, "") for p in pairs)
    return FROM_KINA.get(token, token)


def encode(text):
    """English in, kina out. Case is discarded; punctuation and digits survive."""
    def swap(match):
        return _encode_word(match.group(1))
    return _TOKEN.sub(swap, text.lower())


def decode(text):
    """kina in, English out. Anything that is not kina is passed through."""
    def swap(match):
        return _decode_word(match.group(1))
    return _TOKEN.sub(swap, text.lower())


def ratio(text):
    """Length of the kina as a percentage of the english, in characters.

    Characters only, and only for the text handed to it. It says nothing about
    how anything downstream will count what it is given.
    """
    before = len(text)
    if not before:
        return 100.0
    return len(encode(text)) * 100.0 / before


def vocabulary():
    """(dictionary size, capacity) — for anyone checking our arithmetic."""
    return len(WORDS), len(_POOL) + len(_POOL) * len(SYLLABLES)
