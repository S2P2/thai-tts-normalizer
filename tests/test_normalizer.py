"""Unit tests for the Thai text normalization logic in thai_normalizer.py.

This file's structure and the happy-path cases for num_to_thai /
expand_maiyamok / preprocess_text are derived from PyThaiTTS's
tests/test_preprocess.py (Apache License 2.0):

    Project:  PyThaiTTS
    Source:   https://github.com/PyThaiNLP/PyThaiTTS/blob/main/tests/test_preprocess.py
    Author:   Wannaphong (PyThaiNLP)

Adaptations made here:
  * Imports point at our vendored copy (``thai_normalizer``), not pythaitts.
  * Loose upstream assertions (assertIn / assertNotIn) are tightened to pin the
    exact expected string, so behaviour drift is caught.
  * The known bugs tracked in GitHub issues #1, #2, #3 are encoded as
    ``@unittest.expectedFailure``. They stay green while the bug exists and flip
    to "unexpected success" (red) the moment a fix lands -- which is the prompt
    to remove the decorator and turn them into ordinary passing tests.
  * Adds coverage for ``normalize_for_tts`` (our wrapper) that upstream does not
    have, including thousands-separator stripping and the toggle flags.

Run with:
    python tests/test_normalizer.py -v
"""

from __future__ import annotations

import os
import sys
import unittest

# Make the repo root importable so `import thai_normalizer` works regardless of
# the current working directory (mirrors the bootstrap in tests/test_proxy_e2e.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from thai_normalizer import (  # noqa: E402
    expand_maiyamok,
    normalize_for_tts,
    num_to_thai,
    preprocess_text,
)


class TestNumToThai(unittest.TestCase):
    """Number-to-Thai conversion (magnitude reading)."""

    def test_single_digits(self):
        self.assertEqual(num_to_thai("0"), "ศูนย์")
        self.assertEqual(num_to_thai("1"), "หนึ่ง")
        self.assertEqual(num_to_thai("5"), "ห้า")
        self.assertEqual(num_to_thai("9"), "เก้า")

    def test_tens(self):
        self.assertEqual(num_to_thai("10"), "สิบ")
        self.assertEqual(num_to_thai("11"), "สิบเอ็ด")
        self.assertEqual(num_to_thai("15"), "สิบห้า")
        self.assertEqual(num_to_thai("20"), "ยี่สิบ")
        self.assertEqual(num_to_thai("21"), "ยี่สิบเอ็ด")
        self.assertEqual(num_to_thai("99"), "เก้าสิบเก้า")

    def test_hundreds(self):
        self.assertEqual(num_to_thai("100"), "หนึ่งร้อย")
        self.assertEqual(num_to_thai("123"), "หนึ่งร้อยยี่สิบสาม")
        self.assertEqual(num_to_thai("200"), "สองร้อย")
        self.assertEqual(num_to_thai("999"), "เก้าร้อยเก้าสิบเก้า")

    def test_thousands(self):
        self.assertEqual(num_to_thai("1000"), "หนึ่งพัน")
        self.assertEqual(num_to_thai("1234"), "หนึ่งพันสองร้อยสามสิบสี่")
        self.assertEqual(num_to_thai("5000"), "ห้าพัน")

    def test_ten_thousands(self):
        self.assertEqual(num_to_thai("10000"), "หนึ่งหมื่น")
        self.assertEqual(num_to_thai("50000"), "ห้าหมื่น")

    def test_negative_numbers(self):
        self.assertEqual(num_to_thai("-5"), "ลบห้า")
        self.assertEqual(num_to_thai("-123"), "ลบหนึ่งร้อยยี่สิบสาม")

    def test_decimal_numbers(self):
        # Pinned exactly (upstream only used loose assertIn fragments).
        self.assertEqual(num_to_thai("12.5"), "สิบสองจุดห้า")


