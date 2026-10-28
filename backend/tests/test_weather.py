from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
from types import SimpleNamespace
from typing import Any
import wave

from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest

from app.ai.stt import GroqWhisperClient, get_stt_client
from app.ai.tts import get_tts_client
import app.api.plans as plans_api
from app.db.plans import AuthenticatedUser, get_plan_store
from app.main import app
from app.services.weather import (
    DEFAULT_LATITUDE,
    DEFAULT_LOCATION_NAME,
    DEFAULT_LONGITUDE,
    DEFAULT_TIMEZONE,
    WeatherService,
    _CachedWeatherEntry,
    generate_weather_speech,
    get_wmo_description,
)

PEPPER = "p" * 32
TOKEN = "weather-test-token"
TOKEN_HASH = hashlib.sha256((TOKEN + PEPPER).encode("utf-8")).hexdigest()
USER_ID = "user-weather-123"
USER_TZ = "Europe/Istanbul"

_orig_httpx_get = httpx.Client.get


def _mock_open_meteo_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    def safe_get(self: httpx.Client, url: Any, *args: Any, **kwargs: Any) -> httpx.Response:
        url_str = str(url)
        if "open-meteo.com" in url_str:
            return handler(url_str, *args, **kwargs)
        return _orig_httpx_get(self, url, *args, **kwargs)

    monkeypatch.setattr("httpx.Client.get", safe_get)


def _make_wav_bytes(duration_seconds: float = 0.5) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        n_frames = int(16000 * duration_seconds)
        w.writeframes(b"\x00" * (n_frames * 2))
    return buf.getvalue()


class FakePlanStore:
    def __init__(self) -> None:
        user = AuthenticatedUser(
            id=USER_ID,
            timezone=USER_TZ,
            is_demo=False,
            demo_expires_at=None,
        )
        self.tokens = {TOKEN_HASH: (user, None)}
        self.created_plans: list[dict[str, Any]] = []
        self.proposals: dict[str, list[dict[str, Any]]] = {}

    def get_user_for_token_hash(self, token_hash: str):
        return self.tokens.get(token_hash)

    def create_plan_proposal(self, *, user_id: str, proposal: dict[str, Any], conversation_id: str | None = None):
        return {"id": "prop-1", "user_id": user_id, "title": proposal["title"]}

    def get_latest_pending_proposal(self, *, user_id: str):
        return None


class FakeSTTClient:
    def __init__(self, transcript: str = "Bugün hava nasıl?") -> None:
        self.transcript = transcript

    def validate_wav_audio(self, audio_bytes: bytes, max_seconds: float = 10.0) -> bytes:
        return GroqWhisperClient.validate_wav_audio(audio_bytes, max_seconds=max_seconds)

    def transcribe(self, audio: bytes | Any, **kwargs: Any) -> str:
        return self.transcript


class FakeTTSClient:
    def __init__(self) -> None:
        self.audio = _make_wav_bytes()

    def synthesize(self, text: str, **kwargs: Any) -> bytes:
        return self.audio


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        token_hash_pepper=SecretStr(PEPPER),
        environment="development",
        allowed_origins=[],
        tts_enabled=True,
    )
    monkeypatch.setattr(plans_api, "get_settings", lambda: settings)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    WeatherService.clear_cache()
    yield
    WeatherService.clear_cache()


@pytest.fixture
def fake_store() -> FakePlanStore:
    store = FakePlanStore()
    app.dependency_overrides[get_plan_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_plan_store, None)


@pytest.fixture
def client(fake_store: FakePlanStore) -> TestClient:
    return TestClient(app)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _mock_open_meteo_response(
    weather_code: int = 2,
    temperature: float = 18.4,
    precip: float = 0.0,
    precip_prob: int = 15,
) -> dict[str, Any]:
    times = [f"2026-10-28T{h:02d}:00" for h in range(24)]
    return {
        "latitude": DEFAULT_LATITUDE,
        "longitude": DEFAULT_LONGITUDE,
        "timezone": DEFAULT_TIMEZONE,
        "current": {
            "time": "2026-10-28T13:00",
            "temperature_2m": temperature,
            "apparent_temperature": temperature - 1.0,
            "relative_humidity_2m": 62,
            "precipitation": precip,
            "weather_code": weather_code,
            "wind_speed_10m": 14.5,
        },
        "hourly": {
            "time": times,
            "temperature_2m": [temperature] * 24,
            "precipitation_probability": [precip_prob] * 24,
            "weather_code": [weather_code] * 24,
        },
    }


# =============================================================================
# 1. Weather API Endpoint Tests
# =============================================================================


def test_weather_endpoint_requires_auth(client: TestClient) -> None:
    """GET /weather/current requires authentication like all GAP-AI routers."""
    resp = client.get("/weather/current")
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized", "message": "Token is missing or invalid."}


