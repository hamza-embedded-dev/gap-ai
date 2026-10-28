import { apiFetch } from './client';

export interface WeatherLocation {
  name: string;
  latitude: number;
  longitude: number;
  timezone: string;
}

export interface CurrentWeather {
  temperature: number | null;
  apparent_temperature: number | null;
  humidity: number | null;
  precipitation: number | null;
  precipitation_probability: number | null;
  wind_speed: number | null;
  weather_code: number | null;
  weather_description: string;
  is_rainy: boolean;
  time?: string | null;
}

export interface HourlyForecastItem {
  time: string;
  temperature: number | null;
  precipitation_probability: number | null;
  weather_code: number | null;
  weather_description: string;
  is_rainy: boolean;
}

export interface WeatherCurrentResponse {
  location: WeatherLocation;
  current: CurrentWeather;
  hourly_forecast: HourlyForecastItem[];
  attribution: string;
  source_url: string;
  from_cache: boolean;
  cached_at?: string | null;
  is_stale?: boolean;
  cache_age_seconds?: number | null;
}

export interface FetchWeatherParams {
  latitude?: number;
  longitude?: number;
  timezone?: string;
}

/**
 * Fetch current weather and hourly forecast from GAP-AI backend.
 */
export async function fetchCurrentWeather(
  params?: FetchWeatherParams,
  token?: string | null
): Promise<WeatherCurrentResponse> {
  const query = new URLSearchParams();
  if (params?.latitude !== undefined) query.set('latitude', String(params.latitude));
  if (params?.longitude !== undefined) query.set('longitude', String(params.longitude));
  if (params?.timezone) query.set('timezone', params.timezone);

  const qs = query.toString();
  const endpoint = qs ? `/weather/current?${qs}` : '/weather/current';

  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  return apiFetch<WeatherCurrentResponse>(endpoint, { headers });
}
