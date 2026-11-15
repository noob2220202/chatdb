"""/stream 라우터. 이벤트 버스의 변화를 SSE 로 화면에 밀어 준다."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..deps import Ctx, DbSession, require_admin
from ..events import Event, EventBus

router = APIRouter(prefix="/stream", tags=["stream"], dependencies=[Depends(require_admin)])

PING_INTERVAL_SECONDS = 15.0
READY_FRAME = "event: ready\ndata: {}\n\n"
"""data 줄이 없는 이벤트는 브라우저(EventSource)가 버리기 때문에 빈 객체를 싣는다."""
PING_FRAME = ": ping\n\n"


def format_event(event: Event) -> str:
    """버스 이벤트 하나를 SSE 프레임으로 바꾼다. JSON 은 줄바꿈을 이스케이프하므로 한 줄이다."""
    data = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.type}\ndata: {data}\n\n"


async def event_stream(
    bus: EventBus,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    ping_interval: float = PING_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """구독을 열고 SSE 프레임을 차례로 내놓는다.

    ping_interval 초 동안 조용하면 주석 한 줄(ping)을 보내 연결을 살려 둔다.
    클라이언트가 끊으면 멈추고, 어떻게 끝나든 구독은 정리된다.
    """
    async with bus.subscribe() as queue:
        yield READY_FRAME
        while not await is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=ping_interval)
            except TimeoutError:
                yield PING_FRAME
            else:
                yield format_event(event)


@router.get("", response_class=StreamingResponse)
async def stream(request: Request, ctx: Ctx, session: DbSession) -> StreamingResponse:
    # 스트림은 몇 시간씩 열려 있다. 로그인 확인에 쓴 DB 커넥션을 붙잡고 있지 않도록 먼저 돌려준다.
    await session.close()
    return StreamingResponse(
        event_stream(ctx.bus, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
