"""/api/leads 테스트."""

from __future__ import annotations

import csv
import io
import itertools
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event, func, select

from app.models import (
    Account,
    AccountStatus,
    BlocklistEntry,
    Group,
    GroupStatus,
    Hit,
    Lead,
    LeadStatus,
    Rule,
    RuleKind,
)
from app.telegram.gateway import IncomingMessage, TgUser

T0 = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)
NOW = datetime(2026, 11, 15, 0, 30, tzinfo=UTC)
"""내보내기 테스트에서 '지금'으로 쓰는 시각. 서울 시간으로 11월 15일 09:30 이다."""

BOM = b"\xef\xbb\xbf"
CSV_HEADER = [
    "아이디", "이름", "상태", "감지 횟수", "처음 감지", "마지막 감지",
    "최근 규칙", "최근 그룹", "최근 내용", "메모",
]  # fmt: skip
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")

_user_ids = itertools.count(5000)
_message_ids = itertools.count(1)


@pytest.fixture
def invalidations(ctx, monkeypatch) -> list[None]:
    """수집기 캐시를 버린 횟수만큼 항목이 쌓인다."""
    calls: list[None] = []
    monkeypatch.setattr(ctx.collector, "invalidate", lambda: calls.append(None))
    return calls


@pytest.fixture
def fixed_now(monkeypatch) -> datetime:
    monkeypatch.setattr("app.routers.leads.utcnow", lambda: NOW)
    return NOW


@pytest.fixture
def statements(ctx) -> Iterator[list[str]]:
    """요청하는 동안 DB 에 나간 SQL 문장들."""
    seen: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        seen.append(statement)

    engine = ctx.db.engine.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    yield seen
    event.remove(engine, "before_cursor_execute", record)


# --- 심어 두기 ----------------------------------------------------------------


async def add_group(ctx, title: str = "코인 수다방") -> Group:
    async with ctx.db.session() as session:
        account = (await session.scalars(select(Account).limit(1))).first()
        if account is None:
            account = Account(label="영업 1호", status=AccountStatus.ACTIVE)
            session.add(account)
            await session.flush()
        group = Group(account_id=account.id, title=title, status=GroupStatus.JOINED)
        session.add(group)
        await session.commit()
        return group


async def add_rule(ctx, name: str = "코인 문의", kind: RuleKind = RuleKind.KEYWORD) -> Rule:
    async with ctx.db.session() as session:
        rule = Rule(name=name, kind=kind, keywords=["코인"], min_messages=20, window_hours=24)
        session.add(rule)
        await session.commit()
        return rule


async def add_lead(ctx, username: str, **fields: Any) -> Lead:
    values: dict[str, Any] = {
        "tg_user_id": next(_user_ids),
        "first_kind": RuleKind.KEYWORD,
        "first_seen_at": T0,
        "last_seen_at": T0,
    }
    values.update(fields)
    async with ctx.db.session() as session:
        lead = Lead(username=username, **values)
        session.add(lead)
        await session.commit()
        return lead


async def add_hit(
    ctx,
    lead: Lead,
    *,
    rule: Rule | None = None,
    group: Group | None = None,
    latest: bool = True,
    **fields: Any,
) -> Hit:
    """감지 한 건을 넣는다. latest 면 유저의 last_hit_id 도 이 감지로 돌린다."""
    values: dict[str, Any] = {
        "kind": rule.kind if rule else RuleKind.KEYWORD,
        "rule_name": rule.name if rule else "코인 문의",
        "group_title": group.title if group else "코인 수다방",
        "created_at": T0,
    }
    values.update(fields)
    async with ctx.db.session() as session:
        hit = Hit(
            lead_id=lead.id,
            rule_id=rule.id if rule else None,
            group_id=group.id if group else None,
            **values,
        )
        session.add(hit)
        await session.flush()
        if latest:
            stored = await session.get(Lead, lead.id)
            assert stored is not None
            stored.last_hit_id = hit.id
        await session.commit()
        return hit


async def get_lead(ctx, lead_id: int) -> Lead | None:
    async with ctx.db.session() as session:
        return await session.get(Lead, lead_id)


async def lead_statuses(ctx) -> dict[str, str]:
    async with ctx.db.session() as session:
        rows = await session.execute(select(Lead.username, Lead.status))
        return {username: status for username, status in rows}


async def hit_count(ctx) -> int:
    async with ctx.db.session() as session:
        return (await session.execute(select(func.count()).select_from(Hit))).scalar_one()


async def blocked_usernames(ctx) -> list[str]:
    async with ctx.db.session() as session:
        rows = await session.scalars(select(BlocklistEntry.username).order_by(BlocklistEntry.id))
        return list(rows)


async def listing(client, params: Any = None) -> dict[str, Any]:
    res = await client.get("/api/leads", params=params)
    assert res.status_code == 200, res.text
    return res.json()


async def found(client, params: Any = None) -> set[str]:
    return {item["username"] for item in (await listing(client, params))["items"]}


async def ordered(client, params: Any = None) -> list[str]:
    return [item["username"] for item in (await listing(client, params))["items"]]


def csv_rows(content: bytes) -> list[list[str]]:
    assert content.startswith(BOM)
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline="")))


# --- 로그인 필요 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/leads"),
        ("GET", "/api/leads/export?format=csv"),
        ("GET", "/api/leads/export?format=txt&ids=1"),
        ("GET", "/api/leads/1"),
        ("PATCH", "/api/leads/1"),
        ("POST", "/api/leads/bulk"),
        ("DELETE", "/api/leads/1"),
    ],
)
async def test_requires_login(client, ctx, invalidations, method, path):
    await add_lead(ctx, "kim_trader")

    res = await client.request(method, path, json={"ids": [1], "action": "delete"})

    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"
    assert await lead_statuses(ctx) == {"kim_trader": "new"}
    assert invalidations == []


# --- 목록: 모양 ---------------------------------------------------------------


async def test_list_is_empty_at_first(authed):
    body = await listing(authed)

    assert body == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 50,
        "status_counts": {"new": 0, "reviewed": 0, "contacted": 0, "excluded": 0},
    }


async def test_list_item_shape(authed, ctx):
    group = await add_group(ctx)
    rule = await add_rule(ctx)
    lead = await add_lead(
        ctx,
        "Kim_Trader",
        first_name="민수",
        last_name="김",
        note="관심 많음",
        status=LeadStatus.REVIEWED,
        hit_count=2,
        first_seen_at=T0,
        last_seen_at=T0 + timedelta(hours=5),
    )
    await add_hit(ctx, lead, rule=rule, group=group, excerpt="예전 글", created_at=T0)
    last = await add_hit(
        ctx,
        lead,
        rule=rule,
        group=group,
        keywords=["코인"],
        excerpt="코인 어디서 사요?",
        created_at=T0 + timedelta(hours=5),
    )

    body = await listing(authed)

    assert body["total"] == 1
    assert body["items"] == [
        {
            "id": lead.id,
            "tg_user_id": lead.tg_user_id,
            "username": "Kim_Trader",
            "first_name": "민수",
            "last_name": "김",
            "display_name": "민수 김",
            "status": "reviewed",
            "note": "관심 많음",
            "hit_count": 2,
            "first_seen_at": "2026-11-10T03:00:00Z",
            "last_seen_at": "2026-11-10T08:00:00Z",
            "last_hit": {
                "id": last.id,
                "kind": "keyword",
                "rule_id": rule.id,
                "rule_name": "코인 문의",
                "group_id": group.id,
                "group_title": "코인 수다방",
                "keywords": ["코인"],
                "excerpt": "코인 어디서 사요?",
                "message_count": None,
                "window_hours": None,
                "created_at": "2026-11-10T08:00:00Z",
            },
        }
    ]


