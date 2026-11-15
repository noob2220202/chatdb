"""엔진 테스트. 가짜 게이트웨이, 실제 수집기, 임시 SQLite 파일로 돌린다.

엔진의 기다림은 모두 FakeClock 기준이라, 시계를 앞으로 돌려서 간격·재시도·요청 제한을 시험한다.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import Config
from app.db import Database, utcnow
from app.events import Event, EventBus
from app.links import LinkTarget
from app.models import (
    Account,
    AccountStatus,
    EventLog,
    Group,
    GroupKind,
    GroupStatus,
    Hit,
    LinkKind,
    LogLevel,
    MatchMode,
    Rule,
    RuleKind,
)
from app.security import Secrets
from app.services.collector import Collector
from app.services.logbook import Logbook
from app.settings_store import SettingsStore
from app.telegram.engine import Engine, EngineTimings
from app.telegram.gateway import (
    JoinOutcome,
    JoinResult,
    LoginResult,
    TelegramError,
    TgErrorCode,
    TgUser,
)

from .fakes import FakeGateway, make_chat

START = datetime(2026, 3, 10, 3, 0, tzinfo=UTC)
JOIN_INTERVAL = 90
FAST = EngineTimings(tick=0.005, call_timeout=2.0)

ALICE = TgUser(id=501, username="alice_kim", first_name="앨리스", last_name="김")


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def session_invalid() -> TelegramError:
    return TelegramError(
        TgErrorCode.SESSION_INVALID, "세션이 만료됐어요. 다시 로그인해 주세요.", permanent=True
    )


def network_error() -> TelegramError:
    return TelegramError(TgErrorCode.NETWORK, "텔레그램에 연결하지 못했어요.")


def flood(seconds: int) -> TelegramError:
    return TelegramError(
        TgErrorCode.FLOOD_WAIT, "텔레그램이 요청을 잠시 제한했어요.", retry_after=seconds
    )


def joined(number: int, **chat: Any) -> JoinResult:
    return JoinResult(JoinOutcome.JOINED, chat=make_chat(number, **chat))


async def eventually(
    check: Callable[[], bool | Awaitable[bool]], *, what: str = "조건", within: float = 5.0
) -> None:
    """check 가 참이 될 때까지 짧게 쉬어 가며 기다린다."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within
    while True:
        result = check()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return
        if loop.time() > deadline:
            pytest.fail(f"{within}초 안에 이뤄지지 않았어요: {what}")
        await asyncio.sleep(0.005)


def runner_alive(account_id: int) -> bool:
    """그 계정의 연결 태스크가 아직 돌고 있는지."""
    return any(task.get_name() == f"engine-account-{account_id}" for task in asyncio.all_tasks())


async def settle() -> None:
    """엔진이 하던 일을 마치고 다음 기다림에 들어갈 시간을 준다."""
    await asyncio.sleep(0.05)


@dataclass
class Env:
    db: Database
    bus: EventBus
    settings: SettingsStore
    secrets: Secrets
    logbook: Logbook
    clock: FakeClock
    collector: Collector
    gateway: FakeGateway
    queue: asyncio.Queue[Event]
    engine: Engine = field(init=False)
    _order: Iterator[int] = field(default_factory=lambda: itertools.count(1))

    def __post_init__(self) -> None:
        self.engine = self.new_engine()

    def new_engine(
        self, timings: EngineTimings = FAST, *, clock: Callable[[], datetime] | None = None
    ) -> Engine:
        """같은 DB·게이트웨이를 쓰는 엔진을 새로 만든다. clock 을 주지 않으면 FakeClock 을 쓴다."""
        return Engine(
            db=self.db,
            bus=self.bus,
            settings=self.settings,
            secrets=self.secrets,
            gateway=self.gateway,
            collector=self.collector,
            logbook=self.logbook,
            clock=clock or self.clock,
            timings=timings,
        )

    # --- 준비 ---------------------------------------------------------------

    async def add_account(
        self, *, session: str | None = "stored-session", enabled: bool = True, **values: Any
    ) -> int:
        async with self.db.session() as db_session:
            account = Account(
                session_enc=self.secrets.encrypt(session) if session is not None else None,
                enabled=enabled,
                **values,
            )
            db_session.add(account)
            await db_session.commit()
            return account.id

    async def add_group(
        self,
        account_id: int,
        link: str | None = None,
        *,
        invite: str | None = None,
        status: GroupStatus = GroupStatus.QUEUED,
        **values: Any,
    ) -> int:
        """link 는 공개 아이디, invite 는 초대 해시. 만든 순서대로 created_at 이 늦어진다."""
        async with self.db.session() as db_session:
            group = Group(
                account_id=account_id,
                link_kind=LinkKind.INVITE if invite else LinkKind.PUBLIC,
                public_username=link,
                invite_hash=invite,
                source_link=f"https://t.me/+{invite}" if invite else f"https://t.me/{link}",
                status=status,
                created_at=START + timedelta(seconds=next(self._order)),
                **values,
            )
            db_session.add(group)
            await db_session.commit()
            return group.id

    async def add_keyword_rule(self, *keywords: str) -> int:
        async with self.db.session() as db_session:
            rule = Rule(
                name="키워드 규칙",
                kind=RuleKind.KEYWORD,
                enabled=True,
                keywords=list(keywords),
                exclude_keywords=[],
                match_mode=MatchMode.ANY,
                all_groups=True,
            )
            db_session.add(rule)
            await db_session.commit()
            return rule.id

    # --- 실행 ---------------------------------------------------------------

    async def start(self, *active: int) -> None:
        """엔진을 켜고, active 로 준 계정들이 연결될 때까지 기다린다."""
        await self.engine.start()
        for account_id in active:
            await self.wait_connected(account_id)

    async def advance(self, seconds: float) -> None:
        """엔진이 지금 하던 일을 마친 뒤에 시계를 앞으로 돌린다."""
        await settle()
        self.clock.now += timedelta(seconds=seconds)

    # --- 확인 ---------------------------------------------------------------

    async def account(self, account_id: int) -> Account | None:
        async with self.db.session() as db_session:
            return await db_session.get(Account, account_id)

    async def group(self, group_id: int) -> Group | None:
        async with self.db.session() as db_session:
            return await db_session.get(Group, group_id)

    async def wait_account(self, account_id: int, status: AccountStatus) -> Account:
        async def reached() -> bool:
            account = await self.account(account_id)
            return account is not None and account.status == status

        await eventually(reached, what=f"계정 {account_id} 의 상태가 {status}")
        account = await self.account(account_id)
        assert account is not None
        return account

    async def wait_connected(self, account_id: int) -> Account:
        """계정이 정상 상태가 되고 메시지를 받을 준비까지 마칠 때까지 기다린다."""
        account = await self.wait_account(account_id, AccountStatus.ACTIVE)
        await eventually(
            lambda: self.engine.is_connected(account_id), what=f"계정 {account_id} 연결"
        )
        return account

    async def wait_group(self, group_id: int, status: GroupStatus) -> Group:
        async def reached() -> bool:
            group = await self.group(group_id)
            return group is not None and group.status == status

        await eventually(reached, what=f"그룹 {group_id} 의 상태가 {status}")
        group = await self.group(group_id)
        assert group is not None
        return group

    async def wait_calls(self, name: str, count: int, account_id: int | None = None) -> None:
        await eventually(
            lambda: len(self.gateway.called(name, account_id)) >= count,
            what=f"{name} 호출 {count}번",
        )

    async def logs(self) -> list[EventLog]:
        async with self.db.session() as db_session:
            return list((await db_session.scalars(select(EventLog).order_by(EventLog.id))).all())

    async def log_messages(self) -> list[str]:
        return [log.message for log in await self.logs()]

    async def hits(self) -> list[Hit]:
        async with self.db.session() as db_session:
            return list((await db_session.scalars(select(Hit).order_by(Hit.id))).all())

    def events(self, kind: str) -> list[dict[str, Any]]:
        """지금까지 발행된 이벤트 중 kind 종류의 data 를 꺼낸다(큐를 비운다)."""
        found: list[dict[str, Any]] = []
        while not self.queue.empty():
            event = self.queue.get_nowait()
            if event.type == kind:
                found.append(event.data)
        return found

    def joins(self) -> list[str]:
        """join() 이 불린 링크 값들(순서대로)."""
        return [args[0].value for args in self.gateway.called("join")]


@pytest_asyncio.fixture
async def env(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'engine.sqlite3'}")
    await db.create_all()
    config = Config(
        _env_file=None,
        data_dir=tmp_path,
        secret_key="test-secret-key",
        engine_enabled=False,
        demo=False,
    )
    secrets = Secrets("test-secret-key", 3600)
    bus = EventBus()
    settings = SettingsStore(db, secrets, config)
    logbook = Logbook(db, bus)
    clock = FakeClock(START)
    collector = Collector(db=db, bus=bus, settings=settings, logbook=logbook, clock=clock)
    gateway = FakeGateway()
    async with bus.subscribe() as queue:
        environment = Env(
            db=db,
            bus=bus,
            settings=settings,
            secrets=secrets,
            logbook=logbook,
            clock=clock,
            collector=collector,
            gateway=gateway,
            queue=queue,
        )
        try:
            yield environment
        finally:
            await environment.engine.stop()
            await db.dispose()


