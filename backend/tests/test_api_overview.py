"""/api/overview 테스트."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, event

from app.models import (
    Account,
    AccountStatus,
    Group,
    GroupStatus,
    Hit,
    Lead,
    LeadStatus,
    Rule,
    RuleKind,
)

NOON_NOV15_SEOUL = datetime(2026, 11, 15, 3, 0, tzinfo=UTC)
"""기본 '지금'. 서울 시간으로 2026-11-15 12:00 이다."""

_user_ids = itertools.count(7000)


def utc(month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0, micro: int = 0):
    return datetime(2026, month, day, hour, minute, second, micro, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch) -> dict[str, datetime]:
    """개요가 보는 '지금'. clock["now"] 를 바꾸면 그 시각이 된다."""
    state = {"now": NOON_NOV15_SEOUL}
    monkeypatch.setattr("app.routers.overview.utcnow", lambda: state["now"])
    return state


# --- 심어 두기 ----------------------------------------------------------------


async def add_account(ctx, **fields: Any) -> Account:
    values: dict[str, Any] = {"status": AccountStatus.ACTIVE}
    values.update(fields)
    async with ctx.db.session() as session:
        account = Account(**values)
        session.add(account)
        await session.commit()
        return account


async def add_group(ctx, account: Account, **fields: Any) -> Group:
    values: dict[str, Any] = {"status": GroupStatus.JOINED}
    values.update(fields)
    async with ctx.db.session() as session:
        group = Group(account_id=account.id, **values)
        session.add(group)
        await session.commit()
        return group


async def add_rule(ctx, name: str, kind: RuleKind = RuleKind.KEYWORD, **fields: Any) -> Rule:
    async with ctx.db.session() as session:
        rule = Rule(name=name, kind=kind, keywords=["코인"], **fields)
        session.add(rule)
        await session.commit()
        return rule


async def add_lead(
    ctx, first_seen_at: datetime, kind: str = "keyword", username: str | None = None
) -> Lead:
    number = next(_user_ids)
    async with ctx.db.session() as session:
        lead = Lead(
            tg_user_id=number,
            username=username or f"user_{number}",
            first_kind=kind,
            first_seen_at=first_seen_at,
            last_seen_at=first_seen_at,
        )
        session.add(lead)
        await session.commit()
        return lead


async def add_leads(ctx, count: int) -> list[Lead]:
    return [await add_lead(ctx, utc(10, 1)) for _ in range(count)]


async def add_hit(
    ctx,
    lead: Lead,
    created_at: datetime,
    *,
    rule: Rule | None = None,
    group: Group | None = None,
    **fields: Any,
) -> Hit:
    values: dict[str, Any] = {
        "kind": rule.kind if rule else RuleKind.KEYWORD,
        "rule_name": rule.name if rule else "코인 문의",
        "group_title": group.title if group else None,
    }
    values.update(fields)
    async with ctx.db.session() as session:
        hit = Hit(
            lead_id=lead.id,
            rule_id=rule.id if rule else None,
            group_id=group.id if group else None,
            created_at=created_at,
            **values,
        )
        session.add(hit)
        await session.commit()
        return hit


async def overview(client, params: Any = None) -> dict[str, Any]:
    res = await client.get("/api/overview", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def by_date(body: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """날짜 → (키워드로 처음 수집된 수, 활동량으로 처음 수집된 수)."""
    return {point["date"]: (point["keyword"], point["activity"]) for point in body["series"]}


def dates(body: dict[str, Any]) -> list[str]:
    return [point["date"] for point in body["series"]]


# --- 로그인 필요 --------------------------------------------------------------


async def test_requires_login(client):
    res = await client.get("/api/overview")

    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"


# --- 빈 상태 -----------------------------------------------------------------


async def test_empty_console(authed, clock):
    body = await overview(authed)

    assert body == {
        "today_new": 0,
        "yesterday_new": 0,
        "total_leads": 0,
        "accounts_connected": 0,
        "accounts_total": 0,
        "groups_monitoring": 0,
        "groups_capacity": 0,
        "join_requests_pending": 0,
        "join_queue": 0,
        "series": [
            {"date": f"2026-11-{day:02d}", "keyword": 0, "activity": 0} for day in range(9, 16)
        ],
        "top_groups": [],
        "rule_totals": [],
        "accounts": [],
        "recent_hits": [],
    }


# --- 날짜 경계 (서울) ---------------------------------------------------------


@pytest.fixture
async def around_midnights(ctx) -> None:
    """서울 시간 자정 언저리에 처음 수집된 유저들. 주석은 서울 시간이다."""
    await add_lead(ctx, utc(11, 14, 15, 0, 0), "keyword")  # 11-15 00:00:00 → 오늘의 첫 순간
    await add_lead(ctx, utc(11, 15, 2, 59), "activity")  # 11-15 11:59 → 오늘
    await add_lead(ctx, utc(11, 14, 14, 59, 59, 999999), "keyword")  # 11-14 23:59:59.999999 → 어제
    await add_lead(ctx, utc(11, 14, 3, 0), "keyword")  # 11-14 12:00 → 어제
    await add_lead(ctx, utc(11, 13, 15, 0, 0), "activity")  # 11-14 00:00:00 → 어제의 첫 순간
    await add_lead(ctx, utc(11, 13, 14, 59, 59), "keyword")  # 11-13 23:59:59 → 그저께
    await add_lead(ctx, utc(11, 8, 15, 0, 0), "activity")  # 11-09 00:00:00 → 7일 창의 첫 순간
    await add_lead(ctx, utc(11, 8, 14, 59, 59), "keyword")  # 11-08 23:59:59 → 7일 창 밖
    await add_lead(ctx, utc(1, 1), "keyword")  # 한참 전


async def test_day_buckets_follow_seoul_midnight(authed, clock, around_midnights):
    body = await overview(authed)

    assert body["today_new"] == 2
    assert body["yesterday_new"] == 3
    assert body["total_leads"] == 9
    assert by_date(body) == {
        "2026-11-09": (0, 1),
        "2026-11-10": (0, 0),
        "2026-11-11": (0, 0),
        "2026-11-12": (0, 0),
        "2026-11-13": (1, 0),
        "2026-11-14": (2, 1),
        "2026-11-15": (1, 1),
    }
    assert dates(body) == sorted(dates(body))


async def test_longer_window_reaches_older_days(authed, clock, around_midnights):
    body = await overview(authed, {"days": 8})

    assert len(body["series"]) == 8
    assert body["series"][0] == {"date": "2026-11-08", "keyword": 1, "activity": 0}
    assert body["series"][1] == {"date": "2026-11-09", "keyword": 0, "activity": 1}
    assert body["total_leads"] == 9


@pytest.mark.parametrize("days", [1, 2])
async def test_short_window_still_knows_yesterday(authed, clock, around_midnights, days):
    body = await overview(authed, {"days": days})

    assert body["today_new"] == 2
    assert body["yesterday_new"] == 3
    assert dates(body) == ["2026-11-14", "2026-11-15"][-days:]
    assert body["series"][-1] == {"date": "2026-11-15", "keyword": 1, "activity": 1}


async def test_today_changes_at_seoul_midnight(authed, ctx, clock):
    await add_lead(ctx, utc(11, 14, 14, 59, 50), "keyword")  # 서울 11-14 23:59:50
    await add_lead(ctx, utc(11, 14, 15, 0, 10), "activity")  # 서울 11-15 00:00:10

    clock["now"] = utc(11, 14, 14, 59, 59)  # 서울 11-14 23:59:59
    before = await overview(authed, {"days": 3})
    clock["now"] = utc(11, 14, 15, 0, 30)  # 서울 11-15 00:00:30
    after = await overview(authed, {"days": 3})

    assert dates(before) == ["2026-11-12", "2026-11-13", "2026-11-14"]
    assert (before["today_new"], before["yesterday_new"]) == (1, 0)
    assert before["series"][-1] == {"date": "2026-11-14", "keyword": 1, "activity": 0}
    assert before["total_leads"] == 2

    assert dates(after) == ["2026-11-13", "2026-11-14", "2026-11-15"]
    assert (after["today_new"], after["yesterday_new"]) == (1, 1)
    assert after["series"][-2:] == [
        {"date": "2026-11-14", "keyword": 1, "activity": 0},
        {"date": "2026-11-15", "keyword": 0, "activity": 1},
    ]


async def test_day_buckets_follow_the_timezone_setting(authed, ctx, clock, around_midnights):
    await ctx.settings.update(timezone="UTC")

    body = await overview(authed)

    assert body["today_new"] == 1
    assert body["yesterday_new"] == 3
    assert by_date(body) == {
        "2026-11-09": (0, 0),
        "2026-11-10": (0, 0),
        "2026-11-11": (0, 0),
        "2026-11-12": (0, 0),
        "2026-11-13": (1, 1),
        "2026-11-14": (3, 0),
        "2026-11-15": (0, 1),
    }


async def test_day_buckets_on_a_twenty_five_hour_day(authed, ctx, clock):
    """뉴욕은 2026-11-01 에 서머타임이 끝나 그날이 25시간이다. 24시간씩 자르면 어긋난다."""
    await ctx.settings.update(timezone="America/New_York")
    clock["now"] = utc(11, 3, 17, 0)  # 뉴욕 11-03 12:00
    await add_lead(ctx, utc(11, 1, 3, 59, 59), "keyword")  # 뉴욕 10-31 23:59:59
    await add_lead(ctx, utc(11, 1, 4, 0, 0), "keyword")  # 뉴욕 11-01 00:00
    await add_lead(ctx, utc(11, 2, 4, 30, 0), "activity")  # 뉴욕 11-01 23:30
    await add_lead(ctx, utc(11, 2, 5, 0, 0), "keyword")  # 뉴욕 11-02 00:00

    body = await overview(authed, {"days": 4})

    assert by_date(body) == {
        "2026-10-31": (1, 0),
        "2026-11-01": (1, 1),
        "2026-11-02": (1, 0),
        "2026-11-03": (0, 0),
    }
    assert (body["today_new"], body["yesterday_new"]) == (0, 1)


async def test_today_counts_stay_in_step_with_the_series(authed, ctx, clock):
    for _ in range(3):
        await add_lead(ctx, utc(11, 15, 1, 0), "keyword")
    for _ in range(2):
        await add_lead(ctx, utc(11, 15, 2, 0), "activity")
    await add_lead(ctx, utc(11, 14, 1, 0), "activity")

    body = await overview(authed)

    assert body["today_new"] == 5
    assert body["series"][-1] == {"date": "2026-11-15", "keyword": 3, "activity": 2}
    assert body["yesterday_new"] == 1
    assert body["series"][-2] == {"date": "2026-11-14", "keyword": 0, "activity": 1}


async def test_series_counts_leads_by_first_detection_not_by_status(authed, ctx, clock):
    lead = await add_lead(ctx, utc(11, 15, 1, 0), "keyword")
    async with ctx.db.session() as session:
        stored = await session.get(Lead, lead.id)
        assert stored is not None
        stored.status = LeadStatus.EXCLUDED
        stored.last_seen_at = utc(11, 15, 2, 0)
        await session.commit()
    await add_hit(ctx, lead, utc(11, 15, 2, 0), kind=RuleKind.ACTIVITY)

    body = await overview(authed)

    assert body["today_new"] == 1
    assert body["series"][-1] == {"date": "2026-11-15", "keyword": 1, "activity": 0}


# --- days ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "length", "first_date"),
    [
        (None, 7, "2026-11-09"),
        (7, 7, "2026-11-09"),
        (30, 30, "2026-10-17"),
        (90, 90, "2026-08-18"),
        (91, 90, "2026-08-18"),
        (5000, 90, "2026-08-18"),
        (10**30, 90, "2026-08-18"),
        (1, 1, "2026-11-15"),
        (0, 1, "2026-11-15"),
        (-3, 1, "2026-11-15"),
    ],
)
async def test_days_is_clamped(authed, clock, days, length, first_date):
    body = await overview(authed, None if days is None else {"days": days})

    assert len(body["series"]) == length
    assert body["series"][0]["date"] == first_date
    assert body["series"][-1]["date"] == "2026-11-15"
    assert len(set(dates(body))) == length


async def test_ninety_day_window_buckets_every_day(authed, ctx, clock):
    for offset in range(95):
        await add_lead(ctx, NOON_NOV15_SEOUL - timedelta(days=offset), "keyword")

    body = await overview(authed, {"days": 90})

    assert [point["keyword"] for point in body["series"]] == [1] * 90
    assert body["total_leads"] == 95


@pytest.mark.parametrize("days", ["abc", "1.5", ""])
async def test_days_must_be_a_number(authed, days):
    res = await authed.get("/api/overview", params={"days": days})

    assert res.status_code == 422
    assert res.json()["code"] == "validation"


# --- 계정과 그룹 --------------------------------------------------------------


async def test_account_numbers(authed, ctx, clock):
    statuses = [
        AccountStatus.ACTIVE,
        AccountStatus.FLOOD_WAIT,
        AccountStatus.CONNECTING,
        AccountStatus.REAUTH_REQUIRED,
        AccountStatus.BANNED,
        AccountStatus.ERROR,
        AccountStatus.OFFLINE,
        AccountStatus.ACTIVE,
    ]
    accounts = [
        await add_account(ctx, label=f"영업 {number}호", status=status)
        for number, status in enumerate(statuses, start=1)
    ]
    await add_group(ctx, accounts[0])
    await add_group(ctx, accounts[0], status=GroupStatus.QUEUED)
    await add_group(ctx, accounts[0], status=GroupStatus.REQUESTED)
    await add_group(ctx, accounts[0], status=GroupStatus.FAILED)

    body = await overview(authed)

    assert body["accounts_connected"] == 3
    assert body["accounts_total"] == 8
    assert body["groups_capacity"] == 160
    assert [a["id"] for a in body["accounts"]] == [a.id for a in accounts]
    assert [a["status"] for a in body["accounts"]] == [str(status) for status in statuses]
    first = body["accounts"][0]
    assert first["display_name"] == "영업 1호"
    assert (first["joined_count"], first["pending_count"], first["max_groups"]) == (1, 2, 20)
    assert body["accounts"][1]["joined_count"] == 0


async def test_capacity_follows_the_setting(authed, ctx, clock):
    for _ in range(3):
        await add_account(ctx)
    await ctx.settings.update(max_groups_per_account=7)

    body = await overview(authed)

    assert body["groups_capacity"] == 21
    assert {a["max_groups"] for a in body["accounts"]} == {7}


async def test_group_numbers(authed, ctx, clock):
    first, second = await add_account(ctx), await add_account(ctx, status=AccountStatus.OFFLINE)
    for account, status, monitoring in [
        (first, GroupStatus.JOINED, True),
        (first, GroupStatus.JOINED, True),
        (second, GroupStatus.JOINED, True),
        (first, GroupStatus.JOINED, False),
        (first, GroupStatus.REQUESTED, True),
        (second, GroupStatus.REQUESTED, False),
        (first, GroupStatus.QUEUED, True),
        (second, GroupStatus.QUEUED, True),
        (first, GroupStatus.JOINING, True),
        (first, GroupStatus.FAILED, True),
        (second, GroupStatus.LEFT, True),
    ]:
        await add_group(ctx, account, status=status, monitoring=monitoring)

    body = await overview(authed)

    assert body["groups_monitoring"] == 3
    assert body["join_requests_pending"] == 2
    assert body["join_queue"] == 3


# --- 많이 수집된 그룹 ---------------------------------------------------------


async def test_top_groups(authed, ctx, clock):
    account = await add_account(ctx)
    leads = await add_leads(ctx, 5)
    plan = [
        ("한 명", 1),
        ("세 명", 3),
        ("다섯 명", 5),
        ("두 명 가", 2),
        ("두 명 나", 2),
        ("네 명", 4),
    ]
    groups = {title: await add_group(ctx, account, title=title) for title, _ in plan}
    await add_group(ctx, account, title="조용한 방")
    for title, count in plan:
        for lead in leads[:count]:
            await add_hit(ctx, lead, utc(11, 1), group=groups[title])
    # 같은 사람이 여러 번 걸려도 한 명으로 센다.
    for _ in range(4):
        await add_hit(ctx, leads[0], utc(11, 2), group=groups["한 명"])

    body = await overview(authed)

    assert body["top_groups"] == [
        {"group_id": groups["다섯 명"].id, "title": "다섯 명", "leads": 5},
        {"group_id": groups["네 명"].id, "title": "네 명", "leads": 4},
        {"group_id": groups["세 명"].id, "title": "세 명", "leads": 3},
        {"group_id": groups["두 명 가"].id, "title": "두 명 가", "leads": 2},
        {"group_id": groups["두 명 나"].id, "title": "두 명 나", "leads": 2},
    ]


async def test_top_groups_uses_display_title_and_skips_deleted_groups(authed, ctx, clock):
    account = await add_account(ctx)
    leads = await add_leads(ctx, 3)
    untitled = await add_group(ctx, account, public_username="cointalk")
    left = await add_group(ctx, account, title="나간 방", status=GroupStatus.LEFT)
    deleted = await add_group(ctx, account, title="지운 방")
    for lead in leads:
        await add_hit(ctx, lead, utc(11, 1), group=deleted)
    for lead in leads[:2]:
        await add_hit(ctx, lead, utc(11, 1), group=untitled)
    await add_hit(ctx, leads[0], utc(11, 1), group=left)
    await add_hit(ctx, leads[1], utc(11, 1))
    async with ctx.db.session() as session:
        await session.execute(delete(Group).where(Group.id == deleted.id))
        await session.commit()

    body = await overview(authed)

    assert body["top_groups"] == [
        {"group_id": untitled.id, "title": "@cointalk", "leads": 2},
        {"group_id": left.id, "title": "나간 방", "leads": 1},
    ]


# --- 규칙별 합계 --------------------------------------------------------------


async def test_rule_totals(authed, ctx, clock):
    leads = await add_leads(ctx, 4)
    quiet = await add_rule(ctx, "아직 안 걸린 규칙")
    small = await add_rule(
        ctx, "활발한 유저", RuleKind.ACTIVITY, enabled=False, min_messages=20, window_hours=24
    )
    big = await add_rule(ctx, "코인 문의")
    also_quiet = await add_rule(ctx, "나중에 만든 조용한 규칙")
    for lead in leads[:3]:
        await add_hit(ctx, lead, utc(11, 1), rule=big)
    for _ in range(5):
        await add_hit(ctx, leads[0], utc(11, 2), rule=big)
    await add_hit(ctx, leads[3], utc(11, 3), rule=small)
    await add_hit(ctx, leads[3], utc(11, 4))  # 규칙이 지워진 감지

    body = await overview(authed)

    assert body["rule_totals"] == [
        {"rule_id": big.id, "name": "코인 문의", "kind": "keyword", "enabled": True, "leads": 3},
        {
            "rule_id": small.id,
            "name": "활발한 유저",
            "kind": "activity",
            "enabled": False,
            "leads": 1,
        },
        {
            "rule_id": quiet.id,
            "name": "아직 안 걸린 규칙",
            "kind": "keyword",
            "enabled": True,
            "leads": 0,
        },
        {
            "rule_id": also_quiet.id,
            "name": "나중에 만든 조용한 규칙",
            "kind": "keyword",
            "enabled": True,
            "leads": 0,
        },
    ]


# --- 최근 감지 ----------------------------------------------------------------


async def test_recent_hits_shape(authed, ctx, clock):
    account = await add_account(ctx)
    group = await add_group(ctx, account, title="코인 수다방")
    rule = await add_rule(ctx, "코인 문의")
    lead = await add_lead(ctx, utc(11, 15, 1, 0), username="Kim_Trader")
    async with ctx.db.session() as session:
        stored = await session.get(Lead, lead.id)
        assert stored is not None
        stored.first_name, stored.last_name = "민수", "김"
        await session.commit()
    hit = await add_hit(
        ctx,
        lead,
        utc(11, 15, 1, 0),
        rule=rule,
        group=group,
        keywords=["코인"],
        excerpt="코인 어디서 사요?",
    )
    busy = await add_hit(
        ctx,
        lead,
        utc(11, 15, 2, 0),
        kind=RuleKind.ACTIVITY,
        rule_name="활발한 유저",
        message_count=40,
        window_hours=12,
    )

    body = await overview(authed)

    assert body["recent_hits"] == [
        {
            "hit_id": busy.id,
            "created_at": "2026-11-15T02:00:00Z",
            "kind": "activity",
            "rule_id": None,
            "rule_name": "활발한 유저",
            "group_id": None,
            "group_title": None,
            "keywords": [],
            "excerpt": None,
            "message_count": 40,
            "window_hours": 12,
            "lead_id": lead.id,
            "username": "Kim_Trader",
            "display_name": "민수 김",
            "is_new_lead": False,
        },
        {
            "hit_id": hit.id,
            "created_at": "2026-11-15T01:00:00Z",
            "kind": "keyword",
            "rule_id": rule.id,
            "rule_name": "코인 문의",
            "group_id": group.id,
            "group_title": "코인 수다방",
            "keywords": ["코인"],
            "excerpt": "코인 어디서 사요?",
            "message_count": None,
            "window_hours": None,
            "lead_id": lead.id,
            "username": "Kim_Trader",
            "display_name": "민수 김",
            "is_new_lead": True,
        },
    ]


async def test_recent_hits_are_the_latest_twenty(authed, ctx, clock):
    lead = await add_lead(ctx, utc(11, 1))
    hits = [await add_hit(ctx, lead, utc(11, 1) + timedelta(minutes=n)) for n in range(25)]

    body = await overview(authed)

    assert [item["hit_id"] for item in body["recent_hits"]] == [h.id for h in reversed(hits[5:])]
    assert not any(item["is_new_lead"] for item in body["recent_hits"])


async def test_recent_hits_mark_only_each_leads_earliest_hit(authed, ctx, clock):
    returning, fresh, twice = [await add_lead(ctx, utc(11, 1)) for _ in range(3)]
    await add_hit(ctx, returning, utc(11, 1))  # 최근 20건 밖으로 밀려날 첫 감지
    filler = await add_lead(ctx, utc(11, 2))
    for minute in range(16):
        await add_hit(ctx, filler, utc(11, 2, 0, minute))
    back_again = await add_hit(ctx, returning, utc(11, 3))
    first_time = await add_hit(ctx, fresh, utc(11, 4))
    same_moment_first = await add_hit(ctx, twice, utc(11, 5))
    same_moment_second = await add_hit(ctx, twice, utc(11, 5))

    body = await overview(authed)

    flags = {item["hit_id"]: item["is_new_lead"] for item in body["recent_hits"]}
    assert len(flags) == 20
    assert [item["hit_id"] for item in body["recent_hits"][:4]] == [
        same_moment_second.id,
        same_moment_first.id,
        first_time.id,
        back_again.id,
    ]
    assert flags[back_again.id] is False
    assert flags[first_time.id] is True
    assert flags[same_moment_first.id] is True
    assert flags[same_moment_second.id] is False
    # filler 의 감지 16건 가운데 가장 이른 것 하나만 새 유저 표시가 붙는다.
    assert sum(flags.values()) == 3


async def test_recent_hits_earliest_is_by_time_not_by_insert_order(authed, ctx, clock):
    lead = await add_lead(ctx, utc(11, 1))
    inserted_first = await add_hit(ctx, lead, utc(11, 5))
    inserted_later_but_earlier = await add_hit(ctx, lead, utc(11, 4))

    body = await overview(authed)

    flags = {item["hit_id"]: item["is_new_lead"] for item in body["recent_hits"]}
    assert flags == {inserted_first.id: False, inserted_later_but_earlier.id: True}


# --- 쿼리 수 -----------------------------------------------------------------


async def test_query_count_does_not_grow_with_data(authed, ctx, clock):
    """주기적으로 불리는 엔드포인트다. 데이터가 늘어도 쿼리 수는 그대로여야 한다."""
    seen: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        seen.append(statement)

    engine = ctx.db.engine.sync_engine
    await overview(authed)  # 설정 캐시를 채워 둔다
    event.listen(engine, "before_cursor_execute", record)
    try:
        await overview(authed, {"days": 90})
        empty = len(seen)
        seen.clear()

        accounts = [await add_account(ctx) for _ in range(4)]
        groups = [
            await add_group(ctx, account, title="방") for account in accounts for _ in range(3)
        ]
        rules = [await add_rule(ctx, f"규칙 {n}") for n in range(6)]
        leads = [await add_lead(ctx, utc(11, 15, 1, n)) for n in range(30)]
        for n, lead in enumerate(leads):
            await add_hit(ctx, lead, utc(11, 15, 2, n), rule=rules[n % 6], group=groups[n % 12])
        seen.clear()

        body = await overview(authed, {"days": 90})
        full = len(seen)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert body["total_leads"] == 30
    assert len(body["recent_hits"]) == 20
    assert len(body["top_groups"]) == 5
    assert len(body["rule_totals"]) == 6
    assert full == empty
    # 로그인 확인 1 + 개요 8
    assert full == 9
