from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
import time
from typing import Any
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Default coordinates: Bağlarbaşı, Üsküdar
DEFAULT_LATITUDE: float = 41.022671
DEFAULT_LONGITUDE: float = 29.035980
DEFAULT_TIMEZONE: str = "Europe/Istanbul"
DEFAULT_LOCATION_NAME: str = "Bağlarbaşı, Üsküdar"

OPEN_METEO_ATTRIBUTION: str = "Weather data by Open-Meteo.com"
OPEN_METEO_SOURCE_URL: str = "https://open-meteo.com/"
CACHE_TTL_SECONDS: int = 600  # 10 minutes cache

DEFAULT_USER_AGENT: str = "GAP-AI/1.0 (https://github.com/hamza-embedded-dev/gap-ai)"

WMO_TURKISH_DESCRIPTIONS: dict[int, str] = {
    0: "Açık",
    1: "Çoğunlukla Açık",
    2: "Parçalı Bulutlu",
    3: "Bulutlu",
    45: "Sisli",
    48: "Kırağılı Sis",
    51: "Hafif Çisenti",
    53: "Orta Şiddette Çisenti",
    55: "Yoğun Çisenti",
    56: "Hafif Dondurucu Çisenti",
    57: "Yoğun Dondurucu Çisenti",
    61: "Hafif Yağmurlu",
    63: "Yağmurlu",
    65: "Kuvvetli Yağmurlu",
    66: "Hafif Dondurucu Yağmur",
    67: "Kuvvetli Dondurucu Yağmur",
    71: "Hafif Kar Yağışlı",
    73: "Kar Yağışlı",
    75: "Kuvvetli Kar Yağışlı",
    77: "Kar Taneli",
    80: "Hafif Sağanak Yağışlı",
    81: "Sağanak Yağışlı",
    82: "Şiddetli Sağanak Yağışlı",
    85: "Hafif Kar Sağanağı",
    86: "Kuvvetli Kar Sağanağı",
    95: "Gök Gürültülü Fırtına",
    96: "Hafif Dolulu Gök Gürültülü Fırtına",
    99: "Kuvvetli Dolulu Gök Gürültülü Fırtına",
}


def get_wmo_description(code: int | None) -> str:
    """Return Turkish human-readable description for a WMO weather code."""
    if code is None:
        return "Bilinmeyen"
    return WMO_TURKISH_DESCRIPTIONS.get(code, "Bulutlu")


@dataclass(frozen=True)
class HourlyForecast:
    time: datetime
    precipitation_probability: float | None
    weather_code: int | None
    is_rainy: bool


@dataclass
class _CachedWeatherEntry:
    data: dict[str, Any]
    timestamp: float


def _is_rain_code(code: int | None) -> bool:
    """Return True if WMO weather code indicates rain, showers or drizzle."""
    if code is None:
        return False
    # WMO codes: 51-57 (drizzle), 61-67 (rain), 80-82 (rain showers), 95-99 (thunderstorm)
    return 51 <= code <= 67 or 80 <= code <= 82 or 95 <= code <= 99


def generate_weather_speech(current: dict[str, Any]) -> str:
    """Generates a concise spoken Turkish weather summary for the voice assistant."""
    temp = round(current.get("temperature", 0))
    desc = current.get("weather_description", "Bulutlu").lower()
    precip_prob = current.get("precipitation_probability")
    is_rainy = current.get("is_rainy", False)

    if is_rainy or (precip_prob is not None and precip_prob >= 50):
        prob_str = f" Yağış ihtimali yüzde {int(precip_prob)}." if precip_prob else ""
        return f"Bugün hava {desc}, sıcaklık {temp} derece ve yağış bekleniyor.{prob_str}"
    elif precip_prob is not None and precip_prob >= 25:
        return f"Bugün hava {desc}, sıcaklık {temp} derece. Yağış ihtimali yüzde {int(precip_prob)}."
    else:
        return f"Bugün hava {desc}, sıcaklık {temp} derece. Yağış beklenmiyor."