# ---------------------------------------------------------------------------
# 켜기 · 끄기
# ---------------------------------------------------------------------------


async def test_start_connects_enabled_accounts(env: Env) -> None:
    first = await env.add_account(session="session-a")
    second = await env.add_account(session="session-b", phone="+821011112222")
    env.gateway.users[first] = TgUser(
        id=9001, username="owner_one", first_name="하나", last_name="김", phone="+821099990000"
    )

    await env.start(first, second)

    account = await env.account(first)
    assert account is not None
    assert account.tg_user_id == 9001
    assert (account.first_name, account.last_name, account.username) == ("하나", "김", "owner_one")
    assert account.phone == "+821099990000"  # 비어 있던 번호는 채운다
    assert account.last_connected_at == START
    assert account.status_detail is None
    other = await env.account(second)
    assert other is not None and other.phone == "+821011112222"  # 이미 있던 번호는 그대로

    assert env.engine.is_connected(first) and env.engine.is_connected(second)
    assert env.gateway.client(first).session == "session-a"
    assert env.gateway.client(second).session == "session-b"
    assert len(env.gateway.clients) == 2
    statuses = [(data["id"], data["status"]) for data in env.events("account")]
    assert (first, "active") in statuses and (second, "active") in statuses
    connected = [log for log in await env.logs() if log.message == "텔레그램에 연결됐어요."]
    assert {log.account_id for log in connected} == {first, second}


async def test_start_is_idempotent(env: Env) -> None:
    account_id = await env.add_account()
    await env.start(account_id)

    await env.engine.start()
    await settle()

    assert len(env.gateway.clients) == 1
    assert env.engine.is_connected(account_id)


async def test_disabled_account_stays_offline(env: Env) -> None:
    account_id = await env.add_account(enabled=False, status=AccountStatus.ACTIVE)

    await env.start()
    await settle()

    account = await env.account(account_id)
    assert account is not None and account.status == AccountStatus.OFFLINE
    assert env.gateway.clients == []
    assert not env.engine.is_connected(account_id)


async def test_enabled_account_without_session_needs_reauth(env: Env) -> None:
    account_id = await env.add_account(session=None, status=AccountStatus.ACTIVE)

    await env.start()
    await settle()

    account = await env.account(account_id)
    assert account is not None and account.status == AccountStatus.REAUTH_REQUIRED
    assert account.status_detail == "저장된 세션이 없어요. 다시 로그인해 주세요."
    assert env.gateway.clients == []


async def test_unreadable_session_needs_reauth(env: Env) -> None:
    account_id = await env.add_account()
    async with env.db.session() as session:
        account = await session.get(Account, account_id)
        assert account is not None
        account.session_enc = "not-a-valid-token"
        await session.commit()

    await env.start()

    account = await env.wait_account(account_id, AccountStatus.REAUTH_REQUIRED)
    assert account.status_detail == "저장된 세션을 읽을 수 없어요. 다시 로그인해 주세요."
    assert env.gateway.clients == []
    await eventually(lambda: not runner_alive(account_id), what="연결 태스크 종료")


async def test_start_requeues_groups_stuck_in_joining(env: Env) -> None:
    account_id = await env.add_account(enabled=False)
    stuck = await env.add_group(account_id, "alpha", status=GroupStatus.JOINING)
    done = await env.add_group(
        account_id, "beta", status=GroupStatus.JOINED, tg_chat_id=make_chat(2).id
    )

    await env.start()

    group = await env.group(stuck)
    assert group is not None and group.status == GroupStatus.QUEUED
    untouched = await env.group(done)
    assert untouched is not None and untouched.status == GroupStatus.JOINED


async def test_connect_saves_rotated_session(env: Env) -> None:
    account_id = await env.add_account(session="old-session")
    env.gateway.session_after_connect[account_id] = "rotated-session"

    await env.start(account_id)

    account = await env.account(account_id)
    assert account is not None and account.session_enc is not None
    assert env.secrets.decrypt(account.session_enc) == "rotated-session"


async def test_session_of_already_registered_user_is_rejected(env: Env) -> None:
    await env.add_account(session="session-a", tg_user_id=9001, enabled=False)
    clone = await env.add_account(session="session-b")
    env.gateway.users[clone] = TgUser(id=9001, username="owner_one")

    await env.start()

    account = await env.wait_account(clone, AccountStatus.REAUTH_REQUIRED)
    assert account.tg_user_id is None
    assert "이미 등록된 다른 계정" in (account.status_detail or "")


async def test_stop_leaves_no_tasks_and_disconnects(env: Env) -> None:
    before = asyncio.all_tasks()
    first = await env.add_account(session="session-a")
    second = await env.add_account(session="session-b")
    waiting = await env.add_account(session="session-c")
    env.gateway.script_connect(waiting, network_error())
    await env.add_group(first, "alpha")
    await env.add_group(second, invite="RequestedHash1", status=GroupStatus.REQUESTED)
    await env.start(first, second)
    await env.wait_account(waiting, AccountStatus.ERROR)

    await env.engine.stop()
    await asyncio.sleep(0)

    assert asyncio.all_tasks() - before == set()
    assert all(not client.connected for client in env.gateway.clients)
    assert all(client.handler is None for client in env.gateway.clients)
    assert env.gateway.closed
    assert not env.engine.is_connected(first)
    for account_id in (first, second, waiting):
        account = await env.account(account_id)
        assert account is not None and account.status == AccountStatus.OFFLINE

    await env.engine.stop()  # 두 번 멈춰도 괜찮다
    assert len(env.gateway.called("close")) == 1


async def test_stop_flushes_the_collector(env: Env) -> None:
    account_id = await env.add_account()
    chat = make_chat(1)
    group_id = await env.add_group(
        account_id, "alpha", status=GroupStatus.JOINED, tg_chat_id=chat.id
    )
    await env.start(account_id)
    await env.gateway.client(account_id).emit_message(chat.id, "안녕하세요", ALICE)

    await env.engine.stop()

    group = await env.group(group_id)
    assert group is not None and group.messages_seen == 1


def test_timings_need_a_backoff_schedule() -> None:
    with pytest.raises(ValueError):
        EngineTimings(reconnect_backoff=())


async def test_engine_can_be_started_again_after_stop(env: Env) -> None:
    account_id = await env.add_account()
    await env.start(account_id)
    await env.engine.stop()

    await env.start(account_id)

    assert len(env.gateway.clients) == 2
    assert env.engine.is_connected(account_id)


# ---------------------------------------------------------------------------
# 메시지
# ---------------------------------------------------------------------------


async def test_message_in_monitored_group_produces_hit(env: Env) -> None:
    account_id = await env.add_account()
    chat = make_chat(1)
    group_id = await env.add_group(
        account_id, "alpha", status=GroupStatus.JOINED, tg_chat_id=chat.id, title=chat.title
    )
    rule_id = await env.add_keyword_rule("구매")
    await env.start(account_id)

    await env.gateway.client(account_id).emit_message(chat.id, "이거 구매 문의 드려요", ALICE)

    hits = await env.hits()
    assert len(hits) == 1
    assert (hits[0].group_id, hits[0].rule_id, hits[0].account_id) == (
        group_id,
        rule_id,
        account_id,
    )
    assert hits[0].keywords == ["구매"]
    published = env.events("hit")
    assert len(published) == 1 and published[0]["username"] == "alice_kim"


async def test_unknown_and_unmonitored_chats_are_ignored(env: Env) -> None:
    account_id = await env.add_account()
    watched, muted, pending = make_chat(1), make_chat(2), make_chat(3)
    watched_id = await env.add_group(
        account_id, "alpha", status=GroupStatus.JOINED, tg_chat_id=watched.id
    )
    muted_id = await env.add_group(
        account_id, "beta", status=GroupStatus.JOINED, tg_chat_id=muted.id, monitoring=False
    )
    pending_id = await env.add_group(
        account_id, invite="PendingHash12", status=GroupStatus.REQUESTED, tg_chat_id=pending.id
    )
    await env.add_keyword_rule("구매")
    await env.start(account_id)
    client = env.gateway.client(account_id)

    await client.emit_message(make_chat(99).id, "구매 원해요", ALICE)  # 목록에 없는 방
    await client.emit_message(muted.id, "구매 원해요", ALICE)  # 감시를 꺼 둔 방
    await client.emit_message(pending.id, "구매 원해요", ALICE)  # 아직 가입되지 않은 방
    assert await env.hits() == []

    await client.emit_message(watched.id, "구매 원해요", ALICE)
    assert len(await env.hits()) == 1
    await env.collector.flush()
    seen = {}
    for group_id in (watched_id, muted_id, pending_id):
        group = await env.group(group_id)
        assert group is not None
        seen[group_id] = group.messages_seen
    assert seen == {watched_id: 1, muted_id: 0, pending_id: 0}


