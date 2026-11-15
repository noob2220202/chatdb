"""수집기: 그룹 메시지를 받아 규칙에 걸린 사람을 수집함에 넣는다.

아래 공개 메서드의 이름·인자·동작은 엔진과 라우터가 기대하는 계약이다(바꾸지 않는다).
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import (
    BigInteger,
    CursorResult,
    Integer,
    UpdateBase,
    and_,
    bindparam,
    case,
    delete,
    exists,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Database, UTCDateTime, utcnow
from ..events import EventBus
from ..matching import make_excerpt, match_keywords
from ..models import (
    Account,
    ActivityBucket,
    BlocklistEntry,
    Group,
    Hit,
    Lead,
    LeadStatus,
    LogCategory,
    Rule,
    RuleKind,
)
from ..serializers import feed_item, group_display_title
from ..settings_store import SettingsStore
from ..telegram.gateway import IncomingMessage, TgUser
from .logbook import Logbook

logger = logging.getLogger("chatdb.collector")

FLUSH_INTERVAL_SECONDS = 5.0
KEYWORD_COOLDOWN = timedelta(minutes=5)
"""같은 (유저, 규칙, 그룹)의 키워드 감지를 다시 기록하지 않는 시간."""
HOUSEKEEPING_INTERVAL = timedelta(hours=1)
BUCKET_RETENTION = timedelta(days=31)
"""활동량 집계를 남겨 두는 기간. 활동량 규칙의 최대 기간(720시간)보다 길어야 한다."""
SEEN_MESSAGES_LIMIT = 50_000
COOLDOWN_LIMIT = 20_000
FAILURE_NOTICE_INTERVAL = timedelta(minutes=10)
"""같은 종류의 실패를 활동 기록에 다시 남기기까지 두는 간격."""
IN_CHUNK = 500
"""IN 절 하나에 넣는 값의 최대 개수."""

Clock = Callable[[], datetime]

# flush 가 한 번에 여러 행을 쓰는 문장들. 행마다 값만 바꿔 executemany 로 실행한다.
_GROUP_ID = bindparam("b_group_id", type_=Integer)
_USER_ID = bindparam("b_tg_user_id", type_=BigInteger)
_HOUR = bindparam("b_hour", type_=UTCDateTime)
_AMOUNT = bindparam("b_amount", type_=Integer)
_SEEN_AT = bindparam("b_seen_at", type_=UTCDateTime)

_ADD_GROUP_MESSAGES = (
    update(Group)
    .where(Group.id == _GROUP_ID)
    .values(
        messages_seen=Group.messages_seen + _AMOUNT,
        last_message_at=case(
            (or_(Group.last_message_at.is_(None), Group.last_message_at < _SEEN_AT), _SEEN_AT),
            else_=Group.last_message_at,
        ),
    )
)
_SAME_BUCKET = and_(
    ActivityBucket.group_id == _GROUP_ID,
    ActivityBucket.tg_user_id == _USER_ID,
    ActivityBucket.hour == _HOUR,
)
# 없는 집계 행을 0 으로 만들어 두고(_ENSURE_BUCKET) 그 위에 더한다(_ADD_BUCKET_MESSAGES).
_ENSURE_BUCKET = insert(ActivityBucket).from_select(
    ["group_id", "tg_user_id", "hour", "count"],
    select(_GROUP_ID, _USER_ID, _HOUR, literal(0)).where(~exists().where(_SAME_BUCKET)),
)
_ADD_BUCKET_MESSAGES = (
    update(ActivityBucket).where(_SAME_BUCKET).values(count=ActivityBucket.count + _AMOUNT)
)


def _as_utc(value: datetime) -> datetime:
    """tz 가 없으면 UTC 로 보고, 있으면 UTC 로 바꾼다."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _floor_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _clip(value: str | None, length: int) -> str | None:
    return value[:length] if value else None


