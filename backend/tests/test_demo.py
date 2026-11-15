"""데모 모드 테스트: 가짜 게이트웨이, 처음 채우는 데이터, 그리고 실제 엔진을 얹은 앱 전체."""

from __future__ import annotations

import asyncio
import itertools
import random
import re
import time
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app import demo_seed
from app.config import Config
from app.context import AppContext, build_context
from app.demo_seed import (
    EXPIRED_SESSION,
    FLOOD_WAIT_MINUTES,
    HELD_REQUESTS,
    HISTORY_DAYS,
    RECENT_ACTIVITY_LEADS,
    RECENT_KEYWORD_LEADS,
    TOTAL_LEADS,
    ensure_demo_data,
)
from app.links import LinkTarget
from app.main import create_app
from app.matching import match_keywords
from app.models import (
    Account,
    AccountStatus,
    ActivityBucket,
    Admin,
    BlocklistEntry,
    EventLog,
    Group,
    GroupKind,
    GroupStatus,
    Hit,
    Lead,
    LeadStatus,
    LinkKind,
    LogLevel,
    Rule,
    RuleKind,
)
from app.telegram import demo_gateway, engine
from app.telegram.demo_gateway import (
    CHATTER,
    DEMO_CODE,
    DEMO_PASSWORD,
    INTENT_RATIO,
    POOL_SIZE,
    SESSION_PREFIX,
    DemoClient,
    DemoGateway,
    IntentKind,
    JoinPlanKind,
    demo_chat_cast,
    demo_join_plan,
    demo_population,
    intent_message,
    random_message,
)
from app.telegram.gateway import (
    IncomingMessage,
    JoinOutcome,
    TelegramError,
    TgChat,
    TgErrorCode,
    TgUser,
)

from .stubs import NullGateway

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 11, 15, 5, 30, tzinfo=UTC)  # 서울 기준 14:30
ACCOUNT_NAMES = ["지우", "민호", "서연", "태양", "하늘", "도윤", "예린", "준서", "수아", "건우"]
JOINED_PER_ACCOUNT = [20, 20, 19, 20, 18, 20, 20, 17, 20, 13]
TOP_GROUPS = [
    "스마트스토어 셀러 모임",
    "해외구매대행 정보방",
    "쇼핑몰 창업 스터디",
    "퍼포먼스 마케터 모임",
    "도매 사입 정보 공유",
]
RULE_KEYWORDS = {
    "견적 문의": ["견적", "외주"],
    "업체 찾는 사람": ["업체 추천", "업체 소개", "추천 부탁"],
    "광고 대행": ["광고 대행", "마케팅 대행"],
}
RULE_LEADS = {"견적 문의": 1900, "업체 찾는 사람": 1200, "광고 대행": 700, "활발한 유저": 1000}
INTENT_RULES = {
    IntentKind.QUOTE: "견적 문의",
    IntentKind.VENDOR: "업체 찾는 사람",
    IntentKind.ADS: "광고 대행",
}
ALL_KEYWORDS = [keyword for keywords in RULE_KEYWORDS.values() for keyword in keywords]
YERIN, GUNWOO = 7, 10  # 처음 채운 DB 에서의 계정 id


