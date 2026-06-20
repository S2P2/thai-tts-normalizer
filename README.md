# thai-tts-normalizer

A tiny reverse proxy that fixes Thai text **before** it reaches your TTS
server, so numbers and the repetition mark ๆ are pronounced correctly. It
speaks the standard OpenAI `/audio/speech` protocol, so it works with **any**
compatible client (Open WebUI, SillyTavern, …) and **any** compatible server
(OmniVoice, Kokoro, openedai-speech, …).

- `123` → `หนึ่งร้อยยี่สิบสาม` (Arabic digits → Thai words)
- `1,200` → `หนึ่งพันสองร้อย` (thousands separators handled)
- `ดีๆ` → `ดีดี` (ๆ / mai yamok expanded)

The displayed text is **not** changed — only the text sent to the TTS engine
is normalized. This is a **standalone service**, not a plugin.

## Why a proxy?

Some TTS clients give you no hook to pre-process the text they send for
synthesis. Open WebUI is one: its Filter hooks (`inlet`/`stream`/`outlet`)
only run on the **LLM chat** path, while the TTS engine reads text through a
**separate** endpoint (`/audio/speech`) that filters never touch — there is no
TTS filter hook (see open-webui discussions
[#13778](https://github.com/open-webui/open-webui/discussions/13778) and
[#13979](https://github.com/open-webui/open-webui/discussions/13979)). A proxy
sidesteps the problem entirely, and because it speaks the standard OpenAI TTS
protocol it works with **any** client and **any** server, not just Open WebUI.

```
  any client  ──►  [thai-tts-normalizer]  ──►  any TTS server
  (Open WebUI,     normalizes `input`      (OmniVoice, Kokoro,
   SillyTavern…)   only                     openedai-speech, …)
```

## How it works

- Intercepts `POST /audio/speech` and `POST /v1/audio/speech`, normalizes the
  JSON body's `input` field, then forwards to the upstream TTS server.
- **Everything else** (`/audio/voices`, `/v1/voices`, `/v1/models`,
  `/v1/audio/clone`, `/v1/audio/design`, `/web`, `/docs`, …) is forwarded
  transparently — voice discovery and the upstream server's own features keep
  working.
- Streams the audio response straight back, untouched.

The number/ๆ logic is vendored from
[PyThaiTTS](https://github.com/PyThaiNLP/PyThaiTTS) (`pythaitts.preprocess`,
Apache-2.0). It is pure Python (`re` only) and does **not** pull in any TTS
model weights.

## Run it

### Docker

```bash
docker build -t thai-tts-normalizer .
docker run -p 8080:8080 -e UPSTREAM_BASE_URL=http://omnivoice:8880 thai-tts-normalizer
```

### venv

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export UPSTREAM_BASE_URL=http://localhost:8880   # your OmniVoice server root
python app.py
# or: uvicorn app:app --host 0.0.0.0 --port 8080
```

If OmniVoice runs in another container, put this proxy on the same Docker
network and point `UPSTREAM_BASE_URL` at the OmniVoice service name.

## Example integration: Open WebUI

You only change **one** setting — the TTS API base URL — from the TTS server
to this proxy (keep the `/v1` suffix):

**Admin Panel → Settings → Audio**, with the OpenAI (or Custom TTS) engine:

| Setting | Before | After |
|---|---|---|
| API Base URL | `http://omnivoice:8880/v1` | `http://thai-tts-normalizer:8080/v1` |

Everything else (API key, TTS model, voice, response splitting) stays the same.

Other OpenAI-compatible clients (SillyTavern, LobeChat, custom apps, …) work
the same way: point their TTS / API base URL at the proxy instead of the TTS
server directly.

Quick check that it's alive: `curl http://localhost:8080/_health`

## Configuration

All via environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `UPSTREAM_BASE_URL` | _(required)_ | TTS server root, **no** `/v1` suffix. The path is forwarded verbatim. |
| `LISTEN_HOST` | `0.0.0.0` | Bind host. |
| `LISTEN_PORT` | `8080` | Bind port. |
| `UPSTREAM_API_KEY` | _(empty)_ | Force an `Authorization: Bearer …` upstream. Empty = forward what the client sends. |
| `NORMALIZE_NUMBERS` | `true` | Convert digits to Thai words. |
| `NORMALIZE_MAIYAMOK` | `true` | Expand ๆ. |
| `REQUEST_TIMEOUT` | `120` | Connect/write timeout (s). Audio streaming has no read timeout. |
| `LOG_LEVEL` | `INFO` | Log verbosity. |

## Limitations

- **Phone numbers / long digit strings** are read as a whole number
  (`021234567` → a very large number), not digit-by-digit. This is inherited
  from PyThaiTTS's digit→word logic. Tell me if you need phone-number handling.
- **Thai numerals** (๑๒๓) are not converted — only Arabic digits (123).
  Many TTS servers (including OmniVoice) handle Thai numerals already.
- **Scope of digit conversion**: every digit run is converted, including
  things like `v1.0`, years, and percentages. This is usually what you want
  for speech, but toggle `NORMALIZE_NUMBERS=false` if you need finer control.

## License

- Proxy code: **MIT** — see [LICENSE](LICENSE).
- Vendored normalization logic in `thai_normalizer.py`: **Apache-2.0**, from
  [PyThaiTTS](https://github.com/PyThaiNLP/PyThaiTTS) — see
  [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt) and [NOTICE](NOTICE).
