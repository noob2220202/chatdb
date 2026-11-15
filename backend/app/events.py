"""프로세스 안 이벤트 버스. 실시간 화면(SSE)에 변화를 밀어 준다."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

EventType = Literal["hit", "account", "group", "log"]


@dataclass(frozen=True)
class Event:
    type: EventType
    data: dict[str, Any]
    """JSON 으로 바로 보낼 수 있는 값 (schemas 의 *Out 모델을 model_dump(mode="json") 한 것)."""


class EventBus:
    """구독자마다 큐를 하나씩 둔다. 느린 구독자는 오래된 이벤트부터 버린다."""

    def __init__(self, queue_size: int = 500) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[Event]] = set()

    def publish(self, type: EventType, data: dict[str, Any]) -> None:
        event = Event(type, data)
        for queue in list(self._subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