async def _run_dml(session: AsyncSession, statement: UpdateBase) -> int:
    """INSERT·UPDATE·DELETE 문을 실행하고 바뀐 행 수를 돌려준다."""
    result = await session.execute(statement, execution_options={"synchronize_session": False})
    return cast("CursorResult[Any]", result).rowcount


# ---------------------------------------------------------------------------
# 캐시에 담는 값
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Scope:
    """규칙이 적용되는 그룹.

    그룹 행은 계정마다 따로 있어서, 내 계정 둘이 같은 방에 있으면 행이 둘이다.
    중복 메시지는 먼저 도착한 쪽만 처리하므로 방(chat) 기준으로도 맞춰 본다.
    """

    all_groups: bool
    group_ids: frozenset[int]
    chat_ids: frozenset[int]

    def covers(self, group_id: int, chat_id: int | None) -> bool:
        return self.all_groups or group_id in self.group_ids or chat_id in self.chat_ids


@dataclass(frozen=True, slots=True)
class _KeywordRule:
    id: int
    scope: _Scope
    keywords: list[str]
    exclude_keywords: list[str]
    match_mode: str


@dataclass(frozen=True, slots=True)
class _ActivityRule:
    id: int
    scope: _Scope
    min_messages: int
    window_hours: int


@dataclass(frozen=True, slots=True)
class _Snapshot:
    keyword_rules: tuple[_KeywordRule, ...]
    activity_rules: tuple[_ActivityRule, ...]
    blocked_usernames: frozenset[str]
    excluded_user_ids: frozenset[int]
    own_user_ids: frozenset[int]

    def skips(self, sender: TgUser) -> bool:
        """수집하지 않는 발신자인지: 봇, 아이디 없음, 내 계정, 제외 목록, 제외 상태."""
        if sender.is_bot or not sender.username:
            return True
        return (
            sender.id in self.own_user_ids
            or sender.id in self.excluded_user_ids
            or sender.username.lower() in self.blocked_usernames
        )


# ---------------------------------------------------------------------------
# 버퍼에 담는 값
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _GroupCounter:
    messages: int
    last_message_at: datetime


@dataclass(frozen=True, slots=True)
class _Actor:
    """활동량 평가 때 쓸, 그 유저의 가장 최근 모습과 메시지를 받은 계정."""

    user: TgUser
    account_id: int


@dataclass(frozen=True, slots=True)
class _Talker:
    """이번 flush 에서 말한 (그룹, 유저) 한 쌍과, 그 그룹에 걸려 있는 활동량 규칙."""

    group_id: int
    actor: _Actor
    rules: list[_ActivityRule]


@dataclass(frozen=True, slots=True)
class _Detection:
    kind: RuleKind
    rule_id: int
    group_id: int
    account_id: int
    user: TgUser
    keywords: list[str] = field(default_factory=list)
    excerpt: str | None = None
    tg_message_id: int | None = None
    message_count: int | None = None
    window_hours: int | None = None


class _GroupIndex:
    """flush 시점의 그룹 행과, 같은 방을 가리키는 행 묶음."""

    def __init__(self, rows: Iterable[tuple[int, int | None]]) -> None:
        self._chat_by_group: dict[int, int | None] = dict(rows)
        groups_by_chat: dict[int, list[int]] = {}
        for group_id, chat_id in self._chat_by_group.items():
            if chat_id is not None:
                groups_by_chat.setdefault(chat_id, []).append(group_id)
        self._groups_by_chat = {chat_id: tuple(ids) for chat_id, ids in groups_by_chat.items()}

    def __contains__(self, group_id: int) -> bool:
        return group_id in self._chat_by_group

    def chat_id(self, group_id: int) -> int | None:
        return self._chat_by_group.get(group_id)

    def same_chat(self, group_id: int) -> tuple[int, ...]:
        """이 그룹과 같은 방을 가리키는 그룹 행들(자기 자신 포함)."""
        chat_id = self._chat_by_group.get(group_id)
        if chat_id is None:
            return (group_id,)
        return self._groups_by_chat[chat_id]