async def test_each_account_only_listens_to_its_own_groups(env: Env) -> None:
    first = await env.add_account(session="session-a")
    second = await env.add_account(session="session-b")
    chat = make_chat(1)
    await env.add_group(first, "alpha", status=GroupStatus.JOINED, tg_chat_id=chat.id)
    await env.add_keyword_rule("구매")
    await env.start(first, second)

    # 두 번째 계정도 그 방에 있지만 감시 목록에는 첫 번째 계정의 그룹으로만 올라 있다.
    await env.gateway.client(second).emit_message(chat.id, "구매 원해요", ALICE)
    assert await env.hits() == []

    await env.gateway.client(first).emit_message(chat.id, "구매 원해요", ALICE)
    hits = await env.hits()
    assert [hit.account_id for hit in hits] == [first]


async def test_notify_groups_changed_reloads_monitored_groups(env: Env) -> None:
    account_id = await env.add_account()
    chat = make_chat(1)
    group_id = await env.add_group(
        account_id, "alpha", status=GroupStatus.JOINED, tg_chat_id=chat.id, monitoring=False
    )
    await env.add_keyword_rule("구매")
    await env.start(account_id)
    client = env.gateway.client(account_id)
    await client.emit_message(chat.id, "구매 원해요", ALICE)
    assert await env.hits() == []

    async with env.db.session() as session:
        group = await session.get(Group, group_id)
        assert group is not None
        group.monitoring = True
        await session.commit()
    env.engine.notify_groups_changed(account_id)
    await settle()

    await client.emit_message(chat.id, "구매 원해요", ALICE)
    assert len(await env.hits()) == 1


async def test_messages_stop_after_account_is_disabled(env: Env) -> None:
    account_id = await env.add_account()
    chat = make_chat(1)
    await env.add_group(account_id, "alpha", status=GroupStatus.JOINED, tg_chat_id=chat.id)
    await env.add_keyword_rule("구매")
    await env.start(account_id)
    client = env.gateway.client(account_id)

    await env.engine.set_account_enabled(account_id, False)
    await client.emit_message(chat.id, "구매 원해요", ALICE)

    assert client.handler is None
    assert await env.hits() == []


# ---------------------------------------------------------------------------
# 가입 대기열
# ---------------------------------------------------------------------------


async def test_join_queue_honors_interval_and_order(env: Env) -> None:
    account_id = await env.add_account()
    first = await env.add_group(account_id, "alpha")
    second = await env.add_group(account_id, "beta")
    third = await env.add_group(account_id, invite="GammaHash123")

    await env.start(account_id)
    await env.wait_group(first, GroupStatus.JOINED)
    await settle()
    assert env.joins() == ["alpha"]  # 간격이 지나기 전에는 하나만
    account = await env.account(account_id)
    assert account is not None and account.last_join_at == START

    await env.advance(JOIN_INTERVAL - 1)
    await settle()
    assert env.joins() == ["alpha"]
    waiting = await env.group(second)
    assert waiting is not None and waiting.status == GroupStatus.QUEUED

    await env.advance(1)
    await env.wait_group(second, GroupStatus.JOINED)
    await settle()
    assert env.joins() == ["alpha", "beta"]

    await env.advance(JOIN_INTERVAL)
    await env.wait_group(third, GroupStatus.JOINED)
    assert env.joins() == ["alpha", "beta", "GammaHash123"]
    targets = [args[0] for args in env.gateway.called("join")]
    assert targets[0] == LinkTarget(LinkKind.PUBLIC, "alpha")
    assert targets[2] == LinkTarget(LinkKind.INVITE, "GammaHash123")


async def test_each_account_has_its_own_join_interval(env: Env) -> None:
    first = await env.add_account(session="session-a")
    second = await env.add_account(session="session-b")
    one = await env.add_group(first, "alpha")
    two = await env.add_group(second, "beta")

    await env.start(first, second)

    await env.wait_group(one, GroupStatus.JOINED)
    await env.wait_group(two, GroupStatus.JOINED)


async def test_shorter_join_interval_applies_after_settings_change(env: Env) -> None:
    account_id = await env.add_account()
    first = await env.add_group(account_id, "alpha")
    second = await env.add_group(account_id, "beta")
    await env.start(account_id)
    await env.wait_group(first, GroupStatus.JOINED)
    await env.advance(30)
    await settle()
    assert env.joins() == ["alpha"]

    await env.settings.update(join_interval_seconds=30)
    env.engine.notify_settings_changed()

    await env.wait_group(second, GroupStatus.JOINED)


async def test_group_added_later_is_joined_after_notify(env: Env) -> None:
    account_id = await env.add_account()
    await env.start(account_id)
    await settle()

    group_id = await env.add_group(account_id, "alpha")
    env.engine.notify_groups_changed()

    await env.wait_group(group_id, GroupStatus.JOINED)