async def test_list_last_hit_is_empty_when_pointer_is_missing_or_dangling(authed, ctx):
    await add_lead(ctx, "never_pointed")
    await add_lead(ctx, "pruned_away", last_hit_id=987654)

    body = await listing(authed)

    assert {item["username"]: item["last_hit"] for item in body["items"]} == {
        "never_pointed": None,
        "pruned_away": None,
    }


async def test_list_reads_last_hits_in_one_query(authed, ctx, statements):
    for number in range(30):
        lead = await add_lead(ctx, f"user_{number}")
        await add_hit(ctx, lead, latest=False, excerpt="예전 글")
        await add_hit(ctx, lead, excerpt=f"최근 글 {number}")
    statements.clear()

    body = await listing(authed)

    assert len(body["items"]) == 30
    assert all(item["last_hit"]["excerpt"].startswith("최근 글") for item in body["items"])
    assert len([sql for sql in statements if "FROM hits" in sql]) == 1
    assert len([sql for sql in statements if "FROM leads" in sql]) == 2


# --- 목록: 검색 ---------------------------------------------------------------


@pytest.fixture
async def searchable(ctx) -> None:
    await add_lead(ctx, "Kim_Trader", first_name="민수", last_name="김", note="코인 관심 많음")
    await add_lead(ctx, "kimxtrader", first_name="Jane", last_name="Doe")
    await add_lead(ctx, "lee_coin", first_name="100% 진심")
    await add_lead(ctx, "park", last_name="Trader")


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("kim_trader", {"Kim_Trader"}),
        ("KIM_TRADER", {"Kim_Trader"}),
        ("@Kim_Tr", {"Kim_Trader"}),
        ("kim", {"Kim_Trader", "kimxtrader"}),
        ("민수", {"Kim_Trader"}),
        ("김", {"Kim_Trader"}),
        ("jane", {"kimxtrader"}),
        ("DOE", {"kimxtrader"}),
        ("관심", {"Kim_Trader"}),
        ("trader", {"Kim_Trader", "kimxtrader", "park"}),
        ("100%", {"lee_coin"}),
        ("%", {"lee_coin"}),
        ("_", {"Kim_Trader", "lee_coin"}),
        ("Jane Doe", {"kimxtrader"}),
        ("doe jane", {"kimxtrader"}),
        ("민수 김", {"Kim_Trader"}),
        ("@kim 관심", {"Kim_Trader"}),
        ("kim jane", {"kimxtrader"}),
        ("kim nobody", set()),
        ("nobody", set()),
        ("   ", {"Kim_Trader", "kimxtrader", "lee_coin", "park"}),
        ("@", {"Kim_Trader", "kimxtrader", "lee_coin", "park"}),
    ],
)
async def test_list_search(authed, searchable, q, expected):
    assert await found(authed, {"q": q}) == expected


async def test_list_search_with_many_words(authed, searchable):
    assert await found(authed, {"q": " ".join(["kim"] * 50)}) == {"Kim_Trader", "kimxtrader"}
    assert await found(authed, {"q": " ".join("abcdefghij" * 10)}) == set()


async def test_list_search_counts_follow_the_search(authed, ctx):
    await add_lead(ctx, "kim_one")
    await add_lead(ctx, "kim_two", status=LeadStatus.CONTACTED)
    await add_lead(ctx, "lee_one", status=LeadStatus.CONTACTED)

    body = await listing(authed, {"q": "kim"})

    assert body["total"] == 2
    assert body["status_counts"] == {"new": 1, "reviewed": 0, "contacted": 1, "excluded": 0}


# --- 목록: 상태 ---------------------------------------------------------------


@pytest.fixture
async def mixed_statuses(ctx) -> None:
    for number, status in enumerate(
        ["new", "new", "new", "reviewed", "reviewed", "contacted", "excluded"]
    ):
        await add_lead(ctx, f"{status}_{number}", status=status)


async def test_list_without_status_filter_counts_everyone(authed, mixed_statuses):
    body = await listing(authed)

    assert body["total"] == 7
    assert body["status_counts"] == {"new": 3, "reviewed": 2, "contacted": 1, "excluded": 1}


async def test_list_status_filter_keeps_counts_of_other_statuses(authed, mixed_statuses):
    body = await listing(authed, {"status": "reviewed"})

    assert {item["status"] for item in body["items"]} == {"reviewed"}
    assert body["total"] == 2
    assert body["status_counts"] == {"new": 3, "reviewed": 2, "contacted": 1, "excluded": 1}


async def test_list_status_filter_is_repeatable(authed, mixed_statuses):
    body = await listing(authed, [("status", "new"), ("status", "excluded"), ("status", "new")])

    assert {item["status"] for item in body["items"]} == {"new", "excluded"}
    assert body["total"] == 4
    assert len(body["items"]) == 4


async def test_list_status_filter_with_no_match(authed, ctx):
    await add_lead(ctx, "only_new")

    body = await listing(authed, {"status": "contacted"})

    assert body["items"] == []
    assert body["total"] == 0
    assert body["status_counts"] == {"new": 1, "reviewed": 0, "contacted": 0, "excluded": 0}


# --- 목록: 규칙·그룹·종류 -----------------------------------------------------


@pytest.fixture
async def detected(ctx) -> dict[str, int]:
    """keyword_room1 은 (키워드 규칙, 1번 방), activity_room2 는 (활동량 규칙, 2번 방),
    crossed 는 (키워드 규칙, 2번 방)과 (활동량 규칙, 1번 방) 에서 감지됐다."""
    room1, room2 = await add_group(ctx, "1번 방"), await add_group(ctx, "2번 방")
    keyword = await add_rule(ctx, "코인 문의")
    activity = await add_rule(ctx, "활발한 유저", RuleKind.ACTIVITY)
    await add_hit(ctx, await add_lead(ctx, "keyword_room1"), rule=keyword, group=room1)
    await add_hit(
        ctx,
        await add_lead(ctx, "activity_room2", status=LeadStatus.REVIEWED),
        rule=activity,
        group=room2,
    )
    crossed = await add_lead(ctx, "crossed")
    await add_hit(ctx, crossed, rule=keyword, group=room2)
    await add_hit(ctx, crossed, rule=activity, group=room1)
    await add_lead(ctx, "never_detected")
    return {"keyword": keyword.id, "activity": activity.id, "room1": room1.id, "room2": room2.id}


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"rule_id": "keyword"}, {"keyword_room1", "crossed"}),
        ({"rule_id": "activity"}, {"activity_room2", "crossed"}),
        ({"group_id": "room1"}, {"keyword_room1", "crossed"}),
        ({"group_id": "room2"}, {"activity_room2", "crossed"}),
        ({"kind": "keyword"}, {"keyword_room1", "crossed"}),
        ({"kind": "activity"}, {"activity_room2", "crossed"}),
        ({"rule_id": "keyword", "group_id": "room1"}, {"keyword_room1"}),
        ({"rule_id": "keyword", "group_id": "room2"}, {"crossed"}),
        ({"rule_id": "activity", "group_id": "room2", "kind": "activity"}, {"activity_room2"}),
        ({"rule_id": "keyword", "kind": "activity"}, set()),
    ],
)
async def test_list_hit_filters_match_within_one_hit(authed, detected, filters, expected):
    params = {key: value if key == "kind" else detected[value] for key, value in filters.items()}

    assert await found(authed, params) == expected


async def test_list_hit_filters_with_unknown_ids(authed, detected):
    assert await found(authed, {"rule_id": 999}) == set()
    assert await found(authed, {"group_id": 999}) == set()


