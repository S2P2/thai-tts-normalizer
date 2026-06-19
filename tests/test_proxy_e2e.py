"""End-to-end smoke test: mock OmniVoice upstream + the real proxy.

Not part of the runtime; run with the venv active:
    python tests/test_proxy_e2e.py
"""

from __future__ import annotations

import os
import sys
import threading
import time

# Configure the proxy via env BEFORE importing app (it reads env at import).
os.environ["UPSTREAM_BASE_URL"] = "http://127.0.0.1:9999"
os.environ["LISTEN_PORT"] = "8088"
os.environ["LISTEN_HOST"] = "127.0.0.1"
os.environ["LOG_LEVEL"] = "WARNING"

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response

# --- mock upstream (pretends to be OmniVoice) ---
mock = FastAPI()
received: list[dict] = []


@mock.post("/v1/audio/speech")
@mock.post("/audio/speech")
async def mock_speech(request: Request):
    body = await request.body()
    received.append({"path": request.url.path, "raw": body})
    return Response(content=b"AUDIOBYTES" * 500, media_type="audio/wav")


@mock.get("/v1/audio/voices")
async def mock_voices():
    return {"voices": [{"id": "alloy"}, {"id": "clone:jo"}]}


@mock.get("/v1/models")
async def mock_models():
    return {"data": [{"id": "omnivoice"}]}


def _serve(app: FastAPI, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    return server


def _wait(url: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code < 500:
                return
            last = r.status_code
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(0.1)
    raise RuntimeError(f"{url} never came up (last={last})")


def main() -> int:
    _serve(mock, 9999)
    # import the proxy app now that env is set
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as proxy_app  # noqa: E402

    _serve(proxy_app.app, 8088)
    _wait("http://127.0.0.1:8088/_health")

    base = "http://127.0.0.1:8088"
    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        print(("  OK  " if cond else " FAIL ") + msg)
        if not cond:
            failures.append(msg)

    # 1. speech normalization (with /v1)
    received.clear()
    r = httpx.post(
        f"{base}/v1/audio/speech",
        json={"input": "มี 5 คนๆ ราคา 1,200", "voice": "alloy"},
    )
    check(r.status_code == 200, "speech POST returns 200")
    check(len(b"AUDIOBYTES" * 500) == len(r.content), "audio bytes streamed back intact")
    import json as _json

    fwd = _json.loads(received[-1]["raw"])
    check(fwd["input"] == "มี ห้า คนคน ราคา หนึ่งพันสองร้อย", "input normalized (/v1): " + fwd["input"])
    check(fwd["voice"] == "alloy", "voice field preserved")

    # 2. speech normalization (without /v1)
    received.clear()
    httpx.post(f"{base}/audio/speech", json={"input": "ดีๆ 123"})
    fwd = _json.loads(received[-1]["raw"])
    check(fwd["input"] == "ดีดี หนึ่งร้อยยี่สิบสาม", "input normalized (/audio): " + fwd["input"])

    # 3. already-normalized / no digits-or-ๆ text passes through unchanged
    received.clear()
    httpx.post(f"{base}/v1/audio/speech", json={"input": "สวัสดีครับ"})
    fwd = _json.loads(received[-1]["raw"])
    check(fwd["input"] == "สวัสดีครับ", "no-op text unchanged: " + fwd["input"])

    # 4. missing input -> forwarded untouched
    received.clear()
    httpx.post(f"{base}/v1/audio/speech", json={"voice": "alloy"})
    fwd = _json.loads(received[-1]["raw"])
    check("input" not in fwd, "missing input forwarded as-is")

    # 5. non-JSON body -> forwarded untouched (no crash)
    received.clear()
    r = httpx.post(f"{base}/v1/audio/speech", content=b"plain text not json", headers={"content-type": "text/plain"})
    check(r.status_code == 200, "non-JSON body handled (200)")

    # 6. transparent forwarding: voices + models NOT touched
    r = httpx.get(f"{base}/v1/audio/voices")
    check(r.status_code == 200 and r.json()["voices"][1]["id"] == "clone:jo", "voices forwarded transparently")
    r = httpx.get(f"{base}/v1/models")
    check(r.status_code == 200 and r.json()["data"][0]["id"] == "omnivoice", "models forwarded transparently")

    # 7. health
    r = httpx.get(f"{base}/_health")
    check(r.status_code == 200 and r.json()["status"] == "ok", "_health reports ok")

    print(f"\n{'ALL TESTS PASSED' if not failures else str(len(failures)) + ' FAILURE(S): ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