def test_weather_endpoint_returns_current_weather_and_hourly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /weather/current returns temperature, apparent temp, humidity, wind, and hourly forecast."""
    call_count = 0

    def mock_get(url: str, params: dict[str, Any] | None = None, **kwargs: Any) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            status_code=200,
            json=_mock_open_meteo_response(weather_code=2, temperature=18.4, precip=0.0, precip_prob=15),
            request=httpx.Request("GET", url),
        )

    _mock_open_meteo_client(monkeypatch, mock_get)

    resp = client.get("/weather/current", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()

    assert data["location"]["name"] == DEFAULT_LOCATION_NAME
    assert abs(data["location"]["latitude"] - DEFAULT_LATITUDE) < 0.001
    assert abs(data["location"]["longitude"] - DEFAULT_LONGITUDE) < 0.001
    assert data["location"]["timezone"] == DEFAULT_TIMEZONE

    # Current metrics
    curr = data["current"]
    assert curr["temperature"] == 18.4
    assert curr["apparent_temperature"] == 17.4
    assert curr["humidity"] == 62
    assert curr["wind_speed"] == 14.5
    assert curr["weather_code"] == 2
    assert curr["weather_description"] == "Parçalı Bulutlu"
    assert curr["is_rainy"] is False

    # Attribution & Cache flags
    assert data["attribution"] == "Weather data by Open-Meteo.com"
    assert data["source_url"] == "https://open-meteo.com/"
    assert data["from_cache"] is False

    # Hourly forecast
    hourly = data["hourly_forecast"]
    assert len(hourly) > 0
    assert hourly[0]["weather_description"] == "Parçalı Bulutlu"
    assert hourly[0]["precipitation_probability"] == 15
    assert call_count == 1


def test_weather_endpoint_10_minute_cache(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated calls within 10 minutes return cached data without contacting Open-Meteo again."""
    upstream_calls = 0

    def mock_get(url: str, params: dict[str, Any] | None = None, **kwargs: Any) -> httpx.Response:
        nonlocal upstream_calls
        upstream_calls += 1
        return httpx.Response(
            status_code=200,
            json=_mock_open_meteo_response(weather_code=1, temperature=20.0),
            request=httpx.Request("GET", url),
        )

    _mock_open_meteo_client(monkeypatch, mock_get)

    # First call: hits upstream
    resp1 = client.get("/weather/current", headers=_auth_headers())
    assert resp1.status_code == 200
    assert resp1.json()["from_cache"] is False
    assert upstream_calls == 1

    # Second call immediately: served from 10-minute cache
    resp2 = client.get("/weather/current", headers=_auth_headers())
    assert resp2.status_code == 200
    assert resp2.json()["from_cache"] is True
    assert upstream_calls == 1  # Upstream must NOT be called again


