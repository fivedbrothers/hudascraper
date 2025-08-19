# app/log_broker.py
from __future__ import annotations

import asyncio
import contextlib


class LogBroker:
    """
    Fan-out log broker.

    Each subscriber gets its own asyncio.Queue.
    publish() is non-blocking; if a subscriber is too slow, we drop messages for that subscriber.
    """

    def __init__(self, max_queue_size: int = 1000) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._max_queue_size = max_queue_size
        self._lock = asyncio.Lock()

    async def connect(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=self._max_queue_size)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def disconnect(self, q: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    def publish(self, message: str) -> None:
        # Called from logging threads; avoid awaits.
        subscribers = tuple(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                # Drop oldest-ish: try one get to make room; if still full, drop message.
                with contextlib.suppress(Exception):
                    q.get_nowait()
                with contextlib.suppress(Exception):
                    q.put_nowait(message)


# Singleton broker
broker = LogBroker()