# ---------------------------------------------------------------------------
# 수집기
# ---------------------------------------------------------------------------


class Collector:
    """메시지마다 handle() 이 불리고, 주기적으로 flush() 가 돈다.

    handle() 은 키워드 감지만 바로 DB 에 쓰고 나머지(그룹 카운터, 활동량)는 메모리에 모아 둔다.
    DB 쓰기는 모두 _write_lock 아래에서 한 줄로 이뤄진다.
    """

    def __init__(
        self,
        *,
        db: Database,
        bus: EventBus,
        settings: SettingsStore,
        logbook: Logbook,
        clock: Clock = utcnow,
        flush_interval: float = FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self._db = db
        self._bus = bus
        self._settings = settings
        self._logbook = logbook
        self._clock = clock
        self._flush_interval = flush_interval

        self._task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        """DB 쓰기를 한 줄로 세운다(유저당 Lead 하나를 보장한다)."""

        self._snapshot: _Snapshot | None = None
        self._generation = 0
        self._load_lock = asyncio.Lock()

        self._seen: OrderedDict[tuple[int, int], None] = OrderedDict()
        self._cooldowns: OrderedDict[tuple[int, int, int], datetime] = OrderedDict()

        self._group_counters: dict[int, _GroupCounter] = {}
        self._activity: dict[tuple[int, int, datetime], int] = {}
        self._actors: dict[tuple[int, int], _Actor] = {}

        self._last_housekeeping: datetime | None = None
        self._failure_notices: dict[str, datetime] = {}

    # --- 수명 주기 ---------------------------------------------------------

    async def start(self) -> None:
        """주기적으로 flush() 를 부르는 백그라운드 태스크를 띄운다. 이미 떠 있으면 아무것도 안 한다."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="collector-flush")

    async def stop(self) -> None:
        """백그라운드 태스크를 멈추고 남은 버퍼를 flush 한다."""
        task, self._task = self._task, None
        if task is not None:
            # 쓰기 락을 쥔 채로 취소한다. 그러면 주기 태스크는 자고 있거나 락을 기다리는 중이라
            # DB 쓰기가 중간에 끊기지 않는다.
            async with self._write_lock:
                task.cancel()
            await asyncio.wait({task})
        try:
            await self.flush()
        except Exception:
            logger.exception("수집기를 멈추면서 남은 버퍼를 저장하지 못했어요")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            try:
                await self.flush()
            except Exception:
                logger.exception("주기적인 flush 에 실패했어요. 다음 주기에 다시 시도해요")

    # --- 캐시 --------------------------------------------------------------

    def invalidate(self) -> None:
        """규칙, 규칙의 적용 그룹, 제외 목록, 제외 상태 유저, 내 계정 id 캐시를 버린다.

        규칙·제외 목록·유저 상태·계정이 바뀔 때마다 라우터와 엔진이 부른다.
        다음 메시지를 처리할 때 다시 읽는다.
        """
        self._snapshot = None
        self._generation += 1

    async def _state(self) -> _Snapshot:
        snapshot = self._snapshot
        if snapshot is not None:
            return snapshot
        async with self._load_lock:
            if self._snapshot is not None:
                return self._snapshot
            generation = self._generation
            loaded = await self._load_snapshot()
            # 읽는 사이에 invalidate() 가 불렸으면 이번 호출에만 쓰고 캐시에는 두지 않는다.
            if generation == self._generation:
                self._snapshot = loaded
            return loaded

    async def _load_snapshot(self) -> _Snapshot:
        async with self._db.session() as session:
            rules = (
                await session.scalars(select(Rule).where(Rule.enabled.is_(True)).order_by(Rule.id))
            ).all()
            blocked = (await session.scalars(select(BlocklistEntry.username))).all()
            excluded = (
                await session.scalars(
                    select(Lead.tg_user_id).where(Lead.status == LeadStatus.EXCLUDED)
                )
            ).all()
            own = (
                await session.scalars(
                    select(Account.tg_user_id).where(Account.tg_user_id.is_not(None))
                )
            ).all()

        keyword_rules: list[_KeywordRule] = []
        activity_rules: list[_ActivityRule] = []
        for rule in rules:
            scope = _Scope(
                all_groups=bool(rule.all_groups),
                group_ids=frozenset(group.id for group in rule.groups),
                chat_ids=frozenset(
                    group.tg_chat_id for group in rule.groups if group.tg_chat_id is not None
                ),
            )
            if rule.kind == RuleKind.KEYWORD:
                keyword_rules.append(
                    _KeywordRule(
                        id=rule.id,
                        scope=scope,
                        keywords=list(rule.keywords or []),
                        exclude_keywords=list(rule.exclude_keywords or []),
                        match_mode=rule.match_mode,
                    )
                )
            elif rule.kind == RuleKind.ACTIVITY:
                if not rule.min_messages or not rule.window_hours:
                    logger.warning(
                        "활동량 규칙 %s 에 메시지 수나 기간이 없어서 건너뛰어요", rule.id
                    )
                    continue
                activity_rules.append(
                    _ActivityRule(
                        id=rule.id,
                        scope=scope,
                        min_messages=rule.min_messages,
                        window_hours=rule.window_hours,
                    )
                )
        return _Snapshot(
            keyword_rules=tuple(keyword_rules),
            activity_rules=tuple(activity_rules),
            blocked_usernames=frozenset(name.lower() for name in blocked),
            excluded_user_ids=frozenset(excluded),
            own_user_ids=frozenset(own),
        )

    # --- 메시지 처리 -------------------------------------------------------

    async def handle(self, message: IncomingMessage, group_id: int) -> None:
        """그룹 메시지 하나를 처리한다. group_id 는 groups.id 다.

        예외를 밖으로 던지지 않는다(한 메시지의 실패가 수신 루프를 멈추면 안 된다).
        """
        try:
            await self._handle(message, group_id)
        except Exception:
            logger.exception(
                "메시지를 처리하지 못했어요 (group_id=%s, message_id=%s)",
                group_id,
                message.message_id,
            )
            await self._notify_failure(
                "handle",
                "그룹 메시지를 처리하다 문제가 생겼어요. 계속되면 서버 로그를 확인해 주세요.",
            )

    async def _handle(self, message: IncomingMessage, group_id: int) -> None:
        if self._seen_before((message.chat_id, message.message_id)):
            return
        sent_at = _as_utc(message.date)
        self._count_message(group_id, sent_at)

        state = await self._state()
        sender = message.sender
        if sender is None or state.skips(sender):
            return

        now = self._clock()
        candidates: list[tuple[_KeywordRule, list[str]]] = []
        for rule in state.keyword_rules:
            if not rule.scope.covers(group_id, message.chat_id):
                continue
            if self._cooling_down((sender.id, rule.id, message.chat_id), now):
                continue
            matched = match_keywords(
                message.text, rule.keywords, rule.exclude_keywords, rule.match_mode
            )
            if matched:
                candidates.append((rule, matched))

        if any(rule.scope.covers(group_id, message.chat_id) for rule in state.activity_rules):
            bucket = (group_id, sender.id, _floor_hour(sent_at))
            self._activity[bucket] = self._activity.get(bucket, 0) + 1
            self._actors[(group_id, sender.id)] = _Actor(sender, message.account_id)

        if candidates:
            await self._record_keyword_hits(message, group_id, sender, candidates, now)

    def _seen_before(self, key: tuple[int, int]) -> bool:
        """(chat_id, message_id) 를 이미 처리했는지 보고, 처음이면 기억해 둔다."""
        if key in self._seen:
            self._seen.move_to_end(key)
            return True
        self._seen[key] = None
        if len(self._seen) > SEEN_MESSAGES_LIMIT:
            self._seen.popitem(last=False)
        return False

    def _count_message(self, group_id: int, sent_at: datetime) -> None:
        counter = self._group_counters.get(group_id)
        if counter is None:
            self._group_counters[group_id] = _GroupCounter(1, sent_at)
            return
        counter.messages += 1
        counter.last_message_at = max(counter.last_message_at, sent_at)

    def _cooling_down(self, key: tuple[int, int, int], now: datetime) -> bool:
        last = self._cooldowns.get(key)
        return last is not None and now - last < KEYWORD_COOLDOWN

    def _start_cooldown(self, key: tuple[int, int, int], now: datetime) -> None:
        self._cooldowns[key] = now
        self._cooldowns.move_to_end(key)
        while self._cooldowns:
            oldest = next(iter(self._cooldowns.values()))
            if now - oldest < KEYWORD_COOLDOWN and len(self._cooldowns) <= COOLDOWN_LIMIT:
                break
            self._cooldowns.popitem(last=False)

    async def _record_keyword_hits(
        self,
        message: IncomingMessage,
        group_id: int,
        sender: TgUser,
        candidates: list[tuple[_KeywordRule, list[str]]],
        now: datetime,
    ) -> None:
        settings = await self._settings.get()
        async with self._write_lock:
            for rule, matched in candidates:
                # 락을 기다리는 사이 같은 유저의 다른 메시지가 먼저 기록됐을 수 있어 다시 본다.
                key = (sender.id, rule.id, message.chat_id)
                if self._cooling_down(key, now):
                    continue
                detection = _Detection(
                    kind=RuleKind.KEYWORD,
                    rule_id=rule.id,
                    group_id=group_id,
                    account_id=message.account_id,
                    user=sender,
                    keywords=matched,
                    excerpt=make_excerpt(message.text, matched)
                    if settings.store_excerpts
                    else None,
                    tg_message_id=message.message_id,
                )
                try:
                    recorded = await self._record_hit(detection, now)
                except Exception:
                    logger.exception(
                        "키워드 감지를 저장하지 못했어요 (rule_id=%s, group_id=%s)",
                        rule.id,
                        group_id,
                    )
                    await self._notify_failure(
                        "record",
                        "감지 기록을 저장하지 못했어요. 계속되면 서버 로그를 확인해 주세요.",
                    )
                    continue
                if recorded:
                    self._start_cooldown(key, now)

    # --- 감지 기록 ---------------------------------------------------------

    async def _record_hit(self, detection: _Detection, now: datetime) -> bool:
        """감지 한 건을 한 트랜잭션으로 기록하고 실시간 이벤트를 낸다.

        쓰기 락을 쥔 채로 불러야 한다. 캐시를 읽은 뒤 그룹이 지워졌거나, 규칙이 지워지거나
        꺼졌거나, 유저가 제외 상태가 됐으면 기록하지 않고 False 를 돌려준다.
        """
        user = detection.user
        async with self._db.session() as session:
            group = await session.get(Group, detection.group_id)
            rule = await session.get(Rule, detection.rule_id)
            if group is None or rule is None or not rule.enabled:
                logger.debug(
                    "그룹이나 규칙이 없어져서 감지를 기록하지 않아요 (rule_id=%s, group_id=%s)",
                    detection.rule_id,
                    detection.group_id,
                )
                return False

            lead = (
                await session.execute(select(Lead).where(Lead.tg_user_id == user.id))
            ).scalar_one_or_none()
            is_new_lead = lead is None
            if lead is None:
                lead = Lead(
                    tg_user_id=user.id,
                    status=LeadStatus.NEW,
                    hit_count=0,
                    first_kind=detection.kind,
                    first_seen_at=now,
                )
                session.add(lead)
            elif lead.status == LeadStatus.EXCLUDED:
                return False
            lead.username = (user.username or "")[:64]
            lead.first_name = _clip(user.first_name, 128)
            lead.last_name = _clip(user.last_name, 128)
            lead.hit_count += 1
            lead.last_seen_at = now
            await session.flush()

            hit = Hit(
                lead_id=lead.id,
                rule_id=rule.id,
                group_id=group.id,
                account_id=await self._known_account_id(session, group, detection.account_id),
                kind=detection.kind,
                rule_name=rule.name[:80],
                group_title=group_display_title(group)[:255],
                keywords=list(detection.keywords),
                excerpt=_clip(detection.excerpt, 400),
                tg_message_id=detection.tg_message_id,
                message_count=detection.message_count,
                window_hours=detection.window_hours,
                created_at=now,
            )
            session.add(hit)
            await session.flush()
            lead.last_hit_id = hit.id
            await session.commit()

        payload = feed_item(hit, lead, is_new_lead=is_new_lead).model_dump(mode="json")
        self._bus.publish("hit", payload)
        return True

    @staticmethod
    async def _known_account_id(session: AsyncSession, group: Group, account_id: int) -> int | None:
        """메시지를 받은 계정이 아직 남아 있으면 그 id, 지워졌으면 None."""
        if group.account_id == account_id:
            return account_id
        account = await session.get(Account, account_id)
        return account.id if account is not None else None

    # --- flush -------------------------------------------------------------

    async def flush(self) -> None:
        """버퍼에 쌓인 그룹 카운터와 활동량을 DB 에 반영하고 활동량 규칙을 평가한다."""
        async with self._write_lock:
            now = self._clock()
            if self._group_counters or self._activity or self._actors:
                await self._flush_buffers(now)
            await self._housekeep(now)

    async def _flush_buffers(self, now: datetime) -> None:
        counters, self._group_counters = self._group_counters, {}
        activity, self._activity = self._activity, {}
        actors, self._actors = self._actors, {}
        try:
            groups = await self._write_counts(counters, activity)
        except BaseException as exc:
            # 저장하지 못한 수치는 다음 flush 에 다시 쓴다.
            self._restore(counters, activity, actors)
            if isinstance(exc, Exception):
                await self._notify_failure(
                    "flush",
                    "그룹 메시지 수와 활동량을 저장하지 못했어요. 잠시 뒤에 다시 시도해요.",
                )
            raise

        try:
            state = await self._state()
        except BaseException:
            # 집계는 저장됐다. 평가만 다음 flush 로 미룬다.
            self._restore({}, {}, actors)
            raise
        for group_ids, talkers in self._talkers_by_chat(state, groups, actors).items():
            try:
                await self._evaluate_activity(group_ids, talkers, now)
            except Exception:
                # 집계는 이미 저장됐으므로 그 방의 유저가 다음에 말할 때 다시 평가된다.
                logger.exception("활동량 규칙을 평가하지 못했어요 (group_ids=%s)", group_ids)
                await self._notify_failure(
                    "evaluate",
                    "활동량 규칙을 평가하다 문제가 생겼어요. 계속되면 서버 로그를 확인해 주세요.",
                )

    def _restore(
        self,
        counters: dict[int, _GroupCounter],
        activity: dict[tuple[int, int, datetime], int],
        actors: dict[tuple[int, int], _Actor],
    ) -> None:
        """쓰지 못한 버퍼를, 그 사이 새로 쌓인 버퍼에 합친다."""
        for group_id, counter in counters.items():
            current = self._group_counters.get(group_id)
            if current is None:
                self._group_counters[group_id] = counter
            else:
                current.messages += counter.messages
                current.last_message_at = max(current.last_message_at, counter.last_message_at)
        for bucket, count in activity.items():
            self._activity[bucket] = self._activity.get(bucket, 0) + count
        for key, actor in actors.items():
            self._actors.setdefault(key, actor)

    async def _write_counts(
        self,
        counters: dict[int, _GroupCounter],
        activity: dict[tuple[int, int, datetime], int],
    ) -> _GroupIndex:
        """그룹 카운터와 활동량 집계를 한 트랜잭션으로 쓴다. 지워진 그룹의 몫은 버린다."""
        async with self._db.session() as session:
            rows = (await session.execute(select(Group.id, Group.tg_chat_id))).all()
            groups = _GroupIndex((group_id, chat_id) for group_id, chat_id in rows)

            counter_rows = [
                {
                    "b_group_id": group_id,
                    "b_amount": counter.messages,
                    "b_seen_at": counter.last_message_at,
                }
                for group_id, counter in counters.items()
                if group_id in groups
            ]
            bucket_rows = [
                {
                    "b_group_id": group_id,
                    "b_tg_user_id": tg_user_id,
                    "b_hour": hour,
                    "b_amount": count,
                }
                for (group_id, tg_user_id, hour), count in activity.items()
                if group_id in groups
            ]
            bucket_keys = [
                {name: value for name, value in row.items() if name != "b_amount"}
                for row in bucket_rows
            ]

            connection = await session.connection()
            if counter_rows:
                await connection.execute(_ADD_GROUP_MESSAGES, counter_rows)
            if bucket_rows:
                await connection.execute(_ENSURE_BUCKET, bucket_keys)
                await connection.execute(_ADD_BUCKET_MESSAGES, bucket_rows)
            await session.commit()
        return groups

    @staticmethod
    def _talkers_by_chat(
        state: _Snapshot, groups: _GroupIndex, actors: dict[tuple[int, int], _Actor]
    ) -> dict[tuple[int, ...], list[_Talker]]:
        """평가할 (그룹, 유저) 쌍을 방별로 모은다. 키는 그 방을 가리키는 그룹 행들이다.

        내 계정 둘이 같은 방에 있으면 집계가 두 그룹 행에 나뉘어 쌓이므로 방 단위로 합쳐서 본다.
        """
        by_chat: dict[tuple[int, ...], list[_Talker]] = {}
        for (group_id, _tg_user_id), actor in actors.items():
            if group_id not in groups or state.skips(actor.user):
                continue
            chat_id = groups.chat_id(group_id)
            rules = [rule for rule in state.activity_rules if rule.scope.covers(group_id, chat_id)]
            if rules:
                talker = _Talker(group_id, actor, rules)
                by_chat.setdefault(groups.same_chat(group_id), []).append(talker)
        return by_chat

    async def _evaluate_activity(
        self, group_ids: tuple[int, ...], talkers: list[_Talker], now: datetime
    ) -> None:
        """한 방에서 이번 flush 에 말한 유저들에게 활동량 규칙을 적용한다."""
        windows = {rule.window_hours for talker in talkers for rule in talker.rules}
        user_ids = sorted({talker.actor.user.id for talker in talkers})

        due: list[_Detection] = []
        claimed: set[tuple[int, int]] = set()
        async with self._db.session() as session:
            totals = {
                hours: await self._sum_recent_messages(
                    session, group_ids, user_ids, _floor_hour(now - timedelta(hours=hours))
                )
                for hours in windows
            }
            for talker in talkers:
                user = talker.actor.user
                for rule in talker.rules:
                    total = totals[rule.window_hours].get(user.id, 0)
                    # 같은 유저가 이 방의 두 그룹 행에 걸쳐 말했어도 규칙당 한 번만 기록한다.
                    if total < rule.min_messages or (user.id, rule.id) in claimed:
                        continue
                    claimed.add((user.id, rule.id))
                    since = now - timedelta(hours=rule.window_hours)
                    if await self._has_activity_hit_since(
                        session, group_ids, user.id, rule.id, since
                    ):
                        continue
                    due.append(
                        _Detection(
                            kind=RuleKind.ACTIVITY,
                            rule_id=rule.id,
                            group_id=talker.group_id,
                            account_id=talker.actor.account_id,
                            user=user,
                            message_count=total,
                            window_hours=rule.window_hours,
                        )
                    )

        for detection in due:
            await self._record_hit(detection, now)

    @staticmethod
    async def _sum_recent_messages(
        session: AsyncSession,
        group_ids: tuple[int, ...],
        tg_user_ids: list[int],
        since_hour: datetime,
    ) -> dict[int, int]:
        """since_hour 부터 지금까지, 유저별 메시지 수(한 방의 그룹 행들을 합친 값)."""
        totals: dict[int, int] = {}
        for start in range(0, len(tg_user_ids), IN_CHUNK):
            rows = await session.execute(
                select(ActivityBucket.tg_user_id, func.sum(ActivityBucket.count))
                .where(
                    ActivityBucket.group_id.in_(group_ids),
                    ActivityBucket.tg_user_id.in_(tg_user_ids[start : start + IN_CHUNK]),
                    ActivityBucket.hour >= since_hour,
                )
                .group_by(ActivityBucket.tg_user_id)
            )
            totals.update((tg_user_id, int(total)) for tg_user_id, total in rows)
        return totals

    @staticmethod
    async def _has_activity_hit_since(
        session: AsyncSession,
        group_ids: tuple[int, ...],
        tg_user_id: int,
        rule_id: int,
        since: datetime,
    ) -> bool:
        found = await session.scalar(
            select(Hit.id)
            .join(Lead, Lead.id == Hit.lead_id)
            .where(
                Lead.tg_user_id == tg_user_id,
                Hit.kind == RuleKind.ACTIVITY,
                Hit.rule_id == rule_id,
                Hit.group_id.in_(group_ids),
                Hit.created_at > since,
            )
            .limit(1)
        )
        return found is not None

    # --- 정리 --------------------------------------------------------------

    async def _housekeep(self, now: datetime) -> None:
        """한 시간에 한 번, 오래된 활동량 집계와 보관 기간이 지난 감지 기록을 지운다."""
        if (
            self._last_housekeeping is not None
            and now - self._last_housekeeping < HOUSEKEEPING_INTERVAL
        ):
            return
        self._last_housekeeping = now
        try:
            settings = await self._settings.get()
            removed_hits = 0
            async with self._db.session() as session:
                await _run_dml(
                    session,
                    delete(ActivityBucket).where(ActivityBucket.hour < now - BUCKET_RETENTION),
                )
                if settings.retention_days > 0:
                    removed_hits = await _run_dml(
                        session,
                        delete(Hit).where(
                            Hit.created_at < now - timedelta(days=settings.retention_days)
                        ),
                    )
                    if removed_hits:
                        # 지워진 감지를 가리키던 포인터만 비운다(유저는 그대로 둔다).
                        await _run_dml(
                            session,
                            update(Lead)
                            .where(
                                Lead.last_hit_id.is_not(None),
                                Lead.last_hit_id.not_in(select(Hit.id)),
                            )
                            .values(last_hit_id=None),
                        )
                await session.commit()
        except Exception:
            logger.exception("오래된 기록을 정리하지 못했어요")
            await self._notify_failure(
                "housekeeping", "오래된 기록을 정리하지 못했어요. 한 시간 뒤에 다시 시도해요."
            )
            return
        if removed_hits:
            await self._logbook.info(
                f"보관 기간({settings.retention_days}일)이 지난 감지 기록 {removed_hits:,}건을 지웠어요.",
                category=LogCategory.COLLECT,
            )

    # --- 실패 알림 ---------------------------------------------------------

    async def _notify_failure(self, kind: str, message: str) -> None:
        """실패를 활동 기록에 남긴다. 같은 종류는 일정 간격으로만 남겨 기록이 넘치지 않게 한다."""
        now = self._clock()
        last = self._failure_notices.get(kind)
        if last is not None and now - last < FAILURE_NOTICE_INTERVAL:
            return
        self._failure_notices[kind] = now
        await self._logbook.error(message, category=LogCategory.COLLECT)
