"""/accounts 라우터. 계정 로그인·세션 불러오기·제어, 이미 들어가 있는 그룹 불러오기."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.types import Message as AsgiMessage

from ..db import utcnow
from ..deps import Ctx, DbSession, Settings, require_admin
from ..errors import ApiError, bad_request, conflict, not_found
from ..models import Account, Group, GroupKind, GroupStatus, LinkKind, LogCategory
from ..schemas import (
    AccountOut,
    AccountUpdate,
    DialogImportRequest,
    DialogOut,
    GroupOut,
    LoginCodeRequest,
    LoginPasswordRequest,
    LoginStartRequest,
    LoginStartResponse,
    LoginStepResponse,
    Message,
    SessionImportRequest,
)
from ..serializers import account_out, account_outs, group_outs
from ..settings_store import RuntimeSettings
from ..telegram.gateway import LoginResult, TgChat

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Depends(require_admin)])

_DB_INT_MAX = 2**63 - 1
AccountId = Annotated[int, Path(ge=-_DB_INT_MAX, le=_DB_INT_MAX)]

MAX_SESSION_FILE_BYTES = 2 * 1024 * 1024
_MULTIPART_OVERHEAD_BYTES = 64 * 1024
"""파일 말고 본문에 더 실리는 것(경계선, 파트 헤더, 별칭)의 여유분."""
_LABEL_MAX_LENGTH = 64

_GONE_STATUSES = (GroupStatus.FAILED, GroupStatus.LEFT)
"""감시 목록에서 빠진 것으로 치는 상태. 같은 그룹을 다시 불러오면 이 행을 되살린다."""
_TITLE_MAX_LENGTH = 255
_CHANNEL_DETAIL = "방송 채널이라 유저 채팅은 수집되지 않아요"
"""엔진이 링크로 채널에 가입했을 때 남기는 설명과 같은 문장."""

_IMPORT_FILE_OPENAPI: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "label": {"type": "string", "maxLength": _LABEL_MAX_LENGTH},
                    },
                }
            }
        },
    }
}


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


async def _get_account(session: AsyncSession, account_id: int) -> Account:
    account = await session.get(Account, account_id)
    if account is None:
        raise not_found("계정을")
    return account


async def _fresh_account_out(
    session: AsyncSession, settings: RuntimeSettings, account_id: int
) -> AccountOut:
    # 엔진은 자기 세션으로 계정을 고친다. 이 세션에 남은 예전 값을 버리고 다시 읽는다.
    session.expire_all()
    out = await account_out(session, settings, account_id)
    if out is None:
        raise not_found("계정을")
    return out


def _clean_label(label: str | None) -> str | None:
    return (label or "").strip() or None


async def _login_step(
    session: AsyncSession,
    settings: RuntimeSettings,
    result: LoginResult,
    account: Account | None,
) -> LoginStepResponse:
    return LoginStepResponse(
        status=result.status,
        account=await _fresh_account_out(session, settings, account.id) if account else None,
        password_hint=result.password_hint,
    )


def _file_too_large() -> ApiError:
    megabytes = MAX_SESSION_FILE_BYTES // (1024 * 1024)
    return ApiError(
        413,
        f"세션 파일이 너무 커요. {megabytes}MB 이하 파일만 올릴 수 있어요.",
        code="file_too_large",
    )


def _capped_request(request: Request, limit: int) -> Request:
    """본문을 limit 바이트까지만 읽는 요청으로 감싼다. 넘으면 413 을 던진다."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _file_too_large()
    received = 0

    async def receive() -> AsgiMessage:
        nonlocal received
        message = await request.receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > limit:
                raise _file_too_large()
        return message

    return Request(request.scope, receive)


