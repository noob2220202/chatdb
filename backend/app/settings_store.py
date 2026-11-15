"""콘솔에서 바꾸는 설정. settings 테이블에 JSON 으로 저장하고 메모리에 캐시한다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from .config import Config
from .db import Database
from .models import Setting
from .security import Secrets

DEFAULTS: dict[str, Any] = {
    "max_groups_per_account": 20,
    "join_interval_seconds": 90,
    "retention_days": 0,
    "store_excerpts": True,
    "timezone": "Asia/Seoul",
}


@dataclass(frozen=True)
class RuntimeSettings:
    tg_api_id: int | None
    tg_api_hash: str | None
    tg_api_source: Literal["settings", "env", "none"]
    max_groups_per_account: int
    join_interval_seconds: int
    retention_days: int
    store_excerpts: bool
    timezone: str

    @property
    def tzinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("Asia/Seoul")


class SettingsStore:
    def __init__(self, db: Database, secrets: Secrets, config: Config) -> None:
        self._db = db
        self._secrets = secrets
        self._config = config
        self._cache: RuntimeSettings | None = None

    async def _read_raw(self) -> dict[str, Any]:
        async with self._db.session() as session:
            rows = (await session.execute(select(Setting))).scalars().all()
        raw: dict[str, Any] = {}
        for row in rows:
            try:
                raw[row.key] = json.loads(row.value)
            except json.JSONDecodeError:
                continue
        return raw

    async def get(self) -> RuntimeSettings:
        if self._cache is None:
            raw = {**DEFAULTS, **await self._read_raw()}
            api_id = raw.get("tg_api_id")
            api_hash_enc = raw.get("tg_api_hash_enc")
            api_hash = self._secrets.decrypt(api_hash_enc) if api_hash_enc else None
            if api_id and api_hash:
                source: Literal["settings", "env", "none"] = "settings"
            elif self._config.tg_api_id and self._config.tg_api_hash:
                api_id, api_hash, source = self._config.tg_api_id, self._config.tg_api_hash, "env"
            else:
                api_id, api_hash, source = None, None, "none"
            self._cache = RuntimeSettings(
                tg_api_id=api_id,
                tg_api_hash=api_hash,
                tg_api_source=source,
                max_groups_per_account=int(raw["max_groups_per_account"]),
                join_interval_seconds=int(raw["join_interval_seconds"]),
                retention_days=int(raw["retention_days"]),
                store_excerpts=bool(raw["store_excerpts"]),
                timezone=str(raw["timezone"]),
            )
        return self._cache

    async def update(self, **changes: Any) -> RuntimeSettings:
        """None 이 아닌 값만 저장한다. tg_api_hash 는 암호화해서 넣는다."""
        to_store: dict[str, Any] = {}
        for key, value in changes.items():
            if value is None:
                continue
            if key == "tg_api_hash":
                to_store["tg_api_hash_enc"] = self._secrets.encrypt(value)
            elif key == "timezone":
                try:
                    ZoneInfo(value)
                except (ZoneInfoNotFoundError, ValueError) as exc:
                    raise ValueError("알 수 없는 시간대예요.") from exc
                to_store[key] = value
            elif key in DEFAULTS or key == "tg_api_id":
                to_store[key] = value
        if to_store:
            async with self._db.session() as session:
                for key, value in to_store.items():
                    row = await session.get(Setting, key)
                    encoded = json.dumps(value)
                    if row is None:
                        session.add(Setting(key=key, value=encoded))
                    else:
                        row.value = encoded
                await session.commit()
            self._cache = None
        return await self.get()

    async def delete(self, *keys: str) -> RuntimeSettings:
        """저장된 값을 지워 기본값(또는 환경 변수)으로 돌린다. tg_api_hash 는 암호화된 키도 함께 지운다."""
        names = set(keys)
        if "tg_api_hash" in names:
            names.add("tg_api_hash_enc")
        async with self._db.session() as session:
            for key in names:
                row = await session.get(Setting, key)
                if row is not None:
                    await session.delete(row)
            await session.commit()
        self._cache = None
        return await self.get()

    def peek(self) -> RuntimeSettings | None:
        """캐시된 값(없으면 None). 동기 코드에서 급히 볼 때만 쓴다."""
        return self._cache