class WeatherService:
    """Weather forecast service using Open-Meteo REST API.

    Coordinates must be supplied explicitly or fall back to Üsküdar-Bağlarbaşı defaults.
    Includes in-memory 10-minute caching to minimize upstream API calls and respect rate limits.
    """

    _cache: dict[tuple[float, float, str], _CachedWeatherEntry] = {}

    def __init__(self, client: httpx.Client | None = None, timeout: float = 10.0) -> None:
        self._external_client = client is not None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )

    @classmethod
    def clear_cache(cls) -> None:
        """Clears the shared in-memory weather cache."""
        cls._cache.clear()

    def get_current_weather(
        self,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        timezone_str: str = DEFAULT_TIMEZONE,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        """Fetch current weather and hourly forecast from Open-Meteo with 10-minute caching.

        Returns None if upstream is unavailable and no cache is present.
        """
        lat = DEFAULT_LATITUDE if latitude is None else float(latitude)
        lon = DEFAULT_LONGITUDE if longitude is None else float(longitude)

        if not (math.isfinite(lat) and math.isfinite(lon)):
            logger.warning("Weather lookup skipped: coordinates are not finite.")
            return None

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            logger.warning("Weather lookup skipped: coordinates out of bounds.")
            return None

        cache_key = (round(lat, 4), round(lon, 4), timezone_str)

        # Check in-memory 10-minute cache
        if not force_refresh and cache_key in self._cache:
            entry = self._cache[cache_key]
            age = time.time() - entry.timestamp
            if age < CACHE_TTL_SECONDS:
                cached_data = dict(entry.data)
                cached_data["from_cache"] = True
                cached_data["cache_age_seconds"] = int(age)
                return cached_data

        params: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "timezone": timezone_str,
            "forecast_days": 2,
        }

        try:
            response = self._client.get(
                OPEN_METEO_FORECAST_URL,
                params=params,
                headers={"User-Agent": DEFAULT_USER_AGENT},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Open-Meteo request failed (%s): %s", type(exc).__name__, exc)
            # If upstream fails, fall back to stale cache if available
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                stale_data = dict(entry.data)
                stale_data["from_cache"] = True
                stale_data["is_stale"] = True
                stale_data["cache_age_seconds"] = int(time.time() - entry.timestamp)
                return stale_data
            return None

        if not isinstance(data, dict):
            return None

        current_raw = data.get("current")
        if not isinstance(current_raw, dict):
            return None

        curr_temp = current_raw.get("temperature_2m")
        curr_app = current_raw.get("apparent_temperature")
        curr_hum = current_raw.get("relative_humidity_2m")
        curr_precip = current_raw.get("precipitation")
        curr_code = current_raw.get("weather_code")
        curr_wind = current_raw.get("wind_speed_10m")

        # Parse hourly forecast
        hourly = data.get("hourly", {})
        times_raw = hourly.get("time") if isinstance(hourly, dict) else []
        times = [t for t in times_raw if isinstance(t, str)] if isinstance(times_raw, list) else []

        prob_raw = hourly.get("precipitation_probability") if isinstance(hourly, dict) else []
        probabilities: list[Any] = prob_raw if isinstance(prob_raw, list) else []

        temp_raw = hourly.get("temperature_2m") if isinstance(hourly, dict) else []
        temperatures: list[Any] = temp_raw if isinstance(temp_raw, list) else []

        code_raw = hourly.get("weather_code") if isinstance(hourly, dict) else []
        weather_codes: list[Any] = code_raw if isinstance(code_raw, list) else []

        try:
            tz = ZoneInfo(timezone_str)
        except Exception:
            tz = ZoneInfo("UTC")

        now_local = datetime.now(tz)
        target_hour_str = now_local.strftime("%Y-%m-%dT%H:00")

        start_idx = 0
        if target_hour_str in times:
            start_idx = times.index(target_hour_str)
        else:
            # Fallback to closest hour
            min_diff = None
            for idx, time_str in enumerate(times):
                try:
                    dt = datetime.fromisoformat(time_str).replace(tzinfo=tz)
                    diff = abs((dt - now_local).total_seconds())
                    if min_diff is None or diff < min_diff:
                        min_diff = diff
                        start_idx = idx
                except ValueError:
                    continue

        curr_prob = probabilities[start_idx] if start_idx < len(probabilities) else None

        hourly_items: list[dict[str, Any]] = []
        for i in range(start_idx, min(start_idx + 24, len(times))):
            h_time = times[i]
            h_temp = temperatures[i] if i < len(temperatures) else 0.0
            h_prob = probabilities[i] if i < len(probabilities) else None
            h_code = weather_codes[i] if i < len(weather_codes) else None
            h_desc = get_wmo_description(h_code)
            h_rain = _is_rain_code(h_code) or (h_prob is not None and h_prob >= 50)
            hourly_items.append({
                "time": h_time,
                "temperature": round(float(h_temp), 1) if h_temp is not None else None,
                "precipitation_probability": h_prob,
                "weather_code": h_code,
                "weather_description": h_desc,
                "is_rainy": h_rain,
            })

        is_rain = _is_rain_code(curr_code) or (curr_prob is not None and curr_prob >= 50)

        location_name = (
            DEFAULT_LOCATION_NAME
            if (abs(lat - DEFAULT_LATITUDE) < 0.01 and abs(lon - DEFAULT_LONGITUDE) < 0.01)
            else f"{lat:.4f}, {lon:.4f}"
        )

        result: dict[str, Any] = {
            "location": {
                "name": location_name,
                "latitude": lat,
                "longitude": lon,
                "timezone": timezone_str,
            },
            "current": {
                "temperature": round(float(curr_temp), 1) if curr_temp is not None else None,
                "apparent_temperature": round(float(curr_app), 1) if curr_app is not None else None,
                "humidity": curr_hum,
                "precipitation": curr_precip,
                "precipitation_probability": curr_prob,
                "wind_speed": round(float(curr_wind), 1) if curr_wind is not None else None,
                "weather_code": curr_code,
                "weather_description": get_wmo_description(curr_code),
                "is_rainy": is_rain,
                "time": current_raw.get("time"),
            },
            "hourly_forecast": hourly_items,
            "attribution": OPEN_METEO_ATTRIBUTION,
            "source_url": OPEN_METEO_SOURCE_URL,
            "from_cache": False,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

        # Store in cache
        self._cache[cache_key] = _CachedWeatherEntry(data=result, timestamp=time.time())
        return result

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
            response = self._client.get(
                OPEN_METEO_FORECAST_URL,
                params=params,
                headers={"User-Agent": DEFAULT_USER_AGENT},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Open-Meteo request failed (%s): %s", type(exc).__name__, exc)
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

