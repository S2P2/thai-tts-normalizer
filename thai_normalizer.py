"""Thai text normalization for TTS.

The number-to-Thai and ๆ (mai yamok) expansion logic below is derived
from PyThaiTTS (pythaitts.preprocess) — see
https://github.com/PyThaiNLP/PyThaiTTS — licensed under the Apache License,
Version 2.0. The number-to-Thai functions are vendored verbatim;
``expand_maiyamok`` carries one localized enhancement over the upstream
original (it leaves a ๆ untouched when it is mentioned inside a quote/code
span rather than used as a repetition mark — see its docstring and issue #1).
These functions are pure Python (only the stdlib ``re``) and do not pull in
any TTS model dependencies, which is why they are vendored here rather than
installed via ``pip install pythaitts`` (that package would try to download
TTS model weights).

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


# --- Original code (not from PyThaiTTS): quoted-span detection for ๆ --------
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


def expand_maiyamok(text: str) -> str:
    """Expand the Thai repetition character (ๆ) by repeating the previous word.

    A ๆ that is the sole content of a quote/code span is left untouched (it
    is being *mentioned* as a character, not used as a repetition mark); see
    issue #1.
    """
    if "ๆ" not in text:
        return text

    result = []
    i = 0
    while i < len(text):
        if text[i] == "ๆ":
            if _is_mentioned_yamok(text, i):
                # Mentioned inside a quote/code span; keep it as-is.
                result.append("ๆ")
            elif result:
                # Find the previous word/syllable to repeat
                prev_text = "".join(result)
                thai_char_pattern = r"[ก-๙]+"
                matches = list(re.finditer(thai_char_pattern, prev_text))
                if matches:
                    last_match = matches[-1]
                    word_to_repeat = last_match.group()
                    result.append(word_to_repeat)
            i += 1
        else:
            result.append(text[i])
            i += 1

    return "".join(result)


def preprocess_text(
    text: str,
    expand_numbers: bool = True,
    expand_maiyamok_char: bool = True,
) -> str:
    """Preprocess Thai text: convert numbers to text and expand ๆ."""
    result = text

    # Expand mai yamok (ๆ) first
    if expand_maiyamok_char:
        result = expand_maiyamok(result)

    # Convert numbers to Thai text
    if expand_numbers:
        def replace_number(match):
            return num_to_thai(match.group())

        # Match integers and decimals, including optional negative sign.
        result = re.sub(r"-?\d+(?:\.\d+)?", replace_number, result)

    return result


# --- End vendored code --------------------------------------------------------

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
) -> str:
    """Normalize Thai text for speech synthesis.

    - Strips thousands separators between digits (``1,200`` -> ``1200``).
    - Converts Arabic digits to Thai words (``123`` -> ``หนึ่งร้อยยี่สิบสาม``).
    - Expands the repetition mark ๆ (``ดีๆ`` -> ``ดีดี``).

    Both transforms can be toggled off independently.
    """
    if not isinstance(text, str) or not text:
        return text

    if numbers:
        text = _THOUSANDS_SEP.sub("", text)

    return preprocess_text(
        text,
        expand_numbers=numbers,
        expand_maiyamok_char=maiyamok,
    )
