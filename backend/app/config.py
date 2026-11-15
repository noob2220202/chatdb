"""환경 설정. 모든 값은 CHATDB_ 접두사의 환경 변수로 덮어쓸 수 있다."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHATDB_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    database_url: str | None = None
    """비워 두면 data_dir 아래 SQLite 파일을 쓴다."""

    secret_key: str | None = None
    """쿠키 서명과 세션 문자열 암호화에 쓰는 비밀 값. 비워 두면 data_dir/secret.key 를 만들어 재사용한다."""

    demo: bool = False
    """True 면 텔레그램에 접속하지 않고 가짜 트래픽으로 동작한다(화면 확인·테스트용)."""

    tg_api_id: int | None = None
    tg_api_hash: str | None = None

    cookie_secure: bool = False
    """HTTPS 뒤에서 서비스할 때 True 로 둔다."""
    session_max_age_days: int = 30

    host: str = "127.0.0.1"
    port: int = 8000
    static_dir: Path | None = None
    """빌드된 프론트엔드(dist) 경로. 지정하면 API 와 같은 서버에서 함께 서비스한다."""

    log_level: str = "INFO"
    engine_enabled: bool = Field(default=True)
    """False 면 텔레그램 엔진을 띄우지 않는다(테스트용)."""

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{(self.data_dir / 'chatdb.sqlite3').resolve()}"

    def resolved_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / "secret.key"
        if path.exists():
            return path.read_text().strip()
        key = secrets.token_urlsafe(48)
        path.touch(mode=0o600)
        path.write_text(key)
        return key


@lru_cache
def get_config() -> Config:
    return Config()