async def test_list_hit_filter_counts_follow_the_filter(authed, detected):
    body = await listing(authed, {"kind": "activity", "status": "new"})

    assert [item["username"] for item in body["items"]] == ["crossed"]
    assert body["total"] == 1
    assert body["status_counts"] == {"new": 1, "reviewed": 1, "contacted": 0, "excluded": 0}


# --- 목록: 기간 ---------------------------------------------------------------


@pytest.fixture
async def around_midnight(ctx) -> None:
    """서울 시간 11월 15일의 시작과 끝 언저리에 마지막으로 감지된 유저들."""
    await add_lead(
        ctx, "nov14_last_second", last_seen_at=datetime(2026, 11, 14, 14, 59, 59, tzinfo=UTC)
    )
    await add_lead(ctx, "nov15_midnight", last_seen_at=datetime(2026, 11, 14, 15, 0, tzinfo=UTC))
    await add_lead(
        ctx,
        "nov15_last_moment",
        last_seen_at=datetime(2026, 11, 15, 14, 59, 59, 999999, tzinfo=UTC),
    )
    await add_lead(ctx, "nov16_midnight", last_seen_at=datetime(2026, 11, 15, 15, 0, tzinfo=UTC))


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"since": "2026-11-15"}, {"nov15_midnight", "nov15_last_moment", "nov16_midnight"}),
        ({"until": "2026-11-15"}, {"nov14_last_second", "nov15_midnight", "nov15_last_moment"}),
        ({"since": "2026-11-15", "until": "2026-11-15"}, {"nov15_midnight", "nov15_last_moment"}),
        ({"since": "2026-11-16", "until": "2026-11-15"}, set()),
        # 시간대가 없는 시각은 설정된 시간대(서울)로 본다.
        (
            {"since": "2026-11-15T00:00:00"},
            {"nov15_midnight", "nov15_last_moment", "nov16_midnight"},
        ),
        ({"until": "2026-11-15T00:00:00"}, {"nov14_last_second", "nov15_midnight"}),
        # 시간대가 붙은 시각은 그대로 쓴다. 경계는 포함한다.
        (
            {"since": "2026-11-14T15:00:00Z"},
            {"nov15_midnight", "nov15_last_moment", "nov16_midnight"},
        ),
        ({"since": "2026-11-15T00:00:01+09:00"}, {"nov15_last_moment", "nov16_midnight"}),
        ({"until": "2026-11-14T15:00:00+00:00"}, {"nov14_last_second", "nov15_midnight"}),
        ({"until": "2026-11-14T23:59:59+09:00"}, {"nov14_last_second"}),
        (
            {"since": "", "until": " "},
            {"nov14_last_second", "nov15_midnight", "nov15_last_moment", "nov16_midnight"},
        ),
    ],
)
async def test_list_period_uses_last_seen_in_seoul_time(authed, around_midnight, params, expected):
    assert await found(authed, params) == expected


async def test_list_period_follows_the_timezone_setting(authed, ctx, around_midnight):
    await ctx.settings.update(timezone="UTC")

    assert await found(authed, {"since": "2026-11-15"}) == {"nov15_last_moment", "nov16_midnight"}
    assert await found(authed, {"until": "2026-11-14"}) == {"nov14_last_second", "nov15_midnight"}


@pytest.mark.parametrize(
    "params",
    [
        {"since": "yesterday"},
        {"until": "2026-13-40"},
        {"since": "2026-11-15T25:00:00"},
        {"since": "0001-01-01"},
        {"until": "9999-12-31"},
        {"since": "1" * 41},
    ],
)
async def test_list_rejects_unreadable_period(authed, params):
    res = await authed.get("/api/leads", params=params)

    assert res.status_code == 422
    assert res.json()["code"] == "validation"


async def test_list_period_error_is_korean(authed):
    res = await authed.get("/api/leads", params={"since": "yesterday"})

    assert res.json()["detail"] == "날짜 형식을 다시 확인해 주세요."


# --- 목록: 정렬 ---------------------------------------------------------------


@pytest.fixture
async def sortable(ctx) -> None:
    await add_lead(
        ctx,
        "Bravo",
        last_seen_at=T0 + timedelta(hours=3),
        first_seen_at=T0 - timedelta(days=3),
        hit_count=5,
    )
    await add_lead(
        ctx,
        "alpha",
        last_seen_at=T0 + timedelta(hours=1),
        first_seen_at=T0 - timedelta(days=1),
        hit_count=9,
    )
    await add_lead(
        ctx,
        "charlie",
        last_seen_at=T0 + timedelta(hours=2),
        first_seen_at=T0 - timedelta(days=2),
        hit_count=1,
    )


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, ["Bravo", "charlie", "alpha"]),
        ({"sort": "last_seen"}, ["Bravo", "charlie", "alpha"]),
        ({"sort": "last_seen", "order": "desc"}, ["Bravo", "charlie", "alpha"]),
        ({"sort": "last_seen", "order": "asc"}, ["alpha", "charlie", "Bravo"]),
        ({"order": "asc"}, ["alpha", "charlie", "Bravo"]),
        ({"sort": "first_seen"}, ["alpha", "charlie", "Bravo"]),
        ({"sort": "first_seen", "order": "asc"}, ["Bravo", "charlie", "alpha"]),
        ({"sort": "hit_count"}, ["alpha", "Bravo", "charlie"]),
        ({"sort": "hit_count", "order": "asc"}, ["charlie", "Bravo", "alpha"]),
        ({"sort": "username", "order": "asc"}, ["alpha", "Bravo", "charlie"]),
        ({"sort": "username"}, ["charlie", "Bravo", "alpha"]),
    ],
)
async def test_list_sort(authed, sortable, params, expected):
    assert await ordered(authed, params) == expected


async def test_list_sort_breaks_ties_by_id(authed, ctx):
    for name in ("first", "second", "third"):
        await add_lead(ctx, name, hit_count=4)

    assert await ordered(authed, {"sort": "hit_count"}) == ["third", "second", "first"]
    assert await ordered(authed, {"sort": "hit_count", "order": "asc"}) == [
        "first",
        "second",
        "third",
    ]
    assert await ordered(authed) == ["third", "second", "first"]


# --- 목록: 쪽 나누기 ----------------------------------------------------------


@pytest.fixture
async def five_leads(ctx) -> None:
    for number in range(5):
        await add_lead(ctx, f"user_{number}", last_seen_at=T0 + timedelta(minutes=number))


async def test_list_pages(authed, five_leads):
    first = await listing(authed, {"page_size": 2})
    second = await listing(authed, {"page_size": 2, "page": 2})
    third = await listing(authed, {"page_size": 2, "page": 3})

    assert [item["username"] for item in first["items"]] == ["user_4", "user_3"]
    assert [item["username"] for item in second["items"]] == ["user_2", "user_1"]
    assert [item["username"] for item in third["items"]] == ["user_0"]
    assert (first["page"], first["page_size"], first["total"]) == (1, 2, 5)
    assert (third["page"], third["page_size"], third["total"]) == (3, 2, 5)


async def test_list_page_past_the_end_is_empty_but_counted(authed, five_leads):
    body = await listing(authed, {"page_size": 2, "page": 4})

    assert body["items"] == []
    assert body["total"] == 5
    assert body["page"] == 4
    assert body["status_counts"]["new"] == 5


async def test_list_pages_within_a_filter(authed, five_leads, ctx):
    await add_lead(
        ctx, "other_person", status=LeadStatus.CONTACTED, last_seen_at=T0 + timedelta(days=1)
    )

    body = await listing(authed, {"q": "user", "status": "new", "page_size": 3, "page": 2})

    assert [item["username"] for item in body["items"]] == ["user_1", "user_0"]
    assert body["total"] == 5


