import React, { useCallback, useEffect, useState } from 'react';
import {
  Cloud,
  CloudDrizzle,
  CloudLightning,
  CloudRain,
  CloudSnow,
  Droplets,
  ExternalLink,
  Info,
  RefreshCw,
  Sun,
  Thermometer,
  Wind,
} from 'lucide-react';
import { fetchCurrentWeather } from '../../api/weather';
import type { WeatherCurrentResponse } from '../../api/weather';
import './WeatherCard.css';

interface WeatherCardProps {
  token?: string | null;
  onRequireAuth?: () => void;
  className?: string;
}

function getWeatherIcon(weatherCode: number | null | undefined, isRainy: boolean) {
  if (isRainy) return <CloudRain className="weather-temp-icon" aria-hidden="true" />;
  if (weatherCode === 0) return <Sun className="weather-temp-icon" aria-hidden="true" />;
  if (weatherCode === 1 || weatherCode === 2) return <Cloud className="weather-temp-icon" aria-hidden="true" />;
  if (weatherCode === 3) return <Cloud className="weather-temp-icon" aria-hidden="true" />;
  if (weatherCode && weatherCode >= 51 && weatherCode <= 57) {
    return <CloudDrizzle className="weather-temp-icon" aria-hidden="true" />;
  }
  if (weatherCode && weatherCode >= 61 && weatherCode <= 67) {
    return <CloudRain className="weather-temp-icon" aria-hidden="true" />;
  }
  if (weatherCode && weatherCode >= 71 && weatherCode <= 77) {
    return <CloudSnow className="weather-temp-icon" aria-hidden="true" />;
  }
  if (weatherCode && weatherCode >= 95) {
    return <CloudLightning className="weather-temp-icon" aria-hidden="true" />;
  }
  return <Cloud className="weather-temp-icon" aria-hidden="true" />;
}

