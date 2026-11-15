"""수집기: 그룹 메시지를 받아 규칙에 걸린 사람을 수집함에 넣는다.

아래 공개 메서드의 이름·인자·동작은 엔진과 라우터가 기대하는 계약이다(바꾸지 않는다).
"""

from __future__ import annotations

from ..db import Database
from ..events import EventBus
from ..settings_store import SettingsStore
from ..telegram.gateway import IncomingMessage
from .logbook import Logbook


class Collector:
    def __init__(
        self, *, db: Database, bus: EventBus, settings: SettingsStore, logbook: Logbook
    ) -> None:
        self._db = db
        self._bus = bus
        self._settings = settings
        self._logbook = logbook

    async def start(self) -> None:
        """주기적으로 flush() 를 부르는 백그라운드 태스크를 띄운다. 이미 떠 있으면 아무것도 안 한다."""
        raise NotImplementedError

    async def stop(self) -> None:
        """백그라운드 태스크를 멈추고 남은 버퍼를 flush 한다."""
        raise NotImplementedError

    def invalidate(self) -> None:
        """규칙, 규칙의 적용 그룹, 제외 목록, 제외 상태 유저, 내 계정 id 캐시를 버린다.

        규칙·제외 목록·유저 상태·계정이 바뀔 때마다 라우터와 엔진이 부른다.
        다음 메시지를 처리할 때 다시 읽는다.
        """
        raise NotImplementedError

    async def handle(self, message: IncomingMessage, group_id: int) -> None:
        """그룹 메시지 하나를 처리한다. group_id 는 groups.id 다.

        예외를 밖으로 던지지 않는다(한 메시지의 실패가 수신 루프를 멈추면 안 된다).
        """
        raise NotImplementedError

    async def flush(self) -> None:
        """버퍼에 쌓인 그룹 카운터와 활동량을 DB 에 반영하고 활동량 규칙을 평가한다."""
        raise NotImplementedError