async def test_list_accepts_largest_page_size(authed, five_leads):
    body = await listing(authed, {"page_size": 200})

    assert body["page_size"] == 200
    assert len(body["items"]) == 5


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page": -1},
        {"page": "x"},
        {"page": 10**30},
        {"page_size": 0},
        {"page_size": 201},
        {"sort": "note"},
        {"order": "up"},
        {"status": "blocked"},
        {"kind": "mention"},
        {"rule_id": "abc"},
        {"group_id": 2**70},
        {"q": "가" * 201},
    ],
)
async def test_list_rejects_bad_query(authed, params):
    res = await authed.get("/api/leads", params=params)

    assert res.status_code == 422
    assert res.json()["code"] == "validation"


# --- 내보내기: CSV ------------------------------------------------------------


async def test_export_csv(authed, ctx, fixed_now):
    group = await add_group(ctx, "코인 수다방")
    keyword = await add_rule(ctx, "코인 문의")
    activity = await add_rule(ctx, "활발한 유저", RuleKind.ACTIVITY)
    plain = await add_lead(
        ctx,
        "kim_trader",
        first_name="민수",
        last_name="김",
        note="관심 많음, 다시 연락\n둘째 줄",
        hit_count=3,
        first_seen_at=datetime(2026, 11, 14, 15, 30, tzinfo=UTC),
        last_seen_at=datetime(2026, 11, 15, 0, 5, tzinfo=UTC),
    )
    await add_hit(ctx, plain, rule=keyword, group=group, excerpt='코인 "어디서" 사나요')
    chatty = await add_lead(
        ctx,
        "chatty_one",
        status=LeadStatus.REVIEWED,
        hit_count=1,
        first_seen_at=datetime(2026, 11, 13, 1, 0, tzinfo=UTC),
        last_seen_at=datetime(2026, 11, 14, 14, 59, tzinfo=UTC),
    )
    await add_hit(ctx, chatty, rule=activity, group=group, message_count=37, window_hours=24)
    no_excerpt = await add_lead(
        ctx,
        "no_excerpt",
        first_name="Jane",
        status=LeadStatus.CONTACTED,
        hit_count=2,
        last_seen_at=datetime(2026, 11, 12, 0, 0, tzinfo=UTC),
    )
    await add_hit(ctx, no_excerpt, rule=keyword, group=group, keywords=["코인", "선물"])
    await add_lead(
        ctx,
        "never_hit",
        status=LeadStatus.EXCLUDED,
        last_seen_at=datetime(2026, 11, 11, 0, 0, tzinfo=UTC),
    )

    res = await authed.get("/api/leads/export", params={"format": "csv"})

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "text/csv; charset=utf-8"
    assert (
        res.headers["content-disposition"]
        == 'attachment; filename="chatdb-leads-20261115-0930.csv"'
    )
    assert res.headers["cache-control"] == "no-store"
    assert res.content.startswith(BOM)
    assert not res.content.startswith(BOM + BOM)
    assert csv_rows(res.content) == [
        CSV_HEADER,
        [
            "kim_trader", "민수 김", "새로 수집됨", "3", "2026-11-15 00:30", "2026-11-15 09:05",
            "코인 문의", "코인 수다방", '코인 "어디서" 사나요', "관심 많음, 다시 연락\n둘째 줄",
        ],
        [
            "chatty_one", "", "확인함", "1", "2026-11-13 10:00", "2026-11-14 23:59",
            "활발한 유저", "코인 수다방", "24시간 동안 메시지 37개", "",
        ],
        [
            "no_excerpt", "Jane", "연락함", "2", "2026-11-10 12:00", "2026-11-12 09:00",
            "코인 문의", "코인 수다방", "코인, 선물", "",
        ],
        ["never_hit", "", "제외", "0", "2026-11-10 12:00", "2026-11-11 09:00", "", "", "", ""],
    ]  # fmt: skip


async def test_export_csv_neutralizes_formulas(authed, ctx):
    """그룹 이름·이름·글 내용은 남이 정한다. 스프레드시트가 수식으로 읽으면 안 된다."""
    equals = await add_lead(ctx, "equals", first_name='=HYPERLINK("http://evil.example","눌러")')
    await add_hit(
        ctx,
        equals,
        rule_name="-할인 문의",
        group_title="@promo 모임",
        excerpt="+82 10 1234 5678 연락 주세요",
    )
    await add_lead(ctx, "minus", last_name="-1+1", note="-메모")
    await add_lead(ctx, "plus", first_name="+SUM(A1:A9)", note="+메모")
    await add_lead(ctx, "at_sign", first_name="@cmd", note="@everyone")
    await add_lead(ctx, "tabbed", first_name="\t=1+1", note="\t탭으로 시작")
    await add_lead(ctx, "returned", first_name="\r=1+1", note="\r=cmd|' /C calc'!A0")
    await add_lead(ctx, "harmless", first_name="1+1=2", note="a=b, c-d, e@f")

    res = await authed.get("/api/leads/export", params={"format": "csv", "sort": "first_seen"})

    rows = {row[0]: row for row in csv_rows(res.content)[1:]}
    assert rows["equals"][1] == '\'=HYPERLINK("http://evil.example","눌러")'
    assert rows["equals"][6:9] == ["'-할인 문의", "'@promo 모임", "'+82 10 1234 5678 연락 주세요"]
    assert (rows["minus"][1], rows["minus"][9]) == ("'-1+1", "'-메모")
    assert (rows["plus"][1], rows["plus"][9]) == ("'+SUM(A1:A9)", "'+메모")
    assert (rows["at_sign"][1], rows["at_sign"][9]) == ("'@cmd", "'@everyone")
    assert (rows["tabbed"][1], rows["tabbed"][9]) == ("'\t=1+1", "'\t탭으로 시작")
    assert (rows["returned"][1], rows["returned"][9]) == ("'\r=1+1", "'\r=cmd|' /C calc'!A0")
    assert (rows["harmless"][1], rows["harmless"][9]) == ("1+1=2", "a=b, c-d, e@f")
    for row in rows.values():
        assert not any(cell.startswith(FORMULA_STARTS) for cell in row), row


async def test_export_csv_with_nothing_collected_has_only_the_header(authed, fixed_now):
    res = await authed.get("/api/leads/export")

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "text/csv; charset=utf-8"
    assert res.headers["content-disposition"].endswith('.csv"')
    assert csv_rows(res.content) == [CSV_HEADER]


async def test_export_follows_the_timezone_setting(authed, ctx, fixed_now):
    await ctx.settings.update(timezone="America/New_York")
    await add_lead(
        ctx,
        "kim_trader",
        first_seen_at=datetime(2026, 11, 14, 15, 30, tzinfo=UTC),
        last_seen_at=datetime(2026, 11, 15, 0, 5, tzinfo=UTC),
    )

    res = await authed.get("/api/leads/export", params={"format": "csv"})

    assert 'filename="chatdb-leads-20261114-1930.csv"' in res.headers["content-disposition"]
    assert csv_rows(res.content)[1][4:6] == ["2026-11-14 10:30", "2026-11-14 19:05"]


# --- 내보내기: TXT ------------------------------------------------------------


async def test_export_txt(authed, ctx, fixed_now):
    await add_lead(ctx, "older_one", last_seen_at=T0)
    await add_lead(ctx, "Newer_One", last_seen_at=T0 + timedelta(hours=1))
    await add_lead(ctx, "", last_seen_at=T0 + timedelta(hours=2))

    res = await authed.get("/api/leads/export", params={"format": "txt"})

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "text/plain; charset=utf-8"
    assert (
        res.headers["content-disposition"]
        == 'attachment; filename="chatdb-leads-20261115-0930.txt"'
    )
    assert res.content == b"@Newer_One\n@older_one\n"


