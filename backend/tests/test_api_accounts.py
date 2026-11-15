"""/api/accounts 테스트."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.db import Database
from app.models import (
    Account,
    AccountStatus,
    EventLog,
    Group,
    GroupKind,
    GroupStatus,
    LinkKind,
    LogCategory,
)
from app.routers.accounts import MAX_SESSION_FILE_BYTES
from app.telegram.gateway import (
    LoginResult,
    PendingLogin,
    TelegramError,
    TgChat,
    TgErrorCode,
    TgUser,
)

from .stubs import StubEngine

SESSION_STRING = "1BVtsOHwBu5-" + "A" * 60
EXPIRES_AT = datetime(2026, 11, 15, 12, 10, tzinfo=UTC)


class ScriptedEngine(StubEngine):
    """정해 둔 결과를 돌려주고, 진짜 엔진처럼 자기 DB 세션으로 계정을 고친다."""

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db
        self.errors: dict[str, Exception] = {}
        self.login_result = LoginResult(status="done", session="saved-session")
        self.user = TgUser(id=7001, username="sales_kim", first_name="민수", last_name="김")

    def _enter(self, name: str, *args: Any, **kwargs: Any) -> None:
        self._record(name, *args, **kwargs)
        if name in self.errors:
            raise self.errors[name]

    async def _save_account(self, label: str | None = None) -> Account:
        async with self.db.session() as session:
            account = Account(
                label=label,
                phone="+821012343421",
                tg_user_id=self.user.id,
                first_name=self.user.first_name,
                last_name=self.user.last_name,
                username=self.user.username,
                session_enc="encrypted",
                status=AccountStatus.ACTIVE,
            )
            session.add(account)
            await session.commit()
            return account

    async def _finish_login(self) -> tuple[LoginResult, Account | None]:
        if self.login_result.status != "done":
            return self.login_result, None
        return self.login_result, await self._save_account()

    async def start_login(self, phone: str) -> PendingLogin:
        self._enter("start_login", phone)
        return PendingLogin(login_id="login-1", phone=phone, code_via="app", expires_at=EXPIRES_AT)

    async def submit_code(self, login_id: str, code: str) -> tuple[LoginResult, Account | None]:
        self._enter("submit_code", login_id, code)
        return await self._finish_login()

    async def submit_password(
        self, login_id: str, password: str
    ) -> tuple[LoginResult, Account | None]:
        self._enter("submit_password", login_id, password)
        return await self._finish_login()

    async def import_session(self, data: str | bytes, label: str | None = None) -> Account:
        self._enter("import_session", data, label)
        return await self._save_account(label)

    async def set_account_enabled(self, account_id: int, enabled: bool) -> None:
        self._enter("set_account_enabled", account_id, enabled)
        async with self.db.session() as session:
            account = await session.get(Account, account_id)
            account.enabled = enabled
            account.status = AccountStatus.CONNECTING if enabled else AccountStatus.OFFLINE
            await session.commit()

    async def reconnect(self, account_id: int) -> None:
        self._enter("reconnect", account_id)
        async with self.db.session() as session:
            account = await session.get(Account, account_id)
            account.status = AccountStatus.CONNECTING
            account.status_detail = None
            await session.commit()

    async def remove_account(self, account_id: int, *, log_out: bool = False) -> None:
        self._enter("remove_account", account_id, log_out=log_out)
        async with self.db.session() as session:
            await session.delete(await session.get(Account, account_id))
            await session.commit()

    async def list_dialogs(self, account_id: int) -> list[TgChat]:
        self._enter("list_dialogs", account_id)
        return self.dialogs.get(account_id, [])


@pytest.fixture
def engine(ctx) -> ScriptedEngine:
    scripted = ScriptedEngine(ctx.db)
    ctx.engine = scripted
    return scripted


async def add_account(ctx, **fields: Any) -> Account:
    values: dict[str, Any] = {"session_enc": "encrypted", "status": AccountStatus.ACTIVE}
    values.update(fields)
    async with ctx.db.session() as session:
        account = Account(**values)
        session.add(account)
        await session.commit()
        return account


async def add_group(ctx, account: Account, **fields: Any) -> Group:
    values: dict[str, Any] = {"status": GroupStatus.JOINED, "link_kind": LinkKind.PUBLIC}
    values.update(fields)
    async with ctx.db.session() as session:
        group = Group(account_id=account.id, **values)
        session.add(group)
        await session.commit()
        return group


async def all_groups(ctx) -> list[Group]:
    async with ctx.db.session() as session:
        return list((await session.execute(select(Group).order_by(Group.id))).scalars())


async def all_accounts(ctx) -> list[Account]:
    async with ctx.db.session() as session:
        return list((await session.execute(select(Account).order_by(Account.id))).scalars())


async def all_logs(ctx) -> list[EventLog]:
    async with ctx.db.session() as session:
        return list((await session.execute(select(EventLog).order_by(EventLog.id))).scalars())


def chat(chat_id: int, title: str, **fields: Any) -> TgChat:
    values: dict[str, Any] = {"username": None, "kind": GroupKind.SUPERGROUP, "member_count": 100}
    values.update(fields)
    return TgChat(id=chat_id, title=title, **values)


# --- 로그인 필요 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/accounts"),
        ("POST", "/api/accounts/login/start"),
        ("POST", "/api/accounts/login/code"),
        ("POST", "/api/accounts/login/password"),
        ("DELETE", "/api/accounts/login/login-1"),
        ("POST", "/api/accounts/import"),
        ("POST", "/api/accounts/import-file"),
        ("PATCH", "/api/accounts/1"),
        ("POST", "/api/accounts/1/reconnect"),
        ("DELETE", "/api/accounts/1"),
        ("GET", "/api/accounts/1/dialogs"),
        ("POST", "/api/accounts/1/dialogs/import"),
    ],
)
async def test_requires_login(client, engine, method, path):
    res = await client.request(method, path)

    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"
    assert engine.calls == []


# --- 목록 --------------------------------------------------------------------


async def test_list_empty(authed):
    res = await authed.get("/api/accounts")

    assert res.status_code == 200
    assert res.json() == []


async def test_list_accounts_with_group_counts(authed, ctx):
    flood_until = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=5)
    first = await add_account(
        ctx,
        label="영업 1호",
        phone="+821012343421",
        tg_user_id=111,
        username="sales_one",
        status=AccountStatus.FLOOD_WAIT,
        status_detail="요청이 많아 잠시 쉬고 있어요.",
        flood_until=flood_until,
    )
    second = await add_account(ctx, first_name="지현", last_name="박", enabled=False)
    for status in (GroupStatus.JOINED, GroupStatus.JOINED, GroupStatus.QUEUED):
        await add_group(ctx, first, status=status)
    for status in (GroupStatus.JOINING, GroupStatus.REQUESTED, GroupStatus.FAILED):
        await add_group(ctx, first, status=status)
    await add_group(ctx, second, status=GroupStatus.LEFT)
    await authed.patch("/api/settings", json={"max_groups_per_account": 25})

    res = await authed.get("/api/accounts")

    assert res.status_code == 200
    one, two = res.json()
    assert one["id"] == first.id
    assert one["label"] == "영업 1호"
    assert one["display_name"] == "영업 1호"
    assert one["phone_masked"] == "+82 10-••••-3421"
    assert one["username"] == "sales_one"
    assert one["status"] == "flood_wait"
    assert one["status_detail"] == "요청이 많아 잠시 쉬고 있어요."
    assert datetime.fromisoformat(one["flood_until"]) == flood_until
    assert (one["joined_count"], one["pending_count"], one["max_groups"]) == (2, 3, 25)
    assert two["id"] == second.id
    assert two["display_name"] == "지현 박"
    assert two["enabled"] is False
    assert (two["joined_count"], two["pending_count"]) == (0, 0)
    # 세션이나 번호 원문은 내려가지 않는다.
    assert "session_enc" not in one and "phone" not in one
    assert "encrypted" not in res.text and "+821012343421" not in res.text


# --- 번호 로그인 --------------------------------------------------------------


async def test_login_start(authed, engine):
    res = await authed.post("/api/accounts/login/start", json={"phone": " +821012343421 "})

    assert res.status_code == 200
    body = res.json()
    assert body["login_id"] == "login-1"
    assert body["phone"] == "+821012343421"
    assert body["code_via"] == "app"
    assert datetime.fromisoformat(body["expires_at"]) == EXPIRES_AT
    assert engine.called("start_login") == [(("+821012343421",), {})]


async def test_login_start_validation(authed, engine):
    res = await authed.post("/api/accounts/login/start", json={"phone": "12"})

    assert res.status_code == 422
    assert res.json()["detail"] == "전화번호 값이 너무 짧아요."
    assert engine.calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "retry_after"),
    [
        (TelegramError(TgErrorCode.PHONE_INVALID, "전화번호를 다시 확인해 주세요."), 400, None),
        (
            TelegramError(TgErrorCode.FLOOD_WAIT, "잠시 뒤에 다시 해 주세요.", retry_after=73),
            429,
            73,
        ),
        (TelegramError(TgErrorCode.API_CREDENTIALS, "API 키가 아직 없어요."), 409, None),
        (TelegramError(TgErrorCode.NETWORK, "텔레그램에 연결하지 못했어요."), 503, None),
    ],
)
async def test_login_start_telegram_errors(authed, engine, error, status_code, retry_after):
    engine.errors["start_login"] = error

    res = await authed.post("/api/accounts/login/start", json={"phone": "+821012343421"})

    assert res.status_code == status_code
    assert res.json() == {
        "detail": error.message,
        "code": str(error.code),
        "retry_after": retry_after,
    }
    if retry_after:
        assert res.headers["retry-after"] == str(retry_after)


async def test_login_code_done_returns_saved_account(authed, engine):
    res = await authed.post(
        "/api/accounts/login/code", json={"login_id": "login-1", "code": " 12345 "}
    )

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "done"
    assert body["password_hint"] is None
    assert body["account"]["username"] == "sales_kim"
    assert body["account"]["display_name"] == "민수 김"
    assert body["account"]["status"] == "active"
    assert body["account"]["max_groups"] == 20
    assert engine.called("submit_code") == [(("login-1", "12345"), {})]


async def test_login_code_password_required(authed, engine, ctx):
    engine.login_result = LoginResult(status="password_required", password_hint="고양이 이름")

    res = await authed.post(
        "/api/accounts/login/code", json={"login_id": "login-1", "code": "12345"}
    )

    assert res.status_code == 200
    assert res.json() == {
        "status": "password_required",
        "account": None,
        "password_hint": "고양이 이름",
    }
    assert await all_accounts(ctx) == []


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        (TgErrorCode.CODE_INVALID, 400),
        (TgErrorCode.CODE_EXPIRED, 400),
        (TgErrorCode.LOGIN_EXPIRED, 410),
    ],
)
async def test_login_code_telegram_errors(authed, engine, code, status_code):
    engine.errors["submit_code"] = TelegramError(code, "인증 코드를 다시 확인해 주세요.")

    res = await authed.post(
        "/api/accounts/login/code", json={"login_id": "login-1", "code": "00000"}
    )

    assert res.status_code == status_code
    assert res.json()["code"] == str(code)
    assert res.json()["detail"] == "인증 코드를 다시 확인해 주세요."


async def test_login_code_validation(authed, engine):
    res = await authed.post("/api/accounts/login/code", json={"login_id": "login-1", "code": "1"})

    assert res.status_code == 422
    assert res.json()["detail"] == "인증 코드 값이 너무 짧아요."
    assert engine.calls == []


async def test_login_password_done(authed, engine):
    res = await authed.post(
        "/api/accounts/login/password", json={"login_id": "login-1", "password": " p w "}
    )

    assert res.status_code == 200
    assert res.json()["status"] == "done"
    assert res.json()["account"]["tg_user_id"] == 7001
    # 비밀번호는 앞뒤 공백도 그대로 넘긴다.
    assert engine.called("submit_password") == [(("login-1", " p w "), {})]


async def test_login_password_wrong(authed, engine, ctx):
    engine.errors["submit_password"] = TelegramError(
        TgErrorCode.PASSWORD_INVALID, "2단계 인증 비밀번호가 맞지 않아요."
    )

    res = await authed.post(
        "/api/accounts/login/password", json={"login_id": "login-1", "password": "nope"}
    )

    assert res.status_code == 400
    assert res.json()["code"] == "password_invalid"
    assert await all_accounts(ctx) == []


async def test_login_cancel(authed, engine):
    res = await authed.delete("/api/accounts/login/login-1")

    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert engine.called("cancel_login") == [(("login-1",), {})]


# --- 세션 불러오기 -------------------------------------------------------------


async def test_import_session_string(authed, engine):
    res = await authed.post(
        "/api/accounts/import",
        json={"session_string": f"  {SESSION_STRING}\n", "label": "  영업 2호 "},
    )

    assert res.status_code == 200
    assert res.json()["label"] == "영업 2호"
    assert res.json()["display_name"] == "영업 2호"
    assert engine.called("import_session") == [((SESSION_STRING, "영업 2호"), {})]


@pytest.mark.parametrize("label", [None, "", "   "])
async def test_import_session_blank_label_becomes_none(authed, engine, label):
    res = await authed.post(
        "/api/accounts/import", json={"session_string": SESSION_STRING, "label": label}
    )

    assert res.status_code == 200
    assert res.json()["label"] is None
    assert engine.called("import_session") == [((SESSION_STRING, None), {})]


async def test_import_session_validation(authed, engine):
    res = await authed.post("/api/accounts/import", json={"session_string": "too-short"})

    assert res.status_code == 422
    assert res.json()["detail"] == "세션 문자열 값이 너무 짧아요."
    assert engine.calls == []


@pytest.mark.parametrize(
    "code", [TgErrorCode.SESSION_FORMAT, TgErrorCode.SESSION_INVALID, TgErrorCode.BANNED]
)
async def test_import_session_telegram_errors(authed, engine, ctx, code):
    engine.errors["import_session"] = TelegramError(code, "세션을 쓸 수 없어요.", permanent=True)

    res = await authed.post("/api/accounts/import", json={"session_string": SESSION_STRING})

    assert res.status_code == 400
    assert res.json() == {"detail": "세션을 쓸 수 없어요.", "code": str(code), "retry_after": None}
    assert await all_accounts(ctx) == []


# --- 세션 파일 불러오기 ---------------------------------------------------------

SESSION_FILE = b"SQLite format 3\x00" + bytes(range(256)) * 4


async def test_import_file(authed, engine):
    res = await authed.post(
        "/api/accounts/import-file",
        files={"file": ("account.session", SESSION_FILE, "application/octet-stream")},
        data={"label": " 영업 3호 "},
    )

    assert res.status_code == 200
    assert res.json()["label"] == "영업 3호"
    assert res.json()["username"] == "sales_kim"
    assert engine.called("import_session") == [((SESSION_FILE, "영업 3호"), {})]


async def test_import_file_without_label(authed, engine):
    res = await authed.post(
        "/api/accounts/import-file", files={"file": ("account.session", SESSION_FILE)}
    )

    assert res.status_code == 200
    assert res.json()["label"] is None
    assert engine.called("import_session") == [((SESSION_FILE, None), {})]


async def test_import_file_at_the_size_limit(authed, engine):
    data = b"x" * MAX_SESSION_FILE_BYTES

    res = await authed.post("/api/accounts/import-file", files={"file": ("big.session", data)})

    assert res.status_code == 200
    (args, _kwargs) = engine.called("import_session")[0]
    assert len(args[0]) == MAX_SESSION_FILE_BYTES


async def test_import_file_too_large(authed, engine):
    data = b"x" * (MAX_SESSION_FILE_BYTES + 1)

    res = await authed.post("/api/accounts/import-file", files={"file": ("big.session", data)})

    assert res.status_code == 413
    assert res.json()["code"] == "file_too_large"
    assert res.json()["detail"] == "세션 파일이 너무 커요. 2MB 이하 파일만 올릴 수 있어요."
    assert engine.calls == []


def multipart(files: dict[str, Any]) -> tuple[bytes, str]:
    """(멀티파트 본문, Content-Type) 을 만든다."""
    request = httpx.Request("POST", "http://testserver/", files=files)
    return request.read(), request.headers["content-type"]


class ChunkedBody:
    """Content-Length 없이 조각으로 보내는 본문. 서버가 몇 바이트를 읽어 갔는지 센다."""

    def __init__(self, body: bytes, chunk_size: int = 64 * 1024) -> None:
        self.body = body
        self.chunk_size = chunk_size
        self.sent = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for start in range(0, len(self.body), self.chunk_size):
            piece = self.body[start : start + self.chunk_size]
            self.sent += len(piece)
            yield piece


async def test_import_file_rejects_declared_oversize_without_reading(authed, engine):
    body, content_type = multipart({"file": ("big.session", b"x" * (4 * 1024 * 1024))})
    stream = ChunkedBody(body)

    res = await authed.post(
        "/api/accounts/import-file",
        content=stream,
        headers={"content-type": content_type, "content-length": str(len(body))},
    )

    assert res.status_code == 413
    assert stream.sent == 0
    assert engine.calls == []


async def test_import_file_stops_reading_an_undeclared_oversize_body(authed, engine):
    body, content_type = multipart({"file": ("big.session", b"x" * (8 * 1024 * 1024))})
    stream = ChunkedBody(body)

    res = await authed.post(
        "/api/accounts/import-file", content=stream, headers={"content-type": content_type}
    )

    assert res.status_code == 413
    assert res.json()["code"] == "file_too_large"
    # 한도를 넘긴 조각에서 바로 끊는다(끝까지 받아 두지 않는다).
    assert stream.sent <= MAX_SESSION_FILE_BYTES + 2 * 64 * 1024
    assert engine.calls == []


async def test_import_file_is_not_read_before_login(client, engine):
    body, content_type = multipart({"file": ("account.session", SESSION_FILE)})
    stream = ChunkedBody(body)

    res = await client.post(
        "/api/accounts/import-file", content=stream, headers={"content-type": content_type}
    )

    assert res.status_code == 401
    assert stream.sent == 0


async def test_import_file_missing_file(authed, engine):
    res = await authed.post("/api/accounts/import-file", data={"label": "영업 3호"})

    assert res.status_code == 422
    assert res.json()["detail"] == "세션 파일을 골라 주세요."
    assert engine.calls == []


async def test_import_file_rejects_text_field_named_file(authed, engine):
    # 파일 이름이 없는 파트는 파일이 아니라 글자 필드다.
    res = await authed.post("/api/accounts/import-file", files={"file": (None, "not-a-file")})

    assert res.status_code == 422
    assert res.json()["detail"] == "세션 파일을 골라 주세요."
    assert engine.calls == []


async def test_import_file_rejects_json_body(authed, engine):
    res = await authed.post("/api/accounts/import-file", json={"file": "abc"})

    assert res.status_code == 422
    assert res.json()["detail"] == "세션 파일을 골라 주세요."


async def test_import_file_empty_file(authed, engine):
    res = await authed.post("/api/accounts/import-file", files={"file": ("empty.session", b"")})

    assert res.status_code == 400
    assert res.json()["code"] == "empty_file"
    assert engine.calls == []


async def test_import_file_label_too_long(authed, engine):
    res = await authed.post(
        "/api/accounts/import-file",
        files={"file": ("account.session", SESSION_FILE)},
        data={"label": "가" * 65},
    )

    assert res.status_code == 422
    assert res.json()["detail"] == "별칭은 64자까지 쓸 수 있어요."
    assert engine.calls == []


async def test_import_file_broken_multipart(authed, engine):
    res = await authed.post(
        "/api/accounts/import-file",
        content=b"this is not multipart",
        headers={"content-type": "multipart/form-data"},
    )

    assert res.status_code == 400
    assert res.json()["code"] == "bad_upload"
    assert res.json()["detail"] == "올린 내용을 읽을 수 없어요. 세션 파일을 다시 골라 주세요."
    assert engine.calls == []


async def test_import_file_more_than_one_file(authed, engine):
    res = await authed.post(
        "/api/accounts/import-file",
        files=[("file", ("a.session", SESSION_FILE)), ("file", ("b.session", SESSION_FILE))],
    )

    assert res.status_code == 400
    assert res.json()["code"] == "bad_upload"
    assert engine.calls == []


async def test_import_file_telegram_error(authed, engine):
    engine.errors["import_session"] = TelegramError(
        TgErrorCode.SESSION_FORMAT, "세션 파일을 읽을 수 없어요.", permanent=True
    )

    res = await authed.post(
        "/api/accounts/import-file", files={"file": ("account.session", SESSION_FILE)}
    )

    assert res.status_code == 400
    assert res.json()["code"] == "session_format"
    assert res.json()["detail"] == "세션 파일을 읽을 수 없어요."


# --- 계정 고치기 --------------------------------------------------------------


async def test_patch_label(authed, engine, ctx):
    account = await add_account(ctx, first_name="민수")

    res = await authed.patch(f"/api/accounts/{account.id}", json={"label": "  영업 1호  "})

    assert res.status_code == 200
    assert res.json()["label"] == "영업 1호"
    assert res.json()["display_name"] == "영업 1호"
    assert (await all_accounts(ctx))[0].label == "영업 1호"
    assert engine.calls == []


@pytest.mark.parametrize("label", [None, "", "   "])
async def test_patch_label_can_be_cleared(authed, engine, ctx, label):
    account = await add_account(ctx, label="영업 1호", first_name="민수")

    res = await authed.patch(f"/api/accounts/{account.id}", json={"label": label})

    assert res.status_code == 200
    assert res.json()["label"] is None
    assert res.json()["display_name"] == "민수"


async def test_patch_without_label_keeps_it(authed, engine, ctx):
    account = await add_account(ctx, label="영업 1호")

    res = await authed.patch(f"/api/accounts/{account.id}", json={})

    assert res.status_code == 200
    assert res.json()["label"] == "영업 1호"
    assert engine.calls == []


async def test_patch_label_too_long(authed, engine, ctx):
    account = await add_account(ctx, label="영업 1호")

    res = await authed.patch(f"/api/accounts/{account.id}", json={"label": "가" * 65})

    assert res.status_code == 422
    assert (await all_accounts(ctx))[0].label == "영업 1호"


async def test_patch_disable_goes_through_the_engine(authed, engine, ctx):
    account = await add_account(ctx)

    res = await authed.patch(f"/api/accounts/{account.id}", json={"enabled": False})

    assert res.status_code == 200
    # 엔진이 자기 세션에서 바꾼 값이 응답에 그대로 보여야 한다.
    assert res.json()["enabled"] is False
    assert res.json()["status"] == "offline"
    assert engine.called("set_account_enabled") == [((account.id, False), {})]


async def test_patch_enable_and_label_together(authed, engine, ctx):
    account = await add_account(ctx, enabled=False, status=AccountStatus.OFFLINE)

    res = await authed.patch(
        f"/api/accounts/{account.id}", json={"enabled": True, "label": "다시 켠 계정"}
    )

    assert res.status_code == 200
    assert res.json()["enabled"] is True
    assert res.json()["status"] == "connecting"
    assert res.json()["label"] == "다시 켠 계정"
    assert engine.called("set_account_enabled") == [((account.id, True), {})]


async def test_patch_enabled_unchanged_does_not_touch_the_engine(authed, engine, ctx):
    account = await add_account(ctx)

    res = await authed.patch(f"/api/accounts/{account.id}", json={"enabled": True})

    assert res.status_code == 200
    assert res.json()["status"] == "active"
    assert engine.calls == []


async def test_patch_missing_account(authed, engine):
    res = await authed.patch("/api/accounts/999", json={"enabled": False})

    assert res.status_code == 404
    assert res.json() == {
        "detail": "계정을 찾을 수 없어요.",
        "code": "not_found",
        "retry_after": None,
    }
    assert engine.calls == []


async def test_absurd_account_id_is_rejected_cleanly(authed, engine):
    res = await authed.patch(f"/api/accounts/{2**70}", json={"enabled": False})

    assert res.status_code == 422
    assert engine.calls == []


# --- 다시 연결 · 삭제 -----------------------------------------------------------


async def test_reconnect(authed, engine, ctx):
    account = await add_account(ctx, status=AccountStatus.ERROR, status_detail="연결이 끊겼어요.")

    res = await authed.post(f"/api/accounts/{account.id}/reconnect")

    assert res.status_code == 200
    assert res.json()["status"] == "connecting"
    assert res.json()["status_detail"] is None
    assert engine.called("reconnect") == [((account.id,), {})]


async def test_reconnect_disabled_account(authed, engine, ctx):
    account = await add_account(ctx, enabled=False, status=AccountStatus.OFFLINE)

    res = await authed.post(f"/api/accounts/{account.id}/reconnect")

    assert res.status_code == 409
    assert res.json()["code"] == "account_disabled"
    assert engine.calls == []


async def test_reconnect_missing_account(authed, engine):
    res = await authed.post("/api/accounts/999/reconnect")

    assert res.status_code == 404
    assert res.json()["detail"] == "계정을 찾을 수 없어요."
    assert engine.calls == []


@pytest.mark.parametrize(
    ("query", "log_out"),
    [("", False), ("?log_out=false", False), ("?log_out=true", True)],
)
async def test_delete_account(authed, engine, ctx, query, log_out):
    account = await add_account(ctx)
    keep = await add_account(ctx)

    res = await authed.delete(f"/api/accounts/{account.id}{query}")

    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert engine.called("remove_account") == [((account.id,), {"log_out": log_out})]
    assert [a.id for a in await all_accounts(ctx)] == [keep.id]


async def test_delete_missing_account(authed, engine):
    res = await authed.delete("/api/accounts/999")

    assert res.status_code == 404
    assert engine.calls == []


# --- 이미 들어가 있는 그룹 ------------------------------------------------------


async def test_dialogs_mark_what_is_already_added(authed, engine, ctx):
    account = await add_account(ctx)
    other = await add_account(ctx)
    engine.dialogs[account.id] = [
        chat(-1001, "가입된 방", username="joined_room"),
        chat(-1002, "요청 중인 방"),
        chat(-1003, "실패한 방"),
        chat(-1004, "나간 방", kind=GroupKind.GROUP, member_count=None),
        chat(-1005, "새 방", kind=GroupKind.CHANNEL),
        chat(-1006, "다른 계정만 넣은 방"),
    ]
    await add_group(ctx, account, tg_chat_id=-1001)
    await add_group(ctx, account, tg_chat_id=-1002, status=GroupStatus.REQUESTED)
    await add_group(ctx, account, tg_chat_id=-1003, status=GroupStatus.FAILED)
    await add_group(ctx, account, tg_chat_id=-1004, status=GroupStatus.LEFT)
    await add_group(ctx, other, tg_chat_id=-1006)

    res = await authed.get(f"/api/accounts/{account.id}/dialogs")

    assert res.status_code == 200
    dialogs = res.json()
    assert dialogs[0] == {
        "tg_chat_id": -1001,
        "title": "가입된 방",
        "username": "joined_room",
        "kind": "supergroup",
        "member_count": 100,
        "already_added": True,
    }
    assert [(d["tg_chat_id"], d["already_added"]) for d in dialogs] == [
        (-1001, True),
        (-1002, True),
        (-1003, False),
        (-1004, False),
        (-1005, False),
        (-1006, False),
    ]
    assert (dialogs[3]["kind"], dialogs[3]["member_count"]) == ("group", None)
    assert dialogs[4]["kind"] == "channel"
    assert engine.called("list_dialogs") == [((account.id,), {})]


async def test_dialogs_missing_account(authed, engine):
    res = await authed.get("/api/accounts/999/dialogs")

    assert res.status_code == 404
    assert engine.calls == []


async def test_dialogs_when_account_is_not_connected(authed, engine, ctx):
    account = await add_account(ctx, status=AccountStatus.ERROR)
    engine.errors["list_dialogs"] = TelegramError(TgErrorCode.NETWORK, "계정이 연결돼 있지 않아요.")

    res = await authed.get(f"/api/accounts/{account.id}/dialogs")

    assert res.status_code == 503
    assert res.json() == {
        "detail": "계정이 연결돼 있지 않아요.",
        "code": "network",
        "retry_after": None,
    }


async def test_import_dialogs_creates_joined_groups(authed, engine, ctx):
    account = await add_account(ctx, label="영업 1호")
    engine.dialogs[account.id] = [
        chat(-1001, "코인 수다방", username="CoinTalk", member_count=5321),
        chat(-1002, "비공개 모임", kind=GroupKind.GROUP, member_count=None),
        chat(-1003, "고르지 않은 방"),
    ]
    before = datetime.now(UTC) - timedelta(seconds=1)

    res = await authed.post(
        f"/api/accounts/{account.id}/dialogs/import", json={"tg_chat_ids": [-1001, -1002]}
    )

    assert res.status_code == 200
    by_chat = {g["tg_chat_id"]: g for g in res.json()}
    assert set(by_chat) == {-1001, -1002}
    public = by_chat[-1001]
    assert public["account_id"] == account.id
    assert public["account_name"] == "영업 1호"
    assert public["link_kind"] == "existing"
    assert public["status"] == "joined"
    assert public["monitoring"] is True
    assert public["title"] == public["display_title"] == "코인 수다방"
    assert public["public_username"] == "CoinTalk"
    assert public["kind"] == "supergroup"
    assert public["member_count"] == 5321
    assert public["source_link"] is None
    assert datetime.fromisoformat(public["joined_at"]) >= before
    private = by_chat[-1002]
    assert (private["kind"], private["member_count"], private["public_username"]) == (
        "group",
        None,
        None,
    )
    assert [g.tg_chat_id for g in await all_groups(ctx)] == [-1001, -1002]
    assert engine.called("notify_groups_changed") == [((account.id,), {})]


async def test_import_dialogs_explains_that_channels_are_not_collected(authed, engine, ctx):
    account = await add_account(ctx)
    engine.dialogs[account.id] = [
        chat(-1001, "공지 채널", kind=GroupKind.CHANNEL),
        chat(-1002, "수다방", kind=GroupKind.SUPERGROUP),
    ]

    res = await authed.post(
        f"/api/accounts/{account.id}/dialogs/import", json={"tg_chat_ids": [-1001, -1002]}
    )

    details = {g["tg_chat_id"]: (g["kind"], g["status_detail"]) for g in res.json()}
    assert details == {
        -1001: ("channel", "방송 채널이라 유저 채팅은 수집되지 않아요"),
        -1002: ("supergroup", None),
    }


async def test_import_dialogs_writes_one_log_entry(authed, engine, ctx):
    account = await add_account(ctx)
    engine.dialogs[account.id] = [chat(-1001, "가"), chat(-1002, "나"), chat(-1003, "다")]

    await authed.post(
        f"/api/accounts/{account.id}/dialogs/import",
        json={"tg_chat_ids": [-1001, -1002, -1003]},
    )

    logs = await all_logs(ctx)
    assert len(logs) == 1
    assert logs[0].message == "이미 들어가 있던 그룹 3개를 감시 목록에 넣었어요."
    assert logs[0].category == LogCategory.GROUP
    assert logs[0].account_id == account.id


async def test_import_dialogs_accepts_only_chats_the_account_is_in(authed, engine, ctx):
    account = await add_account(ctx)
    other = await add_account(ctx)
    engine.dialogs[account.id] = [chat(-1001, "내 방")]
    engine.dialogs[other.id] = [chat(-2001, "다른 계정의 방")]

    res = await authed.post(
        f"/api/accounts/{account.id}/dialogs/import",
        json={"tg_chat_ids": [-2001, -1001, -9999, -1001]},
    )

    assert res.status_code == 200
    assert [g["tg_chat_id"] for g in res.json()] == [-1001]
    assert [(g.account_id, g.tg_chat_id) for g in await all_groups(ctx)] == [(account.id, -1001)]


async def test_import_dialogs_with_nothing_acceptable(authed, engine, ctx):
    account = await add_account(ctx)
    engine.dialogs[account.id] = [chat(-1001, "내 방")]

    res = await authed.post(
        f"/api/accounts/{account.id}/dialogs/import", json={"tg_chat_ids": [-9999]}
    )

    assert res.status_code == 200
    assert res.json() == []
    assert await all_groups(ctx) == []
    assert engine.called("notify_groups_changed") == []
    assert await all_logs(ctx) == []


async def test_import_dialogs_skips_rows_that_already_exist(authed, engine, ctx):
    account = await add_account(ctx)
    engine.dialogs[account.id] = [chat(-1001, "가입된 방"), chat(-1002, "요청 중이던 방")]
    joined = await add_group(ctx, account, tg_chat_id=-1001, title="예전 제목", monitoring=False)
    requested = await add_group(
        ctx, account, tg_chat_id=-1002, status=GroupStatus.REQUESTED, link_kind=LinkKind.INVITE
    )

    res = await authed.post(
        f"/api/accounts/{account.id}/dialogs/import", json={"tg_chat_ids": [-1001, -1002]}
    )

    assert res.status_code == 200
    assert res.json() == []
    rows = {g.id: g for g in await all_groups(ctx)}
    assert len(rows) == 2
    # 이미 있는 행은 건드리지 않는다(사용자가 꺼 둔 감시도 그대로).
    assert (rows[joined.id].title, rows[joined.id].monitoring) == ("예전 제목", False)
    assert rows[requested.id].status == GroupStatus.REQUESTED
    assert engine.called("notify_groups_changed") == []


@pytest.mark.parametrize("gone", [GroupStatus.FAILED, GroupStatus.LEFT])
async def test_import_dialogs_revives_gone_rows(authed, engine, ctx, gone):
    account = await add_account(ctx)
    engine.dialogs[account.id] = [chat(-1001, "돌아온 방", username="back_again", member_count=42)]
    old = await add_group(
        ctx,
        account,
        tg_chat_id=-1001,
        status=gone,
        link_kind=LinkKind.INVITE,
        invite_hash="AbCdEfGh1234",
        source_link="https://t.me/+AbCdEfGh1234",
        title="예전 제목",
        status_detail="그룹에서 나갔어요.",
        error_code="private",
        attempts=3,
        next_attempt_at=datetime.now(UTC) + timedelta(hours=1),
        monitoring=False,
        messages_seen=17,
    )

    res = await authed.post(
        f"/api/accounts/{account.id}/dialogs/import", json={"tg_chat_ids": [-1001]}
    )

    assert res.status_code == 200
    (revived,) = res.json()
    assert revived["id"] == old.id
    assert revived["status"] == "joined"
    assert revived["title"] == "돌아온 방"
    assert revived["member_count"] == 42
    assert revived["public_username"] == "back_again"
    assert revived["monitoring"] is True
    assert revived["status_detail"] is None
    assert revived["error_code"] is None
    assert revived["attempts"] == 0
    assert revived["next_attempt_at"] is None
    assert revived["joined_at"] is not None
    # 넣을 때 쓴 링크와 그동안의 집계는 남긴다.
    assert revived["link_kind"] == "invite"
    assert revived["source_link"] == "https://t.me/+AbCdEfGh1234"
    assert revived["messages_seen"] == 17
    (row,) = await all_groups(ctx)
    assert row.invite_hash == "AbCdEfGh1234"
    assert engine.called("notify_groups_changed") == [((account.id,), {})]


async def test_import_dialogs_revive_keeps_what_telegram_did_not_tell_us(authed, engine, ctx):
    account = await add_account(ctx)
    engine.dialogs[account.id] = [chat(-1001, "", member_count=None)]
    await add_group(
        ctx,
        account,
        tg_chat_id=-1001,
        status=GroupStatus.LEFT,
        title="예전 제목",
        member_count=350,
        public_username="old_name",
    )

    res = await authed.post(
        f"/api/accounts/{account.id}/dialogs/import", json={"tg_chat_ids": [-1001]}
    )

    (revived,) = res.json()
    assert revived["status"] == "joined"
    assert (revived["title"], revived["member_count"], revived["public_username"]) == (
        "예전 제목",
        350,
        "old_name",
    )


async def test_import_dialogs_when_another_request_added_the_same_chat_meanwhile(
    authed, engine, ctx, monkeypatch
):
    account = await add_account(ctx)
    engine.dialogs[account.id] = [chat(-1001, "같이 누른 방"), chat(-1002, "다른 방")]

    def now_after_a_competing_insert() -> datetime:
        # 이 요청이 기존 행을 확인한 뒤, 저장하기 전에 다른 요청이 같은 그룹을 먼저 넣은 상황.
        with closing(sqlite3.connect(ctx.config.data_dir / "chatdb.sqlite3")) as conn, conn:
            conn.execute(
                "INSERT INTO groups (account_id, tg_chat_id, link_kind, status, attempts,"
                " monitoring, messages_seen, created_at)"
                " VALUES (?, -1001, 'existing', 'joined', 0, 1, 0, CURRENT_TIMESTAMP)",
                (account.id,),
            )
        return datetime.now(UTC)

    monkeypatch.setattr("app.routers.accounts.utcnow", now_after_a_competing_insert)

    res = await authed.post(
        f"/api/accounts/{account.id}/dialogs/import", json={"tg_chat_ids": [-1001, -1002]}
    )

    assert res.status_code == 409
    assert res.json()["code"] == "already_added"
    # 이 요청은 통째로 취소된다. 먼저 들어간 행만 남는다.
    assert [g.tg_chat_id for g in await all_groups(ctx)] == [-1001]
    assert engine.called("notify_groups_changed") == []

    monkeypatch.undo()
    res = await authed.post(
        f"/api/accounts/{account.id}/dialogs/import", json={"tg_chat_ids": [-1001, -1002]}
    )

    assert res.status_code == 200
    assert [g["tg_chat_id"] for g in res.json()] == [-1002]


async def test_import_dialogs_same_chat_on_two_accounts(authed, engine, ctx):
    first = await add_account(ctx)
    second = await add_account(ctx)
    engine.dialogs[second.id] = [chat(-1001, "같이 들어가 있는 방")]
    await add_group(ctx, first, tg_chat_id=-1001)

    res = await authed.post(
        f"/api/accounts/{second.id}/dialogs/import", json={"tg_chat_ids": [-1001]}
    )

    assert res.status_code == 200
    assert [g["account_id"] for g in res.json()] == [second.id]
    assert len(await all_groups(ctx)) == 2


async def test_import_dialogs_missing_account(authed, engine):
    res = await authed.post("/api/accounts/999/dialogs/import", json={"tg_chat_ids": [-1001]})

    assert res.status_code == 404
    assert engine.calls == []


async def test_import_dialogs_validation(authed, engine, ctx):
    account = await add_account(ctx)

    res = await authed.post(f"/api/accounts/{account.id}/dialogs/import", json={"tg_chat_ids": []})

    assert res.status_code == 422
    assert engine.calls == []


async def test_import_dialogs_when_account_is_not_connected(authed, engine, ctx):
    account = await add_account(ctx)
    engine.errors["list_dialogs"] = TelegramError(TgErrorCode.NETWORK, "계정이 연결돼 있지 않아요.")

    res = await authed.post(
        f"/api/accounts/{account.id}/dialogs/import", json={"tg_chat_ids": [-1001]}
    )

    assert res.status_code == 503
    assert await all_groups(ctx) == []
