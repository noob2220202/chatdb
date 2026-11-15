"""/api/stream 테스트.

httpx 의 ASGITransport 는 응답이 끝날 때까지 본문을 모아 두기 때문에, 열려 있는 스트림은
제너레이터를 직접 돌리거나 ASGI 앱을 직접 불러서 확인한다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.events import EventBus
from app.routers.stream import (
    AUTH_RECHECK_SECONDS,
    PING_FRAME,
    PING_INTERVAL_SECONDS,
    READY_FRAME,
    event_stream,
    format_event,
)
from app.security import COOKIE_NAME

from .conftest import ADMIN_PASSWORD

STEP_TIMEOUT = 2.0


async def never() -> bool:
    return False


async def next_frame(stream) -> str:
    return await asyncio.wait_for(anext(stream), STEP_TIMEOUT)


async def remaining_frames(stream) -> list[str]:
    """스트림이 스스로 끝날 때까지 나온 프레임. 끝나지 않으면 시간 초과로 실패한다."""

    async def drain() -> list[str]:
        return [frame async for frame in stream]

    return await asyncio.wait_for(drain(), STEP_TIMEOUT)


def parse_frame(frame: str) -> tuple[str, Any]:
    """'event: x\\ndata: {...}\\n\\n' → (x, 값)."""
    assert frame.endswith("\n\n")
    lines = frame[:-2].split("\n")
    assert len(lines) == 2, frame
    assert lines[0].startswith("event: ") and lines[1].startswith("data: ")
    return lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))


# --- 프레임 ------------------------------------------------------------------


def test_ready_frame_carries_data_so_browsers_dispatch_it():
    assert parse_frame(READY_FRAME) == ("ready", {})


def test_ping_frame_is_a_comment():
    assert PING_FRAME == ": ping\n\n"


def test_ping_interval_is_fifteen_seconds():
    assert PING_INTERVAL_SECONDS == 15


async def test_format_event_is_one_event_line_and_one_data_line():
    bus = EventBus()
    async with bus.subscribe() as queue:
        bus.publish("log", {"id": 3, "message": "첫 줄\n둘째 줄\r\n끝", "account_id": None})
        event = queue.get_nowait()

    frame = format_event(event)

    assert frame.count("\n") == 3
    assert "\r" not in frame
    assert "첫 줄" in frame  # 한글을 \uXXXX 로 바꾸지 않는다
    assert parse_frame(frame) == (
        "log",
        {"id": 3, "message": "첫 줄\n둘째 줄\r\n끝", "account_id": None},
    )


# --- 제너레이터 ---------------------------------------------------------------


async def test_stream_starts_with_ready_after_subscribing():
    bus = EventBus()
    stream = event_stream(bus, never)

    assert bus.subscriber_count == 0
    assert await next_frame(stream) == READY_FRAME
    # ready 를 받은 뒤에 일어난 일은 놓치지 않는다.
    assert bus.subscriber_count == 1

    await stream.aclose()
    assert bus.subscriber_count == 0


async def test_stream_forwards_bus_events_in_order():
    bus = EventBus()
    stream = event_stream(bus, never)
    await next_frame(stream)

    bus.publish("hit", {"hit_id": 1, "username": "buyer_one"})
    bus.publish("group", {"id": 7, "status": "joined"})
    bus.publish("account", {"id": 2, "status": "flood_wait"})
    bus.publish("log", {"id": 9, "message": "그룹 3개를 가입 대기열에 넣었어요."})

    frames = [parse_frame(await next_frame(stream)) for _ in range(4)]
    assert frames == [
        ("hit", {"hit_id": 1, "username": "buyer_one"}),
        ("group", {"id": 7, "status": "joined"}),
        ("account", {"id": 2, "status": "flood_wait"}),
        ("log", {"id": 9, "message": "그룹 3개를 가입 대기열에 넣었어요."}),
    ]
    await stream.aclose()


async def test_stream_delivers_an_event_published_while_waiting():
    bus = EventBus()
    stream = event_stream(bus, never, ping_interval=30)
    await next_frame(stream)

    waiting = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0.01)
    assert not waiting.done()
    bus.publish("hit", {"hit_id": 5})

    assert parse_frame(await asyncio.wait_for(waiting, STEP_TIMEOUT)) == ("hit", {"hit_id": 5})
    await stream.aclose()


async def test_stream_pings_when_quiet_and_keeps_going():
    bus = EventBus()
    stream = event_stream(bus, never, ping_interval=0.01)
    await next_frame(stream)

    assert await next_frame(stream) == PING_FRAME
    assert await next_frame(stream) == PING_FRAME
    bus.publish("hit", {"hit_id": 1})
    assert parse_frame(await next_frame(stream)) == ("hit", {"hit_id": 1})
    assert await next_frame(stream) == PING_FRAME
    await stream.aclose()


async def test_stream_does_not_ping_while_events_keep_coming():
    bus = EventBus()
    stream = event_stream(bus, never, ping_interval=0.2)
    await next_frame(stream)

    for i in range(5):
        bus.publish("hit", {"hit_id": i})
    frames = [await next_frame(stream) for _ in range(5)]

    assert PING_FRAME not in frames


async def test_stream_stops_when_told_to_while_quiet():
    bus = EventBus()
    gone = False

    async def should_stop() -> bool:
        return gone

    stream = event_stream(bus, should_stop, ping_interval=0.01)
    await next_frame(stream)
    assert await next_frame(stream) == PING_FRAME

    gone = True

    # 멈추라는 답을 들은 뒤에는 더 보내지 않고 구독도 정리한다.
    assert await remaining_frames(stream) in ([], [PING_FRAME])
    assert bus.subscriber_count == 0


async def test_stream_stops_when_told_to_after_an_event():
    bus = EventBus()
    gone = False

    async def should_stop() -> bool:
        return gone

    stream = event_stream(bus, should_stop, ping_interval=30)
    await next_frame(stream)
    bus.publish("hit", {"hit_id": 1})
    assert parse_frame(await next_frame(stream)) == ("hit", {"hit_id": 1})

    gone = True
    bus.publish("hit", {"hit_id": 2})

    assert await remaining_frames(stream) == []
    assert bus.subscriber_count == 0


async def test_stream_unsubscribes_when_cancelled():
    bus = EventBus()
    stream = event_stream(bus, never, ping_interval=30)
    await next_frame(stream)

    waiting = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0.01)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    assert bus.subscriber_count == 0


async def test_each_stream_gets_every_event():
    bus = EventBus()
    first = event_stream(bus, never)
    second = event_stream(bus, never)
    await next_frame(first)
    await next_frame(second)
    assert bus.subscriber_count == 2

    bus.publish("hit", {"hit_id": 1})

    assert parse_frame(await next_frame(first)) == ("hit", {"hit_id": 1})
    assert parse_frame(await next_frame(second)) == ("hit", {"hit_id": 1})
    await first.aclose()
    assert bus.subscriber_count == 1
    await second.aclose()
    assert bus.subscriber_count == 0


# --- HTTP --------------------------------------------------------------------


async def test_stream_requires_login(client, ctx):
    res = await client.get("/api/stream")

    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"
    assert ctx.bus.subscriber_count == 0


class RawStream:
    """ASGI 앱에 직접 붙은 연결 하나. 보낸 메시지를 차례로 받아 보고, 원할 때 끊는다.

    spec_version 2.3 은 uvicorn 과 같다(끊기면 receive 로 http.disconnect 가 온다).
    2.4 이상인 서버는 거기에 더해, 끊긴 뒤의 send 가 OSError 를 던진다.
    """

    def __init__(self, app, cookie: str, spec_version: str = "2.3") -> None:
        self._incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._incoming.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        self._send_fails_after_disconnect = spec_version != "2.3"
        self._disconnected = False
        self.error: BaseException | None = None
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": spec_version},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/stream",
            "raw_path": b"/api/stream",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"accept", b"text/event-stream"),
                (b"cookie", f"{COOKIE_NAME}={cookie}".encode()),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        self.task = asyncio.ensure_future(app(scope, self._incoming.get, self._send))

    async def _send(self, message: dict[str, Any]) -> None:
        if self._disconnected and self._send_fails_after_disconnect:
            raise OSError("client disconnected")
        await self._sent.put(message)

    async def message(self) -> dict[str, Any]:
        return await asyncio.wait_for(self._sent.get(), STEP_TIMEOUT)

    async def frame(self) -> str:
        message = await self.message()
        assert message["type"] == "http.response.body"
        return message["body"].decode()

    def disconnect(self) -> None:
        self._disconnected = True
        self._incoming.put_nowait({"type": "http.disconnect"})

    async def closed(self) -> None:
        """앱이 이 연결의 처리를 끝낼 때까지 기다린다. 끝나지 않으면 실패한다."""
        done, _pending = await asyncio.wait({self.task}, timeout=STEP_TIMEOUT)
        assert done, "스트림이 끝나지 않았어요"
        # 전송 실패로 끝난 경우 서버 쪽으로 올라간 예외는 여기서 받아 둔다.
        self.error = self.task.exception()


@pytest.fixture
async def cookie(authed) -> str:
    return authed.cookies.get(COOKIE_NAME)


async def test_stream_over_asgi(app, ctx, cookie):
    stream = RawStream(app, cookie)

    start = await stream.message()
    assert start["type"] == "http.response.start"
    assert start["status"] == 200
    headers = {name.decode().lower(): value.decode() for name, value in start["headers"]}
    assert headers["content-type"] == "text/event-stream; charset=utf-8"
    assert headers["cache-control"] == "no-cache"
    assert headers["x-accel-buffering"] == "no"

    assert await stream.frame() == READY_FRAME
    assert ctx.bus.subscriber_count == 1

    ctx.bus.publish("hit", {"hit_id": 1, "username": "buyer_one"})
    assert parse_frame(await stream.frame()) == ("hit", {"hit_id": 1, "username": "buyer_one"})
    await ctx.logbook.info("그룹 3개를 가입 대기열에 넣었어요.")
    event, data = parse_frame(await stream.frame())
    assert (event, data["message"]) == ("log", "그룹 3개를 가입 대기열에 넣었어요.")

    stream.disconnect()
    await stream.closed()
    assert stream.error is None
    assert ctx.bus.subscriber_count == 0


async def test_stream_over_asgi_ends_when_sending_to_a_gone_client_fails(app, ctx, cookie):
    # ASGI 2.4 서버에서는 Starlette 가 끊김을 따로 감시하지 않는다. 다음 프레임(늦어도 ping)을
    # 보내다가 실패하는 순간 스트림이 정리돼야 한다.
    stream = RawStream(app, cookie, spec_version="2.4")
    assert (await stream.message())["status"] == 200
    assert await stream.frame() == READY_FRAME
    ctx.bus.publish("hit", {"hit_id": 1})
    assert parse_frame(await stream.frame()) == ("hit", {"hit_id": 1})

    stream.disconnect()
    ctx.bus.publish("hit", {"hit_id": 2})

    await stream.closed()
    assert ctx.bus.subscriber_count == 0


async def test_open_stream_does_not_hold_a_database_connection(app, ctx, cookie):
    stream = RawStream(app, cookie)
    await stream.message()
    assert await stream.frame() == READY_FRAME

    assert ctx.db.engine.pool.checkedout() == 0

    stream.disconnect()
    await stream.closed()


async def test_many_open_streams_do_not_exhaust_the_pool(app, authed, ctx, cookie):
    streams = [RawStream(app, cookie) for _ in range(20)]
    for stream in streams:
        await stream.message()
        assert await stream.frame() == READY_FRAME
    assert ctx.bus.subscriber_count == 20

    # 스트림이 스무 개 열려 있어도 다른 요청은 평소처럼 처리된다.
    res = await asyncio.wait_for(authed.get("/api/settings"), STEP_TIMEOUT)
    assert res.status_code == 200

    for stream in streams:
        stream.disconnect()
    for stream in streams:
        await stream.closed()
    assert ctx.bus.subscriber_count == 0


class FakeClock:
    """스트림이 로그인을 다시 확인할 때 보는 시계."""

    def __init__(self) -> None:
        self.now = 500.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr("app.routers.stream.time", fake)
    return fake


async def change_password(authed) -> None:
    res = await authed.post(
        "/api/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "brand new password"},
    )
    assert res.status_code == 200


async def test_open_stream_ends_after_the_login_is_invalidated(app, authed, ctx, cookie, clock):
    stream = RawStream(app, cookie)
    await stream.message()
    assert await stream.frame() == READY_FRAME

    await change_password(authed)
    event, data = parse_frame(await stream.frame())
    assert event == "log" and data["message"].startswith("관리자 비밀번호를 바꿨어요")
    clock.now += AUTH_RECHECK_SECONDS - 1
    ctx.bus.publish("hit", {"hit_id": 1})
    assert parse_frame(await stream.frame()) == ("hit", {"hit_id": 1})
    # 아직 다시 확인할 때가 아니다. 다음 확인 때 끊긴다.
    assert ctx.bus.subscriber_count == 1

    # 확인할 때가 지나면, 다음에 깨어날 때(이벤트든 ping 이든) 스트림을 정상 종료한다.
    clock.now += 1
    ctx.bus.publish("hit", {"hit_id": 2})
    await stream.closed()
    assert stream.error is None
    assert ctx.bus.subscriber_count == 0
    assert ctx.db.engine.pool.checkedout() == 0


async def test_open_stream_survives_rechecks_while_the_login_is_valid(app, ctx, cookie, clock):
    stream = RawStream(app, cookie)
    await stream.message()
    assert await stream.frame() == READY_FRAME

    for i in range(3):
        clock.now += AUTH_RECHECK_SECONDS
        ctx.bus.publish("hit", {"hit_id": i})
        assert parse_frame(await stream.frame()) == ("hit", {"hit_id": i})

    assert not stream.task.done()
    assert ctx.bus.subscriber_count == 1
    # 다시 확인하는 데 쓴 DB 커넥션도 바로 돌려준다.
    assert ctx.db.engine.pool.checkedout() == 0
    stream.disconnect()
    await stream.closed()


async def test_the_browser_that_changed_the_password_keeps_its_stream(
    app, authed, ctx, cookie, clock
):
    # 비밀번호를 바꾼 브라우저는 새 쿠키를 받지만, 이미 열린 스트림은 예전 쿠키로 열려 있다.
    # 스트림은 끊기고, 브라우저가 새 쿠키로 다시 연결하면 된다.
    await change_password(authed)
    fresh = authed.cookies.get(COOKIE_NAME)
    assert fresh != cookie

    stream = RawStream(app, fresh)
    assert (await stream.message())["status"] == 200
    assert await stream.frame() == READY_FRAME
    clock.now += AUTH_RECHECK_SECONDS
    ctx.bus.publish("hit", {"hit_id": 1})
    assert parse_frame(await stream.frame()) == ("hit", {"hit_id": 1})
    assert not stream.task.done()
    stream.disconnect()
    await stream.closed()


async def test_stream_over_asgi_rejects_a_stale_cookie(app, authed, ctx, cookie):
    await change_password(authed)

    stream = RawStream(app, cookie)

    start = await stream.message()
    assert start["status"] == 401
    await stream.closed()
    assert ctx.bus.subscriber_count == 0