async def test_export_txt_with_nothing_collected_is_empty(authed):
    res = await authed.get("/api/leads/export", params={"format": "txt"})

    assert res.status_code == 200, res.text
    assert res.content == b""


# --- 내보내기: 필터와 고르기 --------------------------------------------------


async def test_export_applies_filters_and_sort(authed, detected):
    by_rule = await authed.get(
        "/api/leads/export",
        params={
            "format": "txt",
            "rule_id": detected["keyword"],
            "sort": "username",
            "order": "asc",
        },
    )
    by_status = await authed.get(
        "/api/leads/export", params={"format": "csv", "status": "reviewed"}
    )
    by_search = await authed.get(
        "/api/leads/export", params={"format": "txt", "q": "@never", "kind": "keyword"}
    )

    assert by_rule.text == "@crossed\n@keyword_room1\n"
    assert [row[0] for row in csv_rows(by_status.content)[1:]] == ["activity_room2"]
    assert by_search.text == ""


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"rule_id": "keyword"}, ["crossed", "keyword_room1"]),
        ({"group_id": "room2"}, ["activity_room2", "crossed"]),
        ({"kind": "activity"}, ["activity_room2", "crossed"]),
        ({"rule_id": "keyword", "group_id": "room1"}, ["keyword_room1"]),
        ({"rule_id": "keyword", "kind": "activity"}, []),
    ],
)
async def test_export_csv_applies_hit_filters(authed, detected, filters, expected):
    """CSV 는 최근 감지를 함께 읽는다. 그 조인과 감지 필터가 서로 섞이면 안 된다."""
    params = {key: value if key == "kind" else detected[value] for key, value in filters.items()}

    res = await authed.get(
        "/api/leads/export", params={**params, "format": "csv", "sort": "username", "order": "asc"}
    )

    assert res.status_code == 200, res.text
    rows = csv_rows(res.content)[1:]
    assert [row[0] for row in rows] == expected
    if "crossed" in expected:
        # crossed 의 최근 감지는 (활발한 유저, 1번 방) 이다. 필터가 무엇이든 최근 감지를 그대로 보여 준다.
        crossed = next(row for row in rows if row[0] == "crossed")
        assert crossed[6:8] == ["활발한 유저", "1번 방"]


async def test_export_applies_period(authed, around_midnight):
    res = await authed.get(
        "/api/leads/export",
        params={"format": "txt", "since": "2026-11-15", "until": "2026-11-15", "order": "asc"},
    )

    assert res.text == "@nov15_midnight\n@nov15_last_moment\n"


async def test_export_chosen_ids_ignores_filters(authed, ctx):
    first = await add_lead(ctx, "first_pick", status=LeadStatus.EXCLUDED, last_seen_at=T0)
    await add_lead(ctx, "not_picked", last_seen_at=T0 + timedelta(hours=1))
    third = await add_lead(ctx, "third_pick", last_seen_at=T0 + timedelta(hours=2))

    res = await authed.get(
        "/api/leads/export",
        params={
            "format": "txt",
            "ids": f"{first.id}, {third.id},{first.id},99999",
            "status": "contacted",
            "q": "nobody",
            "rule_id": 12345,
            "since": "2030-01-01",
        },
    )

    assert res.status_code == 200, res.text
    assert res.text == "@third_pick\n@first_pick\n"


async def test_export_chosen_ids_as_csv_in_requested_order(authed, ctx):
    first = await add_lead(ctx, "bravo", last_seen_at=T0 + timedelta(hours=5))
    second = await add_lead(ctx, "alpha", last_seen_at=T0)
    await add_lead(ctx, "not_picked")

    res = await authed.get(
        "/api/leads/export",
        params={"ids": f"{first.id},{second.id}", "sort": "username", "order": "asc"},
    )

    assert [row[0] for row in csv_rows(res.content)] == ["아이디", "alpha", "bravo"]


@pytest.mark.parametrize(
    ("ids", "detail"),
    [
        ("", "내보낼 유저를 골라 주세요."),
        (" , ,", "내보낼 유저를 골라 주세요."),
        ("abc", "내보낼 유저 번호를 다시 확인해 주세요."),
        ("1,two,3", "내보낼 유저 번호를 다시 확인해 주세요."),
        ("-1", "내보낼 유저 번호를 다시 확인해 주세요."),
        ("1.5", "내보낼 유저 번호를 다시 확인해 주세요."),
        ("1_000", "내보낼 유저 번호를 다시 확인해 주세요."),
        ("１２", "내보낼 유저 번호를 다시 확인해 주세요."),
        (str(2**70), "내보낼 유저 번호를 다시 확인해 주세요."),
        (",".join(str(n) for n in range(1, 5002)), "한 번에 5,000명까지 골라서 내보낼 수 있어요."),
    ],
)
async def test_export_rejects_bad_ids(authed, ctx, ids, detail):
    await add_lead(ctx, "kim_trader")

    res = await authed.get("/api/leads/export", params={"format": "txt", "ids": ids})

    assert res.status_code == 422
    assert res.json() == {"detail": detail, "code": "validation", "retry_after": None}


@pytest.mark.parametrize(
    "params", [{"format": "xlsx"}, {"format": ""}, {"since": "soon"}, {"status": "blocked"}]
)
async def test_export_rejects_bad_query(authed, params):
    res = await authed.get("/api/leads/export", params=params)

    assert res.status_code == 422


async def test_export_has_no_page_limit(authed, ctx):
    count = 2345
    async with ctx.db.session() as session:
        session.add_all(
            Lead(
                tg_user_id=900_000 + number,
                username=f"bulk_{number:04d}",
                first_kind=RuleKind.KEYWORD,
                last_seen_at=T0 + timedelta(seconds=number),
            )
            for number in range(count)
        )
        await session.commit()

    as_txt = await authed.get("/api/leads/export", params={"format": "txt", "order": "asc"})
    as_csv = await authed.get("/api/leads/export", params={"format": "csv", "order": "asc"})

    lines = as_txt.text.splitlines()
    assert len(lines) == count
    assert (lines[0], lines[-1]) == ("@bulk_0000", "@bulk_2344")
    rows = csv_rows(as_csv.content)
    assert len(rows) == count + 1
    assert [row[0] for row in rows[1:]] == [f"bulk_{number:04d}" for number in range(count)]


async def test_export_reads_everything_in_one_query(authed, ctx, statements):
    for number in range(5):
        await add_hit(ctx, await add_lead(ctx, f"user_{number}"))
    statements.clear()

    await authed.get("/api/leads/export", params={"format": "csv"})

    assert len([sql for sql in statements if "FROM leads" in sql]) == 1
    assert not [sql for sql in statements if "FROM hits" in sql]


# --- 상세 --------------------------------------------------------------------


