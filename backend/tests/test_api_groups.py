"""/api/groups 테스트."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.models import (
    Account,
    AccountStatus,
    EventLog,
    Group,
    GroupStatus,
    Hit,
    Lead,
    LinkKind,
    LogCategory,
    Rule,
    RuleKind,
    rule_groups,
)

from .stubs import StubEngine

INVITE_HASH = "AbCdEfGh1234"


async def add_account(ctx, **fields: Any) -> Account:
    values: dict[str, Any] = {"session_enc": "encrypted", "status": AccountStatus.ACTIVE}
    values.update(fields)
    async with ctx.db.session() as session:
        account = Account(**values)
        session.add(account)
        await session.commit()
        return account


async def add_group(ctx, account: Account, **fields: Any) -> Group:
    values: dict[str, Any] = {"status": GroupStatus.JOINED, "link_kind": LinkKind.PUBLIC}
    values.update(fields)
    async with ctx.db.session() as session:
        group = Group(account_id=account.id, **values)
        session.add(group)
        await session.commit()
        return group


async def fill(ctx, account: Account, count: int, status: GroupStatus = GroupStatus.JOINED) -> None:
    """계정에 서로 다른 그룹 count 개를 넣어 둔다."""
    async with ctx.db.session() as session:
        start = (await session.execute(select(func.count()).select_from(Group))).scalar_one()
        session.add_all(
            Group(account_id=account.id, status=status, public_username=f"filler_{start + i}")
            for i in range(count)
        )
        await session.commit()


async def all_groups(ctx) -> list[Group]:
    async with ctx.db.session() as session:
        return list((await session.execute(select(Group).order_by(Group.id))).scalars())


async def get_group(ctx, group_id: int) -> Group | None:
    async with ctx.db.session() as session:
        return await session.get(Group, group_id)


async def all_logs(ctx) -> list[EventLog]:
    async with ctx.db.session() as session:
        return list((await session.execute(select(EventLog).order_by(EventLog.id))).scalars())


async def join(client, links: list[str], account_id: int | None = None) -> dict:
    payload: dict[str, Any] = {"links": links}
    if account_id is not None:
        payload["account_id"] = account_id
    res = await client.post("/api/groups/join", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def outcomes(body: dict) -> list[str]:
    return [item["outcome"] for item in body["items"]]


def assigned(body: dict) -> list[int | None]:
    return [item["group"]["account_id"] if item["group"] else None for item in body["items"]]


# --- 로그인 필요 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/groups"),
        ("POST", "/api/groups/join"),
        ("PATCH", "/api/groups/1"),
        ("POST", "/api/groups/1/retry"),
        ("DELETE", "/api/groups/1"),
        ("DELETE", "/api/groups/1?leave=true"),
    ],
)
async def test_requires_login(client, engine, ctx, method, path):
    account = await add_account(ctx)
    await add_group(ctx, account)

    res = await client.request(method, path)

    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"
    assert engine.calls == []
    assert len(await all_groups(ctx)) == 1


# --- 목록 --------------------------------------------------------------------


async def test_list_filters(authed, ctx):
    first = await add_account(ctx, label="영업 1호")
    second = await add_account(ctx, label="영업 2호")
    joined = await add_group(ctx, first, title="코인 수다방", public_username="cointalk")
    queued = await add_group(
        ctx, first, status=GroupStatus.QUEUED, source_link="https://t.me/stock_room"
    )
    failed = await add_group(ctx, second, status=GroupStatus.FAILED, title="주식 수다방")
    requested = await add_group(ctx, second, status=GroupStatus.REQUESTED, title="비공개 모임")

    async def ids(query: str) -> set[int]:
        res = await authed.get(f"/api/groups{query}")
        assert res.status_code == 200, res.text
        return {g["id"] for g in res.json()}

    assert await ids("") == {joined.id, queued.id, failed.id, requested.id}
    assert await ids(f"?account_id={first.id}") == {joined.id, queued.id}
    assert await ids("?status=failed") == {failed.id}
    assert await ids("?status=queued&status=requested") == {queued.id, requested.id}
    assert await ids(f"?account_id={second.id}&status=requested&status=joined") == {requested.id}
    assert await ids("?q=수다방") == {joined.id, failed.id}
    assert await ids("?q=COINTALK") == {joined.id}
    assert await ids("?q=stock_room") == {queued.id}
    assert await ids("?account_id=999") == set()


async def test_list_shape_and_order(authed, ctx):
    account = await add_account(ctx, label="영업 1호")
    older = await add_group(ctx, account, title="먼저 넣은 방")
    newer = await add_group(ctx, account, status=GroupStatus.QUEUED, public_username="newer_room")

    res = await authed.get("/api/groups")

    first, second = res.json()
    assert (first["id"], second["id"]) == (newer.id, older.id)
    assert first["account_name"] == "영업 1호"
    assert first["display_title"] == "@newer_room"
    assert first["status"] == "queued"
    assert first["lead_count"] == 0
    assert second["display_title"] == "먼저 넣은 방"


@pytest.mark.parametrize("query", ["?status=nope", "?account_id=abc", f"?account_id={2**70}"])
async def test_list_rejects_bad_filters(authed, query):
    res = await authed.get(f"/api/groups{query}")

    assert res.status_code == 422


# --- 가입: 기본 ---------------------------------------------------------------


async def test_join_queues_public_and_invite_links(authed, engine, ctx):
    account = await add_account(ctx, label="영업 1호")

    body = await join(authed, ["  https://t.me/CoinTalk  ", f"t.me/+{INVITE_HASH}"])

    assert body["queued"] == 2
    public, invite = body["items"]
    assert public["input"] == "  https://t.me/CoinTalk  "
    assert public["outcome"] == "queued"
    assert public["reason"] is None
    assert public["group"]["account_id"] == account.id
    assert public["group"]["account_name"] == "영업 1호"
    assert public["group"]["status"] == "queued"
    assert public["group"]["link_kind"] == "public"
    assert public["group"]["public_username"] == "CoinTalk"
    assert public["group"]["source_link"] == "https://t.me/CoinTalk"
    assert public["group"]["display_title"] == "@CoinTalk"
    assert public["group"]["attempts"] == 0
    assert public["group"]["monitoring"] is True
    assert invite["group"]["link_kind"] == "invite"
    assert invite["group"]["public_username"] is None
    assert invite["group"]["source_link"] == f"t.me/+{INVITE_HASH}"

    rows = await all_groups(ctx)
    assert [(g.link_kind, g.public_username, g.invite_hash) for g in rows] == [
        (LinkKind.PUBLIC, "CoinTalk", None),
        (LinkKind.INVITE, None, INVITE_HASH),
    ]
    assert all(g.status == GroupStatus.QUEUED and g.tg_chat_id is None for g in rows)


async def test_join_notifies_engine_and_writes_one_log(authed, engine, ctx):
    await add_account(ctx)
    await add_account(ctx)

    await join(authed, ["@room_one", "@room_two", "@room_three", "not a link!"])

    assert engine.called("notify_groups_changed") == [((None,), {})]
    logs = await all_logs(ctx)
    assert len(logs) == 1
    assert logs[0].message == "그룹 3개를 가입 대기열에 넣었어요."
    assert logs[0].category == LogCategory.GROUP
    assert logs[0].account_id is None


async def test_join_log_names_the_account_when_all_go_to_one(authed, engine, ctx):
    account = await add_account(ctx)

    await join(authed, ["@room_one", "@room_two"])

    assert (await all_logs(ctx))[0].account_id == account.id


async def test_join_invalid_lines(authed, engine, ctx):
    await add_account(ctx)

    body = await join(
        authed,
        ["https://example.com/room", "", "t.me/c/12345/6", "t.me/addlist/abcdef", "@ab"],
    )

    assert outcomes(body) == ["invalid"] * 5
    assert [item["reason"] for item in body["items"]] == [
        "텔레그램 링크(t.me)가 아니에요.",
        "링크가 비어 있어요.",
        "비공개 그룹의 메시지 링크로는 가입할 수 없어요. 초대 링크를 넣어 주세요.",
        "폴더 링크는 지원하지 않아요. 그룹 링크를 하나씩 넣어 주세요.",
        "그룹 아이디 형식이 올바르지 않아요.",
    ]
    assert all(item["group"] is None for item in body["items"])
    assert body["queued"] == 0
    assert await all_groups(ctx) == []
    # 넣은 것이 없으면 엔진도 깨우지 않고 기록도 남기지 않는다.
    assert engine.calls == []
    assert await all_logs(ctx) == []


async def test_join_mixed_results_keep_input_order(authed, engine, ctx):
    account = await add_account(ctx)
    await add_group(ctx, account, public_username="already_here")

    body = await join(
        authed, ["@fresh_room", "nonsense link", "t.me/already_here", "@fresh_room", "@second_room"]
    )

    assert [item["input"] for item in body["items"]] == [
        "@fresh_room",
        "nonsense link",
        "t.me/already_here",
        "@fresh_room",
        "@second_room",
    ]
    assert outcomes(body) == ["queued", "invalid", "duplicate", "duplicate", "queued"]
    assert body["queued"] == 2


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"links": []}, "링크 값이 너무 짧아요."),
        ({"links": ["@room"] * 201}, "링크 값이 너무 길어요."),
        ({}, "링크 값을 넣어 주세요."),
    ],
)
async def test_join_validation(authed, engine, payload, detail):
    res = await authed.post("/api/groups/join", json=payload)

    assert res.status_code == 422
    assert res.json()["detail"] == detail
    assert engine.calls == []


# --- 가입: 중복 ---------------------------------------------------------------


async def test_join_duplicates_within_one_request(authed, engine, ctx):
    await add_account(ctx)
    await add_account(ctx)

    body = await join(
        authed,
        [
            "@CoinTalk",
            "https://t.me/cointalk",
            "t.me/COINTALK/1234",
            f"https://t.me/+{INVITE_HASH}",
            f"https://t.me/joinchat/{INVITE_HASH}",
            f"tg://join?invite={INVITE_HASH}",
        ],
    )

    assert outcomes(body) == [
        "queued",
        "duplicate",
        "duplicate",
        "queued",
        "duplicate",
        "duplicate",
    ]
    assert body["items"][1]["reason"] == "위에 같은 링크가 있어요."
    assert body["queued"] == 2
    assert len(await all_groups(ctx)) == 2


async def test_join_duplicate_across_requests_names_the_account(authed, engine, ctx):
    await add_account(ctx, label="영업 1호")
    await add_account(ctx, label="영업 2호")
    first = await join(authed, ["@CoinTalk"])
    assert assigned(first) == [1]

    second = await join(authed, ["https://t.me/cointalk"])

    assert outcomes(second) == ["duplicate"]
    assert second["items"][0]["reason"] == "영업 1호 계정의 가입 대기열에 이미 있어요."
    assert second["items"][0]["group"] is None
    assert second["queued"] == 0
    assert len(await all_groups(ctx)) == 1


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (GroupStatus.QUEUED, "영업 2호 계정의 가입 대기열에 이미 있어요."),
        (GroupStatus.JOINING, "영업 2호 계정의 가입 대기열에 이미 있어요."),
        (GroupStatus.REQUESTED, "영업 2호 계정이 이미 입장 요청을 보낸 그룹이에요."),
        (GroupStatus.JOINED, "영업 2호 계정이 이미 들어가 있는 그룹이에요."),
    ],
)
async def test_join_duplicate_on_any_account_in_occupying_status(authed, ctx, status, reason):
    await add_account(ctx, label="영업 1호")
    holder = await add_account(ctx, label="영업 2호")
    await add_group(ctx, holder, status=status, link_kind=LinkKind.INVITE, invite_hash=INVITE_HASH)

    body = await join(authed, [f"t.me/+{INVITE_HASH}"])

    assert outcomes(body) == ["duplicate"]
    assert body["items"][0]["reason"] == reason


async def test_join_duplicate_even_when_sent_to_a_specific_account(authed, ctx):
    holder = await add_account(ctx, label="영업 1호")
    target = await add_account(ctx, label="영업 2호")
    await add_group(ctx, holder, public_username="CoinTalk")

    body = await join(authed, ["@cointalk"], account_id=target.id)

    assert outcomes(body) == ["duplicate"]
    assert "영업 1호" in body["items"][0]["reason"]


@pytest.mark.parametrize("status", [GroupStatus.FAILED, GroupStatus.LEFT])
async def test_join_allows_links_whose_old_rows_are_gone(authed, ctx, status):
    account = await add_account(ctx)
    await add_group(ctx, account, status=status, public_username="CoinTalk")

    body = await join(authed, ["@cointalk"])

    assert outcomes(body) == ["queued"]


async def test_join_duplicate_of_an_imported_dialog(authed, ctx):
    account = await add_account(ctx, label="영업 1호")
    await add_group(
        ctx, account, link_kind=LinkKind.EXISTING, public_username="CoinTalk", tg_chat_id=-1001
    )

    body = await join(authed, ["https://t.me/cointalk"])

    assert outcomes(body) == ["duplicate"]
    assert body["items"][0]["reason"] == "영업 1호 계정이 이미 들어가 있는 그룹이에요."


async def test_join_invite_hash_is_case_sensitive(authed, ctx):
    account = await add_account(ctx)
    await add_group(ctx, account, link_kind=LinkKind.INVITE, invite_hash=INVITE_HASH)

    body = await join(authed, [f"t.me/+{INVITE_HASH.lower()}"])

    assert outcomes(body) == ["queued"]


async def test_concurrent_identical_requests_queue_each_link_once(authed, engine, ctx):
    await add_account(ctx)
    await add_account(ctx)
    links = [f"@room_{i:02d}" for i in range(10)]

    first, second = await asyncio.gather(join(authed, links), join(authed, links))

    assert sorted([first["queued"], second["queued"]]) == [0, 10]
    rows = await all_groups(ctx)
    assert len(rows) == 10
    assert len({g.public_username for g in rows}) == 10


# --- 가입: 자동 배정 -----------------------------------------------------------


async def test_join_spreads_over_the_least_loaded_accounts(authed, ctx):
    a = await add_account(ctx)
    b = await add_account(ctx)
    c = await add_account(ctx)
    await fill(ctx, a, 3)
    await fill(ctx, b, 1)
    await fill(ctx, c, 2)

    body = await join(authed, ["@room_one", "@room_two", "@room_three", "@room_four", "@room_five"])

    # b(1) → b·c 동률(2)이면 id 가 작은 b → c(2) → 셋 다 3 이면 a → 다시 b
    assert assigned(body) == [b.id, b.id, c.id, a.id, b.id]


async def test_join_counts_every_occupying_status(authed, ctx):
    a = await add_account(ctx)
    b = await add_account(ctx)
    await fill(ctx, a, 1, GroupStatus.QUEUED)
    await fill(ctx, a, 1, GroupStatus.JOINING)
    await fill(ctx, a, 1, GroupStatus.REQUESTED)
    await fill(ctx, b, 2, GroupStatus.JOINED)
    # 실패했거나 나간 그룹은 자리를 차지하지 않는다.
    await fill(ctx, b, 4, GroupStatus.FAILED)
    await fill(ctx, b, 4, GroupStatus.LEFT)

    body = await join(authed, ["@room_one", "@room_two", "@room_three"])

    assert assigned(body) == [b.id, a.id, b.id]


async def test_join_even_split_from_empty(authed, ctx):
    accounts = [await add_account(ctx) for _ in range(3)]

    body = await join(authed, [f"@room_{i:02d}" for i in range(7)])

    ids = [a.id for a in accounts]
    assert assigned(body) == [ids[0], ids[1], ids[2], ids[0], ids[1], ids[2], ids[0]]


async def test_join_skips_accounts_that_cannot_join(authed, ctx):
    await add_account(ctx, enabled=False, status=AccountStatus.OFFLINE)
    await add_account(ctx, session_enc=None)
    await add_account(ctx, status=AccountStatus.REAUTH_REQUIRED)
    await add_account(ctx, status=AccountStatus.BANNED)
    usable = await add_account(ctx)
    await fill(ctx, usable, 5)

    body = await join(authed, ["@room_one", "@room_two"])

    assert assigned(body) == [usable.id, usable.id]


@pytest.mark.parametrize(
    "status",
    [
        AccountStatus.ACTIVE,
        AccountStatus.CONNECTING,
        AccountStatus.FLOOD_WAIT,
        AccountStatus.ERROR,
        AccountStatus.OFFLINE,
    ],
)
async def test_join_accepts_accounts_that_will_come_back(authed, ctx, status):
    account = await add_account(ctx, status=status)

    body = await join(authed, ["@room_one"])

    assert assigned(body) == [account.id]


async def test_join_respects_the_per_account_limit(authed, ctx):
    a = await add_account(ctx)
    b = await add_account(ctx)
    await ctx.settings.update(max_groups_per_account=3)
    await fill(ctx, a, 2)
    await fill(ctx, b, 1)

    body = await join(authed, ["@room_one", "@room_two", "@room_three", "@room_four"])

    assert outcomes(body) == ["queued", "queued", "queued", "no_capacity"]
    assert assigned(body) == [b.id, a.id, b.id, None]
    assert body["items"][3]["reason"] == "모든 계정이 꽉 찼어요. (계정당 최대 3개)"
    assert body["queued"] == 3
    async with ctx.db.session() as session:
        counts = dict(
            (
                await session.execute(
                    select(Group.account_id, func.count()).group_by(Group.account_id)
                )
            ).all()
        )
    assert counts == {a.id: 3, b.id: 3}


async def test_join_limit_holds_across_requests(authed, ctx):
    await add_account(ctx)
    await ctx.settings.update(max_groups_per_account=2)

    first = await join(authed, ["@room_one", "@room_two"])
    second = await join(authed, ["@room_three"])

    assert outcomes(first) == ["queued", "queued"]
    assert outcomes(second) == ["no_capacity"]


async def test_join_without_usable_accounts(authed, engine, ctx):
    await add_account(ctx, enabled=False)

    body = await join(authed, ["@room_one", "@room_two"])

    assert outcomes(body) == ["no_capacity", "no_capacity"]
    assert (
        body["items"][0]["reason"]
        == "그룹을 넣을 수 있는 계정이 없어요. 계정을 연결하거나 켜 주세요."
    )
    assert await all_groups(ctx) == []
    assert engine.calls == []


async def test_join_without_any_account(authed):
    body = await join(authed, ["@room_one"])

    assert outcomes(body) == ["no_capacity"]
    assert "계정을 연결하거나 켜 주세요" in body["items"][0]["reason"]


# --- 가입: 계정 지정 -----------------------------------------------------------


async def test_join_into_a_chosen_account(authed, ctx):
    empty = await add_account(ctx)
    chosen = await add_account(ctx, label="영업 2호")
    await fill(ctx, chosen, 5)

    body = await join(authed, ["@room_one", "@room_two"], account_id=chosen.id)

    assert assigned(body) == [chosen.id, chosen.id]
    assert all(g.account_id != empty.id for g in await all_groups(ctx))


async def test_join_into_a_chosen_account_that_is_off(authed, ctx):
    # 직접 고른 계정이면 지금 꺼져 있어도 대기열에는 넣어 둔다.
    chosen = await add_account(ctx, enabled=False, status=AccountStatus.OFFLINE)

    body = await join(authed, ["@room_one"], account_id=chosen.id)

    assert assigned(body) == [chosen.id]


async def test_join_into_a_chosen_account_respects_the_limit(authed, ctx):
    await add_account(ctx)
    chosen = await add_account(ctx, label="영업 2호")
    await ctx.settings.update(max_groups_per_account=3)
    await fill(ctx, chosen, 2)

    body = await join(authed, ["@room_one", "@room_two"], account_id=chosen.id)

    # 다른 계정에 자리가 있어도 넘기지 않는다.
    assert outcomes(body) == ["queued", "no_capacity"]
    assert body["items"][1]["reason"] == "영업 2호 계정에 남은 자리가 없어요. (계정당 최대 3개)"
    assert assigned(body) == [chosen.id, None]


async def test_join_into_a_missing_account(authed, engine, ctx):
    await add_account(ctx)

    res = await authed.post("/api/groups/join", json={"links": ["@room_one"], "account_id": 999})

    assert res.status_code == 404
    assert res.json() == {
        "detail": "계정을 찾을 수 없어요.",
        "code": "not_found",
        "retry_after": None,
    }
    assert await all_groups(ctx) == []
    assert engine.calls == []


# --- 감시 켜고 끄기 ------------------------------------------------------------


async def test_patch_monitoring(authed, engine, ctx):
    account = await add_account(ctx)
    group = await add_group(ctx, account, title="코인 수다방")

    res = await authed.patch(f"/api/groups/{group.id}", json={"monitoring": False})

    assert res.status_code == 200
    assert res.json()["id"] == group.id
    assert res.json()["monitoring"] is False
    assert (await get_group(ctx, group.id)).monitoring is False
    assert engine.called("notify_groups_changed") == [((account.id,), {})]

    res = await authed.patch(f"/api/groups/{group.id}", json={"monitoring": True})

    assert res.json()["monitoring"] is True
    assert len(engine.called("notify_groups_changed")) == 2


class RewritingEngine(StubEngine):
    """알림을 받자마자(응답이 만들어지기 전에) 다른 커넥션으로 그룹 행을 고쳐 놓는 엔진."""

    def __init__(self, database_file: Path) -> None:
        super().__init__()
        self.database_file = database_file

    def notify_groups_changed(self, account_id: int | None = None) -> None:
        super().notify_groups_changed(account_id)
        with closing(sqlite3.connect(self.database_file)) as conn, conn:
            conn.execute("UPDATE groups SET title = '엔진이 고친 제목', member_count = 77")


@pytest.mark.parametrize("action", ["patch", "retry"])
async def test_response_shows_what_the_engine_changed_meanwhile(authed, ctx, action):
    ctx.engine = RewritingEngine(ctx.config.data_dir / "chatdb.sqlite3")
    account = await add_account(ctx)
    group = await add_group(
        ctx, account, status=GroupStatus.FAILED, public_username="CoinTalk", title="예전 제목"
    )

    if action == "patch":
        res = await authed.patch(f"/api/groups/{group.id}", json={"monitoring": False})
    else:
        res = await authed.post(f"/api/groups/{group.id}/retry")

    assert res.status_code == 200
    assert res.json()["title"] == "엔진이 고친 제목"
    assert res.json()["member_count"] == 77


async def test_patch_without_fields_changes_nothing(authed, engine, ctx):
    account = await add_account(ctx)
    group = await add_group(ctx, account, monitoring=False)

    res = await authed.patch(f"/api/groups/{group.id}", json={})

    assert res.status_code == 200
    assert res.json()["monitoring"] is False
    assert engine.calls == []


async def test_patch_missing_group(authed, engine):
    res = await authed.patch("/api/groups/999", json={"monitoring": False})

    assert res.status_code == 404
    assert res.json() == {
        "detail": "그룹을 찾을 수 없어요.",
        "code": "not_found",
        "retry_after": None,
    }
    assert engine.calls == []


# --- 다시 시도 ----------------------------------------------------------------


@pytest.mark.parametrize("status", [GroupStatus.FAILED, GroupStatus.LEFT])
async def test_retry_requeues(authed, engine, ctx, status):
    account = await add_account(ctx)
    group = await add_group(
        ctx,
        account,
        status=status,
        public_username="CoinTalk",
        source_link="https://t.me/CoinTalk",
        status_detail="요청이 많아 가입하지 못했어요.",
        error_code="flood_wait",
        attempts=4,
        next_attempt_at=datetime.now(UTC) + timedelta(hours=2),
    )

    res = await authed.post(f"/api/groups/{group.id}/retry")

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == group.id
    assert body["status"] == "queued"
    assert body["attempts"] == 0
    assert body["status_detail"] is None
    assert body["error_code"] is None
    assert body["next_attempt_at"] is None
    assert body["link_kind"] == "public"
    assert body["source_link"] == "https://t.me/CoinTalk"
    row = await get_group(ctx, group.id)
    assert (row.status, row.attempts, row.error_code) == (GroupStatus.QUEUED, 0, None)
    assert engine.called("notify_groups_changed") == [((account.id,), {})]


async def test_retry_invite_link(authed, ctx):
    account = await add_account(ctx)
    group = await add_group(
        ctx, account, status=GroupStatus.FAILED, link_kind=LinkKind.INVITE, invite_hash=INVITE_HASH
    )

    res = await authed.post(f"/api/groups/{group.id}/retry")

    assert res.status_code == 200
    assert res.json()["status"] == "queued"
    assert res.json()["link_kind"] == "invite"


@pytest.mark.parametrize(
    "status",
    [GroupStatus.QUEUED, GroupStatus.JOINING, GroupStatus.REQUESTED, GroupStatus.JOINED],
)
async def test_retry_only_failed_or_left(authed, engine, ctx, status):
    account = await add_account(ctx)
    group = await add_group(ctx, account, status=status, public_username="CoinTalk", attempts=2)

    res = await authed.post(f"/api/groups/{group.id}/retry")

    assert res.status_code == 409
    assert res.json()["code"] == "not_retryable"
    assert res.json()["detail"] == "가입에 실패했거나 나간 그룹만 다시 시도할 수 있어요."
    row = await get_group(ctx, group.id)
    assert (row.status, row.attempts) == (status, 2)
    assert engine.calls == []


@pytest.mark.parametrize(
    "fields",
    [
        {"link_kind": LinkKind.EXISTING, "tg_chat_id": -1001, "title": "불러온 비공개 방"},
        {"link_kind": LinkKind.INVITE, "invite_hash": None},
        {"link_kind": LinkKind.PUBLIC, "public_username": None},
    ],
)
async def test_retry_needs_a_link(authed, engine, ctx, fields):
    account = await add_account(ctx)
    group = await add_group(ctx, account, status=GroupStatus.LEFT, **fields)

    res = await authed.post(f"/api/groups/{group.id}/retry")

    assert res.status_code == 409
    assert res.json()["code"] == "no_link"
    assert (await get_group(ctx, group.id)).status == GroupStatus.LEFT
    assert engine.calls == []


async def test_retry_imported_group_with_public_username_becomes_a_public_join(authed, engine, ctx):
    account = await add_account(ctx)
    group = await add_group(
        ctx,
        account,
        status=GroupStatus.LEFT,
        link_kind=LinkKind.EXISTING,
        public_username="CoinTalk",
        tg_chat_id=-1001,
        title="코인 수다방",
    )

    res = await authed.post(f"/api/groups/{group.id}/retry")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "queued"
    assert body["link_kind"] == "public"
    assert body["source_link"] == "https://t.me/CoinTalk"
    assert body["public_username"] == "CoinTalk"
    assert body["tg_chat_id"] == -1001


async def test_retry_when_the_account_is_full(authed, engine, ctx):
    account = await add_account(ctx, label="영업 1호")
    await ctx.settings.update(max_groups_per_account=2)
    await fill(ctx, account, 1, GroupStatus.JOINED)
    await fill(ctx, account, 1, GroupStatus.REQUESTED)
    group = await add_group(ctx, account, status=GroupStatus.FAILED, public_username="CoinTalk")

    res = await authed.post(f"/api/groups/{group.id}/retry")

    assert res.status_code == 409
    assert res.json()["code"] == "no_capacity"
    assert res.json()["detail"] == "영업 1호 계정에 남은 자리가 없어요. (계정당 최대 2개)"
    assert (await get_group(ctx, group.id)).status == GroupStatus.FAILED
    assert engine.calls == []


async def test_retry_with_one_slot_left(authed, ctx):
    account = await add_account(ctx)
    await ctx.settings.update(max_groups_per_account=2)
    await fill(ctx, account, 1)
    # 실패한 행들은 자리를 차지하지 않는다(다시 시도하려는 자기 자신도).
    await fill(ctx, account, 3, GroupStatus.FAILED)
    group = await add_group(ctx, account, status=GroupStatus.FAILED, public_username="CoinTalk")

    res = await authed.post(f"/api/groups/{group.id}/retry")

    assert res.status_code == 200
    assert res.json()["status"] == "queued"


async def test_retry_when_another_account_took_the_group(authed, engine, ctx):
    first = await add_account(ctx, label="영업 1호")
    second = await add_account(ctx, label="영업 2호")
    group = await add_group(ctx, first, status=GroupStatus.FAILED, public_username="CoinTalk")
    await add_group(ctx, second, status=GroupStatus.JOINED, public_username="cointalk")

    res = await authed.post(f"/api/groups/{group.id}/retry")

    assert res.status_code == 409
    assert res.json()["code"] == "duplicate"
    assert res.json()["detail"] == "영업 2호 계정이 이미 들어가 있는 그룹이에요."
    assert (await get_group(ctx, group.id)).status == GroupStatus.FAILED
    assert engine.calls == []


async def test_retry_missing_group(authed, engine):
    res = await authed.post("/api/groups/999/retry")

    assert res.status_code == 404
    assert res.json()["detail"] == "그룹을 찾을 수 없어요."
    assert engine.calls == []


# --- 삭제 --------------------------------------------------------------------


async def test_delete_without_leaving(authed, engine, ctx):
    account = await add_account(ctx)
    group = await add_group(ctx, account)
    keep = await add_group(ctx, account)

    res = await authed.delete(f"/api/groups/{group.id}")

    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert [g.id for g in await all_groups(ctx)] == [keep.id]
    assert engine.called("leave_group") == []
    assert engine.called("notify_groups_changed") == [((account.id,), {})]


async def test_delete_with_leave_false_in_query(authed, engine, ctx):
    account = await add_account(ctx)
    group = await add_group(ctx, account)

    res = await authed.delete(f"/api/groups/{group.id}?leave=false")

    assert res.status_code == 200
    assert engine.called("leave_group") == []


class LeavingEngine(StubEngine):
    """나가기를 요청받은 순간 행이 아직 있는지 적어 두고, 진짜 엔진처럼 행을 고쳐 둔다."""

    def __init__(self, db) -> None:
        super().__init__()
        self.db = db
        self.row_existed_at_leave: bool | None = None

    async def leave_group(self, group_id: int) -> None:
        await super().leave_group(group_id)
        async with self.db.session() as session:
            group = await session.get(Group, group_id)
            self.row_existed_at_leave = group is not None
            if group is not None:
                group.status = GroupStatus.LEFT
                await session.commit()


async def test_delete_with_leave_calls_the_engine_first(authed, ctx):
    leaving = LeavingEngine(ctx.db)
    ctx.engine = leaving
    account = await add_account(ctx)
    group = await add_group(ctx, account)

    res = await authed.delete(f"/api/groups/{group.id}?leave=true")

    assert res.status_code == 200
    assert leaving.row_existed_at_leave is True
    assert await all_groups(ctx) == []
    assert [name for name, _args, _kwargs in leaving.calls] == [
        "leave_group",
        "notify_groups_changed",
    ]
    assert leaving.called("leave_group") == [((group.id,), {})]
    assert leaving.called("notify_groups_changed") == [((account.id,), {})]


async def test_delete_keeps_hits_and_unlinks_rules(authed, ctx):
    account = await add_account(ctx)
    group = await add_group(ctx, account, title="코인 수다방")
    async with ctx.db.session() as session:
        rule = Rule(name="구매 문의", kind=RuleKind.KEYWORD, keywords=["구매"], all_groups=False)
        rule.groups = [await session.get(Group, group.id)]
        lead = Lead(tg_user_id=5001, username="buyer", first_kind=RuleKind.KEYWORD)
        session.add_all([rule, lead])
        await session.flush()
        hit = Hit(
            lead_id=lead.id,
            rule_id=rule.id,
            group_id=group.id,
            account_id=account.id,
            kind=RuleKind.KEYWORD,
            rule_name=rule.name,
            group_title=group.title,
        )
        session.add(hit)
        await session.commit()

    res = await authed.delete(f"/api/groups/{group.id}")

    assert res.status_code == 200
    async with ctx.db.session() as session:
        kept = (await session.execute(select(Hit))).scalar_one()
        links = (await session.execute(select(func.count()).select_from(rule_groups))).scalar_one()
    # 수집 기록은 남고(그룹 이름은 기록에 적혀 있다), 규칙과의 연결만 사라진다.
    assert kept.group_id is None
    assert kept.group_title == "코인 수다방"
    assert links == 0


async def test_delete_missing_group(authed, engine):
    res = await authed.delete("/api/groups/999?leave=true")

    assert res.status_code == 404
    assert res.json()["detail"] == "그룹을 찾을 수 없어요."
    assert engine.calls == []


async def test_absurd_group_id_is_rejected_cleanly(authed, engine):
    res = await authed.delete(f"/api/groups/{2**70}")

    assert res.status_code == 422
    assert engine.calls == []