export const WeatherCard: React.FC<WeatherCardProps> = ({
  token,
  onRequireAuth,
  className = '',
}) => {
  const [weather, setWeather] = useState<WeatherCurrentResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loadWeather = useCallback(async (refresh = false) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setErrorMessage(null);

    try {
      const data = await fetchCurrentWeather(undefined, token);
      setWeather(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to load weather forecast.';
      setErrorMessage(msg);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [token]);

  useEffect(() => {
    let isMounted = true;
    void (async () => {
      setIsLoading(true);
      setErrorMessage(null);
      try {
        const data = await fetchCurrentWeather(undefined, token);
        if (isMounted) {
          setWeather(data);
        }
      } catch (err) {
        if (isMounted) {
          const msg = err instanceof Error ? err.message : 'Unable to load weather forecast.';
          setErrorMessage(msg);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    })();

    return () => {
      isMounted = false;
    };
  }, [token]);

  if (isLoading) {
    return (
      <section className={`weather-card ${className}`} id="weather-card" aria-busy="true">
        <div className="weather-loading" id="weather-loading-state">
          <div className="weather-spinner" aria-hidden="true" />
          <p>Loading live weather for Uskudar, Baglarbasi...</p>
        </div>
      </section>
    );
  }

  if (errorMessage && !weather) {
    return (
      <section className={`weather-card ${className}`} id="weather-card">
        <div className="weather-error" id="weather-error-state">
          <Info className="weather-detail-icon" aria-hidden="true" />
          <p>{errorMessage}</p>
          <div className="weather-header-actions">
            <button
              id="weather-retry-btn"
              type="button"
              className="weather-refresh-btn"
              onClick={() => loadWeather(true)}
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
              <span>Retry</span>
            </button>
            {onRequireAuth && (
              <button
                type="button"
                className="btn btn-secondary btn-small"
                onClick={onRequireAuth}
              >
                Sign In
              </button>
            )}
          </div>
        </div>
      </section>
    );
  }

  if (!weather) return null;

  const { location, current, hourly_forecast, attribution, source_url, from_cache, cache_age_seconds } = weather;
  const tempStr = current.temperature !== null ? `${Math.round(current.temperature)}°C` : '--';
  const feelsStr = current.apparent_temperature !== null ? `${Math.round(current.apparent_temperature)}°C` : '--';
  const rainProb = current.precipitation_probability !== null ? `${current.precipitation_probability}%` : '--';
  const windStr = current.wind_speed !== null ? `${Math.round(current.wind_speed)} km/h` : '--';
  const humidityStr = current.humidity !== null ? `${Math.round(current.humidity)}%` : '--';

  // Display the next 12 hours of forecast
  const nextHours = (hourly_forecast || []).slice(0, 12);

  return (
    <section className={`weather-card ${className}`} id="weather-card" aria-label="Local Weather Forecast">
      {/* Header */}
      <div className="weather-header">
        <div className="weather-location-group">
          <div className="weather-title-row">
            <h2 className="weather-location-name" id="weather-location-name">
              {location.name || 'Baglarbasi, Uskudar'}
            </h2>
            {current.is_rainy ? (
              <span className="weather-badge badge-rainy" id="weather-rainy-badge">
                Rain Expected
              </span>
            ) : (
              <span className="weather-badge badge-fair" id="weather-fair-badge">
                Fair
              </span>
            )}
            {from_cache && (
              <span
                className="weather-badge badge-cached"
                id="weather-cached-badge"
                title={cache_age_seconds ? `Cached ${cache_age_seconds}s ago` : 'Cached'}
              >
                10-Min Cache
              </span>
            )}
          </div>
          <span className="weather-coords">
            {location.latitude.toFixed(4)}°N, {location.longitude.toFixed(4)}°E • {location.timezone}
          </span>
        </div>

        <div className="weather-header-actions">
          <button
            id="weather-refresh-btn"
            type="button"
            className="weather-refresh-btn"
            onClick={() => loadWeather(true)}
            disabled={isRefreshing}
            aria-label="Refresh weather data"
          >
            <RefreshCw
              className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`}
              aria-hidden="true"
            />
            <span>{isRefreshing ? 'Refreshing...' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      {/* Main Temperature & Description Row */}
      <div className="weather-main-row">
        <div className="weather-temp-hero">
          {getWeatherIcon(current.weather_code, current.is_rainy)}
          <div className="weather-temp-values">
            <span className="weather-current-temp" id="weather-current-temp">{tempStr}</span>
            <span className="weather-feels-like" id="weather-feels-like">Feels like {feelsStr}</span>
          </div>
        </div>

        <div className="weather-condition-meta">
          <div className="weather-condition-desc" id="weather-condition-desc">
            {current.weather_description}
          </div>
          <div className="weather-details-grid">
            <div className="weather-detail-item" title="Precipitation Probability">
              <Droplets className="weather-detail-icon" aria-hidden="true" />
              <div className="weather-detail-meta">
                <span className="weather-detail-label">Precip Prob</span>
                <span className="weather-detail-value" id="weather-rain-prob">{rainProb}</span>
              </div>
            </div>

            <div className="weather-detail-item" title="Wind Speed">
              <Wind className="weather-detail-icon" aria-hidden="true" />
              <div className="weather-detail-meta">
                <span className="weather-detail-label">Wind</span>
                <span className="weather-detail-value" id="weather-wind-speed">{windStr}</span>
              </div>
            </div>

            <div className="weather-detail-item" title="Relative Humidity">
              <Thermometer className="weather-detail-icon" aria-hidden="true" />
              <div className="weather-detail-meta">
                <span className="weather-detail-label">Humidity</span>
                <span className="weather-detail-value" id="weather-humidity">{humidityStr}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Hourly Forecast */}
      {nextHours.length > 0 && (
        <div className="weather-hourly-section" id="weather-hourly-section">
          <span className="weather-hourly-title">Upcoming Forecast (Next 12 Hours)</span>
          <div className="weather-hourly-scroll" role="list">
            {nextHours.map((hour, idx) => {
              const hourDate = new Date(hour.time);
              const hourLabel = isNaN(hourDate.getTime())
                ? hour.time.split('T')[1]?.slice(0, 5) || hour.time
                : hourDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
              const hTemp = hour.temperature !== null ? `${Math.round(hour.temperature)}°` : '--';
              const hProb = hour.precipitation_probability !== null ? `${hour.precipitation_probability}%` : null;

              return (
                <div key={`${hour.time}-${idx}`} className="weather-hourly-card" role="listitem">
                  <span className="hourly-time">{hourLabel}</span>
                  <span className="hourly-temp">{hTemp}</span>
                  {hProb !== null && (
                    <span className="hourly-rain" title="Rain probability">
                      <Droplets className="w-3 h-3" aria-hidden="true" />
                      <span>{hProb}</span>
                    </span>
                  )}
                  <span className="hourly-desc" title={hour.weather_description}>
                    {hour.weather_description}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Attribution Footer */}
      <footer className="weather-footer">
        <span>Attribution:</span>
        <a
          id="weather-attribution-link"
          href={source_url || 'https://open-meteo.com/'}
          target="_blank"
          rel="noopener noreferrer"
          className="weather-attribution-link"
        >
          <span>{attribution || 'Weather data by Open-Meteo.com'}</span>
          <ExternalLink className="w-3 h-3" aria-hidden="true" />
        </a>
      </footer>
    </section>
  );
};

export default WeatherCard;