async def test_detail(authed, ctx):
    lead = await add_lead(ctx, "kim_trader", first_name="민수", hit_count=4)
    await add_hit(ctx, lead, group_title="가 방", created_at=T0, excerpt="첫 글")
    await add_hit(ctx, lead, group_title="나 방", created_at=T0 + timedelta(hours=1))
    await add_hit(ctx, lead, group_title="가 방", created_at=T0 + timedelta(hours=3))
    await add_hit(ctx, lead, group_title=None, created_at=T0 + timedelta(hours=4))
    last = await add_hit(
        ctx,
        lead,
        group_title="다 방",
        kind=RuleKind.ACTIVITY,
        rule_name="활발한 유저",
        message_count=40,
        window_hours=12,
        created_at=T0 + timedelta(hours=2),
    )
    other = await add_lead(ctx, "someone_else")
    await add_hit(ctx, other, group_title="남의 방", created_at=T0 + timedelta(days=1))

    res = await authed.get(f"/api/leads/{lead.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == lead.id
    assert body["username"] == "kim_trader"
    assert body["display_name"] == "민수"
    assert body["hit_count"] == 4
    assert body["last_hit"]["id"] == last.id
    assert body["last_hit"]["message_count"] == 40
    assert [hit["group_title"] for hit in body["hits"]] == [
        None,
        "가 방",
        "다 방",
        "나 방",
        "가 방",
    ]
    assert body["hits"][-1]["excerpt"] == "첫 글"
    assert body["group_titles"] == ["가 방", "다 방", "나 방"]


async def test_detail_shows_latest_hundred_hits(authed, ctx):
    lead = await add_lead(ctx, "busy_one")
    async with ctx.db.session() as session:
        session.add_all(
            Hit(
                lead_id=lead.id,
                kind=RuleKind.KEYWORD,
                rule_name="코인 문의",
                group_title=f"방 {number % 3}",
                excerpt=f"글 {number}",
                created_at=T0 + timedelta(minutes=number),
            )
            for number in range(105)
        )
        await session.commit()

    res = await authed.get(f"/api/leads/{lead.id}")

    hits = res.json()["hits"]
    assert len(hits) == 100
    assert [hit["excerpt"] for hit in hits[:3]] == ["글 104", "글 103", "글 102"]
    assert hits[-1]["excerpt"] == "글 5"
    assert res.json()["group_titles"] == ["방 2", "방 1", "방 0"]


async def test_detail_orders_same_moment_hits_by_id(authed, ctx):
    lead = await add_lead(ctx, "kim_trader")
    first = await add_hit(ctx, lead, group_title="먼저", created_at=T0)
    second = await add_hit(ctx, lead, group_title="나중", created_at=T0)

    res = await authed.get(f"/api/leads/{lead.id}")

    assert [hit["id"] for hit in res.json()["hits"]] == [second.id, first.id]
    assert res.json()["group_titles"] == ["나중", "먼저"]


async def test_detail_without_hits(authed, ctx):
    lead = await add_lead(ctx, "quiet_one")

    res = await authed.get(f"/api/leads/{lead.id}")

    assert res.status_code == 200, res.text
    assert res.json()["hits"] == []
    assert res.json()["group_titles"] == []
    assert res.json()["last_hit"] is None


async def test_detail_unknown_lead(authed):
    res = await authed.get("/api/leads/999")

    assert res.status_code == 404
    assert res.json() == {
        "detail": "수집된 유저를 찾을 수 없어요.",
        "code": "not_found",
        "retry_after": None,
    }


@pytest.mark.parametrize("lead_id", ["abc", str(2**70), "1.5"])
async def test_rejects_bad_lead_id(authed, lead_id):
    assert (await authed.get(f"/api/leads/{lead_id}")).status_code == 422
    assert (await authed.patch(f"/api/leads/{lead_id}", json={})).status_code == 422
    assert (await authed.delete(f"/api/leads/{lead_id}")).status_code == 422


# --- 고치기 ------------------------------------------------------------------


async def test_patch_status_only(authed, ctx):
    lead = await add_lead(ctx, "kim_trader", note="그대로 둘 메모", hit_count=3)
    hit = await add_hit(ctx, lead, excerpt="코인 사요")

    res = await authed.patch(f"/api/leads/{lead.id}", json={"status": "contacted"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "contacted"
    assert body["note"] == "그대로 둘 메모"
    assert body["hit_count"] == 3
    assert body["last_hit"]["id"] == hit.id
    stored = await get_lead(ctx, lead.id)
    assert stored is not None
    assert (stored.status, stored.note) == ("contacted", "그대로 둘 메모")


async def test_patch_note_only(authed, ctx):
    lead = await add_lead(ctx, "kim_trader", status=LeadStatus.REVIEWED)

    res = await authed.patch(f"/api/leads/{lead.id}", json={"note": "  내일 다시 연락  "})

    assert res.status_code == 200, res.text
    assert res.json()["note"] == "내일 다시 연락"
    assert res.json()["status"] == "reviewed"


@pytest.mark.parametrize("note", ["", "   ", None])
async def test_patch_clears_note(authed, ctx, note):
    lead = await add_lead(ctx, "kim_trader", note="지울 메모")

    res = await authed.patch(f"/api/leads/{lead.id}", json={"note": note})

    assert res.status_code == 200, res.text
    assert res.json()["note"] is None
    stored = await get_lead(ctx, lead.id)
    assert stored is not None
    assert stored.note is None


@pytest.mark.parametrize("body", [{}, {"status": None}])
async def test_patch_without_changes(authed, ctx, invalidations, body):
    lead = await add_lead(ctx, "kim_trader", note="메모", status=LeadStatus.REVIEWED)

    res = await authed.patch(f"/api/leads/{lead.id}", json=body)

    assert res.status_code == 200, res.text
    assert (res.json()["status"], res.json()["note"]) == ("reviewed", "메모")
    assert invalidations == []


@pytest.mark.parametrize(
    ("before", "after", "collector_told"),
    [
        ("new", "reviewed", False),
        ("reviewed", "contacted", False),
        ("contacted", "new", False),
        ("new", "excluded", True),
        ("contacted", "excluded", True),
        ("excluded", "new", True),
        ("excluded", "reviewed", True),
        ("excluded", "excluded", False),
        ("new", "new", False),
    ],
)
async def test_patch_tells_collector_when_exclusion_changes(
    authed, ctx, invalidations, before, after, collector_told
):
    lead = await add_lead(ctx, "kim_trader", status=before)

    res = await authed.patch(f"/api/leads/{lead.id}", json={"status": after, "note": "메모"})

    assert res.status_code == 200, res.text
    assert res.json()["status"] == after
    assert len(invalidations) == (1 if collector_told else 0)


async def test_patch_response_shows_what_the_collector_changed_meanwhile(authed, ctx, monkeypatch):
    database_file = ctx.config.data_dir / "chatdb.sqlite3"
    lead = await add_lead(ctx, "kim_trader", hit_count=1)

    def detect_again() -> None:
        with closing(sqlite3.connect(database_file)) as conn, conn:
            conn.execute("UPDATE leads SET hit_count = 77, first_name = '새 이름'")

    monkeypatch.setattr(ctx.collector, "invalidate", detect_again)

    res = await authed.patch(f"/api/leads/{lead.id}", json={"status": "excluded"})

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "excluded"
    assert res.json()["hit_count"] == 77
    assert res.json()["display_name"] == "새 이름"


async def test_patch_unknown_lead(authed, invalidations):
    res = await authed.patch("/api/leads/999", json={"status": "excluded"})

    assert res.status_code == 404
    assert res.json()["detail"] == "수집된 유저를 찾을 수 없어요."
    assert invalidations == []


@pytest.mark.parametrize("body", [{"status": "blocked"}, {"note": "가" * 2001}, {"note": 5}])
async def test_patch_rejects_malformed_body(authed, ctx, invalidations, body):
    lead = await add_lead(ctx, "kim_trader")

    res = await authed.patch(f"/api/leads/{lead.id}", json=body)

    assert res.status_code == 422
    assert invalidations == []


# --- 일괄 처리 ----------------------------------------------------------------


async def bulk(client, ids: list[int], action: str, status: str | None = None):
    payload: dict[str, Any] = {"ids": ids, "action": action}
    if status is not None:
        payload["status"] = status
    return await client.post("/api/leads/bulk", json=payload)


async def test_bulk_set_status(authed, ctx, invalidations):
    first = await add_lead(ctx, "first")
    second = await add_lead(ctx, "second", status=LeadStatus.REVIEWED)
    await add_lead(ctx, "bystander")

    res = await bulk(authed, [first.id, second.id, first.id, 99999], "set_status", "contacted")

    assert res.status_code == 200, res.text
    assert res.json() == {"affected": 2}
    assert await lead_statuses(ctx) == {
        "first": "contacted",
        "second": "contacted",
        "bystander": "new",
    }
    assert invalidations == []


@pytest.mark.parametrize(
    ("before", "after", "collector_told"),
    [
        (["new", "reviewed"], "excluded", True),
        (["excluded", "excluded"], "excluded", False),
        (["new", "excluded"], "excluded", True),
        (["new", "excluded"], "reviewed", True),
        (["excluded", "excluded"], "new", True),
        (["new", "contacted"], "reviewed", False),
    ],
)
async def test_bulk_set_status_tells_collector_when_exclusion_changes(
    authed, ctx, invalidations, before, after, collector_told
):
    leads = [await add_lead(ctx, f"user_{n}", status=status) for n, status in enumerate(before)]

    res = await bulk(authed, [lead.id for lead in leads], "set_status", after)

    assert res.json() == {"affected": 2}
    assert set((await lead_statuses(ctx)).values()) == {after}
    assert len(invalidations) == (1 if collector_told else 0)


async def test_bulk_delete(authed, ctx, invalidations):
    first, second = await add_lead(ctx, "first"), await add_lead(ctx, "second")
    kept = await add_lead(ctx, "kept")
    for lead in (first, first, second, kept):
        await add_hit(ctx, lead)

    res = await bulk(authed, [second.id, first.id, 99999], "delete")

    assert res.status_code == 200, res.text
    assert res.json() == {"affected": 2}
    assert await lead_statuses(ctx) == {"kept": "new"}
    assert await hit_count(ctx) == 1
    assert invalidations == [None]


async def test_bulk_delete_ignores_status_field(authed, ctx):
    lead = await add_lead(ctx, "first")

    res = await bulk(authed, [lead.id], "delete", "contacted")

    assert res.json() == {"affected": 1}
    assert await lead_statuses(ctx) == {}


async def test_bulk_block(authed, ctx, invalidations):
    first = await add_lead(ctx, "Kim_Trader", status=LeadStatus.CONTACTED)
    second = await add_lead(ctx, "PROMO_bot")
    already_listed = await add_lead(ctx, "Old_Spam")
    same_name = await add_lead(ctx, "kim_trader")
    await add_lead(ctx, "bystander")
    async with ctx.db.session() as session:
        session.add(BlocklistEntry(username="old_spam", note="예전에 넣은 것"))
        await session.commit()

    res = await bulk(authed, [first.id, second.id, already_listed.id, same_name.id, 99999], "block")

    assert res.status_code == 200, res.text
    assert res.json() == {"affected": 4}
    assert await lead_statuses(ctx) == {
        "Kim_Trader": "excluded",
        "PROMO_bot": "excluded",
        "Old_Spam": "excluded",
        "kim_trader": "excluded",
        "bystander": "new",
    }
    assert await blocked_usernames(ctx) == ["old_spam", "kim_trader", "promo_bot"]
    assert invalidations == [None]

    listed = await authed.get("/api/blocklist")
    assert {entry["username"] for entry in listed.json()} == {"old_spam", "kim_trader", "promo_bot"}


async def test_bulk_block_twice_does_not_duplicate(authed, ctx):
    lead = await add_lead(ctx, "Kim_Trader")

    first = await bulk(authed, [lead.id], "block")
    second = await bulk(authed, [lead.id], "block", "new")

    assert first.json() == second.json() == {"affected": 1}
    assert await blocked_usernames(ctx) == ["kim_trader"]
    assert await lead_statuses(ctx) == {"Kim_Trader": "excluded"}


async def test_bulk_block_skips_empty_usernames(authed, ctx):
    lead = await add_lead(ctx, "")

    res = await bulk(authed, [lead.id], "block")

    assert res.json() == {"affected": 1}
    assert await blocked_usernames(ctx) == []
    assert await lead_statuses(ctx) == {"": "excluded"}


@pytest.mark.parametrize("action", ["set_status", "delete", "block"])
async def test_bulk_with_no_existing_lead_changes_nothing(authed, ctx, invalidations, action):
    await add_lead(ctx, "bystander")

    res = await bulk(authed, [99999, 0, -5, 2**70], action, "excluded")

    assert res.status_code == 200, res.text
    assert res.json() == {"affected": 0}
    assert await lead_statuses(ctx) == {"bystander": "new"}
    assert await blocked_usernames(ctx) == []
    assert invalidations == []


async def test_bulk_accepts_five_thousand_ids(authed, ctx):
    leads = [await add_lead(ctx, f"user_{number}") for number in range(3)]
    ids = [lead.id for lead in leads] + list(range(100_000, 104_997))

    res = await bulk(authed, ids, "set_status", "reviewed")

    assert len(ids) == 5000
    assert res.status_code == 200, res.text
    assert res.json() == {"affected": 3}


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"ids": [1], "action": "set_status"}, "바꿀 상태를 골라 주세요."),
        ({"ids": [1], "action": "set_status", "status": None}, "바꿀 상태를 골라 주세요."),
        ({"ids": [], "action": "delete"}, None),
        ({"ids": list(range(1, 5002)), "action": "delete"}, None),
        ({"ids": [1], "action": "archive"}, None),
        ({"ids": [1], "action": "set_status", "status": "blocked"}, None),
        ({"ids": ["x"], "action": "delete"}, None),
        ({"action": "delete"}, None),
        ({"ids": [1]}, None),
    ],
)
async def test_bulk_rejects_malformed_body(authed, ctx, invalidations, payload, detail):
    await add_lead(ctx, "bystander")

    res = await authed.post("/api/leads/bulk", json=payload)

    assert res.status_code == 422
    assert res.json()["code"] == "validation"
    if detail is not None:
        assert res.json()["detail"] == detail
    assert await lead_statuses(ctx) == {"bystander": "new"}
    assert invalidations == []


