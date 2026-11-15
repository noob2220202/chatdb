"""FastAPI 의존성."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .context import AppContext
from .errors import ApiError
from .models import Admin
from .security import COOKIE_NAME
from .settings_store import RuntimeSettings


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


async def get_session(ctx: Ctx) -> AsyncIterator[AsyncSession]:
    async with ctx.db.session() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]


async def current_admin(request: Request, ctx: AppContext, session: AsyncSession) -> Admin | None:
    """쿠키가 유효하면 관리자를, 아니면 None 을 돌려준다."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    version = ctx.secrets.read_token(token)
    if version is None:
        return None
    admin = (await session.execute(select(Admin).limit(1))).scalar_one_or_none()
    if admin is None or admin.token_version != version:
        return None
    return admin


async def require_admin(request: Request, ctx: Ctx, session: DbSession) -> Admin:
    admin = await current_admin(request, ctx, session)
    if admin is None:
        raise ApiError(401, "로그인이 필요해요.", code="unauthorized")
    return admin


AdminUser = Annotated[Admin, Depends(require_admin)]


async def get_settings(ctx: Ctx) -> RuntimeSettings:
    return await ctx.settings.get()


Settings = Annotated[RuntimeSettings, Depends(get_settings)]
