"""공용 픽스처. 여러 테스트 파일이 같이 쓰므로 고치지 않는다(필요한 픽스처는 각 테스트 파일에 둔다)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Config
from app.context import AppContext
from app.main import create_app

from .stubs import NullGateway, StubEngine

ADMIN_PASSWORD = "correct horse battery"


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(
        _env_file=None,
        data_dir=tmp_path,
        secret_key="test-secret-key",
        engine_enabled=False,
        demo=False,
    )


@pytest_asyncio.fixture
async def app(config):
    """엔진 대신 StubEngine 을 끼운 앱. DB 는 테스트마다 새 SQLite 파일이다."""
    application = create_app(config, gateway=NullGateway())
    stub = StubEngine()
    stub.collector = application.state.ctx.collector
    application.state.ctx.engine = stub
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
def ctx(app) -> AppContext:
    return app.state.ctx


@pytest.fixture
def engine(ctx) -> StubEngine:
    return ctx.engine


@pytest_asyncio.fixture
async def client(app):
    """로그인하지 않은 클라이언트."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest_asyncio.fixture
async def authed(client):
    """관리자 비밀번호를 만들고 로그인까지 한 클라이언트."""
    res = await client.post("/api/auth/setup", json={"password": ADMIN_PASSWORD})
    assert res.status_code == 200, res.text
    return client
