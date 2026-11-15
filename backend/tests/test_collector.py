"""수집기 테스트. 임시 SQLite 파일과 실제 EventBus·SettingsStore·Logbook 으로 돌린다."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import Config
from app.db import Database
from app.events import Event, EventBus
from app.models import (
    Account,
    ActivityBucket,
    BlocklistEntry,
    EventLog,
    Group,
    GroupKind,
    GroupStatus,
    Hit,
    Lead,
    LeadStatus,
    LogCategory,
    LogLevel,
    MatchMode,
    Rule,
    RuleKind,
)
from app.security import Secrets
from app.services import collector as collector_module
from app.services.collector import Collector
from app.services.logbook import Logbook
from app.settings_store import SettingsStore
from app.telegram.gateway import IncomingMessage, TgUser

START = datetime(2026, 3, 10, 12, 30, tzinfo=UTC)
OWN_TG_ID = 9001
CHAT = -1001000000001
OTHER_CHAT = -1001000000002

ALICE = TgUser(id=101, username="alice_kim", first_name="앨리스", last_name="김")
BOB = TgUser(id=102, username="bob_lee", first_name="밥")


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@dataclass
class Env:
    db: Database
    bus: EventBus
    settings: SettingsStore
    logbook: Logbook
    clock: FakeClock
    collector: Collector
    queue: asyncio.Queue[Event]
    account_id: int = 0
    group_id: int = 0
    _message_ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))

    # --- 준비 ---------------------------------------------------------------

    async def add_account(self, tg_user_id: int | None) -> int:
        async with self.db.session() as session:
            account = Account(tg_user_id=tg_user_id)
            session.add(account)
            await session.commit()
            return account.id

    async def add_group(
        self,
        account_id: int,
        chat_id: int | None,
        *,
        title: str | None = "테스트 그룹",
        public_username: str | None = None,
    ) -> int:
        async with self.db.session() as session:
            group = Group(
                account_id=account_id,
                tg_chat_id=chat_id,
                title=title,
                public_username=public_username,
                kind=GroupKind.SUPERGROUP,
                status=GroupStatus.JOINED,
            )
            session.add(group)
            await session.commit()
            return group.id

    async def _add_rule(self, rule: Rule, group_ids: Sequence[int] | None) -> int:
        async with self.db.session() as session:
            rule.all_groups = group_ids is None
            if group_ids:
                rule.groups = list(
                    (await session.scalars(select(Group).where(Group.id.in_(group_ids)))).all()
                )
            session.add(rule)
            await session.commit()
            return rule.id

    async def add_keyword_rule(
        self,
        keywords: Sequence[str],
        *,
        name: str = "키워드 규칙",
        exclude: Sequence[str] = (),
        mode: MatchMode = MatchMode.ANY,
        enabled: bool = True,
        group_ids: Sequence[int] | None = None,
    ) -> int:
        rule = Rule(
            name=name,
            kind=RuleKind.KEYWORD,
            enabled=enabled,
            keywords=list(keywords),
            exclude_keywords=list(exclude),
            match_mode=mode,
        )
        return await self._add_rule(rule, group_ids)

    async def add_activity_rule(
        self,
        min_messages: int,
        window_hours: int,
        *,
        name: str = "활동량 규칙",
        enabled: bool = True,
        group_ids: Sequence[int] | None = None,
    ) -> int:
        rule = Rule(
            name=name,
            kind=RuleKind.ACTIVITY,
            enabled=enabled,
            min_messages=min_messages,
            window_hours=window_hours,
        )
        return await self._add_rule(rule, group_ids)

    async def add_blocklist(self, username: str) -> None:
        async with self.db.session() as session:
            session.add(BlocklistEntry(username=username))
            await session.commit()

    async def add_lead(self, user: TgUser, status: LeadStatus) -> int:
        async with self.db.session() as session:
            lead = Lead(
                tg_user_id=user.id,
                username=user.username or "",
                status=status,
                first_kind=RuleKind.KEYWORD,
            )
            session.add(lead)
            await session.commit()
            return lead.id

    def message(
        self,
        text: str,
        *,
        sender: TgUser | None = ALICE,
        chat_id: int = CHAT,
        account_id: int | None = None,
        message_id: int | None = None,
        date: datetime | None = None,
    ) -> IncomingMessage:
        return IncomingMessage(
            account_id=account_id if account_id is not None else self.account_id,
            chat_id=chat_id,
            message_id=message_id if message_id is not None else next(self._message_ids),
            sender=sender,
            text=text,
            date=date or self.clock.now,
        )

    async def say(self, text: str, *, group_id: int | None = None, **kwargs: Any) -> None:
        """기본 그룹(또는 group_id)에 메시지 하나를 흘려보낸다."""
        await self.collector.handle(
            self.message(text, **kwargs), group_id if group_id is not None else self.group_id
        )

    # --- 확인 ---------------------------------------------------------------

    def hit_events(self) -> list[dict[str, Any]]:
        """지금까지 버스에 나온 hit 이벤트를 꺼낸다."""
        events: list[dict[str, Any]] = []
        while True:
            try:
                event = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return events
            if event.type == "hit":
                events.append(event.data)

    async def leads(self) -> list[Lead]:
        async with self.db.session() as session:
            return list((await session.scalars(select(Lead).order_by(Lead.id))).all())

    async def hits(self) -> list[Hit]:
        async with self.db.session() as session:
            return list((await session.scalars(select(Hit).order_by(Hit.id))).all())

    async def buckets(self) -> list[ActivityBucket]:
        async with self.db.session() as session:
            query = select(ActivityBucket).order_by(
                ActivityBucket.group_id, ActivityBucket.tg_user_id, ActivityBucket.hour
            )
            return list((await session.scalars(query)).all())

    async def group(self, group_id: int | None = None) -> Group:
        async with self.db.session() as session:
            group = await session.get(Group, group_id if group_id is not None else self.group_id)
            assert group is not None
            return group

    async def logs(self) -> list[EventLog]:
        async with self.db.session() as session:
            return list((await session.scalars(select(EventLog).order_by(EventLog.id))).all())


def make_collector(env: Env, **kwargs: Any) -> Collector:
    return Collector(
        db=env.db,
        bus=env.bus,
        settings=env.settings,
        logbook=env.logbook,
        clock=env.clock,
        **kwargs,
    )


@pytest_asyncio.fixture
async def env(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'collector.sqlite3'}")
    await db.create_all()
    bus = EventBus()
    config = Config(_env_file=None, data_dir=tmp_path, secret_key="test-secret-key")
    settings = SettingsStore(db, Secrets("test-secret-key", 3600), config)
    logbook = Logbook(db, bus)
    clock = FakeClock(START)
    collector = Collector(db=db, bus=bus, settings=settings, logbook=logbook, clock=clock)
    async with bus.subscribe() as queue:
        environment = Env(db, bus, settings, logbook, clock, collector, queue)
        environment.account_id = await environment.add_account(OWN_TG_ID)
        environment.group_id = await environment.add_group(environment.account_id, CHAT)
        try:
            yield environment
        finally:
            await collector.stop()
            await db.dispose()


# ---------------------------------------------------------------------------
# 키워드 감지
# ---------------------------------------------------------------------------


async def test_keyword_hit_creates_lead_hit_and_event(env: Env) -> None:
    rule_id = await env.add_keyword_rule(["업체 추천"], name="업체 문의")
    message = env.message("혹시 괜찮은 업체추천 좀 해주실 분?")

    await env.collector.handle(message, env.group_id)

    [lead] = await env.leads()
    [hit] = await env.hits()
    assert (lead.tg_user_id, lead.username) == (ALICE.id, "alice_kim")
    assert (lead.first_name, lead.last_name) == ("앨리스", "김")
    assert lead.status == LeadStatus.NEW
    assert lead.hit_count == 1
    assert lead.first_kind == RuleKind.KEYWORD
    assert lead.first_seen_at == START
    assert lead.last_seen_at == START
    assert lead.last_hit_id == hit.id

    assert hit.lead_id == lead.id
    assert (hit.rule_id, hit.group_id, hit.account_id) == (rule_id, env.group_id, env.account_id)
    assert hit.kind == RuleKind.KEYWORD
    assert hit.rule_name == "업체 문의"
    assert hit.group_title == "테스트 그룹"
    assert hit.keywords == ["업체 추천"]
    assert hit.excerpt == "혹시 괜찮은 업체추천 좀 해주실 분?"
    assert hit.tg_message_id == message.message_id
    assert (hit.message_count, hit.window_hours) == (None, None)
    assert hit.created_at == START

    [event] = env.hit_events()
    assert event == {
        "hit_id": hit.id,
        "created_at": event["created_at"],
        "kind": "keyword",
        "rule_id": rule_id,
        "rule_name": "업체 문의",
        "group_id": env.group_id,
        "group_title": "테스트 그룹",
        "keywords": ["업체 추천"],
        "excerpt": "혹시 괜찮은 업체추천 좀 해주실 분?",
        "message_count": None,
        "window_hours": None,
        "lead_id": lead.id,
        "username": "alice_kim",
        "display_name": "앨리스 김",
        "is_new_lead": True,
    }
    assert datetime.fromisoformat(event["created_at"]) == START


async def test_message_without_keyword_records_nothing(env: Env) -> None:
    await env.add_keyword_rule(["추천"])

    await env.say("안녕하세요 반갑습니다")

    assert await env.leads() == []
    assert await env.hits() == []
    assert env.hit_events() == []


async def test_second_hit_reuses_lead_and_moves_last_hit_pointer(env: Env) -> None:
    await env.add_keyword_rule(["추천"])
    await env.say("추천 부탁드려요")
    env.clock.advance(minutes=10)

    await env.say("다른 곳도 추천해 주세요")

    [lead] = await env.leads()
    first, second = await env.hits()
    assert lead.hit_count == 2
    assert lead.first_seen_at == START
    assert lead.last_seen_at == START + timedelta(minutes=10)
    assert lead.last_hit_id == second.id != first.id
    assert [event["is_new_lead"] for event in env.hit_events()] == [True, False]


async def test_one_message_can_hit_several_rules(env: Env) -> None:
    first_rule = await env.add_keyword_rule(["추천"], name="추천 문의")
    second_rule = await env.add_keyword_rule(["견적", "가격"], name="가격 문의")
    await env.add_keyword_rule(["환불"], name="환불 문의")

    await env.say("추천도 받고 싶고 가격도 궁금해요")

    [lead] = await env.leads()
    hits = await env.hits()
    assert [(hit.rule_id, hit.rule_name, hit.keywords) for hit in hits] == [
        (first_rule, "추천 문의", ["추천"]),
        (second_rule, "가격 문의", ["가격"]),
    ]
    assert lead.hit_count == 2
    assert lead.last_hit_id == hits[-1].id
    assert [event["is_new_lead"] for event in env.hit_events()] == [True, False]


@pytest.mark.parametrize(
    "sender",
    [
        None,
        TgUser(id=501, username=None, first_name="아이디없음"),
        TgUser(id=502, username=""),
        TgUser(id=503, username="helper_bot", is_bot=True),
        TgUser(id=OWN_TG_ID, username="my_other_account"),
        TgUser(id=504, username="SpamMer"),
        TgUser(id=505, username="excluded_user"),
    ],
    ids=[
        "anonymous",
        "no-username",
        "empty-username",
        "bot",
        "own-account",
        "blocklist",
        "excluded",
    ],
)
async def test_ignored_senders_are_counted_but_never_collected(
    env: Env, sender: TgUser | None
) -> None:
    await env.add_keyword_rule(["추천"])
    await env.add_activity_rule(min_messages=2, window_hours=1)
    await env.add_blocklist("spammer")
    await env.add_lead(TgUser(id=505, username="excluded_user"), LeadStatus.EXCLUDED)

    for _ in range(3):
        await env.say("추천 부탁드려요", sender=sender)
    await env.collector.flush()

    assert await env.hits() == []
    assert env.hit_events() == []
    assert await env.buckets() == []
    assert [lead.hit_count for lead in await env.leads()] == [0]
    assert (await env.group()).messages_seen == 3


async def test_duplicate_message_from_two_accounts_is_counted_once(env: Env) -> None:
    second_account = await env.add_account(9002)
    second_group = await env.add_group(second_account, CHAT)
    await env.add_keyword_rule(["추천"])
    await env.add_activity_rule(min_messages=5, window_hours=1)

    await env.say("추천 부탁드려요", message_id=77)
    await env.say(
        "추천 부탁드려요", message_id=77, account_id=second_account, group_id=second_group
    )
    await env.collector.flush()

    [hit] = await env.hits()
    assert (hit.group_id, hit.account_id) == (env.group_id, env.account_id)
    assert len(env.hit_events()) == 1
    assert [(b.group_id, b.count) for b in await env.buckets()] == [(env.group_id, 1)]
    assert (await env.group()).messages_seen == 1
    assert (await env.group(second_group)).messages_seen == 0


async def test_same_message_id_in_another_chat_is_not_a_duplicate(env: Env) -> None:
    other_group = await env.add_group(env.account_id, OTHER_CHAT, title="다른 그룹")
    await env.add_keyword_rule(["추천"])

    await env.say("추천 부탁드려요", message_id=77)
    await env.say("추천 부탁드려요", message_id=77, chat_id=OTHER_CHAT, group_id=other_group)

    assert [hit.group_id for hit in await env.hits()] == [env.group_id, other_group]


async def test_rule_with_selected_groups_only_applies_there(env: Env) -> None:
    other_group = await env.add_group(env.account_id, OTHER_CHAT, title="다른 그룹")
    await env.add_keyword_rule(["추천"], group_ids=[other_group])
    await env.add_activity_rule(min_messages=2, window_hours=1, group_ids=[other_group])

    for _ in range(2):
        await env.say("추천 부탁드려요")
    await env.collector.flush()
    assert await env.hits() == []
    assert await env.buckets() == []

    await env.say("추천 부탁드려요", chat_id=OTHER_CHAT, group_id=other_group)
    [hit] = await env.hits()
    assert (hit.group_id, hit.group_title) == (other_group, "다른 그룹")


async def test_selected_group_rule_follows_the_chat_across_my_accounts(env: Env) -> None:
    # 규칙은 첫 계정의 그룹 행에만 걸려 있지만, 같은 방의 메시지가 둘째 계정으로 먼저 올 수 있다.
    second_account = await env.add_account(9002)
    second_group = await env.add_group(second_account, CHAT)
    await env.add_keyword_rule(["추천"], group_ids=[env.group_id])

    await env.say("추천 부탁드려요", account_id=second_account, group_id=second_group)

    [hit] = await env.hits()
    assert (hit.group_id, hit.account_id) == (second_group, second_account)


async def test_disabled_rules_do_nothing(env: Env) -> None:
    await env.add_keyword_rule(["추천"], enabled=False)
    await env.add_activity_rule(min_messages=2, window_hours=1, enabled=False)

    for _ in range(3):
        await env.say("추천 부탁드려요")
    await env.collector.flush()

    assert await env.leads() == []
    assert await env.buckets() == []


async def test_exclude_keywords_block_the_hit(env: Env) -> None:
    await env.add_keyword_rule(["대출"], exclude=["광고", "홍보"])

    await env.say("대출 광고 아닙니다 연락주세요")
    assert await env.hits() == []

    await env.say("대출 상담 받을 수 있을까요", sender=BOB)
    [hit] = await env.hits()
    assert hit.keywords == ["대출"]


async def test_match_mode_all_needs_every_keyword(env: Env) -> None:
    await env.add_keyword_rule(["서울", "매매"], mode=MatchMode.ALL)

    await env.say("서울 전세 구합니다")
    assert await env.hits() == []

    await env.say("서울 아파트 매매 알아보는 중입니다", sender=BOB)
    [hit] = await env.hits()
    assert hit.keywords == ["서울", "매매"]


async def test_excerpt_follows_the_store_excerpts_setting(env: Env) -> None:
    await env.add_keyword_rule(["추천"])

    await env.say("추천 부탁드려요")
    # 설정은 invalidate() 없이도 바로 반영된다.
    await env.settings.update(store_excerpts=False)
    await env.say("저도 추천 부탁드려요", sender=BOB)

    stored, hidden = await env.hits()
    assert stored.excerpt == "추천 부탁드려요"
    assert hidden.excerpt is None
    assert hidden.keywords == ["추천"]
    assert [event["excerpt"] for event in env.hit_events()] == ["추천 부탁드려요", None]


async def test_long_message_is_stored_as_short_excerpt_around_keyword(env: Env) -> None:
    await env.add_keyword_rule(["업체 추천"])
    text = "잡담 " * 200 + "믿을 만한 업체추천 부탁드립니다 " + "감사합니다 " * 100

    await env.say(text)

    [hit] = await env.hits()
    assert hit.excerpt is not None
    assert len(hit.excerpt) <= 202
    assert "업체추천" in hit.excerpt
    assert hit.excerpt.startswith("…") and hit.excerpt.endswith("…")


async def test_cooldown_skips_repeat_hits_for_five_minutes(env: Env) -> None:
    await env.add_keyword_rule(["추천"])

    await env.say("추천 부탁드려요")
    env.clock.advance(minutes=4, seconds=59)
    await env.say("추천 좀요")
    assert len(await env.hits()) == 1

    env.clock.advance(seconds=1)
    await env.say("추천 진짜 부탁드려요")

    [lead] = await env.leads()
    assert lead.hit_count == 2
    assert [hit.created_at for hit in await env.hits()] == [START, START + timedelta(minutes=5)]


async def test_cooldown_is_per_user_rule_and_group(env: Env) -> None:
    other_group = await env.add_group(env.account_id, OTHER_CHAT, title="다른 그룹")
    first_rule = await env.add_keyword_rule(["추천"], name="추천")
    second_rule = await env.add_keyword_rule(["견적"], name="견적")

    await env.say("추천 부탁드려요")
    env.clock.advance(minutes=1)
    await env.say("추천 부탁드려요")  # 같은 유저·규칙·그룹 → 건너뜀
    await env.say("추천 부탁드려요", sender=BOB)  # 다른 유저
    await env.say("견적 부탁드려요")  # 다른 규칙
    await env.say("추천 부탁드려요", chat_id=OTHER_CHAT, group_id=other_group)  # 다른 그룹

    assert [(hit.rule_id, hit.group_id, hit.lead_id) for hit in await env.hits()] == [
        (first_rule, env.group_id, 1),
        (first_rule, env.group_id, 2),
        (second_rule, env.group_id, 1),
        (first_rule, other_group, 1),
    ]


async def test_cooldown_table_is_bounded(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collector_module, "COOLDOWN_LIMIT", 2)
    await env.add_keyword_rule(["추천"])
    carol = TgUser(id=103, username="carol_park")

    for sender in (ALICE, BOB, carol):
        await env.say("추천 부탁드려요", sender=sender)
    # 가장 오래된 앨리스의 기록이 밀려나서 다시 잡힌다. 방금 잡힌 캐럴은 아직 대기 시간 안이다.
    await env.say("추천 부탁드려요", sender=ALICE)
    await env.say("추천 부탁드려요", sender=carol)

    assert [lead.hit_count for lead in await env.leads()] == [2, 1, 1]


async def test_seen_message_table_is_bounded(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collector_module, "SEEN_MESSAGES_LIMIT", 3)

    for message_id in (1, 2, 3, 4):
        await env.say("안녕하세요", message_id=message_id)
    await env.say("안녕하세요", message_id=4)  # 아직 기억하고 있다 → 중복
    await env.say("안녕하세요", message_id=1)  # 밀려났다 → 새 메시지로 센다
    await env.collector.flush()

    assert (await env.group()).messages_seen == 5


async def test_username_change_updates_the_lead(env: Env) -> None:
    await env.add_keyword_rule(["추천"])
    await env.say("추천 부탁드려요")
    env.clock.advance(minutes=10)
    renamed = TgUser(id=ALICE.id, username="alice_new", first_name="Alice", last_name=None)

    await env.say("추천 부탁드려요", sender=renamed)

    [lead] = await env.leads()
    assert (lead.username, lead.first_name, lead.last_name) == ("alice_new", "Alice", None)
    assert lead.hit_count == 2
    assert [event["username"] for event in env.hit_events()] == ["alice_kim", "alice_new"]


async def test_hit_keeps_display_title_when_group_has_no_title(env: Env) -> None:
    untitled = await env.add_group(
        env.account_id, OTHER_CHAT, title=None, public_username="seoul_market"
    )
    await env.add_keyword_rule(["추천"])

    await env.say("추천 부탁드려요", chat_id=OTHER_CHAT, group_id=untitled)

    [hit] = await env.hits()
    assert hit.group_title == "@seoul_market"


async def test_hit_from_unknown_account_is_kept_without_account(env: Env) -> None:
    await env.add_keyword_rule(["추천"])

    await env.say("추천 부탁드려요", account_id=999)

    [hit] = await env.hits()
    assert (hit.group_id, hit.account_id) == (env.group_id, None)


# ---------------------------------------------------------------------------
# 캐시
# ---------------------------------------------------------------------------


async def test_invalidate_picks_up_new_rules(env: Env) -> None:
    await env.say("추천 부탁드려요")  # 규칙이 없는 상태로 캐시가 만들어진다
    await env.add_keyword_rule(["추천"])

    await env.say("추천 부탁드려요")
    assert await env.hits() == []

    env.collector.invalidate()
    await env.say("추천 부탁드려요")
    assert len(await env.hits()) == 1


async def test_invalidate_picks_up_blocklist_and_excluded_leads(env: Env) -> None:
    await env.add_keyword_rule(["추천"])
    await env.say("추천 부탁드려요")
    await env.add_blocklist("bob_lee")
    async with env.db.session() as session:
        lead = (await session.scalars(select(Lead))).one()
        lead.status = LeadStatus.EXCLUDED
        await session.commit()
    env.collector.invalidate()
    env.clock.advance(minutes=10)

    await env.say("추천 부탁드려요")
    await env.say("추천 부탁드려요", sender=BOB)

    [lead] = await env.leads()
    assert lead.hit_count == 1
    assert len(await env.hits()) == 1


async def test_excluded_lead_is_not_recorded_even_with_stale_cache(env: Env) -> None:
    await env.add_keyword_rule(["추천"])
    await env.say("추천 부탁드려요")
    async with env.db.session() as session:
        lead = (await session.scalars(select(Lead))).one()
        lead.status = LeadStatus.EXCLUDED
        await session.commit()
    env.clock.advance(minutes=10)

    await env.say("추천 부탁드려요")  # invalidate() 가 아직 안 불린 상태

    [lead] = await env.leads()
    assert lead.hit_count == 1
    assert len(await env.hits()) == 1


async def test_rule_deleted_behind_the_cache_is_skipped_quietly(env: Env) -> None:
    rule_id = await env.add_keyword_rule(["추천"])
    await env.say("안녕하세요")  # 캐시를 채운다
    async with env.db.session() as session:
        await session.delete(await session.get(Rule, rule_id))
        await session.commit()

    await env.say("추천 부탁드려요")

    assert await env.leads() == []
    assert await env.logs() == []


async def test_rule_disabled_behind_the_cache_is_skipped_quietly(env: Env) -> None:
    keyword_rule = await env.add_keyword_rule(["추천"])
    activity_rule = await env.add_activity_rule(min_messages=2, window_hours=1)
    await env.say("안녕하세요")  # 캐시를 채운다
    async with env.db.session() as session:
        for rule_id in (keyword_rule, activity_rule):
            rule = await session.get(Rule, rule_id)
            assert rule is not None
            rule.enabled = False
        await session.commit()

    await env.say("추천 부탁드려요")
    await env.collector.flush()

    assert await env.leads() == []
    assert await env.logs() == []


async def test_invalidate_during_a_reload_is_not_lost(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = env.collector._load_snapshot

    async def racing() -> Any:
        snapshot = await original()
        # 캐시를 읽은 직후에 규칙이 생기고 invalidate() 가 불린 상황
        await env.add_keyword_rule(["견적"])
        env.collector.invalidate()
        return snapshot

    with monkeypatch.context() as patch:
        patch.setattr(env.collector, "_load_snapshot", racing)
        await env.say("안녕하세요")

    await env.say("견적 부탁드려요")

    assert len(await env.hits()) == 1


# ---------------------------------------------------------------------------
# flush: 그룹 카운터
# ---------------------------------------------------------------------------


async def test_flush_writes_messages_seen_and_last_message_at(env: Env) -> None:
    await env.say("하나", date=START - timedelta(minutes=3))
    await env.say("둘", date=START - timedelta(minutes=1))
    await env.say("셋", date=START - timedelta(minutes=2), sender=None)

    before = await env.group()
    assert (before.messages_seen, before.last_message_at) == (0, None)

    await env.collector.flush()
    group = await env.group()
    assert group.messages_seen == 3
    assert group.last_message_at == START - timedelta(minutes=1)

    # 더 오래된 메시지가 늦게 와도 last_message_at 은 뒤로 가지 않는다.
    await env.say("넷", date=START - timedelta(minutes=30))
    await env.collector.flush()
    await env.collector.flush()
    group = await env.group()
    assert group.messages_seen == 4
    assert group.last_message_at == START - timedelta(minutes=1)


async def test_message_dates_are_normalized_to_utc(env: Env) -> None:
    await env.add_activity_rule(min_messages=10, window_hours=1)
    seoul = timezone(timedelta(hours=9))

    await env.say("안녕하세요", date=datetime(2026, 3, 10, 21, 45, tzinfo=seoul))
    await env.say("반갑습니다", date=datetime(2026, 3, 10, 12, 50))  # noqa: DTZ001 - tz 없는 값
    await env.collector.flush()

    [bucket] = await env.buckets()
    assert (bucket.hour, bucket.count) == (datetime(2026, 3, 10, 12, tzinfo=UTC), 2)
    assert (await env.group()).last_message_at == datetime(2026, 3, 10, 12, 50, tzinfo=UTC)


async def test_flush_survives_group_deleted_after_buffering(env: Env) -> None:
    doomed = await env.add_group(env.account_id, OTHER_CHAT, title="사라질 그룹")
    await env.add_activity_rule(min_messages=1, window_hours=1)
    await env.say("안녕하세요", chat_id=OTHER_CHAT, group_id=doomed)
    await env.say("안녕하세요", sender=BOB)
    async with env.db.session() as session:
        await session.delete(await session.get(Group, doomed))
        await session.commit()

    await env.collector.flush()

    assert [(b.group_id, b.tg_user_id) for b in await env.buckets()] == [(env.group_id, BOB.id)]
    assert [lead.tg_user_id for lead in await env.leads()] == [BOB.id]


async def test_failed_flush_keeps_buffers_for_the_next_one(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    await env.add_activity_rule(min_messages=3, window_hours=1)
    await env.say("하나")
    await env.say("둘")
    original = env.collector._write_counts
    calls = 0

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("disk is busy")
        return await original(*args, **kwargs)

    monkeypatch.setattr(env.collector, "_write_counts", flaky)

    with pytest.raises(RuntimeError):
        await env.collector.flush()
    assert (await env.group()).messages_seen == 0

    await env.say("셋")
    await env.collector.flush()

    assert (await env.group()).messages_seen == 3
    [bucket] = await env.buckets()
    assert bucket.count == 3
    [hit] = await env.hits()
    assert hit.message_count == 3
    [log] = await env.logs()
    assert (log.level, log.category) == (LogLevel.ERROR, LogCategory.COLLECT)


# ---------------------------------------------------------------------------
# flush: 활동량 규칙
# ---------------------------------------------------------------------------


async def test_activity_hit_creates_lead_hit_and_event(env: Env) -> None:
    rule_id = await env.add_activity_rule(min_messages=3, window_hours=2, name="수다쟁이")

    for text in ("안녕하세요", "", "ㅋㅋㅋ"):  # 빈 글(미디어)도 활동으로 센다
        await env.say(text)
    assert await env.leads() == []

    await env.collector.flush()

    [lead] = await env.leads()
    [hit] = await env.hits()
    assert lead.first_kind == RuleKind.ACTIVITY
    assert (lead.hit_count, lead.last_hit_id) == (1, hit.id)
    assert hit.kind == RuleKind.ACTIVITY
    assert (hit.rule_id, hit.rule_name) == (rule_id, "수다쟁이")
    assert (hit.group_id, hit.account_id) == (env.group_id, env.account_id)
    assert (hit.message_count, hit.window_hours) == (3, 2)
    assert (hit.keywords, hit.excerpt, hit.tg_message_id) == ([], None, None)
    assert hit.created_at == START

    [event] = env.hit_events()
    assert (event["kind"], event["message_count"], event["window_hours"]) == ("activity", 3, 2)
    assert (event["username"], event["is_new_lead"]) == ("alice_kim", True)


async def test_activity_fires_once_per_window_and_again_after_it(env: Env) -> None:
    await env.add_activity_rule(min_messages=5, window_hours=2)

    for _ in range(4):
        await env.say("수다")
    await env.collector.flush()
    assert await env.hits() == []

    await env.say("수다")
    await env.collector.flush()
    assert [hit.message_count for hit in await env.hits()] == [5]

    # 같은 기간 안에서는 더 떠들어도 다시 기록하지 않는다.
    env.clock.advance(hours=1, minutes=59)
    for _ in range(6):
        await env.say("수다")
    await env.collector.flush()
    assert len(await env.hits()) == 1

    # 기간이 지나고 다시 기준을 넘기면 한 번 더 기록한다.
    env.clock.advance(hours=3)
    for _ in range(4):
        await env.say("수다")
    await env.collector.flush()
    assert len(await env.hits()) == 1

    await env.say("수다")
    await env.collector.flush()

    [lead] = await env.leads()
    assert lead.hit_count == 2
    assert [hit.message_count for hit in await env.hits()] == [5, 5]
    assert [event["is_new_lead"] for event in env.hit_events()] == [True, False]


async def test_activity_counts_span_several_hour_buckets(env: Env) -> None:
    await env.add_activity_rule(min_messages=6, window_hours=3)
    day = datetime(2026, 3, 10, tzinfo=UTC)
    # 지금은 12:30 → 09:00 부터 센다. 08:50 의 글은 기간 밖이다.
    dates = [
        day.replace(hour=8, minute=50),
        day.replace(hour=10, minute=10),
        day.replace(hour=10, minute=40),
        day.replace(hour=11, minute=20),
        day.replace(hour=11, minute=21),
        day.replace(hour=12, minute=25),
    ]
    for date in dates:
        await env.say("수다", date=date)
    await env.collector.flush()

    assert [(b.hour.hour, b.count) for b in await env.buckets()] == [
        (8, 1),
        (10, 2),
        (11, 2),
        (12, 1),
    ]
    assert await env.hits() == []

    await env.say("수다", date=day.replace(hour=12, minute=29))
    await env.collector.flush()

    [hit] = await env.hits()
    assert (hit.message_count, hit.window_hours) == (6, 3)
    assert [(b.hour.hour, b.count) for b in await env.buckets()][-1] == (12, 2)


async def test_activity_is_counted_per_group(env: Env) -> None:
    other_group = await env.add_group(env.account_id, OTHER_CHAT, title="다른 그룹")
    await env.add_activity_rule(min_messages=4, window_hours=1)

    for _ in range(3):
        await env.say("수다")
        await env.say("수다", chat_id=OTHER_CHAT, group_id=other_group)
    await env.collector.flush()
    assert await env.hits() == []

    await env.say("수다", chat_id=OTHER_CHAT, group_id=other_group)
    await env.collector.flush()

    [hit] = await env.hits()
    assert (hit.group_id, hit.message_count) == (other_group, 4)


async def test_activity_is_summed_across_my_accounts_in_the_same_chat(env: Env) -> None:
    # 중복을 걸러 내면 같은 방의 글이 두 그룹 행에 나뉘어 쌓인다. 합쳐서 한 번만 기록해야 한다.
    second_account = await env.add_account(9002)
    second_group = await env.add_group(second_account, CHAT)
    await env.add_activity_rule(min_messages=6, window_hours=1)

    for _ in range(3):
        await env.say("수다")
        await env.say("수다", account_id=second_account, group_id=second_group)
    await env.collector.flush()

    assert [(b.group_id, b.count) for b in await env.buckets()] == [
        (env.group_id, 3),
        (second_group, 3),
    ]
    [hit] = await env.hits()
    assert hit.message_count == 6

    await env.say("수다", account_id=second_account, group_id=second_group)
    await env.collector.flush()
    assert len(await env.hits()) == 1


async def test_activity_evaluation_reads_many_users_in_chunks(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collector_module, "IN_CHUNK", 2)
    await env.add_activity_rule(min_messages=2, window_hours=1)
    chatty = [TgUser(id=200 + index, username=f"user_{index}") for index in range(5)]

    for user in chatty:
        await env.say("수다", sender=user)
        await env.say("수다", sender=user)
    await env.say("수다", sender=BOB)  # 기준 미달
    await env.collector.flush()

    assert [lead.tg_user_id for lead in await env.leads()] == [user.id for user in chatty]
    assert [hit.message_count for hit in await env.hits()] == [2] * 5


async def test_two_activity_rules_fire_independently(env: Env) -> None:
    quick = await env.add_activity_rule(min_messages=2, window_hours=1, name="가벼운 활동")
    heavy = await env.add_activity_rule(min_messages=4, window_hours=1, name="많은 활동")

    for _ in range(2):
        await env.say("수다")
    await env.collector.flush()
    assert [hit.rule_id for hit in await env.hits()] == [quick]

    for _ in range(2):
        await env.say("수다")
    await env.collector.flush()

    assert [(hit.rule_id, hit.message_count) for hit in await env.hits()] == [
        (quick, 2),
        (heavy, 4),
    ]
    [lead] = await env.leads()
    assert lead.hit_count == 2


async def test_activity_skips_user_blocked_before_flush(env: Env) -> None:
    await env.add_activity_rule(min_messages=2, window_hours=1)
    for _ in range(2):
        await env.say("수다")
    await env.add_blocklist("alice_kim")
    env.collector.invalidate()

    await env.collector.flush()

    assert await env.leads() == []
    [bucket] = await env.buckets()
    assert bucket.count == 2


async def test_activity_hit_uses_the_latest_profile_of_the_user(env: Env) -> None:
    await env.add_activity_rule(min_messages=2, window_hours=1)
    renamed = TgUser(id=ALICE.id, username="alice_new", first_name="Alice")

    await env.say("수다")
    await env.say("수다", sender=renamed)
    await env.collector.flush()

    [lead] = await env.leads()
    assert (lead.username, lead.first_name, lead.last_name) == ("alice_new", "Alice", None)


async def test_keyword_then_activity_share_one_lead(env: Env) -> None:
    await env.add_keyword_rule(["추천"])
    await env.add_activity_rule(min_messages=2, window_hours=1)

    await env.say("추천 부탁드려요")
    await env.say("감사합니다")
    await env.collector.flush()

    [lead] = await env.leads()
    assert lead.first_kind == RuleKind.KEYWORD
    assert lead.hit_count == 2
    assert [hit.kind for hit in await env.hits()] == [RuleKind.KEYWORD, RuleKind.ACTIVITY]


# ---------------------------------------------------------------------------
# 동시성
# ---------------------------------------------------------------------------


async def test_concurrent_hits_for_a_new_user_create_exactly_one_lead(env: Env) -> None:
    await env.add_keyword_rule(["추천"])
    groups = [
        (chat_id, await env.add_group(env.account_id, chat_id, title=f"그룹 {index}"))
        for index, chat_id in enumerate(range(-1002000000050, -1002000000000))
    ]
    assert len(groups) == 50

    await asyncio.gather(
        *(
            env.collector.handle(env.message("추천 부탁드려요", chat_id=chat_id), group_id)
            for chat_id, group_id in groups
        )
    )

    [lead] = await env.leads()
    hits = await env.hits()
    assert len(hits) == 50
    assert lead.hit_count == 50
    assert lead.last_hit_id == max(hit.id for hit in hits)
    assert {hit.lead_id for hit in hits} == {lead.id}
    assert sorted(event["is_new_lead"] for event in env.hit_events()) == [False] * 49 + [True]


async def test_concurrent_messages_from_one_user_in_one_group_hit_once(env: Env) -> None:
    await env.add_keyword_rule(["추천"])

    await asyncio.gather(*(env.say("추천 부탁드려요") for _ in range(20)))
    await env.collector.flush()

    [lead] = await env.leads()
    assert lead.hit_count == 1
    assert (await env.group()).messages_seen == 20


# ---------------------------------------------------------------------------
# 정리
# ---------------------------------------------------------------------------


async def test_retention_deletes_old_hits_but_keeps_leads(env: Env) -> None:
    await env.settings.update(retention_days=7)
    await env.add_keyword_rule(["추천"])
    await env.say("추천 부탁드려요")
    env.clock.advance(days=5)
    await env.say("추천 부탁드려요", sender=BOB)
    await env.say("추천 부탁드려요")
    env.clock.advance(days=3)  # 첫 감지는 8일 전, 나머지는 3일 전

    await env.collector.flush()

    alice, bob = await env.leads()
    remaining = await env.hits()
    assert [hit.lead_id for hit in remaining] == [bob.id, alice.id]
    assert (alice.hit_count, alice.last_hit_id) == (2, remaining[1].id)
    assert (bob.hit_count, bob.last_hit_id) == (1, remaining[0].id)

    env.clock.advance(days=5)
    await env.collector.flush()

    alice, bob = await env.leads()
    assert await env.hits() == []
    assert (alice.hit_count, alice.last_hit_id) == (2, None)
    assert (bob.hit_count, bob.last_hit_id) == (1, None)
    messages = [log.message for log in await env.logs() if log.category == LogCategory.COLLECT]
    assert messages == [
        "보관 기간(7일)이 지난 감지 기록 1건을 지웠어요.",
        "보관 기간(7일)이 지난 감지 기록 2건을 지웠어요.",
    ]


async def test_hits_are_kept_forever_when_retention_is_off(env: Env) -> None:
    await env.add_keyword_rule(["추천"])
    await env.say("추천 부탁드려요")
    env.clock.advance(days=400)

    await env.collector.flush()

    [lead] = await env.leads()
    [hit] = await env.hits()
    assert lead.last_hit_id == hit.id
    assert await env.logs() == []


async def test_housekeeping_drops_old_buckets_at_most_once_an_hour(env: Env) -> None:
    async def add_bucket(age: timedelta, tg_user_id: int) -> None:
        async with env.db.session() as session:
            hour = (env.clock.now - age).replace(minute=0, second=0, microsecond=0)
            session.add(
                ActivityBucket(group_id=env.group_id, tg_user_id=tg_user_id, hour=hour, count=4)
            )
            await session.commit()

    await add_bucket(timedelta(days=32), 1)
    await add_bucket(timedelta(days=30), 2)
    await env.collector.flush()
    assert [bucket.tg_user_id for bucket in await env.buckets()] == [2]

    await add_bucket(timedelta(days=40), 3)
    env.clock.advance(minutes=59)
    await env.collector.flush()
    assert [bucket.tg_user_id for bucket in await env.buckets()] == [2, 3]

    env.clock.advance(minutes=1)
    await env.collector.flush()
    assert [bucket.tg_user_id for bucket in await env.buckets()] == [2]


# ---------------------------------------------------------------------------
# 실패 처리
# ---------------------------------------------------------------------------


async def test_handle_never_raises_and_reports_failure_once(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken() -> Any:
        raise RuntimeError("database is gone")

    monkeypatch.setattr(env.collector, "_load_snapshot", broken)

    await env.say("추천 부탁드려요")
    await env.say("추천 부탁드려요")

    [log] = await env.logs()
    assert (log.level, log.category) == (LogLevel.ERROR, LogCategory.COLLECT)
    assert log.message.endswith("요.")

    env.clock.advance(minutes=10)
    await env.say("추천 부탁드려요")
    assert len(await env.logs()) == 2


async def test_failed_hit_write_does_not_start_cooldown(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    await env.add_keyword_rule(["추천"])
    with monkeypatch.context() as patch:

        async def broken(*args: Any, **kwargs: Any) -> bool:
            raise RuntimeError("database is locked")

        patch.setattr(env.collector, "_record_hit", broken)
        await env.say("추천 부탁드려요")
    assert await env.hits() == []

    await env.say("추천 부탁드려요")

    [lead] = await env.leads()
    assert lead.hit_count == 1
    [log] = await env.logs()
    assert log.level == LogLevel.ERROR


async def test_activity_evaluation_failure_does_not_fail_flush(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    await env.add_activity_rule(min_messages=2, window_hours=1)
    await env.say("수다")
    await env.say("수다")
    with monkeypatch.context() as patch:

        async def broken(*args: Any, **kwargs: Any) -> dict[int, int]:
            raise RuntimeError("database is locked")

        patch.setattr(env.collector, "_sum_recent_messages", broken)
        await env.collector.flush()
    assert await env.hits() == []
    [bucket] = await env.buckets()
    assert bucket.count == 2

    # 집계는 남아 있으므로 다음에 말할 때 기준을 넘긴 것으로 잡힌다.
    await env.say("수다")
    await env.collector.flush()
    [hit] = await env.hits()
    assert hit.message_count == 3


# ---------------------------------------------------------------------------
# 백그라운드 태스크
# ---------------------------------------------------------------------------


async def test_background_task_flushes_periodically_and_survives_errors(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = make_collector(env, flush_interval=0.01)
    original = collector._write_counts
    failures = 0
    written = asyncio.Event()

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        nonlocal failures
        if failures < 2:
            failures += 1
            raise RuntimeError("disk is busy")
        result = await original(*args, **kwargs)
        written.set()
        return result

    monkeypatch.setattr(collector, "_write_counts", flaky)
    await collector.start()
    try:
        await collector.handle(env.message("안녕하세요"), env.group_id)
        async with asyncio.timeout(5):
            await written.wait()
    finally:
        await collector.stop()

    assert failures == 2
    assert (await env.group()).messages_seen == 1


async def test_start_twice_keeps_one_task_and_stop_does_final_flush(env: Env) -> None:
    collector = make_collector(env, flush_interval=3600)
    await collector.start()
    task = collector._task
    await collector.start()
    assert collector._task is task

    await collector.handle(env.message("안녕하세요"), env.group_id)
    await collector.stop()

    assert task is not None and task.cancelled()
    assert (await env.group()).messages_seen == 1

    # 멈춘 뒤에도 다시 켤 수 있고, 켜지 않은 채 stop() 을 불러도 된다.
    await collector.start()
    assert collector._task is not task
    await collector.stop()
    await collector.stop()


async def test_stop_swallows_final_flush_failure(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    collector = make_collector(env)
    await collector.handle(env.message("안녕하세요"), env.group_id)

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("disk is busy")

    with monkeypatch.context() as patch:
        patch.setattr(collector, "_write_counts", broken)
        with caplog.at_level("ERROR", logger="chatdb.collector"):
            await collector.stop()
    assert "남은 버퍼를 저장하지 못했어요" in caplog.text

    # 버퍼는 남아 있어 다음 flush 에 반영된다.
    await collector.flush()
    assert (await env.group()).messages_seen == 1


async def test_stop_lets_a_running_flush_finish_instead_of_cutting_it(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = make_collector(env, flush_interval=0.01)
    original = collector._write_counts
    started = asyncio.Event()
    attempts = 0
    writes = 0

    async def slow(*args: Any, **kwargs: Any) -> Any:
        nonlocal attempts, writes
        attempts += 1
        started.set()
        await asyncio.sleep(0.05)
        result = await original(*args, **kwargs)
        writes += 1
        return result

    monkeypatch.setattr(collector, "_write_counts", slow)
    await collector.handle(env.message("안녕하세요"), env.group_id)
    await collector.start()
    async with asyncio.timeout(5):
        await started.wait()

    await collector.stop()

    # 진행 중이던 flush 가 끊기지 않고 끝까지 가서, 마지막 flush 는 더 쓸 것이 없다.
    assert (attempts, writes) == (1, 1)
    assert (await env.group()).messages_seen == 1
