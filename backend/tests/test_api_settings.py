"""/api/settings 테스트."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app import __version__
from app.config import Config
from app.models import Setting

API_HASH = "0123456789abcdef0123456789abcdef"


async def stored_settings(ctx) -> dict[str, str]:
    async with ctx.db.session() as session:
        rows = (await session.execute(select(Setting))).scalars().all()
    return {row.key: row.value for row in rows}


# --- 로그인 필요 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/settings"),
        ("PATCH", "/api/settings"),
        ("DELETE", "/api/settings/telegram-api"),
    ],
)
async def test_requires_login(client, engine, method, path):
    res = await client.request(method, path, json={"retention_days": 7})

    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"
    assert engine.called("notify_settings_changed") == []


# --- 조회 --------------------------------------------------------------------


async def test_get_defaults(authed):
    res = await authed.get("/api/settings")

    assert res.status_code == 200
    assert res.json() == {
        "tg_api_id": None,
        "tg_api_hash_set": False,
        "tg_api_source": "none",
        "max_groups_per_account": 20,
        "join_interval_seconds": 90,
        "retention_days": 0,
        "store_excerpts": True,
        "timezone": "Asia/Seoul",
        "demo": False,
        "version": __version__,
    }


# --- 변경 --------------------------------------------------------------------


async def test_patch_updates_and_persists(authed, engine):
    res = await authed.patch(
        "/api/settings",
        json={
            "max_groups_per_account": 35,
            "join_interval_seconds": 120,
            "retention_days": 30,
            "store_excerpts": False,
            "timezone": "Europe/Berlin",
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["max_groups_per_account"] == 35
    assert body["join_interval_seconds"] == 120
    assert body["retention_days"] == 30
    assert body["store_excerpts"] is False
    assert body["timezone"] == "Europe/Berlin"
    assert (await authed.get("/api/settings")).json() == body
    assert len(engine.called("notify_settings_changed")) == 1


async def test_patch_changes_only_sent_fields(authed):
    await authed.patch("/api/settings", json={"retention_days": 14})
    res = await authed.patch("/api/settings", json={"join_interval_seconds": 300})

    body = res.json()
    assert body["retention_days"] == 14
    assert body["join_interval_seconds"] == 300
    assert body["max_groups_per_account"] == 20


async def test_patch_null_fields_are_ignored(authed, engine):
    res = await authed.patch("/api/settings", json={"retention_days": None, "timezone": None})

    assert res.status_code == 200
    assert res.json()["retention_days"] == 0
    assert res.json()["timezone"] == "Asia/Seoul"
    assert engine.called("notify_settings_changed") == []


async def test_patch_empty_body_changes_nothing(authed, ctx, engine):
    res = await authed.patch("/api/settings", json={})

    assert res.status_code == 200
    assert res.json()["max_groups_per_account"] == 20
    assert await stored_settings(ctx) == {}
    assert engine.called("notify_settings_changed") == []


async def test_patch_api_credentials(authed, ctx, engine):
    res = await authed.patch("/api/settings", json={"tg_api_id": 123456, "tg_api_hash": API_HASH})

    assert res.status_code == 200
    body = res.json()
    assert body["tg_api_id"] == 123456
    assert body["tg_api_hash_set"] is True
    assert body["tg_api_source"] == "settings"
    # api_hash 는 응답으로 나가지 않고, DB 에도 평문으로 남지 않는다.
    assert API_HASH not in res.text
    assert "tg_api_hash" not in body
    stored = await stored_settings(ctx)
    assert all(API_HASH not in value for value in stored.values())
    assert (await ctx.settings.get()).tg_api_hash == API_HASH
    assert len(engine.called("notify_settings_changed")) == 1


async def test_patch_trims_pasted_api_hash(authed, ctx):
    res = await authed.patch(
        "/api/settings", json={"tg_api_id": 123456, "tg_api_hash": f"  {API_HASH}\n"}
    )

    assert res.status_code == 200
    assert (await ctx.settings.get()).tg_api_hash == API_HASH


async def test_patch_rejects_api_hash_that_is_mostly_spaces(authed, ctx, engine):
    res = await authed.patch(
        "/api/settings", json={"tg_api_id": 123456, "tg_api_hash": "  abc     "}
    )

    assert res.status_code == 422
    assert res.json()["code"] == "validation"
    assert res.json()["detail"] == "api_hash 값이 너무 짧아요."
    assert await stored_settings(ctx) == {}
    assert engine.called("notify_settings_changed") == []


@pytest.mark.parametrize("partial", [{"tg_api_id": 123456}, {"tg_api_hash": API_HASH}])
async def test_patch_half_a_credential_pair_is_rejected(authed, ctx, engine, partial):
    res = await authed.patch("/api/settings", json={**partial, "retention_days": 9})

    assert res.status_code == 400
    assert res.json()["code"] == "api_pair_required"
    assert res.json()["detail"] == "api_id 와 api_hash 를 함께 넣어 주세요."
    # 같이 보낸 다른 값도 저장하지 않는다.
    assert await stored_settings(ctx) == {}
    assert engine.called("notify_settings_changed") == []


@pytest.mark.parametrize(
    ("partial", "expected_id", "expected_hash"),
    [
        ({"tg_api_id": 777}, 777, API_HASH),
        ({"tg_api_hash": "ffffffffffffffffffffffffffffffff"}, 123456, "f" * 32),
    ],
)
async def test_patch_one_credential_when_a_pair_is_stored(
    authed, ctx, partial, expected_id, expected_hash
):
    await authed.patch("/api/settings", json={"tg_api_id": 123456, "tg_api_hash": API_HASH})

    res = await authed.patch("/api/settings", json=partial)

    assert res.status_code == 200
    assert res.json()["tg_api_source"] == "settings"
    current = await ctx.settings.get()
    assert (current.tg_api_id, current.tg_api_hash) == (expected_id, expected_hash)


@pytest.mark.parametrize("timezone", ["Mars/Olympus", "", "../etc/passwd", "seoul"])
async def test_patch_unknown_timezone(authed, ctx, engine, timezone):
    res = await authed.patch("/api/settings", json={"timezone": timezone, "retention_days": 5})

    assert res.status_code == 422
    assert res.json() == {
        "detail": "알 수 없는 시간대예요.",
        "code": "validation",
        "retry_after": None,
    }
    assert await stored_settings(ctx) == {}
    assert engine.called("notify_settings_changed") == []


async def test_patch_trims_timezone(authed):
    res = await authed.patch("/api/settings", json={"timezone": " UTC "})

    assert res.status_code == 200
    assert res.json()["timezone"] == "UTC"


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"max_groups_per_account": 0}, "계정당 그룹 수 값을 다시 확인해 주세요."),
        ({"max_groups_per_account": 501}, "계정당 그룹 수 값을 다시 확인해 주세요."),
        ({"join_interval_seconds": 10}, "가입 간격 값을 다시 확인해 주세요."),
        ({"retention_days": -1}, "보관 기간 값을 다시 확인해 주세요."),
        ({"tg_api_id": 0}, "api_id 값을 다시 확인해 주세요."),
        ({"tg_api_hash": "short"}, "api_hash 값이 너무 짧아요."),
    ],
)
async def test_patch_validation(authed, ctx, engine, payload, detail):
    res = await authed.patch("/api/settings", json=payload)

    assert res.status_code == 422
    assert res.json()["detail"] == detail
    assert await stored_settings(ctx) == {}
    assert engine.called("notify_settings_changed") == []


# --- API 키 지우기 -------------------------------------------------------------


async def test_delete_telegram_api(authed, ctx, engine):
    await authed.patch(
        "/api/settings",
        json={"tg_api_id": 123456, "tg_api_hash": API_HASH, "retention_days": 3},
    )

    res = await authed.delete("/api/settings/telegram-api")

    assert res.status_code == 200
    body = res.json()
    assert body["tg_api_id"] is None
    assert body["tg_api_hash_set"] is False
    assert body["tg_api_source"] == "none"
    # API 키만 지운다.
    assert body["retention_days"] == 3
    assert set(await stored_settings(ctx)) == {"retention_days"}
    assert len(engine.called("notify_settings_changed")) == 2


async def test_delete_telegram_api_when_nothing_is_stored(authed, engine):
    res = await authed.delete("/api/settings/telegram-api")

    assert res.status_code == 200
    assert res.json()["tg_api_source"] == "none"
    assert len(engine.called("notify_settings_changed")) == 1


class TestEnvCredentials:
    """환경 변수에 API 키가 있는 서버."""

    @pytest.fixture
    def config(self, tmp_path) -> Config:
        return Config(
            _env_file=None,
            data_dir=tmp_path,
            secret_key="test-secret-key",
            engine_enabled=False,
            tg_api_id=4242,
            tg_api_hash="e" * 32,
        )

    async def test_env_values_are_reported(self, authed):
        body = (await authed.get("/api/settings")).json()

        assert body["tg_api_id"] == 4242
        assert body["tg_api_hash_set"] is True
        assert body["tg_api_source"] == "env"
        assert "e" * 32 not in str(body)

    async def test_settings_override_env_and_delete_falls_back(self, authed):
        res = await authed.patch(
            "/api/settings", json={"tg_api_id": 123456, "tg_api_hash": API_HASH}
        )
        assert res.json()["tg_api_source"] == "settings"
        assert res.json()["tg_api_id"] == 123456

        res = await authed.delete("/api/settings/telegram-api")

        assert res.json()["tg_api_source"] == "env"
        assert res.json()["tg_api_id"] == 4242

    async def test_half_a_pair_cannot_override_env(self, authed, ctx):
        res = await authed.patch("/api/settings", json={"tg_api_id": 123456})

        assert res.status_code == 400
        assert res.json()["code"] == "api_pair_required"
        assert (await ctx.settings.get()).tg_api_id == 4242
