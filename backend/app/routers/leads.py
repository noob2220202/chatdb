"""/leads 라우터. 수집함 목록·내보내기·상태 변경·삭제."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response
from sqlalchemy import ColumnElement, Row, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..db import utcnow
from ..deps import Ctx, DbSession, Settings, require_admin
from ..errors import ApiError, not_found
from ..models import Hit, Lead, LeadStatus, RuleKind
from ..schemas import (
    BulkResult,
    LeadBulkRequest,
    LeadDetail,
    LeadListResponse,
    LeadOut,
    LeadUpdate,
    Message,
)
from ..serializers import hit_out, lead_out
from .blocklist import add_blocked_usernames, blocklist_lock

router = APIRouter(prefix="/leads", tags=["leads"], dependencies=[Depends(require_admin)])

_DB_INT_MAX = 2**63 - 1
LeadId = Annotated[int, Path(ge=-_DB_INT_MAX, le=_DB_INT_MAX)]
_RefId = Annotated[int | None, Query(ge=-_DB_INT_MAX, le=_DB_INT_MAX)]

SortKey = Literal["last_seen", "first_seen", "hit_count", "username"]
SortOrder = Literal["asc", "desc"]

MAX_PAGE_SIZE = 200
_MAX_PAGE = 1_000_000
DETAIL_HITS_LIMIT = 100
EXPORT_IDS_LIMIT = 5000
"""골라서 내보낼 수 있는 최대 인원(일괄 처리 한도와 같다)."""
_EXPORT_CHUNK = 1000
"""내보낼 때 DB 에서 한 번에 읽어 오는 행 수."""

_SEARCH_COLUMNS = (Lead.username, Lead.first_name, Lead.last_name, Lead.note)
_SORT_COLUMNS: dict[str, ColumnElement[Any]] = {
    "last_seen": Lead.last_seen_at,
    "first_seen": Lead.first_seen_at,
    "hit_count": Lead.hit_count,
    "username": func.lower(Lead.username),
}

STATUS_LABELS: dict[str, str] = {
    LeadStatus.NEW: "새로 수집됨",
    LeadStatus.REVIEWED: "확인함",
    LeadStatus.CONTACTED: "연락함",
    LeadStatus.EXCLUDED: "제외",
}
CSV_HEADER = (
    "아이디", "이름", "상태", "감지 횟수", "처음 감지", "마지막 감지",
    "최근 규칙", "최근 그룹", "최근 내용", "메모",
)  # fmt: skip
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_DATE_ONLY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_BOUND_DESCRIPTION = (
    "마지막 감지 시각 기준. 날짜(YYYY-MM-DD)나 ISO 8601 시각을 받는다. "
    "시간대가 없으면 설정된 시간대로 보고, 날짜만 주면 그날 하루 전체를 포함한다."
)


def _invalid(detail: str) -> ApiError:
    """형식 검증(422)과 같은 모양의 오류. 스키마만으로는 걸러지지 않는 값에 쓴다."""
    return ApiError(422, detail, code="validation")


# ---------------------------------------------------------------------------
# 목록 조건
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LeadQuery:
    """목록과 내보내기가 같이 쓰는 필터와 정렬."""

    terms: tuple[str, ...]
    statuses: tuple[LeadStatus, ...]
    rule_id: int | None
    group_id: int | None
    kind: RuleKind | None
    since: datetime | None
    until: datetime | None
    sort: SortKey
    order: SortOrder

    def conditions(self, *, with_status: bool = True) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = [
            # 낱말마다 아이디·이름·메모 중 어딘가에 들어 있어야 한다.
            or_(*(column.icontains(term, autoescape=True) for column in _SEARCH_COLUMNS))
            for term in self.terms
        ]
        if with_status and self.statuses:
            found.append(Lead.status.in_(self.statuses))
        # 규칙·그룹·종류는 같은 감지 한 건이 모두 만족해야 한다.
        hit_conditions: list[ColumnElement[bool]] = []
        if self.rule_id is not None:
            hit_conditions.append(Hit.rule_id == self.rule_id)
        if self.group_id is not None:
            hit_conditions.append(Hit.group_id == self.group_id)
        if self.kind is not None:
            hit_conditions.append(Hit.kind == self.kind)
        if hit_conditions:
            found.append(Lead.id.in_(select(Hit.lead_id).where(*hit_conditions)))
        if self.since is not None:
            found.append(Lead.last_seen_at >= self.since)
        if self.until is not None:
            found.append(Lead.last_seen_at <= self.until)
        return found

    def ordering(self) -> list[ColumnElement[Any]]:
        column = _SORT_COLUMNS[self.sort]
        if self.order == "asc":
            return [column.asc(), Lead.id.asc()]
        return [column.desc(), Lead.id.desc()]


def _search_terms(q: str | None) -> tuple[str, ...]:
    """검색어를 낱말로 나눈다. 낱말 앞의 @ 는 뗀다."""
    words = (word.lstrip("@") for word in (q or "").split())
    return tuple(word for word in words if word)


def _parse_bound(raw: str | None, tz: ZoneInfo, *, end_of_day: bool) -> datetime | None:
    """since/until 값을 UTC 시각으로 읽는다. 비어 있으면 None.

    날짜만 오면 설정된 시간대의 그날 0시(end_of_day 면 그날의 마지막 순간)다.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        if _DATE_ONLY_RE.fullmatch(text):
            day = date.fromisoformat(text)
            if end_of_day:
                next_midnight = datetime.combine(day + timedelta(days=1), time.min, tz)
                moment = next_midnight - timedelta(microseconds=1)
            else:
                moment = datetime.combine(day, time.min, tz)
        else:
            moment = datetime.fromisoformat(text)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=tz)
        return moment.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise _invalid("날짜 형식을 다시 확인해 주세요.") from exc


