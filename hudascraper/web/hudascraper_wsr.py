# app/websocket_routes.py
from __future__ import annotations

import contextlib

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from .hudascraper_log import broker

router = APIRouter()

@router.websocket("/ws/logs")
async def logs_ws(
    websocket: WebSocket,
    token: str | None = Query(default=None),     # optional: attach your auth later
    level: str | None = Query(default=None),     # optional: future filtering
    logger: str | None = Query(default=None),    # optional: future filtering
):
    await websocket.accept()
    q = await broker.connect()
    try:
        # Optional: send a hello so the client knows it's live
        await websocket.send_text('{"type":"hello","msg":"log-stream-ready"}')
        while True:
            msg = await q.get()
            await websocket.send_text(msg)
    except WebSocketDisconnect:
        pass
    finally:
        await broker.disconnect(q)
        with contextlib.suppress(Exception):
            await websocket.close()
