"""/blocklist 라우터. 수집하지 않을 아이디 목록."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Sequence
from typing import Annotated
from weakref import WeakKeyDictionary

from fastapi import APIRouter, Depends, Path
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Database
from ..deps import Ctx, DbSession, require_admin
from ..errors import bad_request, not_found
from ..models import BlocklistEntry, Lead, LeadStatus
from ..schemas import BlocklistCreate, BlocklistOut, Message

router = APIRouter(prefix="/blocklist", tags=["blocklist"], dependencies=[Depends(require_admin)])

_DB_INT_MAX = 2**63 - 1
EntryId = Annotated[int, Path(ge=-_DB_INT_MAX, le=_DB_INT_MAX)]

_LINK_PREFIX_RE = re.compile(r"^(?:https?://)?(?:www\.)?t\.me/", re.IGNORECASE)
_USERNAME_RE = re.compile(r"[a-z0-9_]{3,32}")

_write_locks: WeakKeyDictionary[Database, asyncio.Lock] = WeakKeyDictionary()


def blocklist_lock(db: Database) -> asyncio.Lock:
    """'이미 있는지 확인 → 추가 → 커밋'을 한 번에 하나씩만 하게 하는 잠금(DB 하나에 하나).

    같은 요청이 겹쳐 들어와도(버튼을 두 번 누른 경우 등) 같은 아이디가 두 번 들어가지 않는다.
    """
    return _write_locks.setdefault(db, asyncio.Lock())


def normalize_username(raw: str) -> str | None:
    """입력 한 줄을 @ 없는 소문자 아이디로 바꾼다. 아이디로 볼 수 없으면 None."""
    text = raw.strip()
    if text.startswith("@"):
        text = text[1:]
    else:
        text = _LINK_PREFIX_RE.sub("", text).rstrip("/")
    name = text.lower()
    return name if _USERNAME_RE.fullmatch(name) else None


async def add_blocked_usernames(
    session: AsyncSession, usernames: Iterable[str], note: str | None = None
) -> list[BlocklistEntry]:
    """제외 목록에 아직 없는 아이디만 넣고, 새로 만든 항목을 돌려준다.

    usernames 는 @ 없는 소문자여야 한다. blocklist_lock 을 쥔 채로 부르고 커밋은 부르는 쪽이 한다.
    """
    names = list(dict.fromkeys(usernames))
    if not names:
        return []
    existing = set(
        await session.scalars(
            select(BlocklistEntry.username).where(BlocklistEntry.username.in_(names))
        )
    )
    created = [BlocklistEntry(username=name, note=note) for name in names if name not in existing]
    session.add_all(created)
    await session.flush()
    return created


async def exclude_leads_by_username(session: AsyncSession, usernames: Sequence[str]) -> None:
    """아이디가 usernames(소문자)에 있는 유저를 제외 상태로 바꾼다. 커밋은 부르는 쪽이 한다."""
    if not usernames:
        return
    await session.execute(
        update(Lead)
        .where(func.lower(Lead.username).in_(usernames), Lead.status != LeadStatus.EXCLUDED)
        .values(status=LeadStatus.EXCLUDED),
        execution_options={"synchronize_session": False},
    )


@router.get("", response_model=list[BlocklistOut])
async def list_blocklist(session: DbSession) -> list[BlocklistOut]:
    rows = await session.scalars(
        select(BlocklistEntry).order_by(BlocklistEntry.created_at.desc(), BlocklistEntry.id.desc())
    )
    return [BlocklistOut.model_validate(entry) for entry in rows]


@router.post("", response_model=list[BlocklistOut])
async def add_to_blocklist(
    body: BlocklistCreate, ctx: Ctx, session: DbSession
) -> list[BlocklistOut]:
    """새로 들어간 항목만 돌려준다. 이미 있던 아이디는 건너뛴다."""
    normalized = (normalize_username(raw) for raw in body.usernames)
    names = list(dict.fromkeys(name for name in normalized if name is not None))
    if not names:
        raise bad_request(
            "넣을 수 있는 아이디가 없어요. 영문·숫자·밑줄로 된 3~32자 아이디를 넣어 주세요.",
            code="no_valid_username",
        )
    note = (body.note or "").strip() or None
    async with blocklist_lock(ctx.db):
        created = await add_blocked_usernames(session, names, note)
        await exclude_leads_by_username(session, names)
        await session.commit()
    ctx.collector.invalidate()
    return [BlocklistOut.model_validate(entry) for entry in created]


@router.delete("/{entry_id}", response_model=Message)
async def remove_from_blocklist(entry_id: EntryId, ctx: Ctx, session: DbSession) -> Message:
    """목록에서만 뺀다. 이미 제외 상태가 된 유저는 그대로 둔다(수집함에서 따로 되돌린다)."""
    entry = await session.get(BlocklistEntry, entry_id)
    if entry is None:
        raise not_found("제외 목록에서 그 아이디를")
    await session.execute(delete(BlocklistEntry).where(BlocklistEntry.id == entry_id))
    await session.commit()
    ctx.collector.invalidate()
    return Message()
