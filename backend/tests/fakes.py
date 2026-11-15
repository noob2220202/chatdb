"""조종할 수 있는 가짜 텔레그램 게이트웨이. 실제 접속 없이 엔진과 그 위의 코드를 시험한다.

    gateway = FakeGateway()
    gateway.script_connect(account_id, TelegramError(TgErrorCode.NETWORK, "…"))  # 첫 접속은 실패
    gateway.script_join("some_group", JoinResult(JoinOutcome.JOINED, make_chat(1)))
    gateway.memberships["InviteHash123"] = make_chat(2)   # find_membership 의 답
    ...
    client = gateway.client(account_id)                    # 그 계정의 가장 최근 연결
    await client.emit_message(chat.id, "안녕하세요", sender)  # 그룹에 새 글이 온 것처럼
    client.drop()                                          # 연결이 끊긴 것처럼
    gateway.called("join", account_id)                     # 그동안 받은 호출의 인자들
    gate = gateway.hold("join")                            # gate.set() 할 때까지 join() 이 답하지 않는다

스크립트에 넣는 값이 예외면 그 호출이 그 예외를 던진다.
"""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from app.links import LinkTarget
from app.models import GroupKind, LinkKind
from app.telegram.gateway import (
    AccountClient,
    IncomingMessage,
    JoinOutcome,
    JoinResult,
    LoginResult,
    MessageHandler,
    PendingLogin,
    TelegramGateway,
    TgChat,
    TgUser,
)


def make_chat(
    number: int,
    *,
    title: str | None = None,
    username: str | None = None,
    kind: GroupKind = GroupKind.SUPERGROUP,
    member_count: int | None = 100,
) -> TgChat:
    """number 로 구별되는 슈퍼그룹(기본) 하나. id 는 -1001000000000 - number 다."""
    return TgChat(
        id=-1_001_000_000_000 - number,
        title=title or f"테스트 그룹 {number}",
        username=username,
        kind=kind,
        member_count=member_count,
    )


class FakeClient(AccountClient):
    """계정 하나의 가짜 연결. 무엇을 돌려줄지는 FakeGateway 의 스크립트가 정한다."""

    def __init__(self, gateway: FakeGateway, account_id: int, session: str) -> None:
        self.gateway = gateway
        self.account_id = account_id
        self.session = session
        self.connected = False
        self.logged_out = False
        self.handler: MessageHandler | None = None
        self._closed: asyncio.Future[None] | None = None

    # --- 테스트가 부르는 조종 장치 -----------------------------------------

    async def emit_message(
        self,
        chat_id: int,
        text: str,
        sender: TgUser | None = None,
        *,
        message_id: int | None = None,
        date: datetime | None = None,
    ) -> IncomingMessage:
        """그룹에 새 메시지가 온 것처럼 핸들러를 부른다. 핸들러가 없으면 메시지는 버려진다.

        message_id 를 주지 않으면 게이트웨이 전체에서 겹치지 않는 번호를 쓴다.
        """
        message = IncomingMessage(
            account_id=self.account_id,
            chat_id=chat_id,
            message_id=message_id if message_id is not None else self.gateway.next_message_id(),
            sender=sender,
            text=text,
            date=date or datetime.now(UTC),
        )
        if self.handler is not None:
            await self.handler(message)
        return message

    def drop(self, error: BaseException | None = None) -> None:
        """연결이 끊긴 것처럼 만든다. error 를 주면 wait_closed() 가 그 오류를 던진다."""
        self.connected = False
        closed = self._closed
        if closed is None or closed.done():
            return
        if error is None:
            closed.set_result(None)
        else:
            closed.set_exception(error)

    # --- AccountClient -----------------------------------------------------

    async def connect(self) -> TgUser:
        await self._enter("connect")
        script = self.gateway.connect_script.get(self.account_id)
        outcome = script.popleft() if script else self.gateway.user_for(self)
        if isinstance(outcome, BaseException):
            raise outcome
        self.session = self.gateway.session_after_connect.get(self.account_id, self.session)
        self.connected = True
        self._closed = asyncio.get_running_loop().create_future()
        return outcome

    async def disconnect(self) -> None:
        await self._enter("disconnect")
        self.drop()

    async def wait_closed(self) -> None:
        if self._closed is not None:
            # 기다리던 쪽이 취소돼도 연결 자체는 그대로 둔다.
            await asyncio.shield(self._closed)

    def set_message_handler(self, handler: MessageHandler | None) -> None:
        self.handler = handler

    async def join(self, target: LinkTarget) -> JoinResult:
        await self._enter("join", target)
        return self.gateway.next_join(target)

    async def find_membership(
        self, target: LinkTarget | None, tg_chat_id: int | None
    ) -> TgChat | None:
        await self._enter("find_membership", target, tg_chat_id)
        answers = self.gateway.memberships
        if tg_chat_id is not None and tg_chat_id in answers:
            answer = answers[tg_chat_id]
        else:
            answer = answers.get(target.value) if target is not None else None
        if isinstance(answer, BaseException):
            raise answer
        return answer

    async def list_groups(self) -> list[TgChat]:
        await self._enter("list_groups")
        answer = self.gateway.dialogs.get(self.account_id, [])
        if isinstance(answer, BaseException):
            raise answer
        return list(answer)

    async def leave(self, tg_chat_id: int) -> None:
        await self._enter("leave", tg_chat_id)
        if self.gateway.leave_error is not None:
            raise self.gateway.leave_error

    async def log_out(self) -> None:
        await self._enter("log_out")
        if self.gateway.log_out_error is not None:
            raise self.gateway.log_out_error
        self.logged_out = True
        self.drop()

    def export_session(self) -> str:
        return self.session

    async def _enter(self, name: str, *args: Any) -> None:
        """호출을 적고, 그 메서드가 붙잡혀 있으면(hold) 풀릴 때까지 기다린다."""
        self.gateway.calls.append((self.account_id, name, args))
        gate = self.gateway.gates.get(name)
        if gate is not None:
            await gate.wait()


