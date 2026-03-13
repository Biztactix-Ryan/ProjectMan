"""EventBus for real-time project change notifications."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    """A single event emitted by the EventBus."""

    id: int
    type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Simple async pub/sub for SSE event streaming.

    Each connected client gets its own asyncio.Queue.  Publishers call
    ``publish()`` which fans out to all subscriber queues.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._counter = 0
        self._lock = asyncio.Lock()

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        async with self._lock:
            self._counter += 1
            event = Event(id=self._counter, type=event_type, data=data)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # drop event for slow clients

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=256)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass


class NoOpEventBus:
    """Drop-in replacement that silently discards all events (stdio mode)."""

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        pass

    def subscribe(self) -> None:  # type: ignore[override]
        return None

    def unsubscribe(self, queue: Any) -> None:
        pass
