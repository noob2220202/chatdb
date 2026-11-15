"""모델 → API 응답 변환. 라우터와 엔진(실시간 이벤트)이 같이 쓴다."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Account, EventLog, Group, GroupStatus, Hit, Lead
from .schemas import AccountOut, FeedItem, GroupOut, HitOut, LeadOut, LogOut
from .security import mask_phone
from .settings_store import RuntimeSettings

PENDING_STATUSES = (GroupStatus.QUEUED, GroupStatus.JOINING, GroupStatus.REQUESTED)
OCCUPYING_STATUSES = (*PENDING_STATUSES, GroupStatus.JOINED)
"""계정의 그룹 자리를 차지하는 상태."""


def _full_name(first: str | None, last: str | None) -> str:
    return " ".join(part for part in (first, last) if part).strip()


# --- 계정 -------------------------------------------------------------------


def account_display_name(account: Account) -> str:
    return (
        account.label
        or _full_name(account.first_name, account.last_name)
        or (f"@{account.username}" if account.username else None)
        or mask_phone(account.phone)
        or f"계정 {account.id}"
    )


async def account_outs(
    session: AsyncSession,
    settings: RuntimeSettings,
    account_ids: Sequence[int] | None = None,
) -> list[AccountOut]:
    """계정 목록(만든 순서)."""
    query = select(Account).order_by(Account.id)
    if account_ids is not None:
        query = query.where(Account.id.in_(account_ids))
    accounts = (await session.execute(query)).scalars().all()

    counts: dict[int, dict[str, int]] = {}
    rows = await session.execute(
        select(Group.account_id, Group.status, func.count()).group_by(
            Group.account_id, Group.status
        )
    )
    for account_id, status, n in rows:
        counts.setdefault(account_id, {})[status] = n

    out: list[AccountOut] = []
    for a in accounts:
        by_status = counts.get(a.id, {})
        out.append(
            AccountOut(
                id=a.id,
                label=a.label,
                display_name=account_display_name(a),
                phone_masked=mask_phone(a.phone),
                tg_user_id=a.tg_user_id,
                first_name=a.first_name,
                last_name=a.last_name,
                username=a.username,
                enabled=a.enabled,
                status=a.status,
                status_detail=a.status_detail,
                flood_until=a.flood_until,
                last_connected_at=a.last_connected_at,
                created_at=a.created_at,
                joined_count=by_status.get(GroupStatus.JOINED, 0),
                pending_count=sum(by_status.get(s, 0) for s in PENDING_STATUSES),
                max_groups=settings.max_groups_per_account,
            )
        )
    return out


async def account_out(
    session: AsyncSession, settings: RuntimeSettings, account_id: int
) -> AccountOut | None:
    items = await account_outs(session, settings, [account_id])
    return items[0] if items else None


# --- 그룹 -------------------------------------------------------------------


def group_display_title(group: Group) -> str:
    if group.title:
        return group.title
    if group.public_username:
        return f"@{group.public_username}"
    return group.source_link or f"그룹 {group.id}"


async def group_outs(
    session: AsyncSession,
    *,
    group_ids: Sequence[int] | None = None,
    account_id: int | None = None,
    statuses: Iterable[str] | None = None,
    q: str | None = None,
) -> list[GroupOut]:
    """그룹 목록(최근에 추가한 순)."""
    query = select(Group, Account).join(Account, Account.id == Group.account_id)
    if group_ids is not None:
        query = query.where(Group.id.in_(group_ids))
    if account_id is not None:
        query = query.where(Group.account_id == account_id)
    if statuses:
        query = query.where(Group.status.in_(list(statuses)))
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                Group.title.ilike(like),
                Group.public_username.ilike(like),
                Group.source_link.ilike(like),
            )
        )
    rows = (await session.execute(query.order_by(Group.created_at.desc(), Group.id.desc()))).all()

    ids = [g.id for g, _ in rows]
    lead_counts: dict[int, int] = {}
    if ids:
        counted = await session.execute(
            select(Hit.group_id, func.count(func.distinct(Hit.lead_id)))
            .where(Hit.group_id.in_(ids))
            .group_by(Hit.group_id)
        )
        lead_counts = {gid: n for gid, n in counted}

    return [
        GroupOut(
            id=g.id,
            account_id=g.account_id,
            account_name=account_display_name(a),
            source_link=g.source_link,
            link_kind=g.link_kind,
            public_username=g.public_username,
            tg_chat_id=g.tg_chat_id,
            title=g.title,
            display_title=group_display_title(g),
            kind=g.kind,
            member_count=g.member_count,
            status=g.status,
            status_detail=g.status_detail,
            error_code=g.error_code,
            attempts=g.attempts,
            next_attempt_at=g.next_attempt_at,
            monitoring=g.monitoring,
            messages_seen=g.messages_seen,
            last_message_at=g.last_message_at,
            joined_at=g.joined_at,
            created_at=g.created_at,
            lead_count=lead_counts.get(g.id, 0),
        )
        for g, a in rows
    ]


async def group_out(session: AsyncSession, group_id: int) -> GroupOut | None:
    items = await group_outs(session, group_ids=[group_id])
    return items[0] if items else None


# --- 수집함 -----------------------------------------------------------------


def hit_out(hit: Hit) -> HitOut:
    return HitOut(
        id=hit.id,
        kind=hit.kind,
        rule_id=hit.rule_id,
        rule_name=hit.rule_name,
        group_id=hit.group_id,
        group_title=hit.group_title,
        keywords=list(hit.keywords or []),
        excerpt=hit.excerpt,
        message_count=hit.message_count,
        window_hours=hit.window_hours,
        created_at=hit.created_at,
    )


def lead_display_name(lead: Lead) -> str:
    return _full_name(lead.first_name, lead.last_name) or lead.username


def lead_out(lead: Lead, last_hit: Hit | None) -> LeadOut:
    return LeadOut(
        id=lead.id,
        tg_user_id=lead.tg_user_id,
        username=lead.username,
        first_name=lead.first_name,
        last_name=lead.last_name,
        display_name=lead_display_name(lead),
        status=lead.status,
        note=lead.note,
        hit_count=lead.hit_count,
        first_seen_at=lead.first_seen_at,
        last_seen_at=lead.last_seen_at,
        last_hit=hit_out(last_hit) if last_hit else None,
    )


def feed_item(hit: Hit, lead: Lead, *, is_new_lead: bool) -> FeedItem:
    return FeedItem(
        hit_id=hit.id,
        created_at=hit.created_at,
        kind=hit.kind,
        rule_id=hit.rule_id,
        rule_name=hit.rule_name,
        group_id=hit.group_id,
        group_title=hit.group_title,
        keywords=list(hit.keywords or []),
        excerpt=hit.excerpt,
        message_count=hit.message_count,
        window_hours=hit.window_hours,
        lead_id=lead.id,
        username=lead.username,
        display_name=lead_display_name(lead),
        is_new_lead=is_new_lead,
    )


# --- 활동 기록 --------------------------------------------------------------


def log_out(log: EventLog, account: Account | None, group: Group | None) -> LogOut:
    return LogOut(
        id=log.id,
        level=log.level,
        category=log.category,
        message=log.message,
        account_id=log.account_id,
        account_name=account_display_name(account) if account else None,
        group_id=log.group_id,
        group_title=group_display_title(group) if group else None,
        created_at=log.created_at,
    )
