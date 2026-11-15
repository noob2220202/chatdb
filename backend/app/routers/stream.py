"""/stream 라우터. 이벤트 버스의 변화를 SSE 로 화면에 밀어 준다."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..context import AppContext
from ..deps import Ctx, DbSession, current_admin, require_admin
from ..events import Event, EventBus

router = APIRouter(prefix="/stream", tags=["stream"], dependencies=[Depends(require_admin)])

PING_INTERVAL_SECONDS = 15.0
AUTH_RECHECK_SECONDS = 15.0
"""열려 있는 스트림의 로그인이 아직 유효한지 다시 확인하는 간격."""
READY_FRAME = "event: ready\ndata: {}\n\n"
"""data 줄이 없는 이벤트는 브라우저(EventSource)가 버리기 때문에 빈 객체를 싣는다."""
PING_FRAME = ": ping\n\n"


def format_event(event: Event) -> str:
    """버스 이벤트 하나를 SSE 프레임으로 바꾼다. JSON 은 줄바꿈을 이스케이프하므로 한 줄이다."""
    data = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.type}\ndata: {data}\n\n"


async def event_stream(
    bus: EventBus,
    should_stop: Callable[[], Awaitable[bool]],
    *,
    ping_interval: float = PING_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """구독을 열고 SSE 프레임을 차례로 내놓는다.

    ping_interval 초 동안 조용하면 주석 한 줄(ping)을 보내 연결을 살려 둔다.
    프레임을 하나 보낼 때마다 should_stop 을 물어보고, True 면 끝낸다.
    클라이언트가 끊기면 보통은 그 전에 서버가 이 제너레이터를 취소하거나(uvicorn) 다음 프레임
    전송이 실패하면서 닫힌다. 어떻게 끝나든 구독은 정리된다.
    """
    async with bus.subscribe() as queue:
        yield READY_FRAME
        while not await should_stop():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=ping_interval)
            except TimeoutError:
                yield PING_FRAME
            else:
                yield format_event(event)


async def _login_is_valid(request: Request, ctx: AppContext) -> bool:
    async with ctx.db.session() as session:
        return await current_admin(request, ctx, session) is not None


def stop_check(request: Request, ctx: AppContext) -> Callable[[], Awaitable[bool]]:
    """이 연결의 스트림을 그만 보내야 하는지 알려 주는 함수를 만든다.

    클라이언트가 끊었을 때, 그리고 스트림이 열려 있는 사이에 로그인이 무효가 됐을 때다
    (비밀번호를 바꿔 다른 기기를 로그아웃시킨 경우, 쿠키가 만료된 경우).
    로그인은 AUTH_RECHECK_SECONDS 에 한 번만 DB 에서 다시 확인한다.

    끊김 확인(request.is_disconnected)은 main.py 의 http 미들웨어 뒤에서는 끊김을 알려 주지
    못한다. 그 경우에도 서버가 스트림을 취소하거나 전송이 실패하면서 끝나므로 구독이 남지는 않는다.
    """
    checked_at = time.monotonic()

    async def should_stop() -> bool:
        nonlocal checked_at
        if await request.is_disconnected():
            return True
        now = time.monotonic()
        if now - checked_at < AUTH_RECHECK_SECONDS:
            return False
        checked_at = now
        # 조회 도중에 연결이 끊겨 취소되더라도 DB 커넥션은 끝까지 정리되도록 감싼다.
        return not await asyncio.shield(_login_is_valid(request, ctx))

    return should_stop


@router.get(
    "",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "SSE 스트림. ready 이벤트 뒤에 hit·account·group·log 이벤트가 온다.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def stream(request: Request, ctx: Ctx, session: DbSession) -> StreamingResponse:
    # 스트림은 몇 시간씩 열려 있다. 로그인 확인에 쓴 DB 커넥션을 붙잡고 있지 않도록 먼저 돌려준다.
    await session.close()
    return StreamingResponse(
        event_stream(ctx.bus, stop_check(request, ctx)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