class FakeGateway(TelegramGateway):
    """가짜 게이트웨이. 아래 속성을 테스트에서 직접 채워 동작을 정한다."""

    def __init__(self) -> None:
        self.calls: list[tuple[int | None, str, tuple[Any, ...]]] = []
        """받은 호출을 순서대로 (account_id, 메서드 이름, 인자)로 적는다. 로그인 쪽 호출은 account_id 가 None."""
        self.clients: list[FakeClient] = []
        """create_client() 로 만든 연결 전부(만든 순서)."""
        self.users: dict[int, TgUser] = {}
        """account_id → connect() 가 돌려줄 내 정보. 없으면 세션이나 account_id 로 정해진 값을 쓴다."""
        self.connect_script: dict[int, deque[TgUser | BaseException]] = {}
        self.session_after_connect: dict[int, str] = {}
        """account_id → 접속한 뒤 export_session() 이 돌려줄 세션(DC 이동으로 세션이 바뀐 경우)."""
        self.join_script: dict[str, deque[JoinResult | BaseException]] = {}
        self.gates: dict[str, asyncio.Event] = {}
        """연결 메서드 이름 → 켜질 때까지 그 호출을 붙잡아 두는 이벤트(hold() 로 만든다)."""
        self.memberships: dict[str | int, TgChat | BaseException | None] = {}
        """링크 값(아이디·초대 해시) 또는 tg_chat_id → find_membership() 의 답. 없으면 None(멤버 아님)."""
        self.dialogs: dict[int, list[TgChat] | BaseException] = {}
        """account_id → list_groups() 의 답. 없으면 빈 목록."""
        self.leave_error: BaseException | None = None
        self.log_out_error: BaseException | None = None
        self.start_login_error: BaseException | None = None
        self.login_script: deque[LoginResult | BaseException] = deque()
        """submit_code / submit_password / import_session 이 앞에서부터 하나씩 꺼내 쓴다."""
        self.closed = False

        self._session_users: dict[str, TgUser] = {}
        self._auto_chats: dict[str, TgChat] = {}
        self._login_ids = itertools.count(1)
        self._message_ids = itertools.count(1)

    # --- 테스트가 부르는 조종 장치 -----------------------------------------

    def script_connect(self, account_id: int, *outcomes: TgUser | BaseException) -> None:
        """이 계정의 다음 connect() 들이 차례로 낼 결과. 다 쓰면 평소대로 성공한다."""
        self.connect_script.setdefault(account_id, deque()).extend(outcomes)

    def script_join(self, link: str, *outcomes: JoinResult | BaseException) -> None:
        """링크 값(아이디·초대 해시)에 대한 join() 결과를 차례로 정한다. 마지막 값은 계속 쓴다.

        정해 두지 않은 링크는 링크마다 하나씩 만들어지는 슈퍼그룹(make_chat(1001), make_chat(1002), …)에
        바로 가입된다.
        """
        self.join_script.setdefault(link, deque()).extend(outcomes)

    def hold(self, name: str) -> asyncio.Event:
        """연결의 name 메서드(connect, join, …)가 돌려준 이벤트가 켜질 때까지 답하지 않게 한다."""
        gate = self.gates[name] = asyncio.Event()
        return gate

    def client(self, account_id: int) -> FakeClient:
        """그 계정으로 가장 최근에 만든 연결."""
        for client in reversed(self.clients):
            if client.account_id == account_id:
                return client
        raise LookupError(f"계정 {account_id} 의 연결을 만든 적이 없어요")

    def called(self, name: str, account_id: int | None = None) -> list[tuple[Any, ...]]:
        """name 메서드가 받은 호출의 인자들(account_id 를 주면 그 계정 것만)."""
        return [
            args
            for owner, method, args in self.calls
            if method == name and (account_id is None or owner == account_id)
        ]

    # --- FakeClient 가 쓰는 것 ---------------------------------------------

    def next_message_id(self) -> int:
        return next(self._message_ids)

    def user_for(self, client: FakeClient) -> TgUser:
        """스크립트가 없을 때 connect() 가 돌려줄 내 정보."""
        known = self._session_users.get(client.session) or self.users.get(client.account_id)
        if known is not None:
            return known
        number = client.account_id
        return TgUser(id=7_000_000 + number, username=f"owner_{number}", first_name=f"계정{number}")

    def next_join(self, target: LinkTarget) -> JoinResult:
        script = self.join_script.get(target.value)
        if not script:
            chat = self._auto_chats.get(target.value)
            if chat is None:
                username = target.value if target.kind == LinkKind.PUBLIC else None
                chat = make_chat(1001 + len(self._auto_chats), username=username)
                self._auto_chats[target.value] = chat
            return JoinResult(JoinOutcome.JOINED, chat=chat)
        outcome = script.popleft() if len(script) > 1 else script[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    # --- TelegramGateway ---------------------------------------------------

    def create_client(self, account_id: int, session: str) -> AccountClient:
        client = FakeClient(self, account_id, session)
        self.clients.append(client)
        return client

    async def start_login(self, phone: str) -> PendingLogin:
        self.calls.append((None, "start_login", (phone,)))
        if self.start_login_error is not None:
            raise self.start_login_error
        return PendingLogin(
            login_id=f"login-{next(self._login_ids)}",
            phone=phone,
            code_via="app",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

    async def submit_code(self, login_id: str, code: str) -> LoginResult:
        self.calls.append((None, "submit_code", (login_id, code)))
        return self._next_login()

    async def submit_password(self, login_id: str, password: str) -> LoginResult:
        self.calls.append((None, "submit_password", (login_id, password)))
        return self._next_login()

    async def cancel_login(self, login_id: str) -> None:
        self.calls.append((None, "cancel_login", (login_id,)))

    async def import_session(self, data: str | bytes) -> LoginResult:
        self.calls.append((None, "import_session", (data,)))
        return self._next_login()

    async def close(self) -> None:
        self.calls.append((None, "close", ()))
        self.closed = True

    def _next_login(self) -> LoginResult:
        if not self.login_script:
            raise AssertionError("login_script 가 비어 있어요. 로그인 결과를 먼저 넣어 주세요.")
        outcome = self.login_script.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome.session and outcome.user is not None:
            # 이 세션으로 접속하면 같은 사람이 나오게 한다.
            self._session_users[outcome.session] = outcome.user
        return outcome
