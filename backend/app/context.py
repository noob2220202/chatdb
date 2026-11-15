"""앱 전체가 공유하는 객체 묶음."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .db import Database
from .events import EventBus
from .security import LoginThrottle, Secrets
from .services.collector import Collector
from .services.logbook import Logbook
from .settings_store import SettingsStore
from .telegram.engine import Engine
from .telegram.gateway import TelegramError, TelegramGateway, TgErrorCode


@dataclass
class AppContext:
    config: Config
    db: Database
    secrets: Secrets
    bus: EventBus
    settings: SettingsStore
    throttle: LoginThrottle
    logbook: Logbook
    collector: Collector
    engine: Engine


def build_gateway(config: Config, settings: SettingsStore) -> TelegramGateway:
    if config.demo:
        from .telegram.demo_gateway import DemoGateway

        return DemoGateway()

    from .telegram.telethon_gateway import TelethonGateway

    async def credentials() -> tuple[int, str]:
        current = await settings.get()
        if not current.tg_api_id or not current.tg_api_hash:
            raise TelegramError(
                TgErrorCode.API_CREDENTIALS,
                "텔레그램 API 키가 아직 없어요. 설정에서 api_id 와 api_hash 를 먼저 넣어 주세요.",
                permanent=True,
            )
        return current.tg_api_id, current.tg_api_hash

    return TelethonGateway(credentials)


def build_context(config: Config, gateway: TelegramGateway | None = None) -> AppContext:
    """객체들을 엮는다. gateway 를 주면 그것을 쓴다(테스트용)."""
    db = Database(config.resolved_database_url)
    secrets = Secrets(config.resolved_secret_key(), config.session_max_age_days * 86400)
    bus = EventBus()
    settings = SettingsStore(db, secrets, config)
    logbook = Logbook(db, bus)
    collector = Collector(db=db, bus=bus, settings=settings, logbook=logbook)
    engine = Engine(
        db=db,
        bus=bus,
        settings=settings,
        secrets=secrets,
        gateway=gateway or build_gateway(config, settings),
        collector=collector,
        logbook=logbook,
    )
    return AppContext(
        config=config,
        db=db,
        secrets=secrets,
        bus=bus,
        settings=settings,
        throttle=LoginThrottle(),
        logbook=logbook,
        collector=collector,
        engine=engine,
    )
