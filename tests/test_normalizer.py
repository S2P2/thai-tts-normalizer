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
  * The known bug tracked in GitHub issue #3 is encoded as
    ``@unittest.expectedFailure``. It stays green while the bug exists and flips
    to "unexpected success" (red) the moment a fix lands -- which is the prompt
    to remove the decorator and turn it into an ordinary passing test. Issue #1
    was fixed the same way. Issue #2 is fixed behind an *optional* toggle
    (``segmenter="pythainlp"``, ADR-0001): its test is gated with
    ``@unittest.skipUnless`` on the optional ``pythainlp`` package and so skips
    in a stdlib-only checkout; CI installs pythainlp so it runs there.
  * Adds coverage for ``normalize_for_tts`` (our wrapper) that upstream does not
    have, including thousands-separator stripping and the toggle flags.

Run with:
    python tests/test_normalizer.py
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


def _pythainlp_available() -> bool:
    """Issue #2's segmenter uses the *optional* pythainlp package. Tests that
    exercise it skip when the package isn't installed (e.g. a stdlib-only
    checkout); CI installs pythainlp as a test dependency so they run there."""
    try:
        import pythainlp  # noqa: F401

        return True
    except ImportError:
        return False


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

    def test_hundred_thousands(self):
        # Magnitudes upstream's tests stop short of (แสน).
        self.assertEqual(num_to_thai("100000"), "หนึ่งแสน")
        self.assertEqual(num_to_thai("500000"), "ห้าแสน")
        self.assertEqual(num_to_thai("123456"), "หนึ่งแสนสองหมื่นสามพันสี่ร้อยห้าสิบหก")

    def test_millions(self):
        # ล้าน and above. Anchors issue #3's phone-number fix so it doesn't
        # regress ordinary large-magnitude reading.
        self.assertEqual(num_to_thai("1000000"), "หนึ่งล้าน")
        self.assertEqual(num_to_thai("10000000"), "สิบล้าน")
        self.assertEqual(
            num_to_thai("12345678"),
            "สิบสองล้านสามแสนสี่หมื่นห้าพันหกร้อยเจ็ดสิบแปด",
        )

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

    # --- Issue #1: ๆ mentioned inside a quote/code span is left untouched ----

    def test_maiyamok_not_expanded_inside_code_span(self):
        self.assertEqual(expand_maiyamok("ใช้ `ๆ` แทน"), "ใช้ `ๆ` แทน")

    def test_maiyamok_not_expanded_inside_other_delimiters(self):
        """Sole-content ๆ in any recognized quote/bracket span is protected."""
        for opener, closer in [
            ("'", "'"),               # straight single quote
            ('"', '"'),               # straight double quote
            ("\u2018", "\u2019"),     # curly single
            ("\u201c", "\u201d"),     # curly double
            ("\u00ab", "\u00bb"),     # « »
            ("(", ")"),               # parentheses
            ("[", "]"),               # brackets
        ]:
            with self.subTest(open=opener, close=closer):
                inp = f"ใช้ {opener}ๆ{closer} แทน"
                self.assertEqual(expand_maiyamok(inp), inp)

    def test_maiyamok_whitespace_inside_delimiters(self):
        self.assertEqual(expand_maiyamok("` ๆ `"), "` ๆ `")

    def test_maiyamok_multiple_quoted_spans(self):
        self.assertEqual(expand_maiyamok("`ๆ` และ `ๆ`"), "`ๆ` และ `ๆ`")

    def test_maiyamok_real_repeat_inside_quotes_still_expands(self):
        """Regression guard: a ๆ that follows a real word inside a span is a
        genuine repetition and must still expand (the fix must not suppress it)."""
        self.assertEqual(expand_maiyamok('"ดีๆ"'), '"ดีดี"')
        self.assertEqual(expand_maiyamok('เขียน "เร็วๆ" หน่อย'), 'เขียน "เร็วเร็ว" หน่อย')
        self.assertEqual(expand_maiyamok("(ดีๆ)"), "(ดีดี)")

    # --- Issue #4: a bare ๆ (nothing valid to repeat) is kept, not skipped ----

    def test_maiyamok_bare_at_start_is_kept(self):
        """A ๆ with no preceding Thai word to repeat is kept verbatim."""
        self.assertEqual(expand_maiyamok("ๆ นี่คือไม้ยมก"), "ๆ นี่คือไม้ยมก")

    def test_maiyamok_bare_among_punctuation_is_kept(self):
        self.assertEqual(expand_maiyamok("!!! ๆ !!!"), "!!! ๆ !!!")

    def test_maiyamok_bare_alone_is_kept(self):
        self.assertEqual(expand_maiyamok("ๆ"), "ๆ")

    def test_maiyamok_after_non_thai_is_kept(self):
        """A ๆ following only non-Thai characters has nothing to repeat; keep it."""
        self.assertEqual(expand_maiyamok("abc ๆ xyz"), "abc ๆ xyz")

    def test_maiyamok_unbalanced_opener_bare_is_kept(self):
        """Regression guard for the reported case `` `ๆ `` (unbalanced opener):
        the ๆ is not inside a matched span and has no Thai run before it, so it
        must survive rather than vanish."""
        self.assertEqual(expand_maiyamok("`ๆ"), "`ๆ")

    # --- Issue #2: with segmenter="pythainlp", only the last word repeats ----
    # pythainlp is an optional dependency (ADR-0001); these skip when it isn't
    # installed. CI installs it so they run there.

    @unittest.skipUnless(_pythainlp_available(), "pythainlp not installed")
    def test_maiyamok_in_sentence_repeats_only_last_word(self):
        """Issue #2: with no space before ๆ, segmenter="pythainlp" makes only
        the last word repeat (the stdlib regex over-repeats the whole run)."""
        self.assertEqual(expand_maiyamok("เดินช้าๆ", segmenter="pythainlp"), "เดินช้าช้า")
        self.assertEqual(
            expand_maiyamok("หรือพิมพ์ซ้ำคำตรงๆ", segmenter="pythainlp"),
            "หรือพิมพ์ซ้ำคำตรงตรง",
        )

    def test_maiyamok_default_segmenter_is_off(self):
        # Off by default: the whole run repeats. This is the stdlib-only
        # behaviour, unchanged when the optional pythainlp segmenter is off.
        self.assertEqual(expand_maiyamok("เดินช้าๆ"), "เดินช้าเดินช้า")

    @unittest.skipUnless(_pythainlp_available(), "pythainlp not installed")
    def test_segmenter_does_not_affect_mentioned_or_bare_yamok(self):
        # The segmenter only changes what a *used* ๆ repeats; mentioned-ๆ
        # rendering (issue #7) and a bare ๆ being kept (issue #4) are unchanged.
        self.assertEqual(expand_maiyamok("ใช้ `ๆ` แทน", segmenter="pythainlp"), "ใช้ `ๆ` แทน")
        self.assertEqual(expand_maiyamok("ๆ", segmenter="pythainlp"), "ๆ")

    @unittest.skipUnless(_pythainlp_available(), "pythainlp not installed")
    def test_yamok_segmenter_threads_through_normalize_for_tts(self):
        self.assertEqual(
            normalize_for_tts("เดินช้าๆ", yamok_segmenter="pythainlp"),
            "เดินช้าช้า",
        )


