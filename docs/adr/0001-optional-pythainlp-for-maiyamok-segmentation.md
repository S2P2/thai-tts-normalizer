# ADR-0001: Optional `pythainlp` for mai-yamok word segmentation

- **Status:** Accepted
- **Date:** 2026-06-21
- **Issues:** [#2](https://github.com/S2P2/thai-tts-normalizer/issues/2)

## Context

Issue #2: a *used* ๆ (mai yamok) repeats the text before it. The vendored
`expand_maiyamok` finds the text to repeat with `re.finditer(r"[ก-๙]+", ...)`,
which matches the entire Thai run as one match because Thai is not
space-delimited. So `เดินช้าๆ` becomes `เดินช้าเดินช้า` (the whole run
duplicated) instead of `เดินช้าช้า` (only `ช้า` repeated). Correct behaviour
requires actual word segmentation.

Two constraints shape the decision:

1. **The module is deliberately stdlib-only.** Its docstring states the
   functions are "pure Python (only the stdlib `re`)" and were vendored from
   PyThaiTTS precisely to avoid pulling in heavy dependencies. Reversing that
   for every user is a meaningful identity change, not just a dependency add.
2. **There is no correct stdlib heuristic.** Thai word segmentation needs a
   lexicon; leading-vowel and syllable-pattern heuristics cannot reliably split
   `เดินช้า` into `เดิน` + `ช้า`, so they would not pass issue #2's test.

A throwaway benchmark of `pythainlp` 5.3.4 (default `newmm` engine) found:

- **Zero transitive runtime dependencies** in the base install — `numpy`,
  `torch`, `tensorflow`, `pandas`, `sklearn` are all optional extras and are
  not pulled in. Pure Python, no compiled extensions.
- **Warm per-call latency ~10–60 µs** (a 14-word sentence ~61 µs) — negligible
  per request.
- **One-time costs:** ~64 ms import and ~250 ms first-call trie build, paid
  once per process. Mitigated by lazy import + warm-up at server startup.
- **Footprint:** ~63 MB installed (almost entirely a bundled corpus, of which
  only ~2 MB is used by `newmm`). It fixes both #2 repros exactly.

## Decision

Adopt `pythainlp` as an **optional** dependency, used only when
`YAMOK_SEGMENTER=pythainlp` is set. The default (`off`) keeps the normalizer
stdlib-only and reproduces today's behaviour.

Concretely:

- `expand_maiyamok` gains a `segmenter` argument (`"off"` | `"pythainlp"`),
  threaded env → `app.py` constant → `normalize_for_tts` kwarg →
  `expand_maiyamok`, mirroring the `YAMOK_MENTION_RENDER` pattern.
- `pythainlp.tokenize.word_tokenize` is imported **lazily**, only inside the
  enabled path, so the default path never imports it or requires it.
- `app.py` resolves `YAMOK_SEGMENTER` at startup: a value of `pythainlp`
  without the package installed falls back to `off` with a warning.
- The proxy warms the tokenizer once at startup so the first request does not
  pay the ~250 ms first-call cost.
- `pythainlp` lives in `requirements-dev.txt` (test-only), not
  `requirements.txt`. CI installs it so the gated tests run; runtime users
  install it only if they enable the toggle.

## Consequences

- **Positive:** Correct ๆ handling for unspaced Thai runs is available to users
  who opt in, while the default install stays lean and stdlib-only — keeping
  the documented identity intact for everyone else.
- **Positive:** The opt-in is reversible: setting `YAMOK_SEGMENTER=off` (or
  uninstalling `pythainlp`) restores the prior behaviour exactly.
- **Negative:** Two behaviours now exist behind a toggle, so users must opt in
  to get the fix. Documented in `README.md` §Limitations and the env table.
- **Negative:** `+63 MB` for opt-in users (mostly an unused bundled corpus).
  Acceptable for a self-hosted proxy; the only way to slim it is forking
  `pythainlp`.

## Alternatives considered

- **Take `pythainlp` as a hard dependency (in `requirements.txt`).** Rejected:
  it contradicts the stdlib-only stance for *every* user, not just opt-in ones,
  and adds 63 MB to the default image for a default-off feature.
- **A bounded stdlib-only heuristic.** Rejected: no lexicon-free heuristic can
  reliably find the last word in `เดินช้า`; it would not pass issue #2's test
  and would trade a known limitation for a silently-wrong one.
- **Decline the fix (wontfix, document the limitation).** Rejected: the bug
  affects real, common input (Thai text on the web is usually unspaced), and
  the optional-dependency middle ground makes a correct fix available without
  compromising the default.
