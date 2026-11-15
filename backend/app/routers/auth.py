"""/auth 라우터. 관리자 한 명의 비밀번호 설정·로그인·로그아웃."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..context import AppContext
from ..deps import AdminUser, Ctx, DbSession, current_admin
from ..errors import ApiError, bad_request, conflict
from ..models import Admin
from ..schemas import AuthStatus, LoginRequest, Message, PasswordChangeRequest, SetupRequest
from ..security import COOKIE_NAME, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

_ADMIN_ID = 1
"""관리자 행의 고정 id. 동시에 두 번 설정해도 기본 키 충돌로 하나만 남는다."""


async def _find_admin(session: AsyncSession) -> Admin | None:
    return (await session.execute(select(Admin).limit(1))).scalar_one_or_none()


def _client_key(request: Request) -> str:
    """로그인 제한을 거는 단위. 프록시 헤더는 속일 수 있어서 실제 접속 주소만 본다."""
    return request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")


def _issue_cookie(response: Response, ctx: AppContext, token_version: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        ctx.secrets.issue_token(token_version),
        max_age=ctx.config.session_max_age_days * 86400,
        path="/",
        secure=ctx.config.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _already_setup() -> ApiError:
    return conflict("이미 관리자 비밀번호가 있어요. 로그인해 주세요.", code="already_setup")


def _wait_text(seconds: int) -> str:
    return f"{seconds}초" if seconds < 60 else f"{-(-seconds // 60)}분"


def _ensure_not_locked(ctx: AppContext, key: str) -> None:
    retry_after = ctx.throttle.retry_after(key)
    if retry_after:
        raise ApiError(
            429,
            f"비밀번호를 여러 번 틀렸어요. {_wait_text(retry_after)} 뒤에 다시 시도해 주세요.",
            code="too_many_attempts",
            retry_after=retry_after,
        )


async def _check_password(ctx: AppContext, key: str, admin: Admin, password: str) -> bool:
    """비밀번호를 확인하고 실패 횟수를 관리한다. 잠겨 있으면 429 를 던진다.

    해시 검증은 스레드에서 돌기 때문에, 한꺼번에 몰려온 요청이 한도를 넘겨 시도하지 못하도록
    검증하기 전에 먼저 한 번으로 세어 둔다. 맞으면 기록을 지운다.
    """
    _ensure_not_locked(ctx, key)
    ctx.throttle.record_failure(key)
    is_last_chance = ctx.throttle.retry_after(key) > 0
    if await asyncio.to_thread(verify_password, admin.password_hash, password):
        ctx.throttle.reset(key)
        return True
    if is_last_chance:
        await ctx.logbook.warning(
            f"비밀번호를 {ctx.throttle.limit}번 틀려서 {key} 에서 오는 로그인을 "
            f"{_wait_text(ctx.throttle.window)} 동안 막았어요."
        )
    return False


@router.get("/status", response_model=AuthStatus)
async def auth_status(request: Request, ctx: Ctx, session: DbSession) -> AuthStatus:
    setup_required = await _find_admin(session) is None
    authenticated = not setup_required and await current_admin(request, ctx, session) is not None
    return AuthStatus(
        setup_required=setup_required, authenticated=authenticated, demo=ctx.config.demo
    )


@router.post("/setup", response_model=AuthStatus)
async def setup(body: SetupRequest, response: Response, ctx: Ctx, session: DbSession) -> AuthStatus:
    if await _find_admin(session) is not None:
        raise _already_setup()
    admin = Admin(
        id=_ADMIN_ID,
        password_hash=await asyncio.to_thread(hash_password, body.password),
        token_version=1,
    )
    session.add(admin)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _already_setup() from exc
    _issue_cookie(response, ctx, admin.token_version)
    return AuthStatus(setup_required=False, authenticated=True, demo=ctx.config.demo)


@router.post("/login", response_model=AuthStatus)
async def login(
    body: LoginRequest, request: Request, response: Response, ctx: Ctx, session: DbSession
) -> AuthStatus:
    admin = await _find_admin(session)
    if admin is None:
        raise conflict("아직 관리자 비밀번호를 만들지 않았어요.", code="setup_required")
    if not await _check_password(ctx, _client_key(request), admin, body.password):
        raise ApiError(401, "비밀번호가 맞지 않아요.", code="wrong_password")
    _issue_cookie(response, ctx, admin.token_version)
    return AuthStatus(setup_required=False, authenticated=True, demo=ctx.config.demo)


@router.post("/logout", response_model=Message)
async def logout(response: Response, ctx: Ctx) -> Message:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=ctx.config.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return Message()


@router.post("/password", response_model=Message)
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    ctx: Ctx,
    session: DbSession,
    admin: AdminUser,
) -> Message:
    # 로그인된 쿠키만으로 비밀번호를 무한정 대입해 볼 수 없도록 로그인과 같은 제한을 건다.
    if not await _check_password(ctx, _client_key(request), admin, body.current_password):
        raise bad_request("현재 비밀번호가 맞지 않아요.", code="wrong_password")
    if body.new_password == body.current_password:
        raise bad_request("새 비밀번호가 현재 비밀번호와 같아요.", code="same_password")
    admin.password_hash = await asyncio.to_thread(hash_password, body.new_password)
    admin.token_version += 1
    await session.commit()
    # 버전을 올렸으니 다른 기기의 쿠키는 모두 무효다. 이 요청을 보낸 쪽만 새로 발급한다.
    _issue_cookie(response, ctx, admin.token_version)
    await ctx.logbook.info("관리자 비밀번호를 바꿨어요. 다른 기기에서는 다시 로그인해야 해요.")
    return Message()
