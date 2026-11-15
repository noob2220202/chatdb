"""/rules 라우터. 수집 규칙 만들기·고치기·지우기."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import utcnow
from ..deps import Ctx, DbSession, require_admin
from ..errors import bad_request, not_found
from ..models import Group, Hit, Rule, RuleKind
from ..schemas import Message, RuleCreate, RuleOut, RuleUpdate

router = APIRouter(prefix="/rules", tags=["rules"], dependencies=[Depends(require_admin)])

_DB_INT_MAX = 2**63 - 1
RuleId = Annotated[int, Path(ge=-_DB_INT_MAX, le=_DB_INT_MAX)]

_REQUIRED_FIELDS = ("enabled", "keywords", "exclude_keywords", "match_mode", "all_groups")
"""비워 둘 수 없는 값. PATCH 에서 null 로 오면 바꾸지 않는다."""
_NULLABLE_FIELDS = ("min_messages", "window_hours")
"""비울 수 있는 값. PATCH 에서 null 로 오면 비운다."""


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


async def _get_rule(session: AsyncSession, rule_id: int) -> Rule:
    rule = await session.get(Rule, rule_id)
    if rule is None:
        raise not_found("규칙을")
    return rule


async def _load_groups(session: AsyncSession, group_ids: Sequence[int]) -> list[Group]:
    """group_ids 가 가리키는 그룹들. 하나라도 없으면 400."""
    wanted = list(dict.fromkeys(group_ids))
    if not wanted:
        return []
    storable = [group_id for group_id in wanted if 0 < group_id <= _DB_INT_MAX]
    groups: list[Group] = []
    if storable:
        rows = await session.scalars(select(Group).where(Group.id.in_(storable)).order_by(Group.id))
        groups = list(rows)
    if len(groups) != len(wanted):
        raise bad_request(
            "고른 그룹 중에 지워진 그룹이 있어요. 그룹을 다시 골라 주세요.",
            code="group_not_found",
        )
    return groups


def _check_rule(
    kind: str,
    *,
    keywords: Sequence[str],
    min_messages: int | None,
    window_hours: int | None,
) -> None:
    """종류에 맞는 조건이 채워져 있는지 본다(RuleCreate 와 같은 기준, 같은 문장)."""
    if kind == RuleKind.KEYWORD:
        if not keywords:
            raise bad_request("키워드를 하나 이상 넣어 주세요.", code="invalid_rule")
    elif min_messages is None or window_hours is None:
        raise bad_request("메시지 수와 기간을 정해 주세요.", code="invalid_rule")


async def _rule_outs(session: AsyncSession, rules: Sequence[Rule]) -> list[RuleOut]:
    """규칙마다 수집된 유저 수·감지 수·마지막 감지 시각을 붙여 돌려준다(쿼리 한 번)."""
    stats: dict[int, tuple[int, int, datetime | None]] = {}
    if rules:
        rows = await session.execute(
            select(
                Hit.rule_id,
                func.count(func.distinct(Hit.lead_id)),
                func.count(),
                func.max(Hit.created_at),
            )
            .where(Hit.rule_id.in_([rule.id for rule in rules]))
            .group_by(Hit.rule_id)
        )
        stats = {rule_id: (leads, hits, last_hit_at) for rule_id, leads, hits, last_hit_at in rows}

    outs: list[RuleOut] = []
    for rule in rules:
        lead_count, hit_count, last_hit_at = stats.get(rule.id, (0, 0, None))
        outs.append(
            RuleOut(
                id=rule.id,
                name=rule.name,
                kind=rule.kind,
                enabled=rule.enabled,
                keywords=list(rule.keywords or []),
                exclude_keywords=list(rule.exclude_keywords or []),
                match_mode=rule.match_mode,
                min_messages=rule.min_messages,
                window_hours=rule.window_hours,
                all_groups=rule.all_groups,
                group_ids=sorted(group.id for group in rule.groups),
                created_at=rule.created_at,
                updated_at=rule.updated_at,
                lead_count=lead_count,
                hit_count=hit_count,
                last_hit_at=last_hit_at,
            )
        )
    return outs


async def _fresh_rule_out(session: AsyncSession, rule: Rule) -> RuleOut:
    return (await _rule_outs(session, [rule]))[0]


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.get("", response_model=list[RuleOut])
async def list_rules(session: DbSession) -> list[RuleOut]:
    rows = await session.scalars(select(Rule).order_by(Rule.created_at.desc(), Rule.id.desc()))
    return await _rule_outs(session, rows.all())


@router.post("", response_model=RuleOut, status_code=201)
async def create_rule(body: RuleCreate, ctx: Ctx, session: DbSession) -> RuleOut:
    groups = await _load_groups(session, body.group_ids)
    rule = Rule(
        name=body.name,
        kind=body.kind,
        enabled=body.enabled,
        keywords=body.keywords,
        exclude_keywords=body.exclude_keywords,
        match_mode=body.match_mode,
        min_messages=body.min_messages,
        window_hours=body.window_hours,
        all_groups=body.all_groups,
        groups=groups,
    )
    session.add(rule)
    await session.commit()
    ctx.collector.invalidate()
    return await _fresh_rule_out(session, rule)


@router.patch("/{rule_id}", response_model=RuleOut)
async def update_rule(rule_id: RuleId, body: RuleUpdate, ctx: Ctx, session: DbSession) -> RuleOut:
    rule = await _get_rule(session, rule_id)
    sent = body.model_fields_set

    changes: dict[str, Any] = {}
    if "name" in sent and body.name is not None:
        name = body.name.strip()
        if not name:
            raise bad_request("규칙 이름을 입력해 주세요.", code="invalid_rule")
        changes["name"] = name
    for field in _REQUIRED_FIELDS:
        value = getattr(body, field)
        if field in sent and value is not None:
            changes[field] = value
    for field in _NULLABLE_FIELDS:
        if field in sent:
            changes[field] = getattr(body, field)
    groups: list[Group] | None = None
    if "group_ids" in sent and body.group_ids is not None:
        groups = await _load_groups(session, body.group_ids)

    if not changes and groups is None:
        return await _fresh_rule_out(session, rule)

    merged = {
        field: changes.get(field, getattr(rule, field))
        for field in ("keywords", "all_groups", *_NULLABLE_FIELDS)
    }
    _check_rule(
        rule.kind,
        keywords=merged["keywords"] or [],
        min_messages=merged["min_messages"],
        window_hours=merged["window_hours"],
    )
    # 적용 그룹은 범위를 건드린 요청에서만 본다. 그룹이 지워져서 비어 버린 규칙도
    # 이름을 바꾸거나 끌 수는 있어야 한다.
    if "all_groups" in changes or groups is not None:
        scoped = groups if groups is not None else rule.groups
        if not merged["all_groups"] and not scoped:
            raise bad_request("적용할 그룹을 하나 이상 골라 주세요.", code="invalid_rule")

    for field, value in changes.items():
        setattr(rule, field, value)
    if groups is not None:
        rule.groups = groups
    rule.updated_at = utcnow()
    await session.commit()
    ctx.collector.invalidate()
    return await _fresh_rule_out(session, rule)


@router.delete("/{rule_id}", response_model=Message)
async def delete_rule(rule_id: RuleId, ctx: Ctx, session: DbSession) -> Message:
    await _get_rule(session, rule_id)
    # 적용 그룹 연결은 함께 지워지고 감지 기록은 남는다(hits.rule_id 만 비고 rule_name 은 그대로).
    # 다른 요청이 먼저 지웠어도 어긋나지 않게 id 로 바로 지운다.
    await session.execute(delete(Rule).where(Rule.id == rule_id))
    await session.commit()
    ctx.collector.invalidate()
    return Message()
