"""
FastAPI application entry point.

Run from the project root:
    uvicorn server.app.main:app --host 0.0.0.0 --port 8000 --reload

Or via the helper script:
    python -m server.app.main
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes.camera import router as camera_router
from .state import (
    app_state,
    init_events,
    is_camera_online,
    sse_broadcast,
    status_payload,
)

# ── Directory paths ───────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent  # project root
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", str(_ROOT / "uploads")))
WEB_DIR     = Path(os.getenv("WEB_DIR",     str(_ROOT / "web")))

# Create uploads dir eagerly so StaticFiles mount doesn't fail
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


# ── Background monitor ────────────────────────────────────────────────────────
_MONITOR_INTERVAL = 5  # seconds between offline checks


async def _monitor_camera() -> None:
    """
    Periodically checks whether the camera has stopped polling and broadcasts
    a status change event if the online/offline state flips.
    """
    while True:
        await asyncio.sleep(_MONITOR_INTERVAL)
        online_now = is_camera_online()
        if online_now != app_state.camera_online:
            app_state.camera_online = online_now
            print(
                f"[MONITOR] Camera {'ONLINE' if online_now else 'OFFLINE'}"
                f"  last_seen={app_state.last_seen and time.strftime('%H:%M:%S', time.localtime(app_state.last_seen))}",
                flush=True,
            )
            await sse_broadcast("status", status_payload())
            # If camera went offline mid-capture, reset the request state
            if not online_now and app_state.request_state != "idle":
                app_state.request_state = "idle"
                await sse_broadcast("request_state", {"state": "idle"})


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_events()
    monitor_task = asyncio.create_task(_monitor_camera())
    print(f"[SERVER] Uploads : {UPLOADS_DIR}", flush=True)
    print(f"[SERVER] Web UI  : {WEB_DIR}", flush=True)
    yield
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ESP32-CAM Server",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes first (highest priority)
app.include_router(camera_router, prefix="/api", tags=["camera"])

# Static file mounts (lower priority than routers)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

if WEB_DIR.exists():
    # html=True serves index.html for unknown paths (SPA-style)
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:
    print(f"[SERVER] WARNING: web directory not found at {WEB_DIR}", flush=True)


# ── Dev runner ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server.app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
