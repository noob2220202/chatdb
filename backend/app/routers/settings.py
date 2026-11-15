"""/settings 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import __version__
from ..context import AppContext
from ..deps import Ctx, Settings, require_admin
from ..errors import bad_request
from ..schemas import SettingsOut, SettingsUpdate
from ..settings_store import RuntimeSettings

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_admin)])

_API_FIELDS = ("tg_api_id", "tg_api_hash")
_API_HASH_MIN_LENGTH = 8


def _settings_out(ctx: AppContext, current: RuntimeSettings) -> SettingsOut:
    return SettingsOut(
        tg_api_id=current.tg_api_id,
        tg_api_hash_set=bool(current.tg_api_hash),
        tg_api_source=current.tg_api_source,
        max_groups_per_account=current.max_groups_per_account,
        join_interval_seconds=current.join_interval_seconds,
        retention_days=current.retention_days,
        store_excerpts=current.store_excerpts,
        timezone=current.timezone,
        demo=ctx.config.demo,
        version=__version__,
    )


@router.get("", response_model=SettingsOut)
async def read_settings(ctx: Ctx, settings: Settings) -> SettingsOut:
    return _settings_out(ctx, settings)


@router.patch("", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate, ctx: Ctx, settings: Settings) -> SettingsOut:
    changes = body.model_dump(exclude_none=True)
    for field in ("tg_api_hash", "timezone"):
        if field in changes:
            changes[field] = changes[field].strip()
    api_hash = changes.get("tg_api_hash")
    if api_hash is not None and len(api_hash) < _API_HASH_MIN_LENGTH:
        raise bad_request("api_hash 값이 너무 짧아요.", code="validation")
    # 한쪽만 저장하면 쓸 수 없는 키가 남는다. 저장된 쌍이 없을 때는 둘을 같이 받아야 한다.
    sent = [field for field in _API_FIELDS if field in changes]
    if len(sent) == 1 and settings.tg_api_source != "settings":
        raise bad_request("api_id 와 api_hash 를 함께 넣어 주세요.", code="api_pair_required")
    if not changes:
        return _settings_out(ctx, settings)
    try:
        updated = await ctx.settings.update(**changes)
    except ValueError as exc:
        raise bad_request(str(exc), code="validation") from exc
    ctx.engine.notify_settings_changed()
    return _settings_out(ctx, updated)


@router.delete("/telegram-api", response_model=SettingsOut)
async def delete_telegram_api(ctx: Ctx) -> SettingsOut:
    """콘솔에 저장한 API 키를 지운다. 환경 변수에 키가 있으면 그 값으로 돌아간다."""
    updated = await ctx.settings.delete(*_API_FIELDS)
    ctx.engine.notify_settings_changed()
    return _settings_out(ctx, updated)