async def test_joined_group_is_recorded_and_monitored(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    chat = make_chat(7, title="코인 정보방", username="alpha", member_count=1234)
    env.gateway.script_join("alpha", JoinResult(JoinOutcome.JOINED, chat=chat))
    await env.add_keyword_rule("구매")

    await env.start(account_id)
    group = await env.wait_group(group_id, GroupStatus.JOINED)

    assert group.tg_chat_id == chat.id
    assert (group.title, group.kind, group.member_count) == (
        "코인 정보방",
        GroupKind.SUPERGROUP,
        1234,
    )
    assert group.joined_at == START
    assert (group.status_detail, group.error_code, group.next_attempt_at) == (None, None, None)
    await eventually(
        lambda: [data["status"] for data in env.events("group")][-1:] == ["joined"],
        what="joined 이벤트",
    )
    await eventually(lambda: _has_log(env, "그룹에 들어갔어요."), what="가입 기록")

    # 가입하자마자 감시 대상이 된다.
    await env.gateway.client(account_id).emit_message(chat.id, "구매 문의요", ALICE)
    assert len(await env.hits()) == 1


async def test_joining_state_is_published_while_the_join_is_in_flight(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    gate = env.gateway.hold("join")

    await env.start(account_id)
    await env.wait_group(group_id, GroupStatus.JOINING)
    await eventually(
        lambda: "joining" in [data["status"] for data in env.events("group")],
        what="joining 이벤트",
    )

    gate.set()
    await env.wait_group(group_id, GroupStatus.JOINED)


async def test_broadcast_channel_gets_a_notice(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "newsroom")
    env.gateway.script_join("newsroom", joined(3, kind=GroupKind.CHANNEL))

    await env.start(account_id)
    group = await env.wait_group(group_id, GroupStatus.JOINED)

    assert group.kind == GroupKind.CHANNEL
    assert group.status_detail == "방송 채널이라 유저 채팅은 수집되지 않아요"


async def test_join_request_is_recorded(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, invite="PrivateHash12", title="예전 제목")
    env.gateway.script_join(
        "PrivateHash12", JoinResult(JoinOutcome.REQUESTED, title="비공개 모임", member_count=42)
    )

    await env.start(account_id)
    group = await env.wait_group(group_id, GroupStatus.REQUESTED)

    assert (group.title, group.member_count, group.tg_chat_id) == ("비공개 모임", 42, None)
    assert group.status_detail == "입장 요청을 보냈어요. 관리자 승인을 기다리는 중이에요"
    await eventually(
        lambda: [data["status"] for data in env.events("group")][-1:] == ["requested"],
        what="requested 이벤트",
    )


async def test_join_request_keeps_known_title_when_preview_is_empty(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(
        account_id, invite="PrivateHash12", title="알고 있던 제목", member_count=7
    )
    env.gateway.script_join("PrivateHash12", JoinResult(JoinOutcome.REQUESTED))

    await env.start(account_id)
    group = await env.wait_group(group_id, GroupStatus.REQUESTED)

    assert (group.title, group.member_count) == ("알고 있던 제목", 7)


async def test_permanent_failure_is_final(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, invite="ExpiredHash12")
    env.gateway.script_join(
        "ExpiredHash12",
        TelegramError(TgErrorCode.INVITE_EXPIRED, "초대 링크가 만료됐어요.", permanent=True),
    )

    await env.start(account_id)
    group = await env.wait_group(group_id, GroupStatus.FAILED)

    assert group.error_code == "invite_expired"
    assert group.status_detail == "초대 링크가 만료됐어요."
    assert (group.attempts, group.next_attempt_at) == (0, None)
    await env.advance(3600)
    await settle()
    assert env.joins() == ["ExpiredHash12"]
    logs = [log for log in await env.logs() if log.group_id == group_id]
    assert [(log.level, log.message) for log in logs] == [
        (LogLevel.WARNING, "그룹에 들어가지 못했어요. 초대 링크가 만료됐어요.")
    ]


async def test_retryable_failure_retries_twice_then_fails(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    env.gateway.script_join(
        "alpha", TelegramError(TgErrorCode.UNKNOWN, "텔레그램 요청이 실패했어요.")
    )

    await env.start(account_id)
    await env.wait_calls("join", 1)
    await settle()
    group = await env.group(group_id)
    assert group is not None
    assert (group.status, group.attempts) == (GroupStatus.QUEUED, 1)
    assert group.next_attempt_at == START + timedelta(minutes=5)
    assert (group.error_code, group.status_detail) == ("unknown", "텔레그램 요청이 실패했어요.")

    await env.advance(299)
    await settle()
    assert len(env.joins()) == 1  # 5분이 지나기 전에는 다시 시도하지 않는다

    await env.advance(1)
    await env.wait_calls("join", 2)
    await settle()
    group = await env.group(group_id)
    assert group is not None
    assert (group.status, group.attempts) == (GroupStatus.QUEUED, 2)
    assert group.next_attempt_at == START + timedelta(minutes=35)

    await env.advance(1800)
    group = await env.wait_group(group_id, GroupStatus.FAILED)
    assert (group.attempts, group.error_code, group.next_attempt_at) == (3, "unknown", None)
    await env.advance(7200)
    await settle()
    assert len(env.joins()) == 3


async def test_retry_that_succeeds_clears_the_error(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    env.gateway.script_join(
        "alpha", TelegramError(TgErrorCode.UNKNOWN, "텔레그램 요청이 실패했어요."), joined(1)
    )
    await env.start(account_id)
    await env.wait_calls("join", 1)

    await env.advance(300)
    group = await env.wait_group(group_id, GroupStatus.JOINED)

    assert (group.attempts, group.error_code, group.status_detail) == (0, None, None)


async def test_network_error_requeues_for_a_minute(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    env.gateway.script_join("alpha", network_error(), joined(1))

    await env.start(account_id)
    await env.wait_calls("join", 1)
    await settle()
    group = await env.group(group_id)
    assert group is not None
    assert (group.status, group.attempts) == (GroupStatus.QUEUED, 0)
    assert group.next_attempt_at == START + timedelta(seconds=60)

    await env.advance(59)
    await settle()
    assert len(env.joins()) == 1
    await env.advance(JOIN_INTERVAL)
    await env.wait_group(group_id, GroupStatus.JOINED)


async def test_hung_join_times_out_and_is_retried_later(env: Env) -> None:
    env.engine = env.new_engine(EngineTimings(tick=0.005, call_timeout=0.05))
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    env.gateway.hold("join")  # 풀어 주지 않으므로 join() 이 끝나지 않는다

    await env.start(account_id)
    await env.wait_calls("join", 1)
    await env.wait_group(group_id, GroupStatus.QUEUED)

    group = await env.group(group_id)
    assert group is not None
    assert group.next_attempt_at == START + timedelta(seconds=60)
    assert "제때 응답하지 않았어요" in (group.status_detail or "")
    assert env.engine.is_connected(account_id)  # 일꾼은 멈추지 않는다


async def test_unexpected_join_exception_is_treated_as_retryable(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    env.gateway.script_join("alpha", RuntimeError("boom"))

    await env.start(account_id)
    await env.wait_calls("join", 1)
    await settle()

    group = await env.group(group_id)
    assert group is not None
    assert (group.status, group.attempts, group.error_code) == (GroupStatus.QUEUED, 1, "unknown")
    assert env.engine.is_connected(account_id)


async def test_duplicate_chat_is_failed_instead_of_breaking_the_constraint(env: Env) -> None:
    account_id = await env.add_account()
    chat = make_chat(1, title="같은 방")
    original = await env.add_group(
        account_id, "alpha", status=GroupStatus.JOINED, tg_chat_id=chat.id, title="같은 방"
    )
    duplicate = await env.add_group(account_id, invite="SameRoomHash1")
    env.gateway.script_join("SameRoomHash1", JoinResult(JoinOutcome.JOINED, chat=chat))

    await env.start(account_id)
    group = await env.wait_group(duplicate, GroupStatus.FAILED)

    assert group.error_code == "duplicate"
    assert group.status_detail == "이 계정에 이미 등록된 그룹이에요."
    assert group.tg_chat_id is None
    kept = await env.group(original)
    assert kept is not None and kept.status == GroupStatus.JOINED
    assert env.engine.is_connected(account_id)


async def test_duplicate_join_revives_the_row_that_already_holds_the_chat(env: Env) -> None:
    account_id = await env.add_account()
    chat = make_chat(1, title="돌아온 방", member_count=77)
    gone = await env.add_group(
        account_id, "alpha", status=GroupStatus.LEFT, tg_chat_id=chat.id, title="옛 제목"
    )
    duplicate = await env.add_group(account_id, invite="SameRoomHash1")
    # 나간 그룹은 대기열에 없으므로 새 링크만 시도된다.
    env.gateway.script_join("SameRoomHash1", JoinResult(JoinOutcome.JOINED, chat=chat))

    await env.start(account_id)
    await env.wait_group(duplicate, GroupStatus.FAILED)

    revived = await env.wait_group(gone, GroupStatus.JOINED)
    assert (revived.title, revived.member_count, revived.joined_at) == ("돌아온 방", 77, START)
    await eventually(lambda: _has_log(env, "이미 이 계정에 등록된 그룹"), what="중복 기록")
    await env.gateway.client(account_id).emit_message(chat.id, "아무 말", ALICE)
    await env.collector.flush()
    revived = await env.group(gone)
    assert revived is not None and revived.messages_seen == 1


async def test_same_chat_can_be_joined_by_two_accounts(env: Env) -> None:
    first = await env.add_account(session="session-a")
    second = await env.add_account(session="session-b")
    chat = make_chat(1)
    one = await env.add_group(first, "alpha")
    two = await env.add_group(second, "alpha")
    env.gateway.script_join("alpha", JoinResult(JoinOutcome.JOINED, chat=chat))

    await env.start(first, second)

    assert (await env.wait_group(one, GroupStatus.JOINED)).tg_chat_id == chat.id
    assert (await env.wait_group(two, GroupStatus.JOINED)).tg_chat_id == chat.id


async def test_group_without_a_link_fails_without_calling_telegram(env: Env) -> None:
    account_id = await env.add_account()
    async with env.db.session() as session:
        group = Group(account_id=account_id, link_kind=LinkKind.EXISTING, status=GroupStatus.QUEUED)
        session.add(group)
        await session.commit()
        group_id = group.id

    await env.start(account_id)
    group = await env.wait_group(group_id, GroupStatus.FAILED)

    assert group.error_code == "no_link"
    assert env.joins() == []
    account = await env.account(account_id)
    assert account is not None and account.last_join_at is None  # 가입 간격을 쓰지 않는다


async def test_group_deleted_during_the_join_is_only_logged(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    gate = env.gateway.hold("join")
    await env.start(account_id)
    await env.wait_group(group_id, GroupStatus.JOINING)

    async with env.db.session() as session:
        await session.delete(await session.get(Group, group_id))
        await session.commit()
    gate.set()

    await eventually(
        lambda: _has_log(env, "가입하는 사이에 목록에서 지워진 그룹이 있어요."),
        what="지워진 그룹 기록",
    )
    assert env.engine.is_connected(account_id)


async def test_queue_worker_survives_an_unexpected_error(env: Env, monkeypatch) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    join_next = env.engine._join_next
    calls = 0

    async def fails_once(rt: Any, client: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        await join_next(rt, client)

    monkeypatch.setattr(env.engine, "_join_next", fails_once)
    await env.start(account_id)
    await eventually(lambda: calls == 1, what="첫 시도")
    await settle()
    assert env.joins() == [] and env.engine.is_connected(account_id)

    await env.advance(5)  # 오류 뒤에는 잠깐 쉬었다가 계속한다
    await env.wait_group(group_id, GroupStatus.JOINED)


async def _has_log(env: Env, fragment: str) -> bool:
    return any(fragment in message for message in await env.log_messages())


# ---------------------------------------------------------------------------
# 요청 제한 (FLOOD_WAIT)
# ---------------------------------------------------------------------------


async def test_flood_wait_blocks_joins_until_it_passes(env: Env) -> None:
    account_id = await env.add_account()
    first = await env.add_group(account_id, "alpha")
    second = await env.add_group(account_id, "beta")
    env.gateway.script_join("alpha", flood(600), joined(1))

    await env.start()
    account = await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)
    assert account.flood_until == START + timedelta(seconds=600)
    group = await env.group(first)
    assert group is not None
    assert (group.status, group.attempts) == (GroupStatus.QUEUED, 0)
    assert group.next_attempt_at == START + timedelta(seconds=600)
    await eventually(lambda: _has_log(env, "요청을 잠시 제한했어요"), what="요청 제한 기록")
    assert any(data["status"] == "flood_wait" for data in env.events("account"))
    warnings = [log for log in await env.logs() if log.level == LogLevel.WARNING]
    # 콘솔 시간대(Asia/Seoul)로 12:00 에 시작했으니 12:10 에 풀린다.
    assert [log.message for log in warnings] == [
        "텔레그램이 요청을 잠시 제한했어요. 10분 뒤(12:10)에 이어서 진행해요."
    ]

    await env.advance(599)  # 가입 간격은 한참 지났지만 제한이 풀리지 않았다
    await settle()
    assert env.joins() == ["alpha"]
    account = await env.account(account_id)
    assert account is not None and account.status == AccountStatus.FLOOD_WAIT
    assert env.engine.is_connected(account_id)  # 듣는 것은 계속한다

    await env.advance(1)
    await env.wait_group(first, GroupStatus.JOINED)
    account = await env.wait_account(account_id, AccountStatus.ACTIVE)
    assert account.flood_until is None
    await eventually(lambda: _has_log(env, "요청 제한이 풀려서"), what="제한 해제 기록")
    assert any(data["status"] == "active" for data in env.events("account"))

    await env.advance(JOIN_INTERVAL)
    await env.wait_group(second, GroupStatus.JOINED)
    assert env.joins() == ["alpha", "alpha", "beta"]


async def test_flood_wait_without_a_duration_waits_an_hour(env: Env) -> None:
    account_id = await env.add_account()
    await env.add_group(account_id, "alpha")
    env.gateway.script_join(
        "alpha", TelegramError(TgErrorCode.FLOOD_WAIT, "너무 여러 번 시도했어요."), joined(1)
    )

    await env.start()
    account = await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)

    assert account.flood_until == START + timedelta(hours=1)


async def test_flood_wait_survives_a_reconnect(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    env.gateway.script_join("alpha", flood(600), joined(1))
    await env.start()
    await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)

    await env.engine.reconnect(account_id)
    await env.wait_calls("connect", 2)
    account = await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)
    assert account.flood_until == START + timedelta(seconds=600)
    assert account.status_detail is None
    await env.advance(599)
    await settle()
    assert env.joins() == ["alpha"]

    await env.advance(1)
    await env.wait_group(group_id, GroupStatus.JOINED)
    await env.wait_account(account_id, AccountStatus.ACTIVE)


async def test_nothing_is_sent_for_the_account_while_flood_waiting(env: Env) -> None:
    account_id = await env.add_account()
    chat = make_chat(5)
    joined_id = await env.add_group(
        account_id, "omega", status=GroupStatus.JOINED, tg_chat_id=chat.id
    )
    await env.add_group(account_id, invite="PendingHash12", status=GroupStatus.REQUESTED)
    await env.add_group(account_id, "alpha")
    env.gateway.script_join("alpha", flood(7200), joined(1))
    await env.start()
    await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)

    with pytest.raises(TelegramError) as raised:
        await env.engine.list_dialogs(account_id)
    assert raised.value.code == TgErrorCode.FLOOD_WAIT
    assert raised.value.retry_after == 7200
    await env.engine.leave_group(joined_id)
    await env.advance(3600)  # 입장 요청 확인 주기가 여러 번 지났다
    await settle()

    for name in ("list_groups", "leave", "find_membership"):
        assert env.gateway.called(name) == []
    assert env.joins() == ["alpha"]


async def test_connect_flood_wait_is_honored(env: Env) -> None:
    account_id = await env.add_account()
    env.gateway.script_connect(account_id, flood(120))

    await env.start()
    account = await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)
    assert account.flood_until == START + timedelta(seconds=120)
    assert "접속을 잠시 제한" in (account.status_detail or "")
    assert await _has_log(env, "텔레그램이 접속을 잠시 제한했어요. 2분 뒤에 다시 연결해요.")

    await env.advance(119)
    await env.engine.reconnect(account_id)  # 직접 다시 연결을 눌러도 일찍 시도하지 않는다
    await settle()
    assert len(env.gateway.called("connect")) == 1
    account = await env.account(account_id)
    assert account is not None and account.status == AccountStatus.FLOOD_WAIT

    await env.advance(1)
    account = await env.wait_account(account_id, AccountStatus.ACTIVE)
    assert account.flood_until is None
    assert len(env.gateway.called("connect")) == 2


async def test_connect_flood_wait_is_remembered_across_a_restart(env: Env) -> None:
    account_id = await env.add_account()
    env.gateway.script_connect(account_id, flood(300))
    await env.start()
    await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)
    await settle()
    await env.engine.stop()

    env.engine = env.new_engine()
    await env.start()
    account = await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)
    assert account.flood_until == START + timedelta(seconds=300)
    await env.advance(299)
    await settle()
    assert len(env.gateway.called("connect")) == 1

    await env.advance(1)
    await env.wait_account(account_id, AccountStatus.ACTIVE)
    assert len(env.gateway.called("connect")) == 2


async def test_join_flood_does_not_delay_connecting_after_a_restart(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    env.gateway.script_join("alpha", flood(600), joined(1))
    await env.start()
    await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)
    await settle()
    await env.engine.stop()

    env.engine = env.new_engine()
    await env.start()
    await env.wait_calls("connect", 2)
    account = await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)
    # 듣는 것은 바로 다시 시작한다.
    await eventually(lambda: env.engine.is_connected(account_id), what="다시 연결")
    assert account.flood_until == START + timedelta(seconds=600)
    await env.advance(599)
    await settle()
    assert env.joins() == ["alpha"]

    await env.advance(1)
    await env.wait_group(group_id, GroupStatus.JOINED)


# ---------------------------------------------------------------------------
# 입장 요청 확인 · 가입 상태 맞추기
# ---------------------------------------------------------------------------


async def test_requested_group_is_joined_once_approved(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(
        account_id, invite="PendingHash12", status=GroupStatus.REQUESTED, title="비공개 모임"
    )
    await env.add_keyword_rule("구매")
    chat = make_chat(4, title="비공개 모임", member_count=58)
    await env.start(account_id)

    await env.advance(29)
    await settle()
    assert env.gateway.called("find_membership") == []  # 연결하고 30초 뒤에 처음 확인한다

    await env.advance(1)
    await env.wait_calls("find_membership", 1)
    assert env.gateway.called("find_membership")[0] == (
        LinkTarget(LinkKind.INVITE, "PendingHash12"),
        None,
    )
    await settle()
    pending = await env.group(group_id)
    assert pending is not None and pending.status == GroupStatus.REQUESTED

    env.gateway.memberships["PendingHash12"] = chat
    await env.advance(299)
    await settle()
    assert len(env.gateway.called("find_membership")) == 1  # 5분마다 본다
    await env.advance(1)
    group = await env.wait_group(group_id, GroupStatus.JOINED)

    assert (group.tg_chat_id, group.member_count, group.status_detail) == (chat.id, 58, None)
    assert group.joined_at == env.clock.now
    await eventually(lambda: _has_log(env, "입장 요청이 승인됐어요."), what="승인 기록")
    await env.gateway.client(account_id).emit_message(chat.id, "구매 문의요", ALICE)
    assert len(await env.hits()) == 1


async def test_reconcile_spaces_calls_three_seconds_apart(env: Env) -> None:
    account_id = await env.add_account()
    await env.add_group(account_id, invite="PendingHashAA", status=GroupStatus.REQUESTED)
    await env.add_group(account_id, invite="PendingHashBB", status=GroupStatus.REQUESTED)
    await env.start(account_id)

    await env.advance(30)
    await env.wait_calls("find_membership", 1)
    await env.advance(2)
    await settle()
    assert len(env.gateway.called("find_membership")) == 1

    await env.advance(1)
    await env.wait_calls("find_membership", 2)
    assert [args[0].value for args in env.gateway.called("find_membership")] == [
        "PendingHashAA",
        "PendingHashBB",
    ]


async def test_reconcile_stops_and_waits_on_flood(env: Env) -> None:
    env.engine = env.new_engine(EngineTimings(tick=0.005, reconcile_spacing=0))
    account_id = await env.add_account()
    await env.add_group(account_id, invite="PendingHashAA", status=GroupStatus.REQUESTED)
    second = await env.add_group(account_id, invite="PendingHashBB", status=GroupStatus.REQUESTED)
    env.gateway.memberships["PendingHashAA"] = flood(900)
    env.gateway.memberships["PendingHashBB"] = make_chat(2)
    await env.start(account_id)

    await env.advance(30)
    account = await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)
    assert account.flood_until == START + timedelta(seconds=30 + 900)
    await env.advance(600)  # 다음 확인 주기지만 아직 제한 중이다
    await settle()
    assert len(env.gateway.called("find_membership")) == 1

    env.gateway.memberships["PendingHashAA"] = None
    await env.advance(300)
    await env.wait_account(account_id, AccountStatus.ACTIVE)
    await env.advance(300)
    await env.wait_group(second, GroupStatus.JOINED)


async def test_request_that_can_no_longer_be_checked_is_failed(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, invite="ExpiredHash12", status=GroupStatus.REQUESTED)
    env.gateway.memberships["ExpiredHash12"] = TelegramError(
        TgErrorCode.INVITE_EXPIRED, "초대 링크가 만료됐어요.", permanent=True
    )
    await env.start(account_id)

    await env.advance(30)
    group = await env.wait_group(group_id, GroupStatus.FAILED)

    assert group.error_code == "invite_expired"
    assert group.status_detail == (
        "입장 요청이 승인됐는지 더는 확인할 수 없어요. 초대 링크가 만료됐어요."
    )
    await env.advance(600)
    await settle()
    assert len(env.gateway.called("find_membership")) == 1


async def test_transient_check_error_does_not_block_other_requests(env: Env) -> None:
    env.engine = env.new_engine(EngineTimings(tick=0.005, reconcile_spacing=0))
    account_id = await env.add_account()
    first = await env.add_group(account_id, invite="PendingHashAA", status=GroupStatus.REQUESTED)
    second = await env.add_group(account_id, invite="PendingHashBB", status=GroupStatus.REQUESTED)
    env.gateway.memberships["PendingHashAA"] = TelegramError(
        TgErrorCode.UNKNOWN, "텔레그램 요청이 실패했어요."
    )
    env.gateway.memberships["PendingHashBB"] = make_chat(2)
    await env.start(account_id)

    await env.advance(30)
    await env.wait_group(second, GroupStatus.JOINED)

    still = await env.group(first)
    assert still is not None and still.status == GroupStatus.REQUESTED


async def test_reconcile_survives_an_unexpected_error(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, invite="PendingHash12", status=GroupStatus.REQUESTED)
    env.gateway.memberships["PendingHash12"] = RuntimeError("boom")
    await env.start(account_id)

    await env.advance(30)
    await env.wait_calls("find_membership", 1)
    await settle()
    group = await env.group(group_id)
    assert group is not None and group.status == GroupStatus.REQUESTED
    assert env.engine.is_connected(account_id)

    env.gateway.memberships["PendingHash12"] = make_chat(1)
    await env.advance(300)
    await env.wait_group(group_id, GroupStatus.JOINED)


async def test_approved_request_for_an_already_listed_chat_is_a_duplicate(env: Env) -> None:
    account_id = await env.add_account()
    chat = make_chat(1)
    await env.add_group(account_id, "alpha", status=GroupStatus.JOINED, tg_chat_id=chat.id)
    requested = await env.add_group(
        account_id, invite="SameRoomHash1", status=GroupStatus.REQUESTED
    )
    env.gateway.memberships["SameRoomHash1"] = chat
    await env.start(account_id)

    await env.advance(30)
    group = await env.wait_group(requested, GroupStatus.FAILED)

    assert group.error_code == "duplicate"


async def test_membership_refresh_updates_titles_and_marks_left_groups(env: Env) -> None:
    account_id = await env.add_account()
    staying, gone = make_chat(1), make_chat(2)
    staying_id = await env.add_group(
        account_id,
        "alpha",
        status=GroupStatus.JOINED,
        tg_chat_id=staying.id,
        title="옛 제목",
        member_count=10,
    )
    gone_id = await env.add_group(
        account_id, "beta", status=GroupStatus.JOINED, tg_chat_id=gone.id, title="사라질 방"
    )
    env.gateway.dialogs[account_id] = [make_chat(1, title="새 제목", member_count=250)]
    await env.add_keyword_rule("구매")
    await env.start(account_id)

    await env.advance(6 * 3600 - 1)
    await settle()
    assert env.gateway.called("list_groups") == []

    await env.advance(300)  # 여섯 시간이 지난 뒤의 첫 확인 주기에 맞춰 본다
    left = await env.wait_group(gone_id, GroupStatus.LEFT)
    assert left.status_detail == "그룹에서 나왔거나 내보내졌어요"
    kept = await env.group(staying_id)
    assert kept is not None
    assert (kept.status, kept.title, kept.member_count) == (GroupStatus.JOINED, "새 제목", 250)
    await eventually(lambda: _has_log(env, "그룹에서 나왔거나 내보내졌어요."), what="나감 기록")
    assert len(env.gateway.called("list_groups")) == 1

    # 나간 방은 더는 감시하지 않는다.
    client = env.gateway.client(account_id)
    await client.emit_message(gone.id, "구매 문의요", ALICE)
    assert await env.hits() == []
    await client.emit_message(staying.id, "구매 문의요", ALICE)
    assert len(await env.hits()) == 1

    await env.advance(3600)  # 여섯 시간에 한 번만 한다
    await settle()
    assert len(env.gateway.called("list_groups")) == 1


# ---------------------------------------------------------------------------
# 계정 오류와 다시 연결
# ---------------------------------------------------------------------------


async def test_invalid_session_requires_reauth_and_is_not_retried(env: Env) -> None:
    account_id = await env.add_account()
    env.gateway.script_connect(account_id, session_invalid())

    await env.start()
    account = await env.wait_account(account_id, AccountStatus.REAUTH_REQUIRED)

    assert account.status_detail == "세션이 만료됐어요. 다시 로그인해 주세요."
    await env.advance(24 * 3600)
    await settle()
    assert len(env.gateway.called("connect")) == 1
    assert not env.engine.is_connected(account_id)
    assert not runner_alive(account_id)
    errors = [log for log in await env.logs() if log.level == LogLevel.ERROR]
    assert [(log.account_id, log.message) for log in errors] == [
        (account_id, "세션이 만료됐어요. 다시 로그인해 주세요.")
    ]


async def test_session_revoked_while_connected_requires_reauth(env: Env) -> None:
    account_id = await env.add_account()
    await env.start(account_id)

    env.gateway.client(account_id).drop(session_invalid())

    await env.wait_account(account_id, AccountStatus.REAUTH_REQUIRED)
    await env.advance(3600)
    await settle()
    assert len(env.gateway.called("connect")) == 1
    assert not env.engine.is_connected(account_id)


async def test_banned_account_stops(env: Env) -> None:
    account_id = await env.add_account()
    env.gateway.script_connect(
        account_id,
        TelegramError(TgErrorCode.BANNED, "텔레그램이 이 계정을 정지했어요.", permanent=True),
    )

    await env.start()
    account = await env.wait_account(account_id, AccountStatus.BANNED)

    assert account.status_detail == "텔레그램이 이 계정을 정지했어요."
    await env.advance(3600)
    await settle()
    assert len(env.gateway.called("connect")) == 1


async def test_session_error_during_join_requeues_the_group(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    env.gateway.script_join("alpha", session_invalid())

    await env.start()
    await env.wait_account(account_id, AccountStatus.REAUTH_REQUIRED)

    group = await env.group(group_id)
    assert group is not None
    assert (group.status, group.attempts, group.error_code) == (GroupStatus.QUEUED, 0, None)
    assert not env.gateway.client(account_id).connected
    assert not env.engine.is_connected(account_id)


async def test_api_credentials_error_retries_every_minute_and_on_settings_change(
    env: Env,
) -> None:
    account_id = await env.add_account()
    missing = TelegramError(
        TgErrorCode.API_CREDENTIALS, "텔레그램 API 키가 아직 없어요.", permanent=True
    )
    env.gateway.script_connect(account_id, missing, missing)

    await env.start()
    account = await env.wait_account(account_id, AccountStatus.ERROR)
    assert account.status_detail == "텔레그램 API 키가 아직 없어요."
    await env.advance(59)
    await settle()
    assert len(env.gateway.called("connect")) == 1

    env.engine.notify_settings_changed()  # 설정을 바꾸면 바로 다시 시도한다
    await env.wait_calls("connect", 2)
    await env.wait_account(account_id, AccountStatus.ERROR)
    await env.advance(59)
    await settle()
    assert len(env.gateway.called("connect")) == 2

    await env.advance(1)
    await env.wait_account(account_id, AccountStatus.ACTIVE)
    messages = await env.log_messages()
    assert messages.count("텔레그램 API 키가 아직 없어요.") == 1  # 같은 실패는 한 번만 적는다


async def test_network_errors_back_off(env: Env) -> None:
    account_id = await env.add_account()
    env.gateway.script_connect(account_id, network_error(), network_error(), network_error())

    await env.start()
    account = await env.wait_account(account_id, AccountStatus.ERROR)
    assert account.status_detail == "텔레그램에 연결하지 못했어요."

    for attempt, delay in enumerate((5, 15, 30), start=1):
        await env.wait_calls("connect", attempt)
        await env.advance(delay - 1)
        await settle()
        assert len(env.gateway.called("connect")) == attempt
        await env.advance(1)
    await env.wait_account(account_id, AccountStatus.ACTIVE)
    assert len(env.gateway.called("connect")) == 4


async def test_hung_connect_times_out_and_is_retried(env: Env) -> None:
    env.engine = env.new_engine(EngineTimings(tick=0.005, call_timeout=0.05))
    account_id = await env.add_account()
    env.gateway.hold("connect")  # 풀어 주지 않으므로 connect() 가 끝나지 않는다

    await env.start()
    account = await env.wait_account(account_id, AccountStatus.ERROR)
    assert "제때 응답하지 않았어요" in (account.status_detail or "")

    del env.gateway.gates["connect"]
    await env.advance(5)
    await env.wait_account(account_id, AccountStatus.ACTIVE)
    assert len(env.gateway.called("connect")) == 2


async def test_disconnect_is_followed_by_a_reconnect(env: Env) -> None:
    account_id = await env.add_account()
    chat = make_chat(1)
    await env.add_group(account_id, "alpha", status=GroupStatus.JOINED, tg_chat_id=chat.id)
    await env.add_keyword_rule("구매")
    await env.start(account_id)
    first_client = env.gateway.client(account_id)

    first_client.drop()

    account = await env.wait_account(account_id, AccountStatus.ERROR)
    assert account.status_detail == "텔레그램과 연결이 끊겼어요. 곧 다시 연결해요."
    assert not env.engine.is_connected(account_id)
    await env.advance(4)
    await settle()
    assert len(env.gateway.clients) == 1

    await env.advance(1)
    await env.wait_calls("connect", 2)
    await env.wait_connected(account_id)
    second_client = env.gateway.client(account_id)
    assert second_client is not first_client
    assert first_client.handler is None
    await second_client.emit_message(chat.id, "구매 문의요", ALICE)
    assert len(await env.hits()) == 1


async def test_waits_follow_the_real_clock_too(env: Env) -> None:
    timings = EngineTimings(tick=0.01, reconnect_backoff=(0.05,), stable_after=0.0)
    env.engine = env.new_engine(timings, clock=utcnow)
    account_id = await env.add_account()
    await env.start(account_id)

    env.gateway.client(account_id).drop()

    await env.wait_calls("connect", 2)
    await env.wait_connected(account_id)
    account = await env.account(account_id)
    assert account is not None and account.last_connected_at is not None
    assert abs(utcnow() - account.last_connected_at) < timedelta(seconds=5)


async def test_backoff_starts_over_after_a_stable_connection(env: Env) -> None:
    account_id = await env.add_account()
    await env.start(account_id)

    env.gateway.client(account_id).drop()  # 금방 끊겼다: 5초 뒤에 다시
    await env.wait_account(account_id, AccountStatus.ERROR)
    await env.advance(5)
    await env.wait_account(account_id, AccountStatus.ACTIVE)

    env.gateway.client(account_id).drop()  # 또 금방 끊겼다: 15초 뒤에 다시
    await env.wait_account(account_id, AccountStatus.ERROR)
    await env.advance(14)
    await settle()
    assert len(env.gateway.called("connect")) == 2
    await env.advance(1)
    await env.wait_account(account_id, AccountStatus.ACTIVE)

    await env.advance(60)  # 1분 넘게 붙어 있었으면 처음부터 다시 센다
    env.gateway.client(account_id).drop()
    await env.wait_account(account_id, AccountStatus.ERROR)
    await env.advance(5)
    await env.wait_account(account_id, AccountStatus.ACTIVE)
    assert len(env.gateway.called("connect")) == 4


# ---------------------------------------------------------------------------
# 계정 제어
# ---------------------------------------------------------------------------


async def test_set_account_enabled_off_and_on(env: Env) -> None:
    account_id = await env.add_account()
    await env.start(account_id)
    client = env.gateway.client(account_id)

    await env.engine.set_account_enabled(account_id, False)

    account = await env.account(account_id)
    assert account is not None
    assert (account.enabled, account.status) == (False, AccountStatus.OFFLINE)
    assert not client.connected and not env.engine.is_connected(account_id)
    assert env.events("account")[-1]["status"] == "offline"

    await env.engine.set_account_enabled(account_id, True)

    account = await env.wait_connected(account_id)
    assert account.enabled
    assert len(env.gateway.clients) == 2
    messages = await env.log_messages()
    assert "계정을 껐어요." in messages and "계정을 켰어요." in messages


async def test_enabling_an_account_without_a_session_asks_for_login(env: Env) -> None:
    account_id = await env.add_account(session=None, enabled=False)
    await env.start()

    await env.engine.set_account_enabled(account_id, True)

    account = await env.account(account_id)
    assert account is not None
    assert (account.enabled, account.status) == (True, AccountStatus.REAUTH_REQUIRED)
    assert env.gateway.clients == []


async def test_disabling_requeues_a_join_in_flight(env: Env) -> None:
    account_id = await env.add_account()
    group_id = await env.add_group(account_id, "alpha")
    env.gateway.hold("join")
    await env.start(account_id)
    await env.wait_group(group_id, GroupStatus.JOINING)

    await env.engine.set_account_enabled(account_id, False)

    group = await env.group(group_id)
    assert group is not None and group.status == GroupStatus.QUEUED
    account = await env.account(account_id)
    assert account is not None and account.last_join_at == START  # 시도한 시각은 남는다


async def test_reconnect_restarts_the_connection(env: Env) -> None:
    account_id = await env.add_account()
    env.gateway.script_connect(account_id, session_invalid())
    await env.start()
    await env.wait_account(account_id, AccountStatus.REAUTH_REQUIRED)

    await env.engine.reconnect(account_id)

    await env.wait_connected(account_id)
    assert len(env.gateway.clients) == 2


async def test_reconnect_leaves_a_disabled_account_off(env: Env) -> None:
    account_id = await env.add_account(enabled=False)
    await env.start()

    await env.engine.reconnect(account_id)
    await settle()

    account = await env.account(account_id)
    assert account is not None and account.status == AccountStatus.OFFLINE
    assert env.gateway.clients == []


async def test_controls_ignore_a_missing_account(env: Env) -> None:
    await env.start()

    await env.engine.set_account_enabled(404, True)
    await env.engine.reconnect(404)
    await env.engine.remove_account(404, log_out=True)

    assert env.gateway.clients == []
    assert await env.logs() == []


async def test_remove_account_deletes_rows_without_logging_out(env: Env, monkeypatch) -> None:
    account_id = await env.add_account(label="영업 1호")
    keeper = await env.add_account(session="session-b")
    await env.add_group(account_id, "alpha", status=GroupStatus.JOINED, tg_chat_id=make_chat(1).id)
    await env.add_group(keeper, "beta", status=GroupStatus.JOINED, tg_chat_id=make_chat(2).id)
    await env.start(account_id, keeper)
    client = env.gateway.client(account_id)
    invalidated: list[None] = []
    monkeypatch.setattr(env.collector, "invalidate", lambda: invalidated.append(None))

    await env.engine.remove_account(account_id)

    assert await env.account(account_id) is None
    async with env.db.session() as session:
        remaining = (await session.scalars(select(Group.account_id))).all()
    assert remaining == [keeper]
    assert not client.connected and not client.logged_out
    assert env.gateway.called("log_out") == []
    assert not env.engine.is_connected(account_id) and env.engine.is_connected(keeper)
    assert invalidated == [None]
    assert "'영업 1호' 계정을 지웠어요." in await env.log_messages()


async def test_remove_account_logs_out_through_the_live_connection(env: Env) -> None:
    account_id = await env.add_account()
    await env.start(account_id)
    client = env.gateway.client(account_id)

    await env.engine.remove_account(account_id, log_out=True)

    assert await env.account(account_id) is None
    assert client.logged_out and not client.connected
    assert len(env.gateway.clients) == 1  # 임시 연결을 만들지 않았다
    # 로그아웃하기 전에 연결을 끊지 않는다.
    names = [name for _owner, name, _args in env.gateway.calls]
    assert names.index("log_out") < names.index("disconnect")
    await settle()
    assert await env.logs() != [] and not await _has_log(env, "세션이 만료")


async def test_remove_account_logs_out_with_a_temporary_connection(env: Env) -> None:
    account_id = await env.add_account(session="sleeping-session", enabled=False)
    await env.start()

    await env.engine.remove_account(account_id, log_out=True)

    assert await env.account(account_id) is None
    assert len(env.gateway.clients) == 1
    client = env.gateway.clients[0]
    assert client.session == "sleeping-session"
    assert client.logged_out and not client.connected
    assert [name for _owner, name, _args in env.gateway.calls][:2] == ["connect", "log_out"]


async def test_remove_account_survives_a_failed_log_out(env: Env) -> None:
    account_id = await env.add_account(label="영업 1호")
    await env.start(account_id)
    env.gateway.log_out_error = network_error()

    await env.engine.remove_account(account_id, log_out=True)

    assert await env.account(account_id) is None
    assert not env.gateway.client(account_id).connected
    assert await _has_log(env, "'영업 1호' 계정을 텔레그램에서 로그아웃하지 못했어요.")


async def test_remove_account_skips_log_out_for_a_dead_session(env: Env) -> None:
    account_id = await env.add_account(enabled=False)
    env.gateway.script_connect(account_id, session_invalid())
    await env.start()

    await env.engine.remove_account(account_id, log_out=True)

    assert await env.account(account_id) is None
    assert env.gateway.called("log_out") == []
    assert not await _has_log(env, "로그아웃하지 못했어요")


async def test_remove_account_does_not_log_out_while_flood_waiting(env: Env) -> None:
    account_id = await env.add_account()
    await env.add_group(account_id, "alpha")
    env.gateway.script_join("alpha", flood(600))
    await env.start()
    await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)

    await env.engine.remove_account(account_id, log_out=True)

    assert await env.account(account_id) is None
    assert env.gateway.called("log_out") == []
    assert not env.gateway.client(account_id).connected
    assert await _has_log(env, "요청 제한 중이라 로그아웃 요청을 보내지 않았어요.")


# ---------------------------------------------------------------------------
# 로그인 · 세션 불러오기
# ---------------------------------------------------------------------------

NEWCOMER = TgUser(
    id=5550001, username="newbie", first_name="새", last_name="계정", phone="+821012345678"
)


async def test_login_creates_and_connects_an_account(env: Env, monkeypatch) -> None:
    await env.start()
    env.gateway.login_script.append(LoginResult("done", session="fresh-session", user=NEWCOMER))
    invalidated: list[None] = []
    monkeypatch.setattr(env.collector, "invalidate", lambda: invalidated.append(None))

    pending = await env.engine.start_login("+821012345678")
    result, account = await env.engine.submit_code(pending.login_id, "12345")

    assert result.status == "done" and account is not None
    assert env.gateway.called("submit_code") == [(pending.login_id, "12345")]
    assert (account.tg_user_id, account.username, account.phone) == (
        5550001,
        "newbie",
        "+821012345678",
    )
    assert account.enabled and account.label is None
    assert account.session_enc is not None and account.session_enc != "fresh-session"
    assert env.secrets.decrypt(account.session_enc) == "fresh-session"
    assert invalidated == [None]
    await env.wait_account(account.id, AccountStatus.ACTIVE)
    assert env.gateway.client(account.id).session == "fresh-session"
    assert "계정을 추가했어요." in await env.log_messages()
    assert account.id in {data["id"] for data in env.events("account")}


async def test_two_step_login_saves_the_account_after_the_password(env: Env) -> None:
    await env.start()
    env.gateway.login_script.extend(
        [
            LoginResult("password_required", password_hint="고양이 이름"),
            LoginResult("done", session="fresh-session", user=NEWCOMER),
        ]
    )

    pending = await env.engine.start_login("+821012345678")
    result, account = await env.engine.submit_code(pending.login_id, "12345")
    assert (result.status, result.password_hint, account) == (
        "password_required",
        "고양이 이름",
        None,
    )
    async with env.db.session() as session:
        assert await session.scalar(select(func.count()).select_from(Account)) == 0

    result, account = await env.engine.submit_password(pending.login_id, "hunter2")
    assert result.status == "done" and account is not None
    assert env.gateway.called("submit_password") == [(pending.login_id, "hunter2")]
    await env.wait_account(account.id, AccountStatus.ACTIVE)


async def test_second_login_for_the_same_user_replaces_the_session(env: Env) -> None:
    await env.start()
    env.gateway.login_script.append(LoginResult("done", session="first-session", user=NEWCOMER))
    _, account = await env.engine.submit_code("login-1", "11111")
    assert account is not None
    await env.wait_account(account.id, AccountStatus.ACTIVE)
    first_client = env.gateway.client(account.id)
    await env.engine.set_account_enabled(account.id, False)

    renamed = TgUser(id=NEWCOMER.id, username="renamed", first_name="새")
    env.gateway.login_script.append(LoginResult("done", session="second-session", user=renamed))
    _, again = await env.engine.submit_code("login-2", "22222")

    assert again is not None and again.id == account.id
    async with env.db.session() as session:
        assert await session.scalar(select(func.count()).select_from(Account)) == 1
    stored = await env.wait_account(account.id, AccountStatus.ACTIVE)
    assert stored.enabled and stored.username == "renamed"
    assert stored.phone == "+821012345678"  # 이번 결과에 번호가 없으면 알고 있던 값을 둔다
    assert stored.session_enc is not None
    assert env.secrets.decrypt(stored.session_enc) == "second-session"
    second_client = env.gateway.client(account.id)
    assert second_client is not first_client and second_client.session == "second-session"
    assert not first_client.connected
    assert "다시 로그인해서 계정의 세션을 바꿨어요." in await env.log_messages()


async def test_login_replaces_the_session_of_a_running_account(env: Env) -> None:
    account_id = await env.add_account(session="old-session", tg_user_id=NEWCOMER.id)
    env.gateway.users[account_id] = NEWCOMER
    await env.start(account_id)
    old_client = env.gateway.client(account_id)

    env.gateway.login_script.append(LoginResult("done", session="new-session", user=NEWCOMER))
    _, account = await env.engine.submit_code("login-1", "11111")

    assert account is not None and account.id == account_id
    await env.wait_calls("connect", 2)
    await env.wait_account(account_id, AccountStatus.ACTIVE)
    assert not old_client.connected
    assert env.gateway.client(account_id).session == "new-session"


async def test_import_session_saves_the_label(env: Env) -> None:
    await env.start()
    env.gateway.login_script.append(LoginResult("done", session="imported", user=NEWCOMER))

    account = await env.engine.import_session("1BVtsOKABu…", "  영업 3호  ")

    assert env.gateway.called("import_session") == [("1BVtsOKABu…",)]
    assert account.label == "영업 3호"
    assert account.session_enc is not None
    assert env.secrets.decrypt(account.session_enc) == "imported"
    await env.wait_account(account.id, AccountStatus.ACTIVE)


async def test_login_errors_are_passed_through(env: Env) -> None:
    await env.start()
    env.gateway.start_login_error = TelegramError(
        TgErrorCode.PHONE_INVALID, "전화번호가 올바르지 않아요."
    )
    env.gateway.login_script.extend(
        [
            TelegramError(TgErrorCode.CODE_INVALID, "인증 코드가 틀렸어요."),
            TelegramError(TgErrorCode.SESSION_FORMAT, "세션을 읽을 수 없어요."),
        ]
    )

    for call, code in (
        (env.engine.start_login("12345"), TgErrorCode.PHONE_INVALID),
        (env.engine.submit_code("login-1", "00000"), TgErrorCode.CODE_INVALID),
        (env.engine.import_session(b"garbage"), TgErrorCode.SESSION_FORMAT),
    ):
        with pytest.raises(TelegramError) as raised:
            await call
        assert raised.value.code == code
    async with env.db.session() as session:
        assert await session.scalar(select(func.count()).select_from(Account)) == 0


async def test_incomplete_login_result_is_rejected(env: Env) -> None:
    await env.start()
    env.gateway.login_script.append(LoginResult("done", session=None, user=NEWCOMER))

    with pytest.raises(TelegramError) as raised:
        await env.engine.submit_code("login-1", "11111")

    assert raised.value.code == TgErrorCode.UNKNOWN


async def test_cancel_login_is_delegated(env: Env) -> None:
    await env.engine.cancel_login("login-9")

    assert env.gateway.called("cancel_login") == [("login-9",)]


async def test_login_before_the_engine_starts_only_saves_the_account(env: Env) -> None:
    env.gateway.login_script.append(LoginResult("done", session="fresh-session", user=NEWCOMER))

    _, account = await env.engine.submit_code("login-1", "11111")
    await settle()

    assert account is not None and account.status == AccountStatus.OFFLINE
    assert env.gateway.clients == []

    await env.start(account.id)  # 켜면 그때 연결한다
    assert env.gateway.client(account.id).session == "fresh-session"


# ---------------------------------------------------------------------------
# 이미 들어가 있는 그룹 · 나가기
# ---------------------------------------------------------------------------


async def test_list_dialogs_needs_a_connected_account(env: Env) -> None:
    account_id = await env.add_account()
    offline = await env.add_account(session="session-b", enabled=False)
    chats = [make_chat(1), make_chat(2, kind=GroupKind.CHANNEL)]
    env.gateway.dialogs[account_id] = chats
    await env.start(account_id)

    assert await env.engine.list_dialogs(account_id) == chats

    for missing in (offline, 404):
        with pytest.raises(TelegramError) as raised:
            await env.engine.list_dialogs(missing)
        assert raised.value.code == TgErrorCode.NETWORK
        assert raised.value.message == (
            "계정이 연결돼 있지 않아요. 연결된 뒤에 다시 시도해 주세요."
        )


async def test_list_dialogs_flood_puts_the_account_in_flood_wait(env: Env) -> None:
    account_id = await env.add_account()
    env.gateway.dialogs[account_id] = flood(300)
    await env.start(account_id)

    with pytest.raises(TelegramError) as raised:
        await env.engine.list_dialogs(account_id)

    assert raised.value.code == TgErrorCode.FLOOD_WAIT
    account = await env.wait_account(account_id, AccountStatus.FLOOD_WAIT)
    assert account.flood_until == START + timedelta(seconds=300)


async def test_leave_group_is_best_effort(env: Env) -> None:
    account_id = await env.add_account()
    offline = await env.add_account(session="session-b", enabled=False)
    chat = make_chat(1)
    joined_id = await env.add_group(
        account_id, "alpha", status=GroupStatus.JOINED, tg_chat_id=chat.id
    )
    queued_id = await env.add_group(account_id, "beta", next_attempt_at=START + timedelta(days=1))
    offline_id = await env.add_group(
        offline, "gamma", status=GroupStatus.JOINED, tg_chat_id=make_chat(3).id
    )
    await env.start(account_id)

    await env.engine.leave_group(joined_id)
    assert env.gateway.called("leave") == [(chat.id,)]
    still = await env.group(joined_id)
    assert still is not None and still.status == GroupStatus.JOINED  # 행은 건드리지 않는다

    await env.engine.leave_group(queued_id)  # 아직 방을 모른다
    await env.engine.leave_group(offline_id)  # 계정이 연결돼 있지 않다
    await env.engine.leave_group(404)  # 없는 그룹
    assert len(env.gateway.called("leave")) == 1
    assert await _has_log(env, "텔레그램에서 그룹을 나가지 못했어요. 계정이 연결돼 있지 않아요.")

    env.gateway.leave_error = RuntimeError("boom")
    await env.engine.leave_group(joined_id)  # 실패해도 예외를 올리지 않는다
    env.gateway.leave_error = network_error()
    await env.engine.leave_group(joined_id)
    assert len(env.gateway.called("leave")) == 3
