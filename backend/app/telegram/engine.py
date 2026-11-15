"""엔진: 계정 연결을 유지하고, 그룹 가입 대기열을 처리하고, 메시지를 수집기에 넘긴다.

아래 공개 메서드의 이름·인자·동작은 라우터가 기대하는 계약이다(바꾸지 않는다).

계정마다 연결 태스크가 하나 돈다. 연결돼 있는 동안에는 그 아래에서 일꾼 둘이 돈다.
  - 대기열 일꾼: 감시 대상 맵을 다시 읽고, 가입 간격을 지키며 대기열의 그룹에 하나씩 들어간다.
  - 확인 일꾼: 입장 요청이 승인됐는지, 아직 그룹에 남아 있는지 주기적으로 확인한다.
기다림은 모두 clock 이 주는 시각과 비교해서 잰다. 텔레그램이 요청을 제한하면(FLOOD_WAIT)
알려 준 시각이 지날 때까지 그 계정으로는 아무 요청도 보내지 않는다(연결만 유지한다).
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from functools import partial
from typing import TypeVar

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Database, utcnow
from ..events import EventBus
from ..links import LinkTarget
from ..models import (
    Account,
    AccountStatus,
    Group,
    GroupKind,
    GroupStatus,
    LinkKind,
    LogCategory,
)
from ..security import Secrets
from ..serializers import account_display_name, account_out, group_out
from ..services.collector import Collector
from ..services.logbook import Logbook
from ..settings_store import SettingsStore
from .gateway import (
    AccountClient,
    IncomingMessage,
    JoinOutcome,
    JoinResult,
    LoginResult,
    PendingLogin,
    TelegramError,
    TelegramGateway,
    TgChat,
    TgErrorCode,
    TgUser,
)

logger = logging.getLogger("chatdb.engine")

Clock = Callable[[], datetime]
T = TypeVar("T")

DEFAULT_FLOOD_WAIT_SECONDS = 3600
"""텔레그램이 기다릴 시간을 알려 주지 않은 요청 제한에 쓰는 값. 일찍 다시 시도하지 않도록 넉넉히 잡는다."""

DUPLICATE_ERROR_CODE = "duplicate"
NO_LINK_ERROR_CODE = "no_link"

# 그룹 하나가 아니라 계정 전체의 문제인 오류. 일꾼이 만나면 연결 태스크로 올려 계정 상태로 처리한다.
_ACCOUNT_ERRORS = frozenset(
    {TgErrorCode.SESSION_INVALID, TgErrorCode.BANNED, TgErrorCode.API_CREDENTIALS}
)
# 엔진을 멈출 때 '꺼짐'으로 돌려놓는 상태. 다시 로그인·정지·요청 제한은 다음에 켤 때도 알아야 해서 남긴다.
_LIVE_STATUSES = (AccountStatus.ACTIVE, AccountStatus.CONNECTING, AccountStatus.ERROR)

_DETAIL_CHANNEL = "방송 채널이라 유저 채팅은 수집되지 않아요"
_DETAIL_REQUESTED = "입장 요청을 보냈어요. 관리자 승인을 기다리는 중이에요"
_DETAIL_LEFT = "그룹에서 나왔거나 내보내졌어요"
_DETAIL_DUPLICATE = "이 계정에 이미 등록된 그룹이에요."
_DETAIL_NO_LINK = "가입할 링크가 없어요. 그룹 링크를 다시 넣어 주세요."
_DETAIL_WAITING_FLOOD = "텔레그램 요청 제한이 풀리면 다시 시도해요."
_DETAIL_NO_SESSION = "저장된 세션이 없어요. 다시 로그인해 주세요."
_DETAIL_BAD_SESSION = "저장된 세션을 읽을 수 없어요. 다시 로그인해 주세요."
_DETAIL_FLOOD = "텔레그램이 요청을 잠시 제한했어요. 제한이 풀리면 이어서 진행해요."
_DETAIL_CONNECT_LIMITED = "텔레그램이 접속을 잠시 제한했어요. 제한이 풀리면 다시 연결해요."
"""접속 자체가 제한됐을 때의 상태 설명. start() 가 이 값을 보고, 재시작 뒤에도 제한이 풀릴 때까지 접속을 미룬다."""

_MSG_DISCONNECTED = "텔레그램과 연결이 끊겼어요. 곧 다시 연결해요."
_MSG_UNEXPECTED = "예상하지 못한 문제로 연결이 끊겼어요. 곧 다시 연결해요."
_MSG_TIMEOUT = "텔레그램이 제때 응답하지 않았어요. 잠시 뒤에 다시 시도해요."
_MSG_NOT_CONNECTED = "계정이 연결돼 있지 않아요. 연결된 뒤에 다시 시도해 주세요."
_MSG_SAME_USER = "이미 등록된 다른 계정과 같은 텔레그램 계정의 세션이에요. 이 계정은 지워 주세요."


@dataclass(frozen=True)
class EngineTimings:
    """엔진이 기다리는 시간들(초). 테스트에서는 짧게 바꿔 쓴다."""

    tick: float = 1.0
    """일꾼이 할 일을 살피는 간격이자, 기다리는 동안 시계를 다시 보는 간격."""
    call_timeout: float = 60.0
    """게이트웨이 호출 하나에 허용하는 시간."""
    reconnect_backoff: tuple[float, ...] = (5.0, 15.0, 30.0, 60.0, 120.0, 300.0)
    """연결 실패가 이어질 때 다시 붙기까지 쉬는 시간. 마지막 값을 계속 쓴다."""
    stable_after: float = 60.0
    """연결이 이만큼 유지됐으면 다음 실패는 처음부터 다시 센다."""
    error_pause: float = 5.0
    """대기열 일꾼이 예상하지 못한 오류를 만난 뒤 쉬는 시간(같은 오류로 로그가 넘치지 않게 한다)."""
    credentials_retry: float = 60.0
    join_network_retry: float = 60.0
    join_retry_delays: tuple[float, ...] = (300.0, 1800.0)
    """일시적인 가입 실패 뒤에 다시 시도하기까지의 시간. 다 쓰면 실패로 확정한다."""
    reconcile_delay: float = 30.0
    """연결된 뒤 입장 요청을 처음 확인하기까지의 시간."""
    reconcile_interval: float = 300.0
    reconcile_spacing: float = 3.0
    """입장 요청 확인 호출 사이에 두는 최소 간격."""
    refresh_interval: float = 6 * 3600.0
    """가입된 그룹 목록을 텔레그램과 맞춰 보는 간격."""

    def __post_init__(self) -> None:
        if not self.reconnect_backoff:
            raise ValueError("reconnect_backoff 에는 값이 하나 이상 있어야 해요.")


@dataclass(eq=False)
class _Runtime:
    """계정 하나의 실행 상태. 연결 태스크가 살아 있는 동안만 쓴다."""

    account_id: int
    task: asyncio.Task[None] | None = None
    client: AccountClient | None = None
    connected: bool = False
    monitored: dict[int, int] = field(default_factory=dict)
    """tg_chat_id → groups.id. 가입돼 있고 감시가 켜진 그룹만 담는다."""
    map_stale: bool = False
    flood_until: datetime | None = None
    """accounts.flood_until 의 사본. 이 시각 전에는 일꾼이 요청을 보내지 않는다."""
    last_join_at: datetime | None = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    """대기열 일꾼을 바로 깨운다."""
    settings_changed: asyncio.Event = field(default_factory=asyncio.Event)
    map_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    call_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    """이 계정으로 보내는 요청을 한 줄로 세운다."""
    keep_client: bool = False
    """True 면 태스크를 멈출 때 연결을 끊지 않고 parked 에 남긴다(로그아웃에 쓴다)."""
    parked: AccountClient | None = None


@dataclass
class _Streak:
    """이어지는 연결 실패. 쉬는 시간을 늘리고, 같은 실패를 활동 기록에 거듭 남기지 않는 데 쓴다."""

    failures: int = 0
    note: str | None = None


def _clip(value: str | None, length: int) -> str | None:
    return value[:length] if value else None


def _is_account_error(exc: BaseException) -> bool:
    return isinstance(exc, TelegramError) and exc.code in _ACCOUNT_ERRORS


def _flood_seconds(error: TelegramError) -> int:
    """요청 제한이 풀리기까지 기다릴 시간(초)."""
    if error.retry_after is None:
        return DEFAULT_FLOOD_WAIT_SECONDS
    return max(1, error.retry_after)


def _format_wait(seconds: float) -> str:
    """기다릴 시간을 읽기 좋게 쓴다. 한 시간이 넘으면 분 단위로 올림한다."""
    total = max(1, round(seconds))
    if total < 60:
        return f"{total}초"
    if total < 3600:
        minutes, rest = divmod(total, 60)
        return f"{minutes}분 {rest}초" if rest else f"{minutes}분"
    hours, minutes = divmod(-(-total // 60), 60)
    return f"{hours}시간 {minutes}분" if minutes else f"{hours}시간"


def _format_clock(moment: datetime, now: datetime, zone: tzinfo) -> str:
    """콘솔 시간대의 시각. 오늘이 아니면 날짜도 붙인다."""
    local, today = moment.astimezone(zone), now.astimezone(zone)
    if local.date() == today.date():
        return f"{local:%H:%M}"
    return f"{local.month}월 {local.day}일 {local:%H:%M}"


def _target_of(group: Group) -> LinkTarget | None:
    """그룹 행의 링크 정보로 가입 대상을 만든다. 링크가 없으면 None."""
    if group.link_kind == LinkKind.INVITE:
        return LinkTarget(LinkKind.INVITE, group.invite_hash) if group.invite_hash else None
    if group.public_username:
        return LinkTarget(LinkKind.PUBLIC, group.public_username)
    return None


def _fill_joined(group: Group, chat: TgChat, now: datetime) -> None:
    group.status = GroupStatus.JOINED
    group.tg_chat_id = chat.id
    group.title = _clip(chat.title, 255) or group.title
    group.kind = chat.kind
    if chat.member_count is not None:
        group.member_count = chat.member_count
    group.joined_at = now
    group.status_detail = _DETAIL_CHANNEL if chat.kind == GroupKind.CHANNEL else None
    group.error_code = None
    group.attempts = 0
    group.next_attempt_at = None


async def _nap(event: asyncio.Event, seconds: float) -> bool:
    """event 가 켜지거나 seconds 가 지날 때까지 쉰다. event 로 깼으면 꺼 두고 True."""
    try:
        await asyncio.wait_for(event.wait(), seconds)
    except TimeoutError:
        return False
    event.clear()
    return True


class Engine:
    def __init__(
        self,
        *,
        db: Database,
        bus: EventBus,
        settings: SettingsStore,
        secrets: Secrets,
        gateway: TelegramGateway,
        collector: Collector,
        logbook: Logbook,
        clock: Clock = utcnow,
        timings: EngineTimings | None = None,
    ) -> None:
        self.db = db
        self.bus = bus
        self.settings = settings
        self.secrets = secrets
        self.gateway = gateway
        self.collector = collector
        self.logbook = logbook
        self._clock = clock
        self._timings = timings or EngineTimings()

        self._started = False
        self._ops = asyncio.Lock()
        """켜기·끄기와 계정 단위 조작을 한 줄로 세운다. 연결 태스크는 이 락을 잡지 않는다."""
        self._runtimes: dict[int, _Runtime] = {}
        self._connect_hold: dict[int, datetime] = {}
        """접속이 제한된 계정 → 다시 접속해도 되는 시각. 연결 태스크를 새로 띄워도 유지된다."""

    # --- 수명 주기 ---------------------------------------------------------

    async def start(self) -> None:
        """엔진을 켠다. enabled 이고 세션이 있는 계정마다 연결 태스크를 띄우고 수집기를 시작한다.

        이미 켜져 있으면 아무것도 하지 않는다.
        """
        async with self._ops:
            if self._started:
                return
            account_ids = await self._restore()
            await self.collector.start()
            self._started = True
            for account_id in account_ids:
                self._spawn(account_id)
        logger.info("엔진을 켰어요. 계정 %d개를 연결해요", len(account_ids))

    async def stop(self) -> None:
        """모든 태스크를 멈추고 연결을 끊는다. 수집기도 멈춘다(flush 포함)."""
        async with self._ops:
            if not self._started:
                return
            self._started = False
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()
            tasks = {rt.task for rt in runtimes if rt.task is not None}
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.wait(tasks)
            for task in tasks:
                if not task.cancelled() and (error := task.exception()) is not None:
                    logger.error(
                        "연결 태스크 %s 이(가) 오류로 끝났어요", task.get_name(), exc_info=error
                    )
            try:
                await self._mark_offline()
            except Exception:
                logger.exception("엔진을 멈추면서 계정 상태를 '꺼짐'으로 바꾸지 못했어요")
            try:
                await self.collector.stop()
            except Exception:
                logger.exception("엔진을 멈추면서 수집기를 멈추지 못했어요")
            try:
                await self._call(self.gateway.close())
            except Exception:
                logger.exception("엔진을 멈추면서 게이트웨이를 닫지 못했어요")
        logger.info("엔진을 멈췄어요")

    async def _restore(self) -> list[int]:
        """지난 실행이 남긴 상태를 바로잡고, 연결할 계정 id 를 돌려준다."""
        now = self._clock()
        runnable: list[int] = []
        async with self.db.session() as session:
            await session.execute(
                update(Group)
                .where(Group.status == GroupStatus.JOINING)
                .values(status=GroupStatus.QUEUED),
                execution_options={"synchronize_session": False},
            )
            accounts = (await session.scalars(select(Account).order_by(Account.id))).all()
            for account in accounts:
                if not account.enabled:
                    account.status, account.status_detail = AccountStatus.OFFLINE, None
                elif not account.session_enc:
                    account.status = AccountStatus.REAUTH_REQUIRED
                    account.status_detail = _DETAIL_NO_SESSION
                else:
                    if (
                        account.status == AccountStatus.FLOOD_WAIT
                        and account.status_detail == _DETAIL_CONNECT_LIMITED
                        and account.flood_until is not None
                        and account.flood_until > now
                    ):
                        self._connect_hold[account.id] = account.flood_until
                    account.status, account.status_detail = AccountStatus.CONNECTING, None
                    runnable.append(account.id)
            await session.commit()
        return runnable

    async def _mark_offline(self) -> None:
        async with self.db.session() as session:
            await session.execute(
                update(Account)
                .where(Account.status.in_(_LIVE_STATUSES))
                .values(status=AccountStatus.OFFLINE, status_detail=None),
                execution_options={"synchronize_session": False},
            )
            await session.commit()

    # --- 로그인 · 세션 불러오기 --------------------------------------------
    # 텔레그램 쪽 실패는 TelegramError 를 그대로 올린다(라우터가 HTTP 오류로 바꾼다).

    async def start_login(self, phone: str) -> PendingLogin:
        return await self._call(self.gateway.start_login(phone))

    async def submit_code(self, login_id: str, code: str) -> tuple[LoginResult, Account | None]:
        """코드를 넣는다. 로그인이 끝나면(status=done) 계정을 저장·연결하고 함께 돌려준다."""
        result = await self._call(self.gateway.submit_code(login_id, code))
        return result, await self._account_for(result)

    async def submit_password(
        self, login_id: str, password: str
    ) -> tuple[LoginResult, Account | None]:
        result = await self._call(self.gateway.submit_password(login_id, password))
        return result, await self._account_for(result)

    async def cancel_login(self, login_id: str) -> None:
        await self._call(self.gateway.cancel_login(login_id))

    async def import_session(self, data: str | bytes, label: str | None = None) -> Account:
        """세션 문자열(str) 또는 .session 파일 내용(bytes)을 불러와 계정으로 저장·연결한다.

        같은 텔레그램 유저의 계정이 이미 있으면 새로 만들지 않고 그 계정의 세션을 바꿔 끼운다
        (다시 로그인하는 경우). 로그인 완료 때도 같은 규칙이다.
        """
        result = await self._call(self.gateway.import_session(data))
        return await self._save_login(result, label)

    async def _account_for(self, result: LoginResult) -> Account | None:
        if result.status != "done":
            return None
        return await self._save_login(result, None)

    async def _save_login(self, result: LoginResult, label: str | None) -> Account:
        """로그인 결과를 계정으로 저장하고 연결 태스크를 (다시) 띄운다."""
        user, session_text = result.user, result.session
        if result.status != "done" or user is None or not session_text:
            raise TelegramError(
                TgErrorCode.UNKNOWN,
                "로그인은 됐는데 계정 정보를 받지 못했어요. 처음부터 다시 시도해 주세요.",
            )
        name = (label or "").strip()[:64]
        async with self._ops:
            async with self.db.session() as session:
                existing_id = await session.scalar(
                    select(Account.id).where(Account.tg_user_id == user.id)
                )
            if existing_id is not None:
                # 돌고 있던 연결이 옛 세션을 다시 저장하지 못하게, 새 세션을 쓰기 전에 멈춘다.
                await self._stop_runner(existing_id)
            async with self.db.session() as session:
                account = (
                    await session.get(Account, existing_id) if existing_id is not None else None
                )
                created = account is None
                if account is None:
                    account = Account(tg_user_id=user.id)
                    session.add(account)
                if name:
                    account.label = name
                account.session_enc = self.secrets.encrypt(session_text)
                account.enabled = True
                account.first_name = _clip(user.first_name, 128)
                account.last_name = _clip(user.last_name, 128)
                account.username = _clip(user.username, 64)
                if user.phone:
                    account.phone = user.phone[:32]
                account.status = (
                    AccountStatus.CONNECTING if self._started else AccountStatus.OFFLINE
                )
                account.status_detail = None
                await session.commit()
            self.collector.invalidate()  # 내 계정 id 가 바뀌었다
            if self._started:
                self._spawn(account.id)
        await self._publish_account(account.id)
        await self.logbook.info(
            "계정을 추가했어요." if created else "다시 로그인해서 계정의 세션을 바꿨어요.",
            category=LogCategory.ACCOUNT,
            account_id=account.id,
        )
        return account

    # --- 계정 제어 ---------------------------------------------------------

    async def set_account_enabled(self, account_id: int, enabled: bool) -> None:
        """계정을 켜거나 끈다. 끄면 연결을 끊고 status=offline, 켜면 다시 연결한다."""
        async with self._ops:
            found = await self._relaunch(account_id, enabled=enabled)
        if found:
            await self.logbook.info(
                "계정을 켰어요." if enabled else "계정을 껐어요.",
                category=LogCategory.ACCOUNT,
                account_id=account_id,
            )

    async def reconnect(self, account_id: int) -> None:
        """연결을 끊었다가 다시 붙인다."""
        async with self._ops:
            await self._relaunch(account_id)

    async def remove_account(self, account_id: int, *, log_out: bool = False) -> None:
        """계정을 지운다(그룹 행도 함께). log_out=True 면 텔레그램에서도 세션을 로그아웃한다."""
        async with self._ops:
            client = await self._stop_runner(account_id, keep_client=log_out)
            try:
                async with self.db.session() as session:
                    account = await session.get(Account, account_id)
                if account is None:
                    logger.warning("없는 계정 %s 을(를) 지우려고 했어요", account_id)
                    return
                name = account_display_name(account)
                if log_out:
                    await self._log_out(account, client, name)
            finally:
                if client is not None:
                    await self._disconnect(client)
            async with self.db.session() as session:
                await session.execute(delete(Account).where(Account.id == account_id))
                await session.commit()
            self._connect_hold.pop(account_id, None)
            self.collector.invalidate()  # 내 계정 id 가 바뀌었다
        await self.logbook.info(f"'{name}' 계정을 지웠어요.", category=LogCategory.ACCOUNT)

    def is_connected(self, account_id: int) -> bool:
        rt = self._runtimes.get(account_id)
        return rt is not None and rt.connected

    async def list_dialogs(self, account_id: int) -> list[TgChat]:
        """계정이 이미 들어가 있는 그룹 목록. 연결돼 있지 않으면 TelegramError(NETWORK)."""
        rt = self._runtimes.get(account_id)
        client = rt.client if rt is not None and rt.connected else None
        if rt is None or client is None:
            raise TelegramError(TgErrorCode.NETWORK, _MSG_NOT_CONNECTED)
        async with rt.call_lock:
            self._refuse_while_flooding(rt)
            try:
                return await self._call(client.list_groups())
            except TelegramError as exc:
                if exc.code == TgErrorCode.FLOOD_WAIT:
                    await self._enter_flood(rt, exc)
                raise

    # --- 그룹 --------------------------------------------------------------

    def notify_groups_changed(self, account_id: int | None = None) -> None:
        """그룹 행이 추가·변경·삭제됐음을 알린다.

        감시 대상 맵을 다시 읽고 가입 대기열을 깨운다. account_id 를 주면 그 계정만.
        """
        for rt in self._runtimes_for(account_id):
            rt.map_stale = True
            rt.wake.set()

    async def leave_group(self, group_id: int) -> None:
        """텔레그램에서 그룹을 나간다(가능하면). 행은 지우지 않는다. 실패해도 예외를 올리지 않는다."""
        account_id: int | None = None
        try:
            async with self.db.session() as session:
                group = await session.get(Group, group_id)
            if group is None or group.tg_chat_id is None:
                return
            account_id = group.account_id
            await self._leave(account_id, group.tg_chat_id)
        except TelegramError as exc:
            logger.warning("그룹 %s 에서 나가지 못했어요: %s", group_id, exc.message)
            await self.logbook.warning(
                f"텔레그램에서 그룹을 나가지 못했어요. {exc.message}",
                category=LogCategory.GROUP,
                account_id=account_id,
                group_id=group_id,
            )
        except Exception:
            logger.exception("그룹 %s 에서 나가다 예상하지 못한 문제가 생겼어요", group_id)

    async def _leave(self, account_id: int, tg_chat_id: int) -> None:
        rt = self._runtimes.get(account_id)
        client = rt.client if rt is not None and rt.connected else None
        if rt is None or client is None:
            raise TelegramError(TgErrorCode.NETWORK, "계정이 연결돼 있지 않아요.")
        async with rt.call_lock:
            self._refuse_while_flooding(rt)
            try:
                await self._call(client.leave(tg_chat_id))
            except TelegramError as exc:
                if exc.code == TgErrorCode.FLOOD_WAIT:
                    await self._enter_flood(rt, exc)
                raise

    # --- 설정 --------------------------------------------------------------

    def notify_settings_changed(self) -> None:
        """설정이 바뀌었음을 알린다(가입 간격, 계정당 그룹 수, API 키 등)."""
        for rt in self._runtimes.values():
            rt.settings_changed.set()
            rt.wake.set()

    # --- 연결 태스크 관리 ---------------------------------------------------

    def _runtimes_for(self, account_id: int | None) -> list[_Runtime]:
        if account_id is None:
            return list(self._runtimes.values())
        rt = self._runtimes.get(account_id)
        return [rt] if rt is not None else []

    def _spawn(self, account_id: int) -> None:
        rt = _Runtime(account_id)
        self._runtimes[account_id] = rt
        rt.task = asyncio.create_task(self._run_account(rt), name=f"engine-account-{account_id}")

    async def _stop_runner(
        self, account_id: int, *, keep_client: bool = False
    ) -> AccountClient | None:
        """연결 태스크를 멈추고 끝날 때까지 기다린다.

        keep_client=True 면 연결돼 있던 클라이언트를 끊지 않고 돌려준다(없으면 None).
        """
        rt = self._runtimes.pop(account_id, None)
        if rt is None or rt.task is None:
            return None
        rt.keep_client = keep_client
        rt.task.cancel()
        await asyncio.wait({rt.task})
        if not rt.task.cancelled() and (error := rt.task.exception()) is not None:
            logger.error("계정 %s 의 연결 태스크가 오류로 끝났어요", account_id, exc_info=error)
        return rt.parked

    async def _relaunch(self, account_id: int, *, enabled: bool | None = None) -> bool:
        """연결 태스크를 멈추고, 계정이 켜져 있고 세션이 있으면 새로 띄운다.

        enabled 를 주면 먼저 그 값으로 켜거나 끈다. 계정이 없으면 False.
        """
        await self._stop_runner(account_id)
        async with self.db.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                logger.warning("없는 계정 %s 을(를) 다시 연결하려고 했어요", account_id)
                return False
            if enabled is not None:
                account.enabled = enabled
            runnable = account.enabled and bool(account.session_enc) and self._started
            if runnable:
                account.status, account.status_detail = AccountStatus.CONNECTING, None
            elif account.enabled and not account.session_enc:
                account.status = AccountStatus.REAUTH_REQUIRED
                account.status_detail = _DETAIL_NO_SESSION
            else:
                account.status, account.status_detail = AccountStatus.OFFLINE, None
            await session.commit()
        if runnable:
            self._spawn(account_id)
        await self._publish_account(account_id)
        return True

    async def _log_out(self, account: Account, client: AccountClient | None, name: str) -> None:
        """텔레그램에서 세션을 로그아웃한다. 실패는 기록만 하고 올리지 않는다.

        client 는 살아 있는 연결이다. 없으면 임시 연결을 만들어 쓴다.
        """
        temporary: AccountClient | None = None
        try:
            if self._limited(account):
                raise TelegramError(
                    TgErrorCode.FLOOD_WAIT,
                    "텔레그램 요청 제한 중이라 로그아웃 요청을 보내지 않았어요.",
                )
            if client is None:
                session_text = (
                    self.secrets.decrypt(account.session_enc) if account.session_enc else None
                )
                if session_text is None:
                    return  # 로그아웃할 세션이 없다
                client = temporary = self.gateway.create_client(account.id, session_text)
                await self._call(temporary.connect())
            await self._call(client.log_out())
        except TelegramError as exc:
            if exc.code == TgErrorCode.SESSION_INVALID:
                logger.info("계정 %s 의 세션은 이미 무효라 로그아웃할 것이 없어요", account.id)
                return
            logger.warning("계정 %s 을(를) 로그아웃하지 못했어요: %s", account.id, exc.message)
            await self._note_log_out_failure(name, exc.message)
        except Exception:
            logger.exception(
                "계정 %s 을(를) 로그아웃하다 예상하지 못한 문제가 생겼어요", account.id
            )
            await self._note_log_out_failure(name, "예상하지 못한 문제가 생겼어요.")
        finally:
            if temporary is not None:
                await self._disconnect(temporary)

    def _limited(self, account: Account) -> bool:
        """이 계정이 지금 요청 제한(또는 접속 제한) 중인지."""
        now = self._clock()
        hold = self._connect_hold.get(account.id)
        return (account.flood_until is not None and account.flood_until > now) or (
            hold is not None and hold > now
        )

    async def _note_log_out_failure(self, name: str, reason: str) -> None:
        await self.logbook.warning(
            f"'{name}' 계정을 텔레그램에서 로그아웃하지 못했어요. {reason} "
            "텔레그램 앱의 기기 목록에서 직접 종료해 주세요.",
            category=LogCategory.ACCOUNT,
        )

    # --- 연결 태스크 --------------------------------------------------------

    async def _run_account(self, rt: _Runtime) -> None:
        """계정 하나의 연결을 유지한다. 다시 로그인해야 하거나 계정을 쓸 수 없게 되면 끝난다."""
        streak = _Streak()
        try:
            while await self._run_cycle(rt, streak):
                pass
        finally:
            if self._runtimes.get(rt.account_id) is rt:
                del self._runtimes[rt.account_id]

    async def _run_cycle(self, rt: _Runtime, streak: _Streak) -> bool:
        """한 번 연결해서 끊길 때까지 돌린다. 다시 연결해야 하면 True."""
        try:
            return await self._connect_and_serve(rt, streak)
        except Exception:
            logger.exception(
                "계정 %s 의 연결 태스크에서 예상하지 못한 문제가 생겼어요", rt.account_id
            )
            await self._pause(self._next_backoff(streak))
            return True

    async def _connect_and_serve(self, rt: _Runtime, streak: _Streak) -> bool:
        await self._wait_out_connect_hold(rt)
        # 여기서부터 바뀐 설정만 '즉시 다시 시도'의 계기로 본다.
        rt.settings_changed.clear()
        connected_at: datetime | None = None
        try:
            client = await self._connect(rt)
            if client is None:
                return False
            connected_at = self._clock()
            streak.note = None
            await self._serve(rt, client)
            error = TelegramError(TgErrorCode.NETWORK, _MSG_DISCONNECTED)
        except TelegramError as exc:
            error = exc
        except Exception:
            logger.exception("계정 %s 의 연결이 예상하지 못한 문제로 끊겼어요", rt.account_id)
            error = TelegramError(TgErrorCode.UNKNOWN, _MSG_UNEXPECTED)
        finally:
            await self._close(rt)

        if connected_at is not None:
            lasted = (self._clock() - connected_at).total_seconds()
            if lasted >= self._timings.stable_after:
                streak.failures = 0
        return await self._after_failure(rt, error, streak)

    async def _wait_out_connect_hold(self, rt: _Runtime) -> None:
        """접속이 제한돼 있으면 풀릴 때까지 접속하지 않고 기다린다."""
        until = self._connect_hold.get(rt.account_id)
        if until is None:
            return
        if self._clock() < until:
            await self._update_account(
                rt.account_id,
                status=AccountStatus.FLOOD_WAIT,
                status_detail=_DETAIL_CONNECT_LIMITED,
                flood_until=until,
            )
            await self._wait_until(until)
        self._connect_hold.pop(rt.account_id, None)

    async def _connect(self, rt: _Runtime) -> AccountClient | None:
        """접속하고 계정 정보를 저장한다. 연결할 수 없는 계정이면 None."""
        now = self._clock()
        async with self.db.session() as session:
            account = await session.get(Account, rt.account_id)
            if account is None or not account.enabled:
                return None
            session_text = (
                self.secrets.decrypt(account.session_enc) if account.session_enc else None
            )
            if session_text is None:
                account.status = AccountStatus.REAUTH_REQUIRED
                account.status_detail = (
                    _DETAIL_BAD_SESSION if account.session_enc else _DETAIL_NO_SESSION
                )
            else:
                account.status, account.status_detail = AccountStatus.CONNECTING, None
            if account.flood_until is not None and account.flood_until <= now:
                account.flood_until = None
            detail = account.status_detail
            await session.commit()
        await self._publish_account(rt.account_id)
        if session_text is None:
            await self.logbook.error(
                detail or _DETAIL_NO_SESSION,
                category=LogCategory.ACCOUNT,
                account_id=rt.account_id,
            )
            return None

        client = self.gateway.create_client(rt.account_id, session_text)
        rt.client = client
        me = await self._call(client.connect())
        if not await self._on_connected(rt, client, me, session_text):
            return None
        return client

    async def _on_connected(
        self, rt: _Runtime, client: AccountClient, me: TgUser, session_text: str
    ) -> bool:
        """접속에 성공한 계정의 정보를 저장하고 메시지를 받기 시작한다. 계정이 없어졌으면 False."""
        now = self._clock()
        current = client.export_session()
        async with self.db.session() as session:
            account = await session.get(Account, rt.account_id)
            if account is None:
                return False
            identity_changed = account.tg_user_id != me.id
            if identity_changed:
                taken = await session.scalar(
                    select(Account.id).where(Account.tg_user_id == me.id).limit(1)
                )
                if taken is not None:
                    raise TelegramError(TgErrorCode.SESSION_INVALID, _MSG_SAME_USER, permanent=True)
            account.tg_user_id = me.id
            account.first_name = _clip(me.first_name, 128)
            account.last_name = _clip(me.last_name, 128)
            account.username = _clip(me.username, 64)
            if not account.phone and me.phone:
                account.phone = me.phone[:32]
            account.last_connected_at = now
            flooding = account.flood_until is not None and account.flood_until > now
            if not flooding:
                account.flood_until = None
            account.status = AccountStatus.FLOOD_WAIT if flooding else AccountStatus.ACTIVE
            account.status_detail = None
            if current and current != session_text:
                account.session_enc = self.secrets.encrypt(current)
            rt.flood_until = account.flood_until
            rt.last_join_at = account.last_join_at
            await session.commit()
        if identity_changed:
            self.collector.invalidate()  # 내 계정 id 가 바뀌었다
        await self._publish_account(rt.account_id)
        await self.logbook.info(
            "텔레그램에 연결됐어요.", category=LogCategory.ACCOUNT, account_id=rt.account_id
        )
        await self._reload_monitored(rt)
        client.set_message_handler(partial(self._on_message, rt))
        rt.connected = True
        return True

    async def _serve(self, rt: _Runtime, client: AccountClient) -> None:
        """연결이 끊길 때까지 일꾼들을 돌린다.

        정상적으로 끊기면 그냥 돌아오고, 세션·계정 문제로 끊겼으면 그 TelegramError 를 올린다.
        """
        account_id = rt.account_id
        tasks = [
            asyncio.create_task(client.wait_closed(), name=f"engine-closed-{account_id}"),
            asyncio.create_task(self._queue_loop(rt, client), name=f"engine-queue-{account_id}"),
            asyncio.create_task(
                self._reconcile_loop(rt, client), name=f"engine-reconcile-{account_id}"
            ),
        ]
        errors: list[BaseException | None] = []
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.wait(tasks)
            # 결과를 꺼내 두지 않으면 asyncio 가 '확인하지 않은 예외'라고 경고한다.
            errors = [task.exception() for task in tasks if not task.cancelled()]
        for error in errors:
            if error is not None:
                raise error

    async def _close(self, rt: _Runtime) -> None:
        """연결을 정리한다. 취소되는 중에도 끝까지 돈다."""
        client, rt.client = rt.client, None
        was_connected, rt.connected = rt.connected, False
        rt.monitored = {}
        if client is not None:
            client.set_message_handler(None)
            if rt.keep_client and was_connected:
                rt.parked = client
            else:
                await self._disconnect(client)
        try:
            await self._requeue_joining(rt.account_id)
        except Exception:
            logger.exception(
                "계정 %s 의 가입 시도 중이던 그룹을 대기열로 돌려놓지 못했어요", rt.account_id
            )

    async def _disconnect(self, client: AccountClient) -> None:
        try:
            await self._call(client.disconnect())
        except Exception:
            logger.warning("계정 %s 의 연결을 끊지 못했어요", client.account_id, exc_info=True)

    async def _after_failure(self, rt: _Runtime, error: TelegramError, streak: _Streak) -> bool:
        """연결이 실패했거나 끊긴 뒤의 처리. 다시 연결해야 하면 (필요한 만큼 기다린 뒤) True."""
        account_id, code = rt.account_id, error.code
        detail = _clip(error.message, 500)
        if code in (TgErrorCode.SESSION_INVALID, TgErrorCode.BANNED):
            status = (
                AccountStatus.BANNED
                if code == TgErrorCode.BANNED
                else AccountStatus.REAUTH_REQUIRED
            )
            await self._update_account(account_id, status=status, status_detail=detail)
            await self.logbook.error(
                error.message, category=LogCategory.ACCOUNT, account_id=account_id
            )
            return False

        if code == TgErrorCode.FLOOD_WAIT:
            seconds = _flood_seconds(error)
            until = self._clock() + timedelta(seconds=seconds)
            if rt.flood_until is not None and rt.flood_until > until:
                until = rt.flood_until
            self._connect_hold[account_id] = until
            await self.logbook.warning(
                f"텔레그램이 접속을 잠시 제한했어요. {_format_wait(seconds)} 뒤에 다시 연결해요.",
                category=LogCategory.ACCOUNT,
                account_id=account_id,
            )
            return True

        await self._update_account(account_id, status=AccountStatus.ERROR, status_detail=detail)
        if error.message != streak.note:
            streak.note = error.message
            await self.logbook.warning(
                error.message, category=LogCategory.ACCOUNT, account_id=account_id
            )
        if code == TgErrorCode.API_CREDENTIALS:
            await self._pause(self._timings.credentials_retry, wake=rt.settings_changed)
        else:
            await self._pause(self._next_backoff(streak))
        return True

    def _next_backoff(self, streak: _Streak) -> float:
        schedule = self._timings.reconnect_backoff
        delay = schedule[min(streak.failures, len(schedule) - 1)]
        streak.failures += 1
        return delay

    # --- 메시지 ------------------------------------------------------------

    async def _on_message(self, rt: _Runtime, message: IncomingMessage) -> None:
        group_id = rt.monitored.get(message.chat_id)
        if group_id is not None:
            await self.collector.handle(message, group_id)

    async def _reload_monitored(self, rt: _Runtime) -> None:
        """감시 대상 맵을 DB 에서 다시 읽는다. 실패하면 다음 틱에 대기열 일꾼이 다시 읽는다."""
        async with rt.map_lock:
            rt.map_stale = False
            try:
                async with self.db.session() as session:
                    rows = (
                        await session.execute(
                            select(Group.tg_chat_id, Group.id).where(
                                Group.account_id == rt.account_id,
                                Group.status == GroupStatus.JOINED,
                                Group.monitoring.is_(True),
                                Group.tg_chat_id.is_not(None),
                            )
                        )
                    ).all()
            except BaseException:
                rt.map_stale = True
                raise
            rt.monitored = {chat_id: group_id for chat_id, group_id in rows}

    # --- 대기열 일꾼 --------------------------------------------------------

    async def _queue_loop(self, rt: _Runtime, client: AccountClient) -> None:
        while True:
            try:
                await self._lift_flood(rt)
                if rt.map_stale:
                    await self._reload_monitored(rt)
                await self._join_next(rt, client)
            except Exception as exc:
                if _is_account_error(exc):
                    raise
                logger.exception("계정 %s 의 가입 대기열을 처리하다 문제가 생겼어요", rt.account_id)
                await self._pause(self._timings.error_pause)
            await _nap(rt.wake, self._timings.tick)

    async def _lift_flood(self, rt: _Runtime) -> None:
        """요청 제한 시각이 지났으면 계정을 정상 상태로 돌린다."""
        if rt.flood_until is None or self._clock() < rt.flood_until:
            return
        async with self.db.session() as session:
            account = await session.get(Account, rt.account_id)
            if account is not None:
                account.flood_until = None
                if account.status == AccountStatus.FLOOD_WAIT:
                    account.status, account.status_detail = AccountStatus.ACTIVE, None
                await session.commit()
        rt.flood_until = None
        await self._publish_account(rt.account_id)
        await self.logbook.info(
            "텔레그램 요청 제한이 풀려서 다시 진행해요.",
            category=LogCategory.ACCOUNT,
            account_id=rt.account_id,
        )

    def _flooding(self, rt: _Runtime) -> bool:
        return rt.flood_until is not None and self._clock() < rt.flood_until

    def _refuse_while_flooding(self, rt: _Runtime) -> None:
        """요청 제한 중이면 요청을 보내지 않고 FLOOD_WAIT 오류를 올린다."""
        if rt.flood_until is None:
            return
        remaining = (rt.flood_until - self._clock()).total_seconds()
        if remaining > 0:
            raise TelegramError(
                TgErrorCode.FLOOD_WAIT,
                f"텔레그램 요청 제한으로 쉬는 중이에요. {_format_wait(remaining)} 뒤에 다시 시도해 주세요.",
                retry_after=math.ceil(remaining),
            )

    async def _enter_flood(self, rt: _Runtime, error: TelegramError) -> None:
        """요청 제한에 걸렸다. 풀리는 시각까지 이 계정으로는 요청을 보내지 않는다."""
        seconds = _flood_seconds(error)
        now = self._clock()
        until = now + timedelta(seconds=seconds)
        if rt.flood_until is not None and rt.flood_until > until:
            until = rt.flood_until
        rt.flood_until = until  # 다른 일꾼이 바로 보도록 기다리기 전에 먼저 적는다
        await self._update_account(
            rt.account_id,
            status=AccountStatus.FLOOD_WAIT,
            status_detail=_DETAIL_FLOOD,
            flood_until=until,
        )
        zone = (await self.settings.get()).tzinfo
        await self.logbook.warning(
            "텔레그램이 요청을 잠시 제한했어요. "
            f"{_format_wait(seconds)} 뒤({_format_clock(until, now, zone)})에 이어서 진행해요.",
            category=LogCategory.ACCOUNT,
            account_id=rt.account_id,
        )

    async def _join_next(self, rt: _Runtime, client: AccountClient) -> None:
        """가입 간격이 지났으면 대기열에서 가장 오래된 그룹 하나에 들어가 본다."""
        if self._flooding(rt) or not await self._join_interval_passed(rt):
            return
        async with rt.call_lock:
            if self._flooding(rt):
                return
            picked = await self._pick_queued(rt)
            if picked is None:
                return
            group_id, target = picked
            try:
                result = await self._call(client.join(target))
            except TelegramError as exc:
                await self._on_join_error(rt, group_id, exc)
                return
            except Exception:
                logger.exception("그룹 %s 에 가입하다 예상하지 못한 문제가 생겼어요", group_id)
                unexpected = TelegramError(
                    TgErrorCode.UNKNOWN, "예상하지 못한 문제로 가입하지 못했어요."
                )
                await self._on_join_error(rt, group_id, unexpected)
                return
            await self._on_join_result(rt, group_id, result)

    async def _join_interval_passed(self, rt: _Runtime) -> bool:
        if rt.last_join_at is None:
            return True
        interval = (await self.settings.get()).join_interval_seconds
        return self._clock() - rt.last_join_at >= timedelta(seconds=interval)

    async def _pick_queued(self, rt: _Runtime) -> tuple[int, LinkTarget] | None:
        """차례가 된 그룹을 '가입 시도 중'으로 바꾸고 (그룹 id, 가입 대상)을 돌려준다."""
        now = self._clock()
        async with self.db.session() as session:
            group = (
                await session.scalars(
                    select(Group)
                    .where(
                        Group.account_id == rt.account_id,
                        Group.status == GroupStatus.QUEUED,
                        or_(Group.next_attempt_at.is_(None), Group.next_attempt_at <= now),
                    )
                    .order_by(Group.created_at, Group.id)
                    .limit(1)
                )
            ).first()
            if group is None:
                return None
            account = await session.get(Account, rt.account_id)
            if account is None:
                return None
            group_id, target = group.id, _target_of(group)
            if target is None:
                group.status = GroupStatus.FAILED
                group.error_code = NO_LINK_ERROR_CODE
                group.status_detail = _DETAIL_NO_LINK
                group.next_attempt_at = None
            else:
                group.status = GroupStatus.JOINING
                # 시도를 시작할 때 먼저 적어 둔다. 도중에 멈춰도 가입 간격이 지켜진다.
                account.last_join_at = now
            await session.commit()
        await self._publish_group(group_id)
        if target is None:
            await self._publish_account(rt.account_id)
            await self.logbook.warning(
                f"그룹에 들어가지 못했어요. {_DETAIL_NO_LINK}",
                category=LogCategory.GROUP,
                account_id=rt.account_id,
                group_id=group_id,
            )
            return None
        rt.last_join_at = now
        return group_id, target

    async def _stamp_join(self, session: AsyncSession, rt: _Runtime, now: datetime) -> None:
        """가입 시도가 끝난 시각을 적는다. 다음 시도까지의 간격은 여기서부터 잰다."""
        account = await session.get(Account, rt.account_id)
        if account is not None:
            account.last_join_at = now
        rt.last_join_at = now

    async def _on_join_result(self, rt: _Runtime, group_id: int, result: JoinResult) -> None:
        chat = result.chat
        if result.outcome == JoinOutcome.JOINED and chat is None:
            missing = TelegramError(
                TgErrorCode.UNKNOWN,
                "가입은 됐는데 그룹 정보를 받지 못했어요. 잠시 뒤에 다시 확인할게요.",
            )
            await self._on_join_error(rt, group_id, missing)
            return
        now = self._clock()
        twin_id: int | None = None
        async with self.db.session() as session:
            group = await session.get(Group, group_id)
            await self._stamp_join(session, rt, now)
            if group is not None:
                if chat is not None and result.outcome == JoinOutcome.JOINED:
                    twin_id = await self._mark_joined(session, group, chat, now)
                else:
                    await self._mark_requested(session, group, result)
            await session.commit()
        if group is None:
            await self.logbook.warning(
                "가입하는 사이에 목록에서 지워진 그룹이 있어요. "
                "텔레그램에서는 가입이나 입장 요청이 이미 처리됐을 수 있어요.",
                category=LogCategory.GROUP,
                account_id=rt.account_id,
            )
            return
        if group.status == GroupStatus.REQUESTED:
            await self._publish_group(group_id)
            await self._publish_account(rt.account_id)
            await self.logbook.info(
                "입장 요청을 보냈어요. 관리자가 승인하면 자동으로 가입돼요.",
                category=LogCategory.GROUP,
                account_id=rt.account_id,
                group_id=group_id,
            )
            return
        await self._announce_joined(rt, group, twin_id, "그룹에 들어갔어요.")

    async def _mark_joined(
        self, session: AsyncSession, group: Group, chat: TgChat, now: datetime
    ) -> int | None:
        """group 을 가입된 상태로 만든다.

        같은 계정의 다른 행이 이미 그 방을 가리키면 group 은 중복으로 실패 처리하고,
        방금 멤버인 것을 확인했으니 그 행을 가입 상태로 맞춘 뒤 그 id 를 돌려준다.
        """
        twin = (
            await session.scalars(
                select(Group).where(
                    Group.account_id == group.account_id,
                    Group.tg_chat_id == chat.id,
                    Group.id != group.id,
                )
            )
        ).first()
        if twin is None:
            _fill_joined(group, chat, now)
            return None
        group.status = GroupStatus.FAILED
        group.error_code = DUPLICATE_ERROR_CODE
        group.status_detail = _DETAIL_DUPLICATE
        group.next_attempt_at = None
        if twin.status != GroupStatus.JOINED:
            _fill_joined(twin, chat, now)
        return twin.id

    async def _mark_requested(
        self, session: AsyncSession, group: Group, result: JoinResult
    ) -> None:
        chat = result.chat
        group.status = GroupStatus.REQUESTED
        group.status_detail = _DETAIL_REQUESTED
        group.error_code = None
        group.attempts = 0
        group.next_attempt_at = None
        title = (chat.title if chat is not None else None) or result.title
        if title:
            group.title = title[:255]
        count = chat.member_count if chat is not None else None
        if count is None:
            count = result.member_count
        if count is not None:
            group.member_count = count
        if chat is None:
            return
        group.kind = chat.kind
        taken = await session.scalar(
            select(Group.id)
            .where(
                Group.account_id == group.account_id,
                Group.tg_chat_id == chat.id,
                Group.id != group.id,
            )
            .limit(1)
        )
        # 다른 행이 이미 그 방을 가리키면 id 는 비워 둔다. 승인된 뒤에 중복으로 정리된다.
        if taken is None:
            group.tg_chat_id = chat.id

    async def _announce_joined(
        self, rt: _Runtime, group: Group, twin_id: int | None, message: str
    ) -> None:
        """가입(또는 중복) 처리된 그룹을 감시 대상에 넣고 화면과 활동 기록에 알린다."""
        await self._reload_monitored(rt)  # 알리는 동안 오는 메시지를 놓치지 않게 먼저 읽는다
        await self._publish_group(group.id)
        if twin_id is not None:
            await self._publish_group(twin_id)
        await self._publish_account(rt.account_id)
        if twin_id is None:
            if group.kind == GroupKind.CHANNEL:
                message = f"{message} {_DETAIL_CHANNEL}."
            await self.logbook.info(
                message, category=LogCategory.GROUP, account_id=rt.account_id, group_id=group.id
            )
        else:
            await self.logbook.warning(
                "이미 이 계정에 등록된 그룹이라 따로 추가하지 않았어요.",
                category=LogCategory.GROUP,
                account_id=rt.account_id,
                group_id=group.id,
            )

    async def _on_join_error(self, rt: _Runtime, group_id: int, error: TelegramError) -> None:
        now = self._clock()
        note: str | None = None
        async with self.db.session() as session:
            group = await session.get(Group, group_id)
            await self._stamp_join(session, rt, now)
            if group is not None:
                note = self._apply_join_error(group, error, now)
            await session.commit()
        if group is not None:
            await self._publish_group(group_id)
        if error.code == TgErrorCode.FLOOD_WAIT:
            await self._enter_flood(rt, error)
        elif error.code in _ACCOUNT_ERRORS:
            raise error
        elif note is not None:
            await self._publish_account(rt.account_id)
            await self.logbook.warning(
                note, category=LogCategory.GROUP, account_id=rt.account_id, group_id=group_id
            )

    def _apply_join_error(self, group: Group, error: TelegramError, now: datetime) -> str | None:
        """가입 실패를 그룹 행에 반영한다. 활동 기록에 남길 문장이 있으면 돌려준다."""
        code, detail = error.code, _clip(error.message, 500)
        if code == TgErrorCode.FLOOD_WAIT:
            group.status = GroupStatus.QUEUED
            group.next_attempt_at = now + timedelta(seconds=_flood_seconds(error))
            group.status_detail = _DETAIL_WAITING_FLOOD
            return None
        if code in _ACCOUNT_ERRORS:
            group.status = GroupStatus.QUEUED  # 그룹 탓이 아니다. 계정이 돌아오면 다시 시도한다
            return None
        if code == TgErrorCode.NETWORK:
            group.status = GroupStatus.QUEUED
            group.next_attempt_at = now + timedelta(seconds=self._timings.join_network_retry)
            group.status_detail = detail
            return None
        delays = self._timings.join_retry_delays
        if not error.permanent:
            group.attempts += 1
            if group.attempts <= len(delays):
                delay = delays[group.attempts - 1]
                group.status = GroupStatus.QUEUED
                group.next_attempt_at = now + timedelta(seconds=delay)
                group.error_code = str(code)
                group.status_detail = detail
                return f"그룹 가입에 실패해서 {_format_wait(delay)} 뒤에 다시 시도해요. {error.message}"
        group.status = GroupStatus.FAILED
        group.error_code = str(code)
        group.status_detail = detail
        group.next_attempt_at = None
        return f"그룹에 들어가지 못했어요. {error.message}"

    async def _requeue_joining(self, account_id: int) -> None:
        """'가입 시도 중'에 멈춘 그룹을 대기열로 돌려놓는다(시도하던 태스크가 멈춘 경우)."""
        async with self.db.session() as session:
            group_ids = (
                await session.scalars(
                    select(Group.id).where(
                        Group.account_id == account_id, Group.status == GroupStatus.JOINING
                    )
                )
            ).all()
            if not group_ids:
                return
            await session.execute(
                update(Group).where(Group.id.in_(group_ids)).values(status=GroupStatus.QUEUED),
                execution_options={"synchronize_session": False},
            )
            await session.commit()
        for group_id in group_ids:
            await self._publish_group(group_id)

    # --- 확인 일꾼 ----------------------------------------------------------

    async def _reconcile_loop(self, rt: _Runtime, client: AccountClient) -> None:
        timings = self._timings
        started = self._clock()
        next_check = started + timedelta(seconds=timings.reconcile_delay)
        next_refresh = started + timedelta(seconds=timings.refresh_interval)
        while True:
            await self._wait_until(next_check)
            try:
                await self._check_requested(rt, client)
                if self._clock() >= next_refresh and await self._refresh_memberships(rt, client):
                    next_refresh = self._clock() + timedelta(seconds=timings.refresh_interval)
            except TelegramError as exc:
                if _is_account_error(exc):
                    raise
                logger.warning(
                    "계정 %s 의 그룹 상태를 확인하지 못했어요: %s", rt.account_id, exc.message
                )
            except Exception:
                logger.exception("계정 %s 의 그룹 상태를 확인하다 문제가 생겼어요", rt.account_id)
            next_check = self._clock() + timedelta(seconds=timings.reconcile_interval)

    async def _check_requested(self, rt: _Runtime, client: AccountClient) -> None:
        """입장 요청을 보낸 그룹마다 승인됐는지 확인한다."""
        async with self.db.session() as session:
            groups = (
                await session.scalars(
                    select(Group)
                    .where(
                        Group.account_id == rt.account_id,
                        Group.status == GroupStatus.REQUESTED,
                    )
                    .order_by(Group.id)
                )
            ).all()
        called = False
        for group in groups:
            target = _target_of(group)
            if target is None and group.tg_chat_id is None:
                continue
            if called:
                await self._pause(self._timings.reconcile_spacing)
            async with rt.call_lock:
                if self._flooding(rt):
                    return
                called = True
                try:
                    chat = await self._call(client.find_membership(target, group.tg_chat_id))
                except TelegramError as exc:
                    if exc.code == TgErrorCode.FLOOD_WAIT:
                        await self._enter_flood(rt, exc)
                        return
                    if _is_account_error(exc) or exc.code == TgErrorCode.NETWORK:
                        raise  # 이번 확인은 여기서 멈추고 다음 주기에 다시 본다
                    if exc.permanent:
                        await self._give_up_request(rt, group.id, exc)
                    else:
                        logger.warning(
                            "그룹 %s 의 입장 요청을 확인하지 못했어요: %s", group.id, exc.message
                        )
                    continue
            if chat is not None:
                await self._approve(rt, group.id, chat)

    async def _approve(self, rt: _Runtime, group_id: int, chat: TgChat) -> None:
        now = self._clock()
        async with self.db.session() as session:
            group = await session.get(Group, group_id)
            if group is None or group.status != GroupStatus.REQUESTED:
                return  # 확인하는 사이에 지워졌거나 상태가 바뀌었다
            twin_id = await self._mark_joined(session, group, chat, now)
            await session.commit()
        await self._announce_joined(rt, group, twin_id, "입장 요청이 승인됐어요.")

    async def _give_up_request(self, rt: _Runtime, group_id: int, error: TelegramError) -> None:
        """승인 여부를 더는 확인할 수 없는 입장 요청을 실패로 확정한다(같은 요청을 계속 보내지 않는다)."""
        async with self.db.session() as session:
            group = await session.get(Group, group_id)
            if group is None or group.status != GroupStatus.REQUESTED:
                return
            group.status = GroupStatus.FAILED
            group.error_code = str(error.code)
            group.status_detail = _clip(
                f"입장 요청이 승인됐는지 더는 확인할 수 없어요. {error.message}", 500
            )
            await session.commit()
        await self._publish_group(group_id)
        await self._publish_account(rt.account_id)
        await self.logbook.warning(
            f"입장 요청이 승인됐는지 더는 확인할 수 없어요. {error.message}",
            category=LogCategory.GROUP,
            account_id=rt.account_id,
            group_id=group_id,
        )

    async def _refresh_memberships(self, rt: _Runtime, client: AccountClient) -> bool:
        """가입된 그룹을 텔레그램의 실제 목록과 맞춘다. 요청 제한 때문에 못 했으면 False."""
        async with rt.call_lock:
            if self._flooding(rt):
                return False
            listed_at = self._clock()
            try:
                chats = await self._call(client.list_groups())
            except TelegramError as exc:
                if exc.code != TgErrorCode.FLOOD_WAIT:
                    raise
                await self._enter_flood(rt, exc)
                return False
        present = {chat.id: chat for chat in chats}
        changed: list[int] = []
        left: list[int] = []
        async with self.db.session() as session:
            groups = (
                await session.scalars(
                    select(Group).where(
                        Group.account_id == rt.account_id,
                        Group.status == GroupStatus.JOINED,
                        Group.tg_chat_id.is_not(None),
                    )
                )
            ).all()
            for group in groups:
                chat = present.get(group.tg_chat_id)
                if chat is None:
                    if group.joined_at is not None and group.joined_at >= listed_at:
                        continue  # 목록을 받은 뒤에 가입된 그룹이라 목록에 없을 수 있다
                    group.status = GroupStatus.LEFT
                    group.status_detail = _DETAIL_LEFT
                    left.append(group.id)
                    continue
                title = _clip(chat.title, 255) or group.title
                count = group.member_count if chat.member_count is None else chat.member_count
                if (title, count) != (group.title, group.member_count):
                    group.title, group.member_count = title, count
                    changed.append(group.id)
            await session.commit()
        if left:
            await self._reload_monitored(rt)
        for group_id in (*changed, *left):
            await self._publish_group(group_id)
        for group_id in left:
            await self.logbook.warning(
                f"{_DETAIL_LEFT}.",
                category=LogCategory.GROUP,
                account_id=rt.account_id,
                group_id=group_id,
            )
        if left:
            await self._publish_account(rt.account_id)
        return True

    # --- 공통 도구 ----------------------------------------------------------

    async def _call(self, request: Awaitable[T]) -> T:
        """게이트웨이 호출에 시간 제한을 건다. 멎은 호출 하나가 일꾼을 붙잡지 못하게 한다."""
        try:
            return await asyncio.wait_for(request, self._timings.call_timeout)
        except TimeoutError as exc:
            raise TelegramError(TgErrorCode.NETWORK, _MSG_TIMEOUT) from exc

    async def _pause(self, seconds: float, wake: asyncio.Event | None = None) -> None:
        await self._wait_until(self._clock() + timedelta(seconds=seconds), wake)

    async def _wait_until(self, deadline: datetime, wake: asyncio.Event | None = None) -> None:
        """clock 이 deadline 을 지날 때까지 기다린다. wake 가 켜지면 먼저 돌아온다."""
        idle = wake if wake is not None else asyncio.Event()
        while (remaining := (deadline - self._clock()).total_seconds()) > 0:
            if await _nap(idle, min(remaining, self._timings.tick)):
                return

    async def _update_account(self, account_id: int, **changes: object) -> None:
        """계정 행의 값을 바꾸고 실시간 화면에 알린다. 행이 없으면 아무것도 하지 않는다."""
        async with self.db.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                return
            for name, value in changes.items():
                setattr(account, name, value)
            await session.commit()
        await self._publish_account(account_id)

    async def _publish_account(self, account_id: int) -> None:
        """계정의 지금 모습을 실시간 화면에 보낸다. 실패해도 하던 일을 막지 않는다."""
        try:
            settings = await self.settings.get()
            async with self.db.session() as session:
                out = await account_out(session, settings, account_id)
        except Exception:
            logger.exception("계정 %s 의 변경을 실시간 화면에 알리지 못했어요", account_id)
            return
        if out is not None:
            self.bus.publish("account", out.model_dump(mode="json"))

    async def _publish_group(self, group_id: int) -> None:
        """그룹의 지금 모습을 실시간 화면에 보낸다. 실패해도 하던 일을 막지 않는다."""
        try:
            async with self.db.session() as session:
                out = await group_out(session, group_id)
        except Exception:
            logger.exception("그룹 %s 의 변경을 실시간 화면에 알리지 못했어요", group_id)
            return
        if out is not None:
            self.bus.publish("group", out.model_dump(mode="json"))
