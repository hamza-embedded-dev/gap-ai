import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException as StarletteHTTPException
from pydantic import ValidationError
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
import trio

from app.api.errors import (
    APIError,
    CONTRACT_ERRORS_BY_STATUS,
    api_error_response,
    http_error_response,
    http_exception_handler,
    install_error_handlers,
    request_validation_error_handler,
    request_validation_response,
)
from app.config import Settings
from app.schemas.parsed_plan import ParsedPlan, SCHEMA_PATH


def _valid_plan(**overrides: object) -> dict[str, object]:
    plan: dict[str, object] = {
        "intent": "create_plan",
        "title": "Run",
        "category": "sport",
        "date": "2026-10-13",
        "time": "18:30",
        "duration_minutes": 60,
        "recurrence": None,
        "language": "en",
        "needs_weather_check": False,
        "clarification_question": None,
        "confidence": 0.95,
    }
    plan.update(overrides)
    return plan


def test_schema_path_points_to_shared_ai_schema() -> None:
    assert SCHEMA_PATH == Path(__file__).resolve().parents[2] / "ai" / "schema.json"
    assert ParsedPlan.model_json_schema() == json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "plan",
    [
        _valid_plan(),
        _valid_plan(
            intent="clarify",
            title=None,
            category=None,
            date=None,
            time=None,
            clarification_question="Which day?",
        ),
        _valid_plan(
            intent="unsupported",
            title=None,
            category=None,
            date=None,
            time=None,
            duration_minutes=None,
            recurrence=None,
            needs_weather_check=False,
            clarification_question=None,
        ),
    ],
)
def test_parsed_plan_accepts_each_contract_intent(plan: dict[str, object]) -> None:
    assert ParsedPlan.model_validate(plan).model_dump() == plan


@pytest.mark.parametrize(
    "required_field",
    json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["required"],
)
def test_parsed_plan_rejects_each_missing_required_field(required_field: str) -> None:
    plan = _valid_plan()
    del plan[required_field]
    with pytest.raises(ValidationError):
        ParsedPlan.model_validate(plan)


@pytest.mark.parametrize(
    "changes",
    [
        {"intent": "create_plan", "title": None},
        {"intent": "create_plan", "category": None},
        {"intent": "create_plan", "date": None},
        {"intent": "create_plan", "time": None},
        {"extra": "not allowed"},
        {"time": "25:61"},
        {"date": "2026-1-3"},
        {"recurrence": False},
        {"duration_minutes": 4},
        {"confidence": 1.1},
        {"intent": "clarify", "clarification_question": None},
        {"intent": "unsupported", "title": "Run"},
        {"intent": "unsupported", "category": "sport"},
        {"intent": "unsupported", "date": "2026-10-13"},
        {"intent": "unsupported", "time": "18:30"},
        {"intent": "unsupported", "duration_minutes": 60},
        {"intent": "unsupported", "recurrence": "FREQ=WEEKLY;BYDAY=TU"},
        {"intent": "unsupported", "needs_weather_check": True},
    ],
)
def test_parsed_plan_rejects_schema_violations(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ParsedPlan.model_validate(_valid_plan(**changes))


def test_production_settings_fail_without_strong_pepper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TOKEN_HASH_PEPPER", raising=False)
    with pytest.raises(ValidationError, match="TOKEN_HASH_PEPPER"):
        Settings(_env_file=None)


def test_development_settings_need_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("TOKEN_HASH_PEPPER", raising=False)
    assert Settings(_env_file=None).environment == "development"


def test_http_errors_use_contract_top_level_shape() -> None:
    response = http_error_response(404, "Plan not found")
    assert response.status_code == 404
    assert json.loads(response.body) == {"error": "not_found", "message": "Plan not found"}


def test_http_exception_detail_cannot_override_status_error_code() -> None:
    response = http_error_response(
        404, {"error": "unauthorized", "message": "Plan is missing"}
    )
    assert json.loads(response.body) == {"error": "not_found", "message": "Plan is missing"}


def test_undefined_server_error_does_not_invent_a_contract_code() -> None:
    response = http_error_response(500, "sensitive internal details")
    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "Internal Server Error"}


@pytest.mark.parametrize("status_code,error", sorted(CONTRACT_ERRORS_BY_STATUS.items()))
def test_api_error_requires_contract_status_code_pair(status_code: int, error: str) -> None:
    APIError(status_code, error, "Example")
    wrong_error = "forbidden" if error != "forbidden" else "unauthorized"
    with pytest.raises(ValueError):
        APIError(status_code, wrong_error, "Example")


def test_api_error_response_shape() -> None:
    response = api_error_response(APIError(429, "rate_limited", "Slow down"))
    assert response.status_code == 429
    assert json.loads(response.body) == {"error": "rate_limited", "message": "Slow down"}


def test_error_handlers_are_installed_for_fastapi_errors() -> None:
    app = FastAPI()
    install_error_handlers(app)
    assert app.exception_handlers[StarletteHTTPException] is http_exception_handler
    assert app.exception_handlers[RequestValidationError] is request_validation_error_handler


def test_request_validation_uses_contract_error_shape() -> None:
    response = request_validation_response()
    assert response.status_code == 422
    assert json.loads(response.body) == {
        "error": "validation_error",
        "message": "Request does not match the API contract.",
    }


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows socket-pair initialization is blocked in this sandbox; covered by Linux CI",
)
def test_asgi_404_uses_contract_error_shape() -> None:
    app = _asgi_test_app()
    response = _run_asgi_request(app, "GET", "/missing")
    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "message": "Not Found"}


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows socket-pair initialization is blocked in this sandbox; covered by Linux CI",
)
def test_asgi_422_uses_contract_error_shape() -> None:
    app = _asgi_test_app()

    @app.post("/validated")
    def validated(payload: BaseModelForTest) -> dict[str, int]:
        return {"count": payload.count}

    response = _run_asgi_request(app, "POST", "/validated", {"count": "invalid"})
    assert response.status_code == 422
    assert response.json() == {
        "error": "validation_error",
        "message": "Request does not match the API contract.",
    }


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows socket-pair initialization is blocked in this sandbox; covered by Linux CI",
)
def test_asgi_api_error_uses_contract_error_shape() -> None:
    app = _asgi_test_app()

    @app.get("/limited")
    def limited() -> None:
        raise APIError(429, "rate_limited", "Slow down")

    response = _run_asgi_request(app, "GET", "/limited")
    assert response.status_code == 429
    assert response.json() == {"error": "rate_limited", "message": "Slow down"}


class BaseModelForTest(BaseModel):
    count: int


def _asgi_test_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    return app


def _run_asgi_request(
    app: FastAPI, method: str, path: str, json_body: dict[str, object] | None = None
) -> httpx.Response:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, path, json=json_body)

    return trio.run(request)