# --- 지우기 ------------------------------------------------------------------


async def test_delete_removes_lead_and_its_hits(authed, ctx, invalidations):
    lead, kept = await add_lead(ctx, "kim_trader"), await add_lead(ctx, "kept")
    for owner in (lead, lead, kept):
        await add_hit(ctx, owner)

    res = await authed.delete(f"/api/leads/{lead.id}")

    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True}
    assert await lead_statuses(ctx) == {"kept": "new"}
    assert await hit_count(ctx) == 1
    assert invalidations == [None]
    assert (await authed.get(f"/api/leads/{lead.id}")).status_code == 404


async def test_delete_unknown_lead(authed, ctx, invalidations):
    await add_lead(ctx, "kept")

    res = await authed.delete("/api/leads/999")

    assert res.status_code == 404
    assert res.json()["detail"] == "수집된 유저를 찾을 수 없어요."
    assert await lead_statuses(ctx) == {"kept": "new"}
    assert invalidations == []


# --- 수집기와 맞물림 ----------------------------------------------------------


async def test_collector_is_told_only_after_commit(authed, ctx, monkeypatch):
    """커밋보다 먼저 캐시를 버리면 수집기가 예전 제외 상태를 다시 읽어 버린다."""
    database_file = ctx.config.data_dir / "chatdb.sqlite3"
    committed: list[tuple[dict[str, str], list[str]]] = []

    def probe() -> None:
        with closing(sqlite3.connect(database_file)) as conn:
            statuses = dict(conn.execute("SELECT username, status FROM leads").fetchall())
            blocked = [row[0] for row in conn.execute("SELECT username FROM blocklist")]
        committed.append((statuses, blocked))

    monkeypatch.setattr(ctx.collector, "invalidate", probe)
    one, two, three = [await add_lead(ctx, name) for name in ("one", "two", "three")]

    await authed.patch(f"/api/leads/{one.id}", json={"status": "excluded"})
    await bulk(authed, [two.id], "set_status", "excluded")
    await bulk(authed, [three.id], "block")
    await bulk(authed, [one.id], "delete")
    await authed.delete(f"/api/leads/{two.id}")

    assert committed == [
        ({"one": "excluded", "two": "new", "three": "new"}, []),
        ({"one": "excluded", "two": "excluded", "three": "new"}, []),
        ({"one": "excluded", "two": "excluded", "three": "excluded"}, ["three"]),
        ({"two": "excluded", "three": "excluded"}, ["three"]),
        ({"three": "excluded"}, ["three"]),
    ]


