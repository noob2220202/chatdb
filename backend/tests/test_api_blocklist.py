"""/api/blocklist 테스트."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.models import BlocklistEntry, Lead, LeadStatus
from app.routers import blocklist as blocklist_router
from app.routers.blocklist import normalize_username

T0 = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)


@pytest.fixture
def invalidations(ctx, monkeypatch) -> list[None]:
    """수집기 캐시를 버린 횟수만큼 항목이 쌓인다."""
    calls: list[None] = []
    monkeypatch.setattr(ctx.collector, "invalidate", lambda: calls.append(None))
    return calls


async def add_entry(ctx, username: str, **fields: Any) -> BlocklistEntry:
    async with ctx.db.session() as session:
        entry = BlocklistEntry(username=username, **fields)
        session.add(entry)
        await session.commit()
        return entry


async def add_lead(ctx, username: str, status: LeadStatus = LeadStatus.NEW) -> Lead:
    async with ctx.db.session() as session:
        taken = (await session.scalars(select(Lead.tg_user_id))).all()
        lead = Lead(
            tg_user_id=1000 + len(taken), username=username, status=status, first_kind="keyword"
        )
        session.add(lead)
        await session.commit()
        return lead


async def stored_usernames(ctx) -> list[str]:
    async with ctx.db.session() as session:
        rows = await session.scalars(select(BlocklistEntry.username).order_by(BlocklistEntry.id))
        return list(rows)


async def lead_status(ctx, lead: Lead) -> str:
    async with ctx.db.session() as session:
        found = await session.get(Lead, lead.id)
        assert found is not None
        return found.status


async def post(client, usernames: list[str], note: str | None = None):
    payload: dict[str, Any] = {"usernames": usernames}
    if note is not None:
        payload["note"] = note
    return await client.post("/api/blocklist", json=payload)


# --- 아이디 다듬기 ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("kim_trader", "kim_trader"),
        ("@Kim_Trader", "kim_trader"),
        ("  @spaced_out  ", "spaced_out"),
        ("https://t.me/Some_User", "some_user"),
        ("HTTPS://T.ME/Shouting", "shouting"),
        ("http://t.me/plain_http", "plain_http"),
        ("t.me/no_scheme", "no_scheme"),
        ("https://t.me/trailing/", "trailing"),
        ("abc", "abc"),
        ("a" * 32, "a" * 32),
        ("user_123", "user_123"),
        ("ab", None),
        ("a" * 33, None),
        ("", None),
        ("   ", None),
        ("@", None),
        ("한글아이디", None),
        ("kim trader", None),
        ("kim-trader", None),
        ("kim.trader", None),
        ("@@double", None),
        ("https://t.me/+AbCdEfGh1234", None),
        ("https://t.me/joinchat/AbCdEfGh1234", None),
        ("https://example.com/someone", None),
        ("someone?start=1", None),
        ("ｆｕｌｌｗｉｄｔｈ", None),
    ],
)
def test_normalize_username(raw, expected):
    assert normalize_username(raw) == expected


# --- 로그인 필요 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/blocklist"),
        ("POST", "/api/blocklist"),
        ("DELETE", "/api/blocklist/1"),
    ],
)
async def test_requires_login(client, ctx, invalidations, method, path):
    await add_entry(ctx, "spammer")

    res = await client.request(method, path, json={"usernames": ["someone"]})

    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"
    assert await stored_usernames(ctx) == ["spammer"]
    assert invalidations == []


# --- 목록 --------------------------------------------------------------------


async def test_list_is_empty_at_first(authed):
    res = await authed.get("/api/blocklist")

    assert res.status_code == 200
    assert res.json() == []


async def test_list_newest_first(authed, ctx):
    oldest = await add_entry(ctx, "oldest", created_at=T0)
    newest = await add_entry(ctx, "newest", note="광고 계정", created_at=T0 + timedelta(hours=2))
    middle_a = await add_entry(ctx, "middle_a", created_at=T0 + timedelta(hours=1))
    middle_b = await add_entry(ctx, "middle_b", created_at=T0 + timedelta(hours=1))

    res = await authed.get("/api/blocklist")

    assert res.status_code == 200
    body = res.json()
    assert [e["id"] for e in body] == [newest.id, middle_b.id, middle_a.id, oldest.id]
    assert body[0] == {
        "id": newest.id,
        "username": "newest",
        "note": "광고 계정",
        "created_at": "2026-11-10T05:00:00Z",
    }
    assert body[-1]["note"] is None


# --- 추가 --------------------------------------------------------------------


async def test_add_normalizes_and_returns_created_entries(authed, ctx, invalidations):
    res = await post(
        authed,
        ["@Kim_Trader", " https://t.me/Promo_Bot ", "plain_name", "not valid", "ab"],
        note="  광고 계정  ",
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert [e["username"] for e in body] == ["kim_trader", "promo_bot", "plain_name"]
    assert {e["note"] for e in body} == {"광고 계정"}
    assert all(datetime.fromisoformat(e["created_at"]).tzinfo is not None for e in body)
    assert await stored_usernames(ctx) == ["kim_trader", "promo_bot", "plain_name"]
    assert invalidations == [None]

    listed = await authed.get("/api/blocklist")
    assert sorted(e["id"] for e in listed.json()) == sorted(e["id"] for e in body)


async def test_add_skips_duplicates_and_existing(authed, ctx, invalidations):
    existing = await add_entry(ctx, "already_here", note="예전 메모")

    res = await post(
        authed, ["new_one", "@NEW_ONE", "https://t.me/new_one", "Already_Here", "another"]
    )

    assert res.status_code == 200, res.text
    assert [e["username"] for e in res.json()] == ["new_one", "another"]
    assert existing.id not in {e["id"] for e in res.json()}
    assert await stored_usernames(ctx) == ["already_here", "new_one", "another"]
    async with ctx.db.session() as session:
        kept = await session.get(BlocklistEntry, existing.id)
        assert kept is not None
        assert kept.note == "예전 메모"
    assert invalidations == [None]


async def test_add_only_existing_returns_nothing_new(authed, ctx):
    await add_entry(ctx, "already_here")
    lead = await add_lead(ctx, "Already_Here", LeadStatus.REVIEWED)

    res = await post(authed, ["@already_here"])

    assert res.status_code == 200, res.text
    assert res.json() == []
    assert await stored_usernames(ctx) == ["already_here"]
    assert await lead_status(ctx, lead) == LeadStatus.EXCLUDED


@pytest.mark.parametrize("note", [None, "", "   "])
async def test_add_without_note(authed, note):
    res = await post(authed, ["someone"], note=note)

    assert res.status_code == 200, res.text
    assert res.json()[0]["note"] is None


async def test_add_excludes_matching_leads(authed, ctx):
    same_case = await add_lead(ctx, "kim_trader")
    other_case = await add_lead(ctx, "PROMO_Bot", LeadStatus.CONTACTED)
    already = await add_lead(ctx, "old_spam", LeadStatus.EXCLUDED)
    similar = await add_lead(ctx, "kim_trader2")
    wildcard = await add_lead(ctx, "kimxtrader")
    untouched = await add_lead(ctx, "bystander", LeadStatus.REVIEWED)

    res = await post(authed, ["Kim_Trader", "@promo_bot", "old_spam"])

    assert res.status_code == 200, res.text
    assert await lead_status(ctx, same_case) == LeadStatus.EXCLUDED
    assert await lead_status(ctx, other_case) == LeadStatus.EXCLUDED
    assert await lead_status(ctx, already) == LeadStatus.EXCLUDED
    assert await lead_status(ctx, similar) == LeadStatus.NEW
    assert await lead_status(ctx, wildcard) == LeadStatus.NEW
    assert await lead_status(ctx, untouched) == LeadStatus.REVIEWED


@pytest.mark.parametrize(
    "usernames",
    [["ab"], ["한글아이디", "kim trader"], ["   ", "@"], ["https://t.me/+AbCdEfGh1234"]],
)
async def test_add_rejects_when_nothing_is_valid(authed, ctx, invalidations, usernames):
    lead = await add_lead(ctx, "kim_trader")

    res = await post(authed, usernames)

    assert res.status_code == 400
    assert res.json()["code"] == "no_valid_username"
    assert "아이디" in res.json()["detail"]
    assert await stored_usernames(ctx) == []
    assert await lead_status(ctx, lead) == LeadStatus.NEW
    assert invalidations == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"usernames": []},
        {"usernames": "someone"},
        {"usernames": [f"user_{i}" for i in range(1001)]},
        {"usernames": ["someone"], "note": "가" * 201},
    ],
)
async def test_add_rejects_malformed_body(authed, ctx, invalidations, payload):
    res = await authed.post("/api/blocklist", json=payload)

    assert res.status_code == 422
    assert await stored_usernames(ctx) == []
    assert invalidations == []


async def test_add_accepts_a_thousand_names(authed, ctx):
    names = [f"user_{i}" for i in range(1000)]

    res = await post(authed, names)

    assert res.status_code == 200, res.text
    assert [e["username"] for e in res.json()] == names
    assert len(await stored_usernames(ctx)) == 1000


async def test_same_request_twice_at_once_adds_each_name_once(authed, ctx, monkeypatch):
    lead = await add_lead(ctx, "Double_Click")
    add_now = blocklist_router.add_blocked_usernames

    async def add_slowly(*args: Any, **kwargs: Any) -> list[BlocklistEntry]:
        # 확인과 커밋 사이를 벌려, 두 요청이 겹치면 반드시 서로의 틈에 끼어들게 한다.
        created = await add_now(*args, **kwargs)
        await asyncio.sleep(0.05)
        return created

    monkeypatch.setattr(blocklist_router, "add_blocked_usernames", add_slowly)

    first, second = await asyncio.gather(
        post(authed, ["double_click", "second_name"]),
        post(authed, ["@Double_Click", "second_name"]),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    created = [e["username"] for e in first.json()] + [e["username"] for e in second.json()]
    assert sorted(created) == ["double_click", "second_name"]
    assert sorted(await stored_usernames(ctx)) == ["double_click", "second_name"]
    assert await lead_status(ctx, lead) == LeadStatus.EXCLUDED


# --- 삭제 --------------------------------------------------------------------


async def test_delete_removes_entry_only(authed, ctx, invalidations):
    entry = await add_entry(ctx, "kim_trader")
    other = await add_entry(ctx, "bystander")
    lead = await add_lead(ctx, "kim_trader", LeadStatus.EXCLUDED)

    res = await authed.delete(f"/api/blocklist/{entry.id}")

    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True}
    assert await stored_usernames(ctx) == ["bystander"]
    assert await lead_status(ctx, lead) == LeadStatus.EXCLUDED
    assert invalidations == [None]

    listed = await authed.get("/api/blocklist")
    assert [e["id"] for e in listed.json()] == [other.id]


async def test_deleted_name_can_be_added_again(authed, ctx):
    entry = await add_entry(ctx, "kim_trader")
    await authed.delete(f"/api/blocklist/{entry.id}")

    res = await post(authed, ["kim_trader"])

    assert res.status_code == 200, res.text
    assert [e["username"] for e in res.json()] == ["kim_trader"]


async def test_delete_unknown_entry(authed, ctx, invalidations):
    await add_entry(ctx, "kim_trader")

    res = await authed.delete("/api/blocklist/999")

    assert res.status_code == 404
    assert res.json()["code"] == "not_found"
    assert res.json()["detail"] == "제외 목록에서 그 아이디를 찾을 수 없어요."
    assert await stored_usernames(ctx) == ["kim_trader"]
    assert invalidations == []


@pytest.mark.parametrize("entry_id", ["abc", str(2**70)])
async def test_delete_rejects_bad_id(authed, entry_id):
    res = await authed.delete(f"/api/blocklist/{entry_id}")

    assert res.status_code == 422


# --- 수집기와 맞물림 ----------------------------------------------------------


async def test_collector_is_told_only_after_commit(authed, ctx, monkeypatch):
    """커밋보다 먼저 캐시를 버리면 수집기가 예전 제외 목록을 다시 읽어 버린다."""
    database_file = ctx.config.data_dir / "chatdb.sqlite3"
    lead = await add_lead(ctx, "Kim_Trader")
    committed: list[tuple[list[str], str]] = []

    def probe() -> None:
        with closing(sqlite3.connect(database_file)) as conn:
            names = [row[0] for row in conn.execute("SELECT username FROM blocklist ORDER BY id")]
            status = conn.execute("SELECT status FROM leads WHERE id = ?", (lead.id,)).fetchone()
        committed.append((names, status[0]))

    monkeypatch.setattr(ctx.collector, "invalidate", probe)

    created = await post(authed, ["kim_trader"])
    await authed.delete(f"/api/blocklist/{created.json()[0]['id']}")

    assert committed == [(["kim_trader"], "excluded"), ([], "excluded")]
