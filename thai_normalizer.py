"""Thai text normalization for TTS.

The number-to-Thai and ๆ (mai yamok) expansion logic below is derived
from PyThaiTTS (pythaitts.preprocess) — see
https://github.com/PyThaiNLP/PyThaiTTS — licensed under the Apache License,
Version 2.0. The number-to-Thai functions are vendored verbatim;
``expand_maiyamok`` carries localized enhancements over the upstream
original: it leaves a ๆ untouched when it is mentioned inside a quote/code
span rather than used as a repetition mark (see its docstring and issue #1),
it keeps a bare ๆ (one with nothing valid to repeat) verbatim instead of
silently skipping it (issue #4), and -- when explicitly enabled via the
``segmenter`` argument -- it uses pythainlp to repeat only the last *word*
before a used ๆ rather than the whole Thai run (issue #2).
These functions are pure Python (only the stdlib ``re``) by default and do
not pull in any TTS model dependencies, which is why they are vendored here
rather than installed via ``pip install pythaitts`` (that package would try
to download TTS model weights). The optional ``segmenter="pythainlp"`` path
(issue #2) pulls in the ``pythainlp`` package, an *optional* dependency that
callers install themselves; the default path stays stdlib-only.

The wrapper ``normalize_for_tts`` adds one small enhancement on top: it strips
thousands separators between digits (``1,200`` -> ``1200``) before number
conversion, so formatted numbers read correctly.
"""

from __future__ import annotations

import re

# --- Begin vendored code from PyThaiTTS/pythaitts/preprocess.py -------------