def _lead_query(
    settings: Settings,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[list[LeadStatus] | None, Query()] = None,
    rule_id: _RefId = None,
    group_id: _RefId = None,
    kind: RuleKind | None = None,
    since: Annotated[str | None, Query(max_length=40, description=_BOUND_DESCRIPTION)] = None,
    until: Annotated[str | None, Query(max_length=40, description=_BOUND_DESCRIPTION)] = None,
    sort: SortKey = "last_seen",
    order: SortOrder = "desc",
) -> _LeadQuery:
    tz = settings.tzinfo
    return _LeadQuery(
        terms=_search_terms(q),
        statuses=tuple(dict.fromkeys(status or ())),
        rule_id=rule_id,
        group_id=group_id,
        kind=kind,
        since=_parse_bound(since, tz, end_of_day=False),
        until=_parse_bound(until, tz, end_of_day=True),
        sort=sort,
        order=order,
    )


LeadQuery = Annotated[_LeadQuery, Depends(_lead_query)]


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


async def _get_lead(session: AsyncSession, lead_id: int) -> Lead:
    lead = await session.get(Lead, lead_id)
    if lead is None:
        raise not_found("수집된 유저를")
    return lead


async def _lead_outs(session: AsyncSession, leads: Sequence[Lead]) -> list[LeadOut]:
    """유저들의 가장 최근 감지를 한 번에 읽어 붙인다.

    last_hit_id 가 가리키는 감지가 보관 기간이 지나 지워졌으면 last_hit 은 비어 있다.
    """
    hit_ids = [lead.last_hit_id for lead in leads if lead.last_hit_id is not None]
    last_hits: dict[int | None, Hit] = {}
    if hit_ids:
        rows = await session.scalars(select(Hit).where(Hit.id.in_(hit_ids)))
        last_hits = {hit.id: hit for hit in rows}
    return [lead_out(lead, last_hits.get(lead.last_hit_id)) for lead in leads]


async def _single_lead_out(session: AsyncSession, lead: Lead) -> LeadOut:
    # 이 세션이 이미 읽은 감지라면 다시 조회하지 않는다.
    last_hit = await session.get(Hit, lead.last_hit_id) if lead.last_hit_id is not None else None
    return lead_out(lead, last_hit)


async def _fresh_lead_out(session: AsyncSession, lead_id: int) -> LeadOut:
    # 수집기가 자기 세션에서 고친 값(감지 횟수 등)이 있을 수 있어 다시 읽는다.
    rows = await session.execute(
        select(Lead).where(Lead.id == lead_id).execution_options(populate_existing=True)
    )
    lead = rows.scalar_one_or_none()
    if lead is None:
        raise not_found("수집된 유저를")
    return await _single_lead_out(session, lead)


# ---------------------------------------------------------------------------
# 내보내기
# ---------------------------------------------------------------------------


def _parse_ids(raw: str) -> list[int]:
    """'1,2,3' 을 id 목록으로 읽는다."""
    parts = [part.strip() for part in raw.split(",")]
    parts = [part for part in parts if part]
    if not parts:
        raise _invalid("내보낼 유저를 골라 주세요.")
    if len(parts) > EXPORT_IDS_LIMIT:
        raise _invalid(f"한 번에 {EXPORT_IDS_LIMIT:,}명까지 골라서 내보낼 수 있어요.")
    if not all(part.isascii() and part.isdigit() for part in parts):
        raise _invalid("내보낼 유저 번호를 다시 확인해 주세요.")
    ids = list(dict.fromkeys(int(part) for part in parts))
    if any(lead_id > _DB_INT_MAX for lead_id in ids):
        raise _invalid("내보낼 유저 번호를 다시 확인해 주세요.")
    return ids


