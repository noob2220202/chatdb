"""/api/auth 테스트."""

from __future__ import annotations

import asyncio
from http.cookies import SimpleCookie

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select

from app.config import Config
from app.models import Admin, EventLog, LogLevel
from app.security import COOKIE_NAME, Secrets, verify_password

from .conftest import ADMIN_PASSWORD

NEW_PASSWORD = "brand new password"
WRONG_PASSWORD = "not the password"


class FakeClock:
    """LoginThrottle 이 보는 시계. 기다리지 않고 시간을 넘긴다."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr("app.security.time", fake)
    return fake


def new_client(app, host: str = "127.0.0.1") -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=(host, 50000)), base_url="http://testserver"
    )


@pytest_asyncio.fixture
async def other(app):
    """같은 서버에 붙은 두 번째 브라우저."""
    async with new_client(app) as c:
        yield c


def session_cookie(res: Response) -> SimpleCookie:
    cookie = SimpleCookie()
    cookie.load(res.headers["set-cookie"])
    assert COOKIE_NAME in cookie
    return cookie


async def login(client: AsyncClient, password: str = ADMIN_PASSWORD, **kwargs) -> Response:
    return await client.post("/api/auth/login", json={"password": password}, **kwargs)


async def status(client: AsyncClient) -> dict:
    res = await client.get("/api/auth/status")
    assert res.status_code == 200, res.text
    return res.json()


async def admin_row(ctx) -> Admin:
    async with ctx.db.session() as session:
        return (await session.execute(select(Admin))).scalar_one()


# --- 상태 --------------------------------------------------------------------


async def test_status_before_setup(client):
    assert await status(client) == {"setup_required": True, "authenticated": False, "demo": False}


async def test_status_after_setup_from_another_browser(authed, other):
    assert await status(other) == {"setup_required": False, "authenticated": False, "demo": False}
    assert (await status(authed))["authenticated"] is True


async def test_status_ignores_broken_cookie(authed, other):
    other.cookies.set(COOKIE_NAME, "garbage")
    assert (await status(other))["authenticated"] is False


async def test_status_ignores_cookie_signed_with_another_key(authed, other):
    forged = Secrets("some-other-key", 3600).issue_token(1)
    other.cookies.set(COOKIE_NAME, forged)
    assert (await status(other))["authenticated"] is False
    assert (await other.get("/api/settings")).status_code == 401


async def test_status_reports_demo_mode(client, ctx):
    ctx.config.demo = True
    assert (await status(client))["demo"] is True


# --- 처음 설정 ----------------------------------------------------------------


async def test_setup_creates_admin_and_logs_in(client, ctx):
    res = await client.post("/api/auth/setup", json={"password": ADMIN_PASSWORD})

    assert res.status_code == 200
    assert res.json() == {"setup_required": False, "authenticated": True, "demo": False}
    admin = await admin_row(ctx)
    assert admin.password_hash != ADMIN_PASSWORD
    assert verify_password(admin.password_hash, ADMIN_PASSWORD)
    assert admin.token_version == 1
    assert (await status(client))["authenticated"] is True
    assert (await client.get("/api/settings")).status_code == 200


async def test_setup_cookie_attributes(client, config):
    res = await client.post("/api/auth/setup", json={"password": ADMIN_PASSWORD})

    morsel = session_cookie(res)[COOKIE_NAME]
    assert morsel["httponly"] is True
    assert morsel["samesite"] == "strict"
    assert morsel["path"] == "/"
    assert int(morsel["max-age"]) == config.session_max_age_days * 86400
    assert not morsel["secure"]


async def test_setup_rejects_short_password(client):
    res = await client.post("/api/auth/setup", json={"password": "short"})

    assert res.status_code == 422
    assert res.json()["detail"] == "비밀번호 값이 너무 짧아요."
    assert (await status(client))["setup_required"] is True


async def test_setup_only_once(authed, other, ctx):
    res = await other.post("/api/auth/setup", json={"password": "another password"})

    assert res.status_code == 409
    assert res.json()["code"] == "already_setup"
    assert "set-cookie" not in res.headers
    admin = await admin_row(ctx)
    assert verify_password(admin.password_hash, ADMIN_PASSWORD)


async def test_concurrent_setup_keeps_a_single_admin(app, ctx):
    async with new_client(app) as a, new_client(app) as b:
        results = await asyncio.gather(
            a.post("/api/auth/setup", json={"password": "first password"}),
            b.post("/api/auth/setup", json={"password": "second password"}),
        )

    assert sorted(res.status_code for res in results) == [200, 409]
    async with ctx.db.session() as session:
        assert (await session.execute(select(func.count()).select_from(Admin))).scalar_one() == 1


class TestSecureCookie:
    @pytest.fixture
    def config(self, tmp_path) -> Config:
        return Config(
            _env_file=None,
            data_dir=tmp_path,
            secret_key="test-secret-key",
            engine_enabled=False,
            cookie_secure=True,
            session_max_age_days=7,
        )

    async def test_cookie_follows_config(self, client):
        res = await client.post("/api/auth/setup", json={"password": ADMIN_PASSWORD})

        morsel = session_cookie(res)[COOKIE_NAME]
        assert morsel["secure"] is True
        assert int(morsel["max-age"]) == 7 * 86400

    async def test_logout_clears_the_secure_cookie(self, client):
        res = await client.post("/api/auth/logout")

        morsel = session_cookie(res)[COOKIE_NAME]
        assert morsel["secure"] is True
        assert int(morsel["max-age"]) == 0


# --- 로그인 -------------------------------------------------------------------


async def test_login_success_sets_cookie(authed, other):
    res = await login(other)

    assert res.status_code == 200
    assert res.json() == {"setup_required": False, "authenticated": True, "demo": False}
    morsel = session_cookie(res)[COOKIE_NAME]
    assert morsel["httponly"] is True
    assert morsel["samesite"] == "strict"
    assert (await other.get("/api/settings")).status_code == 200


async def test_login_wrong_password(authed, other):
    res = await login(other, WRONG_PASSWORD)

    assert res.status_code == 401
    assert res.json()["detail"] == "비밀번호가 맞지 않아요."
    assert "set-cookie" not in res.headers
    assert (await other.get("/api/settings")).status_code == 401


async def test_login_before_setup(client):
    res = await login(client)

    assert res.status_code == 409
    assert res.json()["code"] == "setup_required"


async def test_login_requires_password_field(authed, other):
    res = await other.post("/api/auth/login", json={})

    assert res.status_code == 422
    assert res.json()["detail"] == "비밀번호 값을 넣어 주세요."


# --- 로그인 제한 --------------------------------------------------------------


async def test_login_locks_after_repeated_failures(authed, other, ctx, clock):
    for _ in range(ctx.throttle.limit):
        assert (await login(other, WRONG_PASSWORD)).status_code == 401

    # 잠긴 뒤에는 맞는 비밀번호도 받지 않는다.
    res = await login(other)
    assert res.status_code == 429
    body = res.json()
    assert body["code"] == "too_many_attempts"
    assert body["retry_after"] == ctx.throttle.window
    assert res.headers["retry-after"] == str(ctx.throttle.window)
    assert "15분 뒤에" in body["detail"]
    assert "set-cookie" not in res.headers


async def test_login_unlocks_after_the_window(authed, other, ctx, clock):
    for _ in range(ctx.throttle.limit):
        await login(other, WRONG_PASSWORD)
    clock.now += ctx.throttle.window - 30
    res = await login(other)
    assert res.status_code == 429
    assert res.json()["retry_after"] == 30
    assert "30초 뒤에" in res.json()["detail"]

    clock.now += 31
    assert (await login(other)).status_code == 200


async def test_login_success_resets_the_failure_count(authed, other, ctx, clock):
    for _ in range(ctx.throttle.limit - 1):
        assert (await login(other, WRONG_PASSWORD)).status_code == 401
    assert (await login(other)).status_code == 200

    for _ in range(ctx.throttle.limit - 1):
        assert (await login(other, WRONG_PASSWORD)).status_code == 401
    assert (await login(other)).status_code == 200


async def test_login_lock_is_per_client_address(app, authed, ctx, clock):
    async with new_client(app, "10.0.0.5") as attacker, new_client(app, "10.0.0.6") as owner:
        for _ in range(ctx.throttle.limit):
            await login(attacker, WRONG_PASSWORD)

        assert (await login(attacker)).status_code == 429
        assert (await login(owner)).status_code == 200


async def test_login_lock_ignores_forwarded_for(authed, other, ctx, clock):
    for i in range(ctx.throttle.limit):
        await login(other, WRONG_PASSWORD, headers={"X-Forwarded-For": f"203.0.113.{i}"})

    res = await login(other, headers={"X-Forwarded-For": "198.51.100.7"})
    assert res.status_code == 429


async def test_login_burst_cannot_exceed_the_limit(app, authed, ctx, clock):
    async with new_client(app, "10.0.0.9") as attacker:
        results = await asyncio.gather(*(login(attacker, f"guess {i}") for i in range(12)))

    codes = [res.status_code for res in results]
    assert codes.count(401) == ctx.throttle.limit
    assert codes.count(429) == 12 - ctx.throttle.limit


async def test_login_lock_is_written_to_the_logbook(authed, other, ctx, clock):
    for _ in range(ctx.throttle.limit):
        await login(other, WRONG_PASSWORD)

    async with ctx.db.session() as session:
        logs = (await session.execute(select(EventLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].level == LogLevel.WARNING
    assert "127.0.0.1" in logs[0].message


# --- 로그아웃 -----------------------------------------------------------------


async def test_logout_clears_cookie(authed):
    res = await authed.post("/api/auth/logout")

    assert res.status_code == 200
    assert res.json() == {"ok": True}
    morsel = session_cookie(res)[COOKIE_NAME]
    assert morsel.value == ""
    assert int(morsel["max-age"]) == 0
    assert morsel["path"] == "/"
    assert (await status(authed))["authenticated"] is False
    assert (await authed.get("/api/settings")).status_code == 401


async def test_logout_without_login_is_fine(client):
    res = await client.post("/api/auth/logout")

    assert res.status_code == 200
    assert res.json() == {"ok": True}


async def test_logout_keeps_other_browsers_logged_in(authed, other):
    await login(other)
    await authed.post("/api/auth/logout")

    assert (await status(other))["authenticated"] is True


# --- 비밀번호 변경 -------------------------------------------------------------


async def change_password(
    client: AsyncClient, current: str = ADMIN_PASSWORD, new: str = NEW_PASSWORD
) -> Response:
    return await client.post(
        "/api/auth/password", json={"current_password": current, "new_password": new}
    )


async def test_password_change_requires_login(client, authed, other):
    res = await change_password(other)

    assert res.status_code == 401
    assert res.json() == {"detail": "로그인이 필요해요.", "code": "unauthorized", "retry_after": None}


async def test_password_change_success(authed, other, ctx):
    res = await change_password(authed)

    assert res.status_code == 200
    assert res.json() == {"ok": True}
    admin = await admin_row(ctx)
    assert admin.token_version == 2
    assert verify_password(admin.password_hash, NEW_PASSWORD)
    assert (await login(other, ADMIN_PASSWORD)).status_code == 401
    assert (await login(other, NEW_PASSWORD)).status_code == 200


async def test_password_change_invalidates_other_cookies_but_keeps_this_one(authed, other):
    await login(other)
    stolen = other.cookies.get(COOKIE_NAME)
    assert (await other.get("/api/settings")).status_code == 200

    res = await change_password(authed)

    # 바꾼 쪽은 새 쿠키를 받아 계속 쓴다.
    morsel = session_cookie(res)[COOKIE_NAME]
    assert morsel.value != stolen
    assert morsel["httponly"] is True
    assert morsel["samesite"] == "strict"
    assert (await authed.get("/api/settings")).status_code == 200
    assert (await status(authed))["authenticated"] is True
    # 다른 브라우저의 예전 쿠키는 더는 통하지 않는다.
    assert (await other.get("/api/settings")).status_code == 401
    assert (await status(other))["authenticated"] is False


async def test_password_change_wrong_current(authed, ctx):
    res = await change_password(authed, current=WRONG_PASSWORD)

    assert res.status_code == 400
    assert res.json()["detail"] == "현재 비밀번호가 맞지 않아요."
    assert res.json()["code"] == "wrong_password"
    assert "set-cookie" not in res.headers
    admin = await admin_row(ctx)
    assert admin.token_version == 1
    assert verify_password(admin.password_hash, ADMIN_PASSWORD)
    assert (await authed.get("/api/settings")).status_code == 200


async def test_password_change_rejects_same_password(authed, ctx):
    res = await change_password(authed, new=ADMIN_PASSWORD)

    assert res.status_code == 400
    assert res.json()["code"] == "same_password"
    assert (await admin_row(ctx)).token_version == 1


async def test_password_change_rejects_short_new_password(authed, ctx):
    res = await change_password(authed, new="short")

    assert res.status_code == 422
    assert res.json()["detail"] == "새 비밀번호 값이 너무 짧아요."
    assert (await admin_row(ctx)).token_version == 1


async def test_password_change_is_throttled_like_login(authed, ctx, clock):
    for _ in range(ctx.throttle.limit):
        assert (await change_password(authed, current=WRONG_PASSWORD)).status_code == 400

    res = await change_password(authed)
    assert res.status_code == 429
    assert res.json()["retry_after"] == ctx.throttle.window
    assert (await admin_row(ctx)).token_version == 1

    clock.now += ctx.throttle.window + 1
    assert (await change_password(authed)).status_code == 200