class TestExpandMaiyamok(unittest.TestCase):
    """Expansion of the Thai repetition character ๆ."""

    def test_basic_maiyamok_single_word(self):
        # These are upstream's happy-path examples. They work because the whole
        # Thai run before ๆ is a single word.
        self.assertEqual(expand_maiyamok("ดีๆ"), "ดีดี")
        self.assertEqual(expand_maiyamok("ช้าๆ"), "ช้าช้า")
        self.assertEqual(expand_maiyamok("คนๆ"), "คนคน")

    def test_no_maiyamok_passthrough(self):
        self.assertEqual(expand_maiyamok("ภาษาไทย"), "ภาษาไทย")
        self.assertEqual(expand_maiyamok("สวัสดี"), "สวัสดี")

    # --- Known bugs: expected to FAIL until the issues are fixed -------------

    @unittest.expectedFailure
    def test_maiyamok_in_sentence_repeats_only_last_word(self):
        """Issue #2: with no space before ๆ, only the last word repeats.

        Current (buggy) output is ``เดินช้าเดินช้า`` -- the whole run
        ``เดินช้า`` is duplicated. Upstream's assertion was too weak
        (assertNotIn ๆ + assertIn ช้า) and so never caught this.
        """
        self.assertEqual(expand_maiyamok("เดินช้าๆ"), "เดินช้าช้า")

    @unittest.expectedFailure
    def test_maiyamok_not_expanded_inside_code_span(self):
        """Issue #1: a ๆ that is quoted/mentioned must be left untouched.

        Current (buggy) output is ``ใช้ `ใช้` แทน`` -- the quoted ๆ triggers
        spurious repetition of the preceding word.
        """
        self.assertEqual(expand_maiyamok("ใช้ `ๆ` แทน"), "ใช้ `ๆ` แทน")


class TestPreprocessText(unittest.TestCase):
    """Combined preprocessing (numbers + mai yamok)."""

    def test_number_conversion_in_text(self):
        self.assertEqual(preprocess_text("ฉันมี 123 บาท"), "ฉันมี หนึ่งร้อยยี่สิบสาม บาท")

    def test_maiyamok_expansion_in_text(self):
        self.assertEqual(preprocess_text("ดีๆ"), "ดีดี")

    def test_combined_preprocessing(self):
        # ๆ expands first (คนๆ -> คนคน), then the number converts.
        self.assertEqual(preprocess_text("มี 5 คนๆ"), "มี ห้า คนคน")

    def test_disable_number_expansion(self):
        self.assertEqual(preprocess_text("มี 5 คน", expand_numbers=False), "มี 5 คน")

    def test_disable_maiyamok_expansion(self):
        self.assertEqual(preprocess_text("ดีๆ", expand_maiyamok_char=False), "ดีๆ")

    def test_empty_text(self):
        self.assertEqual(preprocess_text(""), "")

    def test_text_without_preprocessing_needs(self):
        text = "ภาษาไทย ง่าย มาก"
        self.assertEqual(preprocess_text(text), text)


class TestNormalizeForTTS(unittest.TestCase):
    """Our wrapper around preprocess_text.

    Covers the thousands-separator stripping and the numbers/maiyamok toggles
    that are specific to normalize_for_tts (no upstream equivalent).
    """

    def test_strips_thousands_separator(self):
        self.assertEqual(normalize_for_tts("ราคา 1,200 บาท"), "ราคา หนึ่งพันสองร้อย บาท")

    def test_strips_full_width_thousands_separator(self):
        self.assertEqual(normalize_for_tts("1，200"), "หนึ่งพันสองร้อย")

    def test_large_number_with_separator(self):
        self.assertEqual(normalize_for_tts("10,000"), "หนึ่งหมื่น")

    def test_maiyamok_toggle_off(self):
        self.assertEqual(normalize_for_tts("ดีๆ", maiyamok=False), "ดีๆ")

    def test_numbers_toggle_off(self):
        self.assertEqual(normalize_for_tts("มี 5 คน", numbers=False), "มี 5 คน")

    def test_empty_and_non_string(self):
        self.assertEqual(normalize_for_tts(""), "")
        self.assertIsNone(normalize_for_tts(None))

    # --- Known bug: expected to FAIL until issue #3 is fixed -----------------

    @unittest.expectedFailure
    def test_phone_number_read_digit_by_digit(self):
        """Issue #3: phone numbers should be spelled out digit-by-digit.

        Current (buggy) output reads each segment as a magnitude and pronounces
        the dashes as ลบ (minus), e.g.
        ``โทร แปดสิบเอ็ดลบสองร้อยสามสิบสี่ลบห้าพันหกร้อยเจ็ดสิบแปด``.
        """
        self.assertEqual(
            normalize_for_tts("โทร 081-234-5678"),
            "โทร ศูนย์แปดหนึ่งสองสามสี่ห้าหกเจ็ดแปด",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
