"""End-to-end smoke test: mock OmniVoice upstream + the real proxy.

Not part of the runtime; run with the venv active:
    python tests/test_proxy_e2e.py
"""

from __future__ import annotations

import os
import subprocess
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


@mock.get("/v1/q")
async def mock_query_echo(request: Request):
    # Echo query params as ordered pairs so the test catches a real bug:
    # dict(request.query_params) would drop repeated keys (?a=1&a=2 -> a=2).
    return {"pairs": [[k, v] for k, v in request.query_params.multi_items()]}


@mock.post("/v1/audio/clone")
async def mock_clone(request: Request):
    raw = await request.body()
    received.append({"path": request.url.path, "raw": raw})
    return {"cloned": True, "bytes": len(raw)}


@mock.post("/v1/audio/speech/clone")
async def mock_clone_speech(request: Request):
    """Pretends to be OmniVoice's voice-cloning endpoint. Captures the parsed
    multipart fields so the test can assert `text` was normalized while the
    binary `ref_audio` part survived byte-for-byte."""
    form = await request.form()
    ref = form.get("ref_audio")
    received.append(
        {
            "path": request.url.path,
            "text": form.get("text"),
            "filename": ref.filename if ref else None,
            "file_bytes": await ref.read() if ref else None,
        }
    )
    return Response(content=b"AUDIOCLONE", media_type="audio/wav")


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


def _pythainlp_available() -> bool:
    try:
        import pythainlp  # noqa: F401

        return True
    except ImportError:
        return False


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
    health = r.json()
    check(r.status_code == 200 and health["status"] == "ok", "_health reports ok")
    check(
        health.get("yamok_mention_render") == "keep",
        f"_health reports yamok_mention_render=keep (got {health.get('yamok_mention_render')!r})",
    )
    check(
        health.get("yamok_segmenter") == "off",
        f"_health reports yamok_segmenter=off (got {health.get('yamok_segmenter')!r})",
    )

    # 8. repeated query params are preserved (not collapsed by dict())
    r = httpx.get(f"{base}/v1/q?a=1&a=2&b=3")
    pairs = r.json().get("pairs")
    check(
        pairs == [["a", "1"], ["a", "2"], ["b", "3"]],
        f"repeated query params preserved: {pairs}",
    )

    # 9. /audio/speech/clone multipart normalization: `text` field normalized,
    #    binary ref_audio preserved byte-for-byte. (Endpoint is multipart, not JSON.)
    received.clear()
    r = httpx.post(
        f"{base}/v1/audio/speech/clone",
        data={"text": "ดีๆ 99", "voice": "alloy"},
        files={"ref_audio": ("ref.wav", b"FAKEWAVEDATA", "audio/wav")},
    )
    check(r.status_code == 200, "clone POST returns 200")
    check(len(b"AUDIOCLONE") == len(r.content), "clone audio streamed back intact")
    check(
        received[-1]["text"] == "ดีดี เก้าสิบเก้า",
        f"clone text normalized: {received[-1]['text']}",
    )
    check(received[-1]["filename"] == "ref.wav", "clone ref_audio filename preserved")
    check(received[-1]["file_bytes"] == b"FAKEWAVEDATA", "clone ref_audio bytes preserved")

    # 10. YAMOK_MENTION_RENDER: an unrecognised value falls back to "keep"
    #     without crashing (issue #7). Imported in a subprocess so the bad
    #     value is seen at app import time, where env is read.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad_env = os.environ.copy()
    bad_env["YAMOK_MENTION_RENDER"] = "not-a-mode"
    bad_env["UPSTREAM_BASE_URL"] = "http://127.0.0.1:9999"
    bad_env["LOG_LEVEL"] = "WARNING"
    proc = subprocess.run(
        [sys.executable, "-c", "import app; print(app.YAMOK_MENTION_RENDER)"],
        capture_output=True,
        text=True,
        env=bad_env,
        cwd=repo_root,
    )
    check(proc.returncode == 0, f"bad YAMOK_MENTION_RENDER doesn't crash (rc={proc.returncode}, stderr={proc.stderr.strip()[:160]})")
    check(
        proc.stdout.strip() == "keep",
        f"bad YAMOK_MENTION_RENDER falls back to keep: {proc.stdout.strip()!r}",
    )

    # 11. YAMOK_MENTION_RENDER=name threads end-to-end: a mentioned ๆ in a
    #     speech request is rendered as ไม้ยมก at the upstream. (Run in its own
    #     subprocess server so we can set the mode without disturbing the
    #     default-mode assertions above.)
    name_env = os.environ.copy()
    name_env["YAMOK_MENTION_RENDER"] = "name"
    name_env["UPSTREAM_BASE_URL"] = "http://127.0.0.1:9999"
    name_env["LISTEN_PORT"] = "8089"
    name_env["LISTEN_HOST"] = "127.0.0.1"
    name_env["LOG_LEVEL"] = "WARNING"
    name_server = subprocess.Popen(
        [sys.executable, "-c", "import uvicorn, app; uvicorn.run(app.app, host='127.0.0.1', port=8089, log_level='warning')"],
        env=name_env,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait("http://127.0.0.1:8089/_health")
        received.clear()
        r = httpx.post(
            "http://127.0.0.1:8089/v1/audio/speech",
            json={"input": "ใช้ `ๆ` แทน", "voice": "alloy"},
            timeout=10.0,
        )
        check(r.status_code == 200, "name-mode speech POST returns 200")
        fwd = _json.loads(received[-1]["raw"])
        check(
            fwd["input"] == "ใช้ `ไม้ยมก` แทน",
            f"name-mode renders mentioned ๆ as ไม้ยมก end-to-end: {fwd['input']}",
        )
    finally:
        name_server.terminate()
        name_server.wait(timeout=5)

    # 12. YAMOK_SEGMENTER=pythainlp threads end-to-end: a used ๆ with no space
    #     before it repeats only the last word. Skipped when pythainlp (an
    #     optional dependency, ADR-0001) isn't importable; CI installs it.
    if not _pythainlp_available():
        print("  SKIP pythainlp not installed — YAMOK_SEGMENTER=pythainlp e2e check")
    else:
        seg_env = os.environ.copy()
        seg_env["YAMOK_SEGMENTER"] = "pythainlp"
        seg_env["UPSTREAM_BASE_URL"] = "http://127.0.0.1:9999"
        seg_env["LISTEN_PORT"] = "8090"
        seg_env["LISTEN_HOST"] = "127.0.0.1"
        seg_env["LOG_LEVEL"] = "WARNING"
        seg_server = subprocess.Popen(
            [sys.executable, "-c", "import uvicorn, app; uvicorn.run(app.app, host='127.0.0.1', port=8090, log_level='warning')"],
            env=seg_env,
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            _wait("http://127.0.0.1:8090/_health")
            received.clear()
            r = httpx.post(
                "http://127.0.0.1:8090/v1/audio/speech",
                json={"input": "เดินช้าๆ", "voice": "alloy"},
                timeout=10.0,
            )
            check(r.status_code == 200, "segmenter-mode speech POST returns 200")
            fwd = _json.loads(received[-1]["raw"])
            check(
                fwd["input"] == "เดินช้าช้า",
                f"segmenter-mode repeats only the last word: {fwd['input']}",
            )
        finally:
            seg_server.terminate()
            seg_server.wait(timeout=5)

    print(f"\n{'ALL TESTS PASSED' if not failures else str(len(failures)) + ' FAILURE(S): ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
