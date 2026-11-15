"""앱 진입점. `uvicorn app.main:app` 으로 띄운다."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import Config, get_config
from .context import build_context
from .errors import ApiError, from_telegram
from .routers import (
    accounts,
    auth,
    blocklist,
    groups,
    leads,
    logs,
    overview,
    rules,
    settings,
    stream,
)
from .telegram.gateway import TelegramError, TelegramGateway

logger = logging.getLogger("chatdb")

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_FIELD_LABELS = {
    "password": "비밀번호",
    "new_password": "새 비밀번호",
    "current_password": "현재 비밀번호",
    "phone": "전화번호",
    "code": "인증 코드",
    "name": "이름",
    "keywords": "키워드",
    "links": "링크",
    "min_messages": "메시지 수",
    "window_hours": "기간",
    "session_string": "세션 문자열",
    "tg_api_id": "api_id",
    "tg_api_hash": "api_hash",
    "max_groups_per_account": "계정당 그룹 수",
    "join_interval_seconds": "가입 간격",
    "retention_days": "보관 기간",
}


def _error_body(detail: str, code: str | None = None, retry_after: int | None = None) -> dict:
    return {"detail": detail, "code": code, "retry_after": retry_after}


def _validation_message(exc: RequestValidationError) -> str:
    """검증 오류를 한국어 한 문장으로 바꾼다."""
    errors = exc.errors()
    if not errors:
        return "입력값을 다시 확인해 주세요."
    first = errors[0]
    message = str(first.get("msg", ""))
    if first.get("type") == "value_error" and message.startswith("Value error, "):
        return message.removeprefix("Value error, ")
    field = next((str(p) for p in reversed(first.get("loc", ())) if isinstance(p, str)), "")
    label = _FIELD_LABELS.get(field)
    kind = str(first.get("type", ""))
    if label:
        if kind in {"string_too_short", "too_short"}:
            return f"{label} 값이 너무 짧아요."
        if kind in {"string_too_long", "too_long"}:
            return f"{label} 값이 너무 길어요."
        if kind == "missing":
            return f"{label} 값을 넣어 주세요."
        return f"{label} 값을 다시 확인해 주세요."
    return "입력값을 다시 확인해 주세요."


def create_app(config: Config | None = None, gateway: TelegramGateway | None = None) -> FastAPI:
    config = config or get_config()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ctx = build_context(config, gateway)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        config.data_dir.mkdir(parents=True, exist_ok=True)
        await ctx.db.create_all()
        if config.demo:
            from .demo_seed import ensure_demo_data

            await ensure_demo_data(ctx)
        if config.engine_enabled:
            await ctx.engine.start()
        try:
            yield
        finally:
            if config.engine_enabled:
                await ctx.engine.stop()
            await ctx.db.dispose()

    app = FastAPI(
        title="ChatDB",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.ctx = ctx

    # --- 미들웨어 ----------------------------------------------------------

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # 다른 사이트에서 보낸 변경 요청을 막는다(쿠키는 SameSite=Strict 이지만 한 겹 더).
        if request.method in _UNSAFE_METHODS and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            host = request.headers.get("host")
            if origin and host and urlsplit(origin).netloc != host:
                return JSONResponse(
                    _error_body("허용되지 않은 출처의 요청이에요.", "bad_origin"), status_code=403
                )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # --- 오류 처리 ---------------------------------------------------------

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return JSONResponse(
            _error_body(exc.detail, exc.code, exc.retry_after),
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(TelegramError)
    async def _telegram_error(request: Request, exc: TelegramError):
        return await _api_error(request, from_telegram(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(_error_body(_validation_message(exc), "validation"), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "요청을 처리할 수 없어요."
        if exc.status_code == 404:
            detail = "찾을 수 없어요."
        elif exc.status_code == 405:
            detail = "허용되지 않은 요청이에요."
        return JSONResponse(_error_body(detail, "http_error"), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception):
        logger.exception("처리하지 못한 오류", exc_info=exc)
        return JSONResponse(
            _error_body("서버에서 문제가 생겼어요. 잠시 뒤에 다시 시도해 주세요.", "server_error"),
            status_code=500,
        )

    # --- 라우터 ------------------------------------------------------------

    @app.get("/api/health", include_in_schema=False)
    async def health():
        return {"ok": True, "version": __version__}

    for module in (
        auth, accounts, groups, rules, leads, blocklist, logs, settings, overview, stream,
    ):  # fmt: skip
        app.include_router(module.router, prefix="/api")

    # --- 프론트엔드(빌드 결과물) -------------------------------------------

    static_dir = config.static_dir
    if static_dir and (static_dir / "index.html").exists():
        root = static_dir.resolve()
        if (root / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse(_error_body("찾을 수 없어요.", "http_error"), status_code=404)
            candidate = (root / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(root):
                return FileResponse(candidate)
            return FileResponse(Path(root / "index.html"), headers={"Cache-Control": "no-cache"})

    return app


def __getattr__(name: str):
    # `uvicorn app.main:app` 을 위한 지연 생성 (import 만으로는 앱을 만들지 않는다).
    if name == "app":
        return create_app()
    raise AttributeError(name)
