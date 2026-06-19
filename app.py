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

from thai_normalizer import normalize_for_tts

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

@asynccontextmanager
async def _lifespan(fastapi_app: FastAPI):
    # read timeout is disabled so long audio streams are never cut short.
    fastapi_app.state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT, read=None),
        follow_redirects=True,
    )
    log.info(
        "forwarding to %s | numbers=%s maiyamok=%s",
        UPSTREAM_BASE_URL or "(unset)",
        NORMALIZE_NUMBERS,
        NORMALIZE_MAIYAMOK,
    )
    try:
        yield
    finally:
        await fastapi_app.state.client.aclose()


app = FastAPI(title="Thai TTS Normalizing Proxy", version="0.1.0", lifespan=_lifespan)


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
        text, numbers=NORMALIZE_NUMBERS, maiyamok=NORMALIZE_MAIYAMOK
    )
    if normalized == text:
        return body, None, None
    data["input"] = normalized
    return (
        json.dumps(data, ensure_ascii=False).encode("utf-8"),
        text,
        normalized,
    )


async def _forward(request: Request) -> Response:
    client: httpx.AsyncClient = app.state.client
    url = UPSTREAM_BASE_URL + request.url.path
    body = await request.body()

    before = after = None
    if request.method.upper() == "POST" and request.url.path in _SPEECH_PATHS:
        body, before, after = _maybe_normalize_body(body)
        if before is not None:
            log.info(
                "normalized speech input (%d -> %d chars): %r -> %r",
                len(before),
                len(after or ""),
                before[:120],
                (after or "")[:120],
            )

    headers = _request_headers(request)
    try:
        req = client.build_request(
            request.method,
            url,
            params=dict(request.query_params),
            headers=headers,
            content=body,
        )
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
    }


@app.post("/audio/speech")
@app.post("/v1/audio/speech")
async def _speech(request: Request) -> Response:
    return await _forward(request)


# Catch-all: forward every other method/path transparently (voices, models,
# clone, design, web UI, swagger, ...). Declared last so the explicit speech
# routes above take precedence.
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
