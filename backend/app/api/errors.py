from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

CONTRACT_ERRORS_BY_STATUS = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    502: "parse_failed",
    503: "llm_unavailable",
}
class APIError(Exception):
    def __init__(self, status_code: int, error: str, message: str) -> None:
        expected_error = CONTRACT_ERRORS_BY_STATUS.get(status_code)
        if expected_error is None or error != expected_error:
            raise ValueError(
                f"HTTP {status_code} must use its contract error code {expected_error!r}"
            )
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.message = message


def _response(status_code: int, error: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "message": message},
        headers=headers,
    )


async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    return api_error_response(exc)


def api_error_response(exc: APIError) -> JSONResponse:
    return _response(exc.status_code, exc.error, exc.message)


def http_error_response(
    status_code: int, detail: object, headers: dict[str, str] | None = None
) -> JSONResponse:
    error = CONTRACT_ERRORS_BY_STATUS.get(status_code)
    message = detail if isinstance(detail, str) else "Request could not be completed."
    if isinstance(detail, Mapping):
        detail_message = detail.get("message")
        if isinstance(detail_message, str):
            message = detail_message
    if error is None:
        # The contract has no code for other statuses, including HTTP 500.
        # Keep the generic server response safe without inventing a contract code.
        fallback_detail = "Internal Server Error" if status_code == 500 else detail
        return JSONResponse(
            status_code=status_code,
            content={"detail": fallback_detail},
            headers=headers,
        )
    return _response(status_code, error, message, headers)


async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return http_error_response(exc.status_code, exc.detail, exc.headers)


def request_validation_response() -> JSONResponse:
    return _response(422, "validation_error", "Request does not match the API contract.")


async def request_validation_error_handler(
    _: Request, __: RequestValidationError
) -> JSONResponse:
    return request_validation_response()


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