async def _read_session_upload(request: Request) -> tuple[bytes, str | None]:
    """멀티파트 본문에서 (세션 파일 내용, 별칭) 을 꺼낸다."""
    capped = _capped_request(request, MAX_SESSION_FILE_BYTES + _MULTIPART_OVERHEAD_BYTES)
    try:
        async with capped.form(max_files=1, max_fields=1) as form:
            upload = form.get("file")
            if not isinstance(upload, UploadFile):
                raise ApiError(422, "세션 파일을 골라 주세요.", code="validation")
            data = await upload.read()
            raw_label = form.get("label")
    except HTTPException as exc:
        raise bad_request(
            "올린 내용을 읽을 수 없어요. 세션 파일을 다시 골라 주세요.", code="bad_upload"
        ) from exc
    if len(data) > MAX_SESSION_FILE_BYTES:
        raise _file_too_large()
    if not data:
        raise bad_request("빈 파일이에요. 세션 파일을 다시 골라 주세요.", code="empty_file")
    label = _clean_label(raw_label if isinstance(raw_label, str) else None)
    if label and len(label) > _LABEL_MAX_LENGTH:
        raise ApiError(422, f"별칭은 {_LABEL_MAX_LENGTH}자까지 쓸 수 있어요.", code="validation")
    return data, label


async def _active_chat_ids(session: AsyncSession, account_id: int) -> set[int]:
    """이 계정의 감시 목록에 살아 있는 그룹들의 tg_chat_id."""
    rows = await session.execute(
        select(Group.tg_chat_id).where(
            Group.account_id == account_id,
            Group.tg_chat_id.is_not(None),
            Group.status.not_in(_GONE_STATUSES),
        )
    )
    return set(rows.scalars())


def _mark_joined(group: Group, chat: TgChat, now: datetime) -> None:
    """불러온 그룹을 '가입됨'으로 채운다. 엔진이 링크로 가입을 마쳤을 때와 같은 모양이다."""
    group.tg_chat_id = chat.id
    group.title = chat.title[:_TITLE_MAX_LENGTH] or group.title
    group.kind = chat.kind
    if chat.member_count is not None:
        group.member_count = chat.member_count
    if chat.username:
        group.public_username = chat.username
    group.status = GroupStatus.JOINED
    group.status_detail = _CHANNEL_DETAIL if chat.kind == GroupKind.CHANNEL else None
    group.error_code = None
    group.attempts = 0
    group.next_attempt_at = None
    group.monitoring = True
    group.joined_at = now


# ---------------------------------------------------------------------------
# 목록 · 로그인 · 세션 불러오기
# ---------------------------------------------------------------------------


@router.get("", response_model=list[AccountOut])
async def list_accounts(session: DbSession, settings: Settings) -> list[AccountOut]:
    return await account_outs(session, settings)


@router.post("/login/start", response_model=LoginStartResponse)
async def login_start(body: LoginStartRequest, ctx: Ctx) -> LoginStartResponse:
    pending = await ctx.engine.start_login(body.phone.strip())
    return LoginStartResponse(
        login_id=pending.login_id,
        phone=pending.phone,
        code_via=pending.code_via,
        expires_at=pending.expires_at,
    )


@router.post("/login/code", response_model=LoginStepResponse)
async def login_code(
    body: LoginCodeRequest, ctx: Ctx, session: DbSession, settings: Settings
) -> LoginStepResponse:
    result, account = await ctx.engine.submit_code(body.login_id, body.code.strip())
    return await _login_step(session, settings, result, account)


@router.post("/login/password", response_model=LoginStepResponse)
async def login_password(
    body: LoginPasswordRequest, ctx: Ctx, session: DbSession, settings: Settings
) -> LoginStepResponse:
    result, account = await ctx.engine.submit_password(body.login_id, body.password)
    return await _login_step(session, settings, result, account)


@router.delete("/login/{login_id}", response_model=Message)
async def login_cancel(login_id: str, ctx: Ctx) -> Message:
    await ctx.engine.cancel_login(login_id)
    return Message()


@router.post("/import", response_model=AccountOut)
async def import_session(
    body: SessionImportRequest, ctx: Ctx, session: DbSession, settings: Settings
) -> AccountOut:
    account = await ctx.engine.import_session(body.session_string.strip(), _clean_label(body.label))
    return await _fresh_account_out(session, settings, account.id)


@router.post("/import-file", response_model=AccountOut, openapi_extra=_IMPORT_FILE_OPENAPI)
async def import_session_file(
    request: Request, ctx: Ctx, session: DbSession, settings: Settings
) -> AccountOut:
    # 본문을 매개변수로 선언하면 FastAPI 가 로그인 확인보다 먼저 파일을 통째로 받아 둔다.
    # 직접 읽어서 로그인 확인 → 크기 제한 → 해석 순서를 지킨다.
    data, label = await _read_session_upload(request)
    account = await ctx.engine.import_session(data, label)
    return await _fresh_account_out(session, settings, account.id)


