"""텔레그램과 맞닿는 경계.

엔진·수집기·API 는 이 파일의 타입만 본다. 실제 구현은 telethon_gateway.py(운영)와
demo_gateway.py(데모·테스트) 두 가지다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from ..links import LinkTarget
from ..models import GroupKind

# ---------------------------------------------------------------------------
# 값 타입
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TgUser:
    id: int
    username: str | None
    first_name: str | None = None
    last_name: str | None = None
    is_bot: bool = False
    phone: str | None = None


@dataclass(frozen=True)
class TgChat:
    id: int
    """marked peer id (슈퍼그룹·채널은 -100…, 일반 그룹은 음수)."""
    title: str
    username: str | None
    kind: GroupKind
    member_count: int | None = None


@dataclass(frozen=True)
class IncomingMessage:
    account_id: int
    chat_id: int
    """TgChat.id 와 같은 marked peer id."""
    message_id: int
    sender: TgUser | None
    """유저가 아닌 발신(익명 관리자, 채널 명의 글)이면 None."""
    text: str
    date: datetime


class JoinOutcome(StrEnum):
    JOINED = "joined"
    REQUESTED = "requested"  # 입장 요청을 보냈고 관리자 승인이 필요하다


@dataclass(frozen=True)
class JoinResult:
    outcome: JoinOutcome
    chat: TgChat | None = None
    """JOINED 면 항상 채워진다. REQUESTED 면 알 수 있는 만큼만(없을 수 있다)."""
    title: str | None = None
    """chat 이 없을 때 초대 미리보기에서 알아낸 제목."""
    member_count: int | None = None


@dataclass(frozen=True)
class PendingLogin:
    login_id: str
    phone: str
    code_via: Literal["app", "sms", "call", "other"]
    expires_at: datetime


@dataclass(frozen=True)
class LoginResult:
    """로그인(또는 세션 불러오기) 결과."""

    status: Literal["done", "password_required"]
    session: str | None = None
    """status=done 일 때 저장할 StringSession."""
    user: TgUser | None = None
    password_hint: str | None = None


# ---------------------------------------------------------------------------
# 오류
# ---------------------------------------------------------------------------


class TgErrorCode(StrEnum):
    # 계정 단위
    FLOOD_WAIT = "flood_wait"  # retry_after 초 뒤에 다시
    SESSION_INVALID = "session_invalid"  # 세션 만료·해지 → 다시 로그인
    BANNED = "banned"  # 계정 정지
    NETWORK = "network"  # 일시적인 연결 문제
    API_CREDENTIALS = "api_credentials"  # api_id/api_hash 가 없거나 틀림
    # 그룹 가입
    INVITE_EXPIRED = "invite_expired"
    INVITE_INVALID = "invite_invalid"
    NOT_FOUND = "not_found"  # 그런 아이디가 없음
    NOT_A_GROUP = "not_a_group"  # 아이디가 그룹이 아니라 사람·봇을 가리킴
    PRIVATE = "private"  # 비공개이거나 접근이 막힘
    BANNED_FROM_GROUP = "banned_from_group"
    TOO_MANY_GROUPS = "too_many_groups"  # 계정이 들어갈 수 있는 그룹 수 한도
    # 로그인
    PHONE_INVALID = "phone_invalid"
    PHONE_BANNED = "phone_banned"
    CODE_INVALID = "code_invalid"
    CODE_EXPIRED = "code_expired"
    PASSWORD_INVALID = "password_invalid"
    LOGIN_EXPIRED = "login_expired"  # 로그인 절차가 만료됨(login_id 없음)
    SESSION_FORMAT = "session_format"  # 불러온 세션을 읽을 수 없음
    UNKNOWN = "unknown"


class TelegramError(Exception):
    """텔레그램 쪽 실패. message 는 화면에 보여 줄 한국어 문장이다."""

    def __init__(
        self,
        code: TgErrorCode,
        message: str,
        *,
        retry_after: int | None = None,
        permanent: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.permanent = permanent
        """True 면 다시 시도해도 소용없다."""


# ---------------------------------------------------------------------------
# 인터페이스
# ---------------------------------------------------------------------------

MessageHandler = Callable[[IncomingMessage], Awaitable[None]]
ApiCredentials = Callable[[], Awaitable[tuple[int, str]]]
"""(api_id, api_hash) 를 돌려준다. 설정돼 있지 않으면 TelegramError(API_CREDENTIALS)."""


class AccountClient(ABC):
    """계정 하나의 연결."""

    account_id: int

    @abstractmethod
    async def connect(self) -> TgUser:
        """접속하고 내 정보를 돌려준다.

        세션이 죽었으면 TelegramError(SESSION_INVALID), 정지면 BANNED,
        일시적 연결 문제면 NETWORK 를 던진다.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """연결을 끊는다. 이미 끊겨 있어도 오류가 아니다."""

    @abstractmethod
    async def wait_closed(self) -> None:
        """연결이 유지되는 동안 기다린다.

        정상적으로 끊기면 그냥 돌아오고, 세션이 무효가 되어 끊겼으면
        TelegramError(SESSION_INVALID / BANNED) 를 던진다.
        """

    @abstractmethod
    def set_message_handler(self, handler: MessageHandler | None) -> None:
        """그룹에 새 메시지가 올 때마다 부를 함수를 정한다(들어오는 메시지만)."""

    @abstractmethod
    async def join(self, target: LinkTarget) -> JoinResult:
        """그룹에 들어간다.

        이미 들어가 있으면 JOINED 로 돌려준다. 승인이 필요한 그룹이면 REQUESTED.
        이미 입장 요청을 보낸 상태여도 REQUESTED.
        실패하면 TelegramError (FLOOD_WAIT 는 retry_after 포함).
        """

    @abstractmethod
    async def find_membership(
        self, target: LinkTarget | None, tg_chat_id: int | None
    ) -> TgChat | None:
        """지금 이 그룹의 멤버인지 확인한다. 멤버면 그룹 정보를, 아니면 None.

        입장 요청이 승인됐는지 확인할 때 쓴다. target(링크)과 tg_chat_id 중 아는 것을 준다.
        """

    @abstractmethod
    async def list_groups(self) -> list[TgChat]:
        """계정이 지금 들어가 있는 그룹·슈퍼그룹·채널 목록."""

    @abstractmethod
    async def leave(self, tg_chat_id: int) -> None:
        """그룹에서 나간다. 이미 멤버가 아니면 조용히 넘어간다."""

    @abstractmethod
    async def log_out(self) -> None:
        """텔레그램에서 이 세션을 로그아웃한다(세션이 영구히 무효가 된다)."""

    @abstractmethod
    def export_session(self) -> str:
        """현재 세션 문자열. DC 이동 등으로 바뀔 수 있어 접속 뒤에 다시 저장한다."""