# --- 실제 수집기와 끝까지 -----------------------------------------------------


async def add_chat(ctx, title: str, chat_id: int) -> Group:
    """수집기가 메시지를 받을 수 있는, 텔레그램 채팅 id 가 붙은 그룹."""
    group = await add_group(ctx, title)
    async with ctx.db.session() as session:
        stored = await session.get(Group, group.id)
        assert stored is not None
        stored.tg_chat_id = chat_id
        await session.commit()
        return stored


async def say(ctx, group: Group, sender: TgUser, text: str) -> None:
    """그룹에 새 글이 올라온 것처럼 수집기에 넘긴다."""
    message = IncomingMessage(
        account_id=group.account_id,
        chat_id=group.tg_chat_id,
        message_id=next(_message_ids),
        sender=sender,
        text=text,
        date=datetime.now(UTC),
    )
    await ctx.collector.handle(message, group.id)


async def test_collected_lead_shows_up_everywhere(authed, ctx):
    room = await add_chat(ctx, "코인 수다방", -1001000000001)
    created = await authed.post(
        "/api/rules", json={"name": "코인 문의", "kind": "keyword", "keywords": ["코인"]}
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    await say(
        ctx, room, TgUser(id=42, username="Kim_Trader", first_name="민수"), "코인 어디서 사요?"
    )

    body = await listing(authed, {"q": "@kim_trader", "rule_id": rule_id, "group_id": room.id})
    assert body["total"] == 1
    lead = body["items"][0]
    assert (lead["username"], lead["display_name"], lead["status"]) == ("Kim_Trader", "민수", "new")
    assert lead["hit_count"] == 1
    assert lead["last_hit"]["rule_id"] == rule_id
    assert lead["last_hit"]["group_title"] == "코인 수다방"
    assert lead["last_hit"]["keywords"] == ["코인"]
    assert lead["last_hit"]["excerpt"] == "코인 어디서 사요?"

    detail = await authed.get(f"/api/leads/{lead['id']}")
    assert [hit["id"] for hit in detail.json()["hits"]] == [lead["last_hit"]["id"]]
    assert detail.json()["group_titles"] == ["코인 수다방"]

    exported = await authed.get("/api/leads/export", params={"format": "txt"})
    assert exported.text == "@Kim_Trader\n"

    rules = await authed.get("/api/rules")
    assert (rules.json()[0]["lead_count"], rules.json()[0]["hit_count"]) == (1, 1)
    assert rules.json()[0]["last_hit_at"] == lead["last_hit"]["created_at"]

    summary = (await authed.get("/api/overview")).json()
    assert summary["total_leads"] == 1
    # 자정을 막 넘기는 순간에 돌아도 흔들리지 않게 오늘과 어제를 함께 본다.
    assert summary["today_new"] + summary["yesterday_new"] == 1
    assert sum(point["keyword"] for point in summary["series"][-2:]) == 1
    assert summary["top_groups"] == [{"group_id": room.id, "title": "코인 수다방", "leads": 1}]
    assert summary["rule_totals"][0]["leads"] == 1
    assert [(item["username"], item["is_new_lead"]) for item in summary["recent_hits"]] == [
        ("Kim_Trader", True)
    ]


async def test_exclusion_and_blocklist_reach_the_real_collector(authed, ctx):
    """같은 (유저, 규칙, 그룹)은 한동안 다시 기록되지 않으므로 매번 다른 그룹에서 말하게 한다."""
    rooms = [await add_chat(ctx, f"{n}번 방", -1001000000100 - n) for n in range(1, 7)]
    created = await authed.post(
        "/api/rules", json={"name": "코인 문의", "kind": "keyword", "keywords": ["코인"]}
    )
    rule_id = created.json()["id"]
    kim = TgUser(id=42, username="Kim_Trader")
    promo = TgUser(id=43, username="Promo_Bot_Guy")

    async def collected() -> dict[str, int]:
        body = await listing(authed)
        return {item["username"]: item["hit_count"] for item in body["items"]}

    await say(ctx, rooms[0], kim, "코인 삽니다")
    assert await collected() == {"Kim_Trader": 1}
    kim_id = (await listing(authed))["items"][0]["id"]

    # 제외 상태로 바꾸면 다른 그룹에서 걸려도 기록하지 않는다.
    await authed.patch(f"/api/leads/{kim_id}", json={"status": "excluded"})
    await say(ctx, rooms[1], kim, "코인 또 삽니다")
    assert await collected() == {"Kim_Trader": 1}

    # 되돌리면 다시 기록한다.
    await bulk(authed, [kim_id], "set_status", "reviewed")
    await say(ctx, rooms[2], kim, "코인 계속 삽니다")
    assert await collected() == {"Kim_Trader": 2}

    # 제외 목록에 있는 아이디는 대소문자가 달라도 처음부터 수집하지 않는다.
    added = await authed.post("/api/blocklist", json={"usernames": ["@promo_bot_guy"]})
    await say(ctx, rooms[0], promo, "코인 홍보합니다")
    assert await collected() == {"Kim_Trader": 2}

    # 목록에서 빼면 수집한다.
    await authed.delete(f"/api/blocklist/{added.json()[0]['id']}")
    await say(ctx, rooms[1], promo, "코인 홍보 한 번 더")
    assert await collected() == {"Kim_Trader": 2, "Promo_Bot_Guy": 1}

    # 수집함에서 차단하면 제외 목록에도 올라가 더는 기록하지 않는다.
    promo_id = next(
        item["id"]
        for item in (await listing(authed))["items"]
        if item["username"] == "Promo_Bot_Guy"
    )
    await bulk(authed, [promo_id], "block")
    await say(ctx, rooms[2], promo, "코인 홍보 또")
    assert await collected() == {"Kim_Trader": 2, "Promo_Bot_Guy": 1}

    # 차단한 유저를 지워도 제외 목록에 남아 있어 다시 수집하지 않는다.
    await authed.delete(f"/api/leads/{promo_id}")
    await say(ctx, rooms[3], promo, "코인 홍보 마지막")
    assert await collected() == {"Kim_Trader": 2}

    # 제외 상태였던 유저를 지우면(제외 목록에는 없으므로) 새로 수집한다.
    await authed.patch(f"/api/leads/{kim_id}", json={"status": "excluded"})
    await bulk(authed, [kim_id], "delete")
    await say(ctx, rooms[3], kim, "코인 다시 왔어요")
    assert await collected() == {"Kim_Trader": 1}

    # 규칙을 끄거나 지우면 걸리지 않는다.
    await authed.patch(f"/api/rules/{rule_id}", json={"enabled": False})
    await say(ctx, rooms[4], kim, "코인 꺼진 규칙")
    assert await collected() == {"Kim_Trader": 1}
    await authed.patch(f"/api/rules/{rule_id}", json={"enabled": True, "keywords": ["선물"]})
    await say(ctx, rooms[4], kim, "코인 말고 선물 얘기")
    assert await collected() == {"Kim_Trader": 2}
    await authed.delete(f"/api/rules/{rule_id}")
    await say(ctx, rooms[5], kim, "선물 얘기 계속")
    assert await collected() == {"Kim_Trader": 2}