# ---------------------------------------------------------------------------
# 계정 제어
# ---------------------------------------------------------------------------


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: AccountId, body: AccountUpdate, ctx: Ctx, session: DbSession, settings: Settings
) -> AccountOut:
    account = await _get_account(session, account_id)
    if "label" in body.model_fields_set:
        account.label = _clean_label(body.label)
        await session.commit()
    if body.enabled is not None and body.enabled != account.enabled:
        await ctx.engine.set_account_enabled(account_id, body.enabled)
    return await _fresh_account_out(session, settings, account_id)


@router.post("/{account_id}/reconnect", response_model=AccountOut)
async def reconnect_account(
    account_id: AccountId, ctx: Ctx, session: DbSession, settings: Settings
) -> AccountOut:
    account = await _get_account(session, account_id)
    if not account.enabled:
        raise conflict("꺼져 있는 계정이에요. 먼저 계정을 켜 주세요.", code="account_disabled")
    await ctx.engine.reconnect(account_id)
    return await _fresh_account_out(session, settings, account_id)


@router.delete("/{account_id}", response_model=Message)
async def remove_account(
    account_id: AccountId, ctx: Ctx, session: DbSession, log_out: bool = False
) -> Message:
    await _get_account(session, account_id)
    await ctx.engine.remove_account(account_id, log_out=log_out)
    return Message()


# ---------------------------------------------------------------------------
# 이미 들어가 있는 그룹
# ---------------------------------------------------------------------------


@router.get("/{account_id}/dialogs", response_model=list[DialogOut])
async def list_dialogs(account_id: AccountId, ctx: Ctx, session: DbSession) -> list[DialogOut]:
    await _get_account(session, account_id)
    chats = await ctx.engine.list_dialogs(account_id)
    added = await _active_chat_ids(session, account_id)
    return [
        DialogOut(
            tg_chat_id=chat.id,
            title=chat.title,
            username=chat.username,
            kind=chat.kind,
            member_count=chat.member_count,
            already_added=chat.id in added,
        )
        for chat in chats
    ]


@router.post("/{account_id}/dialogs/import", response_model=list[GroupOut])
async def import_dialogs(
    account_id: AccountId, body: DialogImportRequest, ctx: Ctx, session: DbSession
) -> list[GroupOut]:
    """고른 그룹을 감시 목록에 넣고, 새로 넣었거나 되살린 그룹을 돌려준다."""
    await _get_account(session, account_id)
    # 보낸 id 를 그대로 믿지 않는다. 계정이 지금 실제로 들어가 있는 그룹만 받는다.
    joined = {chat.id: chat for chat in await ctx.engine.list_dialogs(account_id)}
    chats = [joined[chat_id] for chat_id in dict.fromkeys(body.tg_chat_ids) if chat_id in joined]
    if not chats:
        return []

    rows = await session.execute(
        select(Group).where(
            Group.account_id == account_id, Group.tg_chat_id.in_([chat.id for chat in chats])
        )
    )
    existing = {group.tg_chat_id: group for group in rows.scalars()}
    now = utcnow()
    added: list[Group] = []
    for chat in chats:
        group = existing.get(chat.id)
        if group is None:
            group = Group(account_id=account_id, link_kind=LinkKind.EXISTING)
            session.add(group)
        elif group.status not in _GONE_STATUSES:
            continue
        _mark_joined(group, chat, now)
        added.append(group)
    if not added:
        return []
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise conflict(
            "방금 같은 그룹이 추가됐어요. 목록을 새로 고친 뒤 다시 시도해 주세요.",
            code="already_added",
        ) from exc

    ctx.engine.notify_groups_changed(account_id)
    await ctx.logbook.info(
        f"이미 들어가 있던 그룹 {len(added)}개를 감시 목록에 넣었어요.",
        category=LogCategory.GROUP,
        account_id=account_id,
    )
    return await group_outs(session, group_ids=[group.id for group in added])