def _text_cell(value: str | None) -> str:
    """스프레드시트가 수식으로 읽지 않게 한다. 위험한 글자로 시작하면 앞에 ' 를 붙인다."""
    if not value:
        return ""
    return f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value


def _local_minute(value: datetime, tz: ZoneInfo) -> str:
    return value.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _last_hit_content(row: Row[Any]) -> str:
    """가장 최근 감지의 내용: 키워드 감지는 문장 발췌(없으면 걸린 키워드), 활동량 감지는 메시지 수."""
    if row.kind is None:
        return ""
    if row.kind == RuleKind.ACTIVITY:
        if row.message_count is None or row.window_hours is None:
            return ""
        return f"{row.window_hours}시간 동안 메시지 {row.message_count}개"
    return row.excerpt or ", ".join(row.keywords or [])


def _csv_row(row: Row[Any], tz: ZoneInfo) -> list[str | int]:
    name = " ".join(part for part in (row.first_name, row.last_name) if part)
    return [
        _text_cell(row.username),
        _text_cell(name),
        STATUS_LABELS.get(row.status, row.status),
        row.hit_count,
        _local_minute(row.first_seen_at, tz),
        _local_minute(row.last_seen_at, tz),
        _text_cell(row.rule_name),
        _text_cell(row.group_title),
        _text_cell(_last_hit_content(row)),
        _text_cell(row.note),
    ]


async def _csv_bytes(
    session: AsyncSession,
    conditions: Sequence[ColumnElement[bool]],
    ordering: Sequence[ColumnElement[Any]],
    tz: ZoneInfo,
) -> bytes:
    """BOM 이 붙은 UTF-8 CSV. 유저와 최근 감지를 한 쿼리로 읽어 조금씩 써 내려간다."""
    # 조건 안의 감지 필터(hits)와 이름이 겹치지 않게 최근 감지에는 별칭을 준다.
    last_hit = aliased(Hit, name="last_hit")
    statement = (
        select(
            Lead.username,
            Lead.first_name,
            Lead.last_name,
            Lead.status,
            Lead.hit_count,
            Lead.first_seen_at,
            Lead.last_seen_at,
            Lead.note,
            last_hit.kind,
            last_hit.rule_name,
            last_hit.group_title,
            last_hit.excerpt,
            last_hit.keywords,
            last_hit.message_count,
            last_hit.window_hours,
        )
        .outerjoin(last_hit, last_hit.id == Lead.last_hit_id)
        .where(*conditions)
        .order_by(*ordering)
    )
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    result = await session.stream(statement)
    async for chunk in result.partitions(_EXPORT_CHUNK):
        writer.writerows(_csv_row(row, tz) for row in chunk)
    return buffer.getvalue().encode("utf-8-sig")


async def _txt_bytes(
    session: AsyncSession,
    conditions: Sequence[ColumnElement[bool]],
    ordering: Sequence[ColumnElement[Any]],
) -> bytes:
    """한 줄에 '@아이디' 하나."""
    statement = select(Lead.username).where(*conditions, Lead.username != "").order_by(*ordering)
    lines: list[str] = []
    result = await session.stream_scalars(statement)
    async for chunk in result.partitions(_EXPORT_CHUNK):
        lines.extend(f"@{username}\n" for username in chunk)
    return "".join(lines).encode()


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.get("", response_model=LeadListResponse)
async def list_leads(
    session: DbSession,
    query: LeadQuery,
    page: Annotated[int, Query(ge=1, le=_MAX_PAGE)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
) -> LeadListResponse:
    counted = await session.execute(
        select(Lead.status, func.count())
        .where(*query.conditions(with_status=False))
        .group_by(Lead.status)
    )
    status_counts = {status.value: 0 for status in LeadStatus}
    for status, count in counted:
        if status in status_counts:
            status_counts[status] = count
    selected = query.statuses or tuple(LeadStatus)
    total = sum(status_counts[status] for status in selected)

    leads: Sequence[Lead] = []
    offset = (page - 1) * page_size
    if offset < total:
        rows = await session.scalars(
            select(Lead)
            .where(*query.conditions())
            .order_by(*query.ordering())
            .limit(page_size)
            .offset(offset)
        )
        leads = rows.all()
    return LeadListResponse(
        items=await _lead_outs(session, leads),
        total=total,
        page=page,
        page_size=page_size,
        status_counts=status_counts,
    )


@router.get(
    "/export",
    response_class=Response,
    responses={
        200: {
            "description": "수집함을 파일로 내려받는다.",
            "content": {
                "text/csv": {"schema": {"type": "string"}},
                "text/plain": {"schema": {"type": "string"}},
            },
        }
    },
)
async def export_leads(
    session: DbSession,
    settings: Settings,
    query: LeadQuery,
    file_format: Annotated[Literal["csv", "txt"], Query(alias="format")] = "csv",
    ids: Annotated[
        str | None, Query(description="쉼표로 이은 유저 id. 주면 다른 필터는 보지 않는다.")
    ] = None,
) -> Response:
    tz = settings.tzinfo
    conditions = [Lead.id.in_(_parse_ids(ids))] if ids is not None else query.conditions()
    if file_format == "csv":
        content = await _csv_bytes(session, conditions, query.ordering(), tz)
        media_type = "text/csv; charset=utf-8"
    else:
        content = await _txt_bytes(session, conditions, query.ordering())
        media_type = "text/plain; charset=utf-8"
    stamp = utcnow().astimezone(tz).strftime("%Y%m%d-%H%M")
    filename = f"chatdb-leads-{stamp}.{file_format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{lead_id}", response_model=LeadDetail)
