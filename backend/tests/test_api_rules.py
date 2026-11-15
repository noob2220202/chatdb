"""/api/rules 테스트."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, func, select

from app.models import (
    Account,
    AccountStatus,
    Group,
    GroupStatus,
    Hit,
    Lead,
    MatchMode,
    Rule,
    RuleKind,
    rule_groups,
)

T0 = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)

KEYWORD_BODY: dict[str, Any] = {
    "name": "코인 문의",
    "kind": "keyword",
    "keywords": ["코인", "선물"],
}
ACTIVITY_BODY: dict[str, Any] = {
    "name": "활발한 유저",
    "kind": "activity",
    "min_messages": 20,
    "window_hours": 24,
}


@pytest.fixture
def invalidations(ctx, monkeypatch) -> list[None]:
    """수집기 캐시를 버린 횟수만큼 항목이 쌓인다."""
    calls: list[None] = []
    monkeypatch.setattr(ctx.collector, "invalidate", lambda: calls.append(None))
    return calls


async def add_groups(ctx, count: int) -> list[Group]:
    async with ctx.db.session() as session:
        account = Account(label="영업 1호", status=AccountStatus.ACTIVE)
        session.add(account)
        await session.flush()
        groups = [
            Group(account_id=account.id, title=f"그룹 {i + 1}", status=GroupStatus.JOINED)
            for i in range(count)
        ]
        session.add_all(groups)
        await session.commit()
        return groups


async def add_rule(ctx, group_ids: list[int] | None = None, **fields: Any) -> Rule:
    values: dict[str, Any] = {"name": "코인 문의", "kind": RuleKind.KEYWORD, "keywords": ["코인"]}
    values.update(fields)
    async with ctx.db.session() as session:
        groups = []
        if group_ids:
            rows = await session.scalars(select(Group).where(Group.id.in_(group_ids)))
            groups = list(rows)
        rule = Rule(**values, groups=groups)
        session.add(rule)
        await session.commit()
        return rule


async def add_lead(ctx, number: int) -> Lead:
    async with ctx.db.session() as session:
        lead = Lead(tg_user_id=1000 + number, username=f"user_{number}", first_kind="keyword")
        session.add(lead)
        await session.commit()
        return lead


async def add_hit(ctx, lead: Lead, rule: Rule, created_at: datetime) -> Hit:
    async with ctx.db.session() as session:
        hit = Hit(
            lead_id=lead.id,
            rule_id=rule.id,
            kind=rule.kind,
            rule_name=rule.name,
            created_at=created_at,
        )
        session.add(hit)
        await session.commit()
        return hit


async def get_rule(ctx, rule_id: int) -> Rule | None:
    async with ctx.db.session() as session:
        return await session.get(Rule, rule_id)


async def rule_count(ctx) -> int:
    async with ctx.db.session() as session:
        return (await session.execute(select(func.count()).select_from(Rule))).scalar_one()


async def link_count(ctx) -> int:
    async with ctx.db.session() as session:
        return (await session.execute(select(func.count()).select_from(rule_groups))).scalar_one()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


# --- 로그인 필요 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/rules"),
        ("POST", "/api/rules"),
        ("PATCH", "/api/rules/1"),
        ("DELETE", "/api/rules/1"),
    ],
)
async def test_requires_login(client, ctx, invalidations, method, path):
    await add_rule(ctx)

    res = await client.request(method, path, json=KEYWORD_BODY)

    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"
    assert await rule_count(ctx) == 1
    assert invalidations == []


# --- 목록 --------------------------------------------------------------------


async def test_list_is_empty_at_first(authed):
    res = await authed.get("/api/rules")

    assert res.status_code == 200
    assert res.json() == []


async def test_list_newest_first_with_stats(authed, ctx):
    older = await add_rule(ctx, name="먼저 만든 규칙", created_at=T0)
    newer = await add_rule(ctx, name="나중에 만든 규칙", created_at=T0 + timedelta(hours=1))
    unused = await add_rule(
        ctx,
        name="아직 안 걸린 규칙",
        kind=RuleKind.ACTIVITY,
        keywords=[],
        min_messages=10,
        window_hours=6,
        created_at=T0 + timedelta(hours=2),
    )
    first, second = await add_lead(ctx, 1), await add_lead(ctx, 2)
    await add_hit(ctx, first, older, T0 + timedelta(minutes=1))
    await add_hit(ctx, first, older, T0 + timedelta(minutes=5))
    await add_hit(ctx, second, older, T0 + timedelta(minutes=3))
    await add_hit(ctx, second, newer, T0 + timedelta(minutes=9))

    res = await authed.get("/api/rules")

    assert res.status_code == 200
    rules = res.json()
    assert [r["id"] for r in rules] == [unused.id, newer.id, older.id]
    by_id = {r["id"]: r for r in rules}
    assert (by_id[older.id]["lead_count"], by_id[older.id]["hit_count"]) == (2, 3)
    assert parse_time(by_id[older.id]["last_hit_at"]) == T0 + timedelta(minutes=5)
    assert (by_id[newer.id]["lead_count"], by_id[newer.id]["hit_count"]) == (1, 1)
    assert parse_time(by_id[newer.id]["last_hit_at"]) == T0 + timedelta(minutes=9)
    assert by_id[unused.id]["lead_count"] == 0
    assert by_id[unused.id]["hit_count"] == 0
    assert by_id[unused.id]["last_hit_at"] is None


async def test_list_orders_same_moment_by_id(authed, ctx):
    first = await add_rule(ctx, name="가", created_at=T0)
    second = await add_rule(ctx, name="나", created_at=T0)

    res = await authed.get("/api/rules")

    assert [r["id"] for r in res.json()] == [second.id, first.id]


# --- 만들기 ------------------------------------------------------------------


async def test_create_keyword_rule(authed, ctx, invalidations):
    res = await authed.post(
        "/api/rules",
        json={
            "name": "  코인 문의  ",
            "kind": "keyword",
            "keywords": ["코인", " 선물  거래 ", "코인", ""],
            "exclude_keywords": ["광고"],
            "match_mode": "all",
        },
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "코인 문의"
    assert body["kind"] == "keyword"
    assert body["enabled"] is True
    assert body["keywords"] == ["코인", "선물 거래"]
    assert body["exclude_keywords"] == ["광고"]
    assert body["match_mode"] == "all"
    assert body["min_messages"] is None
    assert body["window_hours"] is None
    assert body["all_groups"] is True
    assert body["group_ids"] == []
    assert (body["lead_count"], body["hit_count"], body["last_hit_at"]) == (0, 0, None)
    assert parse_time(body["created_at"]).tzinfo is not None
    assert invalidations == [None]

    stored = await get_rule(ctx, body["id"])
    assert stored is not None
    assert stored.keywords == ["코인", "선물 거래"]
    assert stored.match_mode == MatchMode.ALL


async def test_create_activity_rule(authed, invalidations):
    res = await authed.post("/api/rules", json={**ACTIVITY_BODY, "enabled": False})

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "activity"
    assert body["enabled"] is False
    assert (body["min_messages"], body["window_hours"]) == (20, 24)
    assert body["keywords"] == []
    assert invalidations == [None]


async def test_create_for_chosen_groups(authed, ctx):
    groups = await add_groups(ctx, 3)
    chosen = [groups[2].id, groups[0].id, groups[2].id]

    res = await authed.post(
        "/api/rules", json={**KEYWORD_BODY, "all_groups": False, "group_ids": chosen}
    )

    assert res.status_code == 201, res.text
    assert res.json()["all_groups"] is False
    assert res.json()["group_ids"] == [groups[0].id, groups[2].id]
    assert await link_count(ctx) == 2


async def test_create_keeps_chosen_groups_even_when_applied_to_all(authed, ctx):
    groups = await add_groups(ctx, 2)

    res = await authed.post("/api/rules", json={**KEYWORD_BODY, "group_ids": [groups[1].id]})

    assert res.status_code == 201, res.text
    assert res.json()["all_groups"] is True
    assert res.json()["group_ids"] == [groups[1].id]


@pytest.mark.parametrize("missing", [999, 0, -3, 2**70])
async def test_create_rejects_unknown_group(authed, ctx, invalidations, missing):
    groups = await add_groups(ctx, 1)

    res = await authed.post(
        "/api/rules",
        json={**KEYWORD_BODY, "all_groups": False, "group_ids": [groups[0].id, missing]},
    )

    assert res.status_code == 400
    assert res.json()["code"] == "group_not_found"
    assert "그룹" in res.json()["detail"]
    assert await rule_count(ctx) == 0
    assert invalidations == []


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"name": "키워드 없음", "kind": "keyword"}, "키워드를 하나 이상 넣어 주세요."),
        (
            {"name": "빈 키워드", "kind": "keyword", "keywords": ["  ", ""]},
            "키워드를 하나 이상 넣어 주세요.",
        ),
        (
            {"name": "기간 없음", "kind": "activity", "min_messages": 5},
            "메시지 수와 기간을 정해 주세요.",
        ),
        (
            {"name": "개수 없음", "kind": "activity", "window_hours": 5},
            "메시지 수와 기간을 정해 주세요.",
        ),
        (
            {**KEYWORD_BODY, "all_groups": False},
            "적용할 그룹을 하나 이상 골라 주세요.",
        ),
        ({**KEYWORD_BODY, "name": "   "}, "규칙 이름을 입력해 주세요."),
        ({**ACTIVITY_BODY, "min_messages": 1}, "메시지 수 값을 다시 확인해 주세요."),
        ({**ACTIVITY_BODY, "window_hours": 721}, "기간 값을 다시 확인해 주세요."),
        ({**KEYWORD_BODY, "name": "가" * 81}, "이름 값이 너무 길어요."),
    ],
)
async def test_create_rejects_invalid_body(authed, ctx, invalidations, body, detail):
    res = await authed.post("/api/rules", json=body)

    assert res.status_code == 422
    assert res.json()["code"] == "validation"
    assert res.json()["detail"] == detail
    assert await rule_count(ctx) == 0
    assert invalidations == []


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "keyword", "keywords": ["코인"]},
        {**KEYWORD_BODY, "kind": "other"},
        {**KEYWORD_BODY, "match_mode": "some"},
    ],
)
async def test_create_rejects_malformed_body(authed, ctx, body):
    res = await authed.post("/api/rules", json=body)

    assert res.status_code == 422
    assert await rule_count(ctx) == 0


# --- 고치기 ------------------------------------------------------------------


async def test_patch_changes_only_sent_fields(authed, ctx, invalidations):
    rule = await add_rule(
        ctx,
        keywords=["코인", "선물"],
        exclude_keywords=["광고"],
        match_mode=MatchMode.ALL,
        created_at=T0,
        updated_at=T0,
    )

    res = await authed.patch(f"/api/rules/{rule.id}", json={"enabled": False})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["enabled"] is False
    assert body["name"] == "코인 문의"
    assert body["keywords"] == ["코인", "선물"]
    assert body["exclude_keywords"] == ["광고"]
    assert body["match_mode"] == "all"
    assert body["all_groups"] is True
    assert parse_time(body["created_at"]) == T0
    assert parse_time(body["updated_at"]) > T0
    assert invalidations == [None]

    stored = await get_rule(ctx, rule.id)
    assert stored is not None
    assert stored.enabled is False
    assert stored.keywords == ["코인", "선물"]


async def test_patch_keyword_fields(authed, ctx):
    rule = await add_rule(ctx)

    res = await authed.patch(
        f"/api/rules/{rule.id}",
        json={
            "name": "  새 이름 ",
            "keywords": ["비트코인", "비트코인 ", "이더"],
            "exclude_keywords": ["홍보", "광고"],
            "match_mode": "all",
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "새 이름"
    assert body["keywords"] == ["비트코인", "이더"]
    assert body["exclude_keywords"] == ["홍보", "광고"]
    assert body["match_mode"] == "all"
    assert body["kind"] == "keyword"


async def test_patch_activity_fields(authed, ctx):
    rule = await add_rule(
        ctx, kind=RuleKind.ACTIVITY, keywords=[], min_messages=20, window_hours=24
    )

    res = await authed.patch(f"/api/rules/{rule.id}", json={"min_messages": 50})

    assert res.status_code == 200, res.text
    assert (res.json()["min_messages"], res.json()["window_hours"]) == (50, 24)


async def test_patch_cannot_change_kind(authed, ctx):
    rule = await add_rule(ctx)

    res = await authed.patch(f"/api/rules/{rule.id}", json={"kind": "activity", "name": "그대로"})

    assert res.status_code == 200, res.text
    assert res.json()["kind"] == "keyword"
    assert res.json()["name"] == "그대로"


async def test_patch_keeps_stats(authed, ctx):
    rule = await add_rule(ctx)
    lead = await add_lead(ctx, 1)
    await add_hit(ctx, lead, rule, T0)
    await add_hit(ctx, lead, rule, T0 + timedelta(minutes=2))

    res = await authed.patch(f"/api/rules/{rule.id}", json={"name": "이름만 바꿈"})

    body = res.json()
    assert (body["lead_count"], body["hit_count"]) == (1, 2)
    assert parse_time(body["last_hit_at"]) == T0 + timedelta(minutes=2)


@pytest.mark.parametrize("body", [{}, {"name": None, "enabled": None, "keywords": None}])
async def test_patch_without_changes_leaves_rule_alone(authed, ctx, invalidations, body):
    rule = await add_rule(ctx, created_at=T0, updated_at=T0)

    res = await authed.patch(f"/api/rules/{rule.id}", json=body)

    assert res.status_code == 200, res.text
    assert res.json()["name"] == "코인 문의"
    assert res.json()["enabled"] is True
    assert res.json()["keywords"] == ["코인"]
    assert parse_time(res.json()["updated_at"]) == T0
    assert invalidations == []


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"keywords": []}, "키워드를 하나 이상 넣어 주세요."),
        ({"keywords": ["  "]}, "키워드를 하나 이상 넣어 주세요."),
        ({"name": "   "}, "규칙 이름을 입력해 주세요."),
        ({"all_groups": False}, "적용할 그룹을 하나 이상 골라 주세요."),
        ({"all_groups": False, "group_ids": []}, "적용할 그룹을 하나 이상 골라 주세요."),
    ],
)
async def test_patch_rejects_broken_keyword_rule(authed, ctx, invalidations, body, detail):
    rule = await add_rule(ctx, created_at=T0, updated_at=T0)

    res = await authed.patch(f"/api/rules/{rule.id}", json={"enabled": False, **body})

    assert res.status_code == 400
    assert res.json()["code"] == "invalid_rule"
    assert res.json()["detail"] == detail
    stored = await get_rule(ctx, rule.id)
    assert stored is not None
    assert (stored.name, stored.keywords, stored.all_groups) == ("코인 문의", ["코인"], True)
    assert stored.enabled is True
    assert stored.updated_at == T0
    assert invalidations == []


@pytest.mark.parametrize("body", [{"min_messages": None}, {"window_hours": None}])
async def test_patch_rejects_activity_rule_without_numbers(authed, ctx, invalidations, body):
    rule = await add_rule(
        ctx, kind=RuleKind.ACTIVITY, keywords=[], min_messages=20, window_hours=24
    )

    res = await authed.patch(f"/api/rules/{rule.id}", json=body)

    assert res.status_code == 400
    assert res.json()["detail"] == "메시지 수와 기간을 정해 주세요."
    stored = await get_rule(ctx, rule.id)
    assert stored is not None
    assert (stored.min_messages, stored.window_hours) == (20, 24)
    assert invalidations == []


async def test_patch_activity_rule_may_have_no_keywords(authed, ctx):
    rule = await add_rule(
        ctx, kind=RuleKind.ACTIVITY, keywords=[], min_messages=20, window_hours=24
    )

    res = await authed.patch(f"/api/rules/{rule.id}", json={"keywords": [], "window_hours": 48})

    assert res.status_code == 200, res.text
    assert res.json()["window_hours"] == 48


async def test_patch_keyword_rule_may_clear_activity_numbers(authed, ctx):
    rule = await add_rule(ctx, min_messages=5, window_hours=2)

    res = await authed.patch(
        f"/api/rules/{rule.id}", json={"min_messages": None, "window_hours": None}
    )

    assert res.status_code == 200, res.text
    assert (res.json()["min_messages"], res.json()["window_hours"]) == (None, None)


@pytest.mark.parametrize(
    "body",
    [
        {"min_messages": 1},
        {"window_hours": 0},
        {"match_mode": "some"},
        {"name": ""},
        {"keywords": "코인"},
        {"group_ids": ["x"]},
    ],
)
async def test_patch_rejects_malformed_body(authed, ctx, invalidations, body):
    rule = await add_rule(ctx)

    res = await authed.patch(f"/api/rules/{rule.id}", json=body)

    assert res.status_code == 422
    assert invalidations == []


async def test_patch_limits_rule_to_groups(authed, ctx, invalidations):
    groups = await add_groups(ctx, 3)
    rule = await add_rule(ctx, created_at=T0, updated_at=T0)

    res = await authed.patch(
        f"/api/rules/{rule.id}",
        json={"all_groups": False, "group_ids": [groups[1].id, groups[0].id]},
    )

    assert res.status_code == 200, res.text
    assert res.json()["all_groups"] is False
    assert res.json()["group_ids"] == [groups[0].id, groups[1].id]
    assert invalidations == [None]


async def test_patch_replaces_groups(authed, ctx):
    groups = await add_groups(ctx, 3)
    rule = await add_rule(
        ctx, [groups[0].id, groups[1].id], all_groups=False, created_at=T0, updated_at=T0
    )

    res = await authed.patch(f"/api/rules/{rule.id}", json={"group_ids": [groups[2].id]})

    assert res.status_code == 200, res.text
    assert res.json()["group_ids"] == [groups[2].id]
    assert parse_time(res.json()["updated_at"]) > T0
    assert await link_count(ctx) == 1


async def test_patch_scoped_rule_cannot_lose_all_groups(authed, ctx, invalidations):
    groups = await add_groups(ctx, 2)
    rule = await add_rule(ctx, [groups[0].id], all_groups=False)

    res = await authed.patch(f"/api/rules/{rule.id}", json={"group_ids": []})

    assert res.status_code == 400
    assert res.json()["detail"] == "적용할 그룹을 하나 이상 골라 주세요."
    assert await link_count(ctx) == 1
    assert invalidations == []


async def test_patch_can_narrow_to_groups_chosen_earlier(authed, ctx):
    groups = await add_groups(ctx, 2)
    rule = await add_rule(ctx, [groups[1].id], all_groups=True)

    res = await authed.patch(f"/api/rules/{rule.id}", json={"all_groups": False})

    assert res.status_code == 200, res.text
    assert res.json()["all_groups"] is False
    assert res.json()["group_ids"] == [groups[1].id]


async def test_patch_can_widen_to_all_groups_with_empty_selection(authed, ctx):
    groups = await add_groups(ctx, 1)
    rule = await add_rule(ctx, [groups[0].id], all_groups=False)

    res = await authed.patch(f"/api/rules/{rule.id}", json={"all_groups": True, "group_ids": []})

    assert res.status_code == 200, res.text
    assert res.json()["all_groups"] is True
    assert res.json()["group_ids"] == []


@pytest.mark.parametrize("missing", [999, 2**70])
async def test_patch_rejects_unknown_group(authed, ctx, invalidations, missing):
    groups = await add_groups(ctx, 1)
    rule = await add_rule(ctx, [groups[0].id], all_groups=False)

    res = await authed.patch(
        f"/api/rules/{rule.id}", json={"name": "바뀌면 안 됨", "group_ids": [missing]}
    )

    assert res.status_code == 400
    assert res.json()["code"] == "group_not_found"
    stored = await get_rule(ctx, rule.id)
    assert stored is not None
    assert stored.name == "코인 문의"
    assert [group.id for group in stored.groups] == [groups[0].id]
    assert invalidations == []


async def test_patch_rule_whose_groups_were_deleted_can_still_be_turned_off(authed, ctx):
    groups = await add_groups(ctx, 1)
    rule = await add_rule(ctx, [groups[0].id], all_groups=False)
    async with ctx.db.session() as session:
        await session.execute(delete(Group).where(Group.id == groups[0].id))
        await session.commit()
    assert await link_count(ctx) == 0

    res = await authed.patch(f"/api/rules/{rule.id}", json={"enabled": False, "name": "정리 예정"})

    assert res.status_code == 200, res.text
    assert res.json()["enabled"] is False
    assert res.json()["name"] == "정리 예정"
    assert res.json()["group_ids"] == []


async def test_patch_unknown_rule(authed, invalidations):
    res = await authed.patch("/api/rules/999", json={"enabled": False})

    assert res.status_code == 404
    assert res.json() == {
        "detail": "규칙을 찾을 수 없어요.",
        "code": "not_found",
        "retry_after": None,
    }
    assert invalidations == []


@pytest.mark.parametrize("rule_id", ["abc", str(2**70)])
async def test_rejects_bad_rule_id(authed, rule_id):
    assert (await authed.patch(f"/api/rules/{rule_id}", json={})).status_code == 422
    assert (await authed.delete(f"/api/rules/{rule_id}")).status_code == 422


# --- 지우기 ------------------------------------------------------------------


async def test_delete_removes_rule_but_keeps_hits(authed, ctx, invalidations):
    groups = await add_groups(ctx, 2)
    rule = await add_rule(ctx, [groups[0].id, groups[1].id], all_groups=False)
    other = await add_rule(ctx, name="남는 규칙")
    lead = await add_lead(ctx, 1)
    hit = await add_hit(ctx, lead, rule, T0)

    res = await authed.delete(f"/api/rules/{rule.id}")

    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True}
    assert invalidations == [None]
    assert await get_rule(ctx, rule.id) is None
    assert await get_rule(ctx, other.id) is not None
    assert await link_count(ctx) == 0
    async with ctx.db.session() as session:
        kept = await session.get(Hit, hit.id)
        assert kept is not None
        assert kept.rule_id is None
        assert kept.rule_name == "코인 문의"
        assert await session.get(Group, groups[0].id) is not None

    listed = await authed.get("/api/rules")
    assert [r["id"] for r in listed.json()] == [other.id]


async def test_delete_unknown_rule(authed, invalidations):
    res = await authed.delete("/api/rules/999")

    assert res.status_code == 404
    assert res.json()["detail"] == "규칙을 찾을 수 없어요."
    assert invalidations == []


# --- 수집기와 맞물림 ----------------------------------------------------------


async def test_collector_is_told_only_after_commit(authed, ctx, monkeypatch):
    """커밋보다 먼저 캐시를 버리면 수집기가 예전 규칙을 다시 읽어 버린다."""
    database_file = ctx.config.data_dir / "chatdb.sqlite3"
    committed: list[list[tuple[str, int]]] = []

    def probe() -> None:
        with closing(sqlite3.connect(database_file)) as conn:
            committed.append(conn.execute("SELECT name, enabled FROM rules").fetchall())

    monkeypatch.setattr(ctx.collector, "invalidate", probe)

    created = await authed.post("/api/rules", json=KEYWORD_BODY)
    rule_id = created.json()["id"]
    await authed.patch(f"/api/rules/{rule_id}", json={"enabled": False})
    await authed.delete(f"/api/rules/{rule_id}")

    assert committed == [[("코인 문의", 1)], [("코인 문의", 0)], []]