class TickClock:
    """테스트가 직접 돌리는 시계."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def demo_config(data_dir: Path, *, engine_enabled: bool = False) -> Config:
    return Config(
        _env_file=None,
        data_dir=data_dir,
        secret_key="demo-test-secret",
        demo=True,
        engine_enabled=engine_enabled,
        log_level="WARNING",
    )


def fast_gateway(clock: Callable[[], datetime] | None = None, **overrides: object) -> DemoGateway:
    options: dict[str, object] = {
        "pace": (0.005, 0.015),
        "join_delay": (0.0, 0.0),
        "approval_delay": (60.0, 120.0),
        "seed": 11,
    }
    options.update(overrides)
    if clock is not None:
        options["clock"] = clock
    return DemoGateway(**options)  # type: ignore[arg-type]


def chat(number: int, *, kind: GroupKind = GroupKind.SUPERGROUP, members: int = 500) -> TgChat:
    return TgChat(-1_003_000_000_000 - number, f"테스트 방 {number}", None, kind, members)


def link_with(kind: JoinPlanKind, link_kind: LinkKind = LinkKind.INVITE) -> LinkTarget:
    """데모 게이트웨이가 kind 로 답하는 링크 하나."""
    for number in itertools.count():
        value = f"DemoInvite{number:06d}" if link_kind == LinkKind.INVITE else f"demo_room_{number}"
        target = LinkTarget(link_kind, value)
        if demo_join_plan(target).kind == kind:
            return target
    raise AssertionError("닿지 않는 줄")


async def wait_until(
    check: Callable[[], Awaitable[bool]], *, within: float = 8.0, what: str = "조건"
) -> None:
    deadline = time.monotonic() + within
    while not await check():
        if time.monotonic() > deadline:
            raise AssertionError(f"{within}초 안에 {what}이(가) 이뤄지지 않았어요")
        await asyncio.sleep(0.05)


def other_tasks() -> set[asyncio.Task[object]]:
    return {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}


async def expect_error(awaitable: Awaitable[object], code: TgErrorCode) -> TelegramError:
    with pytest.raises(TelegramError) as caught:
        await awaitable
    assert caught.value.code == code, caught.value.message
    assert re.search("[가-힣]", caught.value.message), "오류 문장은 한국어여야 해요"
    return caught.value


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------


@pytest.fixture
def clock() -> TickClock:
    return TickClock()


@pytest_asyncio.fixture
async def gateway(clock: TickClock) -> AsyncIterator[DemoGateway]:
    world = fast_gateway(clock)
    yield world
    await world.close()


@pytest_asyncio.fixture
async def client(gateway: DemoGateway) -> DemoClient:
    """접속해 있는 계정 1번의 연결."""
    connection = gateway.create_client(1, f"{SESSION_PREFIX}1")
    assert isinstance(connection, DemoClient)
    await connection.connect()
    return connection


@dataclass
class Snapshot:
    """처음 채운 DB 의 내용 전부."""

    seconds: float
    admins: int
    accounts: list[Account]
    groups: list[Group]
    rules: list[Rule]
    leads: list[Lead]
    hits: list[Hit]
    buckets: list[ActivityBucket]
    logs: list[EventLog]
    blocklist: list[BlocklistEntry]
    sessions: list[str | None]

    def joined(self) -> list[Group]:
        return [group for group in self.groups if group.status == GroupStatus.JOINED]

    def hits_by_lead(self) -> dict[int, list[Hit]]:
        grouped: dict[int, list[Hit]] = defaultdict(list)
        for hit in self.hits:
            grouped[hit.lead_id].append(hit)
        return grouped


async def load_snapshot(ctx: AppContext, seconds: float = 0.0) -> Snapshot:
    async with ctx.db.session() as session:

        async def rows(model: type, order: object) -> list:
            return list((await session.scalars(select(model).order_by(order))).all())

        accounts = await rows(Account, Account.id)
        return Snapshot(
            seconds=seconds,
            admins=await session.scalar(select(func.count()).select_from(Admin)) or 0,
            accounts=accounts,
            groups=await rows(Group, Group.id),
            rules=await rows(Rule, Rule.id),
            leads=await rows(Lead, Lead.id),
            hits=await rows(Hit, Hit.id),
            buckets=await rows(ActivityBucket, ActivityBucket.hour),
            logs=await rows(EventLog, EventLog.id),
            blocklist=await rows(BlocklistEntry, BlocklistEntry.id),
            sessions=[
                ctx.secrets.decrypt(account.session_enc) if account.session_enc else None
                for account in accounts
            ],
        )


async def seed_into(
    data_dir: Path, now: datetime, world: DemoGateway | None = None
) -> tuple[AppContext, float]:
    ctx = build_context(demo_config(data_dir), world or fast_gateway())
    await ctx.db.create_all()
    started = time.perf_counter()
    await ensure_demo_data(ctx, now=now)
    return ctx, time.perf_counter() - started


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def snap(tmp_path_factory: pytest.TempPathFactory) -> Snapshot:
    """NOW 를 기준으로 한 번 채운 DB. 읽기만 하는 테스트들이 같이 쓴다."""
    ctx, seconds = await seed_into(tmp_path_factory.mktemp("demo-seed"), NOW)
    try:
        return await load_snapshot(ctx, seconds)
    finally:
        await ctx.db.dispose()


@pytest_asyncio.fixture
async def seeded(tmp_path: Path, clock: TickClock) -> AsyncIterator[tuple[AppContext, DemoGateway]]:
    """테스트마다 새로 채운 DB 와, 그 DB 를 올린 게이트웨이(엔진은 돌지 않는다)."""
    world = fast_gateway(clock)
    ctx, _ = await seed_into(tmp_path, NOW, world)
    yield ctx, world
    await world.close()
    await ctx.db.dispose()


async def table_counts(ctx: AppContext) -> dict[str, int]:
    async with ctx.db.session() as session:
        return {
            model.__name__: await session.scalar(select(func.count()).select_from(model)) or 0
            for model in (Account, Group, Rule, Lead, Hit, ActivityBucket, EventLog, BlocklistEntry)
        }


# ---------------------------------------------------------------------------
# 사람들과 말뭉치
# ---------------------------------------------------------------------------


def test_population_is_the_same_every_time_and_unique() -> None:
    pool = demo_population(POOL_SIZE)
    assert len(pool) == POOL_SIZE == 400
    assert demo_population(POOL_SIZE + 700)[:POOL_SIZE] == pool  # 더 많이 만들어도 앞은 같다

    everyone = demo_population(6000)
    assert len({user.id for user in everyone}) == len(everyone)
    handles = [user.username.lower() for user in everyone if user.username]
    assert len(set(handles)) == len(handles)
    for user in everyone:
        assert user.first_name and re.search("[가-힣A-Za-z]", user.first_name)
        if user.username:
            assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", user.username), user.username
        if user.is_bot:
            assert user.username and user.username.endswith("_bot")


def test_pool_has_people_who_must_be_skipped() -> None:
    pool = demo_population(POOL_SIZE)
    nameless = sum(1 for user in pool if user.username is None)
    bots = sum(1 for user in pool if user.is_bot)
    assert 0.15 <= nameless / POOL_SIZE <= 0.25  # 다섯에 하나쯤은 아이디가 없다
    assert 2 <= bots <= 20  # 봇도 몇 있다
    korean_names = sum(1 for user in pool if re.search("[가-힣]", user.first_name or ""))
    assert korean_names / POOL_SIZE > 0.7


def test_corpus_sounds_like_ordinary_chatter() -> None:
    assert len(CHATTER) >= 80
    assert len(set(CHATTER)) == len(CHATTER)
    for line in CHATTER:
        assert re.search("[가-힣]", line)
        assert match_keywords(line, ALL_KEYWORDS) == [], line  # 평소 대화는 규칙에 걸리지 않는다


def test_about_fifteen_percent_of_messages_show_buying_intent() -> None:
    rng = random.Random(5)
    messages = [random_message(rng) for _ in range(8000)]
    share = sum(1 for text in messages if match_keywords(text, ALL_KEYWORDS)) / len(messages)
    assert INTENT_RATIO == 0.15
    assert 0.12 <= share <= 0.18
    assert len(set(messages)) > 400  # 같은 말만 되풀이하지 않는다


def test_intent_lines_hit_exactly_their_own_rule() -> None:
    rng = random.Random(9)
    for kind, rule_name in INTENT_RULES.items():
        lines = {intent_message(rng, kind) for _ in range(1500)}
        assert len(lines) > 60
        for line in lines:
            for name, keywords in RULE_KEYWORDS.items():
                matched = match_keywords(line, keywords)
                assert bool(matched) == (name == rule_name), (line, name, matched)


def test_intent_phrases_come_in_varied_spacing() -> None:
    rng = random.Random(2)
    text = "\n".join(intent_message(rng) for _ in range(4000))
    for spaced, joined in (
        ("업체 추천", "업체추천"),
        ("광고 대행", "광고대행"),
        ("추천 부탁", "추천부탁"),
    ):
        assert spaced in text and joined in text
    for word in ("견적", "외주", "업체 소개", "마케팅 대행"):
        assert word in text
    # 두 규칙에 한꺼번에 걸리는 글도 있다.
    assert any(
        match_keywords(line, RULE_KEYWORDS["견적 문의"])
        and match_keywords(line, RULE_KEYWORDS["업체 찾는 사람"])
        for line in text.splitlines()
    )


def test_chat_cast_is_fixed_per_chat() -> None:
    pool = set(demo_population(POOL_SIZE))
    first, second = demo_chat_cast(-1001234567890), demo_chat_cast(-1009876543210)
    assert first == demo_chat_cast(-1001234567890)
    assert first.members != second.members
    for cast in (first, second):
        assert 16 <= len(cast.members) <= 34
        assert set(cast.members) <= pool
        assert len(cast.weights) == len(cast.members)
        assert len(cast.chatty) == 2
        for user in cast.chatty:
            assert user.username and not user.is_bot  # 활동량 규칙에 걸릴 수 있는 사람들
            assert cast.weights[cast.members.index(user)] > 5
    chatty_share = sum(w for w in first.weights if w > 5) / sum(first.weights)
    assert chatty_share > 0.3


# ---------------------------------------------------------------------------
# 링크별 가입 결과
# ---------------------------------------------------------------------------


def test_join_plan_depends_only_on_the_link() -> None:
    target = LinkTarget(LinkKind.PUBLIC, "Some_Seller_Group")
    plan = demo_join_plan(target)
    assert plan == demo_join_plan(LinkTarget(LinkKind.PUBLIC, "some_seller_group"))
    assert plan.chat.username == "some_seller_group"  # 대소문자를 어떻게 적든 같은 방이다
    assert demo_join_plan(LinkTarget(LinkKind.INVITE, "AbCdEfGh12345678")).chat.username is None


def test_join_plans_mostly_join_and_sometimes_fail() -> None:
    plans = [demo_join_plan(LinkTarget(LinkKind.INVITE, f"Hash{n:08d}")) for n in range(3000)]
    kinds = Counter(plan.kind for plan in plans)
    assert set(kinds) == set(JoinPlanKind)
    assert 0.62 <= kinds[JoinPlanKind.JOINED] / len(plans) <= 0.78
    assert 0.09 <= kinds[JoinPlanKind.REQUESTED] / len(plans) <= 0.19
    for kind in (JoinPlanKind.EXPIRED, JoinPlanKind.PRIVATE, JoinPlanKind.FLOOD):
        assert 0.01 <= kinds[kind] / len(plans) <= 0.1
    for plan in plans:
        assert 60 <= plan.flood_seconds <= 120
        assert 0.0 <= plan.approval_point <= 1.0
        assert re.search("[가-힣]", plan.chat.title)
        assert plan.chat.kind == GroupKind.SUPERGROUP
        assert plan.chat.id < -1_000_000_000_000
        assert plan.chat.member_count is not None and 100 <= plan.chat.member_count <= 25_000
    assert len({plan.chat.id for plan in plans}) == len(plans)

    public = [demo_join_plan(LinkTarget(LinkKind.PUBLIC, f"room_{n}")) for n in range(3000)]
    # 공개 아이디는 만료되지 않는다.
    assert JoinPlanKind.EXPIRED not in {plan.kind for plan in public}


def test_new_group_titles_do_not_repeat_seeded_ones() -> None:
    seeded_titles = set(demo_seed._GROUP_TITLES) | {c.title for c in demo_seed._EXTRA_DIALOGS}
    assert not seeded_titles & set(demo_gateway._NEW_GROUP_TITLES)


# ---------------------------------------------------------------------------
# 게이트웨이: 로그인
# ---------------------------------------------------------------------------


async def test_login_with_the_demo_code(gateway: DemoGateway, clock: TickClock) -> None:
    pending = await gateway.start_login("+82 10-5555-1234")
    assert pending.phone == "+821055551234"
    assert pending.code_via == "app"
    assert pending.expires_at == clock.now + timedelta(minutes=10)

    wrong = await expect_error(
        gateway.submit_code(pending.login_id, "54321"), TgErrorCode.CODE_INVALID
    )
    assert DEMO_CODE in wrong.message  # 데모에서는 맞는 코드를 알려 준다
    await expect_error(gateway.submit_code(pending.login_id, "  "), TgErrorCode.CODE_INVALID)

    result = await gateway.submit_code(pending.login_id, "12 345")
    assert result.status == "done"
    assert result.session is not None and result.session.startswith(SESSION_PREFIX)
    assert result.user is not None and result.user.phone == "+821055551234"
    assert result.user.username and result.user.first_name
    # 끝난 절차는 다시 쓸 수 없다.
    await expect_error(gateway.submit_code(pending.login_id, DEMO_CODE), TgErrorCode.LOGIN_EXPIRED)

    # 그 세션으로 접속하면 같은 사람이 나온다.
    connection = gateway.create_client(3, result.session)
    assert await connection.connect() == result.user
    assert connection.export_session() == result.session


async def test_login_accepts_local_numbers_and_rejects_nonsense(gateway: DemoGateway) -> None:
    assert (await gateway.start_login("010-1234-5678")).phone == "+821012345678"
    assert (await gateway.start_login("+1 (415) 555-0199")).phone == "+14155550199"
    for bad in ("abc", "12345", "+82 10 abcd 1234", "1" * 16):
        error = await expect_error(gateway.start_login(bad), TgErrorCode.PHONE_INVALID)
        assert error.permanent


async def test_login_with_two_factor_password(gateway: DemoGateway) -> None:
    pending = await gateway.start_login("+821099990000")
    await expect_error(
        gateway.submit_password(pending.login_id, DEMO_PASSWORD), TgErrorCode.CODE_INVALID
    )

    step = await gateway.submit_code(pending.login_id, DEMO_CODE)
    assert step.status == "password_required"
    assert step.session is None and step.user is None
    assert step.password_hint and DEMO_PASSWORD in step.password_hint

    await expect_error(
        gateway.submit_password(pending.login_id, "hunter2"), TgErrorCode.PASSWORD_INVALID
    )
    await expect_error(gateway.submit_password(pending.login_id, ""), TgErrorCode.PASSWORD_INVALID)
    done = await gateway.submit_password(pending.login_id, DEMO_PASSWORD)
    assert done.status == "done" and done.session and done.user
    assert done.user.phone == "+821099990000"


async def test_login_expires_and_can_be_cancelled(gateway: DemoGateway, clock: TickClock) -> None:
    pending = await gateway.start_login("+821011112222")
    clock.advance(10 * 60 + 1)
    error = await expect_error(
        gateway.submit_code(pending.login_id, DEMO_CODE), TgErrorCode.LOGIN_EXPIRED
    )
    assert error.permanent

    pending = await gateway.start_login("+821011112222")
    await gateway.cancel_login(pending.login_id)
    await gateway.cancel_login(pending.login_id)  # 두 번 버려도 오류가 아니다
    await expect_error(gateway.submit_code(pending.login_id, DEMO_CODE), TgErrorCode.LOGIN_EXPIRED)
    await expect_error(gateway.submit_code("no-such-login", DEMO_CODE), TgErrorCode.LOGIN_EXPIRED)

    # 같은 번호로 다시 시작하면 앞선 절차는 버려진다.
    first = await gateway.start_login("+821011112222")
    second = await gateway.start_login("+821011112222")
    await expect_error(gateway.submit_code(first.login_id, DEMO_CODE), TgErrorCode.LOGIN_EXPIRED)
    assert (await gateway.submit_code(second.login_id, DEMO_CODE)).status == "done"

    # close() 는 진행 중인 절차를 모두 정리한다.
    third = await gateway.start_login("+821033334444")
    await gateway.close()
    await expect_error(gateway.submit_code(third.login_id, DEMO_CODE), TgErrorCode.LOGIN_EXPIRED)


async def test_same_phone_is_the_same_person_with_a_new_session(gateway: DemoGateway) -> None:
    async def login(phone: str) -> tuple[str, TgUser]:
        pending = await gateway.start_login(phone)
        result = await gateway.submit_code(pending.login_id, DEMO_CODE)
        assert result.session and result.user
        return result.session, result.user

    first_session, first_user = await login("+821044445555")
    second_session, second_user = await login("010 4444 5555")
    other_session, other_user = await login("+821066667777")
    assert first_user == second_user
    assert len({first_session, second_session, other_session}) == 3
    assert other_user.id != first_user.id

    # 등록해 둔 세션의 번호로 로그인하면 그 세션의 주인이 나온다.
    owner = TgUser(id=7_700_000_001, username="owner_one", first_name="지우", phone="+821052873421")
    gateway.register_session(f"{SESSION_PREFIX}1", owner)
    _, again = await login("+821052873421")
    assert again == owner


async def test_import_session_accepts_only_demo_sessions(gateway: DemoGateway) -> None:
    text = f"{SESSION_PREFIX}my-second-account-session"
    result = await gateway.import_session(f"  {text}\n")
    assert result.status == "done" and result.session == text and result.user is not None
    assert (await gateway.import_session(text.encode())).user == result.user  # 파일로 올려도 같다
    assert (await gateway.import_session(f"{SESSION_PREFIX}another")).user != result.user

    for bad in ("1BVtsOKABu5aTelethonStringSession", SESSION_PREFIX, "", b"\xff\xfe\x00SQLite"):
        error = await expect_error(gateway.import_session(bad), TgErrorCode.SESSION_FORMAT)
        assert error.permanent

    gateway.revoke_session(text)
    await expect_error(gateway.import_session(text), TgErrorCode.SESSION_INVALID)

    with pytest.raises(ValueError):
        gateway.register_session("1BVtsOKABu5a", result.user)


# ---------------------------------------------------------------------------
# 게이트웨이: 연결과 대화
# ---------------------------------------------------------------------------


async def test_connect_returns_the_session_owner(gateway: DemoGateway) -> None:
    owner = TgUser(
        id=7_700_000_002, username="minho_sales", first_name="민호", phone="+821091246608"
    )
    gateway.register_session(f"{SESSION_PREFIX}2", owner)
    connection = gateway.create_client(2, f"{SESSION_PREFIX}2")
    assert connection.account_id == 2
    assert await connection.connect() == owner
    assert await connection.connect() == owner  # 다시 불러도 같다
    assert connection.export_session() == f"{SESSION_PREFIX}2"

    # 등록하지 않은 세션도 접속된다. 같은 세션은 언제나 같은 사람이다.
    stranger = await gateway.create_client(5, f"{SESSION_PREFIX}77").connect()
    assert stranger == await fast_gateway().create_client(9, f"{SESSION_PREFIX}77").connect()
    assert stranger.id != owner.id and stranger.username


async def test_connect_refuses_real_and_expired_sessions(gateway: DemoGateway) -> None:
    real = gateway.create_client(1, "1BVtsOKABu5aTelethonStringSession")
    error = await expect_error(real.connect(), TgErrorCode.SESSION_INVALID)
    assert error.permanent and "데모" in error.message

    gateway.revoke_session(f"{SESSION_PREFIX}10")
    expired = gateway.create_client(10, f"{SESSION_PREFIX}10")
    error = await expect_error(expired.connect(), TgErrorCode.SESSION_INVALID)
    assert error.permanent
    assert other_tasks() == set()  # 접속하지 못한 연결은 아무 태스크도 남기지 않는다


async def test_wait_closed_stays_pending_until_disconnect(client: DemoClient) -> None:
    waiter = asyncio.create_task(client.wait_closed())
    await asyncio.sleep(0.05)
    assert not waiter.done()

    cancelled = asyncio.create_task(client.wait_closed())
    await asyncio.sleep(0)
    cancelled.cancel()
    await asyncio.sleep(0.01)
    assert client.connected and not waiter.done()  # 기다리던 쪽이 취소돼도 연결은 그대로다

    await client.disconnect()
    await asyncio.wait_for(waiter, 1)
    assert not client.connected
    await client.disconnect()  # 이미 끊겨 있어도 오류가 아니다
    await asyncio.wait_for(client.wait_closed(), 1)
    await asyncio.wait_for(DemoClient(fast_gateway(), 4, f"{SESSION_PREFIX}4").wait_closed(), 1)


async def test_revoking_a_session_drops_its_connection(
    gateway: DemoGateway, client: DemoClient
) -> None:
    waiter = asyncio.create_task(client.wait_closed())
    await asyncio.sleep(0.01)
    gateway.revoke_session(client.session)
    error = await expect_error(asyncio.wait_for(waiter, 1), TgErrorCode.SESSION_INVALID)
    assert error.permanent
    assert not client.connected
    await expect_error(client.connect(), TgErrorCode.SESSION_INVALID)
    await asyncio.sleep(0.01)
    assert other_tasks() == set()


async def test_connected_client_emits_messages_from_its_own_chats(
    gateway: DemoGateway, client: DemoClient, clock: TickClock
) -> None:
    mine, also_mine = chat(1, members=9000), chat(2, members=300)
    channel, not_mine = chat(3, kind=GroupKind.CHANNEL), chat(4)
    for room in (mine, also_mine, channel):
        gateway.register_chat(1, room)
    gateway.register_chat(2, not_mine)

    await asyncio.sleep(0.1)  # 핸들러가 없으면 아무것도 내보내지 않는다
    received: list[IncomingMessage] = []

    async def handler(message: IncomingMessage) -> None:
        received.append(message)

    client.set_message_handler(handler)
    await wait_until(lambda: _enough(received, 150), what="메시지 150개")
    client.set_message_handler(None)
    count = len(received)
    await asyncio.sleep(0.1)
    assert len(received) == count  # 핸들러를 떼면 멈춘다

    by_chat = Counter(message.chat_id for message in received)
    assert set(by_chat) == {mine.id, also_mine.id}  # 채널과 남의 방에서는 오지 않는다
    assert by_chat[mine.id] > by_chat[also_mine.id]  # 사람이 많은 방이 더 시끄럽다
    for room in (mine, also_mine):
        ids = [message.message_id for message in received if message.chat_id == room.id]
        assert ids == sorted(set(ids))  # 방마다 번호가 겹치지 않고 커진다
        members = set(demo_chat_cast(room.id).members)
        for message in received:
            if message.chat_id == room.id and message.sender is not None:
                assert message.sender in members
    for message in received:
        assert message.account_id == 1
        assert message.date == clock.now
        assert re.search("[가-힣]", message.text)


async def _enough(items: list, count: int) -> bool:
    return len(items) >= count


async def test_traffic_exercises_every_skip_rule_and_has_chatty_people(
    gateway: DemoGateway,
) -> None:
    room = chat(5)
    gateway.register_chat(1, room)
    messages = [gateway.compose(1) for _ in range(6000)]
    assert all(message is not None and message.chat_id == room.id for message in messages)
    senders = [message.sender for message in messages if message is not None]

    assert any(sender is None for sender in senders)  # 익명 관리자 글
    assert any(sender is not None and sender.username is None for sender in senders)
    cast = demo_chat_cast(room.id)
    if any(member.is_bot for member in cast.members):
        assert any(sender is not None and sender.is_bot for sender in senders)

    spoke = Counter(sender.id for sender in senders if sender is not None)
    loudest = {user_id for user_id, _ in spoke.most_common(2)}
    assert loudest == {user.id for user in cast.chatty}
    assert spoke.most_common(1)[0][1] / len(senders) > 0.12

    assert gateway.compose(99) is None  # 들어가 있는 방이 없는 계정


async def test_same_seed_gives_the_same_conversation() -> None:
    def script(seed: int) -> list[tuple[int, int | None, str]]:
        world = fast_gateway(seed=seed)
        for number in range(1, 6):
            world.register_chat(1, chat(number, members=200 * number))
        lines = [world.compose(1) for _ in range(300)]
        return [(m.chat_id, m.sender.id if m.sender else None, m.text) for m in lines if m]

    assert script(21) == script(21)
    assert script(21) != script(22)


async def test_close_stops_all_traffic() -> None:
    world = fast_gateway()
    received: list[IncomingMessage] = []

    async def handler(message: IncomingMessage) -> None:
        received.append(message)

    clients = []
    for account_id in (1, 2, 3):
        world.register_chat(account_id, chat(account_id))
        connection = world.create_client(account_id, f"{SESSION_PREFIX}{account_id}")
        await connection.connect()
        connection.set_message_handler(handler)
        clients.append(connection)
    await wait_until(lambda: _enough(received, 30), what="메시지 30개")
    assert {message.account_id for message in received} == {1, 2, 3}

    await world.close()
    count = len(received)
    await asyncio.sleep(0.1)
    assert len(received) == count
    assert other_tasks() == set()
    for connection in clients:
        await asyncio.wait_for(connection.wait_closed(), 1)  # 정상적으로 끊긴 것이다

    # 닫은 뒤에도 세계는 남아 있어서 다시 접속하면 대화가 이어진다.
    await clients[0].connect()
    await wait_until(lambda: _enough(received, count + 5), what="다시 흐르는 메시지")
    await world.close()


async def test_a_failing_handler_does_not_stop_the_traffic(
    gateway: DemoGateway, client: DemoClient
) -> None:
    gateway.register_chat(1, chat(6))
    calls: list[int] = []

    async def handler(message: IncomingMessage) -> None:
        calls.append(message.message_id)
        raise RuntimeError("일부러 낸 오류")

    client.set_message_handler(handler)
    await wait_until(lambda: _enough(calls, 5), what="오류 뒤에도 이어지는 메시지")


def test_pace_must_be_a_positive_ordered_range() -> None:
    for bad in ((0.0, 1.0), (2.0, 1.0), (-1.0, 1.0)):
        with pytest.raises(ValueError):
            DemoGateway(pace=bad)
    with pytest.raises(ValueError):
        DemoGateway(join_delay=(1.0, 0.5))
    with pytest.raises(ValueError):
        DemoGateway(approval_delay=(-1.0, 5.0))


# ---------------------------------------------------------------------------
# 게이트웨이: 그룹 가입
# ---------------------------------------------------------------------------


async def test_requests_need_a_connection(gateway: DemoGateway) -> None:
    idle = gateway.create_client(1, f"{SESSION_PREFIX}1")
    target = link_with(JoinPlanKind.JOINED)
    await expect_error(idle.join(target), TgErrorCode.NETWORK)
    await expect_error(idle.list_groups(), TgErrorCode.NETWORK)
    await expect_error(idle.find_membership(target, None), TgErrorCode.NETWORK)
    await expect_error(idle.leave(-1), TgErrorCode.NETWORK)
    await expect_error(idle.log_out(), TgErrorCode.NETWORK)


async def test_join_most_links_join_right_away(gateway: DemoGateway, client: DemoClient) -> None:
    for link_kind in (LinkKind.INVITE, LinkKind.PUBLIC):
        target = link_with(JoinPlanKind.JOINED, link_kind)
        assert await client.find_membership(target, None) is None

        result = await client.join(target)
        planned = demo_join_plan(target).chat
        assert result.outcome == JoinOutcome.JOINED and result.chat is not None
        assert (result.chat.id, result.chat.username, result.chat.member_count) == (
            planned.id,
            planned.username,
            planned.member_count,
        )
        assert re.search("[가-힣]", result.chat.title) and result.chat.member_count

        assert result.chat in await client.list_groups()
        assert await client.find_membership(target, None) == result.chat
        assert await client.find_membership(None, result.chat.id) == result.chat
        # 이미 들어가 있으면 다시 불러도 JOINED 다.
        assert await client.join(target) == result

    # 다른 계정은 그 방의 멤버가 아니다.
    other = gateway.create_client(2, f"{SESSION_PREFIX}2")
    await other.connect()
    assert await other.list_groups() == []
    assert await other.find_membership(target, None) is None
    # 공개 그룹은 대소문자가 달라도 같은 방이다.
    shouted = LinkTarget(LinkKind.PUBLIC, target.value.upper())
    assert (await client.join(shouted)).chat == result.chat


async def test_join_request_is_approved_later(
    gateway: DemoGateway, client: DemoClient, clock: TickClock
) -> None:
    target = link_with(JoinPlanKind.REQUESTED)
    plan = demo_join_plan(target)

    result = await client.join(target)
    assert result.outcome == JoinOutcome.REQUESTED
    assert result.chat is None  # 초대 링크는 미리보기만 알 수 있다
    assert result.title == plan.chat.title and result.member_count == plan.chat.member_count
    assert await client.list_groups() == []

    clock.advance(59)
    assert await client.find_membership(target, None) is None
    assert (await client.join(target)).outcome == JoinOutcome.REQUESTED  # 이미 요청한 상태

    clock.advance(62)  # 60~120초 사이에 승인된다
    assert await client.find_membership(target, None) == plan.chat
    assert await client.list_groups() == [plan.chat]
    assert (await client.join(target)).outcome == JoinOutcome.JOINED
    assert gateway.compose(1) is not None  # 승인된 방에서 대화가 흐른다


async def test_public_join_request_knows_the_chat(client: DemoClient, clock: TickClock) -> None:
    target = link_with(JoinPlanKind.REQUESTED, LinkKind.PUBLIC)
    result = await client.join(target)
    assert result.outcome == JoinOutcome.REQUESTED
    assert result.chat is not None and result.chat.username == target.value

    assert await client.find_membership(None, result.chat.id) is None
    clock.advance(121)
    # 방 id 만으로도 확인된다.
    assert await client.find_membership(None, result.chat.id) == result.chat


async def test_join_fails_for_expired_and_private_links(client: DemoClient) -> None:
    expired = await expect_error(
        client.join(link_with(JoinPlanKind.EXPIRED)), TgErrorCode.INVITE_EXPIRED
    )
    assert expired.permanent
    for link_kind in (LinkKind.INVITE, LinkKind.PUBLIC):
        private = await expect_error(
            client.join(link_with(JoinPlanKind.PRIVATE, link_kind)), TgErrorCode.PRIVATE
        )
        assert private.permanent
    # 다시 시도해도 결과는 같다.
    await expect_error(client.join(link_with(JoinPlanKind.EXPIRED)), TgErrorCode.INVITE_EXPIRED)
    assert await client.list_groups() == []


async def test_join_flood_wait_must_be_waited_out(
    gateway: DemoGateway, client: DemoClient, clock: TickClock
) -> None:
    target = link_with(JoinPlanKind.FLOOD)
    plan = demo_join_plan(target)

    flood = await expect_error(client.join(target), TgErrorCode.FLOOD_WAIT)
    assert flood.retry_after == plan.flood_seconds and 60 <= flood.retry_after <= 120
    assert not flood.permanent

    # 제한이 풀리기 전에는 이 계정의 어떤 요청도 받지 않고, 남은 시간을 알려 준다.
    clock.advance(plan.flood_seconds - 10)
    for call in (
        client.join(target),
        client.list_groups(),
        client.find_membership(target, None),
        client.leave(plan.chat.id),
        client.join(link_with(JoinPlanKind.JOINED)),
    ):
        early = await expect_error(call, TgErrorCode.FLOOD_WAIT)
        assert early.retry_after == 10
    assert client.connected  # 연결은 유지된다

    # 다른 계정은 영향을 받지 않는다.
    other = gateway.create_client(2, f"{SESSION_PREFIX}2")
    await other.connect()
    assert await other.list_groups() == []

    clock.advance(10)
    result = await client.join(target)
    assert result.outcome == JoinOutcome.JOINED and result.chat == plan.chat


async def test_new_groups_get_distinct_titles(gateway: DemoGateway, client: DemoClient) -> None:
    targets = [
        target
        for target in (LinkTarget(LinkKind.INVITE, f"TitleCheck{n:06d}") for n in range(60))
        if demo_join_plan(target).kind in (JoinPlanKind.JOINED, JoinPlanKind.REQUESTED)
    ][:30]
    planned = [demo_join_plan(target).chat.title for target in targets]
    assert len(set(planned)) < len(planned)  # 링크만으로 정한 이름은 겹치는 것이 있다

    results = [await client.join(target) for target in targets]
    titles = [result.chat.title if result.chat else result.title for result in results]
    assert len(set(titles)) == len(titles)  # 세계에 들어올 때 겹치지 않는 이름으로 바뀐다
    assert set(titles) <= set(demo_gateway._NEW_GROUP_TITLES)

    # 다른 계정이 같은 링크로 들어가면 같은 방(같은 이름)이다.
    other = gateway.create_client(2, f"{SESSION_PREFIX}2")
    await other.connect()
    joined = next(t for t in targets if demo_join_plan(t).kind == JoinPlanKind.JOINED)
    assert (await other.join(joined)).chat == (await client.join(joined)).chat


async def test_scripted_flood_wait(
    gateway: DemoGateway, client: DemoClient, clock: TickClock
) -> None:
    gateway.start_flood_wait(1, 14 * 60)
    gateway.start_flood_wait(1, 30)  # 더 짧은 제한이 긴 제한을 줄이지는 않는다
    error = await expect_error(client.list_groups(), TgErrorCode.FLOOD_WAIT)
    assert error.retry_after == 14 * 60
    assert "14분" in error.message

    clock.advance(14 * 60 - 0.5)
    assert (await expect_error(client.list_groups(), TgErrorCode.FLOOD_WAIT)).retry_after == 1
    clock.advance(0.5)
    assert await client.list_groups() == []


async def test_join_takes_the_configured_delay_and_can_be_cancelled(clock: TickClock) -> None:
    world = fast_gateway(clock, join_delay=(0.2, 0.2))
    connection = world.create_client(1, f"{SESSION_PREFIX}1")
    await connection.connect()
    target = link_with(JoinPlanKind.JOINED)

    attempt = asyncio.create_task(connection.join(target))
    await asyncio.sleep(0.05)
    assert not attempt.done()
    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt
    assert await connection.list_groups() == []  # 취소된 가입은 흔적을 남기지 않는다

    started = time.perf_counter()
    assert (await connection.join(target)).outcome == JoinOutcome.JOINED
    assert time.perf_counter() - started >= 0.19

    # 답을 기다리는 사이 연결이 끊기면 가입되지 않는다.
    late = asyncio.create_task(connection.join(link_with(JoinPlanKind.JOINED, LinkKind.PUBLIC)))
    await asyncio.sleep(0.05)
    await connection.disconnect()
    await expect_error(late, TgErrorCode.NETWORK)
    await world.close()


async def test_leave_and_log_out(gateway: DemoGateway, client: DemoClient) -> None:
    target = link_with(JoinPlanKind.JOINED)
    joined = (await client.join(target)).chat
    assert joined is not None
    kept = chat(8)
    gateway.register_chat(1, kept)

    await client.leave(joined.id)
    await client.leave(joined.id)  # 이미 나간 방이어도 조용히 넘어간다
    assert await client.list_groups() == [kept]
    assert await client.find_membership(target, joined.id) is None
    assert (await client.join(target)).chat == joined  # 다시 들어갈 수 있다

    await client.log_out()
    assert not client.connected
    await asyncio.wait_for(client.wait_closed(), 1)
    await expect_error(client.connect(), TgErrorCode.SESSION_INVALID)  # 세션이 영구히 무효가 된다
    assert other_tasks() == set()


async def test_registered_chats_and_requests(
    gateway: DemoGateway, client: DemoClient, clock: TickClock
) -> None:
    public = TgChat(
        -1_003_000_000_050, "등록한 공개 방", "Registered_Room", GroupKind.SUPERGROUP, 700
    )
    invited = chat(51)
    invite = LinkTarget(LinkKind.INVITE, "RegisteredHash01")
    gateway.register_chat(1, public)
    gateway.register_chat(1, invited, target=invite)
    assert gateway.chats_of(1) == (public, invited)
    assert gateway.chats_of(2) == ()

    # 이미 들어가 있는 방의 링크로 가입하면 바로 JOINED 다(링크로도, 공개 아이디로도 찾는다).
    assert (await client.join(invite)).chat == invited
    assert (await client.join(LinkTarget(LinkKind.PUBLIC, "registered_room"))).chat == public

    waiting = LinkTarget(LinkKind.INVITE, "WaitingHash0001")
    held = LinkTarget(LinkKind.INVITE, "HeldHash00000001")
    gateway.register_request(1, waiting, chat(52))
    gateway.register_request(1, held, chat(53), approve=False)
    assert (await client.join(waiting)).outcome == JoinOutcome.REQUESTED
    clock.advance(3600)
    assert await client.find_membership(waiting, None) == chat(52)
    # 승인하지 않기로 한 요청은 계속 기다린다.
    assert await client.find_membership(held, None) is None
    assert (await client.join(held)).outcome == JoinOutcome.REQUESTED


# ---------------------------------------------------------------------------
# 처음 채우는 데이터
# ---------------------------------------------------------------------------


def test_seed_is_fast(snap: Snapshot) -> None:
    assert snap.seconds < 3.0


def test_seed_does_not_create_the_admin(snap: Snapshot) -> None:
    assert snap.admins == 0


def test_seed_accounts(snap: Snapshot) -> None:
    assert [account.first_name for account in snap.accounts] == ACCOUNT_NAMES
    assert [account.id for account in snap.accounts] == list(range(1, 11))
    assert snap.sessions == [f"{SESSION_PREFIX}{n}" for n in range(1, 11)]
    assert snap.sessions[GUNWOO - 1] == EXPIRED_SESSION
    assert len({account.tg_user_id for account in snap.accounts}) == 10
    assert len({account.username for account in snap.accounts}) == 10
    for account, session in zip(snap.accounts, snap.sessions, strict=True):
        assert account.phone and re.fullmatch(r"\+8210\d{8}", account.phone)
        assert not account.phone.endswith("0000")  # 2단계 인증을 묻는 번호가 아니다
        assert account.session_enc and session not in account.session_enc  # 암호화해서 넣는다
        assert account.enabled and account.tg_user_id and account.username
        assert account.created_at < NOW - timedelta(days=HISTORY_DAYS - 1)
        assert account.last_connected_at is not None and account.last_connected_at <= NOW

    yerin, gunwoo = snap.accounts[YERIN - 1], snap.accounts[GUNWOO - 1]
    assert yerin.status == AccountStatus.FLOOD_WAIT
    assert yerin.flood_until == NOW + timedelta(minutes=FLOOD_WAIT_MINUTES)
    assert FLOOD_WAIT_MINUTES == 14
    assert yerin.status_detail == engine._DETAIL_FLOOD  # 엔진이 쓰는 문장과 같다
    assert gunwoo.status == AccountStatus.REAUTH_REQUIRED
    assert gunwoo.status_detail and "다시 로그인" in gunwoo.status_detail
    for account in snap.accounts:
        if account.id not in (YERIN, GUNWOO):
            assert account.status == AccountStatus.OFFLINE and account.flood_until is None


def test_seed_groups_per_account(snap: Snapshot) -> None:
    by_account: dict[int, Counter[str]] = defaultdict(Counter)
    for group in snap.groups:
        by_account[group.account_id][group.status] += 1
    joined = [by_account[account.id][GroupStatus.JOINED] for account in snap.accounts]
    assert joined == JOINED_PER_ACCOUNT and sum(joined) == 187

    requested = {
        a: c[GroupStatus.REQUESTED] for a, c in by_account.items() if c[GroupStatus.REQUESTED]
    }
    assert sum(requested.values()) == 6 and len(requested) >= 3
    assert dict(by_account[GUNWOO]) == {
        GroupStatus.JOINED: 13,
        GroupStatus.REQUESTED: 3,
        GroupStatus.QUEUED: 2,
        GroupStatus.FAILED: 2,
    }
    for account_id, counts in by_account.items():
        occupying = sum(n for status, n in counts.items() if status != GroupStatus.FAILED)
        assert occupying <= 20, account_id  # 자리가 있는 계정에만 넣었다
    assert len(snap.groups) == 187 + 6 + 2 + 2


def test_seed_joined_groups_look_real(snap: Snapshot) -> None:
    joined = snap.joined()
    titles = [group.title for group in joined]
    assert len(set(titles)) == len(titles)
    for wanted in (*TOP_GROUPS, "프리랜서 디자이너 네트워크", "위탁판매 초보방"):
        assert wanted in titles
    assert len({group.tg_chat_id for group in joined}) == len(joined)

    link_kinds = Counter(group.link_kind for group in joined)
    assert link_kinds[LinkKind.INVITE] > 80 and link_kinds[LinkKind.PUBLIC] > 20
    assert link_kinds[LinkKind.EXISTING] == 6
    for group in joined:
        assert group.title and re.search("[가-힣]", group.title)
        assert group.tg_chat_id is not None and group.tg_chat_id < 0
        assert group.kind in (GroupKind.SUPERGROUP, GroupKind.GROUP)
        assert (group.kind == GroupKind.SUPERGROUP) == (group.tg_chat_id < -1_000_000_000_000)
        assert group.member_count and 30 <= group.member_count <= 20_000
        assert group.monitoring and group.status_detail is None and group.error_code is None
        assert group.joined_at is not None and group.created_at <= group.joined_at <= NOW
        assert group.messages_seen > 0
        assert group.last_message_at is not None
        assert group.joined_at <= group.last_message_at <= NOW
        if group.link_kind == LinkKind.PUBLIC:
            assert group.public_username and group.invite_hash is None
            assert group.public_username in (group.source_link or "")
        elif group.link_kind == LinkKind.INVITE:
            assert group.invite_hash and group.public_username is None
            assert group.source_link == f"https://t.me/+{group.invite_hash}"
        else:
            assert group.source_link is None and group.invite_hash is None

    # 건우 계정은 세션이 만료된 뒤로 메시지를 받지 못했다.
    for group in joined:
        if group.account_id == GUNWOO:
            assert group.last_message_at <= NOW - timedelta(hours=25)


def test_seed_pending_and_failed_groups_match_what_the_gateway_would_answer(snap: Snapshot) -> None:
    def target_of(group: Group) -> LinkTarget:
        if group.link_kind == LinkKind.INVITE:
            assert group.invite_hash
            return LinkTarget(LinkKind.INVITE, group.invite_hash)
        assert group.public_username
        return LinkTarget(LinkKind.PUBLIC, group.public_username)

    by_status: dict[str, list[Group]] = defaultdict(list)
    for group in snap.groups:
        by_status[group.status].append(group)

    requested = by_status[GroupStatus.REQUESTED]
    for group in requested:
        assert demo_join_plan(target_of(group)).kind == JoinPlanKind.REQUESTED
        assert group.status_detail == engine._DETAIL_REQUESTED
        assert group.title and group.member_count and group.joined_at is None
        assert group.tg_chat_id is None and group.kind is None
    held = [group for group in requested if group.invite_hash in HELD_REQUESTS]
    assert len(held) == 5  # 하나는 켜 두면 승인된다

    for group in by_status[GroupStatus.QUEUED]:
        assert demo_join_plan(target_of(group)).kind == JoinPlanKind.JOINED
        assert group.title is None and group.tg_chat_id is None and group.source_link
        assert group.next_attempt_at is None and group.attempts == 0

    failed = {group.error_code: group for group in by_status[GroupStatus.FAILED]}
    assert set(failed) == {"invite_expired", "private"}
    assert demo_join_plan(target_of(failed["invite_expired"])).kind == JoinPlanKind.EXPIRED
    assert demo_join_plan(target_of(failed["private"])).kind == JoinPlanKind.PRIVATE
    assert failed["invite_expired"].status_detail == "초대 링크가 만료됐어요."
    assert "비공개" in (failed["private"].status_detail or "")


def test_seed_rules(snap: Snapshot) -> None:
    assert [rule.name for rule in snap.rules] == list(RULE_LEADS)
    for rule in snap.rules:
        assert rule.enabled and rule.all_groups and rule.groups == []
    for rule in snap.rules[:3]:
        assert rule.kind == RuleKind.KEYWORD
        assert rule.keywords == RULE_KEYWORDS[rule.name]
        assert rule.exclude_keywords == [] and rule.match_mode == "any"
    activity = snap.rules[3]
    assert activity.kind == RuleKind.ACTIVITY
    assert (activity.min_messages, activity.window_hours) == (30, 24)


def test_seed_leads_are_unique_collectable_users(snap: Snapshot) -> None:
    assert len(snap.leads) == TOTAL_LEADS == 4800
    assert len({lead.tg_user_id for lead in snap.leads}) == TOTAL_LEADS
    assert len({lead.username.lower() for lead in snap.leads}) == TOTAL_LEADS  # 같은 아이디가 없다
    people = {user.id: user for user in demo_population(demo_seed._POPULATION)}
    own_ids = {account.tg_user_id for account in snap.accounts}
    own_names = {(account.username or "").lower() for account in snap.accounts}
    blocked = {entry.username for entry in snap.blocklist}
    for lead in snap.leads:
        person = people[lead.tg_user_id]
        assert person.username == lead.username and not person.is_bot
        assert (lead.first_name, lead.last_name) == (person.first_name, person.last_name)
        assert lead.tg_user_id not in own_ids and lead.username.lower() not in own_names
        assert lead.username.lower() not in blocked

    # 지금 그룹에서 말하는 사람들 가운데 일부만 이미 수집돼 있다(나머지는 켜 두면 새로 수집된다).
    speakers = {u.id for u in demo_population(POOL_SIZE) if u.username and not u.is_bot}
    known = speakers & {lead.tg_user_id for lead in snap.leads}
    assert 0.6 <= len(known) / len(speakers) <= 0.85


def test_seed_lead_statuses(snap: Snapshot) -> None:
    statuses = Counter(lead.status for lead in snap.leads)
    assert set(statuses) == set(LeadStatus)
    assert statuses[LeadStatus.NEW] / TOTAL_LEADS > 0.6  # 대부분 새로 수집된 상태
    assert (
        statuses[LeadStatus.REVIEWED]
        > statuses[LeadStatus.CONTACTED]
        > statuses[LeadStatus.EXCLUDED]
    )
    assert 20 <= statuses[LeadStatus.EXCLUDED] <= TOTAL_LEADS * 0.05
    noted = [lead for lead in snap.leads if lead.note]
    assert noted and all(lead.status != LeadStatus.NEW for lead in noted)
    fresh = [lead for lead in snap.leads if lead.first_seen_at > NOW - timedelta(hours=12)]
    assert all(lead.status in (LeadStatus.NEW, LeadStatus.REVIEWED) for lead in fresh)


def test_seed_last_seven_days_match_the_targets(snap: Snapshot) -> None:
    today = NOW.astimezone(SEOUL).date()
    per_day: Counter[tuple[object, str]] = Counter()
    for lead in snap.leads:
        per_day[(lead.first_seen_at.astimezone(SEOUL).date(), lead.first_kind)] += 1
    days = [today - timedelta(days=back) for back in range(6, -1, -1)]
    assert [per_day[(day, RuleKind.KEYWORD)] for day in days] == list(RECENT_KEYWORD_LEADS)
    assert [per_day[(day, RuleKind.ACTIVITY)] for day in days] == list(RECENT_ACTIVITY_LEADS)
    assert RECENT_KEYWORD_LEADS == (52, 61, 44, 83, 97, 68, 89)
    assert RECENT_ACTIVITY_LEADS == (22, 30, 22, 37, 46, 29, 39)

    # 30일에 걸쳐 있고, 처음에 많이 수집되다가 차츰 줄어든다.
    window = [today - timedelta(days=back) for back in range(HISTORY_DAYS - 1, -1, -1)]
    totals = [
        per_day[(day, RuleKind.KEYWORD)] + per_day[(day, RuleKind.ACTIVITY)] for day in window
    ]
    assert sum(totals) == TOTAL_LEADS  # 30일 밖에는 없다
    assert min(totals) >= 60
    assert sum(totals[:7]) > sum(totals[10:17]) > sum(totals[-7:])


def test_seed_has_nothing_in_the_future(snap: Snapshot) -> None:
    assert max(hit.created_at for hit in snap.hits) <= NOW
    assert max(lead.last_seen_at for lead in snap.leads) <= NOW
    assert max(log.created_at for log in snap.logs) <= NOW
    assert max(group.created_at for group in snap.groups) <= NOW
    assert max(entry.created_at for entry in snap.blocklist) <= NOW
    # 오늘 수집된 유저는 오늘 0시와 지금 사이에 있다.
    midnight = datetime.combine(NOW.astimezone(SEOUL).date(), datetime.min.time(), tzinfo=SEOUL)
    today = [lead for lead in snap.leads if lead.first_seen_at >= midnight]
    assert len(today) == RECENT_KEYWORD_LEADS[-1] + RECENT_ACTIVITY_LEADS[-1]
    # 수집은 방금까지 이어졌다.
    assert NOW - max(lead.first_seen_at for lead in today) < timedelta(minutes=30)


def test_seed_lead_and_hit_invariants(snap: Snapshot) -> None:
    hits_by_lead = snap.hits_by_lead()
    assert set(hits_by_lead) == {lead.id for lead in snap.leads}
    hit_counts: Counter[int] = Counter()
    for lead in snap.leads:
        hits = sorted(hits_by_lead[lead.id], key=lambda hit: (hit.created_at, hit.id))
        assert lead.hit_count == len(hits) and 1 <= len(hits) <= 5
        assert lead.first_seen_at == hits[0].created_at
        assert lead.last_seen_at == hits[-1].created_at
        assert lead.last_hit_id == hits[-1].id
        assert lead.first_kind == hits[0].kind
        times = [hit.created_at for hit in hits]
        assert len(set(times)) == len(times)
        activity_times = [hit.created_at for hit in hits if hit.kind == RuleKind.ACTIVITY]
        for earlier, later in itertools.pairwise(activity_times):
            assert later - earlier > timedelta(hours=24)  # 활동량은 기간이 지나야 다시 기록된다
        hit_counts[len(hits)] += 1
    assert set(hit_counts) == {1, 2, 3, 4, 5}
    assert hit_counts[1] > hit_counts[2] > hit_counts[3] > hit_counts[4] > hit_counts[5]

    # 감지와 유저는 저장된 순서가 시간순이다.
    assert [hit.created_at for hit in snap.hits] == sorted(hit.created_at for hit in snap.hits)
    assert [lead.first_seen_at for lead in snap.leads] == sorted(
        lead.first_seen_at for lead in snap.leads
    )


def test_seed_hits_are_consistent_with_rules_and_groups(snap: Snapshot) -> None:
    rules = {rule.id: rule for rule in snap.rules}
    groups = {group.id: group for group in snap.groups}
    gunwoo_expired_at = NOW - timedelta(hours=26)
    excerpts: set[str] = set()
    for hit in snap.hits:
        rule, group = rules[hit.rule_id], groups[hit.group_id]
        assert hit.rule_name == rule.name and hit.kind == rule.kind
        assert group.status == GroupStatus.JOINED
        assert hit.group_title == group.title and hit.account_id == group.account_id
        assert group.joined_at is not None and hit.created_at >= group.joined_at
        if group.account_id == GUNWOO:
            assert hit.created_at <= gunwoo_expired_at
        if hit.kind == RuleKind.KEYWORD:
            assert hit.excerpt and len(hit.excerpt) <= 202
            assert hit.keywords and set(hit.keywords) <= set(rule.keywords)
            assert match_keywords(hit.excerpt, rule.keywords) == hit.keywords
            assert hit.tg_message_id and hit.message_count is None and hit.window_hours is None
            excerpts.add(hit.excerpt)
        else:
            assert hit.excerpt is None and hit.keywords == [] and hit.tg_message_id is None
            assert hit.message_count is not None and hit.message_count >= 30
            assert hit.window_hours == 24
    assert len(excerpts) > 300  # 문장이 다양하다
    assert any(excerpt.endswith("…") for excerpt in excerpts)  # 긴 글은 잘라서 넣는다


def test_seed_rule_lead_counts(snap: Snapshot) -> None:
    by_rule: dict[str, set[int]] = defaultdict(set)
    first_rule: Counter[str] = Counter()
    for hits in snap.hits_by_lead().values():
        first_rule[min(hits, key=lambda hit: (hit.created_at, hit.id)).rule_name] += 1
        for hit in hits:
            by_rule[hit.rule_name].add(hit.lead_id)
    assert dict(first_rule) == RULE_LEADS
    for name, target in RULE_LEADS.items():
        # 대략 1,900 / 1,200 / 700 / 1,000
        assert target <= len(by_rule[name]) <= target * 1.1, name
    # 두 가지 이상의 규칙에 걸린 사람도 조금 있다.
    several = sum(1 for hits in snap.hits_by_lead().values() if len({h.rule_id for h in hits}) > 1)
    assert 50 <= several <= 500


def test_seed_top_groups(snap: Snapshot) -> None:
    leads_by_group: dict[int, set[int]] = defaultdict(set)
    for hit in snap.hits:
        leads_by_group[hit.group_id].add(hit.lead_id)
    titles = {group.id: group.title for group in snap.groups}
    ranking = sorted(
        leads_by_group, key=lambda group_id: len(leads_by_group[group_id]), reverse=True
    )
    assert [titles[group_id] for group_id in ranking[:5]] == TOP_GROUPS
    counts = [len(leads_by_group[group_id]) for group_id in ranking]
    for higher, lower in itertools.pairwise(counts[:6]):
        assert higher - lower >= 40  # 순위가 우연히 뒤집힐 만큼 가깝지 않다
    assert {titles[group_id] for group_id in ranking[5:7]} == {
        "프리랜서 디자이너 네트워크",
        "위탁판매 초보방",
    }
    # 가입된 그룹 대부분에서 수집이 있었다.
    assert len(leads_by_group) > 170


def test_seed_activity_buckets_sit_just_under_the_threshold(snap: Snapshot) -> None:
    groups = {group.id: group for group in snap.groups}
    totals: Counter[tuple[int, int]] = Counter()
    for bucket in snap.buckets:
        assert NOW - timedelta(hours=24) < bucket.hour <= NOW
        assert bucket.hour.minute == bucket.hour.second == 0 and bucket.count > 0
        totals[(bucket.group_id, bucket.tg_user_id)] += bucket.count
    assert len(totals) > 100
    user_ids = {lead.id: lead.tg_user_id for lead in snap.leads}
    recent_activity = {
        (hit.group_id, user_ids[hit.lead_id])
        for hit in snap.hits
        if hit.kind == RuleKind.ACTIVITY and hit.created_at > NOW - timedelta(hours=24)
    }
    for (group_id, tg_user_id), total in totals.items():
        group = groups[group_id]
        assert 12 <= total <= 29  # 몇 마디만 더 하면 30개를 넘는다
        assert group.status == GroupStatus.JOINED and group.account_id != GUNWOO
        assert group.tg_chat_id is not None
        assert tg_user_id in {user.id for user in demo_chat_cast(group.tg_chat_id).chatty}
        assert (group_id, tg_user_id) not in recent_activity


def test_seed_event_logs_read_like_real_operations(snap: Snapshot) -> None:
    assert 55 <= len(snap.logs) <= 65
    assert [log.created_at for log in snap.logs] == sorted(log.created_at for log in snap.logs)
    assert min(log.created_at for log in snap.logs) > NOW - timedelta(days=5)
    messages = [log.message for log in snap.logs]
    for expected in (
        "텔레그램에 연결됐어요.",
        "텔레그램과 연결이 끊겼어요. 곧 다시 연결해요.",
        "그룹에 들어갔어요.",
        "입장 요청을 보냈어요. 관리자가 승인하면 자동으로 가입돼요.",
        "입장 요청이 승인됐어요.",
        "텔레그램 요청 제한이 풀려서 다시 진행해요.",
        "그룹에 들어가지 못했어요. 초대 링크가 만료됐어요.",
        "세션이 만료됐어요. 다시 로그인해 주세요.",
    ):
        assert expected in messages, expected
    floods = [m for m in messages if m.startswith("텔레그램이 요청을 잠시 제한했어요.")]
    assert len(floods) == 2
    assert all(re.search(r"\d+분( \d+초)? 뒤\(\d\d:\d\d\)에 이어서 진행해요\.$", m) for m in floods)
    assert any(re.fullmatch(r"그룹 \d개를 가입 대기열에 넣었어요\.", m) for m in messages)
    assert {log.level for log in snap.logs} == set(LogLevel)
    for message in messages:
        assert message.endswith(("요.", "세요."))  # 해요체 한 문장

    account_ids = {account.id for account in snap.accounts}
    groups = {group.id: group for group in snap.groups}
    for log in snap.logs:
        assert log.account_id is None or log.account_id in account_ids
        if log.group_id is not None:
            group = groups[log.group_id]
            assert log.account_id == group.account_id
            if log.message == "그룹에 들어갔어요.":
                assert group.status == GroupStatus.JOINED and group.joined_at == log.created_at
    # 방금 걸린 요청 제한은 예린 계정의 것이고, 풀리는 시각이 계정에 적힌 시각과 같다.
    last = snap.logs[-1]
    assert last.account_id == YERIN and last.level == LogLevel.WARNING
    until = snap.accounts[YERIN - 1].flood_until
    assert until is not None and f"({until.astimezone(SEOUL):%H:%M})" in last.message
    assert "15분" in last.message and NOW - last.created_at == timedelta(minutes=1)
    # 건우 계정의 마지막 기록은 세션 만료다.
    gunwoo_logs = [log for log in snap.logs if log.account_id == GUNWOO]
    assert gunwoo_logs[-1].level == LogLevel.ERROR and "세션이 만료" in gunwoo_logs[-1].message


def test_seed_blocklist(snap: Snapshot) -> None:
    assert 2 <= len(snap.blocklist) <= 4
    speakers = {(u.username or "").lower() for u in demo_population(POOL_SIZE)}
    for entry in snap.blocklist:
        assert entry.username == entry.username.lower() and not entry.username.startswith("@")
        assert entry.note
    # 지금 그룹에서 말하는 사람도 하나 들어 있어서 제외 목록이 실제로 쓰인다.
    assert any(entry.username in speakers for entry in snap.blocklist)


async def test_seed_is_idempotent(seeded: tuple[AppContext, DemoGateway]) -> None:
    ctx, _ = seeded
    before = await table_counts(ctx)
    first = await load_snapshot(ctx)
    await ensure_demo_data(ctx, now=NOW)
    await ensure_demo_data(ctx, now=NOW + timedelta(days=3))
    assert await table_counts(ctx) == before
    assert before["Account"] == 10 and before["Lead"] == TOTAL_LEADS and before["Rule"] == 4
    again = await load_snapshot(ctx)
    assert [lead.last_hit_id for lead in again.leads] == [lead.last_hit_id for lead in first.leads]
    assert [a.flood_until for a in again.accounts] == [a.flood_until for a in first.accounts]


async def test_seed_is_the_same_for_the_same_moment(tmp_path: Path, snap: Snapshot) -> None:
    ctx, _ = await seed_into(tmp_path, NOW)
    try:
        other = await load_snapshot(ctx)
    finally:
        await ctx.db.dispose()
    assert [lead.username for lead in other.leads] == [lead.username for lead in snap.leads]
    assert [hit.excerpt for hit in other.hits] == [hit.excerpt for hit in snap.hits]
    assert [group.title for group in other.groups] == [group.title for group in snap.groups]


async def test_seed_just_after_midnight_keeps_today_in_the_past(tmp_path: Path) -> None:
    now = datetime(2026, 3, 1, 15, 7, tzinfo=UTC)  # 서울 기준 3월 2일 00:07
    ctx, _ = await seed_into(tmp_path, now)
    try:
        snapshot = await load_snapshot(ctx)
    finally:
        await ctx.db.dispose()
    assert max(hit.created_at for hit in snapshot.hits) <= now
    assert max(log.created_at for log in snapshot.logs) <= now
    midnight = now - timedelta(minutes=7)
    today = Counter(lead.first_kind for lead in snapshot.leads if lead.first_seen_at >= midnight)
    assert today == {
        RuleKind.KEYWORD: RECENT_KEYWORD_LEADS[-1],
        RuleKind.ACTIVITY: RECENT_ACTIVITY_LEADS[-1],
    }
    yesterday = Counter(
        lead.first_kind
        for lead in snapshot.leads
        if midnight - timedelta(days=1) <= lead.first_seen_at < midnight
    )
    assert yesterday == {
        RuleKind.KEYWORD: RECENT_KEYWORD_LEADS[-2],
        RuleKind.ACTIVITY: RECENT_ACTIVITY_LEADS[-2],
    }
    assert len(snapshot.leads) == TOTAL_LEADS
    for lead in snapshot.leads:
        assert lead.first_seen_at <= lead.last_seen_at <= now


async def test_seed_skips_when_accounts_are_gone_but_other_data_remains(
    seeded: tuple[AppContext, DemoGateway],
) -> None:
    ctx, _ = seeded
    async with ctx.db.session() as session:
        await session.execute(delete(Account))
        await session.commit()
    world = fast_gateway()
    ctx.engine.gateway = world

    await ensure_demo_data(ctx, now=NOW)  # 남은 데이터 위에 다시 채우지 않고, 오류도 내지 않는다

    counts = await table_counts(ctx)
    assert counts["Account"] == 0 and counts["Group"] == 0
    assert counts["Lead"] == TOTAL_LEADS and counts["Rule"] == 4
    assert all(world.chats_of(account_id) == () for account_id in range(1, 11))


async def test_seed_fills_the_database_even_without_a_demo_gateway(tmp_path: Path) -> None:
    ctx = build_context(demo_config(tmp_path), NullGateway())
    await ctx.db.create_all()
    try:
        await ensure_demo_data(ctx, now=NOW)
        assert (await table_counts(ctx))["Lead"] == TOTAL_LEADS
    finally:
        await ctx.db.dispose()


def test_demo_config_builds_a_demo_gateway(tmp_path: Path) -> None:
    ctx = build_context(demo_config(tmp_path))
    assert isinstance(ctx.engine.gateway, DemoGateway)


# ---------------------------------------------------------------------------
# 게이트웨이의 세계 채우기
# ---------------------------------------------------------------------------


async def test_world_holds_every_joined_group(seeded: tuple[AppContext, DemoGateway]) -> None:
    ctx, world = seeded
    snapshot = await load_snapshot(ctx)
    for account in snapshot.accounts:
        joined = [g for g in snapshot.joined() if g.account_id == account.id]
        chats = {room.id: room for room in world.chats_of(account.id)}
        for group in joined:
            room = chats[group.tg_chat_id]
            assert (room.title, room.kind, room.member_count) == (
                group.title,
                group.kind,
                group.member_count,
            )
            assert room.username == group.public_username
        # 감시 목록에 없는 방도 몇 개 들어가 있다('이미 들어가 있는 그룹 불러오기'에 나온다).
        extras = [room for room in chats.values() if room.id not in {g.tg_chat_id for g in joined}]
        assert len(extras) == 3
        assert any(room.kind == GroupKind.CHANNEL for room in extras)

    # 대화는 감시 중인 방에서 흐른다.
    monitored = {g.tg_chat_id for g in snapshot.joined() if g.account_id == 1}
    spoken = Counter(
        message.chat_id for message in (world.compose(1) for _ in range(2000)) if message
    )
    assert len(monitored & set(spoken)) == 20
    top = next(g for g in snapshot.joined() if g.title == TOP_GROUPS[0])
    assert spoken.most_common(1)[0][0] == top.tg_chat_id  # 가장 큰 방이 가장 시끄럽다


async def test_world_accounts_connect_as_themselves(seeded: tuple[AppContext, DemoGateway]) -> None:
    ctx, world = seeded
    snapshot = await load_snapshot(ctx)
    for account, session in zip(snapshot.accounts[:9], snapshot.sessions[:9], strict=True):
        assert session is not None
        me = await world.create_client(account.id, session).connect()
        assert (me.id, me.username, me.first_name, me.phone) == (
            account.tg_user_id,
            account.username,
            account.first_name,
            account.phone,
        )

    # 이미 들어가 있는 방의 링크로 가입을 시도하면 바로 JOINED 다.
    linked = next(g for g in snapshot.joined() if g.account_id == 1 and g.invite_hash)
    first = world.create_client(1, f"{SESSION_PREFIX}1")
    await first.connect()
    result = await first.join(LinkTarget(LinkKind.INVITE, linked.invite_hash))
    assert (
        result.outcome == JoinOutcome.JOINED and result.chat and result.chat.id == linked.tg_chat_id
    )


async def test_world_scripts_gunwoo_and_yerin(
    seeded: tuple[AppContext, DemoGateway], clock: TickClock
) -> None:
    _, world = seeded
    gunwoo = world.create_client(GUNWOO, EXPIRED_SESSION)
    await expect_error(gunwoo.connect(), TgErrorCode.SESSION_INVALID)

    yerin = world.create_client(YERIN, f"{SESSION_PREFIX}{YERIN}")
    await yerin.connect()  # 요청 제한 중에도 연결은 되고 메시지는 듣는다
    assert world.compose(YERIN) is not None
    flood = await expect_error(yerin.list_groups(), TgErrorCode.FLOOD_WAIT)
    assert flood.retry_after == FLOOD_WAIT_MINUTES * 60
    clock.advance(FLOOD_WAIT_MINUTES * 60)
    assert len(await yerin.list_groups()) == 23

    # 건우의 번호로 다시 로그인하면 같은 사람으로 새 세션을 받고, 그 세션은 접속된다.
    pending = await world.start_login("+821053162479")
    result = await world.submit_code(pending.login_id, DEMO_CODE)
    assert result.session and result.session != EXPIRED_SESSION
    assert result.user and result.user.first_name == "건우"
    assert await world.create_client(GUNWOO, result.session).connect() == result.user


async def test_world_join_requests(
    seeded: tuple[AppContext, DemoGateway], clock: TickClock
) -> None:
    ctx, world = seeded
    snapshot = await load_snapshot(ctx)
    requested = [g for g in snapshot.groups if g.status == GroupStatus.REQUESTED]
    live = [g for g in requested if g.account_id != GUNWOO]
    assert len(live) == 3
    approved: list[Group] = []
    clock.advance(FLOOD_WAIT_MINUTES * 60 + 3600)
    for group in live:
        connection = world.create_client(group.account_id, f"{SESSION_PREFIX}{group.account_id}")
        await connection.connect()
        assert group.invite_hash is not None
        target = LinkTarget(LinkKind.INVITE, group.invite_hash)
        assert (await connection.join(target)).outcome in (
            JoinOutcome.REQUESTED,
            JoinOutcome.JOINED,
        )
        room = await connection.find_membership(target, group.tg_chat_id)
        if room is not None:
            approved.append(group)
            assert room.title == group.title and room.member_count == group.member_count
            assert room in await connection.list_groups()
    assert len(approved) == 1 and approved[0].invite_hash not in HELD_REQUESTS


async def test_world_is_rebuilt_after_a_restart(tmp_path: Path) -> None:
    ctx, _ = await seed_into(tmp_path, NOW)
    counts = await table_counts(ctx)
    await ctx.db.dispose()

    # 5분 뒤에 다시 켠다: 다시 채우지 않고, 같은 세계가 올라온다.
    later = TickClock(NOW + timedelta(minutes=5))
    world = fast_gateway(later)
    ctx = build_context(demo_config(tmp_path), world)
    await ctx.db.create_all()
    try:
        await ensure_demo_data(ctx, now=later.now)
        assert await table_counts(ctx) == counts
        assert [len(world.chats_of(n)) for n in range(1, 11)] == [n + 3 for n in JOINED_PER_ACCOUNT]

        await expect_error(
            world.create_client(GUNWOO, EXPIRED_SESSION).connect(), TgErrorCode.SESSION_INVALID
        )
        yerin = world.create_client(YERIN, f"{SESSION_PREFIX}{YERIN}")
        assert (await yerin.connect()).first_name == "예린"
        flood = await expect_error(yerin.list_groups(), TgErrorCode.FLOOD_WAIT)
        assert flood.retry_after == (FLOOD_WAIT_MINUTES - 5) * 60  # 남은 만큼만 다시 건다
    finally:
        await world.close()
        await ctx.db.dispose()

    # 한 시간 뒤에 다시 켜면 요청 제한은 이미 풀려 있다.
    much_later = TickClock(NOW + timedelta(hours=1))
    world = fast_gateway(much_later)
    ctx = build_context(demo_config(tmp_path), world)
    try:
        await ensure_demo_data(ctx, now=much_later.now)
        yerin = world.create_client(YERIN, f"{SESSION_PREFIX}{YERIN}")
        await yerin.connect()
        assert len(await yerin.list_groups()) == 23
    finally:
        await world.close()
        await ctx.db.dispose()


# ---------------------------------------------------------------------------
# 앱 전체: 데모 게이트웨이 위에서 실제 엔진과 수집기를 돌린다
# ---------------------------------------------------------------------------


def live_app(data_dir: Path, **gateway_options: object):
    world = DemoGateway(pace=(0.02, 0.05), join_delay=(0.0, 0.02), seed=3, **gateway_options)  # type: ignore[arg-type]
    return create_app(demo_config(data_dir, engine_enabled=True), gateway=world)


async def hit_count(ctx: AppContext) -> int:
    async with ctx.db.session() as session:
        return await session.scalar(select(func.count()).select_from(Hit)) or 0


async def account_statuses(ctx: AppContext) -> dict[str, str]:
    async with ctx.db.session() as session:
        rows = await session.execute(select(Account.first_name, Account.status))
        return {name: status for name, status in rows}


async def test_full_app_collects_live_traffic_and_shuts_down_cleanly(tmp_path: Path) -> None:
    app = live_app(tmp_path)
    ctx: AppContext = app.state.ctx
    async with app.router.lifespan_context(app):
        seeded_hits = await hit_count(ctx)
        assert seeded_hits > TOTAL_LEADS

        async with ctx.bus.subscribe() as events:

            async def new_hits() -> bool:
                return await hit_count(ctx) >= seeded_hits + 5

            started = time.monotonic()
            await wait_until(new_hits, within=6, what="새 감지 5건")
            assert time.monotonic() - started < 4  # 몇 초 안에 새 감지가 생긴다
            live_events = []
            while not events.empty():
                live_events.append(events.get_nowait())
        hit_events = [event.data for event in live_events if event.type == "hit"]
        assert hit_events and all(event["username"] for event in hit_events)

        async def settled() -> bool:
            statuses = await account_statuses(ctx)
            connected = sum(ctx.engine.is_connected(n) for n in range(1, 11))
            return connected == 9 and AccountStatus.CONNECTING not in statuses.values()

        await wait_until(settled, what="계정 연결")
        statuses = await account_statuses(ctx)
        assert statuses.pop("예린") == AccountStatus.FLOOD_WAIT
        assert statuses.pop("건우") == AccountStatus.REAUTH_REQUIRED
        assert set(statuses.values()) == {AccountStatus.ACTIVE} and len(statuses) == 8
        assert [ctx.engine.is_connected(n) for n in range(1, 11)] == [True] * 9 + [False]

        # 활동량 규칙도 걸린다(기준 바로 아래까지 말해 둔 사람들이 몇 마디 더 한다).
        async def activity_hit() -> bool:
            await ctx.collector.flush()
            async with ctx.db.session() as session:
                found = await session.scalar(
                    select(Hit.id)
                    .where(Hit.id > seeded_hits, Hit.kind == RuleKind.ACTIVITY)
                    .limit(1)
                )
            return found is not None

        await wait_until(activity_hit, within=10, what="활동량 감지")

        async with ctx.db.session() as session:
            fresh = (await session.scalars(select(Hit).where(Hit.id > seeded_hits))).all()
            leads = {lead.id: lead for lead in (await session.scalars(select(Lead))).all()}
            blocked = set((await session.scalars(select(BlocklistEntry.username))).all())
        people = {user.id: user for user in demo_population(POOL_SIZE)}
        for hit in fresh:
            lead = leads[hit.lead_id]
            person = people[lead.tg_user_id]  # 말하는 사람은 모두 데모 세계의 사람이다
            # 아이디 없는 사람과 봇은 건너뛴다.
            assert person.username == lead.username and not person.is_bot
            assert lead.status != LeadStatus.EXCLUDED and lead.username.lower() not in blocked
            assert hit.account_id not in (None, GUNWOO)
            if hit.kind == RuleKind.KEYWORD:
                assert hit.excerpt and hit.keywords
        assert len(leads) > TOTAL_LEADS  # 처음 보는 사람도 수집된다

    assert other_tasks() == set()  # 남은 태스크 없이 내려간다

    # 내려간 뒤: 연결돼 있던 계정은 '꺼짐', 요청 제한과 다시 로그인은 그대로 남는다.
    reopened = build_context(demo_config(tmp_path), fast_gateway())
    try:
        statuses = await account_statuses(reopened)
        assert statuses.pop("예린") == AccountStatus.FLOOD_WAIT
        assert statuses.pop("건우") == AccountStatus.REAUTH_REQUIRED
        assert set(statuses.values()) == {AccountStatus.OFFLINE}
        async with reopened.db.session() as session:
            seen = (await session.scalars(select(Group.messages_seen).order_by(Group.id))).all()
            logs = (await session.scalars(select(EventLog.message))).all()
        assert sum(seen) > 0
        assert logs.count("텔레그램에 연결됐어요.") >= 9 + 18  # 지난 기록 18건에 이번 연결 9건
    finally:
        await reopened.db.dispose()


async def test_full_app_with_the_default_gateway_starts_and_stops(tmp_path: Path) -> None:
    app = create_app(demo_config(tmp_path, engine_enabled=True))
    ctx: AppContext = app.state.ctx
    assert isinstance(ctx.engine.gateway, DemoGateway)
    async with app.router.lifespan_context(app):

        async def connected() -> bool:
            return sum(ctx.engine.is_connected(n) for n in range(1, 11)) == 9

        await wait_until(connected, what="계정 9개 연결")
    assert other_tasks() == set()


async def test_full_app_joins_groups_through_the_engine(tmp_path: Path) -> None:
    app = live_app(tmp_path)
    ctx: AppContext = app.state.ctx
    joins = link_with(JoinPlanKind.JOINED)
    asks = link_with(JoinPlanKind.REQUESTED)
    expires = link_with(JoinPlanKind.EXPIRED)
    async with app.router.lifespan_context(app):
        # 자리가 있는 계정(하늘 5, 준서 8, 건우 10)에 링크를 하나씩 넣는다.
        async with ctx.db.session() as session:
            rows = [
                Group(
                    account_id=account_id,
                    source_link=target.canonical_url,
                    link_kind=LinkKind.INVITE,
                    invite_hash=target.value,
                    status=GroupStatus.QUEUED,
                )
                for account_id, target in ((5, joins), (8, asks), (GUNWOO, expires))
            ]
            session.add_all(rows)
            await session.commit()
            joined_id, asked_id, expired_id = (row.id for row in rows)
        ctx.engine.notify_groups_changed()

        async def group(group_id: int) -> Group:
            async with ctx.db.session() as session:
                found = await session.get(Group, group_id)
                assert found is not None
                return found

        async def processed() -> bool:
            return (await group(joined_id)).status == GroupStatus.JOINED and (
                await group(asked_id)
            ).status == GroupStatus.REQUESTED

        await wait_until(processed, what="가입과 입장 요청")
        joined, asked = await group(joined_id), await group(asked_id)
        plan = demo_join_plan(joins)
        assert joined.tg_chat_id == plan.chat.id and joined.kind == GroupKind.SUPERGROUP
        assert joined.member_count == plan.chat.member_count and joined.joined_at is not None
        assert asked.member_count == demo_join_plan(asks).chat.member_count
        assert asked.tg_chat_id is None and asked.status_detail == engine._DETAIL_REQUESTED
        assert {joined.title, asked.title} < set(demo_gateway._NEW_GROUP_TITLES)

        # 새로 들어간 방에서도 메시지가 들어온다.
        async def heard() -> bool:
            await ctx.collector.flush()
            return (await group(joined_id)).messages_seen > 0

        await wait_until(heard, what="새 그룹의 메시지")

        # 건우 계정은 세션이 만료돼 있어서 대기열이 그대로다. 그 번호로 다시 로그인하면 풀린다.
        assert (await group(expired_id)).status == GroupStatus.QUEUED
        pending = await ctx.engine.start_login("+82 10-5316-2479")
        result, account = await ctx.engine.submit_code(pending.login_id, DEMO_CODE)
        assert result.status == "done" and account is not None and account.id == GUNWOO

        async def recovered() -> bool:
            return ctx.engine.is_connected(GUNWOO)

        await wait_until(recovered, what="건우 계정 다시 연결")
        assert (await account_statuses(ctx))["건우"] == AccountStatus.ACTIVE

        async def queue_moved() -> bool:
            async with ctx.db.session() as session:
                statuses = (
                    await session.scalars(
                        select(Group.status).where(
                            Group.account_id == GUNWOO,
                            Group.public_username == demo_seed._QUEUED_PUBLIC_LINK.value,
                        )
                    )
                ).all()
            return statuses == [GroupStatus.JOINED]

        await wait_until(queue_moved, what="건우 계정의 대기열 처리")

        # 새 번호로 로그인하면 계정이 하나 더 생기고 바로 연결된다.
        pending = await ctx.engine.start_login("010-7777-8888")
        result, added = await ctx.engine.submit_code(pending.login_id, DEMO_CODE)
        assert result.status == "done" and added is not None and added.id == 11
        assert added.phone == "+821077778888" and added.first_name

        async def added_connected() -> bool:
            return ctx.engine.is_connected(11)

        await wait_until(added_connected, what="새 계정 연결")
    assert other_tasks() == set()

    # 다시 켜도 새로 받은 세션들은 그대로 쓸 수 있다.
    world = fast_gateway()
    ctx = build_context(demo_config(tmp_path), world)
    try:
        await ensure_demo_data(ctx)
        snapshot = await load_snapshot(ctx)
        assert len(snapshot.accounts) == 11
        for account, session in zip(snapshot.accounts, snapshot.sessions, strict=True):
            assert session is not None and session != EXPIRED_SESSION
            me = await world.create_client(account.id, session).connect()
            assert (me.id, me.first_name) == (account.tg_user_id, account.first_name)
        assert plan.chat.id in {room.id for room in world.chats_of(5)}
    finally:
        await world.close()
        await ctx.db.dispose()
