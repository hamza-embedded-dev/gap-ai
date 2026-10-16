from __future__ import annotations

import json
from typing import Any
import httpx
import pytest
from pydantic import SecretStr

from app.ai.llm import (
    LLMConfigurationError,
    LLMError,
    LLMParseError,
    LLMResponseError,
    LLMUnavailableError,
    NebiusLLMClient,
)
from app.config import Settings
from app.schemas.parsed_plan import ParsedPlan

TEST_API_KEY = "test-nebius-secret-key-123456789"
TEST_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
TEST_MODEL = "nvidia/Llama-3.1-Nemotron-70B-Instruct-HF"


def _make_openai_chat_response(content: str, model: str = TEST_MODEL) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test-id",
        "object": "chat.completion",
        "created": 1728900000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 20,
            "total_tokens": 35,
        },
    }


# -----------------------------------------------------------------------------
# Configuration and Initialization Tests
# -----------------------------------------------------------------------------


def test_client_initialization_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        NEBIUS_API_KEY=TEST_API_KEY,
        NEBIUS_BASE_URL=TEST_BASE_URL,
        MODEL_SUPER=TEST_MODEL,
        NEBIUS_TIMEOUT_SECONDS=45.0,
        _env_file=None,
    )
    monkeypatch.setattr("app.ai.llm.get_settings", lambda: settings)

    client = NebiusLLMClient()
    assert client.base_url == "https://api.tokenfactory.nebius.com/v1/"
    assert client.default_model == TEST_MODEL
    assert client.default_timeout == 45.0
    client.close()


def test_client_explicit_overrides_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        NEBIUS_API_KEY=TEST_API_KEY,
        _env_file=None,
    )
    monkeypatch.setattr("app.ai.llm.get_settings", lambda: settings)

    client = NebiusLLMClient(
        api_key="override-key",
        base_url="https://custom.api.nebius.ai/v1",
        default_model="nvidia/nemotron-4-340b-instruct",
        default_timeout=15.0,
    )
    assert client.base_url == "https://custom.api.nebius.ai/v1/"
    assert client.default_model == "nvidia/nemotron-4-340b-instruct"
    assert client.default_timeout == 15.0
    client.close()


def test_client_requires_api_key_when_called(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        NEBIUS_API_KEY=None,
        _env_file=None,
    )
    monkeypatch.setattr("app.ai.llm.get_settings", lambda: settings)

    client = NebiusLLMClient(api_key=None)
    with pytest.raises(LLMConfigurationError, match="NEBIUS_API_KEY is missing"):
        client.complete([{"role": "user", "content": "Hello"}])
    client.close()


# -----------------------------------------------------------------------------
# Successful Completion Tests
# -----------------------------------------------------------------------------


def test_successful_complete_string() -> None:
    captured_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        payload = _make_openai_chat_response("Merhaba, plan oluşturmaya hazırım.")
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(
            api_key=TEST_API_KEY,
            base_url=TEST_BASE_URL,
            http_client=http_client,
        )
        result = client.complete([{"role": "user", "content": "Plan yap"}])

    assert result == "Merhaba, plan oluşturmaya hazırım."
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.url == httpx.URL("https://api.tokenfactory.nebius.com/v1/chat/completions")
    assert req.headers["authorization"] == f"Bearer {TEST_API_KEY}"
    assert req.headers["content-type"] == "application/json"

    sent_body = json.loads(req.content.decode("utf-8"))
    assert sent_body["model"] == TEST_MODEL
    assert sent_body["messages"] == [{"role": "user", "content": "Plan yap"}]
    assert "response_format" not in sent_body  # json_mode=False


def test_successful_complete_json_mode() -> None:
    plan_json = {
        "intent": "create_plan",
        "title": "Koşu",
        "category": "sport",
        "date": "2026-10-15",
        "time": "18:00",
        "duration_minutes": 45,
        "recurrence": None,
        "language": "tr",
        "needs_weather_check": True,
        "clarification_question": None,
        "confidence": 0.98,
    }

    captured_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        payload = _make_openai_chat_response(json.dumps(plan_json))
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(
            api_key=TEST_API_KEY,
            base_url=TEST_BASE_URL,
            http_client=http_client,
        )
        result = client.complete_json([
            {"role": "system", "content": "Extract plan in JSON"},
            {"role": "user", "content": "Yarın 18'de koşu"},
        ])

    assert result == plan_json
    assert len(captured_requests) == 1
    sent_body = json.loads(captured_requests[0].content.decode("utf-8"))
    assert sent_body["response_format"] == {"type": "json_object"}
    assert sent_body["temperature"] == 0.0