def test_weather_endpoint_rainy_forecast_detection(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Detects rain when weather code is 61 or precipitation probability >= 50%."""

    def mock_get(url: str, params: dict[str, Any] | None = None, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json=_mock_open_meteo_response(weather_code=61, temperature=13.0, precip=2.5, precip_prob=80),
            request=httpx.Request("GET", url),
        )

    _mock_open_meteo_client(monkeypatch, mock_get)

    resp = client.get("/weather/current", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"]["is_rainy"] is True
    assert data["current"]["weather_description"] == "Hafif Yağmurlu"
    assert data["current"]["precipitation_probability"] == 80


def test_weather_endpoint_upstream_timeout_falls_back_to_stale_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When Open-Meteo times out, returns stale cached data if present."""
    # First: seed cache with a successful call
    WeatherService._cache[(round(DEFAULT_LATITUDE, 4), round(DEFAULT_LONGITUDE, 4), DEFAULT_TIMEZONE)] = (
        _CachedWeatherEntry(
            data={
                "location": {"name": DEFAULT_LOCATION_NAME, "latitude": DEFAULT_LATITUDE, "longitude": DEFAULT_LONGITUDE, "timezone": DEFAULT_TIMEZONE},
                "current": {"temperature": 19.0, "apparent_temperature": 18.0, "humidity": 60, "precipitation": 0.0, "wind_speed": 10.0, "weather_code": 0, "weather_description": "Açık", "is_rainy": False},
                "hourly_forecast": [],
                "attribution": "Weather data by Open-Meteo.com",
                "source_url": "https://open-meteo.com/",
                "from_cache": False,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            },
            timestamp=0.0,  # Stale timestamp
        )
    )

    def mock_timeout(url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.TimeoutException("Open-Meteo timed out")

    _mock_open_meteo_client(monkeypatch, mock_timeout)

    resp = client.get("/weather/current", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["from_cache"] is True
    assert data["is_stale"] is True
    assert data["current"]["weather_description"] == "Açık"


def test_weather_endpoint_upstream_error_without_cache_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When Open-Meteo fails and no cache exists, returns 503 without crashing other endpoints."""

    def mock_error(url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("Failed to reach Open-Meteo")

    _mock_open_meteo_client(monkeypatch, mock_error)

    resp = client.get("/weather/current", headers=_auth_headers())
    assert resp.status_code == 503
    assert resp.json()["error"] == "llm_unavailable"


# =============================================================================
# 2. Voice Weather Command Tests (/voice)
# =============================================================================


def test_voice_weather_query_turkish_returns_speech_audio_without_plan(
    client: TestClient, fake_store: FakePlanStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Voice query 'Bugün hava nasıl?' returns spoken audio and creates no plan or proposal."""
    from urllib.parse import unquote

    stt = FakeSTTClient(transcript="Bugün hava nasıl?")
    tts = FakeTTSClient()
    client.app.dependency_overrides[get_stt_client] = lambda: stt
    client.app.dependency_overrides[get_tts_client] = lambda: tts

    # Mock weather service
    monkeypatch.setattr(
        "app.services.weather.WeatherService.get_current_weather",
        lambda *args, **kwargs: {
            "location": {"name": DEFAULT_LOCATION_NAME, "latitude": DEFAULT_LATITUDE, "longitude": DEFAULT_LONGITUDE, "timezone": DEFAULT_TIMEZONE},
            "current": {
                "temperature": 18.0,
                "apparent_temperature": 17.0,
                "humidity": 65,
                "precipitation": 0.0,
                "precipitation_probability": 10,
                "wind_speed": 12.0,
                "weather_code": 2,
                "weather_description": "Parçalı Bulutlu",
                "is_rainy": False,
            },
            "hourly_forecast": [],
            "attribution": "Weather data by Open-Meteo.com",
            "source_url": "https://open-meteo.com/",
            "from_cache": False,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    headers = dict(_auth_headers())
    headers["Accept"] = "audio/wav, application/json"

    response = client.post(
        "/voice",
        files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "audio/wav"
    assert response.headers["X-Intent"] == "weather"
    assert response.headers["X-Needs-Button"] == "false"
    reply_text = unquote(response.headers["X-Reply-Text"])
    assert "parçalı bulutlu" in reply_text.lower()
    assert "18 derece" in reply_text
    assert "yağış beklenmiyor" in reply_text.lower()

    # CRITICAL: Verify NO plan or proposal was created
    assert len(fake_store.created_plans) == 0


def test_voice_weather_query_turkish_tell_weather_command(
    client: TestClient, fake_store: FakePlanStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Voice query 'Hava durumunu söyle' is recognized as weather inquiry."""
    stt = FakeSTTClient(transcript="Hava durumunu söyle")
    tts = FakeTTSClient()
    client.app.dependency_overrides[get_stt_client] = lambda: stt
    client.app.dependency_overrides[get_tts_client] = lambda: tts

    monkeypatch.setattr(
        "app.services.weather.WeatherService.get_current_weather",
        lambda *args, **kwargs: {
            "location": {"name": DEFAULT_LOCATION_NAME, "latitude": DEFAULT_LATITUDE, "longitude": DEFAULT_LONGITUDE, "timezone": DEFAULT_TIMEZONE},
            "current": {
                "temperature": 14.0,
                "apparent_temperature": 13.0,
                "humidity": 80,
                "precipitation": 1.2,
                "precipitation_probability": 75,
                "wind_speed": 18.0,
                "weather_code": 61,
                "weather_description": "Hafif Yağmurlu",
                "is_rainy": True,
            },
            "hourly_forecast": [],
            "attribution": "Weather data by Open-Meteo.com",
            "source_url": "https://open-meteo.com/",
            "from_cache": False,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    headers = dict(_auth_headers())
    headers["Accept"] = "application/json"

    response = client.post(
        "/voice",
        files={"audio": ("sample.wav", _make_wav_bytes(), "audio/wav")},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "weather"
    assert "yağış bekleniyor" in data["reply"].lower() or "hafif yağmurlu" in data["reply"].lower()
    assert len(fake_store.created_plans) == 0


def test_generate_weather_speech_formatting() -> None:
    """Tests Turkish spoken weather synthesis formatting."""
    sunny = {
        "temperature": 21.6,
        "weather_description": "Açık",
        "precipitation_probability": 5,
        "is_rainy": False,
    }
    speech_sunny = generate_weather_speech(sunny)
    assert "açık" in speech_sunny.lower()
    assert "22 derece" in speech_sunny
    assert "yağış beklenmiyor" in speech_sunny.lower()

    rainy = {
        "temperature": 15.2,
        "weather_description": "Sağanak Yağışlı",
        "precipitation_probability": 80,
        "is_rainy": True,
    }
    speech_rainy = generate_weather_speech(rainy)
    assert "sağanak yağışlı" in speech_rainy.lower()
    assert "15 derece" in speech_rainy
    assert "yüzde 80" in speech_rainy
