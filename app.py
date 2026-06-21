"""Thai-normalizing reverse proxy for OpenAI-compatible TTS (e.g. OmniVoice).

Sits between Open WebUI and your TTS server. For ``POST /audio/speech`` (and
``/v1/audio/speech``) it normalizes the request's ``input`` text — Arabic
digits -> Thai words, and ๆ (mai yamok) expanded — then forwards everything to
the upstream TTS server unchanged and streams the audio back.

Everything else (voices, models, clone, design, web UI, swagger, ...) is
forwarded transparently, so Open WebUI's voice discovery and OmniVoice's own
features keep working.

Configure via environment variables (see .env.example). Point Open WebUI's TTS
base URL at this proxy instead of the OmniVoice server directly.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.datastructures import UploadFile

from thai_normalizer import (
    normalize_for_tts,
    warmup_yamok_segmenter,
    YAMOK_MENTION_RENDERS,
    YAMOK_SEGMENTERS,
)

# Hop-by-hop headers (RFC 7230) plus ``host``/``content-length`` which the
# outbound client must recompute for the request body we forward.
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _resolve_mention_render() -> str:
    """Resolve YAMOK_MENTION_RENDER to one of keep/name/strip; fall back to
    ``keep`` with a warning on any unrecognised value (issue #7)."""
    raw = os.environ.get("YAMOK_MENTION_RENDER", "keep").strip().lower()
    if raw not in YAMOK_MENTION_RENDERS:
        log.warning(
            "YAMOK_MENTION_RENDER=%r is not one of %s; falling back to 'keep'",
            raw,
            sorted(YAMOK_MENTION_RENDERS),
        )
        return "keep"
    return raw


def _resolve_segmenter() -> str:
    """Resolve YAMOK_SEGMENTER to one of off/pythainlp; fall back to ``off``
    with a warning on any unrecognised value, and also when ``pythainlp`` is
    chosen but the optional ``pythainlp`` package is not installed (issue #2)."""
    raw = os.environ.get("YAMOK_SEGMENTER", "off").strip().lower()
    if raw not in YAMOK_SEGMENTERS:
        log.warning(
            "YAMOK_SEGMENTER=%r is not one of %s; falling back to 'off'",
            raw,
            sorted(YAMOK_SEGMENTERS),
        )
        return "off"
    if raw == "pythainlp":
        try:
            import pythainlp  # noqa: F401
        except ImportError:
            log.warning(
                "YAMOK_SEGMENTER=pythainlp but pythainlp is not installed; "
                "falling back to 'off'. Install it with: pip install pythainlp"
            )
            return "off"
    return raw


UPSTREAM_BASE_URL = os.environ.get("UPSTREAM_BASE_URL", "").rstrip("/")
LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8080"))
UPSTREAM_API_KEY = os.environ.get("UPSTREAM_API_KEY", "")
NORMALIZE_NUMBERS = _env_bool("NORMALIZE_NUMBERS", True)
NORMALIZE_MAIYAMOK = _env_bool("NORMALIZE_MAIYAMOK", True)
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "120"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Paths whose request body contains the text to speak and must be normalized.
_SPEECH_PATHS = {"/audio/speech", "/v1/audio/speech"}
# Voice-cloning endpoints: `text` arrives as a multipart form field (not JSON)
# alongside a binary `ref_audio` file part.
_CLONE_PATHS = {"/audio/speech/clone", "/v1/audio/speech/clone"}

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s [thai-tts-proxy] %(message)s",
)
log = logging.getLogger("thai-tts-proxy")

if not UPSTREAM_BASE_URL:
    log.warning(
        "UPSTREAM_BASE_URL is not set; the proxy will not be able to forward "
        "requests. Set it to your TTS server root, e.g. http://omnivoice:8880"
    )

# Resolved after `log` exists so a bad value can be warned about at import.
YAMOK_MENTION_RENDER = _resolve_mention_render()
YAMOK_SEGMENTER = _resolve_segmenter()

@asynccontextmanager
async def _lifespan(fastapi_app: FastAPI):
    # read timeout is disabled so long audio streams are never cut short.
    fastapi_app.state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT, read=None),
        follow_redirects=True,
    )
    log.info(
        "forwarding to %s | numbers=%s maiyamok=%s yamok_mention_render=%s yamok_segmenter=%s",
        UPSTREAM_BASE_URL or "(unset)",
        NORMALIZE_NUMBERS,
        NORMALIZE_MAIYAMOK,
        YAMOK_MENTION_RENDER,
        YAMOK_SEGMENTER,
    )
    if YAMOK_SEGMENTER == "pythainlp":
        # Pay the one-time ~250ms newmm-trie load at startup, not on the first
        # request (issue #2).
        warmup_yamok_segmenter()
        log.info("yamok segmenter warmed up")
    try:
        yield
    finally:
        await fastapi_app.state.client.aclose()


app = FastAPI(title="Thai TTS Normalizing Proxy", version="0.1.3", lifespan=_lifespan)


def _request_headers(src: Request) -> dict[str, str]:
    headers = {
        k: v
        for k, v in src.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "content-length"
    }
    if UPSTREAM_API_KEY:
        headers["Authorization"] = f"Bearer {UPSTREAM_API_KEY}"
    return headers


def _response_headers(resp: httpx.Response) -> dict[str, str]:
    return {k: v for k, v in resp.headers.items() if k.lower() not in _HOP_BY_HOP}