# -----------------------------------------------------------------------------
# Error Handling: HTTP Errors, Timeouts, and Network Failures
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [400, 401, 403, 422, 429])
def test_provider_client_4xx_raises_llm_response_error(status_code: int) -> None:
    def mock_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"message": f"Client Error {status_code}", "type": "invalid_request_error"}},
        )

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(api_key=TEST_API_KEY, http_client=http_client)
        with pytest.raises(LLMResponseError) as exc_info:
            client.complete([{"role": "user", "content": "Hi"}])
        assert exc_info.value.status_code == status_code
        assert str(status_code) in str(exc_info.value)


@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
def test_provider_server_5xx_raises_llm_unavailable_error(status_code: int) -> None:
    def mock_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=f"Internal Server Error {status_code}")

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(api_key=TEST_API_KEY, http_client=http_client)
        with pytest.raises(LLMUnavailableError, match=f"HTTP {status_code}"):
            client.complete([{"role": "user", "content": "Hi"}])


def test_timeout_raises_llm_unavailable_error() -> None:
    def mock_handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Request timed out waiting for Nebius")

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(api_key=TEST_API_KEY, http_client=http_client)
        with pytest.raises(LLMUnavailableError, match="timed out"):
            client.complete([{"role": "user", "content": "Hi"}])


def test_connect_error_raises_llm_unavailable_error() -> None:
    def mock_handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by DNS/host")

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(api_key=TEST_API_KEY, http_client=http_client)
        with pytest.raises(LLMUnavailableError, match="Failed to connect"):
            client.complete([{"role": "user", "content": "Hi"}])


# -----------------------------------------------------------------------------
# Error Handling: Parsing and Malformed Response Shapes
# -----------------------------------------------------------------------------


def test_invalid_json_in_json_mode_raises_llm_parse_error() -> None:
    def mock_handler(_: httpx.Request) -> httpx.Response:
        payload = _make_openai_chat_response("This is not valid JSON at all: {foo: bar}")
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(api_key=TEST_API_KEY, http_client=http_client)
        with pytest.raises(LLMParseError, match="not valid JSON"):
            client.complete_json([{"role": "user", "content": "Give me JSON"}])


def test_non_json_http_response_body_raises_llm_parse_error() -> None:
    def mock_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>502 Bad Gateway from cloudflare</html>")

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(api_key=TEST_API_KEY, http_client=http_client)
        with pytest.raises(LLMParseError, match="not valid JSON"):
            client.complete([{"role": "user", "content": "Hi"}])


@pytest.mark.parametrize(
    "malformed_payload,expected_match",
    [
        ({"choices": []}, "missing 'choices' list"),
        ({"choices": None}, "missing 'choices' list"),
        ({"choices": ["not-a-dict"]}, "'choices\\[0\\]' must be an object"),
        ({"choices": [{}]}, "'choices\\[0\\].message' must be an object"),
        ({"choices": [{"message": {}}]}, "content is null or not a string"),
        ({"choices": [{"message": {"content": None}}]}, "content is null or not a string"),
    ],
)
def test_malformed_response_shapes_raise_llm_parse_error(
    malformed_payload: dict[str, Any], expected_match: str
) -> None:
    def mock_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=malformed_payload)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(api_key=TEST_API_KEY, http_client=http_client)
        with pytest.raises(LLMParseError, match=expected_match):
            client.complete([{"role": "user", "content": "Hi"}])


# -----------------------------------------------------------------------------
# Security and Sanitization Tests
# -----------------------------------------------------------------------------


def test_api_key_not_leaked_in_error_message() -> None:
    sensitive_key = "super-secret-production-token-xyz987"

    def mock_handler(_: httpx.Request) -> httpx.Response:
        # Simulate upstream echoing the key in its error payload
        return httpx.Response(
            400,
            text=f"Invalid authorization parameter for key: {sensitive_key}",
        )

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(api_key=sensitive_key, http_client=http_client)
        with pytest.raises(LLMResponseError) as exc_info:
            client.complete([{"role": "user", "content": "Hi"}])

        assert sensitive_key not in str(exc_info.value)
        assert "[REDACTED_API_KEY]" in str(exc_info.value)

