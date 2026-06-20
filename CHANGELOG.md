# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this
project aims to follow [Semantic Versioning](https://semver.org/). The current
version lives in `app.py` (`version="..."`).

## Unreleased

### Fixed

- **Don't expand ๆ when it's quoted/mentioned (issue #1).** A ๆ that is the
  sole content of a quote or code span — e.g. `` ใช้ `ๆ` แทน `` — was being
  treated as a repetition mark and expanded the preceding word
  (`นิยมใช้ `ๆ`` → `นิยมใช้ `นิยมใช้``). `expand_maiyamok` now detects this
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
