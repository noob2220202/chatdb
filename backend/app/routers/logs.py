"""/logs 라우터. 활동 기록 보기와 비우기."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, delete, func, select

from ..deps import DbSession, require_admin
from ..models import Account, EventLog, Group, LogCategory, LogLevel
from ..schemas import LogListResponse, LogOut, Message
from ..serializers import log_out

router = APIRouter(prefix="/logs", tags=["logs"], dependencies=[Depends(require_admin)])

_DB_INT_MAX = 2**63 - 1
MAX_PAGE_SIZE = 200
_MAX_PAGE = 1_000_000


@router.get("", response_model=LogListResponse)
async def list_logs(
    session: DbSession,
    level: LogLevel | None = None,
    category: LogCategory | None = None,
    account_id: Annotated[int | None, Query(ge=-_DB_INT_MAX, le=_DB_INT_MAX)] = None,
    page: Annotated[int, Query(ge=1, le=_MAX_PAGE)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
) -> LogListResponse:
    conditions: list[ColumnElement[bool]] = []
    if level is not None:
        conditions.append(EventLog.level == level)
    if category is not None:
        conditions.append(EventLog.category == category)
    if account_id is not None:
        conditions.append(EventLog.account_id == account_id)

    counted = await session.execute(select(func.count()).select_from(EventLog).where(*conditions))
    total = counted.scalar_one()

    items: list[LogOut] = []
    offset = (page - 1) * page_size
    if offset < total:
        # 계정·그룹 이름까지 한 쿼리로 읽는다(지워진 계정·그룹은 이름 없이 나온다).
        rows = await session.execute(
            select(EventLog, Account, Group)
            .outerjoin(Account, Account.id == EventLog.account_id)
            .outerjoin(Group, Group.id == EventLog.group_id)
            .where(*conditions)
            .order_by(EventLog.created_at.desc(), EventLog.id.desc())
            .limit(page_size)
            .offset(offset)
        )
        items = [log_out(log, account, group) for log, account, group in rows]
    return LogListResponse(items=items, total=total, page=page, page_size=page_size)


@router.delete("", response_model=Message)
async def clear_logs(session: DbSession) -> Message:
    await session.execute(delete(EventLog))
    await session.commit()
    return Message()