@pytest.mark.parametrize("status_code", [400, 500])
def test_api_key_not_partially_leaked_at_truncation_boundary(
    status_code: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure a key crossing the 300-character limit is fully redacted."""
    sensitive_key = "test-secret-boundary-key-123456789"
    error_text = "X" * 290 + sensitive_key

    def mock_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=error_text)

    transport = httpx.MockTransport(mock_handler)

    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(
            api_key=sensitive_key,
            http_client=http_client,
        )

        expected_error = (
            LLMUnavailableError if status_code == 500 else LLMResponseError
        )

        with caplog.at_level("ERROR"):
            with pytest.raises(expected_error):
                client.complete([{"role": "user", "content": "Hi"}])

    assert sensitive_key not in caplog.text
    assert sensitive_key[:10] not in caplog.text
    assert "[REDACTED_" in caplog.text


# -----------------------------------------------------------------------------
# Separation of Concerns: Syntactic JSON vs Contract Schema Validation
# -----------------------------------------------------------------------------


def test_separation_of_concerns_parsed_plan_contract_validation() -> None:
    """Demonstrates that NebiusLLMClient handles JSON parsing while ParsedPlan

    (ai/schema.json) handles domain validation in higher layers (B2-2).
    """
    valid_plan_data = {
        "intent": "create_plan",
        "title": "Study Math",
        "category": "study",
        "date": "2026-10-16",
        "time": "14:00",
        "duration_minutes": 90,
        "recurrence": None,
        "language": "en",
        "needs_weather_check": False,
        "clarification_question": None,
        "confidence": 0.99,
    }

    def mock_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_make_openai_chat_response(json.dumps(valid_plan_data)))

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(api_key=TEST_API_KEY, http_client=http_client)
        raw_json = client.complete_json([{"role": "user", "content": "Study math"}])

    # 1. LLM client returned raw validated JSON
    assert raw_json == valid_plan_data

    # 2. Higher-level domain validation (B2-2 role) validates against ai/schema.json
    parsed_plan = ParsedPlan.model_validate(raw_json)
    assert parsed_plan.root["title"] == "Study Math"


# -----------------------------------------------------------------------------
# JSON Mode Explicit Directive Injection & Normalization Tests
# -----------------------------------------------------------------------------


def test_json_mode_injects_directive_when_word_json_missing() -> None:
    captured_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json=_make_openai_chat_response('{"status": "ok"}'))

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(api_key=TEST_API_KEY, http_client=http_client)
        # Message has NO mention of "json"
        result = client.complete_json([{"role": "user", "content": "Tell me tomorrow's plan"}])

    assert result == {"status": "ok"}
    assert len(captured_requests) == 1
    sent_body = json.loads(captured_requests[0].content.decode("utf-8"))
    assert sent_body["response_format"] == {"type": "json_object"}
    sent_messages = sent_body["messages"]
    # Verify directive was injected at index 0 to fulfill the OpenAI/Nebius specification
    assert len(sent_messages) == 2
    assert sent_messages[0]["role"] == "system"
    assert "JSON" in sent_messages[0]["content"]
    assert sent_messages[1]["content"] == "Tell me tomorrow's plan"


def test_json_mode_does_not_duplicate_when_word_json_already_present() -> None:
    captured_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json=_make_openai_chat_response('{"status": "ok"}'))

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as http_client:
        client = NebiusLLMClient(api_key=TEST_API_KEY, http_client=http_client)
        # Message explicitly mentions "JSON"
        result = client.complete_json([
            {"role": "system", "content": "Extract data in JSON format."},
            {"role": "user", "content": "Plan details"},
        ])

    assert result == {"status": "ok"}
    assert len(captured_requests) == 1
    sent_messages = json.loads(captured_requests[0].content.decode("utf-8"))["messages"]
    # Should not inject an additional directive
    assert len(sent_messages) == 2
    assert sent_messages[0]["content"] == "Extract data in JSON format."


def test_config_aliases_support_both_nebius_model_and_model_super() -> None:
    # 1. NEBIUS_MODEL takes effect
    s1 = Settings(NEBIUS_MODEL="nvidia/custom-nemotron-1", _env_file=None)
    assert s1.nebius_model == "nvidia/custom-nemotron-1"

    # 2. MODEL_SUPER fallback takes effect
    s2 = Settings(MODEL_SUPER="nvidia/custom-nemotron-2", _env_file=None)
    assert s2.nebius_model == "nvidia/custom-nemotron-2"

    # 3. Both provided: NEBIUS_MODEL takes precedence
    s3 = Settings(NEBIUS_MODEL="nvidia/primary", MODEL_SUPER="nvidia/secondary", _env_file=None)
    assert s3.nebius_model == "nvidia/primary"


@pytest.mark.parametrize(
    "raw_base_url,expected_endpoint",
    [
        ("https://api.tokenfactory.nebius.com/v1", "https://api.tokenfactory.nebius.com/v1/chat/completions"),
        ("https://api.tokenfactory.nebius.com/v1/", "https://api.tokenfactory.nebius.com/v1/chat/completions"),
        ("https://api.tokenfactory.nebius.com", "https://api.tokenfactory.nebius.com/v1/chat/completions"),
        ("https://custom.host:8080/prefix/v1", "https://custom.host:8080/prefix/v1/chat/completions"),
    ],
)
def test_base_url_normalization(raw_base_url: str, expected_endpoint: str) -> None:
    client = NebiusLLMClient(api_key=TEST_API_KEY, base_url=raw_base_url)
    assert client._chat_completions_url() == expected_endpoint
    client.close()
