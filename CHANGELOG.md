# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this
project aims to follow [Semantic Versioning](https://semver.org/). The current
version lives in `app.py` (`version="..."`).

## 0.1.3 — 2026-06-21

### Added

- **Configurable rendering of a mentioned ๆ (issue #7).** A *mentioned* ๆ
  — one that is the sole content of a matched quote/code span rather than a
  repetition mark — must still be emitted somehow, and different TTS models
  handle the bare character differently. New `YAMOK_MENTION_RENDER` env var
  selects how: `keep` (default, emit verbatim), `name` (replace with
  `ไม้ยมก`, its spoken name), or `strip` (remove it). A ๆ *used* as a
  repetition mark is always expanded regardless of the mode. Threaded env →
  `app.py` constant → `normalize_for_tts` kwarg → `expand_maiyamok` param.

- **Optional pythainlp segmenter for ๆ (issue #2, ADR-0001).** A *used* ๆ can
  now repeat only the last *word* before it instead of the whole Thai run —
  e.g. `เดินช้าๆ` → `เดินช้าช้า` (was `เดินช้าเดินช้า`) — when the new
  `YAMOK_SEGMENTER=pythainlp` toggle is set. pythainlp is an **optional**
  dependency (`pip install pythainlp`; not added to `requirements.txt`), so the
  default (`off`) keeps the normalizer stdlib-only and reproduces today's
  behaviour. `word_tokenize` is imported lazily and warmed up once at startup;
  if the package is absent the setting falls back to `off` with a warning.
  Decision recorded in ADR-0001 (`docs/adr/`).

### Fixed

- **Keep a bare ๆ instead of silently deleting it (issue #4).** A ๆ with
  nothing valid to repeat (a bare ๆ, or one preceded only by non-Thai text)
  was silently skipped, losing what the user typed. `expand_maiyamok` now
  keeps it verbatim — not safe or reversible to drop input silently.

- **Read leading-zero identifiers (phone numbers) digit-by-digit (issue #3,
  first slice).** A digit run whose first group starts with `0` (len ≥ 2), or a
  dash-separated sequence whose first group does, is now treated as an
  *Identifier* (CONTEXT.md) and read digit-by-digit, with dashes between groups
  becoming single spaces — e.g. `โทร 081-234-5678` → `โทร ศูนย์แปดหนึ่ง สองสามสี่
  ห้าหกเจ็ดแปด`, and `0212345678` is read digit-by-digit instead of as one
  large magnitude. The trigger is deliberately narrow: a Quantity never has a
  leading zero, so Quantities and decimals (`0.5`, `1.081`, `012.34`, `1007`,
  `1234`, dates like `2024-03-15`) are unchanged. Partially closes the
  phone-number item from the 0.1.0 known limitations. Identifiers without a
  leading zero (national ID, zip, account no.), keyword-driven detection, and
  other multi-component patterns (IP addresses, dates) are planned follow-up
  slices — see #15.

- **Don't expand ๆ when it's quoted/mentioned (issue #1).** A ๆ that is the
  sole content of a quote or code span — e.g. `` ใช้ `ๆ` แทน `` — was being
  treated as a repetition mark and expanded the preceding word (so the word
  นิยมใช้ before a quoted ๆ was wrongly duplicated as นิยมใช้ นิยมใช้).
  `expand_maiyamok` now detects this
  case (backtick, straight/curly quotes, guillemets, parentheses, brackets;
  whitespace around the ๆ allowed) and leaves the ๆ untouched. Genuine
  repetitions that follow a real word inside a span (e.g. `"ดีๆ"` → `"ดีดี"`)
  still expand as before. This is a localized enhancement to the
  PyThaiTTS-derived `expand_maiyamok`; NOTICE updated accordingly.

## 0.1.2 — 2026-06-20

### Added

- **Normalize the voice-cloning endpoint too.** `POST /audio/speech/clone`
  (and `/v1/audio/speech/clone`) sends its text as a multipart form field
  (`text`) alongside a binary `ref_audio` file part, which the previous
  release passed through untouched. The proxy now parses that multipart body,
  normalizes the `text` field, and re-encodes the form for the upstream —
  preserving the reference audio and all other fields. Added a new
  `python-multipart` dependency for parsing. The reference audio is buffered
  for the round-trip (capped by the upstream, so safe in practice); every other
  path still streams.

### Fixed

- **New multipart regression test.** The previous test #9 posted JSON to a
  fictional `/v1/audio/clone` path; it is replaced with a real multipart call
  to `/v1/audio/speech/clone` asserting both text normalization and that the
  binary `ref_audio` survives byte-for-byte.

## 0.1.1 — 2026-06-19

### Fixed

- **Preserve repeated query parameters.** Forwarding used
  `dict(request.query_params)`, which silently dropped all but the last value
  for repeated keys (`?a=1&a=2` → `a=2`). Now uses `multi_items()` so every
  value is preserved. (Latent for Open WebUI traffic, but a real correctness
  bug.)
- **Stream non-speech request bodies instead of buffering.** Previously the
  whole request body was read into memory before forwarding. Now only the
  speech endpoint buffers (it must, to rewrite the `input` field); every other
  path (e.g. a large `/v1/audio/clone` upload) streams straight through.
- Clarified that the catch-all route covers all standard HTTP methods.

## 0.1.0 — 2026-06-19

Initial release.

### Added

- **Reverse proxy** (`app.py`): OpenAI-compatible proxy that normalizes the
  `input` field on `POST /audio/speech` and `POST /v1/audio/speech` before
  forwarding to an upstream TTS server such as OmniVoice. All other paths
  (voices, models, clone, design, web UI, swagger) are forwarded transparently,
  and the audio response is streamed back untouched.
- **Thai text normalization** (`thai_normalizer.py`):
  - Arabic digits → Thai words (`123` → `หนึ่งร้อยยี่สิบสาม`).
  - Thousands separators stripped before conversion (`1,200` → `หนึ่งพันสองร้อย`).
  - ๆ (mai yamok) expansion (`ดีๆ` → `ดีดี`).
  - Independent toggles via the `NORMALIZE_NUMBERS` / `NORMALIZE_MAIYAMOK` env
    vars.
- **Vendored normalization logic** from [PyThaiTTS](https://github.com/PyThaiNLP/PyThaiTTS)
  (`pythaitts.preprocess`, Apache-2.0): pure-Python, depends only on the stdlib
  `re` module, pulls no TTS model weights.
- **Operational bits**: `Dockerfile`, `.env.example`, and an end-to-end test
  suite (`tests/test_proxy_e2e.py`) covering normalization, transparent
  forwarding, and edge cases (missing/`non-JSON` bodies).

### Known limitations

- Long digit strings (e.g. phone numbers) are read as a single large number,
  not digit-by-digit — inherited from PyThaiTTS's digit-to-word logic.
- Thai numerals (๑๒๓) are not converted; only Arabic digits (123) are.
