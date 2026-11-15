"""활동 기록 쓰기. DB 에 남기고 실시간 화면에도 알린다."""

from __future__ import annotations

import logging

from ..db import Database
from ..events import EventBus
from ..models import Account, EventLog, Group, LogCategory, LogLevel
from ..serializers import log_out

logger = logging.getLogger("chatdb.logbook")

_PY_LEVEL = {
    LogLevel.INFO: logging.INFO,
    LogLevel.WARNING: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
}


class Logbook:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        self._bus = bus

    async def write(
        self,
        message: str,
        *,
        level: LogLevel = LogLevel.INFO,
        category: LogCategory = LogCategory.SYSTEM,
        account_id: int | None = None,
        group_id: int | None = None,
    ) -> None:
        """기록 한 줄을 남긴다. message 는 한국어 해요체 한 문장으로 쓴다. 실패해도 예외를 올리지 않는다."""
        logger.log(_PY_LEVEL.get(level, logging.INFO), "[%s] %s", category, message)
        try:
            async with self._db.session() as session:
                entry = EventLog(
                    level=level,
                    category=category,
                    message=message[:500],
                    account_id=account_id,
                    group_id=group_id,
                )
                session.add(entry)
                await session.commit()
                account = await session.get(Account, account_id) if account_id else None
                group = await session.get(Group, group_id) if group_id else None
                payload = log_out(entry, account, group).model_dump(mode="json")
            self._bus.publish("log", payload)
        except Exception:  # noqa: BLE001 - 기록 실패가 본 작업을 막으면 안 된다
            logger.exception("활동 기록을 남기지 못했어요")

    async def info(self, message: str, **kw) -> None:
        await self.write(message, level=LogLevel.INFO, **kw)

    async def warning(self, message: str, **kw) -> None:
        await self.write(message, level=LogLevel.WARNING, **kw)

    async def error(self, message: str, **kw) -> None:
        await self.write(message, level=LogLevel.ERROR, **kw)
