"""API 오류. detail 은 화면에 그대로 보여 주는 한국어 문장이다."""

from __future__ import annotations


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.retry_after = retry_after


def not_found(what: str) -> ApiError:
    return ApiError(404, f"{what} 찾을 수 없어요.", code="not_found")


def bad_request(detail: str, code: str | None = None) -> ApiError:
    return ApiError(400, detail, code=code)


def conflict(detail: str, code: str | None = None) -> ApiError:
    return ApiError(409, detail, code=code)


def from_telegram(err: Exception) -> ApiError:
    """TelegramError 를 HTTP 오류로 바꾼다."""
    from .telegram.gateway import TelegramError, TgErrorCode

    if not isinstance(err, TelegramError):
        return ApiError(
            502,
            "텔레그램과 통신하다 문제가 생겼어요. 잠시 뒤에 다시 시도해 주세요.",
            code="unknown",
        )
    status = {
        TgErrorCode.FLOOD_WAIT: 429,
        TgErrorCode.NETWORK: 503,
        TgErrorCode.API_CREDENTIALS: 409,
        TgErrorCode.LOGIN_EXPIRED: 410,
        TgErrorCode.UNKNOWN: 502,
    }.get(err.code, 400)
    return ApiError(status, err.message, code=str(err.code), retry_after=err.retry_after)
