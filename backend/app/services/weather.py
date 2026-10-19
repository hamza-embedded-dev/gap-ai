from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# MVP default coordinates: Üsküdar–Bağlarbaşı
DEFAULT_LATITUDE: float = 41.02052
DEFAULT_LONGITUDE: float = 29.03461


@dataclass(frozen=True)
class HourlyForecast:
    time: datetime
    precipitation_probability: float | None
    weather_code: int | None
    is_rainy: bool


def _is_rain_code(code: int | None) -> bool:
    """Return True if WMO weather code indicates rain, showers or drizzle."""
    if code is None:
        return False
    # WMO codes: 51-57 (drizzle), 61-67 (rain), 80-82 (rain showers), 95-99 (thunderstorm)
    return 51 <= code <= 67 or 80 <= code <= 82 or 95 <= code <= 99


class WeatherService:
    """Weather forecast service using Open-Meteo REST API.

    Coordinates must be supplied explicitly; the service does not infer or guess coordinates
    from timezones or IP addresses. When coordinates are omitted, forecast lookup safely returns None.
    """

    def __init__(self, client: httpx.Client | None = None, timeout: float = 5.0) -> None:
        self._external_client = client is not None
        self._client = client or httpx.Client(timeout=timeout)

    def get_forecast(
        self,
        *,
        latitude: float | None,
        longitude: float | None,
        target_time: datetime,
        timezone_str: str = "UTC",
    ) -> HourlyForecast | None:
        """Fetch hourly weather forecast for explicit coordinates around target_time.

        Returns None if coordinates are missing, out of range, or if the upstream API fails.
        """
        if latitude is None or longitude is None:
            logger.info("Weather lookup skipped: no explicit coordinates provided.")
            return None

        # Validate coordinate bounds and finite numbers
        try:
            lat = float(latitude)
            lon = float(longitude)
        except (TypeError, ValueError):
            logger.warning("Weather lookup skipped: coordinates are not valid numbers.")
            return None

        import math
        if not (math.isfinite(lat) and math.isfinite(lon)):
            logger.warning("Weather lookup skipped: coordinates are not finite.")
            return None

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            logger.warning("Weather lookup skipped: coordinates out of bounds (lat: %s, lon: %s).", lat, lon)
            return None

        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("UTC")

        target_local = target_time.astimezone(tz)
        day_str = target_local.strftime("%Y-%m-%d")

        params: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "precipitation_probability,weather_code",
            "start_date": day_str,
            "end_date": day_str,
            "timezone": timezone_str,
        }

        try:
            response = self._client.get(OPEN_METEO_FORECAST_URL, params=params)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Open-Meteo request failed: %s", exc)
            return None

        if not isinstance(data, dict):
            return None

        hourly = data.get("hourly")
        if not isinstance(hourly, dict):
            return None

        times_raw = hourly.get("time")
        if not isinstance(times_raw, list) or not times_raw:
            return None

        prob_raw = hourly.get("precipitation_probability")
        probabilities: list[Any] = prob_raw if isinstance(prob_raw, list) else []

        code_raw = hourly.get("weather_code")
        weather_codes: list[Any] = code_raw if isinstance(code_raw, list) else []

        times: list[str] = [t for t in times_raw if isinstance(t, str)]
        if not times:
            return None

        # Find closest hour matching target_time
        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("UTC")

        target_local = target_time.astimezone(tz)
        target_hour_str = target_local.strftime("%Y-%m-%dT%H:00")

        best_idx = 0
        if target_hour_str in times:
            best_idx = times.index(target_hour_str)
        else:
            # Fallback to absolute difference if exact hour string not found
            min_diff = None
            for idx, time_str in enumerate(times):
                try:
                    dt = datetime.fromisoformat(time_str).replace(tzinfo=tz)
                    diff = abs((dt - target_local).total_seconds())
                    if min_diff is None or diff < min_diff:
                        min_diff = diff
                        best_idx = idx
                except ValueError:
                    continue

        chosen_time_str = times[best_idx]
        chosen_time = datetime.fromisoformat(chosen_time_str).replace(tzinfo=tz)
        prob = probabilities[best_idx] if best_idx < len(probabilities) else None
        code = weather_codes[best_idx] if best_idx < len(weather_codes) else None

        # A rainy forecast if probability >= 50% or WMO weather code indicates rain
        is_rain = _is_rain_code(code) or (prob is not None and prob >= 50)

        return HourlyForecast(
            time=chosen_time,
            precipitation_probability=prob,
            weather_code=code,
            is_rainy=is_rain,
        )

    def close(self) -> None:
        if not self._external_client:
            self._client.close()

    def __enter__(self) -> "WeatherService":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
