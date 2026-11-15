"""/groups 라우터. 링크로 가입 대기열에 넣기, 감시 켜고 끄기, 다시 시도, 삭제."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, Literal
from weakref import WeakKeyDictionary

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Database
from ..deps import Ctx, DbSession, Settings, require_admin
from ..errors import conflict, not_found
from ..links import LinkError, LinkTarget, parse_link
from ..models import Account, AccountStatus, Group, GroupStatus, LinkKind, LogCategory
from ..schemas import (
    GroupJoinItem,
    GroupJoinRequest,
    GroupJoinResponse,
    GroupOut,
    GroupUpdate,
    Message,
)
from ..serializers import OCCUPYING_STATUSES, account_display_name, group_out, group_outs

router = APIRouter(prefix="/groups", tags=["groups"], dependencies=[Depends(require_admin)])

_DB_INT_MAX = 2**63 - 1
GroupId = Annotated[int, Path(ge=-_DB_INT_MAX, le=_DB_INT_MAX)]

_SOURCE_LINK_MAX_LENGTH = 300
_UNUSABLE_ACCOUNT_STATUSES = (AccountStatus.REAUTH_REQUIRED, AccountStatus.BANNED)
_RETRYABLE_STATUSES = (GroupStatus.FAILED, GroupStatus.LEFT)

_assignment_locks: WeakKeyDictionary[Database, asyncio.Lock] = WeakKeyDictionary()


def _assignment_lock(db: Database) -> asyncio.Lock:
    """자리·중복 확인부터 저장까지를 한 번에 하나씩만 하게 하는 잠금(DB 하나에 하나).

    같은 요청이 겹쳐 들어와도(버튼을 두 번 누른 경우 등) 같은 그룹이 두 계정에 들어가거나
    계정 한도를 넘기지 않는다.
    """
    return _assignment_locks.setdefault(db, asyncio.Lock())


# ---------------------------------------------------------------------------
# 자리와 중복
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Holder:
    """어떤 그룹을 이미 차지하고 있는 계정."""

    account_id: int
    status: str


@dataclass
class _JoinLine:
    """입력 한 줄의 처리 결과."""

    input: str
    outcome: Literal["queued", "duplicate", "invalid", "no_capacity"]
    reason: str | None = None
    group: Group | None = None


def _dedupe_keys(public_username: str | None, invite_hash: str | None) -> list[str]:
    keys: list[str] = []
    if public_username:
        keys.append(LinkTarget(LinkKind.PUBLIC, public_username).dedupe_key)
    if invite_hash:
        keys.append(LinkTarget(LinkKind.INVITE, invite_hash).dedupe_key)
    return keys


async def _occupancy(session: AsyncSession) -> dict[int, int]:
    """계정별로 자리를 차지하고 있는 그룹 수."""
    rows = await session.execute(
        select(Group.account_id, func.count())
        .where(Group.status.in_(OCCUPYING_STATUSES))
        .group_by(Group.account_id)
    )
    return {account_id: count for account_id, count in rows}


async def _holders(session: AsyncSession) -> dict[str, _Holder]:
    """자리를 차지하고 있는 그룹들을 dedupe_key 로 찾는 표."""
    rows = await session.execute(
        select(Group.public_username, Group.invite_hash, Group.account_id, Group.status)
        .where(Group.status.in_(OCCUPYING_STATUSES))
        .order_by(Group.id)
    )
    holders: dict[str, _Holder] = {}
    for public_username, invite_hash, account_id, status in rows:
        for key in _dedupe_keys(public_username, invite_hash):
            holders.setdefault(key, _Holder(account_id, status))
    return holders


def _is_eligible(account: Account) -> bool:
    """자동 배정을 받을 수 있는 계정인지."""
    return (
        account.enabled
        and account.session_enc is not None
        and account.status not in _UNUSABLE_ACCOUNT_STATUSES
    )


def _pick_account(accounts: Iterable[Account], used: dict[int, int], limit: int) -> Account | None:
    """자리가 남은 계정 중 가장 덜 찬 계정(같으면 id 가 작은 쪽)."""
    open_accounts = [a for a in accounts if _is_eligible(a) and used.get(a.id, 0) < limit]
    return min(open_accounts, key=lambda a: (used.get(a.id, 0), a.id), default=None)


def _full_reason(account: Account, limit: int) -> str:
    return f"{account_display_name(account)} 계정에 남은 자리가 없어요. (계정당 최대 {limit}개)"


def _held_reason(holder: _Holder, accounts: dict[int, Account]) -> str:
    account = accounts.get(holder.account_id)
    name = account_display_name(account) if account else f"계정 {holder.account_id}"
    if holder.status == GroupStatus.JOINED:
        return f"{name} 계정이 이미 들어가 있는 그룹이에요."
    if holder.status == GroupStatus.REQUESTED:
        return f"{name} 계정이 이미 입장 요청을 보낸 그룹이에요."
    return f"{name} 계정의 가입 대기열에 이미 있어요."


def _link_target(group: Group) -> LinkTarget | None:
    """이 행으로 다시 가입할 때 쓸 대상. 링크가 없으면 None."""
    if group.link_kind == LinkKind.INVITE:
        return LinkTarget(LinkKind.INVITE, group.invite_hash) if group.invite_hash else None
    # 공개 링크로 넣은 그룹, 또는 불러온 그룹 중 공개 아이디가 있는 것
    if group.public_username:
        return LinkTarget(LinkKind.PUBLIC, group.public_username)
    return None


async def _get_group(session: AsyncSession, group_id: int) -> Group:
    group = await session.get(Group, group_id)
    if group is None:
        raise not_found("그룹을")
    return group


async def _fresh_group_out(session: AsyncSession, group_id: int) -> GroupOut:
    # 엔진이 자기 세션에서 고친 값이 있을 수 있어 이 세션에 남은 값은 버리고 다시 읽는다.
    session.expire_all()
    out = await group_out(session, group_id)
    if out is None:
        raise not_found("그룹을")
    return out


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.get("", response_model=list[GroupOut])
async def list_groups(
    session: DbSession,
    account_id: Annotated[int | None, Query(ge=-_DB_INT_MAX, le=_DB_INT_MAX)] = None,
    status: Annotated[list[GroupStatus] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[GroupOut]:
    return await group_outs(session, account_id=account_id, statuses=status, q=q)


@router.post("/join", response_model=GroupJoinResponse)
async def join_groups(
    body: GroupJoinRequest, ctx: Ctx, session: DbSession, settings: Settings
) -> GroupJoinResponse:
    limit = settings.max_groups_per_account
    lines: list[_JoinLine] = []
    async with _assignment_lock(ctx.db):
        rows = await session.execute(select(Account).order_by(Account.id))
        accounts = {account.id: account for account in rows.scalars()}
        chosen: Account | None = None
        if body.account_id is not None:
            chosen = accounts.get(body.account_id)
            if chosen is None:
                raise not_found("계정을")
        used = await _occupancy(session)
        holders = await _holders(session)
        seen: set[str] = set()

        for raw in body.links:
            try:
                target = parse_link(raw)
            except LinkError as exc:
                lines.append(_JoinLine(raw, "invalid", str(exc)))
                continue
            key = target.dedupe_key
            if key in seen:
                lines.append(_JoinLine(raw, "duplicate", "같은 링크를 위에서 이미 넣었어요."))
                continue
            seen.add(key)
            holder = holders.get(key)
            if holder is not None:
                lines.append(_JoinLine(raw, "duplicate", _held_reason(holder, accounts)))
                continue

            if chosen is not None:
                account = chosen if used.get(chosen.id, 0) < limit else None
                reason = _full_reason(chosen, limit)
            else:
                account = _pick_account(accounts.values(), used, limit)
                if any(_is_eligible(a) for a in accounts.values()):
                    reason = f"모든 계정이 꽉 찼어요. (계정당 최대 {limit}개)"
                else:
                    reason = "그룹을 넣을 수 있는 계정이 없어요. 계정을 연결하거나 켜 주세요."
            if account is None:
                lines.append(_JoinLine(raw, "no_capacity", reason))
                continue

            used[account.id] = used.get(account.id, 0) + 1
            is_public = target.kind == LinkKind.PUBLIC
            group = Group(
                account_id=account.id,
                source_link=raw.strip()[:_SOURCE_LINK_MAX_LENGTH],
                link_kind=target.kind,
                public_username=target.value if is_public else None,
                invite_hash=None if is_public else target.value,
                status=GroupStatus.QUEUED,
            )
            session.add(group)
            lines.append(_JoinLine(raw, "queued", group=group))

        await session.commit()

    queued = [line.group for line in lines if line.group is not None]
    outs = {out.id: out for out in await group_outs(session, group_ids=[g.id for g in queued])}
    if queued:
        ctx.engine.notify_groups_changed()
        account_ids = {group.account_id for group in queued}
        await ctx.logbook.info(
            f"그룹 {len(queued)}개를 가입 대기열에 넣었어요.",
            category=LogCategory.GROUP,
            account_id=account_ids.pop() if len(account_ids) == 1 else None,
        )
    return GroupJoinResponse(
        items=[
            GroupJoinItem(
                input=line.input,
                outcome=line.outcome,
                reason=line.reason,
                group=outs.get(line.group.id) if line.group is not None else None,
            )
            for line in lines
        ],
        queued=len(queued),
    )


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: GroupId, body: GroupUpdate, ctx: Ctx, session: DbSession
) -> GroupOut:
    group = await _get_group(session, group_id)
    if body.monitoring is not None:
        group.monitoring = body.monitoring
        await session.commit()
        ctx.engine.notify_groups_changed(group.account_id)
    return await _fresh_group_out(session, group_id)


@router.post("/{group_id}/retry", response_model=GroupOut)
async def retry_group(
    group_id: GroupId, ctx: Ctx, session: DbSession, settings: Settings
) -> GroupOut:
    limit = settings.max_groups_per_account
    async with _assignment_lock(ctx.db):
        group = await _get_group(session, group_id)
        if group.status not in _RETRYABLE_STATUSES:
            raise conflict(
                "가입에 실패했거나 나간 그룹만 다시 시도할 수 있어요.", code="not_retryable"
            )
        target = _link_target(group)
        if target is None:
            raise conflict(
                "링크가 없는 그룹이라 다시 가입할 수 없어요. 그룹 링크를 새로 넣어 주세요.",
                code="no_link",
            )
        rows = await session.execute(select(Account))
        accounts = {account.id: account for account in rows.scalars()}
        if (await _occupancy(session)).get(group.account_id, 0) >= limit:
            raise conflict(_full_reason(accounts[group.account_id], limit), code="no_capacity")
        holders = await _holders(session)
        for key in _dedupe_keys(group.public_username, group.invite_hash):
            if key in holders:
                raise conflict(_held_reason(holders[key], accounts), code="duplicate")

        if group.link_kind == LinkKind.EXISTING:
            # 불러온 그룹을 다시 넣는 것은 공개 아이디로 새로 가입하는 것과 같다.
            group.link_kind = LinkKind.PUBLIC
            group.source_link = group.source_link or target.canonical_url
        group.status = GroupStatus.QUEUED
        group.status_detail = None
        group.error_code = None
        group.attempts = 0
        group.next_attempt_at = None
        await session.commit()

    ctx.engine.notify_groups_changed(group.account_id)
    return await _fresh_group_out(session, group_id)


@router.delete("/{group_id}", response_model=Message)
async def delete_group(
    group_id: GroupId, ctx: Ctx, session: DbSession, leave: bool = False
) -> Message:
    group = await _get_group(session, group_id)
    account_id = group.account_id
    if leave:
        await ctx.engine.leave_group(group_id)
    # 엔진이 그사이 행을 고쳤거나 다른 요청이 먼저 지웠어도 어긋나지 않게 id 로 바로 지운다.
    await session.execute(delete(Group).where(Group.id == group_id))
    await session.commit()
    ctx.engine.notify_groups_changed(account_id)
    return Message()
