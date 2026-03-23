"""
Camera-facing and UI-facing API routes.

Camera endpoints:
  GET  /api/command   — long-poll; returns {"cmd":"capture"} or {"cmd":"none"}
  POST /api/upload    — raw JPEG body streamed directly to disk

UI endpoints:
  POST /api/capture   — trigger a capture (enqueues command)
  GET  /api/status    — current camera/request state (JSON)
  GET  /api/events    — SSE stream of real-time updates
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..state import (
    LONG_POLL_TIMEOUT_S,
    app_state,
    enqueue_command,
    is_camera_online,
    sse_broadcast,
    sse_subscribe,
    sse_unsubscribe,
    status_payload,
    touch_camera,
)

router = APIRouter()

# Resolved at import time; overridden by env var UPLOADS_DIR
_BASE = Path(__file__).resolve().parent.parent.parent.parent  # project root
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", str(_BASE / "uploads")))


# ── Camera: long-poll for command ────────────────────────────────────────────
@router.get("/command")
async def get_command(timeout: int = LONG_POLL_TIMEOUT_S) -> JSONResponse:
    """
    Camera calls this endpoint repeatedly. The server holds the connection open
    until a command is enqueued (or timeout expires), then responds immediately.
    """
    touch_camera()

    was_online = app_state.camera_online
    app_state.camera_online = True
    if not was_online:
        await sse_broadcast("status", status_payload())

    effective_timeout = min(max(timeout, 5), LONG_POLL_TIMEOUT_S)
    cmd = await wait_for_command_safe(float(effective_timeout))

    touch_camera()  # Refresh timestamp after the wait

    return JSONResponse({"cmd": cmd or "none"})


async def wait_for_command_safe(timeout: float):
    from ..state import wait_for_command
    return await wait_for_command(timeout)


# ── Camera: receive JPEG upload ───────────────────────────────────────────────
@router.post("/upload", status_code=201)
async def upload_image(request: Request) -> JSONResponse:
    """
    Receives a raw JPEG body (Content-Type: image/jpeg) and streams it
    directly to disk without buffering the entire image in memory.
    """
    touch_camera()
    app_state.camera_online = True

    # Transition to uploading state
    if app_state.request_state != "uploading":
        app_state.request_state = "uploading"
        await sse_broadcast("request_state", {"state": "uploading"})

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:6]
    filename = f"{ts}_{uid}.jpg"
    filepath = UPLOADS_DIR / filename

    t0 = time.perf_counter()
    size = 0

    async with aiofiles.open(filepath, "wb") as fh:
        async for chunk in request.stream():
            await fh.write(chunk)
            size += len(chunk)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"[UPLOAD] {filename}  {size:,} bytes  {elapsed_ms:.1f} ms", flush=True)

    app_state.last_image = filename
    app_state.request_state = "idle"

    await sse_broadcast("image", {
        "filename": filename,
        "url": f"/uploads/{filename}",
        "size": size,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    await sse_broadcast("request_state", {"state": "idle"})
    await sse_broadcast("status", status_payload())

    return JSONResponse({"ok": True, "filename": filename, "size": size})


# ── UI: trigger capture ───────────────────────────────────────────────────────
@router.post("/capture")
async def trigger_capture() -> JSONResponse:
    if not is_camera_online():
        raise HTTPException(status_code=503, detail="Camera is offline")

    enqueue_command("capture")
    app_state.request_state = "capturing"
    await sse_broadcast("request_state", {"state": "capturing"})

    return JSONResponse({"ok": True})


# ── UI: current status snapshot ──────────────────────────────────────────────
@router.get("/status")
async def get_status() -> JSONResponse:
    payload = status_payload()
    payload["request_state"] = app_state.request_state
    payload["last_image"] = app_state.last_image
    return JSONResponse(payload)


# ── UI: SSE event stream ──────────────────────────────────────────────────────
@router.get("/events")
async def sse_events(request: Request) -> StreamingResponse:
    """
    Server-Sent Events stream. Sends initial snapshot, then pushes incremental
    updates as they occur. Keepalive comments are sent every 15 s.
    """
    q = sse_subscribe()

    async def stream():
        # ── Initial snapshot ──────────────────────────────────────────────────
        snap = status_payload()
        snap["request_state"] = app_state.request_state
        yield f"event: init\ndata: {json.dumps(snap)}\n\n"

        if app_state.last_image:
            yield (
                f"event: image\n"
                f"data: {json.dumps({'filename': app_state.last_image, 'url': f'/uploads/{app_state.last_image}', 'size': None, 'timestamp': None})}\n\n"
            )

        # ── Live updates ──────────────────────────────────────────────────────
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # Keepalive to prevent proxy timeouts
        except (GeneratorExit, asyncio.CancelledError):
            pass
        finally:
            sse_unsubscribe(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable Nginx response buffering
            "Connection": "keep-alive",
        },
    )