THAI_ONES = ["", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
THAI_TENS = [
    "",
    "สิบ",
    "ยี่สิบ",
    "สามสิบ",
    "สี่สิบ",
    "ห้าสิบ",
    "หกสิบ",
    "เจ็ดสิบ",
    "แปดสิบ",
    "เก้าสิบ",
]


def _num_to_thai_under_hundred(num: int) -> str:
    if num == 0:
        return "ศูนย์"
    elif num < 10:
        return THAI_ONES[num]
    elif num < 20:
        if num == 10:
            return "สิบ"
        elif num == 11:
            return "สิบเอ็ด"
        else:
            return "สิบ" + THAI_ONES[num % 10]
    elif num < 100:
        tens = num // 10
        ones = num % 10
        result = THAI_TENS[tens]
        if ones == 1:
            result += "เอ็ด"
        elif ones > 1:
            result += THAI_ONES[ones]
        return result
    return ""


def _num_to_thai_under_thousand(num: int) -> str:
    if num < 100:
        return _num_to_thai_under_hundred(num)

    hundreds = num // 100
    remainder = num % 100

    if hundreds == 1:
        result = "หนึ่งร้อย"
    elif hundreds == 2:
        result = "สองร้อย"
    else:
        result = THAI_ONES[hundreds] + "ร้อย"

    if remainder > 0:
        result += _num_to_thai_under_hundred(remainder)

    return result


def num_to_thai(num_str: str) -> str:
    """Convert a number string to Thai text. Supports integers and decimals."""
    # Handle decimal numbers
    if "." in num_str:
        integer_part, decimal_part = num_str.split(".")
        result = num_to_thai(integer_part) + "จุด"
        for digit in decimal_part:
            result += THAI_ONES[int(digit)] if int(digit) > 0 else "ศูนย์"
        return result

    # Convert to integer
    try:
        num = int(num_str)
    except ValueError:
        return num_str  # Return original if cannot convert

    if num == 0:
        return "ศูนย์"

    if num < 0:
        return "ลบ" + num_to_thai(str(-num))

    # Handle numbers by magnitude
    if num < 1000:
        return _num_to_thai_under_thousand(num)
    elif num < 10000:
        thousands = num // 1000
        remainder = num % 1000
        result = THAI_ONES[thousands] + "พัน"
        if remainder > 0:
            result += _num_to_thai_under_thousand(remainder)
        return result
    elif num < 100000:
        ten_thousands = num // 10000
        remainder = num % 10000
        if ten_thousands == 1:
            result = "หนึ่งหมื่น"
        elif ten_thousands == 2:
            result = "สองหมื่น"
        else:
            result = THAI_ONES[ten_thousands] + "หมื่น"
        if remainder > 0:
            thousands = remainder // 1000
            if thousands > 0:
                result += THAI_ONES[thousands] + "พัน"
            remainder = remainder % 1000
            if remainder > 0:
                result += _num_to_thai_under_thousand(remainder)
        return result
    elif num < 1000000:
        hundred_thousands = num // 100000
        remainder = num % 100000
        result = THAI_ONES[hundred_thousands] + "แสน"
        if remainder > 0:
            ten_thousands = remainder // 10000
            if ten_thousands > 0:
                result += THAI_ONES[ten_thousands] + "หมื่น"
            remainder = remainder % 10000
            thousands = remainder // 1000
            if thousands > 0:
                result += THAI_ONES[thousands] + "พัน"
            remainder = remainder % 1000
            if remainder > 0:
                result += _num_to_thai_under_thousand(remainder)
        return result
    elif num < 10000000:
        millions = num // 1000000
        remainder = num % 1000000
        result = THAI_ONES[millions] + "ล้าน"
        if remainder > 0:
            result += num_to_thai(str(remainder))
        return result
    else:
        # For very large numbers, use a simple approach
        millions = num // 1000000
        remainder = num % 1000000
        result = num_to_thai(str(millions)) + "ล้าน"
        if remainder > 0:
            result += num_to_thai(str(remainder))
        return result


# --- End vendored code --------------------------------------------------------

# --- Local enhancement to expand_maiyamok (issue #1; not in upstream) --------
#
# When ๆ is *mentioned* as a character (e.g. ``ใช้ `ๆ` แทน``) rather than
# *used* as a repetition mark, it must be left untouched. This only applies
# when ๆ is the sole (or whitespace-only) content of a matched open/close
# delimiter span; a ๆ that follows a real word inside the span (e.g.
# ``"ดีๆ"``) is a genuine repetition and must still expand. See issue #1.
#
# Same-char delimiters (open == close):
_YAMOK_SAME_DELIMS = frozenset("`'\"")
# Distinct open -> close delimiter pairs:
_YAMOK_PAIR_DELIMS = {
    "\u2018": "\u2019",  # ‘ ’
    "\u201c": "\u201d",  # “ ”
    "\u00ab": "\u00bb",  # « »
    "(": ")",
    "[": "]",
}

# How a *mentioned* ๆ (the sole content of a matched delimiter span) is
# rendered. "keep" emits the ๆ verbatim (default); "name" replaces it with
# ไม้ยมก (its spoken name); "strip" omits it. A ๆ *used* as a repetition
# mark is always expanded regardless of this setting. See CONTEXT.md
# (Kept / Named / Stripped) and issue #7.
YAMOK_MENTION_RENDERS = frozenset({"keep", "name", "strip"})

# How the previous word for a *used* ๆ is found. "off" (default) repeats the
# last ``[ก-๙]+`` run -- the stdlib-only behaviour, which over-repeats when
# Thai words are not space-separated (issue #2). "pythainlp" segments the
# preceding text with pythainlp and repeats only the last word. pythainlp is
# an OPTIONAL dependency: the "pythainlp" setting is only honoured when the
# package is importable, otherwise callers fall back to "off" (see app.py).
# See CONTEXT.md (ๆ / Used) and issue #2. ADR-0001 records the decision to
# take the dependency behind this toggle.
YAMOK_SEGMENTERS = frozenset({"off", "pythainlp"})

_word_tokenize = None  # cached lazily by _get_word_tokenize


def _get_word_tokenize():
    """Lazily import and cache pythainlp's ``word_tokenize``.

    Imported lazily so the default (stdlib-only) path never pays for -- or
    even requires -- pythainlp. The newmm trie pythainlp builds on first call
    is cached in a pythainlp-internal process global, so holding the function
    is enough. Raises ``ImportError`` if pythainlp is not installed.
    """
    global _word_tokenize
    if _word_tokenize is None:
        from pythainlp.tokenize import word_tokenize

        _word_tokenize = word_tokenize
    return _word_tokenize


def warmup_yamok_segmenter() -> None:
    """Eagerly load pythainlp (import + newmm trie) so the first real request
    does not pay the ~250ms first-call cost. Callers must only invoke this
    when ``segmenter="pythainlp"`` is in effect (issue #2), i.e. after
    ``_resolve_segmenter`` has already proven pythainlp importable.
    """
    _get_word_tokenize()("เดินช้า")


def _is_mentioned_yamok(text: str, i: int) -> bool:
    """Return True if the ๆ at ``text[i]`` is the sole/whitespace-only
    content of a matched open/close delimiter span.

    We look at the nearest non-space characters immediately to the left and
    right of the ๆ in the *original* text. If they form a recognized
    delimiter pair, the ๆ is being quoted/mentioned, not used.
    """
    left = None
    j = i - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    if j >= 0:
        left = text[j]

    right = None
    j = i + 1
    while j < len(text) and text[j].isspace():
        j += 1
    if j < len(text):
        right = text[j]

    if left is None or right is None:
        return False
    if left == right and left in _YAMOK_SAME_DELIMS:
        return True
    return _YAMOK_PAIR_DELIMS.get(left) == right


def _last_repeatable_word(prev_text: str, segmenter: str) -> str:
    """Return the text a *used* ๆ should repeat.

    With ``segmenter="off"`` (default) this is the last ``[ก-๙]+`` run -- the
    stdlib-only behaviour, which over-repeats when Thai words are not
    space-separated (issue #2). With ``segmenter="pythainlp"`` it is the last
    Thai word found by pythainlp's tokenizer. Returns "" when there is nothing
    Thai to repeat; the caller then keeps the ๆ verbatim (issue #4).
    """
    if not prev_text:
        return ""
    if segmenter == "pythainlp":
        # Walk the tokens back to the last non-whitespace one containing Thai
        # characters (the tokenizer can emit whitespace/punctuation as tokens).
        for token in reversed(_get_word_tokenize()(prev_text)):
            token = token.strip()
            if token and re.search(r"[ก-๙]", token):
                return token
        return ""
    matches = list(re.finditer(r"[ก-๙]+", prev_text))
    return matches[-1].group() if matches else ""


def expand_maiyamok(text: str, mention_render: str = "keep", segmenter: str = "off") -> str:
    """Expand the Thai repetition character (ๆ) by repeating the previous word.

    A ๆ that is the sole content of a quote/code span is *mentioned*, not
    used as a repetition mark; how it is rendered is controlled by
    ``mention_render`` — ``keep`` (default) emits it verbatim, ``name``
    replaces it with ``ไม้ยมก``, ``strip`` omits it (see CONTEXT.md: Kept /
    Named / Stripped). Any unrecognised value falls back to ``keep``. A ๆ
    used as a repetition mark is always expanded regardless of the mode
    (issue #1, #7).

    ``segmenter`` controls how the word to repeat is found: ``off`` (default)
    repeats the last ``[ก-๙]+`` run; ``pythainlp`` repeats only the last word
    via segmentation (issue #2, needs the optional ``pythainlp`` package).
    """
    if "ๆ" not in text:
        return text

    result = []
    i = 0
    while i < len(text):
        if text[i] == "ๆ":
            if _is_mentioned_yamok(text, i):
                # Mentioned inside a quote/code span; render per the mode.
                # An unrecognised mode falls back to "keep" (issue #7).
                if mention_render == "name":
                    result.append("ไม้ยมก")
                elif mention_render == "strip":
                    pass
                else:
                    result.append("ๆ")
            else:
                # Find the previous Thai word/syllable to repeat. If there is
                # nothing valid to repeat (a bare ๆ, or only non-Thai text
                # before it), keep the ๆ verbatim rather than silently skipping
                # it (issue #4); skipping what the user typed is not safe or
                # reversible. With segmenter="pythainlp" only the last *word*
                # repeats (issue #2); otherwise the whole Thai run does.
                repeated = _last_repeatable_word("".join(result), segmenter) if result else ""
                result.append(repeated or "ๆ")
            i += 1
        else:
            result.append(text[i])
            i += 1

    return "".join(result)


# --- Local enhancement: Identifier reading (issue #3; not in upstream) -------
#
# A digit string can be a *Quantity* (read by magnitude: 123 -> หนึ่งร้อย...)
# or an *Identifier* (read digit-by-digit: 081 -> ศูนย์แปดหนึ่ง). Upstream reads
# every digit run by magnitude, which loses leading zeros, misreading phone
# numbers and other leading-zero identifiers. Per CONTEXT.md (Quantity / Identifier), the reading mode
# depends on format, not the digits alone. This first-slice heuristic flags the
# least ambiguous Identifier signal: a digit run -- or a dash-separated
# sequence of digit groups -- whose FIRST group starts with '0' (len >= 2). A
# Quantity never has a leading zero, so this never reclassifies a real
# Quantity. Other Identifier signals (nearby keywords like โทร/เบอร์/รหัส) and
# the rest of the family (national ID, zip, account no. without a leading zero)
# are deliberate follow-up slices.
#
# The lookarounds keep the heuristic out of decimals and larger numbers. The
# lookbehind ``(?<![\d.\-])`` requires the '0' to begin a standalone token:
# not embedded in a longer number (1007), not the fractional part of a decimal
# (1.081), and not a later group of a dash sequence whose first group had no
# leading zero (2024-03-15 -> the 03 is not an Identifier). The trailing
# ``(?![\d.])`` stops a run that abuts a decimal point from being split off by
# backtracking (0.5, 012.34 pass through to magnitude/decimal handling whole).
_IDENTIFIER = re.compile(r"(?<![\d.\-])0\d+(?:-\d+)*(?![\d.])")


def _digits_to_thai_names(digit_str: str) -> str:
    """Read each digit by name, ignoring place value (``081`` -> ``ศูนย์แปดหนึ่ง``).

    Same per-digit mapping ``num_to_thai`` uses for a decimal's fractional part
    (CONTEXT.md: Digit reading).
    """
    return "".join(THAI_ONES[int(d)] if d != "0" else "ศูนย์" for d in digit_str)


def _identifier_to_thai(match: "re.Match[str]") -> str:
    # ``081-234-5678`` -> ``ศูนย์แปดหนึ่ง สองสามสี่ ห้าหกเจ็ดแปด``: each digit read
    # by name within its group, dash separators between groups -> single spaces.
    return " ".join(_digits_to_thai_names(group) for group in match.group().split("-"))


# preprocess_text below is vendored from PyThaiTTS/pythaitts/preprocess.py; the
# identifier pass inside it (issue #3) is a local addition, as is the
# yamok_mention_render kwarg threaded into expand_maiyamok (issue #7).
def preprocess_text(
    text: str,
    expand_numbers: bool = True,
    expand_maiyamok_char: bool = True,
    yamok_mention_render: str = "keep",
    yamok_segmenter: str = "off",
) -> str:
    """Preprocess Thai text: convert numbers to text and expand ๆ."""
    result = text

    # Expand mai yamok (ๆ) first
    if expand_maiyamok_char:
        result = expand_maiyamok(
            result,
            mention_render=yamok_mention_render,
            segmenter=yamok_segmenter,
        )

    # Convert numbers to Thai text
    if expand_numbers:
        # Identifiers (a leading-zero phone number and the like) are read
        # digit-by-digit *before* magnitude conversion, which would otherwise
        # lose the leading zero (issue #3). Deviation from upstream, noted above.
        result = _IDENTIFIER.sub(_identifier_to_thai, result)

        def replace_number(match):
            return num_to_thai(match.group())

        # Match integers and decimals, including optional negative sign.
        result = re.sub(r"-?\d+(?:\.\d+)?", replace_number, result)

    return result


# A comma (or full-width comma) sitting between two digits is a thousands
# separator (e.g. "1,200" or "10,000.50"). Stripping it before number
# conversion lets the formatter read the whole number. Full-width comma is
# included because Thai text sometimes uses it.
_THOUSANDS_SEP = re.compile(r"(?<=\d)[,，](?=\d)")


def normalize_for_tts(
    text: str,
    *,
    numbers: bool = True,
    maiyamok: bool = True,
    yamok_mention_render: str = "keep",
    yamok_segmenter: str = "off",
) -> str:
    """Normalize Thai text for speech synthesis.

    - Strips thousands separators between digits (``1,200`` -> ``1200``).
    - Converts Arabic digits to Thai words (``123`` -> ``หนึ่งร้อยยี่สิบสาม``).
    - Expands the repetition mark ๆ (``ดีๆ`` -> ``ดีดี``).

    Both transforms can be toggled off independently. ``yamok_mention_render``
    controls how a *mentioned* ๆ (inside a matched delimiter span) is rendered
    — ``keep`` (default) / ``name`` (ไม้ยมก) / ``strip``; a ๆ used as a
    repetition mark is always expanded regardless (issue #7).
    ``yamok_segmenter`` controls how the word to repeat is found for a used ๆ
    — ``off`` (default) repeats the last Thai run; ``pythainlp`` repeats only
    the last word via segmentation (issue #2, needs the optional ``pythainlp``
    package).
    """
    if not isinstance(text, str) or not text:
        return text

    if numbers:
        text = _THOUSANDS_SEP.sub("", text)

    return preprocess_text(
        text,
        expand_numbers=numbers,
        expand_maiyamok_char=maiyamok,
        yamok_mention_render=yamok_mention_render,
        yamok_segmenter=yamok_segmenter,
    )
