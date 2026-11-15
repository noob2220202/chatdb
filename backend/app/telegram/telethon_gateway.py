"""Telethon 으로 구현한 텔레그램 게이트웨이(운영용).

듣고 기록하는 데 필요한 호출만 쓴다: 접속, 로그인, 그룹 가입·나가기, 새 메시지 수신.
FloodWait 는 여기서 기다리거나 다시 시도하지 않고 TelegramError(FLOOD_WAIT) 로 올린다.
얼마나 기다릴지는 엔진이 정한다.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import sqlite3
import struct
import tempfile
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from telethon import TelegramClient, errors, events, functions, types, utils
from telethon.crypto import AuthKey
from telethon.sessions import StringSession

from .. import __version__
from ..db import utcnow
from ..links import LinkTarget
from ..models import GroupKind, LinkKind
from .gateway import (
    AccountClient,
    ApiCredentials,
    IncomingMessage,
    JoinOutcome,
    JoinResult,
    LoginResult,
    MessageHandler,
    PendingLogin,
    TelegramError,
    TelegramGateway,
    TgChat,
    TgErrorCode,
    TgUser,
)

__all__ = ["TelethonAccountClient", "TelethonGateway", "to_telegram_error"]

logger = logging.getLogger("chatdb.telegram.telethon")

ClientFactory = Callable[..., TelegramClient]
"""TelegramClient 와 같은 인자를 받는 생성자. 테스트에서 가짜 클라이언트를 끼울 때 쓴다."""

LOGIN_TTL_SECONDS = 600.0

# 공식 앱을 흉내 내지 않고 이 프로그램 그대로 밝힌다.
_CLIENT_OPTIONS: dict[str, Any] = {
    "device_model": "ChatDB",
    "app_version": __version__,
    # FloodWait 를 Telethon 이 몰래 자면서 넘기지 않게 한다. 기다리는 일은 엔진이 한다.
    "flood_sleep_threshold": 0,
    "auto_reconnect": True,
    # 서버 오류로 재시도를 다 쓰면 뜻 없는 ValueError 대신 마지막 RPC 오류를 받는다.
    "raise_last_call_error": True,
}

# min 이 아닌 발신자 정보를 계정마다 이만큼까지 기억한다.
_KNOWN_USERS_LIMIT = 5000

_SQLITE_MAGIC = b"SQLite format 3\x00"
_AUTH_KEY_BYTES = 256

_GROUP_TYPES = (types.Chat, types.Channel)

_MSG_SESSION_EXPIRED = "세션이 만료됐어요. 다시 로그인해 주세요."
_MSG_SESSION_FORMAT = (
    "세션을 읽을 수 없어요. Telethon 세션 문자열이나 .session 파일이 맞는지 확인해 주세요."
)
_MSG_NOT_CONNECTED = "텔레그램에 연결돼 있지 않아요. 잠시 뒤에 다시 시도해 주세요."
_MSG_LOGIN_EXPIRED = "로그인 절차가 만료됐어요. 처음부터 다시 시도해 주세요."
_MSG_UNKNOWN = "텔레그램 요청이 실패했어요. 잠시 뒤에 다시 시도해 주세요."
_MSG_REFUSED = "텔레그램이 이 요청을 받아들이지 않았어요."


# ---------------------------------------------------------------------------
# 오류 변환
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Rule:
    code: TgErrorCode
    message: str
    kinds: tuple[type[BaseException], ...]
    permanent: bool = False


# 번호를 넣는 로그인 화면에서는 같은 오류라도 번호 문제로 알려 준다.
_LOGIN_RULES: tuple[_Rule, ...] = (
    _Rule(
        TgErrorCode.PHONE_BANNED,
        "텔레그램이 정지한 번호예요.",
        (errors.PhoneNumberBannedError,),
        permanent=True,
    ),
)

# 위에서부터 처음 맞는 규칙을 쓴다. 하위 클래스가 상위 클래스보다 먼저 와야 한다.
_RULES: tuple[_Rule, ...] = (
    # --- 계정 ---
    _Rule(
        TgErrorCode.BANNED,
        "텔레그램이 이 계정을 정지했어요.",
        (errors.UserDeactivatedBanError, errors.PhoneNumberBannedError),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.BANNED,
        "텔레그램이 이 계정을 동결해서 이 작업을 할 수 없어요.",
        (errors.FrozenMethodInvalidError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.SESSION_INVALID,
        "다른 기기에서 이 세션을 종료했어요. 다시 로그인해 주세요.",
        (errors.SessionRevokedError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.SESSION_INVALID,
        "같은 세션을 두 곳에서 동시에 써서 텔레그램이 세션을 끊었어요. 다시 로그인해 주세요.",
        (errors.AuthKeyDuplicatedError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.SESSION_INVALID,
        "삭제됐거나 비활성화된 계정이에요.",
        (errors.UserDeactivatedError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.SESSION_INVALID,
        _MSG_SESSION_EXPIRED,
        (
            errors.AuthKeyUnregisteredError,
            errors.SessionExpiredError,
            errors.AuthKeyInvalidError,
            errors.AuthKeyPermEmptyError,
            errors.AuthKeyNotFound,
            errors.UnauthorizedError,  # 그 밖의 401
        ),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.API_CREDENTIALS,
        "api_id 또는 api_hash 가 올바르지 않아요. 설정에서 다시 확인해 주세요.",
        (errors.ApiIdInvalidError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.API_CREDENTIALS,
        "여러 곳에 공개된 API 키라 텔레그램이 막았어요. my.telegram.org 에서 내 키를 받아 주세요.",
        (errors.ApiIdPublishedFloodError,),
        permanent=True,
    ),
    # --- 그룹 가입 ---
    _Rule(
        TgErrorCode.INVITE_EXPIRED,
        "초대 링크가 만료됐어요.",
        (errors.InviteHashExpiredError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.INVITE_INVALID,
        "초대 링크가 올바르지 않아요.",
        (errors.InviteHashInvalidError, errors.InviteHashEmptyError),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.NOT_FOUND,
        "그런 아이디의 그룹을 찾을 수 없어요.",
        (errors.UsernameNotOccupiedError, errors.UsernameInvalidError),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.TOO_MANY_GROUPS,
        "이 계정은 텔레그램이 허용하는 그룹 수를 다 채워서 더 들어갈 수 없어요.",
        (errors.ChannelsTooMuchError, errors.UserChannelsTooMuchError),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.PRIVATE,
        "비공개 그룹이거나 이 계정이 차단돼 있어서 들어갈 수 없어요.",
        (errors.ChannelPrivateError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.PRIVATE,
        "텔레그램이 차단한 그룹이라 들어갈 수 없어요.",
        (errors.ChannelBannedError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.PRIVATE,
        "그룹 정원이 가득 차서 들어갈 수 없어요.",
        (errors.UsersTooMuchError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.PRIVATE,
        "지금은 이용할 수 없는 그룹이에요.",
        (errors.ChannelPublicGroupNaError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.BANNED_FROM_GROUP,
        "이 계정은 텔레그램에서 그룹 이용이 제한돼 있어서 들어갈 수 없어요.",
        (errors.UserBannedInChannelError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.BANNED_FROM_GROUP,
        "이 그룹에서 내보내진 계정이라 다시 들어갈 수 없어요.",
        (errors.UserKickedError,),
        permanent=True,
    ),
    # --- 로그인 ---
    _Rule(
        TgErrorCode.PHONE_INVALID,
        "전화번호가 올바르지 않아요. 국가 번호부터 넣어 주세요(예: +821012345678).",
        (errors.PhoneNumberInvalidError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.PHONE_INVALID,
        "이 번호로 가입된 텔레그램 계정이 없어요.",
        (errors.PhoneNumberUnoccupiedError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.CODE_INVALID,
        "인증 코드가 틀렸어요.",
        (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError),
    ),
    _Rule(
        TgErrorCode.CODE_EXPIRED,
        "인증 코드가 만료됐어요. 처음부터 다시 시도해 주세요.",
        (errors.PhoneCodeExpiredError,),
        permanent=True,
    ),
    _Rule(
        TgErrorCode.PASSWORD_INVALID,
        "2단계 인증 비밀번호가 틀렸어요.",
        (errors.PasswordHashInvalidError,),
    ),
    _Rule(
        TgErrorCode.FLOOD_WAIT,
        "인증 코드를 너무 여러 번 요청했어요. 몇 시간 뒤에 다시 시도해 주세요.",
        (errors.PhoneNumberFloodError,),
    ),
    _Rule(
        TgErrorCode.FLOOD_WAIT,
        "로그인을 너무 여러 번 시도했어요. 몇 시간 뒤에 다시 시도해 주세요.",
        (errors.PhonePasswordFloodError,),
    ),
    # --- 일시적인 문제 ---
    _Rule(
        TgErrorCode.NETWORK,
        "텔레그램 서버가 잠시 불안정해요. 조금 뒤에 다시 시도해 주세요.",
        (errors.ServerError, errors.TimedOutError),
    ),
    _Rule(
        TgErrorCode.NETWORK,
        "텔레그램에 연결하지 못했어요. 네트워크 상태를 확인해 주세요.",
        # ConnectionError 와 TimeoutError(asyncio.TimeoutError)는 OSError 의 하위 클래스다.
        (ConnectionError, TimeoutError, OSError, asyncio.IncompleteReadError),
    ),
)

_FLOOD_WAITS = (
    errors.FloodWaitError,
    errors.FloodPremiumWaitError,
    errors.FloodTestPhoneWaitError,
)

# 나가려는데 이미 멤버가 아닐 때 텔레그램이 주는 오류.
_NOT_A_MEMBER = (
    errors.UserNotParticipantError,
    errors.ChannelPrivateError,
    errors.ChatIdInvalidError,
    errors.PeerIdInvalidError,
)


def _format_wait(seconds: int) -> str:
    """기다릴 시간을 읽기 좋게 쓴다. 한 시간이 넘으면 분 단위로 올림한다."""
    if seconds < 60:
        return f"{seconds}초"
    if seconds < 3600:
        minutes, rest = divmod(seconds, 60)
        return f"{minutes}분 {rest}초" if rest else f"{minutes}분"
    hours, minutes = divmod(-(-seconds // 60), 60)
    return f"{hours}시간 {minutes}분" if minutes else f"{hours}시간"


def to_telegram_error(exc: BaseException, *, login: bool = False) -> TelegramError:
    """Telethon·네트워크 예외를 TelegramError 로 바꾼다. 이 모듈의 모든 호출이 이 함수를 거친다.

    login=True 는 로그인 화면에서 난 오류라는 뜻이다(정지된 번호를 PHONE_BANNED 로 알린다).
    """
    if isinstance(exc, TelegramError):
        return exc
    if isinstance(exc, _FLOOD_WAITS):
        seconds = max(1, int(exc.seconds or 0))
        return TelegramError(
            TgErrorCode.FLOOD_WAIT,
            f"텔레그램이 요청을 잠시 제한했어요. {_format_wait(seconds)} 뒤에 다시 시도할 수 있어요.",
            retry_after=seconds,
        )
    if isinstance(exc, errors.InvalidBufferError):
        if exc.code == 404:
            return TelegramError(TgErrorCode.SESSION_INVALID, _MSG_SESSION_EXPIRED, permanent=True)
        if exc.code == 429:
            return TelegramError(
                TgErrorCode.NETWORK,
                "텔레그램이 이 연결을 잠시 제한했어요. 조금 뒤에 다시 연결해 주세요.",
            )
        return TelegramError(
            TgErrorCode.NETWORK, "텔레그램과 주고받은 데이터가 깨졌어요. 다시 연결해 주세요."
        )
    for rule in (*_LOGIN_RULES, *_RULES) if login else _RULES:
        if isinstance(exc, rule.kinds):
            return TelegramError(rule.code, rule.message, permanent=rule.permanent)
    logger.error("분류하지 못한 텔레그램 오류예요: %s", type(exc).__name__, exc_info=exc)
    # 400·403 은 요청 자체가 거절된 것이라 같은 요청을 다시 보내도 결과가 같다.
    refused = isinstance(exc, (errors.BadRequestError, errors.ForbiddenError))
    return TelegramError(
        TgErrorCode.UNKNOWN, _MSG_REFUSED if refused else _MSG_UNKNOWN, permanent=refused
    )


@contextmanager
def _telegram_errors(*, login: bool = False) -> Iterator[None]:
    """블록 안에서 난 예외를 TelegramError 로 바꿔 올린다."""
    try:
        yield
    except TelegramError:
        raise
    except asyncio.CancelledError as exc:
        task = asyncio.current_task()
        if task is None or task.cancelling():
            raise  # 이 태스크가 실제로 취소됐다
        # Telethon 은 연결을 끊을 때 응답을 기다리던 요청의 future 를 cancel 한다.
        raise TelegramError(TgErrorCode.NETWORK, "연결이 끊겨서 요청을 마치지 못했어요.") from exc
    except Exception as exc:
        raise to_telegram_error(exc, login=login) from exc


def _session_format_error() -> TelegramError:
    return TelegramError(TgErrorCode.SESSION_FORMAT, _MSG_SESSION_FORMAT, permanent=True)


# ---------------------------------------------------------------------------
# 세션 · 클라이언트 만들기
# ---------------------------------------------------------------------------


class _Session(StringSession):
    """엔티티를 쌓아 두지 않는 StringSession.

    기본 구현은 업데이트와 응답에 실려 온 유저·채팅을 전부 메모리에 모으기만 해서, 오래 켜 둔
    수신 전용 프로그램에서는 끝없이 늘어난다. 이 게이트웨이는 필요한 입력 피어를 직접 들고
    있으므로 그 캐시가 필요 없다.
    """

    def process_entities(self, tlo: object) -> None:
        return None


def _load_session(text: str) -> _Session:
    """세션 문자열을 읽는다. 읽을 수 없거나 인증 키가 없으면 TelegramError(SESSION_FORMAT)."""
    try:
        session = _Session(text.strip())
    except (ValueError, struct.error) as exc:
        raise _session_format_error() from exc
    if not session.auth_key:
        raise _session_format_error()
    return session


def _session_text_from_file(data: bytes) -> str:
    """Telethon .session(SQLite) 파일 내용을 세션 문자열로 바꾼다.

    세션 문자열을 담은 텍스트 파일이면 그 문자열을 돌려준다. 블로킹이므로 스레드에서 부른다.
    """
    if not data.startswith(_SQLITE_MAGIC):
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise _session_format_error() from exc

    # 인증 키가 담긴 파일이라 나만 읽을 수 있는 임시 폴더에 두고, 끝나면 폴더째 지운다.
    with tempfile.TemporaryDirectory(prefix="chatdb-session-") as folder:
        path = Path(folder) / "import.session"
        path.touch(mode=0o600)
        path.write_bytes(data)
        try:
            connection = sqlite3.connect(path)
            try:
                row = connection.execute(
                    "select dc_id, server_address, port, auth_key from sessions"
                ).fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise _session_format_error() from exc

    if row is None:
        raise _session_format_error()
    dc_id, server_address, port, auth_key = row
    if not isinstance(auth_key, bytes) or len(auth_key) != _AUTH_KEY_BYTES:
        raise _session_format_error()
    session = StringSession()
    try:
        session.set_dc(dc_id, server_address, port)
        session.auth_key = AuthKey(data=auth_key)
        return session.save()
    except (ValueError, TypeError, struct.error) as exc:
        raise _session_format_error() from exc


def _make_client(
    factory: ClientFactory, session: StringSession, api_id: int, api_hash: str
) -> TelegramClient:
    return factory(session, api_id, api_hash, **_CLIENT_OPTIONS)


async def _new_client(
    credentials: ApiCredentials, factory: ClientFactory, session: StringSession
) -> TelegramClient:
    api_id, api_hash = await credentials()
    with _telegram_errors():
        return _make_client(factory, session, api_id, api_hash)


async def _disconnect_quietly(client: TelegramClient) -> None:
    try:
        await client.disconnect()
    except Exception:
        logger.warning("텔레그램 연결을 정리하다 오류가 났어요", exc_info=True)


async def _fetch_self(client: TelegramClient) -> TgUser:
    """내 정보를 가져온다. 로그인돼 있지 않으면 이유에 맞는 TelegramError 가 난다.

    client.get_me() 와 is_user_authorized() 는 401 을(뒤쪽은 모든 RPC 오류를) 삼켜 버려서
    세션 만료와 계정 정지, FloodWait 를 구분할 수 없다. 그래서 같은 요청을 직접 보낸다.
    """
    users = await client(functions.users.GetUsersRequest([types.InputUserSelf()]))
    me = users[0] if users else None
    if not isinstance(me, types.User):
        raise TelegramError(TgErrorCode.SESSION_INVALID, _MSG_SESSION_EXPIRED, permanent=True)
    return _to_user(me, with_phone=True)


# ---------------------------------------------------------------------------
# Telethon 객체 → 값 타입
# ---------------------------------------------------------------------------


def _username_of(entity: object) -> str | None:
    """대표 아이디. 없으면 usernames 에서 활성 상태인 첫 아이디."""
    username = getattr(entity, "username", None)
    if username:
        return username
    for item in getattr(entity, "usernames", None) or []:
        if item.active and item.username:
            return item.username
    return None


def _to_user(user: types.User, *, with_phone: bool = False) -> TgUser:
    """with_phone 은 내 계정에만 쓴다. 수집 대상의 전화번호는 넘기지 않는다."""
    return TgUser(
        id=user.id,
        username=_username_of(user),
        first_name=user.first_name or None,
        last_name=user.last_name or None,
        is_bot=bool(user.bot),
        phone=f"+{user.phone}" if with_phone and user.phone else None,
    )


def _to_chat(entity: types.Chat | types.Channel) -> TgChat:
    if isinstance(entity, types.Channel):
        grouplike = entity.megagroup or entity.gigagroup
        kind = GroupKind.SUPERGROUP if grouplike else GroupKind.CHANNEL
    else:
        kind = GroupKind.GROUP
    return TgChat(
        id=utils.get_peer_id(entity),
        title=entity.title or "",
        username=_username_of(entity),
        kind=kind,
        member_count=entity.participants_count,
    )


def _is_member(entity: object) -> bool:
    """계정이 지금 이 채팅의 멤버인지. 나갔거나 닫혔거나 슈퍼그룹으로 옮겨 간 채팅은 아니다."""
    if isinstance(entity, types.Channel):
        return entity.left is False
    if isinstance(entity, types.Chat):
        return entity.left is False and not entity.deactivated and entity.migrated_to is None
    return False


def _marked_id(entity: object) -> int | None:
    try:
        return utils.get_peer_id(entity)
    except TypeError:
        return None


def _pick(chats: Iterable[object], chat_id: int) -> object | None:
    """chats 에서 marked id 가 chat_id 인 것."""
    return next((chat for chat in chats if _marked_id(chat) == chat_id), None)


def _result_chats(result: object) -> list[object]:
    """가입 요청(JoinChannel·ImportChatInvite)의 응답에 실린 채팅들."""
    if isinstance(result, types.messages.ChatInviteJoinResultWebView):
        raise TelegramError(
            TgErrorCode.PRIVATE,
            "봇 인증 화면을 거쳐야 들어갈 수 있는 그룹이라 자동으로 가입할 수 없어요.",
            permanent=True,
        )
    if isinstance(result, types.messages.ChatInviteJoinResultOk):
        result = result.updates
    return list(getattr(result, "chats", None) or [])


def _join_result(outcome: JoinOutcome, chat: TgChat) -> JoinResult:
    return JoinResult(outcome, chat=chat, title=chat.title, member_count=chat.member_count)


def _code_via(sent_type: object) -> Literal["app", "sms", "call", "other"]:
    code_types = types.auth
    if isinstance(sent_type, code_types.SentCodeTypeApp):
        return "app"
    if isinstance(
        sent_type,
        (
            code_types.SentCodeTypeSms,
            code_types.SentCodeTypeFirebaseSms,
            code_types.SentCodeTypeSmsWord,
            code_types.SentCodeTypeSmsPhrase,
        ),
    ):
        return "sms"
    if isinstance(
        sent_type,
        (
            code_types.SentCodeTypeCall,
            code_types.SentCodeTypeFlashCall,
            code_types.SentCodeTypeMissedCall,
        ),
    ):
        return "call"
    return "other"


def _normalize_phone(phone: str) -> str:
    """'+' 와 숫자만 남긴다. 국가 번호가 없거나 숫자가 아니면 TelegramError(PHONE_INVALID)."""
    digits = re.sub(r"[\s()+.\-]", "", phone)
    valid = digits.isascii() and digits.isdigit() and 7 <= len(digits) <= 15
    if not valid or digits.startswith("0"):
        raise TelegramError(
            TgErrorCode.PHONE_INVALID,
            "전화번호가 올바르지 않아요. 국가 번호부터 넣어 주세요(예: +821012345678).",
            permanent=True,
        )
    return f"+{digits}"


def _normalize_code(code: str) -> str:
    """'12 345', '12-345' 처럼 끊어 적은 숫자 코드를 붙인다. 단어·문장으로 온 코드는 그대로 둔다."""
    text = code.strip()
    compact = re.sub(r"[\s\-]", "", text)
    return compact if compact.isdigit() or not compact else text


def _aware(moment: datetime | None) -> datetime:
    if moment is None:
        return utcnow()
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class _UserMemo:
    """min 이 아닌 유저 정보를 최근에 본 순서로 정해진 개수만큼 기억한다.

    텔레그램은 그룹 업데이트에 정보가 일부만 든 min 유저를 실어 보내기도 하고, 일반 그룹의
    짧은 업데이트에는 유저를 아예 싣지 않는다. 그럴 때 요청을 보내는 대신 앞서 본 정보를 쓴다.
    """

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._users: OrderedDict[int, TgUser] = OrderedDict()

    def put(self, user: TgUser) -> None:
        self._users[user.id] = user
        self._users.move_to_end(user.id)
        while len(self._users) > self._capacity:
            self._users.popitem(last=False)

    def get(self, user_id: int) -> TgUser | None:
        user = self._users.get(user_id)
        if user is not None:
            self._users.move_to_end(user_id)
        return user


# ---------------------------------------------------------------------------
# 계정 연결
# ---------------------------------------------------------------------------


class TelethonAccountClient(AccountClient):
    """계정 하나의 Telethon 연결. Telethon 클라이언트는 connect() 때 만든다."""

    def __init__(
        self,
        account_id: int,
        session: str,
        credentials: ApiCredentials,
        client_factory: ClientFactory,
    ) -> None:
        self.account_id = account_id
        self._session = session
        self._credentials = credentials
        self._client_factory = client_factory
        self._client: TelegramClient | None = None
        self._handler: MessageHandler | None = None
        self._connect_lock = asyncio.Lock()
        # 채널·슈퍼그룹 id → 요청에 넣을 입력 피어(access_hash 포함).
        self._channels: dict[int, types.InputChannel] = {}
        self._users = _UserMemo(_KNOWN_USERS_LIMIT)

    # --- 연결 --------------------------------------------------------------

    async def connect(self) -> TgUser:
        async with self._connect_lock:
            client = self._client
            if client is None or not client.is_connected():
                client = await self._open_client()
            try:
                with _telegram_errors():
                    await client.connect()
                    return await _fetch_self(client)
            except BaseException:
                # 로그인되지 않은 채로 업데이트 루프가 남지 않게 닫는다.
                await _disconnect_quietly(client)
                raise

    async def _open_client(self) -> TelegramClient:
        """지금 세션으로 새 Telethon 클라이언트를 만든다(API 키가 바뀌었어도 반영된다)."""
        try:
            session = _load_session(self.export_session())
        except TelegramError as exc:
            raise TelegramError(
                TgErrorCode.SESSION_INVALID,
                "저장된 세션을 읽을 수 없어요. 다시 로그인해 주세요.",
                permanent=True,
            ) from exc
        previous = self._client
        if previous is not None:
            await _disconnect_quietly(previous)  # 끊긴 연결에 남은 백그라운드 태스크를 정리한다
        client = await _new_client(self._credentials, self._client_factory, session)
        client.add_event_handler(self._on_new_message, events.NewMessage(incoming=True))
        self._client = client
        return client

    async def disconnect(self) -> None:
        client = self._client
        if client is None:
            return
        self.export_session()  # 끊기 전에 마지막 세션을 챙겨 둔다
        await _disconnect_quietly(client)

    async def wait_closed(self) -> None:
        client = self._client
        if client is None:
            return
        try:
            await client.disconnected
        except Exception as exc:
            # 다시 붙지 못했거나 서버가 인증 키를 모른다고 한 경우
            raise to_telegram_error(exc) from exc
        # 업데이트를 받다가 세션이 무효가 되면 Telethon 은 이유를 여기 남기고 조용히 끊는다.
        error = getattr(client, "_updates_error", None)
        if error is not None:
            raise to_telegram_error(error) from error

    def set_message_handler(self, handler: MessageHandler | None) -> None:
        self._handler = handler

    def export_session(self) -> str:
        client = self._client
        if client is not None and client.session is not None:
            current = client.session.save()
            if current:
                self._session = current
        return self._session

    async def log_out(self) -> None:
        client = self._client
        if client is None or not client.is_connected():
            try:
                await self.connect()
            except TelegramError as exc:
                if exc.code != TgErrorCode.SESSION_INVALID:
                    raise
                logger.info("계정 %s 의 세션은 이미 무효라 로그아웃할 것이 없어요", self.account_id)
                return
            client = self._connected()
        with _telegram_errors():
            try:
                await client(functions.auth.LogOutRequest())
            except errors.UnauthorizedError:
                logger.info("계정 %s 의 세션은 이미 무효라 로그아웃할 것이 없어요", self.account_id)
        await self.disconnect()

    def _connected(self) -> TelegramClient:
        client = self._client
        if client is None or not client.is_connected():
            raise TelegramError(TgErrorCode.NETWORK, _MSG_NOT_CONNECTED)
        return client

    # --- 메시지 수신 -------------------------------------------------------

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        handler = self._handler
        if handler is None:
            return
        try:
            incoming = self._incoming(event.message)
            if incoming is not None:
                await handler(incoming)
        except Exception:
            logger.exception("계정 %s 에 온 메시지를 처리하지 못했어요", self.account_id)

    def _incoming(self, message: types.Message) -> IncomingMessage | None:
        """그룹·슈퍼그룹 메시지만 값 타입으로 바꾼다. 개인 대화와 방송 채널 글은 None."""
        peer = message.peer_id
        if isinstance(peer, types.PeerChannel):
            chat = message.chat
            if message.post or (isinstance(chat, types.Channel) and chat.broadcast):
                return None
        elif not isinstance(peer, types.PeerChat):
            return None
        return IncomingMessage(
            account_id=self.account_id,
            chat_id=utils.get_peer_id(peer),
            message_id=message.id,
            sender=self._sender_of(message),
            text=message.message or "",
            date=_aware(message.date),
        )

    def _sender_of(self, message: types.Message) -> TgUser | None:
        """보낸 유저. 요청을 보내지 않고 업데이트에 실려 온 정보와 앞서 본 정보만 쓴다."""
        author = message.from_id
        if not isinstance(author, types.PeerUser):
            return None  # 익명 관리자, 채널 명의 글
        sender = message.sender
        if isinstance(sender, types.User) and not sender.min:
            user = _to_user(sender)
            self._users.put(user)
            return user
        known = self._users.get(author.user_id)
        if known is not None:
            return known
        return _to_user(sender) if isinstance(sender, types.User) else None

    # --- 그룹 --------------------------------------------------------------

    async def join(self, target: LinkTarget) -> JoinResult:
        client = self._connected()
        with _telegram_errors():
            if target.kind == LinkKind.PUBLIC:
                return await self._join_public(client, target.value)
            if target.kind == LinkKind.INVITE:
                return await self._join_invite(client, target.value)
        raise ValueError(f"가입할 수 없는 링크 종류예요: {target.kind}")

    async def _join_public(self, client: TelegramClient, username: str) -> JoinResult:
        resolved = await client(functions.contacts.ResolveUsernameRequest(username))
        if isinstance(resolved.peer, types.PeerUser):
            raise TelegramError(
                TgErrorCode.NOT_A_GROUP,
                "이 아이디는 그룹이 아니라 사람이나 봇이에요.",
                permanent=True,
            )
        entity = _pick(resolved.chats, utils.get_peer_id(resolved.peer))
        if entity is None:
            raise TelegramError(
                TgErrorCode.NOT_FOUND, "그런 아이디의 그룹을 찾을 수 없어요.", permanent=True
            )
        if not isinstance(entity, types.Channel):
            raise TelegramError(
                TgErrorCode.PRIVATE, "접근이 막혀 있는 그룹이라 들어갈 수 없어요.", permanent=True
            )
        if _is_member(entity):
            return _join_result(JoinOutcome.JOINED, self._chat(entity))
        try:
            result = await client(
                functions.channels.JoinChannelRequest(utils.get_input_channel(entity))
            )
        except errors.InviteRequestSentError:
            return _join_result(JoinOutcome.REQUESTED, self._chat(entity))
        except errors.UserAlreadyParticipantError:
            return _join_result(JoinOutcome.JOINED, self._chat(entity))
        joined = _pick(_result_chats(result), utils.get_peer_id(entity))
        return _join_result(
            JoinOutcome.JOINED,
            self._chat(joined if isinstance(joined, types.Channel) else entity),
        )

    async def _join_invite(self, client: TelegramClient, invite_hash: str) -> JoinResult:
        invite = await client(functions.messages.CheckChatInviteRequest(invite_hash))
        if isinstance(invite, types.ChatInviteAlready):
            return self._joined(invite.chat)

        preview: object | None = None
        if isinstance(invite, types.ChatInvite):
            if invite.subscription_pricing is not None:
                raise TelegramError(
                    TgErrorCode.PRIVATE,
                    "유료 구독이 필요한 그룹이라 자동으로 가입할 수 없어요.",
                    permanent=True,
                )
            title, member_count = invite.title, invite.participants_count
        else:  # ChatInvitePeek: 가입 전에 채팅 정보를 미리 준다
            preview = invite.chat
            title = getattr(preview, "title", None)
            member_count = getattr(preview, "participants_count", None)

        try:
            result = await client(functions.messages.ImportChatInviteRequest(invite_hash))
        except errors.InviteRequestSentError:
            return JoinResult(
                JoinOutcome.REQUESTED,
                chat=self._chat(preview) if isinstance(preview, _GROUP_TYPES) else None,
                title=title,
                member_count=member_count,
            )
        except errors.UserAlreadyParticipantError:
            return self._joined(await self._invited_chat(client, invite_hash))

        chats = [chat for chat in _result_chats(result) if isinstance(chat, _GROUP_TYPES)]
        joined = next((chat for chat in chats if _is_member(chat)), chats[0] if chats else None)
        if joined is None:
            joined = await self._invited_chat(client, invite_hash)
        return self._joined(joined)

    async def _invited_chat(self, client: TelegramClient, invite_hash: str) -> object | None:
        """초대 링크의 그룹에 이미 들어가 있으면 그 채팅."""
        invite = await client(functions.messages.CheckChatInviteRequest(invite_hash))
        return invite.chat if isinstance(invite, types.ChatInviteAlready) else None

    def _joined(self, entity: object | None) -> JoinResult:
        if not isinstance(entity, _GROUP_TYPES):
            raise TelegramError(
                TgErrorCode.UNKNOWN,
                "가입은 됐는데 그룹 정보를 확인하지 못했어요. 잠시 뒤에 다시 확인할게요.",
            )
        return _join_result(JoinOutcome.JOINED, self._chat(entity))

    async def find_membership(
        self, target: LinkTarget | None, tg_chat_id: int | None
    ) -> TgChat | None:
        client = self._connected()
        with _telegram_errors():
            found, entity = False, None
            if tg_chat_id is not None:
                found, entity = await self._entity_by_id(client, tg_chat_id)
            if not found and target is not None:
                found, entity = await self._entity_by_link(client, target)
            if not found and tg_chat_id is not None:
                entity = (await self._dialog_entities(client)).get(tg_chat_id)
        return self._chat(entity) if _is_member(entity) else None

    async def _entity_by_id(
        self, client: TelegramClient, tg_chat_id: int
    ) -> tuple[bool, object | None]:
        """id 로 채팅을 찾는다. (확인했는지, 채팅). 입력 피어를 몰라 확인하지 못하면 (False, None)."""
        raw_id, peer_type = utils.resolve_id(tg_chat_id)
        if peer_type is types.PeerChat:
            try:
                result = await client(functions.messages.GetChatsRequest([raw_id]))
            except (errors.ChatIdInvalidError, errors.PeerIdInvalidError):
                return True, None
            entity = _pick(result.chats, tg_chat_id)
            successor = getattr(entity, "migrated_to", None)
            if isinstance(successor, types.InputChannel):
                # 슈퍼그룹으로 바뀐 그룹은 새 채팅 쪽에서 확인한다.
                entity = await self._fetch_channel(client, successor)
            return True, entity
        if peer_type is types.PeerChannel:
            channel = self._channels.get(raw_id)
            if channel is None:
                return False, None
            try:
                return True, await self._fetch_channel(client, channel)
            except errors.ChannelInvalidError:
                del self._channels[raw_id]  # 들고 있던 access_hash 가 더는 맞지 않는다
                return False, None
        return True, None  # 양수 id 는 사람이다

    async def _fetch_channel(
        self, client: TelegramClient, channel: types.InputChannel
    ) -> object | None:
        try:
            result = await client(functions.channels.GetChannelsRequest([channel]))
        except errors.ChannelPrivateError:
            return None  # 볼 수 없는 채널이면 멤버가 아니다
        return _pick(result.chats, utils.get_peer_id(types.PeerChannel(channel.channel_id)))

    async def _entity_by_link(
        self, client: TelegramClient, target: LinkTarget
    ) -> tuple[bool, object | None]:
        """링크로 채팅을 찾는다. (확인했는지, 채팅)."""
        if target.kind == LinkKind.PUBLIC:
            try:
                resolved = await client(functions.contacts.ResolveUsernameRequest(target.value))
            except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError):
                return False, None
            if isinstance(resolved.peer, types.PeerUser):
                return False, None
            return True, _pick(resolved.chats, utils.get_peer_id(resolved.peer))
        if target.kind == LinkKind.INVITE:
            return True, await self._invited_chat(client, target.value)
        return False, None

    async def list_groups(self) -> list[TgChat]:
        client = self._connected()
        with _telegram_errors():
            entities = await self._dialog_entities(client)
        return [self._chat(entity) for entity in entities.values() if _is_member(entity)]

    async def _dialog_entities(
        self, client: TelegramClient
    ) -> dict[int, types.Chat | types.Channel]:
        """대화 목록의 그룹·슈퍼그룹·채널을 marked id 로 모은다(입력 피어도 기억해 둔다)."""
        found: dict[int, types.Chat | types.Channel] = {}
        async for dialog in client.iter_dialogs(ignore_migrated=True):
            entity = dialog.entity
            if isinstance(entity, _GROUP_TYPES):
                self._remember(entity)
                found[utils.get_peer_id(entity)] = entity
        return found

    async def leave(self, tg_chat_id: int) -> None:
        client = self._connected()
        raw_id, peer_type = utils.resolve_id(tg_chat_id)
        with _telegram_errors():
            try:
                if peer_type is types.PeerChannel:
                    channel = self._channels.get(raw_id)
                    if channel is None:
                        await self._dialog_entities(client)
                        channel = self._channels.get(raw_id)
                    if channel is None:
                        # 대화 목록에 없는 채널이면 이미 멤버가 아니다.
                        logger.info("계정 %s 은(는) 이미 그 그룹에 없어요", self.account_id)
                        return
                    await client(functions.channels.LeaveChannelRequest(channel))
                elif peer_type is types.PeerChat:
                    await client(
                        functions.messages.DeleteChatUserRequest(raw_id, types.InputUserSelf())
                    )
                else:
                    raise TelegramError(
                        TgErrorCode.NOT_A_GROUP, "그룹이 아니라서 나갈 수 없어요.", permanent=True
                    )
            except _NOT_A_MEMBER:
                logger.info("계정 %s 은(는) 이미 그 그룹에 없어요", self.account_id)

    def _chat(self, entity: types.Chat | types.Channel) -> TgChat:
        self._remember(entity)
        return _to_chat(entity)

    def _remember(self, entity: object) -> None:
        """나중에 id 만으로 요청할 수 있게 채널의 입력 피어를 기억한다."""
        if isinstance(entity, types.Channel) and entity.access_hash is not None and not entity.min:
            self._channels[entity.id] = types.InputChannel(entity.id, entity.access_hash)


# ---------------------------------------------------------------------------
# 게이트웨이
# ---------------------------------------------------------------------------


@dataclass
class _Login:
    """진행 중인 로그인 절차 하나."""

    client: TelegramClient
    phone: str
    phone_code_hash: str | None
    expires_at: datetime
    timer: asyncio.Task[None]
    password_needed: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class TelethonGateway(TelegramGateway):
    """계정 연결을 만들고, 진행 중인 로그인 절차를 메모리에 들고 있는다."""

    def __init__(
        self,
        credentials: ApiCredentials,
        *,
        client_factory: ClientFactory = TelegramClient,
        login_ttl: float = LOGIN_TTL_SECONDS,
    ) -> None:
        self._credentials = credentials
        self._client_factory = client_factory
        self._login_ttl = login_ttl
        self._logins: dict[str, _Login] = {}

    def create_client(self, account_id: int, session: str) -> AccountClient:
        return TelethonAccountClient(account_id, session, self._credentials, self._client_factory)

    # --- 로그인 ------------------------------------------------------------

    async def start_login(self, phone: str) -> PendingLogin:
        number = _normalize_phone(phone)
        for login_id, login in list(self._logins.items()):
            if login.phone == number:
                await self._discard(login_id)  # 같은 번호로 다시 시작하면 앞선 절차는 버린다

        client = await _new_client(self._credentials, self._client_factory, _Session())
        try:
            with _telegram_errors(login=True):
                await client.connect()
                sent = await client.send_code_request(number)
        except BaseException:
            await _disconnect_quietly(client)
            raise

        login_id = secrets.token_urlsafe(24)
        expires_at = utcnow() + timedelta(seconds=self._login_ttl)
        self._logins[login_id] = _Login(
            client=client,
            phone=number,
            phone_code_hash=sent.phone_code_hash or None,
            expires_at=expires_at,
            timer=asyncio.create_task(self._expire(login_id)),
        )
        logger.info("로그인 인증 코드를 요청했어요")
        return PendingLogin(
            login_id=login_id,
            phone=number,
            code_via=_code_via(sent.type),
            expires_at=expires_at,
        )

    async def submit_code(self, login_id: str, code: str) -> LoginResult:
        login = self._login(login_id)
        value = _normalize_code(code)
        if not value:
            raise TelegramError(TgErrorCode.CODE_INVALID, "인증 코드를 넣어 주세요.")
        try:
            async with login.lock:
                with _telegram_errors(login=True):
                    try:
                        user = await login.client.sign_in(
                            login.phone, value, phone_code_hash=login.phone_code_hash
                        )
                    except errors.SessionPasswordNeededError:
                        login.password_needed = True
                        return LoginResult(
                            "password_required",
                            password_hint=await _password_hint(login.client),
                        )
        except TelegramError as exc:
            if exc.code == TgErrorCode.CODE_EXPIRED:
                await self._discard(login_id)  # 이 절차로는 더 진행할 수 없다
            raise
        return await self._complete(login_id, login, user)

    async def submit_password(self, login_id: str, password: str) -> LoginResult:
        login = self._login(login_id)
        if not login.password_needed:
            raise TelegramError(TgErrorCode.CODE_INVALID, "인증 코드를 먼저 넣어 주세요.")
        if not password:
            raise TelegramError(TgErrorCode.PASSWORD_INVALID, "2단계 인증 비밀번호를 넣어 주세요.")
        async with login.lock:
            with _telegram_errors(login=True):
                user = await login.client.sign_in(password=password)
        return await self._complete(login_id, login, user)

    async def cancel_login(self, login_id: str) -> None:
        await self._discard(login_id)

    async def import_session(self, data: str | bytes) -> LoginResult:
        if isinstance(data, bytes):
            text = await asyncio.to_thread(_session_text_from_file, data)
        else:
            text = data
        session = _load_session(text)
        client = await _new_client(self._credentials, self._client_factory, session)
        try:
            with _telegram_errors():
                await client.connect()
                me = await _fetch_self(client)
                # 접속하면서 DC 가 바뀌었을 수 있어 다시 뽑는다.
                return LoginResult("done", session=session.save(), user=me)
        finally:
            await _disconnect_quietly(client)

    async def close(self) -> None:
        for login_id in list(self._logins):
            await self._discard(login_id)

    def _login(self, login_id: str) -> _Login:
        login = self._logins.get(login_id)
        if login is None or login.expires_at <= utcnow():
            raise TelegramError(TgErrorCode.LOGIN_EXPIRED, _MSG_LOGIN_EXPIRED, permanent=True)
        return login

    async def _complete(self, login_id: str, login: _Login, user: object) -> LoginResult:
        """로그인이 끝났다. 세션을 뽑고 임시 연결을 닫는다."""
        with _telegram_errors():
            session = login.client.session.save()
        if not isinstance(user, types.User) or not session:
            # 유저나 인증 키 없이 성공했다고 온 경우. 저장할 세션이 없으니 끝난 것으로 치지 않는다.
            raise TelegramError(TgErrorCode.UNKNOWN, _MSG_UNKNOWN)
        await self._discard(login_id)
        logger.info("로그인을 마쳤어요")
        return LoginResult("done", session=session, user=_to_user(user, with_phone=True))

    async def _discard(self, login_id: str) -> None:
        login = self._logins.pop(login_id, None)
        if login is None:
            return
        login.timer.cancel()
        await _disconnect_quietly(login.client)

    async def _expire(self, login_id: str) -> None:
        """끝내지 않은 로그인 절차를 만료 시각에 정리한다."""
        await asyncio.sleep(self._login_ttl)
        login = self._logins.pop(login_id, None)
        if login is not None:
            logger.info("끝내지 않은 로그인 절차가 만료돼 정리했어요")
            await _disconnect_quietly(login.client)


async def _password_hint(client: TelegramClient) -> str | None:
    """2단계 인증 비밀번호 힌트. 못 가져와도 로그인은 계속할 수 있어 None 으로 넘어간다."""
    try:
        password = await client(functions.account.GetPasswordRequest())
    except Exception:
        logger.warning("2단계 인증 힌트를 가져오지 못했어요", exc_info=True)
        return None
    return password.hint or None
