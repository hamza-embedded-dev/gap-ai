from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict

from app.api.errors import APIError
from app.api.plans import current_user
from app.db.plans import AuthenticatedUser
from app.services.weather import (
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_TIMEZONE,
    WeatherService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weather", tags=["weather"])


class WeatherLocation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    latitude: float
    longitude: float
    timezone: str


class CurrentWeather(BaseModel):
    model_config = ConfigDict(extra="ignore")

    temperature: float | None = None
    apparent_temperature: float | None = None
    humidity: float | int | None = None
    precipitation: float | None = None
    precipitation_probability: float | int | None = None
    wind_speed: float | None = None
    weather_code: int | None = None
    weather_description: str
    is_rainy: bool
    time: str | None = None


class HourlyForecastItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time: str
    temperature: float | None = None
    precipitation_probability: float | int | None = None
    weather_code: int | None = None
    weather_description: str
    is_rainy: bool


class WeatherCurrentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    location: WeatherLocation
    current: CurrentWeather
    hourly_forecast: list[HourlyForecastItem]
    attribution: str
    source_url: str
    from_cache: bool = False
    cached_at: str | None = None
    is_stale: bool = False
    cache_age_seconds: int | None = None


def get_weather_service() -> WeatherService:
    return WeatherService()


@router.get("/current", response_model=WeatherCurrentResponse, status_code=status.HTTP_200_OK)
def get_current_weather_endpoint(
    latitude: float = Query(default=DEFAULT_LATITUDE, ge=-90.0, le=90.0),
    longitude: float = Query(default=DEFAULT_LONGITUDE, ge=-180.0, le=180.0),
    timezone: str = Query(default=DEFAULT_TIMEZONE),
    user: AuthenticatedUser = Depends(current_user),
    service: WeatherService = Depends(get_weather_service),
) -> WeatherCurrentResponse:
    """Returns current weather conditions and hourly forecast for Bağlarbaşı, Üsküdar or custom coordinates."""
    tz = timezone or user.timezone or DEFAULT_TIMEZONE
    try:
        data = service.get_current_weather(
            latitude=latitude,
            longitude=longitude,
            timezone_str=tz,
        )
    except Exception as exc:
        logger.warning("Weather service exception: %s", exc)
        data = None

    if not data:
        raise APIError(503, "llm_unavailable", "Weather service is currently unavailable. Please try again later.")

    return WeatherCurrentResponse.model_validate(data)