class TestYamokMentionRender(unittest.TestCase):
    """Configurable rendering of a *mentioned* ๆ (issue #7).

    A mentioned ๆ is one inside a matched delimiter span (the
    ``_is_mentioned_yamok`` case). Its rendering is controlled by
    ``mention_render``: keep (default) / name (ไม้ยมก) / strip. A ๆ *used* as
    a repetition mark must be unaffected by the mode in all three settings.
    """

    MENTIONED = "ใช้ `ๆ` แทน"  # ๆ is the sole content of a code span

    def test_default_mode_is_keep(self):
        # No kwarg == keep == today's behaviour: ๆ emitted verbatim.
        self.assertEqual(expand_maiyamok(self.MENTIONED), self.MENTIONED)
        self.assertEqual(
            expand_maiyamok(self.MENTIONED, mention_render="keep"),
            self.MENTIONED,
        )

    def test_name_mode_replaces_with_spoken_name(self):
        self.assertEqual(
            expand_maiyamok(self.MENTIONED, mention_render="name"),
            "ใช้ `ไม้ยมก` แทน",
        )

    def test_strip_mode_removes_the_character(self):
        self.assertEqual(
            expand_maiyamok(self.MENTIONED, mention_render="strip"),
            "ใช้ `` แทน",
        )

    def test_unrecognised_mode_falls_back_to_keep(self):
        # Graceful degradation: a bogus mode must not crash or strip; it keeps.
        self.assertEqual(
            expand_maiyamok(self.MENTIONED, mention_render="bogus"),
            self.MENTIONED,
        )

    def test_name_mode_across_other_delimiters(self):
        for opener, closer, expected_inner in [
            ("'", "'", "'ไม้ยมก'"),
            ("(", ")", "(ไม้ยมก)"),
            ("\u201c", "\u201d", "\u201cไม้ยมก\u201d"),
        ]:
            with self.subTest(open=opener):
                inp = f"ใช้ {opener}ๆ{closer} แทน"
                self.assertEqual(
                    expand_maiyamok(inp, mention_render="name"),
                    f"ใช้ {expected_inner} แทน",
                )

    def test_multiple_mentioned_each_rendered_per_mode(self):
        self.assertEqual(
            expand_maiyamok("`ๆ` และ `ๆ`", mention_render="name"),
            "`ไม้ยมก` และ `ไม้ยมก`",
        )

    def test_used_yamok_unaffected_by_mode(self):
        """A ๆ used as a repetition mark (following a Thai run) must still
        expand regardless of the render mode."""
        for mode in ("keep", "name", "strip", "bogus"):
            with self.subTest(mode=mode):
                self.assertEqual(expand_maiyamok("ดีๆ", mention_render=mode), "ดีดี")

    def test_kwarg_threads_through_normalize_for_tts(self):
        # Per-call kwarg is unit-testable without touching the env var.
        self.assertEqual(
            normalize_for_tts(self.MENTIONED, yamok_mention_render="name"),
            "ใช้ `ไม้ยมก` แทน",
        )
        self.assertEqual(
            normalize_for_tts(self.MENTIONED, yamok_mention_render="strip"),
            "ใช้ `` แทน",
        )
        # Default kwarg == keep.
        self.assertEqual(normalize_for_tts(self.MENTIONED), self.MENTIONED)

    def test_mentioned_render_independent_of_maiyamok_toggle(self):
        """With maiyamok expansion off, the mode is moot: nothing is touched."""
        self.assertEqual(
            normalize_for_tts(self.MENTIONED, maiyamok=False, yamok_mention_render="name"),
            self.MENTIONED,
        )


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

    def test_millions_with_separator(self):
        # Thousands-separator stripping at magnitude (locks in #3 anchor + the
        # separator-stripping wrapper).
        self.assertEqual(normalize_for_tts("1,000,000"), "หนึ่งล้าน")
        self.assertEqual(
            normalize_for_tts("12,345,678"),
            "สิบสองล้านสามแสนสี่หมื่นห้าพันหกร้อยเจ็ดสิบแปด",
        )

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
            "โทร ศูนย์แปดหนึ่ง สองสามสี่ ห้าหกเจ็ดแปด",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
