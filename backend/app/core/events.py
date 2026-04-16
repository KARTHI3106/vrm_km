"""
Server-Sent Events (SSE) manager for real-time workflow updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from app.core.redis_state import get_redis, _state_key

logger = logging.getLogger(__name__)

_channel = "vrm:workflow_events"


class EventManager:
    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._listener_task: Optional[asyncio.Task] = None

    async def start(self):
        try:
            r = get_redis()
            pubsub = r.pubsub()
            pubsub.subscribe(_channel)
            self._listener_task = asyncio.create_task(self._listen(pubsub))
            logger.info("SSE event listener started")
        except Exception as exc:
            logger.warning("SSE listener could not start: %s", exc)

    async def _listen(self, pubsub):
        try:
            for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    vendor_id = data.get("vendor_id", "")
                    queues = self._subscribers.get(vendor_id, [])
                    dead = []
                    for q in queues:
                        try:
                            q.put_nowait(data)
                        except asyncio.QueueFull:
                            dead.append(q)
                    for q in dead:
                        queues.remove(q)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("SSE listener error: %s", exc)

    async def stop(self):
        if self._listener_task:
            self._listener_task.cancel()
        logger.info("SSE event listener stopped")

    def subscribe(self, vendor_id: str) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(vendor_id, []).append(q)
        return q

    def unsubscribe(self, vendor_id: str, q: asyncio.Queue):
        queues = self._subscribers.get(vendor_id, [])
        if q in queues:
            queues.remove(q)
        if not queues:
            self._subscribers.pop(vendor_id, None)


event_manager = EventManager()


def publish_event(vendor_id: str, event_type: str, data: dict | None = None):
    try:
        r = get_redis()
        payload = {
            "vendor_id": vendor_id,
            "event_type": event_type,
            "data": data or {},
        }
        r.publish(_channel, json.dumps(payload, default=str))
    except Exception as exc:
        logger.debug("Event publish failed: %s", exc)
