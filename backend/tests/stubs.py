"""테스트용 대역. 여러 테스트 파일이 같이 쓰므로 여기 있는 것은 고치지 말고, 필요하면 상속해서 쓴다."""

from __future__ import annotations

from typing import Any

from app.telegram.gateway import (
    AccountClient,
    LoginResult,
    PendingLogin,
    TelegramGateway,
    TgChat,
)


class NullGateway(TelegramGateway):
    """아무것도 하지 않는 게이트웨이. 엔진을 띄우지 않는 API 테스트에서 자리만 채운다."""

    def create_client(self, account_id: int, session: str) -> AccountClient:
        raise NotImplementedError

    async def start_login(self, phone: str) -> PendingLogin:
        raise NotImplementedError

    async def submit_code(self, login_id: str, code: str) -> LoginResult:
        raise NotImplementedError

    async def submit_password(self, login_id: str, password: str) -> LoginResult:
        raise NotImplementedError

    async def cancel_login(self, login_id: str) -> None:
        return None

    async def import_session(self, data: str | bytes) -> LoginResult:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class StubEngine:
    """라우터 테스트용 엔진 대역. 호출을 calls 에 기록하고 기본값을 돌려준다.

    로그인처럼 결과가 필요한 메서드는 테스트에서 상속해 덮어쓴다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.connected: set[int] = set()
        self.dialogs: dict[int, list[TgChat]] = {}
        self.collector: Any = None

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def called(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(a, k) for n, a, k in self.calls if n == name]

    async def start(self) -> None:
        self._record("start")

    async def stop(self) -> None:
        self._record("stop")

    async def start_login(self, phone: str) -> PendingLogin:
        raise NotImplementedError

    async def submit_code(self, login_id: str, code: str):
        raise NotImplementedError

    async def submit_password(self, login_id: str, password: str):
        raise NotImplementedError

    async def cancel_login(self, login_id: str) -> None:
        self._record("cancel_login", login_id)

    async def import_session(self, data: str | bytes, label: str | None = None):
        raise NotImplementedError

    async def set_account_enabled(self, account_id: int, enabled: bool) -> None:
        self._record("set_account_enabled", account_id, enabled)

    async def reconnect(self, account_id: int) -> None:
        self._record("reconnect", account_id)

    async def remove_account(self, account_id: int, *, log_out: bool = False) -> None:
        self._record("remove_account", account_id, log_out=log_out)

    def is_connected(self, account_id: int) -> bool:
        return account_id in self.connected

    async def list_dialogs(self, account_id: int) -> list[TgChat]:
        self._record("list_dialogs", account_id)
        return self.dialogs.get(account_id, [])

    def notify_groups_changed(self, account_id: int | None = None) -> None:
        self._record("notify_groups_changed", account_id)

    async def leave_group(self, group_id: int) -> None:
        self._record("leave_group", group_id)

    def notify_settings_changed(self) -> None:
        self._record("notify_settings_changed")
