"""엔진: 계정 연결을 유지하고, 그룹 가입 대기열을 처리하고, 메시지를 수집기에 넘긴다.

아래 공개 메서드의 이름·인자·동작은 라우터가 기대하는 계약이다(바꾸지 않는다).
"""

from __future__ import annotations

from ..db import Database
from ..events import EventBus
from ..models import Account
from ..security import Secrets
from ..services.collector import Collector
from ..services.logbook import Logbook
from ..settings_store import SettingsStore
from .gateway import LoginResult, PendingLogin, TelegramGateway, TgChat


class Engine:
    def __init__(
        self,
        *,
        db: Database,
        bus: EventBus,
        settings: SettingsStore,
        secrets: Secrets,
        gateway: TelegramGateway,
        collector: Collector,
        logbook: Logbook,
    ) -> None:
        self.db = db
        self.bus = bus
        self.settings = settings
        self.secrets = secrets
        self.gateway = gateway
        self.collector = collector
        self.logbook = logbook

    # --- 수명 주기 ---------------------------------------------------------

    async def start(self) -> None:
        """엔진을 켠다. enabled 이고 세션이 있는 계정마다 연결 태스크를 띄우고 수집기를 시작한다.

        이미 켜져 있으면 아무것도 하지 않는다.
        """
        raise NotImplementedError

    async def stop(self) -> None:
        """모든 태스크를 멈추고 연결을 끊는다. 수집기도 멈춘다(flush 포함)."""
        raise NotImplementedError

    # --- 로그인 · 세션 불러오기 --------------------------------------------
    # 텔레그램 쪽 실패는 TelegramError 를 그대로 올린다(라우터가 HTTP 오류로 바꾼다).

    async def start_login(self, phone: str) -> PendingLogin:
        raise NotImplementedError

    async def submit_code(self, login_id: str, code: str) -> tuple[LoginResult, Account | None]:
        """코드를 넣는다. 로그인이 끝나면(status=done) 계정을 저장·연결하고 함께 돌려준다."""
        raise NotImplementedError

    async def submit_password(
        self, login_id: str, password: str
    ) -> tuple[LoginResult, Account | None]:
        raise NotImplementedError

    async def cancel_login(self, login_id: str) -> None:
        raise NotImplementedError

    async def import_session(self, data: str | bytes, label: str | None = None) -> Account:
        """세션 문자열(str) 또는 .session 파일 내용(bytes)을 불러와 계정으로 저장·연결한다.

        같은 텔레그램 유저의 계정이 이미 있으면 새로 만들지 않고 그 계정의 세션을 바꿔 끼운다
        (다시 로그인하는 경우). 로그인 완료 때도 같은 규칙이다.
        """
        raise NotImplementedError

    # --- 계정 제어 ---------------------------------------------------------

    async def set_account_enabled(self, account_id: int, enabled: bool) -> None:
        """계정을 켜거나 끈다. 끄면 연결을 끊고 status=offline, 켜면 다시 연결한다."""
        raise NotImplementedError

    async def reconnect(self, account_id: int) -> None:
        """연결을 끊었다가 다시 붙인다."""
        raise NotImplementedError

    async def remove_account(self, account_id: int, *, log_out: bool = False) -> None:
        """계정을 지운다(그룹 행도 함께). log_out=True 면 텔레그램에서도 세션을 로그아웃한다."""
        raise NotImplementedError

    def is_connected(self, account_id: int) -> bool:
        raise NotImplementedError

    async def list_dialogs(self, account_id: int) -> list[TgChat]:
        """계정이 이미 들어가 있는 그룹 목록. 연결돼 있지 않으면 TelegramError(NETWORK)."""
        raise NotImplementedError

    # --- 그룹 --------------------------------------------------------------

    def notify_groups_changed(self, account_id: int | None = None) -> None:
        """그룹 행이 추가·변경·삭제됐음을 알린다.

        감시 대상 맵을 다시 읽고 가입 대기열을 깨운다. account_id 를 주면 그 계정만.
        """
        raise NotImplementedError

    async def leave_group(self, group_id: int) -> None:
        """텔레그램에서 그룹을 나간다(가능하면). 행은 지우지 않는다. 실패해도 예외를 올리지 않는다."""
        raise NotImplementedError

    # --- 설정 --------------------------------------------------------------

    def notify_settings_changed(self) -> None:
        """설정이 바뀌었음을 알린다(가입 간격, 계정당 그룹 수, API 키 등)."""
        raise NotImplementedError
