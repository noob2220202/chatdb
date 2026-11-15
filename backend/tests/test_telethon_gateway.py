"""Telethon 게이트웨이 테스트.

텔레그램에는 접속하지 않는다. 두 가지 대역을 쓴다.

- FakeClient: TelegramClient 를 통째로 바꾼 가짜. 응답을 자유롭게 짤 수 있어 대부분의 테스트가 쓴다.
  요청·이벤트·세션은 Telethon 의 실제 클래스라서, 게이트웨이가 만든 요청이 직렬화되는지도 본다.
- StubSender: 실제 TelegramClient 에서 맨 아래 전송 계층만 바꾼 것. connect, 업데이트 루프,
  로그인, FloodWait 처리 같은 Telethon 코드가 설치된 그대로 돈다(파일 끝의 test_real_* 들).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import sqlite3
import struct
import tempfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from telethon import TelegramClient, errors, events, functions, types, utils
from telethon._updates import EntityCache
from telethon.crypto import AuthKey
from telethon.sessions import SQLiteSession, StringSession
from telethon.tl import TLRequest

import app
from app.links import LinkTarget
from app.models import GroupKind, LinkKind
from app.telegram import telethon_gateway as tg
from app.telegram.gateway import (
    IncomingMessage,
    JoinOutcome,
    TelegramError,
    TgChat,
    TgErrorCode,
    TgUser,
)

API_ID = 424242
API_HASH = "c0ffee00c0ffee00c0ffee00c0ffee00"
SELF_ID = 7001
CODE = "24680"
PASSWORD = "sup3r-비밀-pass"
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)

SUPERGROUP_ID = 1001
SUPERGROUP_MARKED = -1000000001001
GROUP_ID = 2002
GROUP_MARKED = -2002

PUBLIC = LinkTarget(LinkKind.PUBLIC, "sales_talk")
INVITE = LinkTarget(LinkKind.INVITE, "AbCdEf123456")


# ---------------------------------------------------------------------------
# 재료
# ---------------------------------------------------------------------------


def session_string(*, dc_id: int = 2, address: str = "149.154.167.51", key: bytes | None = None):
    session = StringSession()
    session.set_dc(dc_id, address, 443)
    session.auth_key = AuthKey(data=key or os.urandom(256))
    return session.save()


def rpc(error_cls: type[Exception], capture: int | None = None) -> Exception:
    """실제 Telethon RPC 오류 객체."""
    if capture is None:
        return error_cls(request=None)
    return error_cls(request=None, capture=capture)


def user(user_id: int = 501, **fields: Any) -> types.User:
    fields.setdefault("first_name", "민수")
    fields.setdefault("access_hash", 11)
    return types.User(id=user_id, **fields)


def supergroup(channel_id: int = SUPERGROUP_ID, **fields: Any) -> types.Channel:
    fields.setdefault("title", "영업 이야기")
    fields.setdefault("megagroup", True)
    fields.setdefault("left", False)
    fields.setdefault("access_hash", 9090)
    return types.Channel(id=channel_id, photo=types.ChatPhotoEmpty(), date=NOW, **fields)


def broadcast(channel_id: int = 3003, **fields: Any) -> types.Channel:
    fields.setdefault("title", "공지 채널")
    return supergroup(channel_id, megagroup=False, broadcast=True, **fields)


def basic_group(chat_id: int = GROUP_ID, **fields: Any) -> types.Chat:
    fields.setdefault("title", "동네 모임")
    fields.setdefault("participants_count", 12)
    fields.setdefault("left", False)
    fields.setdefault("deactivated", False)
    return types.Chat(id=chat_id, photo=types.ChatPhotoEmpty(), date=NOW, version=1, **fields)


def updates_with(*chats: Any) -> types.Updates:
    return types.Updates(updates=[], users=[], chats=list(chats), date=NOW, seq=0)


def join_ok(*chats: Any) -> types.messages.ChatInviteJoinResultOk:
    return types.messages.ChatInviteJoinResultOk(updates_with(*chats))


def resolved(entity: Any) -> types.contacts.ResolvedPeer:
    if isinstance(entity, types.User):
        return types.contacts.ResolvedPeer(types.PeerUser(entity.id), [], [entity])
    return types.contacts.ResolvedPeer(types.PeerChannel(entity.id), [entity], [])


def invite_preview(**fields: Any) -> types.ChatInvite:
    fields.setdefault("title", "비공개 모임")
    fields.setdefault("participants_count", 340)
    return types.ChatInvite(photo=types.PhotoEmpty(id=0), color=0, **fields)


def sent_code(code_type: Any = None) -> types.auth.SentCode:
    return types.auth.SentCode(
        type=code_type or types.auth.SentCodeTypeApp(length=5), phone_code_hash="hash-1"
    )


def password_info(hint: str | None = "첫 강아지 이름") -> types.account.Password:
    return types.account.Password(
        new_algo=types.PasswordKdfAlgoUnknown(),
        new_secure_algo=types.SecurePasswordKdfAlgoUnknown(),
        secure_random=b"",
        has_password=True,
        hint=hint,
    )


ME = user(SELF_ID, first_name="내", last_name="계정", username="my_account", phone="821012345678")


# ---------------------------------------------------------------------------
# 가짜 Telethon 클라이언트
# ---------------------------------------------------------------------------


class Seq:
    """부를 때마다 다음 응답을 준다(마지막 것은 계속 쓴다)."""

    def __init__(self, *items: Any) -> None:
        self.items = list(items)

    def next(self) -> Any:
        return self.items.pop(0) if len(self.items) > 1 else self.items[0]


async def play(reply: Any, *args: Any) -> Any:
    """각본대로 응답한다: 예외면 던지고, 함수면 부르고, 그 밖엔 그대로 돌려준다."""
    if isinstance(reply, Seq):
        reply = reply.next()
    if isinstance(reply, BaseException):
        raise reply
    if callable(reply):
        reply = reply(*args)
        if inspect.isawaitable(reply):
            reply = await reply
    return reply


class Plan:
    """가짜 클라이언트들이 함께 따르는 각본."""

    def __init__(self) -> None:
        self.replies: dict[type, Any] = {functions.users.GetUsersRequest: [ME]}
        self.connect: Any = None
        self.dialogs: Any = []
        self.send_code: Any = sent_code()
        self.sign_in: Any = ME


class FakeClient:
    """게이트웨이가 쓰는 만큼만 흉내 낸 TelegramClient."""

    def __init__(self, session: Any, api_id: int, api_hash: str, **options: Any) -> None:
        self.session = session
        self.initial_session = session.save()
        self.api_id = api_id
        self.api_hash = api_hash
        self.options = options
        self.plan = Plan()
        self.requests: list[TLRequest] = []
        self.handlers: list[tuple[Any, Any]] = []
        self.code_requests: list[str] = []
        self.sign_ins: list[dict[str, Any]] = []
        self.dialog_options: list[dict[str, Any]] = []
        self.connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.closed: asyncio.Future[None] | None = None
        self._updates_error: Exception | None = None
        # 이벤트가 요청 없이 엔티티를 찾을 때 보는 것들
        self._mb_entity_cache = EntityCache()
        self._self_id = SELF_ID

    async def connect(self) -> None:
        self.connect_calls += 1
        await play(self.plan.connect)
        if not self.session.auth_key:
            # 실제 클라이언트는 새 세션으로 접속하면서 DC 를 정하고 인증 키를 만든다.
            self.session.set_dc(2, "149.154.167.51", 443)
            self.session.auth_key = AuthKey(data=os.urandom(256))
        if not self.connected:
            self.connected = True
            self.closed = asyncio.get_running_loop().create_future()

    def is_connected(self) -> bool:
        return self.connected

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False
        if self.closed is not None and not self.closed.done():
            self.closed.set_result(None)

    def drop(self, error: Exception | None = None) -> None:
        """텔레그램 쪽에서 연결이 끊긴 상황."""
        self.connected = False
        assert self.closed is not None
        if error is None:
            self.closed.set_result(None)
        else:
            self.closed.set_exception(error)

    @property
    def disconnected(self) -> asyncio.Future[None]:
        if self.closed is None:
            done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            done.set_result(None)
            return done
        return asyncio.shield(self.closed)

    def add_event_handler(self, callback: Any, event: Any = None) -> None:
        self.handlers.append((callback, event))

    async def get_input_entity(self, peer: Any) -> Any:
        # 실제 클라이언트의 첫 단계와 같다. 여기서 못 바꾸는 값은 캐시나 네트워크가 필요하다는 뜻이다.
        return utils.get_input_peer(peer)

    async def __call__(self, request: TLRequest) -> Any:
        assert isinstance(request, TLRequest)
        await request.resolve(self, utils)  # 실제 클라이언트가 보내기 전에 하는 일
        bytes(request)  # 직렬화되지 않는 요청이면 여기서 터진다
        self.requests.append(request)
        if type(request) not in self.plan.replies:
            raise AssertionError(f"각본에 없는 요청이에요: {type(request).__name__}")
        return await play(self.plan.replies[type(request)], request)

    def sent(self, request_type: type) -> list[Any]:
        return [request for request in self.requests if isinstance(request, request_type)]

    async def iter_dialogs(self, **options: Any):
        self.dialog_options.append(options)
        for entity in await play(self.plan.dialogs):
            yield SimpleNamespace(entity=entity)

    async def send_code_request(self, phone: str) -> Any:
        self.code_requests.append(phone)
        return await play(self.plan.send_code)

    async def sign_in(
        self,
        phone: str | None = None,
        code: str | None = None,
        *,
        password: str | None = None,
        phone_code_hash: str | None = None,
    ) -> Any:
        self.sign_ins.append(
            {"phone": phone, "code": code, "password": password, "hash": phone_code_hash}
        )
        return await play(self.plan.sign_in)


class Factory:
    """TelegramClient 대신 끼우는 생성자. 만든 클라이언트를 모아 둔다."""

    def __init__(self) -> None:
        self.plan = Plan()
        self.clients: list[FakeClient] = []

    def __call__(self, session: Any, api_id: int, api_hash: str, **options: Any) -> FakeClient:
        client = FakeClient(session, api_id, api_hash, **options)
        client.plan = self.plan
        self.clients.append(client)
        return client

    @property
    def last(self) -> FakeClient:
        return self.clients[-1]


async def credentials() -> tuple[int, str]:
    return API_ID, API_HASH


@pytest.fixture
def factory() -> Factory:
    return Factory()


@pytest.fixture
def plan(factory: Factory) -> Plan:
    return factory.plan


@pytest_asyncio.fixture
async def gateway(factory: Factory):
    gateway = tg.TelethonGateway(credentials, client_factory=factory)
    yield gateway
    await gateway.close()


@pytest_asyncio.fixture
async def account(gateway: tg.TelethonGateway) -> tg.TelethonAccountClient:
    """접속을 마친 계정 연결."""
    client = gateway.create_client(7, session_string())
    await client.connect()
    return client


@pytest.fixture
def fake(account: tg.TelethonAccountClient, factory: Factory) -> FakeClient:
    """account 뒤에 있는 가짜 클라이언트."""
    return factory.last


async def failure(awaitable: Any) -> TelegramError:
    with pytest.raises(TelegramError) as caught:
        await awaitable
    return caught.value


# ---------------------------------------------------------------------------
# 오류 변환
# ---------------------------------------------------------------------------

S, B, N = TgErrorCode.SESSION_INVALID, TgErrorCode.BANNED, TgErrorCode.NETWORK

MAPPING = [
    (errors.AuthKeyUnregisteredError, S, True),
    (errors.SessionRevokedError, S, True),
    (errors.SessionExpiredError, S, True),
    (errors.AuthKeyDuplicatedError, S, True),
    (errors.UserDeactivatedError, S, True),
    (errors.AuthKeyInvalidError, S, True),
    (errors.SessionPasswordNeededError, S, True),
    (errors.UserDeactivatedBanError, B, True),
    (errors.PhoneNumberBannedError, B, True),
    (errors.FrozenMethodInvalidError, B, True),
    (errors.ApiIdInvalidError, TgErrorCode.API_CREDENTIALS, True),
    (errors.ApiIdPublishedFloodError, TgErrorCode.API_CREDENTIALS, True),
    (errors.InviteHashExpiredError, TgErrorCode.INVITE_EXPIRED, True),
    (errors.InviteHashInvalidError, TgErrorCode.INVITE_INVALID, True),
    (errors.InviteHashEmptyError, TgErrorCode.INVITE_INVALID, True),
    (errors.UsernameNotOccupiedError, TgErrorCode.NOT_FOUND, True),
    (errors.UsernameInvalidError, TgErrorCode.NOT_FOUND, True),
    (errors.ChannelsTooMuchError, TgErrorCode.TOO_MANY_GROUPS, True),
    (errors.ChannelPrivateError, TgErrorCode.PRIVATE, True),
    (errors.ChannelBannedError, TgErrorCode.PRIVATE, True),
    (errors.UsersTooMuchError, TgErrorCode.PRIVATE, True),
    (errors.UserBannedInChannelError, TgErrorCode.BANNED_FROM_GROUP, True),
    (errors.PhoneNumberInvalidError, TgErrorCode.PHONE_INVALID, True),
    (errors.PhoneNumberUnoccupiedError, TgErrorCode.PHONE_INVALID, True),
    (errors.PhoneCodeInvalidError, TgErrorCode.CODE_INVALID, False),
    (errors.PhoneCodeEmptyError, TgErrorCode.CODE_INVALID, False),
    (errors.PhoneCodeExpiredError, TgErrorCode.CODE_EXPIRED, True),
    (errors.PasswordHashInvalidError, TgErrorCode.PASSWORD_INVALID, False),
    (errors.PhoneNumberFloodError, TgErrorCode.FLOOD_WAIT, False),
    (errors.PhonePasswordFloodError, TgErrorCode.FLOOD_WAIT, False),
    (errors.RpcCallFailError, N, False),
    (errors.TimedOutError, N, False),
]


@pytest.mark.parametrize(("error_cls", "code", "permanent"), MAPPING)
def test_rpc_errors_map_to_codes(error_cls, code, permanent):
    if error_cls is errors.TimedOutError:
        error = error_cls(request=None, message="Timeout")
    else:
        error = rpc(error_cls)

    mapped = tg.to_telegram_error(error)

    assert mapped.code == code
    assert mapped.permanent is permanent
    assert mapped.retry_after is None


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("Connection to Telegram failed 5 time(s)"),
        ConnectionResetError(),
        OSError("network is unreachable"),
        TimeoutError(),
        asyncio.TimeoutError(),  # noqa: UP041 - Telethon 이 이 이름으로 던진다
        asyncio.IncompleteReadError(b"", 8),
    ],
)
def test_connection_problems_map_to_network(error):
    mapped = tg.to_telegram_error(error)

    assert mapped.code == TgErrorCode.NETWORK
    assert mapped.permanent is False


@pytest.mark.parametrize(
    "error_cls",
    [errors.FloodWaitError, errors.FloodPremiumWaitError, errors.FloodTestPhoneWaitError],
)
def test_flood_wait_keeps_the_requested_seconds(error_cls):
    mapped = tg.to_telegram_error(rpc(error_cls, capture=3725))

    assert mapped.code == TgErrorCode.FLOOD_WAIT
    assert mapped.retry_after == 3725
    assert mapped.permanent is False
    assert "1시간 3분" in mapped.message


def test_flood_wait_of_zero_seconds_still_waits():
    assert tg.to_telegram_error(rpc(errors.FloodWaitError, capture=0)).retry_after == 1


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(7, "7초"), (60, "1분"), (95, "1분 35초"), (3600, "1시간"), (3601, "1시간 1분")],
)
def test_wait_is_written_for_people(seconds, text):
    assert tg._format_wait(seconds) == text


def test_login_screen_reports_a_banned_number_as_phone_banned():
    banned = rpc(errors.PhoneNumberBannedError)

    assert tg.to_telegram_error(banned, login=True).code == TgErrorCode.PHONE_BANNED
    assert tg.to_telegram_error(banned).code == TgErrorCode.BANNED


def test_transport_level_errors():
    forgotten = errors.InvalidBufferError(struct.pack("<i", -404))
    limited = errors.InvalidBufferError(struct.pack("<i", -429))

    assert tg.to_telegram_error(errors.AuthKeyNotFound()).code == TgErrorCode.SESSION_INVALID
    assert tg.to_telegram_error(forgotten).code == TgErrorCode.SESSION_INVALID
    assert tg.to_telegram_error(limited).code == TgErrorCode.NETWORK
    assert tg.to_telegram_error(errors.InvalidBufferError(b"??")).code == TgErrorCode.NETWORK


def test_telegram_error_passes_through_unchanged():
    original = TelegramError(TgErrorCode.PRIVATE, "이미 바뀐 오류예요.")

    assert tg.to_telegram_error(original) is original


def test_unknown_error_becomes_unknown_and_is_logged(caplog):
    caplog.set_level(logging.DEBUG)
    original = RuntimeError("처음 보는 실패")

    mapped = tg.to_telegram_error(original)

    assert mapped.code == TgErrorCode.UNKNOWN
    assert mapped.permanent is False
    assert mapped.message.endswith("요.")
    logged = [record for record in caplog.records if record.exc_info]
    assert logged and logged[0].exc_info[1] is original
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize(
    "error_cls",
    [errors.ChatAdminRequiredError, errors.ChannelInvalidError, errors.ChatWriteForbiddenError],
)
def test_unknown_refusal_is_not_worth_repeating(error_cls, caplog):
    """분류하지 못한 400·403 은 같은 요청을 다시 보내도 소용없다고 알린다."""
    original = rpc(error_cls)

    mapped = tg.to_telegram_error(original)

    assert mapped.code == TgErrorCode.UNKNOWN
    assert mapped.permanent is True
    assert mapped.message.endswith("요.")
    assert error_cls.__name__ in caplog.text


def test_group_access_errors_have_their_own_messages():
    messages = {
        tg.to_telegram_error(rpc(error_cls)).message
        for error_cls in (
            errors.ChannelPrivateError,
            errors.ChannelBannedError,
            errors.UsersTooMuchError,
        )
    }

    assert len(messages) == 3


def test_rules_never_hide_a_later_rule():
    """앞선 규칙의 클래스가 뒤 규칙 클래스의 상위 클래스면 뒤 규칙은 영영 쓰이지 않는다."""
    rules = (*tg._LOGIN_RULES, *tg._RULES)
    for index, later in enumerate(rules):
        for earlier in rules[:index]:
            if earlier in tg._LOGIN_RULES and later in tg._RULES:
                continue  # 로그인 규칙은 일부러 앞에서 가로챈다
            for kind in later.kinds:
                assert not issubclass(kind, earlier.kinds), (kind, earlier.kinds)


def test_every_message_is_a_short_korean_sentence():
    for rule in (*tg._LOGIN_RULES, *tg._RULES):
        assert rule.message.endswith("."), rule.message
        assert "요" in rule.message, rule.message
        assert len(rule.message) <= 80, rule.message


# ---------------------------------------------------------------------------
# 클라이언트 만들기
# ---------------------------------------------------------------------------


async def test_real_telegram_client_accepts_our_options():
    client = tg._make_client(TelegramClient, tg._load_session(session_string()), API_ID, API_HASH)

    assert client.flood_sleep_threshold == 0
    assert client._init_request.device_model == "ChatDB"
    assert client._init_request.app_version == app.__version__
    assert client._auto_reconnect is True
    assert client._raise_last_call_error is True
    assert client.api_id == API_ID


def test_gateway_uses_the_real_telegram_client_by_default():
    gateway = tg.TelethonGateway(credentials)

    assert gateway._client_factory is TelegramClient
    assert gateway._login_ttl == 600


async def test_client_is_created_on_connect_with_honest_identity(gateway, factory):
    stored = session_string()
    account = gateway.create_client(7, stored)
    assert factory.clients == []  # create_client 는 아직 접속하지 않는다

    await account.connect()

    fake = factory.last
    assert (fake.api_id, fake.api_hash) == (API_ID, API_HASH)
    assert isinstance(fake.session, StringSession)
    assert fake.session.save() == stored
    assert fake.options["flood_sleep_threshold"] == 0
    assert fake.options["device_model"] == "ChatDB"
    assert fake.options["app_version"] == app.__version__
    assert fake.options["auto_reconnect"] is True
    assert set(fake.options) == set(tg._CLIENT_OPTIONS)  # 프록시·기기 위장 같은 옵션은 없다


def test_session_does_not_pile_up_entities():
    session = tg._load_session(session_string())

    session.process_entities(updates_with(supergroup()))
    session.process_entities([user(username="minsu")])

    assert session._entities == set()


# ---------------------------------------------------------------------------
# 접속
# ---------------------------------------------------------------------------


async def test_connect_returns_my_user(gateway, factory):
    account = gateway.create_client(7, session_string())

    me = await account.connect()

    assert me == TgUser(
        id=SELF_ID,
        username="my_account",
        first_name="내",
        last_name="계정",
        is_bot=False,
        phone="+821012345678",
    )
    assert factory.last.connected
    assert account.account_id == 7
    assert len(factory.last.sent(functions.users.GetUsersRequest)) == 1


async def test_connect_uses_active_username_when_main_one_is_empty(gateway, plan):
    plan.replies[functions.users.GetUsersRequest] = [
        user(
            SELF_ID,
            usernames=[
                types.Username("old_name", active=False),
                types.Username("collectible", active=True),
            ],
        )
    ]

    me = await gateway.create_client(7, session_string()).connect()

    assert me.username == "collectible"
    assert me.phone is None


@pytest.mark.parametrize(
    ("error", "code", "permanent"),
    [
        (rpc(errors.AuthKeyUnregisteredError), TgErrorCode.SESSION_INVALID, True),
        (rpc(errors.SessionRevokedError), TgErrorCode.SESSION_INVALID, True),
        (rpc(errors.UserDeactivatedBanError), TgErrorCode.BANNED, True),
        (rpc(errors.FloodWaitError, capture=40), TgErrorCode.FLOOD_WAIT, False),
        (ConnectionError("Cannot send requests while disconnected"), TgErrorCode.NETWORK, False),
    ],
)
async def test_connect_reports_why_the_session_is_unusable(
    gateway, factory, plan, error, code, permanent
):
    plan.replies[functions.users.GetUsersRequest] = error

    caught = await failure(gateway.create_client(7, session_string()).connect())

    assert caught.code == code
    assert caught.permanent is permanent
    assert caught.__cause__ is error
    assert factory.last.disconnect_calls == 1  # 실패하면 연결을 남겨 두지 않는다
    assert not factory.last.connected


@pytest.mark.parametrize("users", [[], [types.UserEmpty(id=SELF_ID)]])
async def test_connect_without_a_logged_in_user_is_session_invalid(gateway, factory, plan, users):
    plan.replies[functions.users.GetUsersRequest] = users

    caught = await failure(gateway.create_client(7, session_string()).connect())

    assert caught.code == TgErrorCode.SESSION_INVALID
    assert caught.permanent
    assert not factory.last.connected


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ConnectionError("Connection to Telegram failed 5 time(s)"), TgErrorCode.NETWORK),
        (TimeoutError(), TgErrorCode.NETWORK),
        (errors.AuthKeyNotFound(), TgErrorCode.SESSION_INVALID),
        (rpc(errors.ApiIdInvalidError), TgErrorCode.API_CREDENTIALS),
    ],
)
async def test_connect_maps_transport_failures(gateway, factory, plan, error, code):
    plan.connect = error

    caught = await failure(gateway.create_client(7, session_string()).connect())

    assert caught.code == code
    assert factory.last.requests == []


@pytest.mark.parametrize("stored", ["", "1not-a-session", "2AAAA", "한글세션"])
async def test_unreadable_stored_session_needs_a_new_login(gateway, factory, stored):
    caught = await failure(gateway.create_client(7, stored).connect())

    assert caught.code == TgErrorCode.SESSION_INVALID
    assert caught.permanent
    assert factory.clients == []


async def test_missing_api_credentials_are_reported_as_is(factory):
    async def no_credentials() -> tuple[int, str]:
        raise TelegramError(TgErrorCode.API_CREDENTIALS, "API 키가 아직 없어요.", permanent=True)

    gateway = tg.TelethonGateway(no_credentials, client_factory=factory)

    caught = await failure(gateway.create_client(7, session_string()).connect())

    assert caught.code == TgErrorCode.API_CREDENTIALS
    assert caught.message == "API 키가 아직 없어요."
    assert factory.clients == []


async def test_connect_twice_keeps_the_same_connection(account, factory):
    await account.connect()

    assert len(factory.clients) == 1


async def test_reconnect_builds_a_new_client_from_the_latest_session(account, factory):
    first = factory.last
    first.session.set_dc(4, "149.154.167.91", 443)  # 접속 중에 DC 가 바뀐 상황
    moved = first.session.save()

    await account.disconnect()
    await account.connect()

    assert len(factory.clients) == 2
    assert factory.last.session.save() == moved
    assert account.export_session() == moved
    assert first.disconnect_calls >= 1


async def test_export_session_before_connect_is_the_stored_one(gateway):
    stored = session_string()

    assert gateway.create_client(7, stored).export_session() == stored


async def test_disconnect_is_harmless_when_not_connected(gateway, account, fake):
    await gateway.create_client(8, session_string()).disconnect()
    await account.disconnect()
    await account.disconnect()

    assert not fake.connected


async def test_disconnect_failure_is_logged_not_raised(account, fake, caplog, monkeypatch):
    async def broken() -> None:
        raise OSError("socket already closed")

    monkeypatch.setattr(fake, "disconnect", broken)

    await account.disconnect()

    assert "정리하다" in caplog.text


async def test_calls_before_connect_are_network_errors(gateway):
    account = gateway.create_client(7, session_string())

    for call in (
        account.join(PUBLIC),
        account.find_membership(PUBLIC, None),
        account.list_groups(),
        account.leave(SUPERGROUP_MARKED),
    ):
        caught = await failure(call)
        assert caught.code == TgErrorCode.NETWORK
        assert not caught.permanent


# ---------------------------------------------------------------------------
# 연결이 끊길 때
# ---------------------------------------------------------------------------


async def test_wait_closed_returns_when_we_disconnect(account):
    waiter = asyncio.create_task(account.wait_closed())
    await asyncio.sleep(0)
    assert not waiter.done()

    await account.disconnect()

    assert await waiter is None


async def test_wait_closed_returns_at_once_without_a_connection(gateway):
    await gateway.create_client(7, session_string()).wait_closed()


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (rpc(errors.AuthKeyUnregisteredError), TgErrorCode.SESSION_INVALID),
        (rpc(errors.SessionRevokedError), TgErrorCode.SESSION_INVALID),
        (rpc(errors.AuthKeyDuplicatedError), TgErrorCode.SESSION_INVALID),
        (rpc(errors.UserDeactivatedBanError), TgErrorCode.BANNED),
    ],
)
async def test_wait_closed_raises_when_the_session_died_while_listening(account, fake, error, code):
    waiter = asyncio.create_task(account.wait_closed())
    await asyncio.sleep(0)

    # Telethon 의 업데이트 루프는 이유를 _updates_error 에 남기고 평소처럼 끊는다.
    fake._updates_error = error
    fake.drop()

    caught = await failure(waiter)
    assert caught.code == code
    assert caught.permanent


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ConnectionError("Connection to Telegram failed 5 time(s)"), TgErrorCode.NETWORK),
        (errors.AuthKeyNotFound(), TgErrorCode.SESSION_INVALID),
    ],
)
async def test_wait_closed_raises_when_reconnecting_failed(account, fake, error, code):
    fake.drop(error)

    assert (await failure(account.wait_closed())).code == code


async def test_cancelling_wait_closed_leaves_the_connection_alone(account, fake):
    waiter = asyncio.create_task(account.wait_closed())
    await asyncio.sleep(0)

    waiter.cancel()

    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert fake.connected
    assert fake.disconnect_calls == 0


async def test_request_dropped_by_a_disconnect_is_a_network_error(account, plan):
    """Telethon 은 끊을 때 대기 중인 요청의 future 를 cancel 한다. 태스크 취소와 구분해야 한다."""
    pending: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    plan.replies[functions.contacts.ResolveUsernameRequest] = lambda request: pending
    joining = asyncio.create_task(account.join(PUBLIC))
    await asyncio.sleep(0.01)

    pending.cancel()

    caught = await failure(joining)
    assert caught.code == TgErrorCode.NETWORK
    assert not caught.permanent


async def test_cancelling_our_task_is_not_turned_into_an_error(account, plan):
    pending: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    plan.replies[functions.contacts.ResolveUsernameRequest] = lambda request: pending
    joining = asyncio.create_task(account.join(PUBLIC))
    await asyncio.sleep(0.01)

    joining.cancel()

    with pytest.raises(asyncio.CancelledError):
        await joining


# ---------------------------------------------------------------------------
# 메시지 수신
# ---------------------------------------------------------------------------


def message_update(
    peer: Any,
    *,
    sender: Any = 501,
    text: str | None = "견적 문의드립니다",
    out: bool = False,
    post: bool = False,
    message_id: int = 31,
) -> Any:
    author = types.PeerUser(sender) if isinstance(sender, int) else sender
    message = types.Message(
        id=message_id, peer_id=peer, date=NOW, message=text, out=out, post=post, from_id=author
    )
    if isinstance(peer, types.PeerChannel):
        return types.UpdateNewChannelMessage(message, pts=1, pts_count=1)
    return types.UpdateNewMessage(message, pts=1, pts_count=1)


async def deliver(client: FakeClient, update: Any, *entities: Any) -> None:
    """Telethon 의 _dispatch_update 가 하는 대로 이벤트를 만들어 등록된 핸들러에 넘긴다."""
    update._entities = {utils.get_peer_id(entity): entity for entity in entities}
    for callback, builder in client.handlers:
        event = builder.build(update, None, client._self_id)
        if not event:
            continue
        event.original_update = update
        event._entities = update._entities
        event._set_client(client)
        if not builder.resolved:
            await builder.resolve(client)
        if not builder.filter(event):
            continue
        await callback(event)


@pytest.fixture
def inbox(account: tg.TelethonAccountClient) -> list[IncomingMessage]:
    received: list[IncomingMessage] = []

    async def handler(message: IncomingMessage) -> None:
        received.append(message)

    account.set_message_handler(handler)
    return received


IN_SUPERGROUP = types.PeerChannel(SUPERGROUP_ID)
IN_GROUP = types.PeerChat(GROUP_ID)


async def test_handler_listens_to_incoming_new_messages_only(fake):
    [(callback, builder)] = fake.handlers

    assert isinstance(builder, events.NewMessage)
    assert builder.incoming is True
    assert builder.outgoing is False
    assert builder.chats is None
    assert callable(callback)


async def test_supergroup_message_is_forwarded(fake, inbox):
    sender = user(username="minsu_kim", last_name="김")

    await deliver(fake, message_update(IN_SUPERGROUP), sender, supergroup())

    assert inbox == [
        IncomingMessage(
            account_id=7,
            chat_id=SUPERGROUP_MARKED,
            message_id=31,
            sender=TgUser(id=501, username="minsu_kim", first_name="민수", last_name="김"),
            text="견적 문의드립니다",
            date=NOW,
        )
    ]
    assert inbox[0].date.tzinfo is not None
    assert fake.requests[1:] == []  # 접속 때 한 요청 말고는 아무것도 보내지 않는다


async def test_basic_group_message_is_forwarded(fake, inbox):
    await deliver(fake, message_update(IN_GROUP), user(username="minsu_kim"), basic_group())

    assert [message.chat_id for message in inbox] == [GROUP_MARKED]
    assert inbox[0].sender.username == "minsu_kim"


async def test_private_chat_is_not_forwarded(fake, inbox):
    update = message_update(types.PeerUser(501), sender=None)

    await deliver(fake, update, user(username="minsu_kim"))

    assert inbox == []


async def test_channel_post_is_not_forwarded(fake, inbox):
    channel = broadcast()
    peer = types.PeerChannel(channel.id)

    await deliver(fake, message_update(peer, sender=None, post=True), channel)
    await deliver(fake, message_update(peer, sender=None, post=True))  # 채널 정보 없이 와도
    await deliver(fake, message_update(peer, sender=501), user(), channel)  # post 표시가 없어도

    assert inbox == []


async def test_outgoing_message_is_not_forwarded(fake, inbox):
    await deliver(fake, message_update(IN_SUPERGROUP, sender=SELF_ID, out=True), ME, supergroup())

    assert inbox == []


async def test_bot_sender_is_marked_as_bot(fake, inbox):
    await deliver(fake, message_update(IN_SUPERGROUP), user(bot=True, username="helper_bot"))

    assert inbox[0].sender.is_bot is True
    assert inbox[0].sender.username == "helper_bot"


async def test_sender_without_username_is_forwarded_without_one(fake, inbox):
    await deliver(fake, message_update(IN_SUPERGROUP), user(), supergroup())

    assert inbox[0].sender == TgUser(id=501, username=None, first_name="민수")


async def test_sender_username_falls_back_to_the_first_active_one(fake, inbox):
    sender = user(
        username=None,
        usernames=[
            types.Username("retired", active=False),
            types.Username("gold_name", active=True),
            types.Username("second", active=True),
        ],
    )

    await deliver(fake, message_update(IN_SUPERGROUP), sender, supergroup())

    assert inbox[0].sender.username == "gold_name"


async def test_sender_phone_is_never_forwarded(fake, inbox):
    await deliver(fake, message_update(IN_SUPERGROUP), user(username="x", phone="821099998888"))

    assert inbox[0].sender.phone is None


async def test_anonymous_admin_has_no_sender(fake, inbox):
    await deliver(fake, message_update(IN_SUPERGROUP, sender=None), supergroup())

    assert len(inbox) == 1
    assert inbox[0].sender is None
    assert inbox[0].chat_id == SUPERGROUP_MARKED


async def test_message_written_as_a_channel_has_no_sender(fake, inbox):
    linked = broadcast()
    update = message_update(IN_SUPERGROUP, sender=types.PeerChannel(linked.id))

    await deliver(fake, update, linked, supergroup())

    assert len(inbox) == 1
    assert inbox[0].sender is None


async def test_unknown_sender_is_not_looked_up_over_the_network(fake, inbox):
    await deliver(fake, message_update(IN_SUPERGROUP), supergroup())

    assert len(inbox) == 1
    assert inbox[0].sender is None
    assert fake.requests[1:] == []


async def test_short_group_update_uses_what_we_saw_before(fake, inbox):
    """일반 그룹의 짧은 업데이트에는 유저 정보가 실려 오지 않는다."""
    short = types.UpdateShortChatMessage(
        id=40, from_id=501, chat_id=GROUP_ID, message="저도요", pts=2, pts_count=1, date=NOW
    )

    await deliver(fake, short)
    await deliver(fake, message_update(IN_GROUP), user(username="minsu_kim"), basic_group())
    await deliver(fake, short)

    assert [message.sender for message in inbox] == [
        None,
        TgUser(id=501, username="minsu_kim", first_name="민수"),
        TgUser(id=501, username="minsu_kim", first_name="민수"),
    ]
    assert inbox[2].chat_id == GROUP_MARKED
    assert inbox[2].text == "저도요"
    assert fake.requests[1:] == []


async def test_min_user_does_not_replace_what_we_know(fake, inbox):
    partial = user(min=True, first_name="민수", username=None)

    await deliver(fake, message_update(IN_SUPERGROUP), partial, supergroup())
    await deliver(fake, message_update(IN_SUPERGROUP), user(username="minsu_kim"), supergroup())
    await deliver(fake, message_update(IN_SUPERGROUP), partial, supergroup())

    assert [message.sender.username for message in inbox] == [None, "minsu_kim", "minsu_kim"]


async def test_newer_full_user_replaces_the_remembered_one(fake, inbox):
    await deliver(fake, message_update(IN_SUPERGROUP), user(username="before"), supergroup())
    await deliver(fake, message_update(IN_SUPERGROUP), user(username="after"), supergroup())
    await deliver(fake, message_update(IN_SUPERGROUP), supergroup())

    assert [message.sender.username for message in inbox] == ["before", "after", "after"]


def test_user_memo_forgets_the_least_recently_seen():
    memo = tg._UserMemo(2)
    memo.put(TgUser(id=1, username="one"))
    memo.put(TgUser(id=2, username="two"))
    assert memo.get(1) is not None  # 1 을 다시 봤다

    memo.put(TgUser(id=3, username="three"))

    assert memo.get(2) is None
    assert memo.get(1).username == "one"
    assert memo.get(3).username == "three"


async def test_message_without_text_is_forwarded_as_empty(fake, inbox):
    await deliver(fake, message_update(IN_SUPERGROUP, text=None), user(), supergroup())

    assert inbox[0].text == ""


async def test_naive_date_is_treated_as_utc(fake, inbox):
    update = message_update(IN_SUPERGROUP)
    update.message.date = NOW.replace(tzinfo=None)

    await deliver(fake, update, user(), supergroup())

    assert inbox[0].date == NOW


async def test_handler_failure_is_logged_and_listening_goes_on(account, fake, caplog):
    seen: list[int] = []

    async def handler(message: IncomingMessage) -> None:
        seen.append(message.message_id)
        if message.message_id == 1:
            raise RuntimeError("수집기가 넘어졌어요")

    account.set_message_handler(handler)

    await deliver(fake, message_update(IN_SUPERGROUP, message_id=1), user(), supergroup())
    await deliver(fake, message_update(IN_SUPERGROUP, message_id=2), user(), supergroup())

    assert seen == [1, 2]
    assert "처리하지 못했어요" in caplog.text
    assert "수집기가 넘어졌어요" in caplog.text


async def test_no_handler_means_nothing_is_forwarded(account, fake, inbox):
    account.set_message_handler(None)

    await deliver(fake, message_update(IN_SUPERGROUP), user(), supergroup())

    assert inbox == []


async def test_handler_set_before_connect_is_used(gateway, factory):
    account = gateway.create_client(7, session_string())
    received: list[IncomingMessage] = []

    async def handler(message: IncomingMessage) -> None:
        received.append(message)

    account.set_message_handler(handler)
    await account.connect()

    await deliver(factory.last, message_update(IN_SUPERGROUP), user(), supergroup())

    assert len(received) == 1


# ---------------------------------------------------------------------------
# 그룹 가입: 공개 아이디
# ---------------------------------------------------------------------------


async def test_join_public_group(account, fake, plan):
    before = supergroup(left=True, username="sales_talk", participants_count=1500)
    after = supergroup(left=False, username="sales_talk", participants_count=1501)
    plan.replies[functions.contacts.ResolveUsernameRequest] = resolved(before)
    plan.replies[functions.channels.JoinChannelRequest] = join_ok(after)

    result = await account.join(PUBLIC)

    assert result.outcome == JoinOutcome.JOINED
    assert result.chat == TgChat(
        id=SUPERGROUP_MARKED,
        title="영업 이야기",
        username="sales_talk",
        kind=GroupKind.SUPERGROUP,
        member_count=1501,
    )
    assert (result.title, result.member_count) == ("영업 이야기", 1501)
    [lookup] = fake.sent(functions.contacts.ResolveUsernameRequest)
    assert lookup.username == "sales_talk"
    [request] = fake.sent(functions.channels.JoinChannelRequest)
    assert request.channel == types.InputChannel(SUPERGROUP_ID, 9090)


async def test_join_public_accepts_plain_updates_as_the_answer(account, plan):
    plan.replies[functions.contacts.ResolveUsernameRequest] = resolved(supergroup(left=True))
    plan.replies[functions.channels.JoinChannelRequest] = updates_with(supergroup(left=False))

    result = await account.join(PUBLIC)

    assert result.outcome == JoinOutcome.JOINED
    assert result.chat.id == SUPERGROUP_MARKED


async def test_join_public_without_chats_in_the_answer_uses_the_resolved_one(account, plan):
    plan.replies[functions.contacts.ResolveUsernameRequest] = resolved(supergroup(left=True))
    plan.replies[functions.channels.JoinChannelRequest] = join_ok()

    result = await account.join(PUBLIC)

    assert result.outcome == JoinOutcome.JOINED
    assert result.chat.id == SUPERGROUP_MARKED


async def test_join_public_when_already_a_member_sends_no_join(account, fake, plan):
    plan.replies[functions.contacts.ResolveUsernameRequest] = resolved(supergroup(left=False))

    result = await account.join(PUBLIC)

    assert result.outcome == JoinOutcome.JOINED
    assert result.chat.id == SUPERGROUP_MARKED
    assert fake.sent(functions.channels.JoinChannelRequest) == []


async def test_join_public_channel_is_reported_as_a_channel(account, plan):
    channel = broadcast(left=True, username="sales_talk")
    plan.replies[functions.contacts.ResolveUsernameRequest] = resolved(channel)
    plan.replies[functions.channels.JoinChannelRequest] = join_ok(broadcast(left=False))

    result = await account.join(PUBLIC)

    assert result.chat.kind == GroupKind.CHANNEL
    assert result.chat.id == -1000000003003


@pytest.mark.parametrize("target", [user(username="sales_talk"), user(bot=True)])
async def test_join_public_pointing_at_a_person_or_bot(account, fake, plan, target):
    plan.replies[functions.contacts.ResolveUsernameRequest] = resolved(target)

    caught = await failure(account.join(PUBLIC))

    assert caught.code == TgErrorCode.NOT_A_GROUP
    assert caught.permanent
    assert fake.sent(functions.channels.JoinChannelRequest) == []


@pytest.mark.parametrize(
    "reply",
    [
        rpc(errors.UsernameNotOccupiedError),
        rpc(errors.UsernameInvalidError),
        types.contacts.ResolvedPeer(types.PeerChannel(SUPERGROUP_ID), [], []),
    ],
)
async def test_join_public_unknown_username(account, plan, reply):
    plan.replies[functions.contacts.ResolveUsernameRequest] = reply

    caught = await failure(account.join(PUBLIC))

    assert caught.code == TgErrorCode.NOT_FOUND
    assert caught.permanent


async def test_join_public_forbidden_group_is_private(account, plan):
    forbidden = types.ChannelForbidden(id=SUPERGROUP_ID, access_hash=1, title="막힌 곳")
    plan.replies[functions.contacts.ResolveUsernameRequest] = resolved(forbidden)

    caught = await failure(account.join(PUBLIC))

    assert caught.code == TgErrorCode.PRIVATE
    assert caught.permanent


async def test_join_public_that_needs_approval_is_requested(account, plan):
    pending = supergroup(left=True, join_request=True, participants_count=88)
    plan.replies[functions.contacts.ResolveUsernameRequest] = resolved(pending)
    plan.replies[functions.channels.JoinChannelRequest] = rpc(errors.InviteRequestSentError)

    result = await account.join(PUBLIC)

    assert result.outcome == JoinOutcome.REQUESTED
    assert result.chat.id == SUPERGROUP_MARKED
    assert (result.title, result.member_count) == ("영업 이야기", 88)


async def test_join_public_already_participant_is_joined(account, plan):
    plan.replies[functions.contacts.ResolveUsernameRequest] = resolved(supergroup(left=True))
    plan.replies[functions.channels.JoinChannelRequest] = rpc(errors.UserAlreadyParticipantError)

    result = await account.join(PUBLIC)

    assert result.outcome == JoinOutcome.JOINED
    assert result.chat.id == SUPERGROUP_MARKED


JOIN_ERRORS = [
    (rpc(errors.ChannelsTooMuchError), TgErrorCode.TOO_MANY_GROUPS, True, None),
    (rpc(errors.ChannelPrivateError), TgErrorCode.PRIVATE, True, None),
    (rpc(errors.ChannelBannedError), TgErrorCode.PRIVATE, True, None),
    (rpc(errors.UsersTooMuchError), TgErrorCode.PRIVATE, True, None),
    (rpc(errors.UserBannedInChannelError), TgErrorCode.BANNED_FROM_GROUP, True, None),
    (rpc(errors.FloodWaitError, capture=612), TgErrorCode.FLOOD_WAIT, False, 612),
    (rpc(errors.AuthKeyUnregisteredError), TgErrorCode.SESSION_INVALID, True, None),
    (rpc(errors.ChatAdminRequiredError), TgErrorCode.UNKNOWN, True, None),
    (RuntimeError("처음 보는 실패"), TgErrorCode.UNKNOWN, False, None),
]


@pytest.mark.parametrize(("error", "code", "permanent", "retry_after"), JOIN_ERRORS)
async def test_join_public_failures(account, fake, plan, error, code, permanent, retry_after):
    plan.replies[functions.contacts.ResolveUsernameRequest] = resolved(supergroup(left=True))
    plan.replies[functions.channels.JoinChannelRequest] = error

    caught = await failure(account.join(PUBLIC))

    assert (caught.code, caught.permanent, caught.retry_after) == (code, permanent, retry_after)
    assert len(fake.sent(functions.channels.JoinChannelRequest)) == 1  # 다시 시도하지 않는다


async def test_flood_wait_while_resolving_is_not_retried(account, fake, plan):
    plan.replies[functions.contacts.ResolveUsernameRequest] = rpc(errors.FloodWaitError, 86400)

    caught = await failure(account.join(PUBLIC))

    assert (caught.code, caught.retry_after) == (TgErrorCode.FLOOD_WAIT, 86400)
    assert len(fake.sent(functions.contacts.ResolveUsernameRequest)) == 1


async def test_join_that_needs_a_bot_screen_is_not_attempted_further(account, plan):
    plan.replies[functions.contacts.ResolveUsernameRequest] = resolved(supergroup(left=True))
    plan.replies[functions.channels.JoinChannelRequest] = (
        types.messages.ChatInviteJoinResultWebView(bot_id=1, query_id=2, users=[])
    )

    caught = await failure(account.join(PUBLIC))

    assert caught.code == TgErrorCode.PRIVATE
    assert caught.permanent


async def test_join_rejects_a_link_kind_it_cannot_join(account):
    with pytest.raises(ValueError):
        await account.join(LinkTarget(LinkKind.EXISTING, "whatever"))


# ---------------------------------------------------------------------------
# 그룹 가입: 초대 링크
# ---------------------------------------------------------------------------

CHECK = functions.messages.CheckChatInviteRequest
IMPORT = functions.messages.ImportChatInviteRequest


async def test_join_invite(account, fake, plan):
    plan.replies[CHECK] = invite_preview()
    plan.replies[IMPORT] = join_ok(supergroup(left=False, title="비공개 모임"))

    result = await account.join(INVITE)

    assert result.outcome == JoinOutcome.JOINED
    assert result.chat == TgChat(
        id=SUPERGROUP_MARKED, title="비공개 모임", username=None, kind=GroupKind.SUPERGROUP
    )
    assert [request.hash for request in fake.sent(CHECK)] == ["AbCdEf123456"]
    assert [request.hash for request in fake.sent(IMPORT)] == ["AbCdEf123456"]


async def test_join_invite_into_a_basic_group(account, plan):
    plan.replies[CHECK] = invite_preview()
    plan.replies[IMPORT] = join_ok(basic_group())

    result = await account.join(INVITE)

    assert result.chat == TgChat(
        id=GROUP_MARKED,
        title="동네 모임",
        username=None,
        kind=GroupKind.GROUP,
        member_count=12,
    )


async def test_join_invite_picks_the_chat_we_are_now_in(account, plan):
    linked = broadcast(left=True)
    plan.replies[CHECK] = invite_preview()
    plan.replies[IMPORT] = join_ok(linked, supergroup(left=False))

    result = await account.join(INVITE)

    assert result.chat.id == SUPERGROUP_MARKED


async def test_join_invite_when_already_a_member_sends_no_import(account, fake, plan):
    plan.replies[CHECK] = types.ChatInviteAlready(supergroup())

    result = await account.join(INVITE)

    assert result.outcome == JoinOutcome.JOINED
    assert result.chat.id == SUPERGROUP_MARKED
    assert fake.sent(IMPORT) == []


async def test_join_invite_that_needs_approval_is_requested(account, plan):
    plan.replies[CHECK] = invite_preview(request_needed=True)
    plan.replies[IMPORT] = rpc(errors.InviteRequestSentError)

    result = await account.join(INVITE)

    assert result.outcome == JoinOutcome.REQUESTED
    assert result.chat is None
    assert (result.title, result.member_count) == ("비공개 모임", 340)


async def test_join_invite_requested_again_is_still_requested(account, plan):
    plan.replies[CHECK] = invite_preview(request_needed=True)
    plan.replies[IMPORT] = rpc(errors.InviteRequestSentError)

    first = await account.join(INVITE)
    second = await account.join(INVITE)

    assert first.outcome == second.outcome == JoinOutcome.REQUESTED


async def test_join_invite_with_a_peek_keeps_the_chat_for_a_request(account, plan):
    plan.replies[CHECK] = types.ChatInvitePeek(supergroup(left=True, participants_count=5), NOW)
    plan.replies[IMPORT] = rpc(errors.InviteRequestSentError)

    result = await account.join(INVITE)

    assert result.outcome == JoinOutcome.REQUESTED
    assert result.chat.id == SUPERGROUP_MARKED
    assert (result.title, result.member_count) == ("영업 이야기", 5)


async def test_join_invite_already_participant_finds_the_chat(account, fake, plan):
    plan.replies[CHECK] = Seq(invite_preview(), types.ChatInviteAlready(supergroup()))
    plan.replies[IMPORT] = rpc(errors.UserAlreadyParticipantError)

    result = await account.join(INVITE)

    assert result.outcome == JoinOutcome.JOINED
    assert result.chat.id == SUPERGROUP_MARKED
    assert len(fake.sent(CHECK)) == 2


async def test_join_invite_without_chats_in_the_answer_checks_the_link(account, plan):
    plan.replies[CHECK] = Seq(invite_preview(), types.ChatInviteAlready(basic_group()))
    plan.replies[IMPORT] = join_ok()

    result = await account.join(INVITE)

    assert result.outcome == JoinOutcome.JOINED
    assert result.chat.id == GROUP_MARKED


async def test_join_invite_that_cannot_find_the_chat_asks_to_look_again(account, plan):
    plan.replies[CHECK] = invite_preview()
    plan.replies[IMPORT] = join_ok()

    caught = await failure(account.join(INVITE))

    assert caught.code == TgErrorCode.UNKNOWN
    assert not caught.permanent


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (rpc(errors.InviteHashExpiredError), TgErrorCode.INVITE_EXPIRED),
        (rpc(errors.InviteHashInvalidError), TgErrorCode.INVITE_INVALID),
        (rpc(errors.InviteHashEmptyError), TgErrorCode.INVITE_INVALID),
    ],
)
async def test_join_invite_with_a_dead_link(account, fake, plan, error, code):
    plan.replies[CHECK] = error

    caught = await failure(account.join(INVITE))

    assert caught.code == code
    assert caught.permanent
    assert fake.sent(IMPORT) == []


@pytest.mark.parametrize(("error", "code", "permanent", "retry_after"), JOIN_ERRORS)
async def test_join_invite_failures(account, fake, plan, error, code, permanent, retry_after):
    plan.replies[CHECK] = invite_preview()
    plan.replies[IMPORT] = error

    caught = await failure(account.join(INVITE))

    assert (caught.code, caught.permanent, caught.retry_after) == (code, permanent, retry_after)
    assert len(fake.sent(IMPORT)) == 1


async def test_join_invite_never_pays_for_a_subscription(account, fake, plan):
    pricing = types.StarsSubscriptionPricing(period=2592000, amount=100)
    plan.replies[CHECK] = invite_preview(subscription_pricing=pricing)

    caught = await failure(account.join(INVITE))

    assert caught.code == TgErrorCode.PRIVATE
    assert caught.permanent
    assert fake.sent(IMPORT) == []


# ---------------------------------------------------------------------------
# 멤버인지 확인
# ---------------------------------------------------------------------------

RESOLVE = functions.contacts.ResolveUsernameRequest
GET_CHANNELS = functions.channels.GetChannelsRequest
GET_CHATS = functions.messages.GetChatsRequest


async def test_membership_by_invite_after_approval(account, plan):
    plan.replies[CHECK] = types.ChatInviteAlready(supergroup(title="비공개 모임"))

    chat = await account.find_membership(INVITE, None)

    assert chat.id == SUPERGROUP_MARKED
    assert chat.title == "비공개 모임"


@pytest.mark.parametrize(
    "reply",
    [invite_preview(request_needed=True), types.ChatInvitePeek(supergroup(left=True), NOW)],
)
async def test_membership_by_invite_while_still_waiting(account, plan, reply):
    plan.replies[CHECK] = reply

    assert await account.find_membership(INVITE, None) is None


async def test_membership_by_invite_with_a_dead_link_says_so(account, plan):
    plan.replies[CHECK] = rpc(errors.InviteHashExpiredError)

    caught = await failure(account.find_membership(INVITE, None))

    assert caught.code == TgErrorCode.INVITE_EXPIRED
    assert caught.permanent


async def test_membership_by_username(account, plan):
    plan.replies[RESOLVE] = resolved(supergroup(left=False, username="sales_talk"))

    chat = await account.find_membership(PUBLIC, None)

    assert chat.id == SUPERGROUP_MARKED
    assert chat.username == "sales_talk"


@pytest.mark.parametrize(
    "reply",
    [
        resolved(supergroup(left=True)),
        resolved(user(username="sales_talk")),
        resolved(types.ChannelForbidden(id=SUPERGROUP_ID, access_hash=1, title="막힌 곳")),
        rpc(errors.UsernameNotOccupiedError),
    ],
)
async def test_membership_by_username_when_not_a_member(account, plan, reply):
    plan.replies[RESOLVE] = reply

    assert await account.find_membership(PUBLIC, None) is None


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (rpc(errors.FloodWaitError, capture=90), TgErrorCode.FLOOD_WAIT),
        (rpc(errors.AuthKeyUnregisteredError), TgErrorCode.SESSION_INVALID),
        (rpc(errors.UserDeactivatedBanError), TgErrorCode.BANNED),
        (ConnectionError(), TgErrorCode.NETWORK),
    ],
)
@pytest.mark.parametrize("target", [PUBLIC, INVITE])
async def test_membership_lets_account_problems_through(account, plan, target, error, code):
    plan.replies[RESOLVE] = error
    plan.replies[CHECK] = error

    assert (await failure(account.find_membership(target, None))).code == code


async def test_membership_of_a_requested_public_group_is_checked_by_id(account, fake, plan):
    """가입을 요청하며 알게 된 채널은 그 뒤로 아이디 조회 없이 id 로 확인한다."""
    plan.replies[RESOLVE] = resolved(supergroup(left=True))
    plan.replies[functions.channels.JoinChannelRequest] = rpc(errors.InviteRequestSentError)
    requested = await account.join(PUBLIC)
    plan.replies[GET_CHANNELS] = Seq(
        types.messages.Chats([supergroup(left=True)]),
        types.messages.Chats([supergroup(left=False, participants_count=90)]),
    )

    waiting = await account.find_membership(PUBLIC, requested.chat.id)
    approved = await account.find_membership(PUBLIC, requested.chat.id)

    assert waiting is None
    assert approved.id == SUPERGROUP_MARKED
    assert approved.member_count == 90
    assert len(fake.sent(RESOLVE)) == 1  # 가입할 때 한 번뿐
    assert fake.sent(GET_CHANNELS)[0].id == [types.InputChannel(SUPERGROUP_ID, 9090)]


async def test_membership_by_id_of_a_channel_we_can_no_longer_see(account, plan):
    plan.replies[RESOLVE] = resolved(supergroup(left=False))
    await account.find_membership(PUBLIC, None)
    plan.replies[GET_CHANNELS] = rpc(errors.ChannelPrivateError)

    assert await account.find_membership(None, SUPERGROUP_MARKED) is None


async def test_membership_falls_back_to_the_link_when_the_remembered_hash_is_stale(
    account, fake, plan
):
    plan.replies[RESOLVE] = resolved(supergroup(left=False))
    await account.find_membership(PUBLIC, None)
    plan.replies[GET_CHANNELS] = rpc(errors.ChannelInvalidError)
    plan.replies[RESOLVE] = resolved(supergroup(left=False, access_hash=4242))

    chat = await account.find_membership(PUBLIC, SUPERGROUP_MARKED)

    assert chat.id == SUPERGROUP_MARKED
    assert len(fake.sent(RESOLVE)) == 2


async def test_membership_by_id_of_an_unknown_channel_looks_at_the_dialogs(account, fake, plan):
    plan.dialogs = [user(), supergroup(left=False), basic_group()]

    chat = await account.find_membership(None, SUPERGROUP_MARKED)
    missing = await account.find_membership(None, -1000000009999)

    assert chat.id == SUPERGROUP_MARKED
    assert missing is None
    assert fake.sent(RESOLVE) == []


async def test_membership_by_id_of_a_basic_group(account, fake, plan):
    plan.replies[GET_CHATS] = types.messages.Chats([basic_group()])

    chat = await account.find_membership(None, GROUP_MARKED)

    assert chat == TgChat(
        id=GROUP_MARKED, title="동네 모임", username=None, kind=GroupKind.GROUP, member_count=12
    )
    assert fake.sent(GET_CHATS)[0].id == [GROUP_ID]


@pytest.mark.parametrize(
    "reply",
    [
        types.messages.Chats([basic_group(left=True)]),
        types.messages.Chats([basic_group(deactivated=True)]),
        types.messages.Chats([types.ChatForbidden(id=GROUP_ID, title="쫓겨난 곳")]),
        types.messages.Chats([]),
        rpc(errors.ChatIdInvalidError),
        rpc(errors.PeerIdInvalidError),
    ],
)
async def test_membership_by_id_of_a_basic_group_we_are_not_in(account, plan, reply):
    plan.replies[GET_CHATS] = reply

    assert await account.find_membership(None, GROUP_MARKED) is None


async def test_membership_follows_a_group_upgraded_to_a_supergroup(account, fake, plan):
    upgraded = basic_group(migrated_to=types.InputChannel(SUPERGROUP_ID, 9090), deactivated=True)
    plan.replies[GET_CHATS] = types.messages.Chats([upgraded])
    plan.replies[GET_CHANNELS] = types.messages.Chats([supergroup(left=False)])

    chat = await account.find_membership(None, GROUP_MARKED)

    assert chat.id == SUPERGROUP_MARKED
    assert chat.kind == GroupKind.SUPERGROUP


async def test_membership_with_nothing_to_go_on_is_none(account, fake):
    assert await account.find_membership(None, None) is None
    assert await account.find_membership(None, 501) is None  # 사람 id
    assert fake.requests[1:] == []


# ---------------------------------------------------------------------------
# 들어가 있는 그룹 목록
# ---------------------------------------------------------------------------


async def test_list_groups_returns_only_chats_we_are_in(account, fake, plan):
    plan.dialogs = [
        user(username="friend"),
        supergroup(participants_count=1500, username="sales_talk"),
        broadcast(left=False),
        basic_group(),
        supergroup(1002, left=True),
        basic_group(2003, left=True),
        basic_group(2004, deactivated=True),
        basic_group(2005, migrated_to=types.InputChannel(SUPERGROUP_ID, 9090)),
        types.ChannelForbidden(id=1003, access_hash=1, title="쫓겨난 곳"),
        types.ChatForbidden(id=2006, title="쫓겨난 모임"),
    ]

    groups = await account.list_groups()

    assert groups == [
        TgChat(SUPERGROUP_MARKED, "영업 이야기", "sales_talk", GroupKind.SUPERGROUP, 1500),
        TgChat(-1000000003003, "공지 채널", None, GroupKind.CHANNEL, None),
        TgChat(GROUP_MARKED, "동네 모임", None, GroupKind.GROUP, 12),
    ]
    assert fake.dialog_options == [{"ignore_migrated": True}]


async def test_list_groups_stops_on_flood_wait(account, plan):
    plan.dialogs = rpc(errors.FloodWaitError, capture=25)

    caught = await failure(account.list_groups())

    assert (caught.code, caught.retry_after) == (TgErrorCode.FLOOD_WAIT, 25)


async def test_gigagroup_counts_as_a_supergroup():
    assert tg._to_chat(supergroup(megagroup=False, gigagroup=True)).kind == GroupKind.SUPERGROUP


# ---------------------------------------------------------------------------
# 나가기
# ---------------------------------------------------------------------------

LEAVE = functions.channels.LeaveChannelRequest
KICK_SELF = functions.messages.DeleteChatUserRequest


async def test_leave_a_supergroup_found_in_the_dialogs(account, fake, plan):
    plan.dialogs = [supergroup()]
    plan.replies[LEAVE] = updates_with()

    await account.leave(SUPERGROUP_MARKED)

    [request] = fake.sent(LEAVE)
    assert request.channel == types.InputChannel(SUPERGROUP_ID, 9090)


async def test_leave_a_supergroup_we_already_know_skips_the_dialogs(account, fake, plan):
    plan.replies[RESOLVE] = resolved(supergroup(left=False))
    await account.join(PUBLIC)
    plan.replies[LEAVE] = updates_with()

    await account.leave(SUPERGROUP_MARKED)

    assert len(fake.sent(LEAVE)) == 1
    assert fake.dialog_options == []


async def test_leave_a_basic_group(account, fake, plan):
    plan.replies[KICK_SELF] = updates_with()

    await account.leave(GROUP_MARKED)

    [request] = fake.sent(KICK_SELF)
    assert request.chat_id == GROUP_ID
    assert isinstance(request.user_id, types.InputUserSelf)


async def test_leave_a_channel_missing_from_the_dialogs_is_quiet(account, fake):
    await account.leave(SUPERGROUP_MARKED)

    assert fake.sent(LEAVE) == []


@pytest.mark.parametrize(
    "error", [rpc(errors.UserNotParticipantError), rpc(errors.ChannelPrivateError)]
)
async def test_leave_when_no_longer_a_member_is_quiet(account, plan, error):
    plan.dialogs = [supergroup()]
    plan.replies[LEAVE] = error

    await account.leave(SUPERGROUP_MARKED)


@pytest.mark.parametrize(
    "error",
    [
        rpc(errors.UserNotParticipantError),
        rpc(errors.PeerIdInvalidError),
        rpc(errors.ChatIdInvalidError),
    ],
)
async def test_leave_a_basic_group_we_are_not_in_is_quiet(account, plan, error):
    plan.replies[KICK_SELF] = error

    await account.leave(GROUP_MARKED)


async def test_leave_reports_real_failures(account, plan):
    plan.dialogs = [supergroup()]
    plan.replies[LEAVE] = rpc(errors.FloodWaitError, capture=30)

    caught = await failure(account.leave(SUPERGROUP_MARKED))

    assert (caught.code, caught.retry_after) == (TgErrorCode.FLOOD_WAIT, 30)


async def test_leave_refuses_a_person(account):
    caught = await failure(account.leave(501))

    assert caught.code == TgErrorCode.NOT_A_GROUP


# ---------------------------------------------------------------------------
# 로그아웃
# ---------------------------------------------------------------------------

LOG_OUT = functions.auth.LogOutRequest


async def test_log_out_ends_the_session_and_disconnects(account, fake, plan):
    plan.replies[LOG_OUT] = types.auth.LoggedOut()

    await account.log_out()

    assert len(fake.sent(LOG_OUT)) == 1
    assert not fake.connected


async def test_log_out_connects_first_when_needed(gateway, factory, plan):
    plan.replies[LOG_OUT] = types.auth.LoggedOut()
    account = gateway.create_client(7, session_string())

    await account.log_out()

    assert len(factory.last.sent(LOG_OUT)) == 1
    assert not factory.last.connected


async def test_log_out_of_a_dead_session_is_already_done(gateway, account, plan):
    plan.replies[LOG_OUT] = rpc(errors.AuthKeyUnregisteredError)

    await account.log_out()

    plan.replies[functions.users.GetUsersRequest] = rpc(errors.SessionRevokedError)
    await gateway.create_client(8, session_string()).log_out()


async def test_log_out_failure_is_reported(account, fake, plan):
    plan.replies[LOG_OUT] = rpc(errors.FloodWaitError, capture=15)

    caught = await failure(account.log_out())

    assert (caught.code, caught.retry_after) == (TgErrorCode.FLOOD_WAIT, 15)
    assert fake.connected  # 로그아웃되지 않았으니 연결도 그대로다


# ---------------------------------------------------------------------------
# 로그인
# ---------------------------------------------------------------------------


async def test_start_login_sends_a_code(gateway, factory):
    before = datetime.now(UTC)

    pending = await gateway.start_login(" +82 10-1234-5678 ")

    fake = factory.last
    assert pending.phone == "+821012345678"
    assert fake.code_requests == ["+821012345678"]
    assert pending.code_via == "app"
    assert len(pending.login_id) >= 32
    assert before + timedelta(minutes=10) <= pending.expires_at
    assert pending.expires_at <= datetime.now(UTC) + timedelta(minutes=10)
    assert fake.connected
    assert (fake.api_id, fake.api_hash) == (API_ID, API_HASH)
    assert fake.options["device_model"] == "ChatDB"
    assert fake.initial_session == ""  # 인증 키가 없는 새 세션으로 시작한다
    assert fake.handlers == []


async def test_login_ids_are_unpredictable(gateway):
    first = await gateway.start_login("+821012345678")
    second = await gateway.start_login("+821087654321")

    assert first.login_id != second.login_id


@pytest.mark.parametrize(
    ("code_type", "via"),
    [
        (types.auth.SentCodeTypeApp(length=5), "app"),
        (types.auth.SentCodeTypeSms(length=5), "sms"),
        (types.auth.SentCodeTypeFirebaseSms(length=5), "sms"),
        (types.auth.SentCodeTypeSmsWord(beginning="a"), "sms"),
        (types.auth.SentCodeTypeSmsPhrase(beginning="a"), "sms"),
        (types.auth.SentCodeTypeCall(length=5), "call"),
        (types.auth.SentCodeTypeFlashCall(pattern="*"), "call"),
        (types.auth.SentCodeTypeMissedCall(prefix="+82", length=4), "call"),
        (types.auth.SentCodeTypeEmailCode(email_pattern="a*@b.c", length=6), "other"),
        (types.auth.SentCodeTypeFragmentSms(url="https://fragment.com", length=5), "other"),
    ],
)
async def test_start_login_tells_where_the_code_went(gateway, plan, code_type, via):
    plan.send_code = sent_code(code_type)

    assert (await gateway.start_login("+821012345678")).code_via == via


@pytest.mark.parametrize(
    "phone", ["", "abc", "010-1234-5678", "+82 10 12", "+8210123456789012345", "+82 10 abcd 5678"]
)
async def test_start_login_rejects_a_bad_phone_without_calling_telegram(gateway, factory, phone):
    caught = await failure(gateway.start_login(phone))

    assert caught.code == TgErrorCode.PHONE_INVALID
    assert factory.clients == []


@pytest.mark.parametrize(
    ("error", "code", "retry_after"),
    [
        (rpc(errors.PhoneNumberInvalidError), TgErrorCode.PHONE_INVALID, None),
        (rpc(errors.PhoneNumberBannedError), TgErrorCode.PHONE_BANNED, None),
        (rpc(errors.PhoneNumberFloodError), TgErrorCode.FLOOD_WAIT, None),
        (rpc(errors.FloodWaitError, capture=7200), TgErrorCode.FLOOD_WAIT, 7200),
        (rpc(errors.ApiIdInvalidError), TgErrorCode.API_CREDENTIALS, None),
        (ConnectionError(), TgErrorCode.NETWORK, None),
        (
            AttributeError("'SentCodePaymentRequired' object has no attribute 'type'"),
            "unknown",
            None,
        ),
    ],
)
async def test_start_login_failures_close_the_temporary_client(
    gateway, factory, plan, error, code, retry_after
):
    plan.send_code = error

    caught = await failure(gateway.start_login("+821012345678"))

    assert (caught.code, caught.retry_after) == (code, retry_after)
    assert not factory.last.connected
    assert factory.last.disconnect_calls == 1
    assert gateway._logins == {}


async def test_start_login_again_for_the_same_phone_drops_the_earlier_one(gateway, factory):
    first = await gateway.start_login("+821012345678")
    second = await gateway.start_login("+82 10 1234 5678")

    assert not factory.clients[0].connected
    assert factory.clients[1].connected
    assert (await failure(gateway.submit_code(first.login_id, CODE))).code == "login_expired"
    assert (await gateway.submit_code(second.login_id, CODE)).status == "done"


async def test_submit_code_finishes_the_login(gateway, factory):
    pending = await gateway.start_login("+821012345678")
    fake = factory.last

    result = await gateway.submit_code(pending.login_id, " 24 680 ")

    assert result.status == "done"
    assert result.session == fake.session.save() != ""
    assert StringSession(result.session).auth_key == fake.session.auth_key
    assert result.user == TgUser(
        id=SELF_ID,
        username="my_account",
        first_name="내",
        last_name="계정",
        phone="+821012345678",
    )
    assert result.password_hint is None
    assert fake.sign_ins == [
        {"phone": "+821012345678", "code": CODE, "password": None, "hash": "hash-1"}
    ]
    assert not fake.connected  # 임시 연결은 닫는다
    assert (await failure(gateway.submit_code(pending.login_id, CODE))).code == "login_expired"


async def test_wrong_code_can_be_tried_again(gateway, factory, plan):
    pending = await gateway.start_login("+821012345678")
    plan.sign_in = Seq(rpc(errors.PhoneCodeInvalidError), ME)

    caught = await failure(gateway.submit_code(pending.login_id, "11111"))
    result = await gateway.submit_code(pending.login_id, CODE)

    assert caught.code == TgErrorCode.CODE_INVALID
    assert not caught.permanent
    assert result.status == "done"
    assert len(factory.clients) == 1


@pytest.mark.parametrize(
    ("typed", "sent"),
    [
        ("24680", "24680"),
        ("24-680", "24680"),
        ("  2 4 6 8 0\n", "24680"),
        (" apple ", "apple"),  # 단어로 오는 코드
        ("blue sky-high", "blue sky-high"),  # 문장으로 오는 코드는 손대지 않는다
    ],
)
async def test_code_is_tidied_only_when_it_is_a_number(gateway, factory, typed, sent):
    pending = await gateway.start_login("+821012345678")

    await gateway.submit_code(pending.login_id, typed)

    assert factory.last.sign_ins[0]["code"] == sent


async def test_success_without_a_user_is_not_treated_as_done(gateway, factory, plan):
    pending = await gateway.start_login("+821012345678")
    plan.sign_in = Seq(sent_code(), ME)  # 유저 대신 다른 응답이 온 경우

    caught = await failure(gateway.submit_code(pending.login_id, CODE))
    result = await gateway.submit_code(pending.login_id, CODE)

    assert caught.code == TgErrorCode.UNKNOWN
    assert result.status == "done"


async def test_empty_code_is_rejected_without_calling_telegram(gateway, factory):
    pending = await gateway.start_login("+821012345678")

    caught = await failure(gateway.submit_code(pending.login_id, " - "))

    assert caught.code == TgErrorCode.CODE_INVALID
    assert factory.last.sign_ins == []


async def test_expired_code_ends_the_login(gateway, factory, plan):
    pending = await gateway.start_login("+821012345678")
    plan.sign_in = rpc(errors.PhoneCodeExpiredError)

    caught = await failure(gateway.submit_code(pending.login_id, CODE))

    assert caught.code == TgErrorCode.CODE_EXPIRED
    assert not factory.last.connected
    assert (await failure(gateway.submit_code(pending.login_id, CODE))).code == "login_expired"


async def test_number_without_an_account_is_a_phone_problem(gateway, plan):
    pending = await gateway.start_login("+821012345678")
    plan.sign_in = rpc(errors.PhoneNumberUnoccupiedError)

    assert (await failure(gateway.submit_code(pending.login_id, CODE))).code == "phone_invalid"


async def test_two_step_login(gateway, factory, plan):
    pending = await gateway.start_login("+821012345678")
    fake = factory.last
    plan.replies[functions.account.GetPasswordRequest] = password_info()
    plan.sign_in = Seq(
        rpc(errors.SessionPasswordNeededError), rpc(errors.PasswordHashInvalidError), ME
    )

    asked = await gateway.submit_code(pending.login_id, CODE)
    wrong = await failure(gateway.submit_password(pending.login_id, "틀린 비밀번호"))
    done = await gateway.submit_password(pending.login_id, PASSWORD)

    assert (asked.status, asked.password_hint) == ("password_required", "첫 강아지 이름")
    assert asked.session is None and asked.user is None
    assert wrong.code == TgErrorCode.PASSWORD_INVALID
    assert not wrong.permanent
    assert done.status == "done"
    assert done.user.id == SELF_ID
    assert fake.sign_ins[-1] == {"phone": None, "code": None, "password": PASSWORD, "hash": None}
    assert not fake.connected


@pytest.mark.parametrize(
    "reply", [password_info(hint=None), password_info(hint=""), rpc(errors.FloodWaitError, 5)]
)
async def test_two_step_login_without_a_hint(gateway, plan, reply):
    pending = await gateway.start_login("+821012345678")
    plan.replies[functions.account.GetPasswordRequest] = reply
    plan.sign_in = rpc(errors.SessionPasswordNeededError)

    asked = await gateway.submit_code(pending.login_id, CODE)

    assert (asked.status, asked.password_hint) == ("password_required", None)


async def test_password_before_code_is_refused_without_calling_telegram(gateway, factory):
    pending = await gateway.start_login("+821012345678")

    caught = await failure(gateway.submit_password(pending.login_id, PASSWORD))

    assert caught.code == TgErrorCode.CODE_INVALID
    assert factory.last.sign_ins == []


async def test_empty_password_is_refused_without_calling_telegram(gateway, factory, plan):
    pending = await gateway.start_login("+821012345678")
    plan.replies[functions.account.GetPasswordRequest] = password_info()
    plan.sign_in = rpc(errors.SessionPasswordNeededError)
    await gateway.submit_code(pending.login_id, CODE)

    caught = await failure(gateway.submit_password(pending.login_id, ""))

    assert caught.code == TgErrorCode.PASSWORD_INVALID
    assert len(factory.last.sign_ins) == 1


@pytest.mark.parametrize(
    ("error", "code", "retry_after"),
    [
        (rpc(errors.FloodWaitError, capture=300), TgErrorCode.FLOOD_WAIT, 300),
        (rpc(errors.PhonePasswordFloodError), TgErrorCode.FLOOD_WAIT, None),
        (ConnectionError(), TgErrorCode.NETWORK, None),
    ],
)
async def test_login_survives_a_temporary_failure(gateway, plan, error, code, retry_after):
    pending = await gateway.start_login("+821012345678")
    plan.sign_in = Seq(error, ME)

    caught = await failure(gateway.submit_code(pending.login_id, CODE))
    result = await gateway.submit_code(pending.login_id, CODE)

    assert (caught.code, caught.retry_after) == (code, retry_after)
    assert result.status == "done"


async def test_unknown_login_id_is_expired(gateway):
    for call in (gateway.submit_code("nope", CODE), gateway.submit_password("nope", PASSWORD)):
        caught = await failure(call)
        assert caught.code == TgErrorCode.LOGIN_EXPIRED


async def test_login_expires_and_is_cleaned_up(factory):
    gateway = tg.TelethonGateway(credentials, client_factory=factory, login_ttl=0.05)
    pending = await gateway.start_login("+821012345678")
    assert factory.last.connected

    await asyncio.sleep(0.15)

    assert not factory.last.connected
    assert gateway._logins == {}
    assert (await failure(gateway.submit_code(pending.login_id, CODE))).code == "login_expired"
    assert factory.last.sign_ins == []


async def test_login_past_its_deadline_is_refused_even_before_cleanup(gateway):
    pending = await gateway.start_login("+821012345678")
    gateway._logins[pending.login_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)

    assert (await failure(gateway.submit_code(pending.login_id, CODE))).code == "login_expired"


async def test_cancel_login_closes_the_temporary_client(gateway, factory):
    pending = await gateway.start_login("+821012345678")
    timer = gateway._logins[pending.login_id].timer

    await gateway.cancel_login(pending.login_id)
    await gateway.cancel_login(pending.login_id)  # 두 번 불러도 괜찮다
    await gateway.cancel_login("nope")
    await asyncio.sleep(0)

    assert not factory.last.connected
    assert timer.cancelled()
    assert (await failure(gateway.submit_code(pending.login_id, CODE))).code == "login_expired"


async def test_close_drops_every_pending_login(gateway, factory):
    await gateway.start_login("+821012345678")
    await gateway.start_login("+821087654321")

    await gateway.close()

    assert [client.connected for client in factory.clients] == [False, False]
    assert gateway._logins == {}


# ---------------------------------------------------------------------------
# 세션 불러오기
# ---------------------------------------------------------------------------


@pytest.fixture
def private_tmp(tmp_path, monkeypatch):
    """임시 파일이 생기는 곳을 테스트 폴더로 돌려 남는 것이 없는지 본다."""
    folder = tmp_path / "tmp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


def sqlite_session_file(tmp_path, key: bytes, *, dc_id: int = 4, address: str = "149.154.167.91"):
    """Telethon 이 실제로 만드는 .session 파일의 내용."""
    session = SQLiteSession(str(tmp_path / "exported"))
    session.set_dc(dc_id, address, 443)
    session.auth_key = AuthKey(data=key)
    session.save()
    expected = StringSession.save(session)
    session.close()
    return (tmp_path / "exported.session").read_bytes(), expected


async def test_import_session_string(gateway, factory):
    stored = session_string()

    result = await gateway.import_session(f"  {stored}\n")

    assert result.status == "done"
    assert result.session == stored
    assert result.user.id == SELF_ID
    assert result.user.phone == "+821012345678"
    fake = factory.last
    assert fake.connect_calls == 1
    assert fake.disconnect_calls == 1  # 확인만 하고 닫는다
    assert fake.handlers == []


async def test_import_session_returns_the_session_after_connecting(gateway, factory, plan):
    stored = session_string()

    def moved(request: Any) -> list[types.User]:
        factory.last.session.set_dc(5, "91.108.56.130", 443)  # 접속 중 DC 이동
        return [ME]

    plan.replies[functions.users.GetUsersRequest] = moved

    result = await gateway.import_session(stored)

    assert result.session != stored
    assert StringSession(result.session).dc_id == 5


async def test_import_session_file(gateway, factory, tmp_path, private_tmp):
    key = os.urandom(256)
    data, expected = sqlite_session_file(tmp_path, key)

    result = await gateway.import_session(data)

    assert result.status == "done"
    assert result.session == expected
    session = factory.last.session
    assert (session.dc_id, session.server_address, session.port) == (4, "149.154.167.91", 443)
    assert session.auth_key.key == key
    assert list(private_tmp.iterdir()) == []  # 인증 키가 든 임시 파일을 남기지 않는다


async def test_import_session_file_over_ipv6(gateway, tmp_path, private_tmp):
    data, expected = sqlite_session_file(
        tmp_path, os.urandom(256), dc_id=2, address="2001:67c:4e8:f002::a"
    )

    assert (await gateway.import_session(data)).session == expected


async def test_import_session_temp_file_is_private(tmp_path, private_tmp, monkeypatch):
    data, _ = sqlite_session_file(tmp_path, os.urandom(256))
    seen: list[tuple[int, int]] = []
    connect = sqlite3.connect

    def spy(path: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        seen.append((os.stat(path).st_mode & 0o777, os.stat(path.parent).st_mode & 0o777))
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(tg.sqlite3, "connect", spy)

    tg._session_text_from_file(data)

    assert seen == [(0o600, 0o700)]


async def test_import_session_text_file(gateway):
    stored = session_string()

    result = await gateway.import_session(b"\xef\xbb\xbf" + stored.encode() + b"\r\n")

    assert result.session == stored


def sqlite_bytes(tmp_path, *statements: str) -> bytes:
    path = tmp_path / "other.sqlite"
    connection = sqlite3.connect(path)
    for statement in statements:
        connection.execute(statement)
    connection.commit()
    connection.close()
    return path.read_bytes()


SESSIONS_TABLE = (
    "create table sessions (dc_id integer, server_address text, port integer, auth_key blob)"
)


@pytest.mark.parametrize(
    "data",
    [
        "",
        "   ",
        "hello",
        "1AAAA",
        "1" + "A" * 352,  # 모양은 맞지만 인증 키가 비어 있다
        "세션",
        b"",
        b"\xff\xfe\x00garbage",
        b"SQLite format 3\x00" + b"\x00" * 200,
    ],
)
async def test_import_unreadable_session(gateway, factory, private_tmp, data):
    caught = await failure(gateway.import_session(data))

    assert caught.code == TgErrorCode.SESSION_FORMAT
    assert factory.clients == []
    assert list(private_tmp.iterdir()) == []


@pytest.mark.parametrize(
    "statements",
    [
        ["create table notes (body text)"],  # 다른 프로그램의 SQLite 파일
        [SESSIONS_TABLE],  # 표는 있는데 비어 있다
        [SESSIONS_TABLE, "insert into sessions values (2, '149.154.167.51', 443, x'0102')"],
        [SESSIONS_TABLE, "insert into sessions values (2, '149.154.167.51', 443, null)"],
        [SESSIONS_TABLE, f"insert into sessions values (2, 'not-an-ip', 443, x'{'ab' * 256}')"],
        [
            SESSIONS_TABLE,
            f"insert into sessions values (2, '149.154.167.51', null, x'{'ab' * 256}')",
        ],
    ],
)
async def test_import_sqlite_file_that_is_not_a_usable_session(
    gateway, factory, tmp_path, private_tmp, statements
):
    caught = await failure(gateway.import_session(sqlite_bytes(tmp_path, *statements)))

    assert caught.code == TgErrorCode.SESSION_FORMAT
    assert factory.clients == []
    assert list(private_tmp.iterdir()) == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (rpc(errors.AuthKeyUnregisteredError), TgErrorCode.SESSION_INVALID),
        (rpc(errors.UserDeactivatedBanError), TgErrorCode.BANNED),
        (rpc(errors.FloodWaitError, capture=20), TgErrorCode.FLOOD_WAIT),
    ],
)
async def test_import_session_that_telegram_rejects(gateway, factory, plan, error, code):
    plan.replies[functions.users.GetUsersRequest] = error

    caught = await failure(gateway.import_session(session_string()))

    assert caught.code == code
    assert not factory.last.connected
    assert factory.last.disconnect_calls == 1


async def test_import_session_that_cannot_connect(gateway, factory, plan):
    plan.connect = ConnectionError("Connection to Telegram failed 5 time(s)")

    caught = await failure(gateway.import_session(session_string()))

    assert caught.code == TgErrorCode.NETWORK
    assert factory.last.disconnect_calls == 1


# ---------------------------------------------------------------------------
# 실제 TelegramClient 로 (맨 아래 전송 계층만 각본으로 바꾼다)
# ---------------------------------------------------------------------------


class StubSender:
    """TelegramClient 안의 MTProtoSender 자리에 끼우는 대역.

    그 위의 Telethon 코드(connect, 요청 재시도·FloodWait 처리, 업데이트 루프, 로그인, 대화 목록,
    끊기)는 설치된 그대로 돈다. 게이트웨이가 Telethon 을 쓰는 방식이 실제와 맞는지 보는 용도다.
    """

    def __init__(self, plan: Plan, auth_key: AuthKey) -> None:
        self.plan = plan
        self.auth_key = auth_key
        self.wire: list[TLRequest] = []
        self._user_connected = False
        self._closed: asyncio.Future[None] | None = None

    async def connect(self, connection: Any) -> bool:
        self._user_connected = True
        self._closed = asyncio.get_running_loop().create_future()
        return True

    def is_connected(self) -> bool:
        return self._user_connected

    def _transport_connected(self) -> bool:
        return self._user_connected

    def _keepalive_ping(self, rnd_id: int) -> None:
        return None

    async def disconnect(self) -> None:
        self._user_connected = False
        if self._closed is not None and not self._closed.done():
            self._closed.set_result(None)

    @property
    def disconnected(self) -> asyncio.Future[None]:
        if self._closed is None:
            done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            done.set_result(None)
            return done
        return asyncio.shield(self._closed)

    def send(self, request: TLRequest, ordered: bool = False) -> asyncio.Future[Any]:
        bytes(request)  # 실제 전송 계층도 여기서 직렬화한다
        self.wire.append(request)
        inner = request
        while hasattr(inner, "query"):  # InvokeWithLayer(InitConnection(...)) 를 벗긴다
            inner = inner.query
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        try:
            if type(inner) not in self.plan.replies:
                raise AssertionError(f"각본에 없는 요청이에요: {type(inner).__name__}")
            reply = self.plan.replies[type(inner)]
            if isinstance(reply, Seq):
                reply = reply.next()
            if callable(reply):
                reply = reply(inner)
            if isinstance(reply, BaseException):
                raise reply
            future.set_result(reply)
        except Exception as exc:  # noqa: BLE001 - 실제 전송 계층처럼 future 로 돌려준다
            future.set_exception(exc)
        return future

    def sent(self, request_type: type) -> list[Any]:
        return [request for request in self.wire if isinstance(request, request_type)]


@pytest_asyncio.fixture
async def real(plan: Plan):
    """실제 TelegramClient 를 쓰는 게이트웨이와, 그 게이트웨이가 만든 클라이언트들."""
    clients: list[TelegramClient] = []
    plan.replies[functions.help.GetConfigRequest] = types.help.ConfigSimple(NOW, NOW, [])
    plan.replies[functions.updates.GetStateRequest] = types.updates.State(
        pts=1, qts=0, date=NOW, seq=1, unread_count=0
    )
    plan.replies[functions.updates.GetDifferenceRequest] = types.updates.DifferenceEmpty(
        date=NOW, seq=1
    )

    def build(session: Any, api_id: int, api_hash: str, **options: Any) -> TelegramClient:
        client = TelegramClient(session, api_id, api_hash, **options)
        # 새 세션이면 실제 전송 계층이 인증 키를 새로 만든다.
        client._sender = StubSender(plan, session.auth_key or AuthKey(data=os.urandom(256)))
        clients.append(client)
        return client

    gateway = tg.TelethonGateway(credentials, client_factory=build)
    yield SimpleNamespace(gateway=gateway, clients=clients)
    await gateway.close()
    for client in clients:
        await client.disconnect()


async def until(condition: Any) -> None:
    for _ in range(200):
        if condition():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("기다리던 일이 일어나지 않았어요")


def channel_update(message_id: int, pts: int, *, peer: Any = IN_SUPERGROUP, **fields: Any) -> Any:
    fields.setdefault("from_id", types.PeerUser(501))
    message = types.Message(id=message_id, peer_id=peer, date=NOW, message="견적 문의", **fields)
    return types.UpdateNewChannelMessage(message, pts=pts, pts_count=1)


def container(update: Any, *, users: Any = (), chats: Any = ()) -> types.Updates:
    return types.Updates(updates=[update], users=list(users), chats=list(chats), date=NOW, seq=0)


async def test_real_client_introduces_itself_honestly_and_holds_the_connection(real):
    stored = session_string()
    account = real.gateway.create_client(7, stored)

    me = await account.connect()

    [client] = real.clients
    sender = client._sender
    init = sender.wire[0].query
    assert isinstance(init, functions.InitConnectionRequest)
    assert (init.device_model, init.app_version, init.api_id) == ("ChatDB", app.__version__, API_ID)
    assert init.proxy is None
    assert me.id == SELF_ID
    assert client.flood_sleep_threshold == 0
    assert account.export_session() == stored

    waiter = asyncio.create_task(account.wait_closed())
    await asyncio.sleep(0.01)
    assert not waiter.done()

    await account.disconnect()

    assert await waiter is None
    assert not client.is_connected()
    await account.disconnect()  # 한 번 더 끊어도 괜찮다


@pytest.mark.parametrize(
    ("error", "code", "retry_after"),
    [
        (lambda request: errors.AuthKeyUnregisteredError(request), "session_invalid", None),
        (lambda request: errors.UserDeactivatedBanError(request), "banned", None),
        (lambda request: errors.FloodWaitError(request, capture=45), "flood_wait", 45),
    ],
)
async def test_real_client_connect_failure_leaves_nothing_running(
    real, plan, error, code, retry_after
):
    plan.replies[functions.users.GetUsersRequest] = error
    account = real.gateway.create_client(7, session_string())

    caught = await failure(account.connect())

    [client] = real.clients
    assert (caught.code, caught.retry_after) == (code, retry_after)
    assert not client.is_connected()
    await account.wait_closed()  # 끊긴 상태라 바로 돌아온다
    assert client._updates_handle is None or client._updates_handle.done()


async def test_real_update_loop_forwards_only_group_messages(real):
    account = real.gateway.create_client(7, session_string())
    received: list[IncomingMessage] = []

    async def handler(message: IncomingMessage) -> None:
        received.append(message)

    account.set_message_handler(handler)
    await account.connect()
    [client] = real.clients
    before = len(client._sender.wire)
    group, channel, sender = supergroup(), broadcast(), user(username="minsu_kim")
    in_channel = types.PeerChannel(channel.id)
    mine = channel_update(32, 11, out=True, from_id=types.PeerUser(SELF_ID))
    post = channel_update(5, 5, peer=in_channel, post=True, from_id=None)

    # 텔레그램이 보내는 모양 그대로 업데이트 큐에 넣는다.
    for update in (
        container(channel_update(31, 10), users=[sender], chats=[group]),
        container(mine, users=[ME], chats=[group]),
        container(post, chats=[channel]),
        types.UpdateShortChatMessage(
            id=40, from_id=501, chat_id=GROUP_ID, message="저도요", pts=2, pts_count=1, date=NOW
        ),
        types.UpdateShortMessage(
            id=41, user_id=501, message="개인 대화", pts=3, pts_count=1, date=NOW
        ),
        container(channel_update(33, 12, from_id=None), chats=[group]),
    ):
        client._updates_queue.put_nowait(update)
    await until(lambda: len(received) >= 3 and client._updates_queue.empty())
    await asyncio.sleep(0.02)

    assert [(m.chat_id, m.message_id, m.sender and m.sender.username) for m in received] == [
        (SUPERGROUP_MARKED, 31, "minsu_kim"),
        (GROUP_MARKED, 40, "minsu_kim"),  # 짧은 업데이트의 발신자는 앞서 본 정보로 채운다
        (SUPERGROUP_MARKED, 33, None),  # 익명 관리자
    ]
    assert received[1].text == "저도요"
    assert len(client._sender.wire) == before  # 메시지 때문에 보낸 요청이 없다


@pytest.mark.parametrize(
    ("error_cls", "code"),
    [
        (errors.AuthKeyUnregisteredError, TgErrorCode.SESSION_INVALID),
        (errors.SessionRevokedError, TgErrorCode.SESSION_INVALID),
        (errors.UserDeactivatedBanError, TgErrorCode.BANNED),
    ],
)
async def test_real_update_loop_reports_a_session_that_died(real, plan, error_cls, code):
    account = real.gateway.create_client(7, session_string())
    await account.connect()
    [client] = real.clients
    waiter = asyncio.create_task(account.wait_closed())

    # 업데이트를 따라잡으려는 요청에 텔레그램이 401 로 답하는 상황
    plan.replies[functions.updates.GetDifferenceRequest] = lambda request: error_cls(request)
    client._updates_queue.put_nowait(types.UpdatesTooLong())

    caught = await failure(asyncio.wait_for(waiter, 2))
    assert caught.code == code
    assert caught.permanent
    assert not client.is_connected()


async def test_real_flood_wait_is_reported_at_once_and_not_sent_again(real, plan):
    plan.replies[RESOLVE] = lambda request: errors.FloodWaitError(request, capture=30)
    account = real.gateway.create_client(7, session_string())
    await account.connect()
    sender = real.clients[0]._sender
    loop = asyncio.get_running_loop()

    started = loop.time()
    first = await failure(account.join(PUBLIC))
    elapsed = loop.time() - started
    second = await failure(account.join(PUBLIC))

    assert (first.code, first.retry_after) == (TgErrorCode.FLOOD_WAIT, 30)
    assert elapsed < 1  # Telethon 이 대신 자고 다시 보내지 않는다
    assert second.code == TgErrorCode.FLOOD_WAIT
    assert 26 <= second.retry_after <= 30
    assert len(sender.sent(RESOLVE)) == 1  # 기다리는 동안에는 요청이 나가지 않는다


async def test_real_client_lists_groups_and_leaves_one(real, plan):
    plan.replies[functions.messages.GetDialogsRequest] = types.messages.Dialogs(
        dialogs=[
            types.Dialog(
                peer=peer,
                top_message=0,
                read_inbox_max_id=0,
                read_outbox_max_id=0,
                unread_count=0,
                unread_mentions_count=0,
                unread_reactions_count=0,
                unread_poll_votes_count=0,
                notify_settings=types.PeerNotifySettings(),
            )
            for peer in (
                types.PeerChannel(SUPERGROUP_ID),
                types.PeerChat(GROUP_ID),
                types.PeerUser(501),
                types.PeerChannel(1002),
            )
        ],
        messages=[],
        chats=[supergroup(participants_count=10), basic_group(), supergroup(1002, left=True)],
        users=[user()],
    )
    plan.replies[LEAVE] = updates_with()
    account = real.gateway.create_client(7, session_string())
    await account.connect()
    sender = real.clients[0]._sender

    groups = await account.list_groups()
    await account.leave(SUPERGROUP_MARKED)

    assert [(group.id, group.kind) for group in groups] == [
        (SUPERGROUP_MARKED, GroupKind.SUPERGROUP),
        (GROUP_MARKED, GroupKind.GROUP),
    ]
    [request] = sender.sent(LEAVE)
    assert request.channel == types.InputChannel(SUPERGROUP_ID, 9090)
    assert len(sender.sent(functions.messages.GetDialogsRequest)) == 1


async def test_real_client_joins_by_invite_link(real, plan):
    plan.replies[CHECK] = invite_preview()
    plan.replies[IMPORT] = join_ok(supergroup(left=False))
    account = real.gateway.create_client(7, session_string())
    await account.connect()

    result = await account.join(INVITE)

    assert (result.outcome, result.chat.id) == (JoinOutcome.JOINED, SUPERGROUP_MARKED)


async def test_real_client_login_with_a_code(real, plan):
    plan.replies[functions.users.GetUsersRequest] = lambda request: errors.AuthKeyUnregisteredError(
        request
    )
    plan.replies[functions.auth.SendCodeRequest] = sent_code(types.auth.SentCodeTypeSms(length=5))
    plan.replies[functions.auth.SignInRequest] = types.auth.Authorization(user=ME)

    pending = await real.gateway.start_login("+82 10-1234-5678")
    [client] = real.clients
    sender = client._sender
    result = await real.gateway.submit_code(pending.login_id, CODE)

    assert pending.code_via == "sms"
    [code_request] = sender.sent(functions.auth.SendCodeRequest)
    assert (code_request.phone_number, code_request.api_id, code_request.api_hash) == (
        "821012345678",
        API_ID,
        API_HASH,
    )
    [sign_in] = sender.sent(functions.auth.SignInRequest)
    assert (sign_in.phone_number, sign_in.phone_code_hash, sign_in.phone_code) == (
        "821012345678",
        "hash-1",
        CODE,
    )
    assert result.status == "done"
    assert result.user.id == SELF_ID
    assert StringSession(result.session).auth_key == sender.auth_key
    assert not client.is_connected()


async def test_real_client_login_with_two_step_password(real, plan, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    checked: list[str] = []

    def compute_check(request: Any, password: str) -> types.InputCheckPasswordEmpty:
        checked.append(password)  # 실제로는 여기서 SRP 증명을 계산한다
        return types.InputCheckPasswordEmpty()

    monkeypatch.setattr("telethon.password.compute_check", compute_check)
    plan.replies[functions.users.GetUsersRequest] = lambda request: errors.AuthKeyUnregisteredError(
        request
    )
    plan.replies[functions.auth.SendCodeRequest] = sent_code()
    plan.replies[functions.auth.SignInRequest] = lambda request: errors.SessionPasswordNeededError(
        request
    )
    plan.replies[functions.account.GetPasswordRequest] = password_info()
    plan.replies[functions.auth.CheckPasswordRequest] = Seq(
        lambda request: errors.PasswordHashInvalidError(request),
        types.auth.Authorization(user=ME),
    )

    pending = await real.gateway.start_login("+821012345678")
    asked = await real.gateway.submit_code(pending.login_id, CODE)
    wrong = await failure(real.gateway.submit_password(pending.login_id, "틀린 비밀번호"))
    done = await real.gateway.submit_password(pending.login_id, PASSWORD)

    assert (asked.status, asked.password_hint) == ("password_required", "첫 강아지 이름")
    assert wrong.code == TgErrorCode.PASSWORD_INVALID
    assert done.status == "done"
    assert checked == ["틀린 비밀번호", PASSWORD]
    assert not real.clients[0].is_connected()
    assert "로그인을 마쳤어요" in caplog.text
    for secret in (CODE, PASSWORD, "틀린 비밀번호", API_HASH, done.session, "+8210"):
        assert secret not in caplog.text


async def test_real_client_imports_a_session(real):
    stored = session_string()

    result = await real.gateway.import_session(stored)

    assert (result.status, result.session, result.user.id) == ("done", stored, SELF_ID)
    assert not real.clients[0].is_connected()


# ---------------------------------------------------------------------------
# 민감한 값은 로그에 남지 않는다
# ---------------------------------------------------------------------------


async def test_nothing_sensitive_is_logged(gateway, factory, plan, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    key = os.urandom(256)
    stored = session_string(key=key)
    file_data, file_session = sqlite_session_file(tmp_path, os.urandom(256))
    messages: list[str] = []

    async def attempt(awaitable: Any) -> None:
        try:
            await awaitable
        except TelegramError as exc:
            messages.append(f"{exc.message} {exc!r} {exc.__cause__!r}")

    # 로그인: 틀린 코드 → 2단계 인증 → 틀린 비밀번호 → 알 수 없는 오류 → 성공
    pending = await gateway.start_login("+821012345678")
    login_client = factory.last
    login_client.session.set_dc(2, "149.154.167.51", 443)
    login_client.session.auth_key = AuthKey(data=key)
    plan.replies[functions.account.GetPasswordRequest] = rpc(errors.FloodWaitError, capture=3)
    plan.sign_in = Seq(
        rpc(errors.PhoneCodeInvalidError),
        rpc(errors.SessionPasswordNeededError),
        rpc(errors.PasswordHashInvalidError),
        RuntimeError("예상하지 못한 실패"),
        ME,
    )
    await attempt(gateway.submit_code(pending.login_id, CODE))
    await gateway.submit_code(pending.login_id, CODE)
    await attempt(gateway.submit_password(pending.login_id, PASSWORD))
    await attempt(gateway.submit_password(pending.login_id, PASSWORD))
    done = await gateway.submit_password(pending.login_id, PASSWORD)
    assert done.session == stored

    # 만료·취소되는 로그인
    await gateway.cancel_login((await gateway.start_login("+821087654321")).login_id)

    # 세션 불러오기: 성공, 죽은 세션, 읽을 수 없는 값
    await gateway.import_session(stored)
    await gateway.import_session(file_data)
    plan.replies[functions.users.GetUsersRequest] = Seq(
        rpc(errors.AuthKeyUnregisteredError), RuntimeError("예상하지 못한 실패"), [ME]
    )
    await attempt(gateway.import_session(stored))
    await attempt(gateway.import_session(stored))
    await attempt(gateway.import_session(stored[:-7]))
    await attempt(gateway.import_session(file_data[:300]))

    # 계정 연결: 접속, 실패, 끊기
    account = gateway.create_client(7, stored)
    await account.connect()
    await account.disconnect()
    plan.connect = RuntimeError("예상하지 못한 실패")
    await attempt(account.connect())
    await attempt(gateway.create_client(8, stored[:-7]).connect())

    logged = caplog.text + "\n".join(messages)
    assert "예상하지 못한 실패" in logged  # 로그가 실제로 남고 있다
    for secret in (stored, stored[1:60], file_session, CODE, PASSWORD, API_HASH, "+8210"):
        assert secret not in logged
    assert key.hex() not in logged
