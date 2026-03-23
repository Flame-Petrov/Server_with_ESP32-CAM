"""
Shared application state, command channel, and SSE broadcaster.

All mutation happens on the asyncio event loop — no locks needed.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Optional

# ── Tunables ─────────────────────────────────────────────────────────────────
OFFLINE_THRESHOLD_S: float = float(os.getenv("CAMERA_OFFLINE_THRESHOLD", "35"))
LONG_POLL_TIMEOUT_S: int   = int(os.getenv("LONG_POLL_TIMEOUT", "25"))


# ── Camera / request state ────────────────────────────────────────────────────
@dataclass
class AppState:
    camera_online: bool          = False
    last_seen:     Optional[float] = None
    last_image:    Optional[str]   = None
    # "idle" | "capturing" | "uploading"
    request_state: str           = "idle"


app_state = AppState()


def is_camera_online() -> bool:
    if app_state.last_seen is None:
        return False
    return (time.time() - app_state.last_seen) < OFFLINE_THRESHOLD_S


def touch_camera() -> None:
    """Record that the camera polled or uploaded right now."""
    app_state.last_seen = time.time()


def last_seen_iso() -> Optional[str]:
    if app_state.last_seen is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(app_state.last_seen))


def status_payload() -> dict:
    online = is_camera_online()
    app_state.camera_online = online
    return {"online": online, "last_seen": last_seen_iso()}


# ── Command channel (long-poll) ───────────────────────────────────────────────
_command_event: Optional[asyncio.Event] = None
_pending_command: Optional[str]         = None


def init_events() -> None:
    """Must be called once inside the asyncio event loop (lifespan startup)."""
    global _command_event
    _command_event = asyncio.Event()


async def wait_for_command(timeout: float) -> Optional[str]:
    """Block until a command is queued or timeout expires. Returns command or None."""
    global _pending_command
    assert _command_event is not None, "init_events() was not called"
    try:
        await asyncio.wait_for(_command_event.wait(), timeout=timeout)
        cmd = _pending_command
        _command_event.clear()
        _pending_command = None
        return cmd
    except asyncio.TimeoutError:
        return None


def enqueue_command(cmd: str) -> None:
    """Queue a command for the next camera long-poll response."""
    global _pending_command
    assert _command_event is not None, "init_events() was not called"
    _pending_command = cmd
    _command_event.set()


# ── SSE broadcaster ───────────────────────────────────────────────────────────
_sse_clients: list[asyncio.Queue[str]] = []


def sse_subscribe() -> asyncio.Queue[str]:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
    _sse_clients.append(q)
    return q


def sse_unsubscribe(q: asyncio.Queue[str]) -> None:
    try:
        _sse_clients.remove(q)
    except ValueError:
        pass


async def sse_broadcast(event: str, data: dict) -> None:
    import json
    msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    stale: list[asyncio.Queue[str]] = []
    for q in _sse_clients:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            stale.append(q)
    for q in stale:
        sse_unsubscribe(q)
