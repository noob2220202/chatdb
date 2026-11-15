"""/overview 라우터. 대시보드가 주기적으로 읽어 가는 요약."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..db import utcnow
from ..deps import DbSession, Settings, require_admin
from ..models import AccountStatus, Group, GroupStatus, Hit, Lead, Rule, RuleKind
from ..schemas import DayPoint, FeedItem, OverviewOut, RuleTotal, TopGroup
from ..serializers import account_outs, feed_item, group_display_title

router = APIRouter(prefix="/overview", tags=["overview"], dependencies=[Depends(require_admin)])

MIN_DAYS = 1
MAX_DAYS = 90
DEFAULT_DAYS = 7
TOP_GROUPS_LIMIT = 5
RECENT_HITS_LIMIT = 20

_CONNECTED_STATUSES = (AccountStatus.ACTIVE, AccountStatus.FLOOD_WAIT)
_QUEUE_STATUSES = (GroupStatus.QUEUED, GroupStatus.JOINING)


def _day_starts(today: date, days: int, tz: ZoneInfo) -> list[datetime]:
    """오늘로 끝나는 days 일의 각 날짜가 시작하는 시각과, 내일이 시작하는 시각(UTC). 길이는 days + 1."""
    first = today - timedelta(days=days - 1)
    return [
        datetime.combine(first + timedelta(days=offset), time.min, tz).astimezone(UTC)
        for offset in range(days + 1)
    ]


async def _new_leads_by_day(
    session: AsyncSession, today: date, days: int, tz: ZoneInfo
) -> list[DayPoint]:
    """날짜별로 처음 수집된 유저 수(오래된 날부터, 빈 날은 0). days 는 2 이상이어야 한다."""
    starts = _day_starts(today, days, tz)
    last = days - 1
    # 날짜 경계가 시간대마다 달라서 DB 의 날짜 함수 대신 경계 시각과 비교해 며칠째인지 정한다.
    day_index = case(
        *((Lead.first_seen_at < starts[index + 1], index) for index in range(last)), else_=last
    )
    recent = (
        select(day_index.label("day_index"), Lead.first_kind.label("kind"))
        .where(Lead.first_seen_at >= starts[0], Lead.first_seen_at < starts[-1])
        .subquery()
    )
    rows = await session.execute(
        select(recent.c.day_index, recent.c.kind, func.count()).group_by(
            recent.c.day_index, recent.c.kind
        )
    )
    counts: list[dict[str, int]] = [
        {RuleKind.KEYWORD: 0, RuleKind.ACTIVITY: 0} for _ in range(days)
    ]
    for index, kind, count in rows:
        if kind in counts[index]:
            counts[index][kind] = count
    first = today - timedelta(days=last)
    return [
        DayPoint(
            date=(first + timedelta(days=index)).isoformat(),
            keyword=by_kind[RuleKind.KEYWORD],
            activity=by_kind[RuleKind.ACTIVITY],
        )
        for index, by_kind in enumerate(counts)
    ]


async def _top_groups(session: AsyncSession) -> list[TopGroup]:
    per_group = (
        select(
            Hit.group_id.label("group_id"),
            func.count(func.distinct(Hit.lead_id)).label("leads"),
        )
        .where(Hit.group_id.is_not(None))
        .group_by(Hit.group_id)
        .subquery()
    )
    rows = await session.execute(
        select(Group, per_group.c.leads)
        .join(per_group, per_group.c.group_id == Group.id)
        .order_by(per_group.c.leads.desc(), Group.id)
        .limit(TOP_GROUPS_LIMIT)
    )
    return [
        TopGroup(group_id=group.id, title=group_display_title(group), leads=leads)
        for group, leads in rows
    ]


async def _rule_totals(session: AsyncSession) -> list[RuleTotal]:
    per_rule = (
        select(
            Hit.rule_id.label("rule_id"),
            func.count(func.distinct(Hit.lead_id)).label("leads"),
        )
        .where(Hit.rule_id.is_not(None))
        .group_by(Hit.rule_id)
        .subquery()
    )
    leads = func.coalesce(per_rule.c.leads, 0)
    # 규칙의 적용 그룹까지 읽지 않도록 필요한 열만 고른다.
    rows = await session.execute(
        select(Rule.id, Rule.name, Rule.kind, Rule.enabled, leads)
        .outerjoin(per_rule, per_rule.c.rule_id == Rule.id)
        .order_by(leads.desc(), Rule.id)
    )
    return [
        RuleTotal(rule_id=rule_id, name=name, kind=kind, enabled=enabled, leads=count)
        for rule_id, name, kind, enabled, count in rows
    ]


async def _recent_hits(session: AsyncSession) -> list[FeedItem]:
    earlier = aliased(Hit)
    has_earlier = exists().where(
        earlier.lead_id == Hit.lead_id,
        or_(
            earlier.created_at < Hit.created_at,
            and_(earlier.created_at == Hit.created_at, earlier.id < Hit.id),
        ),
    )
    rows = await session.execute(
        select(Hit, Lead, has_earlier.label("has_earlier"))
        .join(Lead, Lead.id == Hit.lead_id)
        .order_by(Hit.created_at.desc(), Hit.id.desc())
        .limit(RECENT_HITS_LIMIT)
    )
    return [feed_item(hit, lead, is_new_lead=not has_earlier) for hit, lead, has_earlier in rows]


@router.get("", response_model=OverviewOut)
async def read_overview(
    session: DbSession, settings: Settings, days: int = DEFAULT_DAYS
) -> OverviewOut:
    days = max(MIN_DAYS, min(MAX_DAYS, days))
    tz = settings.tzinfo
    today = utcnow().astimezone(tz).date()

    # 어제 수치가 필요해서 최소 이틀을 세고, 응답에는 요청한 날 수만 담는다.
    by_day = await _new_leads_by_day(session, today, max(days, 2), tz)
    today_point, yesterday_point = by_day[-1], by_day[-2]

    total_leads = (await session.execute(select(func.count()).select_from(Lead))).scalar_one()
    accounts = await account_outs(session, settings)

    groups_monitoring = join_requests_pending = join_queue = 0
    group_rows = await session.execute(
        select(Group.status, Group.monitoring, func.count()).group_by(
            Group.status, Group.monitoring
        )
    )
    for status, monitoring, count in group_rows:
        if status == GroupStatus.JOINED and monitoring:
            groups_monitoring += count
        elif status == GroupStatus.REQUESTED:
            join_requests_pending += count
        elif status in _QUEUE_STATUSES:
            join_queue += count

    return OverviewOut(
        today_new=today_point.keyword + today_point.activity,
        yesterday_new=yesterday_point.keyword + yesterday_point.activity,
        total_leads=total_leads,
        accounts_connected=sum(1 for a in accounts if a.status in _CONNECTED_STATUSES),
        accounts_total=len(accounts),
        groups_monitoring=groups_monitoring,
        groups_capacity=len(accounts) * settings.max_groups_per_account,
        join_requests_pending=join_requests_pending,
        join_queue=join_queue,
        series=by_day[-days:],
        top_groups=await _top_groups(session),
        rule_totals=await _rule_totals(session),
        accounts=accounts,
        recent_hits=await _recent_hits(session),
    )