class TelegramGateway(ABC):
    """계정 연결을 만들고 로그인 절차를 처리한다."""

    @abstractmethod
    def create_client(self, account_id: int, session: str) -> AccountClient:
        """저장된 세션으로 연결 객체를 만든다(아직 접속하지 않는다)."""

    @abstractmethod
    async def start_login(self, phone: str) -> PendingLogin:
        """번호로 인증 코드를 보낸다. 로그인 절차는 10분 뒤 만료된다."""

    @abstractmethod
    async def submit_code(self, login_id: str, code: str) -> LoginResult:
        """인증 코드를 넣는다. 2단계 인증이 걸려 있으면 password_required."""

    @abstractmethod
    async def submit_password(self, login_id: str, password: str) -> LoginResult:
        """2단계 인증 비밀번호를 넣는다."""

    @abstractmethod
    async def cancel_login(self, login_id: str) -> None:
        """진행 중인 로그인 절차를 버린다."""

    @abstractmethod
    async def import_session(self, data: str | bytes) -> LoginResult:
        """기존 세션을 불러온다.

        data 가 str 이면 Telethon StringSession, bytes 면 Telethon .session(SQLite) 파일 내용.
        실제로 접속해 내 정보를 확인한 뒤 status=done 으로 돌려준다.
        읽을 수 없으면 TelegramError(SESSION_FORMAT), 죽은 세션이면 SESSION_INVALID.
        """

    @abstractmethod
    async def close(self) -> None:
        """진행 중인 로그인 절차를 모두 정리한다."""