async def read_lead(lead_id: LeadId, session: DbSession) -> LeadDetail:
    lead = await _get_lead(session, lead_id)
    hits = (
        await session.scalars(
            select(Hit)
            .where(Hit.lead_id == lead.id)
            .order_by(Hit.created_at.desc(), Hit.id.desc())
            .limit(DETAIL_HITS_LIMIT)
        )
    ).all()
    titles = await session.scalars(
        select(Hit.group_title)
        .where(Hit.lead_id == lead.id, Hit.group_title.is_not(None), Hit.group_title != "")
        .group_by(Hit.group_title)
        .order_by(func.max(Hit.created_at).desc(), func.max(Hit.id).desc())
    )
    base = await _single_lead_out(session, lead)
    return LeadDetail(
        **base.model_dump(),
        hits=[hit_out(hit) for hit in hits],
        group_titles=list(titles),
    )


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(lead_id: LeadId, body: LeadUpdate, ctx: Ctx, session: DbSession) -> LeadOut:
    lead = await _get_lead(session, lead_id)
    sent = body.model_fields_set
    exclusion_changed = False
    if "status" in sent and body.status is not None and body.status != lead.status:
        exclusion_changed = LeadStatus.EXCLUDED in (body.status, lead.status)
        lead.status = body.status
    if "note" in sent:
        lead.note = (body.note or "").strip() or None
    await session.commit()
    if exclusion_changed:
        ctx.collector.invalidate()
    return await _fresh_lead_out(session, lead_id)


@router.post("/bulk", response_model=BulkResult)
async def bulk_leads(body: LeadBulkRequest, ctx: Ctx, session: DbSession) -> BulkResult:
    """고른 유저들을 한꺼번에 처리한다. affected 는 실제로 있던 유저 수다."""
    wanted = sorted({lead_id for lead_id in body.ids if 0 < lead_id <= _DB_INT_MAX})
    if not wanted:
        return BulkResult(affected=0)
    rows = (
        await session.execute(
            select(Lead.id, Lead.username, Lead.status).where(Lead.id.in_(wanted)).order_by(Lead.id)
        )
    ).all()
    if not rows:
        return BulkResult(affected=0)
    selected = Lead.id.in_([row.id for row in rows])
    no_sync = {"synchronize_session": False}

    if body.action == "delete":
        await session.execute(delete(Lead).where(selected), execution_options=no_sync)
        await session.commit()
        collector_stale = True
    elif body.action == "block":
        usernames = [row.username.strip().lower() for row in rows if row.username.strip()]
        async with blocklist_lock(ctx.db):
            await add_blocked_usernames(session, usernames)
            await session.execute(
                update(Lead).where(selected).values(status=LeadStatus.EXCLUDED),
                execution_options=no_sync,
            )
            await session.commit()
        collector_stale = True
    else:
        becomes_excluded = body.status == LeadStatus.EXCLUDED
        await session.execute(
            update(Lead).where(selected).values(status=body.status), execution_options=no_sync
        )
        await session.commit()
        # 제외 상태로 들어가거나 나온 유저가 있을 때만 수집기 캐시를 버린다.
        collector_stale = any(
            (row.status == LeadStatus.EXCLUDED) != becomes_excluded for row in rows
        )

    if collector_stale:
        ctx.collector.invalidate()
    return BulkResult(affected=len(rows))


@router.delete("/{lead_id}", response_model=Message)
async def delete_lead(lead_id: LeadId, ctx: Ctx, session: DbSession) -> Message:
    await _get_lead(session, lead_id)
    # 감지 기록은 함께 지워진다. 다른 요청이 먼저 지웠어도 어긋나지 않게 id 로 바로 지운다.
    await session.execute(delete(Lead).where(Lead.id == lead_id))
    await session.commit()
    ctx.collector.invalidate()
    return Message()
