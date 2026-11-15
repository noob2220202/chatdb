"""/api/logs 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event, func, select

from app.models import (
    Account,
    AccountStatus,
    EventLog,
    Group,
    GroupStatus,
    LogCategory,
    LogLevel,
)

T0 = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)


async def add_account(ctx, **fields: Any) -> Account:
    async with ctx.db.session() as session:
        account = Account(status=AccountStatus.ACTIVE, **fields)
        session.add(account)
        await session.commit()
        return account


async def add_group(ctx, account: Account, **fields: Any) -> Group:
    async with ctx.db.session() as session:
        group = Group(account_id=account.id, status=GroupStatus.JOINED, **fields)
        session.add(group)
        await session.commit()
        return group


async def add_log(ctx, message: str, minutes: int = 0, **fields: Any) -> EventLog:
    async with ctx.db.session() as session:
        entry = EventLog(message=message, created_at=T0 + timedelta(minutes=minutes), **fields)
        session.add(entry)
        await session.commit()
        return entry


async def log_count(ctx) -> int:
    async with ctx.db.session() as session:
        return (await session.execute(select(func.count()).select_from(EventLog))).scalar_one()


async def listing(client, params: Any = None) -> dict[str, Any]:
    res = await client.get("/api/logs", params=params)
    assert res.status_code == 200, res.text
    return res.json()


async def messages(client, params: Any = None) -> list[str]:
    return [item["message"] for item in (await listing(client, params))["items"]]


@pytest.fixture
async def varied(ctx) -> dict[str, int]:
    """계정 둘에 걸친 여러 종류의 기록. 숫자가 클수록 최근 것이다."""
    first, second = (
        await add_account(ctx, label="영업 1호"),
        await add_account(ctx, label="영업 2호"),
    )
    await add_log(ctx, "1 시스템 안내", 1)
    await add_log(ctx, "2 계정 연결", 2, category=LogCategory.ACCOUNT, account_id=first.id)
    await add_log(
        ctx,
        "3 계정 경고",
        3,
        level=LogLevel.WARNING,
        category=LogCategory.ACCOUNT,
        account_id=second.id,
    )
    await add_log(
        ctx, "4 그룹 실패", 4, level=LogLevel.ERROR, category=LogCategory.GROUP, account_id=first.id
    )
    await add_log(ctx, "5 수집 오류", 5, level=LogLevel.ERROR, category=LogCategory.COLLECT)
    await add_log(ctx, "6 그룹 가입", 6, category=LogCategory.GROUP, account_id=second.id)
    return {"first": first.id, "second": second.id}


# --- 로그인 필요 --------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_requires_login(client, ctx, method):
    await add_log(ctx, "남아 있어야 하는 기록")

    res = await client.request(method, "/api/logs")

    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"
    assert await log_count(ctx) == 1


# --- 목록 --------------------------------------------------------------------


async def test_list_is_empty_at_first(authed):
    assert await listing(authed) == {"items": [], "total": 0, "page": 1, "page_size": 50}


async def test_list_resolves_names(authed, ctx):
    account = await add_account(ctx, label="영업 1호")
    group = await add_group(ctx, account, title="코인 수다방")
    untitled = await add_group(ctx, account, public_username="cointalk")
    plain = await add_log(ctx, "엔진을 시작했어요.", 1)
    joined = await add_log(
        ctx,
        "그룹에 가입했어요.",
        2,
        category=LogCategory.GROUP,
        account_id=account.id,
        group_id=group.id,
    )
    failed = await add_log(
        ctx,
        "가입하지 못했어요.",
        3,
        level=LogLevel.ERROR,
        category=LogCategory.GROUP,
        account_id=account.id,
        group_id=untitled.id,
    )

    body = await listing(authed)

    assert body["total"] == 3
    assert body["items"] == [
        {
            "id": failed.id,
            "level": "error",
            "category": "group",
            "message": "가입하지 못했어요.",
            "account_id": account.id,
            "account_name": "영업 1호",
            "group_id": untitled.id,
            "group_title": "@cointalk",
            "created_at": "2026-11-10T03:03:00Z",
        },
        {
            "id": joined.id,
            "level": "info",
            "category": "group",
            "message": "그룹에 가입했어요.",
            "account_id": account.id,
            "account_name": "영업 1호",
            "group_id": group.id,
            "group_title": "코인 수다방",
            "created_at": "2026-11-10T03:02:00Z",
        },
        {
            "id": plain.id,
            "level": "info",
            "category": "system",
            "message": "엔진을 시작했어요.",
            "account_id": None,
            "account_name": None,
            "group_id": None,
            "group_title": None,
            "created_at": "2026-11-10T03:01:00Z",
        },
    ]


async def test_list_keeps_entries_of_deleted_account_and_group(authed, ctx):
    account = await add_account(ctx, label="지울 계정")
    group = await add_group(ctx, account, title="지울 그룹")
    await add_log(ctx, "계정과 그룹이 있던 기록", account_id=account.id, group_id=group.id)
    async with ctx.db.session() as session:
        await session.delete(await session.get(Account, account.id))
        await session.commit()

    body = await listing(authed)

    assert body["total"] == 1
    item = body["items"][0]
    assert item["message"] == "계정과 그룹이 있던 기록"
    assert (item["account_id"], item["account_name"]) == (None, None)
    assert (item["group_id"], item["group_title"]) == (None, None)


async def test_list_newest_first(authed, varied):
    assert await messages(authed) == [
        "6 그룹 가입",
        "5 수집 오류",
        "4 그룹 실패",
        "3 계정 경고",
        "2 계정 연결",
        "1 시스템 안내",
    ]


async def test_list_orders_same_moment_by_id(authed, ctx):
    for name in ("먼저", "다음", "마지막"):
        await add_log(ctx, name)

    assert await messages(authed) == ["마지막", "다음", "먼저"]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"level": "info"}, ["6 그룹 가입", "2 계정 연결", "1 시스템 안내"]),
        ({"level": "warning"}, ["3 계정 경고"]),
        ({"level": "error"}, ["5 수집 오류", "4 그룹 실패"]),
        ({"category": "account"}, ["3 계정 경고", "2 계정 연결"]),
        ({"category": "group"}, ["6 그룹 가입", "4 그룹 실패"]),
        ({"category": "collect"}, ["5 수집 오류"]),
        ({"category": "system"}, ["1 시스템 안내"]),
        ({"account_id": "first"}, ["4 그룹 실패", "2 계정 연결"]),
        ({"account_id": "second"}, ["6 그룹 가입", "3 계정 경고"]),
        ({"account_id": 999}, []),
        ({"level": "error", "category": "group"}, ["4 그룹 실패"]),
        ({"category": "group", "account_id": "second"}, ["6 그룹 가입"]),
        ({"level": "info", "category": "account", "account_id": "first"}, ["2 계정 연결"]),
        ({"level": "warning", "category": "collect"}, []),
    ],
)
async def test_list_filters(authed, varied, params, expected):
    if isinstance(params.get("account_id"), str):
        params = {**params, "account_id": varied[params["account_id"]]}

    body = await listing(authed, params)

    assert [item["message"] for item in body["items"]] == expected
    assert body["total"] == len(expected)


async def test_list_pages(authed, varied):
    first = await listing(authed, {"page_size": 4})
    second = await listing(authed, {"page_size": 4, "page": 2})
    beyond = await listing(authed, {"page_size": 4, "page": 3})

    assert [item["message"][0] for item in first["items"]] == ["6", "5", "4", "3"]
    assert [item["message"][0] for item in second["items"]] == ["2", "1"]
    assert beyond["items"] == []
    assert (first["total"], first["page"], first["page_size"]) == (6, 1, 4)
    assert (second["total"], second["page"], second["page_size"]) == (6, 2, 4)
    assert (beyond["total"], beyond["page"], beyond["page_size"]) == (6, 3, 4)


async def test_list_pages_within_a_filter(authed, varied):
    body = await listing(authed, {"level": "info", "page_size": 2, "page": 2})

    assert [item["message"] for item in body["items"]] == ["1 시스템 안내"]
    assert body["total"] == 3


async def test_list_default_and_largest_page_size(authed, ctx):
    async with ctx.db.session() as session:
        session.add_all(
            EventLog(message=f"기록 {number}", created_at=T0 + timedelta(seconds=number))
            for number in range(205)
        )
        await session.commit()

    default = await listing(authed)
    largest = await listing(authed, {"page_size": 200})

    assert (len(default["items"]), default["page_size"], default["total"]) == (50, 50, 205)
    assert default["items"][0]["message"] == "기록 204"
    assert (len(largest["items"]), largest["page_size"]) == (200, 200)


async def test_list_reads_names_without_extra_queries(authed, ctx):
    account = await add_account(ctx, label="영업 1호")
    for number in range(20):
        group = await add_group(ctx, account, title=f"그룹 {number}")
        await add_log(ctx, f"기록 {number}", number, account_id=account.id, group_id=group.id)
    seen: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        seen.append(statement)

    engine = ctx.db.engine.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        body = await listing(authed)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(body["items"]) == 20
    assert all(item["group_title"] for item in body["items"])
    assert len([sql for sql in seen if "event_logs" in sql]) == 2


@pytest.mark.parametrize(
    "params",
    [
        {"level": "debug"},
        {"category": "billing"},
        {"account_id": "abc"},
        {"account_id": 2**70},
        {"page": 0},
        {"page": 10**30},
        {"page_size": 0},
        {"page_size": 201},
    ],
)
async def test_list_rejects_bad_query(authed, params):
    res = await authed.get("/api/logs", params=params)

    assert res.status_code == 422
    assert res.json()["code"] == "validation"


async def test_list_shows_entries_written_by_the_logbook(authed, ctx):
    account = await add_account(ctx, label="영업 1호")

    await ctx.logbook.warning(
        "요청이 많아 잠시 쉬어요.", category=LogCategory.ACCOUNT, account_id=account.id
    )

    body = await listing(authed, {"level": "warning"})
    assert [(item["message"], item["account_name"]) for item in body["items"]] == [
        ("요청이 많아 잠시 쉬어요.", "영업 1호")
    ]


# --- 비우기 ------------------------------------------------------------------


async def test_clear_removes_everything(authed, ctx, varied):
    res = await authed.delete("/api/logs")

    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True}
    assert await log_count(ctx) == 0
    assert await listing(authed) == {"items": [], "total": 0, "page": 1, "page_size": 50}
    async with ctx.db.session() as session:
        accounts = (await session.execute(select(func.count()).select_from(Account))).scalar_one()
    assert accounts == 2


async def test_clear_when_already_empty(authed, ctx):
    res = await authed.delete("/api/logs")

    assert res.status_code == 200, res.text
    assert await log_count(ctx) == 0