def _maybe_normalize_body(body: bytes) -> tuple[bytes, Optional[str], Optional[str]]:
    """Return (body, before, after). If not a speech-JSON body, pass through."""
    if not body:
        return body, None, None
    try:
        data: Any = json.loads(body)
    except (ValueError, TypeError):
        return body, None, None
    if not isinstance(data, dict):
        return body, None, None
    text = data.get("input")
    if not isinstance(text, str):
        return body, None, None
    normalized = normalize_for_tts(
        text,
        numbers=NORMALIZE_NUMBERS,
        maiyamok=NORMALIZE_MAIYAMOK,
        yamok_mention_render=YAMOK_MENTION_RENDER,
        yamok_segmenter=YAMOK_SEGMENTER,
    )
    if normalized == text:
        return body, None, None
    data["input"] = normalized
    return (
        json.dumps(data, ensure_ascii=False).encode("utf-8"),
        text,
        normalized,
    )


async def _maybe_normalize_clone(
    request: Request,
) -> tuple[dict[str, str], list, Optional[str], Optional[str]]:
    """Parse a multipart ``/audio/speech/clone`` request, normalize its ``text``
    form field, and return ``(data, files, before, after)`` ready for httpx to
    re-encode. ``before``/``after`` are None when there was no text to normalize.

    Unlike the JSON speech path, this buffers the whole request body (the form,
    including the reference audio) because the multipart must be re-encoded after
    rewriting ``text``. The upstream caps reference audio at a modest size, so
    buffering is safe in practice.
    """
    form = await request.form()
    data: dict[str, str] = {}
    files: list = []
    before: Optional[str] = None
    after: Optional[str] = None
    for key, value in form.multi_items():
        if key == "text" and isinstance(value, str):
            normalized = normalize_for_tts(
                value,
                numbers=NORMALIZE_NUMBERS,
                maiyamok=NORMALIZE_MAIYAMOK,
                yamok_mention_render=YAMOK_MENTION_RENDER,
                yamok_segmenter=YAMOK_SEGMENTER,
            )
            before = value
            after = normalized
            data[key] = normalized
        elif isinstance(value, UploadFile):
            files.append(
                (key, (value.filename, await value.read(), value.content_type))
            )
        else:
            data[key] = str(value)
    return data, files, before, after


async def _forward(request: Request) -> Response:
    client: httpx.AsyncClient = app.state.client
    url = UPSTREAM_BASE_URL + request.url.path
    method = request.method.upper()
    path = request.url.path
    is_speech = method == "POST" and path in _SPEECH_PATHS
    is_clone = method == "POST" and path in _CLONE_PATHS

    build_kwargs: dict[str, Any] = {
        # multi_items() preserves repeated query params (?a=1&a=2);
        # dict() would silently keep only the last value.
        "params": list(request.query_params.multi_items()),
        "headers": _request_headers(request),
    }

    if is_speech:
        # Buffer the (small JSON) body so we can rewrite the `input` field.
        new_body, before, after = _maybe_normalize_body(await request.body())
        if before is not None:
            log.info(
                "normalized speech input (%d -> %d chars): %r -> %r",
                len(before),
                len(after or ""),
                before[:120],
                (after or "")[:120],
            )
        build_kwargs["content"] = new_body
    elif is_clone:
        # /clone is multipart: `text` is a form field, `ref_audio` a binary file
        # part. Buffer the form, normalize `text`, let httpx re-encode it. Drop
        # the client's Content-Type so httpx can set its own boundary.
        data, files, before, after = await _maybe_normalize_clone(request)
        if before is not None:
            log.info(
                "normalized clone text (%d -> %d chars): %r -> %r",
                len(before),
                len(after or ""),
                before[:120],
                (after or "")[:120],
            )
        build_kwargs["headers"] = {
            k: v for k, v in build_kwargs["headers"].items() if k.lower() != "content-type"
        }
        build_kwargs["data"] = data
        build_kwargs["files"] = files
    else:
        # Everything else streams straight through without buffering.
        build_kwargs["content"] = request.stream()

    try:
        req = client.build_request(method, url, **build_kwargs)
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        log.error("upstream request failed: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"detail": f"upstream request failed: {exc}"},
        )

    async def stream():
        try:
            async for chunk in resp.aiter_raw():
                yield chunk
        finally:
            await resp.aclose()

    return StreamingResponse(
        stream(),
        status_code=resp.status_code,
        headers=_response_headers(resp),
    )


@app.get("/_health")
async def _health() -> dict[str, Any]:
    return {
        "status": "ok",
        "upstream": UPSTREAM_BASE_URL or "(unset)",
        "numbers": NORMALIZE_NUMBERS,
        "maiyamok": NORMALIZE_MAIYAMOK,
        "yamok_mention_render": YAMOK_MENTION_RENDER,
        "yamok_segmenter": YAMOK_SEGMENTER,
    }


@app.post("/audio/speech")
@app.post("/v1/audio/speech")
async def _speech(request: Request) -> Response:
    return await _forward(request)


# Catch-all: forward every other method/path transparently (voices, models,
# clone, design, web UI, swagger, ...). Declared last so the explicit speech
# routes above take precedence. The method list covers every standard HTTP
# method a client would realistically use against a TTS server.
@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def _proxy(full_path: str, request: Request) -> Response:
    return await _forward(request)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=LISTEN_HOST,
        port=LISTEN_PORT,
        log_level=LOG_LEVEL.lower(),
    )
